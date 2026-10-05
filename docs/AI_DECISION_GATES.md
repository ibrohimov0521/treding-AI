# O'z-o'zini tekshiradigan trading AI: qaror va o'sish qoidalari

## Niyat

Platforma har bir signal uchun yo'nalish ehtimolini, noaniqligini, xarajatlardan
keyingi kutiladigan natijani va bekor qilish shartini hisoblaydi. Ishonch past,
data eskirgan yoki edge xarajatlardan kichik bo'lsa, `HOLD` deydi. Ehtimol
kalibrlanmaguncha xabar `67% BUY/SELL` demaydi.

`10 ta savdodan 5 tasi yutishi` yakka o'zi foyda mezoni emas. Soddalashtirilgan
net expectancy:

`p(win) × o'rtacha foyda − p(loss) × o'rtacha zarar − komissiya − spread − slippage`.

50% win rate bilan ham o'rtacha zarar kattaroq yoki savdo xarajati yuqori bo'lsa
hisob kamayadi. Hech bir reja 5/10 yutuqni yoki foydani kafolatlay olmaydi.

## Avtonom sikl va gate'lar

1. **Data ingest:** Exchange va symbol bo'yicha raw candle/trade/book oqimini
   UTC vaqt, manba, schema versiyasi bilan yozish. Gap, dublikat, eski data va
   outlier'ni aniqlash; REST backfill bilan tiklash. `BITSTAMP:BTCUSD` uchun
   Bitstamp ma'lumoti va o'z fee qoidasi kerak; Binance BTCUSDT natijasini unga
   ko'chirib bo'lmaydi. Tarixiy downloader har muvaffaqiyatli sahifani alohida
   atomik yozadi; uzoq download'lar RAMda to'liq to'planmaydi va uzilishdan
   oldingi to'liq sahifalar saqlanib qoladi.
2. **Candidate train:** Faqat yopilgan tarixdan feature va label; train,
   calibration, validation va tegilmagan test oynalarini vaqt bo'yicha ajratish,
   horizon miqdorida purge. Raw history o'zgarmas manba; derived feature qayta
   quriladigan material.
3. **Candidate evaluate:** Direction accuracy bilan birga class-wise precision/
   recall, Brier/log-loss, reliability bins, calibration error, net expectancy,
   profit factor, max drawdown, turnover va xarajat sensitivity hisoblanadi.
   Buy-and-hold hamda oddiy baseline bilan taqqoslanadi.
4. **Promote yoki rad et:** Candidate faqat bir nechta oldindan belgilangan
   out-of-sample/regime oynalarda fee/slippage stressidan keyin musbat net
   expectancy, risk limiti va probability calibration gate'larini o'tsa
   paper canary'ga chiqadi. Aks holda current champion qoladi; hisobot va rad
   sababi saqlanadi. Threshold'lar natijani ko'rgandan keyin o'zgartirilmaydi.
5. **Paper canary:** Eski va yangi model bir xil live public data'da order
   yubormasdan yuradi. Signal farqi, alert latency, stale data, restart recovery,
   fees, stop slippage va virtual reconciliation tekshiriladi. Faqat belgilangan
   sample/muddat va incident review o'tsa champion yangilanadi.
6. **Rollback/drift:** Kalibratsiya yoki net expectancy tushsa, data drift bo'lsa,
   alert kechiksa yoki audit uzilsa `HOLD`/risk halt; oxirgi tasdiqlangan modelga
   qaytish. Har modelning code commit, feature/schema, train range, parametrlari,
   metric va hash manifesti yoziladi.

## O'zini kengaytirish chegarasi

AI candidate model va strategy parameter'larini izolyatsiyalangan research
jarayonida taklif qilib, sinashi mumkin. U o'zining bajariladigan kodini live
serverda tahrirlamaydi, risk gate'ni yumshatmaydi va birja orderini yubormaydi.
Kod o'zgarishi version control, unit/integration test, statik tekshiruv va
paper canary'dan o'tadi. Real execution kelajakda alohida ruxsat va alohida
hard gate talab qiladi.

## Ma'lumot va disk o'sishi

Disk sig'imi cheksiz bo'lmaydi. 256 GB SATA disk hozircha rejalashtirilgan
sig'im; u serverda `lsblk`, filesystem, SMART va mount holati tekshirilmaguncha
formatlanmaydi yoki unga ma'lumot ko'chirilmaydi. Xavfsiz siyosat:

- raw candles append-only Parquet partition: `exchange/market/symbol/timeframe/year/month`;
- xom va qayta quriladigan feature'larni farqlash; dedup key `(venue,symbol,interval,open_time)`;
- har 24 soatda incremental ingest va data-quality report, gap backfill;
- yillik disk ishlatilishi prognozi, 70% ogohlantirish, 85% da yangi bulk download'ni
  to'xtatib, paper signalni stale-data/risk holatiga o'tkazish;
- ikkinchi diskda asosiy data yoki alohida snapshot; muhim raw va model manifestni
  boshqa fizik qurilma yoki masofaviy backup'ga nusxalash;
- SQLite outbox va paper state uchun transaction, atomik checkpoint va backup
  restore test; generated dataset/reports GitHub'ga kirmaydi.

Avval 256 GB diskni tekshirib, raw market archive uchun mount qilamiz; hozirgi
data bir necha yuz KB bo'lgani sabab ko'chirishga ehtiyoj yo'q. Swap disk
Docker/Dokploy'dagi data volume bilan mos ravishda mount path'da bo'ladi.

## Hozirgi dalil va keyingi bosqich

2024-01/02 baseline hamda 2024-03 holdout zarar bilan tugadi. Shu sabab hozirgi
`EMA-12/26` model promotion gate'dan o'tmadi. Keyingi tartib: fee/slippage
taxminlarini Bitstamp bo'yicha tasdiqlash; signal va fill qatlamini ajratib,
bar close/wick stop modelini yaxshilash; walk-forward fold va probability
reliability hisobotini yuritish; candidate modelni holdout tegilmagan holda
sinash; faqat shundan keyin paper alertlar.
