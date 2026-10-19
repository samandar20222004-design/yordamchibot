# Ishga tushirish: sig'im, o'lchovlar va operatsiya

Raqamlar **lokal** o'lchov (4 yadro, lokal PostgreSQL 16, tarmoq kechikishisiz). Production'da (masofadagi DB, hosting) pastroq bo'ladi —
ularni «yuqori chegara» deb o'qing, va'da emas. Production bazaga/hostingga kirish yo'q edi.

## O'lchovlar (shu repo, `scripts` emas — bir martalik o'lchov)
| Nima | Natija |
|---|---|
| Mini App API (`/me`, `/channels`, `/scheduled-posts`, `/draft`), 1 ta so'rov | 2–4 ms |
| Xuddi shu, 50 parallel | ~400–570 so'rov/s, p50 80–120 ms, 0 xato |
| Xuddi shu, 200 parallel (portlash) | ~800–1200 so'rov/s, ~75% tez `503` (navbat to'lgan: `max_inflight_db=4` + `max_queue=64`), mijoz 1 marta qayta uradi |
| `/draft/media` (rasm, Telegram'dan 150 ms kechikish bilan) | 4 ms (keshdan), 50 parallel p50 124 ms |
| Brauzer (Chromium, 5 sahifa, haqiqiy API + statik) | har sahifa 0,6–0,95 s, konsol/HTTP xatosi 0 |
| Mini App JS (brotli) | ~125 KB (asosiy) + 4–6 KB (admin/birja bo'lagi) |
| DB: keshsiz bitta o'qish (pool 10) | ~2 200–2 500 so'rov/s |
| 600 000 post / 50 000 foydalanuvchi: «vaqti kelgan postlar» so'rovi | 26 ms; foydalanuvchi ro'yxati 0,05 ms |
| `scheduled_posts` 600 000 qator | 121 MB (indekslar bilan) |

## Yuborish tezligi (scheduler)
- Oldin: daqiqada **ko'pi bilan 100 post** (`POST_BATCH_SIZE`, tick'da bitta paket) va postlar ketma-ket. 09:00 da 1 000 ta post bo'lsa — 10 daqiqagacha kechikish.
- Endi: tick'da navbat bo'shaguncha paketlar (`SEND_MAX_ROUNDS`=30 → 3 000 post) va turli kanallarga `SEND_CONCURRENCY`=4 parallel
  (bitta kanalga — ketma-ket). Telegram chegarasi ~30 xabar/s (umumiy), bitta kanalga ~20/daqiqa. `SEND_CONCURRENCY=1` — eski xulq.
- Qo'pol baho: Telegram javobi ~0,3 s bo'lsa 4 parallel bilan ~10 post/s ≈ 600 post/daqiqa (lokal mikro-kechikish 0,08 s hisobga olingan).

## Qancha foydalanuvchi (taxminiy)
- Bitta jarayon (bot + Mini App + scheduler birga). DB so'rovlari: masofadagi DB'da har so'rov kechikishi ~10–30 ms bo'lsa, pool 10 → ~300–1 000 so'rov/s.
  Oddiy bot yangilanishi 3–6 so'rov → ~50–200 yangilanish/s. Kunlik faol 10–30 ming foydalanuvchi uchun bu yetarli (cho'qqi odatda 10–50/s).
- Chegaralar: Telegram'ga yuborish tezligi, DB ulanish limiti (`DB_POOL_MAX` hosting rejasidagi `max_connections` dan oshmasin), AI xarajati (`AI_GLOBAL_DAILY_USD`).
- Gorizontal kengaytirish YO'Q: polling bitta nusxada ishlaydi. Bir nusxa tushsa bot to'xtaydi (Docker `restart`, `/health/live`).

## Zaxira nusxa va monitoring (egasi sozlaydi)
- Bazani avtomatik zaxiralash kod ichida YO'Q: boshqariladigan PostgreSQL (Neon/Aiven/Render) ning kunlik zaxira / PITR xizmatini yoqing va
  hech bo'lmasa bir marta tiklashni sinab ko'ring. Qo'lda: `pg_dump -Fc "$DATABASE_URL" > postassist_$(date +%F).dump`.
- `SENTRY_DSN` (ixtiyoriy), `/health/live` (liveness), `python -m utils.deep_healthcheck` (DB + scheduler + AI holati) — monitoringga ulang.
- Production'da `AI_GLOBAL_DAILY_USD > 0`, `ENVIRONMENT=production`, `scripts/preflight_env.py` o'tishi shart.

## Bilingan cheklovlar
- Katta video (>20 MB): botda qabul qilinadi va kanalga yuboriladi, lekin Mini App'da oldindan ko'rinmaydi (Telegram Bot API `getFile` chegarasi) — katakchada belgi chiqadi.
- Digest/haftalik hisobot va kunlik bonus sanasi Toshkent vaqtida (`docs/TIMEZONES.md`).
