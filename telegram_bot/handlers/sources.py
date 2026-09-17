"""📥 KONTENT MANBALARI — handler/klaviatura qatlami (PHASE D, 2/2).

PHASE D ning 1/2 qismi (``services/sources/*`` + ``services/channels/recycle.py``)
faqat **servis** qatlami edi: SSRF himoyali havola o'quvchi, RSS/ATOM oqimi
va eski postni yangilovchi recycle xizmati. Bu modul ularni FOYDALANUVCHIGA
ulaydi — kanal kontekstidagi HUB orqali:

    📢 Kanallarim → kanal → [📥 Kontent manbalari]
        🔗 Havoladan post   — maqola havolasi → AI 4 format → preview
        📡 RSS oqim         — manba qo'shish/tekshirish/avtopublish
        ♻️ Eski postni yangilash — 14+ kunlik post → yangi hook/sarlavha/CTA
        🗂 Qoralamalar      — tasdiqlash kutayotgan post loyihalari

Preview oynasi BARCHA uch oqim uchun UMUMIY (``SRC_PREVIEW``)::

    [📅 Rejalashtirish]  [🚀 Hozir chiqarish]
    [🔄 Boshqa variant]  [❌ Bekor qilish]

Xavfsizlik kafolotlari (servis qatlamidagilarga qo'shimcha):

  * **IDOR** — har bir kirish ``handlers.channels._owned_channel`` orqali
    kanal egaligini tekshiradi; manba/qoralama so'rovlari ``user_id`` bilan
    filtrlangan DB funksiyalaridan o'tadi (begona id → "topilmadi");
  * **SSRF** — foydalanuvchi yuborgan har bir havola (URL va RSS manzili)
    saqlanishidan OLDIN ``validate_public_url`` dan o'tadi (ichki tarmoq,
    localhost, metadata, nostandart port — bloklanadi);
  * **Fail-soft** — tarmoq/AI/DB xatosida foydalanuvchi JAVOBSIZ QOLMAYDI:
    aniq xabar + qayta urinish tugmasi, hech qanday istisno tashqariga
    chiqmaydi (barchasi ``_safe_edit`` / ``_safe_send`` ichida);
  * **Toza sessiya** — har kirishda eski ``user_data`` qoldiqlari tozalanadi
    (``clear_sources_session``), shu sababli ikki oqim aralashib ketmaydi.

Yozish nuqtasi YAGONA: barcha postlar ``database.add_post`` orqali
``scheduled_posts`` navbatiga tushadi (scheduler ularni o'zi chiqaradi) —
ya'ni "🚀 Hozir chiqarish" ham xavfsiz navbat orqali, dublikat yuborish
xavfisiz ishlaydi.

FSM holatlari 530–539 — repodagi boshqa oqimlar bilan to'qnashmaydi
(480–483 avtopilot, 485–490 shablonlar, 520–525 rasm, 501–512 boshqalar).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from keyboards.callback_data import (
    CB_CHANNEL_SOURCES,
    CB_SOURCE_ACTION,
    CB_SOURCE_BACK,
    CB_SOURCE_CANCEL,
    CB_SOURCE_DRAFT,
    CB_SOURCE_DRAFTS,
    CB_SOURCE_FORMAT,
    CB_SOURCE_REC_PICK,
    CB_SOURCE_RECYCLE,
    CB_SOURCE_RSS,
    CB_SOURCE_RSS_ADD,
    CB_SOURCE_RSS_AUTO,
    CB_SOURCE_RSS_CHECK,
    CB_SOURCE_RSS_DEL,
    CB_SOURCE_RSS_TOGGLE,
    CB_SOURCE_URL,
    cb,
)
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang
from services.channels.recycle import (
    MIN_AGE_DAYS,
    RecycleService,
    load_recycle_candidates,
)
from services.sources.rss_service import (
    DEFAULT_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    RssService,
    clamp_interval,
    parse_interval_input,
)
from services.sources.url_extractor import (
    FORMAT_KEYS,
    UrlPostService,
    format_label,
    validate_public_url,
)
from translations import sources_t
from utils.date_format import format_datetime
from utils.helpers import html_escape
from utils.telegram_sanitizer import sanitize_html

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

# ============================================================
# FSM HOLATLARI (530–539 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
SRC_HUB = 530             # 📥 manbalar HUB'i (4 yo'nalish)
SRC_URL_INPUT = 531       # 🔗 maqola havolasi kutilmoqda
SRC_URL_FORMATS = 532     # 🎛 4 formatdan biri tanlanmoqda
SRC_PREVIEW = 533         # 📝 tayyor post preview (reja/hozir/qayta/bekor)
SRC_TIME_INPUT = 534      # 📅 rejalashtirish vaqti kutilmoqda
SRC_RSS_MENU = 535        # 📡 manbalar ro'yxati (qo'shish/tekshirish/...)
SRC_RSS_URL = 536         # ➕ yangi manba havolasi kutilmoqda
SRC_RSS_INTERVAL = 537    # ⏱ tekshirish intervali kutilmoqda
SRC_RECYCLE_LIST = 538    # ♻️ eski post nomzodlari ro'yxati
SRC_DRAFTS = 539          # 🗂 tasdiqlash kutayotgan qoralamalar

# ============================================================
# user_data kalitlari (yagona manba — tozalash va testlar uchun)
# ============================================================
UD_CHANNEL = "src_channel_id"
UD_TITLE = "src_channel_title"
UD_ARTICLE = "src_article"       # havoladan o'qilgan maqola (dict)
UD_URL = "src_url"               # oxirgi kiritilgan havola
UD_DRAFTS = "src_drafts"         # 4 format (list[dict])
UD_FORMAT = "src_format"         # tanlangan format kaliti
UD_PREVIEW = "src_preview"       # {"mode": url|recycle|draft, "text": ...}
UD_RECYCLE = "src_recycle"       # nomzodlar ro'yxati (list[dict])
UD_RECYCLE_IDX = "src_rec_idx"   # tanlangan nomzod indeksi

#: Bitta xabarda ko'rsatiladigan qoralamalar soni (Telegram chegarasi hisobi).
MAX_DRAFT_BUTTONS = 12
#: Preview matni uchun xavfsiz uzunlik (Telegram 4096 + teglar zaxirasi).
PREVIEW_LIMIT = 3600

#: Xizmatlar — testlarda almashtirish (AI/orkestrator inject) uchun factory.
SERVICE_FACTORIES = {}


def new_url_service() -> UrlPostService:
    """🔗 URL → post xizmati (factory — testlarda almashtiriladi)."""
    return UrlPostService()


def new_rss_service() -> RssService:
    """📡 RSS/ATOM xizmati (factory — testlarda almashtiriladi)."""
    return RssService()


def new_recycle_service() -> RecycleService:
    """♻️ Content Recycle xizmati (factory — testlarda almashtiriladi)."""
    return RecycleService()


def clear_sources_session(context) -> None:
    """Manbalar sessiyasini toza yopadi (boshqa oqimlarga aralashmaydi)."""
    for key in (UD_CHANNEL, UD_TITLE, UD_ARTICLE, UD_URL, UD_DRAFTS,
                UD_FORMAT, UD_PREVIEW, UD_RECYCLE, UD_RECYCLE_IDX):
        context.user_data.pop(key, None)


def _lang(context) -> str:
    try:
        return get_lang(context)
    except Exception:  # pragma: no cover
        return "uz"


def _payload(data: str) -> str:
    """``prefiks:payload`` dan payload'ni ajratadi (yo'q bo'lsa "")."""
    text = str(data or "")
    return text.split(":", 1)[1] if ":" in text else ""


