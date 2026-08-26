import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")
PORT = int(os.getenv("PORT", "8080"))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN aniqlanmadi! .env faylni tekshiring.")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL aniqlanmadi! .env faylni tekshiring.")
