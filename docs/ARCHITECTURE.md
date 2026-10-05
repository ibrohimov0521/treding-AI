# Arxitektura

## Hozirgi data oqimi

```text
Binance Spot public REST
          ↓
BinanceSpotMarketDataProvider
          ↓
HistoricalDownloader (pagination, faqat yopilgan candle)
          ↓
Raw Parquet (takror yozuvdan himoyalangan)
          ↓
DataQualityReport
          ↓
Resampling → processed Parquet (5m / 15m / 1h)
```

`MarketDataProvider` — birjadan mustaqil interfeys. Hozir faqat
`BinanceSpotMarketDataProvider` implementatsiyasi bor. Keyinchalik Bybit yoki OKX
provider qo‘shilganda candle modeli, storage, validator va resampler Binance javob
formatini bilishi shart bo‘lmaydi.

## Joriy modullar

| Modul | Vazifasi |
| --- | --- |
| `core/config.py` | YAML va environment sozlamalarini Pydantic bilan tekshirish |
| `domain/candle.py` | UTC va Decimal OHLCV maydonlariga ega umumiy candle |
| `market_data/base.py` | Umumiy async provider interfeysi |
| `market_data/binance_spot.py` | Faqat public Binance Spot GET va chegaralangan retry |
| `market_data/downloader.py` | Pagination, yopilmagan candle’larni chiqarish va raw yozuv |
| `storage/parquet.py` | Year/month partition, raw deduplication va processed data |
| `validation/candles.py` | Duplicate, gap, tartib, OHLCV, vaqt va corrupt qiymatlar |
| `market_data/resampling.py` | To‘liq UTC 1m guruhlaridan candle aggregation |
| `cli.py` | Developer buyruqlari; live execution buyrug‘i yo‘q |

## Parquet data modeli

Bitta qator bitta candle. Tabiiy identity kaliti:
`exchange + market_type + symbol + timeframe + open_time`. Narx va volume `Decimal`
orqali olinib Parquet’ning sonli ustunlarida yoziladi; vaqtlar UTC. Binance kline’dan
quote volume, trade count va taker-buy volume ham saqlanadi.

Raw data’da bir xil timestamp qayta kelsa, avvalgi qiymat saqlanadi va dublikat qator
qo‘shilmaydi. Yangi qator qo‘shishda shu oyning Parquet fayli atomic swap orqali qayta
yoziladi. Bu candle qiymatlarini immutable saqlaydi, lekin faylning baytlarini
append-only qilmaydi. Schema version va manba provenance’i keyingi bosqichdagi
technical debt hisoblanadi.

## Retry va pagination

Har bir klines so‘rovi ko‘pi bilan 1000 candle oladi. Keyingi `startTime` — oxirgi
candle `open_time` qiymatiga interval qo‘shilgan vaqt. Sahifa oldinga siljimasa,
takroriy so‘rovlar bo‘lmasligi uchun download to‘xtaydi. HTTP 429/418 javoblarida
`Retry-After` ko‘rsatkichi bajariladi; vaqtinchalik server yoki tarmoq xatosida retry
soni chegaralangan exponential backoff ishlaydi. Binance hujjatiga ko‘ra rate limit
oshirilganda 429, qayta-qayta cheklovni buzishda esa 418 qaytishi mumkin.

## Kelajakdagi komponentlar

Quyidagilar **TODO/FUTURE**, Phase 0–1’da kodlanmagan:

```text
Validated processed data
 → Feature Engine (TODO)
 → ML Model (TODO)
 → Strategy (TODO)
 → Risk Engine (TODO)
 → Paper Trading (TODO)
 → Execution Adapter (TODO; order yubormaydi)
```

Keyingi bosqichdan oldin uzoq muddatli yuklash bilan data completeness, schema
version, provenance va takrorlanadigan backfill oqimi tekshiriladi. Hozirgi loyiha
BUY/SELL signali bermaydi.

## Xavfsizlik qoidalari

1. Maxfiy kalitlarni o‘qiydigan sozlama yo‘q; public so‘rovga API key qo‘shilmaydi.
2. Phase 1 config’ida `live_trading: true` bo‘lsa, validatsiya uni rad etadi.
3. Client faqat market-data GET endpoint’larini chaqiradi; order endpoint yo‘q.
4. Kelajakda execution qo‘shilsa production muhiti, aniq ruxsat, risk engine approval
   va kill switch alohida tekshiriladi. Bitta config flag yetmaydi.
