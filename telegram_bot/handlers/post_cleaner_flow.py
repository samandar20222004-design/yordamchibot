"""🧹 Post tozalash va imzo — tezkor rejim.

Foydalanuvchi oqimi:

1. ⚙️ Sozlamalar → 🧹 Post tozalash va imzo (yoki ``/cleaner``).
2. «✍️ Imzoni sozlash» — bir marta: havola (``@kanal`` / ``https://...``)
   yoki matn; matnga havola ulash mumkin. Cheklov: 10 qator, 300 so'z.
3. «🧹 Boshlash» — rejim yoqiladi. Endi har bir yuborilgan
   (yoki forward qilingan) post bir zumda tozalanadi: oxiridagi begona
   havola/reklama qatorlari olib tashlanadi, matnning qolgan qismi
   o'zgarmaydi, oxiriga imzo qo'shiladi.
4. Tayyor post kanalga yuboriladi: «⚡ Darhol yuborish» yoqilgan va bitta
   kanal bo'lsa — avtomatik, aks holda post ostidagi kanal tugmasi bilan.

Albom (bir nechta rasm/video) ``media_group_id`` bo'yicha 1.5 soniyalik
debounce bilan yig'iladi va BITTA post (``album``) sifatida tozalanadi: izoh
butun albomga biriktiriladi (``services/media_group_collector.py``).

Tezlik: imzo, kanallar va tarif rejim ochilganda BIR MARTA yuklanadi
(``user_data``), har bir post DB'ga murojaatsiz qayta ishlanadi.
"""

from __future__ import annotations

import asyncio
import functools
import itertools
import json
import logging

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    Update,
)
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import ADMIN_IDS_SET, BOT_USERNAME
from services.post_cleaner import (
    CAPTION_LIMIT,
    SIGNATURE_MAX_CHARS,
    SIGNATURE_MAX_LINES,
    SIGNATURE_MAX_WORDS,
    TEXT_LIMIT,
    html_to_segment,
    find_link_url,
    own_channel_usernames,
    quick_clean,
    signature_from_message,
    signature_problems,
    wrap_signature_link,
)
from services.album_gate import take_album_payload
from services.media_group_collector import (
    ALBUM_DEBOUNCE_SECONDS as _ALBUM_DEBOUNCE_SECONDS,
)
from services.media_group_collector import FULL, MediaGroupCollector
from translations import settings_stats_t as t
from utils.channel_labels import channel_label_html, sent_notice
from utils.helpers import html_escape, watermark_footer_length, watermark_header
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

#: FSM holatlari (545 — imzo matni; 546 — imzo havolasi; 547 — tozalash rejimi).
CLEANER_SIGNATURE_INPUT = 545
CLEANER_SIGNATURE_LINK = 546
CLEANER_POST_INPUT = 547

#: «⚡ Darhol yuborish» sozlamasi (``user_settings``).
AUTOSEND_KEY = "cleaner_autosend"

CB_SCREEN = "stgs_clean"
CB_START = "stgs_clean_go"
CB_STOP = "stgs_clean_stop"
CB_SIG = "stgs_clean_sig"
CB_SIG_NOLINK = "stgs_clean_signl"
CB_SIG_CLEAR = "stgs_clean_sig_clear"
CB_AUTO = "stgs_clean_auto"
CB_ADVANCED = "stgs_clean_adv"
CB_PUBLISH = "stgs_clean_pub"

_UD_SESSION = "cl_session"
_UD_PENDING = "cl_pending"
_UD_SIG_DRAFT = "cl_sig_draft"
#: Xotirada saqlanadigan tayyor postlar soni (eski tugmalar «eskirgan» bo'ladi).
_PENDING_MAX = 20
#: Kanal tugmalari soni.
_CHANNEL_BUTTONS_MAX = 8
#: Yuborilganini tekshirish: urinishlar × oraliq (soniya).
_STATUS_POLLS, _STATUS_POLL_DELAY = 20, 0.5

_TOKENS = itertools.count(1)

