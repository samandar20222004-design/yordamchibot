import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
import database as db
from keyboards.inline import render_pending_list
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_reactions_keyboard
from locales.translations import clear_fsm_data, get_lang, get_text
from utils.helpers import (
    format_post_type_label, format_schedule_line, html_escape, check_rate_limit, parse_future_time,
    NAV_RATE_LIMIT_MAX, parse_reactions_input,
)

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")
# Eslatma: 201 SLOT_ADD (Queue) bilan to'qnashgan edi — endi 205 unikal.
EDIT_POST_TIME    = 205
EDIT_POST_CONTENT = 202  # Matnni tahrirlash
EDIT_POST_BTN     = 203  # Tugma havolasini o'zgartirish
EDIT_POST_REACT   = 204  # Reaksiyalarni o'zgartirish


async def _build_pending_view(user_id: int):
    user_code = await db.run_db(db.get_user_code, user_id)
    posts = await db.run_db(db.get_pending_posts, user_id)
    if not posts:
        return "⏳ <b>Sizda kutilayotgan faol postlar mavjud emas.</b>", None

    text = f"⏳ <b>Kutilayotgan postlaringiz ({len(posts)} ta):</b>\n\n"
    for p in posts:
        pid, ch_title, p_type, s_time, p_num, r_type, r_day, r_time = p
        code_label = f"{user_code}-{p_num}" if p_num else f"#{pid}"
        time_info = format_schedule_line(s_time, r_type, r_day, r_time)
        text += (
            f"🔹 <b>Post: {code_label}</b>\n"
            f"📢 Kanal: <b>{html_escape(ch_title or 'Kanal')}</b>\n"
            f"📦 Turi: <b>{format_post_type_label(p_type)}</b>\n"
            f"{time_info}\n\n"
        )
    markup = render_pending_list(posts, user_code)
    return text, markup


async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user_id = update.effective_user.id
    text, markup = await _build_pending_view(user_id)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    # Darhol javob — DB ishi tugaguncha tugma muzlab qolmasligi uchun.
    try:
        await query.answer()
    except Exception:
        pass

    try:
        parts = query.data.split(":")
        post_id = int(parts[1])
        await db.run_db(db.cancel_post, post_id, user_id)

        text, markup = await _build_pending_view(user_id)
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        try:
            await query.message.reply_text(f"⚠️ Xatolik: {e}")
        except Exception:
            pass


async def refresh_pending_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ro'yxatni qayta chizadi (🔄 Yangilash tugmasi)."""
    query = update.callback_query
    user_id = query.from_user.id
    is_blocked, _ = check_rate_limit(user_id, max_requests=NAV_RATE_LIMIT_MAX, window_seconds=2.0)
    if is_blocked:
        await query.answer("⏳ Iltimos, biroz kuting...", show_alert=False)
        return
    try:
        text, markup = await _build_pending_view(user_id)
        await query.answer("✅ Yangilandi")
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await query.answer("Yangilab bo'lmadi", show_alert=False)
        logger.warning("Pending yangilash xatosi: %s", e)


# ============================================================
# Postni tahrirlash oqimlari
# ============================================================

async def _get_owned_post(post_id: int, user_id: int, update: Update):
    """Post mavjudligi va egasini tekshiradi. Muvaffaqiyatsiz bo'lsa None qaytadi."""
    post = await db.run_db(db.get_post_by_id, post_id)
    if not post:
        await update.message.reply_text("❌ Post topilmadi.", reply_markup=get_main_keyboard())
        return None
    # post[1] = user_id (get_post_by_id jadvalida 2-ustun)
    if post[1] != user_id:
        await update.message.reply_text("❌ Bu post sizga tegishli emas.")
        return None
    return post


# ------ Vaqt tahrirlash ------

async def edit_post_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    post_id = int(parts[1])

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "time"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="🕒 <b>Post uchun yangi chiqish vaqtini yuboring:</b>\n\n"
             "• Bir martalik post bo'lsa: <code>2026-08-30 20:00</code>\n"
             "• Erkin format ham ishlaydi: <code>ertaga 18:00</code>, <code>bugun 10:00</code>\n"
             "• Har kunlik post bo'lsa faqat soat: <code>10:00</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return EDIT_POST_TIME


