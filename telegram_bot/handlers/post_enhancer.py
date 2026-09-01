"""🛠 Post kuchaytirgich (Post Enhancer) — ⚙️ Qo'shimcha funksiyalar bo'limi.

Jarayon:
  1. Foydalanuvchi tayyor postni yuboradi (matn, rasm, video, albom,
     hujjat/audio yoki istalgan kanaldan FORWARD). Postning ASL MATNIGA
     TEKILMAYDI — bot uni o'zgartirmaydi, qisqartirmaydi, AI bilan
     "yozmaydi". Faqat bepul (Free) rejali foydalanuvchilar uchun kanalga
     yuborilganda scheduler'dagi via/watermark qoidalari qo'llanadi.
  2. Alohida interfeys: 10 tagacha reaksiya (emoji tugma) qo'shish/tahrirlash.
  3. Alohida interfeys: 10 tagacha URL inline tugma (kanal/sayt/bot)
     qo'shish/tahrirlash.
  4. 👁 Prevyu (haqiqiy tugmalar bilan) va 📢 ro'yxatdan o'tgan kanallardan
     birini tanlab, tasdiq bilan to'g'ridan-to'g'ri kanalga yuborish.

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
    REACTION_POOL,
)
from utils.helpers import (
    html_escape,
    safe_html,
    apply_post_watermark,
    get_channel_ad_next_async,
    check_rate_limit,
)
from scheduler import compose_post_text, parse_album_items
# Albom (media_group) yig'ish logikasi new_post bilan umumiy — buffer'lar ham.
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


# ============================================================
# YORDAMCHI FUNKSIYALAR (sof logika — unit-testlanadigan)
# ============================================================

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


def _label_from_url(url: str) -> str:
    """URL bo'yicha tugma yozuvini yasaydi: t.me/x → @x; sayt.uz → Sayt.uz."""
    m = re.match(r"https?://(?:www\.)?t\.me/([A-Za-z0-9_]+)", url or "")
    if m:
        return f"@{m.group(1)}"
    m = re.match(r"https?://(?:www\.)?([^/:?#]+)", url or "")
    if m:
        return btn_label(m.group(1), "🔗 Havola", max_length=BTN_TEXT_MAX)
    return "🔗 Havola"


def add_unique_emoji(current: list, emojis: list, max_count: int = MAX_ENH_REACTIONS) -> "tuple[list, int]":
    """Ro'yxatga takrorlanmas emoji(lar) qo'shadi. (yangi_ro'yxat, qo'shilgan_soni)."""
    result = list(current or [])
    added = 0
    for e in emojis or []:
        if not e:
            continue
        if e in result:
            continue
        if len(result) >= max_count:
            break
        result.append(e)
        added += 1
    return result, added


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
                         preview: bool = False):
    rows = build_enhancer_rows(buttons, reactions, post_id=post_id, preview=preview)
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

