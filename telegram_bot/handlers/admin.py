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
    await update.message.reply_text("⚙️ Admin boshqaruv paneli", reply_markup=get_admin_panel_keyboard())

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = db.get_system_stats()
    text = (
        f"📊 Bot statistikasi:\n\n"
        f"👥 Foydalanuvchilar: {stats['users']} ta\n"
        f"📢 Ulangan kanallar: {stats['channels']} ta\n"
        f"🔗 Homiy kanallar: {stats['sponsors']} ta\n"
        f"⏳ Kutilayotgan postlar: {stats['pending']} ta\n"
        f"✅ Yuborilgan: {stats['sent']} ta\n"
        f"🚫 Bekor qilingan: {stats['cancelled']} ta\n"
        f"❌ Xatolik bo'lgan: {stats['failed']} ta"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard())

async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    stats = db.get_system_stats()
    text = (
        f"🗂 Botdagi barcha postlar holati:\n\n"
        f"⏳ Navbatda kutayotganlar: {stats['pending']} ta\n"
        f"✅ Muvaffaqiyatli chiqqanlar: {stats['sent']} ta\n"
        f"🚫 Bekor qilinganlar: {stats['cancelled']} ta\n\n"
        f"ℹ️ Foydalanuvchilar o'zlarining postlarini '📋 Kutilayotgan postlar' bo'limidan mustaqil boshqaradilar."
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard())

async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    channels = db.get_all_channels()
    text, inline_markup = render_channels_list(channels, show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard())
    if inline_markup:
        await update.message.reply_text("O'chirish 👇", reply_markup=inline_markup)

# --- REKLAMA HAVOLASI ---
async def start_set_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    cur_title = db.get_setting("ad_title", "PostAssistrobot")
    cur_link = db.get_setting("ad_link", "")
    await update.message.reply_text(
        f"📝 Global reklama havolasi sozlamasi:\n\n"
        f"📌 Joriy matn: {cur_title}\n"
        f"🔗 Joriy havola: {cur_link or 'Mavjud emas'}\n\n"
        f"Kanal nomini yoki havolasini yuboring:\n"
        f"• Shunchaki: @kanalim yoki https://t.me/kanalim\n"
        f"• Yoki ixtiyoriy matn bilan: Kanalimiz - https://t.me/kanalim\n\n"
        f"O'chirish uchun 0 yuboring.",
        reply_markup=get_cancel_keyboard()
    )
    return SET_AD_TEXT

async def ad_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "0":
        db.set_setting("ad_title", "")
        db.set_setting("ad_link", "")
        await update.message.reply_text("✅ Reklama o'chirildi.", reply_markup=get_admin_panel_keyboard())
        return ConversationHandler.END
    
    ad_title = "Kanalimiz"
    ad_link = text

    if " - " in text:
        parts = text.split(" - ", 1)
        ad_title = parts[0].strip()
        ad_link = parts[1].strip()
    else:
        # Agar shunchaki havola yoki @username kiritilgan bo'lsa
        clean_user = text.replace("https://t.me/", "").replace("http://t.me/", "").replace("@", "").strip()
        try:
            chat = await context.bot.get_chat(f"@{clean_user}")
            ad_title = chat.title or clean_user
            ad_link = f"https://t.me/{clean_user}"
        except Exception:
            ad_title = "Kanalga o'tish"
            ad_link = text if text.startswith("http") else f"https://t.me/{clean_user}"

    db.set_setting("ad_title", ad_title)
    db.set_setting("ad_link", ad_link)
    await update.message.reply_text(
        f"✅ Yangi reklama saqlandi!\n\n📌 Matn: {ad_title}\n🔗 Havola: {ad_link}",
        reply_markup=get_admin_panel_keyboard()
    )
    return ConversationHandler.END

# --- HOMIY KANALLAR ---
async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    sponsors = db.get_active_sponsors()
    text, markup = render_sponsors_list(sponsors)
    await update.message.reply_text(text, reply_markup=get_sponsors_keyboard())
    if markup:
        await update.message.reply_text("O'chirish uchun tanlang 👇", reply_markup=markup)

async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text(
        "📢 Homiy kanal qo'shish:\n\n"
        "1. Botni homiy kanalga admin qiling.\n"
        "2. Kanal manzilini yuboring:\n"
        "• Masalan: @kgz_z yoki https://t.me/kgz_z",
        reply_markup=get_cancel_keyboard()
    )
    return ADD_SPONSOR_CHANNEL

async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    
    ch_ident = text
    ch_url = ""

    if " - " in text:
        parts = text.split(" - ", 1)
        ch_ident = parts[0].strip()
        ch_url = parts[1].strip()
    else:
        clean = text.replace("https://t.me/", "").replace("http://t.me/", "").replace("@", "").strip()
        ch_ident = f"@{clean}"
        ch_url = f"https://t.me/{clean}"

    try:
        chat = await context.bot.get_chat(ch_ident)
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text("⚠️ Bot bu kanalda admin emas! Botni kanalda admin qiling va qaytadan yuboring:")
            return ADD_SPONSOR_CHANNEL
        
        ch_title = chat.title or ch_ident
        if not ch_url:
            ch_url = f"https://t.me/{chat.username}" if chat.username else f"https://t.me/{clean}"

        db.add_sponsor_channel(str(chat.id), ch_title, ch_url)
        await update.message.reply_text(
            f"✅ '{ch_title}' majburiy obuna ro'yxatiga muvaffaqiyatli qo'shildi!",
            reply_markup=get_admin_panel_keyboard()
        )
        return ConversationHandler.END
    except Exception as e:
        await update.message.reply_text(
            f"❌ Kanalni topib bo'lmadi: {e}\n"
            f"Iltimos, bot kanalda admin ekanligini va @username to'g'riligini tekshiring."
        )
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
    await query.edit_message_text(text, reply_markup=markup)

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    await update.message.reply_text("📝 Barcha foydalanuvchilarga yuboriladigan xabarni yozing:", reply_markup=get_cancel_keyboard())
    return BROADCAST_MESSAGE

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END
    text = update.message.text
    user_ids = db.get_all_user_ids()
    sent = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 Xabar:\n\n{text}")
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Xabar {sent} ta foydalanuvchiga yuborildi.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END
