"""Validated project and runtime settings."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.core.exceptions import ConfigurationError


class MarketConfig(BaseModel):
    """Market-specific settings kept outside the shared platform core."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exchange: str = Field(min_length=1)
    market_type: MarketType
    symbol: str = Field(min_length=1)
    base_asset: str = Field(min_length=1)
    quote_asset: str = Field(min_length=1)
    raw_timeframe: Timeframe = Timeframe.ONE_MINUTE
    derived_timeframes: tuple[Timeframe, ...] = (Timeframe.FIVE_MINUTES,)
    timezone: Literal["UTC"] = "UTC"
    live_trading: Literal[False] = False

    @field_validator("exchange", "symbol", "base_asset", "quote_asset")
    @classmethod
    def uppercase_identifiers(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("derived_timeframes", mode="before")
    @classmethod
    def parse_timeframes(cls, value: object) -> object:
        if isinstance(value, list):
            return tuple(Timeframe.parse(str(item)) for item in value)
        return value

    @model_validator(mode="after")
    def validate_phase_one_scope(self) -> "MarketConfig":
        if self.raw_timeframe != Timeframe.ONE_MINUTE:
            raise ValueError("Phase 1 uses canonical 1m raw candles")
        if any(item == self.raw_timeframe for item in self.derived_timeframes):
            raise ValueError("Derived timeframes must differ from raw_timeframe")
        return self


class Settings(BaseSettings):
    """Environment-backed runtime settings; no credential is needed for public data."""

    model_config = SettingsConfigDict(
        env_prefix="TRADING_PLATFORM_", env_file=".env", extra="ignore"
    )

    environment: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("data")
    live_trading: Literal[False] = False
    log_level: str = "INFO"


def load_market_config(path: Path) -> MarketConfig:
    """Load and validate a YAML market configuration."""
    try:
        with path.open("r", encoding="utf-8") as config_file:
            payload = yaml.safe_load(config_file)
        return MarketConfig.model_validate(payload)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        raise ConfigurationError(f"Could not load market config {path}: {exc}") from exc
