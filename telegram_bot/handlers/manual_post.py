"""✍️ ODDIY POST (AI'SIZ) — tayyor kontentni to'g'ridan-to'g'ri chiqarish.

Birlashtirilgan kontent menyusidagi birinchi yo'nalish. QAT'IY QOIDA: bu
oqimda AI UMUMAN ishtirok etmaydi — foydalanuvchi tayyor matn, rasm yoki
video yuboradi va bot hech qanday uslub/generatsiya savollarini bermasdan
DARHOL preview chiqaradi. Preview ostida universal boshqaruv paneli
(2-qadam UI/UX polish'dan keyin — 4 qatorli, boyitilgan)::

    [🚀 Hozir yuborish]        [📅 Vaqtni belgilash]
    [❤️ Reaksiyalar]           [🔗 Havolali tugma]
    [🗑 24 soatlik e'lon]      [🔄 Takroriy e'lon]
    [✏️ Tahrirlash]            [❌ Bekor qilish]

Amallar (barchasi mavjud, sinovdan o'tgan infratuzilmaga tayanadi):
  * 🚀 Hozir yuborish — post tanlangan kanalga darhol chiqadi
    (``db.add_post`` + scheduler zanjiri, ``scheduled_time=now``);
  * 📅 Vaqtni belgilash — oddiy reja: belgilangan sana/vaqtda chiqadi
    (masalan: ``19:30``);
  * ❤️ Reaksiyalar — presetlar ([👍/👎], [🔥/❤️/👏]) yoki qo'lda
    kiritilgan emojilar post tagiga reaksiya TUGMALARI sifatida ulanadi
    (``enable_reactions`` + ``reaction_emojis`` → scheduler delivery);
  * 🔗 Havolali tugma — "Matn - https://..." formatida kiritiladi; FAQAT
    ``http://``, ``https://``, ``tg://`` protokollari ruxsat etiladi
    (``javascript:``, ``file:`` rad etiladi); tugma preview ostida
    HAQIQIY inline URL tugma sifatida ko'rinadi va kanalga ham chiqadi
    (``btn_text`` + ``btn_url`` → scheduler ``reply_markup``);
  * 🗑 24 soatlik e'lon — kanalga chiqadi va 24 soat o'tib AVTOMATIK
    o'chadi (``delete_after_hours=24``);
  * 🔄 Takroriy e'lon — har kuni bitta vaqtda qayta chiqadi
    (``recurrence_type='daily'`` — reklama/savdo kanallari uchun);
  * ✏️ Tahrirlash — yangi matn/rasm bilan preview yangilanadi;
  * ❌ Bekor qilish — hech narsa yuborilmaydi, asosiy menyu qaytadi.

Callback prefiksi ``mnp_`` (manual post) — Magic Post (``mp_``), Voice
(``vp_``), Image (``image_``), Post Score (``ps_``) va boshqa global
prefikslar bilan to'qnashmaydi. FSM holatlari 450–456 — mavjud holatlar
bilan konfliktsiz (430–442 magic/voice, 460+ post_score/calendar):
455 — qo'lda reaksiya kiritish, 456 — havolali tugma kiritish.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, ContextTypes, ConversationHandler

from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import (
    CB_MANUAL_24H,
    CB_MANUAL_CANCEL,
    CB_MANUAL_CHANNEL,
    CB_MANUAL_DUP_AI,
    CB_MANUAL_DUP_FORCE,
    CB_MANUAL_EDIT,
    CB_MANUAL_NOW,
    CB_MANUAL_PANEL,
    CB_MANUAL_REACT,
    CB_MANUAL_REACT_BACK,
    CB_MANUAL_REACT_CUSTOM,
    CB_MANUAL_REACT_TOGGLE,
    CB_MANUAL_REPEAT,
    CB_MANUAL_TIME,
    CB_MANUAL_URL_BTN,
    CUSTOM_REACTION_MAX,
    build_reaction_button_rows,
    get_duplicate_warning_keyboard,
    get_manual_channel_keyboard,
    get_manual_post_panel,
    get_manual_reaction_keyboard,
    manual_channel_from_callback,
    manual_reaction_from_callback,
    normalize_custom_reaction_emojis,
    strip_variation_selector,
)
from locales.translations import clear_fsm_data, get_lang
from translations import manual_post_t
from utils.date_format import format_datetime, format_time
from utils.helpers import (
    html_escape,
    parse_button_input,
    parse_daily_time_input,
    parse_schedule_input,
    validate_button_text,
    validate_button_url,
)
from utils.telegram_sanitizer import sanitize_html

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

# ============================================================
# FSM HOLATLARI (450–454 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
MANUAL_AWAIT_CONTENT = 450   # tayyor kontent (matn/rasm/video) kutilmoqda
MANUAL_PREVIEW = 451         # preview + universal boshqaruv paneli
MANUAL_CHANNEL_SELECT = 452  # kanal tanlanmoqda (inline tugmalar)
MANUAL_TIME_INPUT = 453      # 📅 vaqt yoki 🔄 takrorlanish vaqti kutilmoqda
MANUAL_EDIT_INPUT = 454      # ✏️ yangi kontent kutilmoqda
MANUAL_REACTION_CUSTOM = 455  # ➕ qo'lda kiritiladigan reaksiya emojilari
MANUAL_URL_INPUT = 456       # 🔗 havolali tugma (matn + URL) kutilmoqda

# Amal rejimi (kanal tanlanishi yoki vaqt kiritilishidan oldin tanlanadi).
MODE_NOW = "now"        # 🚀 Hozir yuborish
MODE_TIME = "time"      # 📅 Vaqtni belgilash
MODE_24H = "24h"        # 🗑 24 soatlik e'lon
MODE_REPEAT = "repeat"  # 🔄 Takroriy e'lon

#: user_data kalitlari (bir joyda — testlar va handlerlar uchun yagona manba).
UD_CONTENT = "mnp_content"
UD_POST_TYPE = "mnp_post_type"
UD_FILE_ID = "mnp_file_id"
UD_MODE = "mnp_mode"
UD_WHEN = "mnp_when"            # ISO datetime (rejalashtirish uchun)
UD_REPEAT_TIME = "mnp_repeat_time"  # "HH:MM" (takroriy e'lon uchun)
# 🔁 PHASE C — dublikat detektori holati (post chiqarilishidan oldin).
UD_DUP_FORCE = "mnp_dup_force"          # foydalanuvchi "Baribir chiqarish" bosdi
UD_DUP_CHANNEL_ID = "mnp_dup_channel"   # ogohlantirilgan kanal (id)
UD_DUP_CHANNEL_TITLE = "mnp_dup_title"  # ogohlantirilgan kanal (nomi)
# 2-QADAM UI/UX POLISH — reaksiyalar va havolali (URL) tugma holati.
UD_REACTIONS = "mnp_reactions"  # tanlangan reaksiya emojilari (list[str])
UD_URL_BTN_TEXT = "mnp_url_text"  # havolali tugma matni
UD_URL_BTN_URL = "mnp_url_url"    # havolali tugma URL'i (xavfsiz protokol)

#: Qabul qilinadigan media turlari → post_type.
_SUPPORTED_MEDIA = ("photo", "video", "animation", "document")


def _extract_media(msg):
    """Xabardan (file_id, post_type) ajratadi; media bo'lmasa (None, 'text')."""
    if getattr(msg, "photo", None):
        return msg.photo[-1].file_id, "photo"
    if getattr(msg, "video", None):
        return msg.video.file_id, "video"
    if getattr(msg, "animation", None):
        return msg.animation.file_id, "animation"
    if getattr(msg, "document", None):
        return msg.document.file_id, "document"
    return None, "text"


