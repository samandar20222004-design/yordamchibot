"""🕒 Vaqt mintaqasi: har yangilanishda foydalanuvchi zonasini o'rnatish va /timezone tanlovi.

Rejalash, ro'yxat va hisobotlar foydalanuvchining O'Z vaqtida. Zona: qo'lda tanlangan -> telefon mamlakati -> Toshkent.
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, SimpleUpdateProcessor

import database as db
from handlers.start import ensure_user_lang
from keyboards.callback_data import cb
from locales.translations import get_text
from services import user_timezone as tzs
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

CB_TZ = "tz:"


async def load_user_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Har yangilanish boshida joriy zonani ``ContextVar``ga qo'yadi (keshda bo'lsa DB'ga bormaydi). Hech narsani to'xtatmaydi."""
    user = getattr(update, "effective_user", None)
    if user is None:
        return
    try:
        name = tzs.cached_name(user.id) or await db.run_db(tzs.tz_name_for, user.id)
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.timezone_flow:load_user_timezone", _silent_exc, user_id=user.id)
        name = tzs.DEFAULT_TZ_NAME
    tzs.set_current(tzs.get_tz(name))


def tz_hint(user, lang: str) -> str:
    """Vaqt belgilanganda qo'shiladigan eslatma: foydalanuvchi zonasi hali tanlanmagan (standart Toshkent) va Telegram tili
    o'zbekcha emas bo'lsa — qaysi zonada hisoblanayotgani va ``/timezone`` ko'rsatiladi (chet eldagi foydalanuvchi vaqti
    jimgina Toshkent bo'yicha hisoblanib, post kutilmagan paytda chiqmasin). Boshqa hollarda bo'sh matn."""
    try:
        zone = tzs.utz()
        if getattr(zone, "zone", None) != tzs.DEFAULT_TZ_NAME:
            return ""
        if str(getattr(user, "language_code", "") or "").lower().startswith("uz"):
            return ""
        return "\n\n" + get_text("tz_note", lang, zone=tzs.DEFAULT_TZ_NAME, offset=tzs.offset_label(zone))
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.timezone_flow:tz_hint", _silent_exc)
        return ""


def _allowed_zones(country: str | None) -> set[str]:
    return set(tzs.country_zones(country)) | {tzs.offset_zone(h) for h in tzs.OFFSET_CHOICES}


def _main_view(lang: str, country: str | None, current: str):
    zone = tzs.get_tz(current)
    text = get_text("tz_title", lang, zone=current, offset=tzs.offset_label(zone))
    rows: list[list[InlineKeyboardButton]] = []
    zones = tzs.country_zones(country)[:12]
    row: list[InlineKeyboardButton] = []
    for name in zones:
        mark = "✅ " if name == current else ""
        row.append(InlineKeyboardButton(f"{mark}{tzs.city(name)}"[:30], callback_data=cb(CB_TZ, "s", name)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(get_text("tz_btn_offset", lang), callback_data=cb(CB_TZ, "off")),
                 InlineKeyboardButton(get_text("tz_btn_auto", lang), callback_data=cb(CB_TZ, "auto"))])
    return text, InlineKeyboardMarkup(rows)


def _offset_view(lang: str, current: str):
    rows, row = [], []
    for h in tzs.OFFSET_CHOICES:
        label = "UTC" + (f"{h:+d}" if h else "")
        mark = "✅ " if tzs.offset_zone(h) == current else ""
        row.append(InlineKeyboardButton(mark + label, callback_data=cb(CB_TZ, "s", tzs.offset_zone(h))))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(get_text("tz_btn_back", lang), callback_data=cb(CB_TZ, "menu"))])
    return get_text("tz_offset_title", lang), InlineKeyboardMarkup(rows)


async def timezone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = await ensure_user_lang(context, user.id)
    name, country = await db.run_db(db.get_timezone_row, user.id)
    current = tzs.resolve(name, country)
    text, markup = _main_view(lang, country, current)
    await update.effective_message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def timezone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = await ensure_user_lang(context, user.id)
    parts = (query.data or "").split(":", 2)
    action = parts[1] if len(parts) > 1 else "menu"
    name, country = await db.run_db(db.get_timezone_row, user.id)
    current = tzs.resolve(name, country)
    await query.answer()
    if action == "off":
        text, markup = _offset_view(lang, current)
    else:
        if action == "s" and len(parts) > 2 and parts[2] in _allowed_zones(country):
            if await db.run_db(db.set_user_timezone, user.id, parts[2]):
                current = parts[2]
        elif action == "auto":
            await db.run_db(db.set_user_timezone, user.id, None)
            current = tzs.resolve(None, country)
        tzs.set_current(tzs.get_tz(current))
        text, markup = _main_view(lang, country, current)
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as _silent_exc:  # noqa: BLE001 — «message is not modified»
        log_silent_failure("handlers.timezone_flow:timezone_callback", _silent_exc, user_id=user.id)


class TimezoneUpdateProcessor(SimpleUpdateProcessor):
    """Har yangilanish handlerlardan OLDIN foydalanuvchi zonasini ``ContextVar``ga qo'yadi (handler guruhlari ro'yxatiga tegmaydi).

    ``ApplicationBuilder().concurrent_updates(TimezoneUpdateProcessor(256))`` — ``True`` bilan bir xil parallellik.
    """

    __slots__ = ()

    async def do_process_update(self, update, coroutine) -> None:
        if isinstance(update, Update):
            await load_user_timezone(update, None)
        await coroutine
