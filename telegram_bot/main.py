import os
import asyncio
import logging
from aiohttp import web
from telegram.ext import ApplicationBuilder

from config import BOT_TOKEN
from database import init_db
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# UptimeRobot signallarini qabul qiluvchi kichik veb-sahifa
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
        logger.error("BOT_TOKEN topilmadi! Sozlamalarni tekshiring.")
        return

    # Bazani yaratish
    init_db()

    # Application qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Rejalashtiruvchini (Scheduler) ulash
    start_scheduler(application)

    # Handlerlarni ulash
    try:
        from handlers.start import register_handlers as reg_start
        reg_start(application)
    except Exception:
        pass

    # Veb-serverni fonda ishga tushirish
    await run_web_server()

    # Botni ishga tushirish (async tarzda)
    async with application:
        await application.start()
        await application.updater.start_polling()
        logger.info("Bot polling rejimida muvaffaqiyatli ishga tushdi!")
        # Doimiy ishlab turishi uchun
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
