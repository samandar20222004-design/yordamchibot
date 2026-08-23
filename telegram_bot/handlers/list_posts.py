from telegram import Update
from telegram.ext import ContextTypes, CommandHandler, MessageHandler, filters
from database import get_posts_by_user

async def list_posts_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    posts = get_posts_by_user(user_id)

    if not posts:
        await update.message.reply_text("📭 Hozircha rejalashtirilgan postlar yo'q.")
        return

    text = "📋 **Rejalashtirilgan postlaringiz:**\n\n"
    for post in posts:
        # post: (id, user_id, channel_id, text, photo_id, scheduled_time, is_sent)
        p_id = post[0]
        channel = post[2]
        time = post[5]
        status = "Yuborilgan" if post[6] else "Kutilmoqda"
        text += f"🆔 Post ID: `{p_id}`\n📢 Kanal: `{channel}`\n⏰ Vaqt: `{time}`\nHolati: {status}\n───────────────\n"

    await update.message.reply_text(text, parse_mode="Markdown")

def register_handlers(application):
    application.add_handler(CommandHandler("posts", list_posts_handler))
    application.add_handler(MessageHandler(filters.Regex("^📋 Rejalashtirilgan postlar$"), list_posts_handler))
