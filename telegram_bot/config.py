import os
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "PostAssistrobot")

# Bot versiyasi — «ℹ️ Bot haqida» ekrani va admin monitoring'da ko'rsatiladi.
BOT_VERSION = os.getenv("BOT_VERSION", "2.0")

# --- Ko'p adminli boshqaruv ---
# ADMIN_ID: eski, bitta raqam (orqaga mos kelish uchun saqlanadi)
# ADMIN_IDS: vergul bilan ajratilgan raqamlar ro'yxati, masalan: "123456,789012"
# Ikkala o'zgaruvchi ham birgalikda ishlaydi.
raw_admin_id = os.getenv("ADMIN_ID", "0").strip()
try:
    ADMIN_ID = int(raw_admin_id) if raw_admin_id else 0
except ValueError:
    logger.warning("ADMIN_ID noto'g'ri qiymatga ega: %r. 0 deb olindi.", raw_admin_id)
    ADMIN_ID = 0

raw_admin_ids = os.getenv("ADMIN_IDS", "").strip()
_parsed_ids: set[int] = set()
if raw_admin_ids:
    for part in raw_admin_ids.split(","):
        part = part.strip()
        try:
            if part:
                _parsed_ids.add(int(part))
        except ValueError:
            logger.warning("ADMIN_IDS ichida noto'g'ri qiymat: %r. O'tkazib yuborildi.", part)
if ADMIN_ID:
    _parsed_ids.add(ADMIN_ID)
# ADMIN_IDS_SET — barcha adminlar to'plami (is_admin() tekshiruvi uchun)
ADMIN_IDS_SET: frozenset[int] = frozenset(_parsed_ids)

def normalize_database_url(url: str | None) -> str | None:
    """Muhitdan kelgan PostgreSQL DSN ni psycopg2/asyncpg uchun moslashtiradi.

    * atrofdagi bo'shliq va qo'shtirnoqlarni olib tashlaydi;
    * Aiven/Heroku/Render ``postgres://`` yoki ``postgresql://`` berishi mumkin —
      drayverlar uchun prefiks ``postgresql://`` ga keltiriladi
      (``DATABASE_URL.replace("postgres://", "postgresql://", 1)``).
    Hardcoded host (neon.tech, aivencloud.com, ...) YO'Q — faqat env qiymati.
    """
    if url is None:
        return None
    url = str(url).strip().strip("\"'")
    if not url:
        return None
    # postgres:// → postgresql:// (faqat prefiks, 1 marta). Mixed-case ham.
    if url.lower().startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
        if url.lower().startswith("postgres://"):
            url = "postgresql://" + url.split("://", 1)[1]
    return url


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL"))

raw_port = os.getenv("PORT", "10000").strip()
try:
    PORT = int(raw_port) if raw_port else 10000
except ValueError:
    logger.warning("PORT noto'g'ri qiymatga ega: %r. 10000 deb olindi.", raw_port)
    PORT = 10000

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
# SambaNova Cloud — cloud.sambanova.ai (bepul tier, 10–30 RPM)
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY", "")
# Cloudflare Workers AI — account id + API token (kunlik 10K neuron bepul)
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "")

# --- Karta orqali to'lov (Uzcard / Humo) — O'zbekiston uchun qulaylik ---
# Karta rekvizitlari KODDA QATTIQ YOZILMAYDI (hardcode YO'Q) — ular FAQAT
# muhit o'zgaruvchilaridan (Render Environment yoki .env) o'qiladi:
#     CARD_NUMBER=<karta raqami, faqat raqamlar>
#     CARD_HOLDER=<karta egasining ismi>
# Berilmagan bo'lsa qiymat bo'sh satr bo'ladi va to'lov oynasida
# "karta rekvizitlari sozlanmagan" xabari chiqadi.


def _str_env(name: str, default: str) -> str:
    """Muhit o'zgaruvchisi (bo'sh bo'lsa default)."""
    raw = (os.getenv(name, "") or "").strip()
    return raw if raw else default


