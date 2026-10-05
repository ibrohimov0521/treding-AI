from datetime import UTC, datetime

import httpx
import pytest

from trading_platform.core.enums import Timeframe
from trading_platform.market_data.binance_spot import BinanceSpotMarketDataProvider


@pytest.mark.asyncio
async def test_binance_provider_uses_unsigned_public_get(candle_factory) -> None:
    requested = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json=[
                [
                    1704067200000,
                    "10.0",
                    "12.0",
                    "9.0",
                    "11.0",
                    "2.5",
                    1704067259999,
                    "25.0",
                    3,
                    "1.0",
                    "10.0",
                    "0",
                ]
            ],
        )

    client = httpx.AsyncClient(
        base_url="https://data-api.binance.vision", transport=httpx.MockTransport(handler)
    )
    provider = BinanceSpotMarketDataProvider(client=client)
    candles = await provider.get_klines(
        "BTCUSDT", Timeframe.ONE_MINUTE, datetime(2024, 1, 1, tzinfo=UTC), limit=1
    )
    await client.aclose()
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].open_time == datetime(2024, 1, 1, tzinfo=UTC)
    assert requested[0].method == "GET"
    assert requested[0].url.path == "/api/v3/klines"
    assert "X-MBX-APIKEY" not in requested[0].headers


@pytest.mark.asyncio
async def test_provider_honors_retry_after_on_rate_limit(monkeypatch) -> None:
    import trading_platform.market_data.binance_spot as binance_module

    calls = 0
    delays = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={})

    async def no_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(binance_module.asyncio, "sleep", no_sleep)
    client = httpx.AsyncClient(
        base_url="https://data-api.binance.vision", transport=httpx.MockTransport(handler)
    )
    provider = BinanceSpotMarketDataProvider(client=client)
    assert await provider.health_check() is True
    await client.aclose()
    assert calls == 2
    assert delays == [0.0]


@pytest.mark.asyncio
async def test_exchange_info_is_parsed_without_credentials() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "X-MBX-APIKEY" not in request.headers
        return httpx.Response(
            200,
            json={
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "status": "TRADING",
                        "quotePrecision": 8,
                        "isSpotTradingAllowed": True,
                    }
                ]
            },
        )

    client = httpx.AsyncClient(
        base_url="https://data-api.binance.vision", transport=httpx.MockTransport(handler)
    )
    provider = BinanceSpotMarketDataProvider(client=client)
    markets = await provider.get_exchange_info()
    await client.aclose()
    assert markets[0].identity.symbol == "BTCUSDT"
    assert markets[0].identity.base_asset == "BTC"
    assert markets[0].status == "TRADING"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_binance_public_api_sample() -> None:
    import os

    if os.getenv("RUN_BINANCE_INTEGRATION") != "1":
        pytest.skip("Set RUN_BINANCE_INTEGRATION=1 to make a read-only public API request")
    async with BinanceSpotMarketDataProvider() as provider:
        assert await provider.health_check()
        candles = await provider.get_klines(
            "BTCUSDT",
            Timeframe.ONE_MINUTE,
            datetime(2024, 1, 1, tzinfo=UTC),
            limit=1,
        )
        assert len(candles) == 1
