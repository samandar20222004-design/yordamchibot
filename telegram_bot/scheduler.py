import asyncio
import logging
from datetime import datetime, timedelta
import pytz
from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError
from config import ADMIN_ID
import database as db

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

# Tarmoq xatosidan keyin qayta urinishdan oldin kutish (soniya)
NETWORK_RETRY_DELAY = 30


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
    """Muddati yetgan postlarni yuborish (har 1 daqiqada scheduler orqali).

    Barcha DB chaqiruvlari alohida thread'da bajariladi (asyncio.to_thread),
    shuning uchun Telegram polling event loop'ini bloklamaydi. Postlar atomik
    ravishda 'processing' holatiga o'tkaziladi — takroriy yuborish bo'lmaydi.
    """
    try:
        now = datetime.now(tashkent_tz)
        due_posts = await asyncio.to_thread(db.get_due_posts, now)
        if due_posts:
            logger.info("Yuboriladigan postlar soni: %d", len(due_posts))
        for post in due_posts:
            try:
                await _execute_send(bot, post)
            except Exception:
                logger.exception("Post yuborishda kutilmagan xato (Post ID: %s)", post[0] if post else "?")
                # Xatolik yuz berganda post 'processing' da qolib ketmasligi uchun qayta navbatga qo'yamiz.
                try:
                    await asyncio.to_thread(db.retry_post, post[0], datetime.now(tashkent_tz) + timedelta(minutes=1))
                except Exception:
                    logger.exception("Postni qayta navbatlashda xato (Post ID: %s)", post[0] if post else "?")
    except Exception:
        logger.exception("Scheduler ishida kutilmagan xato")


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

    # Litsenziyani yuborishdan OLDIN tekshiramiz; sarflash faqat
    # muvaffaqiyatli yuborilgandan keyin amalga oshiriladi.
    has_ad_free = True if is_admin else await asyncio.to_thread(db.peek_ad_free_post, user_id)

    # Faqat bot username qoldirildi (ortiqcha so'zlarsiz)
    if not has_ad_free:
        bot_header = "@PostAssistrobot\n\n"
        channel_ad = (await asyncio.to_thread(db.get_setting, "channel_ad_text", "")).strip()
        ad_footer = f"\n\n{channel_ad}" if channel_ad else ""
        final_content = f"{bot_header}{final_content}{ad_footer}"

    sent_msg = None
    try:
        # Telegram caption limiti 1024, oddiy matn limiti 4096 belgidan iborat.
        pt_for_limit = str(post_type).lower()
        if pt_for_limit in ("photo", "video", "animation", "document", "audio", "voice"):
            final_content = final_content[:1024]
        else:
            final_content = final_content[:4096]
    except Exception:
        logger.exception("Post matnini tayyorlashda xatolik (Post ID: %s)", post_id)
        await asyncio.to_thread(db.mark_post_status, post_id, "failed")
        return

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
        await asyncio.to_thread(db.mark_post_as_sent, post_id, sent_msg_id, channel_id, delete_after_hours)
        # Post muvaffaqiyatli chiqqachgina litsenziya sarflanadi
        if has_ad_free and not is_admin:
            await asyncio.to_thread(db.consume_ad_free_post, user_id)

    except RetryAfter as e:
        # Telegram rate-limit vaqtinchalik: postni yo'qotmasdan,
        # Telegram ko'rsatgan vaqtdan keyin qayta navbatga qo'yamiz.
        wait_seconds = max(5, int(getattr(e, "retry_after", 5) or 5))
        logger.warning(f"Telegram rate limit (Post ID: {post_id}), {wait_seconds}s dan keyin qayta uriniladi")
        retry_at = datetime.now(tashkent_tz) + timedelta(seconds=wait_seconds)
        await asyncio.to_thread(db.retry_post, post_id, retry_at)
        return
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Telegram tarmoq xatosi (Post ID: {post_id}): {e}; qayta uriniladi")
        retry_at = datetime.now(tashkent_tz) + timedelta(seconds=NETWORK_RETRY_DELAY)
        await asyncio.to_thread(db.retry_post, post_id, retry_at)
        return
    except TelegramError as e:
        logger.error(f"Post yuborishda xato (Post ID: {post_id}): {e}")
        await asyncio.to_thread(db.mark_post_status, post_id, "failed")
        return

    if recurrence_type in ('daily', 'weekly'):
        now = datetime.now(tashkent_tz)
        if end_date and now >= end_date:
            await asyncio.to_thread(db.mark_post_status, post_id, "completed")
        else:
            next_time = calculate_next_time(recurrence_type, recurrence_day, recurrence_time, now)
            if next_time:
                await asyncio.to_thread(db.reschedule_recurring_post, post_id, next_time)
                await asyncio.to_thread(db.mark_post_status, post_id, "pending")


async def check_and_delete_expired_posts(bot):
    """Avto-o'chirish muddati yetgan xabarlarni kanaldan o'chirish (har 1 daqiqada)."""
    try:
        now = datetime.now(tashkent_tz)
        to_delete = await asyncio.to_thread(db.get_posts_to_delete, now)
        for item in to_delete:
            pid, ch_id, msg_id = item
            try:
                target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
                await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Avto-o'chirish xatosi (Post {pid}): {e}")
            finally:
                # Xabar topilmasa ham, qayta-qayta urinmaslik uchun bazada belgilab qo'yamiz.
                await asyncio.to_thread(db.mark_post_as_deleted, pid)
    except Exception:
        logger.exception("Avto-o'chirish ishida kutilmagan xato")


async def cleanup_old_data_job():
    """Eski ma'lumotlarni tozalash (har 6 soatda) — baza o'sib ketmasligi uchun."""
    try:
        result = await asyncio.to_thread(db.cleanup_old_data)
        logger.info("DB tozalash yakunlandi: %s", result)
    except Exception:
        logger.exception("DB tozalashda kutilmagan xato")
