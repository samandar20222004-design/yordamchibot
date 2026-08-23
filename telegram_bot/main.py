import os
import asyncio
import logging
from aiohttp import web
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters

from config import BOT_TOKEN
from database import init_db
from scheduler import start_scheduler

# Handlerlarni import qilish
from handlers.start import start_handler
from handlers.admin import admin_panel_handler
from handlers.new_post import new_post_conv_handler
from handlers.list_posts import list_posts_handler
from handlers.delete_post import delete_post_conv_handler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# UptimeRobot uchun veb-sahifa (ping)
async def handle_ping(request):
    return web.Response(text="Bot 24/7 faol ishlamoqda!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Veb-server {port}-portda ishga tushdi.")

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi! Render Environment Variables qismini tekshiring.")
        return

    # Bazani yaratish
    init_db()

    # Botni qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Barcha handlerlarni ulash
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("admin", admin_panel_handler))
    application.add_handler(new_post_conv_handler)
    application.add_handler(delete_post_conv_handler)
    application.add_handler(CommandHandler("posts", list_posts_handler))

    # Rejalashtiruvchini (Scheduler) ulash
    start_scheduler(application)

    # Veb-serverni ishga tushirish
    await run_web_server()

    # Botni ishga tushirish
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot Telegram xabarlarini muvaffaqiyatli qabul qilmoqda!")

    # Fondagi doimiy sikl
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
