from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID
from database import get_active_posts


async def list_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    posts = get_active_posts()
    if not posts:
        await update.message.reply_text("Hozircha rejalashtirilgan xabarlar yo'q.")
        return

    media_icons = {"photo": "🖼", "video": "🎬", "document": "📎"}

    lines = []
    for p in posts:
        text = p["text"] or ""
        preview = text[:40] + ("..." if len(text) > 40 else "")
        icon = media_icons.get(p.get("media_type"), "")
        if icon:
            preview = f"{icon} {preview}" if preview else f"{icon} (izohsiz)"
        if p["post_type"] == "once":
            info = f"bir marta, {p['send_date']} {p['send_time']}"
        else:
            end = f"{p['end_date']} gacha" if p["end_date"] else "cheksiz"
            info = f"har kuni {p['send_time']}, {end}"
        lines.append(f"🆔 {p['id']} — {info}\n   \"{preview}\"")

    await update.message.reply_text(
        "📋 Rejalashtirilgan xabarlar:\n\n" + "\n\n".join(lines)
        + "\n\nO'chirish uchun: /ochir <ID>"
    )
