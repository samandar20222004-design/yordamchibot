import logging
from datetime import datetime, timedelta
import pytz
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError
from config import ADMIN_ID
import database as db

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

def calculate_next_time(recurrence_type, recurrence_day, recurrence_time, current_time):
    now = current_time
    if recurrence_type == 'daily':
        next_dt = now.replace(hour=recurrence_time.hour, minute=recurrence_time.minute, second=0, microsecond=0)
        if next_dt <= now:
            next_dt += timedelta(days=1)
        return next_dt
    elif recurrence_type == 'weekly':
        days_ahead = (recurrence_day - now.weekday() + 7) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_dt = now.replace(hour=recurrence_time.hour, minute=recurrence_time.minute, second=0, microsecond=0) + timedelta(days=days_ahead)
        return next_dt
    return None

async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    due_posts = db.get_due_posts(now)
    for post in due_posts:
        await _execute_send(bot, post)

async def _execute_send(bot, post):
    (
        post_id, user_id, channel_id, post_type, content, file_id,
        btn_text, btn_url, enable_reactions, scheduled_time,
        recurrence_type, recurrence_day, recurrence_time, end_date, delete_after_hours
    ) = post

    buttons = []
    if btn_text and btn_url:
        buttons.append([InlineKeyboardButton(text=btn_text, url=btn_url)])
    if enable_reactions:
        reactions_row = [
            InlineKeyboardButton("👍", callback_data=f"react:{post_id}:👍"),
            InlineKeyboardButton("❤️", callback_data=f"react:{post_id}:❤️"),
            InlineKeyboardButton("🔥", callback_data=f"react:{post_id}:🔥"),
            InlineKeyboardButton("👏", callback_data=f"react:{post_id}:👏"),
        ]
        buttons.append(reactions_row)
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    final_content = content or ""
    is_admin = (user_id == ADMIN_ID)
    has_ad_free = db.consume_ad_free_post(user_id) if not is_admin else True

    # Faqat bot username qoldirildi (ortiqcha so'zlarsiz)
    if not has_ad_free:
        bot_header = "@PostAssistrobot\n\n"
        channel_ad = db.get_setting("channel_ad_text", "").strip()
        ad_footer = f"\n\n{channel_ad}" if channel_ad else ""
        final_content = f"{bot_header}{final_content}{ad_footer}"

    sent_msg = None
    try:
        pt = str(post_type).lower()
        target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

        if pt == "photo":
            sent_msg = await bot.send_photo(chat_id=target_chat, photo=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "video":
            sent_msg = await bot.send_video(chat_id=target_chat, video=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "animation":
            sent_msg = await bot.send_animation(chat_id=target_chat, animation=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "document":
            sent_msg = await bot.send_document(chat_id=target_chat, document=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "audio":
            sent_msg = await bot.send_audio(chat_id=target_chat, audio=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "voice":
            sent_msg = await bot.send_voice(chat_id=target_chat, voice=file_id, caption=final_content, reply_markup=reply_markup, parse_mode="HTML")
        elif pt == "sticker":
            sent_msg = await bot.send_sticker(chat_id=target_chat, sticker=file_id)
        else:
            sent_msg = await bot.send_message(chat_id=target_chat, text=final_content, reply_markup=reply_markup, parse_mode="HTML")

        sent_msg_id = sent_msg.message_id if sent_msg else None
        db.mark_post_as_sent(post_id, sent_msg_id)

    except TelegramError as e:
        logger.error(f"Post yuborishda xato (Post ID: {post_id}): {e}")
        db.mark_post_status(post_id, "failed")
        return

    if recurrence_type in ('daily', 'weekly'):
        now = datetime.now(tashkent_tz)
        if end_date and now >= end_date:
            db.mark_post_status(post_id, "completed")
        else:
            next_time = calculate_next_time(recurrence_type, recurrence_day, recurrence_time, now)
            if next_time:
                db.reschedule_recurring_post(post_id, next_time)
                db.mark_post_status(post_id, "pending")

async def check_and_delete_expired_posts(bot):
    now = datetime.now(tashkent_tz)
    to_delete = db.get_posts_to_delete(now)
    for item in to_delete:
        pid, ch_id, msg_id = item
        try:
            target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
            await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            db.mark_post_as_deleted(pid)
        except Exception as e:
            logger.warning(f"Avto-o'chirish xatosi (Post {pid}): {e}")
            db.mark_post_as_deleted(pid)
