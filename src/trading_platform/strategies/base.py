"""Shared strategy contract."""

from decimal import Decimal
from typing import Protocol

from trading_platform.features.engineering import FeatureRow


class TargetExposureStrategy(Protocol):
    """A strategy may request a long-only target weight after a candle closes.

    Returning ``None`` means warm-up/no decision. A weight of zero means flat;
    one means fully invested. This interface cannot submit exchange orders.
    """

    @property
    def name(self) -> str: ...

    def target_exposure(self, features: FeatureRow) -> Decimal | None: ...
