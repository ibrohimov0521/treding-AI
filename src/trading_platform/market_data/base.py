"""Exchange-independent async market-data interface."""

from datetime import datetime
from typing import Protocol

from trading_platform.core.enums import Timeframe
from trading_platform.domain.candle import Candle
from trading_platform.domain.market import Market


class MarketDataProvider(Protocol):
    """Public market-data operations required by downstream platform layers."""

    async def get_exchange_info(self) -> list[Market]:
        """Return spot markets and their current exchange status."""

    async def get_klines(
        self,
        symbol: str,
        interval: Timeframe,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 1000,
    ) -> list[Candle]:
        """Fetch one page of candles, with UTC-aware optional bounds."""

    async def health_check(self) -> bool:
        """Return whether the public exchange API responds successfully."""
