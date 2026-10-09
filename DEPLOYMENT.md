# 🚀 PostAssist V2 (YORDAMCHIBOT) — DEPLOYMENT QO'LLANMASI

> Maqsad: botni **serverda (Render yoki VPS) 24/7** ishga tushirish — qisqa va lo'nda.
> Barcha sozlamalar faqat **muhit o'zgaruvchilari** orqali (`python-dotenv`
> **ishlatilmaydi**, `.env` faylini ilova o'zi o'qimaydi — quyga qarang).

Bog'liq fayllar: `telegram_bot/main.py` (kirish nuqtasi) · `Dockerfile` ·
`docker-compose.yml` · `.env.example` (yagona kanonik env hujjati) ·
`telegram_bot/README.md` (funksiyalar bo'yicha to'liq hujjat).

---

## 0. Ishga tushirishdan oldin (5 daqiqa)

| # | bajariladigan ish |
|---|---|
| 1 | **@BotFather** → `/newbot` → `BOT_TOKEN`. |
| 2 | **@userinfobot** → o'z ID'ingiz → `ADMIN_IDS=111` (bir nechta: `ADMIN_IDS=111,222`; legacy `ADMIN_ID` ham o'qiladi). |
| 3 | **PostgreSQL**: Neon yoki Render Postgres — `DATABASE_URL` (`?sslmode=require` bilan, pooler-manzil recommended). |
| 4 | Botni kanalga **admin** qilib qo'shing (kamida *Post Messages*). |
| 5 | Kamida **bitta AI kaliti** (`GEMINI_API_KEY` / `GROQ_API_KEY` / `OPENROUTER_API_KEY`). |
| 6 | Kalitlarni `.env` ga yozmangdan avval: `.env` — `.gitignore`'da, repoga tushmaydi. |

**Production uchun ikkita "tetralgan" qiymat (P0-A):**

```
ENVIRONMENT=production     # bo'sh/yuqolsa ham default = production (fail-closed)
AI_ALLOW_MOCK=0            # Mock (shablon) javoblar production'da O'CHIQ
```

> AI provayderlari ishlamasa bot **soxta matn chiqarmaydi**: xavfsiz xabar
> qaytadi va bron qilingan AI kvotasi to'liq qaytariladi.
> `ENVIRONMENT=development|test` yoki `AI_ALLOW_MOCK=1` — faqat lokal sinov uchun.

To'lovlar uchun (ixtiyoriy): `CARD_NUMBER`, `CARD_HOLDER`, `PAYMENT_ADMIN_USERNAME`
— karta rekvizitlari **kodda yo'q**, faqat shu o'zgaruvchilardan olinadi.

**💬 Qo'llab-quvvatlash (4-QISM) — adminlar uchun muhim:** foydalanuvchi
`👤 Profil → [💬 Qo'llab-quvvatlash]` orqali **bitta xabar** yozadi (FSM darhol
yopiladi — ketma-ket yozish adminga spam bo'lib bormaydi) va murojaat
`ADMIN_IDS` ro'yxatidagi **har bir** adminga yuboriladi. Javob berish uchun
admin oddiy Telegram **«Reply»** funksiyasidan foydalanadi — javob avtomatik
ravishda foydalanuvchiga yetib boradi. Shu sababli productionda `ADMIN_IDS`
(bir nechta admin) to'ldirilgan bo'lishi tavsiya etiladi; bo'sh bo'lsa
foydalanuvchiga murojaat yetib bormaganini bildiruvchi halol javob qaytadi.

---

## ⚡️ TEZKOR YO'L — serverda 1 komanda bilan ishga tushirish (tavsiya)

Production (VPS yoki Docker) uchun **bitta buyruq** yetadi — u muhitni
tekshiradi, bazani migratsiya qiladi, botni ko'taradi, health va Telegram
smoke testini o'tkazadi:

```bash
cd /opt/postassist                 # repo klonlangan papka (1-bo'limga qarang)
cp .env.example .env && nano .env  # faqat 3 ta qiymat majburiy:
                                   #   BOT_TOKEN, DATABASE_URL, HEALTH_READY_TOKEN
bash scripts/deploy.sh             # ⚡️ PREFLIGHT → MIGRATION → START → HEALTH → SMOKE
```

`bash scripts/deploy.sh` ichida nima bo'ladi:

| # | Bosqich | Nima tekshiriladi / bajariladi |
|---|---|---|
| 1 | 🛫 **Preflight** | `.env` to'liqligi: `BOT_TOKEN`, `DATABASE_URL` (+`sslmode`), `REDIS_URL`, `HEALTH_READY_TOKEN`, `ENVIRONMENT`/`AI_ALLOW_MOCK` (P0-A fail-closed), `PORT`, `ADMIN_*`, AI provayder kalitlari, DB pool izchilligi, quiet hours formati (`scripts/preflight_env.py`) |
| 2 | 🗄 **Migration** | `schema.sql` **idempotent** qo'llaniladi + schema check (jadvallar/indekslar/integrity; baza "cold start"da retry) — `scripts/db_migrate.py` |
| 3 | 🚀 **Start** | `telegram_bot/main.py`: web health-server `0.0.0.0:$PORT` (standart **8080**), Telegram polling, APScheduler workerlari (postlar, tozalash, RSS, obuna sweep) — parallel |
| 4 | 🩺 **Health** | `GET /health/live` 200 (`{"status":"live"}`) bo'lguncha kutadi (standart 60 s) |
| 5 | 🧪 **Smoke test** | `tests/smoke_test.py`: Telegram `getMe`, polling/webhook rejimi, `/health/live` + `/health/ready` JSON kontraktlari → natija `logs/smoke-<sana>.json` |

Foydali rejimlar:

```bash
bash scripts/deploy.sh --check-only      # preflight + HAQIQIY migratsiya (schema.sql qo'llaniladi); bot yo'q
bash scripts/deploy.sh --verify-only     # ko'taradi, tekshiradi, to'xtatadi (CI/staging)
bash scripts/deploy.sh --offline-smoke   # smoke testni mock Telegram bilan (tashqi tarmoqsiz)
bash scripts/deploy.sh --strict          # ogohlantirish ham deploy'ni to'xtatadi
bash scripts/deploy.sh --no-smoke        # smoke testni o'tkazib yuborish
```

Alohida skriptlar (deploy.sh ularni o'zi chaqiradi):

```bash
bash scripts/start_production.sh                # preflight → migratsiya → bot (foreground)
bash scripts/start_production.sh --migrate-only # preflight + HAQIQIY migratsiya + port band emas (bot yo'q)
bash scripts/start_production.sh --check-only   # READ-ONLY: preflight + sxema HOLATI + port band emas (hech narsa yozilmaydi)
python3 scripts/preflight_env.py --strict --json   # env auditi (secret qiymatlari chiqmaydi)
python3 scripts/db_migrate.py --check-only         # sxema holati (hech narsa yozilmaydi)
```

> ⚠️ **`--check-only` va `--migrate-only` farqi.**
> `--check-only` **hech narsa yozmaydi** (faqat mavjud sxemani tekshiradi) — bo'sh
> bazada u "schema_tables yetishmayapti" deb qaytaradi, bu **xato emas**, read-only
> rejimning tabiiy natijasi. Sxemani **qo'llash** kerak bo'lsa `--migrate-only`
> (yoki oddiy `start_production.sh`) ishlatiladi. `bash scripts/deploy.sh` 2-bosqichda
> aynan `--migrate-only` dan foydalanadi — shu sababli **yangi (bo'sh) bazada ham
> 1-komandalik deploy ishlaydi**.

Smoke testni qo'lda (ishlayotgan serverga qarshi):

```bash
python3 tests/smoke_test.py --base-url http://127.0.0.1:8080 --wait-health 60
python3 tests/smoke_test.py --live --strict-live --base-url http://127.0.0.1:8080   # haqiqiy getMe
```

Chiqish kodlari: `0` — muvaffaqiyat; `1` — preflight/migratsiya/health/smoke xatosi.
Loglar: `logs/deploy-<sana>.log` (git'ga tushmaydi — `.gitignore`).

---

## 1. A variant — Render (Native Python, tavsiya etilgan)

1. **New + → Web Service** → GitHub repozitoriysini ulang (`samandar20222004-design/yordamchibot`).
2. Sozlamalar:

   | Maydon | Qiymat |
   |---|---|
   | Root Directory | `telegram_bot` |
   | Runtime | **Python 3** |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `python main.py` |
   | Instance Type | Starter+ (**Free/ECO plan'da service uxlab qoladi → scheduler to'xtaydi**) |

3. **Environment Variables** — `.env.example` faylidagi kalitlarni kiriting.
   Majburiy: `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_IDS` (+ `ENVIRONMENT=production`,
   `AI_ALLOW_MOCK=0`, AI kalitlari, `CARD_*`).
   `PORT` **o'zingiz qo'ymang** — Render o'zi beradi (web-server shu portda
   `0.0.0.0:$PORT` da turadi). Render'ning eski `postgres://…` URL'ini bot
   avtomatik `postgresql://` sxemasiga o'tkazadi (`config.py`).
4. **Health Check Path**: `/health/live` (Readiness uchun `/health/ready`).
5. Deploy → logda: `Bot ishga tushdi…`, `Web server … 0.0.0.0:<PORT>`,
   `Sxema tekshiruvi OK: N/N jadval`.
6. Telegram'da `/start` → ishlaydi; `/health` (OWNER) → DB/Scheduler/AI/Tizim hisoboti.

**Eslatmalar**

* Render fayl tizimi **ephemeral** (restartda hammasi o'chadi) — bu normal.
  Post **duplikatlariga qarshi kafolat bazada**: `post_deliveries` + `FOR UPDATE
  SKIP LOCKED` + `recover_stale_processing_posts`. `SENT_JOURNAL_PATH` bo'sh
  qoldirilsa (tavsiya) fayl-journal ishlatilmaydi; eskizatsiya qilib aniq yo'l
  bersangiz — Render **Disk** ulab `/var/data/...` ga qarating.
* Postgres **bitta** (Neon/Render) — lokal DB sozlamang.
* Restart/signallar (SIGTERM) **graceful**: in-flight postlar tugadi-mi kutiladi,
  yuborilmaganlari `pending` ga qaytadi, `processing` qolganlari startdaki
  `recover_on_startup()` bilan tiklanadi.

## 1-b. Render Docker varianti (ixtiyoriy)

Root Directory = **repozitoriy ildizi** (`.`), Runtime = **Docker**,
Dockerfile = `Dockerfile`. Render yig'adi `python:3.11-slim` + `tini` +
`HEALTHCHECK` (env: `BOT_TOKEN`, `DATABASE_URL`, `AI_*`, `CARD_*`).
`docker-compose.yml` dagi lokal `postgres` xizmati Render'da **kerak emas** —
 DATABASE_URL Neon/Render'ga qaratiladi.

---

## 2. B variant — VPS (Ubuntu 22.04/24.04, systemd)

### P0/P1 hardening runtime sozlamalari

`.env.example` dagi quyidagi qiymatlar production'da ham aniq ko'rsatilishi kerak:

| O'zgaruvchi | Standart | Vazifasi |
|---|---:|---|
| `ANALYTICS_MAX_BATCH_IDS` | `100` | Analytics channel picker uchun bitta bounded query limiti; N+1 va haddan tashqari katta klaviatura oldini oladi. |
| `QUIET_STAGGER_MIN_SECONDS` | `30` | Quiet-hours tugashida postlar orasidagi minimal qadam. |
| `QUIET_STAGGER_MAX_SECONDS` | `180` | Quiet-hours herd oynasining yuqori chegarasi. |
| `CHANNEL_STAGGER_MIN_SECONDS` | `60` | Bir kanal ketma-ket postlari orasidagi minimum. |

Qiymatlar `config.py` da parse qilinadi, scheduler staggering oynasini
0–3600 soniya bilan chegaralaydi. `ANALYTICS_MAX_BATCH_IDS` kamida 1 bo'lishi
kerak. Deploydan oldin migration'ni idempotent qayta tekshiring:

```bash
python3 scripts/db_migrate.py --check-only
bash scripts/deploy.sh --verify-only --offline-smoke
```

`--verify-only` preflight, schema migration/check, bot start, liveness health
va smoke bosqichlarini ketma-ket bajaradi. `schema.sql` canonical manba,
`init_db()` fallback DDL esa compatibility safety-net hisoblanadi.

```bash
# 1) Kerakli paketlar
sudo apt-get update && sudo apt-get install -y git python3-venv python3-pip

# 2) Kod
sudo mkdir -p /opt/postassist && sudo chown $USER /opt/postassist
git clone https://github.com/samandar20222004-design/yordamchibot.git /opt/postassist
cd /opt/postassist

# 3) Virtual muhit + bog'liqliklar
python3 -m venv venv
./venv/bin/pip install -U pip
./venv/bin/pip install -r telegram_bot/requirements.txt

# 4) Muhit o'zgaruvchilari (systemd EnvironmentFile formati — export YO'Q)
sudo mkdir -p /opt/postassist/data
sudo chown -R www-data:www-data /opt/postassist        # service www-data ostida ishlaydi
sudo cp .env.example /etc/postassist.env
sudo chmod 600 /etc/postassist.env && sudo chown root:root /etc/postassist.env
sudo nano /etc/postassist.env      # BOT_TOKEN, DATABASE_URL, ADMIN_IDS, AI kalitlari...
```

`/etc/systemd/system/postassist.service`:

```ini
[Unit]
Description=PostAssist V2 Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/postassist
EnvironmentFile=/etc/postassist.env
# TAVSIYA: bootstrap skripti — preflight (env to'liqligi) → DB migratsiya/schema
# check → bot start. Muqobil (o'zgarishsiz): ExecStart=/opt/postassist/venv/bin/python main.py
# (WorkingDirectory=/opt/postassist/telegram_bot bilan).
ExecStart=/bin/bash /opt/postassist/scripts/start_production.sh
Restart=always
RestartSec=5
# SIGTERM → graceful shutdown (lifecycle + in-flight postlar)
TimeoutStopSec=30
KillSignal=SIGTERM
# Qattiqlik: faqat /app va /tmp yozadi
NoNewPrivileges=true
ProtectSystem=full
PrivateTmp=false
ReadWritePaths=/opt/postassist/data

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now postassist
sudo systemctl status postassist --no-pager
journalctl -u postassist -f          # loglar
curl -fsS localhost:8080/health/live    # {"status":"live",...}  (PORT berilmasa — 8080)
python3 tests/smoke_test.py --base-url http://127.0.0.1:8080   # to'liq smoke
```

Xavfsizlik devori: bot **long polling** ishlatadi — tashqaridan kiruvchi
port **kerak emas** (80/443 ochish, webhook, domen, TLS shart emas).
`PORT` faqat ichki health-check uchun (`0.0.0.0:$PORT`).

**Lokal/`screen` varianti (tezkor sinov):**

```bash
cd /opt/postassist
set -a; . ./.env; set +a                     # .env → process muhitiga
cd telegram_bot && ../venv/bin/python main.py
```

---

## 3. C variant — Docker Compose (lokal yoki VPS)

```bash
git clone https://github.com/samandar20222004-design/yordamchibot.git && cd yordamchibot
cp .env.example .env && nano .env            # DATABASE_URL Neon'ga qaratilsa: postgres xizmati ortiqcha
docker compose up -d                          # bot + lokal postgres (development)
docker compose ps                             # bot "healthy" bo'lishi kerak (HEALTHCHECK /health/live)
# Konteyner ICHIDA bootstrap/tekshiruv (image'da scripts/ ham bor):
docker exec postassist-bot bash scripts/start_production.sh --check-only
docker compose ps                             # healthcheck: "healthy"
docker compose logs -f bot
```

* Image ichida `WORKDIR=/app`, `CMD ["python","main.py"]` — ya'ni `.env.example`
  dagi `CARD_NUMBER`/`AI_*` qiymatlari `env_file: .env` orqali keladi.
* Post duplikatlari kafolati — DB (`post_deliveries`). `bot_data` volume faqat
  LEGACY `SENT_JOURNAL_PATH=/app/data/sent_journal.json` ni yoqtirgan holatda
  kerak (sinov/eski deploy); bo'sh holda volume shunchaki log/data uchun.
* Yangi versiyaga o'tish: `git pull && docker compose up -d --build`.
* Parolni hujjatga qoldirmang: `docker compose` lokal uchun; prod aks holda
  external PostgreSQL / Neon.

### 3.1 🗄 Redis — Ixtiyoriy (multi-instance uchun)

Rate limitlar va nozik holatlar **bir instance** ichida saqlansa, 2+ replica
ishlatilganda chegaralar yarim qoladi. Buning uchun Redis **opt-in**:

```bash
# lokal: compose faylida ixtiyoriy redis xizmati bor (prof bilan)
docker compose --profile redis up -d
# .env ga:
#   REDIS_ENABLED=1
#   REDIS_URL=redis://redis:6379/0          # docker-compose ichida
#   REDIS_URL=redis://localhost:6379/0      # lokal/VPS
# paketni o'rnatish (ixtiyoriy):
pip install "redis>=5.0"
```

Muhim qoidalar:

* **Redis yo'q bo'lsa ham bot to'liq ishlaydi** — holat In-Memory da qoladi
  (`services/cache_backend.py`, LRU + TTL, 512 MB RAM uchun chegarali).
* **Redis uzilsa bot qulamaydi**: avtomatik In-Memory fallback + circuit
  breaker (`REDIS_CIRCUIT_FAILURES` / `REDIS_CIRCUIT_COOLDOWN`).
* Tekshirish: bot logida `cache: Redis faol (prefix=postassist)` yoki
  `cache: Redis o'chirilgan — In-Memory rejim` qatori chiqadi.
* Render'da tashqi Redis (Upstash/Redis Cloud) `REDIS_URL=rediss://…` shaklida
  beriladi; `.env` da parol saqlanadi, loglarga chiqmaydi.

---

### 3.2 ⚡️ Payme webhook — ulash tartibi (avtomatik PRO)

Karta to'lov ekranidagi **«⚡️ Payme orqali to'lash»** tugmasi to'lovni Payme
callback'lari orqali tasdiqlaydi: PRO **darhol, admin aralashuvisiz** faollashadi.
Telegram Stars va chek (qo'lda tasdiqlash) usullari **o'zgarmaydi** va yonma-yon
ishlaydi. Endpoint botning health web-server'i bilan **bir xil `PORT`** da
ochiladi — alohida jarayon yoki port kerak emas.

**1) `.env` ga yozing** (batafsil izohlar `.env.example` da):

```dotenv
PAYME_MERCHANT_ID=<kassa id>
PAYME_KEY=<kassa kaliti>                    # sandbox: test kaliti
PAYME_CHECKOUT_URL=https://checkout.paycom.uz   # sandbox: https://test.paycom.uz
PAYME_ALLOW_REFUNDS=0                       # 1 = Payme orqali refund ruxsat
```

**2) Payme kabinetida** («Merchant API» / «Касса» bo'limi):

| Maydon | Qiymat |
|---|---|
| Endpoint (Callback URL) | `https://<sizning-domeningiz>/payments/payme` |
| Usul | `POST`, JSON-RPC 2.0 |
| Hisob maydoni (account field) | `order_id` (boshqa nom bo'lsa `PAYME_ACCOUNT_FIELD`) |
| Avtorizatsiya | `Basic base64(PAYME_LOGIN:PAYME_KEY)`, `PAYME_LOGIN` standart — `Paycom` |

**3) Botni qayta ishga tushiring** — `schema.sql` idempotent ravishda
`payme_orders` va `payme_transactions` jadvallarini yaratadi
(`scripts/db_migrate.py` ham ularni tekshiradi):

```bash
sudo systemctl restart postassist           # yoki: bash scripts/deploy.sh --verify-only
```

**Tekshirish (3 ta tezkor qadam):**

```bash
# 1) Endpoint ochiq va Payme protokolida javob qaytadi (HTTP 200 + -32504):
curl -i -X POST https://<domen>/payments/payme \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"CheckTransaction","params":{"id":"x"}}'

# 2) Kassa kaliti to'g'ri ulanganmi (endigina -31003/31050 emas, -32504 bo'lmasligi kerak):
curl -s -X POST https://<domen>/payments/payme \
     -u "Paycom:$PAYME_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"CheckTransaction","params":{"id":"x"}}'
# kutilgan javob: {"error":{"code":-31003,...}}  → auth o'tdi, tranzaksiya topilmadi

# 3) To'liq smoke test (Payme JSON-RPC + Stars + chek bir vaqtda):
python3 tests/smoke_test.py --base-url http://127.0.0.1:8080
```

**Muhim qoidalar:**

* `PAYME_KEY` bo'sh bo'lsa endpoint **barcha** so'rovlarni `-32504` bilan rad
  etadi (fail-closed) va karta ekranida Payme tugmasi **ko'rsatilmaydi**;
  karta + chek oqimi avvalgidek ishlayveradi.
* PRO **aynan bir marta** beriladi: takroriy `PerformTransaction` callback'lari
  saqlangan natijani qaytaradi (`payme:<id>` ledger kaliti UNIQUE).
* `PAYME_ALLOW_REFUNDS=0` (standart) — bajarilgan to'lovni Payme orqali bekor
  qilish `-31007` bilan rad etiladi.
* Kassa kaliti hech qachon log'ga yozilmaydi (`PaymeConfig.__repr__` va Sentry
  scrubber uni yashiradi).
* Batafsil: [docs/reports/PAYME_MERCHANT_API.md](docs/reports/PAYME_MERCHANT_API.md).

---

## 4. Yangilash va rollback

```bash
cd /opt/postassist && git pull                # Render: push → auto-deploy
./venv/bin/pip install -r telegram_bot/requirements.txt
sudo systemctl restart postassist             # graceful: in-flight postlar tugaydi
```

* `schema.sql` **idempotent** — `main.py` startda `db.init_db()` uni o'zi
  qo'llaydi (qo'lda migratsiya kerak emas).
* Rollback: `git checkout <old-tag> && systemctl restart postassist`
  (sxema orqaga qaytarilmaydi — migratsiyalar faqat qo'shimcha).

---

## 5. Yakuniy tekshiruv checklisti

- [ ] `systemctl status postassist` → `active (running)` (Render: service `Live`).
- [ ] `curl localhost:8080/health/live` → 200 `{"status":"live"}` (Docker/Render'da $PORT);
      `/health/ready` token bilan → 200 `{"status":"ready"}` (DB OK), tokensiz → 401
      (token o'rnatilmagan bo'lsa → 404, fail-closed).
- [ ] `bash scripts/deploy.sh --verify-only` → preflight + migratsiya + health +
      smoke test: **0 [FAIL]** (hisobot: `logs/smoke-*.json`).
- [ ] Telegram: `/start` menyuda 6 ta tugma; `/health` (OWNER) → **HEALTHY**
      (DB latency, scheduler, AI provayderlar holati, xatolar soni).
- [ ] Sinov posti: `/newpost` → kanalga chiqdi; `pending` da qolib ketmadi.
- [ ] Logda `[BOT_ERROR]` yo'q; Sentry ulangan bo'lsa eventlarda token/parol **yo'q**
      (scrubber ishlaydi).
- [ ] AI kalitisiz holatda sinov: xavfsiz xabar + kvota qaytadi (soxta matn yo'q).
- [ ] Xavfsizlik darvozasi (serverda bitta komanda — CI ham aynan shu skriptni
      ishlatadi): `bash scripts/security_check.sh` → lint gate yashil,
      `pip-audit` / `bandit` topilmalari ko'rib chiqilgan
      (`--advisory` faqat hisobot, `--skip-network` oflayn serverlar uchun).
- [ ] Testlar (repo ildizida) — 100% yashil:

```bash
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install -r telegram_bot/requirements.txt -r tests/requirements-test.txt
PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
echo "BASH EXIT CODE: $?"                      # kutilgani: 0
```

---

## 6. Ko'p uchraydigan xatolar

| Belgisi | Sabab va yechim |
|---|---|
| `RuntimeError: BOT_TOKEN topilmadi!` | Env fayl systemd `EnvironmentFile`da ko'rsatilmagan yoki `.env` ni o'qishga urinish — `EnvironmentFile=/etc/postassist.env`. |
| `server closed the connection unexpectedly` / SSL xatosi | `DATABASE_URL` da `?sslmode=require` yo'q yoki Neon **pooler** bo'lmagan manzil ishlatilgan