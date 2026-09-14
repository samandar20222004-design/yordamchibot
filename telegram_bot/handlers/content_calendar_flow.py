"""🗓 SMART CONTENT CALENDAR — 7/30 kunlik reja oqimi (PostAssist V2 · 2-qadam).

Bu modul sof mantiq moduli (:mod:`handlers.content_calendar` — entitlement,
normalallashtirish, xavfsiz render) ustiga **FSM qatlamini** qo'yadi va uni
«🤖 AI Yordamchi» submenyusiga ulaydi::

    [🤖 AI Yordamchi] → [🧠 Kontent reja]   (callback: ``studio_content_plan``)
        └─ CALENDAR_BUSINESS : soha (biznes) matni so'raladi
        └─ CALENDAR_DURATION : 7 yoki 30 kun tanlanadi (``cal_days:7|30``)
             • 30 kun + FREE        → ``pro_required`` (PRO taklifi)
             • FREE haftalik limit  → ``weekly_limit``
        └─ AI reja → xavfsiz render (``render_calendar``, HTML escape)
        └─ CALENDAR_VIEW : har bir kun uchun [✨ Post yaratish] (``cal_day:<i>``)
             └─ tanlangan kun mavzusi AYNAN «✨ Magic Post» oqimiga uzatiladi
                (``selected_topic_for_magic_post`` → ``MAGIC_STYLE_SELECT``)

Muhim shartlar (PostAssist V2 · 2-qadam auditi):
  * orqaga moslik: eski ``content_plan`` oqimi (BTN_CONTENT_PLAN, ``plan_*``
    callback'lari) O'CHIRILMAGAN — u alohida alias bo'lib qoladi;
  * yangi FSM holatlari 470–472 — repodagi boshqa oqimlar bilan
    to'qnashmaydi (test: ``tests/refactor_step2_test.py``);
  * AI javobi ishonchsiz: faqat lug'at shaklidagi yozuvlar o'tadi, kunlar
    soni bilan cheklanadi va matn HTML-escape qilinadi (``content_calendar``);
  * uzun reja (30 kun) bir nechta xabarga bo'lib yuboriladi — Telegram
    ``message is too long`` (4096) xatosi yuzaga kelmaydi;
  * hech qanday handler istisno tashlamaydi — foydalanuvchi doim javob oladi.
"""

from __future__ import annotations

import logging
import time
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from keyboards.callback_data import cb
from keyboards.default import get_cancel_keyboard
from keyboards.inline import get_cabinet_back_keyboard
from locales.translations import get_lang, safe_t
from translations.content_calendar import calendar_t
from handlers.content_calendar import (
    can_create_calendar,
    normalize_items,
    selected_topic_for_magic_post,
)

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (noyob: 470–472)
# ============================================================
CALENDAR_BUSINESS = 470   # soha/biznes matni kutilmoqda
CALENDAR_DURATION = 471   # 7 yoki 30 kun tanlanmoqda
CALENDAR_VIEW = 472       # tayyor reja + kun tanlash

# ============================================================
# CALLBACK DATA (barchasi 16 baytdan qisqa)
# ============================================================
CB_CAL_DAYS = "cal_days:"       # cal_days:7 | cal_days:30
CB_CAL_DAY = "cal_day:"         # cal_day:<index>
CB_CAL_CANCEL = "cal_cancel"    # ❌ Bekor qilish / Yopish

#: Telegram xabar chegarasi (4096) uchun xavfsiz bo'lak hajmi (HTML teglar
#: hisobga olingan holda). Reja shu hajmdagi bir nechta xabarga bo'linadi.
CHUNK_LIMIT = 3600

#: FREE tarifidagi haftalik limit oynasi (kun).
WEEKLY_WINDOW_DAYS = 7

