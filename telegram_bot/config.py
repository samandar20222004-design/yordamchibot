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

# --- Sentry monitoring (ixtiyoriy, 10-BOSQICH: maxfiylik filtri bilan) ---
# SENTRY_DSN berilsa va sentry_sdk o'rnatilgan bo'lsa, barcha xatolar
# avtomatik yig'iladi. MUHIM: Sentry'ga yuborilishdan oldin har bir event
# `utils.sentry_scrubber.scrub_event` filtridan o'tadi — bot token, DB paroli,
# karta rekvizitlari va API kalitlar loglarga HECH QACHON tushmaydi.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")


def _db_password_from_url(url: str) -> str:
    """DATABASE_URL ichidagi parolni ajratib oladi (ro'yxatga olish uchun)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url or "")
        return parsed.password or ""
    except Exception:
        return ""


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
        from utils.sentry_scrubber import register_secret, scrub_event

        # 1) Ma'lum sezgir qiymatlar ro'yxati — event matnida aniq ko'rinsa
        #    o'chiriladi (regex'dan oldin ishlaydigan birinchi himoya qatlami).
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


_init_sentry()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Render Environment bo'limida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Render Environment bo'limida DATABASE_URL ni kiriting.")
if not ADMIN_IDS_SET:
    logger.warning("ADMIN_ID/ADMIN_IDS sozlanmagan! Faqat admin paneli ko'rinmaydi.")
