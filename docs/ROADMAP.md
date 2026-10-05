# Loyiha roadmap’i

Platforma keyingi bosqichga faqat oldingi bosqich natijasi tekshirilgach o‘tadi.
Hozir loyiha Binance Spot BTCUSDT public ma’lumotlarida research, backtest va
virtual paper hisobni bajaradi. Birjaga order yuboradigan kod yo‘q.

| Bosqich | Maqsad | Holat |
| --- | --- | --- |
| 0 — Scope va poydevor | Talablar, universal market modeli, config, log va test infratuzilmasi | Tayyor |
| 1 — Data | Public Spot candle’larini yuklash, saqlash, incremental davom ettirish | Tayyor; kichik real yuklash tekshirilgan |
| 2 — Data sifati va EDA | Validatsiya, gap/duplicate tekshiruvi, tavsifiy tahlil | Validatsiya tayyor; to‘liq EDA hisoboti qolgan |
| 3 — Baseline va backtest | EMA benchmark, next-open fill, komissiya/spread/slippage, risk cheklovlari | Asosiy oqim tayyor; kengroq metrikalar va mustaqil tekshiruv qolgan |
| 4 — ML va walk-forward | Label, vaqtli split, baseline model va leakage’dan himoyalangan sinov | LogisticRegression va expanding walk-forward bor; kalibratsiya, untouched holdout va regime tahlili qolgan |
| 5 — Signal va risk | Backtest/paper’da umumiy signal qarori va mustaqil exposure/loss limitlari | Tayyor; signal ID va feature hash qo‘shilgan |
| 6 — Paper execution | Virtual order holati, fill, restart va reconciliation | Virtual portfolio/checkpoint hamda restartda davom etuvchi systemd worker bor; order lifecycle, partial fill va reconciliation qolgan |
| 7 — Monitoring va audit | Kuzatuv, o‘zgartirishni aniqlaydigan log, ogohlantirish va dashboard | Hash-zanjirli JSONL audit hamda `audit-verify` tayyor; dashboard/alert qolgan |
| 8 — Shadow | Jonli public data’da signal hisoblash, order yubormaslik | TODO |
| 9 — Paper gate | Yetarli muddatli paper natijasi va risk/reconciliation tekshiruvi | TODO; gate hali o‘tmagan |
| 10 — Micro-live | Alohida ruxsat va qat’iy limit bilan minimal real savdo | TODO; hozircha o‘chiq va order yo‘li mavjud emas |
| 11 — Scale | Faqat uzoq muddatli dalildan keyin ko‘lamni bosqichma-bosqich oshirish | TODO |

## Hozirgi ishlaydigan oqim

```text
Public Spot candle → validation → causal features → strategy signal
                                                   ↓
                                          shared risk approval
                                                   ↓
                                     backtest / virtual paper state
                                                   ↓
                                      hash-chained audit record
```

Paper worker systemd user service’da har 15 soniyada public yopilgan candle’larni
tekshiradi; fill’lar virtual va keyingi candle open’da simulyatsiya qilinadi.
`data/audit/.../events.jsonl` har bir paper
yangilanishini zanjirlangan SHA-256 hash bilan yozadi. Bu logni o‘zgartirishni
aniqlashga yordam beradi, lekin imzolangan yoki tashqi append-only saqlash o‘rnini
bosmaydi. Auditni `trading-platform audit-verify <fayl>` bilan tekshirish mumkin.

## Hali bajariladigan xavfsiz ishlar

1. Data sifati va EDA uchun eksport qilinadigan hisobot qo‘shish.
2. Backtest natijalariga benchmark, turnover, exposure, risk va cost tahlilini qo‘shish;
   holdout davrini tuning’dan ajratish.
3. Paper adapterida virtual order holati, restart recovery va reconciliation’ni
   yakunlash; audit/checkpoint xatolarini idempotent tiklash.
4. Dashboard/alert va order yubormaydigan shadow rejimini qo‘shish.
5. Yetarli davomiy paper dalili to‘plangandan keyingina Phase 9 gate’ni ko‘rib chiqish.

## Real savdo uchun bloklovchi shartlar

Real savdo hozir yoqilmaydi. Kelgusida ham Phase 9 natijasi tasdiqlanmasdan
authenticated execution qo‘shilmaydi. Alohida ruxsat, alohida credential, withdrawal
huquqisiz API key, qat’iy order/kunlik limit, kill switch, monitoring, audit va
account bilan reconciliation talab qilinadi. Hech bir config flag real savdoni o‘zi
yoqmasligi kerak.