#: Jarayondagi reja yaratishlar (user_id → [timestamp, ...]).
#: Bot bir jarayonda ishlaydi (APScheduler bilan bitta worker), shuning uchun
#: bu hisoblagich FREE haftalik limitini amalda ta'minlaydi. Xatolik yuz
#: bersa — limit qo'llanilmaydi (foydalanuvchi bloklanmaydi), entitlement'ning
#: o'zi esa HAR DOIM fail-closed (``can_create_calendar``).
_RECENT_PLANS: dict[int, list[float]] = {}


def _log(*args) -> None:
    """Debug yordamchisi (handlerlar hech qachon istisno tashlamasligi uchun)."""
    try:
        logger.debug(*args)
    except Exception:  # pragma: no cover
        pass


def clear_calendar_session(context) -> None:
    """Kalendar sessiyasi qoldiqlarini tozalaydi (yangi oqim — toza boshlanish)."""
    for key in ("calendar_business", "calendar_days", "calendar_items"):
        context.user_data.pop(key, None)


def recent_plan_count(user_id: int, now: float = None) -> int:
    """Oxirgi 7 kun ichida yaratilgan rejalar soni (xotira hisoblagichi)."""
    try:
        moment = float(now if now is not None else time.time())
        border = moment - WEEKLY_WINDOW_DAYS * 86400
        stamps = [t for t in _RECENT_PLANS.get(int(user_id), []) if t >= border]
        if stamps:
            _RECENT_PLANS[int(user_id)] = stamps
        else:
            _RECENT_PLANS.pop(int(user_id), None)
        return len(stamps)
    except Exception:  # pragma: no cover
        return 0


def remember_plan(user_id: int, now: float = None) -> None:
    """Muvaffaqiyatli reja yaratilganini qayd etadi (haftalik limit uchun)."""
    try:
        _RECENT_PLANS.setdefault(int(user_id), []).append(
            float(now if now is not None else time.time())
        )
    except Exception:  # pragma: no cover
        pass


def reset_plan_counters() -> None:
    """Hisoblagichni tozalash (test va diagnostika uchun)."""
    _RECENT_PLANS.clear()


# ============================================================
# KLAVIATURALAR
# ============================================================
def calendar_duration_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """7/30 kun tanlash + ❌ Bekor qilish + 💎 PRO (chegaralangan bo'lsa kerak)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(calendar_t("seven", lang), callback_data=CB_CAL_DAYS + "7")],
        [InlineKeyboardButton(calendar_t("thirty", lang), callback_data=CB_CAL_DAYS + "30")],
        [InlineKeyboardButton(safe_t("btn_cancel", lang), callback_data=CB_CAL_CANCEL)],
    ])


def calendar_plan_keyboard(items: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Har bir kun uchun [✨ Post yaratish] + [❌ Yopish].

    ``callback_data`` — ``cal_day:<index>`` (index rejadagi kun tartibi bilan
    bir xil: 0 → 1-kun). Yorliqda kun raqami va mavzu qisqartmasi ko'rinadi.
    """
    rows = []
    for index, item in enumerate(items or []):
        topic = selected_topic_for_magic_post(item) or ""
        preview = topic[:28] + ("…" if len(topic) > 28 else "")
        label = f"{index + 1}. {calendar_t('create', lang)}"
        if preview:
            label = f"{label} — {preview}"
        rows.append([InlineKeyboardButton(
            label[:60],
            callback_data=cb(CB_CAL_DAY, index),
        )])
    rows.append([InlineKeyboardButton(safe_t("pend_close_btn", lang), callback_data=CB_CAL_CANCEL)])
    return InlineKeyboardMarkup(rows)