def _safe_preview(text: str) -> str:
    """Preview matni: sanitizer + uzunlik chegarasi (hech qachon yiqilmaydi)."""
    try:
        return sanitize_html(str(text or ""), PREVIEW_LIMIT)
    except Exception:  # pragma: no cover — sanitizer har doim ishlaydi
        return html_escape(str(text or "")[:PREVIEW_LIMIT])


# ============================================================
# KLAVIATURALAR
# ============================================================
def sources_hub_keyboard(channel_id: str, drafts_count: int = 0,
                         lang: str = "uz") -> InlineKeyboardMarkup:
    """📥 Manbalar HUB'i (4 yo'nalish + Orqaga)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(sources_t("src_btn_url", lang),
                              callback_data=cb(CB_SOURCE_URL, channel_id))],
        [InlineKeyboardButton(sources_t("src_btn_rss", lang),
                              callback_data=cb(CB_SOURCE_RSS, channel_id))],
        [InlineKeyboardButton(sources_t("src_btn_recycle", lang),
                              callback_data=cb(CB_SOURCE_RECYCLE, channel_id))],
        [InlineKeyboardButton(sources_t("src_btn_drafts", lang,
                                        count=int(drafts_count or 0)),
                              callback_data=cb(CB_SOURCE_DRAFTS, channel_id))],
        [InlineKeyboardButton(sources_t("src_btn_back", lang),
                              callback_data=CB_SOURCE_BACK)],
    ])


def formats_keyboard(drafts: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """🎛 4 format tugmasi (2×2) + Bekor qilish."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for item in drafts or []:
        row.append(InlineKeyboardButton(
            item.get("label") or format_label(item.get("format", ""), lang),
            callback_data=cb(CB_SOURCE_FORMAT, item.get("format", "")),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(sources_t("src_btn_cancel", lang),
                                      callback_data=CB_SOURCE_CANCEL)])
    return InlineKeyboardMarkup(rows)


def preview_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📝 Tayyor post paneli (SPEKS: 4 amal)."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(sources_t("src_btn_schedule", lang),
                                 callback_data=cb(CB_SOURCE_ACTION, "sched")),
            InlineKeyboardButton(sources_t("src_btn_publish", lang),
                                 callback_data=cb(CB_SOURCE_ACTION, "now")),
        ],
        [InlineKeyboardButton(sources_t("src_btn_regen", lang),
                              callback_data=cb(CB_SOURCE_ACTION, "regen"))],
        [InlineKeyboardButton(sources_t("src_btn_cancel", lang),
                              callback_data=CB_SOURCE_CANCEL)],
    ])


