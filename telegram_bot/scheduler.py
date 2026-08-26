import logging
from datetime import datetime
from typing import Optional

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError

from database import get_due_posts, mark_post_status

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


async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    posts = get_due_posts(now)

    if not posts:
        return

    promo_markup = _get_promo_markup(bot)

    for post in posts:
        post_id, user_id, channel_id, post_type, content, file_id = post
        try:
            target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

            if post_type == "photo" and file_id:
                await bot.send_photo(
                    chat_id=target_chat,
                    photo=file_id,
                    caption=content or "",
                    reply_markup=promo_markup
                )
            else:
                await bot.send_message(
                    chat_id=target_chat,
                    text=content or "",
                    reply_markup=promo_markup
                )

            mark_post_status(post_id, "posted")
            logger.info(f"PostAssistrobot: Post #{post_id} muvaffaqiyatli yuborildi.")

        except TelegramError as e:
            logger.error(f"PostAssistrobot: Post #{post_id} yuborishda xato: {e}")
            mark_post_status(post_id, "failed")
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"⚠️ **Post #{post_id} yuborilmadi!**\n\n"
                        f"Sabab: `{e}`\n\n"
                        f"Ehtimol bot kanalda admin emas yoki kanaldan chiqarib yuborilgan. "
                        f"Iltimos, botni kanalga admin qilib qo'shib, postni qayta rejalashtiring."
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f"PostAssistrobot: Post #{post_id} yuborishda kutilmagan xato: {e}")
            mark_post_status(post_id, "failed")
