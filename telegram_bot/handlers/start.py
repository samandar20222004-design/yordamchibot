from telegram import Update
from telegram.ext import ContextTypes

from config import ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Kechirasiz, bu bot faqat egasi uchun.")
        return
    await update.message.reply_text(
        "Salom! Men sizning kanalingizga rejalashtirilgan xabarlarni o'zim jo'natib turaman.\n\n"
        "Buyruqlar:\n"
        "/yangi — yangi rejalashtirilgan xabar qo'shish\n"
        "/royxat — barcha rejalashtirilgan xabarlar ro'yxati\n"
        "/ochir <ID> — xabarni o'chirish\n"
        "/bekor — joriy amalni bekor qilish\n"
        "/yordam — yordam"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)
