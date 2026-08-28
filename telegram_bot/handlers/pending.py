from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
import database as db
from keyboards.inline import render_pending_list
from keyboards.default import get_cancel_keyboard, get_main_keyboard

tashkent_tz = pytz.timezone("Asia/Tashkent")
EDIT_POST_TIME = 50

async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    user_code = db.get_user_code(user_id)
    posts = db.get_pending_posts(user_id)
    text, markup = render_pending_list(posts, "📋 *Sizning kutilayotgan postlaringiz:*", user_code=user_code)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    try:
        _, pid_str, scope = query.data.split(":")
        post_id = int(pid_str)
        db.cancel_post(post_id, user_id)
        await query.answer("✅ Post muvaffaqiyatli bekor qilindi.")
        
        user_code = db.get_user_code(user_id)
        posts = db.get_pending_posts(user_id)
        text, markup = render_pending_list(posts, "📋 *Sizning kutilayotgan postlaringiz:*", user_code=user_code)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        await query.answer(f"Xatolik: {e}", show_alert=True)

async def edit_post_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    _, pid_str = query.data.split(":")
    post_id = int(pid_str)
    
    context.user_data["editing_post_id"] = post_id
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text="🕒 *Post uchun yangi chiqish vaqtini yuboring:*\n\n"
             "• Bir martalik post bo'lsa: `2026-08-28 20:00`\n"
             "• Har kunlik/haftalik post bo'lsa faqat soat: `10:00`",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return EDIT_POST_TIME

async def edit_post_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    post_id = context.user_data.get("editing_post_id")
    post = db.get_post_by_id(post_id)
    
    if not post:
        await update.message.reply_text("❌ Post topilmadi.", reply_markup=get_main_keyboard())
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    try:
        if ":" in text and len(text) == 5:
            hh, mm = map(int, text.split(":"))
            new_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if new_run <= now:
                new_run += datetime.timedelta(days=1)
            db.update_post_time(post_id, new_run, f"{hh:02d}:{mm:02d}:00")
        else:
            naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
            new_time = tashkent_tz.localize(naive_time)
            if new_time <= now:
                await update.message.reply_text("⚠️ Kelajakdagi vaqtni kiriting:")
                return EDIT_POST_TIME
            db.update_post_time(post_id, new_time)
            
        await update.message.reply_text("✅ *Post vaqti muvaffaqiyatli yangilandi!*", reply_markup=get_main_keyboard(), parse_mode="Markdown")
        context.user_data.clear()
        return ConversationHandler.END
    except Exception:
        await update.message.reply_text("⚠️ Format xato! Masalan: `2026-08-28 20:00` yoki `10:00`")
        return EDIT_POST_TIME
