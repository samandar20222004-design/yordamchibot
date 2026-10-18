"""📱 Telefon raqamini O'Z kontakti orqali tasdiqlash (Telegram «kontakt ulashish» tugmasi).

Bot ishga tushganda/kirganda raqam SO'RALMAYDI. Faqat «ko'proq ish» qilmoqchi bo'lganda: tarif sotib olish, so'mda to'lash,
reklama birjasiga e'lon qo'yish. Maqsad: mamlakat (statistika, birja filtri, narx mintaqasi) — raqamning o'zi saqlanmaydi,
faqat ISO-2 mamlakat kodi. Kontakt faqat so'ralgan bo'lsa (10 daqiqa ichida) va o'zinikiga tegishli bo'lsa qabul qilinadi.
"""
from __future__ import annotations

import logging
import time

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

import database as db
from config import ADMIN_IDS_SET, PLAN_PRO, PLAN_ULTRA
from handlers.start import ensure_user_lang
from keyboards.default import get_main_keyboard
from locales.translations import get_text
from services.country import UNKNOWN, flag
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

PHONE_VERIFY_TTL_SECONDS = 600
PENDING_KEY = "phone_verify"

#: Nima uchun so'raladi (matn tanlash uchun): tarif sotib olish / so'mda to'lash / birja e'loni.
PURPOSE_BUY, PURPOSE_UZ, PURPOSE_MARKET = "buy", "uz", "market"
_PROMPT_KEYS = {PURPOSE_BUY: "phone_verify_prompt_buy", PURPOSE_UZ: "uz_verify_prompt", PURPOSE_MARKET: "phone_verify_prompt_market"}


async def is_phone_verified(user_id: int) -> bool:
    """Telefon (mamlakat) tasdiqlanganmi? DB xatosida ``False`` (xavfsiz tomon)."""
    try:
        profile = await db.run_db(db.get_pay_profile, user_id)
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.phone_verify:is_phone_verified", _silent_exc, user_id=user_id)
        return False
    return bool((profile or {}).get("phone_verified"))


async def ask_phone_verification(message, context, lang: str, *, purpose: str = PURPOSE_BUY, tier: str | None = None) -> None:
    """«Kontakt ulashish» tugmasi bilan telefonni tasdiqlashni so'raydi va kutish holatini (10 daqiqa) yozadi."""
    ud = getattr(context, "user_data", None)
    if ud is not None:
        ud[PENDING_KEY] = {"purpose": purpose, "tier": tier if tier in (PLAN_PRO, PLAN_ULTRA) else None, "ts": time.time()}
    markup = ReplyKeyboardMarkup(
        [[KeyboardButton(get_text("btn_share_phone", lang), request_contact=True)]],
        resize_keyboard=True, one_time_keyboard=True,
    )
    try:
        await message.reply_text(get_text(_PROMPT_KEYS.get(purpose, _PROMPT_KEYS[PURPOSE_BUY]), lang), reply_markup=markup,
                                 parse_mode="HTML")
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.phone_verify:ask_phone_verification", _silent_exc)


async def phone_contact_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kontakt keldi: faqat telefon so'ralgan bo'lsa (10 daqiqa) va kontakt o'ziniki bo'lsa qabul qilinadi; qolgan kontaktlarga tegilmaydi."""
    message = getattr(update, "message", None)
    contact = getattr(message, "contact", None)
    ud = getattr(context, "user_data", None)
    pending = (ud or {}).get(PENDING_KEY)
    if contact is None or not isinstance(pending, dict):
        return
    ud.pop(PENDING_KEY, None)
    if time.time() - float(pending.get("ts") or 0) > PHONE_VERIFY_TTL_SECONDS:
        return
    user_id = update.effective_user.id
    lang = await ensure_user_lang(context, user_id)
    try:
        country = await db.run_db(db.verify_phone, user_id, getattr(contact, "phone_number", ""), getattr(contact, "user_id", None))
    except Exception as _silent_exc:  # noqa: BLE001
        log_silent_failure("handlers.phone_verify:phone_contact_callback", _silent_exc, user_id=user_id)
        country = None
    keyboard = get_main_keyboard(user_id in ADMIN_IDS_SET, lang=lang)
    if not country:
        await message.reply_text(get_text("phone_verify_fail", lang), reply_markup=keyboard, parse_mode="HTML")
        raise ApplicationHandlerStop
    purpose = pending.get("purpose")
    if country == "UZ":
        await message.reply_text(get_text("uz_verify_ok", lang), reply_markup=keyboard, parse_mode="HTML")
    else:
        text = get_text("phone_verify_ok", lang, flag=flag(country), country="" if country == UNKNOWN else country)
        if purpose == PURPOSE_UZ:
            text += "\n\n" + get_text("uz_only_note", lang)
        await message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    if purpose == PURPOSE_MARKET:
        await message.reply_text(get_text("market_after_verify", lang), parse_mode="HTML")
    elif pending.get("tier"):
        from handlers.subscription import _build_tier_card, _get_tier_keyboard, _user_region

        tier = pending["tier"]
        region = await _user_region(user_id)
        await message.reply_text(_build_tier_card(tier, lang, region), reply_markup=_get_tier_keyboard(tier, lang, region), parse_mode="HTML")
    raise ApplicationHandlerStop  # kontakt qayta ishlandi: «noma'lum xabar» javobi chiqmasin
