"""✨ Postga Tugma & Reaksiya qo'shish (Post Enhancer) — ⚙️ Qo'shimcha funksiyalar.

Bosqichma-bosqich oqim (har bir qadamda "⬅️ Orqaga" va "❌ Bekor qilish" bor):
  0. Kirish: darhol **admin eslatmasi** (bot kanalda admin bo'lishi kerak) va
     postni so'rash.
  1. Foydalanuvchi tayyor postni yuboradi (matn, rasm, video, albom,
     hujjat/audio yoki istalgan kanaldan FORWARD). Postning ASL MATNIGA
     TEKILMAYDI — bot uni o'zgartirmaydi, qisqartirmaydi, AI bilan
     "yozmaydi". Faqat bepul (Free) rejali foydalanuvchilar uchun kanalga
     yuborilganda scheduler'dagi via/watermark qoidalari qo'llanadi.
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
from keyboards.inline import (
    btn_label,
    extract_emoji_tokens,
    strip_variation_selector,
    REACTION_POOL,
)
from utils.helpers import (
    html_escape,
    safe_html,
    apply_post_watermark,
    check_rate_limit,
)
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
ADMIN_NOTICE = (
    "💡 <b>Eslatma:</b> Bot postni kanalingizga joylashi uchun avval uni "
    "kanalingizga <b>Admin</b> qilib qo'shganingizga ishonch hosil qiling."
)
POST_REQUEST_LINE = (
    "Kanalga joylamoqchi bo'lgan postingizni yuboring "
    "(Matn, Rasm, Video yoki boshqa kanaldan Forward):"
)

# ============================================================
# TAYYOR URL TUGMA SHABLONLARI (presets)
# ============================================================
# Foydalanuvchi shablonni tanlasa, bot FAQAT havolani so'raydi — tugma
# yozuvi shablondan avtomatik olinadi.
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


# ============================================================
# YORDAMCHI FUNKSIYALAR (sof logika — unit-testlanadigan)
# ============================================================

def intro_text() -> str:
    """Kirish xabari: AVVAL admin eslatmasi, keyin postni so'rash."""
    return (
        f"{ADMIN_NOTICE}\n\n"
        f"{POST_REQUEST_LINE}\n\n"
        "✅ Asl matnga tegilmaydi — faqat:\n"
        "• 👍 10 tagacha reaksiya (probel bilan batch kiritish mumkin),\n"
        "• 🔗 10 tagacha URL tugma (tayyor shablonlar bilan),\n"
        "• 👁 so'ralganda prevyu va 🚀 kanalga bir zumda yuborish."
    )


