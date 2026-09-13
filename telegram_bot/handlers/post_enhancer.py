"""✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer) — ⚙️ Qo'shimcha funksiyalar.

Bosqichma-bosqich oqim (har bir qadamda "⬅️ Orqaga" va "❌ Bekor qilish" bor):
  0. Kirish: darhol **admin eslatmasi** (bot kanalda admin bo'lishi kerak) va
     postni so'rash.
  1. Foydalanuvchi tayyor postni yuboradi (matn, rasm, video, albom,
     hujjat/audio yoki istalgan kanaldan FORWARD). Postning ASL MATNIGA
     TEKILMAYDI — bot uni o'zgartirmaydi, qisqartirmaydi, AI bilan
     "yozmaydi". Faqat bepul (Free) rejali foydalanuvchilar uchun kanalga
     yuborilganda scheduler'dagi via/watermark qoidalari qo'llanadi.

     YAGONA ISTISNO — foydalanuvchining O'Z so'rovi bilan: PRO tarifda
     hub'da "✨ AI audit (PRO)" tugmasi ko'rinadi. Bosilganda post matni
     2-BOSQICHLI auditor oqimidan o'tadi (``utils.ai_agent``:
     ``_AUDIT_PRO_SYSTEM`` tizim prompti bilan ikkinchi AI so'rovi) va
     foydalanuvchiga mukammallashtirilgan yakuniy variant ko'rsatiladi.
     Auditor timeout/xato bersa yoki tayyor post qaytarmasa — ASL post
     o'zgarmaydi, oqim to'xtab qolmaydi. FREE tarifda tugma ko'rinmaydi
     va ikkinchi AI so'rovi UMUMAN chaqirilmaydi.
  2. 👍 Reaksiyalar: emoji tugmalari YOKI bir nechta emojini probel bilan
     bitta xabarda yuborish (batch): ``👍 ❤️ 🔥 👏 🎉``.
  3. 🔗 URL tugmalar: 3 ta tayyor shablon (Kanalga a'zo bo'lish / Guruhga
     qo'shilish / Botga o'tish) yoki qo'lda kiritish
     (``Tugma nomi - https://havola.uz``).
  4. 👁 Prevyu: faqat foydalanuvchi so'raganda post (media + tugmalar +
     reaksiyalar) ko'rsatiladi; tahrirlash qadamlarida post chiqarilmaydi.
  5. 🚀 Kanalga yuborish: kanal ro'yxati → "Ushbu post **Kanal**ga
     yuborilsinmi?" → ✅ tasdiq → "✅ Post kanalingizga muvaffaqiyatli
     joylandi!" + [🏠 Asosiy menyu].

Barcha ekranlar bitta xabar (hub) ustida inline navigatsiya bilan ishlaydi:
yangi xabarlar spam bo'lmaydi, "Orqaga" tugmalari doim mavjud.
"""
import asyncio
import json
import logging
import re
import time
from datetime import datetime, timedelta

import pytz
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaDocument,
    InputMediaAudio,
)
from telegram.error import TelegramError, BadRequest
from telegram.ext import ContextTypes, ConversationHandler

from config import ADMIN_IDS_SET, BOT_USERNAME
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.callback_data import cb
from keyboards.inline import (
    btn_label,
    extract_emoji_tokens,
    strip_variation_selector,
    strip_leading_reaction_glyphs,
    REACTION_POOL,
)
from utils.helpers import (
    html_escape,
    safe_html,
    apply_post_watermark,
    check_rate_limit,
)
# ✨ PRO 2-bosqichli AI audit: auditor utils.ai_agent'da (_AUDIT_PRO_SYSTEM).
from utils import ai_agent
from scheduler import (
    compose_post_text, parse_album_items,
    resolve_channel_ad, build_ad_button_row,
)
# Albom (media_group) yig'ish logikasi new_post bilan umumiy — buffer'lar ham.
from locales.translations import clear_fsm_data, get_lang, get_text
from handlers.new_post import (
    _media_item_from_message,
    _apply_single_media,
    _purge_stale_albums,
    _ALBUM_BUFFERS,
    _ALBUM_WAIT_SECONDS,
    parse_url_button_line,
    normalize_button_url as _np_normalize_button_url,
)

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

# Holat: butun enhancer oqimi bitta FSM holatida (qadamlar user_data ichida).
# Eslatma: new_post 100-113, queue 200-201, pending 202-205 — 121 band emas.
ENH_POST = 121

MAX_ENH_REACTIONS = 10      # 10 tagacha reaksiya (emoji tugma)
MAX_ENH_BUTTONS = 10        # 10 tagacha URL inline tugma
MAX_KEYBOARD_ROWS = 10      # Telegram cheklovi: inline klaviatura 10 qator
REACTIONS_PER_ROW = 5
BUTTONS_PER_ROW_WIDE = 2    # 4 tadan ko'p tugma bo'lsa — 2 tadan qatorga

# Telegram cheklovi: tugma yozuvi 64, URL 256 belgigacha.
BTN_TEXT_MAX = 64
BTN_URL_MAX = 256

_ENH_KEY = "enh"

TYPE_LABELS = {
    "text": "📝 Matn", "photo": "🖼 Rasm", "video": "🎬 Video",
    "document": "📄 Hujjat", "audio": "🎵 Audio", "voice": "🎙 Ovozli",
    "sticker": "😀 Stiker", "album": "🖼 Albom", "animation": "🎞 GIF",
}

# Kirishdagi majburiy eslatma — bot kanalda admin bo'lmasa post chiqmaydi.
# Bu matn foydalanuvchiga ENG BIRINCHI xabarda ko'rsatiladi.
# Haqiqiy matnlar locales/translations.py da (uz/ru); quyidagi o'zgaruvchilar
# faqat orqaga moslik (eski importlar) uchun o'zbekcha nusxada saqlanadi.
def _view_lang(context, lang: str | None = None) -> str:
    """View ichki til origini: aniq berilmasa ``get_lang(context)`` dan olinadi."""
    return lang if lang else get_lang(context)


ADMIN_NOTICE = get_text("enh_notice_admin", "uz")
POST_REQUEST_LINE = get_text("enh_post_request", "uz")

# ============================================================
# TAYYOR URL TUGMA SHABLONLARI (presets)
# ============================================================
# Foydalanuvchi shablonni tanlasa, bot FAQAT havolani so'raydi — tugma
# yozuvi shablondan avtomatik olinadi.
# Matnlar translations.py dagi enh_preset{1..3}_title/text kalitlaridan
# olinadi (uz/ru); URL_PRESETS — o'zbekcha (orqaga moslik) kanonik ro'yxat.
URL_PRESETS = (
    {
        "id": "join_channel", "icon": "📢", "num": "1",
        "title": "Kanalga a'zo bo'lish", "text": "📢 Kanalga a'zo bo'lish",
        "hint": "https://t.me/kanal_ismi",
    },
    {
        "id": "join_group", "icon": "💬", "num": "2",
        "title": "Guruhga qo'shilish", "text": "💬 Guruhga qo'shilish",
        "hint": "https://t.me/guruh_ismi",
    },
    {
        "id": "open_bot", "icon": "🤖", "num": "3",
        "title": "Botga o'tish", "text": "🤖 Botga o'tish",
        "hint": "https://t.me/bot_ismi",
    },
)


def get_url_presets(lang: str = "uz") -> tuple:
    """Shablonlarni foydalanuvchi tilida qaytaradi (sarlavha/yozuv tarjima (uz/ru)).

    ``hint``/``icon``/``num`` tilga bog'liq emas. ``lang="uz"`` da
    :data:`URL_PRESETS` bilan bir xil qiymat qaytariladi.
    """
    presets = []
    for i, p in enumerate(URL_PRESETS, 1):
        presets.append({
            "id": p["id"], "icon": p["icon"], "num": p["num"],
            "title": get_text(f"enh_preset{i}_title", lang),
            "text": get_text(f"enh_preset{i}_text", lang),
            "hint": p["hint"],
        })
    return tuple(presets)


# ============================================================
# YORDAMCHI FUNKSIYALAR (sof logika — unit-testlanadigan)
# ============================================================

def intro_text(lang: str = "uz") -> str:
    """Kirish xabari: AVVAL admin eslatmasi, keyin postni so'rash (uz/ru)."""
    return (
        f"{get_text('enh_notice_admin', lang)}\n\n"
        f"{get_text('enh_post_request', lang)}\n\n"
        f"{get_text('enh_intro_features', lang)}"
    )


