"""📊 POST SCORE & IMPROVER — KILLER FEATURE #4.

Oqim (FSM)::

    [📊 Post Score] tugmasi (asosiy menyu)
        └─ POST_SCORE_INPUT: foydalanuvchi post matnini yuboradi
        └─ baholash — ``services.ai_engine.gateway.score_post`` (BEPUL: kredit
           yechilmaydi, kunlik kvota sarflanmaydi) — 6 mezon (1–10) +
           100 ballik umumiy natija + 1–2 jumlalik tavsiya
        └─ POST_SCORE_RESULT: vizual natija ekrani + amallar
           [✨ 95/100 ga yaxshilash] — AI eng sara variantni yozadi va
              AYNAN shu bosqichda 1 ta AI krediti atomik yechiladi
              (``db.use_user_credit`` → ``CreditsService.spend_credits``);
              xatolikda kredit qaytariladi (refund).
           [📢 Kanalga yuborish] — ulangan kanallarga jo'natish
              (bitta kanal → darhol, ko'p kanal → tanlov)
           [📅 Rejalashtirish] — mavjud scheduler oqimiga (AI_GET_TIME)
           [📊 Boshqa postni baholash] — yangi matn kutiladi

Shuningdek Magic Post / Voice / Image natijalaridagi «📊 Baholash» tugmasi
(``ps_eval:<flow>``) tayyor postni baholash oqimiga uzatadi — post qayta
yozib o'tirilmaydi.

Qoidalar (repo konventsiyalari):
  * har bir callback handler BOSHIDA ``await query.answer()``;
  * barcha matnlar 3 til (uz/ru/en) — ``translations`` paketi (``post_score_t``);
  * natija ekrani ``HTML`` va faqat xavfsiz teglar bilan;
  * xatolikda kredit/kvota qaytariladi, foydalanuvchi band holatda qolmaydi.
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import ADMIN_IDS_SET
from handlers.ai_assistant import AI_GET_TIME, _show_time_prompt
from handlers.image_post import IMAGE_POST_RESULT
from handlers.magic_post import (
    MAGIC_RESULT,
    _magic_deliver_one,
    _safe_edit,
)
from handlers.voice_post import VOICE_RESULT
from keyboards.callback_data import (
    CB_POST_SCORE_CHANNEL,
    CB_POST_SCORE_EVAL,
    CB_POST_SCORE_IMPROVE,
    CB_POST_SCORE_NEW,
    CB_POST_SCORE_SCHEDULE,
    CB_POST_SCORE_SEND,
    CB_POST_SCORE_SEND_ALL,
    cb,
)
from keyboards.default import get_cancel_keyboard
from keyboards.inline import btn_label
from locales.translations import clear_fsm_data, get_lang, safe_t
from services.ai_quota import (
    ai_quota_temp_error_text,
    is_balance_reason,
    release_ai_quota,
    reservation_source,
    reserve_for_flow,
    take_reservation_id,
)
from services.ai_engine.gateway import improve_post_to_95, score_post
from translations import (
    POST_SCORE_CRITERIA_KEYS,
    post_score_advice,
    post_score_band,
    post_score_criterion_label,
    post_score_t,
)
from utils.helpers import (
    check_ai_daily_limit,
    check_ai_rate_limit,
    html_escape,
    safe_html,
)
from utils.post_scorer import score_bar

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (noyob — Magic 430-433, Voice 440-442, Image 520-524)
# ============================================================
POST_SCORE_INPUT = 460        # baholanadigan post matni kutilmoqda
POST_SCORE_RESULT = 461       # natija ekrani + amallar
POST_SCORE_SEND_CHOOSE = 462  # kanal tanlanmoqda (darhol yuborish)

# ============================================================
# CALLBACK PREFIKSLARI (qisqa va noyob: ``ps_``)
# ============================================================
# Kanonik qiymatlar ``keyboards/callback_data.py`` da (64-bayt kafolati bilan):
# Magic/Voice/Image natijalaridagi «📊 Baholash» tugmasi ham shu prefiksni
# ishlatadi — qiymatlar bitta joyda saqlanadi.
PS_IMPROVE = CB_POST_SCORE_IMPROVE
PS_SEND = CB_POST_SCORE_SEND
PS_SCHED = CB_POST_SCORE_SCHEDULE
PS_NEW = CB_POST_SCORE_NEW
PS_EVAL_PREFIX = CB_POST_SCORE_EVAL
PS_CHANNEL_PREFIX = CB_POST_SCORE_CHANNEL
PS_SEND_ALL = CB_POST_SCORE_SEND_ALL

#: Barcha post-score callback'lari uchun regex (stale handler shu bilan qo'riqlanadi).
PS_CALLBACK_PATTERN = r"^ps_"

#: Magic/Voice/Image natijasidan baholash tugmasi uchun regex.
PS_EVAL_PATTERN = r"^ps_eval:"

#: Natija ekranidagi post ko'rinishi chegarasi (Telegram 4096 belgi).
_PS_POST_PREVIEW_LIMIT = 2400

#: Sessiya kalitlari (tozalash uchun yagona ro'yxat).
_PS_SESSION_KEYS = (
    "ps_text", "ps_post", "ps_score", "ps_improved", "ps_channels",
    "ps_origin", "ps_usage_counted",
)

#: «📊 Baholash» tugmasi qaysi oqim natijasidan bosilgani → FSM holati.
_PS_ORIGIN_STATES = {
    "magic": MAGIC_RESULT,
    "voice": VOICE_RESULT,
    "image": IMAGE_POST_RESULT,
}

#: Oqim natijasidagi post matni kalitlari (baholash uchun manba).
_PS_SOURCE_KEYS = {
    "magic": "magic_post_text",
    "voice": "voice_post_text",
    "image": "image_post_text",
}


# ============================================================
# KLAVIATURALAR
# ============================================================
def post_score_action_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Natija ekrani amallari: yaxshilash / kanalga / rejalashtirish / yangi post."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(post_score_t("ps_btn_improve", lang), callback_data=PS_IMPROVE)],
        [
            InlineKeyboardButton(post_score_t("ps_btn_send", lang), callback_data=PS_SEND),
            InlineKeyboardButton(post_score_t("ps_btn_schedule", lang), callback_data=PS_SCHED),
        ],
        [InlineKeyboardButton(post_score_t("ps_btn_again", lang), callback_data=PS_NEW)],
    ])


def post_score_channel_keyboard(channels: list, lang: str) -> InlineKeyboardMarkup:
    """Kanal tanlash klaviaturasi (darhol yuborish) + «Barcha kanallarga»."""
    rows = []
    for idx, channel in enumerate(channels):
        title = channel[1] if len(channel) > 1 else channel[0]
        rows.append([InlineKeyboardButton(
            f"📢 {btn_label(title, fallback='Kanal', max_length=28)}",
            callback_data=cb(PS_CHANNEL_PREFIX, idx),
        )])
    rows.append([InlineKeyboardButton(
        post_score_t("ps_send_all", lang, count=len(channels)),
        callback_data=PS_SEND_ALL,
    )])
    return InlineKeyboardMarkup(rows)


def build_eval_button(source: str, lang: str) -> InlineKeyboardButton:
    """«📊 Baholash» tugmasi — Magic / Voice / Image natijalari uchun.

    ``source`` (``magic`` | ``voice`` | ``image``) post qaysi oqimda
    yaratilganini bildiradi — foydalanuvchi matnni qayta yozmaydi; tugma
    callback'i ``ps_eval:<source>`` ko'rinishida bo'ladi.
    """
    src = source if source in _PS_ORIGIN_STATES else "magic"
    return InlineKeyboardButton(
        post_score_t("ps_btn_eval", lang),
        # 64-bayt kafolati: dinamik qiymat faqat ``cb()`` orqali quriladi.
        callback_data=cb(PS_EVAL_PREFIX, src),
    )


# ============================================================
# MATN BUILDERLAR
# ============================================================
def _localized_recommendation(payload: dict, lang: str) -> str:
    """AI tavsiyasi bo'lmasa — eng kuchsiz mezon uchun tayyor tavsiya."""
    text = (payload or {}).get("recommendation") or ""
    if text.strip():
        return text.strip()
    return post_score_advice((payload or {}).get("weakest") or "structure", lang)


