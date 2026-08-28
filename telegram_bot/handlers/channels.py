import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
import database as db
from keyboards.default import BTN_ADD_CHANNEL, BTN_MAIN_MENU, get_main_keyboard, get_cancel_keyboard
from keyboards.inline import render_channels_list
from utils.helpers import html_escape

logger = logging.getLogger(__name__)
ADD_CHANNEL = 200

async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    channels = db.get_user_channels(user_id)
    text, inline_markup = render_channels_list(channels, show_owner=False)
    keyboard = [[BTN_ADD_CHANNEL], [BTN_MAIN_MENU]]
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="HTML")
    if inline_markup:
        await update.message.reply_text("O'chirmoqchi bo'lgan kanal/guruhni tanlang 👇", reply_markup=inline_markup)
    return ConversationHandler.END

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "📢 <b>Kanal yoki guruh ulash:</b>\n\n"
        "1. Botni kanalingizga admin (yoki guruhga a'zo) qilib qo'shing.\n"
        "2. Kanal/guruhdan biror xabarni bu yerga <b>Forward</b> qiling yoki <code>@username</code>ini yozing.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return ADD_CHANNEL

async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    msg = update.message
    identifier = None
    
    origin = getattr(msg, 'forward_origin', None)
    if origin:
        chat = getattr(origin, 'chat', None)
        if chat:
            identifier = chat.id
            
    if identifier is None and msg.text:
        t = msg.text.strip()
        bare = t[1:] if t.startswith('-') else t
        if t.startswith("@") or bare.isdigit():
            identifier = t
            
    if identifier is None:
        await msg.reply_text("⚠️ Kanal aniqlanmadi. Xabarni Forward qiling yoki @username yuboring:")
        return ADD_CHANNEL
        
    try:
        chat = await context.bot.get_chat(identifier)
        channel_id = str(chat.id)
        channel_title = chat.title or "Telegram Kanal"
    except TelegramError as e:
        logger.error(f"Kanal xatosi: {e}")
        await msg.reply_text("⚠️ Kanal topilmadi yoki bot u yerda admin emas.", reply_markup=get_cancel_keyboard())
        return ADD_CHANNEL
        
    if db.save_channel(user_id, channel_id, channel_title):
        await msg.reply_text(
            f"✅ <b>Muvaffaqiyatli ulandi!</b>\n\n📢 Nomi: <b>{html_escape(channel_title)}</b>\n🆔 ID: <code>{channel_id}</code>",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="HTML"
        )
    else:
        await msg.reply_text("❌ Saqlashda xatolik.", reply_markup=get_main_keyboard(is_admin))
    return ConversationHandler.END

async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)
    try:
        _, channel_id, scope = query.data.split(":")
    except Exception:
        await query.answer("Xatolik.", show_alert=True)
        return
        
    if db.remove_channel(user_id, channel_id, is_admin=is_admin):
        await query.answer("Kanal o'chirildi.")
    else:
        await query.answer("O'chirib bo'lmadi.", show_alert=True)
        return
        
    if scope == "all":
        channels = db.get_all_channels()
        text, markup = render_channels_list(channels, show_owner=True)
    else:
        channels = db.get_user_channels(user_id)
        text, markup = render_channels_list(channels, show_owner=False)
        
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    except TelegramError:
        pass

async def on_bot_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmu = update.my_chat_member
    if not cmu:
        return
    chat = cmu.chat
    if chat.type not in ("channel", "group", "supergroup"):
        return
    new_status = cmu.new_chat_member.status
    adder = cmu.from_user
    
    if new_status in ("administrator", "creator", "member"):
        if chat.type == "channel" and new_status not in ("administrator", "creator"):
            return
        ok = db.save_channel(adder.id if adder else 0, str(chat.id), chat.title or "Nomsiz")
        if ok and adder:
            try:
                await context.bot.send_message(
                    chat_id=adder.id,
                    text=f"✅ <b>{html_escape(chat.title)}</b> avtomatik ulandi! Endi post rejalashtirishingiz mumkin.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    elif new_status in ("left", "kicked"):
        db.remove_channel(0, str(chat.id), is_admin=True)