def nav_row(back_callback: str = "enh:screen:hub", lang: str = "uz") -> list:
    """Har ekranda doim turadigan navigatsiya qatori: Orqaga + Bekor qilish (uz/ru).

    "⬅️ Orqaga" / "⬅️ Назад" va "❌ Bekor qilish" / "❌ Отмена" —
    translations dagi umumiy btn_back/btn_cancel kalitlaridan.
    """
    return [
        InlineKeyboardButton(get_text("btn_back", lang), callback_data=cb(back_callback)),
        InlineKeyboardButton(get_text("btn_cancel", lang), callback_data="enh:cancel"),
    ]


def parse_button_line(text: str) -> "dict | None":
    """URL tugma qatorini (matn + havola) ga ajratadi.

    Qo'llab-quvvatlanadigan formatlar:
      • "Batafsil - https://sayt.uz"      (new_post tezkor formati)
      • "Batafsil | https://sayt.uz"      (pending edit formati)
      • "Kanalim - @kanalim", "Sayt - example.uz"
      • faqat "@kanalim" / "https://sayt.uz" → yozuv avtomatik tanlanadi
    Yaroqsiz bo'lsa None qaytadi.
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw or "\n" in raw:
        return None

    one_liner = parse_url_button_line(raw)
    if one_liner:
        title, url = one_liner
        return {"text": title, "url": url}

    if "|" in raw:
        left, right = raw.split("|", 1)
        title, link = left.strip(), right.strip()
        url = normalize_button_url(link)
        if title and url:
            return {"text": title, "url": url}
        return None

    # Faqat havola/username — yozuvni uning o'zidan yasaymiz.
    url = normalize_button_url(raw)
    if url:
        return {"text": _label_from_url(url), "url": url}
    return None


def normalize_button_url(link: str) -> "str | None":
    """Havolani inline tugma uchun URL'ga keltiradi (new_post bilan bir xil qoidalar)."""
    return _np_normalize_button_url(link)


def sanitize_button(parsed: "dict | None") -> "dict | None":
    """Tugmani Telegram cheklovlariga moslaydi (yozuv ≤64, URL ≤256)."""
    if not parsed or not parsed.get("url"):
        return None
    url = str(parsed["url"]).strip()
    if not url or len(url) > BTN_URL_MAX:
        return None
    return {"text": btn_label(parsed.get("text"), "🔗 Havola", max_length=BTN_TEXT_MAX), "url": url}


def _label_from_url(url: str) -> str:
    """URL bo'yicha tugma yozuvini yasaydi: t.me/x → @x; sayt.uz → Sayt.uz."""
    m = re.match(r"https?://(?:www\.)?t\.me/([A-Za-z0-9_]+)", url or "")
    if m:
        return f"@{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?([^/:?#]+)", url or "")
    if m:
        return btn_label(m.group(1), "🔗 Havola", max_length=BTN_TEXT_MAX)
    return "🔗 Havola"


def get_url_preset(index, lang: str = "uz") -> "dict | None":
    """Shablon indeksini (int/str) shablon dict'iga aylantiradi; yo'q bo'lsa None.

    ``lang`` — shablon sarlavhasi/yozuvining tili (uz/ru).
    """
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    presets = get_url_presets(lang)
    if 0 <= idx < len(presets):
        return presets[idx]
    return None


def build_preset_button(index, link: str, lang: str = "uz") -> "dict | None":
    """Tayyor shablon + havola → URL tugma. Havola/shablon yaroqsiz bo'lsa None.

    >>> build_preset_button(0, "@kanalim")
    {'text': '📢 Kanalga a'zo bo'lish', 'url': 'https://t.me/kanalim'}
    """
    preset = get_url_preset(index, lang)
    if not preset:
        return None
    url = normalize_button_url((link or "").strip())
    if not url:
        return None
    return sanitize_button({"text": preset["text"], "url": url})


