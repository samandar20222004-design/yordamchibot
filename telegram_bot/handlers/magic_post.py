"""✨ MAGIC POST — KILLER FEATURE #1 (matn → uslub → tayyor post).

Oqim (FSM):

    [✨ Magic Post] tugmasi (asosiy menyu)
        └─ MAGIC_INPUT: foydalanuvchi matn / mahsulot tavsifi / xom g'oya
           yuboradi
        └─ MAGIC_STYLE_SELECT: uslub tanlanadi
           (🔥 Sotuv | 💎 Premium | 😊 Oddiy | 📢 Reklama | 📰 Informativ)
        └─ generatsiya — mavjud Gemini / Groq bepul AI zanjiri
           (:func:`utils.ai_agent.generate_magic_post`, uslubga xos tizim
           prompti bilan) — soniyalar ichida tayyor post
        └─ MAGIC_RESULT: natija ekrani + FAQAT eng kerakli amallar
           [📢 Kanalga yuborish] [📅 Rejalashtirish]
           [✏️ Qayta yozish / Uslub] [📊 Baholash]
                       [◀️ Orqaga]
           (mp_restyle — matnni qayta kiritmasdan qayta generatsiya;
            mp_back — Kontent yaratish submenyusiga qaytish)
        └─ MAGIC_INPUT'da ovoz/rasm yuborilsa — mos killer-feature oqimiga
           (🎙 Ovoz → Post / 📸 Rasm → Post) uzatiladi.

Qoidalar (repo konventsiyalari):
  * har bir callback handler BOSHIDA ``await query.answer()``;
  * barcha matnlar 3 til (uz/ru/en) — ``translations`` paketi;
  * xatolikda ball qaytariladi (refund), foydalanuvchi hech qachon
    band holatda qolib ketmaydi;
  * ball rezervi / kunlik limit / rate-limit — AI Studio bilan bir xil
    qoidalar (``magic_style_callback`` boshidagi preflight);
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from config import ADMIN_IDS_SET
from handlers.ai_assistant import AI_GET_TIME, _show_time_prompt
from keyboards.callback_data import CB_POST_SCORE_EVAL, cb
from keyboards.default import (
    get_cancel_keyboard,
    get_content_creation_keyboard,
)
from keyboards.inline import btn_label
from locales.translations import clear_fsm_data, get_lang, safe_t
from services.ai_quota import (
    denial_message,
    release_ai_quota,
    reservation_source,
    reserve_for_flow,
    take_reservation_id,
)
from translations import MAGIC_STYLE_KEYS, content_menu_t, magic_t, post_score_t
from utils.ai_agent import (
    generate_magic_post,
    normalize_magic_style,
)
from telegram.error import BadRequest
from utils.telegram_sanitizer import html_to_text, sanitize_html
from utils.helpers import (
    check_ai_daily_limit,
    check_ai_rate_limit,
    html_escape,
    telegram_html_payload,
)

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (noyob — repodagi boshqa 4xx holatlar bilan to'qnashmaydi)
# ============================================================
MAGIC_INPUT = 430         # xom matn/matn g'oya kutilmoqda
MAGIC_STYLE_SELECT = 431  # uslub tanlanmoqda
MAGIC_RESULT = 432        # tayyor post + amallar
MAGIC_SEND_CHOOSE = 433   # kanal tanlanmoqda (darhol yuborish)

# Callback data prefikslari (global stale-handler ``^mp_`` bilan qo'riqlanadi)
MP_STYLE_PREFIX = "mp_style:"
MP_SEND = "mp_send"
MP_SCHED = "mp_sched"
MP_RESTYLE = "mp_restyle"
MP_BACK = "mp_back"
MP_CHANNEL_PREFIX = "mp_ch:"
MP_SEND_ALL = "mp_chall"

#: 📊 Post Score oqimiga uzatish uchun manba nomi (``ps_eval:magic``).
PS_EVAL_SOURCE = "magic"

#: Natija ekrani post matni chegarasi (Telegram 4096 belgi xavfsiz chegarasi).
_MAGIC_RESULT_POST_LIMIT = 3600


# ============================================================
# KLAVIATURALAR
# ============================================================
def _magic_style_keyboard(lang: str) -> InlineKeyboardMarkup:
    """5 uslub tugmasi (3+2 qator) — callback ``mp_style:<style>``."""
    buttons = [
        InlineKeyboardButton(
            magic_t(label_key, lang),
            callback_data=cb(MP_STYLE_PREFIX, style),
        )
        for style, (label_key, _desc_key) in MAGIC_STYLE_KEYS.items()
    ]
    return InlineKeyboardMarkup([buttons[:3], buttons[3:]])


def _magic_action_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Natija ekrani — FAQAT eng kerakli amallar (2-BOSQICH ixcham layout):

        [📢 Kanalga yuborish]      [📅 Rejalashtirish]
        [✏️ Qayta yozish / Uslub]  [📊 Baholash]
                    [◀️ Orqaga]

    ``mp_restyle`` callback'i saqlanadi (eski chat tarixidagi «🔄 Boshqa
    uslub» tugmalari ishlashda davom etadi) — faqat yorliq yangilandi.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                magic_t("mp_btn_send_channel", lang), callback_data=MP_SEND
            ),
            InlineKeyboardButton(
                magic_t("mp_btn_schedule", lang), callback_data=MP_SCHED
            ),
        ],
        [
            InlineKeyboardButton(magic_t("mp_btn_rewrite", lang), callback_data=MP_RESTYLE),
            # 📊 Post Score (Killer Feature #4): tayyor postni qayta yozmasdan
            # baholash oqimiga uzatadi (``ps_eval:magic``) — kredit yechilmaydi.
            InlineKeyboardButton(
                post_score_t("ps_btn_eval", lang),
                callback_data=cb(CB_POST_SCORE_EVAL, PS_EVAL_SOURCE),
            ),
        ],
        [InlineKeyboardButton(magic_t("mp_btn_back", lang), callback_data=MP_BACK)],
    ])


def _magic_channel_keyboard(channels: list, lang: str) -> InlineKeyboardMarkup:
    """Kanal tanlash klaviaturasi (darhol yuborish) + «Barcha kanallarga»."""
    rows = []
    for idx, channel in enumerate(channels):
        title = channel[1] if len(channel) > 1 else channel[0]
        rows.append([InlineKeyboardButton(
            f"📢 {btn_label(title, fallback='Kanal', max_length=28)}",
            callback_data=cb(MP_CHANNEL_PREFIX, idx),
        )])
    rows.append([InlineKeyboardButton(
        magic_t("mp_send_all", lang, count=len(channels)),
        callback_data=MP_SEND_ALL,
    )])
    return InlineKeyboardMarkup(rows)


# ============================================================
# MATN BUILDERLAR
# ============================================================
def _magic_style_menu_text(raw_text: str, lang: str, hint_key: str = "mp_choose_style") -> str:
    """Uslub tanlash ekrani: sarlavha + matn ko'rinishi + uslublar jadvali."""
    raw_text = (raw_text or "").strip()
    preview = raw_text[:220] + ("…" if len(raw_text) > 220 else "")
    legend = "\n".join(
        f"{magic_t(label_key, lang)} — {magic_t(desc_key, lang)}"
        for _style, (label_key, desc_key) in MAGIC_STYLE_KEYS.items()
    )
    return (
        f"{magic_t(hint_key, lang)}\n{preview}\n\n{legend}"
        f"{magic_t('mp_choose_style_foot', lang)}"
    )