def nav_row(back_callback: str = "enh:screen:hub") -> list:
    """Har ekranda doim turadigan navigatsiya qatori: Orqaga + Bekor qilish."""
    return [
        InlineKeyboardButton("⬅️ Orqaga", callback_data=back_callback),
        InlineKeyboardButton("❌ Bekor qilish", callback_data="enh:cancel"),
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


def get_url_preset(index) -> "dict | None":
    """Shablon indeksini (int/str) shablon dict'iga aylantiradi; yo'q bo'lsa None."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < len(URL_PRESETS):
        return URL_PRESETS[idx]
    return None


def build_preset_button(index, link: str) -> "dict | None":
    """Tayyor shablon + havola → URL tugma. Havola/shablon yaroqsiz bo'lsa None.

    >>> build_preset_button(0, "@kanalim")
    {'text': '📢 Kanalga a'zo bo'lish', 'url': 'https://t.me/kanalim'}
    """
    preset = get_url_preset(index)
    if not preset:
        return None
    url = normalize_button_url((link or "").strip())
    if not url:
        return None
    return sanitize_button({"text": preset["text"], "url": url})


def parse_button_input(text: str, preset_index=None) -> "dict | None":
    """Foydalanuvchi kiritgan qatorni tugmaga aylantiradi.

    Shablon tanlangan bo'lsa AVVAL faqat havola sifatida urilib ko'riladi
    (yozuv shablondan olinadi); agar qator to'liq formatda bo'lsa
    (``Yozuv - https://...``) — u ustun keladi.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    if preset_index is not None:
        preset = build_preset_button(preset_index, raw)
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

    react_buttons = []
    for emoji in (reactions or [])[:MAX_ENH_REACTIONS]:
        if not emoji:
            continue
        if preview or not post_id:
            react_buttons.append(InlineKeyboardButton(emoji, callback_data="enh:noop"))
        else:
            react_buttons.append(InlineKeyboardButton(emoji, callback_data=f"react:{post_id}:{emoji}"))
    for i in range(0, len(react_buttons), REACTIONS_PER_ROW):
        rows.append(react_buttons[i:i + REACTIONS_PER_ROW])

    return rows[:MAX_KEYBOARD_ROWS]


def build_enhancer_markup(buttons: list, reactions: list, post_id: int = None,
                         preview: bool = False, extra_rows: list = None):
    """Enhancer tugmalari; ``extra_rows`` — masalan reklamaning URL tugmasi."""
    rows = build_enhancer_rows(buttons, reactions, post_id=post_id, preview=preview)
    for row in (extra_rows or []):
        if row and len(rows) < MAX_KEYBOARD_ROWS:
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None


def summarize_selection(enh: dict) -> str:
    """Hub kartasi uchun tanlovlar satri (reaksiyalar/tugmalar soni)."""
    reactions = enh.get("reactions") or []
    buttons = enh.get("buttons") or []
    return (
        f"👍 Reaksiyalar: <b>{len(reactions)}/{MAX_ENH_REACTIONS}</b>"
        f"{' — ' + ' '.join(reactions) if reactions else ''}\n"
        f"🔗 URL tugmalar: <b>{len(buttons)}/{MAX_ENH_BUTTONS}</b>"
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


def _post_line(enh: dict) -> str:
    post = enh.get("post") or {}
    ptype = post.get("type") or "text"
    content = post.get("content") or ""
    line = f"📦 <b>Turi:</b> {TYPE_LABELS.get(ptype, '📝 Xabar')}"
    if ptype == "album":
        items = parse_album_items(post.get("file_id"))
        if items:
            line += f" ({len(items)} ta media)"
    if content:
        preview = content[:220] + ("…" if len(content) > 220 else "")
        line += f"\n📝 <b>Matn:</b> <i>{safe_html(preview)}</i>"
    else:
        line += "\n📝 <b>Matn:</b> <i>(yozuv yo'q — faqat media)</i>"
    return line


def _hub_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    text = (
        "✨ <b>Postga Tugma & Reaksiya qo'shish</b>\n\n"
        f"{_post_line(enh)}\n\n"
        f"{summarize_selection(enh)}\n"
        f"{watermark_note}"
        f"{ADMIN_NOTICE}\n\n"
        "Kerakli qadamni tanlang 👇"
    )
    r_n = len(enh.get("reactions") or [])
    b_n = len(enh.get("buttons") or [])
    keyboard = [
        [InlineKeyboardButton(f"👍 1. Reaksiyalar ({r_n}/{MAX_ENH_REACTIONS})",
                              callback_data="enh:screen:react")],
        [InlineKeyboardButton(f"🔗 2. URL tugmalar ({b_n}/{MAX_ENH_BUTTONS})",
                              callback_data="enh:screen:btns")],
        [
            InlineKeyboardButton("👁️ Prevyu", callback_data="enh:preview"),
            InlineKeyboardButton("🚀 Kanalga yuborish", callback_data="enh:screen:channel"),
        ],
        [
            InlineKeyboardButton("🔁 Postni almashtirish", callback_data="enh:replace"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="enh:cancel"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _react_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    selected = enh.get("reactions") or []
    sel_line = " ".join(selected) if selected else "— (hech narsa tanlanmagan)"
    left = max(0, MAX_ENH_REACTIONS - len(selected))
    text = (
        f"👍 <b>1-qadam. Reaksiyalar</b> (<b>{len(selected)}/{MAX_ENH_REACTIONS}</b>)\n\n"
        f"Tanlangan: {sel_line}\n\n"
        "• Emoji tugmasini bosing — ✅ belgilanadi, qayta bossangiz olib tashlanadi;\n"
        "• Yoki bir nechta emojini <b>probel bilan</b> bir xabarda yuboring "
        "(masalan: <code>👍 ❤️ 🔥 👏 🎉</code>);\n"
        f"• Yana <b>{left}</b> ta reaksiya qo'shsa bo'ladi.\n\n"
        "<i>Post faqat yakuniy prevyu/tasdiqlash bosqichida ko'rsatiladi.</i>"
    )
    rows = []
    row = []
    for emoji in REACTION_POOL:
        mark = " ✅" if any(reaction_key(emoji) == reaction_key(e) for e in selected) else ""
        row.append(InlineKeyboardButton(f"{emoji}{mark}", callback_data=f"enh:rtgl:{emoji}"))
        if len(row) == REACTIONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_label = (f"➡️ Davom etish / URL tugmaga o'tish ({len(selected)})"
                  if selected else "➡️ Davom etish / URL tugmaga o'tish")
    rows.append([InlineKeyboardButton(done_label, callback_data="enh:react:done")])
    extra_row = [InlineKeyboardButton("👁️ Prevyu", callback_data="enh:preview")]
    if selected:
        extra_row.append(InlineKeyboardButton("🗑 Tozalash", callback_data="enh:react:clear"))
    rows.append(extra_row)
    rows.append(nav_row("enh:screen:hub"))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _btn_entry_rows(buttons: list) -> list:
    """Mavjud URL tugmalar ro'yxati (10 qator chegarasiga sig'adigan tartibda)."""

    def entry(i, b):
        return [
            InlineKeyboardButton(f"✏️ {i + 1}. {btn_label(b.get('text'), 'Tugma', max_length=20)}",
                                 callback_data=f"enh:btn:edit:{i}"),
            InlineKeyboardButton("❌", callback_data=f"enh:btn:del:{i}"),
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


def _preset_rows(per_row: int = 2) -> list:
    """Tayyor URL tugma shablonlari qatorlari."""
    buttons = [
        InlineKeyboardButton(f"{p['icon']} {p['num']}. {p['title']}", callback_data=f"enh:preset:{i}")
        for i, p in enumerate(URL_PRESETS)
    ]
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def _btns_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    buttons = enh.get("buttons") or []
    if buttons:
        marks = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟"
        lines = [
            f"{marks[i]} <b>{html_escape(b.get('text') or 'Tugma')}</b> → "
            f"<code>{html_escape(b.get('url') or '')}</code>"
            for i, b in enumerate(buttons)
        ]
        body = "\n".join(lines)
    else:
        body = "<i>Hozircha tugmalar yo'q — shablon tanlang yoki qo'lda kiriting.</i>"
    text = (
        f"🔗 <b>2-qadam. URL tugmalar</b> (<b>{len(buttons)}/{MAX_ENH_BUTTONS}</b>)\n\n"
        f"{body}\n\n"
        "Tayyor shablonni tanlang — bot faqat havolani so'raydi.\n"
        "Qo'lda kiritish: <code>Tugma nomi - https://havola.uz</code> yoki "
        "<code>Tugma nomi | @kanalim</code>"
    )
    entry_rows = _btn_entry_rows(buttons)
    rows = list(entry_rows)

    add_row = [InlineKeyboardButton("➕ Yangi tugma qo'shish", callback_data="enh:btn:add")]
    if buttons:
        add_row.append(InlineKeyboardButton("🗑 Tozalash", callback_data="enh:btn:clear"))
    rows.append(add_row)

    # Shablonlar: ro'yxat qisqa bo'lganda to'g'ridan-to'g'ri shu ekranda,
    # aks holda "➕ Yangi tugma qo'shish" ekranida (10 qator chegarasi uchun).
    if len(buttons) < MAX_ENH_BUTTONS and len(entry_rows) <= 3:
        rows.extend(_preset_rows(per_row=2))
        rows[-1].append(InlineKeyboardButton("✍️ Qo'lda kiritish", callback_data="enh:btn:manual"))

    rows.append([InlineKeyboardButton("➡️ Tasdiqlash va Kanalga yuborish",
                                      callback_data="enh:screen:channel")])
    rows.append(nav_row("enh:screen:hub"))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _btn_add_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    n = len(enh.get("buttons") or [])
    text = (
        "➕ <b>Yangi URL tugma</b> "
        f"(<b>{n}/{MAX_ENH_BUTTONS}</b>)\n\n"
        "Tayyor shablonlardan birini tanlang — bot <b>faqat havolani</b> so'raydi.\n\n"
        "Yoki <b>✍️ Qo'lda kiritish</b> orqali bir qatorda yuboring:\n"
        "<code>Tugma nomi - https://havola.uz</code>\n"
        "<code>Tugma nomi | @kanalim</code>"
    )
    rows = [[InlineKeyboardButton(f"{p['icon']} {p['num']}. {p['title']}",
                                  callback_data=f"enh:preset:{i}")]
            for i, p in enumerate(URL_PRESETS)]
    rows.append([InlineKeyboardButton("✍️ Qo'lda kiritish", callback_data="enh:btn:manual")])
    rows.append(nav_row("enh:screen:btns"))
    return text, InlineKeyboardMarkup(rows)


def _channel_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    channels = enh.get("channels") or []
    text = (
        f"📢 <b>Qaysi kanalga yuborilsin?</b> ({len(channels)} ta)\n\n"
        "<i>Post tanlangan kanalga to'g'ridan-to'g'ri chiqadi "
        "(rejalashtirishsiz). Oxirida tasdiq so'raladi.</i>\n\n"
        f"{ADMIN_NOTICE}"
    )
    rows = []
    visible = channels[:16]
    row = []
    for idx, (ch_id, ch_title) in enumerate(visible):
        row.append(InlineKeyboardButton(f"📢 {btn_label(ch_title, 'Kanal', max_length=24)}",
                                        callback_data=f"enh:send:{idx}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if len(channels) > len(visible):
        rows.append([InlineKeyboardButton(
            f"…va yana {len(channels) - len(visible)} ta (kanal qo'shish bo'limi orqali tanlang)",
            callback_data="enh:noop")])
    # Post allaqachon yuborilgan bo'lsa, "Orqaga" muvaffaqiyat ekraniga qaytadi
    # (editor hubga emas) — muvaffaqiyat xabari asosiy holat bo'lib qoladi.
    back = "enh:screen:sent" if enh.get("sent_channel") else "enh:screen:hub"
    rows.append(nav_row(back))
    return text, InlineKeyboardMarkup(rows[:MAX_KEYBOARD_ROWS])


def _confirm_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    channels = enh.get("channels") or []
    idx = enh.get("ch_idx")
    if not isinstance(idx, int) or not (0 <= idx < len(channels)):
        return (
            "⚠️ <b>Kanal tanlanmagan.</b>\n\nRo'yxatdan kanalni tanlang.",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("📢 Kanallar ro'yxati", callback_data="enh:screen:channel")],
                nav_row("enh:screen:hub"),
            ]),
        )
    ch_id, ch_title = channels[idx][:2]
    text = (
        "📢 <b>Yuborishni tasdiqlang</b>\n\n"
        f"Ushbu post <b>{html_escape(ch_title or 'Kanal')}</b>ga yuborilsinmi?\n\n"
        f"{_post_line(enh)}\n\n"
        f"{summarize_selection(enh)}\n"
        f"{watermark_note}"
        "\n<i>Yuborilgandan keyin postni o'zgartirib bo'lmaydi.</i>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Ha, yuborilsin", callback_data="enh:confirm_send")],
        [InlineKeyboardButton("👁️ Avval prevyu", callback_data="enh:preview")],
        nav_row("enh:screen:channel"),
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _success_view(ch_title: str = "") -> tuple:
    where = f"\n📢 <b>Kanal:</b> {html_escape(ch_title)}" if ch_title else ""
    text = (
        "✅ <b>Post yuklandi!</b>\n"
        "Post kanalingizga muvaffaqiyatli joylandi!"
        f"{where}\n\n"
        "Xohlasangiz shu postni boshqa kanalga ham yuborishingiz yoki yangi "
        "post kuchaytirishingiz mumkin 👇"
    )
    keyboard = [
        [InlineKeyboardButton("🏠 Asosiy menyu", callback_data="enh:home")],
        [
            InlineKeyboardButton("📢 Boshqa kanalga", callback_data="enh:screen:channel"),
            InlineKeyboardButton("👁️ Prevyu", callback_data="enh:preview"),
        ],
        [
            InlineKeyboardButton("🚀 Yangi post", callback_data="enh:again"),
            InlineKeyboardButton("❌ Tugatish", callback_data="enh:cancel"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _sent_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    return _success_view(enh.get("sent_channel") or "")


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
    step = enh.get("step", "hub")
    view = _VIEWS.get(step, _hub_view)
    text, markup = view(context, watermark_note)

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


async def _plan_note(user_id: int) -> str:
    """Watermark/via holati haqida qator (bepul foydalanuvchiga ogohlantirish)."""
    if user_id in ADMIN_IDS_SET:
        return "👑 <i>Admin — post toza chiqadi.</i>\n"
    try:
        is_pro = await db.run_db(db.is_premium, user_id)
    except Exception:
        is_pro = False
    if is_pro:
        return "✨ <i>PRO — via/watermark qo'shilmaydi, post toza chiqadi.</i>\n"
    clean = BOT_USERNAME if str(BOT_USERNAME).startswith("@") else f"@{BOT_USERNAME}"
    return f"🆓 <i>Bepul reja: kanalga yuborilganda post boshiga {clean} qo'shiladi.</i>\n"


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
    enh = _payload(context)
    enh.update(_fresh_enh())
    # ENG BIRINCHI xabar: admin eslatmasi + postni so'rash.
    await msg.reply_text(
        intro_text(),
        reply_markup=get_cancel_keyboard(),
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
        "👇 <b>Postni kuchaytirish uchun pastdagi tugmalardan birini tanlang.</b>\n"
        "Postni almashtirmoqchimisiz — <b>🔁 Postni almashtirish</b> tugmasini bosing.",
        parse_mode="HTML",
    )
    return ENH_POST


async def _capture_post(update, context, msg, enh):
    user_id = update.effective_user.id
    chat_id = msg.chat_id
    if msg.media_group_id:
        item = _media_item_from_message(msg)
        if not item or item["type"] in ("voice", "sticker"):
            await msg.reply_text("⚠️ Bu turdagi media albomga qo'shib bo'lmaydi — yakka yuboring:")
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
                await msg.reply_text("⚠️ Bo'sh xabar qabul qilinmadi. Post matnini yoki mediani yuboring:")
                return ENH_POST
            enh["post"] = {"type": "text", "file_id": None, "content": msg.text or ""}

    enh["step"] = "hub"
    enh["hub_msg_id"] = None  # yangi hub xabari (post bilan bog'liq)
    await _drop_preview(context, chat_id, enh)  # eski post prevyusi eskirgan
    note = await _plan_note(user_id)
    await _render(context, chat_id, target_msg=msg, watermark_note=note)
    # Tahrirlash vaqtida post ko'rsatilmaydi; preview alohida tugma bilan ochiladi.
    return ENH_POST


async def _emoji_text_step(update, context, msg, enh, chat_id):
    """Reaksiya matnini qabul qiladi; post previewsi bu bosqichda yuborilmaydi."""
    raw_text = msg.text or msg.caption or ""
    res = apply_reaction_batch(enh.get("reactions"), raw_text)
    if res["tokens"]:
        enh["reactions"] = res["reactions"]
        total = len(res["reactions"])
        sel_line = " ".join(res["reactions"]) if res["reactions"] else "—"
        if res["added"]:
            extra = ""
            if res["overflow"]:
                extra += (f"\n⚠️ Chegara <b>{MAX_ENH_REACTIONS}</b> ta — "
                          f"{' '.join(res['overflow'])} sig'madi.")
            if res["duplicates"]:
                extra += "\nℹ️ Takrorlangan emojilar hisobga olinmadi."
            await msg.reply_text(
                f"✅ <b>Reaksiyalar saqlandi:</b> {sel_line}\n"
                f"Jami: <b>{total}/{MAX_ENH_REACTIONS}</b>{extra}", parse_mode="HTML")
        elif res["duplicates"] and not res["overflow"]:
            await msg.reply_text(
                f"ℹ️ Bu emojilar allaqachon tanlangan: {' '.join(res['duplicates'])}\n"
                f"Jami: <b>{total}/{MAX_ENH_REACTIONS}</b>", parse_mode="HTML")
        else:
            await msg.reply_text(
                f"⚠️ <b>Reaksiyalar chegarasi to'ldi</b> (maks. {MAX_ENH_REACTIONS} ta). "
                "Avval birortasini olib tashlang.", parse_mode="HTML")
    else:
        low = raw_text.strip().lower()
        if low in ("done", "tayyor", "✅", "davom", "keyingisi"):
            enh["step"] = "btns"
        elif low in ("yo'q", "yoq", "bekor", "tozalash"):
            enh["reactions"] = []
            enh["step"] = "hub"
        else:
            await msg.reply_text(
                "ℹ️ Faqat <b>emoji</b> yuboring — bir nechta bo'lsa <b>probel bilan</b> "
                "(masalan: <code>👍 ❤️ 🔥 👏 🎉</code>) yoki pastdagi tugmalardan foydalaning.",
                parse_mode="HTML")
    await _render(context, chat_id)
    return ENH_POST


async def _button_text_step(update, context, msg, enh, chat_id):
    """URL tugma qadami: shablon (faqat havola) yoki qo'lda kiritish."""
    text = (msg.text or msg.caption or "").strip()
    preset_idx = enh.get("btn_preset")
    if not text or text.lower() in ("yo'q", "yoq", "bekor", "orqaga"):
        enh["btn_preset"] = None
        enh["step"] = "btns"
        await _render(context, chat_id)
        return ENH_POST

    parsed = parse_button_input(text, preset_idx)
    if not parsed:
        preset = get_url_preset(preset_idx)
        if preset:
            await msg.reply_text(
                "⚠️ <b>Havola noto'g'ri.</b>\n\n"
                f"Faqat havolani yuboring, masalan: <code>{preset['hint']}</code>\n"
                "yoki <code>@kanal_ismi</code>",
                parse_mode="HTML",
            )
        else:
            await msg.reply_text(
                "⚠️ <b>Tugma formati noto'g'ri.</b>\n\n"
                "Qaytadan yuboring:\n"
                "<code>Saytga o'tish - https://sayt.uz</code>\n"
                "<code>Kanalim | @kanalim</code>\n"
                "<code>https://t.me/bot_ism/start</code> (yozuv avtomatik tanlanadi)",
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
                f"⚠️ <b>Maksimum {MAX_ENH_BUTTONS} ta URL tugma</b> qo'shish mumkin. "
                "Avval bittasini o'chiring.",
                parse_mode="HTML",
            )
            return ENH_POST
        buttons.append(parsed)
    enh["buttons"] = buttons
    enh["step"] = "btns"
    enh["btn_preset"] = None
    enh.pop("_btn_pending_idx", None)
    verb = "yangilandi" if editing else "saqlandi"
    await msg.reply_text(
        f"✅ <b>Tugma {verb}:</b> {html_escape(parsed['text'])} → "
        f"<code>{html_escape(parsed['url'])}</code>",
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
        await _answer(query, "⚠️ Sessiya tugagan — menyuni qaytadan oching.", alert=True)
        return ConversationHandler.END

    if action in ("cancel", "home"):
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        clear_fsm_data(context)
        try:
            await query.message.delete()
        except Exception:
            pass
        text = ("🏠 <b>Asosiy menyu</b> — kerakli bo'limni tanlang 👇"
                if action == "home"
                else "✅ <b>Qo'shimcha funksiyalar</b> bo'limi yopildi.")
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if action == "again":
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        enh.update(_fresh_enh())
        await query.message.reply_text(
            f"{ADMIN_NOTICE}\n\n"
            "🚀 <b>Yangi post</b> — kuchaytirmoqchi bo'lgan postingizni yuboring "
            "(matn, rasm, video, albom yoki forward):",
            reply_markup=get_cancel_keyboard(),
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
                    "⚠️ Ulangan kanal yo'q — avval kanal ulang va botni "
                    "kanalga Admin qilib qo'shing.",
                    alert=True,
                )
                enh["step"] = "hub"
            else:
                enh["channels"] = channels
        await _render(context, chat_id, target_msg=query.message,
                      watermark_note=await _plan_note(user_id))
        return ENH_POST

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
            await _answer(query, f"⚠️ Maksimum {MAX_ENH_REACTIONS} ta reaksiya!", alert=True)
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
            await _render(context, chat_id, watermark_note=await _plan_note(user_id))
        # Post yuborilgandan keyin biz muvaffaqiyat xabarini saqlaymiz: preview
        # faqat uning ustiga chiqadi va success ekrani o'chirilmaydi.
        return ENH_POST

    if action == "replace":
        await _answer(query)
        await _drop_preview(context, chat_id, enh)
        enh["step"] = "content"
        await query.message.reply_text(
            "🔁 <b>Yangi postni yuboring</b> — joriy post (matn/media) almashtiriladi. "
            "Reaksiyalar va tugmalar saqlanadi 👇",
            reply_markup=get_cancel_keyboard(),
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
            await _answer(query, "⚠️ Bu kanal endi ro'yxatda yo'q.", alert=True)
            return ENH_POST
        enh["ch_idx"] = idx
        enh["step"] = "confirm"
        # Tasdiqlash ekranida post ham albatta ko'rinsin. Agar foydalanuvchi
        # oldin Preview bosgan bo'lsa, mavjud preview qayta ishlatiladi.
        await _send_preview(context, chat_id, enh, create=True)
        await _render(context, chat_id, watermark_note=await _plan_note(user_id))
        return ENH_POST

    if action == "confirm_send":
        await _answer(query)
        return await _execute_send(update, context, query, enh)

    return ENH_POST


async def _preset_action(update, context, query, arg, enh):
    """Tayyor shablon tanlandi — endi faqat havola so'raladi."""
    chat_id = query.message.chat_id if query.message else query.from_user.id
    preset = get_url_preset(arg)
    if not preset:
        await _answer(query, "⚠️ Shablon topilmadi.", alert=True)
        return ENH_POST
    if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
        await _answer(query, f"⚠️ Maksimum {MAX_ENH_BUTTONS} ta tugma!", alert=True)
        return ENH_POST
    await _answer(query)
    enh["btn_preset"] = int(arg)
    enh.pop("_btn_pending_idx", None)
    enh["step"] = "btn_input"
    await query.message.reply_text(
        f"{preset['icon']} <b>{preset['num']}. {preset['title']}</b>\n\n"
        f"Faqat <b>havolani</b> yuboring (masalan: <code>{preset['hint']}</code>) — "
        "tugma yozuvi avtomatik qo'yiladi.\n\n"
        "<i>To'liq formatda ham mumkin: <code>Yozuv - https://havola.uz</code></i>",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Bekor qilish", callback_data="enh:screen:btns")]
        ]),
        parse_mode="HTML",
    )
    return ENH_POST


async def _btn_action(update, context, query, arg, arg2, enh, chat_id):
    user_id = query.from_user.id
    if arg == "add":
        await _answer(query)
        if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
            await _answer(query, f"⚠️ Maksimum {MAX_ENH_BUTTONS} ta tugma!", alert=True)
            return ENH_POST
        enh["btn_preset"] = None
        enh["_btn_pending_idx"] = None
        enh["step"] = "btn_add"
        await _render(context, chat_id)
        return ENH_POST

    if arg == "manual":
        await _answer(query)
        if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
            await _answer(query, f"⚠️ Maksimum {MAX_ENH_BUTTONS} ta tugma!", alert=True)
            return ENH_POST
        enh["btn_preset"] = None
        enh["_btn_pending_idx"] = None
        enh["step"] = "btn_input"
        await query.message.reply_text(
            "✍️ <b>Yangi URL tugma (qo'lda kiritish)</b>\n\n"
            "Bir qatorda yuboring:\n"
            "<code>Tugma nomi - https://havola.uz</code>\n"
            "<code>Tugma nomi | @kanalim</code>\n"
            "<code>Botim - t.me/bot_ismi/start</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="enh:screen:btns")]]),
            parse_mode="HTML")
        return ENH_POST

    if arg in ("edit", "del"):
        try:
            idx = int(arg2)
        except (TypeError, ValueError):
            return ENH_POST
        buttons = list(enh.get("buttons") or [])
        if not (0 <= idx < len(buttons)):
            await _answer(query, "⚠️ Tugma topilmadi.", alert=True)
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
            f"✏️ <b>{idx + 1}-tugmani tahrirlash</b>\n\n"
            f"Hozir: <b>{html_escape(current['text'])}</b> → <code>{html_escape(current['url'])}</code>\n\n"
            "Yangi qiymatni bir qatorda yuboring:\n"
            "<code>Yangi yozuv - https://yangi-havola.uz</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="enh:screen:btns")]]),
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
                        text="👆 <i>Yuqorida — prevyu. Tugmalar kanalda shu post "
                             "ostida chiqadi.</i>",
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
            await bot.send_message(chat_id=chat_id, text="⚠️ Prevyu yasab bo'lmadi (media fayli yaroqsiz).")
            return None
        enh["preview_msg_id"] = getattr(sent, "message_id", None)
        enh["preview_type"] = ptype
        enh["preview_extra_ids"] = list(getattr(sent, "extra_ids", []) or [])
        return enh["preview_msg_id"]
    except Exception:
        logger.exception("Enhancer prevyu xatosi")
        try:
            await bot.send_message(chat_id=chat_id, text="⚠️ Prevyu ko'rsatib bo'lmadi.")
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

    # Spam-himoya: ketma-ket yuborishlarni cheklash.
    blocked, _ = check_rate_limit(user_id, max_requests=6, window_seconds=30)
    if blocked:
        await _answer(query, "⏳ Juda tez — birozdan so'ng qayta urinib ko'ring.", alert=True)
        return ENH_POST

    channels = enh.get("channels") or []
    idx = enh.get("ch_idx")
    if not isinstance(idx, int) or not (0 <= idx < len(channels)):
        await _answer(query, "⚠️ Kanal tanlanmagan.", alert=True)
        return ENH_POST
    ch_id, ch_title = channels[idx][:2]

    # Kanal hali ham foydalanuvchiga tegishli mi? (egallik tekshiruvi)
    owned = await db.run_db(db.get_user_channels, user_id)
    if not any(str(c[0]) == str(ch_id) for c in (owned or [])):
        await _answer(query, "⚠️ Bu kanal endi sizning ro'yxatingizda yo'q.", alert=True)
        enh["step"] = "channel"
        enh["channels"] = owned or []
        await _render(context, chat_id)
        return ENH_POST

    post = enh.get("post") or {}
    ptype = post.get("type") or "text"
    file_id = post.get("file_id")
    content = post.get("content") or ""
    reactions = list(enh.get("reactions") or [])
    buttons = list(enh.get("buttons") or [])
    if ptype == "sticker":
        reactions, buttons = [], []  # sticker ostiga tugma qo'shib bo'lmaydi

    # --- Kanal ko'rinishidagi yakuniy matn (asl matn O'ZGARMAYDI, faqat
    # scheduler bilan bir xil qoidalar: watermark → reklama → nishon) ---
    try:
        has_ad_free = True if is_admin else await db.run_db(db.peek_ad_free_post, user_id)
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
        await _answer(query, "⚠️ Postni tayyorlab bo'lmadi. Qaytadan urinib ko'ring.", alert=True)
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
            tip = ("⚠️ Bot kanalda admin emas (yoki ruxsati yo'q). "
                   "Kanalga admin qilib qo'shing.")
        else:
            tip = f"⚠️ Yuborib bo'lmadi: {html_escape(str(e))[:200]}"
        await _answer(query, tip, alert=True)
        return ENH_POST

    if pid:
        extra = getattr(result, "extra_ids", None)
        await db.run_db(db.mark_post_as_sent, pid, getattr(result, "message_id", None),
                        str(ch_id), 0, extra)
    if has_ad_free and not is_admin:
        try:
            await db.run_db(db.consume_ad_free_post, user_id)
        except Exception:
            pass

    logger.info("Enhancer: post kanalga yuborildi (%s → %s)", user_id, ch_id)
    enh["step"] = "sent"
    enh["sent_channel"] = ch_title or ""
    text, markup_done = _success_view(ch_title or "")
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
    """Conversation tugagach eski enhancer/prevyu tugmalari bosilsa — jim javob.

    Prevyu xabari buzilmasligi uchun edit QILINMAYDI.
    """
    try:
        await update.callback_query.answer("⚠️ Bu menyuning muddati tugagan — ⚙️ Qo'shimcha funksiyalarni qaytadan oching.")
    except Exception:
        pass
