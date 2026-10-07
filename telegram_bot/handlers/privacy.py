# -*- coding: utf-8 -*-
"""🔐 MAXFIYLIK SIYOSATI + «MA'LUMOTLARIMNI O'CHIRISH» — handlerlar.

SPRINT 1 (Privacy & GDPR) talabi:

  1. ``/privacy`` buyrug'i va Sozlamalar hub'idagi «🔐 Maxfiylik siyosati»
     tugmasi — bot qanday ma'lumotlarni saqlashini (kanal ID, post matnlari,
     AI telemetriyasi, to'lov yozuvlari) uchala tilda OCHIQ ko'rsatadi;
  2. «🗑 Ma'lumotlarimni o'chirish» — AVVAL tasdiq so'raladi (bir bosishda
     o'chirib bo'lmaydi), so'ng foydalanuvchi hisobi, uchinchi tomon AI
     tarixi va bog'langan kanallar kaskadli/soft-delete qilinadi. To'lov
     tranzaksiyalari qonuniy audit uchun SAQLANADI.

Xavfsizlik qoidalari
--------------------
  * O'chirish faqat TASDIQLANGAN tugma orqali (``stgs_privacy_del_ok``);
    callback'ni qo'lda yuborish (tampering) baribir foydalanuvchining
    O'Z hisobini o'chiradi — boshqa odamning ma'lumotiga tegmaydi
    (user_id faqat ``update.effective_user`` dan olinadi);
  * DB xatosida xato YUTILMAYDI — ``logger.error`` + Sentry va foydalanuvchiga
    xavfsiz xabar (``pv_delete_error``); o'chirilgan bo'lsa — yarim holat
    haqida aniq xabar;
  * matnlar HTML rejimida yuboriladi, qiymatlar ``html_escape`` bilan
    tozalanadi (yangi qatorlar ``\\n`` — foydalanuvchi kiritmasi emas).
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import database as db
from config import ADMIN_IDS_SET, SUPPORT_USERNAME
from keyboards.default import get_main_keyboard
from locales.translations import get_text, normalize_lang
from translations import privacy_t
from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)


def _support_handle() -> str:
    """Qo'llab-quvvatlash manzili (bo'sh bo'lsa — umumiy matn)."""
    try:
        username = str(SUPPORT_USERNAME or "").strip().lstrip("@")
    except Exception:
        username = ""
    return f"@{username}" if username else "—"


def build_policy_text(lang: str = "uz") -> str:
    """Maxfiylik siyosati matni (barcha bo'limlar, bitta HTML xabar).

    ``/privacy`` ham, Sozlamalar hub'i ham AYNAN shu funksiyadan foydalanadi —
    matn ikki joyda ajralib ketmaydi (single source of truth).
    """
    code = normalize_lang(lang)
    parts = [
        privacy_t("pv_title", code),
        privacy_t("pv_intro", code),
        privacy_t("pv_data_title", code),
        privacy_t("pv_data_account", code),
        privacy_t("pv_data_channels", code),
        privacy_t("pv_data_posts", code),
        privacy_t("pv_data_ai", code),
        privacy_t("pv_data_payments", code),
        privacy_t("pv_not_title", code),
        privacy_t("pv_not_body", code),
        privacy_t("pv_use_title", code),
        privacy_t("pv_use_body", code),
        privacy_t("pv_rights_title", code),
        privacy_t("pv_rights_body", code).format(support=_support_handle()),
        privacy_t("pv_retention_title", code),
        privacy_t("pv_retention_body", code),
        privacy_t("pv_delete_hint", code),
    ]
    return "\n\n".join(part for part in parts if part)


def get_privacy_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Siyosat ekrani klaviaturasi: [🗑 O'chirish] + [◀️ Orqaga]."""
    code = normalize_lang(lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(privacy_t("pv_btn_delete", code),
                              callback_data="stgs_privacy_del")],
        [InlineKeyboardButton(get_text("btn_back", code), callback_data="stgs_hub")],
    ])


def get_delete_confirm_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Tasdiqlash klaviaturasi: xavfli amal — ikki bosqichli himoya."""
    code = normalize_lang(lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(privacy_t("pv_btn_confirm_delete", code),
                              callback_data="stgs_privacy_del_ok")],
        [InlineKeyboardButton(privacy_t("pv_btn_cancel_delete", code),
                              callback_data="stgs_privacy_cancel")],
    ])


def build_delete_confirm_text(lang: str = "uz") -> str:
    """Tasdiqlash ekrani: nima o'chiriladi / nima saqlanadi."""
    code = normalize_lang(lang)
    return "\n\n".join([
        privacy_t("pv_delete_title", code),
        privacy_t("pv_delete_intro", code),
        privacy_t("pv_delete_items", code),
        privacy_t("pv_delete_kept", code),
        privacy_t("pv_delete_ask", code),
    ])


async def _edit_or_send(query, text: str, keyboard, lang: str) -> None:
    """Xabarni tahrirlaydi, imkonsiz bo'lsa yangisini yuboradi.

    ``edit_message_text`` Telegram tomonidan rad etilishi mumkin (eski xabar,
    o'zgarmagan matn) — bunday holat jimgina yutilmaydi, DEBUG log yoziladi.
    """
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        return
    except Exception as edit_exc:  # noqa: BLE001 — fallback: yangi xabar
        log_silent_failure(
            "handlers.privacy:_edit_or_send", edit_exc, expected=True,
            user_id=getattr(getattr(query, "from_user", None), "id", None),
        )
    try:
        await query.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as send_exc:  # noqa: BLE001 — foydalanuvchi xabari yetmadi
        log_silent_failure(
            "handlers.privacy:_edit_or_send:reply", send_exc,
            user_id=getattr(getattr(query, "from_user", None), "id", None),
        )


