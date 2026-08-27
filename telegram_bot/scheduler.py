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
    
    # 1. Post egasining URL tugmasi
    if custom_btn_text and custom_btn_url:
        keyboard.append([InlineKeyboardButton(custom_btn_text, url=custom_btn_url)])
        
    # 2. Reaksiya tugmalari
    if enable_reactions:
        counts = db.get_reaction_counts(post_id)
        react_row = []
        for emoji in DEFAULT_REACTIONS:
            c = counts.get(emoji, 0)
            label = f"{emoji} {c}" if c > 0 else emoji
            react_row.append(InlineKeyboardButton(label, callback_data=f"react:{post_id}:{emoji}"))
        keyboard.append(react_row)

    return InlineKeyboardMarkup(keyboard) if keyboard else None

def _next_weekly_occurrence(current_scheduled_time, now):
    next_time = current_scheduled_time + timedelta(weeks=1)
    while next_time <= now:
        next_time += timedelta(weeks=1)
    return next_time

async def _send_with_fallback(send_func, **kwargs):
    """Markdown formati xato bo'lsa, oddiy matn sifatida xatosiz yuborish himoyasi"""
    try:
        await send_func(**kwargs, parse_mode="Markdown")
    except TelegramError as e:
        if "can't parse entities" in str(e).lower():
            await send_func(**kwargs, parse_mode=None)
        else:
            raise e

async def _send_by_type(bot, target_chat, post_type, content, file_id, markup):
    caption = content or ""
    
    # Reklama imzosini tepaga qo'yish
    ad_title = db.get_setting("ad_title", "")
    ad_link = db.get_setting("ad_link", "")
    header = ""
    if ad_title and ad_link:
        header = f"📢 [{ad_title}]({ad_link})\n\n"
    elif getattr(bot, "username", None):
        header = f"🤖 [@{bot.username}]\n\n"
        
    full_caption = header + caption if header else caption

    if post_type == "text":
        await _send_with_fallback(bot.send_message, chat_id=target_chat, text=full_caption, reply_markup=markup)
    elif post_type == "photo":
        await _send_with_fallback(bot.send_photo, chat_id=target_chat, photo=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "video":
        await _send_with_fallback(bot.send_video, chat_id=target_chat, video=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "animation":
        await _send_with_fallback(bot.send_animation, chat_id=target_chat, animation=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "document":
        await _send_with_fallback(bot.send_document, chat_id=target_chat, document=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "audio":
        await _send_with_fallback(bot.send_audio, chat_id=target_chat, audio=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "voice":
        await _send_with_fallback(bot.send_voice, chat_id=target_chat, voice=file_id, caption=full_caption, reply_markup=markup)
    elif post_type == "video_note":
        await bot.send_video_note(chat_id=target_chat, video_note=file_id)
    elif post_type == "sticker":
        await bot.send_sticker(chat_id=target_chat, sticker=file_id, reply_markup=markup)
    else:
        await _send_with_fallback(bot.send_message, chat_id=target_chat, text=full_caption, reply_markup=markup)

async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    posts = db.get_due_posts(now)
    if not posts:
        return

    for post in posts:
        (post_id, user_id, channel_id, post_type, content, file_id,
         btn_text, btn_url, enable_reactions, scheduled_time, is_recurring, recurrence_day, recurrence_time) = post
        
        markup = build_post_keyboard(post_id, btn_text, btn_url, enable_reactions)
        try:
            target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id
            await _send_by_type(bot, target_chat, post_type, content, file_id, markup)
            if is_recurring:
                next_time = _next_weekly_occurrence(scheduled_time, now)
                db.reschedule_recurring_post(post_id, next_time)
            else:
                db.mark_post_status(post_id, "posted")
        except TelegramError as e:
            logger.error(f"Post #{post_id} yuborishda xato: {e}")
            if not is_recurring:
                db.mark_post_status(post_id, "failed")
            try:
                await bot.send_message(chat_id=user_id, text=f"⚠️ Post #{post_id} yuborilmadi: {e}")
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Kutilmagan xato: {e}")
            if not is_recurring:
                db.mark_post_status(post_id, "failed")
