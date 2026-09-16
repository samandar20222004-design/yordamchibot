import os
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_USERNAME = os.getenv("BOT_USERNAME", "PostAssistrobot")

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

DATABASE_URL = os.getenv("DATABASE_URL")
# Render ba'zan eski postgres:// formatini beradi; psycopg2 uchun standart sxemaga o'tkazamiz.
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql://" + DATABASE_URL[len("postgres://"):]

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
    raise RuntimeError("BOT_TOKEN topilmadi! Render Environment bo'limida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Render Environment bo'limida DATABASE_URL ni kiriting.")
if not ADMIN_IDS_SET:
    logger.warning("ADMIN_ID/ADMIN_IDS sozlanmagan! Faqat admin paneli ko'rinmaydi.")
