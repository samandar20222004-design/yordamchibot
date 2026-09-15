"""🎙 VOICE → POST — KILLER FEATURE (ovoz → matn → uslub → tayyor post).

RESURS-TEJAMKOR OQIM (FSM):

    Foydalanuvchi ovozli xabar (Voice) yoki audio yuboradi
        └─ ⛑ CHEKLOVLAR (resurs himoyasi — kredit/limit EMAS):
           * FREE: maksimum 60 soniya (1 daqiqa)
           * PRO:  maksimum 180 soniya (3 daqiqa)
           * fayl hajmi: maksimum 20 MB
           Cheklovdan oshsa — xushmuomala rad etish, HECH NARSA yechilmaydi.
        └─ STT ($0 XARAJAT): Groq Whisper Large v3 (bepul) → zaxira
           Gemini multimodal audio (:func:`utils.audio_transcriber`).
           Transkripsiya bepul — AI limiti/krediti YECHILMAYDI.
        └─ VOICE_STYLE_SELECT: transkripsiyalangan xom matn ko'rsatiladi:
           «🎙 Sizning ovozingiz matnga o'girildi: '...'
             Qaysi uslubda post tayyorlaymiz?»
           [🔥 Sotuv] [💎 Premium] [😊 Oddiy] [📢 Reklama] [📰 Informativ]
           [❌ Bekor qilish] — bekor qilinsa HECH NARSA yechilmaydi.
        └─ Uslub tanlanganda FAQAT SHU PAYT: credits_service orqali FAQAT
           1 ta yagona AI kvotasi/krediti ATOMIK yechiladi
           (``db.check_ai_limit`` + ``db.use_user_credit`` — magic post
           bilan bir xil preflight zanjiri), so'ng Magic Post prompti
           orqali tayyor post generatsiya qilinadi.
        └─ VOICE_RESULT: natija ekrani + amallar
           [📢 Kanalga yuborish] [📅 Rejalashtirish] [🔄 Boshqa uslub]

Qoidalar (repo konventsiyalari — magic_post bilan bir xil):
  * har bir callback handler BOSHIDA ``await query.answer()``;
  * barcha matnlar 3 til (uz/ru/en) — ``translations.voice_post``;
  * xatolikda ball qaytariladi (refund) — foydalanuvchi hech qachon
    band holatda qolib ketmaydi;
  * Magic Post oqimi VA UNING TESTLARI BUZILMAYDI — yordamchilar
    (``_safe_edit``, ``_magic_deliver_one``) qayta ishlatiladi.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters

import database as db
from config import ADMIN_IDS_SET
from handlers.ai_assistant import AI_GET_TIME, _show_time_prompt
# Magic Post'dan barqaror (test qilingan) yordamchilar — oqimlar bir xil
# ko'rinsin va mantiq DUBLIKATSIZ bo'lsin. Bu yordamchilar faqat (query, text,
# markup) / (bot, chat_id, post_text) kontraktida ishlaydi — magic post
# regressiyasiga ta'sir qilmaydi.
from handlers.magic_post import _magic_deliver_one, _safe_edit
from handlers.start import check_user_subscribed, ensure_user_lang
from keyboards.callback_data import CB_POST_SCORE_EVAL, cb
from keyboards.default import get_cancel_keyboard
from keyboards.inline import btn_label, get_subscription_check_keyboard
from locales.translations import clear_fsm_data, get_lang, safe_t
from services.ai_quota import (
    denial_message,
    release_ai_quota,
    reservation_source,
    reserve_for_flow,
    take_reservation_id,
)
from translations import MAGIC_STYLE_KEYS, magic_t, post_score_t, voice_t
from utils.ai_agent import (
    MAGIC_POST_MAX_MATERIAL_CHARS,
    generate_magic_post,
    normalize_magic_style,
)
from utils.audio_transcriber import (
    check_duration,
    check_size,
    transcribe_voice,
)
from utils.helpers import (
    check_ai_daily_limit,
    check_ai_rate_limit,
    html_escape,
)

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (noyob — repodagi boshqa 4xx holatlar bilan to'qnashmaydi)
# ============================================================
VOICE_AWAIT = 439         # 🧩 submenu'dan kirish: ovozli xabar kutilmoqda
VOICE_STYLE_SELECT = 440  # uslub tanlanmoqda (transkripsiya allaqachon tayyor)
VOICE_RESULT = 441        # tayyor post + amallar
VOICE_SEND_CHOOSE = 442   # kanal tanlanmoqda (darhol yuborish)

# Callback data prefikslari (global stale-handler ``^vp_`` bilan qo'riqlanadi)
VP_STYLE_PREFIX = "vp_style:"
VP_CANCEL = "vp_cancel"
VP_SEND = "vp_send"
VP_SCHED = "vp_sched"
VP_RESTYLE = "vp_restyle"
VP_CHANNEL_PREFIX = "vp_ch:"
VP_SEND_ALL = "vp_chall"

#: 📊 Post Score oqimiga uzatish uchun manba nomi (``ps_eval:voice``).
PS_EVAL_SOURCE = "voice"

#: 🎙 Ovozli xabar / audio filtri — faqat shaxsiy chat, tahrirlanganlar tashqari.
VOICE_MESSAGE_FILTER = (
    (filters.VOICE | filters.AUDIO | filters.Document.AUDIO)
    & filters.ChatType.PRIVATE
    & ~filters.UpdateType.EDITED
)


# ============================================================
# ENTRY HANDLER — dialog TASHQARISIDA GINA mos keladi (regressiya himoyasi)
# ============================================================
# PTB ``ConversationHandler(allow_reentry=True)`` entry point'larni FAOL
# dialog paytida ham tekshiradi. Oddiy MessageHandler entry bo'lsa, foydalanuvchi
# boshqa dialog o'rtasida (masalan ball o'tkazish — TRANSFER_TARGET) ovoz
# yuborsa — ovozli oqim dialogni BUZARDI. Eski repo xulqi: dialog ichidagi
# ovoz ``unknown_message_fallback`` ga tushadi (``unknown_in_dialog`` eslatma,
# holat SAQLANADI). Shu xulqni saqlash uchun check_update dialog holatini
# tekshiradi va dialog faol bo'lsa UMUMAN mos kelmaydi.
_APPLICATION = None


def set_application(app) -> None:
    """VoiceEntryHandler uchun Application havolasini o'rnatadi.

    ``handlers.register_all_handlers(app)`` boshida chaqiriladi — check_update
    dialog holatini (``ConversationHandler._conversations``) tekshirishi uchun.
    """
    global _APPLICATION
    _APPLICATION = app


def _is_inside_dialog(update) -> bool:
    """Foydalanuvchi biror ConversationHandler dialogida bo'lsa True."""
    app = _APPLICATION
    if app is None:
        return False
    try:
        from handlers import _active_conversation_state

        return _active_conversation_state(app, update) is not None
    except Exception:  # pragma: no cover — himoya: xatoda oqim ochiq qolsin
        return False


