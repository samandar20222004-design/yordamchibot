import os
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

raw_admin_id = os.getenv("ADMIN_ID", "0").strip()
try:
    ADMIN_ID = int(raw_admin_id) if raw_admin_id else 0
except ValueError:
    logger.warning("ADMIN_ID noto'g'ri qiymatga ega: %r. 0 deb olindi.", raw_admin_id)
    ADMIN_ID = 0

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

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Render Environment bo'limida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Render Environment bo'limida DATABASE_URL ni kiriting.")
if ADMIN_ID == 0:
    logger.warning("ADMIN_ID sozlanmagan (0)! Faqat admin paneli ko'rinmaydi.")
