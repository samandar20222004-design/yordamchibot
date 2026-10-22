# Yuk testi (sig'imni o'lchash)

Asbob: `scripts/loadtest.py` (ikki rejim). Production bazaga YUK BERMANG — `local` rejimi lokal bo'lmagan bazani rad etadi.

## 1. `local` — sinov bazasi bilan (haqiqiy kod, soxta Telegram)
```bash
python scripts/loadtest.py local --db-url postgresql://user:pass@127.0.0.1:5432/sinov_baza \
    --users 300 --levels 10,50,200 --duration 8 --tg-latency 0.3 --json natija.json
```
- `db` — botning odatiy so'rovlari (foydalanuvchi + kanallar + postlar) kesh'siz, parallel oqimlar bilan.
- `miniapp` — Mini App API (`/me`, `/channels`, `/scheduled-posts`) parallel foydalanuvchilar bilan (tezlik chegarasi o'chirilgan: API'ning o'zi).
- `scheduler` — N ta post M kanalga yuborish tezligi (`--posts-per-user 1` odatiy; >1 — bitta kanalga to'planish: kanal chegarasi 1 post/s).
- `loadtest_` prefiksli yozuvlar oxirida o'chiriladi.

## 2. `remote` — joylashtirilgan Mini App'ga (faqat o'qish so'rovlari)
```bash
python scripts/loadtest.py remote --url https://sizning.domen --init-data "<Telegram.WebApp.initData>" --levels 10,50,200
```
Bitta foydalanuvchi bilan o'lchanadi: foydalanuvchi bo'yicha rate limit `429` beradi — bu himoya, hisobotda alohida ko'rsatiladi.

## Lokal o'lchov (4 yadro, lokal PG 16, 2026-10-22)
| Stsenariy | Natija |
|---|---|
| db, 5 oqim (kesh yo'q, 3 so'rov/op) | ~2 400 so'rov/s, p95 4 ms |
| db, 20 oqim (pool 10) | ~1 500 so'rov/s, p95 11 ms (pool navbati: boshida p100 ~2 s) |
| miniapp API, 10 parallel | ~460 so'rov/s, p50 21 ms, p95 28 ms, 0 xato |
| miniapp API, 50 parallel | ~460 so'rov/s, p50 107 ms, p95 131 ms, 0 xato |
| scheduler, 300 post / 300 kanal, Telegram 300 ms | **12 post/s (~720/daqiqa)** — `SEND_CONCURRENCY` 4 va 16 da bir xil |
| scheduler, 200 post / 50 kanal (kanalga 4 tadan) | 2,9–3,5 post/s — kanal chegarasi 1 post/s |

## Topilmalar
1. **Scheduler tezligi ~12 post/s da to'xtaydi** (`SEND_CONCURRENCY` ni oshirish yordam bermaydi): har post orasida `SEND_MICRO_DELAY=0.08 s`
   (`scheduler.py`, ataylab FloodWait himoyasi; `tests/unit_test.py` 0.05–0.1 oralig'ini qo'riqlaydi) — 1/0,08 = 12,5 post/s. Telegram umumiy chegarasi ~30/s,
   dvigatel (`services/delivery`) o'zi ham 30 msg/s va kanalga 1 post/s qo'yadi. Ya'ni yuqori chegara ~40% ishlatiladi. Oshirish — egasi qarori
   (mikro-kechikishni ~0,03 s ga tushirish ~30 post/s beradi, lekin testni moslash va FloodWait kuzatuvi kerak).
2. **Kanal chegarasi bitta slotni band qiladi**: bitta kanalga bir vaqtda ko'p post to'plansa, kanal pauzasida `SEND_CONCURRENCY` slotlaridan biri bo'sh turadi.
3. DB pool (10) dan ko'p oqim bir vaqtda ishlasa — navbat; masofadagi DB'da `DB_POOL_MAX` ni hosting limitiga qarab oshiring.
