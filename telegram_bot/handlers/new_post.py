import asyncio
import json
import re
import time
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    # Eski/yangi "skip" yorliqlari — SKIP_BUTTON_TEXTS ro'yxatini to'plash
    # uchun (chat tarixidagi klaviatura xabarlari buzilmasligi kerak).
    BTN_SKIP_BUTTON, BTN_SKIP_URL_BUTTON,
    BTN_SKIP_BUTTON_RU, BTN_SKIP_URL_BUTTON_RU,
    get_main_keyboard, get_cancel_keyboard, get_button_prompt_keyboard,
    get_auto_delete_keyboard, get_time_keyboard,
    get_duration_keyboard, get_weekday_keyboard,
    # 🌐 Uch tilli tugma registry (uz/ru/en) — barcha matn solishtiruvlari
    # shu yerdan foydalanadi, shunda klaviatura qaysi tilda chizilganiga
    # qaramay tugmalar BIR XIL ishlaydi:
    #   • "⚡ 5 minutes" (EN) ham xuddi "⚡ 5 daqiqa" (UZ) kabi rejalashtiriladi;
    #   • "Friday" (EN) ham hafta kuni sifatida qabul qilinadi;
    #   • "Skip" / "Пропустить" / "⏭ O'tkazib yuborish" — bitta oqim.
    is_menu_text, weekday_index, menu_texts,
)
from keyboards.inline import (
    btn_label, get_reaction_toggle_keyboard, normalize_reaction_emojis,
    normalize_custom_reaction_emojis, strip_variation_selector,
    strip_leading_reaction_glyphs,
    REACTION_EMOJIS,
)
from utils.helpers import (
    html_escape, safe_html, parse_reactions_input,
    get_auto_ad_injection_async, keep_typing,
    parse_schedule_input, parse_daily_time_input, schedule_time_example,
    SCHEDULE_ERR_PAST,
)
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from locales.translations import clear_fsm_data, get_lang, get_text
from utils.date_format import format_datetime, format_time, weekday_label

tashkent_tz = pytz.timezone("Asia/Tashkent")

# Albom (media_group) yig'ish: bir nechta rasm/video bitta post bo'lishi uchun.
#
# MUHIM: ``GuardedApplication`` har bir foydalanuvchi update'larini per-user
# lock bilan SERIYALI qayta ishlaydi. Shu sababli handler ICHIDA
# ``await asyncio.sleep(...)`` qilish mumkin EMAS — albomning qolgan qismlari
# lock ortida kutib qoladi va har bir rasm ALOHIDA post bo'lib ketadi.
# Yechim: birinchi albom xabari kelganda arka fonda AJRATILGAN yig'uvchi task
# (collector) ishga tushadi; qolgan xabarlar shu task kutayotganda buferga
# yig'iladi; vaqt tugagach bitta "Albom" posti sifatida yakunlanadi.
_ALBUM_BUFFERS: dict = {}       # (user_id, media_group_id) -> buffer dict
_ALBUM_WAIT_SECONDS = 3.0       # Telegram albom qismlari kelishi uchun kutiladigan vaqt
_ALBUM_MAX_ITEMS = 10           # Telegram albom chegarasi

# "⏩ O'tkazib yuborish" — pastki reply-klaviaturadagi skip tugmalari.
# Eski/asosiy yorliqlar (⏭ ...), legacy "Tugmasiz davom etish" va qo'shimcha
# variantlar ham qo'llab-quvvatlanadi.
# YANGI: ro'yxat ``MENU_TEXTS["np_skip"]`` registry'dan yig'iladi — shunda
# UZ ("⏭ O'tkazib yuborish"), RU ("⏭ Пропустить") va EN ("⏭ Skip" /
# "➡️ Continue without button") yorliqlari ham, qo'lda yozilgan "Skip" ham
# BIR XIL ishlaydi. Eski yorliqlar (⏩ ...) ham saqlanib qolgan.
SKIP_BUTTON_TEXTS = tuple(dict.fromkeys((
    "⏩ O'tkazib yuborish",
    "⏩ Пропустить",
    "⏭ O'tkazib yuborish",
    "⏭ Пропустить",
    "O'tkazib yuborish",
    "Пропустить",
    BTN_SKIP_BUTTON,
    BTN_SKIP_URL_BUTTON,
    BTN_SKIP_BUTTON_RU,
    BTN_SKIP_URL_BUTTON_RU,
) + menu_texts("np_skip")))

# ⏳ Throttling / Debounce Middleware: Callback tugmalarini ketma-ket bosishlarni oldiniш
# Foydalanuvchi_id bo'yicha so'nggi callback vaqtini xotirada saqlab, 1.5 soniya ichida
# takroriy bosishlarni oldiniш va Telegram API yordamida xabarda tuzatish.

_callback_last_call: dict = {}  # user_id -> timestamp


def check_callback_throttle(user_id: int, min_interval: float = 1.5) -> bool:
    """
    Callback query throttle tekshiriши.
    
    - True = o'tkazib yuborish (throttling effektiga uchragan)
    - False = handler davom etishi kerak
    """
    now = time.time()
    last_time = _callback_last_call.get(user_id, 0)
    elapsed = now - last_time
    
    if elapsed < min_interval:
        # Kichik vaqt o'tgan - throttling effectively
        return True
    
    # Vaqt saqlab qolamiz
    _callback_last_call[user_id] = now
    return False


def reset_callback_throttle(user_id: int) -> None:
    "Foydalanuvchi uchun throttling holatini tozalash."
    _callback_last_call.pop(user_id, None)



#: ``db.find_next_queue_slot`` qaytargan UZ yorliqlar → lug'at kaliti.
_QUEUE_SLOT_LABEL_KEYS = {"Bugun": "np_label_today", "Ertaga": "np_label_tomorrow"}


