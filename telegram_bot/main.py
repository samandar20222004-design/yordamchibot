import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from config import BOT_TOKEN
import database as db
from handlers import register_all_handlers
from scheduler import check_and_send_posts
from telegram.ext import ApplicationBuilder
from utils.web_server import start_web_server

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def post_init(application):
  await start_web_server()


def main():
  db.init_db()
  app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
  register_all_handlers(app)

  scheduler = AsyncIOScheduler(timezone="Asia/Tashkent")
  scheduler.add_job(
      check_and_send_posts, "interval", minutes=1, args=[app.bot]
  )
  scheduler.start()

  logger.info("Bot muvaffaqiyatli ishga tushdi.")
  app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
  main()
