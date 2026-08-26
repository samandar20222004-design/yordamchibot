from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from database import add_user

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.full_name)
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [KeyboardButton("➕ Yangi post rejalashtirish")],
        [KeyboardButton("📋 Kutilayotgan postlar"), KeyboardButton("📢 Kanallar")],
        [KeyboardButton("➕ Kanal qo'shish")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    text = (
        f"Salom, {update.effective_user.first_name}! 👋\n\n"
        "🤖 <b>PostAssist robot</b> — Telegram kanallaringiz uchun aqlli avtoposting yordamchingiz.\n\n"
        "Quyidagi menyudan kerakli bo'limni tanlang 👇"
    )
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    elif update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