#: Telegram xabar turi → ``scheduled_posts.post_type`` va ``file_id`` manbai.
_MEDIA_TYPES = ("photo", "video", "animation", "document", "audio", "voice")

#: Albomga kira oladigan turlar (ovozli xabar albomga kirmaydi).
_ALBUM_KINDS = ("photo", "video", "document", "audio", "animation")

#: Albom (media_group) yig'uvchi: bir nechta fayl BITTA post bo'lib tozalanadi.
#: Debounce — oxirgi fayldan keyingi jimlik oynasi; YAGONA manba
#: ``services.media_group_collector.ALBUM_DEBOUNCE_SECONDS`` (qat'iy 2.0s).
#: Kutish fon vazifada (handler bloklanmaydi, foydalanuvchi updatelari ketma-ket
#: ishlanadi).
ALBUM_DEBOUNCE_SECONDS = _ALBUM_DEBOUNCE_SECONDS
_ALBUMS = MediaGroupCollector(delay=ALBUM_DEBOUNCE_SECONDS)


async def _lang(context, user_id) -> str:
    from handlers.start import ensure_user_lang

    return await ensure_user_lang(context, user_id)


def _btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


async def _answer(query, text: str = "", alert: bool = False) -> None:
    try:
        await query.answer(text or None, show_alert=alert)
    except Exception as exc:
        log_silent_failure("handlers.post_cleaner_flow:_answer", exc)


# ============================================================
# 1) SOZLASH EKRANI
# ============================================================
async def build_screen(user_id: int, lang: str) -> tuple:
    """Ekran matni va tugmalari (imzo + «⚡ Darhol yuborish» holati)."""
    try:
        signature, autosend = await asyncio.gather(
            db.run_db(db.get_user_post_signature_html, user_id),
            db.run_db(db.get_user_setting, user_id, AUTOSEND_KEY, False),
        )
    except Exception as exc:  # baza javob bermasa ham ekran ochiladi
        log_silent_failure("handlers.post_cleaner_flow:build_screen", exc, user_id=user_id)
        signature, autosend = "", False
    state_on = t("ss_cl_on", lang) if autosend else t("ss_cl_off", lang)
    parts = [t("ss_cl_title", lang), t("ss_cl_how", lang)]
    parts.append(t("ss_cl_sig_line", lang, sig=signature) if signature
                 else t("ss_cl_sig_none", lang))
    parts.append(t("ss_cl_auto_line", lang, state=state_on))
    rows = [
        [_btn(t("ss_cl_btn_start", lang), CB_START)],
        [_btn(t("ss_cl_btn_sig", lang), CB_SIG),
         _btn(t("ss_cl_btn_auto", lang, state="✅" if autosend else "⬜️"), CB_AUTO)],
    ]
    if signature:
        rows.append([_btn(t("ss_cl_btn_clear", lang), CB_SIG_CLEAR)])
    rows.append([_btn(t("ss_cl_btn_adv", lang), CB_ADVANCED)])
    rows.append([_btn(t("ss_btn_back", lang), "stgs_hub")])
    return "".join(parts), InlineKeyboardMarkup(rows)


async def render_screen(query, user_id: int, lang: str) -> None:
    """Ekranni joriy xabar o'rnida chizadi (bo'lmasa yangi xabar)."""
    text, markup = await build_screen(user_id, lang)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        return
    except Exception as exc:
        if "not modified" in str(exc).lower():
            return
    await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def send_screen(bot, chat_id: int, user_id: int, lang: str) -> None:
    text, markup = await build_screen(user_id, lang)
    await bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")


async def toggle_autosend(query, user_id: int, lang: str) -> None:
    current = await db.run_db(db.get_user_setting, user_id, AUTOSEND_KEY, False)
    await db.run_db(db.set_user_setting, user_id, AUTOSEND_KEY, not current)
    await _answer(query)
    await render_screen(query, user_id, lang)


async def clear_signature(query, user_id: int, lang: str) -> None:
    saved = await db.run_db(db.set_user_post_signature_html, user_id, "", "")
    await _answer(query, t("ss_clean_sig_cleared", lang) if saved
                  else t("ss_clean_sig_none", lang))
    await render_screen(query, user_id, lang)


