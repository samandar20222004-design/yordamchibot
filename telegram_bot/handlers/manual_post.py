"""✍️ ODDIY POST (AI'SIZ) — tayyor kontentni to'g'ridan-to'g'ri chiqarish.

Birlashtirilgan kontent menyusidagi birinchi yo'nalish. QAT'IY QOIDA: bu
oqimda AI UMUMAN ishtirok etmaydi — foydalanuvchi tayyor matn, rasm yoki
video yuboradi va bot hech qanday uslub/generatsiya savollarini bermasdan
DARHOL preview chiqaradi. Preview ostida universal boshqaruv paneli
(2-qadam UI/UX polish'dan keyin — 4 qatorli, boyitilgan)::

    [🚀 Hozir yuborish]        [📅 Vaqtni belgilash]
    [❤️ Reaksiyalar]           [🔗 Havolali tugma]
    [🗑 24 soatlik e'lon]      [🔄 Takroriy e'lon]
    [✏️ Tahrirlash]            [❌ Bekor qilish]

Amallar (barchasi mavjud, sinovdan o'tgan infratuzilmaga tayanadi):
  * 🚀 Hozir yuborish — post tanlangan kanalga darhol chiqadi
    (``db.add_post`` + scheduler zanjiri, ``scheduled_time=now``);
  * 📅 Vaqtni belgilash — oddiy reja: belgilangan sana/vaqtda chiqadi
    (masalan: ``19:30``);
  * ❤️ Reaksiyalar — presetlar ([👍/👎], [🔥/❤️/👏]) yoki qo'lda
    kiritilgan emojilar post tagiga reaksiya TUGMALARI sifatida ulanadi
    (``enable_reactions`` + ``reaction_emojis`` → scheduler delivery);
  * 🔗 Havolali tugma — "Matn - https://..." formatida kiritiladi; FAQAT
    ``http://``, ``https://``, ``tg://`` protokollari ruxsat etiladi
    (``javascript:``, ``file:`` rad etiladi); tugma preview ostida
    HAQIQIY inline URL tugma sifatida ko'rinadi va kanalga ham chiqadi
    (``btn_text`` + ``btn_url`` → scheduler ``reply_markup``);
  * 🗑 24 soatlik e'lon — kanalga chiqadi va 24 soat o'tib AVTOMATIK
    o'chadi (``delete_after_hours=24``);
  * 🔄 Takroriy e'lon — har kuni bitta vaqtda qayta chiqadi
    (``recurrence_type='daily'`` — reklama/savdo kanallari uchun);
  * ✏️ Tahrirlash — yangi matn/rasm bilan preview yangilanadi;
  * ❌ Bekor qilish — hech narsa yuborilmaydi, asosiy menyu qaytadi.

Callback prefiksi ``mnp_`` (manual post) — Magic Post (``mp_``), Voice
(``vp_``), Image (``image_``), Post Score (``ps_``) va boshqa global
prefikslar bilan to'qnashmaydi. FSM holatlari 450–456 — mavjud holatlar
bilan konfliktsiz (430–442 magic/voice, 460+ post_score/calendar):
455 — qo'lda reaksiya kiritish, 456 — havolali tugma kiritish.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler

from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import (
    CB_MANUAL_24H,
    CB_MANUAL_CANCEL,
    CB_MANUAL_CHANNEL,
    CB_MANUAL_CH_SELECTOR,
    CB_MANUAL_DUP_AI,
    CB_MANUAL_DUP_FORCE,
    CB_MANUAL_EDIT,
    CB_MANUAL_FINISH,
    CB_MANUAL_NOW,
    CB_MANUAL_PANEL,
    CB_MANUAL_REACT,
    CB_MANUAL_REACT_BACK,
    CB_MANUAL_REACT_CUSTOM,
    CB_MANUAL_REACT_TOGGLE,
    CB_MANUAL_REPEAT,
    CB_MANUAL_TIME,
    CB_MANUAL_URL_BTN,
    CUSTOM_REACTION_MAX,
    build_reaction_button_rows,
    btn_label,
    get_duplicate_warning_keyboard,
    get_manual_channel_keyboard,
    get_manual_post_panel,
    get_manual_reaction_keyboard,
    is_emoji_token,
    manual_channel_from_callback,
    manual_reaction_from_callback,
    normalize_custom_reaction_emojis,
    strip_variation_selector,
)
from locales.translations import clear_fsm_data, get_lang
from translations import manual_post_t
from utils.date_format import format_datetime, format_time
from utils.helpers import (
    html_escape,
    parse_button_input,
    parse_daily_time_input,
    parse_schedule_input,
    validate_button_text,
    validate_button_url,
)
from utils.telegram_sanitizer import sanitize_html

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

# ============================================================
# FSM HOLATLARI (450–454 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
MANUAL_AWAIT_CONTENT = 450   # tayyor kontent (matn/rasm/video) kutilmoqda
MANUAL_PREVIEW = 451         # preview + universal boshqaruv paneli
MANUAL_CHANNEL_SELECT = 452  # kanal tanlanmoqda (inline tugmalar)
MANUAL_TIME_INPUT = 453      # 📅 vaqt yoki 🔄 takrorlanish vaqti kutilmoqda
MANUAL_EDIT_INPUT = 454      # ✏️ yangi kontent kutilmoqda
MANUAL_REACTION_CUSTOM = 455  # ➕ qo'lda kiritiladigan reaksiya emojilari
MANUAL_URL_INPUT = 456       # 🔗 havolali tugma (matn + URL) kutilmoqda

# Amal rejimi (kanal tanlanishi yoki vaqt kiritilishidan oldin tanlanadi).
MODE_NOW = "now"        # 🚀 Hozir yuborish
MODE_TIME = "time"      # 📅 Vaqtni belgilash
MODE_24H = "24h"        # 🗑 24 soatlik e'lon
MODE_REPEAT = "repeat"  # 🔄 Takroriy e'lon

#: user_data kalitlari (bir joyda — testlar va handlerlar uchun yagona manba).
from utils.delivery_options import DELIVERY_KEYS, delivery_labels, delivery_markup

UD_DELIVERY = "mnp_delivery"
UD_CONTENT = "mnp_content"
UD_POST_TYPE = "mnp_post_type"
UD_FILE_ID = "mnp_file_id"
UD_MEDIA_GROUP = "mnp_media_group"
UD_MODE = "mnp_mode"
UD_WHEN = "mnp_when"            # ISO datetime (rejalashtirish uchun)
UD_REPEAT_TIME = "mnp_repeat_time"  # "HH:MM" (takroriy e'lon uchun)
# 🔁 PHASE C — dublikat detektori holati (post chiqarilishidan oldin).
UD_DUP_FORCE = "mnp_dup_force"          # foydalanuvchi "Baribir chiqarish" bosdi
UD_DUP_CHANNEL_ID = "mnp_dup_channel"   # ogohlantirilgan kanal (id)
UD_DUP_CHANNEL_TITLE = "mnp_dup_title"  # ogohlantirilgan kanal (nomi)
# 2-QADAM UI/UX POLISH — reaksiyalar va havolali (URL) tugma holati.
UD_REACTIONS = "mnp_reactions"  # tanlangan reaksiya emojilari (list[str])
UD_URL_BTN_TEXT = "mnp_url_text"  # havolali tugma matni
UD_URL_BTN_URL = "mnp_url_url"    # havolali tugma URL'i (xavfsiz protokol)
# 📢 Kanal tanlash — target channel selector (1-vazifa)
UD_SELECTED_CHANNEL_ID = "mnp_ch_id"
UD_SELECTED_CHANNEL_TITLE = "mnp_ch_title"

#: Qabul qilinadigan media turlari → post_type.
_SUPPORTED_MEDIA = ("photo", "video", "animation", "document")


def _extract_media(msg):
    """Xabardan (file_id, post_type) ajratadi; media bo'lmasa (None, 'text')."""
    if getattr(msg, "photo", None):
        return msg.photo[-1].file_id, "photo"
    if getattr(msg, "video", None):
        return msg.video.file_id, "video"
    if getattr(msg, "animation", None):
        return msg.animation.file_id, "animation"
    if getattr(msg, "document", None):
        return msg.document.file_id, "document"
    return None, "text"


