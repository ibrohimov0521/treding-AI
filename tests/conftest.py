from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.domain.candle import Candle


@pytest.fixture
def candle_factory():
    def make(
        minute: int,
        *,
        timeframe: Timeframe = Timeframe.ONE_MINUTE,
        open_price: str = "10.0",
        high: str = "12.0",
        low: str = "9.0",
        close: str = "11.0",
        volume: str = "2.5",
    ) -> Candle:
        opened = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=minute)
        return Candle(
            exchange="BINANCE",
            market_type=MarketType.SPOT,
            symbol="BTCUSDT",
            timeframe=timeframe,
            open_time=opened,
            close_time=opened + timeframe.duration - timedelta(milliseconds=1),
            open=Decimal(open_price),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal(volume),
            quote_volume=Decimal("25.0"),
            number_of_trades=3,
            taker_buy_base_volume=Decimal("1.0"),
            taker_buy_quote_volume=Decimal("10.0"),
        )

    return make
