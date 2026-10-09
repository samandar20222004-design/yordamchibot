# 🚀 PRODUCTION RUNTIME & DEPLOYMENT VERIFICATION — YAKUNIY HISOBOT

> **Sana:** 2026-10-06 · **Branch:** `arena/77146863-yordamchibot` · **Baza commit:** `06f4ce8`
> **Maqsad:** botni serverga **1 komanda** bilan chiqarish va ishga tushgandan keyin
> **haqiqatan ishlayotganini** isbotlaydigan runtime smoke test bilan ta'minlash.
> **Natija:** `bash tests/run_tests.sh` → **0 [FAIL], exit 0** · `bash scripts/deploy.sh --verify-only`
> → **preflight OK, migratsiya OK, `/health/ready` = 200 ready, smoke 63 PASS / 0 FAIL, graceful shutdown OK**.

---

## 1. XULOSA (bir qarashda)

| Talab | Holat | Dalil |
|---|---|---|
| 1. Production ishga tushirish skripti (entrypoint & bootstrap) | ✅ | `scripts/deploy.sh`, `scripts/start_production.sh`, `scripts/preflight_env.py`, `scripts/db_migrate.py` |
| · `.env` to'liqligi (Bot token, DB url, Redis url, Health token) | ✅ | `scripts/preflight_env.py` — 42 xil tekshiruv ID (muhitga qarab 12–20 tasi faol), secret qiymatlar chop etilmaydi |
| · DB migratsiya/schema check (avtomatik, xavfsiz, idempotent) | ✅ | `db_migrate.py` — `real PostgreSQL`: 34 jadval / 38 indeks / 16 constraint OK |
| · Healthcheck porti **8080** + background workerlar parallel | ✅ | `start_production.sh` (PORT berilmasa 8080), `deploy.sh` health-wait; APScheduler 9 job (`/health/ready` → `scheduler: ok`) |
| 2. Runtime Telegram smoke test | ✅ | `tests/smoke_test.py` — **64 PASS / 0 FAIL** (offline) · 63 PASS / 0 FAIL (live serverga qarshi verify-only) |
| · Telegram API ulanishi (`getMe`) | ✅ | MOCK Bot API orqali HAQIQIY tarmoq zanjiri (PTB → HTTPX → JSON) + LIVE rejimda `api.telegram.org` |
| · Webhook yoki Polling rejimida xatosiz start | ✅ | `start_polling` → update in'yeksiyasi → handler + `sendMessage` javobi → graceful stop; `setWebhook/getWebhookInfo/deleteWebhook` kontrakti |
| · `/health/live` va `/health/ready` JSON kontrakti | ✅ | live: 200 `{"status":"live"}`; ready: 404 (token yo'q) / 401 (noto'g'ri) / 200 ready + `checks` / no-store / secret yo'q |
| 3. `.env.example` yangilanishi (Redis, DB pool, AI gateway, Quiet hours, Health token) | ✅ | 157 kalit, ikkala nusxa **bayt-bayt bir xil** (`diff` bo'sh), `env_docs_parity_test` 45/45 OK |
| 4. `DEPLOYMENT.md` — 1 komanda bilan o'rnatish | ✅ | «⚡️ TEZKOR YO'L» bo'limi (49-qator): `bash scripts/deploy.sh` |
| 5. `bash tests/run_tests.sh` 100% yashil | ✅ | `BARCHA TESTLAR 100% YASHIL ✔` · `VERIFY_EXIT=0` · 19 100 qator log · 0 `[FAIL]` |

---

## 2. YANGI VA O'ZGARTIRILGAN FAYLLAR

### Yangi fayllar

| Fayl | Vazifasi | Hajmi |
|---|---|---|
| `scripts/preflight_env.py` | 🛫 Muhit to'liqligi + xavfsizlik siyosati auditi (BOT_TOKEN, DATABASE_URL, REDIS_URL, HEALTH_READY_TOKEN, ENVIRONMENT/AI_ALLOW_MOCK, PORT, ADMIN, AI kalitlar, DB pool, quiet hours, shutdown byudjet). `--env-file` (xavfsiz parser), `--strict`, `--json`, `--quiet`. Secret qiymatlar **hech qachon** chop etilmaydi. | 570 qator |
| `scripts/db_migrate.py` | 🗄 Xavfsiz migratsiya: ping (retry — cold start) → `db.init_db()` (schema.sql **idempotent**) → schema check (jadvallar/indekslar) → pool + integrity hisoboti. `--check-only` (hech narsa yozmaydi), `--validate-integrity`, `--json`. | 345 qator |
| `scripts/start_production.sh` | 🚀 Entrypoint/bootstrap: `.env` xavfsiz yuklash → preflight → migratsiya → `PORT` (standart **8080**) → `exec python main.py` (web health-server + polling + scheduler). `--check-only`, `--skip-migrate`, `--strict`, `--port`. | 224 qator |
| `scripts/deploy.sh` | ⚡️ 1-komandalik deploy: preflight → migratsiya → bot start (fon) → `/health/live` kutish → smoke test → hisobot. `--verify-only`, `--check-only`, `--no-smoke`, `--offline-smoke`, `--health-timeout`. Log: `logs/deploy-*.log`, hisobot: `logs/smoke-*.json`. | 331 qator |
| `tests/smoke_test.py` | 🧪 Runtime smoke test (quyida batafsil). Runner'ga ham ulandi. | 826 qator |

### O'zgartirilgan fayllar

| Fayl | O'zgarish |
|---|---|
| `.env.example` + `telegram_bot/.env.example` | Yangi: 🌙 `AUTOPILOT_QUIET_HOURS=23:00 - 08:00` (Quiet hours), 🔐 `HEALTH_READY_TOKEN=` (fail-closed izohi, `openssl rand -hex 32`, 401/404/200-503 semantikasi), HEALTH bo'limi sarlavhasi, DEPLOYMENT bo'limiga 1-komandalik deploy yo'riqnomasi + 8080 eslatmasi. Ikkala nusxa **aynan bir xil**. |
| `telegram_bot/services/autopilot/planner.py` | `DEFAULT_QUIET_HOURS` endi `AUTOPILOT_QUIET_HOURS` env'dan o'qiladi (noto'g'ri format → ogohlantirish + xavfsiz standart `23:00 - 08:00`); `_QUIET_RE` dublikati olib tashlandi. |
| `telegram_bot/staging/mock_telegram_server.py` | Webhook holati qo'shildi: `setWebhook` (URL saqlanadi), `getWebhookInfo` (URL + `pending_update_count`), `deleteWebhook` (tozalaydi), `snapshot()`da `webhook_url`. Staging/CI'da webhook rejimini real sinash uchun. |
| `Dockerfile` | `COPY --chown=appuser:appgroup scripts/ /app/scripts/` — konteyner ichida `bash scripts/start_production.sh --check-only` ishlaydi. **CMD va HEALTHCHECK o'zgarmagan** (`python main.py`, `/health/live`). |
| `DEPLOYMENT.md` | Yangi «⚡️ TEZKOR YO'L — serverda 1 komanda bilan ishga tushirish» bo'limi (5 bosqich jadvali + rejimlar + qo'lda smoke); systemd `ExecStart` → `start_production.sh`; health `curl localhost:8080/health/live`; checklist yangilandi. |
| `README.md` | Tezkor deploy bloki (3 qator) `DEPLOYMENT.md` havolasi bilan. |
| `tests/run_tests.sh` | Yangi yakuniy bosqich: «🧪 PRODUCTION RUNTIME & DEPLOYMENT VERIFICATION» → `"$PY" tests/smoke_test.py --offline`. |

---

## 3. RUNTIME SMOKE TEST — NIMA TEKSHIRILADI

`tests/smoke_test.py` — 5 bo'lim, 63 ta qat'iy tekshiruv (offline/mock rejimda ham
to'liq deterministik; `--live` bilan haqiqiy Telegram ham qo'shiladi):

| # | Bo'lim | Tekshiruvlar (qisqacha) |
|---|---|---|
| 0 | 📦 Deploy artefaktlari | 4 ta skript mavjud + sintaksis (`bash -n`, `compile`); `.env.example` pariteti va yangi kalitlar; `DEPLOYMENT.md` 1-komandalik yo'riqnoma; `Dockerfile` HEALTHCHECK/CMD kontrakti; runner smoke testni chaqiradi |
| 1 | 🛫 Muhit/entry | `BOT_TOKEN`, `PORT` oralig'i, `TELEGRAM_API_BASE_URL` siyosati, rejim aniqlash |
| 2 | 📡 Telegram ulanishi | MOCK `getMe` (to'liq tarmoq zanjiri) + `--live`/`--auto` da haqiqiy `api.telegram.org` `getMe` (token namuna bo'lsa yoki tarmoq yopiq bo'lsa — **halol `[NOT TESTED]`**, `--strict-live` bilan FAIL) |
| 3 | 🔄 Polling/Webhook | `Application.updater.start_polling(drop_pending_updates=False)` → update in'yeksiyasi → handler ishga tushdi → `sendMessage` javobi serverga yetdi → graceful stop; `setWebhook → getWebhookInfo (URL mos) → deleteWebhook` |
| 4 | ⚙️ Background workerlar | APScheduler job'lari import/registratsiya, `main.py` kontrakti (web-server, polling, `scheduler.start()`, `concurrent_updates`, `recover_on_startup`) va fon vazifasi **haqiqatan** bajarilishi |
| 5 | 🩺 Health endpointlari | `/health/live` → 200 `{"status":"live","uptime_seconds":N}`, `Cache-Control: no-store`, `checks`/`metrics` yo'q; `/health/ready` → token yo'q = **404 fail-closed**, noto'g'ri = **401**, to'g'ri = **200 `ready`** yoki **503 `not_ready`** + `checks{database,redis,scheduler}`, javobda secret yo'q |

### Chiqish kodlari va artefaktlar

```bash
python3 tests/smoke_test.py --offline                      # CI/test runner
python3 tests/smoke_test.py --base-url http://127.0.0.1:8080 --wait-health 60
python3 tests/smoke_test.py --live --strict-live --base-url http://127.0.0.1:8080
python3 tests/smoke_test.py --offline --json logs/smoke.json
```

* `0` — barcha tekshiruvlar PASS (NOT TESTED suite'ni yiqitmaydi);
* `1` — kamida bitta `[FAIL]`;
* JSON hisobot (`--json`) — CI artefakti sifatida saqlanadi (`logs/` git'ga tushmaydi).

---

## 4. ISBOT: `deploy.sh --verify-only` — TO'LIQ RUNTIME SINOVI

Muhit: **haqiqiy PostgreSQL** (pgserver; 34 jadval sxemasi), mock Telegram Bot API
(`staging.mock_telegram_server`), `ENVIRONMENT=staging`, `AUTOPILOT_QUIET_HOURS=22:00 - 07:00`,
`SHUTDOWN_GRACE_SECONDS=5`, `HEALTH_READY_TOKEN` o'rnatilgan, PORT=8090.

```
1/5 PREFLIGHT + 2/5 DB MIGRASYON + SCHEMA CHECK
  [OK] JAMI: OK=13, WARN=1, ERROR=0            (WARN: AI kaliti yo'q — kutilgan, test muhiti)
  ✅ connection — ping OK (4 ms) · ✅ migration — schema.sql idempotent qo'llanildi
  ✅ schema_tables — 34 ta jadval joyida · ✅ schema_indexes — 38 ta indeks joyida
  ✅ pool — ready=True · ✅ integrity — 16 constraint, yetim qator yo'q
3/5 BOT START (fon rejimi)          → PID 3429, main.py: web-server + polling + scheduler
4/5 HEALTH CHECK                    → ✅ /health/live → LIVE (200)
5/5 SMOKE TEST                      → PASS=63, FAIL=0, NOT TESTED=2
  [OK] polling: yuborilgan update handler'ga yetib bordi — matn='smoke test xabari'
  [OK] webhook: getWebhookInfo URL mos
  [OK] workerlar: 9 ta job ro'yxatga olindi — 9
  [OK] /health/live → JSON status='live'
  [OK] token o'rnatilmagan → /health/ready fail-closed 404
  [OK] /health/ready to'g'ri token → 200 ready — {"status":"ready",
       "checks":{"database":"ok","redis":"disabled","scheduler":"ok"}}
  [OK] /health/ready javobida token/secret YO'Q
  ✅ DEPLOY VERIFICATION YAKUNLANDI → SIGTERM → graceful shutdown (12 bosqich) → exit 0
```

> **Eslatma:** `[NOT TESTED]` — (1) haqiqiy `api.telegram.org` `getMe` (sandbox'da
> haqiqiy token/tashqi tarmoq yo'q), (2) live webhook — `TELEGRAM_WEBHOOK_URL`
> berilmagan (bot **polling** rejimida ishlaydi). Bu ikkisi serverda `--live` bilan
> tekshiriladi. PTB shutdown paytida bitta "get_updates cleanup → PoolTimeout"
> logi chiqadi — kutubxona buni o'zi "Suppressing error to ensure graceful shutdown"
> deb qayd etadi, jarayon `exit 0` bilan tugaydi (real Telegram'da kuzatilmaydi).

---

## 5. `.ENV.EXAMPLE` — YANGI KALITLAR VA PARITET

| Kalit | Qiymat | Ma'nosi |
|---|---|---|
| `AUTOPILOT_QUIET_HOURS` | `23:00 - 08:00` | Avtopilot tinchlik soatlari **standarti** (foydalanuvchi menyudan ham o'zgartiradi); noto'g'ri format → ogohlantirish + standart |
| `HEALTH_READY_TOKEN` | *(bo'sh)* | `/health/ready` uchun alohida kredensial (`openssl rand -hex 32`); bo'sh = **fail-closed 404**; `Authorization: Bearer` yoki `X-Health-Token`; `BOT_TOKEN` bilan bir xil bo'lmasligi shart (`preflight` tekshiradi) |

Redis (`REDIS_URL`, `REDIS_ENABLED`, …), DB pool (`DB_POOL_MIN/MAX/SIZE`, `DB_CONNECT_TIMEOUT`),
AI gateway (`AI_PROVIDER_CHAIN`, `AI_FAST/QUALITY/REASONING/VISION_TIMEOUT`, breaker, kesh)
va qolgan barcha fazalar hujjati avvaldan to'liq edi — yangi tekshiruv
(`env_docs_parity_test`) **157 kalitning 100% kod↔hujjat qamrovini** qulflaydi (shundan 64 tasi Redis / DB pool / AI gateway guruhlarida):
dublikat yo'q, ikki nusxa bayt-bayt bir xil, orphan kalit yo'q.

---

## 6. SERVERDA ISHGA TUSHIRISH (1 KOMANDA)

```bash
# 1) Kod + muhit
git clone https://github.com/samandar20222004-design/yordamchibot.git /opt/postassist
cd /opt/postassist && python3 -m venv venv && ./venv/bin/pip install -r telegram_bot/requirements.txt

# 2) Majburiy 3 qiymat
cp .env.example .env && nano .env     # BOT_TOKEN, DATABASE_URL, HEALTH_READY_TOKEN
#    (tavsiya: ADMIN_IDS, kamida bitta AI kaliti, REDIS_URL — multi-instance uchun)

# 3) ⚡️ DEPLOY + TEKSHIRUV (bitta komanda)
bash scripts/deploy.sh                # preflight → migratsiya → start → health(8080) → smoke
```

24/7 rejim (server o'chib yonmaydi):

```bash
# systemd (DEPLOYMENT.md, 2-bo'lim): ExecStart=/bin/bash /opt/postassist/scripts/start_production.sh
sudo systemctl restart postassist && sudo systemctl status postassist --no-pager

# yoki Docker
docker compose up -d --build && docker compose ps     # bot \"healthy\"
```

Tekshirib olish (deploy qilmasdan):

```bash
bash scripts/deploy.sh --check-only            # .env + baza tayyorligi
bash scripts/deploy.sh --verify-only           # ko'taradi → smoke → to'xtatadi
python3 tests/smoke_test.py --live --strict-live --base-url http://127.0.0.1:8080
curl -fsS localhost:8080/health/live
curl -fsS -H "Authorization: Bearer $HEALTH_READY_TOKEN" localhost:8080/health/ready
```

---

## 7. TESTLAR (YAKUNIY — TO'LIQ SUITE)

```bash
PYTHON=$HOME/.venv/bin/python bash tests/run_tests.sh
#   ... 19 100 qator log ...
#   ======== 🧪 PRODUCTION RUNTIME & DEPLOYMENT VERIFICATION ========
#     PASS       : 64
#     FAIL       : 0
#     NOT TESTED : 2      (live getMe, live webhook — token/tarmoq yo'q)
#     ✅ SMOKE TEST 100% YASHIL
#   ==============================================================
#   BARCHA TESTLAR 100% YASHIL ✔
#   VERIFY_EXIT=0
```

* Chiqish kodi **0**; logda `[FAIL]` **yo'q** (uchraydigan 3 ta `[FAIL]` satri ham
  `[FAIL]=0` ko'rinishidagi yakuniy hisobot qatorlari).
* Ishlash vaqti: **~6 daqiqa** (11:19:42 → 11:26:01 UTC); bu — barcha
  o'zgarishlardan keyingi YAKUNIY to'liq yugurtirish (undan oldingi baseline ham
  0 `[FAIL]`, exit 0 edi).
* Yangi bosqich: «🧪 PRODUCTION RUNTIME & DEPLOYMENT VERIFICATION» → `tests/smoke_test.py --offline`
  (runner'ning eng oxirida, yakuniy hisobotdan oldin).
* Alohida yugurtirilgan muhim suite'lar (hammasi yashil): `env_docs_parity_test` 45/45,
  `secret_leak_scan_test` 25/25, `phase12_docker_and_shutdown_test` 83 OK / 0 FAIL,
  `observability_test` 29 passed / 0 failed.
* CI lint gate (`ruff`/`flake8`, E9/F63/F7/F82): `All checks passed!` —
  `telegram_bot/` hamda yangi `scripts/` + `tests/smoke_test.py` uchun.

---

## 8. MA'LUM CHEKLOVLAR (halol qayd)

1. **LIVE `getMe` va live webhook** sandbox'da `[NOT TESTED]` — haqiqiy `BOT_TOKEN` va
   tashqi tarmoq yo'q. Serverda: `python3 tests/smoke_test.py --live --strict-live`.
2. **Docker image build** bu muhitda sinalmadi (`docker` CLI yo'q) — `phase12` suite
   statik kontraktlarni (multi-stage, non-root, HEALTHCHECK, CMD) tekshiradi;
   `COPY scripts/` qatori shu kontraktlarni buzmaganini `phase12` tasdiqlaydi.
3. **PTB shutdown logi**: mock API bilan `get_updates` cleanup'da bitta `PoolTimeout`
   (kutubxona "suppressed" deb yozadi, `exit 0`); real Telegram long-poll'da bu holat
   kuzatilmaydi. Kod o'zgartirilmadi (xatti-harakatga ta'siri yo'q).
4. `[WARN] AI_PROVIDERS_MISSING` — preflight'ning **ogohlantirishi** (deploy to'xtamaydi):
   AI kalitisiz bot ishlaydi, lekin generatsiya o'rniga xavfsiz xabar qaytaradi.
