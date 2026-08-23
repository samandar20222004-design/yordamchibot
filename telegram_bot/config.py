import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPER_ADMIN_RAW = os.getenv("ADMIN_ID", "0")

try:
    SUPER_ADMIN = int(SUPER_ADMIN_RAW)
except ValueError:
    SUPER_ADMIN = 0

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN topilmadi! .env faylida BOT_TOKEN ni belgilang.")
