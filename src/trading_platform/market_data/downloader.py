"""Paginated and incremental historical candle downloads."""

from datetime import UTC, datetime

import structlog

from trading_platform.core.enums import Timeframe
from trading_platform.market_data.base import MarketDataProvider
from trading_platform.storage.base import CandleStorage

logger = structlog.get_logger(__name__)
BINANCE_PAGE_SIZE = 1000


class HistoricalDownloader:
    """Download closed candles in bounded pages and persist idempotently."""

    def __init__(self, provider: MarketDataProvider, storage: CandleStorage) -> None:
        self.provider = provider
        self.storage = storage

    async def download(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: Timeframe,
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[int, int]:
        """Download [start_time, end_time); return fetched rows and inserted rows."""
        start = _utc(start_time)
        end = _utc(end_time)
        if start >= end:
            raise ValueError("Download start must be earlier than end")
        cursor = start
        fetched_count = 0
        inserted_count = 0
        last_open: datetime | None = None
        while cursor < end:
            page = await self.provider.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=cursor,
                end_time=end,
                limit=BINANCE_PAGE_SIZE,
            )
            if not page:
                break
            page = sorted(page, key=lambda candle: candle.open_time)
            fresh = [
                candle
                for candle in page
                if start <= candle.open_time < end
                and candle.close_time < datetime.now(UTC)
                and (last_open is None or candle.open_time > last_open)
            ]
            fetched_count += len(fresh)
            # Commit every completed page atomically. Long archives stay
            # bounded in memory and a later network failure keeps prior pages.
            inserted_count += self.storage.save_raw(fresh)
            if not fresh:
                break
            last_open = fresh[-1].open_time
            next_cursor = last_open + interval.duration
            if next_cursor <= cursor:
                raise RuntimeError("Pagination did not advance; aborting duplicate-page loop")
            cursor = next_cursor
            logger.info(
                "historical_page_downloaded",
                symbol=symbol,
                interval=interval.value,
                rows=len(fresh),
                next_cursor=cursor.isoformat(),
            )
            if len(page) < BINANCE_PAGE_SIZE:
                break
        return fetched_count, inserted_count


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Download boundaries must be timezone-aware")
    return value.astimezone(UTC)
