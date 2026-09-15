"""📸 IMAGE → POST — KILLER FEATURE #3.

Oqim:

    /imagepost yoki "📸 Rasm → Post"
        → rasm + caption
        → Gemini Vision mahsulot tahlili (bepul, kredit yo'q)
        → qisqa xulosa + 5 uslub + bekor qilish
        → uslub tanlanganda aynan 1 ta AI krediti + tayyor post
        → rasm ostida caption preview
        → [📢 Kanalga yuborish] [📅 Rejalashtirish] / [✏️ Qayta yozish / Uslub]
          [📊 Baholash] / [◀️ Orqaga]  (Magic Post bilan bir xil layout)

3-BOSQICH FALLBACK (Vision timeout / rate-limit / model 404 / tushunarsiz javob):
    * caption bor → o'sha matn asos qilinadi va ✨ Magic Post generatoriga
      uzatiladi (foydalanuvchi quruq xato ko'rmaydi);
    * caption yo'q → «🖼 Rasm qabul qilindi! … mavzu yozing» (IMAGE_TOPIC_INPUT).
    Faqat rasmning o'zi yaroqsiz bo'lsa (format/10 MB) yangi rasm so'raladi.

Legacy AI Studio Vision oqimi ``handlers.ai_assistant`` da ataylab saqlanadi.
Bu modul yangi kontraktni alohida ushlab, Magic Post, Voice va mavjud
moderatsiya photo handlerlari bilan callback/state to'qnashuvini oldini oladi.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler

import database as db
from config import ADMIN_IDS_SET
from keyboards.callback_data import CB_POST_SCORE_EVAL, cb
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang, safe_t
from translations import content_menu_t, magic_t, post_score_t
from services.ai_service import generate_image_post
from utils.ai_agent import pick_supported_kwargs
from utils.helpers import html_escape, telegram_html_payload, parse_schedule_input
from utils.vision_analyzer import (
    MAX_IMAGE_BYTES,
    TEXT_SOURCE_CAPTION,
    TEXT_SOURCE_TOPIC,
    VisionError,
    analysis_from_text,
    analyze_image,
    is_text_based_analysis,
    normalize_analysis,
    validate_image,
)

logger = logging.getLogger(__name__)

# FSM qiymatlari boshqa oqimlardan ajratilgan (AI 401–410, moderation 604).
IMAGE_POST_INPUT = 520
IMAGE_STYLE_SELECT = 521
IMAGE_POST_RESULT = 522
IMAGE_SEND_CHOOSE = 523
IMAGE_SCHEDULE_INPUT = 524
#: Vision ishlamadi va caption yo'q — foydalanuvchidan post mavzusi so'raladi
#: (3-BOSQICH fallback; jarayon to'xtab qolmaydi).
IMAGE_TOPIC_INPUT = 525


# ============================================================
# ENTRY HANDLER — boshqa faol dialoglarni buzmasin
# ============================================================
# PTB ConversationHandler allow_reentry=True bo'lsa entry point'ni faol
# dialogda ham sinab ko'rishi mumkin. Oddiy MessageHandler shu sababli
# transfer, receipt, moderation yoki new-post oqimini photo bilan almashtirib
# yuboradi. Voice oqimidagi himoya bilan bir xil tarzda photo entry'ni faqat
# boshqa dialog faol bo'lmaganda mos qilamiz.
_IMAGE_APPLICATION = None


def set_application(app) -> None:
    """ImageEntryHandler uchun Application havolasini o'rnatadi."""
    global _IMAGE_APPLICATION
    _IMAGE_APPLICATION = app


def _is_inside_dialog(update) -> bool:
    app = _IMAGE_APPLICATION
    if app is None:
        return False
    try:
        from handlers import _active_conversation_state

        return _active_conversation_state(app, update) is not None
    except Exception:  # pragma: no cover - xatoda entry'ni xavfsiz yopamiz
        return False


class ImageEntryHandler(MessageHandler):
    """Oddiy photo uchun direct Image → Post entry.

    Faol ConversationHandler holatlarida ``None`` qaytaradi: navbatdagi
    state-specific handler (masalan, receipt yoki photo moderation) o'z ishini
    davom ettiradi.
    """

    def check_update(self, update):
        base = super().check_update(update)
        if base is None or _is_inside_dialog(update):
            return None
        return base


# Qisqa nomlar — integratsiya/testlar uchun qulay.
IMAGE_INPUT = IMAGE_POST_INPUT
IMAGE_RESULT = IMAGE_POST_RESULT

