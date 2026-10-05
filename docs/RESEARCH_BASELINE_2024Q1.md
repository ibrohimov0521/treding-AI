# BTCUSDT 1m virtual tadqiqot — 2024 yanvar–mart

2026-10-06 (Toshkent). Ma'lumot: Binance Spot `BTCUSDT` public 1m OHLCV.
Grafik namunasi `BITSTAMP:BTCUSD` bo'lgani uchun narx, USD/USDT va birja
komissiyasi aynan foydalanuvchining TradingView pozitsiyasi bilan teng emas.

Strategiya: EMA 12/26 long/flat baseline. Signal yopilgan candle'dan keyin,
oddiy fill keyingi candle open'da. 10 000 USDT boshlang'ich virtual kapital;
har bir tarafda 10 bps komissiya, to'liq spread 2 bps va 5 bps slippage.
Komissiya raqami Binance regular Spot stavkasiga mos keladigan taxmin, real
hisob/VIP/aksiya bo'yicha o'zgarishi mumkin. Stop virtual OHLC `low` trigger;
gap bo'lsa open'da, so'ng xarajatlar bilan chiqadi. Bu haqiqiy stop order
ijrosi yoki telefon signalining tezlik testi emas.

| Davr | Risk limiti | Stop | Yopilgan virtual bitim | G'olib | Stop chiqish | Yakun / qaytim | Max drawdown |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Yan–fev (86 400 candle) | Kunlik 2%, peak 8% | 0,2% | 7 | 1 (14,29%) | 2 | 9 776,21 / −2,24% | 2,38% |
| Mart, mustaqil davr (44 640) | Kunlik 2%, peak 8% | 0,2% | 10 | 2 (20,00%) | 3 | 9 778,79 / −2,21% | 2,43% |
| Yan–fev diagnostika | Ikkalasi 100% | 1% | 1 594 | 147 (9,22%) | 4 | 68,45 / −99,32% | 99,32% |
| Mart diagnostika | Ikkalasi 100% | 1% | 851 | 101 (11,87%) | 3 | 680,35 / −93,20% | 93,24% |

Diagnostika qatorlari risk limitini ataylab bo'shatadi; real foydalanish
uchun ruxsat yoki tavsiya emas. 100 ta ijobiy natija yig'ish uchun parametr
tanlamadik. Ikkala davrda ham hozirgi baseline zarar ko'rsatdi. `67% SELL`
kabi ehtimol hisoblanmagan va kalibrlanmagan; xabarga kiritilmaydi.

2024 mart alohida oynada, state boshidan 10 000 USDT bilan qayta boshlandi;
birinchi kun uchun indikator warmup talab qilinadi. Foyda, win rate va
drawdown bir-birini almashtirmaydi. Natijalar OHLC model, bid/ask bo'lmagan
spread/slippage taxmini, partial fill va tezkor data uzilishi modellashtirilmagani
uchun optimistik yoki pessimistik bo'lishi mumkin. Paper worker'da hozir
intrabar stop order yo'q; faqat backtest virtual stop modeli qo'shildi.

Hisobot JSON/Parquet fayllari serverdagi
`/home/javohir/dev/trading-platform/data/reports/backtest/binance/spot/BTCUSDT/1m/`
ichida, har bir parametr to'plamiga alohida hash nom bilan saqlanadi.
