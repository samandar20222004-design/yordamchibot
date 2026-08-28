import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
import database as db

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

DEFAULT_REACTIONS = ["👍", "❤️", "🔥", "👏"]

def build_post_keyboard(post_id: int, custom_btn_text: Optional[str], custom_btn_url: Optional[str], enable_reactions: bool) -> Optional[InlineKeyboardMarkup]:
    keyboard = []
    
    if custom_btn_text and custom_btn_url:
        keyboard.append([InlineKeyboardButton(custom_btn_text, url=custom_btn_url)])
        
    if enable_reactions:
        counts = db.get_reaction_counts(post_id)
        react_row = []
        for emoji in DEFAULT_REACTIONS:
            c = counts.get(emoji, 0)
            label = f"{emoji} {c}" if c > 0 else emoji
            react_row.append(InlineKeyboardButton(label, callback_data=f"react:{post_id}:{emoji}"))
        keyboard.append(react_row)

    return InlineKeyboardMarkup(keyboard) if keyboard else None

def _calculate_next_run(rec_type, current_time, now):
    if rec_type == 'daily':
        next_time = current_time + timedelta(days=1)
        while next_time <= now:
            next_time += timedelta(days=1)
        return next_time
    elif rec_type == 'weekly':
        next_time = current_time + timedelta(weeks=1)
        while next_time <= now:
            next_time += timedelta(weeks=1)
        return next_time
    return None

async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    posts = db.get_due_posts(now)
    if not posts:
        return

    for post in posts:
        (post_id, user_id, channel_id, post_type, content, file_id,
         btn_text, btn_url, enable_reactions, scheduled_time,
         recurrence_type, recurrence_day, recurrence_time, end_date) = post
        
        markup = build_post_keyboard(post_id, btn_text, btn_url, enable_reactions)
        try:
            target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id
            
            # Premium emojilar va formatlarni 100% asl holatda nusxalash
            if post_type == "original_message" and file_id:
                await bot.copy_message(
                    chat_id=target_chat,
                    from_chat_id=user_id,
                    message_id=int(file_id),
                    reply_markup=markup
                )
            else:
                caption = content or ""
                await bot.send_message(chat_id=target_chat, text=caption, reply_markup=markup)

            if recurrence_type in ('daily', 'weekly'):
                if end_date and now >= end_date:
                    db.mark_post_status(post_id, "completed")
                else:
                    next_time = _calculate_next_run(recurrence_type, scheduled_time, now)
                    if next_time and (end_date is None or next_time <= end_date):
                        db.reschedule_recurring_post(post_id, next_time)
                    else:
                        db.mark_post_status(post_id, "completed")
            else:
                db.mark_post_status(post_id, "posted")

        except TelegramError as e:
            logger.error(f"Post #{post_id} yuborishda xato: {e}")
            if recurrence_type == 'none':
                db.mark_post_status(post_id, "failed")
            try:
                await bot.send_message(chat_id=user_id, text=f"⚠️ Post #{post_id} kanalingizga yuborilmadi: {e}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Kutilmagan xato: {e}")
            if recurrence_type == 'none':
                db.mark_post_status(post_id, "failed")