def source_list_keyboard(sources: list, channel_id: str,
                         lang: str = "uz") -> InlineKeyboardMarkup:
    """📡 Manbalar ro'yxati: har manba — tekshirish + 3 boshqaruv amali."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(sources_t("src_rss_btn_add", lang),
                              callback_data=CB_SOURCE_RSS_ADD)],
    ]
    for item in sources or []:
        source_id = int(item.get("id") or 0)
        icon = "▶️" if item.get("enabled") else "⏸"
        rows.append([InlineKeyboardButton(
            sources_t("src_rss_source_item", lang, icon=icon,
                      title=(item.get("title") or item.get("source_url")
                             or "—")[:32],
                      minutes=int(item.get("interval_minutes")
                                  or DEFAULT_INTERVAL_MINUTES)),
            callback_data=cb(CB_SOURCE_RSS_CHECK, source_id),
        )])
        rows.append([
            InlineKeyboardButton(
                sources_t("src_rss_btn_toggle_on" if item.get("enabled")
                          else "src_rss_btn_toggle_off", lang),
                callback_data=cb(CB_SOURCE_RSS_TOGGLE, source_id)),
            InlineKeyboardButton(
                sources_t("src_rss_btn_auto_on" if item.get("autopublish")
                          else "src_rss_btn_auto_off", lang),
                callback_data=cb(CB_SOURCE_RSS_AUTO, source_id)),
            InlineKeyboardButton(
                sources_t("src_rss_btn_delete", lang),
                callback_data=cb(CB_SOURCE_RSS_DEL, source_id)),
        ])
    rows.append([InlineKeyboardButton(sources_t("src_btn_back", lang),
                                      callback_data=CB_SOURCE_BACK)])
    return InlineKeyboardMarkup(rows)


def drafts_keyboard(drafts: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """🗂 Qoralamalar: har biri uchun [📅 Rejalashtirish] [🗑 O'chirish]."""
    rows: list[list[InlineKeyboardButton]] = []
    for item in (drafts or [])[:MAX_DRAFT_BUTTONS]:
        draft_id = int(item.get("id") or 0)
        rows.append([
            InlineKeyboardButton(
                sources_t("src_rss_draft_btn_approve", lang),
                callback_data=cb(CB_SOURCE_DRAFT, "ok", draft_id)),
            InlineKeyboardButton(
                sources_t("src_rss_draft_btn_delete", lang),
                callback_data=cb(CB_SOURCE_DRAFT, "del", draft_id)),
        ])
    rows.append([InlineKeyboardButton(sources_t("src_btn_back", lang),
                                      callback_data=CB_SOURCE_BACK)])
    return InlineKeyboardMarkup(rows)


def recycle_keyboard(candidates: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """♻️ Eski post nomzodlari (har biri alohida tugma + Orqaga)."""
    rows: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(candidates or []):
        preview = html_escape(str(item.get("text") or "")[:40])
        rows.append([InlineKeyboardButton(
            sources_t("src_rec_item", lang,
                      views=int(item.get("views") or 0),
                      age=int(round(float(item.get("age_days") or 0))),
                      preview=preview),
            callback_data=cb(CB_SOURCE_REC_PICK, index),
        )])
    rows.append([InlineKeyboardButton(sources_t("src_btn_back", lang),
                                      callback_data=CB_SOURCE_BACK)])
    return InlineKeyboardMarkup(rows)


# ============================================================
# XAVFSIZ YUBORISH YORDAMCHILARI
# ============================================================
async def _safe_edit(query, text: str, markup=None) -> bool:
    try:
        await query.edit_message_text(text, reply_markup=markup,
                                      parse_mode="HTML")
        return True
    except Exception:
        logger.debug("manbalar: edit ishlamadi", exc_info=True)
    try:
        await query.message.reply_text(text, reply_markup=markup,
                                       parse_mode="HTML")
        return True
    except Exception:
        logger.debug("manbalar: xabar yuborib bo'lmadi", exc_info=True)
        return False


async def _safe_send(msg, text: str, markup=None) -> bool:
    try:
        await msg.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        logger.debug("manbalar: yuborish xatosi", exc_info=True)
        return False


async def _dna_block(user_id: int, channel_id: str, lang: str = "uz") -> str:
    """Kanal DNA bloki (prompt uchun). Fail-soft: xatoda bo'sh satr."""
    if not channel_id or not user_id:
        return ""
    try:
        from services.channels.dna import build_dna_system_prompt, get_channel_dna

        result = await get_channel_dna(channel_id, int(user_id), db_module=db)
        profile = result.get("profile") if isinstance(result, dict) else None
        if isinstance(profile, dict) and profile:
            return build_dna_system_prompt(profile, lang=lang)
    except Exception:  # noqa: BLE001 — DNA yo'qligi oqimni to'xtatmaydi
        logger.debug("manbalar: DNA bloki olinmadi", exc_info=True)
    return ""


# ============================================================
# KIRISH — 📢 Kanallarim → kanal → [📥 Kontent manbalari]
# ============================================================
async def channel_sources_entry(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """HUB'ni ochadi (kanal egaligi — IDOR tekshiruvi bilan)."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = _payload(query.data)

    from handlers.channels import _owned_channel, _channel_title
    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        from keyboards.inline import render_channel_panel
        await _safe_edit(query, sources_t("src_not_found", lang),
                         render_channel_panel(channel_id, lang))
        return ConversationHandler.END

    clear_sources_session(context)
    context.user_data[UD_CHANNEL] = str(channel_id)
    context.user_data[UD_TITLE] = (channel[1] or "Kanal") if len(channel) > 1 else "Kanal"
    title = _channel_title(channel)

    drafts_count = 0
    try:
        drafts_count = await db.run_db(db.count_source_drafts, user_id)
    except Exception:  # noqa: BLE001 — badge yo'qligi HUB'ni to'xtatmaydi
        drafts_count = 0

    await _safe_edit(
        query,
        sources_t("src_menu_title", lang, channel=title),
        sources_hub_keyboard(channel_id, drafts_count, lang),
    )
    return SRC_HUB


# ============================================================
# SRC_HUB — yo'nalish tanlash
# ============================================================
async def sources_hub_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):
    """🔗 / 📡 / ♻️ / 🗂 yo'nalishlaridan birini ochadi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    data = str(getattr(query, "data", "") or "")

    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    channel_title = html_escape(str(context.user_data.get(UD_TITLE) or "Kanal"))
    if not channel_id:
        await _safe_edit(query, sources_t("src_stale", lang))
        return ConversationHandler.END

    # --- 🔗 Havoladan post ---
    if data.startswith(CB_SOURCE_URL):
        await _safe_edit(query, sources_t("src_url_ask", lang),
                         get_cancel_keyboard(lang))
        return SRC_URL_INPUT

    # --- 📡 RSS/ATOM oqimi ---
    if data.startswith(CB_SOURCE_RSS):
        return await _render_rss_menu(query, context, user_id, channel_id,
                                      channel_title, lang)

    # --- ♻️ Eski postni yangilash ---
    if data.startswith(CB_SOURCE_RECYCLE):
        return await _render_recycle_list(query, context, user_id, channel_id,
                                          channel_title, lang)

    # --- 🗂 Qoralamalar ---
    if data.startswith(CB_SOURCE_DRAFTS):
        return await _render_drafts(query, context, user_id, channel_id,
                                    channel_title, lang)

    await _safe_edit(query, sources_t("src_menu_title", lang,
                                      channel=channel_title),
                     sources_hub_keyboard(channel_id, 0, lang))
    return SRC_HUB


async def sources_back_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """◀️ Orqaga — manbalar HUB'iga (kanal ichida qolamiz)."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    channel_title = html_escape(str(context.user_data.get(UD_TITLE) or "Kanal"))

    if not channel_id:
        clear_sources_session(context)
        await _safe_edit(query, sources_t("src_cancel_done", lang))
        return ConversationHandler.END

    drafts_count = 0
    try:
        drafts_count = await db.run_db(db.count_source_drafts, user_id)
    except Exception:  # noqa: BLE001
        drafts_count = 0
    context.user_data.pop(UD_PREVIEW, None)
    await _safe_edit(query, sources_t("src_menu_title", lang,
                                      channel=channel_title),
                     sources_hub_keyboard(channel_id, drafts_count, lang))
    return SRC_HUB


async def source_cancel_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """❌ Bekor qilish — sessiya toza yopiladi."""
    query = getattr(update, "callback_query", None)
    if query is not None:
        try:
            await query.answer()
        except Exception:
            pass
    lang = _lang(context)
    clear_sources_session(context)
    if query is not None:
        try:
            await query.edit_message_text(sources_t("src_cancel_done", lang),
                                          parse_mode="HTML")
            return ConversationHandler.END
        except Exception:
            pass
        await _safe_edit(query, sources_t("src_cancel_done", lang))
    return ConversationHandler.END


async def sources_stale_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """Eski (sessiyadan tashqari) ``src_*`` tugmasi — muloyim toast."""
    query = getattr(update, "callback_query", None)
    lang = _lang(context)
    if query is not None:
        try:
            await query.answer(sources_t("src_stale", lang), show_alert=False)
        except Exception:
            logger.debug("manbalar: stale toast yuborilmadi", exc_info=True)
    return ConversationHandler.END


# ============================================================
# 🔗 URL → POST
# ============================================================
async def url_text_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Havola qabul qilinadi → maqola o'qiladi → 4 format tayyorlanadi."""
    message = getattr(update, "message", None)
    if message is None:
        return SRC_URL_INPUT
    lang = _lang(context)
    user_id = update.effective_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not channel_id:
        await _safe_send(message, sources_t("src_stale", lang))
        return ConversationHandler.END

    raw = str(getattr(message, "text", "") or "").strip()
    if not raw or raw.startswith("/"):
        await _safe_send(message, sources_t("src_url_ask", lang),
                         get_cancel_keyboard(lang))
        return SRC_URL_INPUT

    # 1) SSRF GUARD — havola bazaga/AI ga borishdan OLDIN tekshiriladi.
    guard = validate_public_url(raw)
    if not guard.get("ok"):
        await _safe_send(message, sources_t("src_rss_invalid_url", lang),
                         get_cancel_keyboard(lang))
        return SRC_URL_INPUT

    url = str(guard.get("url") or raw)
    context.user_data[UD_URL] = url
    await _safe_send(message, sources_t("src_url_checking", lang))

    # 2) Tarmoq — event loop BLOKLANMASIN (thread'da).
    try:
        loaded = await asyncio.to_thread(fetch_article_safe, url)
    except Exception:  # noqa: BLE001 — tarmoq xatosi fail-soft
        logger.info("manbalar: havola o'qilmadi (%s)", url, exc_info=True)
        loaded = {"ok": False, "error_code": "network_error"}

    if not loaded.get("ok"):
        await _safe_send(message, loaded.get("message")
                         or sources_t("src_rss_invalid_url", lang),
                         get_cancel_keyboard(lang))
        return SRC_URL_INPUT

    article = dict(loaded.get("article") or {})
    context.user_data[UD_ARTICLE] = article

    # 3) AI — Channel DNA asosida 4 format.
    dna_block = await _dna_block(user_id, channel_id, lang)
    service = new_url_service()
    try:
        result = await service.build_drafts(
            url, user_id=user_id, lang=lang, db_module=db,
            article=article, dna_block=dna_block, allow_local=False)
    except Exception:  # noqa: BLE001 — AI xatosi foydalanuvchini to'xtatmaydi
        logger.exception("manbalar: URL→post generatsiya xatosi (user=%s)",
                         user_id)
        result = {"ok": False, "error_code": "ai_failed"}

    drafts = list(result.get("drafts") or [])
    if not drafts:
        context.user_data.pop(UD_ARTICLE, None)
        await _safe_send(message, sources_t("src_url_ai_failed", lang),
                         get_cancel_keyboard(lang))
        return SRC_URL_INPUT

    context.user_data[UD_DRAFTS] = drafts
    title = html_escape(str(article.get("title") or "")[:120])
    source = html_escape(str(article.get("source") or article.get("source_url")
                             or url)[:120])
    signals = len(list(loaded.get("injection_signals")
                       or article.get("injection_signals") or []))
    await _safe_send(
        message,
        sources_t("src_url_article", lang, title=title, source=source,
                  chars=len(str(article.get("text") or "")), signals=signals),
    )
    await _safe_send(message, sources_t("src_url_formats", lang),
                     formats_keyboard(drafts, lang))
    return SRC_URL_FORMATS


def fetch_article_safe(url: str) -> dict:
    """Havolani o'qiydi (thread'da chaqiriladi, istisno tashlamaydi)."""
    try:
        from services.sources.url_extractor import fetch_and_extract
        return fetch_and_extract(url)
    except Exception as exc:  # noqa: BLE001
        logger.info("manbalar: havola o'qishda xato: %s", exc)
        return {"ok": False, "error_code": "network_error", "message": None}


async def url_format_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):
    """🎛 Format tanlandi → preview."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return SRC_URL_FORMATS
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    key = _payload(query.data)
    drafts = list(context.user_data.get(UD_DRAFTS) or [])
    chosen = next((item for item in drafts if item.get("format") == key), None)
    if chosen is None:
        await _safe_edit(query, sources_t("src_url_formats", lang),
                         formats_keyboard(drafts, lang))
        return SRC_URL_FORMATS

    context.user_data[UD_FORMAT] = key
    context.user_data[UD_PREVIEW] = {
        "mode": "url",
        "format": key,
        "text": chosen.get("text") or "",
        "ai": bool(chosen.get("ai")),
    }
    await _send_preview(query, context, lang)
    return SRC_PREVIEW


# ============================================================
# 📝 UMUMIY PREVIEW (URL / RSS qoralamasi / Recycle)
# ============================================================
async def _send_preview(target, context, lang: str) -> bool:
    """Tayyor post preview'ini yuboradi (4 amal bilan)."""
    preview = dict(context.user_data.get(UD_PREVIEW) or {})
    text = str(preview.get("text") or "")
    if preview.get("mode") == "url":
        head = sources_t("src_url_draft_title", lang,
                         label=format_label(preview.get("format", ""), lang))
        foot = sources_t("src_url_draft_foot", lang)
        if not preview.get("ai"):
            foot = f"{foot}\n{sources_t('src_url_local_note', lang)}"
    elif preview.get("mode") == "recycle":
        head = "♻️ <b>YANGILANGAN POST</b>\n\n"
        foot = sources_t("src_url_draft_foot", lang)
        similarity = preview.get("similarity")
        if similarity is not None:
            foot = (
                f"{foot}\n\n" + sources_t(
                    "src_rec_similarity", lang,
                    similarity=int(similarity),
                    threshold=int(preview.get("threshold") or 75))
            )
    else:
        head = "📝 <b>QORALAMA</b>\n\n"
        foot = sources_t("src_url_draft_foot", lang)
    body = f"{head}{_safe_preview(text)}{foot}"
    if hasattr(target, "edit_message_text"):
        return await _safe_edit(target, body, preview_keyboard(lang))
    return await _safe_send(target, body, preview_keyboard(lang))


async def preview_action_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """📅 / 🚀 / 🔄 — preview amallari."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return SRC_PREVIEW
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    action = _payload(query.data)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    preview = dict(context.user_data.get(UD_PREVIEW) or {})

    if not channel_id or not preview.get("text"):
        await _safe_edit(query, sources_t("src_stale", lang))
        clear_sources_session(context)
        return ConversationHandler.END

    # --- 📅 Rejalashtirish ---
    if action == "sched":
        await _safe_edit(query, sources_t("src_schedule_prompt", lang),
                         get_cancel_keyboard(lang))
        return SRC_TIME_INPUT

    # --- 🚀 Hozir chiqarish (navbat orqali — scheduler chiqaradi) ---
    if action == "now":
        post_id = await _write_post(user_id, channel_id, preview.get("text"),
                                    None)
        if not post_id:
            await _safe_edit(query, sources_t("src_write_failed", lang))
            return SRC_PREVIEW
        draft_id = preview.get("draft_id")
        if draft_id:
            try:
                await db.run_db(db.set_source_draft_status, int(draft_id),
                                user_id, "queued", int(post_id))
            except Exception:  # noqa: BLE001
                logger.debug("manbalar: qoralama statusi yangilanmadi",
                             exc_info=True)
        clear_sources_session(context)
        await _safe_edit(query, sources_t("src_publish_queued", lang))
        return ConversationHandler.END

    # --- 🔄 Boshqa variant ---
    if action == "regen":
        return await _regenerate(query, context, user_id, channel_id, lang)

    await _safe_edit(query, sources_t("src_stale", lang))
    return SRC_PREVIEW


async def _regenerate(query, context, user_id: int, channel_id: str,
                      lang: str) -> int:
    """🔄 Yangi variant (URL → qayta generatsiya; recycle → qayta urinish)."""
    preview = dict(context.user_data.get(UD_PREVIEW) or {})
    mode = str(preview.get("mode") or "")

    if mode == "url":
        article = dict(context.user_data.get(UD_ARTICLE) or {})
        service = new_url_service()
        try:
            result = await service.build_drafts(
                context.user_data.get(UD_URL), user_id=user_id, lang=lang,
                db_module=db, article=article,
                dna_block=await _dna_block(user_id, channel_id, lang),
                allow_local=False)
        except Exception:  # noqa: BLE001
            logger.exception("manbalar: qayta generatsiya xatosi")
            result = {}
        drafts = list(result.get("drafts") or [])
        if not drafts:
            await _safe_edit(query, sources_t("src_regen_failed", lang),
                             preview_keyboard(lang))
            return SRC_PREVIEW
        context.user_data[UD_DRAFTS] = drafts
        key = str(preview.get("format") or "")
        chosen = next((item for item in drafts if item.get("format") == key),
                      drafts[0])
        context.user_data[UD_PREVIEW] = {
            "mode": "url", "format": chosen.get("format"),
            "text": chosen.get("text") or "", "ai": bool(chosen.get("ai")),
        }
        await _safe_edit(query, sources_t("src_regen_done", lang))
        await _send_preview(query.message, context, lang)
        return SRC_PREVIEW

    if mode == "recycle":
        original = str(preview.get("original") or "")
        if not original:
            await _safe_edit(query, sources_t("src_regen_failed", lang),
                             preview_keyboard(lang))
            return SRC_PREVIEW
        service = new_recycle_service()
        try:
            result = await service.generate(
                original, user_id=user_id, lang=lang, db_module=db,
                channel_id=channel_id,
                dna_block=await _dna_block(user_id, channel_id, lang))
        except Exception:  # noqa: BLE001
            logger.exception("manbalar: recycle qayta urinish xatosi")
            result = {}
        if not result.get("ok"):
            await _safe_edit(query, sources_t("src_rec_blind_repost", lang)
                             if result.get("error_code") == "BLIND_REPOST"
                             else sources_t("src_regen_failed", lang),
                             preview_keyboard(lang))
            return SRC_PREVIEW
        context.user_data[UD_PREVIEW] = {
            "mode": "recycle", "text": result.get("text") or "",
            "original": original, "ai": True,
        }
        await _safe_edit(query, sources_t("src_regen_done", lang))
        await _send_preview(query.message, context, lang)
        return SRC_PREVIEW

    await _safe_edit(query, sources_t("src_regen_failed", lang),
                     preview_keyboard(lang))
    return SRC_PREVIEW


async def schedule_time_received(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """📅 Vaqt matni → post navbatga yoziladi."""
    message = getattr(update, "message", None)
    if message is None:
        return SRC_TIME_INPUT
    lang = _lang(context)
    user_id = update.effective_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    preview = dict(context.user_data.get(UD_PREVIEW) or {})
    if not channel_id or not preview.get("text"):
        await _safe_send(message, sources_t("src_stale", lang))
        clear_sources_session(context)
        return ConversationHandler.END

    raw = str(getattr(message, "text", "") or "").strip()
    from utils.helpers import parse_schedule_input
    moment, reason = parse_schedule_input(raw)
    if moment is None:
        await _safe_send(message, sources_t("src_bad_time", lang),
                         get_cancel_keyboard(lang))
        return SRC_TIME_INPUT

    post_id = await _write_post(user_id, channel_id, preview.get("text"),
                                moment)
    if not post_id:
        await _safe_send(message, sources_t("src_write_failed", lang))
        return SRC_TIME_INPUT

    draft_id = preview.get("draft_id")
    if draft_id:
        try:
            await db.run_db(db.set_source_draft_status, int(draft_id),
                            user_id, "queued", int(post_id))
        except Exception:  # noqa: BLE001
            logger.debug("manbalar: qoralama statusi yangilanmadi",
                         exc_info=True)

    when = format_datetime(moment, lang)
    clear_sources_session(context)
    await _safe_send(message, sources_t("src_scheduled_ok", lang, time=when))
    return ConversationHandler.END


async def _write_post(user_id: int, channel_id: str, text: str,
                      scheduled_time) -> int:
    """Yagona yozish nuqtasi — ``scheduled_posts`` navbati (``add_post``)."""
    content = str(text or "").strip()
    if not content or not channel_id:
        return 0
    moment = scheduled_time or datetime.now(tashkent_tz)
    try:
        post_id = await db.run_db(
            db.add_post,
            user_id=int(user_id),
            channel_id=str(channel_id),
            post_type="text",
            content=content,
            file_id=None,
            scheduled_time=moment,
        )
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: post yozilmadi (user=%s)", user_id)
        return 0
    return int(post_id or 0)


# ============================================================
# 📡 RSS / ATOM OQIMI
# ============================================================
async def _render_rss_menu(query, context, user_id: int, channel_id: str,
                           channel_title: str, lang: str) -> int:
    """Manbalar ro'yxatini chizadi."""
    sources = []
    try:
        sources = await db.run_db(db.list_content_sources, user_id)
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: manbalar ro'yxati o'qilmadi")
        sources = []

    limit = int(getattr(db, "CONTENT_SOURCES_LIMIT", 10))
    if not sources:
        await _safe_edit(query, sources_t("src_rss_empty", lang),
                         source_list_keyboard([], channel_id, lang))
        return SRC_RSS_MENU

    lines = [sources_t("src_rss_title", lang, channel=channel_title,
                       count=len(sources), limit=limit)]
    for item in sources[:limit]:
        icon = "▶️" if item.get("enabled") else "⏸"
        lines.append(sources_t("src_rss_source_item", lang, icon=icon,
                               title=html_escape(str(item.get("title")
                                                     or item.get("source_url")
                                                     or "—")[:60]),
                               minutes=int(item.get("interval_minutes")
                                           or DEFAULT_INTERVAL_MINUTES)))
    await _safe_edit(query, "\n".join(lines),
                     source_list_keyboard(sources, channel_id, lang))
    return SRC_RSS_MENU


async def rss_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📡 Manba amallari: qo'shish / tekshirish / yoqish / avtopublish / o'chirish."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return SRC_RSS_MENU
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    data = str(getattr(query, "data", "") or "")
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    channel_title = html_escape(str(context.user_data.get(UD_TITLE) or "Kanal"))
    if not channel_id:
        await _safe_edit(query, sources_t("src_stale", lang))
        return ConversationHandler.END

    # --- ➕ Yangi manba ---
    if data == CB_SOURCE_RSS_ADD:
        sources = []
        try:
            sources = await db.run_db(db.list_content_sources, user_id)
        except Exception:  # noqa: BLE001
            sources = []
        if len(sources) >= int(getattr(db, "CONTENT_SOURCES_LIMIT", 10)):
            await _safe_edit(query,
                             sources_t("src_rss_limit", lang,
                                       limit=getattr(db,
                                                     "CONTENT_SOURCES_LIMIT",
                                                     10)),
                             source_list_keyboard(sources, channel_id, lang))
            return SRC_RSS_MENU
        await _safe_edit(query, sources_t("src_rss_ask_url", lang),
                         get_cancel_keyboard(lang))
        return SRC_RSS_URL

    source_id = _payload(data)
    try:
        source_id_int = int(source_id)
    except (TypeError, ValueError):
        source_id_int = 0
    if not source_id_int:
        return await _render_rss_menu(query, context, user_id, channel_id,
                                      channel_title, lang)

    # --- 🔄 Hoziroq tekshirish ---
    if data.startswith(CB_SOURCE_RSS_CHECK):
        source = await db.run_db(db.get_content_source, source_id_int, user_id)
        if source is None:
            await _safe_edit(query, sources_t("src_rss_draft_notfound", lang))
            return await _render_rss_menu(query, context, user_id, channel_id,
                                          channel_title, lang)
        await _safe_edit(query, sources_t("src_rss_checking", lang))
        return await _check_source_now(query, context, user_id, source, lang,
                                       channel_title)

    # --- ▶️/⏸ Yoqish / to'xtatish ---
    if data.startswith(CB_SOURCE_RSS_TOGGLE):
        source = await db.run_db(db.get_content_source, source_id_int, user_id)
        enabled = not bool((source or {}).get("enabled"))
        ok = await db.run_db(db.set_content_source_enabled, source_id_int,
                             user_id, enabled)
        if ok:
            await _safe_edit(query, sources_t("src_rss_enabled" if enabled
                                              else "src_rss_disabled", lang))
        return await _render_rss_menu(query, context, user_id, channel_id,
                                      channel_title, lang)

    # --- 🤖 Avtopublish ---
    if data.startswith(CB_SOURCE_RSS_AUTO):
        source = await db.run_db(db.get_content_source, source_id_int, user_id)
        enabled = not bool((source or {}).get("autopublish"))
        await db.run_db(db.set_content_source_autopublish, source_id_int,
                        user_id, enabled)
        await _safe_edit(query, sources_t("src_rss_auto_enabled" if enabled
                                          else "src_rss_auto_disabled", lang))
        return await _render_rss_menu(query, context, user_id, channel_id,
                                      channel_title, lang)

    # --- 🗑 O'chirish ---
    if data.startswith(CB_SOURCE_RSS_DEL):
        await db.run_db(db.delete_content_source, source_id_int, user_id)
        await _safe_edit(query, sources_t("src_rss_deleted", lang))
        return await _render_rss_menu(query, context, user_id, channel_id,
                                      channel_title, lang)

    return await _render_rss_menu(query, context, user_id, channel_id,
                                  channel_title, lang)


async def _check_source_now(query, context, user_id: int, source: dict,
                            lang: str, channel_title: str) -> int:
    """Manbani Hoziroq tekshiradi (dublikatlar qayta ishlanmaydi)."""
    service = new_rss_service()
    dna_block = await _dna_block(user_id, str(source.get("channel_id") or ""),
                                 lang)
    try:
        result = await service.check_source(
            source, db_module=db, lang=lang, dna_block=dna_block,
            channel_title=channel_title)
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: manba tekshirilmadi (id=%s)",
                         source.get("id"))
        result = {"ok": False, "error_code": "fetch_failed"}

    if not result.get("ok"):
        await _safe_edit(query,
                         sources_t("src_rss_check_failed", lang,
                                   reason=html_escape(str(result.get(
                                       "error_code") or "—"))))
        return await _render_rss_menu(query, context, user_id,
                                      str(context.user_data.get(UD_CHANNEL)
                                          or ""), channel_title, lang)

    new_items = len(list(result.get("new") or []))
    duplicates = int(result.get("duplicates") or 0)
    if not new_items:
        await _safe_edit(query, sources_t("src_rss_check_empty", lang))
        return await _render_rss_menu(query, context, user_id,
                                      str(context.user_data.get(UD_CHANNEL)
                                          or ""), channel_title, lang)

    await _safe_edit(query, sources_t("src_rss_check_done", lang,
                                      new=new_items, duplicates=duplicates))
    # Birinchi yangi qoralama — darhol preview (tasdiqlash oynasi).
    drafts = list(result.get("drafts") or [])
    if drafts:
        first = dict(drafts[0])
        context.user_data[UD_PREVIEW] = {
            "mode": "draft",
            "text": first.get("text") or "",
            "draft_id": first.get("draft_id"),
            "ai": bool(first.get("ai_used")),
        }
        await _send_preview(query.message, context, lang)
        return SRC_PREVIEW
    return await _render_rss_menu(query, context, user_id,
                                  str(context.user_data.get(UD_CHANNEL) or ""),
                                  channel_title, lang)


async def rss_url_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """➕ Yangi manba havolasi → interval so'rovi."""
    message = getattr(update, "message", None)
    if message is None:
        return SRC_RSS_URL
    lang = _lang(context)
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    if not channel_id:
        await _safe_send(message, sources_t("src_stale", lang))
        return ConversationHandler.END

    raw = str(getattr(message, "text", "") or "").strip()
    guard = validate_public_url(raw)
    if not guard.get("ok"):
        await _safe_send(message, sources_t("src_rss_invalid_url", lang),
                         get_cancel_keyboard(lang))
        return SRC_RSS_URL

    context.user_data["src_new_source_url"] = str(guard.get("url") or raw)
    await _safe_send(message, sources_t("src_rss_ask_interval", lang),
                     get_cancel_keyboard(lang))
    return SRC_RSS_INTERVAL


async def rss_interval_received(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """⏱ Interval → manba saqlanadi (15..1440 daqiqa, qat'iy clamp)."""
    message = getattr(update, "message", None)
    if message is None:
        return SRC_RSS_INTERVAL
    lang = _lang(context)
    user_id = update.effective_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    url = str(context.user_data.get("src_new_source_url") or "")
    if not channel_id or not url:
        await _safe_send(message, sources_t("src_stale", lang))
        return ConversationHandler.END

    raw = str(getattr(message, "text", "") or "").strip()
    minutes = parse_interval_input(raw)
    if minutes is None:
        await _safe_send(message, sources_t("src_rss_invalid_interval", lang),
                         get_cancel_keyboard(lang))
        return SRC_RSS_INTERVAL
    minutes = clamp_interval(minutes)

    source_id = await db.run_db(db.create_content_source, user_id, channel_id,
                                url, minutes, False, url[:120])
    context.user_data.pop("src_new_source_url", None)
    if not source_id:
        await _safe_send(message, sources_t("src_rss_limit", lang,
                                            limit=getattr(
                                                db, "CONTENT_SOURCES_LIMIT",
                                                10)))
        return SRC_RSS_MENU

    await _safe_send(message,
                     sources_t("src_rss_added", lang,
                               title=html_escape(url[:80]), minutes=minutes))
    return await _render_rss_menu(message, context, user_id, channel_id,
                                  html_escape(str(context.user_data.get(
                                      UD_TITLE) or "Kanal")), lang)


# ============================================================
# ♻️ CONTENT RECYCLE
# ============================================================
async def _render_recycle_list(query, context, user_id: int, channel_id: str,
                               channel_title: str, lang: str) -> int:
    """14+ kunlik, yaxshi ko'rsatkichli postlar ro'yxati."""
    try:
        result = await load_recycle_candidates(channel_id, user_id,
                                               db_module=db,
                                               min_age_days=MIN_AGE_DAYS)
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: recycle nomzodlari o'qilmadi")
        result = {"ok": False, "candidates": []}

    candidates = list(result.get("candidates") or [])
    context.user_data[UD_RECYCLE] = candidates
    if not candidates:
        note = ""
        if result.get("metrics_available") is False:
            note = f"\n\n{sources_t('src_rec_no_metrics', lang)}"
        await _safe_edit(query,
                         f"{sources_t('src_rec_empty', lang)}{note}",
                         recycle_keyboard([], lang))
        return SRC_RECYCLE_LIST

    await _safe_edit(query, sources_t("src_rec_title", lang,
                                      channel=channel_title),
                     recycle_keyboard(candidates, lang))
    return SRC_RECYCLE_LIST


async def recycle_pick_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """♻️ Nomzod tanlandi → AI yangilaydi → preview."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return SRC_RECYCLE_LIST
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")

    try:
        index = int(_payload(query.data))
    except (TypeError, ValueError):
        index = -1
    candidates = list(context.user_data.get(UD_RECYCLE) or [])
    if index < 0 or index >= len(candidates) or not channel_id:
        await _safe_edit(query, sources_t("src_stale", lang))
        return SRC_RECYCLE_LIST

    candidate = dict(candidates[index])
    context.user_data[UD_RECYCLE_IDX] = index
    await _safe_edit(query, sources_t("src_rec_generating", lang))

    service = new_recycle_service()
    try:
        result = await service.generate(
            candidate.get("text") or "", user_id=user_id, lang=lang,
            db_module=db, channel_id=channel_id,
            dna_block=await _dna_block(user_id, channel_id, lang))
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: recycle generatsiya xatosi")
        result = {"ok": False, "error_code": "AI_FAILED"}

    if not result.get("ok"):
        if result.get("error_code") == "BLIND_REPOST":
            await _safe_edit(query, sources_t("src_rec_blind_repost", lang),
                             recycle_keyboard(candidates, lang))
        else:
            await _safe_edit(query, sources_t("src_rec_failed", lang),
                             recycle_keyboard(candidates, lang))
        return SRC_RECYCLE_LIST

    context.user_data[UD_PREVIEW] = {
        "mode": "recycle",
        "text": result.get("text") or "",
        "original": candidate.get("text") or "",
        "ai": True,
        "similarity": int(round(float(result.get("similarity") or 0.0) * 100)),
        "threshold": int(round(float(result.get("threshold") or 0.75) * 100)),
    }
    await _send_preview(query.message, context, lang)
    return SRC_PREVIEW


# ============================================================
# 🗂 QORALAMALAR (tasdiqlash kutayotgan post loyihalari)
# ============================================================
async def _render_drafts(query, context, user_id: int, channel_id: str,
                         channel_title: str, lang: str) -> int:
    """Tasdiqlash kutayotgan qoralamalar ro'yxati."""
    drafts = []
    try:
        drafts = await db.run_db(db.list_source_drafts, user_id, "pending")
    except Exception:  # noqa: BLE001
        logger.exception("manbalar: qoralamalar o'qilmadi")
        drafts = []

    if not drafts:
        await _safe_edit(query, sources_t("src_rss_drafts_empty", lang),
                         drafts_keyboard([], lang))
        return SRC_DRAFTS

    lines = [sources_t("src_rss_drafts_title", lang, count=len(drafts),
                       channel=channel_title)]
    for item in drafts[:MAX_DRAFT_BUTTONS]:
        lines.append(sources_t("src_rss_draft_item", lang,
                               title=html_escape(str(item.get("title")
                                                     or "—")[:80])))
    await _safe_edit(query, "\n".join(lines),
                     drafts_keyboard(drafts, lang))
    return SRC_DRAFTS


async def draft_action_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE):
    """📅 Rejalashtirish / 🗑 O'chirish — qoralama kartochkasi."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return SRC_DRAFTS
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = str(context.user_data.get(UD_CHANNEL) or "")

    parts = str(getattr(query, "data", "") or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    try:
        draft_id = int(parts[2]) if len(parts) > 2 else 0
    except (TypeError, ValueError):
        draft_id = 0

    draft = None
    if draft_id:
        try:
            draft = await db.run_db(db.get_source_draft, draft_id, user_id)
        except Exception:  # noqa: BLE001
            draft = None
    if draft is None:
        await _safe_edit(query, sources_t("src_rss_draft_notfound", lang))
        return await _render_drafts(query, context, user_id, channel_id,
                                    html_escape(str(context.user_data.get(
                                        UD_TITLE) or "Kanal")), lang)

    # --- 🗑 O'chirish ---
    if action == "del":
        try:
            await db.run_db(db.set_source_draft_status, draft_id, user_id,
                            "dismissed", None)
        except Exception:  # noqa: BLE001
            logger.debug("manbalar: qoralama o'chirilmadi", exc_info=True)
        await _safe_edit(query, sources_t("src_rss_draft_deleted", lang))
        return await _render_drafts(query, context, user_id, channel_id,
                                    html_escape(str(context.user_data.get(
                                        UD_TITLE) or "Kanal")), lang)

    # --- 📅 Rejalashtirish: qoralama matni preview'ga tushadi ---
    context.user_data[UD_PREVIEW] = {
        "mode": "draft",
        "text": draft.get("content") or "",
        "draft_id": draft_id,
        "ai": True,
    }
    await _send_preview(query, context, lang)
    return SRC_PREVIEW


__all__ = [
    "SRC_HUB", "SRC_URL_INPUT", "SRC_URL_FORMATS", "SRC_PREVIEW",
    "SRC_TIME_INPUT", "SRC_RSS_MENU", "SRC_RSS_URL", "SRC_RSS_INTERVAL",
    "SRC_RECYCLE_LIST", "SRC_DRAFTS",
    "UD_CHANNEL", "UD_TITLE", "UD_ARTICLE", "UD_URL", "UD_DRAFTS",
    "UD_FORMAT", "UD_PREVIEW", "UD_RECYCLE", "UD_RECYCLE_IDX",
    "clear_sources_session", "sources_hub_keyboard", "formats_keyboard",
    "preview_keyboard", "source_list_keyboard", "drafts_keyboard",
    "recycle_keyboard", "new_url_service", "new_rss_service",
    "new_recycle_service", "fetch_article_safe",
    "channel_sources_entry", "sources_hub_callback", "sources_back_callback",
    "source_cancel_callback", "sources_stale_callback",
    "url_text_received", "url_format_callback", "preview_action_callback",
    "schedule_time_received", "rss_menu_callback", "rss_url_received",
    "rss_interval_received", "recycle_pick_callback", "draft_action_callback",
    "FORMAT_KEYS", "MIN_INTERVAL_MINUTES", "DEFAULT_INTERVAL_MINUTES",
    "CB_CHANNEL_SOURCES",
]
