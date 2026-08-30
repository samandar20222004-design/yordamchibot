import asyncio
import logging
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder
from telegram import BotCommand
from config import BOT_TOKEN
import database as db
from handlers import register_all_handlers
from scheduler import (
    check_and_send_posts,
    check_and_delete_expired_posts,
    cleanup_old_data_job,
)
from utils.web_server import start_web_server
from utils.ai_agent import close_ai_session

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")


async def error_handler(update, context):
    """Hech qanday xatolik botni o'chirib yubormasligi uchun global ushlagich."""
    logger.error("Xatolik yuz berdi (update=%s): %s", update, context.error, exc_info=context.error)


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
        # Telegram API so'rovlari uchun aniq timeout'lar (Render Free'da
        # tarmoq sekinlashganda bot osilib qolmasligi uchun).
        .connect_timeout(15)
        .read_timeout(15)
        .write_timeout(30)
        .media_write_timeout(60)
        .pool_timeout(5)
        .connection_pool_size(8)
        .build()
    )

    # Kutilmagan xatoliklarni log qilish (jim o'tib ketmasligi uchun)
    application.add_error_handler(error_handler)

    register_all_handlers(application)
    web_runner = await start_web_server()

    # Scheduler: har bir ish (job) maks. 1 marta parallel ishlaydi (max_instances=1),
    # o'tkazib yuborilgan ishlar birlashtiriladi (coalesce), va bot qayta
    # ishga tushganda kechikkan postlar darhol tekshiriladi (next_run_time).
    scheduler = AsyncIOScheduler(timezone=tashkent_tz)
    scheduler.add_job(
        check_and_send_posts, 'interval', minutes=1, args=[application.bot],
        id="check_and_send_posts",
        max_instances=1, coalesce=True, misfire_grace_time=300,
        next_run_time=datetime.now(tashkent_tz),
    )
    scheduler.add_job(
        check_and_delete_expired_posts, 'interval', minutes=1, args=[application.bot],
        id="check_and_delete_expired_posts",
        max_instances=1, coalesce=True, misfire_grace_time=300,
        next_run_time=datetime.now(tashkent_tz),
    )
    scheduler.add_job(
        cleanup_old_data_job, 'interval', hours=6,
        id="cleanup_old_data",
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )

    await application.initialize()
    await application.start()
    await set_bot_commands(application)
    await application.updater.start_polling(drop_pending_updates=True)

    # Scheduler'ni app to'liq ishga tushgandan keyin boshlaymiz —
    # shunda birinchi ishlash ham to'liq tayyor muhitda bo'ladi.
    scheduler.start()
    logger.info("Scheduler started: postlar har 1 daqiqada, DB tozalash har 6 soatda.")
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
        db.close_pool()
        await close_ai_session()
        logger.info("Bot to'liq to'xtatildi va barcha resurslar yopildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
