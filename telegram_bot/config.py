import os

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi! .env faylida BOT_TOKEN ni to'g'ri kiriting.")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL topilmadi! .env faylida DATABASE_URL ni to'g'ri kiriting.")
if ADMIN_ID == 0:
    import logging
    logging.getLogger(__name__).warning(
        "ADMIN_ID sozlanmagan (0)! Admin panel va statistika hech kimga ko'rinmaydi."
    )
