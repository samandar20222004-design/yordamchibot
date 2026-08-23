from telegram import Update
from telegram.ext import ContextTypes
from database import get_user_posts

async def list_posts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    posts = get_user_posts(user_id)
    
    if not posts:
        await update.message.reply_text("Sizda rejalashtirilgan faol postlar mavjud emas.")
        return
        
    text = "📋 **Sizning rejalashtirilgan postlaringiz:**\n\n"
    for post in posts:
        post_id, channel_title, post_text, sched_time = post
        ch_name = channel_title or "Kanal"
        snippet = (post_text[:40] + "...") if post_text and len(post_text) > 40 else (post_text or "[Rasm]")
        text += f"🆔 **ID:** `{post_id}` | 📢 **{ch_name}**\n⏰ {sched_time}\n📝 {snippet}\n\n"
        
    await update.message.reply_text(text, parse_mode="Markdown")
