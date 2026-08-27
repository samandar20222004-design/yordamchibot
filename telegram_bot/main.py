import logging
from telegram.ext import ApplicationBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN
import database as db
from scheduler import check_and_send_posts
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
    await start_web_server()

def main():
    # 1. Ma'lumotlar bazasini tayyorlash
    db.init_db()

    # 2. Bot dasturini qurish
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # 3. Barcha handlerlarni ulash
    register_all_handlers(app)

    # 4. Avtoposting schedulerini yoqish
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_posts, 'interval', minutes=1, args=[app.bot])
    scheduler.start()

    logger.info("Bot muvaffaqiyatli ishga tushdi.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
