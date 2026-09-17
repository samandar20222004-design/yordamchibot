# 🚀 PostAssist V2 (YORDAMCHIBOT) — DEPLOYMENT QO'LLANMASI

> Maqsad: botni **serverda (Render yoki VPS) 24/7** ishga tushirish — qisqa va lo'nda.
> Barcha sozlamalar faqat **muhit o'zgaruvchilari** orqali (`python-dotenv`
> **ishlatilmaydi**, `.env` faylini ilova o'zi o'qimaydi — quyga qarang).

Bog'liq fayllar: `telegram_bot/main.py` (kirish nuqtasi) · `Dockerfile` ·
`docker-compose.yml` · `.env.example` (kononik env hujjati — ikkala nusxa
bir xil) · `telegram_bot/README.md` (funksiyalar bo'yicha to'liq hujjat).

---

## 0. Ishga tushirishdan oldin (5 daqiqa)

| # | bajariladigan ish |
|---|---|
| 1 | **@BotFather** → `/newbot` → `BOT_TOKEN`. |
| 2 | **@userinfobot** → o'z ID'ingiz → `ADMIN_ID` (bir nechta admin: `ADMIN_IDS=111,222`). |
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
   Majburiy: `BOT_TOKEN`, `DATABASE_URL`, `ADMIN_ID` (+ `ENVIRONMENT=production`,
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
sudo nano /etc/postassist.env      # BOT_TOKEN, DATABASE_URL, ADMIN_ID, AI kalitlari...
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
WorkingDirectory=/opt/postassist/telegram_bot
EnvironmentFile=/etc/postassist.env
ExecStart=/opt/postassist/venv/bin/python main.py
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
curl -fsS localhost:10000/health/live   # {"status":"ok",...}
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
- [ ] `curl localhost:10000/health/live` → 200; `/health/ready` → 200 (DB OK).
- [ ] Telegram: `/start` menyuda 6 ta tugma; `/health` (OWNER) → **HEALTHY**
      (DB latency, scheduler, AI provayderlar holati, xatolar soni).
- [ ] Sinov posti: `/newpost` → kanalga chiqdi; `pending` da qolib ketmadi.
- [ ] Logda `[BOT_ERROR]` yo'q; Sentry ulangan bo'lsa eventlarda token/parol **yo'q**
      (scrubber ishlaydi).
- [ ] AI kalitisiz holatda sinov: xavfsiz xabar + kvota qaytadi (soxta matn yo'q).
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
| `server closed the connection unexpectedly` / SSL xatosi | `DATABASE_URL` da `?sslmode=require` yo'q yoki Neon **pooler** bo'lmagan manzil ishlatilgan. |
| Bot javob bermaydi, logda `Unauthorized` | `BOT_TOKEN` noto'g'ri/almashirilgan. |
| Postlar chiqmaydi, kanalga `Forbidden` | Bot kanal admini emas yoki "Post Messages" huquqi yo'q. |
| `AI hozirda mavjud emas` | Hech bir AI kaliti ishlamayapti (rate-limit/balan). `ENVIRONMENT=production` da bu **to'g'ri xatti-harakat** — `AI_ALLOW_MOCK` ni yoqmang. |
| Restart'dan keyin postlar kechikadi | Scheduler har 1 daqiqada `check_and_send_posts` ni tekshiradi va `recover_on_startup()` stale postlarni tiklaydi; Free/ECO Render uxlashida davom etmaydi → Always-on instance. |
| `pip install pgserver` xatosi | Test uchun (`tests/requirements-test.txt` — `pgserver>=0.1.4`); prod image'da kerak emas. |
