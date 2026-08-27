import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from database import get_due_posts, mark_post_status, reschedule_recurring_post

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

_bot_username_cache = None

def _get_combined_markup(bot, custom_btn_text: Optional[str] = None, custom_btn_url: Optional[str] = None) -> Optional[InlineKeyboardMarkup]:
    """
    Foydalanuvchi kiritgan maxsus havola tugmasini va botning promo imzosini birlashtiradi.
    """
    global _bot_username_cache
    keyboard = []
    
    # 1. Foydalanuvchi postiga qo'shgan havola tugmasi
    if custom_btn_text and custom_btn_url:
        keyboard.append([InlineKeyboardButton(custom_btn_text, url=custom_btn_url)])
        
    # 2. Botning doimiy tarqatuvchi promo imzosi
    try:
        username = _bot_username_cache or getattr(bot, "username", None)
        if username:
            _bot_username_cache = username
            keyboard.append([InlineKeyboardButton("✨ Bot orqali yaratildi", url=f"https://t.me/{username}")])
    except Exception:
        pass

    return InlineKeyboardMarkup(keyboard) if keyboard else None

def _next_weekly_occurrence(current_scheduled_time, now):
    next_time = current_scheduled_time + timedelta(weeks=1)
    while next_time <= now:
        next_time += timedelta(weeks=1)
    return next_time

async def _send_by_type(bot, target_chat, post_type, content, file_id, markup):
    caption = content or ""
    if post_type == "text":
        await bot.send_message(chat_id=target_chat, text=caption, reply_markup=markup)
    elif post_type == "photo":
        await bot.send_photo(chat_id=target_chat, photo=file_id, caption=caption, reply_markup=markup)
    elif post_type == "video":
        await bot.send_video(chat_id=target_chat, video=file_id, caption=caption, reply_markup=markup)
    elif post_type == "animation":
        await bot.send_animation(chat_id=target_chat, animation=file_id, caption=caption, reply_markup=markup)
    elif post_type == "document":
        await bot.send_document(chat_id=target_chat, document=file_id, caption=caption, reply_markup=markup)
    elif post_type == "audio":
        await bot.send_audio(chat_id=target_chat, audio=file_id, caption=caption, reply_markup=markup)
    elif post_type == "voice":
        await bot.send_voice(chat_id=target_chat, voice=file_id, caption=caption, reply_markup=markup)
    elif post_type == "video_note":
        await bot.send_video_note(chat_id=target_chat, video_note=file_id)
    elif post_type == "sticker":
        await bot.send_sticker(chat_id=target_chat, sticker=file_id, reply_markup=markup)
    else:
        await bot.send_message(chat_id=target_chat, text=caption or f"[{post_type}]", reply_markup=markup)

async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    posts = get_due_posts(now)
    if not posts:
        return

    for post in posts:
        (post_id, user_id, channel_id, post_type, content, file_id,
         btn_text, btn_url, scheduled_time, is_recurring, recurrence_day, recurrence_time) = post
        
        markup = _get_combined_markup(bot, btn_text, btn_url)
        
        try:
            target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id
            await _send_by_type(bot, target_chat, post_type, content, file_id, markup)
            
            if is_recurring:
                next_time = _next_weekly_occurrence(scheduled_time, now)
                reschedule_recurring_post(post_id, next_time)
                logger.info(f"Takrorlanuvchi post #{post_id} yuborildi, keyingisi: {next_time}")
            else:
                mark_post_status(post_id, "posted")
                logger.info(f"Post #{post_id} muvaffaqiyatli yuborildi.")
        except TelegramError as e:
            logger.error(f"Post #{post_id} yuborishda xato: {e}")
            if not is_recurring:
                mark_post_status(post_id, "failed")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⚠️ Post #{post_id} kanalga yuborilmadi!\n\n"
                        f"Sabab: {e}\n\n"
                        f"Iltimos, botning kanalda adminlik huquqini tekshiring."
                    )
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Post #{post_id} yuborishda kutilmagan xato: {e}")
            if not is_recurring:
                mark_post_status(post_id, "failed")
