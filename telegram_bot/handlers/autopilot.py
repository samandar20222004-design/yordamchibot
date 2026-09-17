"""🚀 AI AUTOPILOT — 7 kunlik to'liq post rejasini tuzish oqimi (PHASE C, 7-band).

Foydalanuvchi mavzu/yo'nalish kiritadi → AI kanalning Channel DNA uslubi va
Smart Best Time tavsiyalariga tayangan holda 7 kunlik (Dushanba–Yakshanba)
reja tuzadi → tasdiqlash oynasi::

    [🚀 Hammasini rejalashtirish]   — 7 ta post BITTA atomik tranzaksiyada
                                      ``scheduled_posts`` navbatiga qo'yiladi
    [✏️ Tahrirlash]                 — muayyan kun postini almashtirish
    [🔄 Qayta yaratish]             — butun reja qayta generatsiya qilinadi
    [❌ Bekor qilish]                — sessiya tozalanadi, hech narsa yozilmaydi

Xavfsizlik va limitlar:
  * IDOR: kirishda kanal egaligi tekshiriladi (``_owned_channel``) va
    servis qatlami (DNA/best-time) ham qayta tekshiradi (fail-closed);
  * FREE navbat limiti: ``check_week_quota`` — 7 ta postga joy yetmasa
    xavfsiz ogohlantirish (hech narsa yozilmaydi);
  * DUBLIKAT DETEKTORI: rejalashtirishdan OLDIN har bir kun posti kanalning
    oxirgi postlari bilan yengil (AI'siz) solishtiriladi — 85%+ o'xshashlik
    topilsa ``[🚀 Baribir chiqarish] | [✨ AI bilan yangilash] | [❌ Bekor
    qilish]`` oynasi chiqadi.

Kirish: 📢 Kanallarim → kanal → [🚀 AI Avtopilot] (``ch_ap:<channel_id>``).
FSM holatlari 480–483 — repodagi boshqa oqimlar bilan to'qnashmaydi
(470–472 kalendar, 450–454 oddiy post, 460–462 post score).
"""

from __future__ import annotations

import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from keyboards.callback_data import cb
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang
from services.autopilot import (
    AUTOPILOT_DAYS,
    check_week_quota,
    create_autopilot_plan,
    flag_duplicate_days,
    load_recent_channel_texts,
    rewrite_flagged_posts,
    schedule_autopilot_week,
)
from services.channels.best_time import WEEKDAY_NAMES
from services.channels.duplicate_detector import DUPLICATE_WARNING_MESSAGE
from translations import autopilot_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (480–483 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
AUTOPILOT_TOPIC = 480        # mavzu/yo'nalish matni kutilmoqda
AUTOPILOT_VIEW = 481         # tasdiqlash oynasi (reja + 4 amal)
AUTOPILOT_EDIT_DAY = 482     # tahrirlanadigan kun tanlanmoqda
AUTOPILOT_EDIT_INPUT = 483   # tanlangan kun uchun yangi matn kutilmoqda

# ============================================================
# CALLBACK DATA (barchasi 16 bayt byudjetida)
# ============================================================
CB_AP_CONFIRM = "ap_confirm"    # 🚀 Hammasini rejalashtirish
CB_AP_EDIT = "ap_edit"          # ✏️ Tahrirlash
CB_AP_EDAY = "ap_eday:"         # kun tanlash (ap_eday:<index>)
CB_AP_REGEN = "ap_regen"        # 🔄 Qayta yaratish
CB_AP_CANCEL = "ap_cancel"      # ❌ Bekor qilish
CB_AP_FORCE = "ap_force"        # 🚀 Baribir chiqarish (dublikatga qaramay)
CB_AP_REFRESH = "ap_refresh"    # ✨ AI bilan yangilash (dublikat postlar)

#: user_data kalitlari (bir joyda — tozalash va testlar uchun yagona manba).
UD_CHANNEL = "ap_channel_id"
UD_TITLE = "ap_channel_title"
UD_TOPIC = "ap_topic"
UD_DAYS = "ap_days"
UD_DUP_FLAGGED = "ap_dup_flagged"

#: Telegram xabar chegarasi hisobiga xavfsiz bo'lak hajmi.
CHUNK_LIMIT = 3600


def clear_autopilot_session(context) -> None:
    """Avtopilot sessiyasini toza yopadi (user_data qoldiqlari yo'q)."""
    for key in (UD_CHANNEL, UD_TITLE, UD_TOPIC, UD_DAYS, UD_DUP_FLAGGED,
                "ap_edit_day", "ap_dup_preview", "ap_dup_score"):
        context.user_data.pop(key, None)


def _lang(context) -> str:
    try:
        return get_lang(context)
    except Exception:  # pragma: no cover
        return "uz"


# ============================================================
# KLAVIATURALAR
# ============================================================
def autopilot_confirm_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Tasdiqlash oynasi (SPEKS: 4 amal)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(autopilot_t("btn_schedule_all", lang),
                              callback_data=CB_AP_CONFIRM)],
        [
            InlineKeyboardButton(autopilot_t("btn_edit", lang),
                                 callback_data=CB_AP_EDIT),
            InlineKeyboardButton(autopilot_t("btn_regen", lang),
                                 callback_data=CB_AP_REGEN),
        ],
        [InlineKeyboardButton(autopilot_t("btn_cancel", lang),
                              callback_data=CB_AP_CANCEL)],
    ])


