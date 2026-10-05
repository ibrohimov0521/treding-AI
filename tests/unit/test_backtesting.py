from decimal import Decimal

import pytest

from trading_platform.backtesting.engine import BacktestConfig, run_backtest


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
