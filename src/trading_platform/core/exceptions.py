"""Application-level exceptions with actionable error messages."""


class TradingPlatformError(Exception):
    """Base exception for expected platform errors."""


class MarketDataError(TradingPlatformError):
    """A public market-data request failed or returned invalid content."""


class StorageError(TradingPlatformError):
    """Historical market data could not be read or written."""


class ConfigurationError(TradingPlatformError):
    """The market or runtime configuration is invalid."""
