"""Structural and time-series checks for OHLCV candles."""

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from pydantic import ValidationError

from trading_platform.core.enums import Timeframe
from trading_platform.domain.candle import Candle


class QualityStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    """Counts and examples from one candle-series validation run."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    rows: int
    duplicates: int
    missing_candles: int
    missing_open_times: tuple[str, ...]
    out_of_order: int
    invalid_ohlc: int
    negative_volume: int
    impossible_timestamps: int
    null_values: int
    corrupt_rows: int
    status: QualityStatus

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable report data."""
        return {**asdict(self), "status": self.status.value}


def validate_records(
    records: list[dict[str, object]],
    timeframe: Timeframe,
    as_of: datetime | None = None,
    exchange: str | None = None,
    market_type: str | None = None,
    symbol: str | None = None,
) -> DataQualityReport:
    """Validate untrusted stored rows, counting null and unparseable records."""
    valid: list[Candle] = []
    null_values = 0
    corrupt_rows = 0
    for record in records:
        null_values += sum(value is None for value in record.values())
        try:
            valid.append(Candle.model_validate(record))
        except (ValidationError, ValueError, TypeError):
            corrupt_rows += 1
    report = validate_candles(valid, timeframe, as_of=as_of)
    status = QualityStatus.FAIL if null_values or corrupt_rows else report.status
    return replace(
        report,
        exchange=report.exchange if valid else (exchange or report.exchange),
        market_type=report.market_type if valid else (market_type or report.market_type),
        symbol=report.symbol if valid else (symbol or report.symbol),
        rows=len(records),
        null_values=report.null_values + null_values,
        corrupt_rows=report.corrupt_rows + corrupt_rows,
        status=status,
    )


def validate_candles(
    candles: list[Candle],
    timeframe: Timeframe,
    as_of: datetime | None = None,
    missing_sample_limit: int = 25,
) -> DataQualityReport:
    """Check uniqueness, spacing, timestamps, nulls, volume, and OHLC logic."""
    reference_time = as_of or datetime.now(UTC)
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("Validation reference time must be timezone-aware")
    reference_time = reference_time.astimezone(UTC)
    if not candles:
        return DataQualityReport(
            exchange="unknown",
            market_type="unknown",
            symbol="unknown",
            timeframe=timeframe.value,
            rows=0,
            duplicates=0,
            missing_candles=0,
            missing_open_times=(),
            out_of_order=0,
            invalid_ohlc=0,
            negative_volume=0,
            impossible_timestamps=0,
            null_values=0,
            corrupt_rows=0,
            status=QualityStatus.WARNING,
        )

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    first = candles[0]
    open_counts = Counter(candle.open_time for candle in candles)
    duplicates = sum(count - 1 for count in open_counts.values() if count > 1)
    out_of_order = sum(
        current.open_time <= previous.open_time for previous, current in pairwise(candles)
    )

    expected_step = timeframe.duration
    missing_count = 0
    missing_samples: list[str] = []
    for previous, current in pairwise(ordered):
        gap_seconds = (current.open_time - previous.open_time).total_seconds()
        if gap_seconds > expected_step.total_seconds():
            count = int(gap_seconds // expected_step.total_seconds()) - 1
            missing_count += count
            next_time = previous.open_time + expected_step
            for _ in range(min(count, max(0, missing_sample_limit - len(missing_samples)))):
                missing_samples.append(next_time.isoformat())
                next_time += expected_step

    invalid_ohlc = 0
    negative_volume = 0
    impossible_timestamps = 0
    null_values = 0
    corrupt_rows = 0
    numeric_fields = (
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
    )
    for candle in candles:
        values = [getattr(candle, name) for name in numeric_fields]
        null_values += sum(value is None for value in values)
        if not all(isinstance(value, Decimal) and value.is_finite() for value in values):
            corrupt_rows += 1
            continue
        if not (
            candle.high >= candle.open
            and candle.high >= candle.close
            and candle.high >= candle.low
            and candle.low <= candle.open
            and candle.low <= candle.close
        ):
            invalid_ohlc += 1
        if any(value < 0 for value in values[4:]):
            negative_volume += 1
        expected_close = candle.open_time + candle.timeframe.duration - timedelta(milliseconds=1)
        open_epoch_ms = int(candle.open_time.timestamp() * 1000)
        if (
            candle.open_time > reference_time
            or candle.close_time > reference_time
            or candle.close_time < candle.open_time
            or candle.close_time != expected_close
            or open_epoch_ms % timeframe.milliseconds != 0
        ):
            impossible_timestamps += 1

    hard_failures = sum(
        (invalid_ohlc, negative_volume, impossible_timestamps, null_values, corrupt_rows)
    )
    warnings = duplicates + missing_count + out_of_order
    status = (
        QualityStatus.FAIL
        if hard_failures
        else (QualityStatus.WARNING if warnings else QualityStatus.PASS)
    )
    return DataQualityReport(
        exchange=first.exchange,
        market_type=first.market_type.value,
        symbol=first.symbol,
        timeframe=timeframe.value,
        rows=len(candles),
        duplicates=duplicates,
        missing_candles=missing_count,
        missing_open_times=tuple(missing_samples),
        out_of_order=out_of_order,
        invalid_ohlc=invalid_ohlc,
        negative_volume=negative_volume,
        impossible_timestamps=impossible_timestamps,
        null_values=null_values,
        corrupt_rows=corrupt_rows,
        status=status,
    )