# ============================================================
# 2) IMZONI SOZLASH (bir marta)
# ============================================================
async def signature_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await _answer(query)
    lang = await _lang(context, user_id)
    context.user_data.pop(_UD_SIG_DRAFT, None)
    prompt = t("ss_cl_sig_prompt", lang, lines=SIGNATURE_MAX_LINES,
               words=SIGNATURE_MAX_WORDS, chars=SIGNATURE_MAX_CHARS)
    try:
        await query.edit_message_text(prompt, parse_mode="HTML")
    except Exception:
        await query.message.reply_text(prompt, parse_mode="HTML")
    return CLEANER_SIGNATURE_INPUT


def _limit_details(problems: dict, lang: str) -> str:
    keys = {"lines": "ss_cl_lim_lines", "words": "ss_cl_lim_words", "chars": "ss_cl_lim_chars"}
    return "\n".join(t(keys[name], lang, n=value[0], max=value[1])
                     for name, value in problems.items())


async def _save_signature(update, context, user_id: int, lang: str, html: str) -> int:
    plain = html_to_segment(html).text
    if not await db.run_db(db.set_user_post_signature_html, user_id, html, plain):
        await update.effective_message.reply_text(t("ss_clean_sig_rejected", lang),
                                                  parse_mode="HTML")
        return CLEANER_SIGNATURE_INPUT
    context.user_data.pop(_UD_SIG_DRAFT, None)
    context.user_data.pop(_UD_SESSION, None)  # rejim yangi imzoni olishi uchun
    await update.effective_message.reply_text(t("ss_cl_sig_saved", lang), parse_mode="HTML")
    await send_screen(context.bot, update.effective_chat.id, user_id, lang)
    return ConversationHandler.END


async def signature_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imzo matni: cheklov tekshiruvi → havolasi bo'lsa saqlanadi, bo'lmasa so'raladi."""
    message = update.message
    user_id = update.effective_user.id
    lang = await _lang(context, user_id)
    text = (message.text or "") if message else ""
    if not text.strip():
        await message.reply_text(t("ss_cl_sig_need_text", lang), parse_mode="HTML")
        return CLEANER_SIGNATURE_INPUT
    problems = signature_problems(text)
    if problems:
        await message.reply_text(
            t("ss_cl_sig_too_long", lang, details=_limit_details(problems, lang)),
            parse_mode="HTML",
        )
        return CLEANER_SIGNATURE_INPUT
    html, has_link = signature_from_message(text, message.entities)
    if has_link:
        return await _save_signature(update, context, user_id, lang, html)
    context.user_data[_UD_SIG_DRAFT] = html
    await message.reply_text(
        t("ss_cl_sig_ask_link", lang), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[_btn(t("ss_cl_btn_nolink", lang), CB_SIG_NOLINK)]]),
    )
    return CLEANER_SIGNATURE_LINK


async def signature_link_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Imzo matniga ulanadigan havola."""
    user_id = update.effective_user.id
    lang = await _lang(context, user_id)
    draft = context.user_data.get(_UD_SIG_DRAFT)
    if not draft:
        return await signature_entry_message(update, context, lang)
    url = find_link_url(update.message.text or "")
    if not url:
        await update.message.reply_text(t("ss_cl_bad_link", lang), parse_mode="HTML")
        return CLEANER_SIGNATURE_LINK
    return await _save_signature(update, context, user_id, lang,
                                 wrap_signature_link(draft, url))


async def signature_nolink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«💾 Havolasiz saqlash»."""
    query = update.callback_query
    user_id = query.from_user.id
    await _answer(query)
    lang = await _lang(context, user_id)
    draft = context.user_data.get(_UD_SIG_DRAFT)
    if not draft:
        await query.message.reply_text(t("ss_cl_expired", lang), parse_mode="HTML")
        return ConversationHandler.END
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as exc:
        log_silent_failure("handlers.post_cleaner_flow:signature_nolink", exc)
    return await _save_signature(update, context, user_id, lang, draft)


