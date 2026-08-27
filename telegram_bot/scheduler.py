import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from database import get_due_posts, mark_post_status, reschedule_recurring_post

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

# Botni tarqatuvchi "imzo" tugmasi keshi (bot.username har safar API'dan so'ralmasligi uchun)
_bot_username_cache = None


def _get_promo_markup(bot) -> Optional[InlineKeyboardMarkup]:
    """
    O'sish uchun: har bir chiqadigan postga botga havola beruvchi tugma qo'shiladi.
    Post boshqa kanal/guruhga forward qilinganda ham bot doimiy targ'ib bo'ladi
    (postassist_features_plan.pdf, 1-bosqich: "Tugmali Post Generatori + Bot Imzosi").
    """
    global _bot_username_cache
    try:
        username = _bot_username_cache or getattr(bot, "username", None)
        if not username:
            return None
        _bot_username_cache = username
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🤖 Bot orqali yaratildi", url=f"https://t.me/{username}")]
        ])
    except Exception:
        return None


def _next_weekly_occurrence(current_scheduled_time, now):
    """
    Takrorlanuvchi (haftalik) post uchun keyingi chiqish vaqtini hisoblaydi.
    Agar bot vaqtincha ishlamay qolgan bo'lsa (masalan bir necha hafta), "hozir"dan
    keyingi birinchi mos vaqtgacha bir necha hafta qo'shib davom etadi (o'zini tuzatadi).
    """
    next_time = current_scheduled_time + timedelta(weeks=1)
    while next_time <= now:
        next_time += timedelta(weeks=1)
    return next_time


async def _send_by_type(bot, target_chat, post_type, content, file_id, promo_markup):
    """
    Post turi qanday bo'lishidan qat'iy nazar (matn, rasm, video, gif, audio,
    ovozli xabar, hujjat, stiker, video-doira) — hammasi bir xilda, avtomatik
    to'g'ri Telegram metodiga yo'naltiriladi. Foydalanuvchi post turini qo'lda
    tanlashi shart emas.
    """
    caption = content or ""

    if post_type == "text":
        await bot.send_message(chat_id=target_chat, text=caption, reply_markup=promo_markup)
    elif post_type == "photo":
        await bot.send_photo(chat_id=target_chat, photo=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "video":
        await bot.send_video(chat_id=target_chat, video=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "animation":
        await bot.send_animation(chat_id=target_chat, animation=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "document":
        await bot.send_document(chat_id=target_chat, document=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "audio":
        await bot.send_audio(chat_id=target_chat, audio=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "voice":
        await bot.send_voice(chat_id=target_chat, voice=file_id, caption=caption, reply_markup=promo_markup)
    elif post_type == "video_note":
        # sendVideoNote caption/keyboardni qo'llab-quvvatlamaydi (Telegram cheklovi).
        await bot.send_video_note(chat_id=target_chat, video_note=file_id)
    elif post_type == "sticker":
        # Stikerlar caption qo'llamaydi, lekin inline tugma qo'llaydi.
        await bot.send_sticker(chat_id=target_chat, sticker=file_id, reply_markup=promo_markup)
    else:
        # Noma'lum tur bo'lsa ham, hech bo'lmasa matnni yuborishga harakat qilamiz.
        await bot.send_message(chat_id=target_chat, text=caption or f"[{post_type}]", reply_markup=promo_markup)


async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    posts = get_due_posts(now)

    if not posts:
        return

    promo_markup = _get_promo_markup(bot)

    for post in posts:
        (post_id, user_id, channel_id, post_type, content, file_id,
         scheduled_time, is_recurring, recurrence_day, recurrence_time) = post
        try:
            target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

            await _send_by_type(bot, target_chat, post_type, content, file_id, promo_markup)

            if is_recurring:
                next_time = _next_weekly_occurrence(scheduled_time, now)
                reschedule_recurring_post(post_id, next_time)
                logger.info(f"PostAssistrobot: Takrorlanuvchi post #{post_id} yuborildi, keyingisi: {next_time}")
            else:
                mark_post_status(post_id, "posted")
                logger.info(f"PostAssistrobot: Post #{post_id} muvaffaqiyatli yuborildi.")

        except TelegramError as e:
            logger.error(f"PostAssistrobot: Post #{post_id} yuborishda xato: {e}")
            if not is_recurring:
                mark_post_status(post_id, "failed")
            try:
                # Diqqat: bu yerda parse_mode ishlatilmaydi — Telegram xatolik matni
                # ("e") ichida "_" yoki "*" kabi belgilar bo'lishi mumkin, bu esa
                # Markdown bilan yuborilsa xabarning o'zi ham yuborilmay qolishiga
                # sabab bo'lardi.
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⚠️ Post #{post_id} yuborilmadi!\n\n"
                        f"Sabab: {e}\n\n"
                        f"Ehtimol bot kanal/guruhda postlash huquqiga ega emas yoki u yerdan "
                        f"chiqarib yuborilgan. Iltimos, botni qayta admin/a'zo qilib qo'shing."
                    )
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"PostAssistrobot: Post #{post_id} yuborishda kutilmagan xato: {e}")
            if not is_recurring:
                mark_post_status(post_id, "failed")