def _queue_slot_label(label, lang: str = "uz") -> str:
    """Navbat sloti yorlig'ini foydalanuvchi tiliga o'giradi (uz/ru/en).

    ``database.find_next_queue_slot`` yorliqlarni doim o'zbekcha qaytaradi
    ("Bugun"/"Ertaga"/"05.09.2026"). Foydalanuvchi RU yoki EN bo'lsa ham
    xuddi shu so'zni ko'rib qolmasligi uchun bu yerda tilga mos tarjimasi
    olinadi; sana ko'rinishlari o'zgarishsiz qaytadi.
    """
    text = "" if label is None else str(label).strip()
    if not text:
        return ""
    key = _QUEUE_SLOT_LABEL_KEYS.get(text)
    if key:
        translated = get_text(key, lang)
        # Kalit yo'q bo'lsa ``get_text`` kalit nomini qaytaradi — unda
        # foydalanuvchiga "np_label_today" ko'rsatmaymiz.
        if translated and translated != key:
            return translated
    return text


def is_skip_button_text(text) -> bool:
    """Skip (o'tkazib yuborish) tugmasi bosilganini uchala tilda aniqlaydi.

    ``MENU_TEXTS["np_skip"]`` registry'i ishlatiladi: uz/ru/en yorliqlari,
    ularning eski ko'rinishlari va emoji/bo'shliq farqlari HISOBGA
    OLINMAYDI (masalan foydalanuvchi qo'lda "Skip" deb yozsa ham ishlaydi).
    """
    if not text:
        return False
    if str(text).strip() in SKIP_BUTTON_TEXTS:
        return True
    return is_menu_text(text, "np_skip")

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
    # Eski (tugallanmagan) albom yig'uvi qolgan bo'lsa — bekor qilinadi,
    # aks holda u yangi konversatsiya user_data'iga yozilishi mumkin.
    cancel_album_collections(user_id)
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
    if is_menu_text(text, "np_all_channels"):
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
    """Eski/uzoq qolgan albom buferlarini tozalaydi (task'larni ham bekor qiladi)."""
    now = time.time()
    stale = [k for k, v in _ALBUM_BUFFERS.items() if now - v.get("ts", 0) > 120]
    for k in stale:
        _cancel_album_buffer(k)


def _album_key_of(key) -> tuple:
    return key if isinstance(key, tuple) else tuple(key)


def _cancel_album_buffer(key):
    """Bitta albom buferini va uning collector task'ini bekor qiladi."""
    buf = _ALBUM_BUFFERS.pop(key, None)
    if not buf:
        return
    task = buf.get("task")
    if task is not None and not task.done() and not task.cancelled():
        task.cancel()
    buf["done"] = True


def cancel_album_collections(user_id: int):
    """Foydalanuvchining barcha faol albom yig'ish vazifalarini bekor qiladi.

    Conversation tugaganda (cancel / time-out / yangi post boshlanganda) chaqiriladi —
    aks holda collector eski postni keyingi sessiya user_data'iga yozib qo'yishi mumkin.
    """
    for key in [k for k in _ALBUM_BUFFERS if k[0] == user_id]:
        _cancel_album_buffer(key)


def _album_items_to_post(items: list) -> dict:
    """Yig'ilgan albom elementlarini post user_data qiymatlariga aylantiradi.

    Caption har doim TO'LIQ olinadi (birinchisidan) — hech qanday qator/kesish
    qilinmaydi. Bitta element bo'lsa ham yaxlit saqlanadi (scheduler keyinchalik
    yakka media sifatida yuboradi).
    """
    caption = ""
    for item in items:
        cap = (item.get("caption") or "").strip()
        if cap:
            caption = cap
            break
    if len(items) == 1:
        return {"post_type": items[0]["type"], "file_id": items[0]["file_id"], "content": caption}
    return {
        "post_type": "album",
        "file_id": json.dumps(items, ensure_ascii=False),
        "content": caption,
    }


def _finalize_album_buffer(key, cancel_task=False) -> dict | None:
    """Buferdagi albomni HOZIROQ yakunlaydi va user_data'ga yozadi.

    ``cancel_task=True`` — kutayotgan collector task bekor qilinadi (masalan,
    foydalanuvchi vaqt o'tmasdan matn yuborganda yoki yangi albom boshlaganda).
    """
    key = _album_key_of(key)
    buf = _ALBUM_BUFFERS.get(key)
    if not buf or buf.get("done"):
        return None
    if cancel_task:
        task = buf.get("task")
        if task is not None and not task.done() and not task.cancelled():
            task.cancel()
    buf["done"] = True
    _ALBUM_BUFFERS.pop(key, None)
    items = buf.get("items") or []
    if not items:
        return None
    final = _album_items_to_post(items)
    ud = buf.get("user_data")
    if ud is not None:
        ud.update({
            "post_type": final["post_type"],
            "file_id": final["file_id"],
            "content": final["content"],
            "_album_ready": True,
            "_album_count": len(items),
        })
    return final


def _active_user_album_keys(user_id: int):
    return [k for k, v in _ALBUM_BUFFERS.items() if k[0] == user_id and not v.get("done")]


