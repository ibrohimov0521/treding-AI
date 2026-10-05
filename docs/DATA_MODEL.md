# Data modeli

## Candle

| Maydon | Turi / birligi | Ma’nosi |
| --- | --- | --- |
| `exchange` | Katta harfli satr | Birja yoki provider identifikatori |
| `market_type` | Enum | Phase 1’da `spot` |
| `symbol` | Katta harfli satr | Umumiy bozor nomi, masalan `BTCUSDT` |
| `timeframe` | Enum | Raw `1m`; hosila `5m`, `15m`, `1h` |
| `open_time`, `close_time` | Timezone-aware UTC datetime | Candle vaqt chegaralari |
| `open`, `high`, `low`, `close` | Decimal | Binary float ishlatmasdan saqlangan narxlar |
| `volume`, `quote_volume` | Decimal | Base va quote asset hajmi |
| `number_of_trades` | Butun son | Candle ichidagi bitimlar soni |
| `taker_buy_base_volume`, `taker_buy_quote_volume` | Decimal | Taker buy hajmlari |

Tabiiy identity key: `(exchange, market_type, symbol, timeframe, open_time)`.

## Storage partition

```text
<data_dir>/raw/<exchange>/<market>/<symbol>/<timeframe>/year=YYYY/month=MM/candles.parquet
<data_dir>/processed/<exchange>/<market>/<symbol>/<timeframe>/year=YYYY/month=MM/candles.parquet
```

Har oy alohida o‘qiladi. Raw write bir xil key’ni ikkinchi marta qo‘shmaydi va
saqlangan qator qiymatini o‘zgartirmaydi. Processed natijani raw manbadan qayta
hisoblash mumkin. Hisobot JSON bo‘ladi va katta gaplarda hajmni cheklash uchun
ko‘pi bilan 25 ta missing timestamp misolini saqlaydi.

## Candle chegaralari

Downloader vaqtlari UTC bo‘ladi. `end_time` exclusive; CLI’dagi `--end YYYY-MM-DD`
esa o‘sha sananing butun kunini o‘z ichiga oladi. Binance API timestamp’lari
millisekundda. Hali yopilmagan candle raw storage’ga yozilmaydi.

Resampling UTC epoch chegaralariga mos bucket ishlatadi. Masalan, 12:05 dagi 5m
candle 12:05 dan 12:09 gacha bo‘lgan minutlarni birlashtiradi. Kutilgan har bir
1m `open_time` aynan bir marta mavjud bo‘lsagina bucket chiqariladi.

## Data quality statuslari

| Status | Ma’nosi |
| --- | --- |
| `PASS` | Tekshirilgan muammo topilmadi |
| `WARNING` | Duplicate, missing yoki tartibsiz candle; ma’lumot yashirincha tuzatilmaydi |
| `FAIL` | Noto‘g‘ri OHLC, manfiy volume, null/corrupt qator yoki imkonsiz timestamp |
