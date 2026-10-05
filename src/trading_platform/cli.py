"""Developer command-line interface for safe research workflows."""

import asyncio
import json
from collections.abc import Coroutine
from dataclasses import asdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import polars as pl
import structlog
import typer

from trading_platform import __version__
from trading_platform.backtesting.engine import BacktestConfig, run_backtest
from trading_platform.core.config import MarketConfig, Settings, load_market_config
from trading_platform.core.enums import Timeframe
from trading_platform.core.exceptions import TradingPlatformError
from trading_platform.core.logging import configure_logging
from trading_platform.features.engineering import compute_features, features_frame
from trading_platform.market_data.binance_spot import BinanceSpotMarketDataProvider
from trading_platform.market_data.downloader import HistoricalDownloader
from trading_platform.market_data.resampling import resample_candles
from trading_platform.ml.dataset import build_labeled_dataset
from trading_platform.ml.walkforward import evaluate_walk_forward
from trading_platform.observability.audit import AuditLog
from trading_platform.paper.engine import HISTORY_LIMIT, PaperTrader, PaperUpdate
from trading_platform.risk.engine import RiskLimits
from trading_platform.storage.parquet import ParquetCandleStorage
from trading_platform.strategies.moving_average import MovingAverageCrossover
from trading_platform.validation.candles import validate_records
from trading_platform.validation.reports import save_report

app = typer.Typer(
    name="trading-platform",
    help="Safe crypto research tools; no authenticated trading or order submission.",
    no_args_is_help=True,
    add_completion=False,
)
logger = structlog.get_logger(__name__)
DEFAULT_CONFIG = Path("configs/markets/btcusdt.yaml")


def _context(
    config_path: Path, data_dir: Path | None
) -> tuple[MarketConfig, Settings, ParquetCandleStorage]:
    config = load_market_config(config_path)
    settings = Settings(data_dir=data_dir) if data_dir is not None else Settings()
    if settings.live_trading is not False:
        raise TradingPlatformError("Live trading is forbidden; no execution adapter exists")
    return config, settings, ParquetCandleStorage(settings.data_dir)