def _has_content(context) -> bool:
    """Preview uchun kontent saqlanganmi (sessiya eskirmaganmi)."""
    ud = context.user_data
    return bool(
        (ud.get(UD_CONTENT) or "").strip()
        or (ud.get(UD_FILE_ID) and ud.get(UD_POST_TYPE) in _SUPPORTED_MEDIA)
    )


def _clear_manual_state(context) -> None:
    """Oddiy post oqimi ma'lumotlarini tozalaydi (FSM kontekstidan tashqari)."""
    for key in (UD_CONTENT, UD_POST_TYPE, UD_FILE_ID, UD_MEDIA_GROUP, UD_MODE, UD_WHEN,
                UD_REPEAT_TIME, UD_DUP_FORCE, UD_DUP_CHANNEL_ID,
                UD_DUP_CHANNEL_TITLE, UD_REACTIONS, UD_URL_BTN_TEXT,
                UD_URL_BTN_URL, UD_DELIVERY, UD_SELECTED_CHANNEL_ID,
                UD_SELECTED_CHANNEL_TITLE):
        context.user_data.pop(key, None)


def _get_selected_channel(context):
    """Saqlangan tanlangan kanalni qaytaradi (id, title) yoki None."""
    ch_id = context.user_data.get(UD_SELECTED_CHANNEL_ID)
    ch_title = context.user_data.get(UD_SELECTED_CHANNEL_TITLE)
    if ch_id:
        return ch_id, ch_title or str(ch_id)
    return None


def _set_selected_channel(context, channel_id, channel_title):
    """Tanlangan kanalni saqlaydi."""
    context.user_data[UD_SELECTED_CHANNEL_ID] = str(channel_id)
    context.user_data[UD_SELECTED_CHANNEL_TITLE] = str(channel_title or channel_id)


# ============================================================
# SMART EMOJI VA SMART URL — YORDAMCHI FUNKSIYALAR (2-QISM BUGFIX)
# ============================================================
import re as _re

#: Smart emoji uchun maksimal son (topshiriq bo'yicha 5 tagacha).
SMART_EMOJI_MAX = 5

#: Smart URL uchun avtomatik tugma matnlari.
AUTO_BTN_TEXT_TME = "📢 Kanalga o'tish"
AUTO_BTN_TEXT_WEB = "🔗 Batafsil"


def _auto_button_text(url: str) -> str:
    """URL'ga qarab avtomatik tugma matnini tanlaydi.

    - t.me yoki tg:// bo'lsa → \"📢 Kanalga o'tish\"
    - boshqa veb-sayt bo'lsa → \"🔗 Batafsil\"
    """
    low = (url or "").lower()
    if "t.me" in low or low.startswith("tg://"):
        return AUTO_BTN_TEXT_TME
    return AUTO_BTN_TEXT_WEB


def _token_to_emojis(token: str) -> list:
    """Bitta token (masalan \"😎🔥\" yoki \"❤️\") ni alohida emojilarga bo'ladi.

    - ZWJ (\\u200d) bo'lsa butun tokenni bitta emoji deb saqlaydi (masalan 👨‍💻).
    - Variation Selector (\\ufe0f/\\ufe0e) va skin-tone modifier'lar (\\U0001f3fb-\\U0001f3ff)
      oldingi belgi bilan birga guruhlanadi.
    - Natijada faqat emoji tokenlari qaytadi.
    """
    if not token:
        return []
    # ZWJ ketma-ketligi — butunligicha bitta emoji (bo'lib tashlamaymiz)
    if "\u200d" in token:
        return [token] if is_emoji_token(token) else []
    emojis = []
    cur = ""
    for ch in token:
        if ch in ("\ufe0f", "\ufe0e"):
            # VS — oldingi belgiga yopishadi
            cur += ch
            continue
        # Skin-tone modifier'lar (1F3FB..1F3FF) — oldingi emoji bilan birga
        cp = ord(ch)
        if 0x1F3FB <= cp <= 0x1F3FF:
            cur += ch
            continue
        # Yangi belgi boshlandi — avvalgisini yopamiz
        if cur:
            if is_emoji_token(cur):
                emojis.append(cur)
            cur = ch
        else:
            cur = ch
    if cur and is_emoji_token(cur):
        emojis.append(cur)
    return emojis


def _smart_extract_emojis(text: str, max_count: int = SMART_EMOJI_MAX) -> list:
    """Matndan emojilarni ajratib oladi (maksimal ``max_count`` tagacha) — KIRITISH TARTIBI SAQLANADI.

    SMART EMOJI BUGFIX (2-qism):
      * Foydalanuvchi "😎" yoki "🔥 👍" kabi sof emoji yuborsa, xato berilmaydi.
      * Emoji(lar) ajratib olinib (maksimal 5 tagacha) saqlanadi.
      * Kiritish tartibi saqlanadi — masalan "🔥 👍" → ["🔥", "👍"], kanonik saralash emas.
      * Vergul, nuqta-vergul, | / kabi ajratgichlar bo'sh joyga almashtiriladi.
      * Har bir token alohida emojilarga bo'linadi (masalan "😎🔥" → ["😎", "🔥"]).
      * Takrorlar VS hisobga olinmasdan olib tashlanadi.
    """
    if not text:
        return []
    # To'g'ridan-to'g'ri kiritish tartibida ajratamiz (kanonik saralashsiz)
    raw = _re.split(r"[\s,;|/]+", str(text).strip())
    result = []
    seen = set()
    for token in raw:
        if not token:
            continue
        split_emojis = _token_to_emojis(token)
        if not split_emojis and is_emoji_token(token):
            split_emojis = [token]
        for emo in split_emojis:
            if not emo:
                continue
            key = strip_variation_selector(emo)
            if not key or key in seen:
                continue
            if not is_emoji_token(emo):
                continue
            seen.add(key)
            result.append(emo)
            if len(result) >= max_count:
                return result[:max_count]
    if not result:
        try:
            normalized = normalize_custom_reaction_emojis(text, max_count=max_count)
            if normalized:
                dedup = []
                seen2 = set()
                for e in normalized:
                    k = strip_variation_selector(e)
                    if k and k not in seen2:
                        seen2.add(k)
                        dedup.append(e)
                    if len(dedup) >= max_count:
                        break
                return dedup[:max_count]
        except Exception as _silent_exc:
            log_silent_failure("handlers.manual_post:_smart_extract_emojis", _silent_exc)
    return result[:max_count]




def _is_pure_emoji_text(text: str) -> bool:
    """Matn faqat emoji(lar) va ajratgichlardan iboratmi?

    Masalan: \"😎\" → True, \"🔥 👍\" → True, \"salom 😎\" → False.
    """
    if not text or not str(text).strip():
        return False
    emojis = _smart_extract_emojis(text, max_count=10)
    if not emojis:
        return False
    temp = str(text)
    for e in emojis:
        temp = temp.replace(e, "")
    # Variation selector'larni ham olib tashlaymiz
    temp = temp.replace("\ufe0f", "").replace("\ufe0e", "")
    # Qolgan ajratgichlar (bo'sh joy, vergul, nuqta-vergul, | /) ni tozalaymiz
    temp = _re.sub(r"[\s,;|/]+", "", temp)
    return temp == ""


def _smart_parse_url_button(raw_text: str):
    """Smart URL parser — \"Matn - Havola\" yoki faqat \"Havola\" formatlarini qo'llaydi.

    Qaytaradi: (btn_text, btn_url) yoki (None, None) agar noto'g'ri bo'lsa.

    Qoidalari:
      * Agar matnning o'zi yakka URL bo'lsa (http/https/tg) → avtomatik matn:
        t.me/tg:// → \"📢 Kanalga o'tish\", boshqa → \"🔗 Batafsil\"
      * Aks holda \"Matn - Havola\" (|, \" - \", \"—\") ajratgichlari orqali
      * Qo'shimcha fallback: oxirgi token URL bo'lsa, qolgan qismi matn sifatida
    """
    raw = (raw_text or "").strip()
    if not raw:
        return None, None

    # 1) Yakka URL holati — eng oddiy va keng tarqalgan xato manbasi
    ok_single, _ = validate_button_url(raw)
    if ok_single:
        return _auto_button_text(raw), raw

    # 2) Mavjud parser (|, \" - \", \"—\") orqali
    btn_text, btn_url = parse_button_input(raw)
    if btn_text and btn_url:
        ok_t, _ = validate_button_text(btn_text)
        ok_u, _ = validate_button_url(btn_url)
        if ok_t and ok_u:
            return btn_text, btn_url

    # 3) Fallback: oxirgi bo'shliqdan keyin URL bo'lsa, oldingi qismi matn
    #    Masalan: \"Batafsil https://t.me/kanal\" yoki \"Kanal -https://...\" kabi
    #    foydalanuvchi xatolariga chidamli bo'lish uchun
    #    Rasmiy format \"Matn - Havola\" bo'lsa ham, bo'shliq bilan yozilgan
    #    variantlarni ham qabul qilamiz
    parts = raw.rsplit(None, 1)
    if len(parts) == 2:
        potential_text, potential_url = parts
        # Oxiridagi \"-\", \"|\", \"—\" belgilarini tozalaymiz
        potential_text = potential_text.rstrip(" -|—").strip()
        ok_t, _ = validate_button_text(potential_text)
        ok_u, _ = validate_button_url(potential_url)
        if ok_t and ok_u and potential_text:
            return potential_text, potential_url

    return None, None


