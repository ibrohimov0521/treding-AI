"""Deterministic UTC-aligned aggregation from canonical 1m candles."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from trading_platform.core.enums import Timeframe
from trading_platform.domain.candle import Candle


@dataclass(frozen=True, slots=True)
class ResampleResult:
    """Complete derived candles and the number of skipped incomplete buckets."""

    candles: list[Candle]
    skipped_incomplete_groups: int


def resample_candles(candles: list[Candle], target: Timeframe) -> ResampleResult:
    """Aggregate complete 1m candles; incomplete buckets are deliberately omitted."""
    if target == Timeframe.ONE_MINUTE:
        raise ValueError("Target timeframe must be larger than 1m")
    if not candles:
        return ResampleResult(candles=[], skipped_incomplete_groups=0)
    if any(candle.timeframe != Timeframe.ONE_MINUTE for candle in candles):
        raise ValueError("Resampling requires canonical 1m source candles")
    identity = candles[0]
    if any(
        candle.exchange != identity.exchange
        or candle.market_type != identity.market_type
        or candle.symbol != identity.symbol
        for candle in candles
    ):
        raise ValueError("Resampling input must contain exactly one market series")

    target_ms = target.milliseconds
    buckets: dict[datetime, list[Candle]] = defaultdict(list)
    for candle in candles:
        epoch_ms = int(candle.open_time.timestamp() * 1000)
        bucket_ms = epoch_ms - epoch_ms % target_ms
        bucket_time = datetime.fromtimestamp(bucket_ms / 1000, tz=UTC)
        buckets[bucket_time].append(candle)

    expected_rows = target_ms // Timeframe.ONE_MINUTE.milliseconds
    result: list[Candle] = []
    skipped = 0
    for bucket_time, group in sorted(buckets.items()):
        group.sort(key=lambda item: item.open_time)
        expected_times = [
            bucket_time + index * Timeframe.ONE_MINUTE.duration for index in range(expected_rows)
        ]
        if len(group) != expected_rows or [item.open_time for item in group] != expected_times:
            skipped += 1
            continue
        first, last = group[0], group[-1]
        result.append(
            Candle(
                exchange=first.exchange,
                market_type=first.market_type,
                symbol=first.symbol,
                timeframe=target,
                open_time=bucket_time,
                close_time=bucket_time + target.duration - timedelta(milliseconds=1),
                open=first.open,
                high=max(item.high for item in group),
                low=min(item.low for item in group),
                close=last.close,
                volume=sum((item.volume for item in group), start=first.volume * 0),
                quote_volume=sum(
                    (item.quote_volume for item in group), start=first.quote_volume * 0
                ),
                number_of_trades=sum(item.number_of_trades for item in group),
                taker_buy_base_volume=sum(
                    (item.taker_buy_base_volume for item in group),
                    start=first.taker_buy_base_volume * 0,
                ),
                taker_buy_quote_volume=sum(
                    (item.taker_buy_quote_volume for item in group),
                    start=first.taker_buy_quote_volume * 0,
                ),
            )
        )
    return ResampleResult(candles=result, skipped_incomplete_groups=skipped)