async def privacy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``/privacy`` — maxfiylik siyosatini ochadi (istalgan tildan)."""
    user = update.effective_user
    if user is None:  # kanal postlari va boshqa usersiz update'lar
        return
    from handlers.start import ensure_user_lang

    lang = await ensure_user_lang(context, user.id)
    text = build_policy_text(lang)
    keyboard = get_privacy_keyboard(lang)
    if update.message is not None:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        # Buyruq callback orqali kelgan (masalan, qayta yo'naltirish).
        query = update.callback_query
        if query is not None:
            await _edit_or_send(query, text, keyboard, lang)


async def _render_policy(query, context, user_id: int, lang: str) -> None:
    """Sozlamalar hub'idan ochilgan siyosat ekrani."""
    await _edit_or_send(query, build_policy_text(lang), get_privacy_keyboard(lang), lang)


async def _render_delete_confirm(query, context, user_id: int, lang: str) -> None:
    """«Ma'lumotlarimni o'chirish» — tasdiq ekrani (hali O'CHIRILMAYDI)."""
    await _edit_or_send(
        query, build_delete_confirm_text(lang), get_delete_confirm_keyboard(lang), lang,
    )


async def _send_fresh(update, context, user_id: int, lang: str, text: str,
                      reply_markup=None) -> None:
    """Yangi xabar yuboradi (profil/menyu klaviaturasi bilan).

    Parametr nomi ``reply_markup`` — chaqiruvchilar shu kalit so'z bilan
    uzatadi (kalit nomi mos kelmasa ``TypeError`` bo'lardi va
    foydalanuvchi hisobni o'chirgach JAVOB OLMASDAN qolardi).
    """
    query = update.callback_query
    try:
        if query is not None and query.message is not None:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        elif update.effective_message is not None:
            await update.effective_message.reply_text(
                text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as send_exc:  # noqa: BLE001
        log_silent_failure("handlers.privacy:_send_fresh", send_exc, user_id=user_id)


async def privacy_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«✅ Ha, hammasini o'chirish» — kaskadli o'chirishni BAJARADI.

    Qaytaradi: DB funksiyasi natijasi (testlar uchun ham foydali).
    """
    query = update.callback_query
    user = update.effective_user
    if user is None:
        return None
    from handlers.start import ensure_user_lang

    user_id = user.id
    lang = await ensure_user_lang(context, user_id)
    try:
        await query.answer()
    except Exception as answer_exc:  # noqa: BLE001 — toast yuborilmasa ham davom
        log_silent_failure("handlers.privacy:answer", answer_exc, user_id=user_id)

    try:
        result = await db.run_db(db.delete_user_data, user_id)
    except Exception as db_exc:  # noqa: BLE001 — foydalanuvchiga xavfsiz xabar
        log_silent_failure("handlers.privacy:delete_user_data", db_exc,
                           user_id=user_id)
        await _send_fresh(
            update, context, user_id, lang,
            privacy_t("pv_delete_error", lang).format(support=_support_handle()),
            reply_markup=None,
        )
        return None

    if not result or not result.get("ok"):
        reason = (result or {}).get("reason", "unknown")
        logger.error(
            "Ma'lumot o'chirish bajarilmadi: user=%s reason=%s", user_id, reason)
        await _send_fresh(
            update, context, user_id, lang,
            privacy_t("pv_delete_error", lang).format(support=_support_handle()),
            reply_markup=None,
        )
        return result

    # FSM va keshni tozalaymiz — foydalanuvchi toza holatdan boshlaydi.
    # ``clear_fsm_data`` — locales/translations.py dagi umumiy helper
    # (handlers/__init__.py va boshqa handlerlar ham shundan oladi).
    try:
        from locales.translations import clear_fsm_data

        clear_fsm_data(context)
    except Exception as fsm_exc:  # noqa: BLE001
        log_silent_failure("handlers.privacy:clear_fsm_data", fsm_exc, user_id=user_id)

    text = privacy_t("pv_delete_done", lang).format(
        channels=int(result.get("channels") or 0),
        posts=int(result.get("posts") or 0),
        ai_events=int(result.get("ai_events") or 0),
    )
    try:
        is_admin = user_id in ADMIN_IDS_SET
    except Exception:
        is_admin = False
    keyboard = get_main_keyboard(is_admin, lang=lang)
    await _send_fresh(update, context, user_id, lang, text, reply_markup=keyboard)
    return result


async def privacy_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«❌ Bekor qilish» — o'chirish to'xtatiladi (ma'lumot tegilmaydi)."""
    query = update.callback_query
    user = update.effective_user
    if user is None:
        return
    from handlers.start import ensure_user_lang

    lang = await ensure_user_lang(context, user.id)
    try:
        await query.answer()
    except Exception as answer_exc:  # noqa: BLE001
        log_silent_failure("handlers.privacy:cancel_answer", answer_exc,
                           user_id=user.id)
    await _edit_or_send(
        query, privacy_t("pv_delete_cancelled", lang),
        get_privacy_keyboard(lang), lang,
    )


__all__ = [
    "build_delete_confirm_text",
    "build_policy_text",
    "get_delete_confirm_keyboard",
    "get_privacy_keyboard",
    "privacy_cancel",
    "privacy_command",
    "privacy_delete_confirm",
]
