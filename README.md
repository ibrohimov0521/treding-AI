# Trading Platform — research va paper bosqichlari

> **Safety: this project does not send real orders.** The implementation downloads
> public Binance Spot data, builds causal features and ML research datasets, runs
> walk-forward evaluation, and can update a restartable virtual Spot portfolio.
> It has no authenticated account, signed-request, leverage, futures, or
> live-execution module. `live_trading` is a validated literal `false`; setting it
> to `true` is rejected.

## Loyiha maqsadi

Bu loyiha BTC/USDT bilan boshlanadigan, lekin bitta coin yoki birjaga qattiq
bog‘lanmagan quantitative research platformadir. Hozir Binance Spot public
ma’lumotlarini yuklaydi, tekshiradi va Parquet’da saqlaydi; yopilgan candle’lardan
feature’lar hisoblaydi; EMA benchmarkni keyingi candle ochilishida simulyatsion fill
bilan tarixiy tekshiradi. Forward-return dataset, purged walk-forward LogisticRegression
baseline va virtual Spot paper portfolio mavjud. Raw 1m ma’lumotdan 5m, 15m va 1h
qatorlar hosil qilinadi. ML ehtimollari kalibrlanmagan; ular real order yoki
tasdiqlangan edge emas.

Ma’lumot oqimi:

```text
Binance public API → MarketDataProvider → Raw Parquet → Validation
                                              ↓
                                     Resample → Processed Parquet
                                              ↓
                                    Causal features → EMA / ML research
                                              ↓
                            Backtest → Paper portfolio → Risk halt
                                              ↓
                                 No authenticated orders
```

EMA strategiyasi foyda va’da qilmaydigan, taqqoslash uchun mo‘ljallangan benchmarkdir.
Backtest natijasi faqat tanlangan tarixiy oraliq va cost taxminlarini ifodalaydi; u
live natija yoki statistik edge isboti emas.

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
- Feature’lar faqat joriy va oldingi yopilgan candle’lardan tuziladi; indikator
  warm-up davri `ready=false` sifatida belgilanadi.
- Backtest signalni candle yopilgach oladi va eng erta keyingi candle ochilishida
  simulyatsiya qiladi; fee, spread va slippage alohida hisoblanadi.

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
maydonlari bo‘sh qoladi. Walk-forward ML uchun optional dependency’ni qo‘shing:

```bash
uv sync --dev --extra ml
```

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
uv run trading-platform features --symbol BTCUSDT --interval 1m
uv run trading-platform backtest --symbol BTCUSDT --interval 1m \
  --start 2024-01-01 --end 2024-02-01 --fee-bps 10 --spread-bps 2 --slippage-bps 5
uv run trading-platform build-dataset --symbol BTCUSDT --interval 1m --horizon 5
uv run trading-platform walk-forward --symbol BTCUSDT --interval 1m \
  --horizon 5 --min-train-rows 1000 --test-rows 500
uv run trading-platform paper --symbol BTCUSDT --interval 1m
uv run trading-platform paper --symbol BTCUSDT --interval 1m --follow
uv run trading-platform audit-verify data/audit/binance/spot/BTCUSDT/1m/events.jsonl
uv run pytest
uv run ruff check .
uv run mypy
```

Resampling faqat har bir 1m candle to'liq mavjud bo'lgan UTC bucket’ni saqlaydi. Gap
yoki dataset chegarasidagi chala bucket tashlab ketiladi va soni ko'rsatiladi. Data-quality
report: `data/reports/binance/spot/<SYMBOL>/<TIMEFRAME>/quality.json`.
Derived timeframe’lar `processed` data’dan tekshiriladi.

### Feature engineering va backtest

`features` buyruği `return_1/5/15`, EMA-12/26, RSI-14, ATR-14, 20 candle’lik
volatility va relative volume, volume change, candle range va taker-buy ratio’ni
hisoblaydi. Har bir qatorning vaqti candle yopilgan paytga tegishli. Warm-up
qiymatlari `null`; ular nolga almashtirilmaydi.

`backtest` hozircha EMA-12/26 long/flat benchmarkini ishlatadi. Strategiya signalni
close’dan keyin chiqaradi, fill esa keyingi candle’ning open narxida, sozlangan
half-spread va slippage bilan simulyatsiya qilinadi. Spot modeli short pozitsiyaga
ruxsat bermaydi; uzilgan timeframe qatori aniqlansa test to‘xtaydi. Fee, spread yoki
slippage’ni nol qilish mumkin, lekin bunday natijani realistik deb talqin qilmang.

`build-dataset` yopilgan candle feature’laridan kelajak return label’larini alohida
datasetga yozadi. `walk-forward` vaqt tartibini saqlagan purged train/test fold’lar
bilan baseline modelni tekshiradi; bu buyruq uchun `uv sync --dev --extra ml`
kerak. `paper` faqat public candle’larni yuklaydi, keyingi candle open’da virtual
fill simulyatsiya qiladi va holatni checkpoint’ga yozadi. `--follow` jarayonni
terminalda uzluksiz ishlatadi. Backtest va paper bir xil signal/risk qatlamidan
foydalanadi; har bir qaror uchun takrorlanuvchi signal ID va feature hash yaratiladi.
Risk limiti yetganda virtual target nolga tushadi va mavjud virtual pozitsiya keyingi
candle’da yopiladi. Paper hisob real birja balansiga ulanmaydi va order yubormaydi.

Paper yangilanishlari `data/audit/<exchange>/<market>/<symbol>/<timeframe>/events.jsonl`
fayliga SHA-256 hash chain bilan yoziladi. Auditni `audit-verify` tekshiradi; zanjir
log o‘rtasidagi o‘zgarishlarni aniqlaydi, lekin imzolangan tashqi backup o‘rnini
bosmaydi. `docs/ROADMAP.md` bajarilgan, qisman tayyor va hali bloklangan bosqichlarni
ajratadi. Shadow, paper gate va real execution tayyor deb hisoblanmaydi.

```bash
uv run trading-platform resample --from 1m --to 5m
uv run trading-platform features --interval 5m
uv run trading-platform backtest --interval 5m --starting-cash 10000
```

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
├── features/binance/spot/BTCUSDT/1m/features.parquet
├── audit/binance/spot/BTCUSDT/1m/events.jsonl
└── reports/binance/spot/BTCUSDT/1m/quality.json
```

Backtest summary va equity curve `data/reports/backtest/<exchange>/<market>/<symbol>/<timeframe>/`
ichida JSON va Parquet fayllarda saqlanadi.

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
- **Transaction cost:** backtest commission, spread va slippage’ni hisoblaydi. Doimiy
  bps taxminlari order-book impact va real fee tier’ni to‘liq modellashtirmaydi.
  Fee’siz yoki qisqa davrli natija edge isboti emas.

## Xavfsizlik

`.env` git’ga qo‘shilmaydi; `.env.example`’da credential qiymatlari bo‘sh. Kod Binance
account yoki order endpoint’lariga murojaat qilmaydi. Keyingi bosqichlarda execution
qo‘shish alohida xavfsizlik va ruxsat ko‘rigini talab qiladi; bitta `LIVE_TRADING=false`
flag yetarli himoya bo‘lmaydi. Ushbu kodda real order yuborish yo‘li mavjud emas.

## Binance API manbasi

- [Binance Spot REST API — public market-data host va rate limits](https://developers.binance.com/en/docs/products/spot/rest-api)