def post_score_result_text(payload: dict, lang: str,
                           header_key: str = "ps_result_header",
                           post_text: str = "") -> str:
    """Natija ekrani: 6 mezon shkalasi + umumiy ball + tavsiya (+ post)."""
    scores = (payload or {}).get("scores") or {}
    overall = int((payload or {}).get("overall") or 0)
    lines = [post_score_t(header_key, lang, overall=overall)]
    lines.append(post_score_t("ps_criteria_header", lang))
    for criterion in POST_SCORE_CRITERIA_KEYS:
        value = scores.get(criterion, 0)
        lines.append(
            f"{post_score_criterion_label(criterion, lang)}  "
            f"{score_bar(value)}  <b>{int(value)}/10</b>\n"
        )
    lines.append(post_score_t(
        "ps_overall_line", lang, overall=overall,
        band=post_score_band(overall, lang),
    ))
    recommendation = _localized_recommendation(payload, lang)
    if recommendation:
        # ``safe_html`` — Telegram uchun xavfsiz, lekin o'zbekcha apostrof (')
        # kabi belgilarni buzmaydi (``html_escape`` ularni &#x27; ga aylantirardi).
        lines.append("\n" + post_score_t(
            "ps_recommendation_label", lang, text=safe_html(recommendation)
        ))
    if (payload or {}).get("fallback"):
        lines.append(post_score_t("ps_fallback_note", lang))

    body = "".join(lines)
    post_text = (post_text or "").strip()
    if post_text:
        if len(post_text) > _PS_POST_PREVIEW_LIMIT:
            post_text = post_text[:_PS_POST_PREVIEW_LIMIT - 1] + "…"
        body += "\n\n" + post_text
    body += post_score_t("ps_result_foot", lang)
    return body