def _payload(context) -> dict:
    enh = context.user_data.get(_ENH_KEY)
    if not isinstance(enh, dict):
        enh = {"step": "content", "post": None, "reactions": [], "buttons": [],
               "hub_msg_id": None, "btn_edit": None, "channels": [], "ch_idx": None}
        context.user_data[_ENH_KEY] = enh
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
        "🛠 <b>Post kuchaytirgich</b>\n\n"
        f"{_post_line(enh)}\n\n"
        f"{summarize_selection(enh)}\n"
        f"{watermark_note}"
        "\nKerakli qadamni tanlang 👇"
    )
    r_n = len(enh.get("reactions") or [])
    b_n = len(enh.get("buttons") or [])
    keyboard = [
        [InlineKeyboardButton(f"👍 Reaksiyalar ({r_n}/{MAX_ENH_REACTIONS})", callback_data="enh:screen:react")],
        [InlineKeyboardButton(f"🔗 URL tugmalar ({b_n}/{MAX_ENH_BUTTONS})", callback_data="enh:screen:btns")],
        [
            InlineKeyboardButton("👁️ Prevyu", callback_data="enh:preview"),
            InlineKeyboardButton("📢 Kanalga yuborish", callback_data="enh:screen:channel"),
        ],
        [
            InlineKeyboardButton("🔁 Postni almashtirish", callback_data="enh:replace"),
            InlineKeyboardButton("❌ Bekor qilish", callback_data="enh:cancel"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _react_view(context) -> tuple:
    enh = _payload(context)
    selected = enh.get("reactions") or []
    sel_line = " ".join(selected) if selected else "— (hech narsa tanlanmagan)"
    text = (
        "👍 <b>Reaksiya tugmalari</b>\n\n"
        f"Tanlangan (<b>{len(selected)}/{MAX_ENH_REACTIONS}</b>): {sel_line}\n\n"
        "• Emoji tugmasini bosing — ✅ belgilanadi, qayta bossangiz olib tashlanadi;\n"
        "• Istalgan emojilarni <i>xabar qilib ham yuboring</i> (masalan: <code>👍 🔥 😍</code>);\n"
        "• Reaksiyalar post ostida hisoblagich tugmalari bo'lib chiqadi."
    )
    rows = []
    row = []
    for idx, emoji in enumerate(REACTION_POOL):
        mark = " ✅" if emoji in selected else ""
        row.append(InlineKeyboardButton(f"{emoji}{mark}", callback_data=f"enh:rtgl:{emoji}"))
        if len(row) == REACTIONS_PER_ROW:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_label = f"✅ Tasdiqlash ({len(selected)})" if selected else "✅ Tasdiqlash"
    rows.append([
        InlineKeyboardButton(done_label, callback_data="enh:react:done"),
        InlineKeyboardButton("🗑 Tozalash", callback_data="enh:react:clear"),
    ])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="enh:screen:hub")])
    return text, InlineKeyboardMarkup(rows)


def _btns_view(context) -> tuple:
    enh = _payload(context)
    buttons = enh.get("buttons") or []
    if buttons:
        lines = []
        marks = "1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟"
        for i, b in enumerate(buttons):
            lines.append(f"{marks[i]} <b>{html_escape(b['text'])}</b> → <code>{html_escape(b['url'])}</code>")
        body = "\n".join(lines)
    else:
        body = "<i>Hozircha tugmalar yo'q.</i>"
    text = (
        f"🔗 <b>URL inline tugmalar</b> (<b>{len(buttons)}/{MAX_ENH_BUTTONS}</b>)\n\n"
        f"{body}\n\n"
        "Qo'shish/tahrirlash formati: <code>Tugma yozuvi - https://havola</code>\n"
        "Yoki: <code>Matn | @kanalim</code>, <code>Matn | t.me/bot_ism</code>"
    )
    rows = []
    def entry(i, b):
        return [
            InlineKeyboardButton(f"✏️ {i + 1}. {btn_label(b['text'], 'Tugma', max_length=20)}",
                                 callback_data=f"enh:btn:edit:{i}"),
            InlineKeyboardButton("❌", callback_data=f"enh:btn:del:{i}"),
        ]
    if len(buttons) <= 6:
        for i, b in enumerate(buttons):
            rows.append(entry(i, b))
    else:
        # 7-10 tugma bo'lsa: ikkitadan birlashtiramiz (10 qator chegarasi uchun)
        for i in range(0, len(buttons), 2):
            merged = entry(i, buttons[i])
            if i + 1 < len(buttons):
                merged += entry(i + 1, buttons[i + 1])
            rows.append(merged)
    add_row = [InlineKeyboardButton("➕ Yangi tugma qo'shish", callback_data="enh:btn:add")]
    if buttons:
        add_row.append(InlineKeyboardButton("🗑 Tozalash", callback_data="enh:btn:clear"))
    rows.append(add_row)
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="enh:screen:hub")])
    return text, InlineKeyboardMarkup(rows)


def _channel_view(context) -> tuple:
    enh = _payload(context)
    channels = enh.get("channels") or []
    text = (
        f"📢 <b>Qaysi kanalga yuborilsin?</b> ({len(channels)} ta)\n\n"
        "<i>Post tanlangan kanalga to'g'ridan-to'g'ri chiqadi "
        "(rejalashtirishsiz). Oxirida tasdiq so'raladi.</i>"
    )
    rows = []
    visible = channels[:18]
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
        rows.append([InlineKeyboardButton(f"…va yana {len(channels) - len(visible)} ta (kanal qo'shish bo'limi orqali tanlang)",
                                         callback_data="enh:noop")])
    rows.append([InlineKeyboardButton("⬅️ Orqaga", callback_data="enh:screen:hub")])
    return text, InlineKeyboardMarkup(rows)


