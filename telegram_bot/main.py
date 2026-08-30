import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder
from telegram import BotCommand
from config import BOT_TOKEN
import database as db
from handlers import register_all_handlers
from scheduler import check_and_send_posts, check_and_delete_expired_posts
from utils.web_server import start_web_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Bosh menyu"),
        BotCommand("newpost", "Yangi post rejalashtirish"),
        BotCommand("profile", "Kabinet va sozlamalar"),
        BotCommand("help", "Yordam va qo'llanma"),
        BotCommand("cancel", "Amalni bekor qilish"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Telegram Menyu buyruqlari muvaffaqiyatli o'rnatildi.")
    except Exception as e:
        logger.warning(f"Menyu buyruqlarini o'rnatishda xatolik: {e}")

async def main():
    db.init_db()

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    register_all_handlers(application)
    web_runner = await start_web_server()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_posts, 'interval', minutes=1, args=[application.bot], id="check_and_send_posts")
    scheduler.add_job(check_and_delete_expired_posts, 'interval', minutes=1, args=[application.bot], id="check_and_delete_expired_posts")
    scheduler.start()
    logger.info("Scheduler started.")

    await application.initialize()
    await application.start()
    await set_bot_commands(application)
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot muvaffaqiyatli ishga tushdi.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatilmoqda...")
    finally:
        scheduler.shutdown(wait=False)
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await web_runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
