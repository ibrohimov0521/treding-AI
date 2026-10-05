# Trading Platform — Phase 0–1

> **WARNING: THIS PROJECT MUST NOT PLACE REAL ORDERS IN PHASE 0–8.**
> Phase 0–1 only downloads public Binance Spot market data. There is no order,
> account, balance, signed-request, leverage, futures, or live-execution module.
> `live_trading` is a validated literal `false`; setting it to `true` is rejected.

## Loyiha maqsadi

Bu loyiha BTC/USDT bilan boshlanadigan, lekin bitta coin yoki bitta birjaga qattiq
bog‘lanmagan quantitative research platform poydevoridir. Hozirgi scope ataylab
kichik: Binance Spot’dan **faqat public 1m candle** ma’lumotlarini olish, ularni
tekshirish va mahalliy Parquet fayllarda saqlash. 5m, 15m va 1h ma’lumotlar 1m
qatorlardan qayta hosil qilinadi.

Ma’lumot oqimi:

```text
Binance public API → MarketDataProvider → Raw Parquet → Data validation
                                                   ↓
                                            Processed Parquet
```

Feature engineering, model, strategiya, backtest va order bajarish keyingi
bosqichlar. Ular bu kodda yo‘q. Bosh maqsad — keyinchalik real kapitalga aloqador
qarorlar oldidan tekshirib bo‘ladigan va takrorlanuvchi ma’lumot poydevorini qurish.

## Arxitektura tamoyillari

- BTCUSDT market config’da turadi; domain va storage kodida BTCga xos branch yo‘q.
- Birja integratsiyasi `MarketDataProvider` interfeysi orqali ulanadi.
- Binance integratsiyasi `https://data-api.binance.vision` public hostiga faqat
  HTTP GET so‘rovlari yuboradi. API key yoki account credential kerak emas.
- Narx va hajmlar `Decimal` bilan parse qilinadi; vaqtlar ichkarida UTC bo‘ladi.
- Raw candle yozuvlari idempotent: `open_time` qayta kelganda takroriy qator
  qo‘shilmaydi; avval saqlangan candle qiymatlari o‘zgarmaydi.
- Oylik Parquet partition Zstandard bilan siqiladi. Derived data raw’dan alohida.
- Exchange-specific parsing faqat provider qatlamida; data model, validation va
  resampling providerdan mustaqil.

## Talablar va o‘rnatish

