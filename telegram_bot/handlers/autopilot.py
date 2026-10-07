"""🚀 AI AUTOPILOT V2 — 7 kunlik strategik post rejasini tuzish oqimi (PHASE C + PHASE 8).

Foydalanuvchi mavzu/yo'nalish va strategiya parametrlarini (`goal`,
`frequency`, `approval_mode`, `quiet_hours`) kiritadi → AI kanalning
Channel DNA uslubi, ContentLoop bo'shliqlari (Gaps) va Smart Best Time
tavsiyalariga tayangan holda 7 kunlik (Dushanba–Yakshanba) balanslangan
reja tuzadi → tasdiqlash oynasi::

    [🚀 Hammasini rejalashtirish]   — postlar BITTA atomik tranzaksiyada
                                      ``scheduled_posts`` navbatiga qo'yiladi
    [✏️ Tahrirlash]                 — muayyan postni ko'rish, tasdiqlash
                                      (Approve), tahrirlash (Edit), AI bilan
                                      qayta yaratish (Regenerate) yoki
                                      o'chirish (Delete)
    [🔄 Qayta yaratish]             — butun reja qayta generatsiya qilinadi
    [❌ Bekor qilish]                — sessiya tozalanadi, hech narsa yozilmaydi

Tasdiqlash rejimlari (Approval Modes):
  * ``MANUAL``: barcha postlar oldindan ko'rsatiladi va tasdiqlangach
    jadvalga qo'yiladi;
  * ``SEMI_AUTO``: ``quality_score >= 0.8`` bo'lgan postlar avtomatik
    jadvalga olinadi, shubhali postlar tasdiqqa yuboriladi;
  * ``AUTO``: barcha postlar to'g'ridan-to'g'ri jadvalga joylashtiriladi
    (faqat PRO foydalanuvchilar uchun).

Xavfsizlik va limitlar:
  * IDOR: kirishda kanal egaligi tekshiriladi (``_owned_channel``) va
    servis qatlami (DNA/best-time/ContentLoop) ham qayta tekshiradi (fail-closed);
  * FREE navbat limiti: ``check_week_quota`` — postlarga joy yetmasa
    xavfsiz ogohlantirish (hech narsa yozilmaydi);
  * DUBLIKAT DETEKTORI: rejalashtirishdan OLDIN har bir post 7 kunlik reja
    ichida VA kanalning oxirgi 30 kunlik postlari bilan solishtiriladi —
    85%+ o'xshashlik topilsa ``[🚀 Baribir chiqarish] | [✨ AI bilan yangilash]
    | [❌ Bekor qilish]`` oynasi chiqadi.

Kirish: 📢 Kanallarim → kanal → [🚀 AI Avtopilot] (``ch_ap:<channel_id>``).
FSM holatlari 480–483 — repodagi boshqa oqimlar bilan to'qnashmaydi
(470–472 kalendar, 450–454 oddiy post, 460–462 post score).
"""

from __future__ import annotations