def parse_button_input(text: str, preset_index=None, lang: str = "uz") -> "dict | None":
    """Foydalanuvchi kiritgan qatorni tugmaga aylantiradi.

    Shablon tanlangan bo'lsa AVVAL faqat havola sifatida urilib ko'riladi
    (yozuv shablondan olinadi); agar qator to'liq formatda bo'lsa
    (``Yozuv - https://...``) — u ustun keladi.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if preset_index is not None:
        preset = build_preset_button(preset_index, raw, lang)
        if preset:
            return preset
    return sanitize_button(parse_button_line(raw))


def reaction_key(emoji: str) -> str:
    """Emoji uchun taqqoslash kaliti (Variation Selector'lar e'tiborga olinmaydi)."""
    return strip_variation_selector(emoji)


def add_unique_emoji(current: list, emojis: list, max_count: int = MAX_ENH_REACTIONS) -> "tuple[list, int]":
    """Ro'yxatga takrorlanmas emoji(lar) qo'shadi. (yangi_ro'yxat, qo'shilgan_soni).

    ❤️ va ❤ bitta reaksiya hisoblanadi (Variation Selector farqi yo'qoladi).
    """
    result = list(current or [])
    seen = {reaction_key(e) for e in result}
    added = 0
    for e in emojis or []:
        if not e:
            continue
        key = reaction_key(e)
        if key in seen:
            continue
        if len(result) >= max_count:
            break
        result.append(e)
        seen.add(key)
        added += 1
    return result, added


def apply_reaction_batch(current: list, text: str, max_count: int = MAX_ENH_REACTIONS) -> dict:
    """Bir xabardagi BARCHA emojilarni probel bo'yicha ajratib reaksiyaga qo'shadi.

    Masalan ``"👍 ❤️ 🔥 salom 👍"`` → ``👍 ❤️ 🔥`` qo'shiladi (takror tashlanadi).

    Qaytaradi::

        {"reactions": [...yangi ro'yxat...], "added": int, "tokens": [...],
         "duplicates": [...], "overflow": [...]}
    """
    tokens = extract_emoji_tokens(text, max_count=64)
    new_list, added = add_unique_emoji(current, tokens, max_count=max_count)
    have = {reaction_key(e) for e in (current or [])}
    final = {reaction_key(e) for e in new_list}
    duplicates, overflow = [], []
    for token in tokens:
        key = reaction_key(token)
        if key in have:
            duplicates.append(token)
        elif key not in final:
            overflow.append(token)
    return {
        "reactions": new_list,
        "added": added,
        "tokens": tokens,
        "duplicates": duplicates,
        "overflow": overflow,
    }


def build_enhancer_rows(buttons: list, reactions: list, post_id: int = None,
                       preview: bool = False) -> list:
    """Post ostidagi InlineKeyboardButton qatorlarini tuzadi.

    - URL tugmalar: 4 tadan ko'p bo'lsa 2 tadan qatorga joylanadi (Telegram
      10 qator cheklovi reaksiya qatori bilan birga sig'ishi uchun).
    - Reaksiyalar: har qatorda 5 tagacha. ``post_id`` bilan haqiqiy
      ``react:`` hisoblagich callback'lari, preview'da esa neytral tugmalar.
    - Jami qatorlar qat'iy 10 ta bilan chegaralanadi.
    """
    rows = []
    url_buttons = []
    for b in (buttons or [])[:MAX_ENH_BUTTONS]:
        if isinstance(b, dict):
            label, url = b.get("text"), b.get("url")
        else:
            label, url = b, None
        if not url:
            continue
        url_buttons.append(
            InlineKeyboardButton(btn_label(label, "🔗 Havola", max_length=BTN_TEXT_MAX), url=url)
        )
    per_row = 1 if len(url_buttons) <= 4 else BUTTONS_PER_ROW_WIDE
    for i in range(0, len(url_buttons), per_row):
        rows.append(url_buttons[i:i + per_row])

    # Reaksiya tugmalari (scheduler bilan bir xil logika — kanondan
    # tashqari qo'lda kiritilgan emojilar ham ishlaydi, 5 tadan qatorlarga
    # bo'linadi). Umumiy yordamchi keyboards.inline.build_reaction_button_rows.
    from keyboards.inline import build_reaction_button_rows
    react_rows = build_reaction_button_rows(
        post_id,
        (reactions or [])[:MAX_ENH_REACTIONS],
        per_row=REACTIONS_PER_ROW,
        preview=(preview or not post_id),
    )
    rows.extend(react_rows)

    return rows[:MAX_KEYBOARD_ROWS]


def build_enhancer_markup(buttons: list, reactions: list, post_id: int = None,
                         preview: bool = False, extra_rows: list = None):
    """Enhancer tugmalari; ``extra_rows`` — masalan reklamaning URL tugmasi."""
    rows = build_enhancer_rows(buttons, reactions, post_id=post_id, preview=preview)
    for row in (extra_rows or []):
        if row and len(rows) < MAX_KEYBOARD_ROWS:
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None


def summarize_selection(enh: dict, lang: str = "uz") -> str:
    """Hub kartasi uchun tanlovlar satri (reaksiyalar/tugmalar soni) (uz/ru)."""
    reactions = enh.get("reactions") or []
    buttons = enh.get("buttons") or []
    return get_text(
        "enh_summary", lang,
        rn=len(reactions), maxr=MAX_ENH_REACTIONS,
        emojis=(" — " + " ".join(reactions)) if reactions else "",
        bn=len(buttons), maxb=MAX_ENH_BUTTONS,
    )


# ============================================================
# PAYLOAD VA EKRANLAR
# ============================================================

def _fresh_enh() -> dict:
    """Bo'sh enhancer holati (barcha kalitlar bir joyda — KeyError bo'lmasligi uchun)."""
    return {
        "step": "content", "post": None, "reactions": [], "buttons": [],
        "hub_msg_id": None, "btn_edit": None, "channels": [], "ch_idx": None,
        "btn_preset": None, "_btn_pending_idx": None, "sent_channel": "",
        "success_msg_id": None, "preview_msg_id": None, "preview_type": None,
        "preview_extra_ids": [],
        # ✨ PRO 2-bosqichli AI audit: None = hali aniqlanmagan (DB so'rovi
        # bir marta qilinadi va shu yerda keshlanadi).
        "is_pro": None,
    }


def _payload(context) -> dict:
    enh = context.user_data.get(_ENH_KEY)
    if not isinstance(enh, dict):
        enh = _fresh_enh()
        context.user_data[_ENH_KEY] = enh
    else:
        # Eski sessiyalardan kelgan yarim to'ldirilgan dict'lar uchun zaxira.
        for key, value in _fresh_enh().items():
            enh.setdefault(key, value)
    return enh


def _post_line(enh: dict, lang: str = "uz") -> str:
    """Post turi/matni qisqacha satri (uz/ru). Turlar np_type_* kalitlaridan."""
    post = enh.get("post") or {}
    ptype = post.get("type") or "text"
    content = post.get("content") or ""
    type_key = f"np_type_{ptype}"
    type_label = get_text(type_key, lang)
    if type_label == type_key:  # noma'lum tur — universal fallback
        type_label = get_text("np_type_unknown", lang)
    line = get_text("enh_post_line_type", lang, type=type_label)
    if ptype == "album":
        items = parse_album_items(post.get("file_id"))
        if items:
            line += get_text("enh_post_line_album_count", lang, n=len(items))
    if content:
        preview = content[:220] + ("…" if len(content) > 220 else "")
        line += get_text("enh_post_line_text", lang, preview=safe_html(preview))
    else:
        line += get_text("enh_post_line_no_text", lang)
    return line


def _auditable_text(enh: dict) -> str:
    """✨ PRO AI audit uchun yaroqli matn (faqat matnli postlar).

    Media/albom postlarida audit ishlamaydi — post mazmuni (rasm/video
    fayl_id) o'zgarmasligi kerak, matn esa caption sifatida kanal
    formatlash qoidalariga bog'liq. Bo'sh satr = "audit qilinmaydi".
    """
    post = (enh or {}).get("post") or {}
    if str(post.get("type") or "") != "text":
        return ""
    return str(post.get("content") or "").strip()


async def _resolve_is_pro(user_id: int, enh: dict) -> bool:
    """PRO holatini aniqlaydi va enhancer holatida keshlaydi.

    Adminlar ham PRO imkoniyatlaridan foydalanadi (boshqa oqimlardagi
    kabi). DB xatosida ``False`` qaytadi — audit tugmasi ko'rinmaydi,
    oqim to'xtab qolmaydi.
    """
    if user_id in ADMIN_IDS_SET:
        enh["is_pro"] = True
        return True
    cached = enh.get("is_pro")
    if cached is not None:
        return bool(cached)
    try:
        is_pro = bool(await db.run_db(db.is_premium, user_id))
    except Exception:  # pragma: no cover - himoya
        is_pro = False
    enh["is_pro"] = is_pro
    return is_pro


def _hub_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    text = get_text(
        "enh_hub_title", lang,
        post=_post_line(enh, lang),
        summary=summarize_selection(enh, lang),
        note=watermark_note,
        notice=get_text("enh_notice_admin", lang),
    )
    r_n = len(enh.get("reactions") or [])
    b_n = len(enh.get("buttons") or [])
    keyboard = [
        [InlineKeyboardButton(
            get_text("enh_hub_btn_reacts", lang, n=r_n, max=MAX_ENH_REACTIONS),
            callback_data="enh:screen:react")],
        [InlineKeyboardButton(
            get_text("enh_hub_btn_buttons", lang, n=b_n, max=MAX_ENH_BUTTONS),
            callback_data="enh:screen:btns")],
        [
            InlineKeyboardButton(get_text("enh_btn_preview", lang), callback_data="enh:preview"),
            InlineKeyboardButton(get_text("enh_btn_send_channel", lang), callback_data="enh:screen:channel"),
        ],
        [
            InlineKeyboardButton(get_text("enh_btn_replace", lang), callback_data="enh:replace"),
            InlineKeyboardButton(get_text("btn_cancel", lang), callback_data="enh:cancel"),
        ],
    ]
    # ✨ PRO: 2-bosqichli AI audit tugmasi — FAQAT PRO foydalanuvchilarda va
    # faqat matnli postda ko'rinadi. Post matni enhancer tomonidan hech qachon
    # O'ZICHA o'zgartirilmaydi: audit faqat foydalanuvchi shu tugmani bosganda
    # ishlaydi (yuqoridagi "ASL MATNGA TEKILMAYDI" kafolati saqlanadi).
    if enh.get("is_pro") and _auditable_text(enh):
        keyboard.insert(2, [InlineKeyboardButton(
            get_text("enh_btn_ai_audit", lang), callback_data="enh:audit")])
    return text, InlineKeyboardMarkup(keyboard[:MAX_KEYBOARD_ROWS])


def _react_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    selected = enh.get("reactions") or []
    sel_line = " ".join(selected) if selected else get_text("enh_react_none", lang)
    left = max(0, MAX_ENH_REACTIONS - len(selected))
    text = get_text(
        "enh_react_title", lang,
        n=len(selected), max=MAX_ENH_REACTIONS, sel=sel_line, left=left,
    )
    rows = []
    row = []
    for emoji in REACTION_POOL:
        mark = " ✅" if any(reaction_key(emoji) == reaction_key(e) for e in selected) else ""
        row.append(InlineKeyboardButton(f"{emoji}{mark}", callback_data=cb(f"enh:rtgl:{emoji}")))
        if len(row) == REACTIONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_label = (
        get_text("enh_react_done_count", lang, n=len(selected))
        if selected else get_text("enh_react_done", lang)
    )
    rows.append([InlineKeyboardButton(done_label, callback_data="enh:react:done")])
    extra_row = [InlineKeyboardButton(get_text("enh_btn_preview", lang), callback_data="enh:preview")]
    if selected:
        extra_row.append(InlineKeyboardButton(
            get_text("enh_btn_clear", lang), callback_data="enh:react:clear"))
    rows.append(extra_row)
    rows.append(nav_row("enh:screen:hub", lang))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _btn_entry_rows(buttons: list, lang: str = "uz") -> list:
    """Mavjud URL tugmalar ro'yxati (10 qator chegarasiga sig'adigan tartibda)."""

    def entry(i, b):
        label = get_text(
            "enh_btn_entry_edit", lang, num=i + 1,
            text=btn_label(b.get('text'), get_text("enh_btn_fallback", lang), max_length=20),
        )
        return [
            InlineKeyboardButton(label, callback_data=cb(f"enh:btn:edit:{i}")),
            InlineKeyboardButton("❌", callback_data=cb(f"enh:btn:del:{i}")),
        ]

    rows = []
    if len(buttons) <= 2:
        for i, b in enumerate(buttons):
            rows.append(entry(i, b))
    else:
        # 3-10 tugma: ikkitadan birlashtiramiz (maks. 5 qator)
        for i in range(0, len(buttons), 2):
            merged = entry(i, buttons[i])
            if i + 1 < len(buttons):
                merged += entry(i + 1, buttons[i + 1])
            rows.append(merged)
    return rows


def _preset_rows(per_row: int = 2, lang: str = "uz") -> list:
    """Tayyor URL tugma shablonlari qatorlari (uz/ru)."""
    buttons = [
        InlineKeyboardButton(f"{p['icon']} {p['num']}. {p['title']}", callback_data=cb(f"enh:preset:{i}"))
        for i, p in enumerate(get_url_presets(lang))
    ]
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _btns_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    buttons = enh.get("buttons") or []
    if buttons:
        marks = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟"
        fallback = get_text("enh_btn_fallback", lang)
        lines = [
            get_text(
                "enh_btns_line", lang, mark=marks[i],
                text=html_escape(b.get('text') or fallback),
                url=html_escape(b.get('url') or ''),
            )
            for i, b in enumerate(buttons)
        ]
        body = "\n".join(lines)
    else:
        body = get_text("enh_btns_empty", lang)
    text = get_text(
        "enh_btns_title", lang, n=len(buttons), max=MAX_ENH_BUTTONS, body=body,
    )
    entry_rows = _btn_entry_rows(buttons, lang)
    rows = list(entry_rows)

    add_row = [InlineKeyboardButton(get_text("enh_btn_add_new", lang), callback_data="enh:btn:add")]
    if buttons:
        add_row.append(InlineKeyboardButton(
            get_text("enh_btn_clear", lang), callback_data="enh:btn:clear"))
    rows.append(add_row)

    # Shablonlar: ro'yxat qisqa bo'lganda to'g'ridan-to'g'ri shu ekranda,
    # aks holda "➕ Yangi tugma qo'shish" ekranida (10 qator chegarasi uchun).
    if len(buttons) < MAX_ENH_BUTTONS and len(entry_rows) <= 3:
        rows.extend(_preset_rows(per_row=2, lang=lang))
        rows[-1].append(InlineKeyboardButton(
            get_text("enh_btn_manual", lang), callback_data="enh:btn:manual"))

    rows.append([InlineKeyboardButton(
        get_text("enh_btn_confirm_send", lang), callback_data="enh:screen:channel")])
    rows.append(nav_row("enh:screen:hub", lang))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _btn_add_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    n = len(enh.get("buttons") or [])
    text = get_text("enh_btn_add_title", lang, n=n, max=MAX_ENH_BUTTONS)
    rows = [[InlineKeyboardButton(f"{p['icon']} {p['num']}. {p['title']}",
                                  callback_data=cb(f"enh:preset:{i}"))]
            for i, p in enumerate(get_url_presets(lang))]
    rows.append([InlineKeyboardButton(
        get_text("enh_btn_manual", lang), callback_data="enh:btn:manual")])
    rows.append(nav_row("enh:screen:btns", lang))
    return text, InlineKeyboardMarkup(rows)


def _channel_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    channels = enh.get("channels") or []
    text = get_text(
        "enh_channel_title", lang, n=len(channels),
        notice=get_text("enh_notice_admin", lang),
    )
    rows = []
    visible = channels[:16]
    row = []
    ch_fallback = get_text("enh_channel_fallback", lang)
    for idx, (ch_id, ch_title) in enumerate(visible):
        row.append(InlineKeyboardButton(
            f"📢 {btn_label(ch_title, ch_fallback, max_length=24)}",
            callback_data=cb(f"enh:send:{idx}")))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if len(channels) > len(visible):
        rows.append([InlineKeyboardButton(
            get_text("enh_channels_more", lang, n=len(channels) - len(visible)),
            callback_data="enh:noop")])
    # Post allaqachon yuborilgan bo'lsa, "Orqaga" muvaffaqiyat ekraniga qaytadi
    # (editor hubga emas) — muvaffaqiyat xabari asosiy holat bo'lib qoladi.
    back = "enh:screen:sent" if enh.get("sent_channel") else "enh:screen:hub"
    rows.append(nav_row(back, lang))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _confirm_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    channels = enh.get("channels") or []
    idx = enh.get("ch_idx")
    if not isinstance(idx, int) or not (0 <= idx < len(channels)):
        return (
            get_text("enh_confirm_no_channel", lang),
            InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    get_text("enh_btn_channel_list", lang),
                    callback_data="enh:screen:channel")],
                nav_row("enh:screen:hub", lang),
            ]),
        )
    ch_id, ch_title = channels[idx][:2]
    ch_name = html_escape(ch_title or get_text("enh_channel_fallback", lang))
    text = get_text(
        "enh_confirm_title", lang,
        channel=ch_name,
        post=_post_line(enh, lang),
        summary=summarize_selection(enh, lang),
        note=watermark_note,
    )
    keyboard = [
        [InlineKeyboardButton(get_text("enh_btn_confirm_yes", lang), callback_data="enh:confirm_send")],
        [InlineKeyboardButton(get_text("enh_btn_preview_first", lang), callback_data="enh:preview")],
        nav_row("enh:screen:channel", lang),
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _success_view(ch_title: str = "", lang: str = "uz") -> tuple:
    """Muvaffaqiyat ekrani (uz/ru): [🏠 Asosiy menyu / 🏠 Главное меню] ..."""
    where = (
        get_text("enh_success_where", lang, channel=html_escape(ch_title))
        if ch_title else ""
    )
    text = get_text("enh_success_text", lang, where=where)
    keyboard = [
        [InlineKeyboardButton(get_text("enh_btn_home", lang), callback_data="enh:home")],
        [
            InlineKeyboardButton(get_text("enh_btn_other_channel", lang), callback_data="enh:screen:channel"),
            InlineKeyboardButton(get_text("enh_btn_preview", lang), callback_data="enh:preview"),
        ],
        [
            InlineKeyboardButton(get_text("enh_btn_new_post", lang), callback_data="enh:again"),
            InlineKeyboardButton(get_text("enh_btn_finish", lang), callback_data="enh:cancel"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _sent_view(context, watermark_note: str = "", lang: str | None = None) -> tuple:
    enh = _payload(context)
    lang = _view_lang(context, lang)
    return _success_view(enh.get("sent_channel") or "", lang)


_VIEWS = {
    "hub": _hub_view, "react": _react_view, "btns": _btns_view,
    "btn_add": _btn_add_view, "channel": _channel_view,
    "confirm": _confirm_view, "sent": _sent_view,
}


async def _render(context, chat_id: int, target_msg=None, watermark_note: str = ""):
    """Boshqaruv panelini har safar chatning eng pastiga chiqaradi.

    Avvalgi versiyada hub xabari ``edit_message_text`` bilan o'zgartirilardi.
    Telegram xabarni tahrirlashda uning joylashuvi o'zgarmaydi, shu sababli
    foydalanuvchi yangi reaksiya/tugma qo'shganda panel tepada qolib ketardi.
    Panelni o'chirib, oddiy yangi xabar sifatida yuborish uni doim eng pastga
    qo'yadi. ``target_msg`` faqat eski API bilan moslik uchun qoldirilgan —
    panel foydalanuvchi xabariga reply qilinmaydi.

    ``success_msg_id`` — kanalga yuborilgandan keyingi muvaffaqiyat xabari.
    U hech qachon panel sifatida O'CHIRILMAYDI: foydalanuvchi boshqa kanalga
    yoki boshqa amalga o'tsa ham post yuklangani haqidagi tasdiq saqlanib qoladi.
    """
    enh = _payload(context)
    lang = get_lang(context)
    step = enh.get("step", "hub")
    view = _VIEWS.get(step, _hub_view)
    text, markup = view(context, watermark_note, lang)

    old_id = enh.get("hub_msg_id")
    if old_id and old_id == enh.get("success_msg_id"):
        # Eski sessiyalarda muvaffaqiyat xabari hub_msg_id'da saqlanib qolgan
        # bo'lishi mumkin — uni panel yangilashda o'chirmaymiz.
        old_id = None
    if old_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except TelegramError:
            # Xabar o'chirilgan yoki muddati o'tgan bo'lishi mumkin.
            pass
        finally:
            enh["hub_msg_id"] = None

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=text[:4090],
        reply_markup=markup,
        parse_mode="HTML",
    )
    enh["hub_msg_id"] = msg.message_id


async def _plan_note(user_id: int, lang: str = "uz") -> str:
    """Watermark/via holati haqida qator (bepul foydalanuvchiga ogohlantirish) (uz/ru)."""
    if user_id in ADMIN_IDS_SET:
        return get_text("enh_note_admin", lang)
    try:
        is_pro = await db.run_db(db.is_premium, user_id)
    except Exception:
        is_pro = False
    if is_pro:
        return get_text("enh_note_pro", lang)
    clean = BOT_USERNAME if str(BOT_USERNAME).startswith("@") else f"@{BOT_USERNAME}"
    return get_text("enh_note_free", lang, bot=clean)


# ============================================================
# KIRISH NUQTASI (⚙️ Qo'shimcha funksiyalar menyusidan)
# ============================================================

async def post_enhancer_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """"⚙️ Qo'shimcha funksiyalar" menyusidan ✨ Postga Tugma & Reaksiya qo'shish."""
    query = update.callback_query
    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
        msg = query.message
        try:
            await msg.delete()
        except Exception:
            pass
    else:
        msg = update.message

    clear_fsm_data(context)
    lang = get_lang(context)
    enh = _payload(context)
    enh.update(_fresh_enh())
    # ENG BIRINCHI xabar: admin eslatmasi + postni so'rash (foydalanuvchi tilida).
    await msg.reply_text(
        intro_text(lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return ENH_POST


# ============================================================
# XABAR QABUL QILISH (post / emoji / tugma kiritish)
# ============================================================

async def enh_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    chat_id = msg.chat_id
    enh = _payload(context)
    step = enh.get("step", "content")

    if step == "content":
        return await _capture_post(update, context, msg, enh)
    if step == "react":
        return await _emoji_text_step(update, context, msg, enh, chat_id)
    if step == "btn_input":
        return await _button_text_step(update, context, msg, enh, chat_id)

    # Hub/boshqa ekranlarda matn yuborilsa — yo'nalish eslatib turiladi.
    await msg.reply_text(
        get_text("enh_use_buttons", get_lang(context)),
        parse_mode="HTML",
    )
    return ENH_POST


async def _capture_post(update, context, msg, enh):
    user_id = update.effective_user.id
    chat_id = msg.chat_id
    lang = get_lang(context)
    if msg.media_group_id:
        item = _media_item_from_message(msg)
        if not item or item["type"] in ("voice", "sticker"):
            await msg.reply_text(get_text("enh_album_reject", lang))
            return ENH_POST
        _purge_stale_albums()
        key = (user_id, msg.media_group_id)
        buf = _ALBUM_BUFFERS.setdefault(key, {"items": [], "seq": 0, "ts": time.time()})
        if len(buf["items"]) < 10:
            buf["items"].append(item)
        buf["seq"] += 1
        buf["ts"] = time.time()
        my_seq = buf["seq"]
        await asyncio.sleep(0)
        await asyncio.sleep(_ALBUM_WAIT_SECONDS)
        current = _ALBUM_BUFFERS.get(key)
        if not current or current.get("seq") != my_seq:
            return ENH_POST
        items = _ALBUM_BUFFERS.pop(key, {}).get("items") or [item]
        caption = next((i.get("caption") or "" for i in items if i.get("caption")), "")
        if len(items) == 1:
            _apply_single_media(context, items[0])
        else:
            context.user_data["post_type"] = "album"
            context.user_data["file_id"] = json.dumps(items, ensure_ascii=False)
            context.user_data["content"] = caption
        enh["post"] = {
            "type": context.user_data["post_type"],
            "file_id": context.user_data["file_id"],
            "content": context.user_data["content"],
        }
    else:
        item = _media_item_from_message(msg)
        if item:
            _apply_single_media(context, item)
            enh["post"] = {
                "type": context.user_data["post_type"],
                "file_id": context.user_data["file_id"],
                "content": context.user_data["content"],
            }
        else:
            text = (msg.text or "").strip()
            if not text:
                await msg.reply_text(get_text("enh_empty_msg", lang))
                return ENH_POST
            enh["post"] = {"type": "text", "file_id": None, "content": msg.text or ""}

    enh["step"] = "hub"
    enh["hub_msg_id"] = None  # yangi hub xabari (post bilan bog'liq)
    await _drop_preview(context, chat_id, enh)  # eski post prevyusi eskirgan
    # ✨ PRO bo'lsa hub'da "AI audit (PRO)" tugmasi ko'rinadi (bitta DB so'rovi,
    # natija enhancer holatida keshlanadi).
    await _resolve_is_pro(user_id, enh)
    note = await _plan_note(user_id, lang)
    await _render(context, chat_id, target_msg=msg, watermark_note=note)
    # Tahrirlash vaqtida post ko'rsatilmaydi; preview alohida tugma bilan ochiladi.
    return ENH_POST


async def _emoji_text_step(update, context, msg, enh, chat_id):
    """Reaksiya matnini qabul qiladi; post previewsi bu bosqichda yuborilmaydi (uz/ru)."""
    lang = get_lang(context)
    raw_text = msg.text or msg.caption or ""
    res = apply_reaction_batch(enh.get("reactions"), raw_text)
    if res["tokens"]:
        enh["reactions"] = res["reactions"]
        total = len(res["reactions"])
        sel_line = " ".join(res["reactions"]) if res["reactions"] else "—"
        if res["added"]:
            extra = ""
            if res["overflow"]:
                extra += get_text(
                    "enh_react_overflow_part", lang,
                    max=MAX_ENH_REACTIONS, items=" ".join(res['overflow']),
                )
            if res["duplicates"]:
                extra += get_text("enh_react_dups_part", lang)
            await msg.reply_text(
                get_text(
                    "enh_react_saved", lang,
                    sel=sel_line, total=total, max=MAX_ENH_REACTIONS, extra=extra,
                ),
                parse_mode="HTML",
            )
        elif res["duplicates"] and not res["overflow"]:
            await msg.reply_text(
                get_text(
                    "enh_react_dups", lang,
                    items=" ".join(res['duplicates']),
                    total=total, max=MAX_ENH_REACTIONS,
                ),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                get_text("enh_react_full", lang, max=MAX_ENH_REACTIONS),
                parse_mode="HTML",
            )
    else:
        low = raw_text.strip().lower()
        # "Davom etish" / "Tozalash" — uz/ru matnli buyruqlar sirf qulaylik uchun.
        if low in ("done", "tayyor", "✅", "davom", "keyingisi",
                   "готово", "дальше", "следующий", "продолжить"):
            enh["step"] = "btns"
        elif low in ("yo'q", "yoq", "bekor", "tozalash",
                     "нет", "отмена", "очистить"):
            enh["reactions"] = []
            enh["step"] = "hub"
        else:
            await msg.reply_text(
                get_text("enh_react_hint_msg", lang),
                parse_mode="HTML",
            )
    await _render(context, chat_id)
    return ENH_POST


async def _button_text_step(update, context, msg, enh, chat_id):
    """URL tugma qadami: shablon (faqat havola) yoki qo'lda kiritish (uz/ru)."""
    lang = get_lang(context)
    text = (msg.text or msg.caption or "").strip()
    preset_idx = enh.get("btn_preset")
    if not text or text.lower() in ("yo'q", "yoq", "bekor", "orqaga",
                                    "нет", "отмена", "назад"):
        enh["btn_preset"] = None
        enh["step"] = "btns"
        await _render(context, chat_id)
        return ENH_POST

    parsed = parse_button_input(text, preset_idx, lang)
    if not parsed:
        preset = get_url_preset(preset_idx, lang)
        if preset:
            await msg.reply_text(
                get_text("enh_bad_link", lang, hint=preset['hint']),
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                get_text("enh_bad_format", lang),
                parse_mode="HTML",
            )
        return ENH_POST

    buttons = list(enh.get("buttons") or [])
    idx = enh.get("_btn_pending_idx")
    editing = isinstance(idx, int) and 0 <= idx < len(buttons)
    if editing:
        buttons[idx] = parsed  # tahrirlash
    else:
        if len(buttons) >= MAX_ENH_BUTTONS:
            await msg.reply_text(
                get_text("enh_btn_limit_reached", lang, max=MAX_ENH_BUTTONS),
                parse_mode="HTML",
            )
            return ENH_POST
        buttons.append(parsed)
    enh["buttons"] = buttons
    enh["step"] = "btns"
    enh["btn_preset"] = None
    enh.pop("_btn_pending_idx", None)
    verb = get_text("enh_btn_verb_updated" if editing else "enh_btn_verb_saved", lang)
    await msg.reply_text(
        get_text(
            "enh_btn_saved", lang, verb=verb,
            text=html_escape(parsed['text']), url=html_escape(parsed['url']),
        ),
        parse_mode="HTML",
    )
    await _render(context, chat_id)
    return ENH_POST


# ============================================================
# INLINE CALLBACK YO'NALTIRUVCHISI (enh:*)
# ============================================================

async def _answer(query, text: str = None, alert: bool = False):
    """query.answer() ni xatosiz chaqiradi (ikki marta bosilganda ham)."""
    try:
        if text:
            await query.answer(text, show_alert=alert)
        else:
            await query.answer()
    except Exception:
        pass


async def _audit_post_step(update, context, query, enh):
    """✨ AI audit (PRO): post matnini 2-bosqichli auditor orqali yaxshilaydi.

    Oqim (utils.ai_agent'dagi PRO auditor pipeline'i bilan bir xil):
      1-bosqich — foydalanuvchi yuborgan/AI generatsiya qilgan post matni;
      2-bosqich — ``_AUDIT_PRO_SYSTEM`` tizim prompti bilan ikkinchi AI
      so'rovi: auditor kuchsiz joylarni bartaraf etib, TAYYOR yakuniy
      variantni qaytaradi va post shu variant bilan almashtiriladi.

    XAVFSIZLIK: 2-bosqich timeout/tarmoq uzilishi/yaroqsiz javob bersa
    (zaxira modellardan keyin ham) — ASL post o'zgarmaydi, foydalanuvchiga
    sabab aytiladi va oqim to'xtab qolmaydi (hub qayta chiziladi).
    """
    lang = get_lang(context)
    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id

    text = _auditable_text(enh)
    if not text:
        await _answer(query, get_text("enh_audit_text_only", lang), alert=True)
        return ENH_POST

    # Tugma faqat PRO'da ko'rinadi, lekin har doim qayta tekshiriladi
    # (eskirgan panel/tarif muddati tugagan holatlar uchun).
    if not await _resolve_is_pro(user_id, enh):
        await _answer(query, get_text("enh_audit_pro_only", lang), alert=True)
        await _render(context, chat_id,
                      watermark_note=await _plan_note(user_id, lang))
        return ENH_POST

    await _answer(query)
    wait_msg = None
    try:
        wait_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=get_text("enh_audit_wait", lang),
            parse_mode="HTML",
        )
    except TelegramError:
        wait_msg = None

    try:
        refined = await ai_agent.refine_post_pro(text, lang=lang)
    except Exception as e:  # pragma: no cover - himoya
        logger.warning("AI audit (enhancer) xatosi: %s", e)
        refined = {"post_text": "", "error": str(e)}
    finally:
        if wait_msg is not None:
            try:
                await context.bot.delete_message(
                    chat_id=chat_id, message_id=wait_msg.message_id)
            except TelegramError:
                pass

    improved = str((refined or {}).get("post_text") or "").strip()
    plan_note = await _plan_note(user_id, lang)

    if not improved:
        # XAVFSIZ fallback: asl post saqlanadi, oqim davom etadi.
        logger.info("AI audit (PRO) natija bermadi — asl post saqlandi (%s)",
                    (refined or {}).get("error"))
        note = "\n".join(x for x in (get_text("enh_audit_fallback", lang), plan_note) if x)
        await _drop_preview(context, chat_id, enh)  # prevyu eskirgan bo'lishi mumkin
        await _render(context, chat_id, watermark_note=note)
        return ENH_POST

    enh["post"]["content"] = improved
    context.user_data["content"] = improved
    note = "\n".join(x for x in (get_text("enh_audit_done", lang), plan_note) if x)
    await _drop_preview(context, chat_id, enh)  # eski prevyu yangi matnga to'g'ri kelmaydi
    await _render(context, chat_id, watermark_note=note)
    return ENH_POST


async def enh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    arg2 = parts[3] if len(parts) > 3 else ""
    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else user_id
    enh = context.user_data.get(_ENH_KEY)

    if action == "noop":
        await _answer(query)
        return ENH_POST

    if not isinstance(enh, dict) or (
        not enh.get("post") and action not in ("cancel", "home", "again")
    ):
        await _answer(query, get_text("enh_session_expired", get_lang(context)), alert=True)
        return ConversationHandler.END

    if action in ("cancel", "home"):
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        lang = get_lang(context)
        clear_fsm_data(context)
        try:
            await query.message.delete()
        except Exception:
            pass
        text = (get_text("enh_home_msg", lang)
                if action == "home"
                else get_text("extras_closed", lang))
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if action == "again":
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        lang = get_lang(context)
        enh.update(_fresh_enh())
        await query.message.reply_text(
            get_text(
                "enh_again_prompt", lang,
                notice=get_text("enh_notice_admin", lang),
            ),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return ENH_POST

    if action == "screen":
        await _answer(query)
        if arg == "sent":
            # Muvaffaqiyat xabari allaqachon saqlab qo'yilgan — faqat joriy
            # pastki panelni yopamiz, yangi takroriy success xabari chiqarmaymiz.
            old_id = enh.get("hub_msg_id")
            if old_id and old_id != enh.get("success_msg_id"):
                try:
                    await context.bot.delete_message(chat_id=chat_id, message_id=old_id)
                except Exception:
                    pass
            enh["hub_msg_id"] = None
            return ENH_POST
        enh["step"] = arg if arg in _VIEWS else "hub"
        if enh["step"] == "channel":
            channels = await db.run_db(db.get_user_channels, user_id)
            if not channels:
                await _answer(
                    query,
                    get_text("enh_no_channels_alert", get_lang(context)),
                    alert=True,
                )
                enh["step"] = "hub"
            else:
                enh["channels"] = channels
        await _render(context, chat_id, target_msg=query.message,
                      watermark_note=await _plan_note(user_id, get_lang(context)))
        return ENH_POST

    if action == "audit":
        # ✨ PRO: 2-bosqichli AI audit (faqat matnli postlar uchun).
        return await _audit_post_step(update, context, query, enh)

    if action == "rtgl":
        await _answer(query)
        emoji = arg
        if not emoji:
            return ENH_POST
        selected = list(enh.get("reactions") or [])
        key = reaction_key(emoji)
        hit = next((e for e in selected if reaction_key(e) == key), None)
        if hit is not None:
            selected.remove(hit)
        elif len(selected) >= MAX_ENH_REACTIONS:
            await _answer(
                query,
                get_text("enh_react_limit_alert", get_lang(context), max=MAX_ENH_REACTIONS),
                alert=True,
            )
            return ENH_POST
        else:
            selected.append(emoji)
        enh["reactions"] = selected
        await _render(context, chat_id)
        return ENH_POST

    if action == "react":
        await _answer(query)
        if arg == "clear":
            enh["reactions"] = []
        # "➡️ Davom etish / URL tugmaga o'tish" — keyingi qadam.
        enh["step"] = "btns" if arg == "done" else "hub"
        await _render(context, chat_id)
        return ENH_POST

    if action == "preset":
        return await _preset_action(update, context, query, arg, enh)

    if action == "btn":
        return await _btn_action(update, context, query, arg, arg2, enh, chat_id)

    if action == "preview":
        await _answer(query)
        # Post faqat foydalanuvchi Preview ni so'raganda chiqadi.
        await _send_preview(context, chat_id, enh, create=True)
        if not enh.get("sent_channel"):
            enh["step"] = "hub"
            await _render(
                context, chat_id,
                watermark_note=await _plan_note(user_id, get_lang(context)),
            )
        # Post yuborilgandan keyin biz muvaffaqiyat xabarini saqlaymiz: preview
        # faqat uning ustiga chiqadi va success ekrani o'chirilmaydi.
        return ENH_POST

    if action == "replace":
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        lang = get_lang(context)
        enh["step"] = "content"
        await query.message.reply_text(
            get_text("enh_replace_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return ENH_POST

    if action == "send":
        await _answer(query)
        try:
            idx = int(arg)
        except (TypeError, ValueError):
            return ENH_POST
        channels = enh.get("channels") or []
        if not (0 <= idx < len(channels)):
            await _answer(
                query,
                get_text("enh_channel_gone_alert", get_lang(context)),
                alert=True,
            )
            return ENH_POST
        enh["ch_idx"] = idx
        enh["step"] = "confirm"
        # Tasdiqlash ekranida post ham albatta ko'rinsin. Agar foydalanuvchi
        # oldin Preview bosgan bo'lsa, mavjud preview qayta ishlatiladi.
        await _send_preview(context, chat_id, enh, create=True)
        await _render(context, chat_id, watermark_note=await _plan_note(user_id, get_lang(context)))
        return ENH_POST

    if action == "confirm_send":
        await _answer(query)
        return await _execute_send(update, context, query, enh)

    return ENH_POST


async def _preset_action(update, context, query, arg, enh):
    """Tayyor shablon tanlandi — endi faqat havola so'raladi (uz/ru)."""
    chat_id = query.message.chat_id if query.message else query.from_user.id
    lang = get_lang(context)
    preset = get_url_preset(arg, lang)
    if not preset:
        await _answer(query, get_text("enh_preset_missing", lang), alert=True)
        return ENH_POST
    if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
        await _answer(
            query, get_text("enh_btn_limit_alert", lang, max=MAX_ENH_BUTTONS), alert=True,
        )
        return ENH_POST
    await _answer(query)
    enh["btn_preset"] = int(arg)
    enh.pop("_btn_pending_idx", None)
    enh["step"] = "btn_input"
    await query.message.reply_text(
        get_text(
            "enh_preset_prompt", lang,
            icon=preset['icon'], num=preset['num'],
            title=preset['title'], hint=preset['hint'],
        ),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(
                get_text("enh_btn_back_cancel", lang), callback_data="enh:screen:btns")]
        ]),
        parse_mode="HTML",
    )
    return ENH_POST


async def _btn_action(update, context, query, arg, arg2, enh, chat_id):
    user_id = query.from_user.id
    lang = get_lang(context)
    if arg == "add":
        await _answer(query)
        if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
            await _answer(
                query, get_text("enh_btn_limit_alert", lang, max=MAX_ENH_BUTTONS), alert=True,
            )
            return ENH_POST
        enh["btn_preset"] = None
        enh["_btn_pending_idx"] = None
        enh["step"] = "btn_add"
        await _render(context, chat_id)
        return ENH_POST

    if arg == "manual":
        await _answer(query)
        if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
            await _answer(
                query, get_text("enh_btn_limit_alert", lang, max=MAX_ENH_BUTTONS), alert=True,
            )
            return ENH_POST
        enh["btn_preset"] = None
        enh["_btn_pending_idx"] = None
        enh["step"] = "btn_input"
        await query.message.reply_text(
            get_text("enh_manual_prompt", lang),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    get_text("enh_btn_back_cancel", lang), callback_data="enh:screen:btns")]]),
            parse_mode="HTML")
        return ENH_POST

    if arg in ("edit", "del"):
        try:
            idx = int(arg2)
        except (TypeError, ValueError):
            return ENH_POST
        buttons = list(enh.get("buttons") or [])
        if not (0 <= idx < len(buttons)):
            await _answer(query, get_text("enh_btn_missing_alert", lang), alert=True)
            enh["step"] = "btns"
            await _render(context, chat_id)
            return ENH_POST
        if arg == "del":
            await _answer(query)
            removed = buttons.pop(idx)
            enh["buttons"] = buttons
            enh["step"] = "btns"
            await _render(context, chat_id)
            logger.info("Enhancer: tugma o'chirildi (%s → %s)", user_id, removed.get("url"))
            return ENH_POST

        await _answer(query)
        enh["_btn_pending_idx"] = idx
        enh["btn_preset"] = None
        enh["step"] = "btn_input"
        current = buttons[idx]
        await query.message.reply_text(
            get_text(
                "enh_edit_prompt", lang, num=idx + 1,
                text=html_escape(current['text']), url=html_escape(current['url']),
            ),
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton(
                    get_text("enh_btn_back_cancel", lang), callback_data="enh:screen:btns")]]),
            parse_mode="HTML")
        return ENH_POST

    if arg == "clear":
        await _answer(query)
        enh["buttons"] = []
        enh["step"] = "btns"
        await _render(context, chat_id)
    return ENH_POST


