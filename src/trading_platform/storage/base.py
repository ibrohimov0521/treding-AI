"""Historical candle storage protocol."""

from datetime import datetime
from typing import Protocol

from trading_platform.domain.candle import Candle


class CandleStorage(Protocol):
    """Storage contract used by download, validation, and processing services."""

    def save_raw(self, candles: list[Candle]) -> int:
        """Idempotently persist raw candles and return the count of new records."""

    def load_candles(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Load candles in chronological order, optionally bounded by open time."""

    def latest_open_time(
        self, exchange: str, market_type: str, symbol: str, timeframe: str
    ) -> datetime | None:
        """Return the newest stored candle open time, if available."""
