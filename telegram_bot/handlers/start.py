from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

# Asosiy menyu klaviaturasi
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("➕ Yangi post rejalashtirish")],
        [KeyboardButton("📋 Rejalashtirilgan postlar"), KeyboardButton("🗑 Postni o'chirish")],
        [KeyboardButton("⚙️ Admin panel"), KeyboardButton("ℹ️ Bot haqida")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (
        f"Assalomu alaykum, {user.first_name}!\n\n"
        "🤖 **Telegram Avtoposting Botiga xush kelibsiz!**\n\n"
        "Ushbu bot orqali kanallaringizga postlarni belgilangan vaqtda "
        "avtomatik tarzda chiqarishingiz mumkin.\n\n"
        "Kerakli bo'limni tanlang 👇"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")

async def about_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📌 **Bot haqida ma'lumot:**\n\n"
        "• Kanallarga matn, rasm, video va tugmali postlarni rejalashtirish\n"
        "• Postlarni belgilangan vaqtda avtomatik ulashish\n"
        "• 24/7 uzluksiz server faoliyati"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

def register_handlers(application):
    application.add_handler(CommandHandler("start", start_command))
