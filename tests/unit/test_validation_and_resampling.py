from decimal import Decimal

import pytest

from trading_platform.core.enums import Timeframe
from trading_platform.market_data.resampling import resample_candles
from trading_platform.validation.candles import QualityStatus, validate_candles, validate_records


def test_validator_reports_duplicate_gap_and_ohlc(candle_factory) -> None:
    first = candle_factory(0)
    last = candle_factory(2)
    invalid = last.model_copy(update={"high": Decimal("8.0")})
    report = validate_candles([first, first, invalid], Timeframe.ONE_MINUTE)
    assert report.rows == 3
    assert report.duplicates == 1
    assert report.missing_candles == 1
    assert report.invalid_ohlc == 1
    assert report.status is QualityStatus.FAIL


def test_validator_warns_for_missing_candle_without_hiding_it(candle_factory) -> None:
    report = validate_candles([candle_factory(0), candle_factory(3)], Timeframe.ONE_MINUTE)
    assert report.missing_candles == 2
    assert len(report.missing_open_times) == 2
    assert report.status is QualityStatus.WARNING


def test_validator_counts_null_and_corrupt_rows(candle_factory) -> None:
    good = candle_factory(0).model_dump(mode="json")
    null_row = {**good, "open": None}
    corrupt_row = {**good, "open": "not-a-price"}
    report = validate_records([good, null_row, corrupt_row], Timeframe.ONE_MINUTE)
    assert report.rows == 3
    assert report.null_values == 1
    assert report.corrupt_rows == 2
    assert report.status is QualityStatus.FAIL


def test_resample_aggregates_only_complete_5m_groups(candle_factory) -> None:
    source = [
        candle_factory(
            minute,
            open_price=str(100 + minute),
            high=str(110 + minute),
            low=str(90 + minute),
            close=str(105 + minute),
            volume="1.25",
        )
        for minute in range(5)
    ] + [candle_factory(6)]
    result = resample_candles(source, Timeframe.FIVE_MINUTES)
    assert len(result.candles) == 1
    assert result.skipped_incomplete_groups == 1
    candle = result.candles[0]
    assert candle.open == Decimal("100")
    assert candle.close == Decimal("109")
    assert candle.high == Decimal("114")
    assert candle.low == Decimal("90")
    assert candle.volume == Decimal("6.25")
    assert candle.quote_volume == Decimal("125.0")
    assert candle.number_of_trades == 15
    assert candle.close_time.isoformat() == "2024-01-01T00:04:59.999000+00:00"


def test_resample_rejects_one_minute_target(candle_factory) -> None:
    with pytest.raises(ValueError, match="larger than 1m"):
        resample_candles([candle_factory(0)], Timeframe.ONE_MINUTE)


def test_resample_rejects_mixed_symbols(candle_factory) -> None:
    other = candle_factory(0).model_copy(update={"symbol": "ETHUSDT"})
    with pytest.raises(ValueError, match="one market series"):
        resample_candles([candle_factory(0), other], Timeframe.FIVE_MINUTES)


@pytest.mark.parametrize(
    ("target", "source_count"),
    [(Timeframe.FIFTEEN_MINUTES, 15), (Timeframe.ONE_HOUR, 60)],
)
def test_resample_supports_all_configured_timeframes(candle_factory, target, source_count) -> None:
    source = [candle_factory(minute) for minute in range(source_count)]
    result = resample_candles(source, target)
    assert len(result.candles) == 1
    assert result.skipped_incomplete_groups == 0
    assert result.candles[0].timeframe is target
