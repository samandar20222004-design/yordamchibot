import pytz
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from config import TIMEZONE
from database import update_post_status

scheduler = AsyncIOScheduler(timezone=pytz.timezone(TIMEZONE))

async def send_scheduled_post(bot: Bot, post_id: int, channel_id: int, message_type: str, text_content: str, file_id: str, buttons_data: str):
    try:
        reply_markup = None
        if buttons_data:
            buttons = []
            for item in buttons_data.split("||"):
                if "-" in item:
                    title, url = item.split("-", 1)
                    buttons.append([InlineKeyboardButton(text=title.strip(), url=url.strip())])
            if buttons:
                reply_markup = InlineKeyboardMarkup(buttons)

        if message_type == 'photo' and file_id:
            await bot.send_photo(chat_id=channel_id, photo=file_id, caption=text_content, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await bot.send_message(chat_id=channel_id, text=text_content, reply_markup=reply_markup, parse_mode="HTML")
        
        update_post_status(post_id, "sent")
    except Exception as e:
        print(f"Post {post_id} yuborishda xatolik: {e}")
        update_post_status(post_id, f"failed: {str(e)[:40]}")

def schedule_post_job(bot: Bot, post_id: int, channel_id: int, message_type: str, text_content: str, file_id: str, buttons_data: str, scheduled_time: datetime):
    scheduler.add_job(
        send_scheduled_post,
        'date',
        run_date=scheduled_time,
        args=[bot, post_id, channel_id, message_type, text_content, file_id, buttons_data],
        id=f"post_{post_id}"
    )
