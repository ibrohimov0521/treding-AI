"""Bitstamp public Spot market data using unsigned read-only endpoints."""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import structlog

from trading_platform.core.enums import MarketType, Timeframe
from trading_platform.core.exceptions import MarketDataError
from trading_platform.domain.candle import Candle
from trading_platform.domain.market import Market
from trading_platform.domain.symbol import Symbol

logger = structlog.get_logger(__name__)
DEFAULT_BASE_URL = "https://www.bitstamp.net"
MAX_ATTEMPTS = 5
MAX_OHLC_PAGE_SIZE = 1000


class BitstampSpotMarketDataProvider:
    """Fetch Bitstamp Spot metadata, OHLC, and health data without credentials."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": "trading-platform/0.1.0 public-market-data"},
        )

    async def __aenter__(self) -> "BitstampSpotMarketDataProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await self._client.get(path, params=params)
                if response.status_code in {418, 429} or response.status_code >= 500:
                    if attempt + 1 >= MAX_ATTEMPTS:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else min(2**attempt, 30)
                    logger.warning(
                        "bitstamp_public_request_retry",
                        path=path,
                        status=response.status_code,
                        attempt=attempt + 1,
                        delay_seconds=delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.TransportError as exc:
                if attempt + 1 >= MAX_ATTEMPTS:
                    raise MarketDataError(f"Bitstamp public API connection failed: {exc}") from exc
                delay = min(2**attempt, 30)
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                raise MarketDataError(
                    f"Bitstamp public API returned HTTP {exc.response.status_code} for {path}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except ValueError as exc:
                raise MarketDataError(f"Bitstamp returned invalid JSON for {path}") from exc
        raise MarketDataError(f"Bitstamp request failed after {MAX_ATTEMPTS} attempts: {path}")

    async def get_exchange_info(self) -> list[Market]:
        payload = await self._get_json("/api/v2/trading-pairs-info/")
        markets: list[Market] = []
        for item in payload:
            if str(item.get("market_type", "SPOT")).upper() != "SPOT":
                continue
            identity = Symbol(
                exchange="BITSTAMP",
                market_type=MarketType.SPOT,
                symbol=str(item["market_symbol"]).upper(),
                base_asset=str(item["base_currency"]).upper(),
                quote_asset=str(item["counter_currency"]).upper(),
            )
            markets.append(
                Market(
                    identity=identity,
                    status=str(item.get("trading", "UNKNOWN")).upper(),
                    quote_precision=item.get("counter_decimals"),
                )
            )
        return markets

    async def get_klines(
        self,
        symbol: str,
        interval: Timeframe,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = MAX_OHLC_PAGE_SIZE,
    ) -> list[Candle]:
        if not 1 <= limit <= MAX_OHLC_PAGE_SIZE:
            raise ValueError(f"Bitstamp OHLC limit must be between 1 and {MAX_OHLC_PAGE_SIZE}")
        params: dict[str, str | int] = {
            "step": int(interval.duration.total_seconds()),
            "limit": limit,
            "exclude_current_candle": "true",
        }
        if start_time is not None:
            params["start"] = _to_epoch_seconds(start_time)
        if end_time is not None:
            params["end"] = _to_epoch_seconds(end_time)
        payload = await self._get_json(f"/api/v2/ohlc/{_market_symbol(symbol)}/", params)
        rows = payload.get("data", {}).get("ohlc", [])
        candles = [self._parse_ohlc(row, symbol.upper(), interval) for row in rows]
        start = _utc(start_time) if start_time is not None else None
        end = _utc(end_time) if end_time is not None else None
        return [
            candle
            for candle in candles
            if (start is None or candle.open_time >= start)
            and (end is None or candle.open_time < end)
        ]

    async def health_check(self) -> bool:
        await self._get_json("/api/v2/ticker/btcusd/")
        return True

    @staticmethod
    def _parse_ohlc(row: dict[str, Any], symbol: str, interval: Timeframe) -> Candle:
        try:
            open_time = datetime.fromtimestamp(int(row["timestamp"]), tz=UTC)
            return Candle(
                exchange="BITSTAMP",
                market_type=MarketType.SPOT,
                symbol=symbol,
                timeframe=interval,
                open_time=open_time,
                close_time=open_time + interval.duration - timedelta(milliseconds=1),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(f"Bitstamp returned a malformed OHLC row: {row!r}") from exc


def _market_symbol(symbol: str) -> str:
    return symbol.replace("/", "").replace("-", "").lower()


def _to_epoch_seconds(value: datetime) -> int:
    return int(_utc(value).timestamp())


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Bitstamp timestamp parameters must be timezone-aware")
    return value.astimezone(UTC)