import inspect
import logging
from html import escape
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from keyboards.callback_data import CB_CHANNEL_AUTOPILOT, cb
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang
from services.autopilot import (
    APPROVAL_AUTO,
    APPROVAL_MANUAL,
    APPROVAL_SEMI_AUTO,
    AUTOPILOT_DAYS,
    DEFAULT_APPROVAL_MODE,
    DEFAULT_FREQUENCY,
    DEFAULT_GOAL,
    DEFAULT_QUIET_HOURS,
    GOAL_LABELS,
    SEMI_AUTO_QUALITY_THRESHOLD,
    apply_approval_mode_schedule,
    approve_single_plan_post,
    check_user_is_pro,
    check_week_quota,
    compose_post_text,
    create_autopilot_plan,
    delete_plan_post,
    edit_plan_post,
    flag_duplicate_days,
    format_quiet_hours,
    load_recent_channel_texts,
    normalize_approval_mode,
    normalize_frequency,
    normalize_goal,
    parse_quiet_hours,
    regenerate_single_plan_post,
    rewrite_flagged_posts,
    schedule_autopilot_week,
    validate_approval_mode_access,
    view_plan_post,
)
from services.channels.best_time import WEEKDAY_NAMES
from services.channels.duplicate_detector import DUPLICATE_WARNING_MESSAGE
# 🔐 PHASE 3 — markaziy RBAC: avtopilot kanal ustida amal bajaradi.
from services import rbac_service
from translations import autopilot_t
from utils.helpers import html_escape

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (480–483 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
AUTOPILOT_TOPIC = 480        # mavzu/yo'nalish matni + strategiya sozlamasi
AUTOPILOT_VIEW = 481         # tasdiqlash oynasi (reja + 4 amal)
AUTOPILOT_EDIT_DAY = 482     # tahrirlanadigan/boshqariladigan post tanlanmoqda
AUTOPILOT_EDIT_INPUT = 483   # tanlangan post uchun yangi matn yoki amal kutilmoqda

# ============================================================
# CALLBACK DATA (barchasi 16 bayt byudjetida)
# ============================================================
CB_AP_CONFIRM = "ap_confirm"    # 🚀 Hammasini rejalashtirish
CB_AP_EDIT = "ap_edit"          # ✏️ Tahrirlash / postlarni boshqarish
CB_AP_EDAY = "ap_eday:"         # kun/post tanlash (ap_eday:<index>)
CB_AP_REGEN = "ap_regen"        # 🔄 Qayta yaratish
CB_AP_CANCEL = "ap_cancel"      # ❌ Bekor qilish
CB_AP_FORCE = "ap_force"        # 🚀 Baribir chiqarish (dublikatga qaramay)
CB_AP_REFRESH = "ap_refresh"    # ✨ AI bilan yangilash (dublikat postlar)

# PHASE 8 — Autopilot V2 callback prefikslari:
CB_AP_GOAL = "ap_goal:"         # strategik maqsad tanlash (ap_goal:growth|sales|...)
CB_AP_FREQ = "ap_freq:"         # kunlik chastota (ap_freq:1|2|3)
CB_AP_MODE = "ap_mode:"         # tasdiqlash rejimi (ap_mode:MANUAL|SEMI_AUTO|AUTO)
CB_AP_QUIET = "ap_quiet:"       # tinchlik soati (ap_quiet:on|off|23:00-08:00)
CB_AP_PVIEW = "ap_pview:"       # postni ko'rish (ap_pview:<index>)
CB_AP_PAPP = "ap_papp:"         # postni tasdiqlash — Approve (ap_papp:<index>)
CB_AP_PEDIT = "ap_pedit:"       # postni tahrirlash — Edit (ap_pedit:<index>)
CB_AP_PREGEN = "ap_pregen:"     # postni qayta yaratish — Regenerate (ap_pregen:<index>)
CB_AP_PDEL = "ap_pdel:"         # postni o'chirish — Delete (ap_pdel:<index>)

#: user_data kalitlari (bir joyda — tozalash va testlar uchun yagona manba).
UD_CHANNEL = "ap_channel_id"
UD_TITLE = "ap_channel_title"
UD_TOPIC = "ap_topic"
UD_DAYS = "ap_days"
UD_DUP_FLAGGED = "ap_dup_flagged"
UD_CONFIG = "ap_config"

#: Qo'shimcha nomlar (moslik uchun).
UD_CHANNEL_ID = UD_CHANNEL
UD_CHANNEL_TITLE = UD_TITLE

#: Telegram xabar chegarasi hisobiga xavfsiz bo'lak hajmi.
CHUNK_LIMIT = 3600


def clear_autopilot_session(context) -> None:
    """Avtopilot sessiyasini toza yopadi (user_data qoldiqlari yo'q)."""
    for key in (
        UD_CHANNEL, UD_TITLE, UD_TOPIC, UD_DAYS, UD_DUP_FLAGGED, UD_CONFIG,
        "ap_edit_day", "ap_dup_preview", "ap_dup_score",
    ):
        context.user_data.pop(key, None)


def _lang(context) -> str:
    try:
        return get_lang(context)
    except Exception:  # pragma: no cover
        return "uz"


def _get_or_init_config(context, channel_id: str = "") -> dict:
    """``context.user_data[UD_CONFIG]`` ichidan strategiya konfiguratsiyasini oladi."""
    ud = getattr(context, "user_data", None)
    if not isinstance(ud, dict):
        return {
            "channel_id": str(channel_id or ""),
            "goal": DEFAULT_GOAL,
            "frequency": DEFAULT_FREQUENCY,
            "approval_mode": DEFAULT_APPROVAL_MODE,
            "quiet_hours": DEFAULT_QUIET_HOURS,
        }
    cfg = ud.get(UD_CONFIG)
    if not isinstance(cfg, dict):
        cfg = {
            "channel_id": str(channel_id or ud.get(UD_CHANNEL) or ""),
            "goal": DEFAULT_GOAL,
            "frequency": DEFAULT_FREQUENCY,
            "approval_mode": DEFAULT_APPROVAL_MODE,
            "quiet_hours": DEFAULT_QUIET_HOURS,
        }
        ud[UD_CONFIG] = cfg
    else:
        if channel_id:
            cfg["channel_id"] = str(channel_id)
        cfg["goal"] = normalize_goal(cfg.get("goal"))
        cfg["frequency"] = normalize_frequency(cfg.get("frequency"))
        cfg["approval_mode"] = normalize_approval_mode(cfg.get("approval_mode"))
        if "quiet_hours" not in cfg:
            cfg["quiet_hours"] = DEFAULT_QUIET_HOURS
    return cfg


def _goal_label(goal: str, lang: str = "uz") -> str:
    canon = normalize_goal(goal)
    return (GOAL_LABELS.get(lang) or GOAL_LABELS["uz"]).get(canon, canon)


def _quiet_label(quiet_hours: Any, lang: str = "uz") -> str:
    parsed = parse_quiet_hours(quiet_hours)
    if not parsed:
        return {"uz": "O'chiq", "ru": "Выкл", "en": "Off"}.get(lang, "Off")
    return format_quiet_hours(parsed)


# ============================================================
# KLAVIATURALAR
# ============================================================
def autopilot_strategy_keyboard(
    config: dict | None = None,
    lang: str = "uz",
) -> InlineKeyboardMarkup:
    """Autopilot V2 strategiya tanlash + bekor qilish inline klaviaturasi."""
    cfg = config if isinstance(config, dict) else {}
    goal = normalize_goal(cfg.get("goal"))
    freq = normalize_frequency(cfg.get("frequency"))
    mode = normalize_approval_mode(cfg.get("approval_mode"))
    qh_on = parse_quiet_hours(cfg.get("quiet_hours", DEFAULT_QUIET_HOURS)) is not None

    next_goal = {
        "growth": "sales",
        "sales": "engagement",
        "engagement": "expertise",
        "expertise": "growth",
    }.get(goal, "sales")
    goal_btn_key = {
        "growth": "btn_goal_growth",
        "sales": "btn_goal_sales",
        "engagement": "btn_goal_engagement",
        "expertise": "btn_goal_expertise",
    }.get(goal, "btn_goal_growth")

    next_freq = 1 if freq >= 3 else freq + 1
    freq_label = {
        "uz": f"📊 {freq}x/kun",
        "ru": f"📊 {freq}x/день",
        "en": f"📊 {freq}x/day",
    }.get(lang, f"📊 {freq}x/kun")

    next_mode = {
        APPROVAL_MANUAL: APPROVAL_SEMI_AUTO,
        APPROVAL_SEMI_AUTO: APPROVAL_AUTO,
        APPROVAL_AUTO: APPROVAL_MANUAL,
    }.get(mode, APPROVAL_SEMI_AUTO)
    mode_btn_key = {
        APPROVAL_MANUAL: "btn_mode_manual",
        APPROVAL_SEMI_AUTO: "btn_mode_semi",
        APPROVAL_AUTO: "btn_mode_auto",
    }.get(mode, "btn_mode_manual")

    quiet_btn = (
        autopilot_t("btn_quiet_on", lang)
        if qh_on
        else autopilot_t("btn_quiet_off", lang)
    )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                autopilot_t(goal_btn_key, lang),
                callback_data=cb(CB_AP_GOAL, next_goal),
            ),
            InlineKeyboardButton(
                freq_label,
                callback_data=cb(CB_AP_FREQ, next_freq),
            ),
        ],
        [
            InlineKeyboardButton(
                autopilot_t(mode_btn_key, lang),
                callback_data=cb(CB_AP_MODE, next_mode),
            ),
            InlineKeyboardButton(
                quiet_btn,
                callback_data=cb(CB_AP_QUIET, "off" if qh_on else "on"),
            ),
        ],
        [
            InlineKeyboardButton(
                autopilot_t("btn_cancel", lang),
                callback_data=CB_AP_CANCEL,
            ),
        ],
    ])


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
    """Tahrirlash / boshqarish uchun post tanlash (postlar + Orqaga + Bekor qilish)."""
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    rows = []
    for day in days or []:
        if not isinstance(day, dict) or day.get("approval_status") == "deleted":
            continue
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


