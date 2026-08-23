from datetime import datetime, timedelta, date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    MessageHandler, CallbackQueryHandler, filters
)

from config import ADMIN_ID, CHANNEL_ID
from database import add_post
from scheduler import schedule_post

TEXT, TYPE, ONCE_DATETIME, DAILY_TIME, DAILY_DURATION = range(5)

DURATION_OPTIONS = {
    "dur_week": ("1 hafta", 7),
    "dur_month": ("1 oy", 30),
    "dur_3month": ("3 oy", 90),
    "dur_6month": ("6 oy", 182),
    "dur_year": ("1 yil", 365),
    "dur_forever": ("Doimiy (cheksiz)", None),
}


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


async def new_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update):
        await update.message.reply_text("Bu buyruq faqat bot egasi uchun.")
        return ConversationHandler.END
    await update.message.reply_text(
        "Yangi xabarni yuboring:\n"
        "— oddiy matn, YOKI\n"
        "— rasm / video / fayl (xohlasangiz izoh — caption — bilan birga)\n\n"
        "(Bekor qilish uchun /bekor)"
    )
    return TEXT


async def receive_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    if message.photo:
        context.user_data["media_type"] = "photo"
        context.user_data["media_file_id"] = message.photo[-1].file_id  # eng yuqori sifat
        context.user_data["new_post_text"] = message.caption or ""
    elif message.video:
        context.user_data["media_type"] = "video"
        context.user_data["media_file_id"] = message.video.file_id
        context.user_data["new_post_text"] = message.caption or ""
    elif message.document:
        context.user_data["media_type"] = "document"
        context.user_data["media_file_id"] = message.document.file_id
        context.user_data["new_post_text"] = message.caption or ""
    else:
        context.user_data["media_type"] = None
        context.user_data["media_file_id"] = None
        context.user_data["new_post_text"] = message.text or ""

    keyboard = [
        [InlineKeyboardButton("Bir marta", callback_data="type_once")],
        [InlineKeyboardButton("Har kuni (takrorlanuvchi)", callback_data="type_daily")],
    ]
    await message.reply_text(
        "Bu xabar qanday yuborilsin?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TYPE


async def receive_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["post_type"] = "once" if query.data == "type_once" else "daily"

    if context.user_data["post_type"] == "once":
        await query.edit_message_text(
            "Xabar qachon yuborilsin? Quyidagi formatda yozing:\n"
            "kun.oy.yil soat:daqiqa\n\n"
            "Masalan: 25.08.2026 14:30\n"
            "Bugun uchun ham xuddi shu formatda bugungi sanani yozing."
        )
        return ONCE_DATETIME
    else:
        await query.edit_message_text(
            "Xabar har kuni soat nechada yuborilsin?\n"
            "Formatda yozing: soat:daqiqa\n\nMasalan: 09:00"
        )
        return DAILY_TIME


async def receive_once_datetime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        dt = datetime.strptime(raw, "%d.%m.%Y %H:%M")
    except ValueError:
        await update.message.reply_text(
            "Format noto'g'ri. Iltimos qayta yuboring: kun.oy.yil soat:daqiqa\n"
            "Masalan: 25.08.2026 14:30"
        )
        return ONCE_DATETIME

    if dt < datetime.now():
        await update.message.reply_text(
            "Bu sana o'tib ketgan. Iltimos, kelajakdagi sana kiriting."
        )
        return ONCE_DATETIME

    text = context.user_data["new_post_text"]
    media_type = context.user_data.get("media_type")
    media_file_id = context.user_data.get("media_file_id")

    post_id = add_post(
        text=text,
        post_type="once",
        send_time=dt.strftime("%H:%M"),
        send_date=dt.strftime("%Y-%m-%d"),
        media_type=media_type,
        media_file_id=media_file_id,
    )
    post = {
        "id": post_id, "text": text, "post_type": "once",
        "send_time": dt.strftime("%H:%M"), "send_date": dt.strftime("%Y-%m-%d"),
        "end_date": None, "media_type": media_type, "media_file_id": media_file_id,
    }
    schedule_post(context.bot, CHANNEL_ID, post)

    await update.message.reply_text(
        f"✅ Xabar rejalashtirildi!\nID: {post_id}\nSana: {dt.strftime('%d.%m.%Y %H:%M')}"
    )
    context.user_data.clear()
    return ConversationHandler.END


async def receive_daily_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw = update.message.text.strip()
    try:
        t = datetime.strptime(raw, "%H:%M")
    except ValueError:
        await update.message.reply_text(
            "Format noto'g'ri. Iltimos: soat:daqiqa\nMasalan: 09:00"
        )
        return DAILY_TIME

    context.user_data["daily_time"] = t.strftime("%H:%M")

    keyboard = [[InlineKeyboardButton(label, callback_data=key)]
                for key, (label, _) in DURATION_OPTIONS.items()]
    await update.message.reply_text(
        "Xabar qancha muddat davomida takrorlansin?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DAILY_DURATION


async def receive_daily_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    label, days = DURATION_OPTIONS[query.data]

    end_date = None
    if days is not None:
        end_date = (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")

    text = context.user_data["new_post_text"]
    send_time = context.user_data["daily_time"]
    media_type = context.user_data.get("media_type")
    media_file_id = context.user_data.get("media_file_id")

    post_id = add_post(
        text=text, post_type="daily", send_time=send_time, end_date=end_date,
        media_type=media_type, media_file_id=media_file_id,
    )
    post = {
        "id": post_id, "text": text, "post_type": "daily",
        "send_time": send_time, "send_date": None, "end_date": end_date,
        "media_type": media_type, "media_file_id": media_file_id,
    }
    schedule_post(context.bot, CHANNEL_ID, post)

    end_text = f"gacha ({end_date})" if end_date else "cheksiz muddatda"
    await query.edit_message_text(
        f"✅ Xabar rejalashtirildi!\nID: {post_id}\n"
        f"Har kuni soat {send_time} da, {end_text} yuboriladi."
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


new_post_conversation = ConversationHandler(
    entry_points=[CommandHandler("yangi", new_post_start)],
    states={
        TEXT: [MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL) & ~filters.COMMAND,
            receive_text
        )],
        TYPE: [CallbackQueryHandler(receive_type, pattern="^type_")],
        ONCE_DATETIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_once_datetime)],
        DAILY_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_daily_time)],
        DAILY_DURATION: [CallbackQueryHandler(receive_daily_duration, pattern="^dur_")],
    },
    fallbacks=[CommandHandler("bekor", cancel)],
)
