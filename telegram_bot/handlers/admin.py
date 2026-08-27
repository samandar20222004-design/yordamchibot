import logging
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_admin_panel_keyboard, get_cancel_keyboard, get_sponsors_keyboard
from keyboards.inline import render_pending_list, render_channels_list, render_sponsors_list
from utils.helpers import md_escape

logger = logging.getLogger(__name__)

BROADCAST_MESSAGE = 20
ADD_SPONSOR_CHANNEL = 30
SET_AD_TEXT = 40

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
        f"📢 Ulangan kanallar: *{stats['channels']} ta*\n"
        f"🔗 Homiy kanallar: *{stats['sponsors']} ta*\n"
        f"⏳ Kutilayotgan postlar: *{stats['pending']} ta*\n"
        f"✅ Yuborilgan: *{stats['sent']} ta*\n"
        f"🚫 Bekor qilingan: *{stats['cancelled']} ta*\n"
        f"❌ Xatolik bo'lgan: *{stats['failed']} ta*"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

# --- SPONSOR CHANNELS (MAJBURIIY OBUNA) ---
async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user.id != ADMIN_ID:
        return
    sponsors = db.get_active_sponsors()
    text, markup = render_sponsors_list(sponsors)
    await update.message.reply_text(text, reply_markup=get_sponsors_keyboard(), parse_mode="Markdown")
    if markup:
        await update.message.reply_text("O'chirmoqchi bo'lgan homiy kanalni tanlang 👇", reply_markup=markup)

async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 *Homiy kanal qo'shish:*\n\n"
        "1. Botni homiy kanalga admin qilib qo'shing.\n"
        "2. Kanal ssilkasi va username/ID sini yuboring:\n"
        "Format: `@kanal_username - https://t.me/kanal_link`",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return ADD_SPONSOR_CHANNEL

async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if " - " not in text:
        await update.message.reply_text("⚠️ Noto'g'ri format!\nMasalan: `@kanal_nomi - https://t.me/kanal_nomi`")
        return ADD_SPONSOR_CHANNEL
    
    ch_ident, ch_url = text.split(" - ", 1)
    ch_ident = ch_ident.strip()
    ch_url = ch_url.strip()

    try:
        chat = await context.bot.get_chat(ch_ident)
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("⚠️ Bot bu kanalda admin emas! Botni admin qilib qayta urinib ko'ring.")
            return ADD_SPONSOR_CHANNEL
        
        db.add_sponsor_channel(str(chat.id), chat.title or "Homiy Kanal", ch_url)
        await update.message.reply_text(f"✅ *{md_escape(chat.title)}* majburiy obuna ro'yxatiga qo'shildi!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    except TelegramError as e:
        await update.message.reply_text(f"❌ Kanalni aniqlab bo'lmadi: {e}")
        return ADD_SPONSOR_CHANNEL

async def del_sponsor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return
    try:
        _, s_id = query.data.split(":")
        db.remove_sponsor_channel(int(s_id))
        await query.answer("Homiy kanal o'chirildi.")
        sponsors = db.get_active_sponsors()
        text, markup = render_sponsors_list(sponsors)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except Exception as e:
        await query.answer(f"Xatolik: {e}", show_alert=True)

# --- GLOBAL AD TEXT / LINK ---
async def start_set_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    cur_title = db.get_setting("ad_title", "🤖 Avto Post Assist Bot")
    cur_link = db.get_setting("ad_link", "")
    await update.message.reply_text(
        f"📝 *Postlar tagiga chiqadigan doimiy reklama imzosi:*\n\n"
        f"📌 Joriy matn: *{cur_title}*\n"
        f"🔗 Joriy havola: `{cur_link or 'Mavjud emas (Botning o`zi)'}`\n\n"
        f"Yangi reklama o'rnatish uchun quyidagicha yuboring:\n"
        f"`Tugma matni - https://t.me/kanalim`\n\n"
        f"O'chirish (standart holatga qaytarish) uchun `0` yuboring.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return SET_AD_TEXT

async def ad_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "0":
        db.set_setting("ad_title", "")
        db.set_setting("ad_link", "")
        await update.message.reply_text("✅ Reklama o'chirildi va standart bot ssilkasi tiklandi.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    
    if " - " in text:
        parts = text.split(" - ", 1)
        db.set_setting("ad_title", parts[0].strip())
        db.set_setting("ad_link", parts[1].strip())
        await update.message.reply_text(f"✅ Yangi reklama muvaffaqiyatli saqlandi!\n\nMatn: *{parts[0]}*\nHavola: {parts[1]}", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    else:
        await update.message.reply_text("⚠️ Format noto'g'ri. Namuna: `Bizning kanal - https://t.me/kanal`")
        return SET_AD_TEXT

# --- POSTS & CHANNELS ---
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