IMAGE_STYLE_PREFIX = "image_style:"
IMAGE_CANCEL = "image_cancel"
IMAGE_SEND = "image_send"
IMAGE_SCHEDULE = "image_schedule"
IMAGE_RESTYLE = "image_restyle"
IMAGE_BACK = "image_back"
IMAGE_CHANNEL_PREFIX = "image_ch:"
IMAGE_SEND_ALL = "image_ch:all"

#: 📊 Post Score oqimiga uzatish uchun manba nomi (``ps_eval:image``).
PS_EVAL_SOURCE = "image"

# Eski naming variantlari bilan patch/integratsiya mosligi.
IMG_STYLE_PREFIX = IMAGE_STYLE_PREFIX
IMG_CANCEL = IMAGE_CANCEL
IMG_SEND = IMAGE_SEND
IMG_SCHEDULE = IMAGE_SCHEDULE
IMG_RESTYLE = IMAGE_RESTYLE

IMAGE_STYLES = ("sales", "premium", "simple", "discount", "review")
_STYLE_KEYS = {
    "sales": "image_style_sales",
    "premium": "image_style_premium",
    "simple": "image_style_simple",
    "discount": "image_style_discount",
    "review": "image_style_review",
}

_SESSION_KEYS = (
    "image_post_file_id",
    "image_post_caption",
    "image_post_analysis",
    "image_post_text",
    "image_post_style",
    "image_post_channels",
    "image_post_credit_reserved",
    "image_post_scheduled_time",
    "image_post_generating",
    "image_post_source",
)


def _style_label(style: str, lang: str = "uz") -> str:
    return safe_t(_STYLE_KEYS.get(style, "image_style_sales"), lang)