# ============================================================
# PREVYU (faqat foydalanuvchi so'raganda yuboriladi)
# ============================================================

# Tahrirlab bo'ladigan turlar (albom/ovozli/stiker bundan mustasno).
_PREVIEW_EDITABLE = ("text", "photo", "video", "animation", "document", "audio")


async def _drop_preview(context, chat_id: int, enh: dict):
    """Eski prevyu xabar(lar)ini o'chiradi (best-effort)."""
    ids = [enh.get("preview_msg_id")] + list(enh.get("preview_extra_ids") or [])
    for mid in ids:
        if not mid:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass
    enh["preview_msg_id"] = None
    enh["preview_type"] = None
    enh["preview_extra_ids"] = []


async def _edit_preview(context, chat_id: int, enh: dict, ptype: str, text: str, markup) -> bool:
    """Mavjud prevyu xabarini tahrirlaydi. Muvaffaqiyatli bo'lsa True."""
    mid = enh.get("preview_msg_id")
    if not mid:
        return False
    caption = None if ptype == "text" else (text or None)
    body = (text or " ") if ptype == "text" else None
    for parse in ("HTML", None):
        try:
            if ptype == "text":
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=mid, text=body,
                    reply_markup=markup, parse_mode=parse,
                )
            else:
                await context.bot.edit_message_caption(
                    chat_id=chat_id, message_id=mid, caption=caption,
                    reply_markup=markup, parse_mode=parse,
                )
            return True
        except BadRequest as e:
            if "not modified" in str(e).lower():
                return True
            if parse == "HTML" and "parse" in str(e).lower():
                continue  # HTML teg xatosi — oddiy matn bilan qayta
            return False
        except TelegramError:
            return False
    return False


