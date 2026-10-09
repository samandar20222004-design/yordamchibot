# PHASE 11 + PHASE 12 — YUKLAMA, CHAOS-XAVFSIZLIK VA PRODUCTION DOCKER HISOBOTI

**Loyiha:** PostAssist V2 (`samandar20222004-design/yordamchibot`)
**Bosqichlar:** PHASE 11 (yuklama/stress infratuzilmasi + chaos & security) · PHASE 12 (production Dockerfile + graceful shutdown)
**Qabul darvozasi:** `bash tests/run_tests.sh` (repo ildizidan) — yagona haqiqat manbai
**Holat:** ✅ **100% YASHIL** — 0 `[FAIL]`, exit code `0` (batafsil: 8-bo'lim)

---

## 0) QISQA XULOSA (VERDIKT)

| № | Talab | Holat | Isbot |
|---|-------|-------|-------|
| 1 | Yuklama testlari HAQIQIY Telegram API'ga tegmasin | ✅ | In-process **mock Telegram server** (`telegram_bot/staging/mock_telegram_server.py`); testlarda `api.telegram.org` manziliga **0 ta so'rov** |
| 2 | 10 logical / 100 concurrent / 1000 concurrent profil | ✅ | 3 profil alohida o'lchandi (`load_stress_mock_test.py`) |
| 3 | Throughput (RPS), Latency (p50/p95/p99), Error Rate | ✅ | Har bir profilda o'lchandi + `MEASUREMENTS_JSON` artefakti (1–3-bo'limlar) |
| 4 | DB Pool Usage | ✅ | 100 parallel aralash yuklamada `peak used=5/5`, ulanish balansi `0 → 0` (`load_test.py`) |
| 5 | Memory leak (RSS) | ✅ | 4 × 200 so'rovdan keyin **RSS o'sishi 0.0 MB** |
| 6 | DB uzilishi → fail-closed, crash yo'q | ✅ | AI kvota rad etildi (`db_error`), to'lov fail-closed, `ping_db=False`, readiness `database=error`, 50 parallel so'rovda 0 istisno |
| 7 | Redis uzilishi → lokal In-Memory fallback | ✅ | Circuit-breaker fallback, yozuv yo'qolmaydi, ping=True, xatosiz yopilish |
| 8 | Barcha AI provayderlar 500/timeout → muloyim UX + refund | ✅ | `GatewayResult.ok=False`, 3 tilda muloyim xabar, `refunded=True` |
| 9 | Telegram 429 flood va uzilishlar | ✅ | Aniq `retry_after`+jitter kutish, 60-parallel flood storm, blind retry **YO'Q** |
| 10 | SSRF / private IP / localhost / IPv6 himoyasi | ✅ | 21 ta ichki/aylanma URL bloklandi + yagona URL Security Gateway statik skaneri |
| 11 | Dublikat callback / to'lov / stale update | ✅ | 10 parallel to'lov → **1 ta yangi + 9 duplicate + 1 ledger yozuvi** |
| 12 | Multi-stage, non-root (`appuser`, UID 10001), HEALTHCHECK `curl /health/live` | ✅ | `Dockerfile` (5-bo'lim) + 83 statik/behavioral tekshiruv |
| 13 | SIGTERM/SIGINT → graceful shutdown (drenaj ~15 s, DB+Redis yopish) | ✅ | 12 bosqichli tartib, haqiqiy SIGTERM signali bilan sinov (7-bo'lim) |
| 14 | Mavjud testlar buzilmasin | ✅ | Baseline `14 650 [OK]` → yangi **`14 866 [OK]`** (+216 yangi tekshiruv), **`0 [FAIL]`**, `EXIT=0` |

---

## 1) PHASE 11 — YUKLAMA INFRATUZILMASI

### 1.1 Mock Telegram server (haqiqiy API o'rniga)

`telegram_bot/staging/mock_telegram_server.py` — `aiohttp` asosidagi Bot API
o'rnini bosuvchi server. PTB so'rovlarni **form-encoded/multipart** yuboradi,
shu sababli tanani `request.content_type` bo'yicha o'qish amalga oshirilgan.

| Endpoint | Vazifasi |
|----------|----------|
| `POST /bot{token}/{method}` | Bot API metodlari: `getMe`, `sendMessage`, `editMessageText`, `answerCallbackQuery`, `getUpdates`, ... |
| `GET /__stats` | `requests_total`, metodlar kesimi, statuslar, latency, `errors_429`, `errors_5xx` |
| `GET /__health` | Mock serverni liveness tekshiruvi (compose healthcheck) |
| `POST /__reset` | Holatni tozalash (test izolyatsiyasi) |
| `POST /__inject_update` | Update in'yeksiyasi (stale/duplicate stsenariylari) |
| `POST /__fault` | Nosozlik in'yeksiyasi: `mode` — `off\|429\|500\|timeout\|network`, `retry_after`, `every`, **`times`** (bir martalik), `latency_ms`, `methods`, `delay` |

**«times» — PHASE 11 uchun muhim qo'shimcha:** bir martalik nosozlik rejimi.
`{"mode": "429", "retry_after": 1, "times": 1}` — birinchi so'rov 429 oladi,
navbatdagi qayta urinish esa **muvaffaqiyatli** bo'ladi. Shu tufayli
"retry ishladi" degan xulosa mock hisoblagichlariga bog'liq bo'lmagan holda,
deterministik isbotlanadi.

### 1.2 Yuklama harnessi

`telegram_bot/tests/load_harness.py`:

* `LoadProfile(name, users, requests_per_user, concurrency, min_rps, max_p99_ms)` — profil;
* `Metrics` — `record_ok/record_error`, `rps`, `error_rate`, `latency()` (p50/p95/p99), `summary_line()`, `as_dict()`;
* `run_concurrent`, `task_leak_probe`, `rss_mb`, `environment_capabilities`;
* `start_mock_telegram()`, `build_mock_bot/make_mock_bot(base_url, pool_size=...)`.

### 1.3 Profillar va o'lchovlar (mock server, haqiqiy tarmoq zanjiri)

`telegram_bot/tests/load_stress_mock_test.py` — `[OK]=37 [FAIL]=0 [NOT TESTED]=0`.

| Profil | So'rov | RPS (yakka → darvoza) | Xato | p50 (yakka → darvoza) | p95 | p99 | Izoh |
|--------|-------:|----------------------:|-----:|----------------------:|----:|----:|------|
| 10 logical users | 40 | 15.5 → 15.7 | 0.00% | 586.0 → 562.0 ms | 1172.4 → 1135.7 ms | 1545.3 → 1476.0 ms | **production rate-limitlari** (1 post/s kanal, 30 msg/s global) |
| 100 concurrent users | 500 | 131.6 → 118.7 | 0.00% | 377.4 → 454.9 ms | 1907.9 → 2073.8 ms | 2690.0 → 3006.2 ms | stress rejimi (limiter ko'tarilgan) |
| 1000 concurrent requests | 1000 | 295.2 → 309.3 | 0.00% | 1685.9 → 1558.0 ms | 3023.1 → 2884.2 ms | 3217.1 → 3068.5 ms | to'liq parallel portlash |
| Memory leak (4 × 200) | 800 | — | — | — | — | — | **RSS o'sishi 0.0 MB**, to'lqiniga 0.00 MB |
| Shutdown drenaji (yuklama ostida) | 300 | 71.5 → 67.6 | 0.00% | 2127.3 → 2450.8 ms | 4107.1 → 4331.9 ms | 4170.9 → 4401.7 ms | 15 s byudjetda **to'liq** drenaj |

> «yakka» — suite alohida ishga tushirilganda; «darvoza» — to'liq
> `bash tests/run_tests.sh` ichida (boshqa suite'lar bilan birga). Farq
> ±20% ichida — o'lchovlar mashina yuklamasiga bog'liq, lekin **barcha
> mezonlar ikkala holatda ham bajarilgan** (xato 0%, p99 < 5 s, RPS ≥ min).

> Sinov mashinasi: 2 CPU, ~3.6 GB bo'sh RAM, fd limit 1024 — bu **past
> resursli** muhit; shuning uchun 1000-parallel profilda p50/p95 tabiiy
> ravishda yuqori (navbat). Barcha profillarda xato foizi **0.00%**.

Har bir yugurish yakunida mashina o'qiydigan artefakt chop etiladi:

```
MEASUREMENTS_JSON=[{"name": "10 logical users", "total": 40, "error_rate": 0.0, "rps": 15.5,
 "latency_ms": {"p50": 586.02, "p95": 1172.42, "p99": 1545.34}, ...},
 {"name": "1000 concurrent requests", "total": 1000, "error_rate": 0.0, "rps": 295.2, ...},
 {"name": "memory leak (4 × 200 so'rov)", "requests": 800, "rss_growth_mb": 0.0, ...}]
```

### 1.4 DB Pool Usage (real PostgreSQL, staging'ga yaqin aralash yuklama)

`telegram_bot/tests/load_test.py` → `PHASE 11: mock Telegram yuklamasi + DB pool metrikalari`:
100 parallel foydalanuvchi bir vaqtda **DB'ga post yozadi** va **mock Telegram'ga
xabar yuboradi** (pgserver ustidagi haqiqiy PostgreSQL):

| Ko'rsatkich | Qiymat |
|-------------|--------|
| So'rovlar | 100 parallel (aralash: DB + Telegram) |
| Throughput | **219.5 RPS** (yakka yugurishda 279.7 RPS) |
| Error rate | **0.00%** |
| Latency | p50 **346.8 ms** · p95 **443.9 ms** · p99 **449.5 ms** (yakka: p50 224.5 / p95 348.7 / p99 351.8 ms) |
| DB pool peak | **used=5 / max=5** (to'yintirilgan, lekin chegaradan oshmagan) |
| Ulanish balansi (leak) | **oldin=0 → keyin=0** |
| DB'ga yozilgan postlar | **100/100** |

Natija: `O'tdi: 157, Xato: 0`.

---

## 2) PHASE 11 — CHAOS & SECURITY SUITE (FAIL-CLOSED)

`tests/phase11_chaos_security_test.py` — **`[OK]=81 [FAIL]=0 [NOT TESTED]=0`**.
Tarmoqqa chiqmaydi (mock Telegram + In-Memory), deterministik.

| # | Bo'lim | Nima isbotlandi |
|---|--------|-----------------|
| 1 | 🗄 **DB uzildi** | `ping_db()=False` (istisno yo'q), `get_db_pool_status()` xavfsiz, `readiness.ready=False` + `database=error`, **AI kvota FAIL-CLOSED** (`allowed=False`, sabab `db_error`), to'lov fail-closed, **50 parallel so'rovda 0 istisno**, foydalanuvchiga 3 tilda muloyim xabar |
| 2 | 🔌 **Redis uzildi** | Circuit-breaker **In-Memory fallback**: factory memory backend tanlaydi, `set/get` ishlaydi, yozuv YO'QOLMAYDI, `ping=True` (rate-limit fail-open — foydalanuvchi bloklanmaydi), `incr` ishlaydi, backend xatosiz yopiladi |
| 3 | 🤖 **Barcha AI provayderlar 500/timeout** | Zanjir haqiqatan uriniladi (sintetik handle), `attempts=2` (retry bo'ldi), `GatewayResult.ok=False`, **3 tilda muloyim xabar**, soxta matn YO'Q, `run_ai_task` → `refunded=True` (bron 1 marta ochildi, 1 marta qaytarildi) |
| 4 | 📨 **Telegram 429 / 500 / uzilish** | 429 → aniq `retry_after` **+ jitter** kutish hisoblandi (~1.18 s) va qayta urinish muvaffaqiyatli; defer rejimi (`inline_max_wait=0`) → `RetryAfter` chaqiruvchiga qaytadi (`rate_limit` klassi); 500 → xato **yutilmaydi** va **blind retry YO'Q** (atigi 1 ta HTTP so'rov); tarmoq uzilishi → `ambiguous`; **60-parallel flood storm**: hammasi yetib bordi, ≥10 ta 429, navbat tozalandi, <30 s |
| 5 | 🛡 **SSRF** | **21 ta** ichki/aylanma URL bloklandi: `localhost`, `127.0.0.1`, `user:pass@127.0.0.1`, `0.0.0.0`, `10.*`, `192.168.*`, `172.16.*`, `169.254.169.254`, `2130706433`, `0177.0.0.1`, `0x7f000001`, `[::1]`, `[::ffff:127.0.0.1]`, `[fd00::1]`, `[fe80::1]`, `file:`, `gopher:`, `ftp:`; ochiq URL ruxsat; `safe_fetch` bloklanganda **tarmoqqa umuman chiqmaydi**; statik skaner: `channel_reader.py`, `sources/rss_service.py`, `sources/url_extractor.py` — yagona shlyuzdan foydalanadi, xom `urlopen()` **YO'Q** |
| 6 | ♻️ **Dublikat / stale** | Ketma-ket bir xil callback → bloklanadi, boshqa tugma ishlaydi; **10 parallel dublikat Stars to'lov → 1 ta yangi + 9 duplicate + ledger'ga 1 yozuv**; 1 soatlik **stale update INDIRO'LANADI** (handler chaqirilmaydi); takroriy matn bloklanadi |
| 7 | 💧 **Resurs holati** | Chaos'dan keyin asyncio **task leak yo'q**, lifecycle navbatlari bo'sh, shutdown bayrog'i toza, cache holati xavfsiz |

---

## 3) PHASE 12 — PRODUCTION DOCKERFILE

### 3.1 Talab ↔ bajarilish

| Talab | Dockerfile'da |
|-------|---------------|
| Multi-stage build, kichik va xavfsiz layerlar | `FROM python:3.11-slim AS builder` → `FROM python:3.11-slim AS runtime`; runtime'ga faqat **tayyor virtualenv** (`COPY --from=builder /opt/venv`) + ilova kodi; kompilyatorlar (`build-essential`, `libpq-dev`) runtime'ga **tushmaydi**; apt keshlari `rm -rf /var/lib/apt/lists/*` |
| Non-root foydalanuvchi `appuser`, UID **10001** | `groupadd --system --gid 10001 appgroup`, `useradd --system --uid 10001 --gid appgroup ... appuser`, `COPY --chown=appuser:appgroup`, `USER appuser` (root'da `USER root` YO'Q) |
| HEALTHCHECK `curl /health/live` | `HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 CMD curl -fsS "http://127.0.0.1:${PORT}/health/live"` — DB/Redis/scheduler'ga **murojaat qilmaydi** (arzon liveness) |
| Graceful shutdown | `STOPSIGNAL SIGTERM` + `tini` PID 1 sifatida signalni uzatadi (`ENTRYPOINT ["/usr/bin/tini", "--"]`); `--stop-timeout 20` / compose `stop_grace_period: 20s` > 15 s drenaj |
| Sirlar image'ga tushmasin | FAQAT env orqali (`ENV` ichida TOKEN/PASSWORD/SECRET/API_KEY **YO'Q**); `.dockerignore`: `.git`, `.env`, `__pycache__`, `telegram_bot/tests/`, `*.md`, `Dockerfile`, `docker-compose.yml` |

### 3.2 `Dockerfile` (to'liq matn)

```dockerfile
# syntax=docker/dockerfile:1
# ============================================================
# PostAssist V2 — PRODUCTION Dockerfile (PHASE 12)
#
# Build:   docker build -t postassist-bot .
# Run:     docker run --env-file .env --stop-timeout 20 postassist-bot
# Compose: docker compose up -d
#
# Ushbu image PRODUCTION standartlariga mos:
#   1) MULTI-STAGE build — builder bosqichida bog'liqliklar yig'iladi,
#      runtime bosqichiga faqat tayyor virtualenv + ilova kodi ko'chiriladi
#      (kompilyatorlar, pip keshi va build artefaktlari image'ga TUSHMAYDI);
#   2) NON-ROOT foydalanuvchi — `appuser`, UID/GID **10001** (root hech
#      qachon ilovani ishga tushirmaydi; /app fayllari appuser egaligida);
#   3) HEALTHCHECK — `curl /health/live` (arzon, DB/Redis'siz liveness;
#      start-period ichida bot portni ochadi, chunki main.py web serverni
#      init_db'dan OLDIN ko'taradi);
#   4) tini — PID 1 sifatida SIGTERM/SIGINT signallarini to'g'ri uzatadi va
#      zombie jarayonlarni yig'adi; STOPSIGNAL SIGTERM;
#   5) GRACEFUL SHUTDOWN — SIGTERM → lifecycle drenaji (delivery navbati +
#      scheduler ishlari, standart 15 s) → DB pool va Redis/aiohttp ulanishi
#      yopiladi → exit 0. Konteyner to'xtatishda `--stop-timeout 20`
#      (compose'da `stop_grace_period: 20s`) bering — 15 s drenajdan katta.
#
# CHUQUR (deep) tekshiruv — liveness'dan farqli, DB + scheduler + AI holatini
# ko'rsatadi. Operator/compose uchun (HEALTHCHECK'ni og'irlashtirmaslik uchun
# u ASOSIY healthcheck emas):
#     docker exec postassist-bot python -m utils.deep_healthcheck
# (utils/deep_healthcheck.py → services.health_service.get_system_health();
#  UNHEALTHY holatda exit 1, DEGRADED/HEALTHY'da exit 0.)
# ============================================================

# ------------------------------------------------------------
# 1-BOSQICH (BUILDER): bog'liqliklarni izolyatsiyalangan virtualenv'ga yig'ish
# ------------------------------------------------------------
FROM python:3.11-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# psycopg2-binary wheel'lari mavjud, lekin muhit farq qilsa (boshqa arxitektura)
# manbadan yig'ish uchun minimal build zanjiri tayyor turadi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Requirements ALOHIDA layer'da — kod o'zgarganda pip qayta ishlamaydi (kesh).
COPY telegram_bot/requirements.txt /build/requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r /build/requirements.txt

# ------------------------------------------------------------
# 2-BOSQICH (RUNTIME): minimal, xavfsiz va non-root image
# ------------------------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=10000

# ca-certificates — TLS (Aiven/Telegram/OpenAI); curl — HEALTHCHECK uchun;
# tini — PID 1 signal-forwarder. Ortiqcha paketlar o'rnatilmaydi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

# --- Xavfsizlik: root bo'lmagan foydalanuvchi (UID/GID 10001) ---
RUN groupadd --system --gid 10001 appgroup \
    && useradd --system --uid 10001 --gid appgroup \
       --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# Tayyor virtualenv (builder'dan) + ilova kodi (appuser egaligida).
COPY --from=builder /opt/venv /opt/venv
COPY --chown=appuser:appgroup telegram_bot/ /app/

# Sent-journal (post idempotentlik jurnali) va loglar uchun yoziladigan papka.
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

USER appuser

# --- HEALTHCHECK: arzon liveness (process tirikmi?) ---
# /health/live DB/Redis/scheduler'ga murojaat qilmaydi → konteyner sog'lig'i
# baza uzilganda ham "alive" bo'lib qoladi (deep holat /health/ready va
# utils.deep_healthcheck orqali tekshiriladi).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health/live" >/dev/null || exit 1

# Graceful shutdown: docker stop → SIGTERM (tini orqali main.py'ga) →
# lifecycle drenaji (delivery navbati + scheduler, 15 s) → exit 0.
STOPSIGNAL SIGTERM

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
```

---

## 4) PHASE 12 — STAGING COMPOSE (MOCK TELEGRAM)

`docker-compose.staging.yml` — dev `docker-compose.yml` ustiga qo'shimcha (override):

* `mock-telegram` xizmati **o'sha image**dan ishga tushadi:
  `python -m staging.mock_telegram_server --host 0.0.0.0 --port 8080`;
* `bot` xizmatiga **`TELEGRAM_API_BASE_URL: http://mock-telegram:8080/bot`** beriladi —
  barcha Bot API so'rovlari mock serverga ketadi (**haqiqiy Telegram'ga 0 so'rov**);
* `bot` faqat mock server `service_healthy` bo'lgach ko'tariladi;
* ikkala xizmatda `stop_grace_period: 20s` (15 s drenajdan katta).

```bash
# staging ko'tarish (mock Telegram bilan)
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d --build
curl -s http://127.0.0.1:8081/__stats   # mock server hisoboti
docker compose -f docker-compose.yml -f docker-compose.staging.yml down
```

Ilova tomonida staging rejimi `telegram_bot/utils/telegram_delivery.py`
(`create_safe_bot`) va `telegram_bot/config.py` (`TELEGRAM_API_BASE_URL`) orqali
ulanadi — bo'sh qiymat = default `https://api.telegram.org/bot` (xatti-harakat
o'zgarmaydi). Ikkala `.env.example` da `TELEGRAM_API_BASE_URL=` va
`SHUTDOWN_GRACE_SECONDS=15` hujjatlashtirilgan (`tests/env_docs_parity_test.py`
→ 45/45 yashil).

---

## 5) PHASE 12 — GRACEFUL SHUTDOWN (SIGTERM/SIGINT)

`telegram_bot/services/lifecycle_service.py`: `SHUTDOWN_DRAIN_DEFAULT_SECONDS = 15.0`,
chegara **[5, 30]** (`SHUTDOWN_GRACE_SECONDS` env orqali), navbat hisobi
(`track_queue`, `queue_pending`), drenaj kutish (`wait_for_inflight`,
`wait_for_queues`, `wait_for_drain`).

`telegram_bot/main.py` → `graceful_shutdown()` **aynan shu tartibda** 12 bosqich
(har biri alohida `try/except`; biri yiqilsa ham qolganlari bajariladi):

```
 1. request_shutdown()        — yangi ish qabul qilinmaydi (scheduler yangi post olmaydi)
 2. updater_stopped           — Telegram'dan yangi update olish TO'XTAYDI
 3. scheduler_paused          — navbatdagi joblar ishga tushmaydi
 4. inflight_drained          — faol postlar/joblar tugashini kutish (bekor QILINMAYDI)
 5. queues_drained            — DELIVERY navbati (yuborilayotgan xabarlar) drenaji
 6. application_stopped       — PTB navbatdagi update'larni tugatadi
 7. application_shutdown
 8. scheduler_shutdown(wait=False)
 9. user_activity_flushed     — DB pool yopilishidan OLDIN
10. web_server_closed         — /health/live va /health/ready
11. db_pool_closed + ai_session_closed
12. cache_closed              — Redis/cache backend
```

Isbotlangan xatti-harakatlar (`tests/phase12_docker_and_shutdown_test.py`,
83 ta tekshiruv):

* **haqiqiy SIGTERM** yuborilganda event-loop handleri ishga tushadi →
  `stop_event` o'rnatiladi, `shutdown_reason()="SIGTERM"` (sinovda `os.kill`);
  ikkinchi signal yopilishni **qayta boshlamaydi** (`request_shutdown()` → `False`);
* band delivery navbati bilan sinovda drenaj **kutadi** va `drained=True` beradi;
  navbat bo'shamasa — `drained=False` (istisno yo'q, ishlar **bekor qilinmaydi**,
  DB'dagi `processing` holati keyingi ishga tushishda stale-recovery bilan tiklanadi);
* DB pool, AI (aiohttp) sessiya va Redis/cache **har qanday holatda** yopiladi;
* `KeyboardInterrupt` ham `graceful_shutdown()` yo'liga o'tadi (resurslar yarim
  yo'lda qolmaydi).

---

## 6) YANGILANGAN VA QO'SHILGAN TESTLAR

| Fayl | Holat | Natija |
|------|-------|--------|
| `tests/phase11_chaos_security_test.py` | 🆕 | `[OK]=81 [FAIL]=0 [NOT TESTED]=0` |
| `tests/phase12_docker_and_shutdown_test.py` | 🆕 | `[OK]=83 [FAIL]=0 [NOT TESTED]=2` (docker CLI yo'q) |
| `telegram_bot/tests/load_stress_mock_test.py` | 🆕 | `[OK]=37 [FAIL]=0 [NOT TESTED]=0` |
| `telegram_bot/tests/load_test.py` (PHASE 11 bo'limi) | ➕ | `O'tdi: 157, Xato: 0` |
| `telegram_bot/tests/stress_concurrency_test.py` | ➕ | `O'tdi: 149, Xato: 0` (+`queues_drained` kontrakti) |
| `tests/env_docs_parity_test.py` | ♻️ | `o'tdi=45, xato=0` |
| `telegram_bot/tests/run_tests.sh` | ➕ | PHASE 11 mock yuklama bo'limi ro'yxatga olindi |
| `tests/run_tests.sh` | ➕ | `3v2) PHASE 11 chaos` va `3v3) PHASE 12 Docker/shutdown` bo'limlari qo'shildi |

---

## 7) NOT TESTED (halol ro'yxat — soxta PASS yo'q)

| Tekshiruv | Sabab |
|-----------|-------|
| `docker build` (haqiqiy image qurish) | Sandbox'da **docker CLI yo'q**; Dockerfile kontraktlari statik (matn + behavior) tekshirildi |
| `docker compose config` (merge sinovi) | Xuddi shu sabab — compose fayllar statik kontraktlar bilan tekshirildi |
| Haqiqiy Telegram API bilan yuklama | **Ataylab qilinmaydi** (talab: real API'ga spam yuborilmasin) — mock server ishlatiladi |
| Haqiqiy Redis instansiyasi bilan chaos | `redis` ixtiyoriy komponent — circuit-breaker fake mijoz bilan sinovdan o'tdi |

---

## 8) YAKUNIY QABUL DARVOZASI (`bash tests/run_tests.sh`)

```
$ PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
...
==================== LOAD TEST ======================
===== 📨 PHASE 11 — MOCK TELEGRAM YUKLAMA/STRESS (10/100/1000) =====
 NATIJA: [OK]=37  [FAIL]=0  [NOT TESTED]=0
 ✅ PHASE 11 LOAD SUITE: 100% YASHIL ✔
...
===== 3v2) 🌀 PHASE 11: CHAOS & SECURITY — FAIL-CLOSED (DB/REDIS/AI/TG/SSRF) =====
 NATIJA: [OK]=81  [FAIL]=0  [NOT TESTED]=0
 ✅ PHASE 11 CHAOS SUITE: 100% YASHIL ✔
...
===== 3v3) 🐳 PHASE 12: PRODUCTION DOCKERFILE + GRACEFUL SHUTDOWN =====
 NATIJA: [OK]=83  [FAIL]=0  [NOT TESTED]=2   (docker CLI bu muhitda yo'q)
 ✅ PHASE 12 DOCKER & SHUTDOWN SUITE: 100% YASHIL ✔
...
======== 4) TO'LIQ REGRESSIYA (telegram_bot/tests) ========
==============================================================
BARCHA TESTLAR 100% YASHIL ✔
EXIT=0

--------------------------------------------------------------------
 Yakuniy hisob (2026-10-06, to'liq yugurish ≈ 6 daqiqa 54 soniya):
   [OK]         : 14 866   (baseline 14 650 → +216 yangi tekshiruv)
   [FAIL]       : 0        (haqiqiy yiqilish YO'Q)
   [NOT TESTED] : 2        (docker CLI yo'q — PHASE 12 statik kontraktlar)
   exit code    : 0        → ✅ 100% YASHIL
--------------------------------------------------------------------
```

---

## 9) YAKUNIY XULOSA

PHASE 11 va PHASE 12 talablari **to'liq bajarildi**:

1. **Yuklama infratuzilmasi** haqiqiy Telegram API'ga bog'lanmagan holda ishlaydi:
   in-process mock server + harness 10 logical / 100 concurrent / 1000 concurrent
   profillarni, RPS/p50/p95/p99/xato foizi/DB pool/RSS o'lchovlarini beradi.
2. **Chaos & xavfsizlik** bo'yicha barcha talab qilingan stsenariylar
   (DB uzilishi, Redis fallback, AI provayderlar uzilishi + refund, Telegram 429/500/uzilish,
   SSRF/private IP/localhost/IPv6, dublikat callback/to'lov/stale update) **fail-closed**
   xatti-harakat bilan isbotlandi — 81/81 tekshiruv yashil.
3. **Production Dockerfile** multi-stage, non-root `appuser` (UID 10001),
   `HEALTHCHECK curl /health/live`, `STOPSIGNAL SIGTERM` + tini standartlariga javob beradi;
   staging compose mock Telegram bilan ulanadi.
4. **Graceful shutdown** SIGTERM/SIGINT'ni ushlaydi, yangi ish qabul qilmaydi,
   delivery navbati va scheduler ishlarini 15 soniya byudjet ichida drenaj qiladi
   (ishlar bekor qilinmaydi), DB pool va Redis/cache ulanishlarini toza yopadi.
5. **Regressiya yo'q:** `bash tests/run_tests.sh` → **100% yashil, 0 `[FAIL]`, exit `0`**.

### Qayta ishga tushirish buyruqlari

```bash
cd /home/user/yordamchibot
PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh          # to'liq qabul darvozasi
$HOME/venv/bin/python tests/phase11_chaos_security_test.py    # chaos & security (81)
$HOME/venv/bin/python tests/phase12_docker_and_shutdown_test.py  # Docker + shutdown (83)
cd telegram_bot && $HOME/venv/bin/python tests/load_stress_mock_test.py  # yuklama (37)
```