def autopilot_post_action_keyboard(index: int, lang: str = "uz") -> InlineKeyboardMarkup:
    """Bitta post uchun V2 amallar: Approve / Edit / Regenerate / Delete / Back / Cancel."""
    idx = int(index)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                autopilot_t("btn_post_approve", lang),
                callback_data=cb(CB_AP_PAPP, idx),
            ),
            InlineKeyboardButton(
                autopilot_t("btn_post_edit", lang),
                callback_data=cb(CB_AP_PEDIT, idx),
            ),
        ],
        [
            InlineKeyboardButton(
                autopilot_t("btn_post_regen", lang),
                callback_data=cb(CB_AP_PREGEN, idx),
            ),
            InlineKeyboardButton(
                autopilot_t("btn_post_delete", lang),
                callback_data=cb(CB_AP_PDEL, idx),
            ),
        ],
        [
            InlineKeyboardButton(
                autopilot_t("edit_back", lang),
                callback_data="ap_back",
            ),
            InlineKeyboardButton(
                autopilot_t("btn_cancel", lang),
                callback_data=CB_AP_CANCEL,
            ),
        ],
    ])


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
        if not isinstance(day, dict) or day.get("approval_status") == "deleted":
            continue
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


def render_post_detail_text(day: dict, lang: str = "uz") -> str:
    """Bitta post kartochkasini batafsil ko'rsatadi (PURE)."""
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    idx = int(day.get("index", 0))
    weekday = names[int(day.get("weekday", 0)) % 7]
    score_pct = int(round(float(day.get("quality_score") or 0.85) * 100))
    status = str(day.get("approval_status") or "pending_approval")
    if day.get("already_scheduled") or status in ("approved", "scheduled"):
        status_label = autopilot_t("v2_status_approved", lang)
    elif status == "auto_scheduled":
        status_label = autopilot_t("v2_status_auto", lang)
    elif status == "needs_review":
        status_label = autopilot_t("v2_status_review", lang)
    else:
        status_label = autopilot_t("v2_status_pending", lang)

    quiet_note = (
        autopilot_t("v2_quiet_shifted", lang)
        if day.get("rescheduled_from_quiet_hours")
        else ""
    )
    return autopilot_t(
        "v2_post_card",
        lang,
        n=idx + 1,
        weekday=html_escape(weekday),
        date=escape(str(day.get("date", ""))),
        time=escape(str(day.get("time", ""))),
        topic=html_escape(str(day.get("topic") or "—")),
        fmt=html_escape(str(day.get("format") or "post")),
        score=score_pct,
        status=html_escape(status_label),
        quiet_note=quiet_note,
        post=html_escape(str(day.get("post_text") or "")[:2000]),
    )


