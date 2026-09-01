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

# --- Sentry monitoring (ixtiyoriy) ---
# Render'da SENTRY_DSN o'zgaruvchisini qo'shsangiz, barcha xatolar avtomatik yig'iladi.
SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if SENTRY_DSN:
    try:
        import sentry_sdk
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            traces_sample_rate=0.1,   # 10% so'rovlarni kuzatish
            profiles_sample_rate=0.05,
        )
        logger.info("Sentry monitoring yoqildi.")
    except ImportError:
        logger.warning("sentry_sdk o'rnatilmagan. pip install sentry-sdk")
    except Exception as e:
        logger.warning("Sentry ishga tushmadi: %s", e)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Render Environment bo'limida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Render Environment bo'limida DATABASE_URL ni kiriting.")
if not ADMIN_IDS_SET:
    logger.warning("ADMIN_ID/ADMIN_IDS sozlanmagan! Faqat admin paneli ko'rinmaydi.")