def _has_content(context) -> bool:
    """Preview uchun kontent saqlanganmi (sessiya eskirmaganmi)."""
    ud = context.user_data
    return bool(
        (ud.get(UD_CONTENT) or "").strip()
        or (ud.get(UD_FILE_ID) and ud.get(UD_POST_TYPE) in _SUPPORTED_MEDIA)
    )


def _clear_manual_state(context) -> None:
    """Oddiy post oqimi ma'lumotlarini tozalaydi (FSM kontekstidan tashqari)."""
    for key in (UD_CONTENT, UD_POST_TYPE, UD_FILE_ID, UD_MODE, UD_WHEN,
                UD_REPEAT_TIME, UD_DUP_FORCE, UD_DUP_CHANNEL_ID,
                UD_DUP_CHANNEL_TITLE, UD_REACTIONS, UD_URL_BTN_TEXT,
                UD_URL_BTN_URL):
        context.user_data.pop(key, None)


# ============================================================
# PREVIEW — postning o'zi (AI'siz, o'zgarishsiz) + universal panel
# ============================================================
def _manual_reactions(context) -> list:
    """Saqlangan reaksiya emojilari (normal, takrorsiz ro'yxat)."""
    return normalize_custom_reaction_emojis(
        context.user_data.get(UD_REACTIONS) or [])


def _manual_url_button(context):
    """Saqlangan havolali tugma — ``(text, url)`` yoki ``None``."""
    text = str(context.user_data.get(UD_URL_BTN_TEXT) or "").strip()
    url = str(context.user_data.get(UD_URL_BTN_URL) or "").strip()
    if text and url:
        return text, url
    return None


