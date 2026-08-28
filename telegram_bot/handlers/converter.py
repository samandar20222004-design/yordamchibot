import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from keyboards.default import get_cancel_keyboard
from utils.converter import to_cyrillic, to_latin
from utils.helpers import html_escape

logger = logging.getLogger(__name__)
CONVERT_INPUT = 300

async def start_converter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchidan matn yoki matnli media fayl yuborishni so'raydi."""
    context.user_data.clear()
    await update.message.reply_text(
        "🔤 <b>Lotin ⇄ Kirill Matn O'girgich:</b>\n\n"
        "Istalgan matnni yoki <b>rasm/video/fayl</b> (tagida yozuvi bilan) yuboring:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return CONVERT_INPUT

async def converter_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kelgan xabar turini (matn yoki media) aniqlaydi va o'girish tugmalarini chiqaradi."""
    msg = update.message
    
    text = ""
    media_type = "text"
    file_id = None
    
    # 1. Media turini va matnni aniqlaymiz
    if msg.text:
        text = msg.text
        media_type = "text"
    elif msg.photo:
        text = msg.caption or ""
        media_type = "photo"
        file_id = msg.photo[-1].file_id
    elif msg.video:
        text = msg.caption or ""
        media_type = "video"
        file_id = msg.video.file_id
    elif msg.document:
        text = msg.caption or ""
        media_type = "document"
        file_id = msg.document.file_id
    elif msg.audio:
        text = msg.caption or ""
        media_type = "audio"
        file_id = msg.audio.file_id
    elif msg.voice:
        text = msg.caption or ""
        media_type = "voice"
        file_id = msg.voice.file_id
    elif msg.animation: # GIF
        text = msg.caption or ""
        media_type = "animation"
        file_id = msg.animation.file_id
        
    if not text:
        await msg.reply_text(
            "⚠️ Ushbu fayl tagida hech qanday yozuv (matn) topilmadi.\n"
            "Iltimos, matn yuboring yoki fayl tagiga izoh yozib qaytadan yuboring:"
        )
        return CONVERT_INPUT

    # 2. Lotin va Kirill variantlarini hisoblaymiz
    cyr = to_cyrillic(text)
    lat = to_latin(text)
    
    # Ma'lumotlarni sessiyada saqlaymiz
    context.user_data["media_type"] = media_type
    context.user_data["file_id"] = file_id
    context.user_data["cyr_text"] = cyr
    context.user_data["lat_text"] = lat
    
    keyboard = [
        [InlineKeyboardButton("🔤 Kirillcha nusxasi", callback_data="conv_show:cyr")],
        [InlineKeyboardButton("🔤 Lotincha nusxasi", callback_data="conv_show:lat")]
    ]
    
    await msg.reply_text(
        "📝 <b>Matn qabul qilindi!</b>\n\n"
        "Qaysi alifboga o'girmoqchisiz? Quyidagi tugmalardan birini tanlang 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CONVERT_INPUT

async def converter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma bosilganda o'girilgan matnni yoki faylni yangi izoh bilan qaytaradi."""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.split(":")[1]
    res_text = context.user_data.get("cyr_text", "") if choice == "cyr" else context.user_data.get("lat_text", "")
    media_type = context.user_data.get("media_type", "text")
    file_id = context.user_data.get("file_id")
    
    if not res_text:
        await query.message.reply_text("⚠️ Matn topilmadi, iltimos qaytadan yuboring.")
        return
        
    chat_id = query.from_user.id
    bot = context.bot
    
    # Media turiga qarab mos holda qaytarib yuboramiz
    try:
        if media_type == "text":
            await bot.send_message(
                chat_id=chat_id,
                text=f"📋 <b>Natija:</b>\n\n<code>{html_escape(res_text)}</code>\n\n<i>(Nusxalash uchun matn ustiga bosing)</i>",
                parse_mode="HTML"
            )
        elif media_type == "photo":
            await bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=res_text
            )
        elif media_type == "video":
            await bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=res_text
            )
        elif media_type == "document":
            await bot.send_document(
                chat_id=chat_id,
                document=file_id,
                caption=res_text
            )
        elif media_type == "audio":
            await bot.send_audio(
                chat_id=chat_id,
                audio=file_id,
                caption=res_text
            )
        elif media_type == "voice":
            await bot.send_voice(
                chat_id=chat_id,
                voice=file_id,
                caption=res_text
            )
        elif media_type == "animation":
            await bot.send_animation(
                chat_id=chat_id,
                animation=file_id,
                caption=res_text
            )
    except Exception as e:
        logger.error(f"Konverter natijasini yuborishda xato: {e}")
        await bot.send_message(chat_id=chat_id, text=f"⚠️ Xatolik yuz berdi: {e}")