class VoiceEntryHandler(MessageHandler):
    """🎙 Voice/audio entry — FAQAT hech qanday dialog faol bo'lmaganda.

    Dialog ICHIDA ``None`` qaytaradi → update keyingi handlerlarga (oxirida
    ``unknown_message_fallback``) o'tadi — dialog holati HECH QACHON
    buzilmaydi (``new_requirements_test`` kontrakti).
    """

    def check_update(self, update):
        base = super().check_update(update)
        if base is None:
            return None
        if _is_inside_dialog(update):
            return None
        return base

#: Natija ekrani post matni chegarasi (Telegram 4096 belgi xavfsiz chegarasi).
_VOICE_RESULT_POST_LIMIT = 3600
#: Transkripsiyalangan matn ko'rinishi (preview) chegarasi.
_VOICE_PREVIEW_LIMIT = 220


# ============================================================
# KLAVIATURALAR
# ============================================================
def _voice_style_keyboard(lang: str) -> InlineKeyboardMarkup:
    """5 uslub tugmasi + [❌ Bekor qilish] — callback ``vp_style:<style>``."""
    buttons = [
        InlineKeyboardButton(
            magic_t(label_key, lang),
            callback_data=cb(VP_STYLE_PREFIX, style),
        )
        for style, (label_key, _desc_key) in MAGIC_STYLE_KEYS.items()
    ]
    return InlineKeyboardMarkup([
        buttons[:3],
        buttons[3:],
        [InlineKeyboardButton(voice_t("vp_btn_cancel", lang), callback_data=VP_CANCEL)],
    ])


