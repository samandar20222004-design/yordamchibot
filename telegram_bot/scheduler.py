import asyncio
import json
import logging
from datetime import datetime, timedelta
import pytz
from telegram import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
)
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


def compose_post_text(content: str, has_ad_free: bool, channel_ad: str, brand_text: str = "") -> str:
    """Post matniga (ixtiyoriy) admin reklamasi va nishonni qo'shadi.

    ``brand_text`` — admin belgilagan so'z/watermark (masalan ``@PostAssistrobot``).
    Standart qiymati bo'sh, ya'ni majburiy watermark YO'Q — litsenziyasiz post ham
    toza chiqadi; nishon faqat admin yoqsa qo'shiladi.
    """
    text = content or ""
    ad = (channel_ad or "").strip()
    if not has_ad_free and ad:
        text = f"{text}\n\n{ad}" if text else ad

    brand = (brand_text or "").strip()
    if brand:
        text = f"{text}\n\n{brand}" if text else brand
    return text


def parse_album_items(file_id) -> list:
    """Albom JSON'ini listga aylantiradi; xato bo'lsa bo'sh list."""
    if not file_id:
        return []
    try:
        items = json.loads(file_id) if isinstance(file_id, str) else file_id
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    cleaned = []
    for item in items[:10]:
        if not isinstance(item, dict):
            continue
        fid = item.get("file_id")
        kind = (item.get("type") or "photo").lower()
        if fid:
            cleaned.append({"type": kind, "file_id": fid, "caption": item.get("caption") or ""})
    return cleaned


def _build_album_media(items: list, caption: str):
    media = []
    for i, item in enumerate(items):
        cap = caption if i == 0 else None
        parse = "HTML" if cap else None
        fid = item["file_id"]
        kind = item["type"]
        if kind == "video":
            media.append(InputMediaVideo(media=fid, caption=cap, parse_mode=parse))
        elif kind == "document":
            media.append(InputMediaDocument(media=fid, caption=cap, parse_mode=parse))
        elif kind == "audio":
            media.append(InputMediaAudio(media=fid, caption=cap, parse_mode=parse))
        else:
            media.append(InputMediaPhoto(media=fid, caption=cap, parse_mode=parse))
    return media


