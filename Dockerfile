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