def _confirm_view(context, watermark_note: str = "") -> tuple:
    enh = _payload(context)
    ch_id, ch_title = (enh.get("channels") or [])[enh["ch_idx"]][:2]
    text = (
        "✅ <b>Yuborishni tasdiqlang</b>\n\n"
        f"📢 <b>Kanal:</b> {html_escape(ch_title or 'Kanal')}\n"
        f"{_post_line(enh)}\n\n"
        f"{summarize_selection(enh)}\n"
        f"{watermark_note}"
        "\n<i>Yuborilgandan keyin postni o'zgartirib bo'lmaydi.</i>"
    )
    keyboard = [
        [InlineKeyboardButton("✅ Ha, kanalga yuborish", callback_data="enh:confirm_send")],
        [
            InlineKeyboardButton("👁️ Avval prevyu", callback_data="enh:preview"),
            InlineKeyboardButton("⬅️ Orqaga", callback_data="enh:screen:hub"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


def _success_view() -> tuple:
    text = (
        "🎉 <b>Post kanalga yuborildi!</b>\n\n"
        "Xohlasangiz shu postni boshqa kanalga ham yuborishingiz, oldindan "
        "ko'rishingiz yoki yangi post kuchaytirishingiz mumkin 👇"
    )
    keyboard = [
        [
            InlineKeyboardButton("📢 Boshqa kanalga", callback_data="enh:screen:channel"),
            InlineKeyboardButton("👁️ Prevyu", callback_data="enh:preview"),
        ],
        [
            InlineKeyboardButton("🚀 Yangi post kuchaytirish", callback_data="enh:again"),
            InlineKeyboardButton("❌ Tugatish", callback_data="enh:cancel"),
        ],
    ]
    return text, InlineKeyboardMarkup(keyboard)


_VIEWS = {"hub": _hub_view, "react": _react_view, "btns": _btns_view,
          "channel": _channel_view, "confirm": _confirm_view}


async def _render(context, chat_id: int, target_msg=None, watermark_note: str = ""):
    """Joriy qadam ekranini ko'rsatadi: hub xabari bo'lsa EDIT qilinadi."""
    enh = _payload(context)
    step = enh.get("step", "hub")
    view = _VIEWS.get(step, _hub_view)
    if view in (_hub_view, _confirm_view):
        text, markup = view(context, watermark_note)
    else:
        text, markup = view(context)
    hub_id = enh.get("hub_msg_id")
    if hub_id:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id, message_id=hub_id, text=text[:4090],
                reply_markup=markup, parse_mode="HTML",
            )
            return
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                enh["hub_msg_id"] = None
        except TelegramError:
            enh["hub_msg_id"] = None
    msg = None
    if target_msg is not None:
        try:
            msg = await target_msg.reply_text(text, reply_markup=markup, parse_mode="HTML")
        except TelegramError:
            msg = None
    if msg is None:
        msg = await context.bot.send_message(chat_id=chat_id, text=text[:4090],
                                             reply_markup=markup, parse_mode="HTML")
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
    """"⚙️ Qo'shimcha funksiyalar" menyusidan 🛠 Post kuchaytirgichni ochish."""
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

    context.user_data.clear()
    enh = _payload(context)
    enh["step"] = "content"
    await msg.reply_text(
        "🛠 <b>Post kuchaytirgich</b>\n\n"
        "Tayyor postingizni yuboring: <b>matn, rasm, video, GIF, albom, hujjat, "
        "audio yoki istalgan postni FORWARD qilib</b> yuboring.\n\n"
        "✅ Asl matnga tegilmaydi — faqat:\n"
        "• 👍 10 tagacha reaksiya tugmasi,\n"
        "• 🔗 10 tagacha URL tugma,\n"
        "• 👁 prevyu va 📢 tanlangan kanalga bir zumda yuborish.\n\n"
        "<i>Endi postni yuboring 👇</i>",
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
    note = await _plan_note(user_id)
    await _render(context, chat_id, target_msg=msg, watermark_note=note)
    return ENH_POST


async def _emoji_text_step(update, context, msg, enh, chat_id):
    emojis = extract_emoji_tokens(msg.text or "", max_count=MAX_ENH_REACTIONS)
    if emojis:
        new_list, added = add_unique_emoji(enh.get("reactions"), emojis)
        enh["reactions"] = new_list
        if added == 0:
            await msg.reply_text(
                f"⚠️ <b>Reaksiyalar chegarasi to'ldi</b> (maks. {MAX_ENH_REACTIONS} ta). "
                "Avval birortasini olib tashlang.",
                parse_mode="HTML",
            )
    else:
        low = (msg.text or "").strip().lower()
        if low in ("done", "tayyor", "✅"):
            enh["step"] = "hub"
        elif low in ("yo'q", "yoq", "bekor", "tozalash"):
            enh["reactions"] = []
            enh["step"] = "hub"
        else:
            await msg.reply_text(
                "ℹ️ Faqat <b>emoji</b> yuboring (masalan: <code>👍 🔥 😍</code>) "
                "yoki <b>✅ Tasdiqlash</b> tugmasini bosing.",
                parse_mode="HTML",
            )
    await _render(context, chat_id)
    return ENH_POST


async def _button_text_step(update, context, msg, enh, chat_id):
    text = (msg.text or "").strip()
    if not text:
        enh["step"] = "btns"
        await _render(context, chat_id)
        return ENH_POST
    if text.lower() in ("yo'q", "yoq", "bekor", "orqaga"):
        enh["step"] = "btns"
        await _render(context, chat_id)
        return ENH_POST

    parsed = parse_button_line(text)
    if not parsed or len(parsed["url"]) > BTN_URL_MAX:
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
    if isinstance(idx, int) and 0 <= idx < len(buttons):
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
    enh.pop("_btn_pending_idx", None)
    await msg.reply_text(
        f"✅ Tugma saqlandi: <b>{html_escape(parsed['text'])}</b> → "
        f"<code>{html_escape(parsed['url'])}</code>",
        parse_mode="HTML",
    )
    await _render(context, chat_id)
    return ENH_POST


# ============================================================
# INLINE CALLBACK YO'NALTIRUVCHISI (enh:*)
# ============================================================

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
        try:
            await query.answer()
        except Exception:
            pass
        return ENH_POST

    if not isinstance(enh, dict) or (not enh.get("post") and action not in ("cancel", "again")):
        try:
            await query.answer("⚠️ Sessiya tugagan — menyuni qaytadan oching.", show_alert=True)
        except Exception:
            pass
        return ConversationHandler.END

    if action == "cancel":
        await query.answer()
        context.user_data.clear()
        try:
            await query.message.delete()
        except Exception:
            pass
        await context.bot.send_message(
            chat_id=user_id,
            text="✅ <b>Qo'shimcha funksiyalar</b> bo'limi yopildi.",
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if action == "again":
        await query.answer()
        context.user_data[_ENH_KEY] = {"step": "content", "post": None, "reactions": [],
                                       "buttons": [], "hub_msg_id": None, "btn_edit": None,
                                       "channels": [], "ch_idx": None}
        await query.message.reply_text(
            "🚀 <b>Yangi post</b> — kuchaytirmoqchi bo'lgan postingizni yuboring "
            "(matn, rasm, video, albom yoki forward):",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return ENH_POST

    if action == "screen":
        await query.answer()
        enh["step"] = arg if arg in _VIEWS else "hub"
        if enh["step"] == "channel":
            channels = await db.run_db(db.get_user_channels, user_id)
            if not channels:
                await query.answer("⚠️ Ulangan kanal yo'q — avval kanal ulang.", show_alert=True)
                enh["step"] = "hub"
            else:
                enh["channels"] = channels
        await _render(context, chat_id, target_msg=query.message,
                      watermark_note=await _plan_note(user_id))
        return ENH_POST

    if action == "rtgl":
        await query.answer()
        emoji = arg
        if not emoji:
            return ENH_POST
        selected = list(enh.get("reactions") or [])
        if emoji in selected:
            selected.remove(emoji)
        elif len(selected) >= MAX_ENH_REACTIONS:
            try:
                await query.answer(f"⚠️ Maksimum {MAX_ENH_REACTIONS} ta reaksiya!", show_alert=True)
            except Exception:
                pass
            return ENH_POST
        else:
            selected.append(emoji)
        enh["reactions"] = selected
        await _render(context, chat_id)
        return ENH_POST

    if action == "react":
        await query.answer()
        if arg == "clear":
            enh["reactions"] = []
        enh["step"] = "hub"
        await _render(context, chat_id)
        return ENH_POST

    if action == "btn":
        return await _btn_action(update, context, query, arg, arg2, enh, chat_id)

    if action == "preview":
        await query.answer()
        await _send_preview(context, user_id, enh)
        return ENH_POST

    if action == "replace":
        await query.answer()
        enh["step"] = "content"
        await query.message.reply_text(
            "🔁 <b>Yangi postni yuboring</b> — joriy post (matn/media) almashtiriladi. "
            "Reaksiyalar va tugmalar saqlanadi 👇",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return ENH_POST

    if action == "send":
        await query.answer()
        try:
            idx = int(arg)
        except (TypeError, ValueError):
            return ENH_POST
        channels = enh.get("channels") or []
        if not (0 <= idx < len(channels)):
            await query.answer("⚠️ Bu kanal endi ro'yxatda yo'q.", show_alert=True)
            return ENH_POST
        enh["ch_idx"] = idx
        enh["step"] = "confirm"
        await _render(context, chat_id, watermark_note=await _plan_note(user_id))
        return ENH_POST

    if action == "confirm_send":
        await query.answer()
        return await _execute_send(update, context, query, enh)

    return ENH_POST


async def _btn_action(update, context, query, arg, arg2, enh, chat_id):
    user_id = query.from_user.id
    if arg == "add":
        await query.answer()
        if len(enh.get("buttons") or []) >= MAX_ENH_BUTTONS:
            await query.answer(f"⚠️ Maksimum {MAX_ENH_BUTTONS} ta tugma!", show_alert=True)
            return ENH_POST
        enh["_btn_pending_idx"] = None
        enh["step"] = "btn_input"
        await query.message.reply_text(
            "➕ <b>Yangi URL tugma</b>\n\n"
            "Bir qatorda yuboring:\n"
            "<code>Tugma yozuvi - https://sayt.uz</code>\n"
            "<code>Kanalga a'zo bo'lish | @kanal_ismi</code>\n"
            "<code>Botim - t.me/bot_ismi/start</code>\n\n"
            "<i>Faqat havola yuborsangiz — yozuv avtomatik tanlanadi.</i>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="enh:screen:btns")]]
            ),
            parse_mode="HTML",
        )
        return ENH_POST

    if arg in ("edit", "del"):
        try:
            idx = int(arg2)
        except (TypeError, ValueError):
            return ENH_POST
        buttons = list(enh.get("buttons") or [])
        if not (0 <= idx < len(buttons)):
            await query.answer("⚠️ Tugma topilmadi (ro'yxat o'zgargan).", show_alert=True)
            enh["step"] = "btns"
            await _render(context, chat_id)
            return ENH_POST

        if arg == "del":
            await query.answer()
            removed = buttons.pop(idx)
            enh["buttons"] = buttons
            enh["step"] = "btns"
            await _render(context, chat_id)
            logger.info("Enhancer: tugma o'chirildi (%s → %s)", user_id, removed.get("url"))
            return ENH_POST

        await query.answer()
        enh["_btn_pending_idx"] = idx
        enh["step"] = "btn_input"
        current = buttons[idx]
        await query.message.reply_text(
            f"✏️ <b>{idx + 1}-tugmani tahrirlash</b>\n\n"
            f"Hozir: <b>{html_escape(current['text'])}</b> → <code>{html_escape(current['url'])}</code>\n\n"
            "Yangi qiymatni bir qatorda yuboring:\n"
            "<code>Yangi yozuv - https://yangi-havola.uz</code>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Bekor qilish", callback_data="enh:screen:btns")]]
            ),
            parse_mode="HTML",
        )
        return ENH_POST

    if arg == "clear":
        await query.answer()
        enh["buttons"] = []
        enh["step"] = "btns"
        await _render(context, chat_id)
        return ENH_POST

    return ENH_POST


# ============================================================
# PREVYU
# ============================================================

async def _send_preview(context, user_id: int, enh: dict):
    """Postni bot chatida haqiqiy tugmalar bilan ko'rsatadi (kanalda chiqadigan joylashuv)."""
    post = enh.get("post") or {}
    ptype = post.get("type") or "text"
    file_id = post.get("file_id")
    content = post.get("content") or ""
    if ptype != "sticker":
        content = (content[:1000] + "…") if (ptype != "text" and len(content) > 1000) else content
        if len(content) > 4000:
            content = content[:4000] + "…"
    markup = build_enhancer_markup(enh.get("buttons"), enh.get("reactions"), post_id=None, preview=True)
    bot = context.bot
    try:
        if ptype == "album":
            items = parse_album_items(file_id)
            media = _build_album_media_local(items, content, parse_mode="HTML")
            try:
                await bot.send_media_group(chat_id=user_id, media=media)
            except TelegramError:
                await bot.send_media_group(chat_id=user_id, media=_build_album_media_local(items, content, parse_mode=None))
            if markup:
                await bot.send_message(chat_id=user_id, text="👆 <i>Yuqorida — prevyu. Tugmalar kanalda shu post ostida chiqadi.</i>",
                                       reply_markup=markup, parse_mode="HTML")
            return
        sent = await _dispatch_message(bot, user_id, ptype, file_id, content, markup, html=True)
        if sent is None:
            await bot.send_message(chat_id=user_id, text="⚠️ Prevyu yasab bo'lmadi (media fayli yaroqsiz).")
    except Exception:
        logger.exception("Enhancer prevyu xatosi")
        try:
            await bot.send_message(chat_id=user_id, text="⚠️ Prevyu ko'rsatib bo'lmadi.")
        except Exception:
            pass


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
        await query.answer("⏳ Juda tez — birozdan so'ng qayta urinib ko'ring.", show_alert=True)
        return ENH_POST

    channels = enh.get("channels") or []
    idx = enh.get("ch_idx")
    if not isinstance(idx, int) or not (0 <= idx < len(channels)):
        await query.answer("⚠️ Kanal tanlanmagan.", show_alert=True)
        return ENH_POST
    ch_id, ch_title = channels[idx][:2]

    # Kanal hali ham foydalanuvchiga tegishli mi? (egallik tekshiruvi)
    owned = await db.run_db(db.get_user_channels, user_id)
    if not any(str(c[0]) == str(ch_id) for c in (owned or [])):
        await query.answer("⚠️ Bu kanal endi sizning ro'yxatingizda yo'q.", show_alert=True)
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
        channel_ad = ""
        if not has_ad_free:
            channel_ad = await get_channel_ad_next_async()
        brand_text = (await db.run_db(db.get_setting, "post_tag_text", "") or "").strip()
        watermarked = await apply_post_watermark(content, user_id, BOT_USERNAME)
        text_limit = 4096 if ptype == "text" else 1024
        final_content = compose_post_text(watermarked, has_ad_free, channel_ad, brand_text,
                                          limit=text_limit)
    except Exception:
        logger.exception("Enhancer: matnni tayyorlashda xato")
        await query.answer("⚠️ Postni tayyorlab bo'lmadi. Qaytadan urinib ko'ring.", show_alert=True)
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
    markup = build_enhancer_markup(buttons, reactions, post_id=pid or None)

    target_chat = int(ch_id) if str(ch_id).lstrip("-").isdigit() else ch_id
    try:
        result = await _dispatch_message(context.bot, target_chat, ptype, file_id,
                                         final_content, markup, html=True)
    except TelegramError as e:
        if pid:
            await db.run_db(db.mark_post_status, pid, "cancelled")
        err = str(e).lower()
        if "bot was kicked" in err or "chat not found" in err or "not enough rights" in err:
            tip = "⚠️ Bot kanalda admin emas (yoki ruxsati yo'q). Kanalga admin qilib qo'shing."
        else:
            tip = f"⚠️ Yuborib bo'lmadi: {html_escape(str(e))[:200]}"
        try:
            await query.answer(tip, show_alert=True)
        except Exception:
            pass
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

    enh["step"] = "sent"
    text, markup_done = _success_view()
    try:
        await query.edit_message_text(text, reply_markup=markup_done, parse_mode="HTML")
        enh["hub_msg_id"] = query.message.message_id
    except Exception:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup_done,
                                       parse_mode="HTML")
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
