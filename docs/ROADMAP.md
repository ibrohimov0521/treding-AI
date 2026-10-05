# Development roadmap

Platforma har bosqich o‘lchanib tekshirilgandan keyin kengayadi. Ushbu repository
hozir **Phase 0–9**ni bajaradi; real exchange orderlari hali yo‘q.

| Phase | Maqsad | Holat |
| --- | --- | --- |
| 0 — Foundation | Project tuzilmasi, config, domain, logging, test/lint va safety poydevori | Tayyor |
| 1 — Market data | Binance Spot public 1m, incremental Parquet, validation, resampling | Tayyor; real yuklash bilan tekshirildi |
| 2 — Feature engineering | Faqat yopilgan candle’larga asoslangan deterministic feature’lar | Tayyor: returns, EMA, RSI, ATR, volatility, volume va candle range |
| 3 — Baseline strategies | Sodda, izohlash mumkin bo‘lgan benchmark strategiyalar | Tayyor: EMA-12/26 long/flat; signal, order emas |
| 4 — Backtesting engine | Event-time fill, fee, spread, slippage; kelajak ma’lumotlarisiz | Tayyor: next-open fill, spot long-only; tarixiy smoke-test qilingan |
| 5 — ML dataset | Aniq label va vaqt bo‘yicha ajratilgan train/validation/test | Tayyor: forward return label, vaqtli purge |
| 6 — ML models | Avval baseline modellar; probability calibration | Tayyor: StandardScaler + LogisticRegression baseline; calibration yo‘q |
| 7 — Walk-forward validation | Out-of-sample tekshiruv va market regime tahlili | Tayyor: expanding folds, purged label horizon, baseline metrics |
| 8 — Paper trading | Real bozorni kuzatish, virtual pozitsiyalar; order yo‘q | Tayyor: public closed candles, restartable virtual Spot, `paper --follow` |
| 9 — Risk engine | Position sizing, loss/drawdown limitlari, mustaqil approval | Tayyor: exposure cap, kunlik zarar va peak drawdown halt |
| 10 — Exchange execution | Authenticated adapter va test muhitini tekshirish | TODO; o‘chiq qoladi |
| 11 — Controlled live trading | Ko‘p bosqichli ruxsat, kichik limit, monitoring, kill switch | TODO |

## Phase 0–1 bajarilganini tasdiqlovchi shartlar

- Public API orqali kichik tarixiy yuklash bajariladi.
- `--start` bermay qayta ishga tushirish faqat keyingi yopilgan candle’larni qo‘shadi.
- Avvalgi vaqtni backfill qilish duplicate `open_time` qatorlarini yaratmaydi.
- Validator ma’lum gapni timestamp bilan ko‘rsatadi.
- 1m→5m, 1m→15m va 1m→1h faqat to‘liq guruhlarni chiqaradi.
- Takroriy ishga tushirishlarda Parquet qiymatlari va quality report bir xil qoladi.
- Avtomatik testlar va static checks muvaffaqiyatli o‘tadi.
- Phase 0–9’da order/account yo‘li yo‘q; `live_trading: true` config’da rad etiladi.

## Hozirgi Phase 2–9 chegaralari

- Feature hisoblash bitta tartiblangan market series’ni talab qiladi; warm-up qatorlari
  `null` bo‘lib qoladi. `ready` asosiy indikatorlar tayyor bo‘lganda `true`.
- EMA benchmark 0–100% long-only exposure beradi. Bu taqqoslash strategiyasi bo‘lib,
  foyda yoki barqaror edge kafolati emas.
- Backtest bitta spot qatoridagi candle’lar uzluksiz bo‘lishini talab qiladi.
  Signal `t` candle yopilgach yaratiladi va `t+1` open’da fill qilinadi.
- Fee, spread va slippage doimiy bps taxminlari; partial fill, order-book impact,
  fee tier, latency, exchange outage va dynamic market impact yo‘q.
- Qisqa smoke-test moliyaviy xulosa yoki model tanlash uchun ishlatilmaydi.
- ML baseline optional `ml` dependency talab qiladi; ehtimollar kalibrlanmagan va signal
  mustaqil savdo edge’i sifatida tasdiqlanmagan.
- Paper engine yopilgan public candle’larni virtual hisobga qo‘llaydi. Signal keyingi
  candle open’da taxminiy fill qilinadi; partial fill, order-book va exchange execution yo‘q.
- Risk halt latched bo‘ladi, yangi targetni nolga tushiradi va keyingi candle open’da
  virtual pozitsiyani yopishni rejalaydi. Qayta boshlashdan oldin holatni qo‘lda ko‘rib
  chiqish kerak.
- `paper --follow` terminal jarayoni sifatida ishlaydi; server qayta yuklanganda
  avtomatik ishga tushirish alohida process supervisor sozlamasini talab qiladi.

## Kelgusi quant bosqichlari uchun qoidalar

- **Look-ahead bias:** `t` vaqtidagi feature `t` dan keyin yopiladigan candle’ni
  ishlatmasin. Qaror faqat o‘sha paytda mavjud bo‘lgan ma’lumotga tayanadi.
- **Data leakage:** transform’larni faqat train oynasida fit qiling. Train,
  validation va test davrlari vaqt bo‘yicha ajralgan bo‘lishi kerak.
- **Survivorship bias:** ko‘p asset’ga o‘tganda tarixiy universe’ni va delist qilingan
  aktivlarni ham hisobga oling.
- **Overfitting:** parameter/model qidiruvini cheklang; yakuniy test va walk-forward
  davrlarini tuning uchun ishlatmang; sinovlar sonini qayd qiling.
- **Transaction cost:** simulyatsiya commission, spread va slippage’ni hisoblaydi;
  keyingi bosqichlarda dynamic spread, fee tier va fill uncertainty qo‘shilishi kerak.