# QAT'IY talab: faqat .env / Render orqali.
CARD_NUMBER = os.getenv("CARD_NUMBER", "")
CARD_HOLDER = os.getenv("CARD_HOLDER", "")
# Ehtiyot chorasi: qiymatlar atrofidagi ortiqcha bo'shliqlar olib tashlanadi.
CARD_NUMBER = (CARD_NUMBER or "").strip()
CARD_HOLDER = (CARD_HOLDER or "").strip()
# Eski nomlar — mavjud importlar buzilmasligi uchun alias sifatida saqlanadi;
# qiymati har doim CARD_NUMBER/CARD_HOLDER bilan bir xil.
PAYMENT_CARD_NUMBER = CARD_NUMBER
PAYMENT_CARD_HOLDER = CARD_HOLDER
# Chek yuboriladigan admin username (@ belgisisiz ham bo'lishi mumkin)
PAYMENT_ADMIN_USERNAME = os.getenv("PAYMENT_ADMIN_USERNAME", "").strip().lstrip("@")

# --- Yordam / Qo'llab-quvvatlash aloqasi (📖 Qo'llanma bo'limi) ---
# /help va FAQ oxiridagi "💬 Bog'lanish / Связаться с поддержкой" tugmasi
# shu username'ga (t.me/<username>) yo'naltiriladi. Bo'sh qoldirilsa
# PAYMENT_ADMIN_USERNAME ishlatiladi; u ham bo'sh bo'lsa tugma ko'rsatilmaydi.
SUPPORT_USERNAME = (
    os.getenv("SUPPORT_USERNAME", "").strip().lstrip("@") or PAYMENT_ADMIN_USERNAME
)
# Tariflar narxi so'mda (Stars narxiga taxminan mos)
def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        logger.warning("%s noto'g'ri qiymatga ega: %r. %s deb olindi.", name, raw, default)
        return default


