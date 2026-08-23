from telegram import Update, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from database import delete_user_post

WAIT_DELETE_ID = 1

async def delete_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "O'chirmoqchi bo'lgan postingizning **ID raqamini** yuboring:\n*(ID ni '📋 Rejalashtirilgan postlar' bo'limidan ko'rishingiz mumkin)*\n\nBekor qilish uchun `/cancel` deb yozing.",
        parse_mode="Markdown"
    )
    return WAIT_DELETE_ID

async def delete_post_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not text.isdigit():
        await update.message.reply_text("Iltimos, faqat raqamli ID kiriting:")
        return WAIT_DELETE_ID
        
    post_id = int(text)
    success = delete_user_post(user_id, post_id)
    
    if success:
        await update.message.reply_text(f"✅ #{post_id} raqamli post bekor qilindi va o'chirildi.")
    else:
        await update.message.reply_text(f"❌ #{post_id} raqamli post topilmadi yoki u sizga tegishli emas.")
        
    return ConversationHandler.END
