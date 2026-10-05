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
Causal features → EMA-12/26 strategy → SignalEngine → RiskEngine
                                             ↓
                              Backtest / virtual PaperTrader
                                             ↓
                              Hash-chained paper audit log
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
| `signals/engine.py` | Backtest va paper uchun umumiy signal, takrorlanuvchi ID va feature hash |
| `risk/engine.py` | Spot exposure cap, kunlik zarar va drawdown halt |
| `backtesting/engine.py` | Spot long-only simulator, umumiy risk oqimi, next-open fills va cost |
| `paper/engine.py` | Virtual Spot balans, checkpoint va yopilgan candle’larni qayta ishlash |
| `observability/audit.py` | Ketma-ketlik va SHA-256 hash zanjirini tekshiradigan JSONL audit |
| `cli.py` | Data, backtest, paper va `audit-verify` buyruqlari; live execution yo‘q |

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

## Signal, risk va audit oqimi

`SignalEngine` strategiya targetini hisoblaydi va har candle’da `RiskEngine`dan
mustaqil qaror oladi. Backtest va paper bir xil risk qoidasini ishlatadi: Spot exposure
0–1 oralig‘ida qoladi; daily loss yoki peak drawdown limitiga yetganda halt latched
bo‘lib target nol qilinadi. Qarorda feature hash, signal ID, so‘ralgan va tasdiqlangan
target hamda risk holati saqlanadi.

Paper CLI har bir checkpoint yangilanishiga audit event yozadi. Eventlar JSONL’da
ketma-ket raqam va oldingi event hash’i bilan bog‘lanadi; `audit-verify` yozuvlar
ketma-ketligi va hash’larini qayta hisoblaydi. Bu zanjir o‘rtadagi o‘zgarish va chala
oxirgi yozuvni aniqlaydi. U imzo emas; serverdagi faylni to‘liq almashtira oladigan
shaxsdan himoya qilmaydi. Hozir audit va checkpoint alohida faylga yoziladi, shu bois
process yoki disk xatosi atrofidagi tiklanish Phase 6’da yanada mustahkamlanishi kerak.

## Kelajakdagi komponentlar

Quyidagilar **TODO/FUTURE**:

```text
EDA hisoboti, untouched holdout va model kalibratsiyasi
 → Paper virtual order lifecycle, partial-fill simulyatsiyasi va reconciliation
 → Dashboard, monitoring ogohlantirishlari va order yubormaydigan shadow rejimi
 → Yetarli paper dalilidan keyin gate review
 → Faqat alohida ruxsatdan keyin authenticated execution (hozir mavjud emas)
```

Hozirgi EMA benchmark long/flat target exposure chiqaradi; signal candle yopilgach
hisoblanadi, simulyatsion fill esa keyingi candle ochilishida qo‘llanadi. Paper engine
public yopilgan candle’larni virtual hisobga qo‘llaydi va holatni atomik checkpoint’da
saqlaydi. Binance’ga order yuborilmaydi.

## Xavfsizlik qoidalari

1. Maxfiy kalitlarni o‘qiydigan sozlama yo‘q; public so‘rovga API key qo‘shilmaydi.
2. `live_trading: true` bo‘lsa, config validatsiyasi uni rad etadi.
3. Exchange client faqat public market-data GET endpoint’larini chaqiradi; order endpoint yo‘q.
4. Kelajakda execution qo‘shilsa production muhiti, aniq ruxsat, risk engine approval
   va kill switch alohida tekshiriladi. Bitta config flag yetmaydi.
