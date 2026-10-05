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
          ↓
Causal features → EMA-12/26 target exposure → Backtest simulator
                                          (next-candle-open fills; no orders)
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
| `features/engineering.py` | Causal returns, EMA, RSI, ATR, volatility va volume feature’lari |
| `strategies/moving_average.py` | EMA-12/26 long/flat benchmark signali |
| `backtesting/engine.py` | Spot long-only simulator, next-open fills, fee/spread/slippage |
| `cli.py` | Data, validation, features va backtest buyruqlari; live execution yo‘q |

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

Feature Parquet har bir candle uchun bitta qator saqlaydi. Warm-up davridagi
indicator qiymatlari `null`; `ready` EMA-12/26, RSI-14, ATR-14, 20-return
volatility va 20-candle relative-volume mavjudligini bildiradi. Feature’lar faqat
shu qatorgacha yopilgan candle’lardan olinadi.

## Retry va pagination

Har bir klines so‘rovi ko‘pi bilan 1000 candle oladi. Keyingi `startTime` — oxirgi
candle `open_time` qiymatiga interval qo‘shilgan vaqt. Sahifa oldinga siljimasa,
takroriy so‘rovlar bo‘lmasligi uchun download to‘xtaydi. HTTP 429/418 javoblarida
`Retry-After` ko‘rsatkichi bajariladi; vaqtinchalik server yoki tarmoq xatosida retry
soni chegaralangan exponential backoff ishlaydi. Binance hujjatiga ko‘ra rate limit
oshirilganda 429, qayta-qayta cheklovni buzishda esa 418 qaytishi mumkin.

## Kelajakdagi komponentlar

Quyidagilar **TODO/FUTURE**, Phase 0–9’da hali kodlanmagan:

```text
Validated processed data
 → Label/dataset va vaqt bo‘yicha split (tayyor)
 → LogisticRegression baseline va purged walk-forward (tayyor; optional ML extra)
 → Paper-trading engine va restartable checkpoint (tayyor; virtual pozitsiya)
 → Risk engine (tayyor; exposure, daily loss, drawdown)
 → Authenticated execution adapter (TODO; alohida ruxsat va gate talab qiladi)
```

Hozirgi EMA benchmark long/flat target exposure chiqaradi; simulator signalni candle
yopilgach oladi va keyingi candle ochilishida taxminiy fill qiladi. Paper engine
public yopilgan candle’larni virtual hisobga qo‘llaydi, holatni atomik checkpoint’da
saqlaydi va risk limitida targetni nolga tushiradi. Binance’ga order yuborilmaydi.

## Xavfsizlik qoidalari

1. Maxfiy kalitlarni o‘qiydigan sozlama yo‘q; public so‘rovga API key qo‘shilmaydi.
2. `live_trading: true` bo‘lsa, config validatsiyasi uni rad etadi.
3. Exchange client faqat public market-data GET endpoint’larini chaqiradi; order endpoint yo‘q.
4. Kelajakda execution qo‘shilsa production muhiti, aniq ruxsat, risk engine approval
   va kill switch alohida tekshiriladi. Bitta config flag yetmaydi.
