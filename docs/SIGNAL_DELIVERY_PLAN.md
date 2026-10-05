# BTCUSDT signal yetkazish va qolgan loyiha ishlari

Yangilangan reja: 2026-10-05. Bu hujjat `AI_Trading_Master_Prompt.txt` dagi 0–11 bosqichlarni saqlaydi. Boshlang‘ich bozor — Binance Spot BTCUSDT; signal, backtest, shadow va paper bosqichlari real order yubormaydi.

TradingView namunasi `BITSTAMP:BTCUSD` 1m: hozirgi Binance `BTCUSDT`
ma'lumoti bilan bir xil narx yoki fee emas. Aynan shu grafikka mos signal
uchun Bitstamp BTCUSD public adapteri, o'z fee modeli va alohida sinov kerak.
Paper ishini keyingi bosqichda mavjud Dockploy loyihalaridan alohida servisga
ko'chiramiz; [Dockploy qo'llanmasi](DOCKPLOY_DEPLOY.md).

## Hozirgi holat

- Public REST 1m yopilgan candle’lari har 15 soniyada tekshiriladi; virtual paper worker systemd orqali ishlaydi.
- EMA-12/26 target, umumiy signal/risk engine, backtest, ML baseline/walk-forward va virtual checkpoint bor.
- Paper qarorlari SHA-256 zanjirli `data/audit/.../events.jsonl` fayliga yoziladi; `audit-verify` ularni tekshiradi.
- Telefon xabari, dashboard, WebSocket, shadow rejim, to‘liq paper reconciliation va live gate hali tayyor emas.
- Joriy signal foyda yoki statistik ustunlik isboti emas. Telegram xabarlari avval `PAPER/TEST` sifatida chiqadi.

## Tezlikni to‘g‘ri o‘lchash

Binance Spot `{symbol}@kline_1m` oqimi 1m candle’ni taxminan har 2 soniyada yangilaydi; `k.x=true` candle yopilganini bildiradi. Yopilgan candle signali shu hodisadan so‘ng hisoblanadi. Jonli grafik esa candle ichidagi narxni oldin ko‘rsatishi mumkin. Broker grafigidan doim tez bo‘lish kafolati yo‘q. [Binance rasmiy WebSocket hujjati](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams).

O‘lchov zanjiri: birja hodisasi vaqti → server qabul qilgan vaqt → risk qarori → audit/outbox → Telegram API javobi → foydalanuvchi qurilmasida ko‘ringan vaqt. Oxirgi bosqichni serverning Telegram API javobidan bilib bo‘lmaydi; haqiqiy qurilma yetib kelishini alohida sinaymiz. p50/p95/p99 (hodisalarning 50/95/99 foizi uchun kechikish) hisobotini tayyorlab, keyin maqsad chegarani o‘lchovga tayangan holda belgilaymiz.

Ikki signal sinfi:

1. **Tasdiqlangan:** `k.x=true` yopilgan 1m candle va mustaqil risk qaroridan keyin. Dastlabki bildirishnomalar shundan chiqadi.
2. **Erta kuzatuv:** candle ichidagi trade yoki best bid/ask oqimidan olinadigan, o‘zgarishi mumkin bo‘lgan `WATCH`. Bu alohida strategiya va alohida tarixiy/replay tekshiruvidan keyingina qo‘shiladi; uni tasdiqlangan BUY/SELL deb ko‘rsatmaymiz.

## Signal foydalanuvchiga qanday ko‘rinadi

| Holat | Yuborish sharti | Mazmuni |
| --- | --- | --- |
| BUY KANDIDAT | Oldingi tasdiqlangan target 0, yangi risk tasdiqlagan target 0 dan katta | Strategiya virtual Spot long exposure istaydi; real narx/fill kafolati emas |
| SELL / EXIT KANDIDAT | Oldingi target 0 dan katta, yangi target 0 | Strategiya virtual long’ni yopadi; short ochmaydi |
| RISK HALT | Loss/drawdown/stale-data yoki boshqa veto | Yangi kandidatlar bloklanadi; sabab va tiklash tartibi ko‘rsatiladi |
| CAPPED | Risk targetni qisqartirdi | So‘ralgan va tasdiqlangan exposure alohida ko‘rsatiladi |
| HOLD | Target o‘zgarmadi | Jurnalda saqlanadi, har minut telefonni bezovta qilmaydi |
| WATCH | Kelgusidagi intrabar prototip | “Taxminiy, bekor bo‘lishi mumkin” deb aniq belgilanadi |

