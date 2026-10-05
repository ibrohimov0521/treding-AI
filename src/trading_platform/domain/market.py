"""Resolved market metadata."""

from dataclasses import dataclass

from trading_platform.domain.symbol import Symbol


@dataclass(frozen=True, slots=True)
class Market:
    """Market identity and tradability reported by a market-data provider."""

    identity: Symbol
    status: str
    quote_precision: int | None = None
