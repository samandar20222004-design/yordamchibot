import logging
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_admin_panel_keyboard, get_cancel_keyboard, get_sponsors_keyboard
from keyboards.inline import render_channels_list, render_sponsors_list
from utils.helpers import md_escape

logger = logging.getLogger(__name__)
BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_AD_TEXT = 20, 30, 40

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

async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = db.get_system_stats()
    text = (
        f"🗂 *Botdagi barcha postlar holati:*\n\n"
        f"⏳ Navbatda kutayotganlar: *{stats['pending']} ta*\n"
        f"✅ Muvaffaqiyatli chiqqanlar: *{stats['sent']} ta*\n"
        f"🚫 Bekor qilinganlar: *{stats['cancelled']} ta*\n\n"
        f"ℹ️ _Foydalanuvchilar o'zlarining postlarini '📋 Kutilayotgan postlar' bo'limidan mustaqil boshqaradilar._"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")

async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    channels = db.get_all_channels()
    text, inline_markup = render_channels_list(channels, show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("O'chirish 👇", reply_markup=inline_markup)

# --- REKLAMA HAVOLASI ---
async def start_set_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    cur_title = db.get_setting("ad_title", "PostAssistrobot")
    cur_link = db.get_setting("ad_link", "")
    await update.message.reply_text(
        f"📝 *Global reklama havolasi sozlamasi:*\n\n"
        f"📌 Joriy matn: *{cur_title}*\n"
        f"🔗 Joriy havola: `{cur_link or 'Mavjud emas'}`\n\n"
        f"O'zgartirish uchun yozing: `Kanal nomi - https://t.me/kanal`\n"
        f"O'chirish uchun `0` yuboring.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return SET_AD_TEXT

async def ad_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "0":
        db.set_setting("ad_title", "")
        db.set_setting("ad_link", "")
        await update.message.reply_text("✅ Reklama o'chirildi.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    
    if " - " in text:
        parts = text.split(" - ", 1)
        db.set_setting("ad_title", parts[0].strip())
        db.set_setting("ad_link", parts[1].strip())
        await update.message.reply_text(f"✅ Reklama saqlandi:\n*{parts[0]}* -> {parts[1]}", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    else:
        await update.message.reply_text("⚠️ Format xato. Masalan: `Kanalimiz - https://t.me/kanal`")
        return SET_AD_TEXT

# --- HOMIY KANALLAR ---
async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    sponsors = db.get_active_sponsors()
    text, markup = render_sponsors_list(sponsors)
    await update.message.reply_text(text, reply_markup=get_sponsors_keyboard(), parse_mode="Markdown")
    if markup:
        await update.message.reply_text("O'chirish uchun tanlang 👇", reply_markup=markup)

async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 *Homiy kanal qo'shish:*\n"
        "Format: `@kanal_username - https://t.me/kanal_link`",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return ADD_SPONSOR_CHANNEL

async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if " - " not in text:
        await update.message.reply_text("⚠️ Masalan: `@kanal_nomi - https://t.me/kanal_nomi`")
        return ADD_SPONSOR_CHANNEL
    
    ch_ident, ch_url = text.split(" - ", 1)
    try:
        chat = await context.bot.get_chat(ch_ident.strip())
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("⚠️ Bot bu kanalda admin emas!")
            return ADD_SPONSOR_CHANNEL
        db.add_sponsor_channel(str(chat.id), chat.title or "Homiy Kanal", ch_url.strip())
        await update.message.reply_text(f"✅ *{md_escape(chat.title)}* homiy kanal sifatida ulandi!", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(f"❌ Xatolik: {e}")
        return ADD_SPONSOR_CHANNEL

async def del_sponsor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID:
        return
    _, s_id = query.data.split(":")
    db.remove_sponsor_channel(int(s_id))
    await query.answer("Homiy kanal o'chirildi.")
    sponsors = db.get_active_sponsors()
    text, markup = render_sponsors_list(sponsors)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)

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
    sent = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 *Xabar:*\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Xabar *{sent}* ta foydalanuvchiga yuborildi.", reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    return ConversationHandler.END
