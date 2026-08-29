import logging
from telegram import Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import render_channels_list
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# Kanal qo'shish holati
ADD_CHANNEL = 301

async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchining ulangan kanallari ro'yxati."""
    user_id = update.effective_user.id
    channels = db.get_user_channels(user_id)
    
    if not channels:
        await update.message.reply_text(
            "📢 <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Kanal ulash uchun botni kanalingizga administrator qiling va <b>➕ Kanal/Guruh qo'shish</b> tugmasini bosing.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"📢 <b>Sizning ulangan kanallaringiz ({len(channels)} ta):</b>\n\n"
        "Kanalni o'chirish uchun '❌ O'chirish' tugmasini bosing 👇",
        reply_markup=render_channels_list(channels),
        parse_mode="HTML"
    )
    return ConversationHandler.END

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi kanal qo'shish bo'yicha ko'rsatma."""
    bot_obj = await context.bot.get_me()
    await update.message.reply_text(
        f"➕ <b>Yangi kanal yoki guruh ulash:</b>\n\n"
        f"1. Botni (<code>@{bot_obj.username}</code>) kanalingizga yoki guruhingizga <b>Administrator</b> qilib qo'shing (xabar yuborish ruxsati bilan).\n"
        f"2. So'ngra o'sha kanaldan istalgan bir xabarni menga <b>Forward (Uzatish)</b> qiling yoki kanal ID raqamini (masalan: <code>-1001234567890</code>) yozib yuboring:\n\n"
        f"<i>Bekor qilish uchun '🔙 Asosiy menyu' tugmasini bosing.</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return ADD_CHANNEL

async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal ma'lumotlarini qabul qilib saqlash."""
    msg = update.message
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    
    channel_id = None
    channel_title = None

    if msg.forward_from_chat:
        channel_id = str(msg.forward_from_chat.id)
        channel_title = msg.forward_from_chat.title or "Telegram Kanal"
    elif msg.text:
        text = msg.text.strip()
        channel_id = text
        try:
            target_chat = int(text) if text.lstrip('-').isdigit() else text
            chat_obj = await context.bot.get_chat(target_chat)
            channel_id = str(chat_obj.id)
            channel_title = chat_obj.title or "Telegram Kanal"
        except TelegramError:
            channel_title = "Telegram Kanal"

    if not channel_id:
        await update.message.reply_text("❌ Kanal ma'lumotlari aniqlanmadi. Iltimos, kanaldan xabarni forward qiling:")
        return ADD_CHANNEL

    try:
        target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id
        member = await context.bot.get_chat_member(chat_id=target_chat, user_id=context.bot.id)
        if member.status not in ("administrator", "creator"):
            await update.message.reply_text(
                "⚠️ <b>Bot ushbu kanalda administrator emas!</b>\n\nIltimos, avval botga kanalda xabar yuborish ruxsatini bering.",
                parse_mode="HTML"
            )
            return ADD_CHANNEL
    except TelegramError as e:
        logger.warning(f"Kanal tekshirishda xato: {e}")

    success = db.save_channel(user_id, channel_id, channel_title)
    if success:
        await update.message.reply_text(
            f"✅ <b>Kanal muvaffaqiyatli ulandi!</b>\n\n📢 Nomi: <b>{html_escape(channel_title)}</b>\n🆔 ID: <code>{channel_id}</code>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("❌ Kanalni saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
        
    return ConversationHandler.END

async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanalni o'chirish."""
    query = update.callback_query
    await query.answer()
    channel_id = query.data.split(":")[1]
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)
    
    db.remove_channel(user_id, channel_id, is_admin=is_admin)
    await query.edit_message_text("✅ Kanal muvaffaqiyatli o'chirildi.")

async def on_bot_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot kanalga admin qilib qo'shilganda avtomatik saqlash."""
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    new_status = result.new_chat_member.status
    user_id = result.from_user.id
    
    if new_status in ("administrator", "creator") and chat.type in ("channel", "supergroup", "group"):
        db.save_channel(user_id, str(chat.id), chat.title or "Telegram Kanal")
