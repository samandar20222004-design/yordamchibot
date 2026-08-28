import logging
from telegram import BotCommand
from telegram.ext import ApplicationBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import BOT_TOKEN
import database as db
from scheduler import check_and_send_posts, check_and_delete_expired_posts
from handlers import register_all_handlers
from utils.web_server import start_web_server

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

async def post_init(application):
    # 1. Web serverni yoqish
    await start_web_server()
    
    # 2. Telegram pastki chap "Menyu" tugmasiga standart buyruqlarni o'rnatish
    commands = [
        BotCommand("start", "Asosiy menyu va botni ishga tushirish"),
        BotCommand("newpost", "Yangi post rejalashtirish"),
        BotCommand("profile", "Kabinet, ballar va taklif havolasi"),
        BotCommand("help", "Bot qo'llanmasi va vazifalari"),
        BotCommand("cancel", "Joriy amalni bekor qilish"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Telegram Menyu buyruqlari muvaffaqiyatli o'rnatildi.")
    except Exception as e:
        logger.warning(f"Menyu buyruqlarini o'rnatishda xatolik: {e}")

def main():
    db.init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    register_all_handlers(app)

    scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
    scheduler.add_job(check_and_send_posts, 'interval', minutes=1, args=[app.bot], misfire_grace_time=30)
    scheduler.add_job(check_and_delete_expired_posts, 'interval', minutes=1, args=[app.bot], misfire_grace_time=30)
    scheduler.start()

    logger.info("Bot muvaffaqiyatli ishga tushdi.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
