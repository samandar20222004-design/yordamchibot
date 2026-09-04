import asyncio
import json
import re
import time
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    BTN_ALL_CHANNELS_TARGET, BTN_MAIN_MENU, BTN_BACK, BTN_SKIP_BUTTON,
    BTN_ADD_URL_BUTTON, BTN_SKIP_URL_BUTTON,
    BTN_T_5MIN, BTN_T_15MIN, BTN_T_1H, BTN_T_DAILY, BTN_T_WEEKLY,
    BTN_DUR_1W, BTN_DUR_1M, BTN_DUR_3M, BTN_DUR_6M, BTN_DUR_1Y, BTN_DUR_INF,
    WEEKDAY_MAP, WEEKDAY_LABELS,
    BTN_ALL_CHANNELS_TARGET_RU, BTN_SKIP_BUTTON_RU, BTN_ADD_URL_BUTTON_RU,
    BTN_SKIP_URL_BUTTON_RU, BTN_NO_REACT_RU, BTN_BACK_RU, BTN_BACK_TO_CONFIRM_RU,
    BTN_T_5MIN_RU, BTN_T_15MIN_RU, BTN_T_1H_RU, BTN_T_DAILY_RU, BTN_T_WEEKLY_RU,
    BTN_DUR_1W_RU, BTN_DUR_1M_RU, BTN_DUR_3M_RU, BTN_DUR_6M_RU, BTN_DUR_1Y_RU,
    BTN_DUR_INF_RU, WEEKDAY_MAP_RU, WEEKDAY_LABELS_RU,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_reactions_keyboard, get_auto_delete_keyboard, get_time_keyboard,
    get_duration_keyboard, get_weekday_keyboard
)
from keyboards.inline import (
    btn_label, get_reaction_toggle_keyboard, normalize_reaction_emojis,
    normalize_custom_reaction_emojis, strip_variation_selector,
    REACTION_EMOJIS,
)
from utils.helpers import html_escape, parse_future_time, safe_html, parse_reactions_input, get_auto_ad_injection_async
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from locales.translations import clear_fsm_data, get_lang, get_text

tashkent_tz = pytz.timezone("Asia/Tashkent")

# Albom (media_group) yig'ish: bir nechta rasm/video bitta post bo'lishi uchun.
# concurrent_updates=True bo'lgani uchun token+sleep ishlaydi.
_ALBUM_BUFFERS = {}
_ALBUM_WAIT_SECONDS = 1.5
_ALBUM_MAX_ITEMS = 10

CHOOSE_CHANNEL = 100
GET_CONTENT = 101
GET_BTN_TITLE = 102
GET_BTN_URL = 103
GET_REACTIONS = 104
GET_AUTO_DELETE = 105
GET_TIME = 106
DAILY_TIME = 107
RECUR_DAY = 108
RECUR_TIME = 109
GET_DURATION = 110
CONFIRM_POST = 111       # Tasdiqlash ekrani
EDIT_CONFIRM_FIELD = 112  # Confirmation'dan tahrirlash

def build_channel_labels(channels) -> dict:
    """Kanal ro'yxatidan tugma yorliqlari xaritasini tuzadi ({label: channel_id}).

    - Bo'sh/None sarlavhali kanal ham yaroqli yorliq oladi (Telegram bo'sh
      tugma matnini rad etadi).
    - Bir xil nomli kanallar bir-birini yopib qo'ymaydi: nomga ID, kerak
      bo'lsa tartib raqami qo'shiladi.
    """
    channels_map = {}
    for ch_id, ch_title in channels:
        label = btn_label(ch_title, "Kanal", max_length=48)
        if label in channels_map:
            label = f"{label} ({ch_id})"
        base_label = label
        suffix = 2
        while label in channels_map:
            label = f"{base_label} #{suffix}"
            suffix += 1
        channels_map[label] = ch_id
    return channels_map


# ============================================================
# INLINE URL TUGMA QURUVCHI (tezkor format: "Button Text - https://link.com")
# ============================================================
_URL_BUTTON_SEPARATORS = (" - ", " — ", " – ", "|", "=")


def normalize_button_url(link: str) -> str | None:
    """Havolani InlineKeyboardButton(url=...) uchun normalize qiladi.

    '@kanal' → https://t.me/kanal; 'example.uz' → https://example.uz;
    't.me/kanal' → https://t.me/kanal. URL ko'rinishiga kelmagan
    matn uchun None qaytaradi.
    """
    if not link:
        return None
    link = str(link).strip()
    if not link or " " in link:
        return None
    if link.startswith(("http://", "https://", "tg://")):
        return link
    if link.startswith("t.me/"):
        return "https://" + link
    if link.startswith("@"):
        username = link.lstrip("@")
        return f"https://t.me/{username}" if re.fullmatch(r"[A-Za-z0-9_]{3,32}", username) else None
    if "." in link:  # example.uz ko'rinishidagi domen
        return "https://" + link
    return None


def parse_url_button_line(text: str) -> "tuple[str, str] | None":
    """'Button Text - https://link.com' formatidagi qatorni (matn, havola) ga ajratadi.

    Qo'llab-quvvatlanadi:
      • "Batafsil - https://sayt.uz"
      • "Kanalim - @kanalim"
      • "Sayt - example.uz"
      • "A'zo bo'lish | https://t.me/kanal"

    Havola qismi oxirgi so'z bo'lishi va URL/@username/t.me ko'rinishida
    bo'lishi kerak — aks holda None qaytadi (oddiy matn sanaladi).
    """
    if not text:
        return None
    raw = str(text).strip()
    if "\n" in raw or len(raw) < 3:
        return None
    for sep in _URL_BUTTON_SEPARATORS:
        if sep not in raw:
            continue
        parts = raw.rsplit(sep, 1)
        if len(parts) != 2:
            continue
        title, link = parts[0].strip(), parts[1].strip()
        # Havola qismi bitta so'z bo'lishi kerak (ichida bo'sh joy bo'lmasin)
        if not title or not link or " " in link:
            continue
        normalized = normalize_button_url(link)
        if normalized:
            return title, normalized
    return None


