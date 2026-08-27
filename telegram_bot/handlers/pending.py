from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from config import ADMIN_ID
import database as db
from keyboards.default import get_main_keyboard
from keyboards.inline import render_pending_list

async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    posts = db.get_pending_posts(user_id)
    user_code = db.get_user_code(user_id)
    text, inline_markup = render_pending_list(posts, "📋 *Kutilayotgan postlaringiz:*", user_code=user_code)
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("Bekor qilish uchun tanlang 👇", reply_markup=inline_markup)

async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)
    try:
        _, pid_str, scope = query.data.split(":")
        post_id = int(pid_str)
    except Exception:
        await query.answer("Xatolik.", show_alert=True)
        return

    if db.cancel_post(post_id, user_id, is_admin=is_admin):
        await query.answer("Post bekor qilindi.")
    else:
        await query.answer("Bekor qilib bo'lmadi.", show_alert=True)
        return

    if scope == "all":
        posts = db.get_all_pending_posts()
        text, markup = render_pending_list(posts, "🗂 *Barcha kutilayotgan postlar:*", show_owner=True)
    else:
        posts = db.get_pending_posts(user_id)
        text, markup = render_pending_list(posts, "📋 *Kutilayotgan postlaringiz:*", user_code=db.get_user_code(user_id))
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except TelegramError:
        pass
