"""Forward-return labels and purged chronological dataset splits."""

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from math import isfinite

import polars as pl

from trading_platform.domain.candle import Candle
from trading_platform.features.engineering import FeatureRow, compute_features

CLASS_LABELS = ("DOWN", "NEUTRAL", "UP")
FEATURE_NAMES = (
    "return_1",
    "return_5",
    "return_15",
    "ema_12_gap",
    "ema_26_gap",
    "rsi_14_scaled",
    "atr_14_pct",
    "realized_volatility_20",
    "relative_volume_20",
    "volume_change_1",
    "range_pct",
    "taker_buy_ratio",
)


@dataclass(frozen=True, slots=True)
class LabeledSample:
    """Feature vector at one close and a label ending ``horizon`` bars later."""

    feature_time: datetime
    label_end_time: datetime
    forward_return: float
    label: str
    features: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class LabeledDataset:
    """Chronologically ordered supervised examples from one market series."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    horizon: int
    neutral_band_bps: float
    samples: tuple[LabeledSample, ...]

    @property
    def feature_names(self) -> tuple[str, ...]:
        return FEATURE_NAMES

    def class_counts(self) -> dict[str, int]:
        counts = Counter(sample.label for sample in self.samples)
        return {label: counts.get(label, 0) for label in CLASS_LABELS}

    def to_frame(self) -> pl.DataFrame:
        """Return a Parquet-ready frame; future-derived label fields are explicit."""
        records = []
        for sample in self.samples:
            record: dict[str, object] = {
                "feature_time": sample.feature_time,
                "label_end_time": sample.label_end_time,
                "forward_return": sample.forward_return,
                "label": sample.label,
            }
            record.update(dict(zip(FEATURE_NAMES, sample.features, strict=True)))
            records.append(record)
        return pl.DataFrame(records)


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    """Chronological train/validation/test sets with a horizon-sized purge gap."""

    train: tuple[LabeledSample, ...]
    validation: tuple[LabeledSample, ...]
    test: tuple[LabeledSample, ...]
    purge_bars: int


def build_labeled_dataset(
    candles: list[Candle],
    *,
    horizon: int = 5,
    neutral_band_bps: float = 10.0,
    as_of: datetime | None = None,
) -> LabeledDataset:
    """Label future returns while keeping future prices out of feature vectors.

    For a sample at candle ``t``, the feature vector uses information through
    ``t`` and the label uses the close at ``t + horizon``. The final ``horizon``
    candles are excluded because their outcomes are not observable yet.
    """
    if horizon < 1:
        raise ValueError("horizon must be at least one candle")
    if not 0 <= neutral_band_bps < 10_000:
        raise ValueError("neutral_band_bps must be in [0, 10000)")
    if not candles:
        raise ValueError("Cannot build a dataset from an empty candle series")

    cutoff = _utc_cutoff(as_of)
    closed = [candle for candle in candles if candle.close_time < cutoff]
    feature_rows = compute_features(candles, as_of=cutoff)
    if not closed:
        raise ValueError("No candles are closed at the selected as_of time")
    _validate_contiguous(closed)

    samples: list[LabeledSample] = []
    band = neutral_band_bps / 10_000.0
    closes = [float(candle.close) for candle in closed]
    for index in range(max(0, len(closed) - horizon)):
        row = feature_rows[index]
        if not row.ready:
            continue
        vector = _feature_vector(row)
        if vector is None:
            continue
        forward_return = closes[index + horizon] / closes[index] - 1.0
        if forward_return > band:
            label = "UP"
        elif forward_return < -band:
            label = "DOWN"
        else:
            label = "NEUTRAL"
        samples.append(
            LabeledSample(
                feature_time=row.close_time,
                label_end_time=closed[index + horizon].close_time,
                forward_return=forward_return,
                label=label,
                features=vector,
            )
        )
    return LabeledDataset(
        exchange=closed[0].exchange,
        market_type=closed[0].market_type.value,
        symbol=closed[0].symbol,
        timeframe=closed[0].timeframe.value,
        horizon=horizon,
        neutral_band_bps=neutral_band_bps,
        samples=tuple(samples),
    )


def chronological_split(
    dataset: LabeledDataset,
    *,
    train_fraction: float = 0.6,
    validation_fraction: float = 0.2,
) -> DatasetSplit:
    """Split in time order and purge labels that reach across split boundaries."""
    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("train and validation fractions must sum to less than 1")
    samples = dataset.samples
    count = len(samples)
    train_boundary = int(count * train_fraction)
    validation_boundary = int(count * (train_fraction + validation_fraction))
    train_end = max(0, train_boundary - dataset.horizon)
    validation_end = max(train_boundary, validation_boundary - dataset.horizon)
    split = DatasetSplit(
        train=samples[:train_end],
        validation=samples[train_boundary:validation_end],
        test=samples[validation_boundary:],
        purge_bars=dataset.horizon,
    )
    if not split.train or not split.validation or not split.test:
        raise ValueError("Dataset is too small for non-empty purged train/validation/test sets")
    if split.train[-1].label_end_time >= split.validation[0].feature_time:
        raise ValueError("Training labels overlap the validation period")
    if split.validation[-1].label_end_time >= split.test[0].feature_time:
        raise ValueError("Validation labels overlap the test period")
    return split


def _feature_vector(row: FeatureRow) -> tuple[float, ...] | None:
    required = (
        row.return_1,
        row.return_5,
        row.return_15,
        row.ema_12,
        row.ema_26,
        row.rsi_14,
        row.atr_14,
        row.realized_volatility_20,
        row.relative_volume_20,
        row.volume_change_1,
        row.range_pct,
        row.taker_buy_ratio,
    )
    if any(value is None for value in required):
        return None
    assert row.return_1 is not None
    assert row.return_5 is not None
    assert row.return_15 is not None
    assert row.ema_12 is not None
    assert row.ema_26 is not None
    assert row.rsi_14 is not None
    assert row.atr_14 is not None
    assert row.realized_volatility_20 is not None
    assert row.relative_volume_20 is not None
    assert row.volume_change_1 is not None
    assert row.range_pct is not None
    assert row.taker_buy_ratio is not None
    close = row.close
    vector = (
        float(row.return_1),
        float(row.return_5),
        float(row.return_15),
        float(row.ema_12) / close - 1.0,
        float(row.ema_26) / close - 1.0,
        float(row.rsi_14) / 100.0,
        float(row.atr_14) / close,
        float(row.realized_volatility_20),
        float(row.relative_volume_20),
        float(row.volume_change_1),
        float(row.range_pct),
        float(row.taker_buy_ratio),
    )
    return vector if all(isfinite(value) for value in vector) else None


def _utc_cutoff(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _validate_contiguous(candles: list[Candle]) -> None:
    first = candles[0]
    previous: Candle | None = None
    for candle in candles:
        if (
            candle.exchange != first.exchange
            or candle.market_type != first.market_type
            or candle.symbol != first.symbol
            or candle.timeframe != first.timeframe
        ):
            raise ValueError("Dataset input must contain exactly one market series")
        if (
            previous is not None
            and candle.open_time != previous.open_time + first.timeframe.duration
        ):
            raise ValueError("Dataset requires contiguous candles; validate and backfill first")
        previous = candle