async def check_and_send_posts(bot):
    """Muddati yetgan postlarni yuborish (har 1 daqiqada scheduler orqali).

    Barcha DB chaqiruvlari alohida thread'da bajariladi (db.run_db),
    shuning uchun Telegram polling event loop'ini bloklamaydi. Postlar atomik
    ravishda 'processing' holatiga o'tkaziladi — takroriy yuborish bo'lmaydi.
    """
    try:
        now = datetime.now(tashkent_tz)
        due_posts = await db.run_db(db.get_due_posts, now)
        if due_posts:
            logger.info("Yuboriladigan postlar soni: %d", len(due_posts))
        for post in due_posts:
            try:
                await _execute_send(bot, post)
            except Exception:
                logger.exception("Post yuborishda kutilmagan xato (Post ID: %s)", post[0] if post else "?")
                # Xatolik yuz berganda post 'processing' da qolib ketmasligi uchun qayta navbatga qo'yamiz.
                try:
                    await db.run_db(db.retry_post, post[0], datetime.now(tashkent_tz) + timedelta(minutes=1))
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

    is_admin = (user_id == ADMIN_ID)

    # Litsenziyani yuborishdan OLDIN tekshiramiz; sarflash faqat
    # muvaffaqiyatli yuborilgandan keyin amalga oshiriladi.
    has_ad_free = True if is_admin else await db.run_db(db.peek_ad_free_post, user_id)
    channel_ad = ""
    if not has_ad_free:
        channel_ad = (await db.run_db(db.get_setting, "channel_ad_text", "")).strip()
    # Admin tomonidan yoqilgan nishon (masalan @PostAssistrobot) — bo'sh bo'lsa qo'shilmaydi.
    brand_text = (await db.run_db(db.get_setting, "post_tag_text", "")).strip()
    final_content = compose_post_text(content, has_ad_free, channel_ad, brand_text)

    sent_msg = None
    extra_ids = []
    try:
        # Telegram caption limiti 1024, oddiy matn limiti 4096 belgidan iborat.
        pt_for_limit = str(post_type).lower()
        if pt_for_limit in ("photo", "video", "animation", "document", "audio", "voice", "album"):
            final_content = final_content[:1024]
        else:
            final_content = final_content[:4096]
    except Exception:
        logger.exception("Post matnini tayyorlashda xatolik (Post ID: %s)", post_id)
        await db.run_db(db.mark_post_status, post_id, "failed")
        return

    try:
        pt = str(post_type).lower()
        target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id

        if pt == "album":
            items = parse_album_items(file_id)
            if not items:
                logger.error("Albom tarkibi bo'sh (Post ID: %s)", post_id)
                await db.run_db(db.mark_post_status, post_id, "failed")
                return
            if len(items) == 1:
                # Bitta element — oddiy media (tugmalar ishlashi uchun)
                only = items[0]
                sent_msg = await _send_single_media(
                    bot, target_chat, only["type"], only["file_id"], final_content, reply_markup
                )
            else:
                media = _build_album_media(items, final_content)
                sent_group = await bot.send_media_group(chat_id=target_chat, media=media)
                sent_msg = sent_group[0] if sent_group else None
                extra_ids = [m.message_id for m in (sent_group or [])[1:] if getattr(m, "message_id", None)]
                # sendMediaGroup reply_markup'ni qo'llab-quvvatlamaydi — tugmalarni alohida xabar
                if reply_markup:
                    follow = await bot.send_message(
                        chat_id=target_chat, text="🔗", reply_markup=reply_markup
                    )
                    if follow and follow.message_id:
                        extra_ids.append(follow.message_id)
        elif pt == "photo":
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
            sent_msg = await bot.send_message(chat_id=target_chat, text=final_content or " ", reply_markup=reply_markup, parse_mode="HTML")

        sent_msg_id = sent_msg.message_id if sent_msg else None
        await db.run_db(
            db.mark_post_as_sent, post_id, sent_msg_id, channel_id, delete_after_hours, extra_ids or None
        )
        # Post muvaffaqiyatli chiqqachgina litsenziya sarflanadi
        if has_ad_free and not is_admin:
            await db.run_db(db.consume_ad_free_post, user_id)

    except RetryAfter as e:
        # Telegram rate-limit vaqtinchalik: postni yo'qotmasdan,
        # Telegram ko'rsatgan vaqtdan keyin qayta navbatga qo'yamiz.
        wait_seconds = max(5, int(getattr(e, "retry_after", 5) or 5))
        logger.warning(f"Telegram rate limit (Post ID: {post_id}), {wait_seconds}s dan keyin qayta uriniladi")
        retry_at = datetime.now(tashkent_tz) + timedelta(seconds=wait_seconds)
        await db.run_db(db.retry_post, post_id, retry_at)
        return
    except (TimedOut, NetworkError) as e:
        logger.warning(f"Telegram tarmoq xatosi (Post ID: {post_id}): {e}; qayta uriniladi")
        retry_at = datetime.now(tashkent_tz) + timedelta(seconds=NETWORK_RETRY_DELAY)
        await db.run_db(db.retry_post, post_id, retry_at)
        return
    except TelegramError as e:
        logger.error(f"Post yuborishda xato (Post ID: {post_id}): {e}")
        await db.run_db(db.mark_post_status, post_id, "failed")
        return

    if recurrence_type in ('daily', 'weekly'):
        now = datetime.now(tashkent_tz)
        if end_date and now >= end_date:
            await db.run_db(db.mark_post_status, post_id, "completed")
        else:
            next_time = calculate_next_time(recurrence_type, recurrence_day, recurrence_time, now)
            if next_time:
                await db.run_db(db.reschedule_recurring_post, post_id, next_time)
                await db.run_db(db.mark_post_status, post_id, "pending")


async def _send_single_media(bot, target_chat, kind, file_id, caption, reply_markup):
    kind = (kind or "photo").lower()
    if kind == "video":
        return await bot.send_video(chat_id=target_chat, video=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "document":
        return await bot.send_document(chat_id=target_chat, document=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "audio":
        return await bot.send_audio(chat_id=target_chat, audio=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    if kind == "animation":
        return await bot.send_animation(chat_id=target_chat, animation=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")
    return await bot.send_photo(chat_id=target_chat, photo=file_id, caption=caption, reply_markup=reply_markup, parse_mode="HTML")


async def check_and_delete_expired_posts(bot):
    """Avto-o'chirish muddati yetgan xabarlarni kanaldan o'chirish (har 1 daqiqada)."""
    try:
        now = datetime.now(tashkent_tz)
        to_delete = await db.run_db(db.get_posts_to_delete, now)
        for item in to_delete:
            pid, ch_id, msg_id = item
            try:
                target_chat = int(ch_id) if str(ch_id).lstrip('-').isdigit() else ch_id
                await bot.delete_message(chat_id=target_chat, message_id=msg_id)
            except Exception as e:
                logger.warning(f"Avto-o'chirish xatosi (Post {pid}): {e}")
            finally:
                # Xabar topilmasa ham, qayta-qayta urinmaslik uchun bazada belgilab qo'yamiz.
                await db.run_db(db.mark_post_as_deleted, pid)
    except Exception:
        logger.exception("Avto-o'chirish ishida kutilmagan xato")


async def cleanup_old_data_job():
    """Eski ma'lumotlarni tozalash (har 6 soatda) — baza o'sib ketmasligi uchun."""
    try:
        result = await db.run_db(db.cleanup_old_data)
        logger.info("DB tozalash yakunlandi: %s", result)
    except Exception:
        logger.exception("DB tozalashda kutilmagan xato")
