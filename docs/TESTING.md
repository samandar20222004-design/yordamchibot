# Testlar

## Python (bot + Mini App backend)

```bash
cd telegram_bot
ruff check ..                                   # lint
PYTHONPATH=. bash ../tests/run_tests.sh         # to'liq to'plam; oxirida yiqilgan fayllar ro'yxati
BOT_TOKEN=123456:ABCdef PYTHONPATH=. python ../tests/<nom>_test.py   # bitta fayl
bash ../scripts/security_check.sh               # ruff, flake8, pip-audit, bandit
```

- `run_tests.sh` ni `BOT_TOKEN`siz ishga tushiring (o'zi sozlaydi). Bitta fayl uchun `BOT_TOKEN` kerak.
- Har fayl `[OK]`/`[XATO]`/`[SKIP]` chiqaradi va nolga teng bo'lmagan kod bilan tugaydi; `run_tests.sh` oxirida yiqilganlarni ro'yxatlaydi.
- **Haqiqiy PostgreSQL** testlari uchun env: `MINIAPP_`, `P0_`, `STEP5_`, `FINAL_`, `RBAC_`, `INTEGRITY_`, `LOAD_`, `STRESS_` + `TEST_DATABASE_URL`
  (faqat SINOV bazasi; production emas). URL bo'lmasa shu testlar `SKIP`/BLOCKED bo'ladi. `refactor_step5_test` TOZA bazani kutadi.
- Real DB'siz testlar mock/fake bilan ishlaydi (Telegram API, AI provayderlari tarmoqsiz).

Muhim regressiya to'plamlari: scheduler (`scheduler_*`), yetkazish va takroriy yuborish, albom (`album_*`, `miniapp_album_test`),
Mini App (`miniapp_*_test.py`: auth, xavfsizlik auditi, yozuv, tahrirlash, statik, navigatsiya, sozlamalar), tarif (`tariff_tiers_test`),
to'lov (`stars_rejected_payment`, `p0_concurrency_test`), lokalizatsiya paritet testlari, parallel/yuklama (`concurrency_load_test`).

## Mini App (frontend)

```bash
cd miniapp
npm ci
npm test              # vitest (jsdom)
npx tsc --noEmit      # tur tekshiruvi
npm run build         # tsc + vite + scripts/check-dist.mjs + compress-dist.mjs
```

## CI (`.github/workflows/ci.yml`)

Ishlar: `test` (lint gate + `tests/run_tests.sh`), `miniapp` (vitest + typecheck/build + `npm audit` maslahat), `docker` (image yig'ish, tini/curl/non-root/Mini App dist tekshiruvi).
CI toza PostgreSQL'da ishlaydi, shuning uchun migratsiya tartibi xatolari lokal (to'lgan) bazada ko'rinmasligi mumkin.

## Ma'lum holatlar

- `concurrency_load_test`, `load_stress_mock_test` — yuklamaga sezgir; yuklangan mashinada yoki CI'da ba'zan yiqiladi, toza mashinada o'tadi.
- Testlar sanaga bog'liq bo'lmasligi kerak (real vaqtga nisbatan hisoblang).
