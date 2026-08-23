from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import get_post, delete_post as db_delete_post
from scheduler import remove_job


async def delete_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if not context.args:
        await update.message.reply_text("Foydalanish: /ochir <ID>\nMasalan: /ochir 3")
        return

    try:
        post_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID raqam bo'lishi kerak. Masalan: /ochir 3")
        return

    post = get_post(post_id)
    if not post:
        await update.message.reply_text("Bunday ID topilmadi.")
        return

    remove_job(post_id)
    db_delete_post(post_id)
    await update.message.reply_text(f"🗑 {post_id}-ID li xabar o'chirildi.")
