from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import SUPER_ADMIN
from database import register_user, add_channel, get_user_channels

WAITING_CHANNEL_FORWARD = 100

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    register_user(user.id, user.username or "", user.full_name or "")
    
    keyboard = [
        ["➕ Yangi post yaratish"],
        ["📋 Rejalashtirilgan postlar", "❌ Postni o'chirish"],
        ["📢 Kanallarim", "➕ Kanal ulash"]
    ]
    
    if user.id == SUPER_ADMIN:
        keyboard.append(["👑 Admin Panel"])
        
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"👋 Salom, **{user.first_name}**!\n\n"
        "Kanallaringizga postlarni avtomatik rejalashtirish botiga xush kelibsiz.\n\n"
        "📌 **Boshlash tartibi:**\n"
        "1. Botni o'z kanalingizga qo'shib **Admin** qiling.\n"
        "2. **➕ Kanal ulash** tugmasi orqali kanalingizni ro'yxatdan o'tkazing.\n"
        "3. **➕ Yangi post yaratish** orqali postlarni tayyorlang.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def list_channels_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = get_user_channels(user_id)
    
    if not channels:
        await update.message.reply_text("Sizda hali ulangan kanallar yo'q. '➕ Kanal ulash' tugmasi orqali kanal qo'shing.")
        return
        
    text = "📢 **Siz ulagan kanallar:**\n\n"
    for idx, ch in enumerate(channels, 1):
        text += f"{idx}. **{ch[1]}** (ID: `{ch[0]}`)\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def add_channel_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Kanalni ulash uchun:\n"
        "1. Kanalingizdan istalgan xabarni bu yerga **Forward** qiling.\n"
        "2. Yoki ochiq kanal linkini yuboring (masalan: `@kanal_nomi`).\n\n"
        "*(Eslatma: Bot kanalda avvaldan admin bo'lishi shart)*"
    )
    return WAITING_CHANNEL_FORWARD

async def add_channel_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    msg = update.message

    channel_id = None
    channel_title = None

    if msg.forward_from_chat:
        channel_id = msg.forward_from_chat.id
        channel_title = msg.forward_from_chat.title or "Kanal"
    elif msg.text and (msg.text.startswith("@") or msg.text.startswith("-100")):
        try:
            chat = await context.bot.get_chat(msg.text.strip())
            channel_id = chat.id
            channel_title = chat.title or msg.text.strip()
        except Exception:
            await msg.reply_text("❌ Kanal topilmadi yoki bot u yerda admin emas.")
            return WAITING_CHANNEL_FORWARD

    if channel_id:
        try:
            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=context.bot.id)
            if member.status in ["administrator", "creator"]:
                add_channel(user_id, str(channel_id), channel_title)
                await msg.reply_text(f"✅ **{channel_title}** muvaffaqiyatli ulandi!", parse_mode="Markdown")
                return ConversationHandler.END
            else:
                await msg.reply_text("❌ Bot bu kanalda admin emas. Unga admin huquqini bering.")
                return WAITING_CHANNEL_FORWARD
        except Exception:
            await msg.reply_text("❌ Xatolik: Bot kanalga a'zo qilinmagan.")
            return WAITING_CHANNEL_FORWARD
    else:
        await msg.reply_text("Iltimos, xabarni Forward qiling yoki kanal usernameni to'g'ri yozing.")
        return WAITING_CHANNEL_FORWARD