# ============================================================
# PREVIEW — postning o'zi (AI'siz, o'zgarishsiz) + universal panel
# ============================================================
def _manual_album_warning(context, lang: str) -> str:
    """Albomda tugma/reaksiya sozlanganda cheklov eslatmasi."""
    if not context.user_data.get(UD_MEDIA_GROUP):
        return ""
    # 5-vazifa: aniq ogohlantirish matni (uz/ru/en)
    return "\n\n" + manual_post_t("mp_album_warning", lang)


# ============================================================
# FSM INPUT FALLBACK (PHASE 1) — yumshoq bosqich eslatmasi
# ============================================================
def _stage_hint(lang: str) -> str:
    """💡 Bosqich eslatmasi — tugma bosish kutilganda (yumshoq ogohlantirish)."""
    try:
        return manual_post_t("mp_stage_hint", lang)
    except Exception:  # noqa: BLE001 — pragma: no cover, tarjima topilmasa
        return ("💡 Hozirgi bosqichda quyidagi tugmalardan birini "
                "tanlashingiz kerak:")


async def _reply_stage_hint(msg, lang: str) -> None:
    """💡 yumshoq ogohlantirishni yuboradi (xatoda oqim uzilmaydi)."""
    try:
        await msg.reply_text(_stage_hint(lang), parse_mode="HTML")
    except Exception:  # eslatma muhim emas — oqim davom etadi
        logger.debug("Bosqich eslatmasi yuborilmadi", exc_info=True)


async def _preview_soft_fallback(msg, context, lang: str) -> int:
    """💡 eslatma + joriy Preview menyusini qayta ko'rsatish.

    FSM holati (MANUAL_PREVIEW) BEKOR BO'LIB KETMAYDI: foydalanuvchi tugma
    bosish o'rniga adashib erkin matn yozsa yoki media tashlasa, bot quruq
    «qabul qilinmaydi» deb to'xtab qolmaydi — yumshoq ogohlantirish beradi
    va mavjud panelni qayta ko'rsatadi. Sessiya eskirgan bo'lsa (kontent
    yo'q) — eski xulq: muloyim xabar + asosiy menyu + END.
    """
    if not _has_content(context):
        await msg.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(
                (msg.from_user.id if getattr(msg, "from_user", None) else 0)
                in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        clear_fsm_data(context)
        _clear_manual_state(context)
        return ConversationHandler.END
    await _reply_stage_hint(msg, lang)
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


def _manual_reactions(context) -> list:
    """Saqlangan reaksiya emojilari (normal, takrorsiz ro'yxat)."""
    return normalize_custom_reaction_emojis(
        context.user_data.get(UD_REACTIONS) or [])


def _manual_url_button(context):
    """Saqlangan havolali tugma — ``(text, url)`` yoki ``None``."""
    text = str(context.user_data.get(UD_URL_BTN_TEXT) or "").strip()
    url = str(context.user_data.get(UD_URL_BTN_URL) or "").strip()
    if text and url:
        return text, url
    return None


def _manual_preview_markup(context, lang: str) -> InlineKeyboardMarkup:
    """Preview ostidagi to'liq markup: kanal tugmasi + URL + reaksiyalar + panel.

    Tartib: (0) 📢 Kanal: [name] (1-vazifa), (1) havolali tugma,
    (2) reaksiya emojilari, (3) delivery, (4) 4 qatorli universal panel,
    (5) agar vaqt belgilangan bo'lsa — ✅ Rejalashtirishni yakunlash.
    """
    rows = []
    # 1-vazifa: 📢 Kanal: [Tanlangan kanal nomi] tugmasi
    selected = _get_selected_channel(context)
    if selected:
        ch_id, ch_title = selected
        try:
            ch_label = btn_label(ch_title, max_length=20)
        except Exception:
            ch_label = str(ch_title)[:20]
        # mp_btn_channel = "📢 Kanal: {name}" — tarjima orqali
        try:
            channel_btn_text = manual_post_t("mp_btn_channel", lang, name=ch_label)
        except Exception:
            channel_btn_text = f"📢 Kanal: {ch_label}"
        rows.append([InlineKeyboardButton(channel_btn_text, callback_data=CB_MANUAL_CH_SELECTOR)])
    else:
        try:
            sel_text = manual_post_t("mp_btn_channel_select", lang)
        except Exception:
            sel_text = "📢 Kanalni tanlash"
        rows.append([InlineKeyboardButton(sel_text, callback_data=CB_MANUAL_CH_SELECTOR)])

    url_btn = _manual_url_button(context)
    if url_btn:
        rows.append([InlineKeyboardButton(url_btn[0], url=url_btn[1])])
    reactions = _manual_reactions(context)
    if reactions:
        rows.extend(build_reaction_button_rows(None, reactions, preview=True))
    rows.append([InlineKeyboardButton(delivery_labels(lang)["title"], callback_data="mnp_delivery")])
    rows.extend(get_manual_post_panel(lang).inline_keyboard)
    # 3-vazifa: agar vaqt belgilangan bo'lsa — yakunlash tugmasi
    if context.user_data.get(UD_WHEN) or context.user_data.get(UD_REPEAT_TIME):
        try:
            finish_text = manual_post_t("mp_btn_finish", lang)
        except Exception:
            finish_text = "✅ Yakunlash"
        rows.append([InlineKeyboardButton(finish_text, callback_data=CB_MANUAL_FINISH)])
    return InlineKeyboardMarkup(rows)


def _manual_extras_text(context, lang: str) -> str:
    """Preview matniga qo'shiladigan reaksiya/tugma xulosasi (bo'sh ham mumkin)."""
    lines = []
    reactions = _manual_reactions(context)
    if reactions:
        lines.append(manual_post_t(
            "mp_reactions_on", lang, emojis=" ".join(reactions)))
    url_btn = _manual_url_button(context)
    if url_btn:
        lines.append(manual_post_t(
            "mp_url_on", lang, text=html_escape(url_btn[0]),
            url=html_escape(url_btn[1])))
    # 5-vazifa: albom + tugma cheklovi haqida ogohlantirish
    if context.user_data.get(UD_MEDIA_GROUP) and (reactions or url_btn):
        lines.append(manual_post_t("mp_album_warning", lang))
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines)


async def _show_preview(target_msg, context, lang: str):
    """Saqlangan kontentni preview sifatida ko'rsatadi (panel tugmalari bilan).

    Matnli post — to'liq matn; media post — media + caption. Hech qanday AI
    qo'shimchasi YO'Q: foydalanuvchi nima yuborgan bo'lsa, aynan o'sha chiqadi.
    Tanlangan reaksiyalar va havolali tugma bo'lsa — preview matnida xulosa
    qatori, markup'da esa TUGMALAR ko'rinadi (2-qadam UI/UX polish).
    """
    content = context.user_data.get(UD_CONTENT, "") or ""
    post_type = context.user_data.get(UD_POST_TYPE, "text")
    file_id = context.user_data.get(UD_FILE_ID)
    panel = _manual_preview_markup(context, lang)
    title = manual_post_t("mp_preview_title", lang)
    foot = manual_post_t("mp_preview_foot", lang)
    extras = _manual_extras_text(context, lang)

    if post_type in _SUPPORTED_MEDIA and file_id:
        # Caption Telegram chegarasi 1024 — preview matni ham caption'da.
        caption_text = f"{title}{content}{extras}{foot}"
        cap = sanitize_html(caption_text, 1024)
        kwargs = dict(caption=cap, reply_markup=panel, parse_mode="HTML")
        try:
            if post_type == "photo":
                return await target_msg.reply_photo(photo=file_id, **kwargs)
            if post_type == "video":
                return await target_msg.reply_video(video=file_id, **kwargs)
            if post_type == "animation":
                return await target_msg.reply_animation(animation=file_id, **kwargs)
            return await target_msg.reply_document(document=file_id, **kwargs)
        except Exception:
            logger.warning("Oddiy post media preview xatosi", exc_info=True)
            # Media preview imkonsiz bo'lsa — matn ko'rinishida davom etamiz.

    body = f"{title}{sanitize_html(content, 3600)}{extras}{foot}"
    return await target_msg.reply_text(body, reply_markup=panel, parse_mode="HTML")


