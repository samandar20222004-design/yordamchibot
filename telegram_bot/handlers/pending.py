from datetime import datetime, timedelta
import pytz
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
import database as db
from keyboards.inline import render_pending_list
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from utils.helpers import format_post_type_label, format_schedule_line, html_escape

tashkent_tz = pytz.timezone("Asia/Tashkent")
EDIT_POST_TIME = 201

def _build_pending_view(user_id: int):
    user_code = db.get_user_code(user_id)
    posts = db.get_pending_posts(user_id)
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
    context.user_data.clear()
    user_id = update.effective_user.id
    text, markup = _build_pending_view(user_id)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")

async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        parts = query.data.split(":")
        post_id = int(parts[1])
        db.cancel_post(post_id, user_id)
        await query.answer("✅ Post bekor qilindi.")
        
        text, markup = _build_pending_view(user_id)
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await query.answer(f"Xatolik: {e}", show_alert=True)

async def edit_post_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    parts = query.data.split(":")
    post_id = int(parts[1])
    
    context.user_data["editing_post_id"] = post_id
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="🕒 <b>Post uchun yangi chiqish vaqtini yuboring:</b>\n\n"
             "• Bir martalik post bo'lsa: <code>2026-08-30 20:00</code>\n"
             "• Har kunlik post bo'lsa faqat soat: <code>10:00</code>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return EDIT_POST_TIME

async def edit_post_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    post_id = context.user_data.get("editing_post_id")
    post = db.get_post_by_id(post_id)
    # Tuzatildi: avval bu yerda mavjud bo'lmagan `query` o'zgaruvchisi ishlatilgan edi
    # (NameError yuz berardi). Endi to'g'ridan-to'g'ri foydalanuvchi ID'si tekshiriladi.
    if post and post[1] != update.effective_user.id:
        await update.message.reply_text("❌ Bu post sizga tegishli emas.")
        return ConversationHandler.END
    
    if not post:
        await update.message.reply_text("❌ Post topilmadi.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    try:
        if ":" in text and len(text) == 5:
            hh, mm = map(int, text.split(":"))
            new_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if new_run <= now:
                new_run += timedelta(days=1)
            db.update_post_time(post_id, new_run, f"{hh:02d}:{mm:02d}:00", user_id=update.effective_user.id)
        else:
            naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            new_time = tashkent_tz.localize(naive_time)
            if new_time <= now:
                await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
                return EDIT_POST_TIME
            db.update_post_time(post_id, new_time, user_id=update.effective_user.id)
            
        await update.message.reply_text("✅ <b>Post vaqti muvaffaqiyatli yangilandi!</b>", reply_markup=get_main_keyboard(), parse_mode="HTML")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: <code>2026-08-30 20:00</code> yoki <code>10:00</code>", parse_mode="HTML")
        return EDIT_POST_TIME
