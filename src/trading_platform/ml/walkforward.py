"""Expanding-window model evaluation with causal preprocessing."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from importlib import import_module
from math import log
from typing import Any

from trading_platform.ml.dataset import CLASS_LABELS, LabeledDataset, LabeledSample


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    index: int
    train: tuple[LabeledSample, ...]
    test: tuple[LabeledSample, ...]


@dataclass(frozen=True, slots=True)
class FoldMetrics:
    index: int
    train_rows: int
    test_rows: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_class_counts: dict[str, int]
    test_class_counts: dict[str, int]
    accuracy: float
    balanced_accuracy: float
    majority_class_accuracy: float
    log_loss: float
    brier_score: float


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    exchange: str
    market_type: str
    symbol: str
    timeframe: str
    horizon: int
    neutral_band_bps: float
    model: str
    preprocessing: str
    probabilities_calibrated: bool
    folds: tuple[FoldMetrics, ...]

    def to_dict(self) -> dict[str, object]:
        fold_records = [asdict(fold) for fold in self.folds]
        return {
            "exchange": self.exchange,
            "market_type": self.market_type,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "horizon": self.horizon,
            "neutral_band_bps": self.neutral_band_bps,
            "model": self.model,
            "preprocessing": self.preprocessing,
            "probabilities_calibrated": self.probabilities_calibrated,
            "fold_count": len(self.folds),
            "mean_accuracy": _mean(fold.accuracy for fold in self.folds),
            "mean_balanced_accuracy": _mean(fold.balanced_accuracy for fold in self.folds),
            "mean_majority_class_accuracy": _mean(
                fold.majority_class_accuracy for fold in self.folds
            ),
            "mean_log_loss": _mean(fold.log_loss for fold in self.folds),
            "mean_brier_score": _mean(fold.brier_score for fold in self.folds),
            "folds": fold_records,
        }


def make_walk_forward_folds(
    dataset: LabeledDataset,
    *,
    min_train_rows: int = 1_000,
    test_rows: int = 500,
    step_rows: int = 500,
) -> tuple[WalkForwardFold, ...]:
    """Create expanding train windows and separated, never-shuffled test windows."""
    if min_train_rows < 2 or test_rows < 1 or step_rows < 1:
        raise ValueError("min_train_rows must be >=2; test_rows and step_rows must be positive")
    samples = dataset.samples
    folds: list[WalkForwardFold] = []
    test_start = min_train_rows + dataset.horizon
    while test_start + test_rows <= len(samples):
        train_end = test_start - dataset.horizon
        train = samples[:train_end]
        test = samples[test_start : test_start + test_rows]
        if train and test:
            if train[-1].label_end_time >= test[0].feature_time:
                raise ValueError("Walk-forward training labels overlap the test period")
            folds.append(WalkForwardFold(index=len(folds) + 1, train=train, test=test))
        test_start += step_rows
    if not folds:
        minimum = min_train_rows + dataset.horizon + test_rows
        raise ValueError(
            f"Not enough labeled rows for a walk-forward fold; need at least {minimum}"
        )
    return tuple(folds)


def evaluate_walk_forward(
    dataset: LabeledDataset,
    *,
    min_train_rows: int = 1_000,
    test_rows: int = 500,
    step_rows: int = 500,
) -> WalkForwardReport:
    """Fit a scaled multinomial logistic baseline per fold and report OOS metrics.

    The scaler is inside the sklearn pipeline and is fit only on each fold's
    training window. No random shuffle or test-set preprocessing is performed.
    Probability outputs are reported as uncalibrated estimates.
    """
    pipeline_class, scaler_class, logistic_class = _sklearn_types()
    fold_metrics: list[FoldMetrics] = []
    for fold in make_walk_forward_folds(
        dataset,
        min_train_rows=min_train_rows,
        test_rows=test_rows,
        step_rows=step_rows,
    ):
        train_labels = [sample.label for sample in fold.train]
        class_counts = Counter(train_labels)
        if len(class_counts) < 2:
            raise ValueError(f"Fold {fold.index} training window contains fewer than two classes")
        model = pipeline_class(
            [
                ("scaler", scaler_class()),
                (
                    "classifier",
                    logistic_class(max_iter=1_000, class_weight="balanced", random_state=42),
                ),
            ]
        )
        model.fit(_matrix(fold.train), train_labels)
        predictions = model.predict(_matrix(fold.test))
        classifier = model.named_steps["classifier"]
        raw_probabilities = model.predict_proba(_matrix(fold.test))
        classes = list(classifier.classes_)
        probabilities = [
            [
                float(raw_probabilities[row][classes.index(label)]) if label in classes else 0.0
                for label in CLASS_LABELS
            ]
            for row in range(len(fold.test))
        ]
        actual = [sample.label for sample in fold.test]
        test_counts = Counter(actual)
        accuracy = sum(
            prediction == label for prediction, label in zip(predictions, actual, strict=True)
        ) / len(actual)
        recalls = [
            sum(
                prediction == label
                for prediction, actual_label in zip(predictions, actual, strict=True)
                if actual_label == label
            )
            / count
            for label, count in test_counts.items()
        ]
        majority_label = max(class_counts, key=lambda label: class_counts[label])
        majority_accuracy = sum(label == majority_label for label in actual) / len(actual)
        log_loss = -sum(
            log(max(probabilities[index][CLASS_LABELS.index(label)], 1e-15))
            for index, label in enumerate(actual)
        ) / len(actual)
        brier = sum(
            sum(
                (probability - (1.0 if label == class_label else 0.0)) ** 2
                for probability, class_label in zip(probabilities[index], CLASS_LABELS, strict=True)
            )
            for index, label in enumerate(actual)
        ) / len(actual)
        fold_metrics.append(
            FoldMetrics(
                index=fold.index,
                train_rows=len(fold.train),
                test_rows=len(fold.test),
                train_start=fold.train[0].feature_time.isoformat(),
                train_end=fold.train[-1].feature_time.isoformat(),
                test_start=fold.test[0].feature_time.isoformat(),
                test_end=fold.test[-1].feature_time.isoformat(),
                train_class_counts={label: class_counts.get(label, 0) for label in CLASS_LABELS},
                test_class_counts={label: test_counts.get(label, 0) for label in CLASS_LABELS},
                accuracy=accuracy,
                balanced_accuracy=sum(recalls) / len(recalls),
                majority_class_accuracy=majority_accuracy,
                log_loss=log_loss,
                brier_score=brier,
            )
        )
    return WalkForwardReport(
        exchange=dataset.exchange,
        market_type=dataset.market_type,
        symbol=dataset.symbol,
        timeframe=dataset.timeframe,
        horizon=dataset.horizon,
        neutral_band_bps=dataset.neutral_band_bps,
        model="StandardScaler + multinomial LogisticRegression(class_weight=balanced)",
        preprocessing="scaler fit inside each training fold only",
        probabilities_calibrated=False,
        folds=tuple(fold_metrics),
    )


def _sklearn_types() -> tuple[type[Any], type[Any], type[Any]]:
    try:
        logistic_regression = import_module("sklearn.linear_model").LogisticRegression
        pipeline = import_module("sklearn.pipeline").Pipeline
        standard_scaler = import_module("sklearn.preprocessing").StandardScaler
    except ImportError as exc:
        raise ValueError(
            "Walk-forward ML requires the optional dependency: uv sync --extra ml"
        ) from exc
    return pipeline, standard_scaler, logistic_regression


def _matrix(samples: tuple[LabeledSample, ...]) -> list[list[float]]:
    return [list(sample.features) for sample in samples]


def _mean(values: Iterable[float]) -> float | None:
    items = list(values)
    return sum(items) / len(items) if items else None


__all__ = [
    "FoldMetrics",
    "WalkForwardFold",
    "WalkForwardReport",
    "evaluate_walk_forward",
    "make_walk_forward_folds",
]
