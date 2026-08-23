import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import get_due_posts, mark_post_sent

logger = logging.getLogger(__name__)

async def check_and_send_posts(bot):
    due_posts = get_due_posts()
    for post in due_posts:
        post_id, channel_id, text, photo = post
        try:
            if photo:
                await bot.send_photo(chat_id=channel_id, photo=photo, caption=text)
            else:
                await bot.send_message(chat_id=channel_id, text=text)
            mark_post_sent(post_id)
            logger.info(f"Post #{post_id} {channel_id} kanaliga muvaffaqiyatli yuborildi.")
        except Exception as e:
            logger.error(f"Post #{post_id} ni {channel_id} ga yuborishda xatolik: {e}")

def start_scheduler(bot):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_posts, "interval", minutes=1, args=[bot])
    scheduler.start()
    return scheduler