def _entitlement_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """PRO taklifi + yopish (eski ``sub_open`` oqimiga yo'naltiradi)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_t("btn_premium", lang), callback_data="sub_open")],
        [InlineKeyboardButton(safe_t("pend_close_btn", lang), callback_data=CB_CAL_CANCEL)],
    ])


# ============================================================
# YORDAMCHILAR
# ============================================================
async def _safe_edit(query, text: str, markup=None) -> bool:
    """Xabarni edit qiladi; imkoni bo'lmasa yangi xabar yuboradi (crash yo'q)."""
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        _log("calendar: edit ishlamadi, yangi xabar yuboriladi", exc_info=True)
    try:
        await query.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        _log("calendar: xabar yuborib bo'lmadi", exc_info=True)
        return False


async def _safe_send(target, text: str, markup=None) -> bool:
    """Yangi xabar yuboradi (xato bo'lsa jim qaytadi — oqim davom etadi)."""
    try:
        await target.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        _log("calendar: xabar yuborilmadi", exc_info=True)
        return False


def _lang(context) -> str:
    """Handler ichidagi til (context keshidan — bot qayta ishga tushsa uz)."""
    try:
        return get_lang(context)
    except Exception:  # pragma: no cover
        return "uz"


def plan_chunks(items: list, business: str, lang: str = "uz") -> list:
    """Rejani ``CHUNK_LIMIT`` hajmdagi bo'laklarga ajratadi (kun chegarasida).

    Kun yozuvlari hech qachon bo'linmaydi va matn ``render_calendar`` bilan
    AYNAN bir xil qoidalarda (``normalize_items`` + HTML-escape) chiziladi —
    Telegram ``message is too long`` xatosi yuzaga kelmaydi. Sarlavha faqat
    birinchi bo'lakda takrorlanadi.
    """
    header = calendar_t("header", lang, business=escape(str(business)[:200]))
    blocks = []
    for number, item in enumerate(normalize_items(items, len(items) or 1), 1):
        blocks.append(calendar_t(
            "day", lang, n=number,
            rubric=escape(item["rubric"]), topic=escape(item["topic"]),
            tip=escape(item["tip"]),
        ))

    chunks, current = [], header
    for block in blocks:
        if current.strip() and len(current) + len(block) > CHUNK_LIMIT:
            chunks.append(current.rstrip())
            current = ""
        current += block
    if current.strip():
        chunks.append(current.rstrip())
    return chunks or [header]


async def check_calendar_entitlement(user_id: int, days: int, recent_count: int = 0):
    """Entitlement tekshiruvi (``can_create_calendar``) — FAIL-CLOSED.

    Database/xizmat xatosi bo'lsa PRO berilmaydi va foydalanuvchi xato o'rniga
    tushunarli PRO/limit xabarini oladi.
    """
    try:
        return await db.run_db(can_create_calendar, user_id, int(days), db, int(recent_count))
    except Exception:
        logger.warning("Kontent-kalendar entitlement xatosi", exc_info=True)
        return False, "pro_required"


async def generate_calendar_items(business: str, days: int, lang: str = "uz") -> list:
    """AI orqali ``days`` ta kunlik mavzu ro'yxatini oladi (xatoda — []).

    Test/mock uchun yagona patch nuqtasi: funksiya modul atributi sifatida
    chaqiriladi, shuning uchun testlar uni almashtirib tarmoqsiz ishlaydi.
    """
    try:
        from services.ai_service import run_ai_chain
        from utils.ai_agent import _extract_json
    except Exception:  # pragma: no cover - import xatosi (test muhiti)
        return []

    system = (
        "Siz tajribali SMM kontent-strategisiz. Faqat JSON qaytaring:\n"
        '{"days": [{"rubric": "...", "topic": "...", "tip": "..."}]}\n'
        f"Aynan {int(days)} ta yozuv bo'lsin, boshqa matn qo'shmang."
    )
    prompt = (
        f"Soha/biznes: {str(business)[:200]}\n"
        f"{int(days)} kunlik kontent-reja tuzing: har bir kun uchun "
        "rubrika (qisqa), mavzu (aniq post g'oyasi) va bitta amaliy tavsiya."
    )
    try:
        result = await run_ai_chain(prompt, system, lang)
    except Exception:
        logger.warning("Kontent-kalendar AI xatosi", exc_info=True)
        return []

    if not isinstance(result, dict) or result.get("error"):
        return []
    text = result.get("text") or result.get("content") or ""
    if not text:
        return []
    try:
        payload = _extract_json(text)
    except Exception:
        logger.warning("Kontent-kalendar javobini JSON qilib o'qib bo'lmadi")
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("days") or payload.get("plan") or payload.get("items") or []
    return normalize_items(items, days)


async def deliver_calendar(query, items: list, business: str, lang: str = "uz") -> None:
    """Rejani bo'lib-bo'lib yuboradi va kun tanlash klaviaturasini biriktiradi."""
    chunks = plan_chunks(items, business, lang)
    if not await _safe_edit(query, chunks[0], None):
        return
    for extra in chunks[1:]:
        await _safe_send(query.message, extra)
    if query.message is not None:
        await _safe_send(query.message, calendar_t("choose_day", lang),
                         calendar_plan_keyboard(items, lang))


# ============================================================
# ENTRY — 🤖 AI Yordamchi → [🧠 Kontent reja]
# ============================================================
async def content_calendar_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kalendar oqimini ochadi: soha (biznes) so'raladi.

    Kirish ham inline callback (AI Yordamchi tugmasi), ham oddiy xabar
    bo'lishi mumkin.
    """
    query = getattr(update, "callback_query", None)
    message = getattr(update, "message", None)
    lang = _lang(context)
    clear_calendar_session(context)

    text = calendar_t("ask_business", lang)
    keyboard = get_cancel_keyboard(lang)

    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
        await _safe_edit(query, text, keyboard)
        return CALENDAR_BUSINESS

    if message is None:
        return ConversationHandler.END
    await _safe_send(message, text, keyboard)
    return CALENDAR_BUSINESS


# ============================================================
# CALENDAR_BUSINESS — soha matni qabul qilinadi
# ============================================================
async def calendar_business_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Soha/biznes matni → davomiylik tanlash ekrani."""
    message = getattr(update, "message", None)
    if message is None:
        return CALENDAR_BUSINESS
    lang = _lang(context)
    text = str(getattr(message, "text", "") or "").strip()
    if not text or text.startswith("/") or len(text) < 2:
        await _safe_send(message, calendar_t("ask_business", lang), get_cancel_keyboard(lang))
        return CALENDAR_BUSINESS

    context.user_data["calendar_business"] = text[:200]
    await _safe_send(message, calendar_t("choose_duration", lang),
                     calendar_duration_keyboard(lang))
    return CALENDAR_DURATION


# ============================================================
# CALENDAR_DURATION — 7/30 kun tanlash + entitlement
# ============================================================
async def calendar_duration_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Davomiylik tanlandi → entitlement → AI reja → xavfsiz render."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return CALENDAR_DURATION
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    data = str(getattr(query, "data", "") or "")
    if data == CB_CAL_CANCEL:
        return await calendar_cancel_callback(update, context)

    try:
        days = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return CALENDAR_DURATION

    user_id = getattr(getattr(query, "from_user", None), "id", 0) or 0
    business = str(context.user_data.get("calendar_business") or "").strip()

    allowed, reason = await check_calendar_entitlement(user_id, days, recent_plan_count(user_id))
    if not allowed:
        text = calendar_t("pro", lang) if reason == "pro_required" else calendar_t("limit", lang)
        await _safe_edit(query, text, _entitlement_keyboard(lang))
        return CALENDAR_VIEW

    if not business:
        # Sessiya eskirgan (bot qayta ishga tushgan) — boshidan so'raymiz.
        await _safe_edit(query, calendar_t("ask_business", lang), get_cancel_keyboard(lang))
        return CALENDAR_BUSINESS

    await _safe_edit(query, calendar_t("generating", lang), None)

    items = await generate_calendar_items(business, days, lang)
    if not items:
        await _safe_edit(query, calendar_t("error", lang), get_cabinet_back_keyboard(lang))
        return CALENDAR_VIEW

    context.user_data["calendar_items"] = items
    context.user_data["calendar_days"] = days
    if days == 7:
        # Haftalik limit FAQAT 7 kunlik (FREE) rejalarga taalluqli.
        remember_plan(user_id)

    await deliver_calendar(query, items, business, lang)
    return CALENDAR_VIEW


# ============================================================
# CALENDAR_VIEW — kun tanlash → ✨ Magic Post
# ============================================================
async def calendar_day_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tanlangan kun mavzusi AYNAN «✨ Magic Post» oqimiga uzatiladi.

    Yangi generatsiya oqimi yaratilmaydi: mavzu ``magic_raw_text`` ga yoziladi
    va mavjud uslub tanlash ekrani ochiladi (``MAGIC_STYLE_SELECT``).
    """
    query = getattr(update, "callback_query", None)
    if query is None:
        return CALENDAR_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    data = str(getattr(query, "data", "") or "")
    if data == CB_CAL_CANCEL:
        return await calendar_cancel_callback(update, context)

    items = context.user_data.get("calendar_items") or []
    try:
        index = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return CALENDAR_VIEW

    if index < 0 or index >= len(items):
        # Eskirgan tugma — crash emas, qisqa yo'riqnoma.
        await _safe_edit(query, calendar_t("error", lang), None)
        return CALENDAR_VIEW

    topic = selected_topic_for_magic_post(items[index])
    if not topic:
        await _safe_edit(query, calendar_t("error", lang), None)
        return CALENDAR_VIEW

    try:
        from handlers.magic_post import (
            MAGIC_STYLE_SELECT,
            _magic_style_keyboard,
            _magic_style_menu_text,
            _safe_edit as magic_safe_edit,
        )
    except Exception:  # pragma: no cover - import himoyasi
        logger.exception("Magic Post moduli yuklanmadi")
        await _safe_edit(query, calendar_t("error", lang), None)
        return CALENDAR_VIEW

    context.user_data["magic_raw_text"] = topic
    await magic_safe_edit(query, _magic_style_menu_text(topic, lang), _magic_style_keyboard(lang))
    return MAGIC_STYLE_SELECT


async def calendar_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """❌ Bekor qilish / Yopish — sessiya tozalanadi, oqim yopiladi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    clear_calendar_session(context)
    text = safe_t("cancel_done", lang)
    try:
        await query.edit_message_text(text, reply_markup=None, parse_mode="HTML")
    except Exception:
        if query.message is not None:
            await _safe_send(query.message, text)
    return ConversationHandler.END


async def calendar_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Eskirgan ``cal_`` tugmalari (sessiyadan tashqari) — toast, crash yo'q."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer(safe_t("sys_stale_button", get_lang(context)))
    except Exception:
        pass
    return ConversationHandler.END


# Integratsiya/alias nomlar (routing va testlar uchun).
calendar_entry = content_calendar_entry
calendar_days_callback = calendar_duration_callback

__all__ = [
    "CALENDAR_BUSINESS", "CALENDAR_DURATION", "CALENDAR_VIEW",
    "CB_CAL_DAYS", "CB_CAL_DAY", "CB_CAL_CANCEL", "CHUNK_LIMIT",
    "content_calendar_entry", "calendar_entry", "calendar_business_received",
    "calendar_duration_callback", "calendar_days_callback", "calendar_day_callback",
    "calendar_cancel_callback", "calendar_stale_callback",
    "calendar_duration_keyboard", "calendar_plan_keyboard", "plan_chunks",
    "clear_calendar_session", "recent_plan_count", "remember_plan",
    "reset_plan_counters", "check_calendar_entitlement", "generate_calendar_items",
    "deliver_calendar",
]
