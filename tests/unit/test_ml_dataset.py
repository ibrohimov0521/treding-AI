from math import sin

import pytest

from trading_platform.ml.dataset import (
    CLASS_LABELS,
    build_labeled_dataset,
    chronological_split,
)
from trading_platform.ml.walkforward import evaluate_walk_forward, make_walk_forward_folds


def _oscillating(candle_factory, count: int = 300):
    candles = []
    for index in range(count):
        close = 100.0 + 4.0 * sin(index / 5.0) + 1.5 * sin(index / 17.0)
        candles.append(
            candle_factory(
                index,
                open_price=str(close),
                high=str(close + 2.0),
                low=str(close - 2.0),
                close=str(close),
                volume=str(100 + index % 23),
            )
        )
    return candles


def test_forward_labels_use_horizon_and_exclude_unobservable_tail(candle_factory) -> None:
    candles = [
        candle_factory(
            index,
            open_price=str(100 + index),
            high=str(102 + index),
            low=str(98 + index),
            close=str(100 + index),
            volume=str(10 + index),
        )
        for index in range(40)
    ]
    dataset = build_labeled_dataset(candles, horizon=5, neutral_band_bps=0)

    assert dataset.samples
    assert dataset.samples[0].feature_time == candles[25].close_time
    assert dataset.samples[0].label_end_time == candles[30].close_time
    assert dataset.samples[0].forward_return == pytest.approx(130 / 125 - 1)
    assert dataset.samples[0].label == "UP"
    assert len(dataset.samples) == 10
    assert len(dataset.samples[-1].features) == len(dataset.feature_names)
    assert dataset.class_counts() == {"DOWN": 0, "NEUTRAL": 0, "UP": 10}


def test_chronological_split_purges_overlapping_forward_labels(candle_factory) -> None:
    dataset = build_labeled_dataset(_oscillating(candle_factory), horizon=3, neutral_band_bps=10)
    split = chronological_split(dataset)

    assert split.train[-1].feature_time < split.validation[0].feature_time
    assert split.train[-1].label_end_time < split.validation[0].feature_time
    assert split.validation[-1].label_end_time < split.test[0].feature_time
    assert split.purge_bars == 3
    assert (
        split.train[0].feature_time < split.validation[0].feature_time < split.test[0].feature_time
    )


def test_walk_forward_folds_expand_training_and_keep_time_order(candle_factory) -> None:
    dataset = build_labeled_dataset(_oscillating(candle_factory), horizon=3, neutral_band_bps=10)
    folds = make_walk_forward_folds(
        dataset,
        min_train_rows=60,
        test_rows=30,
        step_rows=30,
    )

    assert len(folds) > 1
    assert folds[0].train[-1].label_end_time < folds[0].test[0].feature_time
    assert len(folds[1].train) > len(folds[0].train)
    assert folds[0].test[-1].feature_time < folds[1].test[0].feature_time


def test_walk_forward_logistic_baseline_reports_out_of_sample_metrics(candle_factory) -> None:
    pytest.importorskip("sklearn")
    dataset = build_labeled_dataset(_oscillating(candle_factory), horizon=3, neutral_band_bps=10)
    report = evaluate_walk_forward(
        dataset,
        min_train_rows=60,
        test_rows=30,
        step_rows=30,
    )

    metrics = report.to_dict()
    assert report.probabilities_calibrated is False
    assert len(report.folds) > 1
    assert set(report.folds[0].train_class_counts) == set(CLASS_LABELS)
    assert 0 <= report.folds[0].accuracy <= 1
    assert report.folds[0].log_loss >= 0
    assert metrics["fold_count"] == len(report.folds)


def test_dataset_rejects_gaps(candle_factory) -> None:
    candles = _oscillating(candle_factory, 40)
    candles[10] = candle_factory(11)
    with pytest.raises(ValueError, match="unique, increasing"):
        build_labeled_dataset(candles, horizon=1)