async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_fsm_data(context)
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)
    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await update.message.reply_text(
            get_text("new_post_no_channels", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML"
        )
        return ConversationHandler.END

    # Bir xil nomli kanallar bo'lsa, nomga ID qo'shib farqlaymiz —
    # aks holda ikkita kanal bir xil nomda bo'lsa, biri ikkinchisini yopib qo'yardi.
    # Nomsiz (bo'sh sarlavhali) kanal ham yaroqli yorliq oladi: Telegram bo'sh
    # tugma matnini qabul qilmaydi.
    channels_map = build_channel_labels(channels)
    keyboard = [[label] for label in channels_map]
    if len(channels) > 1:
        keyboard.append([get_text("np_btn_all_channels", lang)])
    keyboard.append([get_text("btn_main_menu", lang)])

    context.user_data["channels_map"] = channels_map
    await update.message.reply_text(
        get_text("new_post_choose_channel", lang),
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSE_CHANNEL

async def channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    if text in (BTN_ALL_CHANNELS_TARGET, BTN_ALL_CHANNELS_TARGET_RU):
        context.user_data["selected_channel_id"] = "ALL"
        context.user_data["selected_channel_title"] = get_text("np_all_channel_title", lang)
    else:
        channels_map = context.user_data.get("channels_map", {})
        if text not in channels_map:
            await update.message.reply_text(get_text("np_channel_not_found", lang))
            return CHOOSE_CHANNEL
        context.user_data["selected_channel_id"] = channels_map[text]
        context.user_data["selected_channel_title"] = text

    await update.message.reply_text(
        get_text("np_channel_selected", lang,
                 channel=html_escape(context.user_data["selected_channel_title"])),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_CONTENT


def _media_item_from_message(msg):
    """Bitta xabardan media elementi (albom yoki yakka). None = matn."""
    caption = msg.caption or ""
    if msg.photo:
        return {"type": "photo", "file_id": msg.photo[-1].file_id, "caption": caption}
    if msg.video:
        return {"type": "video", "file_id": msg.video.file_id, "caption": caption}
    if msg.document:
        return {"type": "document", "file_id": msg.document.file_id, "caption": caption}
    if msg.audio:
        return {"type": "audio", "file_id": msg.audio.file_id, "caption": caption}
    if msg.animation:
        return {"type": "animation", "file_id": msg.animation.file_id, "caption": caption}
    if msg.voice:
        return {"type": "voice", "file_id": msg.voice.file_id, "caption": caption}
    if msg.sticker:
        return {"type": "sticker", "file_id": msg.sticker.file_id, "caption": ""}
    return None


def _purge_stale_albums():
    now = time.time()
    stale = [k for k, v in _ALBUM_BUFFERS.items() if now - v.get("ts", 0) > 120]
    for k in stale:
        _ALBUM_BUFFERS.pop(k, None)


def _apply_single_media(context, item):
    context.user_data["post_type"] = item["type"]
    context.user_data["file_id"] = item["file_id"]
    context.user_data["content"] = item.get("caption") or ""


async def _ask_button_prompt(msg, lang="uz"):
    await msg.reply_text(
        get_text("np_button_ask", lang),
        reply_markup=get_button_prompt_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_BTN_TITLE


async def _ask_reactions_step(msg, context):
    """Multi-select reaksiya tanlash qadami (inline toggle klaviatura).

    Keyingi qadamga faqat "[➡️ Davom etish]" yoki "[⏭ Reaksiyasiz o'tish]"
    bosilganda o'tiladi (callback handlerlar orqali).
    """
    lang = get_lang(context)
    selected = context.user_data.setdefault("selected_reactions", [])
    await msg.reply_text(
        get_text("np_reactions_ask", lang),
        reply_markup=get_reaction_toggle_keyboard(selected, lang),
        parse_mode="HTML"
    )
    return GET_REACTIONS


async def _proceed_after_reactions(msg, context, selected_emojis):
    """Reaksiya tanlovidan yakunlanganidan keyingi qadam (avto-o'chirish).

    ``normalize_custom_reaction_emojis``: foydalanuvchi QO'LDA kiritgan
    kanondan tashqari emojilar (😍, 💯, 🙏 ...) ham saqlanib qoladi va
    kanal postida tugma sifatida chiqadi (faqat 6 ta standart emoji bilan
    chegaralanib qolmaydi).
    """
    lang = get_lang(context)
    ordered = normalize_custom_reaction_emojis(selected_emojis)
    context.user_data["enable_reactions"] = bool(ordered)
    context.user_data["reaction_emojis"] = ordered
    await msg.reply_text(
        get_text("np_auto_delete_ask", lang),
        reply_markup=get_auto_delete_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_AUTO_DELETE


def _build_preview_text(context) -> str:
    """Confirmation ekrani uchun post preview matnini tuzadi (uz/ru)."""
    lang = get_lang(context)
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data.get("post_type", "text")
    content = context.user_data.get("content", "")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    delete_after_hours = context.user_data.get("delete_after_hours", 0)
    post_time = context.user_data.get("confirm_post_time")
    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")
    recurrence_day = context.user_data.get("confirm_recurrence_day")

    if recurrence_type == "daily" and recurrence_time_str:
        when_text = get_text("np_confirm_time_daily", lang, time=recurrence_time_str[:5])
    elif recurrence_type == "weekly" and recurrence_time_str:
        day_label = (WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS).get(recurrence_day, "?")
        when_text = get_text("np_confirm_time_weekly", lang, day=day_label, time=recurrence_time_str[:5])
    elif post_time:
        when_text = get_text("np_confirm_time_single", lang,
                             time=post_time.strftime("%Y-%m-%d %H:%M"))
    else:
        when_text = get_text("np_confirm_time_none", lang)

    type_labels = {
        "text": "np_type_text", "photo": "np_type_photo", "video": "np_type_video",
        "document": "np_type_document", "audio": "np_type_audio",
        "voice": "np_type_voice", "sticker": "np_type_sticker",
        "album": "np_type_album", "animation": "np_type_animation",
    }
    type_text = get_text(type_labels.get(post_type, "np_type_unknown"), lang)

    content_preview = ""
    if content:
        preview = content[:300]
        if len(content) > 300:
            preview += "…"
        content_preview = "\n\n" + get_text("np_confirm_content", lang, content=safe_html(preview))

    btn_info = ""
    if btn_text and btn_url:
        btn_info = "\n" + get_text("np_confirm_button", lang, text=html_escape(btn_text))
    react_info = ""
    if enable_reactions:
        # Qo'lda kiritilgan (kanondan tashqari) emojilar ham ko'rsatiladi.
        chosen_emojis = normalize_custom_reaction_emojis(context.user_data.get("reaction_emojis"))
        react_info = "\n" + (
            get_text("np_confirm_reactions", lang, emojis=" ".join(chosen_emojis))
            if chosen_emojis else get_text("np_confirm_reactions_on", lang)
        )
    del_info = (
        "\n" + get_text("np_confirm_auto_delete", lang, hours=delete_after_hours)
        if delete_after_hours > 0 else ""
    )

    return (
        f"{get_text('np_confirm_title', lang)}\n\n"
        f"{get_text('np_confirm_channel', lang, channel=html_escape(channel_title))}\n"
        f"{get_text('np_confirm_type', lang, type=type_text)}\n"
        f"{when_text}"
        f"{content_preview}"
        f"{btn_info}{react_info}{del_info}"
    )


def _get_confirm_keyboard(lang="uz"):
    """Tasdiqlash ekranidagi inline tugmalar (uz/ru)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("np_confirm_ok_btn", lang), callback_data="confirm_post:ok")],
        [InlineKeyboardButton(get_text("np_confirm_queue_btn", lang), callback_data="confirm_post:queue")],
        [
            InlineKeyboardButton(get_text("np_confirm_edit_btn", lang), callback_data="confirm_post:edit"),
            InlineKeyboardButton(get_text("np_confirm_cancel_btn", lang), callback_data="confirm_post:cancel"),
        ],
    ])


def _get_edit_confirm_keyboard(lang="uz"):
    """Tahrirlash sub-menyusi tugmalari (uz/ru)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text("np_edit_content_btn", lang), callback_data="edit_field:content"),
            InlineKeyboardButton(get_text("np_edit_channel_btn", lang), callback_data="edit_field:channel"),
        ],
        [
            InlineKeyboardButton(get_text("np_edit_time_btn", lang), callback_data="edit_field:time"),
            InlineKeyboardButton(get_text("np_edit_button_btn", lang), callback_data="edit_field:btn"),
        ],
        [InlineKeyboardButton(get_text("np_edit_back_btn", lang), callback_data="edit_field:back")],
    ])


# Tasdiqlash kartasi sifatida IN-PLACE tahrirlanadigan media turlari.
# sticker/voice/album uchun karta matn (text) ko'rinishida ko'rsatiladi.
_CONFIRM_MEDIA_TYPES = ("photo", "video", "document", "audio", "animation")


async def _edit_confirm_card(bot, chat_id, msg_id, card_type, preview, keyboard):
    """Mavjud tasdiqlash kartasini joyida (in-place) tahrirlaydi.

    - Media karta (photo/video/...) uchun ``edit_message_caption`` chaqiriladi
      — rasm/video file_id QAYTA YUKLANMAYDI (tez ishlaydi va media yo'qolmaydi).
    - Matn karta uchun ``edit_message_text`` chaqiriladi.
    Muvaffaqiyatli bo'lsa True qaytadi.
    """
    try:
        if card_type == "text":
            await bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=preview[:4096], reply_markup=keyboard, parse_mode="HTML",
            )
        else:
            await bot.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=preview[:1024], reply_markup=keyboard, parse_mode="HTML",
            )
        return True
    except Exception:
        # HTML parse xatosi bo'lsa — oddiy matn bilan bir marta qayta urinamiz.
        try:
            if card_type == "text":
                await bot.edit_message_text(
                    chat_id=chat_id, message_id=msg_id,
                    text=preview[:4096], reply_markup=keyboard, parse_mode=None,
                )
            else:
                await bot.edit_message_caption(
                    chat_id=chat_id, message_id=msg_id,
                    caption=preview[:1024], reply_markup=keyboard, parse_mode=None,
                )
            return True
        except Exception:
            return False


