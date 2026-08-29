import os
import logging

logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! Render Environment bo'limida BOT_TOKEN ni kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! Render Environment bo'limida DATABASE_URL ni kiriting.")
if ADMIN_ID == 0:
    logger.warning("ADMIN_ID sozlanmagan (0)! Faqat admin paneli ko'rinmaydi.")
