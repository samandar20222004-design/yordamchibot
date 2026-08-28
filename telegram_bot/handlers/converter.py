from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from utils.converter import to_cyrillic, to_latin

CONVERT_INPUT = 300

async def start_converter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchidan o'girish uchun matn so'raydi."""
    context.user_data.clear()
    await update.message.reply_text(
        "🔤 <b>Lotin ⇄ Kirill Matn O'girgich:</b>\n\n"
        "O'girmoqchi bo'lgan matningizni yuboring:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return CONVERT_INPUT

async def converter_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Matn kelganda uning Lotin va Kirill variantlarini inline tugma bilan beradi."""
    text = update.message.text
    if not text:
        await update.message.reply_text("Iltimos, faqat matn yuboring:")
        return CONVERT_INPUT
    
    cyr = to_cyrillic(text)
    lat = to_latin(text)
    
    # Natijani xotiraga olamiz
    context.user_data["raw_text"] = text
    context.user_data["cyr_text"] = cyr
    context.user_data["lat_text"] = lat
    
    keyboard = [
        [InlineKeyboardButton("🔤 Kirillcha nusxasi", callback_data="conv_show:cyr")],
        [InlineKeyboardButton("🔤 Lotincha nusxasi", callback_data="conv_show:lat")]
    ]
    
    await update.message.reply_text(
        f"📝 <b>Matningiz qabul qilindi!</b>\n\n"
        f"Qaysi alifboga o'girmoqchisiz? Quyidagi tugmalardan birini bosing 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CONVERT_INPUT

async def converter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tugma bosilganda o'girilgan matnni foydalanuvchiga yuboradi."""
    query = update.callback_query
    await query.answer()
    
    choice = query.data.split(":")[1]
    if choice == "cyr":
        res = context.user_data.get("cyr_text", "")
        title = "Kirillcha matn"
    else:
        res = context.user_data.get("lat_text", "")
        title = "Lotincha matn"
        
    if not res:
        await query.message.reply_text("Matn topilmadi, iltimos qaytadan yuboring.")
        return
        
    await query.message.reply_text(
        f"📋 <b>{title}:</b>\n\n<code>{res}</code>\n\n<i>(Nusxalab olish uchun matn ustiga bosing)</i>",
        parse_mode="HTML"
    )
