"""Shared market enums and timeframe parsing."""

from datetime import timedelta
from enum import StrEnum


class MarketType(StrEnum):
    SPOT = "spot"


class Timeframe(StrEnum):
    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"

    @property
    def duration(self) -> timedelta:
        """Return the duration represented by this interval."""
        return {
            Timeframe.ONE_MINUTE: timedelta(minutes=1),
            Timeframe.FIVE_MINUTES: timedelta(minutes=5),
            Timeframe.FIFTEEN_MINUTES: timedelta(minutes=15),
            Timeframe.ONE_HOUR: timedelta(hours=1),
        }[self]

    @property
    def milliseconds(self) -> int:
        return int(self.duration.total_seconds() * 1000)

    @classmethod
    def parse(cls, value: str) -> "Timeframe":
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(f"Unsupported timeframe {value!r}; choose one of: {allowed}") from exc