Har xabarda bozor, timeframe, qaror vaqti (UTC va Toshkent), ma’lumot yangiligi, strategiya/model versiyasi, signal ID, oldingi/yangi target, risk sababi va signalning amal qilish muddati bo‘ladi. Faqat tasdiqlangan target o‘zgarganda yangi BUY/EXIT xabari yuboriladi; dublikatlar signal ID bilan to‘siladi. Stop-loss/take-profit va “ishonch foizi” faqat alohida hisoblash va kalibratsiyadan keyin qo‘shiladi.

Bu xabarlar strategiyaning virtual holatini bildiradi. Foydalanuvchining haqiqiy hisobidagi BTC miqdorini tizim hozir bilmaydi; shu sabab shaxsiy sotish miqdorini hisoblamaydi.

## Tartib bilan bajariladigan ishlar

| Tartib / master bosqich | Bajariladigan ish | Natija va keyingi bosqich sharti |
| --- | --- | --- |
| 0 — Talab va bazaviy o‘lchov | Solishtiriladigan aniq grafik, kanal va signal sinfini belgilash; mavjud REST worker kechikishini vaqt belgilari bilan o‘lchash | Talab yoziladi, bir xil bozor/timeframe bo‘yicha bazaviy p50/p95/p99 hisobot bor |
| 1 — WebSocket market data (Phase 1–2) | Public 1m kline adapteri, UTC normalizatsiya, faqat yopilgan candle’ni tasdiqlash; disconnect/reconnect, dublikat, gap, REST backfill | WS va REST yopilgan candle qiymatlari mos; uzilishdan keyin bo‘shliq qolmaydi; eskirgan data bloklanadi |
| 2 — Signal kontrakti (Phase 5) | Mavjud strategiya/risk kodini bir xil saqlab, target o‘zgarishini BUY/EXIT/HOLD/RISK HALT eventiga aylantirish; oldingi state va expiry | Replay’da bir xil signal ID; o‘zgarmagan target takroriy BUY bermaydi; risk veto har doim ustun |
| 3 — Xabar yetkazish (Phase 7) | SQLite durable outbox, Telegram yuboruvchi, retry/dedup, o‘tkazib yuborilgan/eskirgan signalni belgilash, faqat o‘z chatiga test | Audit → outbox → Telegram API qabul qilishi bog‘langan; uzilish/restartda yo‘qolish yoki takror yuborish testi o‘tadi |
| 4 — Tezlik va shaffoflik (Phase 7) | Birja/receive/decision/send vaqtlarini yig‘ish, p50/p95/p99 va stale alert; foydalanuvchining grafigi bilan bir xil sharoitda taqqoslash | Kechikish va xato foizi o‘lchangan; grafikdan tezlik haqida faqat shu test natijasiga tayangan xulosa |
| 5 — Research gap’lari (Phase 2–4) | EDA, backtest risk/cost/benchmark metrikalari, untouched holdout, walk-forward va kalibratsiya/tree baseline; ortiqcha moslashishni tekshirish | Mustaqil davr va xarajat stressida strategiya baholangan; paper alert “real tavsiya” deb talqin qilinmaydi |
| 6 — Paper/monitoring (Phase 6–7) | Virtual order lifecycle, partial fill va fee/slippage taxminlari, checkpoint-audit tiklanishi, reconciliation, dashboard va alert health, backup | Qayta ishga tushish va data uzilishida state izchil; audit/virtual balansda noma’lum tafovut yo‘q |
| 7 — Shadow va gate (Phase 8–9) | WS signalini order yubormasdan REST paper bilan parallel solishtirish, yetarli paper sample/regime, latency va incident review | Paper gate hujjat bilan ko‘rib chiqiladi; statistik va operatsion dalil bo‘lmasa gate o‘tilmaydi |
| 8 — Keyingi imkoniyat (Phase 10–11) | Faqat alohida ruxsatdan so‘ng micro-live adapter, alohida kalit/muhit, hard caps, kill switch, reconciliation; keyin sekin scale | Explicit unlock va barcha oldingi gate’lar shart; bugun bu bosqich yoqilmaydi |

1–4 ishlarni tezroq bildirishnoma prototipi sifatida quramiz, ammo u `PAPER/TEST` yorlig‘i bilan qoladi. 5–7 dalillar signalni real pul uchun ishlatishdan oldin majburiy.

## Kod, ma’lumot va maxfiy qiymatlar qayerda bo‘ladi

