import json
from decimal import Decimal

import pytest

from trading_platform.backtesting.engine import BacktestConfig
from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.paper.engine import PaperTrader
from trading_platform.risk.engine import RiskEngine, RiskLimits


class AlwaysLong:
    @property
    def name(self) -> str:
        return "test_always_long"

    def target_exposure(self, features):
        return Decimal("1")


def _trader(*, limits: RiskLimits | None = None) -> PaperTrader:
    return PaperTrader(
        exchange="BINANCE",
        market_type=MarketType.SPOT,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        strategy=AlwaysLong(),
        config=BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
        risk_limits=limits,
    )


def test_paper_signals_fill_next_open_and_duplicate_is_idempotent(candle_factory) -> None:
    candles = [candle_factory(index) for index in range(28)]
    trader = _trader()

    seeded = trader.bootstrap(candles[:26])
    signal = trader.process_closed(candles[26])
    assert seeded.status == "BOOTSTRAPPED"
    assert signal is not None
    assert signal.signal_target == "1"
    assert signal.fill is None
    assert trader.process_closed(candles[26]) is None

    filled = trader.process_closed(candles[27])
    assert filled is not None
    assert filled.fill is not None
    assert filled.fill.side == "BUY"
    assert filled.fill.time == candles[27].open_time.isoformat()
    assert Decimal(filled.base_quantity) > 0


def test_paper_state_round_trip_and_closed_candle_checkpoint(candle_factory, tmp_path) -> None:
    candles = [candle_factory(index) for index in range(27)]
    trader = _trader()
    trader.bootstrap(candles[:26])
    trader.process_closed(candles[26])
    state_file = tmp_path / "paper" / "state.json"
    trader.save(state_file)

    raw = json.loads(state_file.read_text(encoding="utf-8"))
    restored = _trader().__class__(
        exchange="BINANCE",
        market_type=MarketType.SPOT,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        strategy=AlwaysLong(),
        config=trader.config,
        risk_limits=trader.risk_limits,
        snapshot=raw,
    )
    assert restored.snapshot() == trader.snapshot()
    assert restored.process_closed(candles[26]) is None


def test_paper_restore_normalizes_decimal_rounding_dust_but_rejects_real_debt() -> None:
    trader = _trader()
    snapshot = trader.snapshot()
    snapshot["cash"] = "-2.993e-24"
    restored = PaperTrader(
        exchange="BINANCE",
        market_type=MarketType.SPOT,
        symbol="BTCUSDT",
        timeframe=Timeframe.ONE_MINUTE,
        strategy=AlwaysLong(),
        config=trader.config,
        risk_limits=trader.risk_limits,
        snapshot=snapshot,
    )
    assert restored.cash == 0

    snapshot["cash"] = "-0.01"
    with pytest.raises(ValueError, match="cash cannot be negative"):
        PaperTrader(
            exchange="BINANCE",
            market_type=MarketType.SPOT,
            symbol="BTCUSDT",
            timeframe=Timeframe.ONE_MINUTE,
            strategy=AlwaysLong(),
            config=trader.config,
            risk_limits=trader.risk_limits,
            snapshot=snapshot,
        )


def test_risk_halt_latches_and_schedules_flatten(candle_factory) -> None:
    candles = [candle_factory(index) for index in range(29)]
    losing = candle_factory(27, open_price="11", high="12", low="9", close="10")
    trader = _trader(limits=RiskLimits(max_daily_loss_pct=Decimal("2")))
    trader.bootstrap(candles[:26])
    trader.process_closed(candles[26])

    halted = trader.process_closed(losing)
    assert halted is not None
    assert halted.halted is True
    assert halted.pending_target == "0"
    assert halted.risk_reason == "maximum daily loss reached"

    flattened = trader.process_closed(candles[28])
    assert flattened is not None
    assert flattened.fill is not None
    assert flattened.fill.side == "SELL"
    assert Decimal(flattened.base_quantity) == 0
    assert flattened.halted is True


def test_risk_engine_clamps_exposure_and_latches_loss() -> None:
    engine = RiskEngine(RiskLimits(max_exposure=Decimal("0.4")))
    capped = engine.assess(
        desired_target=Decimal("1"),
        equity=Decimal("100"),
        daily_start_equity=Decimal("100"),
        peak_equity=Decimal("100"),
    )
    halted = engine.assess(
        desired_target=Decimal("0.2"),
        equity=Decimal("97"),
        daily_start_equity=Decimal("100"),
        peak_equity=Decimal("100"),
    )

    assert capped.approved_target == Decimal("0.4")
    assert capped.halted is False
    assert halted.approved_target == 0
    assert halted.halted is True


def test_paper_rejects_gaps_and_open_bootstrap_candles(candle_factory) -> None:
    trader = _trader()
    candles = [candle_factory(index) for index in range(27)]
    with pytest.raises(ValueError, match="contiguous"):
        trader.bootstrap([candles[0], candles[2]])

    future = candle_factory(27).model_copy(
        update={"close_time": candle_factory(27).close_time.replace(year=2999)}
    )
    with pytest.raises(ValueError, match="closed candles"):
        _trader().bootstrap([future])