async def _album_collector(key, bot, chat_id, lang, user_data):
    """Arka fondagi albom yig'uvchi: kutish tugagach yaxlit post qilib yakunlaydi.

    - Hech qachon handler'ni bloklamaydi (per-user lock ortida qolmaydi) —
      albomning barcha qismlari buferga yig'iladi.
    - Yakun topgach user_data'ga post_type='album' + file_id (JSON ro'yxat)
      yoziladi va foydalanuvchiga keyingi qadam (tugma so'rovi) yuboriladi.
    """
    try:
        await asyncio.sleep(_ALBUM_WAIT_SECONDS)
    except asyncio.CancelledError:
        return
    buf = _ALBUM_BUFFERS.get(key)
    if not buf or buf.get("done"):
        return
    final = _finalize_album_buffer(key)
    if not final:
        return
    # Foydalanuvchiga keyingi qadam so'rovi:
    #  • ALBOM (bir nechta fayl): sendMediaGroup'ga inline_keyboard ulab
    #    bo'lmaydi — xushmuomala ogohlantirish + 2 ta tanlov;
    #  • yakka media (bitta faylli albom yoki oddiy rasm): odatdagi
    #    "Tugma qo'shilsinmi?" so'rovi (eski oqim).
    try:
        if final["post_type"] == "album":
            ud = buf.get("user_data")
            if ud is not None:
                ud["_album_warning_stage"] = "button"
            await bot.send_message(
                chat_id=chat_id,
                text=get_text("np_album_warning", lang),
                reply_markup=_album_choice_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await bot.send_message(
                chat_id=chat_id,
                text=get_text("np_button_ask", lang),
                reply_markup=get_button_prompt_keyboard(lang),
                parse_mode="HTML",
            )
    except Exception:
        # Xabar yuborib bo'lmasa ham post ma'lumotlari saqlanadi —
        # foydalanuvchi keyingi xabarni yuborganda oqim davom etadi.
        pass


def _build_album_summary(items: list, lang: str) -> str:
    """Albom uchun lokalizatsiya qilingan xulosa: '🖼 Albom: 6 ta rasm' kabi."""
    photos = sum(1 for i in items if (i.get("type") or "photo") in ("photo", "animation"))
    videos = sum(1 for i in items if (i.get("type") or "") == "video")
    total = len(items)
    if photos and videos:
        return get_text("np_confirm_album_mixed", lang, photos=photos, videos=videos)
    if photos == total:
        return get_text("np_confirm_album_photos", lang, count=total)
    if videos == total:
        return get_text("np_confirm_album_videos", lang, count=total)
    return get_text("np_confirm_album_files", lang, count=total)


def _apply_single_media(context, item):
    context.user_data["post_type"] = item["type"]
    context.user_data["file_id"] = item["file_id"]
    context.user_data["content"] = item.get("caption") or ""


# ============================================================
# 🖼 ALBOM + TUGMA/REAKSIYA CHEKLOVI (sendMediaGroup qoidasi)
# ============================================================
# Telegram Bot API qoidasi: ``sendMediaGroup`` ga ``inline_keyboard``
# (URL tugma yoki reaksiya tugmalari) ulab BO'LMAydi. Shu sababli foydalanuvchi
# bir nechta faylli ALBOM yuborgani va tugma/reaksiya bosqichiga yetgani
# dalolatida bot xushmuomala ogohlantirish beradi va 2 ta tanlov taklif etadi:
#   [🖼 1-rasm qolsin + tugma qo'shilsin] — post bitta rasmga aylanadi,
#                                           tugma/reaksiya ulanadi;
#   [⏩ Tugmalarsiz to'liq albom chiqsin] — 10 tagacha to'liq albom
#                                           tugma/reaksiyasiz chiqadi.
def _album_items_of(context) -> list:
    """user_data'dagi albom tarkibini (file_id JSON ro'yxati) qaytaradi.

    Albom bo'lmagan (yakka media/matn) yoki JSON buzilgan bo'lsa — bo'sh ro'yxat.
    """
    file_id = context.user_data.get("file_id")
    if not file_id:
        return []
    try:
        items = json.loads(file_id) if isinstance(file_id, str) else file_id
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return items if isinstance(items, list) else []


def _is_multi_album(context) -> bool:
    """Post bir nechta faylli ALBOMmi (tugma/reaksiya ulab bo'lmaydigan holat)."""
    return context.user_data.get("post_type") == "album" and len(_album_items_of(context)) > 1


def _strip_unsupported_album_options(context) -> None:
    """Albom post uchun sendMediaGroup qo'llab-quvvatlamaydigan opsiyalarni tozalaydi.

    Albom postida URL tugma (``btn_text``/``btn_url``) va reaksiya tugmalari
    (``enable_reactions``/``reaction_emojis``) hech qachon DB'ga yozilmaydi —
    aks holda kanalda albom ortidan "🔗" xizmat xabari chiqib qolardi.
    Yakka media/matn postlariga ta'siri YO'Q (o'zgarishsiz qaytadi).
    """
    if not _is_multi_album(context):
        return
    ud = context.user_data
    ud["btn_text"] = None
    ud["btn_url"] = None
    ud["enable_reactions"] = False
    ud["reaction_emojis"] = []
    ud["selected_reactions"] = []


def _album_choice_keyboard(lang="uz") -> InlineKeyboardMarkup:
    """Ogohlantirish ostidagi 2 ta tanlov tugmasi (inline)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(get_text("np_album_choice_first_photo", lang),
                              callback_data="album_choice:first_photo")],
        [InlineKeyboardButton(get_text("np_album_choice_full", lang),
                              callback_data="album_choice:full_album")],
    ])


async def _show_album_warning(msg, context, stage: str):
    """Albom + tugma/reaksiya cheklovi ogohlantirishini ko'rsatadi (uz/ru).

    ``stage`` — ogohlantirish qaysi bosqichda chiqqani (``"button"`` yoki
    ``"reactions"``): foydalanuvchi [🖼 1-rasm] ni tanlasa, aynan shu
    bosqichdan davom ettiriladi. Konversatsiya holati O'ZGARMAYDI — tanlov
    callback'lari joriy holatda ro'yxatdan o'tgan.
    """
    lang = get_lang(context)
    context.user_data["_album_warning_stage"] = stage
    await msg.reply_text(
        get_text("np_album_warning", lang),
        reply_markup=_album_choice_keyboard(lang),
        parse_mode="HTML",
    )


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

    ⚠️ Oldingi bosqichning pastki reply-klaviaturasi ("⏭ O'tkazib yuborish"
    tugmasi) Telegram'da NAVBATDA qoladi va GET_REACTIONS holatida bosilsa
    "Kutilmagan xatolik" berardi. Shuning uchun bu yerda ReplyKeyboardRemove
    bilan eski klaviatura olib tashlanadi — foydalanuvchi faqat inline
    reaksiya tugmalarini ko'radi.

    🖼 ALBOM: reaksiya tugmalari ham ``inline_keyboard`` — albomga ulanmaydi.
    Bir nechta faylli albom bo'lsa reaksiya klaviaturasi O'RNIGA ogohlantirish
    + 2 ta tanlov chiqadi (holat GET_REACTIONS da saqlanadi).
    """
    lang = get_lang(context)
    if _is_multi_album(context):
        await _show_album_warning(msg, context, "reactions")
        return GET_REACTIONS
    selected = context.user_data.setdefault("selected_reactions", [])
    await msg.reply_text(
        get_text("np_reactions_ask", lang),
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML"
    )
    await msg.reply_text(
        get_text("np_reactions_use_inline", lang),
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

    Tanlangan emojilar FAQAT ``reaction_emojis`` / ``enable_reactions``
    maydonlariga yoziladi — ``content`` (post matni/caption) o'zgarmaydi.

    🖼 ALBOM: reaksiya tugmalari (inline_keyboard) albomga ulanmaydi —
    albom postida reaksiyalar hech qachon saqlanmaydi (qayta himoya).
    """
    lang = get_lang(context)
    if _is_multi_album(context):
        selected_emojis = []
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
    """Confirmation (post preview) oynasi — SANA/VAQT ham foydalanuvchi tilida.

    Avval bu yerda ``strftime("%Y-%m-%d %H:%M")`` va hafta kunlari uchun
    ``WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS`` ishlatilardi —
    ya'ni EN foydalanuvchi hafta kunini O'ZBEKCHA ("Juma") deb o'qirdi va
    sana formati umuman tilga bog'liq emasdi. Endi yagona manba:
    :mod:`utils.date_format` (har tilga o'zining sana tartibi va oy/hafta
    kunlari nomlari bilan).
    """
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
        when_text = get_text("np_confirm_time_daily", lang,
                             time=format_time(recurrence_time_str, lang))
    elif recurrence_type == "weekly" and recurrence_time_str:
        when_text = get_text("np_confirm_time_weekly", lang,
                             day=weekday_label(recurrence_day, lang),
                             time=format_time(recurrence_time_str, lang))
    elif post_time:
        when_text = get_text("np_confirm_time_single", lang,
                             time=format_datetime(post_time, lang))
    else:
        when_text = get_text("np_confirm_time_none", lang)

    type_labels = {
        "text": "np_type_text", "photo": "np_type_photo", "video": "np_type_video",
        "document": "np_type_document", "audio": "np_type_audio",
        "voice": "np_type_voice", "sticker": "np_type_sticker",
        "album": "np_type_album", "animation": "np_type_animation",
    }
    type_text = get_text(type_labels.get(post_type, "np_type_unknown"), lang)

    # 🖼 ALBOM: preview'da nechta fayl borligi aniq ko'rsatiladi
    # ("🖼 Albom: 6 ta rasm") — barcha fayllar saqlangan va scheduler
    # send_media_group orqali to'liq yuboradi.
    if post_type == "album":
        try:
            items = json.loads(context.user_data.get("file_id") or "[]")
            if isinstance(items, list) and items:
                type_text = _build_album_summary(items, lang)
        except (TypeError, ValueError, json.JSONDecodeError):
            pass

    # 📝 To'liq matn: 300 belgida UZIB QOLINMAYDI. Telegram chegarasi
    # (matn 4096 / caption 1024) doirasida to'liq ko'rsatiladi; undan uzun
    # bo'lsa qancha qismi chiqishi aniq eslatma bilan aytiladi.
    content_preview = ""
    if content:
        caption_media = post_type in _CONFIRM_MEDIA_TYPES or post_type == "album"
        limit = 3600 if post_type == "text" else 900
        if len(content) <= limit:
            shown = content
            truncate_note = ""
        else:
            shown = content[:limit].rstrip() + "…"
            truncate_note = "\n" + get_text(
                "np_confirm_content_truncated", lang,
                total=len(content), limit=(1024 if caption_media else 4096),
            )
        content_preview = (
            "\n\n" + get_text("np_confirm_content", lang, content=safe_html(shown))
            + truncate_note
        )

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


def is_sticker_message(msg) -> bool:
    """Xabar stiker ekanini aniqlaydi (oddiy, animatsion yoki video stiker).

    Post tayyorlash bosqichida stikerlar hech qachon post bo'lolmaydi —
    ular kanalga caption/tugma bilan chiqmaydi va Telegram ularni albomga
    ham qo'shmaydi. Shu sababli stiker alohida, ANIQ xabar bilan rad etiladi.
    """
    return bool(getattr(msg, "sticker", None))


def classify_post_content(msg) -> str:
    """Post kontenti sifatida kelgan xabarni tasniflaydi.

    Qaytaradi:
      * ``"sticker"``     — stiker (alohida ogohlantirish: ``np_sticker_not_allowed``);
      * ``"unsupported"`` — voice/video_note yoki media ham, matn ham bo'lmagan
        xabar (kontakt, joylashuv, o'yincha, poll...) — ``np_media_not_allowed``;
      * ``"ok"``          — matn, rasm, video, hujjat, audio yoki GIF (post bo'ladi).
    """
    if is_sticker_message(msg):
        return "sticker"
    item0 = _media_item_from_message(msg)
    if item0 is not None and item0["type"] in ("sticker", "voice", "video_note"):
        return "unsupported"
    if getattr(msg, "video_note", None):
        return "unsupported"
    if item0 is None and not getattr(msg, "photo", None) \
            and not getattr(msg, "text", None) and not (getattr(msg, "caption", None) or ""):
        return "unsupported"
    return "ok"


async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    user_id = update.effective_user.id
    lang = get_lang(context)

    # 🚫 Stiker va qo'llab-quvvatlanmaydigan media — post sifatida qabul
    # qilinmaydi. Bot JIM QOLMASLIGI uchun foydalanuvchiga o'z tilida (uz/ru)
    # aniq xabar yuborib, GET_CONTENT holatida qolamiz (post yaratish davom etadi):
    #   • stiker  → "Kechirasiz, stikerlar post sifatida qabul qilinmaydi..."
    #   • voice / video_note / kontakt / joylashuv / o'yincha → umumiy xabar.
    kind = classify_post_content(msg)
    if kind == "sticker":
        await msg.reply_text(
            get_text("np_sticker_not_allowed", lang),
            parse_mode="HTML",
        )
        return GET_CONTENT
    if kind == "unsupported":
        await msg.reply_text(
            get_text("np_media_not_allowed", lang),
            parse_mode="HTML",
        )
        return GET_CONTENT

    _purge_stale_albums()

    # 1) Yakunlangan (collector tugagan) albom kutilmoqda:
    #    foydalanuvchi yuborgan KEYINGI matn — tugma so'rovining javobi.
    #    context.user_data HECH NARSA yo'qotilmaydi, oqim xuddi inline
    #    callback bosilgandek davom etadi.
    if context.user_data.get("_album_ready"):
        incoming_media = msg.media_group_id or _media_item_from_message(msg)
        if not incoming_media:
            return await btn_title_received(update, context)
        # Media keldi — foydalanuvchi kontentni almashtirmoqchi;
        # eski albom holati tozalanadi va yangi media quyida qo'llanadi.
        context.user_data.pop("_album_ready", None)

    # 2) Hali yig'ilayotgan albom bor va foydalanuvchi matn yubordi —
    #    kutishsiz yig'ishni yakunlab, matnni tugma sarlavhasi sifatida qabul qilamiz.
    incoming_is_media = bool(msg.media_group_id or _media_item_from_message(msg))
    if not incoming_is_media:
        active = _active_user_album_keys(user_id)
        if active:
            _finalize_album_buffer(active[-1], cancel_task=True)
            return await btn_title_received(update, context)

    # 3) ALBOM (media_group): barcha qismlar bitta buferga yig'iladi.
    if msg.media_group_id:
        item = _media_item_from_message(msg)
        if not item or item["type"] in ("voice", "sticker"):
            return GET_CONTENT

        key = (user_id, msg.media_group_id)
        # Aynan shu foydalanuvchining BOSHQA (eski) albomi hali yig'ilmoqda —
        # uni darhol yakunlab, yangi albomni boshidan to'playmiz.
        for old_key in _active_user_album_keys(user_id):
            if old_key != key:
                _cancel_album_buffer(old_key)
        # Albom yakunlanishi kutilmagan paytda yangi albom boshlasa —
        # eski "_album_ready" holati yangi yig'ish davomida oqimni buzmasin.
        context.user_data.pop("_album_ready", None)

        buf = _ALBUM_BUFFERS.get(key)
        if not buf:
            buf = {
                "items": [],
                "task": None,
                "user_data": context.user_data,
                "bot": context.bot if getattr(context, "bot", None) is not None else None,
                "chat_id": msg.chat_id,
                "lang": lang,
                "ts": time.time(),
                "done": False,
            }
            _ALBUM_BUFFERS[key] = buf
            # Arka fondagi collector — handler bloklanmaydi, shuning uchun
            # per-user lock albom qismlarini yig'ishga to'sqinlik qilmaydi.
            buf["task"] = asyncio.get_running_loop().create_task(
                _album_collector(key, buf["bot"], buf["chat_id"], buf["lang"], buf["user_data"])
            )
        if len(buf["items"]) < _ALBUM_MAX_ITEMS:
            buf["items"].append(item)
        buf["ts"] = time.time()
        return GET_CONTENT

    item = _media_item_from_message(msg)
    if item:
        _apply_single_media(context, item)
    else:
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["content"] = msg.text or ""

    return await _ask_button_prompt(msg, lang)

async def skip_url_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'⏩ O'tkazib yuborish' — URL tugma bosqichini o'tkazib yuborish.

    GET_BTN_TITLE / GET_BTN_URL holatlarida Ishlatiladi: tugma yo'qligini
    belgilaydi va xuddi inline callback bosilgandek reaksiya bosqichiga o'tadi.
    """
    context.user_data["btn_text"] = None
    context.user_data["btn_url"] = None
    return await _ask_reactions_step(update.message, context)


async def skip_reactions_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'⏩ O'tkazib yuborish' — reaksiya bosqichini o'tkazib yuborish.

    GET_REACTIONS holatida ishlatiladi: reaksiyalarsiz avto-o'chirish
    bosqichiga xavfsiz (crash'siz) o'tadi.
    """
    context.user_data["selected_reactions"] = []
    return await _proceed_after_reactions(update.message, context, [])


async def btn_title_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()

    # 🖼 ALBOM + tugma: sendMediaGroup'ga inline_keyboard ulab bo'lmaydi.
    # Albom yuborilgan bo'lsa — tugma sarlavhasi QABUL QILINMAYDI, o'rniga
    # xushmuomala ogohlantirish + 2 ta tanlov chiqadi (holat GET_BTN_TITLE da).
    # "⏩ O'tkazib yuborish" — reaksiya bosqichiga o'tadi (u yerda ham albom
    # bo'lsa ogohlantirish chiqadi) — foydalanuvchi ixtiyori xohishiga
    # to'g'ri keladi (tugmasiz davom etish = to'liq albom).
    if _is_multi_album(context) and not is_skip_button_text(text):
        await _show_album_warning(update.message, context, "button")
        return GET_BTN_TITLE

    # ✨ AI Yordamchi tugmasi — uchala tilda ham ishlaydi
    if is_menu_text(text, "np_ai_assistant"):
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
    if is_skip_button_text(text):
        context.user_data["btn_text"], context.user_data["btn_url"] = None, None
        return await _ask_reactions_step(update.message, context)

    # "🔗 URL tugma qo'shish" — bir qatorli tezkor formatga yo'naltirish
    if is_menu_text(text, "np_url_add"):
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
    if is_skip_button_text(text) or is_menu_text(text, "np_url_add"):
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

async def handle_reaction_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """GET_REACTIONS (reaksiya tanlash) bosqichida STIKER uchun alohida handler.

    Foydalanuvchi reaksiya tanlamoqda stiker yuborsa:
      1. Stikerning emojisi (``update.message.sticker.emoji``) ajratib olinadi
         va ``normalize_custom_reaction_emojis`` orqali normalizatsiya qilinadi.
      2. Emoji postning reaksiyalari ro'yxatiga
         (``user_data["selected_reactions"]``) takrorlanishsiz qo'shiladi.
      3. Tasdiq xabari (``np_reactions_selected``) chiqadi va inline toggle
         klaviaturada aynan o'sha emoji TANLANGAN (✅) holatda ko'rsatiladi.
      4. Post yaratish jarayoni uzilmaydi — holat GET_REACTIONS da qoladi
         (global "Kechirasiz, men bu xabarni tushunmadim" fallback'iga
         tushib ketishning oldi olinadi).

    MUHIM: reaksiya emojilari HECH QACHON post matni/caption'iga
    (``user_data["content"]``) qo'shilmaydi — ular faqat
    ``reaction_emojis`` maydonida saqlanadi va kanal postiga pastidagi
    INLINE TUGMA sifatida chiqadi (``scheduler.build_reaction_buttons``).

    Agar stikerning emojisi bo'lmasa (kamdan-kam holat) — jarayonni bekor
    qilmay, xushmuomala tushuntirish (``np_reactions_use_inline``) beriladi
    va GET_REACTIONS holati saqlanadi.
    """
    lang = get_lang(context)
    msg = update.message
    sticker = getattr(msg, "sticker", None)
    emoji = getattr(sticker, "emoji", None) if sticker is not None else None
    typed = normalize_custom_reaction_emojis(emoji) if emoji else []

    if typed:
        selected = context.user_data.setdefault("selected_reactions", [])
        existing_keys = {strip_variation_selector(e) for e in selected}
        for e in typed:
            if strip_variation_selector(e) not in existing_keys:
                selected.append(e)
                existing_keys.add(strip_variation_selector(e))
        # Tasdiq xabari + inline klaviaturada tanlangan emojilar ✅ bilan
        # ko'rsatiladi. ``content`` (post matni/caption) O'ZGARMAYDI.
        await msg.reply_text(
            get_text("np_reactions_selected", lang, emojis=" ".join(selected)),
            reply_markup=get_reaction_toggle_keyboard(selected, lang),
            parse_mode="HTML",
        )
        return GET_REACTIONS

    # Emojisi bo'lmagan (kamdan-kam) stiker — xushmuomala tushuntirish,
    # mavjud tanlov saqlanadi va jarayon davom etadi.
    await msg.reply_text(
        get_text("np_reactions_use_inline", lang),
        reply_markup=get_reaction_toggle_keyboard(
            context.user_data.get("selected_reactions", []), lang),
        parse_mode="HTML",
    )
    return GET_REACTIONS


async def reactions_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """GET_REACTIONS uchun zaxira handler (asosiy yo'l — inline toggle).

    - Emoji matn sifatida yuborilsa (masalan "👍 ❤️ 🔥") — tanlovga qo'shiladi
      va klaviatura yangilanadi.
    - Stiker yuborilsa — alohida ``handle_reaction_sticker`` handler orqali
      uning emojisi (``message.sticker.emoji``) reaksiya sifatida tanlovga
      qo'shiladi (fayl emas, aynan stiker emojisi).
    - "reaksiyasiz/yo'q/skip" — reaksiyasiz davom etiladi.
    - Boshqa matn — inline tugmalarni ishlatish eslatiladi.
    """
    lang = get_lang(context)
    msg = update.message
    text = msg.text

    # 🚀 "⏩ O'tkazib yuborish" / "⏩ Пропустить" / "⏭ ..." — foydalanuvchi
    # pastki reply-klaviaturani bosganida ham xuddi inline "⏭ Reaksiyasiz
    # o'tish" kabi xavfsiz davom etamiz (crash yo'q, user_data yo'qolmaydi).
    if is_skip_button_text(text):
        # ALBOM uchun bu ham to'g'ri yo'l: reaksiyasiz davom etish =
        # tugmalarsiz to'liq albom (reaksiya albomga ulanmaydi).
        context.user_data["selected_reactions"] = []
        return await _proceed_after_reactions(msg, context, [])

    # 🖼 ALBOM: reaksiya tugmalari (inline_keyboard) albomga ulanmaydi —
    # ogohlantirish + 2 ta tanlov chiqadi (holat GET_REACTIONS da saqlanadi).
    if _is_multi_album(context):
        await _show_album_warning(msg, context, "reactions")
        return GET_REACTIONS

    # 🎯 STIKER: stiker yuborilganda global "tushunmadim" fallback'iga tushib
    # ketmasdan, alohida ``handle_reaction_sticker`` handler uni qabul qiladi
    # (GET_REACTIONS holatida filters.Sticker.ALL bilan ro'yxatdan o'tgan).
    if getattr(msg, "sticker", None) is not None:
        return await handle_reaction_sticker(update, context)

    parsed = parse_reactions_input(text)

    # "Reaksiyasiz" tugma/so'zlari UCHALA tilda ham reaksiyasiz davom ettiradi.
    no_reaction_words = (
        # o'zbekcha
        "reaksiyasiz", "yo'q", "yoq", "o'tkazib yuborish", "otkazib yuborish",
        # ruscha
        "без реакций", "нет", "пропустить", "отключить", "не надо",
        # inglizcha
        "no reactions", "none", "no", "skip", "without reactions",
        "continue without reactions", "disable",
    )
    if parsed is False or is_menu_text(text, "np_no_reactions") \
            or (text or "").strip().lower() in no_reaction_words:
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
    await query.answer()
    context.user_data["selected_reactions"] = []
    return await _proceed_after_reactions(query.message, context, [])


async def album_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Albom cheklovi tanlovi: [🖼 1-rasm qolsin + tugma] / [⏩ Tugmalarsiz to'liq albom].

    Telegram Bot API qoidasi: ``sendMediaGroup`` ga ``inline_keyboard``
    (URL tugma yoki reaksiya) ulab bo'lmaydi. Foydalanuvchi tanlovi:

    - ``first_photo`` — albomning BIRINCHI rasmi qoladi, post yakka media'ga
      aylanadi (caption o'zgarishsiz) va foydalanuvchi ogohlantirish chiqqan
      bosqichdan (tugma yoki reaksiya) davom etadi — endi tugma/reaksiya
      qo'shish mumkin.
    - ``full_album`` — tugma/reaksiya olib tashlanadi, to'liq albom
      (10 tagacha fayl) avto-o'chirish bosqichiga o'tadi.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    ud = context.user_data
    data = query.data or ""
    action = data.split(":", 1)[1] if ":" in data else ""
    items = _album_items_of(context)
    is_album = _is_multi_album(context)

    if action == "first_photo" and is_album and items and isinstance(items[0], dict):
        stage = ud.pop("_album_warning_stage", "button") or "button"
        first = items[0]
        # Post yakka media'ga aylanadi — content (caption) o'zgarishsiz qoladi.
        ud["post_type"] = first.get("type") or "photo"
        ud["file_id"] = first.get("file_id")
        ud.pop("_album_count", None)
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("np_album_first_photo_done", lang),
            parse_mode="HTML",
        )
        if stage == "reactions":
            return await _ask_reactions_step(query.message, context)
        return await _ask_button_prompt(query.message, lang)

    if action == "full_album" and is_album:
        count = len(items) or int(ud.get("_album_count") or 0)
        ud.pop("_album_warning_stage", None)
        ud.pop("_album_count", None)
        # Albom to'liq qoladi — lekin sendMediaGroup cheklovi tufayli
        # tugma/reaksiya opsiyalari olib tashlanadi.
        ud["btn_text"] = None
        ud["btn_url"] = None
        ud["selected_reactions"] = []
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await query.message.reply_text(
            get_text("np_album_full_done", lang, count=count),
            parse_mode="HTML",
        )
        return await _proceed_after_reactions(query.message, context, [])

    # Eskirgan/ikkilangan bosish (albom allaqachon hal qilingan) — o'zgarish
    # yo'q, faqat tugmalar yashiriladi.
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return GET_BTN_TITLE

async def auto_delete_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    # Avval TUGMA matnlari uchala tilda solishtiriladi ("❌ O'chirilmasin
    # (Doimiy)" / "❌ Не удалять (постоянно)" / "❌ Never delete (Permanent)"),
    # so'ng eski raqam-guruch mantiqi (12/24/48/72) sinab ko'riladi.
    if is_menu_text(text, "np_del_never"):
        hours = 0
    elif is_menu_text(text, "np_del_12h"):
        hours = 12
    elif is_menu_text(text, "np_del_24h"):
        hours = 24
    elif is_menu_text(text, "np_del_48h"):
        hours = 48
    elif is_menu_text(text, "np_del_72h"):
        hours = 72
    elif "12" in text:
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
    example = schedule_time_example(now)
    await update.message.reply_text(
        get_text("np_time_ask", lang, example=example),
        reply_markup=get_time_keyboard(lang),
        parse_mode="HTML"
    )
    return GET_TIME


def _content_for_db(content, reaction_emojis):
    """DB'ga yoziladigan matn: reaksiya glyph'lari caption'ga qo'shilmaydi."""
    return strip_leading_reaction_glyphs(content, reaction_emojis)

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    now = datetime.now(tashkent_tz)

    # Tayyor tugmalar UCHALA tilda taniyadi (MENU_TEXTS["np_time_*"]) —
    # klaviatura EN bo'lsa ham "⚡ 5 minutes" / "🔁 Daily" ishlaydi.
    if is_menu_text(text, "np_time_daily"):
        await update.message.reply_text(
            get_text("np_daily_time_ask", lang), reply_markup=get_cancel_keyboard(lang), parse_mode="HTML")
        return DAILY_TIME
    elif is_menu_text(text, "np_time_weekly"):
        await update.message.reply_text(
            get_text("np_weekday_ask", lang), reply_markup=get_weekday_keyboard(lang), parse_mode="HTML")
        return RECUR_DAY

    # Tayyor tugmalar (5 daqiqa / 15 daqiqa / 1 soat) — Toshkent vaqtida.
    if is_menu_text(text, "np_time_5m"):
        post_time, reason = now + timedelta(minutes=5), ""
    elif is_menu_text(text, "np_time_15m"):
        post_time, reason = now + timedelta(minutes=15), ""
    elif is_menu_text(text, "np_time_1h"):
        post_time, reason = now + timedelta(hours=1), ""
    else:
        # Qo'lda kiritilgan vaqt: parser HECH QACHON exception tashlamaydi —
        # noto'g'ri format ham, noto'g'ri sonlar ham (masalan "25:99") xato
        # sababi sifatida qaytadi va foydalanuvchiga o'z tilida tushuntiriladi.
        post_time, reason = parse_schedule_input(text, now)

    if post_time is None:
        example = schedule_time_example(now)
        key = "np_time_future" if reason == SCHEDULE_ERR_PAST else "np_time_format_error"
        await update.message.reply_text(
            get_text(key, lang, example=example, now=format_datetime(now, lang)),
            parse_mode="HTML",
        )
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
    # `text` None bo'lishi mumkin (rasm/stiker yuborilsa) — .strip() qulatmasin.
    parsed = parse_daily_time_input(getattr(update.message, "text", None))
    if parsed is None:
        await update.message.reply_text(
            get_text("np_daily_time_format", lang), parse_mode="HTML")
        return DAILY_TIME
    hh, mm = parsed

    now = datetime.now(tashkent_tz)
    first_run = tashkent_tz.localize(
        datetime(now.year, now.month, now.day, hh, mm)
    )
    if first_run <= now:
        first_run = tashkent_tz.normalize(first_run + timedelta(days=1))

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
    # Hafta kuni ham uchala tilda qabul qilinadi: "Juma"/"Пятница"/"Friday".
    day_idx = weekday_index(text)
    if day_idx is None:
        await update.message.reply_text(get_text("np_weekday_invalid", lang))
        return RECUR_DAY

    context.user_data["rec_day"] = day_idx
    await update.message.reply_text(
        get_text("np_recur_time_ask", lang, day=weekday_label(day_idx, lang)),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return RECUR_TIME

async def recur_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    parsed = parse_daily_time_input(getattr(update.message, "text", None))
    if parsed is None:
        await update.message.reply_text(
            get_text("np_recur_time_format", lang), parse_mode="HTML")
        return RECUR_TIME
    hh, mm = parsed

    now = datetime.now(tashkent_tz)
    target_day = context.user_data.get("rec_day")
    if target_day is None:
        await update.message.reply_text(
            get_text("np_weekday_invalid", lang), parse_mode="HTML")
        return RECUR_DAY
    days_ahead = (int(target_day) - now.weekday() + 7) % 7
    # Toshkent zonasida qayta localize qilinadi (UTC-ofset to'g'ri hisoblansin).
    first_run = tashkent_tz.normalize(
        tashkent_tz.localize(datetime(now.year, now.month, now.day, hh, mm))
        + timedelta(days=days_ahead)
    )
    if first_run <= now:
        first_run = tashkent_tz.normalize(first_run + timedelta(days=7))

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

    if is_menu_text(text, "np_dur_1w"):
        # Yangi: post har kuni roppa-rosa 1 hafta (7 kun) davomida chiqadi
        end_date = now + timedelta(days=7)
    elif is_menu_text(text, "np_dur_1m"):
        end_date = now + timedelta(days=30)
    elif is_menu_text(text, "np_dur_3m"):
        end_date = now + timedelta(days=90)
    elif is_menu_text(text, "np_dur_6m"):
        end_date = now + timedelta(days=180)
    elif is_menu_text(text, "np_dur_1y"):
        end_date = now + timedelta(days=365)
    elif is_menu_text(text, "np_dur_inf"):
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
    await query.answer()
    data = query.data
    action = data.split(":", 1)[1] if ":" in data else ""
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    lang = get_lang(context)

    if action == "cancel":
        clear_fsm_data(context)
        cancel_album_collections(user_id)
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

        # 🖼 ALBOM: sendMediaGroup'ga inline_keyboard ulanmaydi — albom uchun
        # tugma/reaksiya opsiyalari DB'ga yozilmaydi.
        _strip_unsupported_album_options(context)
        post_type = context.user_data.get("post_type")
        reaction_emojis = context.user_data.get("reaction_emojis")
        content = _content_for_db(context.user_data.get("content"), reaction_emojis)
        file_id = context.user_data.get("file_id")
        btn_text = context.user_data.get("btn_text")
        btn_url = context.user_data.get("btn_url")
        enable_reactions = context.user_data.get("enable_reactions", False)
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
            time_str = format_time(slot_dt, lang)
            ad_line = await get_auto_ad_injection_async(user_id)
            # db.find_next_queue_slot "Bugun"/"Ertaga" qaytaradi — bu yorliq
            # har bir tilga (uz/ru/en) o'giramiz.
            label_i18n = _queue_slot_label(label, lang)
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
    # 🖼 ALBOM: sendMediaGroup'ga inline_keyboard ulanmaydi — albom uchun
    # tugma/reaksiya opsiyalari DB'ga yozilmaydi.
    _strip_unsupported_album_options(context)
    post_type = context.user_data.get("post_type")
    reaction_emojis = context.user_data.get("reaction_emojis")
    content = _content_for_db(context.user_data.get("content"), reaction_emojis)
    file_id = context.user_data.get("file_id")
    btn_text = context.user_data.get("btn_text")
    btn_url = context.user_data.get("btn_url")
    enable_reactions = context.user_data.get("enable_reactions", False)
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
            when_text = get_text("np_scheduled_when_daily", lang,
                                 time=format_time(recurrence_time_str, lang))
        elif recurrence_type == "weekly" and recurrence_time_str:
            when_text = get_text("np_scheduled_when_weekly", lang,
                                 day=weekday_label(recurrence_day, lang),
                                 time=format_time(recurrence_time_str, lang))
        else:
            when_text = get_text("np_scheduled_when_single", lang,
                                 time=format_datetime(post_time_tz, lang))
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
    cancel_album_collections(user_id)
    clear_fsm_data(context)
    return ConversationHandler.END


async def edit_confirm_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tahrirlash sub-menyusi."""
    query = update.callback_query
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
        example = schedule_time_example(now)
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
    # 🚫 Tasdiqlash/tahrirlash bosqichida stiker kelsa — jim qolmaymiz,
    # foydalanuvchiga o'z tilida aniq xabar beramiz va kartani saqlab qolamiz.
    if is_sticker_message(update.message):
        await update.message.reply_text(
            get_text("np_sticker_not_allowed", lang), parse_mode="HTML",
        )
        return CONFIRM_POST
    text = (update.message.text or "").strip()

    if is_menu_text(text, "np_back_confirm", "back", "main_menu"):
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    edit_channels_map = context.user_data.get("edit_channels_map")
    if edit_channels_map:
        if is_menu_text(text, "np_all_channels"):
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
    if is_menu_text(text, "np_time_5m"):
        new_time = now + timedelta(minutes=5)
    elif is_menu_text(text, "np_time_15m"):
        new_time = now + timedelta(minutes=15)
    elif is_menu_text(text, "np_time_1h"):
        new_time = now + timedelta(hours=1)
    else:
        # Crash-proof parser: bu bosqichda matn tugma/URL ham bo'lishi mumkin,
        # shuning uchun tanilmasa jim o'tib ketamiz (quyidagi tarmoqlar ishlaydi).
        new_time, _reason = parse_schedule_input(text, now)

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

    if text.lower() in ("yo'q", "yoq", "none", "-", "o'chir", "нет", "удалить",
                         "remove", "delete", "no", "no button", "без кнопки"):
        context.user_data["btn_text"] = None
        context.user_data["btn_url"] = None
        await _show_confirmation(update.message, context)
        return CONFIRM_POST

    # Bu bosqichda MATN — post matni sifatida qabul qilinadi, lekin menyuga
    # tegishli tugmalar (har qanday tilda) EMAS.
    if text and not is_menu_text(text, "np_time_daily", "np_time_weekly",
                                 "back", "main_menu", "np_back_confirm"):
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
    # AI javob kelgunicha chatda uzluksiz "typing..." ko'rsatamiz
    async with keep_typing(context.bot, query.message.chat_id):
        # 🌐 AI formatlash foydalanuvchi tilida (uz/ru/en).
        result = await format_post_text(content, action, lang=lang)

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
    user_id = update.effective_user.id
    if check_callback_throttle(user_id):
        try:
            await update.callback_query.answer(
                text=get_text("np_callback_wait", get_lang(context)),
                show_alert=False
        )
        except Exception:
            pass
        return
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
        # AI javob kelgunicha chatda uzluksiz "typing..." ko'rsatamiz
        async with keep_typing(context.bot, query.message.chat_id):
            result = await format_post_text(content, last_action, lang=lang)

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