def autopilot_duplicate_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Dublikat ogohlantirishi (SPEKS: 3 amal)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(autopilot_t("btn_dup_force", lang),
                              callback_data=CB_AP_FORCE)],
        [InlineKeyboardButton(autopilot_t("btn_dup_refresh", lang),
                              callback_data=CB_AP_REFRESH)],
        [InlineKeyboardButton(autopilot_t("btn_cancel", lang),
                              callback_data=CB_AP_CANCEL)],
    ])


def autopilot_edit_day_keyboard(days: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Tahrirlash uchun kun tanlash (7 tugma + Orqaga + Bekor qilish)."""
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    rows = []
    for day in days or []:
        index = int(day.get("index", 0))
        rows.append([InlineKeyboardButton(
            autopilot_t("edit_day_btn", lang, n=index + 1,
                        weekday=names[int(day.get("weekday", 0)) % 7]),
            callback_data=cb(CB_AP_EDAY, index),
        )])
    rows.append([
        InlineKeyboardButton(autopilot_t("edit_back", lang),
                             callback_data=CB_AP_CONFIRM),
    ])
    rows.append([InlineKeyboardButton(autopilot_t("btn_cancel", lang),
                                      callback_data=CB_AP_CANCEL)])
    return InlineKeyboardMarkup(rows)


def _quota_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Limit to'lganda: 💎 PRO taklifi + Bekor qilish."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(autopilot_t("quota_btn_pro", lang),
                              callback_data="sub_open")],
        [InlineKeyboardButton(autopilot_t("btn_cancel", lang),
                              callback_data=CB_AP_CANCEL)],
    ])


# ============================================================
# XAVFSIZ YUBORISH YORDAMCHILARI (handler hech qachon yiqilmaydi)
# ============================================================
async def _safe_edit(query, text: str, markup=None) -> bool:
    try:
        await query.edit_message_text(text, reply_markup=markup,
                                      parse_mode="HTML")
        return True
    except Exception:
        logger.debug("avtopilot: edit ishlamadi", exc_info=True)
    try:
        await query.message.reply_text(text, reply_markup=markup,
                                       parse_mode="HTML")
        return True
    except Exception:
        logger.debug("avtopilot: xabar yuborib bo'lmadi", exc_info=True)
        return False


async def _safe_send(msg, text: str, markup=None) -> bool:
    try:
        await msg.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        logger.debug("avtopilot: yuborish xatosi", exc_info=True)
        return False


# ============================================================
# REJANI RENDER QILISH (4096 chegarasi bilan bo'laklab)
# ============================================================
def render_plan_text(days: list, topic: str, channel_title: str,
                     hour_source: str, best_window: str | None,
                     hour: int, lang: str = "uz") -> list[str]:
    """Rejani HTML bo'laklarga aylantiradi (kun chegarasi buzilmaydi)."""
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    if hour_source == "best_time" and best_window:
        time_note = autopilot_t("time_note_best", lang, window=best_window)
    else:
        time_note = autopilot_t("time_note_default", lang,
                                hour=f"{int(hour) % 24:02d}")
    header = autopilot_t(
        "plan_header", lang,
        channel=html_escape(channel_title or "Kanal"),
        topic=html_escape(topic), time_note=time_note,
    )
    blocks = []
    for day in days or []:
        blocks.append(autopilot_t(
            "plan_day", lang,
            n=int(day.get("index", 0)) + 1,
            weekday=names[int(day.get("weekday", 0)) % 7],
            date=escape(str(day.get("date", ""))),
            time=escape(str(day.get("time", ""))),
            fmt=html_escape(str(day.get("format", "")) or "—"),
            post=html_escape(str(day.get("post_text", ""))),
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


def _day_lines(days: list, lang: str = "uz") -> str:
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    return "\n".join(
        autopilot_t("sched_day_line", lang,
                    weekday=names[int(d.get("weekday", 0)) % 7],
                    date=str(d.get("date", "")), time=str(d.get("time", "")))
        for d in days or []
    )


# ============================================================
# KIRISH — 📢 Kanallarim → kanal → [🚀 AI Avtopilot]
# ============================================================
async def channel_autopilot_entry(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Avtopilotni ochadi: kanal egaligi (IDOR) + mavzu so'rovi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    from handlers.channels import _owned_channel, _channel_title
    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        from keyboards.inline import render_channel_panel
        await _safe_edit(query, autopilot_t("no_channel", lang),
                         render_channel_panel(channel_id, lang))
        return ConversationHandler.END

    clear_autopilot_session(context)
    context.user_data[UD_CHANNEL] = str(channel_id)
    context.user_data[UD_TITLE] = (channel[1] or "Kanal") if len(channel) > 1 else "Kanal"
    title = _channel_title(channel)

    await _safe_edit(
        query,
        autopilot_t("intro", lang, channel=title),
        get_cancel_keyboard(lang),
    )
    return AUTOPILOT_TOPIC


# ============================================================
# AUTOPILOT_TOPIC — mavzu qabul qilinadi → AI reja
# ============================================================
async def autopilot_topic_received(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Mavzu/yo'nalish matni → 7 kunlik AI reja → tasdiqlash oynasi."""
    message = getattr(update, "message", None)
    if message is None:
        return AUTOPILOT_TOPIC
    lang = _lang(context)
    user_id = update.effective_user.id
    text = str(getattr(message, "text", "") or "").strip()

    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not channel_id or not context.user_data.get(UD_TITLE):
        await _safe_send(message, autopilot_t("stale", lang),
                         get_cancel_keyboard(lang))
        return ConversationHandler.END

    if not text or text.startswith("/") or len(text) < 3:
        await _safe_send(message, autopilot_t("topic_too_short", lang),
                         get_cancel_keyboard(lang))
        return AUTOPILOT_TOPIC

    context.user_data[UD_TOPIC] = text[:200]
    await _safe_send(message, autopilot_t("generating", lang))

    result = await create_autopilot_plan(user_id, channel_id, text, lang=lang)
    if not result.get("ok"):
        logger.warning("Avtopilot reja tuzilmadi (user=%s): %s", user_id,
                       result.get("error_code"))
        await _safe_send(message, autopilot_t("ai_failed", lang),
                         get_cancel_keyboard(lang))
        return AUTOPILOT_TOPIC

    days = result["days"]
    context.user_data[UD_DAYS] = days
    context.user_data[UD_DUP_FLAGGED] = []
    await _deliver_plan(message, context, days, result, lang)
    return AUTOPILOT_VIEW


async def _deliver_plan(target, context, days: list, result: dict,
                        lang: str = "uz") -> None:
    """Reja bo'laklarini + tasdiqlash oynasini yuboradi."""
    topic = str(context.user_data.get(UD_TOPIC) or "")
    title = str(context.user_data.get(UD_TITLE) or "Kanal")
    chunks = render_plan_text(
        days, topic, title, result.get("hour_source", "default"),
        result.get("best_window"), result.get("hour", 19), lang)
    if not await _safe_send(target, chunks[0]):
        return
    for extra in chunks[1:]:
        await _safe_send(target, extra)
    await _safe_send(target, autopilot_t("confirm_hint", lang),
                     autopilot_confirm_keyboard(lang))


def _stored_days(context) -> list:
    days = context.user_data.get(UD_DAYS) or []
    return [d for d in days if isinstance(d, dict) and d.get("post_text")]


# ============================================================
# AUTOPILOT_VIEW — tasdiqlash oynasi amallari
# ============================================================
async def autopilot_confirm_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """[🚀 Hammasini rejalashtirish] — limit → dublikat → atomik navbat."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    days = _stored_days(context)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not days or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    # 1) NAVBAT LIMITI (FREE qat'iy nazorat — hech narsa yozilmaydi).
    quota = await check_week_quota(user_id, needed=len(days))
    if not quota.get("allowed"):
        await _safe_edit(
            query,
            autopilot_t("quota_full", lang,
                        current=quota.get("current", 0),
                        max=quota.get("max", 0),
                        needed=quota.get("needed", AUTOPILOT_DAYS)),
            _quota_keyboard(lang),
        )
        return AUTOPILOT_VIEW

    # 2) DUBLIKAT DETEKTORI (rejalashtirishdan oldin, AI'siz).
    flagged = context.user_data.get(UD_DUP_FLAGGED) or []
    if not flagged:
        recent = await load_recent_channel_texts(channel_id, user_id)
        if recent:
            screen = flag_duplicate_days(days, recent)
            flagged = screen.get("flagged") or []
            context.user_data[UD_DUP_FLAGGED] = flagged
            context.user_data["ap_dup_preview"] = screen.get("best_preview", "")
            context.user_data["ap_dup_score"] = max(
                (screen.get("scores") or {}).values(), default=0.0)
    if flagged:
        await _show_duplicate_warning(query, context, days, flagged, lang)
        return AUTOPILOT_VIEW

    # 3) ATOMIK REJALASHTIRISH (hammasi yoki hech narsa).
    return await _schedule_and_finish(query, context, user_id, days, lang)


async def _show_duplicate_warning(query, context, days: list, flagged: list,
                                  lang: str) -> None:
    """⚠️ Speks bo'yicha qat'iy ogohlantirish + 3 tugma."""
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    flagged_days = ", ".join(
        f"{int(i) + 1}-kun ({names[int(days[i].get('weekday', 0)) % 7]})"
        for i in flagged if 0 <= int(i) < len(days)
    )
    try:
        best_score = float(context.user_data.get("ap_dup_score") or 0.0)
    except (TypeError, ValueError):
        best_score = 0.0
    text = DUPLICATE_WARNING_MESSAGE + autopilot_t(
        "dup_days", lang, days=flagged_days or "—",
        score=int(round(best_score * 100)))
    preview = str(context.user_data.get("ap_dup_preview") or "").strip()
    if preview:
        text += autopilot_t("dup_match", lang,
                            preview=html_escape(preview[:220]))
    await _safe_edit(query, text, autopilot_duplicate_keyboard(lang))


async def _schedule_and_finish(query, context, user_id: int, days: list,
                               lang: str) -> int:
    """7 postni bitta atomik tranzaksiyada navbatga qo'yadi + yakuniy ekran."""
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    result = await schedule_autopilot_week(user_id, channel_id, days)
    if not result.get("success"):
        logger.error("Avtopilot: navbatga qo'yilmadi (user=%s): %s",
                     user_id, result.get("error"))
        await _safe_edit(query, autopilot_t("sched_error", lang),
                         autopilot_confirm_keyboard(lang))
        return AUTOPILOT_VIEW

    count = int(result.get("count") or len(days))
    text = autopilot_t("sched_ok", lang, count=count,
                       lines=_day_lines(days, lang))
    clear_autopilot_session(context)
    await _safe_edit(query, text)
    return ConversationHandler.END


async def autopilot_force_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """[🚀 Baribir chiqarish] — dublikat ogohlantirishiga qaramay rejalashtiradi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    quota = await check_week_quota(user_id, needed=len(days))
    if not quota.get("allowed"):
        await _safe_edit(
            query,
            autopilot_t("quota_full", lang,
                        current=quota.get("current", 0),
                        max=quota.get("max", 0),
                        needed=quota.get("needed", AUTOPILOT_DAYS)),
            _quota_keyboard(lang),
        )
        return AUTOPILOT_VIEW

    context.user_data[UD_DUP_FLAGGED] = []
    return await _schedule_and_finish(query, context, user_id, days, lang)


async def autopilot_refresh_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE):
    """[✨ AI bilan yangilash] — dublikat postlarni AI qayta yozadi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    days = _stored_days(context)
    flagged = context.user_data.get(UD_DUP_FLAGGED) or []
    topic = str(context.user_data.get(UD_TOPIC) or "")
    if not days or not flagged:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    await _safe_edit(query, autopilot_t("dup_refreshing", lang))
    payload = [{"index": int(i), "content": days[int(i)].get("content", "")}
               for i in flagged if 0 <= int(i) < len(days)]
    rewritten = await rewrite_flagged_posts(topic, payload, lang=lang)
    if not rewritten:
        await _safe_edit(query, autopilot_t("dup_refresh_failed", lang),
                         autopilot_duplicate_keyboard(lang))
        return AUTOPILOT_VIEW

    for item in rewritten:
        index = int(item.get("index", -1))
        if 0 <= index < len(days):
            days[index]["content"] = item.get("content", "")
            from services.autopilot import compose_post_text
            days[index]["post_text"] = compose_post_text(
                item.get("content", ""), days[index].get("cta", ""))
    context.user_data[UD_DAYS] = days
    context.user_data[UD_DUP_FLAGGED] = []
    context.user_data.pop("ap_dup_preview", None)
    context.user_data.pop("ap_dup_score", None)

    title = str(context.user_data.get(UD_TITLE) or "Kanal")
    chunks = render_plan_text(days, topic, title, "default", None, 19, lang)
    await _safe_edit(query, autopilot_t("dup_refresh_done", lang))
    for chunk in chunks:
        await _safe_send(query.message, chunk)
    await _safe_send(query.message, autopilot_t("confirm_hint", lang),
                     autopilot_confirm_keyboard(lang))
    return AUTOPILOT_VIEW


async def autopilot_regen_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """[🔄 Qayta yaratish] — mavzuni saqlab, butun reja qayta tuziladi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    topic = str(context.user_data.get(UD_TOPIC) or "")
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not topic or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    await _safe_edit(query, autopilot_t("generating", lang))
    result = await create_autopilot_plan(user_id, channel_id, topic, lang=lang)
    if not result.get("ok"):
        await _safe_edit(query, autopilot_t("ai_failed", lang),
                         autopilot_confirm_keyboard(lang))
        return AUTOPILOT_VIEW

    days = result["days"]
    context.user_data[UD_DAYS] = days
    context.user_data[UD_DUP_FLAGGED] = []
    context.user_data.pop("ap_dup_preview", None)
    context.user_data.pop("ap_dup_score", None)
    title = str(context.user_data.get(UD_TITLE) or "Kanal")
    chunks = render_plan_text(days, topic, title,
                              result.get("hour_source", "default"),
                              result.get("best_window"),
                              result.get("hour", 19), lang)
    await _safe_edit(query, chunks[0])
    for extra in chunks[1:]:
        await _safe_send(query.message, extra)
    await _safe_send(query.message, autopilot_t("confirm_hint", lang),
                     autopilot_confirm_keyboard(lang))
    return AUTOPILOT_VIEW


# ============================================================
# ✏️ TAHRIRLASH — kun tanlash → yangi matn
# ============================================================
async def autopilot_edit_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """[✏️ Tahrirlash] — kun tanlash oynasi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END
    await _safe_edit(query, autopilot_t("edit_pick", lang),
                     autopilot_edit_day_keyboard(days, lang))
    return AUTOPILOT_EDIT_DAY


async def autopilot_edit_day_callback(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    """Kun tanlandi — yangi post matni so'raladi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_EDIT_DAY
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    data = str(getattr(query, "data", "") or "")
    try:
        index = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return AUTOPILOT_EDIT_DAY
    days = _stored_days(context)
    if not days or not (0 <= index < len(days)):
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    context.user_data["ap_edit_day"] = index
    await _safe_edit(
        query,
        autopilot_t("edit_prompt", lang, n=index + 1,
                    weekday=names[int(days[index].get("weekday", 0)) % 7]),
        get_cancel_keyboard(lang),
    )
    return AUTOPILOT_EDIT_INPUT


async def autopilot_edit_input_received(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE):
    """Yangi matn → kun posti almashtiriladi → tasdiqlash oynasiga qaytadi."""
    message = getattr(update, "message", None)
    if message is None:
        return AUTOPILOT_EDIT_INPUT
    lang = _lang(context)
    text = str(getattr(message, "text", "") or "").strip()
    days = _stored_days(context)
    index = context.user_data.get("ap_edit_day")
    if not days or index is None or not (0 <= int(index) < len(days)):
        await _safe_send(message, autopilot_t("stale", lang))
        return ConversationHandler.END
    if not text or text.startswith("/"):
        return AUTOPILOT_EDIT_INPUT

    from services.autopilot import compose_post_text
    day = days[int(index)]
    day["content"] = text[:3500]
    day["post_text"] = compose_post_text(day["content"], day.get("cta", ""))
    context.user_data[UD_DAYS] = days
    context.user_data.pop("ap_edit_day", None)
    context.user_data[UD_DUP_FLAGGED] = []  # tahrirdan keyin qayta tekshiramiz

    topic = str(context.user_data.get(UD_TOPIC) or "")
    title = str(context.user_data.get(UD_TITLE) or "Kanal")
    await _safe_send(message, autopilot_t("edit_done", lang, n=int(index) + 1))
    chunks = render_plan_text(days, topic, title, "default", None, 19, lang)
    for chunk in chunks:
        await _safe_send(message, chunk)
    await _safe_send(message, autopilot_t("confirm_hint", lang),
                     autopilot_confirm_keyboard(lang))
    return AUTOPILOT_VIEW


# ============================================================
# ❌ BEKOR QILISH + ESKIRGAN TUGMALAR
# ============================================================
async def autopilot_cancel_callback(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    """[❌ Bekor qilish] — sessiya tozalanadi, hech narsa yozilmaydi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    clear_autopilot_session(context)
    text = autopilot_t("cancel_done", lang)
    try:
        await query.edit_message_text(text, parse_mode="HTML")
    except Exception:
        if query.message is not None:
            await _safe_send(query.message, text)
    return ConversationHandler.END


async def autopilot_stale_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Eskirgan ``ap_`` tugmalari (sessiyadan tashqari) — toast, crash yo'q."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer(autopilot_t("stale", get_lang(context)))
    except Exception:
        pass
    return ConversationHandler.END


__all__ = [
    "AUTOPILOT_TOPIC", "AUTOPILOT_VIEW", "AUTOPILOT_EDIT_DAY",
    "AUTOPILOT_EDIT_INPUT",
    "CB_AP_CONFIRM", "CB_AP_EDIT", "CB_AP_EDAY", "CB_AP_REGEN",
    "CB_AP_CANCEL", "CB_AP_FORCE", "CB_AP_REFRESH",
    "channel_autopilot_entry", "autopilot_topic_received",
    "autopilot_confirm_callback", "autopilot_force_callback",
    "autopilot_refresh_callback", "autopilot_regen_callback",
    "autopilot_edit_callback", "autopilot_edit_day_callback",
    "autopilot_edit_input_received", "autopilot_cancel_callback",
    "autopilot_stale_callback", "clear_autopilot_session",
    "autopilot_confirm_keyboard", "autopilot_duplicate_keyboard",
    "autopilot_edit_day_keyboard", "render_plan_text",
]