async def _send_confirm_card(target_msg, context, preview, keyboard, post_type, file_id):
    """Yangi tasdiqlash kartasini yuboradi (media karta yoki matn karta)."""
    bot = context.bot if getattr(context, "bot", None) is not None else target_msg
    chat_id = target_msg.chat_id
    if file_id and post_type in _CONFIRM_MEDIA_TYPES:
        cap = preview[:1024]
        try:
            if post_type == "photo":
                sent = await bot.send_photo(chat_id=chat_id, photo=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "video":
                sent = await bot.send_video(chat_id=chat_id, video=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "document":
                sent = await bot.send_document(chat_id=chat_id, document=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            elif post_type == "audio":
                sent = await bot.send_audio(chat_id=chat_id, audio=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            else:
                sent = await bot.send_animation(chat_id=chat_id, animation=file_id, caption=cap, reply_markup=keyboard, parse_mode="HTML")
            return sent.message_id, post_type
        except Exception:
            pass
    sent = await bot.send_message(chat_id=chat_id, text=preview[:4096], reply_markup=keyboard, parse_mode="HTML")
    return sent.message_id, "text"


async def _show_confirmation(target_msg, context):
    """Preview kartasini ko'rsatadi va CONFIRM_POST holatiga qaytadi.

    TEZLIK VA MEDIA SAQLASH: tahrirlash (matn/tugma/vaqt o'zgartirish)
    paytida har safar YANGI media xabar yuborilmasligi uchun avvalgi karta
    JOYIDA tahrirlanadi:
      • media post (photo/video/document/audio/animation) → edit_message_caption
        — file_id saqlanib qoladi, rasm/video qayta yuklanmaydi;
      • faqat matnli post → edit_message_text.
    Tur o'zgargan yoki xabar tahrirlab bo'lmaydigan hollarda eskisi
    o'chirilib, yangi karta yuboriladi (ortiqcha kutishlarsiz).
    """
    preview = _build_preview_text(context)
    post_type = context.user_data.get("post_type", "text")
    file_id = context.user_data.get("file_id")
    keyboard = _get_confirm_keyboard(get_lang(context))

    bot = context.bot if getattr(context, "bot", None) is not None else target_msg
    chat_id = target_msg.chat_id
    new_card_type = post_type if (file_id and post_type in _CONFIRM_MEDIA_TYPES) else "text"

    old_id = context.user_data.get("confirm_msg_id")
    old_type = context.user_data.get("confirm_msg_type") or "text"

    # 1) Bir xil turdagi kartani joyida tahrirlaymiz (eng tez yo'l).
    if old_id and old_type == new_card_type:
        if await _edit_confirm_card(bot, chat_id, old_id, old_type, preview, keyboard):
            return
        # Tahrirlab bo'lmadi (xabar o'chirilgan va h.k.) — eskisini tozalab, yangi yuboramiz.
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass
        context.user_data["confirm_msg_id"] = None

    # 2) Tur o'zgargan (matn↔media) yoki karta yo'q — yangi karta yuboramiz.
    if old_id and old_type != new_card_type:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass
        context.user_data["confirm_msg_id"] = None

    new_id, sent_type = await _send_confirm_card(target_msg, context, preview, keyboard, post_type, file_id)
    context.user_data["confirm_msg_id"] = new_id
    context.user_data["confirm_msg_type"] = sent_type


async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id

    # 🚫 Stiker va qo'llab-quvvatlanmaydigan media — post sifatida qabul
    # qilinmaydi. Bot OSILIB QOLMASLIGI uchun foydalanuvchiga aniq (uz/ru)
    # xabar yuborib, GET_CONTENT holatida qaytamiz (post yaratish davom etadi).
    item0 = _media_item_from_message(msg)
    unsupported = bool(getattr(msg, "sticker", None)) or (
        item0 is not None and item0["type"] in ("sticker", "voice", "video_note")
    )
    # Rasm/video/hujjat/audio/animation yoki matn yo'q bo'lgan (masalan,
    # kontakt, joylashuv, o'yincha) xabarlar ham post bo'lolmaydi.
    if unsupported or (
        item0 is None
        and not getattr(msg, "photo", None)
        and not getattr(msg, "text", None)
        and not (msg.caption or "")
    ):
        await msg.reply_text(
            get_text("np_media_not_allowed", get_lang(context)),
            parse_mode="HTML",
        )
        return GET_CONTENT

    if msg.media_group_id:
        item = _media_item_from_message(msg)
        if not item or item["type"] in ("voice", "sticker"):
            return GET_CONTENT

        _purge_stale_albums()
        key = (user_id, msg.media_group_id)
        buf = _ALBUM_BUFFERS.setdefault(key, {"items": [], "seq": 0, "ts": time.time()})
        if len(buf["items"]) < _ALBUM_MAX_ITEMS:
            buf["items"].append(item)
        buf["seq"] += 1
        buf["ts"] = time.time()
        my_seq = buf["seq"]

        # Boshqa albom elementlari ham start bo'lishi uchun avval yield
        await asyncio.sleep(0)
        await asyncio.sleep(_ALBUM_WAIT_SECONDS)
        current = _ALBUM_BUFFERS.get(key)
        if not current or current.get("seq") != my_seq:
            return GET_CONTENT

        items = _ALBUM_BUFFERS.pop(key, {}).get("items") or [item]
        caption = next((i.get("caption") or "" for i in items if i.get("caption")), "")
        if len(items) == 1:
            _apply_single_media(context, items[0])
        else:
            context.user_data["post_type"] = "album"
            context.user_data["file_id"] = json.dumps(items, ensure_ascii=False)
            context.user_data["content"] = caption
        return await _ask_button_prompt(msg, get_lang(context))

    item = _media_item_from_message(msg)
    if item:
        _apply_single_media(context, item)
    else:
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["content"] = msg.text or ""

    return await _ask_button_prompt(msg, get_lang(context))

async def btn_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()

    # AI Yordamchi tugmasi (uz/ru)
    if text in (get_text("np_btn_ai_assistant", "uz"), get_text("np_btn_ai_assistant", "ru")):
        content = context.user_data.get("content", "")
        if not content:
            await update.message.reply_text(
                get_text("np_ai_empty_content", lang),
                parse_mode="HTML",
            )
            return GET_BTN_TITLE
        preview = content[:200]
        if len(content) > 200:
            preview += "…"
        await update.message.reply_text(
            get_text("np_ai_menu_title", lang, preview=html_escape(preview)),
            reply_markup=_get_ai_action_keyboard(lang),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    # Tugmasiz o'tish (eski va yangi "skip" tugmalari bir xil ishlaydi)
    if text in (BTN_SKIP_BUTTON, BTN_SKIP_URL_BUTTON,
                BTN_SKIP_BUTTON_RU, BTN_SKIP_URL_BUTTON_RU):
        context.user_data["btn_text"], context.user_data["btn_url"] = None, None
        return await _ask_reactions_step(update.message, context)

    # "🔗 URL tugma qo'shish" — bir qatorli tezkor formatga yo'naltirish
    if text in (BTN_ADD_URL_BUTTON, BTN_ADD_URL_BUTTON_RU):
        await update.message.reply_text(
            get_text("np_button_url_add_ask", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    # Tezkor format: "Button Text - https://link.com" — bir xabarda tugma tayyor
    one_liner = parse_url_button_line(text)
    if one_liner:
        btn_text, btn_url = one_liner
        context.user_data["btn_text"] = btn_text
        context.user_data["btn_url"] = btn_url
        await update.message.reply_text(
            get_text("np_button_ready", lang,
                     title=html_escape(btn_text), url=html_escape(btn_url)),
            parse_mode="HTML",
        )
        return await _ask_reactions_step(update.message, context)

    context.user_data["btn_text"] = text
    await update.message.reply_text(
        get_text("np_button_url_ask", lang, title=html_escape(text)),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_BTN_URL

async def btn_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()

    # GET_BTN_URL holatida ham tezkor format ishlashi mumkin
    if text in (BTN_SKIP_BUTTON, BTN_SKIP_URL_BUTTON,
                BTN_SKIP_BUTTON_RU, BTN_SKIP_URL_BUTTON_RU,
                BTN_ADD_URL_BUTTON, BTN_ADD_URL_BUTTON_RU):
        return await btn_title_received(update, context)
    one_liner = parse_url_button_line(text)
    if one_liner:
        btn_text, btn_url = one_liner
        context.user_data["btn_text"] = btn_text
        context.user_data["btn_url"] = btn_url
        await update.message.reply_text(
            get_text("np_button_ready", lang,
                     title=html_escape(btn_text), url=html_escape(btn_url)),
            parse_mode="HTML",
        )
        return await _ask_reactions_step(update.message, context)

    btn_link = text
    if btn_link.startswith("@"):
        btn_link = f"https://t.me/{btn_link.lstrip('@')}"
    elif not (btn_link.startswith("http://") or btn_link.startswith("https://") or btn_link.startswith("t.me/")):
        if "." in btn_link:
            btn_link = "https://" + btn_link
        else:
            btn_link = f"https://t.me/{btn_link.lstrip('@')}"

    context.user_data["btn_url"] = btn_link
    return await _ask_reactions_step(update.message, context)

async def reactions_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """GET_REACTIONS uchun matnli zaxira handler (asosiy yo'l — inline toggle).

    - Emoji matn sifatida yuborilsa — tanlovga qo'shiladi va klaviatura yangilanadi.
    - "reaksiyasiz/yo'q/skip" — reaksiyasiz davom etiladi.
    - Boshqa matn — inline tugmalarni ishlatish eslatiladi.
    """
    lang = get_lang(context)
    msg = update.message
    text = msg.text
    parsed = parse_reactions_input(text)

    # Rus tilidagi "reaksiyasiz" tugma/so'zlar ham reaksiyasiz davom ettiradi.
    ru_skip_words = ("без реакций", "нет", "пропустить", "отключить", "не надо")
    if parsed is False or text in (BTN_NO_REACT, BTN_NO_REACT_RU) \
            or (text or "").strip().lower() in ru_skip_words:
        return await _proceed_after_reactions(msg, context, [])

    if parsed is True:
        # Emoji(yorliq) matn sifatida yuborilgan bo'lsa — multi-select tanlovga qo'shamiz.
        # normalize_custom_reaction_emojis: kanonik 6 ta emoji BILAN BIRGA
        # foydalanuvchi qo'lda kiritgan boshqa emojilar (😍, 💯, 🙏 ...) ham
        # saqlanib qoladi va kanal postida tugma bo'lib chiqadi.
        typed = normalize_custom_reaction_emojis(text)
        if typed and len(text) <= 60:
            selected = context.user_data.setdefault("selected_reactions", [])
            existing_keys = {strip_variation_selector(e) for e in selected}
            for emoji in typed:
                if strip_variation_selector(emoji) not in existing_keys:
                    selected.append(emoji)
                    existing_keys.add(strip_variation_selector(emoji))
            # Foydalanuvchiga aniq emoji ko'rsatish uchun kanonik normalizatsiyani
            # qo'shimcha bajarib qo'yamiz (toggle ✅ belgilari uchun).
            await msg.reply_text(
                get_text("np_reactions_selected", lang, emojis=" ".join(selected)),
                reply_markup=get_reaction_toggle_keyboard(selected, lang),
                parse_mode="HTML",
            )
            return GET_REACTIONS
        # "ha/reaksiya/yes" kabi matnli tasdiqlash — mavjud tanlov yoki standart to'plam bilan davom etamiz
        selected = context.user_data.get("selected_reactions") or normalize_reaction_emojis(None)
        return await _proceed_after_reactions(msg, context, selected)

    await msg.reply_text(
        get_text("np_reactions_use_inline", lang),
        reply_markup=get_reaction_toggle_keyboard(context.user_data.get("selected_reactions", []), lang),
        parse_mode="HTML",
    )
    return GET_REACTIONS


async def reaction_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Multi-select: emoji tugma bosilganda tanlovga qo'shadi yoki olib tashlaydi."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    parts = data.split(":", 2)
    emoji = parts[2] if len(parts) == 3 else ""
    if emoji not in REACTION_EMOJIS:
        return GET_REACTIONS

    selected = context.user_data.setdefault("selected_reactions", [])
    if emoji in selected:
        selected.remove(emoji)
    else:
        selected.append(emoji)

    try:
        await query.edit_message_reply_markup(
            reply_markup=get_reaction_toggle_keyboard(selected, get_lang(context))
        )
    except Exception:
        pass
    return GET_REACTIONS


async def reactions_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"➡️ Davom etish" — tanlangan reaksiyalar bilan keyingi qadamga o'tadi."""
    query = update.callback_query
    await query.answer()
    # Qo'lda kiritilgan (kanondan tashqari) emojilar ham saqlanib qoladi.
    selected = normalize_custom_reaction_emojis(context.user_data.get("selected_reactions"))
    if not selected:
        await query.message.reply_text(
            get_text("np_reactions_none", get_lang(context)),
            parse_mode="HTML",
        )
    return await _proceed_after_reactions(query.message, context, selected)


async def reactions_skip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"⏭ Reaksiyasiz o'tish" — reaksiyalarsiz keyingi qadamga o'tadi."""
    query = update.callback_query
    await query.answer()
    context.user_data["selected_reactions"] = []
    return await _proceed_after_reactions(query.message, context, [])

async def auto_delete_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    hours = 0
    if "12" in text:
        hours = 12
    elif "24" in text:
        hours = 24
    elif "48" in text:
        hours = 48
    elif "72" in text:
        hours = 72

    context.user_data["delete_after_hours"] = hours

    lang = get_lang(context)
    now = datetime.now(tashkent_tz)
    example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    await update.message.reply_text(
        get_text("np_time_ask", lang, example=example),
        reply_markup=get_time_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_TIME

async def _save_and_finish(update, context, post_time, recurrence_type='none', recurrence_day=None, recurrence_time_str=None, end_date=None):
    is_admin = (update.effective_user.id in ADMIN_IDS_SET)
    user_id = update.effective_user.id
    selected_channel_id = context.user_data["selected_channel_id"]
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data["post_type"]
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    reaction_emojis = context.user_data.get("reaction_emojis")
    delete_after_hours = context.user_data.get("delete_after_hours", 0)

    post_time_tz = post_time.astimezone(tashkent_tz)
    channels = (
        await db.run_db(db.get_user_channels, user_id)
        if selected_channel_id == "ALL"
        else [(selected_channel_id, channel_title)]
    )
    ok_count = 0

    for ch_id, _ in channels:
        pid = await db.run_db(
            db.add_post,
            user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
            file_id=file_id, scheduled_time=post_time_tz, recurrence_type=recurrence_type,
            recurrence_day=recurrence_day, recurrence_time=recurrence_time_str, end_date=end_date,
            btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
                    reaction_emojis=reaction_emojis,
            delete_after_hours=delete_after_hours
        )
        if pid:
            ok_count += 1

    lang = get_lang(context)
    if ok_count:
        if recurrence_type == 'daily':
            when_text = get_text("np_scheduled_when_daily", lang, time=recurrence_time_str[:5])
        elif recurrence_type == 'weekly':
            day_label = (WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS).get(recurrence_day, "?")
            when_text = get_text("np_scheduled_when_weekly", lang, day=day_label, time=recurrence_time_str[:5])
        else:
            when_text = get_text("np_scheduled_when_single", lang,
                                 time=post_time_tz.strftime("%Y-%m-%d %H:%M"))

        del_info = get_text("np_scheduled_del", lang, hours=delete_after_hours) if delete_after_hours > 0 else ""
        await update.message.reply_text(
            get_text("np_scheduled_ok", lang,
                     channel=html_escape(channel_title), when=when_text, del_info=del_info),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            get_text("np_save_error", lang),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML"
        )
    clear_fsm_data(context)

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    now = datetime.now(tashkent_tz)

    if text in (BTN_T_DAILY, BTN_T_DAILY_RU):
        await update.message.reply_text(
            get_text("np_daily_time_ask", lang), reply_markup=get_cancel_keyboard(lang), parse_mode="HTML")
        return DAILY_TIME
    elif text in (BTN_T_WEEKLY, BTN_T_WEEKLY_RU):
        await update.message.reply_text(
            get_text("np_weekday_ask", lang), reply_markup=get_weekday_keyboard(lang), parse_mode="HTML")
        return RECUR_DAY

    post_time = None
    try:
        if text in (BTN_T_5MIN, BTN_T_5MIN_RU):
            post_time = now + timedelta(minutes=5)
        elif text in (BTN_T_15MIN, BTN_T_15MIN_RU):
            post_time = now + timedelta(minutes=15)
        elif text in (BTN_T_1H, BTN_T_1H_RU):
            post_time = now + timedelta(hours=1)
        else:
            post_time = parse_future_time(text.strip(), now)
            if post_time is None:
                naive_time = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
                post_time = tashkent_tz.localize(naive_time)

        if post_time is None or post_time <= now:
            await update.message.reply_text(get_text("np_time_future", lang))
            return GET_TIME
    except Exception:
        await update.message.reply_text(get_text("np_time_format_error", lang), parse_mode="HTML")
        return GET_TIME

    # Confirmation ekranini ko'rsatish
    context.user_data["confirm_post_time"] = post_time
    context.user_data["confirm_recurrence_type"] = "none"
    context.user_data["confirm_recurrence_day"] = None
    context.user_data["confirm_recurrence_time_str"] = None
    context.user_data["confirm_end_date"] = None
    await _show_confirmation(update.message, context)
    return CONFIRM_POST

async def daily_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text(
            get_text("np_daily_time_format", lang), parse_mode="HTML")
        return DAILY_TIME

    now = datetime.now(tashkent_tz)
    first_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if first_run <= now:
        first_run += timedelta(days=1)

    context.user_data["rec_first_run"] = first_run
    context.user_data["rec_type"] = "daily"
    context.user_data["rec_time_str"] = f"{hh:02d}:{mm:02d}:00"
    context.user_data["rec_day"] = None

    await update.message.reply_text(
        get_text("np_duration_ask_daily", lang),
        reply_markup=get_duration_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_DURATION

async def recur_day_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    day_idx = WEEKDAY_MAP_RU.get(text) if text in WEEKDAY_MAP_RU else WEEKDAY_MAP.get(text)
    if day_idx is None:
        await update.message.reply_text(get_text("np_weekday_invalid", lang))
        return RECUR_DAY

    context.user_data["rec_day"] = day_idx
    await update.message.reply_text(
        get_text("np_recur_time_ask", lang, day=text),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return RECUR_TIME

async def recur_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()
    try:
        hh, mm = map(int, text.split(":"))
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text(
            get_text("np_recur_time_format", lang), parse_mode="HTML")
        return RECUR_TIME

    now = datetime.now(tashkent_tz)
    target_day = context.user_data["rec_day"]
    days_ahead = (target_day - now.weekday() + 7) % 7
    first_run = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(days=days_ahead)
    if first_run <= now:
        first_run += timedelta(days=7)

    context.user_data["rec_first_run"] = first_run
    context.user_data["rec_type"] = "weekly"
    context.user_data["rec_time_str"] = f"{hh:02d}:{mm:02d}:00"

    await update.message.reply_text(
        get_text("np_duration_ask_weekly", lang),
        reply_markup=get_duration_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_DURATION

async def duration_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    now = datetime.now(tashkent_tz)
    end_date = None

    if text in (BTN_DUR_1W, BTN_DUR_1W_RU):
        # Yangi: post har kuni roppa-rosa 1 hafta (7 kun) davomida chiqadi
        end_date = now + timedelta(days=7)
    elif text in (BTN_DUR_1M, BTN_DUR_1M_RU):
        end_date = now + timedelta(days=30)
    elif text in (BTN_DUR_3M, BTN_DUR_3M_RU):
        end_date = now + timedelta(days=90)
    elif text in (BTN_DUR_6M, BTN_DUR_6M_RU):
        end_date = now + timedelta(days=180)
    elif text in (BTN_DUR_1Y, BTN_DUR_1Y_RU):
        end_date = now + timedelta(days=365)
    elif text in (BTN_DUR_INF, BTN_DUR_INF_RU):
        end_date = None
    else:
        await update.message.reply_text(get_text("np_duration_invalid", lang))
        return GET_DURATION

    # Confirmation ekranini ko'rsatish
    context.user_data["confirm_post_time"] = context.user_data["rec_first_run"]
    context.user_data["confirm_recurrence_type"] = context.user_data["rec_type"]
    context.user_data["confirm_recurrence_day"] = context.user_data["rec_day"]
    context.user_data["confirm_recurrence_time_str"] = context.user_data["rec_time_str"]
    context.user_data["confirm_end_date"] = end_date
    await _show_confirmation(update.message, context)
    return CONFIRM_POST


# ============================================================
# CONFIRMATION CALLBACK HANDLERS
# ============================================================

async def confirm_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tasdiqlash ekranidagi tugmalar: OK / Queue / Edit / Cancel."""
    query = update.callback_query
    await query.answer()
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else ""
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    lang = get_lang(context)

    if action == "cancel":
        clear_fsm_data(context)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("np_cancelled", lang),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if action == "edit":
        await query.message.reply_text(
            get_text("np_edit_menu_title", lang),
            reply_markup=_get_edit_confirm_keyboard(lang),
            parse_mode="HTML",
        )
        return EDIT_CONFIRM_FIELD

    if action == "queue":
        selected_channel_id = context.user_data.get("selected_channel_id")
        if not selected_channel_id:
            await query.message.reply_text(
                get_text("np_no_channel", lang),
                reply_markup=get_main_keyboard(is_admin, context=context),
                parse_mode="HTML",
            )
            clear_fsm_data(context)
            return ConversationHandler.END

        now = datetime.now(tashkent_tz)
        slots = await db.run_db(db.get_queue_slots, user_id)
        ch_id_for_q = selected_channel_id if selected_channel_id != "ALL" else "ALL"
        occupied = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, now.date())

        slot_dt, label = db.find_next_queue_slot(slots, occupied, now)
        if not slot_dt:
            tomorrow = now + timedelta(days=1)
            tomorrow_start = tashkent_tz.localize(
                datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
            )
            occ_tom = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, tomorrow.date())
            slot_dt, label = db.find_next_queue_slot(slots, occ_tom, tomorrow_start)

        if not slot_dt:
            for day_off in range(2, 8):
                future_date = now.date() + timedelta(days=day_off)
                occ = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, future_date)
                future_start = tashkent_tz.localize(
                    datetime(future_date.year, future_date.month, future_date.day, 0, 0)
                )
                slot_dt, label = db.find_next_queue_slot(slots, occ, future_start)
                if slot_dt:
                    break

        if not slot_dt:
            await query.message.reply_text(
                get_text("np_no_slot", lang),
                reply_markup=get_main_keyboard(is_admin, context=context),
                parse_mode="HTML",
            )
            clear_fsm_data(context)
            return ConversationHandler.END

        post_type = context.user_data.get("post_type")
        content = context.user_data.get("content")
        file_id = context.user_data.get("file_id")
        btn_text = context.user_data.get("btn_text")
        btn_url = context.user_data.get("btn_url")
        enable_reactions = context.user_data.get("enable_reactions", False)
        reaction_emojis = context.user_data.get("reaction_emojis")
        delete_after_hours = context.user_data.get("delete_after_hours", 0)
        channel_title = context.user_data.get("selected_channel_title", "Kanal")

        channels = (
            await db.run_db(db.get_user_channels, user_id)
            if selected_channel_id == "ALL"
            else [(selected_channel_id, channel_title)]
        )
        ok_count = 0
        for ch_id, _ in channels:
            try:
                pid = await db.run_db(
                    db.add_post,
                    user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
                    file_id=file_id, scheduled_time=slot_dt, recurrence_type='none',
                    recurrence_day=None, recurrence_time=None, end_date=None,
                    btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
                    reaction_emojis=reaction_emojis,
                    delete_after_hours=delete_after_hours
                )
                if pid:
                    ok_count += 1
            except Exception:
                pass

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        if ok_count:
            time_str = slot_dt.strftime("%H:%M")
            ad_line = await get_auto_ad_injection_async(user_id)
            # db.find_next_queue_slot "Bugun"/"Ertaga" qaytaradi — RU'ga o'giramiz.
            label_ru = {"Bugun": get_text("np_label_today", "ru"),
                        "Ertaga": get_text("np_label_tomorrow", "ru")}.get(label, label)
            label_uz = {"Bugun": get_text("np_label_today", "uz"),
                        "Ertaga": get_text("np_label_tomorrow", "uz")}.get(label, label)
            label_i18n = label_ru if lang == "ru" else label_uz
            await query.message.reply_text(
                get_text("np_queue_added", lang, label=label_i18n, time=time_str,
                         channel=html_escape(channel_title), ad_line=ad_line or ""),
                reply_markup=get_main_keyboard(is_admin, context=context),
                parse_mode="HTML",
            )
        else:
            await query.message.reply_text(
                get_text("np_queue_error", lang),
                reply_markup=get_main_keyboard(is_admin, context=context),
                parse_mode="HTML",
            )
        clear_fsm_data(context)
        return ConversationHandler.END

    # action == "ok"
    post_time = context.user_data.get("confirm_post_time")
    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_day = context.user_data.get("confirm_recurrence_day")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")
    end_date = context.user_data.get("confirm_end_date")

    if not post_time:
        await query.message.reply_text(
            get_text("np_no_time", lang),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML"
        )
        clear_fsm_data(context)
        return ConversationHandler.END

    selected_channel_id = context.user_data.get("selected_channel_id")
    channel_title = context.user_data.get("selected_channel_title", "Kanal")
    post_type = context.user_data.get("post_type")
    content = context.user_data.get("content")
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
    reaction_emojis = context.user_data.get("reaction_emojis")
    delete_after_hours = context.user_data.get("delete_after_hours", 0)

    post_time_tz = post_time.astimezone(tashkent_tz)
    channels = (
        await db.run_db(db.get_user_channels, user_id)
        if selected_channel_id == "ALL"
        else [(selected_channel_id, channel_title)]
    )
    ok_count = 0
    for ch_id, _ in channels:
        try:
            pid = await db.run_db(
                db.add_post,
                user_id=user_id, channel_id=ch_id, post_type=post_type, content=content,
                file_id=file_id, scheduled_time=post_time_tz, recurrence_type=recurrence_type,
                recurrence_day=recurrence_day, recurrence_time=recurrence_time_str, end_date=end_date,
                btn_text=btn_text, btn_url=btn_url, enable_reactions=enable_reactions,
                    reaction_emojis=reaction_emojis,
                delete_after_hours=delete_after_hours
            )
            if pid:
                ok_count += 1
        except Exception:
            pass

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    if ok_count:
        if recurrence_type == "daily" and recurrence_time_str:
            when_text = get_text("np_scheduled_when_daily", lang, time=recurrence_time_str[:5])
        elif recurrence_type == "weekly" and recurrence_time_str:
            day_label = (WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS).get(recurrence_day, "?")
            when_text = get_text("np_scheduled_when_weekly", lang, day=day_label, time=recurrence_time_str[:5])
        else:
            when_text = get_text("np_scheduled_when_single", lang,
                                 time=post_time_tz.strftime("%Y-%m-%d %H:%M"))
        del_info = get_text("np_scheduled_del", lang, hours=delete_after_hours) if delete_after_hours > 0 else ""
        ad_line = await get_auto_ad_injection_async(user_id)
        await query.message.reply_text(
            get_text("np_scheduled_ok", lang,
                     channel=html_escape(channel_title), when=when_text,
                     del_info=del_info) + (ad_line or ""),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text(
            get_text("np_save_error_bold", lang),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML"
        )
    clear_fsm_data(context)
    return ConversationHandler.END


    return CONFIRM_POST


async def edit_confirm_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tahrirlash sub-menyusi."""
    query = update.callback_query
    await query.answer()
    data = query.data
    field = data.split(":", 1)[1] if ":" in data else ""

    if field == "back":
        await _show_confirmation(query.message, context)
        return CONFIRM_POST

    lang = get_lang(context)

    if field == "content":
        await query.message.reply_text(
            get_text("np_edit_content_ask", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML"
        )
        return EDIT_CONFIRM_FIELD

    if field == "channel":
        user_id = query.from_user.id
        channels = await db.run_db(db.get_user_channels, user_id)
        if not channels:
            await query.message.reply_text(get_text("np_edit_channel_not_found", lang))
            return EDIT_CONFIRM_FIELD
        channels_map = build_channel_labels(channels)
        keyboard = [[label] for label in channels_map]
        if len(channels) > 1:
            keyboard.append([get_text("np_btn_all_channels", lang)])
        keyboard.append([get_text("np_btn_back_confirm", lang)])
        context.user_data["edit_channels_map"] = channels_map
        await query.message.reply_text(
            get_text("np_edit_channel_ask", lang),
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
            parse_mode="HTML"
        )
        return EDIT_CONFIRM_FIELD

    if field == "time":
        now = datetime.now(tashkent_tz)
        example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
        await query.message.reply_text(
            get_text("np_edit_time_ask", lang, example=example),
            reply_markup=get_time_keyboard(lang),
            parse_mode="HTML"
        )
        return EDIT_CONFIRM_FIELD

    if field == "btn":
        await query.message.reply_text(
            get_text("np_edit_button_ask", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML"
        )
        return EDIT_CONFIRM_FIELD

    return EDIT_CONFIRM_FIELD


async def edit_confirm_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """EDIT_CONFIRM_FIELD holatida matn qabul qilish."""
    lang = get_lang(context)
    text = (update.message.text or "").strip()

    if text in (get_text("np_btn_back_confirm", "uz"), BTN_BACK, BTN_MAIN_MENU,
                get_text("np_btn_back_confirm", "ru"), BTN_BACK_RU,
                BTN_BACK_TO_CONFIRM_RU):
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    edit_channels_map = context.user_data.get("edit_channels_map")
    if edit_channels_map:
        if text in (get_text("np_btn_all_channels", "uz"), get_text("np_btn_all_channels", "ru")):
            context.user_data["selected_channel_id"] = "ALL"
            context.user_data["selected_channel_title"] = get_text("np_all_channel_title", lang)
            context.user_data.pop("edit_channels_map", None)
            await _show_confirmation(update.message, context)
            return CONFIRM_POST
        elif text in edit_channels_map:
            context.user_data["selected_channel_id"] = edit_channels_map[text]
            context.user_data["selected_channel_title"] = text
            context.user_data.pop("edit_channels_map", None)
            await _show_confirmation(update.message, context)
            return CONFIRM_POST

    now = datetime.now(tashkent_tz)
    new_time = None
    try:
        if text in (BTN_T_5MIN, BTN_T_5MIN_RU):
            new_time = now + timedelta(minutes=5)
        elif text in (BTN_T_15MIN, BTN_T_15MIN_RU):
            new_time = now + timedelta(minutes=15)
        elif text in (BTN_T_1H, BTN_T_1H_RU):
            new_time = now + timedelta(hours=1)
        else:
            new_time = parse_future_time(text, now)
            if new_time is None:
                try:
                    naive_time = datetime.strptime(text, "%Y-%m-%d %H:%M")
                    new_time = tashkent_tz.localize(naive_time)
                except Exception:
                    pass
    except Exception:
        pass

    if new_time and new_time > now:
        context.user_data["confirm_post_time"] = new_time
        context.user_data["confirm_recurrence_type"] = "none"
        context.user_data["confirm_recurrence_day"] = None
        context.user_data["confirm_recurrence_time_str"] = None
        context.user_data["confirm_end_date"] = None
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if "|" in text:
        parts = text.split("|", 1)
        btn_t = parts[0].strip()
        btn_u = parts[1].strip()
        if btn_u.startswith("@"):
            btn_u = f"https://t.me/{btn_u.lstrip('@')}"
        elif not btn_u.startswith(("http://", "https://", "t.me/")):
            btn_u = "https://" + btn_u if "." in btn_u else f"https://t.me/{btn_u.lstrip('@')}"
        context.user_data["btn_text"] = btn_t
        context.user_data["btn_url"] = btn_u
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if text.lower() in ("yo'q", "yoq", "none", "-", "o'chir", "нет", "удалить"):
        context.user_data["btn_text"] = None
        context.user_data["btn_url"] = None
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    if text and text not in (BTN_T_DAILY, BTN_T_WEEKLY, BTN_T_DAILY_RU, BTN_T_WEEKLY_RU,
                             BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU):
        # Caption/text editing must never discard the original media.  Only a
        # newly uploaded media message is allowed to replace type/file_id.
        context.user_data["content"] = text
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    await _show_confirmation(update.message, context)
    return CONFIRM_POST


async def edit_confirm_media_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """EDIT_CONFIRM_FIELD holatida media qabul qilish."""
    msg = update.message
    item = _media_item_from_message(msg)
    if item:
        _apply_single_media(context, item)
    await _show_confirmation(msg, context)
    return CONFIRM_POST


# ============================================================
# AI FORMATTING ACTIONS
# ============================================================
# ============================================================
# AI FORMATTING ACTIONS
# ============================================================

def _get_ai_action_keyboard(lang="uz"):
    """AI harakatlari keyboard (uz/ru)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text("np_ai_action_grammar", lang), callback_data="ai_act:grammar"),
            InlineKeyboardButton(get_text("np_ai_action_emoji", lang), callback_data="ai_act:emoji"),
        ],
        [
            InlineKeyboardButton(get_text("np_ai_action_hashtags", lang), callback_data="ai_act:hashtags"),
            InlineKeyboardButton(get_text("np_ai_action_tldr", lang), callback_data="ai_act:tldr"),
        ],
        [InlineKeyboardButton(get_text("np_ai_btn_back", lang), callback_data="ai_act:back")],
    ])


def _get_ai_result_keyboard(lang="uz"):
    """AI natijasidan keyin tasdiqlash keyboard (uz/ru)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text("np_ai_btn_accept", lang), callback_data="ai_res:accept"),
            InlineKeyboardButton(get_text("np_ai_btn_retry", lang), callback_data="ai_res:retry"),
        ],
        [InlineKeyboardButton(get_text("np_ai_btn_revert", lang), callback_data="ai_res:revert")],
    ])


async def ai_action_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI harakatlari menyusini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    content = context.user_data.get("content", "")
    if not content:
        await query.message.reply_text(
            get_text("np_ai_empty_content", lang),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    preview = content[:200]
    if len(content) > 200:
        preview += "…"
    await query.message.reply_text(
        get_text("np_ai_menu_title", lang, preview=html_escape(preview)),
        reply_markup=_get_ai_action_keyboard(lang),
        parse_mode="HTML",
    )
    return GET_BTN_TITLE


async def ai_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI harakati tugmasi bosilganda."""
    query = update.callback_query
    data = query.data
    lang = get_lang(context)
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "back":
        await query.answer()
        return GET_BTN_TITLE

    content = context.user_data.get("content", "")
    if not content:
        await query.answer(get_text("np_ai_empty_alert", lang), show_alert=True)
        return GET_BTN_TITLE

    await query.answer(get_text("np_ai_working", lang))

    # Asl matnni saqlab qolish (revert uchun)
    context.user_data["ai_original_content"] = content

    from utils.ai_agent import format_post_text
    result = await format_post_text(content, action)

    if "error" in result:
        await query.message.reply_text(result["error"], parse_mode="HTML")
        return GET_BTN_TITLE

    formatted = result.get("formatted", "")
    if not formatted:
        await query.message.reply_text(
            get_text("np_ai_empty_result", lang), parse_mode="HTML")
        return GET_BTN_TITLE

    context.user_data["ai_proposed_content"] = formatted
    context.user_data["ai_last_action"] = action

    old_preview = content[:150]
    if len(content) > 150:
        old_preview += "…"
    new_preview = formatted[:300]
    if len(formatted) > 300:
        new_preview += "…"

    await query.message.reply_text(
        get_text("np_ai_proposal", lang, new=safe_html(new_preview),
                 old=html_escape(old_preview)),
        reply_markup=_get_ai_result_keyboard(lang),
        parse_mode="HTML",
    )
    return GET_BTN_TITLE


async def ai_result_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """AI natijasini qabul qilish / rad etish."""
    query = update.callback_query
    data = query.data
    lang = get_lang(context)
    action = data.split(":", 1)[1] if ":" in data else ""

    if action == "accept":
        proposed = context.user_data.get("ai_proposed_content", "")
        if proposed:
            # AI FAQAT matnni o'zgartiradi — media (rasm/video/file_id) HECH
            # QACHON o'chirilmaydi. Avvalgi xato: post_type="text", file_id=None
            # qilinardi, natijada rasm/video post matn postiga aylanib, media
            # yo'qolib qolardi.
            context.user_data["content"] = proposed
        context.user_data.pop("ai_original_content", None)
        context.user_data.pop("ai_proposed_content", None)
        context.user_data.pop("ai_last_action", None)
        await query.answer(get_text("np_ai_accepted_alert", lang))
        await query.message.reply_text(
            get_text("np_ai_accept_msg", lang, content=safe_html(proposed[:300])),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    if action == "revert":
        original = context.user_data.get("ai_original_content", "")
        if original:
            context.user_data["content"] = original
        context.user_data.pop("ai_original_content", None)
        context.user_data.pop("ai_proposed_content", None)
        context.user_data.pop("ai_last_action", None)
        await query.answer(get_text("np_ai_reverted_alert", lang))
        await query.message.reply_text(
            get_text("np_ai_revert_msg", lang),
            parse_mode="HTML",
        )
        return GET_BTN_TITLE

    if action == "retry":
        await query.answer(get_text("np_ai_retrying", lang))
        content = context.user_data.get("ai_original_content", context.user_data.get("content", ""))
        last_action = context.user_data.get("ai_last_action", "grammar")

        from utils.ai_agent import format_post_text
        result = await format_post_text(content, last_action)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
            return GET_BTN_TITLE

        formatted = result.get("formatted", "")
        if formatted:
            context.user_data["ai_proposed_content"] = formatted
            new_preview = formatted[:300]
            if len(formatted) > 300:
                new_preview += "…"
            await query.message.reply_text(
                get_text("np_ai_retry_proposal", lang, new=safe_html(new_preview)),
                reply_markup=_get_ai_result_keyboard(lang),
                parse_mode="HTML",
            )
        return GET_BTN_TITLE

    return GET_BTN_TITLE