def _voice_action_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Natija amallari: baholash / kanalga yuborish / rejalashtirish / uslub."""
    return InlineKeyboardMarkup([
        # 📊 Post Score (Killer Feature #4): transkripsiyadan tayyorlangan postni
        # qayta yozmasdan baholash (``ps_eval:voice``) — kredit yechilmaydi.
        [InlineKeyboardButton(
            post_score_t("ps_btn_eval", lang),
            callback_data=cb(CB_POST_SCORE_EVAL, PS_EVAL_SOURCE),
        )],
        [
            InlineKeyboardButton(
                voice_t("vp_btn_send_channel", lang), callback_data=VP_SEND
            ),
            InlineKeyboardButton(
                voice_t("vp_btn_schedule", lang), callback_data=VP_SCHED
            ),
        ],
        [InlineKeyboardButton(voice_t("vp_btn_restyle", lang), callback_data=VP_RESTYLE)],
    ])


def _voice_channel_keyboard(channels: list, lang: str) -> InlineKeyboardMarkup:
    """Kanal tanlash klaviaturasi (darhol yuborish) + «Barcha kanallarga»."""
    rows = []
    for idx, channel in enumerate(channels):
        title = channel[1] if len(channel) > 1 else channel[0]
        rows.append([InlineKeyboardButton(
            f"📢 {btn_label(title, fallback='Kanal', max_length=28)}",
            callback_data=cb(VP_CHANNEL_PREFIX, idx),
        )])
    rows.append([InlineKeyboardButton(
        voice_t("vp_send_all", lang, count=len(channels)),
        callback_data=VP_SEND_ALL,
    )])
    return InlineKeyboardMarkup(rows)


# ============================================================
# MATN BUILDERLAR
# ============================================================
def _voice_menu_text(raw_text: str, lang: str) -> str:
    """«Ovozingiz matnga o'girildi» ekrani: matn + uslublar jadvali."""
    raw_text = (raw_text or "").strip()
    preview = raw_text[:_VOICE_PREVIEW_LIMIT]
    if len(raw_text) > _VOICE_PREVIEW_LIMIT:
        preview += "…"
    legend = "\n".join(
        f"{magic_t(label_key, lang)} — {magic_t(desc_key, lang)}"
        for _style, (label_key, desc_key) in MAGIC_STYLE_KEYS.items()
    )
    return (
        f"{voice_t('vp_transcribed_header', lang, text=html_escape(preview))}"
        f"\n{legend}"
        f"{voice_t('vp_choose_foot', lang)}"
    )


def _voice_result_text(post_text: str, style: str, lang: str) -> str:
    """Natija ekrani: header + post + footer (post xavfsiz HTML)."""
    style_label = magic_t(
        MAGIC_STYLE_KEYS.get(style, ("mp_style_casual", ""))[0], lang
    )
    post_text = (post_text or "").strip()
    if len(post_text) > _VOICE_RESULT_POST_LIMIT:
        post_text = post_text[:_VOICE_RESULT_POST_LIMIT - 1] + "…"
    return (
        f"{voice_t('vp_result_header', lang, style=style_label)}"
        f"{post_text}"
        f"{voice_t('vp_result_foot', lang)}"
    )


# ============================================================
# YORDAMCHILAR
# ============================================================
_VOICE_SESSION_KEYS = (
    "voice_raw_text", "voice_post_text", "voice_style",
    "voice_channels", "voice_usage_counted", "voice_provider",
)


def _clear_voice_session(context) -> None:
    """Voice sessiyasi kalitlarini tozalaydi (til keshi saqlanadi)."""
    for key in _VOICE_SESSION_KEYS:
        context.user_data.pop(key, None)