def _render_intro_with_strategy(channel_title: str, config: dict, lang: str) -> str:
    base = autopilot_t("intro", lang, channel=channel_title)
    strat = autopilot_t(
        "v2_strategy_box",
        lang,
        goal=html_escape(_goal_label(config.get("goal", DEFAULT_GOAL), lang)),
        frequency=normalize_frequency(config.get("frequency", DEFAULT_FREQUENCY)),
        mode=html_escape(normalize_approval_mode(config.get("approval_mode", DEFAULT_APPROVAL_MODE))),
        quiet=html_escape(_quiet_label(config.get("quiet_hours", DEFAULT_QUIET_HOURS), lang)),
    )
    return base + strat


def _day_lines(days: list, lang: str = "uz") -> str:
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    return "\n".join(
        autopilot_t("sched_day_line", lang,
                    weekday=names[int(d.get("weekday", 0)) % 7],
                    date=str(d.get("date", "")), time=str(d.get("time", "")))
        for d in days or []
        if isinstance(d, dict) and d.get("approval_status") != "deleted"
    )


async def _invoke_create_plan(
    user_id: int,
    channel_id: str | int,
    topic: str,
    *,
    lang: str,
    config: dict | None = None,
) -> dict:
    """``create_autopilot_plan`` ni imzosiga mos chaqiradi (monkeypatch-safe)."""
    cfg = config if isinstance(config, dict) else {}
    fn = create_autopilot_plan
    try:
        sig = inspect.signature(fn)
        params = sig.parameters
        supports_v2 = "goal" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except Exception:
        supports_v2 = False

    if supports_v2:
        res = await fn(
            user_id,
            channel_id,
            topic,
            lang=lang,
            goal=cfg.get("goal", DEFAULT_GOAL),
            frequency=cfg.get("frequency", DEFAULT_FREQUENCY),
            approval_mode=cfg.get("approval_mode", DEFAULT_APPROVAL_MODE),
            quiet_hours=cfg.get("quiet_hours", DEFAULT_QUIET_HOURS),
        )
    else:
        res = await fn(user_id, channel_id, topic, lang=lang)

    if isinstance(res, dict) and res.get("ok"):
        res.setdefault("goal", normalize_goal(cfg.get("goal", DEFAULT_GOAL)))
        res.setdefault("frequency", normalize_frequency(cfg.get("frequency", DEFAULT_FREQUENCY)))
        res.setdefault("approval_mode", normalize_approval_mode(cfg.get("approval_mode", DEFAULT_APPROVAL_MODE)))
        res.setdefault("quiet_hours", cfg.get("quiet_hours", DEFAULT_QUIET_HOURS))
    return res