def _preview_content(post: dict) -> str:
    """Prevyu uchun matn (Telegram caption/matn chegaralariga moslab)."""
    ptype = post.get("type") or "text"
    content = post.get("content") or ""
    if ptype == "sticker":
        return content
    if ptype != "text" and len(content) > 1000:
        content = content[:1000] + "…"
    if len(content) > 4000:
        content = content[:4000] + "…"
    return content


async def _send_preview(context, chat_id: int, enh: dict, create: bool = True):
    """Postni faqat Preview/tasdiqlash bosqichida tugmalari bilan ko'rsatadi.

    ``create=False`` bo'lsa va preview hali yuborilmagan bo'lsa — hech narsa
    qilinmaydi. Bu tahrirlash qadamlarida postning ortiqcha ko'rinishini
    chiqarib yubormaslik uchun muhim.
    """
    post = enh.get("post") or {}
    if not post:
        return None
    ptype = post.get("type") or "text"
    file_id = post.get("file_id")
    content = _preview_content(post)
    markup = None
    if ptype != "sticker":
        markup = build_enhancer_markup(enh.get("buttons"), enh.get("reactions"),
                                       post_id=None, preview=True)
    bot = context.bot

    # 1) Mavjud prevyuni tahrirlash (doimiy prevyu).
    if (enh.get("preview_msg_id") and enh.get("preview_type") == ptype
            and ptype in _PREVIEW_EDITABLE):
        if await _edit_preview(context, chat_id, enh, ptype, content, markup):
            return enh.get("preview_msg_id")

    if not create and not enh.get("preview_msg_id"):
        return None

    # 2) Tur o'zgargan/yangilash iloji bo'lmagan — eskisini o'chirib yangi yuboramiz.
    if enh.get("preview_msg_id"):
        await _drop_preview(context, chat_id, enh)

    try:
        if ptype == "album":
            items = parse_album_items(file_id)
            media = _build_album_media_local(items, content, parse_mode="HTML")
            try:
                group = await bot.send_media_group(chat_id=chat_id, media=media)
            except TelegramError:
                media = _build_album_media_local(items, content, parse_mode=None)
                group = await bot.send_media_group(chat_id=chat_id, media=media)
            extra = []
            if markup:
                try:
                    follow = await bot.send_message(
                        chat_id=chat_id,
                        text=get_text("enh_preview_follow_note", get_lang(context)),
                        reply_markup=markup, parse_mode="HTML",
                    )
                    extra = [follow.message_id]
                except TelegramError:
                    extra = []
            enh["preview_msg_id"] = group[0].message_id if group else None
            enh["preview_type"] = ptype
            enh["preview_extra_ids"] = extra
            return enh["preview_msg_id"]

        sent = await _dispatch_message(bot, chat_id, ptype, file_id, content, markup, html=True)
        if sent is None:
            await bot.send_message(
                chat_id=chat_id,
                text=get_text("enh_preview_failed", get_lang(context)),
            )
            return None
        enh["preview_msg_id"] = getattr(sent, "message_id", None)
        enh["preview_type"] = ptype
        enh["preview_extra_ids"] = list(getattr(sent, "extra_ids", []) or [])
        return enh["preview_msg_id"]
    except Exception:
        logger.exception("Enhancer prevyu xatosi")
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=get_text("enh_preview_error", get_lang(context)),
            )
        except Exception:
            pass
        return None


