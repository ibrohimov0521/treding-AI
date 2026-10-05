import pytest
from pydantic import ValidationError

from trading_platform.core.config import MarketConfig, Settings


def test_live_trading_cannot_be_enabled_in_phase_one() -> None:
    with pytest.raises(ValidationError):
        Settings(live_trading=True)

    with pytest.raises(ValidationError):
        MarketConfig.model_validate(
            {
                "exchange": "binance",
                "market_type": "spot",
                "symbol": "BTCUSDT",
                "base_asset": "BTC",
                "quote_asset": "USDT",
                "live_trading": True,
            }
        )