def _magic_result_text(post_text: str, style: str, lang: str) -> str:
    """Natija ekrani: header + post + footer (post xavfsiz HTML)."""
    style_label = magic_t(
        MAGIC_STYLE_KEYS.get(style, ("mp_style_casual", ""))[0], lang
    )
    post_text = (post_text or "").strip()
    post_text = sanitize_html(post_text, _MAGIC_RESULT_POST_LIMIT)
    return (
        f"{magic_t('mp_result_header', lang, style=style_label)}"
        f"{post_text}"
        f"{magic_t('mp_result_foot', lang)}"
    )


async def _safe_edit(query, text: str, reply_markup=None):
    """Xabarni edit qiladi; iloji bo'lmasa yangi xabar yuboradi (hech qachon yiqilmaydi)."""
    text = sanitize_html(text)
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        try:
            await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            pass


# ============================================================
# AI BALL / LIMIT PREFLIGHT (AI Studio bilan bir xil qoidalar)
# ============================================================
async def _magic_refund(user_id: int, is_admin: bool, is_pro: bool,
                        reservation_id=None):
    """Band qilingan AI kvota/kreditini qaytaradi (generatsiya xato/timeout).

    ``reservation_id`` berilgan bo'lsa — ATOMIK va IDEMPOTENT
    ``refund_ai_request`` ishlaydi (ikki marta qaytarib bo'lmaydi). Legacy
    bronda (ID yo'q) eski ``add_user_credit`` + ``refund_ai_usage`` zanjiri
    saqlanadi.
    """
    if is_admin or is_pro:
        return
    if reservation_id:
        try:
            await release_ai_quota(db, user_id, reservation_id)
        except Exception:
            pass
        return
    try:
        await db.run_db(db.add_user_credit, user_id)
    except Exception:
        pass
    if hasattr(db, "refund_ai_usage"):
        try:
            await db.run_db(db.refund_ai_usage, user_id)
        except Exception:
            pass


