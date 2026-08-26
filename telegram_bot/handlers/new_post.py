from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_channels, save_scheduled_post
from scheduler import schedule_new_post
from datetime import datetime
import pytz
import os

SELECT_CHANNEL, SEND_POST, SET_TIME = range(3)

async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        await update.message.reply_text("Sizda hali ulangan kanallar yo'q. Avval 'Kanal ulash' bo'limidan kanal qo'shing.")
        return ConversationHandler.END

    keyboard = [[KeyboardButton(c['channel_title'])] for c in channels]
    keyboard.append([KeyboardButton("🔙 Asosiy menyu")])
    
    await update.message.reply_text(
        "Qaysi kanalga post rejalashtiramiz?\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return SELECT_CHANNEL

async def select_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🔙 Asosiy menyu":
        from handlers.start import show_main_menu
        await show_main_menu(update, context)
        return ConversationHandler.END

    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    # Kanalni title yoki username bo'yicha qidirish
    selected = None
    for c in channels:
        if c['channel_title'].strip() == text or c.get('channel_username', '') == text:
            selected = c
            break

    if not selected:
        keyboard = [[KeyboardButton(c['channel_title'])] for c in channels]
        keyboard.append([KeyboardButton("🔙 Asosiy menyu")])
        await update.message.reply_text(
            "🤔 Bunday kanal yo'q. Pastdagi tugmalardan tanlang:",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return SELECT_CHANNEL

    context.user_data['post_channel_id'] = selected['channel_id']
    context.user_data['post_channel_title'] = selected['channel_title']
    
    cancel_keyboard = ReplyKeyboardMarkup([[KeyboardButton("🔙 Asosiy menyu")]], resize_keyboard=True)
    await update.message.reply_text(
        f"Tanlandi: <b>{selected['channel_title']}</b>\n\nEndi kanalga yuborilishi kerak bo'lgan postni (matn, rasm, video yoki forward) yuboring:",
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )
    return SEND_POST

async def receive_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.text == "🔙 Asosiy menyu":
        from handlers.start import show_main_menu
        await show_main_menu(update, context)
        return ConversationHandler.END

    # Post turini aniqlash
    if msg.photo:
        context.user_data['message_type'] = 'photo'
        context.user_data['file_id'] = msg.photo[-1].file_id
        context.user_data['caption'] = msg.caption_html or ""
    elif msg.video:
        context.user_data['message_type'] = 'video'
        context.user_data['file_id'] = msg.video.file_id
        context.user_data['caption'] = msg.caption_html or ""
    elif msg.document:
        context.user_data['message_type'] = 'document'
        context.user_data['file_id'] = msg.document.file_id
        context.user_data['caption'] = msg.caption_html or ""
    elif msg.text:
        context.user_data['message_type'] = 'text'
        context.user_data['post_text'] = msg.text_html
    else:
        await update.message.reply_text("Iltimos, faqat matn, rasm, video yoki hujjat yuboring.")
        return SEND_POST

    tz_str = os.getenv("TIMEZONE", "Asia/Tashkent")
    tz = pytz.timezone(tz_str)
    now_str = datetime.now(tz).strftime("%Y-%m-%d %H:%M")

    cancel_keyboard = ReplyKeyboardMarkup([[KeyboardButton("🔙 Asosiy menyu")]], resize_keyboard=True)
    await update.message.reply_text(
        f"Post qabul qilindi! ✅\n\nQaysi vaqtda chiqsin? Format: <code>YYYY-MM-DD HH:MM</code>\nMasalan: <code>{now_str}</code>",
        reply_markup=cancel_keyboard,
        parse_mode="HTML"
    )
    return SET_TIME

async def receive_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text == "🔙 Asosiy menyu":
        from handlers.start import show_main_menu
        await show_main_menu(update, context)
        return ConversationHandler.END

    tz_str = os.getenv("TIMEZONE", "Asia/Tashkent")
    tz = pytz.timezone(tz_str)

    try:
        scheduled_dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        scheduled_dt = tz.localize(scheduled_dt)
        now_dt = datetime.now(tz)
        
        if scheduled_dt <= now_dt:
            await update.message.reply_text("⚠️ Rejalashtirish vaqti kelajakdagi vaqt bo'lishi kerak. Qaytadan kiriting:")
            return SET_TIME
    except ValueError:
        await update.message.reply_text("❌ Noto'g'ri vaqt formati. Iltimos, <code>YYYY-MM-DD HH:MM</code> formatida kiriting (masalan: 2026-08-26 20:00):", parse_mode="HTML")
        return SET_TIME

    user_id = update.effective_user.id
    post_id = save_scheduled_post(
        user_id=user_id,
        channel_id=context.user_data['post_channel_id'],
        message_type=context.user_data['message_type'],
        text=context.user_data.get('post_text'),
        file_id=context.user_data.get('file_id'),
        caption=context.user_data.get('caption'),
        scheduled_time=scheduled_dt
    )

    schedule_new_post(context.application, post_id, scheduled_dt)

    from handlers.start import show_main_menu
    await update.message.reply_text(f"✅ Post muvaffaqiyatli rejalashtirildi!\n🆔 Post ID: #{post_id}\n📅 Vaqti: {text}")
    await show_main_menu(update, context)
    return ConversationHandler.END