# ============================================================
# YORDAMCHILAR
# ============================================================
def _clear_session(context) -> None:
    """Post Score sessiyasi kalitlarini tozalaydi (til keshi saqlanadi)."""
    for key in _PS_SESSION_KEYS:
        context.user_data.pop(key, None)


def _return_state(context) -> int:
    """Qaysi holatga qaytish kerak (asosiy menyu yoki natija oqimi)."""
    origin = context.user_data.get("ps_origin")
    return _PS_ORIGIN_STATES.get(origin, POST_SCORE_RESULT)


async def _add_credit_back(user_id: int, reservation_id=None) -> None:
    """Yechilgan kvota/kreditni qaytaradi (AI xatosi/timeout bo'lsa).

    ``reservation_id`` berilgan bo'lsa — ATOMIK va IDEMPOTENT
    ``refund_ai_request`` ishlaydi. Legacy bronda (ID yo'q) eski
    ``add_user_credit`` + ``refund_ai_usage`` zanjiri saqlanadi.
    """
    if reservation_id:
        try:
            await release_ai_quota(db, user_id, reservation_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("Post Score refund xatosi (user=%s): %s", user_id, e)
        return
    try:
        await db.run_db(db.add_user_credit, user_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("Post Score refund xatosi (user=%s): %s", user_id, e)
    if hasattr(db, "refund_ai_usage"):
        try:
            await db.run_db(db.refund_ai_usage, user_id)
        except Exception:
            pass


async def _toast(query, text: str) -> None:
    """Xavfsiz toast (xato bo'lsa jim o'tadi)."""
    try:
        await query.answer(text, show_alert=True)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass


async def _send_score_screen(target, payload: dict, lang: str,
                             header_key: str = "ps_result_header",
                             post_text: str = "") -> None:
    """Natija ekranini yangi xabar sifatida yuboradi (post ko'rinib tursin)."""
    markup = post_score_action_keyboard(lang)
    text = post_score_result_text(payload, lang, header_key=header_key,
                                  post_text=post_text)
    reply_text = getattr(target, "reply_text", None)
    if callable(reply_text):
        try:
            await reply_text(text, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    await _safe_edit(target, text, markup)


# ============================================================
# ENTRY: asosiy menyu «📊 Post Score» tugmasi
# ============================================================
async def post_score_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post Score oqimini ochadi: yo'riqnoma + matn kutilmoqda."""
    msg = update.message
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    _clear_session(context)
    await msg.reply_text(
        post_score_t("ps_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return POST_SCORE_INPUT


# ============================================================
# POST_SCORE_INPUT: matn qabul qilinadi → baholash (BEPUL)
# ============================================================
async def post_score_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi post matnini yubordi — 6 mezon bo'yicha baholanadi."""
    msg = update.message
    if msg is None:
        return POST_SCORE_INPUT
    lang = get_lang(context)
    user_id = update.effective_user.id if update.effective_user else 0

    raw_text = msg.text if msg.text is not None else (msg.caption or "")
    text = (raw_text or "").strip()
    if not text:
        # Matn umuman yuborilmagan (rasm/stiker/fayl) → media yo'riqnomasi;
        # faqat bo'sh joy yuborilgan bo'lsa → «bo'sh post» ogohlantirishi.
        key = "ps_warn_media" if not raw_text else "ps_warn_empty"
        await msg.reply_text(post_score_t(key, lang), parse_mode="HTML")
        return POST_SCORE_INPUT

    clean = text.strip()
    if len(clean) < 2:
        await msg.reply_text(post_score_t("ps_warn_empty", lang), parse_mode="HTML")
        return POST_SCORE_INPUT

    # Rate-limit: baholash bepul, lekin AI provayderini flooddan himoya qilamiz.
    if user_id and user_id not in ADMIN_IDS_SET and check_ai_rate_limit(user_id, max_per_minute=6):
        try:
            await msg.reply_text(safe_t("ai_rate_limit_alert", lang), parse_mode="HTML")
        except Exception:
            pass
        return POST_SCORE_INPUT

    status = await msg.reply_text(post_score_t("ps_scoring", lang), parse_mode="HTML")

    try:
        payload = await score_post(clean, lang=lang)
    except Exception as e:  # noqa: BLE001 — oqim hech qachon yiqilmaydi
        logger.error("Post Score xatosi: %s", e)
        payload = {"error": "score_failed"}

    error = (payload or {}).get("error")
    if error:
        hint_key = {
            "empty": "ps_warn_empty",
            "too_short": "ps_warn_short",
            "no_content": "ps_warn_short",
        }.get(str(error), "ps_score_error")  # yaroqsiz matn → xavfsiz ogohlantirish
        try:
            await status.edit_text(post_score_t(hint_key, lang), parse_mode="HTML")
        except Exception:
            await msg.reply_text(post_score_t(hint_key, lang), parse_mode="HTML")
        # Yaroqsiz matnda ham holat matn kutishda qoladi — kredit/limit
        # yechilmaydi va foydalanuvchi qayta urinib ko'ra oladi.
        return POST_SCORE_INPUT

    context.user_data["ps_text"] = clean
    context.user_data["ps_post"] = ""
    context.user_data["ps_score"] = payload
    context.user_data["ps_improved"] = False
    context.user_data.pop("ps_origin", None)

    text_out = post_score_result_text(payload, lang)
    try:
        await status.edit_text(text_out, reply_markup=post_score_action_keyboard(lang),
                               parse_mode="HTML")
    except Exception:
        await _send_score_screen(msg, payload, lang)
    return POST_SCORE_RESULT


# ============================================================
# «📊 Baholash» — Magic / Voice / Image natijasidan
# ============================================================
async def post_score_eval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tayyor postni qayta yozmasdan baholash (natija ekranidan)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    source = (query.data or "").split(":", 1)[-1].strip()
    if source not in _PS_SOURCE_KEYS:
        source = "magic"
    post_text = (context.user_data.get(_PS_SOURCE_KEYS[source]) or "").strip()
    if not post_text:
        await _toast(query, post_score_t("ps_stale", lang))
        return _return_state(context)

    user_id = query.from_user.id if query.from_user else 0
    if user_id and user_id not in ADMIN_IDS_SET and check_ai_rate_limit(user_id, max_per_minute=6):
        await _toast(query, safe_t("ai_rate_limit_alert", lang))
        return _return_state(context)

    try:
        payload = await score_post(post_text, lang=lang)
    except Exception as e:  # noqa: BLE001
        logger.error("Post Score (eval) xatosi: %s", e)
        payload = {"error": "score_failed"}

    if (payload or {}).get("error"):
        await _toast(query, post_score_t("ps_score_error", lang))
        return _return_state(context)

    context.user_data["ps_text"] = post_text
    context.user_data["ps_post"] = ""
    context.user_data["ps_score"] = payload
    context.user_data["ps_improved"] = False
    context.user_data["ps_origin"] = source

    await _send_score_screen(query.message, payload, lang)
    return _return_state(context)


# ============================================================
# POST_SCORE_RESULT: [✨ 95/100 ga yaxshilash] — 1 kredit
# ============================================================
async def post_score_improve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[✨ 95/100 ga yaxshilash]: AI eng sara variantni yozadi (1 kredit atomik)."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = get_lang(context)

    source_text = (context.user_data.get("ps_text") or "").strip()
    if not source_text:
        await _safe_edit(query, post_score_t("ps_stale", lang), None)
        return POST_SCORE_INPUT

    # --- Preflight: rate-limit → kunlik limit → DB kvota → ball rezervi ---
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        await _toast(query, safe_t("ai_rate_limit_alert", lang))
        return _return_state(context)

    is_pro = False
    if not is_admin:
        try:
            is_pro = await db.run_db(db.is_premium, user_id)
        except Exception:
            is_pro = False

    if not is_admin and not is_pro and check_ai_daily_limit(user_id, max_per_day=30):
        await _toast(query, safe_t("ai_daily_limit", lang))
        return _return_state(context)

    # 🔒 PHASE 2 / 1-QADAM: kunlik kvota YOKI AYNAN 1 kredit BITTA atomik
    # tranzaksiyada bron qilinadi (qator qulfi + credits_ledger auditi).
    # Avvalgi ikki alohida tranzaksiya race condition va yarim bron xavfini
    # tug'dirar edi; DB xatosida esa faqat kredit qadami fail-closed edi,
    # kvota qadami esa fail-open (can_use=True) qolardi. Endi ikkalasi ham
    # bitta atomik zanjirda va qat'iy FAIL-CLOSED.
    if not is_admin and not is_pro:
        reservation = await reserve_for_flow(
            db, context, user_id, "post_score", "score", 1)
        if not reservation.get("allowed"):
            if is_balance_reason(reservation.get("reason")):
                await _safe_edit(
                    query, post_score_t("ps_no_credit", lang),
                    post_score_action_keyboard(lang))
            else:
                # DB/pool xatosi — ruxsat YO'Q (fail-closed), muloyim xabar.
                await _safe_edit(query, ai_quota_temp_error_text(lang),
                                 post_score_action_keyboard(lang))
            return _return_state(context)

    await _safe_edit(query, post_score_t("ps_improving", lang), None)

    try:
        result = await improve_post_to_95(source_text, lang=lang, is_pro=is_pro)
    except Exception as e:  # noqa: BLE001 — hech qachon yiqilmaydi
        logger.error("Post Score improve error: %s", e)
        result = {"error": "exception"}

    improved_text = (result or {}).get("post_text") if isinstance(result, dict) else ""
    if not improved_text or (result or {}).get("error"):
        logger.warning("Post Score improve bajarilmadi (lang=%s): %s",
                       lang, (result or {}).get("error"))
        if not is_admin and not is_pro:
            await _add_credit_back(
                user_id, take_reservation_id(context, "score"))
        await _safe_edit(
            query,
            post_score_t("ps_improve_error", lang),
            post_score_action_keyboard(lang),
        )
        return _return_state(context)

    score_payload = (result or {}).get("score") or {}
    context.user_data["ps_post"] = improved_text
    context.user_data["ps_score"] = score_payload
    context.user_data["ps_improved"] = True

    await _safe_edit(
        query,
        post_score_result_text(
            score_payload, lang, header_key="ps_improved_header",
            post_text=improved_text,
        ),
        post_score_action_keyboard(lang),
    )
    return _return_state(context)


# ============================================================
# [📊 Boshqa postni baholash]
# ============================================================
async def post_score_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📊 Boshqa postni baholash]: yangi matn kutish holatiga qaytaradi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    _clear_session(context)
    await _safe_edit(query, post_score_t("ps_intro", lang), None)
    return POST_SCORE_INPUT


# ============================================================
# [📢 Kanalga yuborish]
# ============================================================
async def _finish_send(query, context, targets: list) -> int:
    """Tanlangan kanallarga yuboradi va natija xabarini chiqaradi."""
    lang = get_lang(context)
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    post_text = (context.user_data.get("ps_post")
                 or context.user_data.get("ps_text") or "")

    sent, sent_names = 0, []
    for channel in targets:
        ch_id = channel[0]
        ch_title = channel[1] if len(channel) > 1 else str(ch_id)
        if await _magic_deliver_one(context.bot, ch_id, post_text):
            sent += 1
            sent_names.append(html_escape(str(ch_title or ch_id)))

    if sent > 0:
        # AI kvotasining hisoblagichi (free uchun) — bir marta yoziladi.
        if not is_admin and not context.user_data.get("ps_usage_counted"):
            context.user_data["ps_usage_counted"] = True
            # 🔒 PHASE 2 / 1-qadam: atomik bron sanagichni ALLAQACHON
            # oshirgan — double-count bo'lmasligi uchun atomik bronda
            # increment chaqirilmaydi (legacy bronda eski xatti-harakat).
            if not reservation_source(context, "score"):
                try:
                    await db.run_db(db.increment_ai_usage, user_id)
                except Exception:
                    pass
        try:
            await query.edit_message_text(
                post_score_t("ps_sent_ok", lang,
                             channels=", ".join(sent_names[:5]), count=sent),
                parse_mode="HTML",
            )
        except Exception:
            pass
        clear_fsm_data(context)
        return sent

    try:
        await query.edit_message_text(
            post_score_t("ps_sent_fail", lang),
            reply_markup=post_score_action_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return 0


async def post_score_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📢 Kanalga yuborish]: bitta kanal bo'lsa darhol, ko'p bo'lsa tanlov."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = (context.user_data.get("ps_post")
                 or context.user_data.get("ps_text") or "").strip()
    if not post_text:
        await _toast(query, post_score_t("ps_stale", lang))
        return ConversationHandler.END

    try:
        channels = await db.run_db(db.get_user_channels, query.from_user.id) or []
    except Exception:
        channels = []
    channels = [ch for ch in channels if ch]

    if not channels:
        await _toast(query, post_score_t("ps_no_channels", lang))
        return _return_state(context)

    context.user_data["ps_channels"] = channels
    if len(channels) == 1:
        sent = await _finish_send(query, context, channels)
        return ConversationHandler.END if sent > 0 else _return_state(context)

    await _safe_edit(query, post_score_t("ps_send_choose", lang),
                     post_score_channel_keyboard(channels, lang))
    return POST_SCORE_SEND_CHOOSE


async def post_score_channel_picked_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlandi (yoki «Barcha kanallarga») — yuborish bajariladi."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    channels = context.user_data.get("ps_channels") or []
    post_text = (context.user_data.get("ps_post")
                 or context.user_data.get("ps_text") or "").strip()
    if not post_text or not channels:
        await _toast(query, post_score_t("ps_stale", get_lang(context)))
        return ConversationHandler.END

    if data == PS_SEND_ALL:
        targets = list(channels)
    else:
        try:
            idx = int(data.split(":", 1)[-1])
            targets = [channels[idx]]
        except (ValueError, IndexError):
            return POST_SCORE_SEND_CHOOSE

    sent = await _finish_send(query, context, targets)
    return ConversationHandler.END if sent > 0 else POST_SCORE_SEND_CHOOSE


# ============================================================
# [📅 Rejalashtirish] — mavjud scheduler oqimi (AI_GET_TIME)
# ============================================================
async def post_score_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📅 Rejalashtirish]: postni AI_GET_TIME → AI_CONFIRM oqimiga uzatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = (context.user_data.get("ps_post")
                 or context.user_data.get("ps_text") or "").strip()
    if not post_text:
        await _toast(query, post_score_t("ps_stale", lang))
        return ConversationHandler.END

    # Scheduler oqimi (ai_time_received/ai_confirm_callback) kutgan kalitlar:
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_file_id"] = None
    context.user_data["ai_post_type"] = "text"
    context.user_data.pop("ai_scheduled_time", None)
    context.user_data.pop("ai_target_all", None)
    _clear_session(context)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_time_prompt(query.message, post_text, None, "text", lang)
    return AI_GET_TIME


# ============================================================
# STALE TUGMALAR (conversation tashqarisida bosilgan eski tugmalar)
# ============================================================
async def post_score_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``^ps_`` tugmalari sessiya tugagach bosilsa — jim toast ko'rsatadi."""
    query = update.callback_query
    try:
        await query.answer(post_score_t("ps_stale", get_lang(context)), show_alert=True)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass


__all__ = [
    "POST_SCORE_INPUT", "POST_SCORE_RESULT", "POST_SCORE_SEND_CHOOSE",
    "PS_IMPROVE", "PS_SEND", "PS_SCHED", "PS_NEW", "PS_EVAL_PREFIX",
    "PS_CHANNEL_PREFIX", "PS_SEND_ALL", "PS_CALLBACK_PATTERN", "PS_EVAL_PATTERN",
    "post_score_entry", "post_score_text_received", "post_score_eval_callback",
    "post_score_improve_callback", "post_score_new_callback",
    "post_score_send_callback", "post_score_channel_picked_callback",
    "post_score_schedule_callback", "post_score_stale_callback",
    "post_score_action_keyboard", "post_score_channel_keyboard",
    "post_score_result_text", "build_eval_button",
]