async def _choose_channel_or_act(query_msg, context, user_id: int, lang: str):
    """Kanal tanlash: tanlangan kanal bo'lsa darhol amal, bo'lmasa inline tanlov.

    1-vazifa: agar kanal tanlanmagan bo'lsa — "Qaysi kanalga chiqsin?" deb so'rash.
    Bitta kanal bo'lsa avtomatik tanlanadi.
    Qaytaradi: keyingi FSM holati (MANUAL_CHANNEL_SELECT yoki END).
    """
    # Avval saqlangan tanlangan kanalni tekshiramiz
    selected = _get_selected_channel(context)
    if selected:
        ch_id, ch_title = selected
        return await _publish(query_msg, context, user_id, ch_id, ch_title, lang)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        clear_fsm_data(context)
        _clear_manual_state(context)
        await query_msg.reply_text(
            manual_post_t("mp_no_channels", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    if len(channels) == 1:
        _set_selected_channel(context, channels[0][0], channels[0][1])
        return await _publish(query_msg, context, user_id, channels[0][0],
                              channels[0][1], lang)
    # Ko'p kanal — tanlash so'rovi (1-vazifa: "Qaysi kanalga chiqsin?")
    try:
        prompt = manual_post_t("mp_channel_prompt", lang)
    except Exception:
        try:
            prompt = manual_post_t("mp_choose_channel", lang)
        except Exception:
            prompt = "📢 Qaysi kanalga chiqsin?"
    await query_msg.reply_text(
        prompt,
        reply_markup=get_manual_channel_keyboard(channels, lang),
        parse_mode="HTML",
    )
    return MANUAL_CHANNEL_SELECT


# ============================================================
# PHASE 3 — RBAC/IDOR YORDAMCHISI (markaziy ruxsat tekshiruvi)
# ============================================================
async def manual_channel_guard(user_id: int, channel_id, action: str = "create") -> bool:
    """Foydalanuvchi AYNAN shu kanal ustida amal bajara oladimi?

    Markaziy nuqta — ``services.rbac_service.can(...)`` (resurs rollari:
    OWNER | EDITOR | SCHEDULER | ANALYST).  Fail-closed: RBAC moduli yoki DB
    xato bersa — ruxsat BERILMAYDI.

    Foydalanish::

        if not await manual_channel_guard(user_id, channel_id, "create"):
            ...  # Permission Denied — so'rov yopiq rad etiladi
    """
    from services import rbac_service

    try:
        return await rbac_service.can(
            user_id, resource_type="channel", resource_id=channel_id,
            action=action,
        )
    except Exception:  # pragma: no cover — kutilmagan xato ham ruxsat bermaydi
        logger.exception(
            "RBAC tekshiruvi xatosi (user=%s, channel=%s) — fail-closed",
            user_id, str(channel_id)[:64],
        )
        return False


# ============================================================
# YUBORISH/REJALASHTIRISH — yagona publish nuqtasi (db.add_post)
# ============================================================
async def _publish(target_msg, context, user_id: int, channel_id,
                   channel_title, lang: str):
    """Tanlangan rejim bo'yicha postni DB'ga yozadi (scheduler darhol oladi).

    🔁 PHASE C — DUBLIKAT DETEKTORI: post kanalga chiqarilishidan/rejalanishidan
    OLDIN kanalning oxirgi postlari bilan yengil (AI'siz) solishtiriladi.
    85%+ o'xshashlik topilsa — yozish TO'XTATILADI va SPEKS bo'yicha 3 tugmali
    ogohlantirish chiqadi: [🚀 Baribir chiqarish] | [✨ AI bilan yangilash] |
    [❌ Bekor qilish]. Detektor fail-soft: DB/kanal tarixi o'qilmasa post
    to'sib qo'yilmaydi.

    Qaytaradi: ConversationHandler.END — yakuniy xabar yuborilgan, FSM
    tozalanadi va asosiy menyu qaytadi. (Dublikat ogohlantirishida:
    MANUAL_PREVIEW.)
    """
    is_admin = user_id in ADMIN_IDS_SET
    mode = context.user_data.get(UD_MODE, MODE_NOW)

    # --- 🔐 PHASE 3: IDOR HIMOYASI (markaziy RBAC) ---------------------------
    # Kanal ID'si callback payload'idan yoki ``user_data`` dan kelishi mumkin —
    # unga ISHONIB BO'LMAYDI.  Yozishdan OLDIN foydalanuvchi AYNAN shu kanal
    # ustida post yaratish huquqiga ega ekani qayta tekshiriladi
    # (``services.rbac_service.can``: owner/editor → ruxsat, scheduler/analyst
    # va begona foydalanuvchi → rad).
    if not await manual_channel_guard(user_id, channel_id, "create"):
        logger.warning(
            "RBAC/IDOR: oddiy post rad etildi (user=%s, channel=%s) — ruxsat yo'q",
            user_id, str(channel_id)[:64],
        )
        await _finalize(target_msg, context, user_id, lang,
                        manual_post_t("mp_no_access", lang))
        return ConversationHandler.END

    # --- 🔁 DUBLIKAT TEKSHIRUVI (bir marta; "Baribir chiqarish" o'tkazib yuboradi)
    if not context.user_data.get(UD_DUP_FORCE):
        content_for_check = str(context.user_data.get(UD_CONTENT, "") or "")
        if content_for_check.strip():
            from services.channels.duplicate_detector import (
                screen_post_for_duplicates,
            )
            try:
                screen = await screen_post_for_duplicates(
                    channel_id, user_id, content_for_check)
            except Exception:  # fail-soft: detektor hech qachon to'suvchi emas
                logger.debug("Dublikat tekshiruvi xatosi (kanal=%s)",
                             channel_id, exc_info=True)
                screen = {"duplicate": False}
            if screen.get("duplicate"):
                context.user_data[UD_DUP_CHANNEL_ID] = str(channel_id)
                context.user_data[UD_DUP_CHANNEL_TITLE] = str(channel_title or "")
                try:
                    score_pct = int(round(
                        float(screen.get("score") or 0.0) * 100))
                except (TypeError, ValueError):
                    score_pct = 0
                preview = html_escape(
                    str(screen.get("matched_text") or "")[:220])
                try:
                    await target_msg.reply_text(
                        manual_post_t("mp_dup_warning", lang,
                                      score=score_pct, preview=preview),
                        reply_markup=get_duplicate_warning_keyboard(lang),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("Dublikat ogohlantirishi yuborilmadi",
                                 exc_info=True)
                return MANUAL_PREVIEW
    context.user_data.pop(UD_DUP_FORCE, None)
    context.user_data.pop(UD_DUP_CHANNEL_ID, None)
    context.user_data.pop(UD_DUP_CHANNEL_TITLE, None)

    now = datetime.now(tashkent_tz)

    delete_after_hours = 24 if mode == MODE_24H else 0
    recurrence_type = "daily" if mode == MODE_REPEAT else "none"
    recurrence_time = (
        f"{context.user_data.get(UD_REPEAT_TIME)}:00"
        if mode == MODE_REPEAT and context.user_data.get(UD_REPEAT_TIME)
        else None
    )

    if mode == MODE_REPEAT and context.user_data.get(UD_REPEAT_TIME):
        hh, mm = (int(x) for x in context.user_data[UD_REPEAT_TIME].split(":"))
        scheduled_time = tashkent_tz.localize(
            datetime(now.year, now.month, now.day, hh, mm))
        if scheduled_time <= now:
            scheduled_time = tashkent_tz.normalize(
                scheduled_time + timedelta(days=1))
    elif context.user_data.get(UD_WHEN):
        try:
            scheduled_time = datetime.strptime(
                context.user_data[UD_WHEN], "%Y-%m-%d %H:%M")
            scheduled_time = tashkent_tz.localize(scheduled_time)
        except (ValueError, TypeError):
            scheduled_time = now
    else:
        scheduled_time = now

    # 2-QADAM UI/UX POLISH: preview'da tanlangan reaksiyalar va havolali
    # tugma DB'ga to'liq saqlanadi — scheduler kanalga xuddi shu
    # reply_markup bilan chiqaradi (btn_text/btn_url + enable_reactions +
    # reaction_emojis ustunlari orqali).
    reactions = _manual_reactions(context)
    url_btn = _manual_url_button(context)

    ok = False
    try:
        pid = await db.run_db(
            db.add_post,
            delivery_options=context.user_data.get(UD_DELIVERY, {}),
            user_id=user_id,
            channel_id=channel_id,
            post_type=context.user_data.get(UD_POST_TYPE, "text"),
            content=context.user_data.get(UD_CONTENT, "") or "",
            file_id=context.user_data.get(UD_FILE_ID),
            scheduled_time=scheduled_time,
            recurrence_type=recurrence_type,
            recurrence_day=None,
            recurrence_time=recurrence_time,
            end_date=None,
            btn_text=(url_btn[0] if url_btn else None),
            btn_url=(url_btn[1] if url_btn else None),
            enable_reactions=bool(reactions),
            delete_after_hours=delete_after_hours,
            reaction_emojis=(" ".join(reactions) if reactions else None),
        )
        ok = bool(pid)
    except Exception:
        logger.exception("Oddiy post saqlash xatosi (user_id=%s)", user_id)

    if not ok:
        await _finalize(target_msg, context, user_id, lang,
                        manual_post_t("mp_save_error", lang))
        return ConversationHandler.END

    channel_safe = html_escape((channel_title or "").strip() or "Kanal")
    if mode == MODE_TIME:
        msg_key = "mp_scheduled"
        time_display = (
            format_datetime(scheduled_time, lang)
            or scheduled_time.strftime("%Y-%m-%d %H:%M")
        )
    elif mode == MODE_24H:
        msg_key = "mp_sent_24h"
        time_display = ""
    elif mode == MODE_REPEAT:
        msg_key = "mp_repeat_ok"
        time_display = format_time(
            f"{context.user_data.get(UD_REPEAT_TIME)}:00", lang)
    else:
        msg_key = "mp_sent_now"
        time_display = ""

    await _finalize(
        target_msg, context, user_id, lang,
        manual_post_t(msg_key, lang, channel=channel_safe, time=time_display),
    )
    return ConversationHandler.END


async def _dup_ai_refresh(query, context, user_id: int, lang: str) -> int:
    """[✨ AI bilan yangilash] — dublikat postni AI boshqacha qilib yozadi.

    Oddiy post oqimining "AI'siz" qoidasi buzilmaydi: bu amal FAQAT dublikat
    ogohlantirishida, foydalanuvchi o'zi bosganda ishlaydi. AI javobi
    ``sanitize_html`` bilan xavfsizlanadi; xatoda eski matn saqlanib qoladi
    va muloyim xabar ko'rsatiladi.
    """
    old_text = str(context.user_data.get(UD_CONTENT, "") or "")
    if not old_text.strip():
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    try:
        from services.ai_engine import gateway
        result = await gateway.legacy_chain(
            f"Quyidagi Telegram postini mavzusi saqlanib, lekin tuzilishi, "
            f"hook va so'zlari BUTUNLAY BOSHQAChA qilib qayta yozing "
            f"(bu post kanalda yaqinda chiqqan postga juda o'xshab qoldi):\n\n"
            f"{old_text[:3000]}",
            "Siz SMM copywriter'siz. Faqat tayyor post matnini qaytaring — "
            "izoh, sarlavha va hech qanday qo'shimcha yo'q.",
            lang,
        )
    except Exception:
        logger.warning("Dublikat AI-yangilash xatosi (user=%s)", user_id,
                       exc_info=True)
        result = {}
    new_text = ""
    if isinstance(result, dict) and not result.get("error"):
        new_text = str(result.get("text") or result.get("content") or "").strip()

    if not new_text:
        try:
            await query.message.reply_text(
                manual_post_t("mp_dup_ai_failed", lang),
                reply_markup=get_duplicate_warning_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("AI-yangilash xato xabari yuborilmadi", exc_info=True)
        return MANUAL_PREVIEW

    context.user_data[UD_CONTENT] = sanitize_html(new_text, 3600)
    for key in (UD_DUP_FORCE, UD_DUP_CHANNEL_ID, UD_DUP_CHANNEL_TITLE):
        context.user_data.pop(key, None)
    try:
        await query.message.reply_text(
            manual_post_t("mp_dup_ai_done", lang), parse_mode="HTML")
    except Exception as _silent_exc:
        log_silent_failure("handlers.manual_post:_dup_ai_refresh", _silent_exc, user_id=user_id, lang=lang)
    await _show_preview(query.message, context, lang)
    return MANUAL_PREVIEW


async def _finalize(target_msg, context, user_id: int, lang: str,
                    text: str) -> None:
    """Yakuniy xabar + asosiy menyu + holatni tozalash (yagona nuqta)."""
    clear_fsm_data(context)
    _clear_manual_state(context)
    if target_msg is None:
        return
    try:
        await target_msg.reply_text(
            text,
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("Oddiy post yakuniy xabarini yuborib bo'lmadi",
                     exc_info=True)


# ============================================================
# HANDLERLAR
# ============================================================
async def manual_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✍️ Oddiy post (AI'siz) — kontent kutish holatini ochadi.

    Kanal ulanmagan bo'lsa oqim ochilmaydi (muloyim yo'riqnoma + asosiy
    menyu). HECH QANDAY AI tekshiruvi/limiti YO'Q — bu oddiy posting.
    """
    query = getattr(update, "callback_query", None)
    if query is not None:
        try:
            await query.answer()
        except Exception as _silent_exc:
            log_silent_failure("handlers.manual_post:manual_post_entry", _silent_exc)
    msg = (
        getattr(update, "message", None)
        or getattr(update, "effective_message", None)
        or getattr(query, "message", None)
    )
    if msg is None:
        return ConversationHandler.END
    clear_fsm_data(context)
    _clear_manual_state(context)
    user = getattr(update, "effective_user", None) or getattr(query, "from_user", None)
    user_id = user.id if user else 0
    lang = get_lang(context)
    from handlers.navigation import SECTION_CONTENT, remember_section
    remember_section(context, SECTION_CONTENT)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await msg.reply_text(
            manual_post_t("mp_no_channels", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # 1-vazifa: bitta kanal bo'lsa avtomatik tanlash, lekin nomini ko'rsatish
    if len(channels) == 1:
        _set_selected_channel(context, channels[0][0], channels[0][1])

    await msg.reply_text(
        manual_post_t("mp_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return MANUAL_AWAIT_CONTENT


async def manual_content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tayyor kontent qabul qilindi → DARHOL preview (AI savollarsiz).

    Matn, rasm, video, GIF yoki hujjat (caption bilan yokisiz) qabul
    qilinadi; qolgan turlar (stiker, ovoz, kontakt...) aniq izoh bilan
    rad etiladi — lekin oqim uzilmaydi.
    """
    msg = update.message
    lang = get_lang(context)

    file_id, post_type = _extract_media(msg)
    text_input = (msg.text or msg.caption or "").strip()

    if not file_id and not text_input:
        # Qo'llab-quvvatlanmaydigan xabar turi (stiker/ovoz/kontakt...).
        await msg.reply_text(
            manual_post_t("mp_unsupported", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_AWAIT_CONTENT

    context.user_data[UD_CONTENT] = text_input
    context.user_data[UD_POST_TYPE] = post_type if file_id else "text"
    context.user_data[UD_FILE_ID] = file_id
    context.user_data[UD_MEDIA_GROUP] = bool(getattr(msg, "media_group_id", None))

    # 1-vazifa: agar kanal hali tanlanmagan bo'lsa va bitta kanal bo'lsa — auto-select
    if not _get_selected_channel(context):
        try:
            chs = await db.run_db(db.get_user_channels, msg.from_user.id)
            if chs and len(chs) == 1:
                _set_selected_channel(context, chs[0][0], chs[0][1])
        except Exception as _silent_exc:
            log_silent_failure("handlers.manual_post:manual_content_received", _silent_exc)

    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_edit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✏️ Tahrirlash: yangi kontent bilan preview yangilanadi."""
    msg = update.message
    lang = get_lang(context)

    file_id, post_type = _extract_media(msg)
    text_input = (msg.text or msg.caption or "").strip()
    if not file_id and not text_input:
        await msg.reply_text(
            manual_post_t("mp_unsupported", lang), parse_mode="HTML",
        )
        return MANUAL_EDIT_INPUT

    # Tahrirlash: media almashtirilsa — yangi media; matn har doim yangilanadi.
    if file_id:
        context.user_data[UD_POST_TYPE] = post_type
        context.user_data[UD_FILE_ID] = file_id
        context.user_data[UD_MEDIA_GROUP] = bool(getattr(msg, "media_group_id", None))
    context.user_data[UD_CONTENT] = text_input

    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Vaqtni belgilash / 🔄 Takroriy e'lon vaqti qabul qilinadi.

    ``parse_schedule_input`` — "19:30", "ertaga 09:00", "25.09.2026 18:00"
    kabi barcha ko'rinishlarni xavfsiz o'qiydi (o'tmishdagi vaqt rad etiladi).
    Takroriy rejada faqat KUNLIK VAQT ("HH:MM") olinadi.
    """
    msg = update.message
    user_id = update.effective_user.id
    lang = get_lang(context)
    mode = context.user_data.get(UD_MODE, MODE_TIME)

    if msg is None:
        return MANUAL_TIME_INPUT
    if not getattr(msg, "text", None):
        await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_TIME_INPUT

    text = msg.text.strip()

    if mode == MODE_REPEAT:
        parsed = parse_daily_time_input(text)
        if parsed is None:
            candidate, _reason = parse_schedule_input(text)
            parsed = (candidate.hour, candidate.minute) if candidate else None
        if parsed is None:
            await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                                 parse_mode="HTML")
            return MANUAL_TIME_INPUT
        hh, mm = parsed
        time_str = f"{hh:02d}:{mm:02d}"
        context.user_data[UD_REPEAT_TIME] = time_str
        # 3-vazifa: FSM yopilmaydi, vaqt saqlanadi va preview qayta ko'rsatiladi
        try:
            time_msg = manual_post_t("mp_time_set", lang, time=time_str)
        except Exception:
            time_msg = f"🕒 Vaqt belgilandi: {time_str}. Yana reaksiya, havola yoki sozlamalarni o'zgartirishingiz mumkin."
        await msg.reply_text(time_msg, parse_mode="HTML")
        await _show_preview(msg, context, lang)
        return MANUAL_PREVIEW

    candidate, _reason = parse_schedule_input(text)
    if candidate is None:
        await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_TIME_INPUT

    context.user_data[UD_WHEN] = candidate.strftime("%Y-%m-%d %H:%M")
    # 3-vazifa: FSM yopilmaydi, vaqt saqlanadi va preview qayta ko'rsatiladi
    try:
        display_time = format_datetime(candidate, lang) if 'format_datetime' in globals() else candidate.strftime("%Y-%m-%d %H:%M")
    except Exception:
        display_time = candidate.strftime("%Y-%m-%d %H:%M")
    try:
        time_msg = manual_post_t("mp_time_set", lang, time=display_time)
    except Exception:
        time_msg = f"🕒 Vaqt belgilandi: {display_time}. Yana reaksiya, havola yoki sozlamalarni o'zgartirishingiz mumkin."
    await msg.reply_text(time_msg, parse_mode="HTML")
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_reaction_custom_received(update: Update,
                                          context: ContextTypes.DEFAULT_TYPE):
    """➕ O'zim kiritaman: qo'lda yuborilgan reaksiya emojilari qabul qilinadi.

    SMART EMOJI (2-qism bugfix):
      * Foydalanuvchi sof emoji(lar) yuborsa (masalan 😎 yoki 🔥 👍),
        xato berilmasin — emoji(lar) ajratib olinib (maksimal 5 tagacha)
        postning reaction_emojis ro'yxatiga saqlanadi va preview darhol
        shu tugmalar bilan yangilanadi.
      * Emoji bo'lmagan belgilar tashlanadi; hech narsa topilmasa muloyim
        xato bilan holat saqlanadi.
    """
    msg = update.message
    lang = get_lang(context)
    if msg is None or not (msg.text or "").strip():
        if msg is not None:
            await msg.reply_text(
                manual_post_t("mp_react_custom_invalid", lang),
                parse_mode="HTML",
            )
        return MANUAL_REACTION_CUSTOM

    # SMART: maksimal 5 tagacha emoji ajratib olinadi
    emojis = _smart_extract_emojis(msg.text, max_count=SMART_EMOJI_MAX)
    if not emojis:
        # Fallback — eski normalizator (10 tagacha) bilan ham sinab ko'ramiz,
        # lekin natijani 5 tagacha kesamiz
        try:
            fallback = normalize_custom_reaction_emojis(msg.text, max_count=SMART_EMOJI_MAX)
        except TypeError:
            fallback = normalize_custom_reaction_emojis(msg.text)
        if fallback:
            emojis = fallback[:SMART_EMOJI_MAX]

    if not emojis:
        await msg.reply_text(
            manual_post_t("mp_react_custom_invalid", lang),
            parse_mode="HTML",
        )
        return MANUAL_REACTION_CUSTOM

    context.user_data[UD_REACTIONS] = emojis[:SMART_EMOJI_MAX]
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_preview_emoji_received(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """SMART EMOJI — preview holatida (reaksiyalar oynasida) to'g'ridan-to'g'ri emoji yuborish.

    Muammo: foydalanuvchi reaksiyalar tanlash oynasida (MANUAL_PREVIEW) to'g'ridan-to'g'ri
    emoji yuborsa, bot \"Bu turdagi xabar qabul qilinmaydi\" deb xato berardi,
    chunki MANUAL_PREVIEW holatida faqat callback'lar bor edi, matn handler'i yo'q edi.

    Yechim: preview holatida ham sof emoji(lar) qabul qilinadi, 5 tagacha ajratib olinib
    reaksiyalar ro'yxatiga saqlanadi va preview darhol yangilanadi. Emoji bo'lmagan
    matn bo'lsa — FSM INPUT FALLBACK (PHASE 1): 💡 yumshoq eslatma + preview qayta
    ko'rsatiladi (xato berilmaydi, oqim va FSM holati uzilmaydi).
    """
    msg = update.message
    lang = get_lang(context)
    if msg is None:
        return MANUAL_PREVIEW

    # Kontent yo'q bo'lsa (sessiya eskirgan) — eski xatti-harakat saqlanadi
    if not _has_content(context):
        await msg.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(
                (msg.from_user.id if getattr(msg, "from_user", None) else 0) in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        clear_fsm_data(context)
        _clear_manual_state(context)
        return ConversationHandler.END

    text = (msg.text or "").strip()
    if not text:
        # Media — FSM INPUT FALLBACK: 💡 eslatma + preview qayta (holat saqlanadi)
        return await _preview_soft_fallback(msg, context, lang)

    emojis = _smart_extract_emojis(text, max_count=SMART_EMOJI_MAX)
    if emojis:
        # Sof emoji yoki emoji aralash matn bo'lsa ham, emojilarni reaksiya sifatida qabul qilamiz
        # (topshiriq: sof emoji bo'lsa xato berilmasin; biz biroz kengroq — har qanday emoji topilsa qabul qilamiz)
        context.user_data[UD_REACTIONS] = emojis[:SMART_EMOJI_MAX]
        await _show_preview(msg, context, lang)
        return MANUAL_PREVIEW

    # Emoji topilmadi — foydalanuvchi erkin matn yozib yubordi.
    # FSM INPUT FALLBACK (PHASE 1): quruq javob YO'Q — 💡 yumshoq eslatma
    # beriladi va mavjud Preview menyusi (inline boshqaruv paneli) qayta
    # ko'rsatiladi; foydalanuvchi panel tugmalaridan foydalanadi.
    return await _preview_soft_fallback(msg, context, lang)


async def manual_preview_media_received(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """MEDIA (rasm/video/stiker...) preview bosqichida — yumshoq fallback.

    Foydalanuvchi [Post preview] panelida tugma bosish o'rniga adashib media
    tashlab yuborsa: bot quruq «xabar qabul qilinmaydi» deb to'xtab qolmaydi —
    💡 yumshoq ogohlantirish beriladi, mavjud Preview menyusi qayta ko'rsatiladi
    va FSM holati (MANUAL_PREVIEW) bekor bo'lib ketmaydi.
    """
    msg = update.message
    if msg is None:
        return MANUAL_PREVIEW
    lang = get_lang(context)
    return await _preview_soft_fallback(msg, context, lang)


async def manual_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔗 Havolali tugma: "Matn - https://havola" yoki faqat "https://havola" formati.

    SMART URL PARSER (2-qism bugfix):
      * Agar foydalanuvchi faqat bitta havolani yuborsa (matnsiz, masalan
        https://t.me/kanal yoki https://sayt.uz) — bot xato bermasin!
        Tugma matni avtomatik tanlanadi:
          - Havola t.me bo'lsa → "📢 Kanalga o'tish"
          - Boshqa veb-sayt bo'lsa → "🔗 Batafsil"
      * Agar format "Matn - Havola" ko'rinishida yuborilgan bo'lsa →
        foydalanuvchi kiritgan matn ishlatiladi.
      * URL xavfsizligi (http, https, tg protokollari) qat'iy saqlanadi.

    XAVFSIZLIK: havola ``validate_button_url`` (utils.security
    ``url_rejection_reason`` asosida) tekshiruvidan o'tadi — FAQAT
    ``http://``, ``https://`` va ``tg://`` protokollariga ruxsat;
    ``javascript:``, ``file:``, ``data:`` kabi xavfli havolalar RAD
    etiladi va holat saqlanadi. Muvaffaqiyatda tugma preview ostida
    HAQIQIY inline URL tugma sifatida paydo bo'ladi.
    """
    msg = update.message
    lang = get_lang(context)
    if msg is None or not (msg.text or "").strip():
        if msg is not None:
            await msg.reply_text(manual_post_t("mp_url_invalid", lang),
                                 parse_mode="HTML")
        return MANUAL_URL_INPUT

    raw = (msg.text or "").strip()

    # SMART PARSER — yakka URL yoki "Matn - URL" ni qo'llaydi
    btn_text, btn_url = _smart_parse_url_button(raw)

    if not btn_text or not btn_url:
        await msg.reply_text(manual_post_t("mp_url_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_URL_INPUT

    # Xavfsizlik: har ikkala qism ham validatsiya qilinadi (protokol cheklovi saqlanadi)
    ok_text, _err_text = validate_button_text(btn_text)
    ok_url, _err_url = validate_button_url(btn_url)
    if not (ok_text and ok_url):
        await msg.reply_text(manual_post_t("mp_url_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_URL_INPUT

    context.user_data[UD_URL_BTN_TEXT] = btn_text
    context.user_data[UD_URL_BTN_URL] = btn_url
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


# ============================================================
# FSM INPUT FALLBACK (PHASE 1) — kiritish bosqichlari uchun
# yumshoq eslatma + joriy menyuni qayta ko'rsatish (holat saqlanadi)
# ============================================================
async def manual_channel_select_fallback(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlash bosqichida erkin matn/media — yumshoq fallback.

    MANUAL_CHANNEL_SELECT holatida inline kanal tugmalari kutilmoqda;
    foydalanuvchi adashib matn yozsa yoki media tashsa — bot quruq javob
    bilan to'xtab qolmaydi: 💡 yumshoq eslatma beriladi, kanal tanlov
    klaviaturasi qayta ko'rsatiladi va FSM holati bekor bo'lib ketmaydi.
    """
    msg = update.message
    if msg is None:
        return MANUAL_CHANNEL_SELECT
    user_id = update.effective_user.id if update.effective_user else 0
    lang = get_lang(context)
    await _reply_stage_hint(msg, lang)
    try:
        channels = await db.run_db(db.get_user_channels, user_id) or []
    except Exception:
        logger.debug("Kanal ro'yxatini o'qishda xato", exc_info=True)
        channels = []
    if not channels:
        # Kanallar mavjud bo'lmasa — oqimni muloyim yopamiz (eski xulq).
        await _finalize(msg, context, user_id, lang,
                        manual_post_t("mp_no_channels", lang))
        return ConversationHandler.END
    try:
        prompt = manual_post_t("mp_channel_prompt", lang)
    except Exception:  # noqa: BLE001 — zaxira matn bilan davom etamiz
        prompt = manual_post_t("mp_choose_channel", lang)
    await msg.reply_text(
        prompt,
        reply_markup=get_manual_channel_keyboard(channels, lang),
        parse_mode="HTML",
    )
    return MANUAL_CHANNEL_SELECT


async def manual_reaction_custom_media_received(
        update: Update, context: ContextTypes.DEFAULT_TYPE):
    """➕ Reaksiya kiritish bosqichida MEDIA — yumshoq fallback.

    Emoji kutilmoqda, lekin rasm/video tashlandi: 💡 eslatma + kiritish
    yo'riqnomasi qayta ko'rsatiladi, FSM holati (MANUAL_REACTION_CUSTOM)
    bekor bo'lib ketmaydi.
    """
    msg = update.message
    if msg is None:
        return MANUAL_REACTION_CUSTOM
    lang = get_lang(context)
    await _reply_stage_hint(msg, lang)
    await msg.reply_text(
        manual_post_t("mp_react_custom_prompt", lang)
        + _manual_album_warning(context, lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return MANUAL_REACTION_CUSTOM


async def manual_url_media_received(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    """🔗 Havolali tugma kiritish bosqichida MEDIA — yumshoq fallback.

    «Matn - havola» kutilmoqda, lekin rasm/video tashlandi: 💡 eslatma +
    kiritish yo'riqnomasi qayta ko'rsatiladi, FSM holati (MANUAL_URL_INPUT)
    bekor bo'lib ketmaydi.
    """
    msg = update.message
    if msg is None:
        return MANUAL_URL_INPUT
    lang = get_lang(context)
    await _reply_stage_hint(msg, lang)
    await msg.reply_text(
        manual_post_t("mp_url_prompt", lang)
        + _manual_album_warning(context, lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return MANUAL_URL_INPUT


async def manual_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Universal boshqaruv paneli tugmalari (``mnp_*`` callback'lari)."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()  # SPEKS: har callback boshida darhol answer
    user_id = query.from_user.id
    lang = get_lang(context)
    data = query.data or ""

    # Eski tugmalarga qarshi himoya: kontent saqlanmagan bo'lsa, yangi
    # oqimni ochish taklif qilinadi (foydalanuvchi hech qachon "qotmaydi").
    if data != CB_MANUAL_CANCEL and not _has_content(context):
        await query.message.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        clear_fsm_data(context)
        return ConversationHandler.END

    if data == "mnp_delivery" or data.startswith("mnp_delivery:"):
        options = context.user_data.setdefault(UD_DELIVERY, {})
        if ":" in data:
            key = data.split(":", 1)[1]
            if key not in DELIVERY_KEYS:
                return MANUAL_PREVIEW
            options[key] = not options.get(key, False)
        await query.edit_message_reply_markup(reply_markup=delivery_markup(options, lang))
        return MANUAL_PREVIEW

    if data == CB_MANUAL_CANCEL:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception as _silent_exc:
            log_silent_failure("handlers.manual_post:manual_panel_callback", _silent_exc)
        await _finalize(query.message, context, user_id, lang,
                        manual_post_t("mp_cancelled", lang))
        return ConversationHandler.END

    if data == CB_MANUAL_PANEL:
        # Kanal tanlashdan preview paneliga qaytish.
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    if data == CB_MANUAL_EDIT:
        await query.message.reply_text(
            manual_post_t("mp_edit_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_EDIT_INPUT

    # --- ❤️ REAKSIYALAR (2-qadam UI/UX polish) ---
    if data == CB_MANUAL_REACT:
        # Preset tanlash oynasi: [👍/👎] | [🔥/❤️/👏] + ➕ O'zim kiritaman
        # + ◀️ Orqaga. Tanlov shu xabarning o'zida (toggle) yangilanadi.
        await query.message.reply_text(
            manual_post_t("mp_react_prompt", lang)
            + _manual_album_warning(context, lang),
            reply_markup=get_manual_reaction_keyboard(
                _manual_reactions(context), lang),
            parse_mode="HTML",
        )
        return MANUAL_PREVIEW

    if data == CB_MANUAL_REACT_BACK:
        # Saqlash / Orqaga — tanlangan reaksiyalar bilan preview yangilanadi.
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    if data == CB_MANUAL_REACT_CUSTOM:
        # ➕ O'zim kiritaman — qo'lda emoji kiritish holati ochiladi.
        await query.message.reply_text(
            manual_post_t("mp_react_custom_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_REACTION_CUSTOM

    if data.startswith(CB_MANUAL_REACT_TOGGLE):
        emoji = manual_reaction_from_callback(data)
        selected = list(context.user_data.get(UD_REACTIONS) or [])
        if emoji:
            key = strip_variation_selector(emoji)
            existing = next(
                (e for e in selected
                 if strip_variation_selector(e) == key), None)
            if existing is not None:
                selected.remove(existing)          # takror bosildi → o'chadi
            elif len(selected) < CUSTOM_REACTION_MAX:
                selected.append(emoji)             # yangi tanlov qo'shiladi
            context.user_data[UD_REACTIONS] = selected
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_manual_reaction_keyboard(selected, lang))
        except Exception:
            logger.debug("Reaksiya klaviaturasini yangilab bo'lmadi",
                         exc_info=True)
        return MANUAL_PREVIEW

    # --- 🔗 HAVOLALI (URL) TUGMA (2-qadam UI/UX polish) ---
    if data == CB_MANUAL_URL_BTN:
        await query.message.reply_text(
            manual_post_t("mp_url_prompt", lang)
            + _manual_album_warning(context, lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_URL_INPUT

    if data == CB_MANUAL_TIME:
        context.user_data[UD_MODE] = MODE_TIME
        await query.message.reply_text(
            manual_post_t("mp_time_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_TIME_INPUT

    if data == CB_MANUAL_REPEAT:
        context.user_data[UD_MODE] = MODE_REPEAT
        await query.message.reply_text(
            manual_post_t("mp_repeat_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_TIME_INPUT

    # 1-vazifa: 📢 Kanal: [name] tugmasi — kanal ro'yxatini ochish
    if data == CB_MANUAL_CH_SELECTOR:
        channels = await db.run_db(db.get_user_channels, user_id) or []
        if not channels:
            await query.message.reply_text(
                manual_post_t("mp_no_channels", lang),
                reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
                parse_mode="HTML",
            )
            return ConversationHandler.END
        if len(channels) == 1:
            _set_selected_channel(context, channels[0][0], channels[0][1])
            await _show_preview(query.message, context, lang)
            return MANUAL_PREVIEW
        try:
            prompt = manual_post_t("mp_channel_prompt", lang)
        except Exception:
            prompt = manual_post_t("mp_choose_channel", lang)
        await query.message.reply_text(
            prompt,
            reply_markup=get_manual_channel_keyboard(channels, lang),
            parse_mode="HTML",
        )
        return MANUAL_CHANNEL_SELECT

    # 3-vazifa: ✅ Rejalashtirishni yakunlash — vaqt belgilangan bo'lsa publish
    if data == CB_MANUAL_FINISH:
        # Vaqt belgilanganmi tekshiramiz
        if not (context.user_data.get(UD_WHEN) or context.user_data.get(UD_REPEAT_TIME)):
            await _show_preview(query.message, context, lang)
            return MANUAL_PREVIEW
        return await _choose_channel_or_act(query.message, context, user_id, lang)

    if data == CB_MANUAL_NOW:
        context.user_data[UD_MODE] = MODE_NOW
        return await _choose_channel_or_act(query.message, context, user_id, lang)

    if data == CB_MANUAL_24H:
        context.user_data[UD_MODE] = MODE_24H
        return await _choose_channel_or_act(query.message, context, user_id, lang)

    # 🔁 PHASE C — dublikat ogohlantirishi amallari (SPEKS: 3 tugma).
    if data == CB_MANUAL_DUP_FORCE:
        context.user_data[UD_DUP_FORCE] = True
        dup_channel = context.user_data.get(UD_DUP_CHANNEL_ID)
        dup_title = str(context.user_data.get(UD_DUP_CHANNEL_TITLE) or "")
        if dup_channel:
            return await _publish(query.message, context, user_id,
                                  dup_channel, dup_title, lang)
        return await _choose_channel_or_act(query.message, context, user_id,
                                            lang)

    if data == CB_MANUAL_DUP_AI:
        return await _dup_ai_refresh(query, context, user_id, lang)

    if data.startswith(CB_MANUAL_CHANNEL):
        channel_id = manual_channel_from_callback(data)
        if channel_id is None:
            await _show_preview(query.message, context, lang)
            return MANUAL_PREVIEW
        channels = await db.run_db(db.get_user_channels, user_id) or []
        title = next((t for cid, t in channels if str(cid) == str(channel_id)),
                     "")
        if not title and channels:
            await query.message.reply_text(
                manual_post_t("mp_choose_channel", lang),
                reply_markup=get_manual_channel_keyboard(channels, lang),
                parse_mode="HTML",
            )
            return MANUAL_CHANNEL_SELECT
        # 1-vazifa: kanalni saqlab, preview'ga qaytish (darhol publish emas)
        _set_selected_channel(context, channel_id, title)
        # Agar oldin biror amal (masalan Hozir yuborish) bosilgan bo'lsa va endi kanal tanlangan bo'lsa,
        # keyingi qadamda foydalanuvchi yana Hozir yuborish bosishi kerakmi yoki darhol publish?
        # Talab: kanal tanlangach preview ko'rsatilsin, foydalanuvchi yana reaksiya/havola o'zgartirishi mumkin.
        # Shuning uchun avval preview qaytaramiz. Agar mode NOW/24H bo'lsa va foydalanuvchi kanal tanlash
        # orqali kelgan bo'lsa, darhol publish qilmasdan preview ko'rsatamiz — bu 1-vazifa talabiga mos.
        # Ammo agar foydalanuvchi avval "Hozir yuborish" bosib, kanal tanlashga o'tgan bo'lsa,
        # biz channel tanlangach darhol publish qilmaymiz, balki preview ko'rsatamiz.
        # Foydalanuvchi istasa yana "Hozir yuborish" bosadi — bu aniq UX.
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    return MANUAL_PREVIEW


async def manual_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sessiya tugagach bosilgan eski ``mnp_*`` tugma — muloyim javob.

    Entry point sifatida ro'yxatdan o'tadi: eski preview xabaridagi tugma
    bosilsa foydalanuvchi javobsiz qolmaydi (crash ham yo'q).
    """
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    lang = get_lang(context)
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.manual_post:manual_stale_callback:1516", _silent_exc, user_id=user_id, lang=lang)
    clear_fsm_data(context)
    _clear_manual_state(context)
    try:
        await query.message.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
    except Exception as _silent_exc:
        log_silent_failure("handlers.manual_post:manual_stale_callback:1526", _silent_exc, user_id=user_id, lang=lang)
    return ConversationHandler.END


# ============================================================
# DIALOG HIMOYASI (content_creation.ContentOfferEntryHandler usuli)
# ============================================================
_APPLICATION = None


def set_application(app) -> None:
    """``ManualEntryHandler`` uchun Application havolasini o'rnatadi."""
    global _APPLICATION
    _APPLICATION = app


def _is_inside_dialog(update) -> bool:
    """Foydalanuvchi biror ConversationHandler dialogida bo'lsa True."""
    app = _APPLICATION
    if app is None:
        return False
    try:
        from handlers import _active_conversation_state

        return _active_conversation_state(app, update) is not None
    except Exception:  # pragma: no cover - xatoda entry'ni xavfsiz yopamiz
        return False


class ManualEntryHandler(CallbackQueryHandler):
    """Eski ``mnp_*`` panel tugmasi — faqat dialog TASHQARISIDA ishlaydi.

    Boshqa dialog (to'lov, kanal ulash, new_post...) faol bo'lsa tugma mos
    KELMAYDI: holat buzilmaydi, xabar o'sha dialogning o'z handlerlariga
    (yoki fallback'ga) qoladi. Dialog TASHQARISIDA esa sessiya eskirgani
    haqida muloyim javob qaytaradi.
    """

    def check_update(self, update):
        base = super().check_update(update)
        if not base or _is_inside_dialog(update):
            return None
        return base