async def signature_entry_message(update, context, lang: str):
    prompt = t("ss_cl_sig_prompt", lang, lines=SIGNATURE_MAX_LINES,
               words=SIGNATURE_MAX_WORDS, chars=SIGNATURE_MAX_CHARS)
    await update.effective_message.reply_text(prompt, parse_mode="HTML")
    return CLEANER_SIGNATURE_INPUT


# ============================================================
# 3) TOZALASH REJIMI
# ============================================================
async def _load_session(user_id: int) -> dict:
    """Rejim uchun hamma narsa BIR MARTA (parallel) yuklanadi."""
    signature, autosend, channels, own, premium = await asyncio.gather(
        db.run_db(db.get_user_post_signature_html, user_id),
        db.run_db(db.get_user_setting, user_id, AUTOSEND_KEY, False),
        db.run_db(db.get_user_channels, user_id),
        own_channel_usernames(user_id),
        db.run_db(db.is_premium, user_id),
    )
    return {
        "signature": signature or "",
        "autosend": bool(autosend),
        "channels": [(str(c[0]), str(c[1] or c[0])) for c in (channels or [])],
        "own": frozenset(own or ()),
        # Bepul foydalanuvchi postining BOSHIGA «🤖 @bot» qo'shiladi — joy qoldiramiz.
        "reserve": 0 if (premium or user_id in ADMIN_IDS_SET)
        else watermark_footer_length(BOT_USERNAME),
    }


async def mode_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«🧹 Boshlash»."""
    query = update.callback_query
    user_id = query.from_user.id
    lang = await _lang(context, user_id)
    session = await _load_session(user_id)
    if not session["signature"]:
        await _answer(query, t("ss_cl_no_sig", lang), alert=True)
        return ConversationHandler.END
    await _answer(query)
    context.user_data[_UD_SESSION] = session
    channels = session["channels"]
    if not channels:
        dest = t("ss_cl_dest_none", lang)
    elif session["autosend"] and len(channels) == 1:
        dest = t("ss_cl_dest_auto", lang, channel=html_escape(channels[0][1]))
    else:
        dest = t("ss_cl_dest_pick", lang)
    await query.message.reply_text(
        t("ss_cl_mode_on", lang, dest=dest), parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[_btn(t("ss_cl_btn_stop", lang), CB_STOP)]]),
    )
    return CLEANER_POST_INPUT


async def mode_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await _answer(query)
    lang = await _lang(context, user_id)
    context.user_data.pop(_UD_SESSION, None)
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as exc:
        log_silent_failure("handlers.post_cleaner_flow:mode_stop", exc)
    await query.message.reply_text(t("ss_cl_mode_off", lang), parse_mode="HTML")
    return ConversationHandler.END


def _message_payload(message) -> tuple:
    """``(post_type, file_id, text, entities)`` yoki turi qo'llanmasa ``None``."""
    if message.text:
        return "text", None, message.text, message.entities
    for kind in _MEDIA_TYPES:
        media = getattr(message, kind, None)
        if not media:
            continue
        if kind == "photo":
            media = media[-1]
        return kind, media.file_id, message.caption or "", message.caption_entities
    return None


def _remember(context, item: dict) -> str:
    pending = context.user_data.setdefault(_UD_PENDING, {})
    token = str(next(_TOKENS))
    pending[token] = item
    while len(pending) > _PENDING_MAX:
        pending.pop(next(iter(pending)))
    return token


def _album_item(message) -> dict | None:
    """Albom elementi: ``{message_id, type, file_id, caption, entities}`` (yoki ``None``)."""
    for kind in _ALBUM_KINDS:
        media = getattr(message, kind, None)
        if not media:
            continue
        if kind == "photo":
            media = media[-1]
        return {
            "message_id": getattr(message, "message_id", None),
            "type": kind,
            "file_id": media.file_id,
            "caption": message.caption or "",
            "entities": tuple(message.caption_entities or ()),
        }
    return None


