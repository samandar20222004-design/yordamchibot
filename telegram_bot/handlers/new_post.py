from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from database import get_user_channels, add_post

CHOOSE_CHANNEL, POST_CONTENT, POST_TIME, CONFIRM_POST = range(1, 5)

async def new_post_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        await update.message.reply_text("Avval '➕ Kanal ulash' tugmasi orqali kanalingizni ulang.")
        return ConversationHandler.END
    
    context.user_data["channels_map"] = {ch[1]: ch[0] for ch in channels}
    buttons = [[ch[1]] for ch in channels]
    buttons.append(["❌ Bekor qilish"])
    
    await update.message.reply_text(
        "Post qaysi kanalga joylansin? Quyidagilardan tanlang:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return CHOOSE_CHANNEL

async def choose_channel_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "❌ Bekor qilish":
        await update.message.reply_text("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    
    channels_map = context.user_data.get("channels_map", {})
    if choice not in channels_map:
        await update.message.reply_text("Iltimos, tugmalardan birini tanlang.")
        return CHOOSE_CHANNEL
        
    context.user_data["post_channel_id"] = channels_map[choice]
    context.user_data["post_channel_name"] = choice
    
    await update.message.reply_text(
        f"Kanal tanlandi: **{choice}**\n\nEndi post matnini yoki rasmini (tagiga yozuv bilan) yuboring:",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    return POST_CONTENT

async def post_content_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if msg.photo:
        context.user_data["photo"] = msg.photo[-1].file_id
        context.user_data["text"] = msg.caption or ""
    elif msg.text:
        context.user_data["photo"] = None
        context.user_data["text"] = msg.text
    else:
        await msg.reply_text("Faqat matn yoki rasm yuboring.")
        return POST_CONTENT
        
    await msg.reply_text(
        "Post qachon chiqarilsin?\nFormat: `YYYY-MM-DD HH:MM`\nMisol: `2026-08-25 18:30`",
        parse_mode="Markdown"
    )
    return POST_TIME

async def post_time_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    time_text = update.message.text.strip()
    try:
        scheduled_dt = datetime.strptime(time_text, "%Y-%m-%d %H:%M")
        if scheduled_dt <= datetime.now():
            await update.message.reply_text("Belgilangan vaqt hozirgi vaqtdan keyin bo'lishi kerak. Qaytadan kiriting:")
            return POST_TIME
    except ValueError:
        await update.message.reply_text("Noto'g'ri format. Misoldagidek yozing: `2026-08-25 18:30`", parse_mode="Markdown")
        return POST_TIME
        
    context.user_data["scheduled_time"] = time_text
    
    preview = f"📢 **Kanal:** {context.user_data['post_channel_name']}\n"
    preview += f"⏰ **Vaqt:** {time_text}\n\n"
    preview += f"📝 **Matn:**\n{context.user_data.get('text', '')}"
    
    keyboard = [["✅ Tasdiqlash", "❌ Bekor qilish"]]
    
    if context.user_data.get("photo"):
        await update.message.reply_photo(
            photo=context.user_data["photo"],
            caption=f"{preview}\n\nPostni tasdiqlaysizmi?",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"{preview}\n\nPostni tasdiqlaysizmi?",
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="Markdown"
        )
    return CONFIRM_POST

async def confirm_post_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choice = update.message.text
    if choice == "✅ Tasdiqlash":
        user_id = update.effective_user.id
        add_post(
            user_id=user_id,
            channel_id=context.user_data["post_channel_id"],
            text=context.user_data.get("text", ""),
            photo=context.user_data.get("photo"),
            scheduled_time=context.user_data["scheduled_time"]
        )
        await update.message.reply_text("✅ Post muvaffaqiyatli rejalashtirildi!", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("❌ Post bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Jarayon bekor qilindi.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