- Python 3.12 yoki undan yangisi
- [uv](https://docs.astral.sh/uv/)
- Public internetga chiqish (faqat Binance market data uchun)

```bash
uv sync --dev
cp .env.example .env  # ixtiyoriy; public data uchun credential kiritmang
uv run trading-platform info
uv run trading-platform health
```

`uv sync --dev` package, CLI, test, lint va type-check dependencies’larini o‘rnatadi
hamda platform-specific `uv.lock` lockfile yaratadi. `.env` ichidagi Binance key
maydonlari bo‘sh qoladi.

## Komandalar

Default market `configs/markets/btcusdt.yaml`; boshqa config yoki data katalogi uchun
`--config` va `--data-dir` ishlating.

### Birinchi yuklash

Boshlanish kuni intervalga kiradi. Faqat sana shaklidagi `--end` o‘sha kunning
hamma candle’larini qamrash uchun inclusive; vaqt ko‘rsatilsa, tugash nuqtasi exclusive.

```bash
uv run trading-platform download --interval 1m --start 2024-01-01 --end 2024-01-03
```

Symbol ko‘rsatilmasa config’dagi BTCUSDT ishlatiladi. Masalan, ETHUSDT uchun
`--symbol ETHUSDT` bering. Yangi market’ni doimiy ishlatishdan oldin unga alohida
YAML config yarating.

### Incremental yuklash

Birinchi yuklashdan keyin `--start` bermasdan ishga tushirish eng oxirgi saqlangan
candle’dan keyingi daqiqadan davom etadi. Hali yopilmagan joriy candle saqlanmaydi.

```bash
uv run trading-platform download --interval 1m
```

Incremental rejim avvalgi ma’lumot ichidagi gaplarni avtomatik to‘ldirmaydi;
validator ularni ko‘rsatadi. Gapni to‘ldirish uchun eski vaqt oralig‘ini `--start`
va `--end` bilan backfill qiling.

### Tekshirish, timeframe hosil qilish va test

```bash
uv run trading-platform validate --symbol BTCUSDT --interval 1m
uv run trading-platform resample --symbol BTCUSDT --from 1m --to 5m
uv run trading-platform resample --symbol BTCUSDT --from 1m --to 15m
uv run trading-platform resample --symbol BTCUSDT --from 1m --to 1h
uv run pytest
uv run ruff check .
uv run mypy
```

Resampling faqat har bir 1m candle to'liq mavjud bo'lgan UTC bucket’ni saqlaydi. Gap
yoki dataset chegarasidagi chala bucket tashlab ketiladi va soni ko'rsatiladi. Data-quality
report: `data/reports/binance/spot/<SYMBOL>/<TIMEFRAME>/quality.json`.

### Integratsion test (ixtiyoriy)

Bu test Binance public API’ga faqat bir read-only so'rov yuboradi; account key kerak emas.

```bash
RUN_BINANCE_INTEGRATION=1 uv run pytest -m integration
```

## Parquet joylashuvi

```text
data/
├── raw/binance/spot/BTCUSDT/1m/year=2024/month=01/candles.parquet
├── processed/binance/spot/BTCUSDT/5m/year=2024/month=01/candles.parquet
└── reports/binance/spot/BTCUSDT/1m/quality.json
```

Raw path exchange, market type, symbol, timeframe, year va month bo'yicha ajralgan.
Oldingi `open_time` qiymatlari saqlanadi, takroriy timestamp yangi satr bo'lmaydi.
Yangi satr oylik partition’ga qo'shilganda Parquet fayli atomic usulda qayta yoziladi;
demak, bu byte-level immutable fayl emas, existing candle qiymatlarini saqlovchi raw data.

## Sifat hisoboti misoli

```json
{
  "symbol": "BTCUSDT",
  "timeframe": "1m",
  "rows": 100000,
  "duplicates": 0,
  "missing_candles": 3,
  "missing_open_times": ["2024-05-02T10:01:00+00:00"],
  "invalid_ohlc": 0,
  "status": "WARNING"
}
```

To'liq hisobot out-of-order, manfiy volume, imkonsiz timestamp, null va corrupt row’larni
ham ko'rsatadi. Gap/duplicate — `WARNING`; candle logikasi yoki malumot xatosi — `FAIL`.
Missing candle’lar mavjuddek to'ldirilmaydi.

## Quant xatolari haqida

- **Look-ahead bias:** o'sha vaqtda hali malum bo'lmagan kelajak narxi feature yoki
  backtest’ga kirmasin. Candle yopilmasdan turib uni qarorda ishlatish mumkin emas.
- **Data leakage:** train/test vaqtini ajrating; scaler va feature parametrlarini butun
  dataset’da fit qilmang.
- **Survivorship bias:** ko'p asset’ga o'tganda faqat hozirda bor coin’larni tanlash va
  delisting bo'lganlarni tashlab ketish tarixiy natijani asossiz yaxshilaydi.
- **Overfitting:** ortiqcha parameter search tarixiy bozorni yodlatib qo'yadi; walk-forward
  validation va avval ko'rilmagan test davrini ishlating.
- **Transaction cost:** kelajak backtest’lari commission, spread va slippage’ni hisoblasin.
  Fee’siz natija amaliy foydaning isboti emas.

## Xavfsizlik

`.env` git’ga qo'shilmaydi; `.env.example`’da key qiymatlari bo'sh. Kod Binance account
yoki order endpoint’lariga murojaat qilmaydi. Keyin execution qo'shilsa, faqat
`LIVE_TRADING=false` etarli himoya bo'lmaydi: production muhiti, explicit permission,
risk engine ruxsati, miqdor limiti va kill switch kabi bir necha mustaqil nazorat
kerak. Roadmap’dagi Phase 0–8 davomida haqiqiy order yuborilmaydi.

## Binance API manbasi

- [Binance Spot REST API — public market-data host va rate limits](https://developers.binance.com/en/docs/products/spot/rest-api)