def _env_float(name: str, default: float) -> float:
    """Muhitdan float (soniya/foiz) o'qiydi — noto'g'ri bo'lsa ``default``."""
    raw = os.getenv(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        logger.warning("%s noto'g'ri qiymatga ega: %r. %s deb olindi.", name, raw, default)
        return default


def _env_flag(name: str, default: bool) -> bool:
    """Muhitdan boolean bayroq o'qiydi (``1/true/yes/on`` — True)."""
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


PAYMENT_PRICE_1M_UZS = _int_env("PAYMENT_PRICE_1M_UZS", 19000)
PAYMENT_PRICE_3M_UZS = _int_env("PAYMENT_PRICE_3M_UZS", 45000)
PAYMENT_PRICE_1Y_UZS = _int_env("PAYMENT_PRICE_1Y_UZS", 140000)

# --- YAGONA TARIF MANBAI (single source of truth) ---
# Stars / karta / AI-kanal limitlari faqat shu yerdan o'qiladi.
STARS_1M = _int_env("STARS_PRICE_1M", 75)
STARS_3M = _int_env("STARS_PRICE_3M", 175)
STARS_1Y = _int_env("STARS_PRICE_1Y", 550)
USD_1M = _str_env("USD_EQUIV_1M", "1.5")
USD_3M = _str_env("USD_EQUIV_3M", "3.5")
USD_1Y = _str_env("USD_EQUIV_1Y", "11.0")

FREE_MAX_CHANNELS = _int_env("FREE_MAX_CHANNELS", 3)
FREE_DAILY_AI = _int_env("FREE_DAILY_AI", 5)
PRO_MAX_CHANNELS = _int_env("PRO_MAX_CHANNELS", 999)
PRO_DAILY_AI = _int_env("PRO_DAILY_AI", 999)

# --- FAZA 25: Update handler va fon vazifalari uchun timeout chegaralari ---
# UPDATE_HANDLER_TIMEOUT_SECONDS — bitta Telegram update handlerining
# bajarilishiga berilgan QAT'IY maksimal vaqt (soniya). Og'ir AI/tahlil
# chaqiruvlari adatda bu chegaradan ancha pastraq muddatga ega
# (provider darajasidagi alohida timeout'lar); bu chegara "osilib qolgan"
# handler butun qabul zanjirini to'xtatib qo'ymasligi uchun SO'NGGI himoya
# chizig'i (watchdog). Chegaradan oshsa — bekor qilinadi, foydalanuvchiga
# xushmuomala javob beriladi, batafsil log scrubber orqali yoziladi.
UPDATE_HANDLER_TIMEOUT_SECONDS = _int_env("UPDATE_HANDLER_TIMEOUT_SECONDS", 110)
# BACKGROUND_TASK_TIMEOUT_SECONDS — fon (fire-and-forget) vazifalarining
# umumiy maksimal bajarilish muddati (soniya). Fon vazifalari asosiy qabul
# zanjirini (update intake) bloklamaydi va shu chegaradan oshsa
# bekor qilinadi — resurs sizmalari (task leak) oldi olinadi.
BACKGROUND_TASK_TIMEOUT_SECONDS = _int_env("BACKGROUND_TASK_TIMEOUT_SECONDS", 300)

# --- 1-BOSQICH: Render Free tezligi va kechikishni yo'qotish -----------
# STALE_UPDATE_SECONDS — bot o'chgan paytda Telegram serverida yig'ilib
# qolgan ESKI xabarlarni filtrlash chegarasi (soniya). Bot o'chganda
# foydalanuvchilar xabar yuboraveradi; ular Render'da qayta ishga
# tushganda birdan kelib tushadi va har biri qayta ishlovchi bot
# javobini kutadi. Eski update'lar muqaddas 600 soniyadan (10 daqiqa)
# kattasiga INDIRO'LADI — ular hech qachon foydalanuvchiga ko'rinmaydi.
# 0 = filtr yo'q (barcha update'lar bajariladi). Telegram getUpdates
# navbati 24 soat; 600s xavfsiz chegara (jonli xabarlar bir soniyada
# yuboriladi, shuning uchun chegara hech qachon haqiqiy xabarni
# kesib tashlamaydi).
STALE_UPDATE_SECONDS = max(0, _int_env("STALE_UPDATE_SECONDS", 600))
# KEEP_ALIVE_URL — Render/Aiven free-tier da instance'ni «uyqudan»
# chiqarish uchun ixtiyoriy tashqi ping manzili (masalan UptimeRobot
# yoki cron-job.org GET so'rovi). Bo'sh = keep-alive O'CHIRILGAN.
# Bot har 10 daqiqada (600s) shu manzilga aiohttp orqali GET yuboradi.
# DIQQAT: URL'ga maxfiy token QO'YMANG (u Render loglarida ko'rinadi);
# hech bo'lmasa ping maxfiy kalitsiz bo'lsin.
KEEP_ALIVE_URL = _str_env("KEEP_ALIVE_URL", "")
# KEEP_ALIVE_INTERVAL_SECONDS — ping orasidagi interval (soniya).
KEEP_ALIVE_INTERVAL_SECONDS = max(60, _int_env("KEEP_ALIVE_INTERVAL_SECONDS", 600))

# ============================================================================
# PHASE 2 · DISTRIBUTED STATE / CACHE (Redis) + GRANULAR RATE LIMITING
# ----------------------------------------------------------------------------
# Bot bir necha instance'da (Render/Docker: 2+ replica) ishlayotgan holat
# uchun holat (rate limit sanagichlari, kesh) UMUMIY manbada saqlanishi
# kerak. Redis — ixtiyoriy: `redis` paketi o'rnatilmasa yoki `REDIS_URL`
# bo'sh bo'lsa, tizim butunlay In-Memory rejimda ishlaydi
# (services/cache_backend.py — circuit breaker bilan avtomatik fallback).
# ============================================================================
# REDIS_URL — masalan `redis://localhost:6379/0` yoki
# `rediss://user:parol@host:6380/0`. BO'SH = Redis ishlatilmaydi.
# DIQQAT: parol DSN ichida — uni loglarga yozmang (.env faylida saqlang).
REDIS_URL = _str_env("REDIS_URL", "")
# REDIS_ENABLED — bayroq. Bo'sh bo'lsa avtomatik: URL bor bo'lsa 1,
# yo'q bo'lsa 0 (fail-safe: tasodifan URL yozilib qolsa ham bot ishlaydi).
# `0` = atayin In-Memory (Redis ulanmagan bo'lsa ham).
REDIS_ENABLED = (
    os.getenv("REDIS_ENABLED", "").strip()
    or ("1" if REDIS_URL else "0")
)
# REDIS_KEY_PREFIX — boshqa ilovalar bilan to'qnashmasligi uchun.
REDIS_KEY_PREFIX = _str_env("REDIS_KEY_PREFIX", "postassist")
# REDIS_SOCKET_TIMEOUT — ulanish/buyruq timeout'i (soniya). Bot startini
# kechiktirmaslik uchun qisqa (Redis o'lganda fallback tez ishga tushadi).
REDIS_SOCKET_TIMEOUT = _env_float("REDIS_SOCKET_TIMEOUT", 2.0)
# REDIS_MAX_CONNECTIONS — connection pool hajmi.
REDIS_MAX_CONNECTIONS = _int_env("REDIS_MAX_CONNECTIONS", 10)
# REDIS_CIRCUIT_FAILURES — shuncha ketma-ket xatodan keyin breaker OCHILADI
# (Redis o'lgan bo'lsa har bir so'rov timeout bo'lib botni sekinlashtirmasin).
REDIS_CIRCUIT_FAILURES = _int_env("REDIS_CIRCUIT_FAILURES", 3)
# REDIS_CIRCUIT_COOLDOWN — breaker ochiq turgan davr (soniya); keyin
# yarim-ochiq (half-open) proba yuboriladi.
REDIS_CIRCUIT_COOLDOWN = _env_float("REDIS_CIRCUIT_COOLDOWN", 30.0)
# MEM_CACHE_MAX_ENTRIES / MEM_CACHE_MAX_VALUE_BYTES / MEM_CACHE_MAX_TOTAL_BYTES
# — In-Memory backend chegaralari (Render 512 MB RAM himoyasi):
# LRU yozuvlar soni, bitta qiymatning maksimal hajmi va umumiy hajm.
MEM_CACHE_MAX_ENTRIES = _int_env("MEM_CACHE_MAX_ENTRIES", 20000)
MEM_CACHE_MAX_VALUE_BYTES = _int_env("MEM_CACHE_MAX_VALUE_BYTES", 65536)
MEM_CACHE_MAX_TOTAL_BYTES = _int_env("MEM_CACHE_MAX_TOTAL_BYTES", 33554432)

# Local admission: includes active updates and user-lock waiters. These are
# per-process RAM limits, not distributed Redis locks. Always enabled.
UPDATE_ADMISSION_MAX_PENDING = max(1, _int_env("UPDATE_ADMISSION_MAX_PENDING", 128))
UPDATE_ADMISSION_MAX_PER_USER = max(1, _int_env("UPDATE_ADMISSION_MAX_PER_USER", 20))

# --- Granular rate limiting (middlewares/rate_limiter.py) -----------------
# Har bir harakat uchun ALOHIDA kalit + ALOHIDA TTL (global tozalash yo'q).
# RATE_LIMIT_ENABLED=0 — barcha granullar o'chiriladi (diagnostika uchun).
RATE_LIMIT_ENABLED = _env_flag("RATE_LIMIT_ENABLED", True)
# Matnli xabarlar: 1 soniyada ko'pi bilan 2 ta.
RATE_LIMIT_MESSAGE_MAX = _int_env("RATE_LIMIT_MESSAGE_MAX", 2)
RATE_LIMIT_MESSAGE_WINDOW = _env_float("RATE_LIMIT_MESSAGE_WINDOW", 1.0)
# Callback throttling: (user_id, callback_action) — bir xil tugma bloklanadi,
# BOSHQA tugma erkin (masalan: "◀️ Orqaga" → "📊 Statistika" o'ta oladi).
RATE_LIMIT_CALLBACK_MAX = _int_env("RATE_LIMIT_CALLBACK_MAX", 1)
RATE_LIMIT_CALLBACK_WINDOW = _env_float("RATE_LIMIT_CALLBACK_WINDOW", 1.5)
# Qimmatli AI generatsiyasi: 4 soniyada 1 ta so'rov.
RATE_LIMIT_AI_MAX = _int_env("RATE_LIMIT_AI_MAX", 1)
RATE_LIMIT_AI_WINDOW = _env_float("RATE_LIMIT_AI_WINDOW", 4.0)
# URL / RSS fetch (SSRF + DoS): foydalanuvchi bo'yicha 60 s da 5 ta,
# butun bot bo'yicha 60 s da 120 ta (Redis bilan — barcha instance uchun).
RATE_LIMIT_FETCH_MAX = _int_env("RATE_LIMIT_FETCH_MAX", 5)
RATE_LIMIT_FETCH_WINDOW = _env_float("RATE_LIMIT_FETCH_WINDOW", 60.0)
RATE_LIMIT_FETCH_GLOBAL_MAX = _int_env("RATE_LIMIT_FETCH_GLOBAL_MAX", 120)
# RATE_LIMIT_AI_ACTIONS / RATE_LIMIT_FETCH_ACTIONS — vergul bilan ajratilgan
# callback action ro'yxati (bo'sh = modulning o'z standartlari).
RATE_LIMIT_AI_ACTIONS = _str_env("RATE_LIMIT_AI_ACTIONS", "")
RATE_LIMIT_FETCH_ACTIONS = _str_env("RATE_LIMIT_FETCH_ACTIONS", "")

STARS_PLANS = {
    "stars_1m": {
        "key": "1m",
        "stars": STARS_1M,
        "days": 30,
        "usd": USD_1M,
        "uzs": PAYMENT_PRICE_1M_UZS,
        "label": f"⭐️ 1 oylik ({STARS_1M} Stars)",
        "description": f"~${USD_1M}",
    },
    "stars_3m": {
        "key": "3m",
        "stars": STARS_3M,
        "days": 90,
        "usd": USD_3M,
        "uzs": PAYMENT_PRICE_3M_UZS,
        "label": f"⭐️ 3 oylik ({STARS_3M} Stars)",
        "description": f"~${USD_3M}",
    },
    "stars_1y": {
        "key": "1y",
        "stars": STARS_1Y,
        "days": 365,
        "usd": USD_1Y,
        "uzs": PAYMENT_PRICE_1Y_UZS,
        "label": f"⭐️ 1 yillik ({STARS_1Y} Stars)",
        "description": f"~${USD_1Y} / -40% chegirma",
    },
}

SUBSCRIPTION_PLANS = {
    "1m": {
        "days": 30,
        "stars": STARS_1M,
        "usd": USD_1M,
        "uzs": PAYMENT_PRICE_1M_UZS,
        "stars_key": "stars_1m",
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
    "3m": {
        "days": 90,
        "stars": STARS_3M,
        "usd": USD_3M,
        "uzs": PAYMENT_PRICE_3M_UZS,
        "stars_key": "stars_3m",
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
    "1y": {
        "days": 365,
        "stars": STARS_1Y,
        "usd": USD_1Y,
        "uzs": PAYMENT_PRICE_1Y_UZS,
        "stars_key": "stars_1y",
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
    "free": {
        "days": 0,
        "stars": 0,
        "usd": "0",
        "uzs": 0,
        "stars_key": None,
        "max_channels": FREE_MAX_CHANNELS,
        "daily_ai_requests": FREE_DAILY_AI,
    },
    "pro": {
        "days": 30,
        "stars": STARS_1M,
        "usd": USD_1M,
        "uzs": PAYMENT_PRICE_1M_UZS,
        "stars_key": "stars_1m",
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
    "enterprise": {
        "days": 365,
        "stars": STARS_1Y,
        "usd": USD_1Y,
        "uzs": PAYMENT_PRICE_1Y_UZS,
        "stars_key": "stars_1y",
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
}

PLAN_LIMITS = {
    "free": {
        "max_channels": FREE_MAX_CHANNELS,
        "daily_ai_requests": FREE_DAILY_AI,
    },
    "pro": {
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
    "enterprise": {
        "max_channels": PRO_MAX_CHANNELS,
        "daily_ai_requests": PRO_DAILY_AI,
    },
}


def get_stars_plan(plan_key: str) -> dict | None:
    return STARS_PLANS.get(str(plan_key or "").strip())


def get_subscription_plan(plan_key: str) -> dict | None:
    return SUBSCRIPTION_PLANS.get(str(plan_key or "").strip())

# --- Sentry monitoring (ixtiyoriy, 10-BOSQICH: maxfiylik filtri bilan) ---
# SENTRY_DSN berilsa va sentry_sdk o'rnatilgan bo'lsa, barcha xatolar
# avtomatik yig'iladi. MUHIM: Sentry'ga yuborilishdan oldin har bir event
# `utils.sentry_scrubber.scrub_event` filtridan o'tadi — bot token, DB paroli,
# karta rekvizitlari va API kalitlar loglarga HECH QACHON tushmaydi.
# --- PHASE A: Production safety — ENVIRONMENT / AI_ALLOW_MOCK (P0-A) ---
# ENVIRONMENT: production|development|test default production (fail-closed).
# AI_ALLOW_MOCK: 0|1 default 0 — MockProvider faqat dev/test yoki 1 bo'lganda.
_raw_env = (os.getenv("ENVIRONMENT", "") or "").strip().lower()
ENVIRONMENT = _raw_env if _raw_env else "production"
_raw_allow_mock = (os.getenv("AI_ALLOW_MOCK", "") or "").strip().lower()
AI_ALLOW_MOCK = _raw_allow_mock if _raw_allow_mock else "0"
# Legacy/test uchun ham foydalaniladigan qat'iy ro'yxat (spec bo'yicha faqat 2 ta).
MOCK_ALLOWED_ENVIRONMENTS: frozenset[str] = frozenset({"development", "test"})

SENTRY_DSN = os.getenv("SENTRY_DSN", "")


def _db_password_from_url(url: str) -> str:
    """DATABASE_URL ichidagi parolni ajratib oladi (ro'yxatga olish uchun)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        return parsed.password or ""
    except Exception:
        return ""


def _register_known_secrets() -> None:
    """Ma'lum sezgir qiymatlarni scrubber ro'yxatiga oladi.

    11-bosqich: Sentry yoqilgan-yoqilmaganidan QAT'I NAZAR chaqiriladi —
    stdlib ``logging`` filtri (``utils.sentry_scrubber.install_logging_scrubber``)
    ham shu ro'yxatdan foydalanadi, shuning uchun bot token, DB paroli, karta
    raqami va API kalitlar oddiy loglarga ham tushmaydi.
    """
    try:
        from utils.sentry_scrubber import register_secret

        _sensitive = (
            (BOT_TOKEN, "BOT_TOKEN"),
            (CARD_NUMBER, "CARD_NUMBER"),
            (CARD_HOLDER, "CARD_HOLDER"),
            (_db_password_from_url(DATABASE_URL), "DB_PASSWORD"),
            (GEMINI_API_KEY, "GEMINI_API_KEY"),
            (GROQ_API_KEY, "GROQ_API_KEY"),
            (OPENROUTER_API_KEY, "OPENROUTER_API_KEY"),
            (MISTRAL_API_KEY, "MISTRAL_API_KEY"),
            (CEREBRAS_API_KEY, "CEREBRAS_API_KEY"),
            (SAMBANOVA_API_KEY, "SAMBANOVA_API_KEY"),
            (CLOUDFLARE_API_TOKEN, "CLOUDFLARE_API_TOKEN"),
        )
        for value, label in _sensitive:
            register_secret(value, label)
    except Exception as e:  # pragma: no cover
        logger.warning("Maxfiy qiymatlarni ro'yxatga olishda xato: %s", e)


def _init_log_scrubber() -> bool:
    """stdlib logging uchun maxfiylik filtrini o'rnatadi (Sentry'siz ham)."""
    try:
        from utils.sentry_scrubber import install_logging_scrubber
        install_logging_scrubber()
        return True
    except Exception as e:  # pragma: no cover
        logger.warning("Log scrubber o'rnatilmadi: %s", e)
        return False


def _init_sentry() -> bool:
    """Sentry'ni maxfiylik filtri bilan ishga tushiradi.

    Qaytadi: ``True`` — Sentry faollashtirildi; aks holda ``False``.
    Hech qachon istisno ko'tarmaydi: Sentry'siz bot ishlashi davom etadi.
    """
    if not SENTRY_DSN:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry_sdk o'rnatilmagan. pip install sentry-sdk")
        return False
    try:
        from utils.sentry_scrubber import scrub_event

        # 1) Ma'lum sezgir qiymatlar ro'yxati allaqachon
        #    _register_known_secrets() orqali to'ldirilgan.
        # 2) Sentry ishga tushirish: before_send — maxfiylik filtri,
        #    send_default_pii=False — foydalanuvchi PII yig'ilmaydi.
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.1,   # 10% so'rovlarni kuzatish
            profiles_sample_rate=0.05,
            send_default_pii=False,
            before_send=scrub_event,
        )
        logger.info("Sentry monitoring yoqildi (maxfiylik filtri faol).")
        return True
    except Exception as e:
        logger.warning("Sentry ishga tushmadi: %s", e)
        return False


_register_known_secrets()
_init_log_scrubber()
_init_sentry()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Muhit o'zgaruvchisida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Muhit o'zgaruvchisida DATABASE_URL ni kiriting.")
if not ADMIN_IDS_SET:
    logger.warning("ADMIN_ID/ADMIN_IDS sozlanmagan! Faqat admin paneli ko'rinmaydi.")
