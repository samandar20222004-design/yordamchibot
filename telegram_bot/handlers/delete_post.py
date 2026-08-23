from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters
)
from database import delete_post_by_id

CONFIRM_DELETE = 1

async def start_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "O'chirmoqchi bo'lgan postingizning **ID raqamini** yozing:\n"
        "(ID raqamini '📋 Rejalashtirilgan postlar' bo'limidan olishingiz mumkin)",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["Bekor qilish"]], resize_keyboard=True)
    )
    return CONFIRM_DELETE

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message.text.strip()
    if msg == "Bekor qilish":
        await update.message.reply_text("O'chirish bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    try:
        post_id = int(msg)
        delete_post_by_id(post_id)
        await update.message.reply_text(f"✅ ID `{post_id}` bo'lgan post muvaffaqiyatli o'chirildi.", parse_mode="Markdown")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("⚠️ Iltimos, faqat raqam (ID) kiriting:")
        return CONFIRM_DELETE

delete_post_conv_handler = ConversationHandler(
    entry_points=[
        MessageHandler(filters.Regex("^🗑 Postni o'chirish$"), start_delete),
        CommandHandler("deletepost", start_delete)
    ],
    states={
        CONFIRM_DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)]
    },
    fallbacks=[MessageHandler(filters.Regex("^Bekor qilish$"), start_delete)]
)

def register_handlers(application):
    application.add_handler(delete_post_conv_handler)