def _build_album_media_local(items: list, caption: str, parse_mode: str = "HTML") -> list:
    media = []
    for i, item in enumerate(items):
        cap = caption if i == 0 else None
        pm = parse_mode if cap else None
        fid, kind = item["file_id"], item["type"]
        if kind == "video":
            media.append(InputMediaVideo(media=fid, caption=cap, parse_mode=pm))
        elif kind == "document":
            media.append(InputMediaDocument(media=fid, caption=cap, parse_mode=pm))
        elif kind == "audio":
            media.append(InputMediaAudio(media=fid, caption=cap, parse_mode=pm))
        else:
            media.append(InputMediaPhoto(media=fid, caption=cap, parse_mode=pm))
    return media


async def _dispatch_message(bot, chat_id, ptype, file_id, text, markup, html=True, album_items=None):
    """Xabarni turiga qarab yuboradi. HTML parse xatosi bo'lsa — oddiy matn bilan qayta urinish."""
    parse = "HTML" if html else None
    try:
        if ptype == "album":
            items = album_items if album_items is not None else parse_album_items(file_id)
            if not items:
                raise ValueError("album_empty")
            if len(items) == 1:
                only = items[0]
                return await _dispatch_message(bot, chat_id, only.get("type") or "photo",
                                               only.get("file_id"), text, markup, html=html)
            media = _build_album_media_local(items, text, parse_mode=parse)
            group = await bot.send_media_group(chat_id=chat_id, media=media)
            if markup:
                follow = await bot.send_message(chat_id=chat_id, text="🔗", reply_markup=markup)
                extra = [follow.message_id] if follow and follow.message_id else []
                return _GroupResult(group, extra)
            return _GroupResult(group, [])
        if ptype == "photo":
            return await bot.send_photo(chat_id=chat_id, photo=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "video":
            return await bot.send_video(chat_id=chat_id, video=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "animation":
            return await bot.send_animation(chat_id=chat_id, animation=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "document":
            return await bot.send_document(chat_id=chat_id, document=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "audio":
            return await bot.send_audio(chat_id=chat_id, audio=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "voice":
            return await bot.send_voice(chat_id=chat_id, voice=file_id, caption=text or None, reply_markup=markup, parse_mode=parse)
        if ptype == "sticker":
            return await bot.send_sticker(chat_id=chat_id, sticker=file_id)
        return await bot.send_message(chat_id=chat_id, text=text or " ", reply_markup=markup, parse_mode=parse)
    except TelegramError as e:
        # HTML teg xatosi bo'lsa — matnni BUZMASDAN, oddiy rejimda qayta yuboramiz.
        if html and "can't parse entities" in str(e).lower():
            return await _dispatch_message(bot, chat_id, ptype, file_id, text, markup, html=False, album_items=album_items)
        raise


class _GroupResult:
    """sendMediaGroup natijasi — birinchi xabar + qo'shimcha (tugmalar) xabarlari."""
    def __init__(self, messages, extra_ids):
        msgs = [m for m in (messages or []) if getattr(m, "message_id", None)]
        self.message_id = msgs[0].message_id if msgs else None
        self.extra_ids = list(extra_ids)


# ============================================================
# KANALGA YUBORISH (tasdiq bilan, to'g'ridan-to'g'ri)
# ============================================================

async def _execute_send(update, context, query, enh):
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    chat_id = query.message.chat_id if query.message else user_id
    lang = get_lang(context)

    # Spam-himoya: ketma-ket yuborishlarni cheklash.
    blocked, _ = check_rate_limit(user_id, max_requests=6, window_seconds=30)
    if blocked:
        await _answer(query, get_text("enh_too_fast", lang), alert=True)
        return ENH_POST

    channels = enh.get("channels") or []
    idx = enh.get("ch_idx")
    if not isinstance(idx, int) or not (0 <= idx < len(channels)):
        await _answer(query, get_text("enh_no_channel_sel", lang), alert=True)
        return ENH_POST
    ch_id, ch_title = channels[idx][:2]

    # Kanal hali ham foydalanuvchiga tegishli mi? (egallik tekshiruvi)
    owned = await db.run_db(db.get_user_channels, user_id)
    if not any(str(c[0]) == str(ch_id) for c in (owned or [])):
        await _answer(query, get_text("enh_channel_not_owned", lang), alert=True)
        enh["step"] = "channel"
        enh["channels"] = owned or []
        await _render(context, chat_id)
        return ENH_POST

    post = enh.get("post") or {}
    ptype = post.get("type") or "text"
    file_id = post.get("file_id")
    reactions = list(enh.get("reactions") or [])
    buttons = list(enh.get("buttons") or [])
    if ptype == "sticker":
        reactions, buttons = [], []  # sticker ostiga tugma qo'shib bo'lmaydi
    # Reaksiyalar faqat inline tugma — caption/matn boshiga sizib chiqqan
    # emoji qatori (👍 ❤️ 🔥\n\n...) kanalga yuborishdan oldin olinadi.
    content = strip_leading_reaction_glyphs(post.get("content") or "", reactions)

    # --- Kanal ko'rinishidagi yakuniy matn (asl matn O'ZGARMAYDI, faqat
    # scheduler bilan bir xil qoidalar: watermark → reklama → nishon) ---
    try:
        has_ad_free = True if is_admin else await db.run_db(db.is_premium, user_id)
        # Reklama scheduler bilan bir xil qoida bo'yicha qo'shiladi: har bir
        # kanalning ALOHIDA post sanagichi + admin belgilagan oraliq.
        ad_info = await resolve_channel_ad(str(ch_id), has_ad_free)
        channel_ad = (ad_info.get("text") or "").strip()
        ad_button = build_ad_button_row(ad_info)
        brand_text = (await db.run_db(db.get_setting, "post_tag_text", "") or "").strip()
        watermarked = await apply_post_watermark(content, user_id, BOT_USERNAME)
        text_limit = 4096 if ptype == "text" else 1024
        final_content = compose_post_text(watermarked, has_ad_free, channel_ad, brand_text,
                                          limit=text_limit)
    except Exception:
        logger.exception("Enhancer: matnni tayyorlashda xato")
        await _answer(query, get_text("enh_prepare_failed", lang), alert=True)
        return ENH_POST

    # --- Reaksiya hisoblagichi uchun yozuv (tarix + react: callback ID) ---
    now = datetime.now(tashkent_tz)
    first_btn = buttons[0] if buttons else None
    pid = await db.run_db(
        db.add_post,
        user_id=user_id, channel_id=str(ch_id), post_type=ptype, content=content,
        file_id=file_id, scheduled_time=now + timedelta(days=3650),
        recurrence_type="none", recurrence_day=None, recurrence_time=None, end_date=None,
        btn_text=(first_btn or {}).get("text"), btn_url=(first_btn or {}).get("url"),
        enable_reactions=bool(reactions), reaction_emojis=" ".join(reactions) or None,
        delete_after_hours=0,
    )
    markup = build_enhancer_markup(buttons, reactions, post_id=pid or None,
                                   extra_rows=[ad_button] if ad_button else None)

    target_chat = int(ch_id) if str(ch_id).lstrip("-").isdigit() else ch_id
    try:
        result = await _dispatch_message(context.bot, target_chat, ptype, file_id,
                                         final_content, markup, html=True)
    except TelegramError as e:
        if pid:
            await db.run_db(db.mark_post_status, pid, "cancelled")
        err = str(e).lower()
        if "bot was kicked" in err or "chat not found" in err or "not enough rights" in err:
            tip = get_text("enh_send_no_rights", lang)
        else:
            tip = get_text("enh_send_failed", lang, error=html_escape(str(e))[:200])
        await _answer(query, tip, alert=True)
        return ENH_POST

    if pid:
        extra = getattr(result, "extra_ids", None)
        await db.run_db(db.mark_post_as_sent, pid, getattr(result, "message_id", None),
                        str(ch_id), 0, extra)

    logger.info("Enhancer: post kanalga yuborildi (%s → %s)", user_id, ch_id)
    enh["step"] = "sent"
    enh["sent_channel"] = ch_title or ""
    text, markup_done = _success_view(ch_title or "", lang)
    try:
        await query.edit_message_text(text, reply_markup=markup_done, parse_mode="HTML")
        enh["success_msg_id"] = query.message.message_id
    except Exception:
        # Muvaffaqiyat xabari alohida yuboriladi; eski panel hub_msg_id
        # sifatida saqlanmaydi, shuning uchun keyingi ekranlar uni o'chirmaydi.
        success = await context.bot.send_message(chat_id=user_id, text=text,
                                                 reply_markup=markup_done, parse_mode="HTML")
        enh["success_msg_id"] = getattr(success, "message_id", None)
    enh["hub_msg_id"] = None
    return ENH_POST


# ============================================================
# SESSIYADAN TASHQARI STALE TUGMALAR (global zaxira)
# ============================================================

async def enh_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Conversation tugagach eski enhancer/prevyu tugmalari bosilsa — jim javob (uz/ru).

    Prevyu xabari buzilmasligi uchun edit QILINMAYDI.
    """
    try:
        await update.callback_query.answer(
            get_text("enh_stale_notice", get_lang(context))
        )
    except Exception:
        pass
