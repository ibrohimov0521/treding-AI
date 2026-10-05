# Development roadmap

Platforma joriy bosqich o‘lchanib tekshirilgandan keyin kengayadi. Ushbu repository
hozir **Phase 0–1**ni bajaradi.

| Phase | Maqsad | Holat |
| --- | --- | --- |
| 0 — Foundation | Project tuzilmasi, config, domain, logging, test/lint va safety poydevori | Tayyor |
| 1 — Market data | Binance Spot public 1m, incremental Parquet, validation, resampling | Tayyor; real yuklash bilan tekshirildi |
| 2 — Feature engineering | Faqat yopilgan candle’larga asoslangan deterministic feature’lar | TODO |
| 3 — Baseline strategies | Sodda, izohlash mumkin bo‘lgan benchmark strategiyalar | TODO |
| 4 — Backtesting engine | Event-time fill, fee, spread, slippage; kelajak ma’lumotlarisiz | TODO |
| 5 — ML dataset | Aniq label va vaqt bo‘yicha ajratilgan train/validation/test | TODO |
| 6 — ML models | Avval baseline modellar; probability calibration | TODO |
| 7 — Walk-forward validation | Out-of-sample tekshiruv va market regime tahlili | TODO |
| 8 — Paper trading | Real bozorni kuzatish, virtual pozitsiyalar; order yo‘q | TODO |
| 9 — Risk engine | Position sizing, loss/drawdown limitlari, mustaqil approval | TODO |
| 10 — Exchange execution | Authenticated adapter va test muhitini tekshirish | TODO; o‘chiq qoladi |
| 11 — Controlled live trading | Ko‘p bosqichli ruxsat, kichik limit, monitoring, kill switch | TODO |

## Phase 2 dan oldingi shartlar

- Public API orqali kichik tarixiy yuklash bajariladi.
- `--start` bermay qayta ishga tushirish faqat keyingi yopilgan candle’larni qo‘shadi.
- Avvalgi vaqtni backfill qilish duplicate `open_time` qatorlarini yaratmaydi.
- Validator ma’lum gapni timestamp bilan ko‘rsatadi.
- 1m→5m, 1m→15m va 1m→1h faqat to‘liq guruhlarni chiqaradi.
- Takroriy ishga tushirishlarda Parquet qiymatlari va quality report bir xil qoladi.
- Avtomatik testlar va static checks muvaffaqiyatli o‘tadi.
- Phase 0–1’da order/account yo‘li yoki yoqish mumkin bo‘lgan live flag bo‘lmaydi.

## Kelgusi quant bosqichlari uchun qoidalar

- **Look-ahead bias:** `t` vaqtidagi feature `t` dan keyin yopiladigan candle’ni
  ishlatmasin. Qaror faqat o‘sha paytda mavjud bo‘lgan ma’lumotga tayanadi.
- **Data leakage:** transform’larni faqat train oynasida fit qiling. Train,
  validation va test davrlari vaqt bo‘yicha ajralgan bo‘lishi kerak.
- **Survivorship bias:** ko‘p asset’ga o‘tganda tarixiy universe’ni va delist qilingan
  aktivlarni ham hisobga oling.
- **Overfitting:** parameter/model qidiruvini cheklang; yakuniy test va walk-forward
  davrlarini tuning uchun ishlatmang; sinovlar sonini qayd qiling.
- **Transaction cost:** har bir backtest commission, spread va slippage’ni hisoblasin.
  Xarajatsiz simulyatsiyani paper/live natija bilan taqqoslamang.