# ============================================================
# KIRISH — 📢 Kanallarim → kanal → [🚀 AI Avtopilot]
# ============================================================
async def channel_autopilot_entry(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Avtopilotni ochadi: kanal egaligi (IDOR) + strategiya + mavzu so'rovi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:channel_autopilot_entry", _silent_exc)
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    from handlers.channels import _owned_channel, _channel_title
    # 🔐 PHASE 3 — IDOR: avtopilot faqat kanal ustida ``create`` huquqi
    # bo'lgan foydalanuvchi uchun ochiladi (owner/editor; scheduler/analyst
    # va begona foydalanuvchi — rad).
    if not await autopilot_channel_guard(user_id, channel_id, "create"):
        from keyboards.inline import render_channel_panel
        await _safe_edit(query, autopilot_t("no_permission", lang),
                         render_channel_panel(channel_id, lang))
        return ConversationHandler.END
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
    cfg = _get_or_init_config(context, channel_id=str(channel_id))

    await _safe_edit(
        query,
        _render_intro_with_strategy(title, cfg, lang),
        autopilot_strategy_keyboard(cfg, lang),
    )
    return AUTOPILOT_TOPIC


# ============================================================
# PHASE 8 — STRATEGIYA SOZLAMALARI CALLBACK (goal / freq / mode / quiet)
# ============================================================
async def autopilot_strategy_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """Strategik parametrlarni (goal, frequency, approval_mode, quiet_hours) yangilaydi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_TOPIC
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not channel_id:
        try:
            await query.answer(autopilot_t("stale", lang), show_alert=True)
        except Exception as _silent_exc:
            log_silent_failure("handlers.autopilot:autopilot_strategy_callback:616", _silent_exc)
        return ConversationHandler.END

    cfg = _get_or_init_config(context, channel_id=channel_id)
    data = str(getattr(query, "data", "") or "")
    prefix, _, val = data.partition(":")

    if prefix == "ap_goal":
        cfg["goal"] = normalize_goal(val)
    elif prefix == "ap_freq":
        cfg["frequency"] = normalize_frequency(val)
    elif prefix == "ap_mode":
        target_mode = normalize_approval_mode(val)
        if target_mode == APPROVAL_AUTO:
            is_pro = await check_user_is_pro(user_id)
            access = validate_approval_mode_access(target_mode, is_pro=is_pro)
            if not access["allowed"]:
                try:
                    await query.answer(
                        autopilot_t("v2_auto_pro_only", lang)[:190],
                        show_alert=True,
                    )
                except Exception as _silent_exc:
                    log_silent_failure("handlers.autopilot:autopilot_strategy_callback:639", _silent_exc)
                await _safe_edit(
                    query,
                    autopilot_t("v2_auto_pro_only", lang),
                    _quota_keyboard(lang),
                )
                return AUTOPILOT_TOPIC
        cfg["approval_mode"] = target_mode
    elif prefix == "ap_quiet":
        if str(val).lower() in ("off", "none", "0", "false"):
            cfg["quiet_hours"] = None
        elif str(val).lower() in ("on", "default", "1", "true"):
            cfg["quiet_hours"] = DEFAULT_QUIET_HOURS
        else:
            parsed = parse_quiet_hours(val)
            cfg["quiet_hours"] = format_quiet_hours(parsed) if parsed else DEFAULT_QUIET_HOURS

    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_strategy_callback:659", _silent_exc, user_id=user_id, channel_id=channel_id, lang=lang)

    title = str(context.user_data.get(UD_TITLE) or "Kanal")
    await _safe_edit(
        query,
        _render_intro_with_strategy(title, cfg, lang),
        autopilot_strategy_keyboard(cfg, lang),
    )
    return AUTOPILOT_TOPIC


# ============================================================
# PHASE 3 — RBAC/IDOR YORDAMCHISI
# ============================================================
async def autopilot_channel_guard(user_id: int, channel_id, action: str) -> bool:
    """Foydalanuvchi AYNAN shu kanalda amal bajara oladimi (markaziy RBAC)?

    Fail-closed: RBAC/DB xatosi — ruxsat BERILMAYDI. ``channel_id``
    server-side ``user_data`` dan (yoki tekshirilgan callback payload'idan)
    olinadi; payload'dagi ID'ga hech qachon ishonilmaydi.
    """
    try:
        return await rbac_service.can(
            user_id, resource_type="channel", resource_id=channel_id,
            action=action,
        )
    except Exception:  # pragma: no cover — fail-closed
        logger.exception("RBAC tekshiruvi xatosi (user=%s, action=%s)",
                         user_id, action)
        return False


# ============================================================
# AUTOPILOT_TOPIC — mavzu qabul qilinadi → AI reja (+ Approval Mode)
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

    cfg = _get_or_init_config(context, channel_id=channel_id)
    mode = normalize_approval_mode(cfg.get("approval_mode", DEFAULT_APPROVAL_MODE))

    # AUTO rejimi faqat PRO foydalanuvchilar uchun
    if mode == APPROVAL_AUTO:
        is_pro = await check_user_is_pro(user_id)
        if not is_pro:
            await _safe_send(
                message,
                autopilot_t("v2_auto_pro_only", lang),
                _quota_keyboard(lang),
            )
            return AUTOPILOT_TOPIC

    context.user_data[UD_TOPIC] = text[:200]
    await _safe_send(message, autopilot_t("generating", lang))

    result = await _invoke_create_plan(
        user_id, channel_id, text, lang=lang, config=cfg
    )
    if not result.get("ok"):
        logger.warning("Avtopilot reja tuzilmadi (user=%s): %s", user_id,
                       result.get("error_code"))
        if result.get("error_code") == "PRO_REQUIRED":
            await _safe_send(
                message,
                autopilot_t("v2_auto_pro_only", lang),
                _quota_keyboard(lang),
            )
            return AUTOPILOT_TOPIC
        await _safe_send(message, autopilot_t("ai_failed", lang),
                         get_cancel_keyboard(lang))
        return AUTOPILOT_TOPIC

    days = result["days"]
    context.user_data[UD_DAYS] = days
    context.user_data[UD_DUP_FLAGGED] = []

    # Approval Modes ijrosi:
    # - AUTO (PRO): barcha toza postlar to'g'ridan-to'g'ri jadvalga qo'yiladi
    # - SEMI_AUTO: quality_score >= 0.8 postlar avtomatik jadvalga qo'yiladi,
    #              shubhali postlar tasdiq uchun qoldiriladi
    # - MANUAL: barcha postlar tasdiq uchun ko'rsatiladi
    effective_mode = normalize_approval_mode(result.get("approval_mode", mode))
    dup_flagged = (result.get("duplicate_report") or {}).get("flagged") or []

    if effective_mode == APPROVAL_AUTO:
        exec_res = await apply_approval_mode_schedule(
            user_id,
            channel_id,
            days,
            approval_mode=APPROVAL_AUTO,
            is_pro=True,
            duplicate_indices=dup_flagged,
        )
        if exec_res.get("ok") and exec_res.get("pending_approval_count", 0) == 0:
            count = int(exec_res.get("scheduled_count") or len(days))
            done_text = autopilot_t(
                "sched_ok", lang, count=count, lines=_day_lines(days, lang)
            )
            clear_autopilot_session(context)
            await _safe_send(message, done_text)
            return ConversationHandler.END
    elif effective_mode == APPROVAL_SEMI_AUTO:
        exec_res = await apply_approval_mode_schedule(
            user_id,
            channel_id,
            days,
            approval_mode=APPROVAL_SEMI_AUTO,
            is_pro=True,
            semi_auto_threshold=SEMI_AUTO_QUALITY_THRESHOLD,
            duplicate_indices=dup_flagged,
        )
        if exec_res.get("ok"):
            await _safe_send(
                message,
                autopilot_t(
                    "v2_semi_summary",
                    lang,
                    auto_count=exec_res.get("scheduled_count", 0),
                    review_count=exec_res.get("pending_approval_count", 0),
                ),
            )

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
    return [
        d for d in days
        if isinstance(d, dict) and d.get("post_text") and d.get("approval_status") != "deleted"
    ]


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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_confirm_callback", _silent_exc)
    lang = _lang(context)
    user_id = query.from_user.id
    days = _stored_days(context)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not days or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    unscheduled_days = [d for d in days if not d.get("already_scheduled")]
    needed_count = len(unscheduled_days) if unscheduled_days else len(days)

    # 1) NAVBAT LIMITI (FREE qat'iy nazorat — hech narsa yozilmaydi).
    quota = await check_week_quota(user_id, needed=needed_count)
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

    # 2) DUBLIKAT DETEKTORI (rejalashtirishdan oldin, AI'siz: 30 kunlik tarix + 7 kunlik reja ichida).
    flagged = context.user_data.get(UD_DUP_FLAGGED) or []
    if not flagged:
        recent = await load_recent_channel_texts(channel_id, user_id)
        screen = flag_duplicate_days(days, recent or [])
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
    """Postlarni bitta atomik tranzaksiyada navbatga qo'yadi + yakuniy ekran."""
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    # 🔐 PHASE 3 — IDOR: yozishdan OLDIN kanal ustida ``schedule`` huquqi
    # qayta tekshiriladi (kanal ``user_data`` da bo'lsa ham — sessiya
    # eskirgan yoki a'zolik olib tashlangan bo'lishi mumkin).
    if not await autopilot_channel_guard(user_id, channel_id, "schedule"):
        logger.warning(
            "RBAC/IDOR: avtopilot rejalashtirish rad etildi (user=%s, channel=%s)",
            user_id, channel_id[:64],
        )
        await _safe_edit(query, autopilot_t("no_permission", lang),
                         get_cancel_keyboard(lang))
        clear_autopilot_session(context)
        return ConversationHandler.END
    pending_days = [d for d in days if not d.get("already_scheduled")]
    target_days = pending_days if pending_days else days
    result = await schedule_autopilot_week(user_id, channel_id, target_days)
    if not result.get("success"):
        logger.error("Avtopilot: navbatga qo'yilmadi (user=%s): %s",
                     user_id, result.get("error"))
        await _safe_edit(query, autopilot_t("sched_error", lang),
                         autopilot_confirm_keyboard(lang))
        return AUTOPILOT_VIEW

    count = int(result.get("count") or len(target_days))
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_force_callback", _silent_exc)
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_refresh_callback", _silent_exc)
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
            if item.get("topic"):
                days[index]["topic"] = item["topic"]
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_regen_callback", _silent_exc)
    lang = _lang(context)
    user_id = query.from_user.id
    topic = str(context.user_data.get(UD_TOPIC) or "")
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not topic or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    await _safe_edit(query, autopilot_t("generating", lang))
    cfg = _get_or_init_config(context, channel_id=channel_id)
    result = await _invoke_create_plan(
        user_id, channel_id, topic, lang=lang, config=cfg
    )
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
# ✏️ TAHRIRLASH VA POST BOSHQARUVI (View / Approve / Edit / Regenerate / Delete)
# ============================================================
async def autopilot_edit_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """[✏️ Tahrirlash] — post tanlash oynasi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_edit_callback", _silent_exc)
    lang = _lang(context)
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END
    await _safe_edit(query, autopilot_t("edit_pick", lang),
                     autopilot_edit_day_keyboard(days, lang))
    return AUTOPILOT_EDIT_DAY


async def autopilot_back_to_plan_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[◀️ Orqaga — rejaga] (`ap_back`) — tasdiqlash oynasiga qaytaradi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_back_to_plan_callback", _silent_exc)
    lang = _lang(context)
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    context.user_data.pop("ap_edit_day", None)
    await _safe_edit(
        query,
        autopilot_t("confirm_hint", lang),
        autopilot_confirm_keyboard(lang),
    )
    return AUTOPILOT_VIEW


async def autopilot_edit_day_callback(update: Update,
                                      context: ContextTypes.DEFAULT_TYPE):
    """Kun/post tanlandi — post ma'lumotlari + V2 boshqaruv tugmalari va matn so'rovi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_EDIT_DAY
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_edit_day_callback", _silent_exc)
    lang = _lang(context)
    data = str(getattr(query, "data", "") or "")
    arg = data.split(":", 1)[1] if ":" in data else ""
    if arg == "back":
        return await autopilot_back_to_plan_callback(update, context)
    try:
        index = int(arg)
    except (IndexError, ValueError):
        return AUTOPILOT_EDIT_DAY
    days = _stored_days(context)
    day = view_plan_post(days, index)
    if not days or day is None:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    actual_idx = int(day.get("index", index))
    context.user_data["ap_edit_day"] = actual_idx
    card = render_post_detail_text(day, lang)
    prompt = autopilot_t(
        "edit_prompt", lang, n=actual_idx + 1,
        weekday=names[int(day.get("weekday", 0)) % 7],
    )
    await _safe_edit(
        query,
        f"{card}\n\n{prompt}",
        autopilot_post_action_keyboard(actual_idx, lang),
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
    if not days or index is None or view_plan_post(days, int(index)) is None:
        await _safe_send(message, autopilot_t("stale", lang))
        return ConversationHandler.END
    if not text or text.startswith("/"):
        return AUTOPILOT_EDIT_INPUT

    cfg = _get_or_init_config(context)
    edit_plan_post(
        days,
        int(index),
        text[:3500],
        goal=cfg.get("goal", DEFAULT_GOAL),
    )
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
# PHASE 8 — POST DARAJASIDAGI CALLBACKLAR (View / Approve / Edit / Regen / Delete)
# ============================================================
async def autopilot_post_view_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[👁 View] (`ap_pview:<idx>`) — tanlangan postni ko'rsatadi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_post_view_callback", _silent_exc)
    lang = _lang(context)
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    data = str(getattr(query, "data", "") or "")
    try:
        idx = int(data.split(":", 1)[1]) if ":" in data else int(context.user_data.get("ap_edit_day", 0))
    except (TypeError, ValueError):
        return AUTOPILOT_EDIT_DAY

    day = view_plan_post(days, idx)
    if day is None:
        return AUTOPILOT_EDIT_DAY

    actual_idx = int(day.get("index", idx))
    context.user_data["ap_edit_day"] = actual_idx
    await _safe_edit(
        query,
        render_post_detail_text(day, lang),
        autopilot_post_action_keyboard(actual_idx, lang),
    )
    return AUTOPILOT_EDIT_INPUT


async def autopilot_post_approve_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[✅ Approve] (`ap_papp:<idx>`) — bitta postni tasdiqlaydi va jadvalga yozadi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_post_approve_callback", _silent_exc)
    lang = _lang(context)
    user_id = query.from_user.id
    days = _stored_days(context)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not days or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    if not await autopilot_channel_guard(user_id, channel_id, "schedule"):
        await _safe_edit(query, autopilot_t("no_permission", lang),
                         get_cancel_keyboard(lang))
        clear_autopilot_session(context)
        return ConversationHandler.END

    data = str(getattr(query, "data", "") or "")
    try:
        idx = int(data.split(":", 1)[1]) if ":" in data else int(context.user_data.get("ap_edit_day", 0))
    except (TypeError, ValueError):
        return AUTOPILOT_VIEW

    res = await approve_single_plan_post(user_id, channel_id, days, idx)
    if not res.get("ok"):
        if res.get("error_code") == "QUOTA_EXCEEDED":
            q_info = res.get("quota") or {}
            await _safe_edit(
                query,
                autopilot_t(
                    "quota_full",
                    lang,
                    current=q_info.get("current", 0),
                    max=q_info.get("max", 0),
                    needed=q_info.get("needed", 1),
                ),
                _quota_keyboard(lang),
            )
            return AUTOPILOT_VIEW
        await _safe_edit(
            query,
            autopilot_t("sched_error", lang),
            autopilot_confirm_keyboard(lang),
        )
        return AUTOPILOT_VIEW

    context.user_data.pop("ap_edit_day", None)
    await _safe_edit(
        query,
        autopilot_t("v2_post_approved", lang, n=idx + 1) + "\n\n"
        + autopilot_t("confirm_hint", lang),
        autopilot_confirm_keyboard(lang),
    )
    return AUTOPILOT_VIEW


async def autopilot_post_edit_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[✏️ Edit] (`ap_pedit:<idx>`) — post uchun yangi matn kiritishni so'raydi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_EDIT_INPUT
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_post_edit_callback", _silent_exc)
    lang = _lang(context)
    days = _stored_days(context)
    data = str(getattr(query, "data", "") or "")
    try:
        idx = int(data.split(":", 1)[1]) if ":" in data else int(context.user_data.get("ap_edit_day", 0))
    except (TypeError, ValueError):
        return AUTOPILOT_EDIT_DAY

    day = view_plan_post(days, idx)
    if day is None:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    actual_idx = int(day.get("index", idx))
    context.user_data["ap_edit_day"] = actual_idx
    names = WEEKDAY_NAMES.get(lang, WEEKDAY_NAMES["uz"])
    await _safe_edit(
        query,
        autopilot_t(
            "edit_prompt",
            lang,
            n=actual_idx + 1,
            weekday=names[int(day.get("weekday", 0)) % 7],
        ),
        get_cancel_keyboard(lang),
    )
    return AUTOPILOT_EDIT_INPUT


async def autopilot_post_regen_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[🔄 Regenerate] (`ap_pregen:<idx>`) — bitta postni AI bilan qayta yaratadi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_post_regen_callback", _silent_exc)
    lang = _lang(context)
    user_id = query.from_user.id
    days = _stored_days(context)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    topic = str(context.user_data.get(UD_TOPIC) or "")
    if not days or not channel_id:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    data = str(getattr(query, "data", "") or "")
    try:
        idx = int(data.split(":", 1)[1]) if ":" in data else int(context.user_data.get("ap_edit_day", 0))
    except (TypeError, ValueError):
        return AUTOPILOT_VIEW

    cfg = _get_or_init_config(context, channel_id=channel_id)
    res = await regenerate_single_plan_post(
        user_id,
        channel_id,
        days,
        idx,
        topic=topic,
        goal=cfg.get("goal", DEFAULT_GOAL),
        lang=lang,
    )
    if not res.get("ok"):
        await _safe_edit(
            query,
            autopilot_t("dup_refresh_failed", lang),
            autopilot_post_action_keyboard(idx, lang),
        )
        return AUTOPILOT_EDIT_INPUT

    context.user_data[UD_DAYS] = days
    context.user_data[UD_DUP_FLAGGED] = []
    updated_day = res.get("post") or view_plan_post(days, idx)
    if updated_day is not None:
        await _safe_edit(
            query,
            autopilot_t("v2_post_regenerated", lang, n=idx + 1) + "\n\n"
            + render_post_detail_text(updated_day, lang),
            autopilot_post_action_keyboard(int(updated_day.get("index", idx)), lang),
        )
        return AUTOPILOT_EDIT_INPUT

    await _safe_edit(
        query,
        autopilot_t("v2_post_regenerated", lang, n=idx + 1),
        autopilot_confirm_keyboard(lang),
    )
    return AUTOPILOT_VIEW


async def autopilot_post_delete_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """[🗑 Delete] (`ap_pdel:<idx>`) — bitta postni rejadan o'chiradi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return AUTOPILOT_VIEW
    try:
        await query.answer()
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_post_delete_callback", _silent_exc)
    lang = _lang(context)
    days = _stored_days(context)
    if not days:
        await _safe_edit(query, autopilot_t("stale", lang))
        return ConversationHandler.END

    data = str(getattr(query, "data", "") or "")
    try:
        idx = int(data.split(":", 1)[1]) if ":" in data else int(context.user_data.get("ap_edit_day", 0))
    except (TypeError, ValueError):
        return AUTOPILOT_VIEW

    remaining = delete_plan_post(days, idx)
    context.user_data[UD_DAYS] = remaining
    context.user_data[UD_DUP_FLAGGED] = []
    context.user_data.pop("ap_edit_day", None)

    if not remaining:
        clear_autopilot_session(context)
        await _safe_edit(query, autopilot_t("cancel_done", lang))
        return ConversationHandler.END

    await _safe_edit(
        query,
        autopilot_t("v2_post_deleted", lang, n=idx + 1) + "\n\n"
        + autopilot_t("confirm_hint", lang),
        autopilot_confirm_keyboard(lang),
    )
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_cancel_callback", _silent_exc)
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.autopilot:autopilot_stale_callback", _silent_exc)
    return ConversationHandler.END


# Moslik aliaslari (testlar va kengaytirilgan chaqiruvlar uchun)
autopilot_edit_menu_callback = autopilot_edit_callback
autopilot_edit_day_selected = autopilot_edit_day_callback
autopilot_edit_day_text_received = autopilot_edit_input_received
autopilot_force_schedule_callback = autopilot_force_callback
autopilot_refresh_flagged_callback = autopilot_refresh_callback


__all__ = [
    "AUTOPILOT_TOPIC", "AUTOPILOT_VIEW", "AUTOPILOT_EDIT_DAY",
    "AUTOPILOT_EDIT_INPUT",
    "CB_AP_CONFIRM", "CB_AP_EDIT", "CB_AP_EDAY", "CB_AP_REGEN",
    "CB_AP_CANCEL", "CB_AP_FORCE", "CB_AP_REFRESH",
    "CB_AP_GOAL", "CB_AP_FREQ", "CB_AP_MODE", "CB_AP_QUIET",
    "CB_AP_PVIEW", "CB_AP_PAPP", "CB_AP_PEDIT", "CB_AP_PREGEN", "CB_AP_PDEL",
    "CB_CHANNEL_AUTOPILOT",
    "UD_CHANNEL", "UD_TITLE", "UD_TOPIC", "UD_DAYS", "UD_DUP_FLAGGED", "UD_CONFIG",
    "UD_CHANNEL_ID", "UD_CHANNEL_TITLE",
    "channel_autopilot_entry", "autopilot_strategy_callback",
    "autopilot_topic_received",
    "autopilot_confirm_callback", "autopilot_force_callback",
    "autopilot_refresh_callback", "autopilot_regen_callback",
    "autopilot_edit_callback", "autopilot_edit_day_callback",
    "autopilot_edit_input_received", "autopilot_back_to_plan_callback",
    "autopilot_post_view_callback", "autopilot_post_approve_callback",
    "autopilot_post_edit_callback", "autopilot_post_regen_callback",
    "autopilot_post_delete_callback",
    "autopilot_cancel_callback", "autopilot_stale_callback",
    "autopilot_channel_guard", "clear_autopilot_session",
    "autopilot_strategy_keyboard", "autopilot_confirm_keyboard",
    "autopilot_duplicate_keyboard", "autopilot_edit_day_keyboard",
    "autopilot_post_action_keyboard",
    "render_plan_text", "render_post_detail_text",
]