def _album_media(items: list, html: str) -> list:
    """``send_media_group`` uchun InputMedia ro'yxati; izoh faqat BIRINCHI faylda."""
    media = []
    for index, entry in enumerate(items):
        caption = (html or None) if index == 0 else None
        mode = "HTML" if caption else None
        kind, file_id = entry.get("type"), entry["file_id"]
        if kind == "video":
            media.append(InputMediaVideo(file_id, caption=caption, parse_mode=mode))
        elif kind in ("document", "animation"):
            media.append(InputMediaDocument(file_id, caption=caption, parse_mode=mode))
        elif kind == "audio":
            media.append(InputMediaAudio(file_id, caption=caption, parse_mode=mode))
        else:
            media.append(InputMediaPhoto(file_id, caption=caption, parse_mode=mode))
    return media


async def _send_preview(bot, chat_id: int, item: dict, markup, lang: str = "uz") -> None:
    if item["type"] == "album":
        entries = json.loads(item["file_id"])
        await bot.send_media_group(chat_id, media=_album_media(entries, item["html"]))
        if markup is not None:
            await bot.send_message(chat_id, t("ss_cl_album_pick", lang, count=len(entries)),
                                   parse_mode="HTML", reply_markup=markup)
        return
    if item["type"] == "text":
        await bot.send_message(chat_id, item["html"], parse_mode="HTML", reply_markup=markup)
        return
    method = getattr(bot, f"send_{item['type']}")
    await method(chat_id, item["file_id"], caption=item["html"] or None,
                 parse_mode="HTML", reply_markup=markup)