# ============================================================
# MEDIA ROUTING: Magic Post ichida ovoz/rasm → o'z killer-feature oqimi
# ============================================================
def _is_voice_message(msg) -> bool:
    if getattr(msg, "voice", None) or getattr(msg, "audio", None):
        return True
    doc = getattr(msg, "document", None)
    mime = str(getattr(doc, "mime_type", "") or "").lower() if doc is not None else ""
    return mime.startswith("audio/")


def _is_image_message(msg) -> bool:
    if getattr(msg, "photo", None):
        return True
    doc = getattr(msg, "document", None)
    mime = str(getattr(doc, "mime_type", "") or "").lower() if doc is not None else ""
    return mime.startswith("image/")


async def _route_media_to_flow(update, context, msg):
    """Ovoz → ``voice_message_received``, rasm → ``image_photo_received``.

    Mos oqim topilsa uning FSM holatini qaytaradi; media emas yoki oqim
    mavjud bo'lmasa ``None`` (chaqiruvchi mp_media_hint ko'rsatadi).
    Importlar funksiya ichida — aylanma importdan himoya (voice_post shu
    modulni import qiladi).
    """
    try:
        if _is_voice_message(msg):
            from handlers.voice_post import voice_message_received

            for key in ("magic_raw_text", "magic_post_text", "magic_style",
                        "magic_channels", "magic_usage_counted"):
                context.user_data.pop(key, None)
            return await voice_message_received(update, context)
        if _is_image_message(msg):
            from handlers.image_post import image_photo_received

            for key in ("magic_raw_text", "magic_post_text", "magic_style",
                        "magic_channels", "magic_usage_counted"):
                context.user_data.pop(key, None)
            return await image_photo_received(update, context)
    except Exception as exc:  # noqa: BLE001 — oqim hech qachon yiqilmaydi
        logger.warning("Magic Post media routing xatosi: %s", type(exc).__name__)
    return None


