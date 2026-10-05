from decimal import Decimal

import pytest

from trading_platform.backtesting.engine import BacktestConfig, rebalance_spot, run_backtest
from trading_platform.backtesting.statistics import summarize_trades
from trading_platform.risk.engine import RiskLimits


class AlwaysLong:
    @property
    def name(self) -> str:
        return "test_always_long"

    def target_exposure(self, features):
        return Decimal("1")


class InvalidExposure:
    @property
    def name(self) -> str:
        return "test_invalid"

    def target_exposure(self, features):
        return Decimal("1.1")


def _candles(candle_factory):
    return [
        candle_factory(
            index,
            open_price=str(10 + index * 10),
            high=str(12 + index * 10),
            low=str(9 + index * 10),
            close=str(10 + index * 10),
        )
        for index in range(3)
    ]


def test_backtest_fills_next_open_and_marks_equity(candle_factory) -> None:
    candles = _candles(candle_factory)
    result = run_backtest(
        candles,
        AlwaysLong(),
        BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
    )

    assert result.trade_count == 1
    assert result.fills[0].side == "BUY"
    assert result.fills[0].time == candles[1].open_time.isoformat()
    assert Decimal(result.fills[0].price) == candles[1].open
    assert Decimal(result.ending_equity) == Decimal("1500")
    assert Decimal(result.total_return_pct) == Decimal("50.0")


def test_transaction_costs_reduce_backtest_equity(candle_factory) -> None:
    candles = _candles(candle_factory)
    free = run_backtest(
        candles,
        AlwaysLong(),
        BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
    )
    charged = run_backtest(
        candles,
        AlwaysLong(),
        BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("10"),
            spread_bps=Decimal("4"),
            slippage_bps=Decimal("5"),
        ),
    )
    assert Decimal(charged.ending_equity) < Decimal(free.ending_equity)
    assert Decimal(charged.fees_paid) > 0


def test_full_spot_allocation_keeps_cash_nonnegative_with_costs(candle_factory) -> None:
    candle = candle_factory(
        0,
        open_price="108000.12",
        high="108100",
        low="107900",
        close="108020",
    )
    cash, quantity, fill = rebalance_spot(
        candle,
        Decimal("10000"),
        Decimal("0"),
        Decimal("1"),
        Decimal("0.001"),
        Decimal("0.0006"),
    )

    assert fill is not None
    assert fill.side == "BUY"
    assert quantity > 0
    assert Decimal("0") <= cash < Decimal("1e-18")


def test_backtest_rejects_gap_and_short_exposure(candle_factory) -> None:
    candles = _candles(candle_factory)
    with pytest.raises(ValueError, match="contiguous"):
        run_backtest([candles[0], candles[2]], AlwaysLong())
    with pytest.raises(ValueError, match="between 0 and 1"):
        run_backtest(candles, InvalidExposure())


def test_backtest_config_rejects_unusable_costs() -> None:
    with pytest.raises(ValueError, match="starting_cash"):
        BacktestConfig(starting_cash=Decimal("0"))
    with pytest.raises(ValueError, match="fee_bps"):
        BacktestConfig(fee_bps=Decimal("10000"))
    with pytest.raises(ValueError, match="stop_loss_pct"):
        BacktestConfig(stop_loss_pct=Decimal("0"))


def test_backtest_uses_shared_risk_engine_and_flattens_after_halt(candle_factory) -> None:
    candles = [
        candle_factory(0, open_price="10", high="11", low="9", close="10"),
        candle_factory(1, open_price="10", high="11", low="9", close="10"),
        candle_factory(2, open_price="10", high="11", low="9", close="9"),
        candle_factory(3, open_price="9", high="10", low="8", close="9"),
    ]

    result = run_backtest(
        candles,
        AlwaysLong(),
        BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("0"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
        ),
        risk_limits=RiskLimits(max_daily_loss_pct=Decimal("2")),
    )

    assert result.risk_halted is True
    assert result.risk_halt_reason == "maximum daily loss reached"
    assert result.fills[-1].side == "SELL"
    assert Decimal(result.ending_base_quantity) == 0


def test_virtual_stop_exits_intrabar_and_waits_for_flat_signal(candle_factory) -> None:
    candles = [
        candle_factory(0, open_price="100", high="101", low="99", close="100"),
        candle_factory(1, open_price="100", high="101", low="99.5", close="100"),
        candle_factory(2, open_price="95", high="96", low="94", close="95"),
        candle_factory(3, open_price="95", high="96", low="94", close="95"),
    ]
    result = run_backtest(
        candles,
        AlwaysLong(),
        BacktestConfig(
            starting_cash=Decimal("1000"),
            fee_bps=Decimal("10"),
            spread_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            stop_loss_pct=Decimal("1"),
        ),
        risk_limits=RiskLimits(max_daily_loss_pct=Decimal("100")),
    )
    assert [fill.side for fill in result.fills] == ["BUY", "STOP_SELL"], result.fills
    assert result.stop_exits == 1
    # The second candle opens below the stop: no unrealistically good fill at 99.
    assert Decimal(result.fills[1].price) == Decimal("95")
    stats = summarize_trades(result.fills)
    assert stats["closed_trades"] == 1
    assert stats["winning_trades"] == 0
    assert Decimal(stats["net_realized_pnl"]) < Decimal("-50")
