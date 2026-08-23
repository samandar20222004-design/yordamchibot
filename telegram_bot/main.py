import os
import asyncio
import logging
from threading import Thread
from aiohttp import web
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters
)

from config import BOT_TOKEN, ADMIN_ID
from database import init_db
from scheduler import start_scheduler

# Barcha handler modullarini import qilish
from handlers import start, admin, new_post, list_posts, delete_post

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Render 24/7 faol turishi uchun veb-server (UptimeRobot uchun)
async def handle_ping(request):
    return web.Response(text="Bot 24/7 uzluksiz ishlamoqda!")

def start_background_web_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    loop.run_until_complete(site.start())
    logger.info(f"Veb-server {port}-portda faol.")
    loop.run_forever()

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN aniqlanmadi!")
        return

    # Ma'lumotlar bazasini tayyorlash
    init_db()

    # Veb-serverni fonda ishga tushirish
    Thread(target=start_background_web_server, daemon=True).start()

    # Telegram Bot dasturini qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 1. Yangi post yaratish dialogi (Conversation)
    if hasattr(new_post, "new_post_conv_handler"):
        application.add_handler(new_post.new_post_conv_handler)

    # 2. Postni o'chirish dialogi (Conversation)
    if hasattr(delete_post, "delete_post_conv_handler"):
        application.add_handler(delete_post.delete_post_conv_handler)

    # 3. Har bir modulning maxsus register_handlers funksiyalarini ulash
    for module in [start, admin, list_posts, new_post, delete_post]:
        if hasattr(module, "register_handlers"):
            module.register_handlers(application)

    # 4. Rejalashtiruvchi (Scheduler) ni ishga tushirish
    start_scheduler(application)

    # 5. Botni doimiy polling rejimida ishga tushirish
    logger.info("Bot barcha tugmalar va buyruqlar bilan to'liq ishga tushdi!")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