async def edit_post_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update)
    if not post:
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    try:
        if ":" in text and len(text) == 5:
            hh, mm = map(int, text.split(":"))
            new_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if new_run <= now:
                new_run += timedelta(days=1)
            await db.run_db(db.update_post_time, post_id, new_run, f"{hh:02d}:{mm:02d}:00", user_id=update.effective_user.id)
        else:
            new_time = parse_future_time(text, now)
            if new_time is None:
                naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
                new_time = tashkent_tz.localize(naive_time)
            if new_time <= now:
                await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
                return EDIT_POST_TIME
            await db.run_db(db.update_post_time, post_id, new_time, user_id=update.effective_user.id)

        await update.message.reply_text("✅ <b>Post vaqti muvaffaqiyatli yangilandi!</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
        clear_fsm_data(context)
        return ConversationHandler.END
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: <code>2026-08-30 20:00</code> yoki <code>10:00</code>", parse_mode="HTML")
        return EDIT_POST_TIME


# ------ Matn tahrirlash ------

async def edit_post_content_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post matnini tahrirlash boshlash."""
    query = update.callback_query
    parts = query.data.split(":")
    post_id = int(parts[1])

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "content"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="✏️ <b>Post uchun yangi matnni yuboring:</b>\n\n"
             "HTML teglar (<b>bold</b>, <i>italic</i>, <code>code</code>) qo'llab-quvvatlanadi.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return EDIT_POST_CONTENT


async def edit_post_content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_content = update.message.text
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update)
    if not post:
        return ConversationHandler.END

    updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, content=new_content)
    if updated:
        await update.message.reply_text("✅ <b>Post matni yangilandi!</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ O'zgartirib bo'lmadi.", reply_markup=get_main_keyboard())
    clear_fsm_data(context)
    return ConversationHandler.END


# ------ Tugma URL tahrirlash ------

async def edit_post_btn_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post tugmasini tahrirlash."""
    query = update.callback_query
    parts = query.data.split(":")
    post_id = int(parts[1])

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "btn"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="🔗 <b>Yangi tugma matnini yuboring:</b>\n\n"
             "Format: <code>Tugma matni | https://havola.uz</code>\n"
             "Tugmani o'chirish uchun: <code>yo'q</code> deb yozing.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return EDIT_POST_BTN


async def edit_post_btn_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update)
    if not post:
        return ConversationHandler.END

    if text.lower() in ("yo'q", "yoq", "none", "-", "o'chir"):
        updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, btn_text="", btn_url="")
        msg = "✅ <b>Tugma o'chirildi!</b>"
    elif "|" in text:
        parts = text.split("|", 1)
        btn_title = parts[0].strip()
        btn_link = parts[1].strip()
        if btn_link.startswith("@"):
            btn_link = f"https://t.me/{btn_link.lstrip('@')}"
        elif not btn_link.startswith(("http://", "https://", "t.me/")):
            btn_link = "https://" + btn_link
        updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, btn_text=btn_title, btn_url=btn_link)
        msg = f"✅ <b>Tugma yangilandi:</b> <code>{html_escape(btn_title)}</code>"
    else:
        await update.message.reply_text(
            "⚠️ Format xato!\nMasalan: <code>Batafsil | https://sayt.uz</code>\nYoki o'chirish: <code>yo'q</code>",
            parse_mode="HTML",
        )
        return EDIT_POST_BTN

    if updated:
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ O'zgartirib bo'lmadi.", reply_markup=get_main_keyboard())
    clear_fsm_data(context)
    return ConversationHandler.END


# ------ Reaksiya tahrirlash ------

async def edit_post_react_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post reaksiyalarini yoqish/o'chirish."""
    query = update.callback_query
    parts = query.data.split(":")
    post_id = int(parts[1])

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "react"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="👍 <b>Post reaksiyalarini o'zgartirish:</b>\n\nQuyidagidan birini tanlang:",
        reply_markup=get_reactions_keyboard(),
        parse_mode="HTML",
    )
    return EDIT_POST_REACT


async def edit_post_react_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update)
    if not post:
        return ConversationHandler.END

    parsed = parse_reactions_input(text)
    if parsed is None:
        await update.message.reply_text("⚠️ Tugmalardan birini tanlang:", reply_markup=get_reactions_keyboard())
        return EDIT_POST_REACT

    enable = parsed
    updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, enable_reactions=enable)
    msg = "✅ <b>Reaksiyalar yoqildi!</b>" if enable else "✅ <b>Reaksiyalar o'chirildi!</b>"
    if updated:
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ O'zgartirib bo'lmadi.", reply_markup=get_main_keyboard())
    clear_fsm_data(context)
    return ConversationHandler.END