async def _voice_refund(user_id: int, is_admin: bool, is_pro: bool,
                        reservation_id=None):
    """Band qilingan AI kvota/kreditini qaytaradi (generatsiya xatosida).

    ``reservation_id`` berilgan bo'lsa — ATOMIK va IDEMPOTENT
    ``refund_ai_request`` ishlaydi. Legacy bronda (ID yo'q) eski
    ``add_user_credit`` + ``refund_ai_usage`` zanjiri saqlanadi.
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


def _extract_voice_media(msg):
    """Xabardan voice/audio/audio-document obyektini ajratib oladi."""
    media = getattr(msg, "voice", None) or getattr(msg, "audio", None)
    if media is None:
        doc = getattr(msg, "document", None)
        if doc is not None and str(getattr(doc, "mime_type", "") or "").startswith("audio/"):
            media = doc
    return media


# ============================================================
# MENU ENTRY: «🧩 Kontent yaratish → 🎙 Ovoz → Post» yo'riqnomasi
# ============================================================
async def voice_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«🎙 Ovoz → Post» bo'limini ochadi: yo'riqnoma + ovozli xabar kutiladi.

    DIQQAT (2-qadam): «Iltimos, g'oyangizni ovozli xabar (1 daqiqa ichida)
    qilib yuboring» talabi shu yerda ko'rsatiladi. Keyingi ovozli xabar
    ``VOICE_AWAIT`` holatidagi ``voice_message_received`` orqali STT oqimiga
    tushadi — ya'ni menyu orqali kirish ham, menyu tashqarisidagi
    action-first kirish ham (``VoiceEntryHandler``) BITTА oqimdan foydalanadi.
    Hech qanday kredit/limit bu bosqichda yechilmaydi.
    """
    msg = getattr(update, "message", None)
    if msg is None:
        return ConversationHandler.END
    lang = get_lang(context)
    _clear_voice_session(context)
    await msg.reply_text(
        voice_t("vp_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return VOICE_AWAIT


# ============================================================
# ENTRY: ovozli xabar / audio qabul qilinadi → STT → uslublar menyusi
# ============================================================
async def voice_message_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ovozli xabarni tutib olish: cheklovlar → STT ($0) → uslublar menyusi.

    MUHIM (resurs-tejamkor): transkripsiya BEPUL — bu funksiya hech qanday
    AI limiti yoki kreditni YECHMAYDI. Kredit faqat uslub tanlanganda
    (:func:`voice_style_callback`) atomik yechiladi.
    """
    msg = update.message
    if msg is None:
        return ConversationHandler.END  # callback-only edit kelgan — oqimni buzmaymiz
    user = update.effective_user
    user_id = user.id if user else 0
    if not user_id:
        return ConversationHandler.END

    media = _extract_voice_media(msg)
    if media is None:
        return ConversationHandler.END

    # Tilni bazadan keshga yuklaymiz (bot restartidan keyin ham to'g'ri til).
    try:
        lang = await ensure_user_lang(context, user_id)
    except Exception:
        lang = get_lang(context)

    is_admin = (user_id in ADMIN_IDS_SET)

    # --- Homiy obuna tekshiruvi (boshqa AI oqimlari bilan bir xil qoida) ---
    try:
        is_sub, unsubs = await check_user_subscribed(context.bot, user_id)
    except Exception:
        is_sub, unsubs = True, []
    if unsubs is None:
        await msg.reply_text(safe_t("sys_busy", lang), parse_mode="HTML")
        return ConversationHandler.END
    if not is_sub:
        await msg.reply_text(
            safe_t("sub_required", lang),
            reply_markup=get_subscription_check_keyboard(unsubs, lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # --- PRO aniqlash (davomiylik limiti uchun; admin = PRO) ---
    is_pro = False
    if not is_admin:
        try:
            is_pro = bool(await db.run_db(db.is_premium, user_id))
        except Exception:
            is_pro = False

    # --- ⛑ 1-CHEKLOV: davomiylik (FREE ≤60s, PRO ≤180s) ---
    ok, limit = check_duration(getattr(media, "duration", 0), is_pro)
    if not ok:
        logger.info("VOICE rad etildi (uzun audio): user=%s dur=%ss limit=%ss",
                    user_id, getattr(media, "duration", 0), limit)
        await msg.reply_text(
            voice_t("vp_too_long", lang, mins=max(1, limit // 60)),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # --- ⛑ 2-CHEKLOV: fayl hajmi (≤20 MB) ---
    if not check_size(getattr(media, "file_size", None)):
        await msg.reply_text(voice_t("vp_too_large", lang), parse_mode="HTML")
        return ConversationHandler.END

    # --- 🎙 STT jarayoni boshlandi (BEPUL — limit yechilmaydi) ---
    await msg.reply_text(voice_t("vp_listening", lang), parse_mode="HTML")

    # --- Telegramdan audio faylni yuklab olish (.ogg/.oga/.mp3...) ---
    try:
        tg_file = await context.bot.get_file(media.file_id)
        data = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.warning("Voice faylni yuklab olishda xato (user=%s): %s", user_id, e)
        await msg.reply_text(voice_t("vp_transcribe_error", lang), parse_mode="HTML")
        return ConversationHandler.END

    if not check_size(len(data)):
        await msg.reply_text(voice_t("vp_too_large", lang), parse_mode="HTML")
        return ConversationHandler.END

    filename = (
        getattr(media, "file_name", None)
        or ("voice.ogg" if getattr(msg, "voice", None) else "audio.mp3")
    )

    # --- STT: Groq Whisper Large v3 → zaxira Gemini ($0, limit YO'Q) ---
    try:
        result = await transcribe_voice(data, filename)
    except Exception as e:  # noqa: BLE001 — hech qachon yiqilmaydi
        logger.error("Transkripsiya istisnosi (user=%s): %s", user_id, e)
        result = {"error": "stt_unavailable"}

    error = (result or {}).get("error")
    if error == "too_large":
        await msg.reply_text(voice_t("vp_too_large", lang), parse_mode="HTML")
        return ConversationHandler.END
    if error == "empty_text":
        await msg.reply_text(voice_t("vp_empty_text", lang), parse_mode="HTML")
        return ConversationHandler.END
    if error or not (result or {}).get("text", "").strip():
        logger.warning("STT muvaffaqiyatsiz (user=%s): %s", user_id, error)
        await msg.reply_text(voice_t("vp_transcribe_error", lang), parse_mode="HTML")
        return ConversationHandler.END

    text = (result.get("text") or "").strip()
    if len(text) < 2:
        # Tushunarsiz/jitillagan audio — hech qanday limit yechilmagan.
        await msg.reply_text(voice_t("vp_empty_text", lang), parse_mode="HTML")
        return ConversationHandler.END
    if len(text) > MAGIC_POST_MAX_MATERIAL_CHARS:
        text = text[:MAGIC_POST_MAX_MATERIAL_CHARS]

    # --- ✅ Muvaffaqiyat: xom matn saqlanadi → uslublar menyusi ---
    _clear_voice_session(context)
    context.user_data["voice_raw_text"] = text
    context.user_data["voice_provider"] = result.get("provider", "")

    await msg.reply_text(
        _voice_menu_text(text, lang),
        reply_markup=_voice_style_keyboard(lang),
        parse_mode="HTML",
    )
    return VOICE_STYLE_SELECT


# ============================================================
# VOICE_STYLE_SELECT: uslub tanlandi → 1 kredit ATOMIK → AI generatsiya
# ============================================================
async def voice_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uslub tugmasi: FAQAT SHU ERDA 1 ta AI krediti atomik yechiladi.

    Preflight zanjiri (magic post bilan bir xil qoidalar):
      rate-limit → kunlik limit → DB kvota (atomik bron) → 1 ball rezervi.
    Generatsiya xato/timeout bo'lsa — to'liq refund.
    """
    query = update.callback_query
    await query.answer()  # SPEKS: darhol answer — tugma "yopishib" qolmaydi
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    style = normalize_magic_style((query.data or "").split(":", 1)[-1])
    raw_text = (context.user_data.get("voice_raw_text") or "").strip()
    if not raw_text:
        await _safe_edit(query, voice_t("vp_stale", lang), None)
        return VOICE_STYLE_SELECT

    # --- Preflight: rate-limit → kunlik limit → DB kvota → ball rezervi ---
    if not is_admin and check_ai_rate_limit(user_id, max_per_minute=4):
        try:
            await query.answer(safe_t("ai_rate_limit_alert", lang), show_alert=True)
        except Exception:
            pass
        return VOICE_STYLE_SELECT

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
        return VOICE_STYLE_SELECT

    # 🔒 PHASE 2 / 1-QADAM: kunlik kvota YOKI kredit BITTA atomik
    # tranzaksiyada bron qilinadi (qator qulfi + credits_ledger auditi).
    # Avvalgi ikki qadam alohida tranzaksiyalar edi → race condition va
    # yarim bron xavfi; DB xatosida esa oqim DAVOM ETARDI (fail-open).
    # Endi qat'iy FAIL-CLOSED.
    if not is_admin and not is_pro:
        reservation = await reserve_for_flow(
            db, context, user_id, "voice_post", "voice", 1)
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
            return VOICE_STYLE_SELECT

    context.user_data["voice_style"] = style
    style_label = magic_t(MAGIC_STYLE_KEYS[style][0], lang)
    await _safe_edit(query, voice_t("vp_generating", lang, style=style_label), None)

    # --- ✨ AI generatsiya (Magic Post prompti: sarlavha, CTA, emoji, hashtag) ---
    try:
        result = await generate_magic_post(raw_text, style, lang=lang, is_pro=is_pro)
    except Exception as e:  # noqa: BLE001 — hech qachon yiqilmaydi
        logger.error("Voice→Post generation error: %s", e)
        result = {"error": "exception"}

    if not isinstance(result, dict) or result.get("error") or not (result.get("post_text") or "").strip():
        logger.warning("Voice→Post AI xatosi (style=%s, lang=%s): %s",
                       style, lang, (result or {}).get("error"))
        # ♻️ Refund: ball va kunlik kvota qaytariladi.
        await _voice_refund(
            user_id, is_admin, is_pro,
            take_reservation_id(context, "voice"),
        )
        await _safe_edit(
            query,
            voice_t("vp_error", lang),
            _voice_style_keyboard(lang),
        )
        return VOICE_STYLE_SELECT

    post_text = (result.get("post_text") or "").strip()
    context.user_data["voice_post_text"] = post_text
    context.user_data["voice_style"] = result.get("style", style)
    context.user_data["voice_usage_counted"] = False

    await _safe_edit(query, _voice_result_text(post_text, result.get("style", style), lang),
                     _voice_action_keyboard(lang))
    return VOICE_RESULT


# ============================================================
# BEKOR QILISH: hech qanday AI limiti/kredit yechilmagan holda tugaydi
# ============================================================
async def voice_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[❌ Bekor qilish]: jarayon to'xtaydi, limit/kredit TIYILMAYDI."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    _clear_voice_session(context)
    try:
        await query.edit_message_text(voice_t("vp_cancel_done", lang), parse_mode="HTML")
    except Exception:
        try:
            await query.message.reply_text(
                voice_t("vp_cancel_done", lang), parse_mode="HTML"
            )
        except Exception:
            pass
    # Sessiya yopildi — yangi ovoz entry point orqali qaytadan boshlanadi.
    return ConversationHandler.END


# ============================================================
# YUBORISH: kanalga darhol jo'natish
# ============================================================
async def _voice_finish_send(query, context, targets: list) -> int:
    """Tanlangan kanallarga yuboradi, natija xabarini chiqaradi, sessiyani yopadi.

    Returns: muvaffaqiyatli yuborilgan kanallar soni.
    """
    user_id = query.from_user.id
    lang = get_lang(context)
    is_admin = (user_id in ADMIN_IDS_SET)
    post_text = context.user_data.get("voice_post_text") or ""

    sent, sent_names = 0, []
    for channel in targets:
        ch_id = channel[0]
        ch_title = channel[1] if len(channel) > 1 else str(ch_id)
        if await _magic_deliver_one(context.bot, ch_id, post_text):
            sent += 1
            sent_names.append(html_escape(str(ch_title or ch_id)))

    if sent > 0:
        # AI ball "sarflandi" — birinchi muvaffaqiyatli yuborishda (free uchun).
        # (Kvota allaqachon uslub tanlashda atomik bron qilingan — no-op.)
        if not is_admin and not context.user_data.get("voice_usage_counted"):
            context.user_data["voice_usage_counted"] = True
            # 🔒 PHASE 2 / 1-qadam: atomik bron sanagichni ALLAQACHON
            # oshirgan — double-count bo'lmasligi uchun atomik bronda
            # increment chaqirilmaydi (legacy bronda eski xatti-harakat).
            if not reservation_source(context, "voice"):
                try:
                    await db.run_db(db.increment_ai_usage, user_id)
                except Exception:
                    pass
        try:
            await query.edit_message_text(
                voice_t(
                    "vp_sent_ok", lang,
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
            voice_t("vp_sent_fail", lang),
            reply_markup=_voice_action_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return 0


async def voice_send_now_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📢 Kanalga yuborish]: bitta kanal bo'lsa darhol, ko'p bo'lsa tanlov."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = context.user_data.get("voice_post_text") or ""
    if not post_text:
        try:
            await query.answer(voice_t("vp_stale", lang), show_alert=True)
        except Exception:
            pass
        return VOICE_RESULT

    try:
        channels = await db.run_db(db.get_user_channels, query.from_user.id) or []
    except Exception:
        channels = []
    channels = [ch for ch in channels if ch]

    if not channels:
        try:
            await query.answer(voice_t("vp_no_channels", lang), show_alert=True)
        except Exception:
            pass
        return VOICE_RESULT

    context.user_data["voice_channels"] = channels
    if len(channels) == 1:
        sent = await _voice_finish_send(query, context, channels)
        # Yuborish muvaffaqiyatsiz bo'lsa sessiya ochiq qoladi (qayta urinish).
        return VOICE_RESULT if sent <= 0 else ConversationHandler.END

    await _safe_edit(query, voice_t("vp_send_choose", lang),
                     _voice_channel_keyboard(channels, lang))
    return VOICE_SEND_CHOOSE


async def voice_channel_picked_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlandi (yoki «Barcha kanallarga») — yuborish bajariladi."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    channels = context.user_data.get("voice_channels") or []
    post_text = context.user_data.get("voice_post_text") or ""
    if not post_text or not channels:
        try:
            await query.answer(voice_t("vp_stale", get_lang(context)), show_alert=True)
        except Exception:
            pass
        return VOICE_SEND_CHOOSE

    if data == VP_SEND_ALL:
        targets = list(channels)
    else:
        try:
            idx = int(data.split(":", 1)[-1])
            targets = [channels[idx]]
        except (ValueError, IndexError):
            return VOICE_SEND_CHOOSE

    sent = await _voice_finish_send(query, context, targets)
    # Yuborish muvaffaqiyatsiz bo'lsa — tanlov menyusi ochiq qoladi.
    return VOICE_RESULT if sent <= 0 else VOICE_RESULT


# ============================================================
# REJALASHTIRISH: mavjud scheduler oqimiga uzatish (AI_GET_TIME)
# ============================================================
async def voice_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📅 Rejalashtirish]: postni AI_GET_TIME → AI_CONFIRM oqimiga uzatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    post_text = context.user_data.get("voice_post_text") or ""
    if not post_text:
        try:
            await query.answer(voice_t("vp_stale", lang), show_alert=True)
        except Exception:
            pass
        return VOICE_RESULT

    # Scheduler oqimi (ai_time_received/ai_confirm_callback) kutgan kalitlar:
    context.user_data["ai_generated_post"] = post_text
    context.user_data["ai_file_id"] = None
    context.user_data["ai_post_type"] = "text"
    context.user_data.pop("ai_scheduled_time", None)
    context.user_data.pop("ai_target_all", None)
    _clear_voice_session(context)

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    await _show_time_prompt(query.message, post_text, None, "text", lang)
    return AI_GET_TIME


# ============================================================
# BOSHQA USLUB: ovozni qayta yubormasdan qayta generatsiya
# ============================================================
async def voice_restyle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[🔄 Boshqa uslub]: saqlangan matn bilan uslublar menyusini qaytaradi.

    Yangi transkripsiya TALAB QILINMAYDI — kredit faqat yangi uslub
    tanlanib generatsiya bajarilganda yechiladi.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)

    raw_text = (context.user_data.get("voice_raw_text") or "").strip()
    if not raw_text:
        await _safe_edit(query, voice_t("vp_stale", lang), None)
        return VOICE_STYLE_SELECT

    context.user_data.pop("voice_post_text", None)
    await _safe_edit(query, voice_t("vp_restyle_hint", lang),
                     _voice_style_keyboard(lang))
    return VOICE_STYLE_SELECT


# ============================================================
# STALE TUGMALAR (conversation tashqarisida bosilgan eski tugmalar)
# ============================================================
async def voice_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """``^vp_`` tugmalari sessiya tugagach bosilsa — jim toast ko'rsatadi."""
    query = update.callback_query
    try:
        lang = get_lang(context)
        await query.answer(voice_t("vp_stale", lang), show_alert=True)
    except Exception:
        try:
            await query.answer()
        except Exception:
            pass
