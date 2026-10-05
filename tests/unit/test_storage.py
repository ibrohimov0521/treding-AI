from decimal import Decimal

from trading_platform.core.enums import Timeframe
from trading_platform.storage.parquet import ParquetCandleStorage


def test_raw_parquet_roundtrip_is_idempotent_and_partitioned(tmp_path, candle_factory) -> None:
    storage = ParquetCandleStorage(tmp_path / "data")
    candle = candle_factory(0)
    assert storage.save_raw([candle, candle]) == 1
    assert storage.save_raw([candle]) == 0
    loaded = storage.load_candles("binance", "spot", "BTCUSDT", "1m")
    assert len(loaded) == 1
    assert loaded[0].open == Decimal("10.0")
    assert loaded[0].open_time == candle.open_time
    assert storage.latest_open_time("binance", "spot", "BTCUSDT", "1m") == candle.open_time
    assert list(
        (tmp_path / "data/raw/binance/spot/BTCUSDT/1m").glob("year=*/month=*/candles.parquet")
    )


def test_processed_parquet_roundtrip(tmp_path, candle_factory) -> None:
    storage = ParquetCandleStorage(tmp_path / "data")
    derived = candle_factory(0, timeframe=Timeframe.FIVE_MINUTES)
    assert storage.save_processed([derived]) == 1
    loaded = storage.load_candles("BINANCE", "spot", "BTCUSDT", "5m", processed=True)
    assert loaded[0].timeframe is Timeframe.FIVE_MINUTES
