# ⚡️ Payme Merchant API — avtomatik to'lov

Karta to'lov ekranida (Uzcard/Humo) **«⚡️ Payme orqali to'lash»** tugmasi
chiqadi. To'lov Payme callback'lari orqali tasdiqlanadi va PRO **darhol, admin
aralashuvisiz** faollashadi. Telegram Stars va chek (qo'lda tasdiqlash)
usullari **o'zgarmagan** va yonma-yon ishlaydi.

| Qism | Fayl |
|---|---|
| JSON-RPC state machine, Basic Auth, checkout havola | `telegram_bot/services/payments/payme_provider.py` |
| aiohttp endpoint `POST /payments/payme` | `telegram_bot/services/payments/payme_webhook.py` |
| PostgreSQL store (qulflar, ledger, PRO) | `telegram_bot/repositories/payme_repository.py` |
| Jadvallar `payme_orders`, `payme_transactions` | `telegram_bot/schema.sql` |
| Testlar (unit + HTTP + real PostgreSQL) | `tests/payme_merchant_test.py` |

## 1. Sozlash

1. `.env` ga yozing (batafsil izohlar `.env.example` da):

   ```dotenv
   PAYME_MERCHANT_ID=<kassa id>
   PAYME_KEY=<kassa kaliti>          # sandbox uchun test kaliti
   PAYME_CHECKOUT_URL=https://checkout.paycom.uz   # sandbox: https://test.paycom.uz
   PAYME_ALLOW_REFUNDS=0
   ```

2. Payme kabinetida kassa endpoint'i: `https://<domen>/payments/payme`
   (bot health web server'i bilan bir xil `PORT`, alohida jarayon kerak emas).
   Hisob maydoni: `order_id` (boshqa nom bo'lsa `PAYME_ACCOUNT_FIELD`).
3. Botni qayta ishga tushiring — `schema.sql` yangi jadvallarni idempotent
   yaratadi (`scripts/db_migrate.py` ham tekshiradi).

`PAYME_KEY` bo'sh bo'lsa endpoint barcha so'rovlarni `-32504` bilan rad etadi
(fail-closed) va tugma ko'rsatilmaydi.

## 2. Oqim

```
Foydalanuvchi tarif tanlaydi → payme_orders (pending, summa tiyin'da)
   → checkout.paycom.uz/<base64(m;ac.order_id;a;l;c)>
Payme → CheckPerformTransaction  (buyurtma bormi, summa to'g'rimi)
      → CreateTransaction        (tx state 1 / status 'pending')
      → PerformTransaction       (tx state 2 / 'paid', order 'paid',
                                  payments ledger + PRO +N kun, bildirishnoma)
      ↘ CancelTransaction        (state 1 → -1; state 2 → -2 faqat
                                  PAYME_ALLOW_REFUNDS=1 bo'lsa, aks holda -31007)
      CheckTransaction / GetStatement — holat va solishtirish (sandbox talabi)
```

## 3. Idempotentlik — ikki marta PRO berilmaydi

| Daraja | Mexanizm |
|---|---|
| State machine | `PerformTransaction` takrorlansa saqlangan natija qaytadi, PRO'ga tegilmaydi |
| Qulflar | har metod bitta DB tranzaksiyasi; tartib: `payme_orders` → `payme_transactions` → `payments` → `users` (deadlock'siz) |
| `UNIQUE (payme_transaction_id)` | bitta Payme id = bitta qator (`INSERT … ON CONFLICT DO NOTHING`) |
| `uq_payme_tx_active_order` (partial UNIQUE) | buyurtmada faqat bitta faol (state 1/2) tranzaksiya → boshqasi `-31052` |
| `CHECK` | `status ∈ {pending, paid, cancelled}` va status↔state izchilligi |
| Ledger kaliti | `payments.telegram_payment_charge_id = 'payme:<id>'` (UNIQUE) — PRO faqat yangi qator yozilganda uzaytiriladi |

Bu kafolatlar `tests/payme_merchant_test.py` da real PostgreSQL ustida
(8 ta parallel `PerformTransaction`, 6 ta parallel `CreateTransaction`) tekshiriladi.

## 4. Xato kodlari

`-32504` auth · `-32300` POST emas · `-32700` JSON xato · `-32600` maydonlar ·
`-32601` metod yo'q · `-32400` ichki xato (Payme qayta urinadi) ·
`-31001` summa · `-31003` tx topilmadi · `-31007` bekor qilib bo'lmaydi ·
`-31008` bajarib bo'lmaydi (holat / 12 soatlik timeout) ·
`-31050` buyurtma topilmadi · `-31051` to'langan/bekor qilingan · `-31052` band.
Xabarlar uz/ru/en; har doim HTTP 200 (Payme protokoli).
