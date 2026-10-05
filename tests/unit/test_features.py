from dataclasses import asdict
from datetime import timedelta

import pytest

from trading_platform.features.engineering import compute_features, features_frame


def _trend(candle_factory, count: int = 40):
    return [
        candle_factory(
            index,
            open_price=str(100 + index),
            high=str(102 + index),
            low=str(98 + index),
            close=str(100 + index),
            volume=str(10 + index),
        )
        for index in range(count)
    ]


def test_features_are_causal_and_have_expected_warmup(candle_factory) -> None:
    candles = _trend(candle_factory)
    cutoff = candles[-1].close_time + timedelta(microseconds=1)
    rows = compute_features(candles, as_of=cutoff)

    assert rows[0].return_1 is None
    assert rows[1].return_1 == pytest.approx(101 / 100 - 1)
    assert rows[5].return_5 == pytest.approx(105 / 100 - 1)
    assert rows[14].rsi_14 == 100.0
    assert rows[24].ema_26 is None
    assert rows[25].ema_26 is not None
    assert rows[25].ready is True
    assert rows[25].relative_volume_20 is not None
    assert rows[25].taker_buy_ratio == pytest.approx(1.0 / (10 + 25))

    prefix = compute_features(
        candles[:30], as_of=candles[29].close_time + timedelta(microseconds=1)
    )
    assert asdict(prefix[-1]) == asdict(rows[29])


def test_as_of_excludes_open_or_not_yet_closed_candles(candle_factory) -> None:
    candles = _trend(candle_factory, 3)
    before_second_close = compute_features(candles, as_of=candles[1].close_time)
    assert [row.open_time for row in before_second_close] == [candles[0].open_time]
    rows = compute_features(candles, as_of=candles[1].close_time + timedelta(microseconds=1))
    assert [row.open_time for row in rows] == [item.open_time for item in candles[:2]]


def test_feature_input_rejects_duplicate_or_mixed_series(candle_factory) -> None:
    first = candle_factory(0)
    second = candle_factory(1)
    with pytest.raises(ValueError, match="unique, increasing"):
        compute_features([first, second, second])

    other_market = second.model_copy(update={"symbol": "ETHUSDT"})
    with pytest.raises(ValueError, match="exactly one market series"):
        compute_features([first, other_market])


def test_feature_frame_has_stable_schema_even_when_empty(candle_factory) -> None:
    assert (
        features_frame([]).columns
        == features_frame([compute_features([candle_factory(0)])[0]]).columns
    )


def test_feature_cutoff_must_be_timezone_aware(candle_factory) -> None:
    from datetime import datetime

    with pytest.raises(ValueError, match="timezone-aware"):
        compute_features([candle_factory(0)], as_of=datetime(2024, 1, 1))