async def post_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rejimdagi har bir post: tozalash → cheklov → kanalga yoki tugmalar bilan."""
    message = update.message
    user_id = update.effective_user.id
    lang = await _lang(context, user_id)
    session = context.user_data.get(_UD_SESSION)
    if not session:
        session = await _load_session(user_id)
        context.user_data[_UD_SESSION] = session
    if not session["signature"]:
        await message.reply_text(t("ss_cl_no_sig", lang), parse_mode="HTML")
        return ConversationHandler.END
    # 🖼 KONSOLIDATSIYALANGAN ALBOM: ``services/album_gate.py`` butun media
    # guruhni yig'ib BITTA update qilib qaytargan bo'lsa — barcha fayllar bir
    # yo'la buferga yoziladi. Natijada bitta albom = bitta tozalangan post,
    # bitta preview (kanalga esa bitta ``sendMediaGroup``).
    _payload = take_album_payload(context, message)
    if _payload is not None and _payload.is_album:
        entries = [
            {
                "message_id": raw_item.get("message_id"),
                "type": raw_item.get("type") or "photo",
                "file_id": raw_item.get("file_id"),
                "caption": raw_item.get("caption") or "",
                "entities": tuple(raw_item.get("entities") or ()),
            }
            for raw_item in _payload.media_items()
        ]
        entries = [entry for entry in entries if entry["file_id"]]
        if entries:
            key = (user_id, str(_payload.media_group_id))
            _ALBUMS.add_many(key, entries, functools.partial(
                _album_ready, context, user_id, lang, message.chat_id))
            return CLEANER_POST_INPUT

    if message.media_group_id:
        # Albom: fayllar fon kollektorida yig'iladi (handler darhol qaytadi),
        # jimlikdan keyin BITTA post sifatida tozalanadi (izoh — albom izohi).
        entry = _album_item(message)
        if entry is None:
            await message.reply_text(t("ss_cl_unsupported", lang), parse_mode="HTML")
            return CLEANER_POST_INPUT
        key = (user_id, str(message.media_group_id))
        outcome = _ALBUMS.add(key, entry, functools.partial(
            _album_ready, context, user_id, lang, message.chat_id))
        if outcome == FULL:
            logger.info("cleaner: albom 10 fayldan oshdi (user=%s) — ortiqchasi tashlandi", user_id)
        return CLEANER_POST_INPUT
    payload = _message_payload(message)
    if payload is None:
        await message.reply_text(t("ss_cl_unsupported", lang), parse_mode="HTML")
        return CLEANER_POST_INPUT

    post_type, file_id, text, entities = payload
    result = quick_clean(text, entities, session["signature"], session["own"])
    limit = TEXT_LIMIT if post_type == "text" else CAPTION_LIMIT
    total = result.length + session["reserve"]
    if total > limit:
        note = t("ss_cl_limit_text" if post_type == "text" else "ss_cl_limit_caption", lang)
        await message.reply_text(
            t("ss_cl_too_long", lang, length=total, limit=limit, note=note, over=total - limit),
            parse_mode="HTML",
        )
        return CLEANER_POST_INPUT

    item = {"type": post_type, "file_id": file_id, "html": result.html}
    channels = session["channels"]
    if session["autosend"] and len(channels) == 1:
        status = await message.reply_text(
            t("ss_cl_sending", lang, channel=html_escape(channels[0][1])), parse_mode="HTML")
        await publish(context, user_id, lang, item, channels[0], status)
        return CLEANER_POST_INPUT

    token = _remember(context, item)
    rows = [[_btn(t("ss_cl_btn_pub", lang, channel=title[:40]),
                  f"{CB_PUBLISH}:{token}:{index}")]
            for index, (_cid, title) in enumerate(channels[:_CHANNEL_BUTTONS_MAX])]
    await _send_preview(context.bot, message.chat_id, item,
                        InlineKeyboardMarkup(rows) if rows else None, lang)
    return CLEANER_POST_INPUT


async def _album_ready(context, user_id: int, lang: str, chat_id: int, entries: list) -> None:
    """Albom yig'ildi: izoh tozalanadi → BITTA post (kanalga yoki tugmalar bilan)."""
    session = context.user_data.get(_UD_SESSION)
    if not session or not entries:
        return  # tozalash rejimi bu orada to'xtatilgan
    bot = context.bot
    try:
        # Izoh butun albomga tegishli: birinchi bo'sh bo'lmagan izoh ishlatiladi.
        primary = next((e for e in entries if (e.get("caption") or "").strip()), None)
        text = primary["caption"] if primary else ""
        entities = primary["entities"] if primary else ()
        result = quick_clean(text, entities, session["signature"], session["own"])
        total = result.length + session["reserve"]
        if total > CAPTION_LIMIT:
            await bot.send_message(
                chat_id,
                t("ss_cl_too_long", lang, length=total, limit=CAPTION_LIMIT,
                  note=t("ss_cl_limit_caption", lang), over=total - CAPTION_LIMIT),
                parse_mode="HTML")
            return
        if len(entries) == 1:
            single = entries[0]
            item = {"type": single["type"], "file_id": single["file_id"], "html": result.html}
        else:
            files = [{"type": e["type"], "file_id": e["file_id"],
                      "caption": result.html if i == 0 else ""}
                     for i, e in enumerate(entries)]
            item = {"type": "album", "file_id": json.dumps(files, ensure_ascii=False),
                    "html": result.html}
        channels = session["channels"]
        if session["autosend"] and len(channels) == 1:
            status = await bot.send_message(
                chat_id, t("ss_cl_sending", lang, channel=html_escape(channels[0][1])),
                parse_mode="HTML")
            await publish(context, user_id, lang, item, channels[0], status)
            return
        token = _remember(context, item)
        rows = [[_btn(t("ss_cl_btn_pub", lang, channel=title[:40]),
                      f"{CB_PUBLISH}:{token}:{index}")]
                for index, (_cid, title) in enumerate(channels[:_CHANNEL_BUTTONS_MAX])]
        # Preview the same Free-tier header (post BOSHIDA) that the scheduler applies at
        # delivery time; keep the stored body independent of tier changes.
        preview_item = dict(item)
        if session["reserve"]:
            preview_item["html"] = watermark_header(BOT_USERNAME) + preview_item["html"]
        await _send_preview(bot, chat_id, preview_item,
                            InlineKeyboardMarkup(rows) if rows else None, lang)
    except Exception as exc:  # noqa: BLE001 — fon vazifa foydalanuvchiga xabar beradi
        log_silent_failure("handlers.post_cleaner_flow:_album_ready", exc, user_id=user_id)
        try:
            await bot.send_message(chat_id, t("ss_cl_album_fail", lang), parse_mode="HTML")
        except Exception as notify_exc:  # noqa: BLE001
            log_silent_failure("handlers.post_cleaner_flow:_album_ready:notify", notify_exc)


