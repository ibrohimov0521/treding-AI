"""Market and symbol identifiers."""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from trading_platform.core.enums import MarketType


class Symbol(BaseModel):
    """A trading pair with its exchange-independent identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange: str = Field(min_length=1)
    market_type: MarketType
    symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)

    @field_validator("exchange", "symbol", "base_asset", "quote_asset")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().upper()
