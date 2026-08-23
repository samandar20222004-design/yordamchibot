from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from config import SUPER_ADMIN
from database import get_system_stats, get_all_user_ids

ADMIN_BROADCAST_STATE = 200

async def admin_panel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != SUPER_ADMIN:
        return
        
    stats = get_system_stats()
    text = (
        "👑 **Bosh Admin Paneli**\n\n"
        f"👥 Foydalanuvchilar: **{stats['users']}** ta\n"
        f"📢 Ulangan kanallar: **{stats['channels']}** ta\n"
        f"⏳ Kutilayotgan postlar: **{stats['pending']}** ta\n"
        f"✅ Yuborilgan postlar: **{stats['sent']}** ta\n"
    )
    keyboard = [
        ["📢 Barchaga xabar yuborish"],
        ["🔙 Asosiy menyu"]
    ]
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != SUPER_ADMIN:
        return ConversationHandler.END
        
    await update.message.reply_text(
        "Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing:\nBekor qilish uchun `/cancel` yozing.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ADMIN_BROADCAST_STATE

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != SUPER_ADMIN:
        return ConversationHandler.END
        
    text = update.message.text
    user_ids = get_all_user_ids()
    sent = 0
    
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"🔔 **Tizim xabari:**\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
            
    await update.message.reply_text(f"✅ Xabar **{sent}** ta foydalanuvchiga yuborildi.")
    return ConversationHandler.END
