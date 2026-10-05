"""Canonical candle domain model."""

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator

from trading_platform.core.enums import MarketType, Timeframe


class Candle(BaseModel):
    """A UTC, timezone-aware OHLCV candle using Decimal for market values."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange: str
    market_type: MarketType
    symbol: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    quote_volume: Decimal = Decimal("0")
    number_of_trades: int = 0
    taker_buy_base_volume: Decimal = Decimal("0")
    taker_buy_quote_volume: Decimal = Decimal("0")

    @field_validator("open_time", "close_time")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Candle timestamps must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator(
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base_volume",
        "taker_buy_quote_volume",
        mode="before",
    )
    @classmethod
    def preserve_decimal_precision(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError(f"Expected a decimal value; received {value!r}") from exc
