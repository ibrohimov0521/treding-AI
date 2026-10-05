"""Factory for public spot data providers supported by the platform."""

from typing import Protocol

from trading_platform.core.exceptions import ConfigurationError
from trading_platform.market_data.base import MarketDataProvider
from trading_platform.market_data.binance_spot import BinanceSpotMarketDataProvider
from trading_platform.market_data.bitstamp_spot import BitstampSpotMarketDataProvider


class ManagedPublicMarketDataProvider(MarketDataProvider, Protocol):
    """A provider that can be safely used as an async context manager."""

    async def __aenter__(self) -> "ManagedPublicMarketDataProvider": ...

    async def __aexit__(self, *_: object) -> None: ...


def public_market_data_provider(exchange: str) -> ManagedPublicMarketDataProvider:
    """Create a read-only public provider for one configured Spot venue."""
    normalized = exchange.strip().upper()
    if normalized == "BINANCE":
        return BinanceSpotMarketDataProvider()
    if normalized == "BITSTAMP":
        return BitstampSpotMarketDataProvider()
    raise ConfigurationError(f"No public market-data provider is configured for {normalized!r}")
