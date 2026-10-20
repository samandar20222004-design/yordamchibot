"""🧭 AQLLI QABUL — menyu tashqarisida kelgan xabar uchun «Bu bilan nima qilamiz?».

MUAMMO: foydalanuvchi shunchaki matn/rasm yuborsa, bot o'zicha AI'ni ishga
tushirardi (rasm → darhol Vision tahlili), foydalanuvchi esa faqat kanalga
chiqarmoqchi edi — AI xarajati va kutish bekorga ketardi.

QOIDA: dialogdan TASHQARIDA kelgan matn / rasm / video / hujjat / albom uchun
AI HECH QACHON o'zi ishlamaydi. Bot xabarni eslab qoladi va uch yo'l beradi:

  * 📝 Post qilish   — xabar O'ZGARTIRILMASDAN oddiy post preview'iga o'tadi
                       (vaqt, tugma, reaksiya, kanalga yuborish shu yerda);
  * ✨ AI ...        — faqat bosilganda: matn → Magic Post uslub tanlash,
                       rasm → Vision/Magic Post (kredit uslub tanlanganda);
  * ❌ Yopish        — hech narsa qilinmaydi.

Xabar modul darajasidagi TTL keshida saqlanadi (``clear_fsm_data`` butun
``user_data`` ni tozalaydi, shu sababli u yerda saqlab bo'lmaydi).
"""
import logging
import time
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler

from locales.translations import get_lang
from services.album_gate import take_album_payload
from translations import content_menu_t
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

IN_POST = "in_post"
IN_AI = "in_ai"
IN_CLOSE = "in_close"

#: Matn «xabar»ga o'xshashligi uchun eng kam chegara («ha», «???» o'tmaydi).
MIN_TEXT_CHARS = 8
MIN_TEXT_WORDS = 2

_TTL_SECONDS = 20 * 60
_MAX_KEYS = 5000
_CACHE: dict = {}


def _put(user_id: int, snap: dict) -> None:
    if len(_CACHE) > _MAX_KEYS:
        _CACHE.clear()
    _CACHE[user_id] = (snap, time.time())


def peek(user_id: int) -> Optional[dict]:
    item = _CACHE.get(user_id)
    if not item:
        return None
    snap, ts = item
    if time.time() - ts > _TTL_SECONDS:
        _CACHE.pop(user_id, None)
        return None
    return snap


def take(user_id: int) -> Optional[dict]:
    snap = peek(user_id)
    _CACHE.pop(user_id, None)
    return snap


def looks_like_message(text) -> bool:
    """Matn oddiy javob («ha», «rahmat», «???») emas, post boshlang'ichiga o'xshaydimi."""
    if not isinstance(text, str):
        return False
    value = text.strip()
    if not value or value.startswith("/"):
        return False
    return len(value) >= MIN_TEXT_CHARS and len(value.split()) >= MIN_TEXT_WORDS


def _snapshot(msg, album_items: Optional[list] = None) -> Optional[dict]:
    """Xabardan keyinchalik postga aylantirish uchun kerakli ma'lumot."""
    from handlers.manual_post import _extract_media

    if album_items:
        caption = ""
        for item in album_items:
            caption = (item.get("caption") or "").strip()
            if caption:
                break
        return {"kind": "album", "text": caption, "file_id": None,
                "post_type": "album", "album": album_items, "message": msg}
    file_id, post_type = _extract_media(msg)
    text = (getattr(msg, "text", None) or getattr(msg, "caption", None) or "").strip()
    if file_id:
        return {"kind": "photo" if post_type == "photo" else "media",
                "text": text, "file_id": file_id, "post_type": post_type,
                "album": None, "message": msg}
    if looks_like_message(text):
        return {"kind": "text", "text": text, "file_id": None,
                "post_type": "text", "album": None, "message": msg}
    return None


def intake_keyboard(kind: str, lang: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(content_menu_t("in_btn_post", lang), callback_data=IN_POST)]]
    if kind == "text":
        rows.append([InlineKeyboardButton(content_menu_t("in_btn_ai_text", lang), callback_data=IN_AI)])
    elif kind == "photo":
        rows.append([InlineKeyboardButton(content_menu_t("in_btn_ai_photo", lang), callback_data=IN_AI)])
    rows.append([InlineKeyboardButton(content_menu_t("in_btn_close", lang), callback_data=IN_CLOSE)])
    return InlineKeyboardMarkup(rows)