| Narsa | Joy | GitHub’ga chiqadimi? |
| --- | --- | --- |
| Reja va public sozlamalar | `docs/SIGNAL_DELIVERY_PLAN.md`; `configs/markets/btcusdt.yaml` | Ha, maxfiy qiymatsiz |
| WS adapter, signal, risk, xabar kodi | `src/trading_platform/market_data/`, `signals/`, `risk/`, yangi `notifications/` va `shadow/` | Ha |
| Unit fayllar va testlar | `deploy/systemd/` va `tests/` | Ha |
| Raw candle va paper checkpoint | `data/raw/`, `data/paper/binance/spot/BTCUSDT/1m/state.json` | Yo‘q, serverda |
| Audit va yetkazish navbati | `data/audit/binance/spot/BTCUSDT/1m/events.jsonl`, keyin `data/alerts/outbox.sqlite3` | Yo‘q, serverda |
| Tezlik va tadqiqot hisobotlari | `data/reports/latency/` va `data/reports/` | Yo‘q, serverda; eksport nusxasi alohida beriladi |
| Telegram bot tokeni va chat ID | `/home/javohir/.config/trading-platform/telegram.env`, faqat `javohir` o‘qiy oladi (0600) | Hech qachon |
| Kelgusidagi live API kaliti | Alohida service account va host secret store; paper’dan ajratiladi | Hech qachon; hozir kerak emas |

Serverdagi `~/.config/systemd/user/trading-platform-paper.service` worker’ni ishga tushiradi. Shadow va xabar yuboruvchi uchun alohida unitlar repositoryda yaratiladi. Telegram bot serverdan tashqariga chiquvchi HTTPS orqali ishlaydi; unga yangi public tunnel shart emas. Dashboard kerak bo‘lsa, keyingi bosqichda masalan `signals.jibrohimov.uz` manzili, autentifikatsiya va Cloudflare Access alohida sozlanadi.

## Javohirdan kerak bo‘ladigan ma’lumotlar

**Hozir, sir bo‘lmaganlari — shu chatda yoziladi:**

1. Taqqoslanadigan grafikning aniq nomi yoki URL’i: Binance, TradingView yoki qaysi broker; aynan BTCUSDT Spot va qaysi timeframe ko‘rinishi.
2. Bildirishnoma kanali: avval Telegram tavsiya qilinadi; keyin dashboard ham kerakmi. Xabar tili o‘zbekcha, vaqt Toshkent va UTC deb qabul qilinadi.
3. Dastlab faqat tasdiqlangan 1m signalmi yoki keyin alohida `WATCH` prototipi ham kerakmi. Tavsiya: avval tasdiqlangan signalni tugatish.
4. Agar qo‘lda savdo qilish rejalansa, foydalanuvchi bajargan savdoni qo‘lda belgilash uchun keyin mini-panel kerakmi. Hozirgi tizim real balansni bilmaydi.

**Xabar yuborish bosqichida:**

5. Telegram’da [@BotFather](https://core.telegram.org/bots/tutorial) orqali yangi bot yaratish; botning ochiq username’ini shu chatga aytish mumkin. Tokenni chatga yoki GitHub’ga yubormaslik.
6. Windows PowerShell’dan SSH bilan serverga kirib, maxfiy faylni yaratish va tokenni editor orqali kiritish:

```bash
ssh javohir@ssh.bestgamers.win
install -d -m 700 ~/.config/trading-platform
nano ~/.config/trading-platform/telegram.env
chmod 600 ~/.config/trading-platform/telegram.env
```

Fayl ichida `TELEGRAM_BOT_TOKEN=<BotFather bergan token>` bo‘ladi. Botga Telegram’da `/start` yuboriladi. Keyin chat ID’ni aynan o‘sha chat ekanini tekshirib, shu maxfiy faylga joylaymiz. Rasmiy Bot API xabar yuborishda `chat_id` talab qiladi: [Telegram Bot API](https://core.telegram.org/bots/api#sendmessage).

**Hozir kerak bo‘lmaydiganlar:** Binance API key, Binance paroli, withdrawal ruxsati, haqiqiy pul miqdori, Cloudflare’da alohida ish muhiti. Real savdo muhokamasi faqat Phase 9 gate’dan keyin boshlanadi.

## Ish tartibi va o‘zgarish nazorati

Har bir kichik bosqichda kod, test, server smoke-test, kechikish/quality natijasi va qisqa izoh bitta GitHub commitga kiradi. Hozirgi paper worker ishlashda davom etadi; yangi WS/shadow oqimi avval alohida state bilan parallel sinovdan o‘tadi. Bir xil candle ikki marta virtual fill bo‘lmasligi, auditi to‘liq bo‘lishi va xatoda eskirgan BUY chiqmasligi majburiy. Bot yoki live credential repositoryga yozilmaydi.
