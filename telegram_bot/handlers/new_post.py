from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters
)
from database import add_post

CHOOSING_TYPE, GET_CONTENT, GET_CHANNEL, GET_TIME = range(4)

async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    types_keyboard = [["Matnli post", "Rasmli post"], ["Bekor qilish"]]
    await update.message.reply_text(
        "Qanday turdagi post joylamoqchisiz?",
        reply_markup=ReplyKeyboardMarkup(types_keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return CHOOSING_TYPE

async def post_type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post_type = update.message.text
    if post_type == "Bekor qilish":
        await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    context.user_data["post_type"] = post_type
    await update.message.reply_text("Post matnini (yoki rasmini) yuboring:")
    return GET_CONTENT

async def get_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["photo_id"] = update.message.photo[-1].file_id
        context.user_data["text"] = update.message.caption or ""
    else:
        context.user_data["photo_id"] = None
        context.user_data["text"] = update.message.text

    await update.message.reply_text(
        "Kanal ID yoki @username'ni kiriting (masalan: `@kanal_nomi` yoki `-10012345678`):"
    )
    return GET_CHANNEL

async def get_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["channel_id"] = update.message.text.strip()
    await update.message.reply_text(
        "Post chiqish vaqtini quyidagi formatda kiriting:\n"
        "`YYYY-MM-DD HH:MM`\n\n"
        "Masalan: `2026-08-25 18:30`",
        parse_mode="Markdown"
    )
    return GET_TIME

async def get_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_str = update.message.text.strip()
    try:
        post_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        channel_id = context.user_data["channel_id"]
        text = context.user_data["text"]
        photo_id = context.user_data.get("photo_id")

        add_post(
            user_id=update.effective_user.id,
            channel_id=channel_id,
            text=text,
            photo_id=photo_id,
            scheduled_time=time_str
        )

        await update.message.reply_text(
            f"✅ Post muvaffaqiyatli saqlandi!\n\n"
            f"📅 Belgilangan vaqt: {time_str}\n"
            f"📢 Kanal: {channel_id}",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ Vaqt formati noto'g'ri. Qaytadan kiriting (`YYYY-MM-DD HH:MM`):")
        return GET_TIME

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Amal bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

new_post_conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^➕ Yangi post rejalashtirish$"), start_new_post),
        CommandHandler("newpost", start_new_post)
    ],
    states={
        CHOOSING_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_type_chosen)],
        GET_CONTENT: [MessageHandler(filters.ALL & ~filters.COMMAND, get_content)],
        GET_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_channel)],
        GET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_time)],
    },
    fallbacks=[CommandHandler("cancel", cancel), MessageHandler(filters.Regex("^Bekor qilish$"), cancel)]
)

def register_handlers(application):
    application.add_handler(new_post_conv_handler)