def _parse_utc(value: str | None, *, is_end: bool = False) -> datetime | None:
    if value is None:
        return None
    try:
        parsed_date = date.fromisoformat(value)
        result = datetime.combine(parsed_date, time.min, tzinfo=UTC)
        return result + timedelta(days=1) if is_end else result
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("Use YYYY-MM-DD or an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _run[ResultT](coroutine: Coroutine[object, object, ResultT]) -> ResultT:
    try:
        return asyncio.run(coroutine)
    except TradingPlatformError as exc:
        logger.error("command_failed", error=str(exc))
        raise typer.Exit(code=1) from exc


@app.command()
def health() -> None:
    """Check connectivity to Binance's public Spot API."""

    async def run() -> bool:
        async with BinanceSpotMarketDataProvider() as provider:
            return await provider.health_check()

    configure_logging()
    healthy = _run(run())
    typer.echo("Binance public API: healthy" if healthy else "Binance public API: unavailable")


@app.command()
def info(
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Show loaded market settings and the execution safety state."""
    market, settings, _ = _context(config, data_dir)
    typer.echo(f"Platform version: {__version__}")
    typer.echo(f"Exchange: {market.exchange}")
    typer.echo(f"Market: {market.market_type.value}")
    typer.echo(f"Symbol: {market.symbol}")
    typer.echo(f"Raw timeframe: {market.raw_timeframe.value}")
    typer.echo(f"Derived timeframes: {', '.join(item.value for item in market.derived_timeframes)}")
    typer.echo(f"Data directory: {settings.data_dir}")
    typer.echo("Live trading: DISABLED (no authenticated execution adapter exists)")


@app.command()
def download(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option(
        "1m", "--interval", help="Canonical raw interval; Phase 1 uses 1m."
    ),
    start: str | None = typer.Option(
        None, "--start", help="UTC start, inclusive (YYYY-MM-DD or ISO-8601)."
    ),
    end: str | None = typer.Option(None, "--end", help="UTC end date, inclusive if date-only."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Download historical public candles; omit --start to continue incrementally."""
    market, _, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe:
        raise typer.BadParameter(
            f"Raw downloads must use configured canonical interval {market.raw_timeframe.value}; "
            "use `resample` for derived timeframes."
        )
    market_symbol = (symbol or market.symbol).upper()
    end_time = _parse_utc(end) or datetime.now(UTC)
    start_time = _parse_utc(start)
    if start_time is None:
        latest = storage.latest_open_time(
            market.exchange, market.market_type.value, market_symbol, timeframe.value
        )
        if latest is None:
            raise typer.BadParameter("No existing data found; provide --start for first download.")
        start_time = latest + timeframe.duration
    if start_time >= end_time:
        typer.echo("No new range to download.")
        return

    async def run() -> tuple[int, int]:
        async with BinanceSpotMarketDataProvider() as provider:
            downloader = HistoricalDownloader(provider, storage)
            return await downloader.download(
                exchange=market.exchange,
                market_type=market.market_type.value,
                symbol=market_symbol,
                interval=timeframe,
                start_time=start_time,
                end_time=end_time,
            )

    configure_logging()
    fetched, inserted = _run(run())
    typer.echo(f"Fetched {fetched} completed candles; inserted {inserted} new rows.")
    raw_path = (
        storage.raw_root
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
    )
    typer.echo(f"Raw Parquet: {raw_path}")


@app.command()
def validate(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Stored timeframe to validate."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Validate stored candles and write a JSON data-quality report."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe and timeframe not in market.derived_timeframes:
        configured = ", ".join(
            item.value for item in (market.raw_timeframe, *market.derived_timeframes)
        )
        raise typer.BadParameter(f"Timeframe must be configured; available: {configured}")
    records = storage.load_records(
        market.exchange,
        market.market_type.value,
        (symbol or market.symbol).upper(),
        timeframe.value,
        processed=timeframe != market.raw_timeframe,
    )
    report = validate_records(
        records,
        timeframe,
        exchange=market.exchange,
        market_type=market.market_type.value,
        symbol=(symbol or market.symbol).upper(),
    )
    report_path = save_report(report, settings.data_dir)
    typer.echo(f"symbol: {report.symbol}")
    typer.echo(f"timeframe: {report.timeframe}")
    typer.echo(f"rows: {report.rows}")
    typer.echo(f"duplicates: {report.duplicates}")
    typer.echo(f"missing_candles: {report.missing_candles}")
    typer.echo(f"invalid_ohlc: {report.invalid_ohlc}")
    typer.echo(f"status: {report.status.value}")
    typer.echo(f"report: {report_path}")
    if report.status.value == "FAIL":
        raise typer.Exit(code=2)


@app.command()
def resample(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    source: str = typer.Option("1m", "--from", help="Raw source timeframe."),
    target: str = typer.Option("5m", "--to", help="Derived target timeframe."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Create complete 5m, 15m, or 1h candles from canonical 1m data."""
    market, _, storage = _context(config, data_dir)
    source_timeframe = Timeframe.parse(source)
    target_timeframe = Timeframe.parse(target)
    if source_timeframe != market.raw_timeframe:
        raise typer.BadParameter(f"Source must be canonical {market.raw_timeframe.value}")
    if target_timeframe not in market.derived_timeframes:
        choices = ", ".join(item.value for item in market.derived_timeframes)
        raise typer.BadParameter(f"Target must be configured as derived: {choices}")
    market_symbol = (symbol or market.symbol).upper()
    raw = storage.load_candles(
        market.exchange, market.market_type.value, market_symbol, source_timeframe.value
    )
    outcome = resample_candles(raw, target_timeframe)
    stored = storage.save_processed(outcome.candles)
    typer.echo(f"Created {len(outcome.candles)} complete {target_timeframe.value} candles.")
    typer.echo(f"Skipped incomplete groups: {outcome.skipped_incomplete_groups}")
    typer.echo(f"Stored processed rows: {stored}")


@app.command()
def features(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Stored candle timeframe."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Compute causal indicators from closed stored candles and save Parquet."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe and timeframe not in market.derived_timeframes:
        configured = ", ".join(
            item.value for item in (market.raw_timeframe, *market.derived_timeframes)
        )
        raise typer.BadParameter(f"Timeframe must be configured; available: {configured}")
    market_symbol = (symbol or market.symbol).upper()
    candles = storage.load_candles(
        market.exchange,
        market.market_type.value,
        market_symbol,
        timeframe.value,
        processed=timeframe != market.raw_timeframe,
    )
    if not candles:
        raise typer.BadParameter(
            "No candle data found; download or resample the selected series first."
        )
    rows = compute_features(candles)
    frame = features_frame(rows)
    feature_path = (
        settings.data_dir
        / "features"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
        / "features.parquet"
    )
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    frame.write_parquet(feature_path, compression="zstd")
    ready = sum(row.ready for row in rows)
    typer.echo(f"Feature rows: {len(rows)}; model-ready rows: {ready}")
    typer.echo(f"Features: {feature_path}")


@app.command()
def backtest(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Stored candle timeframe."),
    start: str | None = typer.Option(None, "--start", help="UTC start, inclusive."),
    end: str | None = typer.Option(None, "--end", help="UTC end, exclusive unless date-only."),
    starting_cash: float = typer.Option(10_000.0, min=0.01, help="Quote-asset simulation balance."),
    fee_bps: float = typer.Option(10.0, min=0.0, max=9_999.0, help="Commission in basis points."),
    spread_bps: float = typer.Option(
        2.0, min=0.0, max=9_999.0, help="Full spread in basis points."
    ),
    slippage_bps: float = typer.Option(
        5.0, min=0.0, max=9_999.0, help="Per-side slippage in basis points."
    ),
    max_daily_loss_pct: float = typer.Option(
        2.0, min=0.01, max=100.0, help="Latch a halt at this daily loss percentage."
    ),
    max_drawdown_pct: float = typer.Option(
        8.0, min=0.01, max=100.0, help="Latch a halt at this peak drawdown percentage."
    ),
    max_exposure: float = typer.Option(
        1.0, min=0.0, max=1.0, help="Maximum long Spot exposure as a fraction of equity."
    ),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Run a long-only EMA benchmark using next-candle-open simulated fills."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe and timeframe not in market.derived_timeframes:
        configured = ", ".join(
            item.value for item in (market.raw_timeframe, *market.derived_timeframes)
        )
        raise typer.BadParameter(f"Timeframe must be configured; available: {configured}")
    market_symbol = (symbol or market.symbol).upper()
    candles = storage.load_candles(
        market.exchange,
        market.market_type.value,
        market_symbol,
        timeframe.value,
        start_time=_parse_utc(start),
        end_time=_parse_utc(end, is_end=True),
        processed=timeframe != market.raw_timeframe,
    )
    if len(candles) < 2:
        raise typer.BadParameter("At least two stored candles are required for a backtest.")
    try:
        result = run_backtest(
            candles,
            MovingAverageCrossover(),
            BacktestConfig(
                starting_cash=Decimal(str(starting_cash)),
                fee_bps=Decimal(str(fee_bps)),
                spread_bps=Decimal(str(spread_bps)),
                slippage_bps=Decimal(str(slippage_bps)),
            ),
            risk_limits=RiskLimits(
                max_daily_loss_pct=Decimal(str(max_daily_loss_pct)),
                max_drawdown_pct=Decimal(str(max_drawdown_pct)),
                max_exposure=Decimal(str(max_exposure)),
            ),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    report_dir = (
        settings.data_dir
        / "reports"
        / "backtest"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    range_key = f"{candles[0].open_time:%Y%m%dT%H%M}_{candles[-1].open_time:%Y%m%dT%H%M}"
    report_path = report_dir / f"{result.strategy}_{range_key}.json"
    equity_path = report_dir / f"{result.strategy}_{range_key}_equity.parquet"
    report = result.to_dict()
    report.pop("equity_curve")
    report["assumptions"] = {
        "signal_timing": "after candle close; fill at the next candle open",
        "positioning": "long-only spot; target exposure from 0 to 100%",
        "fee_bps": str(Decimal(str(fee_bps))),
        "spread_bps_full": str(Decimal(str(spread_bps))),
        "slippage_bps_per_side": str(Decimal(str(slippage_bps))),
        "max_daily_loss_pct": str(Decimal(str(max_daily_loss_pct))),
        "max_drawdown_pct": str(Decimal(str(max_drawdown_pct))),
        "max_exposure": str(Decimal(str(max_exposure))),
        "live_orders": False,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    pl.DataFrame([asdict(point) for point in result.equity_curve]).write_parquet(
        equity_path, compression="zstd"
    )
    typer.echo(f"Strategy: {result.strategy}")
    start_open = candles[0].open_time.isoformat()
    end_open = candles[-1].open_time.isoformat()
    typer.echo(f"Candles: {len(candles)} ({start_open} – {end_open})")
    typer.echo(f"Ending equity: {result.ending_equity} {market.quote_asset}")
    typer.echo(f"Total return: {result.total_return_pct}%")
    typer.echo(f"Max drawdown: {result.max_drawdown_pct}%")
    typer.echo(
        f"Simulated fills: {result.trade_count}; fees: {result.fees_paid} {market.quote_asset}"
    )
    typer.echo(f"Report: {report_path}")
    typer.echo(f"Equity curve: {equity_path}")


@app.command("build-dataset")
def build_dataset_command(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Stored candle timeframe."),
    horizon: int = typer.Option(5, min=1, help="Future candle count used for the label."),
    neutral_band_bps: float = typer.Option(
        10.0, min=0.0, max=9_999.0, help="Return dead-zone threshold in basis points."
    ),
    start: str | None = typer.Option(None, "--start", help="UTC start, inclusive."),
    end: str | None = typer.Option(None, "--end", help="UTC end; date-only includes that date."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Create forward-return labels for ML; future values are labels only."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe and timeframe not in market.derived_timeframes:
        raise typer.BadParameter("Timeframe must be configured as raw or derived.")
    market_symbol = (symbol or market.symbol).upper()
    candles = storage.load_candles(
        market.exchange,
        market.market_type.value,
        market_symbol,
        timeframe.value,
        start_time=_parse_utc(start),
        end_time=_parse_utc(end, is_end=True),
        processed=timeframe != market.raw_timeframe,
    )
    try:
        dataset = build_labeled_dataset(
            candles,
            horizon=horizon,
            neutral_band_bps=neutral_band_bps,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if not dataset.samples:
        raise typer.BadParameter("No model-ready samples; load more candles or lower the horizon.")
    dataset_dir = (
        settings.data_dir
        / "datasets"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
        / f"horizon={horizon}"
    )
    dataset_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = dataset_dir / "labeled_samples.parquet"
    metadata_path = dataset_dir / "metadata.json"
    dataset.to_frame().write_parquet(parquet_path, compression="zstd")
    metadata = {
        "exchange": dataset.exchange,
        "market_type": dataset.market_type,
        "symbol": dataset.symbol,
        "timeframe": dataset.timeframe,
        "horizon_candles": dataset.horizon,
        "neutral_band_bps": dataset.neutral_band_bps,
        "feature_names": list(dataset.feature_names),
        "label_definition": "UP/DOWN beyond the neutral band; otherwise NEUTRAL",
        "rows": len(dataset.samples),
        "class_counts": dataset.class_counts(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    typer.echo(f"Labeled samples: {len(dataset.samples)}")
    typer.echo(f"Class counts: {dataset.class_counts()}")
    typer.echo(f"Dataset: {parquet_path}")
    typer.echo(f"Metadata: {metadata_path}")


@app.command("walk-forward")
def walk_forward_command(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Stored candle timeframe."),
    horizon: int = typer.Option(5, min=1, help="Future candle count used for the label."),
    neutral_band_bps: float = typer.Option(
        10.0, min=0.0, max=9_999.0, help="Return dead-zone threshold in basis points."
    ),
    min_train_rows: int = typer.Option(1_000, min=2, help="Minimum expanding training window."),
    test_rows: int = typer.Option(500, min=1, help="Out-of-sample rows in each fold."),
    step_rows: int = typer.Option(500, min=1, help="Rows between consecutive test windows."),
    start: str | None = typer.Option(None, "--start", help="UTC start, inclusive."),
    end: str | None = typer.Option(None, "--end", help="UTC end; date-only includes that date."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Evaluate a logistic baseline on expanding, purged out-of-sample folds."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe and timeframe not in market.derived_timeframes:
        raise typer.BadParameter("Timeframe must be configured as raw or derived.")
    market_symbol = (symbol or market.symbol).upper()
    candles = storage.load_candles(
        market.exchange,
        market.market_type.value,
        market_symbol,
        timeframe.value,
        start_time=_parse_utc(start),
        end_time=_parse_utc(end, is_end=True),
        processed=timeframe != market.raw_timeframe,
    )
    try:
        dataset = build_labeled_dataset(
            candles,
            horizon=horizon,
            neutral_band_bps=neutral_band_bps,
        )
        report = evaluate_walk_forward(
            dataset,
            min_train_rows=min_train_rows,
            test_rows=test_rows,
            step_rows=step_rows,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    report_dir = (
        settings.data_dir
        / "reports"
        / "walk_forward"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    range_key = f"{candles[0].open_time:%Y%m%dT%H%M}_{candles[-1].open_time:%Y%m%dT%H%M}"
    report_path = report_dir / f"horizon={horizon}_{range_key}.json"
    report_dict = report.to_dict()
    report_path.write_text(json.dumps(report_dict, indent=2), encoding="utf-8")
    typer.echo(f"Model: {report.model}")
    typer.echo(f"Walk-forward folds: {len(report.folds)}")
    typer.echo(f"Mean accuracy: {report_dict['mean_accuracy']}")
    typer.echo(f"Mean balanced accuracy: {report_dict['mean_balanced_accuracy']}")
    typer.echo(f"Mean majority baseline accuracy: {report_dict['mean_majority_class_accuracy']}")
    typer.echo(f"Mean log loss: {report_dict['mean_log_loss']}")
    typer.echo("Probability calibration: not applied")
    typer.echo(f"Report: {report_path}")


@app.command("paper")
def paper_command(
    symbol: str | None = typer.Option(None, "--symbol", help="Override configured market symbol."),
    interval: str = typer.Option("1m", "--interval", help="Paper market timeframe (raw only)."),
    starting_cash: float = typer.Option(10_000.0, min=0.01, help="Virtual quote-asset balance."),
    fee_bps: float = typer.Option(10.0, min=0.0, max=9_999.0, help="Commission in basis points."),
    spread_bps: float = typer.Option(
        2.0, min=0.0, max=9_999.0, help="Full spread in basis points."
    ),
    slippage_bps: float = typer.Option(
        5.0, min=0.0, max=9_999.0, help="Per-side slippage in basis points."
    ),
    max_daily_loss_pct: float = typer.Option(
        2.0, min=0.01, max=100.0, help="Latch a halt at this daily loss percentage."
    ),
    max_drawdown_pct: float = typer.Option(
        8.0, min=0.01, max=100.0, help="Latch a halt at this peak drawdown percentage."
    ),
    max_exposure: float = typer.Option(
        1.0, min=0.0, max=1.0, help="Maximum virtual Spot exposure as a fraction of equity."
    ),
    state_file: Path | None = typer.Option(
        None, "--state-file", help="Paper checkpoint path; defaults under data/paper/."
    ),
    audit_file: Path | None = typer.Option(
        None, "--audit-file", help="Hash-chained audit JSONL path; defaults under data/audit/."
    ),
    follow: bool = typer.Option(
        False, "--follow", help="Keep polling and processing closed candles."
    ),
    poll_seconds: int = typer.Option(10, min=1, help="Polling interval used with --follow."),
    config: Path = typer.Option(DEFAULT_CONFIG, "--config", help="Market YAML configuration."),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="Override data directory."),
) -> None:
    """Run a restartable virtual Spot portfolio using public closed candles only."""
    market, settings, storage = _context(config, data_dir)
    timeframe = Timeframe.parse(interval)
    if timeframe != market.raw_timeframe:
        raise typer.BadParameter(
            f"Paper mode currently requires the raw {market.raw_timeframe.value} timeframe."
        )
    market_symbol = (symbol or market.symbol).upper()
    checkpoint = state_file or (
        settings.data_dir
        / "paper"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
        / "state.json"
    )
    audit_path = audit_file or (
        settings.data_dir
        / "audit"
        / market.exchange.lower()
        / market.market_type.value
        / market_symbol
        / timeframe.value
        / "events.jsonl"
    )
    try:
        audit = AuditLog(audit_path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    backtest_config = BacktestConfig(
        starting_cash=Decimal(str(starting_cash)),
        fee_bps=Decimal(str(fee_bps)),
        spread_bps=Decimal(str(spread_bps)),
        slippage_bps=Decimal(str(slippage_bps)),
    )
    risk_limits = RiskLimits(
        max_daily_loss_pct=Decimal(str(max_daily_loss_pct)),
        max_drawdown_pct=Decimal(str(max_drawdown_pct)),
        max_exposure=Decimal(str(max_exposure)),
    )
    snapshot: dict[str, object] | None = None
    if checkpoint.exists():
        try:
            loaded = json.loads(checkpoint.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise typer.BadParameter(f"Could not read paper state: {exc}") from exc
        if not isinstance(loaded, dict):
            raise typer.BadParameter("Paper state must contain a JSON object.")
        snapshot = loaded
    trader = PaperTrader(
        exchange=market.exchange,
        market_type=market.market_type,
        symbol=market_symbol,
        timeframe=timeframe,
        strategy=MovingAverageCrossover(),
        config=backtest_config,
        risk_limits=risk_limits,
        snapshot=snapshot,
    )

    async def run() -> None:
        async with BinanceSpotMarketDataProvider() as provider:
            downloader = HistoricalDownloader(provider, storage)
            while True:
                now = datetime.now(UTC)
                start_time = (
                    trader.last_processed_open + timeframe.duration
                    if trader.last_processed_open is not None
                    else now - timeframe.duration * HISTORY_LIMIT
                )
                if start_time < now:
                    await downloader.download(
                        market.exchange,
                        market.market_type.value,
                        market_symbol,
                        timeframe,
                        start_time,
                        now,
                    )
                candles = storage.load_candles(
                    market.exchange,
                    market.market_type.value,
                    market_symbol,
                    timeframe.value,
                    start_time=start_time,
                )
                if not trader.bootstrapped:
                    if len(candles) < 26:
                        raise TradingPlatformError(
                            "Paper bootstrap needs at least 26 contiguous closed candles."
                        )
                    try:
                        bootstrap_update = trader.bootstrap(candles[-HISTORY_LIMIT:])
                    except ValueError as exc:
                        raise TradingPlatformError(str(exc)) from exc
                    trader.save(checkpoint)
                    _emit_paper_update(bootstrap_update, audit)
                else:
                    for candle in candles:
                        try:
                            processed_update = trader.process_closed(candle)
                        except ValueError as exc:
                            raise TradingPlatformError(str(exc)) from exc
                        if processed_update is not None:
                            trader.save(checkpoint)
                            _emit_paper_update(processed_update, audit)
                if not follow:
                    return
                await asyncio.sleep(poll_seconds)

    configure_logging()
    _run(run())
    typer.echo(f"Paper state: {checkpoint}")
    typer.echo(f"Audit log: {audit_path}")


def _emit_paper_update(update: PaperUpdate, audit: AuditLog) -> None:
    record = audit.append("paper_update", {"update": update.to_dict(), "live_orders": False})
    typer.echo(
        json.dumps(
            {
                **update.to_dict(),
                "live_orders": False,
                "audit_sequence": record["sequence"],
                "audit_hash": record["event_hash"],
            }
        )
    )


@app.command("audit-verify")
def audit_verify_command(
    path: Path = typer.Argument(..., help="Hash-chained JSONL audit file."),
) -> None:
    """Verify event sequence and every SHA-256 link in an audit file."""
    try:
        result = AuditLog.verify(path)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"Verified audit events: {result.event_count}")
    typer.echo(f"Last hash: {result.last_hash}")


def main() -> None:
    """Entry point used by the installed console script."""
    app()


if __name__ == "__main__":
    main()