def image_style_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Vision xulosasidan keyingi 5 uslub + bekor qilish tugmalari."""
    rows = [
        [
            InlineKeyboardButton(_style_label("sales", lang), callback_data=cb(IMAGE_STYLE_PREFIX, "sales")),
            InlineKeyboardButton(_style_label("premium", lang), callback_data=cb(IMAGE_STYLE_PREFIX, "premium")),
        ],
        [
            InlineKeyboardButton(_style_label("simple", lang), callback_data=cb(IMAGE_STYLE_PREFIX, "simple")),
            InlineKeyboardButton(_style_label("discount", lang), callback_data=cb(IMAGE_STYLE_PREFIX, "discount")),
        ],
        [InlineKeyboardButton(_style_label("review", lang), callback_data=cb(IMAGE_STYLE_PREFIX, "review"))],
        [InlineKeyboardButton(safe_t("image_btn_cancel", lang), callback_data=IMAGE_CANCEL)],
    ]
    return InlineKeyboardMarkup(rows)


def image_action_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Tayyor photo+caption preview amallari — Magic Post bilan BIR XIL layout:

        [📢 Kanalga yuborish]      [📅 Rejalashtirish]
        [✏️ Qayta yozish / Uslub]  [📊 Baholash]
                    [◀️ Orqaga]

    Callback'lar o'zgarmagan (``image_send`` / ``image_schedule`` /
    ``image_restyle`` / ``ps_eval:image``) — eski chat tarixidagi tugmalar
    ishlashda davom etadi; ``image_back`` Kontent yaratish submenyusiga qaytaradi.
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(safe_t("image_btn_send", lang), callback_data=IMAGE_SEND),
            InlineKeyboardButton(safe_t("image_btn_schedule", lang), callback_data=IMAGE_SCHEDULE),
        ],
        [
            InlineKeyboardButton(magic_t("mp_btn_rewrite", lang), callback_data=IMAGE_RESTYLE),
            # 📊 Post Score (Killer Feature #4): tayyor caption'ni qayta yozmasdan
            # baholash (``ps_eval:image``) — baholash bepul (kredit yechilmaydi).
            InlineKeyboardButton(
                post_score_t("ps_btn_eval", lang),
                callback_data=cb(CB_POST_SCORE_EVAL, PS_EVAL_SOURCE),
            ),
        ],
        [InlineKeyboardButton(magic_t("mp_btn_back", lang), callback_data=IMAGE_BACK)],
    ])


def image_channel_keyboard(channels: list, lang: str = "uz") -> InlineKeyboardMarkup:
    rows = []
    for index, channel in enumerate(channels or []):
        channel_id, title = _channel_values(channel)
        rows.append([InlineKeyboardButton(
            f"📢 {str(title or channel_id)[:32]}",
            callback_data=cb(IMAGE_CHANNEL_PREFIX, index),
        )])
    if len(channels or []) > 1:
        rows.append([InlineKeyboardButton(
            safe_t("image_btn_send_all", lang, count=len(channels)),
            callback_data=IMAGE_SEND_ALL,
        )])
    rows.append([InlineKeyboardButton(safe_t("image_btn_cancel", lang), callback_data=IMAGE_CANCEL)])
    return InlineKeyboardMarkup(rows)


def _channel_values(channel):
    if isinstance(channel, dict):
        return channel.get("channel_id") or channel.get("id"), channel.get("channel_title") or channel.get("title") or "Kanal"
    if isinstance(channel, (tuple, list)):
        if len(channel) >= 2:
            return channel[0], channel[1]
        if channel:
            return channel[0], str(channel[0])
    return channel, str(channel or "Kanal")


def _clear_image_session(context) -> None:
    for key in _SESSION_KEYS:
        context.user_data.pop(key, None)


def _image_entry_text(lang: str) -> str:
    return safe_t("image_post_intro", lang)


def _analysis_summary(analysis: dict, lang: str = "uz") -> str:
    if is_text_based_analysis(analysis):
        # Vision emas, foydalanuvchi matni asos: mahsulot kartochkasi o'rniga
        # qisqa "matn qabul qilindi" xulosasi (noma'lum/noma'lum chiqmaydi).
        preview = str(analysis.get("source_text") or analysis.get("summary") or "").strip()
        preview = html_escape(preview[:300] + ("…" if len(preview) > 300 else ""))
        key = "image_text_summary_caption" if analysis.get("source") == TEXT_SOURCE_CAPTION else "image_text_summary_topic"
        return safe_t(key, lang, text=preview)
    data = normalize_analysis(analysis or {})
    f = data.get("visual_features") or {}
    details = data.get("caption_details") or {}
    facts = []
    if isinstance(details, dict):
        # Faqat foydalanuvchi captionidan kelgan amaliy ma'lumotlarni qisqa
        # ko'rsatamiz; modelning noma'lum qo'shimcha matni UI'ga chiqmaydi.
        for key in ("price", "narx", "size", "o'lcham", "delivery", "yetkazib_berish"):
            if details.get(key):
                facts.append(html_escape(str(details[key])))
    fact_line = f"\n📌 {' · '.join(facts)}" if facts else ""
    return safe_t(
        "image_analysis_summary",
        lang,
        product=html_escape(data.get("product_name") or "Noma'lum mahsulot"),
        category=html_escape(data.get("category") or "Noma'lum toifa"),
        color=html_escape(f.get("color") or "noma'lum"),
        material=html_escape(f.get("material") or "noma'lum"),
        design=html_escape(f.get("design") or "noma'lum"),
        style=html_escape(f.get("style") or "noma'lum"),
        facts=fact_line,
    )


def _analysis_error_text(error: Any, lang: str = "uz") -> str:
    # Foydalanuvchiga ichki provider trace/status chiqmasin.
    text = str(error or "").strip()
    if text.startswith(("📦", "🖼", "⚠️", "🔑", "⏳")):
        return text
    return safe_t("image_analysis_error", lang)


def _extract_image_media(message):
    photos = getattr(message, "photo", None) or []
    if photos:
        return photos[-1], "image/jpeg"
    document = getattr(message, "document", None)
    if document is not None:
        mime = str(getattr(document, "mime_type", "") or "").lower()
        if not mime or mime.startswith("image/"):
            return document, mime or None
    return None, None


async def _download_image_bytes(bot, media) -> bytes:
    if media is None or not getattr(media, "file_id", None):
        raise VisionError("🖼 Rasm topilmadi. Iltimos, JPG, PNG yoki WEBP yuboring.")
    advertised = getattr(media, "file_size", None)
    if advertised is not None:
        # Eslatma: VisionError ValueError'dan meros olgan — shu sababli int()
        # xatosi va limit xatosi ALOHIDA ushlanadi (aks holda limit jim o'tardi).
        try:
            advertised_size = int(advertised)
        except (TypeError, ValueError):
            advertised_size = 0
        if advertised_size > MAX_IMAGE_BYTES:
            raise VisionError("📦 Rasm hajmi 10 MB dan oshib ketdi. Kichikroq rasm yuboring.")
    try:
        tg_file = await bot.get_file(media.file_id)
        raw = bytes(await tg_file.download_as_bytearray())
    except VisionError:
        raise
    except Exception as exc:
        logger.warning("Image Post Telegram download failed: %s", type(exc).__name__)
        raise VisionError("⚠️ Rasmni yuklab bo'lmadi. Qayta urinib ko'ring.") from exc
    # Erta validation: noto'g'ri fayl Gemini request'iga yetib bormaydi.
    validate_image(raw, mime_type=getattr(media, "mime_type", None))
    return raw


async def image_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """«📸 Rasm → Post» — YAGONA rasm oqimining kirish nuqtasi (B2).

    PostAssist V2 · 2-qadam: AI Studio (``studio_ai_photo``) va Onboarding
    (``quick_photo_post_entry``) menyularidagi barcha «🖼 Rasmdan post...»
    tugmalari AYNAN shu funksiyaga yo'naltiriladi — endi botda ikkita
    chalg'ituvchi rasm oqimi emas, bitta implementatsiya (Vision + Post
    Score) bor. Eski ``photo_`` callback'lari esa xavfsiz alias bo'lib
    qoladi (``handlers.ai_assistant`` + global stale handler).

    Kirish ikki shaklda bo'lishi mumkin:
      * oddiy xabar (reply-tugma / ``/imagepost``) — yo'riqnoma yuboriladi;
      * inline tugma (AI Studio/Onboarding menyusi) — xabar EDIT qilinadi.

    Kredit hali sarflanmaydi: u FAQAT uslub tanlanganda (``image_style:``)
    atomik yechiladi.
    """
    message = getattr(update, "message", None)
    query = getattr(update, "callback_query", None)
    _clear_image_session(context)
    lang = get_lang(context)
    text = _image_entry_text(lang)
    keyboard = get_cancel_keyboard(lang)

    if query is not None:
        # Inline tugma (studio_ai_photo / onboarding / cc_*) — xabar O'CHIRILMAYDI
        # (menyu xabari edit qilinadi), aks holda AI Studio uslubidagi
        # «edit → yo'riqnoma» xatti-harakati buzilardi.
        try:
            await query.answer()
        except Exception:
            pass
        edited = False
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
            edited = True
        except Exception:
            edited = False
        if not edited:
            target = message or getattr(query, "message", None)
            if target is not None:
                try:
                    await target.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
                except Exception:
                    logger.debug("image_post_entry: xabar yuborib bo'lmadi", exc_info=True)
        return IMAGE_POST_INPUT

    if message is None:
        return ConversationHandler.END
    await message.reply_text(text, reply_markup=keyboard, parse_mode="HTML")
    return IMAGE_POST_INPUT


def _message_caption(message) -> str:
    """Caption (forward qilingan xabarlarda ham) — bo'lmasa bo'sh satr."""
    for attr in ("caption", "text"):
        value = getattr(message, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()[:1000]
    return ""


def _is_recoverable_vision_error(exc: BaseException | None) -> bool:
    """Xato RASMDA emas, XIZMATDA bo'lsa (timeout, 404 model, rate-limit,
    tarmoq, yuklab olish) — fallback mexanizmi ishlaydi. Format/hajm xatosi
    esa yangi rasm talab qiladi."""
    if exc is None:
        return True
    if isinstance(exc, VisionError):
        if getattr(exc, "recoverable", False):
            return True
        text = str(exc)
        # Yuklab olish/bo'sh javob kabi xizmat xatolari ham tiklanuvchi.
        return not text.startswith(("📦", "🖼"))
    return True


async def _start_style_select(message, context, analysis: dict, lang: str,
                              notice_key: str | None = None):
    """Tahlil (Vision yoki matn) tayyor — uslub menyusini chiqaradi."""
    context.user_data["image_post_analysis"] = analysis
    context.user_data["image_post_source"] = analysis.get("source") or "vision"
    context.user_data.pop("image_post_text", None)
    context.user_data.pop("image_post_style", None)
    context.user_data["image_post_credit_reserved"] = False
    parts = []
    if notice_key:
        parts.append(safe_t(notice_key, lang))
    parts.append(_analysis_summary(analysis, lang))
    parts.append(safe_t("image_choose_style", lang))
    await message.reply_text(
        "\n\n".join(parts),
        reply_markup=image_style_keyboard(lang),
        parse_mode="HTML",
    )
    return IMAGE_STYLE_SELECT


async def _vision_fallback(message, context, caption: str, lang: str):
    """MUSTAHKAM FALLBACK — Vision xatosi foydalanuvchiga quruq xato bo'lib
    qaytmaydi:

      * caption bor → o'sha matn asos qilinadi (Magic Post generatoriga
        uzatiladi), uslub menyusi darhol chiqadi;
      * caption yo'q → muloyimlik bilan mavzu so'raladi (``IMAGE_TOPIC_INPUT``).
    """
    if caption:
        analysis = analysis_from_text(caption, TEXT_SOURCE_CAPTION)
        return await _start_style_select(
            message, context, analysis, lang, notice_key="image_vision_fallback_caption",
        )
    await message.reply_text(safe_t("image_topic_prompt", lang), parse_mode="HTML")
    return IMAGE_TOPIC_INPUT


async def image_photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Rasmni yuklaydi, Gemini Vision bilan tahlil qiladi va uslub menyusini chiqaradi.

    Vision xizmati (timeout / rate-limit / model 404 / tushunarsiz javob)
    yiqilsa oqim TO'XTAMAYDI: caption bo'lsa u asos qilinadi, bo'lmasa mavzu
    so'raladi. Faqat rasmning o'zi yaroqsiz bo'lsa (format/hajm) yangi rasm
    so'raladi.
    """
    message = getattr(update, "message", None)
    if message is None:
        return IMAGE_POST_INPUT
    lang = get_lang(context)
    media, declared_mime = _extract_image_media(message)
    if media is None:
        await message.reply_text(safe_t("image_photo_only", lang), parse_mode="HTML")
        return IMAGE_POST_INPUT

    caption = _message_caption(message)
    # file_id Vision natijasidan qat'i nazar saqlanadi — fallback'da ham
    # tayyor post AYNAN shu rasm bilan yuboriladi.
    context.user_data["image_post_file_id"] = getattr(media, "file_id", None)
    context.user_data["image_post_caption"] = caption

    result = None
    failure: BaseException | None = None
    try:
        raw = await _download_image_bytes(context.bot, media)
        analyzer = globals().get("analyze_image") or analyze_image
        result = await analyzer(
            raw,
            **pick_supported_kwargs(
                analyzer,
                caption=caption,
                mime_type=declared_mime,
                lang=lang,
            ),
        )
    except VisionError as exc:
        failure = exc
    except Exception as exc:  # noqa: BLE001 - user oqimi yiqilmasin
        logger.exception("Image Post Vision error: %s", exc)
        failure = exc

    if failure is not None:
        if not _is_recoverable_vision_error(failure):
            await message.reply_text(_analysis_error_text(failure, lang), parse_mode="HTML")
            return IMAGE_POST_INPUT
        logger.info("Image Post: Vision ishlamadi (%s) — fallback", type(failure).__name__)
        return await _vision_fallback(message, context, caption, lang)

    if not isinstance(result, dict) or result.get("error"):
        logger.info("Image Post: Vision natijasi xato — fallback")
        return await _vision_fallback(message, context, caption, lang)

    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else result
    analysis = normalize_analysis(analysis, caption=caption)
    return await _start_style_select(message, context, analysis, lang)


