"""Binance Spot implementation that only calls public, read-only endpoints."""

import asyncio
from datetime import UTC, datetime
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
DEFAULT_BASE_URL = "https://data-api.binance.vision"
MAX_ATTEMPTS = 5
MAX_KLINE_PAGE_SIZE = 1000


class BinanceSpotMarketDataProvider:
    """Read public Binance Spot data; this class contains no account/order API."""

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

    async def __aenter__(self) -> "BinanceSpotMarketDataProvider":
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_json(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        """GET JSON with bounded retries and exchange-provided Retry-After handling."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                response = await self._client.get(path, params=params)
                if response.status_code in {418, 429} or response.status_code >= 500:
                    if attempt + 1 >= MAX_ATTEMPTS:
                        response.raise_for_status()
                    retry_after = response.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else min(2**attempt, 30)
                    logger.warning(
                        "binance_public_request_retry",
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
                    raise MarketDataError(f"Binance public API connection failed: {exc}") from exc
                delay = min(2**attempt, 30)
                logger.warning(
                    "binance_transport_retry", path=path, attempt=attempt + 1, delay_seconds=delay
                )
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError as exc:
                raise MarketDataError(
                    f"Binance public API returned HTTP {exc.response.status_code} for {path}: "
                    f"{exc.response.text[:300]}"
                ) from exc
            except ValueError as exc:
                raise MarketDataError(f"Binance returned invalid JSON for {path}") from exc
        raise MarketDataError(f"Binance request failed after {MAX_ATTEMPTS} attempts: {path}")

    async def get_exchange_info(self) -> list[Market]:
        """Fetch public Spot exchange metadata without account credentials."""
        payload = await self._get_json("/api/v3/exchangeInfo")
        markets: list[Market] = []
        for item in payload.get("symbols", []):
            if item.get("isSpotTradingAllowed") is False:
                continue
            identity = Symbol(
                exchange="BINANCE",
                market_type=MarketType.SPOT,
                symbol=item["symbol"],
                base_asset=item["baseAsset"],
                quote_asset=item["quoteAsset"],
            )
            markets.append(
                Market(
                    identity=identity,
                    status=str(item.get("status", "UNKNOWN")),
                    quote_precision=item.get("quotePrecision"),
                )
            )
        return markets

    async def get_klines(
        self,
        symbol: str,
        interval: Timeframe,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = MAX_KLINE_PAGE_SIZE,
    ) -> list[Candle]:
        """Fetch and decode a single public kline page."""
        if not 1 <= limit <= MAX_KLINE_PAGE_SIZE:
            raise ValueError(f"Binance kline limit must be between 1 and {MAX_KLINE_PAGE_SIZE}")
        params: dict[str, str | int] = {
            "symbol": symbol.upper(),
            "interval": interval.value,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = _to_epoch_ms(start_time)
        if end_time is not None:
            params["endTime"] = _to_epoch_ms(end_time)
        payload = await self._get_json("/api/v3/klines", params)
        return [self._parse_kline(row, symbol.upper(), interval) for row in payload]

    async def health_check(self) -> bool:
        """Call the unsigned Spot ping endpoint."""
        await self._get_json("/api/v3/ping")
        return True

    @staticmethod
    def _parse_kline(row: list[Any], symbol: str, interval: Timeframe) -> Candle:
        try:
            return Candle(
                exchange="BINANCE",
                market_type=MarketType.SPOT,
                symbol=symbol,
                timeframe=interval,
                open_time=_from_epoch_ms(int(row[0])),
                open=Decimal(str(row[1])),
                high=Decimal(str(row[2])),
                low=Decimal(str(row[3])),
                close=Decimal(str(row[4])),
                volume=Decimal(str(row[5])),
                close_time=_from_epoch_ms(int(row[6])),
                quote_volume=Decimal(str(row[7])),
                number_of_trades=int(row[8]),
                taker_buy_base_volume=Decimal(str(row[9])),
                taker_buy_quote_volume=Decimal(str(row[10])),
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise MarketDataError(f"Binance returned a malformed kline row: {row!r}") from exc


def _to_epoch_ms(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Binance timestamp parameters must be timezone-aware")
    return int(value.astimezone(UTC).timestamp() * 1000)


def _from_epoch_ms(value: int) -> datetime:
    return datetime.fromtimestamp(value / 1000, tz=UTC)
