"""Partitioned Parquet storage with idempotent raw writes."""

import os
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import structlog

from trading_platform.core.exceptions import StorageError
from trading_platform.domain.candle import Candle

logger = structlog.get_logger(__name__)
CANDLE_COLUMNS = [
    "exchange",
    "market_type",
    "symbol",
    "timeframe",
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
]


class ParquetCandleStorage:
    """Store raw candles by exchange/market/symbol/timeframe/year/month."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.raw_root = data_dir / "raw"
        self.processed_root = data_dir / "processed"

    def _symbol_dir(
        self, root: Path, exchange: str, market_type: str, symbol: str, timeframe: str
    ) -> Path:
        return root / exchange.lower() / market_type.lower() / symbol.upper() / timeframe

    def _partition_file(self, folder: Path, date: datetime) -> Path:
        return folder / f"year={date.year}" / f"month={date.month:02d}" / "candles.parquet"

    @staticmethod
    def _records(candles: list[Candle]) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for candle in candles:
            row = candle.model_dump()
            row["market_type"] = candle.market_type.value
            row["timeframe"] = candle.timeframe.value
            records.append(row)
        return records

    def save_raw(self, candles: list[Candle]) -> int:
        """Append new rows to monthly files while preserving existing rows unchanged."""
        grouped: dict[Path, list[Candle]] = defaultdict(list)
        for candle in candles:
            folder = self._symbol_dir(
                self.raw_root,
                candle.exchange,
                candle.market_type.value,
                candle.symbol,
                candle.timeframe.value,
            )
            grouped[self._partition_file(folder, candle.open_time)].append(candle)

        added = 0
        for path, group in grouped.items():
            existing: list[Candle] = []
            if path.exists():
                existing = self._load_file(path)
            known = {candle.open_time for candle in existing}
            new_candles: list[Candle] = []
            for candle in group:
                if candle.open_time not in known:
                    new_candles.append(candle)
                    known.add(candle.open_time)
            if not new_candles:
                continue
            merged = sorted([*existing, *new_candles], key=lambda candle: candle.open_time)
            self._atomic_write(path, merged)
            added += len(new_candles)
            logger.info("raw_partition_written", path=str(path), inserted=len(new_candles))
        return added

    def save_processed(self, candles: list[Candle]) -> int:
        """Write derived candles to replaceable processed partitions."""
        grouped: dict[Path, list[Candle]] = defaultdict(list)
        for candle in candles:
            folder = self._symbol_dir(
                self.processed_root,
                candle.exchange,
                candle.market_type.value,
                candle.symbol,
                candle.timeframe.value,
            )
            grouped[self._partition_file(folder, candle.open_time)].append(candle)
        for path, group in grouped.items():
            previous = self._load_file(path) if path.exists() else []
            indexed = {item.open_time: item for item in previous}
            indexed.update({item.open_time: item for item in group})
            self._atomic_write(path, sorted(indexed.values(), key=lambda item: item.open_time))
        return len(candles)

    def load_candles(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        timeframe: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        processed: bool = False,
    ) -> list[Candle]:
        root = self.processed_root if processed else self.raw_root
        folder = self._symbol_dir(root, exchange, market_type, symbol, timeframe)
        if not folder.exists():
            return []
        candles: list[Candle] = []
        try:
            for path in sorted(folder.glob("year=*/month=*/candles.parquet")):
                for candle in self._load_file(path):
                    if start_time is not None and candle.open_time < _utc(start_time):
                        continue
                    if end_time is not None and candle.open_time >= _utc(end_time):
                        continue
                    candles.append(candle)
        except (OSError, pl.exceptions.PolarsError, ValueError) as exc:
            raise StorageError(f"Could not load Parquet candles from {folder}: {exc}") from exc
        return sorted(candles, key=lambda candle: candle.open_time)

    def load_records(
        self, exchange: str, market_type: str, symbol: str, timeframe: str, processed: bool = False
    ) -> list[dict[str, object]]:
        """Read stored rows without domain parsing so validation can count bad values."""
        root = self.processed_root if processed else self.raw_root
        folder = self._symbol_dir(root, exchange, market_type, symbol, timeframe)
        if not folder.exists():
            return []
        records: list[dict[str, object]] = []
        try:
            for path in sorted(folder.glob("year=*/month=*/candles.parquet")):
                records.extend(pl.read_parquet(path).to_dicts())
        except (OSError, pl.exceptions.PolarsError) as exc:
            raise StorageError(f"Could not read raw Parquet rows from {folder}: {exc}") from exc
        return records

    def latest_open_time(
        self, exchange: str, market_type: str, symbol: str, timeframe: str
    ) -> datetime | None:
        folder = self._symbol_dir(
            self.raw_root, exchange, market_type, symbol, timeframe
        )
        paths = sorted(folder.glob("year=*/month=*/candles.parquet"), reverse=True)
        try:
            for path in paths:
                column = pl.read_parquet(path, columns=["open_time"]).get_column("open_time")
                latest = column.max()
                if isinstance(latest, datetime):
                    return latest.astimezone(UTC) if latest.tzinfo else latest.replace(tzinfo=UTC)
                if latest is not None:
                    raise StorageError(f"Unexpected timestamp value in {path}: {latest!r}")
        except (OSError, pl.exceptions.PolarsError) as exc:
            message = f"Could not read latest candle timestamp from {folder}: {exc}"
            raise StorageError(message) from exc
        return None

    @staticmethod
    def _load_file(path: Path) -> list[Candle]:
        try:
            rows = pl.read_parquet(path).select(CANDLE_COLUMNS).to_dicts()
            return [Candle.model_validate(row) for row in rows]
        except (OSError, pl.exceptions.PolarsError, ValueError, TypeError) as exc:
            raise StorageError(f"Corrupt or unreadable Parquet file {path}: {exc}") from exc

    @staticmethod
    def _atomic_write(path: Path, candles: list[Candle]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pl.DataFrame(ParquetCandleStorage._records(candles))
        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".candles-", suffix=".parquet", dir=path.parent, delete=False
            ) as temporary_file:
                temporary_path = temporary_file.name
            frame.write_parquet(temporary_path, compression="zstd", statistics=True)
            os.replace(temporary_path, path)
        except (OSError, pl.exceptions.PolarsError) as exc:
            if temporary_path and os.path.exists(temporary_path):
                os.unlink(temporary_path)
            raise StorageError(f"Could not atomically write Parquet file {path}: {exc}") from exc


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Storage date bounds must be timezone-aware")
    return value.astimezone(UTC)
