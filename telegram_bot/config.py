import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID_RAW = os.getenv("ADMIN_ID", "0")
CHANNEL_ID = os.getenv("CHANNEL_ID")

try:
    ADMIN_ID = int(ADMIN_ID_RAW)
except ValueError:
    ADMIN_ID = 0

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN topilmadi! .env faylini tekshiring (BOT_TOKEN=... qatorini kiriting)."
    )
if not ADMIN_ID:
    raise ValueError(
        "ADMIN_ID topilmadi yoki noto'g'ri! .env faylida ADMIN_ID=sizning_telegram_id_ingiz deb yozing."
    )
if not CHANNEL_ID:
    raise ValueError(
        "CHANNEL_ID topilmadi! .env faylida CHANNEL_ID=@kanal_username yoki -100... deb yozing."
    )
