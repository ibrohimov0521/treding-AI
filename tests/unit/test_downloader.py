from datetime import UTC, datetime, timedelta

import pytest

import trading_platform.market_data.downloader as downloader_module
from trading_platform.core.enums import Timeframe
from trading_platform.market_data.downloader import HistoricalDownloader
from trading_platform.storage.parquet import ParquetCandleStorage


class PaginatedProvider:
    def __init__(self, candles):
        self.candles = candles
        self.cursors = []

    async def get_klines(self, symbol, interval, start_time=None, end_time=None, limit=1000):
        self.cursors.append(start_time)
        return [
            candle
            for candle in self.candles
            if candle.open_time >= start_time and candle.open_time < end_time
        ][:limit]

    async def get_exchange_info(self):
        return []

    async def health_check(self):
        return True


@pytest.mark.asyncio
async def test_download_paginates_and_persists_without_duplicates(
    tmp_path, candle_factory, monkeypatch
) -> None:
    candles = [candle_factory(index) for index in range(5)]
    provider = PaginatedProvider(candles)
    storage = ParquetCandleStorage(tmp_path / "data")
    monkeypatch.setattr(downloader_module, "BINANCE_PAGE_SIZE", 2)
    downloader = HistoricalDownloader(provider, storage)
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(minutes=5)
    fetched, inserted = await downloader.download(
        "BINANCE", "spot", "BTCUSDT", Timeframe.ONE_MINUTE, start, end
    )
    assert (fetched, inserted) == (5, 5)
    assert len(provider.cursors) == 3
    assert len(storage.load_candles("binance", "spot", "BTCUSDT", "1m")) == 5


@pytest.mark.asyncio
async def test_download_requires_aware_boundaries(candle_factory, tmp_path) -> None:
    downloader = HistoricalDownloader(PaginatedProvider([]), ParquetCandleStorage(tmp_path))
    with pytest.raises(ValueError, match="timezone-aware"):
        await downloader.download(
            "BINANCE",
            "spot",
            "BTCUSDT",
            Timeframe.ONE_MINUTE,
            datetime(2024, 1, 1),
            datetime(2024, 1, 2, tzinfo=UTC),
        )
