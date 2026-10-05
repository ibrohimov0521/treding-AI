# Dockploy: BTCUSDT virtual paper worker

`compose.dokploy.yaml` GitHub repo ildizidagi Docker Compose loyihasi sifatida
Dockploy'da alohida `trading-platform-paper` project/environment'da ishlaydi.
Port va public domain talab qilinmaydi: worker faqat public Binance API'ga
chiquvchi so'rov yuboradi. Bitta nusxa ishlatiladi.

Avval `paper-shadow` alohida checkpoint va audit bilan ishga tushadi. Hozirgi
systemd `trading-platform-paper.service` o'z state'ida davom etadi. Shadow
natijalari va logi tekshirilgach, eski xizmat to'xtatiladi, backup olinadi va
Dockploy command/state path'i yagona authoritative paper worker uchun
o'zgartiriladi. Ikkala worker bir xil checkpointga bir vaqtda yozmaydi.

Hostdagi `/home/javohir/dev/trading-platform/data` doimiy bind mount sifatida
`/app/data`ga ulanadi; image/build'da hech qanday credential yoki data yo'q.
Compose user UID 1000 hostdagi `javohir` bilan mos. Kelgusidagi Telegram tokeni
alohida owner-only host faylida saqlanadi va faqat notification service'ga
mount qilinadi; hech qachon build context yoki GitHub'ga kirmaydi.

Replika soni 1 bo'lishi shart. Service restart policy, log va data backup
Dockploy'da tekshiriladi. Stop signalining tarixiy OHLC modeli virtual
simulyatsiya; hozirgi real-time paper runner hali birja stop orderini yubormaydi.