def _manual_preview_markup(context, lang: str) -> InlineKeyboardMarkup:
    """Preview ostidagi to'liq markup: URL tugma + reaksiyalar + panel.

    Tartib: (1) havolali tugma (haqiqiy URL button), (2) reaksiya
    emojilari (ko'rinish uchun neytral ``enh:noop`` callback'li preview
    tugmalar), (3) 4 qatorli universal boshqaruv paneli.
    """
    rows = []
    url_btn = _manual_url_button(context)
    if url_btn:
        rows.append([InlineKeyboardButton(url_btn[0], url=url_btn[1])])
    reactions = _manual_reactions(context)
    if reactions:
        rows.extend(build_reaction_button_rows(None, reactions, preview=True))
    rows.extend(get_manual_post_panel(lang).inline_keyboard)
    return InlineKeyboardMarkup(rows)


def _manual_extras_text(context, lang: str) -> str:
    """Preview matniga qo'shiladigan reaksiya/tugma xulosasi (bo'sh ham mumkin)."""
    lines = []
    reactions = _manual_reactions(context)
    if reactions:
        lines.append(manual_post_t(
            "mp_reactions_on", lang, emojis=" ".join(reactions)))
    url_btn = _manual_url_button(context)
    if url_btn:
        lines.append(manual_post_t(
            "mp_url_on", lang, text=html_escape(url_btn[0]),
            url=html_escape(url_btn[1])))
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines)


async def _show_preview(target_msg, context, lang: str):
    """Saqlangan kontentni preview sifatida ko'rsatadi (panel tugmalari bilan).

    Matnli post — to'liq matn; media post — media + caption. Hech qanday AI
    qo'shimchasi YO'Q: foydalanuvchi nima yuborgan bo'lsa, aynan o'sha chiqadi.
    Tanlangan reaksiyalar va havolali tugma bo'lsa — preview matnida xulosa
    qatori, markup'da esa TUGMALAR ko'rinadi (2-qadam UI/UX polish).
    """
    content = context.user_data.get(UD_CONTENT, "") or ""
    post_type = context.user_data.get(UD_POST_TYPE, "text")
    file_id = context.user_data.get(UD_FILE_ID)
    panel = _manual_preview_markup(context, lang)
    title = manual_post_t("mp_preview_title", lang)
    foot = manual_post_t("mp_preview_foot", lang)
    extras = _manual_extras_text(context, lang)

    if post_type in _SUPPORTED_MEDIA and file_id:
        # Caption Telegram chegarasi 1024 — preview matni ham caption'da.
        caption_text = f"{title}{content}{extras}{foot}"
        cap = sanitize_html(caption_text, 1024)
        kwargs = dict(caption=cap, reply_markup=panel, parse_mode="HTML")
        try:
            if post_type == "photo":
                return await target_msg.reply_photo(photo=file_id, **kwargs)
            if post_type == "video":
                return await target_msg.reply_video(video=file_id, **kwargs)
            if post_type == "animation":
                return await target_msg.reply_animation(animation=file_id, **kwargs)
            return await target_msg.reply_document(document=file_id, **kwargs)
        except Exception:
            logger.warning("Oddiy post media preview xatosi", exc_info=True)
            # Media preview imkonsiz bo'lsa — matn ko'rinishida davom etamiz.

    body = f"{title}{sanitize_html(content, 3600)}{extras}{foot}"
    return await target_msg.reply_text(body, reply_markup=panel, parse_mode="HTML")