# ============================================================
# 4) KANALGA YUBORISH
# ============================================================
async def publish(context, user_id: int, lang: str, item: dict, channel: tuple,
                  status_message) -> bool:
    """Postni kanal navbatiga «hozir» yozadi va darhol yetkazishni boshlaydi.

    Yuborish umumiy rejalashtiruvchi orqali o'tadi (reklama siyosati,
    idempotentlik, statistika bir xil), lekin daqiqalik tick kutilmaydi.
    """
    from handlers.manual_post import manual_channel_guard
    from scheduler import now_tashkent

    channel_id, title = channel
    safe_title = html_escape(title)
    label = channel_label_html(channel_id, title)
    if not await manual_channel_guard(user_id, channel_id, "create"):
        await status_message.edit_text(t("ss_cl_no_access", lang), parse_mode="HTML")
        return False
    post_id = await db.run_db(
        db.add_post, user_id=user_id, channel_id=channel_id,
        post_type=item["type"], content=item["html"], file_id=item["file_id"],
        scheduled_time=now_tashkent(),
    )
    if not post_id:
        await status_message.edit_text(t("ss_cl_send_fail", lang, channel=safe_title),
                                       parse_mode="HTML")
        return False
    from utils.handler_timeout import run_background_task

    run_background_task(
        _deliver_and_report(context.bot, user_id, lang, post_id, safe_title, status_message,
                            label),
        name=f"cleaner:publish:{post_id}",
    )
    return True


async def _deliver_and_report(bot, user_id: int, lang: str, post_id: int,
                              safe_title: str, status_message, label: str = "") -> None:
    from scheduler import deliver_due_posts_now

    await deliver_due_posts_now(bot)
    status = ""
    for _ in range(_STATUS_POLLS):
        status = await db.run_db(db.get_post_status, post_id, user_id)
        if status not in ("pending", "processing"):
            break
        await asyncio.sleep(_STATUS_POLL_DELAY)
    if status == "posted":
        # Aniq nishon: «Nomi» (@username) kanaliga yuborildi.
        text = sent_notice(lang, [label or safe_title])
    elif status in ("pending", "processing"):
        return  # navbatda (masalan tungi soatlar) — rejalashtiruvchi yuboradi
    else:
        text = t("ss_cl_send_fail", lang, channel=safe_title)
    try:
        await status_message.edit_text(text, parse_mode="HTML")
    except Exception as exc:
        log_silent_failure("handlers.post_cleaner_flow:_deliver_and_report", exc)


async def publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``stgs_clean_pub:<token>:<kanal>`` — tayyor postni tanlangan kanalga."""
    query = update.callback_query
    user_id = query.from_user.id
    lang = await _lang(context, user_id)
    parts = str(query.data or "").split(":")
    item = (context.user_data.get(_UD_PENDING) or {}).get(parts[1] if len(parts) > 2 else "")
    session = context.user_data.get(_UD_SESSION) or await _load_session(user_id)
    try:
        channel = session["channels"][int(parts[2])]
    except (IndexError, ValueError):
        channel = None
    if not item or channel is None:
        await _answer(query, t("ss_cl_expired", lang), alert=True)
        return None
    await _answer(query)
    (context.user_data.get(_UD_PENDING) or {}).pop(parts[1], None)  # ikki marta yuborilmasin
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as exc:
        log_silent_failure("handlers.post_cleaner_flow:publish_callback", exc)
    status = await query.message.reply_text(
        t("ss_cl_sending", lang, channel=html_escape(channel[1])), parse_mode="HTML")
    await publish(context, user_id, lang, item, channel, status)
    return None
