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
        └─ MAGIC_RESULT: natija ekrani + amallar
           [📢 Kanalga yuborish] — ulangan kanallarga DARHOL jo'natish
           [📅 Rejalashtirish] — mavjud scheduler oqimiga (AI_GET_TIME) uzatish
           [🔄 Boshqa uslub] — matnni qayta kiritmasdan qayta generatsiya

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
from keyboards.callback_data import cb
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import btn_label
from locales.translations import clear_fsm_data, get_lang, safe_t
from translations import MAGIC_STYLE_KEYS, magic_t
from utils.ai_agent import (
    generate_magic_post,
    normalize_magic_style,
)
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
MP_CHANNEL_PREFIX = "mp_ch:"
MP_SEND_ALL = "mp_chall"

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
    """Natija ekrani amallari: kanalga yuborish / rejalashtirish / boshqa uslub."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                magic_t("mp_btn_send_channel", lang), callback_data=MP_SEND
            ),
            InlineKeyboardButton(
                magic_t("mp_btn_schedule", lang), callback_data=MP_SCHED
            ),
        ],
        [InlineKeyboardButton(magic_t("mp_btn_restyle", lang), callback_data=MP_RESTYLE)],
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
    if len(post_text) > _MAGIC_RESULT_POST_LIMIT:
        post_text = post_text[:_MAGIC_RESULT_POST_LIMIT - 1] + "…"
    return (
        f"{magic_t('mp_result_header', lang, style=style_label)}"
        f"{post_text}"
        f"{magic_t('mp_result_foot', lang)}"
    )


async def _safe_edit(query, text: str, reply_markup=None):
    """Xabarni edit qiladi; iloji bo'lmasa yangi xabar yuboradi (hech qachon yiqilmaydi)."""
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
async def _magic_refund(user_id: int, is_admin: bool, is_pro: bool):
    """Band qilingan AI ballini qaytaradi (generatsiya xato/timeout bo'lsa)."""
    if is_admin or is_pro:
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
    if not text:
        # Rasm/fayl/sticker va boshqalar — hozircha faqat matn oqimi.
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

    if not is_admin and not is_pro:
        try:
            can_use, used, max_ai = await db.run_db(db.check_ai_limit, user_id)
        except Exception:
            can_use, used, max_ai = True, 0, 0
        if not can_use:
            await _safe_edit(
                query,
                safe_t("ai_limit_msg", lang, used=used, max=max_ai),
                None,
            )
            return MAGIC_STYLE_SELECT
        try:
            reserved = await db.run_db(db.use_user_credit, user_id)
        except Exception:
            reserved = True  # DB band bo'lsa ham oqim davom etadi (fail-open)
        if not reserved:
            await _safe_edit(
                query,
                safe_t("ai_limit_msg", lang, used=used, max=max_ai),
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
        await _magic_refund(user_id, is_admin, is_pro)
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
            chat_id=chat_id, text=(payload or " ")[:4000], parse_mode=parse_mode
        )
        return True
    except Exception:
        pass
    # Fallback: HTML'siz oddiy matn (Telegram parseri umuman ishga tushmaydi).
    try:
        plain = html_escape(post_text)[:4000]
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
