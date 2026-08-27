from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_admin_panel_keyboard, get_cancel_keyboard
from keyboards.inline import render_pending_list, render_channels_list

BROADCAST_MESSAGE = 20

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user.id != ADMIN_ID:
        return
    await update.message.reply_text("⚙️ *Admin boshqaruv paneli*", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = db.get_system_stats()
    text = (
        f"📊 *Bot statistikasi:*\n\n"
        f"👥 Foydalanuvchilar: *{stats['users']} ta*\n"
        f"📢 Kanallar: *{stats['channels']} ta*\n"
        f"⏳ Kutilayotgan: *{stats['pending']} ta*\n"
        f"✅ Yuborilgan: *{stats['sent']} ta*\n"
        f"🚫 Bekor qilingan: *{stats['cancelled']} ta*\n"
        f"❌ Xatolik bo'lgan: *{stats['failed']} ta*"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    posts = db.get_all_pending_posts()
    text, inline_markup = render_pending_list(posts, "🗂 *Barcha kutilayotgan postlar:*", show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("Bekor qilish 👇", reply_markup=inline_markup)

async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    channels = db.get_all_channels()
    text, inline_markup = render_channels_list(channels, show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("O'chirish 👇", reply_markup=inline_markup)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📝 *Barcha foydalanuvchilarga yuboriladigan xabarni yozing:*", reply_markup=get_cancel_keyboard(), parse_mode="Markdown")
    return BROADCAST_MESSAGE

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    user_ids = db.get_all_user_ids()
    sent, failed = 0, 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 *Tizim xabari:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(
        f"✅ Xabar *{sent}* ta foydalanuvchiga yetkazildi. ({failed} ta xatolik)",
        reply_markup=get_admin_panel_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END
