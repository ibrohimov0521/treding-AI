"""Deterministic indicators computed from closed candles only.

Every feature at index ``i`` uses candle ``i`` and earlier candles. No rolling
operation is centered, and no future row is read. Returned values are suitable
for research; they are not trading recommendations.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from statistics import pstdev
from typing import Any

import polars as pl

from trading_platform.domain.candle import Candle

EMA_FAST_SPAN = 12
EMA_SLOW_SPAN = 26
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLATILITY_WINDOW = 20
VOLUME_WINDOW = 20


@dataclass(frozen=True, slots=True)
class FeatureRow:
    """One feature observation available immediately after a candle closes."""

    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    close: float
    return_1: float | None
    return_5: float | None
    return_15: float | None
    ema_12: float | None
    ema_26: float | None
    rsi_14: float | None
    atr_14: float | None
    realized_volatility_20: float | None
    relative_volume_20: float | None
    volume_change_1: float | None
    range_pct: float | None
    taker_buy_ratio: float | None
    ready: bool


FEATURE_SCHEMA: dict[str, Any] = {
    "exchange": pl.String,
    "market_type": pl.String,
    "symbol": pl.String,
    "timeframe": pl.String,
    "open_time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "close_time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "close": pl.Float64,
    "return_1": pl.Float64,
    "return_5": pl.Float64,
    "return_15": pl.Float64,
    "ema_12": pl.Float64,
    "ema_26": pl.Float64,
    "rsi_14": pl.Float64,
    "atr_14": pl.Float64,
    "realized_volatility_20": pl.Float64,
    "relative_volume_20": pl.Float64,
    "volume_change_1": pl.Float64,
    "range_pct": pl.Float64,
    "taker_buy_ratio": pl.Float64,
    "ready": pl.Boolean,
}


def compute_features(candles: list[Candle], *, as_of: datetime | None = None) -> list[FeatureRow]:
    """Build causal features for one strictly ordered market series.

    ``as_of`` is the information cutoff. A candle is included only when its
    inclusive ``close_time`` is earlier than that cutoff. Omitting ``as_of``
    uses the current UTC time, which excludes a still-open candle.
    """
    if not candles:
        return []
    cutoff = _utc_cutoff(as_of)
    identity = candles[0]
    previous_time: datetime | None = None
    for candle in candles:
        if (
            candle.exchange != identity.exchange
            or candle.market_type != identity.market_type
            or candle.symbol != identity.symbol
            or candle.timeframe != identity.timeframe
        ):
            raise ValueError("Feature input must contain exactly one market series")
        if previous_time is not None and candle.open_time <= previous_time:
            raise ValueError("Feature input must have unique, increasing open_time values")
        if candle.close <= 0:
            raise ValueError("Feature input close prices must be positive")
        previous_time = candle.open_time

    closed = [candle for candle in candles if candle.close_time < cutoff]
    if not closed:
        return []

    closes = [float(candle.close) for candle in closed]
    highs = [float(candle.high) for candle in closed]
    lows = [float(candle.low) for candle in closed]
    volumes = [float(candle.volume) for candle in closed]
    taker_buys = [float(candle.taker_buy_base_volume) for candle in closed]

    ema_12 = _ema(closes, EMA_FAST_SPAN)
    ema_26 = _ema(closes, EMA_SLOW_SPAN)
    rsi_14 = _rsi(closes, RSI_PERIOD)
    atr_14 = _atr(highs, lows, closes, ATR_PERIOD)
    returns_1 = [_return(closes, index, 1) for index in range(len(closed))]
    returns_5 = [_return(closes, index, 5) for index in range(len(closed))]
    returns_15 = [_return(closes, index, 15) for index in range(len(closed))]
    volatility = _rolling_volatility(returns_1, VOLATILITY_WINDOW)
    relative_volume = _relative_volume(volumes, VOLUME_WINDOW)

    rows: list[FeatureRow] = []
    for index, candle in enumerate(closed):
        volume_change = _return(volumes, index, 1)
        average_features = (
            ema_12[index],
            ema_26[index],
            rsi_14[index],
            atr_14[index],
            volatility[index],
            relative_volume[index],
        )
        rows.append(
            FeatureRow(
                exchange=candle.exchange,
                market_type=candle.market_type.value,
                symbol=candle.symbol,
                timeframe=candle.timeframe.value,
                open_time=candle.open_time,
                close_time=candle.close_time,
                close=closes[index],
                return_1=returns_1[index],
                return_5=returns_5[index],
                return_15=returns_15[index],
                ema_12=ema_12[index],
                ema_26=ema_26[index],
                rsi_14=rsi_14[index],
                atr_14=atr_14[index],
                realized_volatility_20=volatility[index],
                relative_volume_20=relative_volume[index],
                volume_change_1=volume_change,
                range_pct=(highs[index] - lows[index]) / closes[index],
                taker_buy_ratio=(
                    taker_buys[index] / volumes[index] if volumes[index] > 0 else None
                ),
                ready=all(value is not None for value in average_features),
            )
        )
    return rows


def features_frame(rows: list[FeatureRow]) -> pl.DataFrame:
    """Convert feature rows to a stable-schema Polars frame for storage/analysis."""
    if not rows:
        return pl.DataFrame(schema=FEATURE_SCHEMA)
    return pl.DataFrame([asdict(row) for row in rows], schema=FEATURE_SCHEMA)


def _utc_cutoff(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return value.astimezone(UTC)


def _ema(values: list[float], span: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) < span:
        return output
    current = sum(values[:span]) / span
    output[span - 1] = current
    alpha = 2.0 / (span + 1.0)
    for index in range(span, len(values)):
        current = alpha * values[index] + (1.0 - alpha) * current
        output[index] = current
    return output


def _rsi(values: list[float], period: int) -> list[float | None]:
    output: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return output
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    output[period] = _rsi_value(average_gain, average_loss)
    for index in range(period + 1, len(values)):
        change_index = index - 1
        average_gain = (average_gain * (period - 1) + gains[change_index]) / period
        average_loss = (average_loss * (period - 1) + losses[change_index]) / period
        output[index] = _rsi_value(average_gain, average_loss)
    return output


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 50.0 if average_gain == 0 else 100.0
    relative_strength = average_gain / average_loss
    return 100.0 - 100.0 / (1.0 + relative_strength)


def _atr(
    highs: list[float], lows: list[float], closes: list[float], period: int
) -> list[float | None]:
    output: list[float | None] = [None] * len(closes)
    if not closes:
        return output
    true_ranges = [highs[0] - lows[0]]
    for index in range(1, len(closes)):
        true_ranges.append(
            max(
                highs[index] - lows[index],
                abs(highs[index] - closes[index - 1]),
                abs(lows[index] - closes[index - 1]),
            )
        )
    if len(true_ranges) < period:
        return output
    current = sum(true_ranges[:period]) / period
    output[period - 1] = current
    for index in range(period, len(true_ranges)):
        current = (current * (period - 1) + true_ranges[index]) / period
        output[index] = current
    return output


def _return(values: list[float], index: int, lookback: int) -> float | None:
    previous_index = index - lookback
    if previous_index < 0 or values[previous_index] == 0:
        return None
    return values[index] / values[previous_index] - 1.0


def _rolling_volatility(returns: list[float | None], window: int) -> list[float | None]:
    output: list[float | None] = [None] * len(returns)
    for index in range(window, len(returns)):
        sample = returns[index - window + 1 : index + 1]
        if all(value is not None for value in sample):
            output[index] = pstdev(value for value in sample if value is not None)
    return output


def _relative_volume(volumes: list[float], window: int) -> list[float | None]:
    output: list[float | None] = [None] * len(volumes)
    for index in range(window - 1, len(volumes)):
        average = sum(volumes[index - window + 1 : index + 1]) / window
        if average > 0:
            output[index] = volumes[index] / average
    return output


__all__ = [
    "FeatureRow",
    "compute_features",
    "features_frame",
]
