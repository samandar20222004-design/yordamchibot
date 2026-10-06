# PostAssist V2 — YORDAMCHIBOT (Telegram AI Kanal Operatori)

Telegram kanallar uchun **AI kontent studiyasi + rejalashtiruvchi + monetizatsiya**
boti: Magic Post (5 uslub), 📸 Image→Post, 🎙 Voice→Post, 📊 Post Score,
URL→Post va RSS manbalar, ♻️ Content Recycle, 🧠 Channel DNA, ⏰ Smart Best Time,
🚀 7 kunlik Autopilot, 📋 shablonlar, 👥 jamoa rollari va tasdiqlash oqimi,
💳 Stars + karta (Uzcard/Humo) to'lovlari, RBAC admin paneli, 🩺 health monitoring.

* **Tillar:** o'zbek / rus / ingliz (100% paritet — `tests/i18n_full_parity_test.py`)
* **DB:** PostgreSQL (Neon / Render) — `schema.sql` idempotent, `main.py` startda qo'llanadi
* **AI:** Gemini → Groq → OpenRouter → (Mistral/Cerebras/SambaNova/Cloudflare) zanjiri,
  circuit-breaker + atomik kvota + fail-closed refund
* **State/Cache:** Redis (ixtiyoriy, `REDIS_URL`) ⇄ In-Memory (TTL+LRU) —
  circuit breaker bilan avtomatik fallback; rate limitlar **granular**
  (matn / `(user_id, callback_action)` / AI / URL-RSS) — `docs/reports/PHASE2_RATE_LIMITING_REDIS_report.md`

## 📚 Hujjatlar

| Fayl | Nima haqida |
|---|---|
| **[DEPLOYMENT.md](DEPLOYMENT.md)** | **Serverga chiqarish: Render / VPS (systemd) / Docker — qadam-baqadam** |
| [.env.example](.env.example) · [telegram_bot/.env.example](telegram_bot/.env.example) | Barcha muhit o'zgaruvchilari (kononik, dublikatsiz, ikkala nusxa parityetda) |
| **[PHASE2_RATE_LIMITING_REDIS_report.md](docs/reports/PHASE2_RATE_LIMITING_REDIS_report.md)** | **Rate limiting + Redis/Distributed state arxitekturasi (Phase 2)** |
| [telegram_bot/README.md](telegram_bot/README.md) | Funksiyalar, buyruqlar, arxitektura va bosqich bo'yicha to'liq hujjat |
| [`docs/reports/`](docs/reports/) | Audit va bosqich yakunlari hisobotlari (`AUDIT_*.md`, `PHASE*_report.md`, …) |

## ⚡️ Tezkor start (lokal)

```bash
cd telegram_bot
python3 -m venv ../venv && source ../venv/bin/activate
pip install -r requirements.txt
set -a; . ../.env; set +a          # .env → process muhiti (dotenv ishlatilmaydi!)
python main.py                      # bot + web health-server 0.0.0.0:$PORT
```

Serverga chiqarish (Render / VPS / Docker) — **[DEPLOYMENT.md](DEPLOYMENT.md)**.

## ✅ Testlar va lint (repozitoriy ildizida)

```bash
# 1) Muhit
python3 -m venv /tmp/venv
/tmp/venv/bin/pip install -r telegram_bot/requirements.txt -r tests/requirements-test.txt

# 2) Lint gate (CI'dagi bilan bir xil)
cd telegram_bot && /tmp/venv/bin/ruff check . --select=E9,F63,F7,F82 \
  && /tmp/venv/bin/flake8 . --select=E9,F63,F7,F82 --max-line-length=127; cd ..

# 3) TO'LIQ suite (barcha bosqichlar: Phase A/B/C/D/E + regressiya)
PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
```

## 🧱 Tuzilish

```
telegram_bot/
├── main.py            # ishga tushirish + scheduler + graceful shutdown
├── config.py          # barcha env sozlamalari (yagona manba)
├── database.py        # PostgreSQL pool, idempotent sxema, tranzaksiyalar
├── scheduler.py       # post yuborish (idempotentlik, FloodWait, recovery)
├── handlers/          # 34 modul: UI oqimlari (Magic Post, Autopilot, team, admin…)
├── services/ai/       # provayder zanjiri, validator, orkestrator, kvota, concurrency
├── services/cache_backend.py  # State/cache adapter: Redis ⇄ In-Memory (opt-in, circuit breaker)
├── middlewares/       # FSM tozalash, RBAC, GRANULAR rate limiting (per-action TTL)
├── services/channels/ # DNA, best time, monitoring, team, recycle
├── keyboards/ translations/ locales/   # UI + uz/ru/en i18n
tests/                 # yagona test suite + run_tests.sh
docs/reports/          # audit va bosqich hisobotlari
```
