import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from keyboards.default import get_cancel_keyboard
from utils.converter import to_cyrillic, to_latin
from utils.helpers import html_escape, get_auto_ad_injection_async
from locales.translations import clear_fsm_data, get_lang, get_text

logger = logging.getLogger(__name__)

# State (Holat): Matn yoki media kutish
# Eslatma: 601 SUBSCRIPTION_VIEW bilan to'qnashgan edi (states dict'da
# biri ikkinchisini o'chirib yuborardi) — endi unikal qiymat.
CONVERT_INPUT = 300


async def start_converter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Konverter holatini boshlaydi (waiting_for_text) — foydalanuvchi tilida."""
    clear_fsm_data(context)
    lang = get_lang(context)
    await update.message.reply_text(
        get_text("conv_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return CONVERT_INPUT


async def converter_inline_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'⚙️ Qo'shimcha funksiyalar' inline menyusidan konverterni ochish (uz/ru)."""
    query = update.callback_query
    await query.answer()
    clear_fsm_data(context)
    lang = get_lang(context)
    try:
        await query.message.delete()
    except Exception:
        pass
    await query.message.reply_text(
        get_text("conv_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return CONVERT_INPUT


async def converter_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Faqat CONVERT_INPUT holatida kelgan xabarlarni o'giradi (uz/ru)."""
    msg = update.message
    lang = get_lang(context)
    text = ""
    media_type = "text"
    file_id = None

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
    elif msg.animation:
        text = msg.caption or ""
        media_type = "animation"
        file_id = msg.animation.file_id

    if not text:
        await msg.reply_text(
            get_text("conv_no_text", lang),
            reply_markup=get_cancel_keyboard(lang)
        )
        return CONVERT_INPUT

    cyr = to_cyrillic(text)
    lat = to_latin(text)

    context.user_data["media_type"] = media_type
    context.user_data["file_id"] = file_id
    context.user_data["cyr_text"] = cyr
    context.user_data["lat_text"] = lat

    keyboard = [
        [InlineKeyboardButton(get_text("conv_btn_cyr", lang), callback_data="conv_show:cyr")],
        [InlineKeyboardButton(get_text("conv_btn_lat", lang), callback_data="conv_show:lat")],
        [InlineKeyboardButton(get_text("cab_close", lang), callback_data="conv_close")],
    ]

    await msg.reply_text(
        get_text("conv_received", lang),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    return CONVERT_INPUT


async def converter_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Konverter inline oynasini yopadi (✅ Yopildi. / ✅ Закрыто.)."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        try:
            await query.edit_message_text(
                get_text("msg_closed", get_lang(context)), reply_markup=None
            )
        except Exception:
            pass


def _split_smartly(text: str, max_first_len: int = 950) -> tuple[str, str]:
    if len(text) <= max_first_len:
        return text, ""
    split_index = text.rfind("\n", 0, max_first_len)
    if split_index == -1 or split_index < 400:
        split_index = text.rfind(". ", 0, max_first_len)
        if split_index != -1:
            split_index += 1
    if split_index == -1 or split_index < 400:
        split_index = text.rfind(" ", 0, max_first_len)
    if split_index == -1:
        split_index = max_first_len

    part1 = text[:split_index].strip()
    part2 = text[split_index:].strip()
    return part1, part2


async def converter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """conv_show:cyr / conv_show:lat — natijani foydalanuvchi tilida chiqaradi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    choice = query.data.split(":")[1]
    res_text = context.user_data.get("cyr_text", "") if choice == "cyr" else context.user_data.get("lat_text", "")
    media_type = context.user_data.get("media_type", "text")
    file_id = context.user_data.get("file_id")

    if not res_text:
        await query.message.reply_text(get_text("conv_no_saved_text", lang))
        return

    chat_id = query.from_user.id
    bot = context.bot
    ad_line = await get_auto_ad_injection_async(chat_id)

    try:
        if media_type == "text":
            if len(res_text) <= 4000:
                await bot.send_message(
                    chat_id=chat_id,
                    text=(
                        f"{get_text('conv_result_title', lang)}\n\n"
                        f"<code>{html_escape(res_text)}</code>\n\n"
                        f"{get_text('conv_copy_hint', lang)}{ad_line}"
                    ),
                    parse_mode="HTML"
                )
            else:
                part1, part2 = _split_smartly(res_text, max_first_len=3800)
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"{get_text('conv_result_part1', lang)}\n\n<code>{html_escape(part1)}</code>",
                    parse_mode="HTML",
                )
                if part2:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=f"{get_text('conv_result_part2', lang)}\n\n<code>{html_escape(part2)}</code>{ad_line}",
                        parse_mode="HTML",
                    )
            return

        if len(res_text) > 1000:
            part1, part2 = _split_smartly(res_text, max_first_len=950)
            if media_type == "photo":
                await bot.send_photo(chat_id=chat_id, photo=file_id, caption=part1)
            elif media_type == "video":
                await bot.send_video(chat_id=chat_id, video=file_id, caption=part1)
            elif media_type == "document":
                await bot.send_document(chat_id=chat_id, document=file_id, caption=part1)
            elif media_type == "audio":
                await bot.send_audio(chat_id=chat_id, audio=file_id, caption=part1)
            elif media_type == "voice":
                await bot.send_voice(chat_id=chat_id, voice=file_id, caption=part1)
            elif media_type == "animation":
                await bot.send_animation(chat_id=chat_id, animation=file_id, caption=part1)

            if part2:
                notice = (
                    f"{get_text('conv_cont_title', lang)}\n\n"
                    f"<code>{html_escape(part2)}</code>{ad_line}"
                )
                await bot.send_message(chat_id=chat_id, text=notice, parse_mode="HTML")
        else:
            if media_type == "photo":
                await bot.send_photo(chat_id=chat_id, photo=file_id, caption=res_text)
            elif media_type == "video":
                await bot.send_video(chat_id=chat_id, video=file_id, caption=res_text)
            elif media_type == "document":
                await bot.send_document(chat_id=chat_id, document=file_id, caption=res_text)
            elif media_type == "audio":
                await bot.send_audio(chat_id=chat_id, audio=file_id, caption=res_text)
            elif media_type == "voice":
                await bot.send_voice(chat_id=chat_id, voice=file_id, caption=res_text)
            elif media_type == "animation":
                await bot.send_animation(chat_id=chat_id, animation=file_id, caption=res_text)
            if ad_line:
                await bot.send_message(chat_id=chat_id, text=ad_line.strip(), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Konverter xatosi: {e}")
        await bot.send_message(
            chat_id=chat_id,
            text=get_text("conv_error", lang, error=e),
        )
