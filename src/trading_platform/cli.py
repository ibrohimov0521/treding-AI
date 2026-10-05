"""Developer command-line interface for Phase 0–1 workflows."""

import asyncio
from collections.abc import Coroutine
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import structlog
import typer

from trading_platform import __version__
from trading_platform.core.config import MarketConfig, Settings, load_market_config
from trading_platform.core.enums import Timeframe
from trading_platform.core.exceptions import TradingPlatformError
from trading_platform.core.logging import configure_logging
from trading_platform.market_data.binance_spot import BinanceSpotMarketDataProvider
from trading_platform.market_data.downloader import HistoricalDownloader
from trading_platform.market_data.resampling import resample_candles
from trading_platform.storage.parquet import ParquetCandleStorage
from trading_platform.validation.candles import validate_records
from trading_platform.validation.reports import save_report

app = typer.Typer(
    name="trading-platform",
    help="Safe Phase 0–1 tools for public crypto market data.",
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
        raise TradingPlatformError("Live trading is forbidden in Phase 0–1")
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
    typer.echo("Live trading: DISABLED (no execution code exists in Phase 0–1)")


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
    records = storage.load_records(
        market.exchange,
        market.market_type.value,
        (symbol or market.symbol).upper(),
        timeframe.value,
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


def main() -> None:
    """Entry point used by the installed console script."""
    app()


if __name__ == "__main__":
    main()