# ============================================================
# ENTRY: asosiy menyu «✨ Magic Post» tugmasi
# ============================================================
async def magic_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Magic Post oqimini ochadi: yo'riqnoma + matn kutilmoqda."""
    msg = update.message
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    # Eski magic sessiyasi qoldiqlarini tozalaymiz (yangi oqim — toza boshlanish).
    for key in ("magic_raw_text", "magic_post_text", "magic_style",
                "magic_channels", "magic_usage_counted"):
        context.user_data.pop(key, None)
    await msg.reply_text(
        magic_t("mp_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return MAGIC_INPUT


# Alias for backward compatibility and tests
magic_start = magic_post_entry


# ============================================================
# MAGIC_INPUT: xom matn qabul qilinadi → uslublar menyusi
# ============================================================
async def magic_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi matn/g'oyasini yubordi — uslub tanlash ekrani chiqadi."""
    msg = update.message
    if msg is None:
        return MAGIC_INPUT
    lang = get_lang(context)

    text = (msg.text or "").strip()
    if text:
        try:
            from middlewares.fsm_cleaner import is_cancel_trigger, is_start_or_menu_trigger, clear_user_fsm
        except ImportError:
            from telegram_bot.middlewares.fsm_cleaner import is_cancel_trigger, is_start_or_menu_trigger, clear_user_fsm
        if is_cancel_trigger(text):
            clear_user_fsm(context)
            from handlers.start import cancel_handler
            return await cancel_handler(update, context)
        if is_start_or_menu_trigger(text):
            clear_user_fsm(context)
            from handlers.start import start
            return await start(update, context)

    if not text:
        # 🎙 Ovoz → «🎙 Ovoz → Post» (STT) oqimiga, 📸 rasm → «📸 Rasm → Post»
        # (Vision) oqimiga UZATILADI — intro va'da qilganidek, foydalanuvchi
        # Magic Post ichida ham ovoz/rasm yubora oladi (matn qayta so'ralmaydi).
        routed = await _route_media_to_flow(update, context, msg)
        if routed is not None:
            return routed
        # Boshqa media (sticker/fayl) — caption bo'lsa matn sifatida olinadi.
        if (msg.caption or "").strip():
            text = msg.caption.strip()
        else:
            await msg.reply_text(
                magic_t("mp_media_hint", lang),
                parse_mode="HTML",
            )
            return MAGIC_INPUT

    if len(text) < 2:
        await msg.reply_text(magic_t("mp_text_hint", lang), parse_mode="HTML")
        return MAGIC_INPUT

    context.user_data["magic_raw_text"] = text
    await msg.reply_text(
        _magic_style_menu_text(text, lang),
        reply_markup=_magic_style_keyboard(lang),
        parse_mode="HTML",
    )
    return MAGIC_STYLE_SELECT


# ============================================================
# MAGIC_STYLE_SELECT: uslub tanlandi → AI generatsiya
# ============================================================
async def magic_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uslub tugmasi: AI so'rovi uslubga xos tizim prompti bilan yuboriladi."""
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    style = normalize_magic_style((query.data or "").split(":", 1)[-1])
    raw_text = (context.user_data.get("magic_raw_text") or "").strip()
    if not raw_text:
        await _safe_edit(query, magic_t("mp_stale", lang), None)
        return MAGIC_INPUT

    # --- Preflight: rate-limit → kunlik limit → DB kvota → ball rezervi ---
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        try:
            await query.answer(safe_t("ai_rate_limit_alert", lang), show_alert=True)
        except Exception:
            pass
        return MAGIC_STYLE_SELECT

    is_pro = False
    if not is_admin:
        try:
            is_pro = await db.run_db(db.is_premium, user_id)
        except Exception:
            is_pro = False

    if not is_admin and not is_pro and check_ai_daily_limit(user_id, max_per_day=30):
        try:
            await query.answer(safe_t("ai_daily_limit", lang), show_alert=True)
        except Exception:
            pass
        return MAGIC_STYLE_SELECT

    # 🔒 PHASE 2 / 1-QADAM: kunlik kvota YOKI kredit BITTA atomik
    # tranzaksiyada bron qilinadi (qator qulfi + credits_ledger auditi).
    # Avvalgi ikki qadam (check_ai_limit + use_user_credit) alohida
    # tranzaksiyalar edi → race condition va yarim bron xavfi bor edi;
    # DB xatosida esa oqim DAVOM ETARDI (fail-open). Endi qat'iy FAIL-CLOSED.
    if not is_admin and not is_pro:
        reservation = await reserve_for_flow(
            db, context, user_id, "magic_post", "magic", 1)
        if not reservation.get("allowed"):
            await _safe_edit(
                query,
                denial_message(
                    reservation,
                    safe_t("ai_limit_msg", lang,
                           used=int(reservation.get("used") or 0),
                           max=int(reservation.get("max_ai") or 0)),
                    lang,
                ),
                None,
            )
            return MAGIC_STYLE_SELECT

    context.user_data["magic_style"] = style
    style_label = magic_t(MAGIC_STYLE_KEYS[style][0], lang)
    await _safe_edit(query, magic_t("mp_generating", lang, style=style_label), None)

    # --- ✨ AI generatsiya (Gemini/Groq bepul zanjiri, uslubga xos prompt) ---
    try:
        result = await generate_magic_post(raw_text, style, lang=lang, is_pro=is_pro)
    except Exception as e:  # noqa: BLE001 — hech qachon yiqilmaydi
        logger.error("Magic Post generation error: %s", e)
        result = {"error": "exception"}

    if not isinstance(result, dict) or result.get("error") or not (result.get("post_text") or "").strip():
        logger.warning("Magic Post AI xatosi (style=%s, lang=%s): %s",
                       style, lang, (result or {}).get("error"))
        await _magic_refund(
            user_id, is_admin, is_pro,
            take_reservation_id(context, "magic"),
        )
        await _safe_edit(
            query,
            magic_t("mp_error", lang),
            _magic_style_keyboard(lang),
        )
        return MAGIC_STYLE_SELECT

    post_text = (result.get("post_text") or "").strip()
    context.user_data["magic_post_text"] = post_text
    context.user_data["magic_style"] = result.get("style", style)
    context.user_data["magic_usage_counted"] = False

    await _safe_edit(query, _magic_result_text(post_text, result.get("style", style), lang),
                     _magic_action_keyboard(lang))
    return MAGIC_RESULT


# ============================================================
# YUBORISH: kanalga darhol jo'natish
# ============================================================
async def _magic_deliver_one(bot, chat_id, post_text: str) -> bool:
    """Bitta kanalga post yuboradi (safe HTML, xato bo'lsa plain-text fallback)."""
    payload, parse_mode = telegram_html_payload(post_text)
    try:
        await bot.send_message(
            chat_id=chat_id, text=payload or " ", parse_mode=parse_mode
        )
        return True
    except BadRequest as exc:
        if "parse entities" not in str(exc).lower():
            logger.warning("Magic Post rejected (chat=%s): %s", chat_id, exc)
            return False
    except Exception as exc:
        # Unknown delivery/permissions/flood errors are not parse failures.
        # A second send after a timeout could publish the same post twice.
        logger.warning("Magic Post delivery failed (chat=%s): %s", chat_id, exc)
        return False
    # Fallback: HTML'siz oddiy matn (Telegram parseri umuman ishga tushmaydi).
    try:
        plain = html_to_text(post_text, 4096) or " "
        await bot.send_message(chat_id=chat_id, text=plain, parse_mode=None)
        return True
    except Exception as e:
        logger.warning("Magic Post yuborish xatosi (chat=%s): %s", chat_id, e)
        return False


async def _magic_finish_send(query, context, targets: list) -> int:
    """Tanlangan kanallarga yuboradi, natija xabarini chiqaradi va sessiyani yopadi.

    Returns: muvaffaqiyatli yuborilgan kanallar soni.
    """
    user_id = query.from_user.id
    lang = get_lang(context)
    is_admin = (user_id in ADMIN_IDS_SET)
    post_text = context.user_data.get("magic_post_text") or ""

    sent, sent_names = 0, []
    for channel in targets:
        ch_id = channel[0]
        ch_title = channel[1] if len(channel) > 1 else str(ch_id)
        if await _magic_deliver_one(context.bot, ch_id, post_text):
            sent += 1
            sent_names.append(html_escape(str(ch_title or ch_id)))

    if sent > 0:
        # AI ball "sarflandi" — birinchi muvaffaqiyatli yuborishda (free uchun).
        if not is_admin and not context.user_data.get("magic_usage_counted"):
            context.user_data["magic_usage_counted"] = True
            # 🔒 PHASE 2 / 1-qadam: atomik bron kunlik sanagichni ALLAQACHON
            # oshirgan (reserve_ai_request). Shu sababli atomik bronda
            # increment_ai_usage chaqirilmaydi — double-count bo'lmasligi
            # uchun. Legacy bronda (test adapterlari / eski deploy) eski
            # xatti-harakat saqlanadi.
            if not reservation_source(context, "magic"):
                try:
                    await db.run_db(db.increment_ai_usage, user_id)
                except Exception:
                    pass
        try:
            await query.edit_message_text(
                magic_t(
                    "mp_sent_ok", lang,
                    channels=", ".join(sent_names[:5]),
                    count=sent,
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
        # Sessiya tugadi — kontekst tozalanadi (til saqlanadi).
        clear_fsm_data(context)
        return sent

    try:
        await query.edit_message_text(
            magic_t("mp_sent_fail", lang),
            reply_markup=_magic_action_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return 0


async def magic_send_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📢 Kanalga yuborish]: bitta kanal bo'lsa darhol, ko'p bo'lsa tanlov."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = context.user_data.get("magic_post_text") or ""
    if not post_text:
        try:
            await query.answer(magic_t("mp_stale", lang), show_alert=True)
        except Exception:
            pass
        return ConversationHandler.END

    try:
        channels = await db.run_db(db.get_user_channels, query.from_user.id) or []
    except Exception:
        channels = []
    channels = [ch for ch in channels if ch]

    if not channels:
        try:
            await query.answer(magic_t("mp_no_channels", lang), show_alert=True)
        except Exception:
            pass
        return MAGIC_RESULT

    context.user_data["magic_channels"] = channels
    if len(channels) == 1:
        sent = await _magic_finish_send(query, context, channels)
        # Yuborish muvaffaqiyatsiz bo'lsa sessiya ochiq qoladi (qayta urinish).
        return ConversationHandler.END if sent > 0 else MAGIC_RESULT

    await _safe_edit(query, magic_t("mp_send_choose", lang),
                     _magic_channel_keyboard(channels, lang))
    return MAGIC_SEND_CHOOSE


async def magic_channel_picked_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlandi (yoki «Barcha kanallarga») — yuborish bajariladi."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    channels = context.user_data.get("magic_channels") or []
    post_text = context.user_data.get("magic_post_text") or ""
    if not post_text or not channels:
        try:
            await query.answer(magic_t("mp_stale", get_lang(context)), show_alert=True)
        except Exception:
            pass
        return ConversationHandler.END

    if data == MP_SEND_ALL:
        targets = list(channels)
    else:
        try:
            idx = int(data.split(":", 1)[-1])
            targets = [channels[idx]]
        except (ValueError, IndexError):
            return MAGIC_SEND_CHOOSE

    sent = await _magic_finish_send(query, context, targets)
    # Yuborish muvaffaqiyatsiz bo'lsa — tanlov menyusi ochiq qoladi.
    return ConversationHandler.END if sent > 0 else MAGIC_SEND_CHOOSE


# ============================================================
# REJALASHTIRISH: mavjud scheduler oqimiga uzatish (AI_GET_TIME)
# ============================================================
async def magic_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📅 Rejalashtirish]: postni AI_GET_TIME → AI_CONFIRM oqimiga uzatadi.

    ``ai_studio_schedule_callback`` bilan bir xil kontrakt: ``ai_generated_post``
    va media kalitlari to'ldirilib, vaqt tanlash oynasi ko'rsatiladi. Vaqt
    kiritilgach mavjud scheduler xizmati postni DB'ga yozadi va jo'natadi.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = context.user_data.get("magic_post_text") or ""
    if not post_text:
        try:
            await query.answer(magic_t("mp_stale", lang), show_alert=True)
        except Exception:
            pass
        return ConversationHandler.END

    # Scheduler oqimi (ai_time_received/ai_confirm_callback) kutgan kalitlar:
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_file_id"] = None
    context.user_data["ai_post_type"] = "text"
    context.user_data.pop("ai_scheduled_time", None)
    context.user_data.pop("ai_target_all", None)
    # Magic-oqim qoldiqlari endi kerak emas.
    for key in ("magic_raw_text", "magic_post_text", "magic_style",
                "magic_channels", "magic_usage_counted"):
        context.user_data.pop(key, None)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_time_prompt(query.message, post_text, None, "text", lang)
    return AI_GET_TIME


# ============================================================
# BOSHQA USLUB: matnni qayta kiritmasdan qayta generatsiya
# ============================================================
async def magic_restyle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[🔄 Boshqa uslub]: saqlangan matn bilan uslublar menyusini qaytaradi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    raw_text = (context.user_data.get("magic_raw_text") or "").strip()
    if not raw_text:
        await _safe_edit(query, magic_t("mp_stale", lang), None)
        return MAGIC_INPUT

    context.user_data.pop("magic_post_text", None)
    await _safe_edit(query, _magic_style_menu_text(raw_text, lang, "mp_restyle_hint"),
                     _magic_style_keyboard(lang))
    return MAGIC_STYLE_SELECT


# ============================================================
# ◀️ ORQAGA: natija ekranidan «🧩 Kontent yaratish» submenyusiga
# ============================================================
async def magic_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[◀️ Orqaga]: Magic sessiyasi yopiladi, Kontent yaratish submenyusi chiziladi.

    4-qadam navigatsiya stacki: foydalanuvchi «🧩 Kontent yaratish» →
    «✨ Magic Post» yo'li bilan kelgan — Orqaga aynan shu yo'lni teskari
    yuradi (asosiy menyuga sakramaydi). Kredit/limit tegilmaydi.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    for key in ("magic_raw_text", "magic_post_text", "magic_style",
                "magic_channels", "magic_usage_counted"):
        context.user_data.pop(key, None)
    clear_fsm_data(context)
    try:
        from handlers.navigation import SECTION_CONTENT, remember_section

        remember_section(context, SECTION_CONTENT)
    except Exception:  # pragma: no cover - navigatsiya moduli bo'lmasa ham ishlaydi
        pass
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    try:
        await query.message.reply_text(
            content_menu_t("cm_menu_intro", lang),
            reply_markup=get_content_creation_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return ConversationHandler.END


# ============================================================
# STALE TUGMALAR (conversation tashqarisida bosilgan eski tugmalar)
# ============================================================
async def magic_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``^mp_`` tugmalari sessiya tugagach bosilsa — jim toast ko'rsatadi."""
    query = update.callback_query
    try:
        lang = get_lang(context)
        await query.answer(magic_t("mp_stale", lang), show_alert=True)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass
