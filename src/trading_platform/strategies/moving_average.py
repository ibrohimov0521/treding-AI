"""Simple explainable long/flat benchmark strategy."""

from decimal import Decimal

from trading_platform.features.engineering import FeatureRow


class MovingAverageCrossover:
    """Hold spot exposure when EMA-12 is above EMA-26; otherwise remain flat.

    Signals are evaluated only after the feature candle closes. The backtest
    engine executes them no earlier than the following candle's open.
    """

    @property
    def name(self) -> str:
        return "ema_12_26_long_flat"

    def target_exposure(self, features: FeatureRow) -> Decimal | None:
        if features.ema_12 is None or features.ema_26 is None:
            return None
        if features.ema_12 > features.ema_26:
            return Decimal("1")
        return Decimal("0")