async def _choose_channel_or_act(query_msg, context, user_id: int, lang: str):
    """Kanal tanlash: bitta bo'lsa darhol amal, ko'p bo'lsa inline tanlov.

    Qaytaradi: keyingi FSM holati (MANUAL_CHANNEL_SELECT yoki END).
    """
    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        clear_fsm_data(context)
        _clear_manual_state(context)
        await query_msg.reply_text(
            manual_post_t("mp_no_channels", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END
    if len(channels) == 1:
        return await _publish(query_msg, context, user_id, channels[0][0],
                              channels[0][1], lang)
    await query_msg.reply_text(
        manual_post_t("mp_choose_channel", lang),
        reply_markup=get_manual_channel_keyboard(channels, lang),
        parse_mode="HTML",
    )
    return MANUAL_CHANNEL_SELECT


# ============================================================
# YUBORISH/REJALASHTIRISH — yagona publish nuqtasi (db.add_post)
# ============================================================
async def _publish(target_msg, context, user_id: int, channel_id,
                   channel_title, lang: str):
    """Tanlangan rejim bo'yicha postni DB'ga yozadi (scheduler darhol oladi).

    🔁 PHASE C — DUBLIKAT DETEKTORI: post kanalga chiqarilishidan/rejalanishidan
    OLDIN kanalning oxirgi postlari bilan yengil (AI'siz) solishtiriladi.
    85%+ o'xshashlik topilsa — yozish TO'XTATILADI va SPEKS bo'yicha 3 tugmali
    ogohlantirish chiqadi: [🚀 Baribir chiqarish] | [✨ AI bilan yangilash] |
    [❌ Bekor qilish]. Detektor fail-soft: DB/kanal tarixi o'qilmasa post
    to'sib qo'yilmaydi.

    Qaytaradi: ConversationHandler.END — yakuniy xabar yuborilgan, FSM
    tozalanadi va asosiy menyu qaytadi. (Dublikat ogohlantirishida:
    MANUAL_PREVIEW.)
    """
    is_admin = user_id in ADMIN_IDS_SET
    mode = context.user_data.get(UD_MODE, MODE_NOW)

    # --- 🔁 DUBLIKAT TEKSHIRUVI (bir marta; "Baribir chiqarish" o'tkazib yuboradi)
    if not context.user_data.get(UD_DUP_FORCE):
        content_for_check = str(context.user_data.get(UD_CONTENT, "") or "")
        if content_for_check.strip():
            from services.channels.duplicate_detector import (
                screen_post_for_duplicates,
            )
            try:
                screen = await screen_post_for_duplicates(
                    channel_id, user_id, content_for_check)
            except Exception:  # fail-soft: detektor hech qachon to'suvchi emas
                logger.debug("Dublikat tekshiruvi xatosi (kanal=%s)",
                             channel_id, exc_info=True)
                screen = {"duplicate": False}
            if screen.get("duplicate"):
                context.user_data[UD_DUP_CHANNEL_ID] = str(channel_id)
                context.user_data[UD_DUP_CHANNEL_TITLE] = str(channel_title or "")
                try:
                    score_pct = int(round(
                        float(screen.get("score") or 0.0) * 100))
                except (TypeError, ValueError):
                    score_pct = 0
                preview = html_escape(
                    str(screen.get("matched_text") or "")[:220])
                try:
                    await target_msg.reply_text(
                        manual_post_t("mp_dup_warning", lang,
                                      score=score_pct, preview=preview),
                        reply_markup=get_duplicate_warning_keyboard(lang),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.debug("Dublikat ogohlantirishi yuborilmadi",
                                 exc_info=True)
                return MANUAL_PREVIEW
    context.user_data.pop(UD_DUP_FORCE, None)
    context.user_data.pop(UD_DUP_CHANNEL_ID, None)
    context.user_data.pop(UD_DUP_CHANNEL_TITLE, None)

    now = datetime.now(tashkent_tz)

    delete_after_hours = 24 if mode == MODE_24H else 0
    recurrence_type = "daily" if mode == MODE_REPEAT else "none"
    recurrence_time = (
        f"{context.user_data.get(UD_REPEAT_TIME)}:00"
        if mode == MODE_REPEAT and context.user_data.get(UD_REPEAT_TIME)
        else None
    )

    if mode == MODE_REPEAT and context.user_data.get(UD_REPEAT_TIME):
        hh, mm = (int(x) for x in context.user_data[UD_REPEAT_TIME].split(":"))
        scheduled_time = tashkent_tz.localize(
            datetime(now.year, now.month, now.day, hh, mm))
        if scheduled_time <= now:
            scheduled_time = tashkent_tz.normalize(
                scheduled_time + timedelta(days=1))
    elif context.user_data.get(UD_WHEN):
        try:
            scheduled_time = datetime.strptime(
                context.user_data[UD_WHEN], "%Y-%m-%d %H:%M")
            scheduled_time = tashkent_tz.localize(scheduled_time)
        except (ValueError, TypeError):
            scheduled_time = now
    else:
        scheduled_time = now

    # 2-QADAM UI/UX POLISH: preview'da tanlangan reaksiyalar va havolali
    # tugma DB'ga to'liq saqlanadi — scheduler kanalga xuddi shu
    # reply_markup bilan chiqaradi (btn_text/btn_url + enable_reactions +
    # reaction_emojis ustunlari orqali).
    reactions = _manual_reactions(context)
    url_btn = _manual_url_button(context)

    ok = False
    try:
        pid = await db.run_db(
            db.add_post,
            user_id=user_id,
            channel_id=channel_id,
            post_type=context.user_data.get(UD_POST_TYPE, "text"),
            content=context.user_data.get(UD_CONTENT, "") or "",
            file_id=context.user_data.get(UD_FILE_ID),
            scheduled_time=scheduled_time,
            recurrence_type=recurrence_type,
            recurrence_day=None,
            recurrence_time=recurrence_time,
            end_date=None,
            btn_text=(url_btn[0] if url_btn else None),
            btn_url=(url_btn[1] if url_btn else None),
            enable_reactions=bool(reactions),
            delete_after_hours=delete_after_hours,
            reaction_emojis=(" ".join(reactions) if reactions else None),
        )
        ok = bool(pid)
    except Exception:
        logger.exception("Oddiy post saqlash xatosi (user_id=%s)", user_id)

    if not ok:
        await _finalize(target_msg, context, user_id, lang,
                        manual_post_t("mp_save_error", lang))
        return ConversationHandler.END

    channel_safe = html_escape((channel_title or "").strip() or "Kanal")
    if mode == MODE_TIME:
        msg_key = "mp_scheduled"
        time_display = (
            format_datetime(scheduled_time, lang)
            or scheduled_time.strftime("%Y-%m-%d %H:%M")
        )
    elif mode == MODE_24H:
        msg_key = "mp_sent_24h"
        time_display = ""
    elif mode == MODE_REPEAT:
        msg_key = "mp_repeat_ok"
        time_display = format_time(
            f"{context.user_data.get(UD_REPEAT_TIME)}:00", lang)
    else:
        msg_key = "mp_sent_now"
        time_display = ""

    await _finalize(
        target_msg, context, user_id, lang,
        manual_post_t(msg_key, lang, channel=channel_safe, time=time_display),
    )
    return ConversationHandler.END


async def _dup_ai_refresh(query, context, user_id: int, lang: str) -> int:
    """[✨ AI bilan yangilash] — dublikat postni AI boshqacha qilib yozadi.

    Oddiy post oqimining "AI'siz" qoidasi buzilmaydi: bu amal FAQAT dublikat
    ogohlantirishida, foydalanuvchi o'zi bosganda ishlaydi. AI javobi
    ``sanitize_html`` bilan xavfsizlanadi; xatoda eski matn saqlanib qoladi
    va muloyim xabar ko'rsatiladi.
    """
    old_text = str(context.user_data.get(UD_CONTENT, "") or "")
    if not old_text.strip():
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    try:
        from services.ai_service import run_ai_chain
        result = await run_ai_chain(
            f"Quyidagi Telegram postini mavzusi saqlanib, lekin tuzilishi, "
            f"hook va so'zlari BUTUNLAY BOSHQAChA qilib qayta yozing "
            f"(bu post kanalda yaqinda chiqqan postga juda o'xshab qoldi):\n\n"
            f"{old_text[:3000]}",
            "Siz SMM copywriter'siz. Faqat tayyor post matnini qaytaring — "
            "izoh, sarlavha va hech qanday qo'shimcha yo'q.",
            lang,
        )
    except Exception:
        logger.warning("Dublikat AI-yangilash xatosi (user=%s)", user_id,
                       exc_info=True)
        result = {}
    new_text = ""
    if isinstance(result, dict) and not result.get("error"):
        new_text = str(result.get("text") or result.get("content") or "").strip()

    if not new_text:
        try:
            await query.message.reply_text(
                manual_post_t("mp_dup_ai_failed", lang),
                reply_markup=get_duplicate_warning_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            logger.debug("AI-yangilash xato xabari yuborilmadi", exc_info=True)
        return MANUAL_PREVIEW

    context.user_data[UD_CONTENT] = sanitize_html(new_text, 3600)
    for key in (UD_DUP_FORCE, UD_DUP_CHANNEL_ID, UD_DUP_CHANNEL_TITLE):
        context.user_data.pop(key, None)
    try:
        await query.message.reply_text(
            manual_post_t("mp_dup_ai_done", lang), parse_mode="HTML")
    except Exception:
        pass
    await _show_preview(query.message, context, lang)
    return MANUAL_PREVIEW


async def _finalize(target_msg, context, user_id: int, lang: str,
                    text: str) -> None:
    """Yakuniy xabar + asosiy menyu + holatni tozalash (yagona nuqta)."""
    clear_fsm_data(context)
    _clear_manual_state(context)
    if target_msg is None:
        return
    try:
        await target_msg.reply_text(
            text,
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("Oddiy post yakuniy xabarini yuborib bo'lmadi",
                     exc_info=True)


# ============================================================
# HANDLERLAR
# ============================================================
async def manual_post_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✍️ Oddiy post (AI'siz) — kontent kutish holatini ochadi.

    Kanal ulanmagan bo'lsa oqim ochilmaydi (muloyim yo'riqnoma + asosiy
    menyu). HECH QANDAY AI tekshiruvi/limiti YO'Q — bu oddiy posting.
    """
    clear_fsm_data(context)
    _clear_manual_state(context)
    user_id = update.effective_user.id
    lang = get_lang(context)
    from handlers.navigation import SECTION_CONTENT, remember_section
    remember_section(context, SECTION_CONTENT)

    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await update.message.reply_text(
            manual_post_t("mp_no_channels", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    await update.message.reply_text(
        manual_post_t("mp_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return MANUAL_AWAIT_CONTENT


async def manual_content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tayyor kontent qabul qilindi → DARHOL preview (AI savollarsiz).

    Matn, rasm, video, GIF yoki hujjat (caption bilan yokisiz) qabul
    qilinadi; qolgan turlar (stiker, ovoz, kontakt...) aniq izoh bilan
    rad etiladi — lekin oqim uzilmaydi.
    """
    msg = update.message
    lang = get_lang(context)

    file_id, post_type = _extract_media(msg)
    text_input = (msg.text or msg.caption or "").strip()

    if not file_id and not text_input:
        # Qo'llab-quvvatlanmaydigan xabar turi (stiker/ovoz/kontakt...).
        await msg.reply_text(
            manual_post_t("mp_unsupported", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_AWAIT_CONTENT

    context.user_data[UD_CONTENT] = text_input
    context.user_data[UD_POST_TYPE] = post_type if file_id else "text"
    context.user_data[UD_FILE_ID] = file_id

    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_edit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✏️ Tahrirlash: yangi kontent bilan preview yangilanadi."""
    msg = update.message
    lang = get_lang(context)

    file_id, post_type = _extract_media(msg)
    text_input = (msg.text or msg.caption or "").strip()
    if not file_id and not text_input:
        await msg.reply_text(
            manual_post_t("mp_unsupported", lang), parse_mode="HTML",
        )
        return MANUAL_EDIT_INPUT

    # Tahrirlash: media almashtirilsa — yangi media; matn har doim yangilanadi.
    if file_id:
        context.user_data[UD_POST_TYPE] = post_type
        context.user_data[UD_FILE_ID] = file_id
    context.user_data[UD_CONTENT] = text_input

    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Vaqtni belgilash / 🔄 Takroriy e'lon vaqti qabul qilinadi.

    ``parse_schedule_input`` — "19:30", "ertaga 09:00", "25.09.2026 18:00"
    kabi barcha ko'rinishlarni xavfsiz o'qiydi (o'tmishdagi vaqt rad etiladi).
    Takroriy rejada faqat KUNLIK VAQT ("HH:MM") olinadi.
    """
    msg = update.message
    user_id = update.effective_user.id
    lang = get_lang(context)
    mode = context.user_data.get(UD_MODE, MODE_TIME)

    if msg is None:
        return MANUAL_TIME_INPUT
    if not getattr(msg, "text", None):
        await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_TIME_INPUT

    text = msg.text.strip()

    if mode == MODE_REPEAT:
        parsed = parse_daily_time_input(text)
        if parsed is None:
            # "ertaga 9 da" kabi ifodani ham qabul qilamiz.
            candidate, _reason = parse_schedule_input(text)
            parsed = (candidate.hour, candidate.minute) if candidate else None
        if parsed is None:
            await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                                 parse_mode="HTML")
            return MANUAL_TIME_INPUT
        hh, mm = parsed
        context.user_data[UD_REPEAT_TIME] = f"{hh:02d}:{mm:02d}"
        return await _choose_channel_or_act(msg, context, user_id, lang)

    candidate, _reason = parse_schedule_input(text)
    if candidate is None:
        await msg.reply_text(manual_post_t("mp_time_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_TIME_INPUT

    context.user_data[UD_WHEN] = candidate.strftime("%Y-%m-%d %H:%M")
    return await _choose_channel_or_act(msg, context, user_id, lang)


async def manual_reaction_custom_received(update: Update,
                                          context: ContextTypes.DEFAULT_TYPE):
    """➕ O'zim kiritaman: qo'lda yuborilgan reaksiya emojilari qabul qilinadi.

    Emoji bo'lmagan belgilar tashlanadi (``normalize_custom_reaction_emojis``);
    hech narsa topilmasa muloyim xato bilan holat saqlanadi. Muvaffaqiyatda
    emojilar postga ulanadi va preview yangilanadi.
    """
    msg = update.message
    lang = get_lang(context)
    if msg is None or not (msg.text or "").strip():
        if msg is not None:
            await msg.reply_text(
                manual_post_t("mp_react_custom_invalid", lang),
                parse_mode="HTML",
            )
        return MANUAL_REACTION_CUSTOM

    emojis = normalize_custom_reaction_emojis(msg.text)
    if not emojis:
        await msg.reply_text(
            manual_post_t("mp_react_custom_invalid", lang),
            parse_mode="HTML",
        )
        return MANUAL_REACTION_CUSTOM

    context.user_data[UD_REACTIONS] = emojis
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔗 Havolali tugma: "Matn - https://havola" formatidagi kiritma.

    XAVFSIZLIK: havola ``validate_button_url`` (utils.security
    ``url_rejection_reason`` asosida) tekshiruvidan o'tadi — FAQAT
    ``http://``, ``https://`` va ``tg://`` protokollariga ruxsat;
    ``javascript:``, ``file:``, ``data:`` kabi xavfli havolalar RAD
    etiladi va holat saqlanadi. Muvaffaqiyatda tugma preview ostida
    HAQIQIY inline URL tugma sifatida paydo bo'ladi.
    """
    msg = update.message
    lang = get_lang(context)
    if msg is None or not (msg.text or "").strip():
        if msg is not None:
            await msg.reply_text(manual_post_t("mp_url_invalid", lang),
                                 parse_mode="HTML")
        return MANUAL_URL_INPUT

    btn_text, btn_url = parse_button_input(msg.text)
    ok_text, _err_text = validate_button_text(btn_text) if btn_text else (False, "")
    ok_url, _err_url = validate_button_url(btn_url) if btn_url else (False, "")
    if not (btn_text and btn_url and ok_text and ok_url):
        await msg.reply_text(manual_post_t("mp_url_invalid", lang),
                             parse_mode="HTML")
        return MANUAL_URL_INPUT

    context.user_data[UD_URL_BTN_TEXT] = btn_text
    context.user_data[UD_URL_BTN_URL] = btn_url
    await _show_preview(msg, context, lang)
    return MANUAL_PREVIEW


async def manual_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Universal boshqaruv paneli tugmalari (``mnp_*`` callback'lari)."""
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    await query.answer()  # SPEKS: har callback boshida darhol answer
    user_id = query.from_user.id
    lang = get_lang(context)
    data = query.data or ""

    # Eski tugmalarga qarshi himoya: kontent saqlanmagan bo'lsa, yangi
    # oqimni ochish taklif qilinadi (foydalanuvchi hech qachon "qotmaydi").
    if data != CB_MANUAL_CANCEL and not _has_content(context):
        await query.message.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
        clear_fsm_data(context)
        return ConversationHandler.END

    if data == CB_MANUAL_CANCEL:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _finalize(query.message, context, user_id, lang,
                        manual_post_t("mp_cancelled", lang))
        return ConversationHandler.END

    if data == CB_MANUAL_PANEL:
        # Kanal tanlashdan preview paneliga qaytish.
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    if data == CB_MANUAL_EDIT:
        await query.message.reply_text(
            manual_post_t("mp_edit_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_EDIT_INPUT

    # --- ❤️ REAKSIYALAR (2-qadam UI/UX polish) ---
    if data == CB_MANUAL_REACT:
        # Preset tanlash oynasi: [👍/👎] | [🔥/❤️/👏] + ➕ O'zim kiritaman
        # + ◀️ Orqaga. Tanlov shu xabarning o'zida (toggle) yangilanadi.
        await query.message.reply_text(
            manual_post_t("mp_react_prompt", lang),
            reply_markup=get_manual_reaction_keyboard(
                _manual_reactions(context), lang),
            parse_mode="HTML",
        )
        return MANUAL_PREVIEW

    if data == CB_MANUAL_REACT_BACK:
        # ◀️ Orqaga — tanlangan reaksiyalar bilan preview yangilanadi.
        await _show_preview(query.message, context, lang)
        return MANUAL_PREVIEW

    if data == CB_MANUAL_REACT_CUSTOM:
        # ➕ O'zim kiritaman — qo'lda emoji kiritish holati ochiladi.
        await query.message.reply_text(
            manual_post_t("mp_react_custom_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_REACTION_CUSTOM

    if data.startswith(CB_MANUAL_REACT_TOGGLE):
        emoji = manual_reaction_from_callback(data)
        selected = list(context.user_data.get(UD_REACTIONS) or [])
        if emoji:
            key = strip_variation_selector(emoji)
            existing = next(
                (e for e in selected
                 if strip_variation_selector(e) == key), None)
            if existing is not None:
                selected.remove(existing)          # takror bosildi → o'chadi
            elif len(selected) < CUSTOM_REACTION_MAX:
                selected.append(emoji)             # yangi tanlov qo'shiladi
            context.user_data[UD_REACTIONS] = selected
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_manual_reaction_keyboard(selected, lang))
        except Exception:
            logger.debug("Reaksiya klaviaturasini yangilab bo'lmadi",
                         exc_info=True)
        return MANUAL_PREVIEW

    # --- 🔗 HAVOLALI (URL) TUGMA (2-qadam UI/UX polish) ---
    if data == CB_MANUAL_URL_BTN:
        await query.message.reply_text(
            manual_post_t("mp_url_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_URL_INPUT

    if data == CB_MANUAL_TIME:
        context.user_data[UD_MODE] = MODE_TIME
        await query.message.reply_text(
            manual_post_t("mp_time_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_TIME_INPUT

    if data == CB_MANUAL_REPEAT:
        context.user_data[UD_MODE] = MODE_REPEAT
        await query.message.reply_text(
            manual_post_t("mp_repeat_prompt", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return MANUAL_TIME_INPUT

    if data == CB_MANUAL_NOW:
        context.user_data[UD_MODE] = MODE_NOW
        return await _choose_channel_or_act(query.message, context, user_id, lang)

    if data == CB_MANUAL_24H:
        context.user_data[UD_MODE] = MODE_24H
        return await _choose_channel_or_act(query.message, context, user_id, lang)

    # 🔁 PHASE C — dublikat ogohlantirishi amallari (SPEKS: 3 tugma).
    if data == CB_MANUAL_DUP_FORCE:
        # [🚀 Baribir chiqarish] — ogohlantirishga qaramay xuddi shu kanalga
        # yozamiz (kanal saqlangan bo'lishi shart — payload manipulyatsiyasi
        # imkonsiz: faqat _publish o'zi yozgan kanal ishlatiladi).
        context.user_data[UD_DUP_FORCE] = True
        dup_channel = context.user_data.get(UD_DUP_CHANNEL_ID)
        dup_title = str(context.user_data.get(UD_DUP_CHANNEL_TITLE) or "")
        if dup_channel:
            return await _publish(query.message, context, user_id,
                                  dup_channel, dup_title, lang)
        return await _choose_channel_or_act(query.message, context, user_id,
                                            lang)

    if data == CB_MANUAL_DUP_AI:
        # [✨ AI bilan yangilash] — matnni AI boshqacha qilib qayta yozadi
        # (foydalanuvchi O'ZI bosgan holda; oddiy oqim AI'siz qoladi).
        return await _dup_ai_refresh(query, context, user_id, lang)

    if data.startswith(CB_MANUAL_CHANNEL):
        channel_id = manual_channel_from_callback(data)
        if channel_id is None:
            await _show_preview(query.message, context, lang)
            return MANUAL_PREVIEW
        channels = await db.run_db(db.get_user_channels, user_id) or []
        title = next((t for cid, t in channels if str(cid) == str(channel_id)),
                     "")
        if not title and channels:
            # Payload manipulyatsiyasi — foydalanuvchiga TEGISHLI kanalni
            # tanlatamiz (fail-closed: o'zga kanalga post chiqmaydi).
            await query.message.reply_text(
                manual_post_t("mp_choose_channel", lang),
                reply_markup=get_manual_channel_keyboard(channels, lang),
                parse_mode="HTML",
            )
            return MANUAL_CHANNEL_SELECT
        return await _publish(query.message, context, user_id, channel_id,
                              title, lang)

    return MANUAL_PREVIEW


async def manual_stale_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sessiya tugagach bosilgan eski ``mnp_*`` tugma — muloyim javob.

    Entry point sifatida ro'yxatdan o'tadi: eski preview xabaridagi tugma
    bosilsa foydalanuvchi javobsiz qolmaydi (crash ham yo'q).
    """
    query = update.callback_query
    if query is None:
        return ConversationHandler.END
    lang = get_lang(context)
    user_id = query.from_user.id
    try:
        await query.answer()
    except Exception:
        pass
    clear_fsm_data(context)
    _clear_manual_state(context)
    try:
        await query.message.reply_text(
            manual_post_t("mp_session_expired", lang),
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET, lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return ConversationHandler.END


# ============================================================
# DIALOG HIMOYASI (content_creation.ContentOfferEntryHandler usuli)
# ============================================================
_APPLICATION = None


def set_application(app) -> None:
    """``ManualEntryHandler`` uchun Application havolasini o'rnatadi."""
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
    except Exception:  # pragma: no cover - xatoda entry'ni xavfsiz yopamiz
        return False


class ManualEntryHandler(CallbackQueryHandler):
    """Eski ``mnp_*`` panel tugmasi — faqat dialog TASHQARISIDA ishlaydi.

    Boshqa dialog (to'lov, kanal ulash, new_post...) faol bo'lsa tugma mos
    KELMAYDI: holat buzilmaydi, xabar o'sha dialogning o'z handlerlariga
    (yoki fallback'ga) qoladi. Dialog TASHQARISIDA esa sessiya eskirgani
    haqida muloyim javob qaytaradi.
    """

    def check_update(self, update):
        base = super().check_update(update)
        if not base or _is_inside_dialog(update):
            return None
        return base