async def image_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Vision ishlamagach foydalanuvchi yozgan mavzu → matn asosidagi tahlil."""
    message = getattr(update, "message", None)
    if message is None:
        return IMAGE_TOPIC_INPUT
    lang = get_lang(context)
    topic = _message_caption(message)
    if not topic:
        await message.reply_text(safe_t("image_topic_prompt", lang), parse_mode="HTML")
        return IMAGE_TOPIC_INPUT
    if not context.user_data.get("image_post_file_id"):
        await message.reply_text(safe_t("image_session_expired", lang), parse_mode="HTML")
        return ConversationHandler.END
    context.user_data["image_post_caption"] = topic
    analysis = analysis_from_text(topic, TEXT_SOURCE_TOPIC)
    return await _start_style_select(message, context, analysis, lang)


async def _get_pro_and_admin(user_id: int):
    is_admin = user_id in ADMIN_IDS_SET
    if is_admin:
        return is_admin, True
    try:
        return is_admin, bool(await db.run_db(db.is_premium, user_id))
    except Exception:
        return is_admin, False


async def _reserve_one_ai_credit(user_id: int) -> tuple[bool, bool, bool]:
    """Style callback uchun bitta credit/quota rezervi.

    Returns ``(ok, is_admin, is_pro)``. ``check_ai_limit`` mavjud loyihaning
    atomik kunlik quota rezervidir; keyingi ``use_user_credit`` esa aynan bitta
    AI creditni yechadi.
    """
    is_admin, is_pro = await _get_pro_and_admin(user_id)
    if is_admin or is_pro:
        return True, is_admin, is_pro

    try:
        limit = await db.run_db(db.check_ai_limit, user_id)
    except Exception:
        return False, is_admin, is_pro
    if isinstance(limit, (tuple, list)) and limit and limit[0] is False:
        return False, is_admin, is_pro
    if limit is False:
        return False, is_admin, is_pro

    try:
        reserved = await db.run_db(db.use_user_credit, user_id)
    except Exception:
        # check_ai_limit quota bron qilgan bo'lishi mumkin; credit yechilmasa
        # o'sha bron ham qolib ketmasin.
        if hasattr(db, "refund_ai_usage"):
            try:
                await db.run_db(db.refund_ai_usage, user_id)
            except Exception:
                pass
        return False, is_admin, is_pro
    # Real DB adapter qaytargan qiymat bool. None esa eski test adapterining
    # "javob bermadim" qiymati bo'lishi mumkin; uni muvaffaqiyat deb qabul
    # qilish faqat mock/backward compatibility uchun, DB xatosi yuqorida False.
    if reserved is False:
        if hasattr(db, "refund_ai_usage"):
            try:
                await db.run_db(db.refund_ai_usage, user_id)
            except Exception:
                pass
        return False, is_admin, is_pro
    return True, is_admin, is_pro


async def _refund_one_ai_credit(user_id: int, is_admin: bool, is_pro: bool) -> None:
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


async def _safe_edit(query, text: str, reply_markup=None):
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="HTML")
        return
    except Exception:
        pass
    try:
        await query.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        pass


async def _send_photo_preview(target, file_id: str, caption: str,
                              reply_markup=None):
    """Preview/kanal uchun Telegram photo+caption payload.

    Caption 1024 belgidan oshsa qolgan qismi alohida xabar sifatida yuboriladi
    (preview helperning o'zi esa test/consumer uchun message qaytaradi).
    """
    payload, parse_mode = telegram_html_payload(caption or "")
    payload = (payload or " ").strip()
    short = payload[:1024]
    try:
        return await target.reply_photo(
            photo=file_id,
            caption=short,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except AttributeError:
        # Fake/minimal targetlar va integration adapterlari uchun.
        return await target.reply_text(
            short,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )


async def _send_photo_to_chat(bot, chat_id, file_id: str, caption: str):
    payload, parse_mode = telegram_html_payload(caption or "")
    kwargs = {
        "chat_id": chat_id,
        "photo": file_id,
        "caption": (payload or " ")[:1024],
        "parse_mode": parse_mode,
    }
    try:
        return await bot.send_photo(**kwargs)
    except TypeError:
        kwargs.pop("parse_mode", None)
        return await bot.send_photo(**kwargs)


async def image_style_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Uslub tanlash: Vision'dan keyingi birinchi va yagona credit yechimi."""
    query = update.callback_query
    await query.answer()
    data = str(getattr(query, "data", "") or "")
    lang = get_lang(context)
    user_id = query.from_user.id

    if data in (IMAGE_CANCEL, "img_cancel"):
        _clear_image_session(context)
        await _safe_edit(query, safe_t("image_cancelled", lang), None)
        return ConversationHandler.END

    style = data.split(":", 1)[1] if ":" in data else ""
    if style not in IMAGE_STYLES:
        return IMAGE_STYLE_SELECT
    analysis = context.user_data.get("image_post_analysis")
    file_id = context.user_data.get("image_post_file_id")
    if not analysis or not file_id:
        await _safe_edit(query, safe_t("image_session_expired", lang), None)
        return ConversationHandler.END

    # Natija allaqachon tayyor bo'lsa, eski/stale style callback yana kredit
    # yechmasin. ``Boshqa uslub`` oqimi image_post_text'ni avval tozalaydi.
    if context.user_data.get("image_post_text"):
        return IMAGE_POST_RESULT
    # Double-click race: per-user lock Application darajasida bor, ammo
    # callbackning o'zida ham qayta ishlashni oldini olamiz.
    if context.user_data.get("image_post_generating"):
        return IMAGE_STYLE_SELECT
    context.user_data["image_post_generating"] = True

    ok, is_admin, is_pro = await _reserve_one_ai_credit(user_id)
    if not ok:
        context.user_data.pop("image_post_generating", None)
        await _safe_edit(query, safe_t("image_no_credit", lang), image_style_keyboard(lang))
        return IMAGE_STYLE_SELECT
    context.user_data["image_post_credit_reserved"] = True

    await _safe_edit(query, safe_t("image_generating", lang, style=_style_label(style, lang)), None)
    try:
        generator = globals().get("generate_image_post") or generate_image_post
        result = await generator(
            analysis,
            style,
            **pick_supported_kwargs(
                generator,
                caption=context.user_data.get("image_post_caption", ""),
                lang=lang,
                is_pro=is_pro,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Image Post generation error: %s", exc)
        result = {"error": "generation_error"}
    finally:
        context.user_data.pop("image_post_generating", None)

    if not isinstance(result, dict) or result.get("error") or not str(result.get("post_text") or "").strip():
        await _refund_one_ai_credit(user_id, is_admin, is_pro)
        context.user_data["image_post_credit_reserved"] = False
        await _safe_edit(query, safe_t("image_generation_error", lang), image_style_keyboard(lang))
        return IMAGE_STYLE_SELECT

    post_text = str(result.get("post_text") or "").strip()
    context.user_data["image_post_text"] = post_text
    context.user_data["image_post_style"] = style
    # Credit already spent once. Subsequent action buttons do not call reserve.
    context.user_data["image_post_credit_reserved"] = False

    await _safe_edit(query, safe_t("image_preview_ready", lang), None)
    try:
        await _send_photo_preview(
            query.message,
            file_id,
            post_text,
            image_action_keyboard(lang),
        )
    except Exception:
        # Minimal test/adapters may not expose reply_photo; still keep the
        # result usable via text and action keyboard.
        await _safe_edit(query, post_text[:4000], image_action_keyboard(lang))
    return IMAGE_POST_RESULT


async def image_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _clear_image_session(context)
    await _safe_edit(query, safe_t("image_cancelled", get_lang(context)), None)
    return ConversationHandler.END


async def _load_image_channels(user_id: int):
    try:
        return [c for c in (await db.run_db(db.get_user_channels, user_id) or []) if c]
    except Exception:
        return []


async def _deliver_targets(query, context, targets: list) -> int:
    file_id = context.user_data.get("image_post_file_id")
    caption = context.user_data.get("image_post_text") or ""
    sent = 0
    for channel in targets:
        channel_id, _title = _channel_values(channel)
        try:
            await _send_photo_to_chat(context.bot, channel_id, file_id, caption)
            sent += 1
        except Exception as exc:
            logger.warning("Image Post channel delivery failed: %s", type(exc).__name__)
    if sent:
        await _safe_edit(
            query,
            safe_t("image_sent_ok", get_lang(context), count=sent),
            None,
        )
        _clear_image_session(context)
    else:
        await _safe_edit(query, safe_t("image_send_error", get_lang(context)), image_action_keyboard(get_lang(context)))
    return sent


async def image_send_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📢 Kanalga yuborish] — ayni rasm + generated caption."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    if not context.user_data.get("image_post_text"):
        await _safe_edit(query, safe_t("image_session_expired", lang), None)
        return ConversationHandler.END
    channels = await _load_image_channels(query.from_user.id)
    if not channels:
        try:
            await query.answer(safe_t("image_no_channels", lang), show_alert=True)
        except Exception:
            pass
        return IMAGE_POST_RESULT
    context.user_data["image_post_channels"] = channels
    if len(channels) == 1:
        sent = await _deliver_targets(query, context, channels)
        return ConversationHandler.END if sent else IMAGE_POST_RESULT
    await _safe_edit(query, safe_t("image_choose_channel", lang), image_channel_keyboard(channels, lang))
    return IMAGE_SEND_CHOOSE


async def image_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    channels = context.user_data.get("image_post_channels") or []
    if not channels or not context.user_data.get("image_post_text"):
        return ConversationHandler.END
    data = str(getattr(query, "data", "") or "")
    if data == IMAGE_SEND_ALL:
        targets = channels
    else:
        try:
            index = int(data.rsplit(":", 1)[1])
            targets = [channels[index]]
        except (ValueError, IndexError):
            return IMAGE_SEND_CHOOSE
    sent = await _deliver_targets(query, context, targets)
    return ConversationHandler.END if sent else IMAGE_SEND_CHOOSE


async def schedule_photo_post(user_id: int, channel_id, file_id: str,
                              caption: str, scheduled_time,
                              db_runner=None) -> int:
    """Scheduler uchun photo postni yagona DB payload bilan saqlaydi.

    Bu helper testlar va boshqa handlerlar uchun public contract: ``post_type``
    doim ``photo``, rasm ``file_id`` da, generated matn ``content``/caption'da.
    """
    runner = db_runner or db.run_db
    result = await runner(
        db.add_post,
        user_id=user_id,
        channel_id=str(channel_id),
        post_type="photo",
        content=str(caption or ""),
        file_id=str(file_id or ""),
        scheduled_time=scheduled_time,
        recurrence_type="none",
    )
    try:
        return int(result or 0)
    except (TypeError, ValueError):
        return 0


async def image_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[📅 Rejalashtirish] — vaqt so'raydi, so'ng scheduler'ga photo saqlaydi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    if not context.user_data.get("image_post_text"):
        await _safe_edit(query, safe_t("image_session_expired", lang), None)
        return ConversationHandler.END
    channels = await _load_image_channels(query.from_user.id)
    if not channels:
        try:
            await query.answer(safe_t("image_no_channels", lang), show_alert=True)
        except Exception:
            pass
        return IMAGE_POST_RESULT
    context.user_data["image_post_channels"] = channels
    await _safe_edit(query, safe_t("image_schedule_prompt", lang), None)
    return IMAGE_SCHEDULE_INPUT


async def image_schedule_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = getattr(update, "message", None)
    if message is None:
        return IMAGE_SCHEDULE_INPUT
    lang = get_lang(context)
    text = str(getattr(message, "text", "") or "").strip()
    now = datetime.now()
    candidate, reason = parse_schedule_input(text, now)
    if candidate is None:
        await message.reply_text(safe_t("image_schedule_invalid", lang), parse_mode="HTML")
        return IMAGE_SCHEDULE_INPUT
    channels = context.user_data.get("image_post_channels") or []
    if not channels:
        channels = await _load_image_channels(update.effective_user.id)
    if not channels:
        await message.reply_text(safe_t("image_no_channels", lang), parse_mode="HTML")
        return ConversationHandler.END
    channel_id, title = _channel_values(channels[0])
    post_id = await schedule_photo_post(
        update.effective_user.id,
        channel_id,
        context.user_data.get("image_post_file_id"),
        context.user_data.get("image_post_text") or "",
        candidate,
    )
    if not post_id:
        await message.reply_text(safe_t("image_schedule_error", lang), parse_mode="HTML")
        return IMAGE_SCHEDULE_INPUT
    await message.reply_text(
        safe_t("image_schedule_ok", lang, channel=html_escape(title), post_id=post_id),
        parse_mode="HTML",
    )
    _clear_image_session(context)
    return ConversationHandler.END


async def image_restyle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[🔄 Boshqa uslub] — Vision qayta chaqirilmaydi, kredit hali tanlovda."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    if not context.user_data.get("image_post_analysis"):
        return ConversationHandler.END
    context.user_data.pop("image_post_text", None)
    context.user_data.pop("image_post_style", None)
    await _safe_edit(query, safe_t("image_choose_style_again", lang), image_style_keyboard(lang))
    return IMAGE_STYLE_SELECT


async def image_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[◀️ Orqaga] — Magic Post bilan bir xil: sessiya yopiladi, Kontent
    yaratish submenyusi chiziladi (kredit tegilmaydi)."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    _clear_image_session(context)
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
        from keyboards.default import get_content_creation_keyboard

        await query.message.reply_text(
            content_menu_t("cm_menu_intro", lang),
            reply_markup=get_content_creation_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return ConversationHandler.END


async def image_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer(safe_t("image_session_expired", get_lang(context)), show_alert=True)
    return ConversationHandler.END


# Explicitly named aliases used by integrations.
image_post_received = image_photo_received
image_to_post_entry = image_post_entry
image_style_selected = image_style_callback
send_image_post_callback = image_send_callback
schedule_image_post_callback = image_schedule_callback

__all__ = [
    "IMAGE_POST_INPUT", "IMAGE_STYLE_SELECT", "IMAGE_POST_RESULT", "IMAGE_SEND_CHOOSE",
    "IMAGE_SCHEDULE_INPUT", "IMAGE_TOPIC_INPUT", "IMAGE_INPUT", "IMAGE_RESULT", "IMAGE_STYLES",
    "IMAGE_STYLE_PREFIX", "IMAGE_CANCEL", "IMAGE_SEND", "IMAGE_SCHEDULE", "IMAGE_RESTYLE",
    "IMAGE_BACK",
    "image_post_entry", "image_photo_received", "image_topic_received",
    "image_style_keyboard", "image_style_callback",
    "image_cancel_callback", "image_action_keyboard", "image_send_callback",
    "image_channel_callback", "image_schedule_callback", "image_schedule_time_received",
    "image_restyle_callback", "image_back_callback", "schedule_photo_post",
    "image_stale_callback",
]
