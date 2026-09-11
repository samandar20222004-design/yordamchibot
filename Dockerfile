# ============================================================
# PostAssist V2 — Production Dockerfile (10-BOSQICH)
#
# Build:   docker build -t postassist-bot .
# Run:     docker run --env-file .env postassist-bot
# Compose: docker compose up -d
# ============================================================
FROM python:3.11-slim

# --- Muhit: deterministik, bytecodesiz, buffer'siz Python ---
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tizim kutubxonalari: psycopg2-binary o'zi bilan wheel olib keladi, shuning
# uchun kompilyatsiya vositalari kerak emas — image iloji boricha kichik.
# tini — PID 1 sifatida signallarni to'g'ri uzatadi (graceful shutdown).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini \
    && rm -rf /var/lib/apt/lists/*

# --- Xavfsizlik: root bo'lmagan foydalanuvchi ---
RUN groupadd --system --gid 10001 appgroup \
    && useradd --system --uid 10001 --gid appgroup \
       --home-dir /app --shell /usr/sbin/nologin appuser

WORKDIR /app

# --- Bog'liqliklar (avval requirements — layer keshi uchun) ---
COPY telegram_bot/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# --- Ilova kodi ---
COPY telegram_bot/ /app/

# Jurnal/ jurnal-fayl va sent-journal uchun yoziladigan papka.
RUN mkdir -p /app/data && chown -R appuser:appgroup /app

# --- Xavfsizlik va barqarorlik ---
USER appuser

# Health check: DB + scheduler + AI holatini tekshiradi. Faqat UNHEALTHY
# (DB javob bermayapti) holatida konteyner nosog'lom deb topiladi;
# DEGRADED (masalan, alohida healthcheck jarayonida scheduler ko'rinmasligi)
# nosog'lom hisoblanmaydi.
HEALTHCHECK --interval=30s --timeout=20s --start-period=40s --retries=3 \
    CMD python -c "from services.health_service import get_system_health; import asyncio; res=asyncio.run(get_system_health()); exit(0 if res.get('status')!='UNHEALTHY' else 1)" || exit 1

# Graceful shutdown: docker stop → SIGTERM → main.py signal handlerlari
# (lifecycle.request_shutdown → in-flight postlar tugashi kutiladi → exit 0).
STOPSIGNAL SIGTERM

# tini — PID 1 sifatida signallarni to'g'ri uzatadi va zombie jarayonlarni yig'adi.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
