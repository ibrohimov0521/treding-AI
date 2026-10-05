from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from trading_platform.core.config import MarketConfig, load_market_config
from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.domain.candle import Candle


def test_timeframe_parse_and_duration() -> None:
    assert Timeframe.parse("15m") is Timeframe.FIFTEEN_MINUTES
    assert Timeframe.ONE_HOUR.milliseconds == 3_600_000
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        Timeframe.parse("2h")


def test_candle_rejects_naive_timestamps(candle_factory) -> None:
    candle = candle_factory(0)
    with pytest.raises(ValidationError, match="timezone-aware"):
        Candle.model_validate({**candle.model_dump(), "open_time": datetime(2024, 1, 1)})


def test_market_config_loads_and_disallows_live_trading() -> None:
    config = load_market_config(Path("configs/markets/btcusdt.yaml"))
    assert config.symbol == "BTCUSDT"
    assert config.market_type is MarketType.SPOT
    assert config.derived_timeframes == (
        Timeframe.FIVE_MINUTES,
        Timeframe.FIFTEEN_MINUTES,
        Timeframe.ONE_HOUR,
    )
    with pytest.raises(ValidationError):
        MarketConfig.model_validate(
            {
                "exchange": "binance",
                "market_type": "spot",
                "symbol": "ETHUSDT",
                "base_asset": "ETH",
                "quote_asset": "USDT",
                "live_trading": True,
            }
        )


def test_config_rejects_noncanonical_raw_timeframe() -> None:
    with pytest.raises(ValidationError, match="canonical 1m"):
        MarketConfig.model_validate(
            {
                "exchange": "binance",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "raw_timeframe": "5m",
            }
        )