async def offer_intake(update: Update, context: ContextTypes.DEFAULT_TYPE, lang: str) -> bool:
    """Xabar uchun «nima qilamiz?» taklifini yuboradi. ``False`` — xabar mos emas
    (qisqa javob, ovoz, stiker...) va eski xulq davom etadi. AI chaqirilmaydi."""
    msg = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", 0) or 0
    if msg is None or not user_id:
        return False
    album_items = None
    payload = take_album_payload(context, msg)
    if payload is not None and payload.is_album:
        album_items = [
            {"type": i.get("type") or "photo", "file_id": i.get("file_id"),
             "caption": i.get("caption") or "", "message_id": i.get("message_id")}
            for i in payload.media_items()
            if (i.get("type") or "") not in ("voice", "sticker") and i.get("file_id")
        ]
        if len(album_items) < 2:
            album_items = None
    snap = _snapshot(msg, album_items)
    if snap is None:
        return False
    _put(user_id, snap)
    key = {"text": "in_offer_text", "photo": "in_offer_photo",
           "media": "in_offer_media", "album": "in_offer_album"}[snap["kind"]]
    text = content_menu_t(key, lang)
    if snap["kind"] == "album":
        text = text.replace("{n}", str(len(snap["album"])))
    await msg.reply_text(text, reply_markup=intake_keyboard(snap["kind"], lang),
                         parse_mode="HTML")
    return True


async def _drop_offer(query) -> None:
    """Taklif oynasi ochiq qolmasin (o'chirib bo'lmasa — tugmalari olib tashlanadi)."""
    try:
        await query.message.delete()
        return
    except Exception as _silent_exc:
        log_silent_failure("handlers.smart_intake:_drop_offer:delete", _silent_exc)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as _silent_exc:
        log_silent_failure("handlers.smart_intake:_drop_offer:markup", _silent_exc)


async def intake_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``in_post`` / ``in_ai`` / ``in_close`` — asosiy FSM kirish nuqtasi."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()
    lang = get_lang(context)
    user_id = getattr(update.effective_user, "id", 0) or 0
    data = query.data or ""

    if data == IN_CLOSE:
        _CACHE.pop(user_id, None)
        await _drop_offer(query)
        try:
            from keyboards.default import get_main_keyboard
            from config import ADMIN_IDS_SET
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=content_menu_t("in_closed", lang),
                reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang),
            )
        except Exception as _silent_exc:
            log_silent_failure("handlers.smart_intake:close", _silent_exc)
        return ConversationHandler.END

    snap = take(user_id)
    if snap is None:
        try:
            await query.message.reply_text(content_menu_t("in_expired", lang))
        except Exception as _silent_exc:
            log_silent_failure("handlers.smart_intake:expired", _silent_exc)
        await _drop_offer(query)
        return ConversationHandler.END

    if data == IN_AI and snap["kind"] == "text":
        # Taklif oynasi o'z joyida uslub tanlash ekraniga aylanadi.
        from handlers.content_creation import open_magic_style_menu, remember_direct_text
        remember_direct_text(user_id, snap["text"])
        return await open_magic_style_menu(query, context, user_id, lang)

    await _drop_offer(query)

    if data == IN_POST:
        from handlers.manual_post import manual_post_from_snapshot
        return await manual_post_from_snapshot(update, context, snap)

    if data == IN_AI and snap["kind"] == "photo":
        # Faqat foydalanuvchi so'raganda: rasm → Vision → uslub tanlash.
        from handlers.image_post import image_photo_received
        return await image_photo_received(Update(0, message=snap["message"]), context)

    return ConversationHandler.END


def intake_handler() -> CallbackQueryHandler:
    return CallbackQueryHandler(intake_callback, pattern=r"^in_(post|ai|close)$")


async def photo_intake_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dialogdan tashqari rasm: Vision O'ZI ishlamaydi — avval «nima qilamiz?»."""
    from handlers.image_post import image_photo_received
    from utils.helpers import send_no_channel_media_guide

    msg = getattr(update, "effective_message", None)
    caption = ((getattr(msg, "caption", None) or "").strip().lower())
    if caption.split(" ", 1)[0].split("@", 1)[0] == "/ai":
        # Aniq buyruq (/ai + rasm) — foydalanuvchi AI so'ragan.
        return await image_photo_received(update, context)
    if await send_no_channel_media_guide(update, context):
        return ConversationHandler.END
    lang = get_lang(context)
    if not await offer_intake(update, context, lang):
        return await image_photo_received(update, context)
    return ConversationHandler.END
