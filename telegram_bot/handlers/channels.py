import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import (
    get_cancel_keyboard, get_main_keyboard, get_tone_keyboard,
    TONE_LABELS, TONE_LABELS_RU, BTN_BACK_RU,
    is_menu_text, tone_from_text, tone_labels,
)
from keyboards.callback_data import CB_CHANNEL_VOICE
from keyboards.inline import (
    render_channel_panel, render_channel_settings, render_channels_list,
    render_my_channels_list,
)
from locales.translations import get_lang, safe_t, normalize_lang
from translations import channels_queue_t
from utils.helpers import html_escape
from utils.fsm_state import active_conversation_state
from utils.ai_agent import analyze_channel_voice
from utils.channel_reader import read_channel_posts

logger = logging.getLogger(__name__)

ADD_CHANNEL = 301
SET_TONE = 302

# Kanal manbasini aniqlash: foydalanuvchi forward, @username, raqamli ID
# yoki t.me/havola yuborishi mumkin — oqim shu to'rt formatning birini
# qabul qiladi (avval faqat forward/ID/@username ishlagan).
_T_ME_LINK_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/([A-Za-z][A-Za-z0-9_]{3,31})/?$", re.IGNORECASE
)
_T_ME_INVITE_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?t\.me/(?:\+|joinchat/)", re.IGNORECASE
)


def parse_channel_target(text: str):
    """Matndan kanal manbasini ajratadi: (target, xato_html|None).

    Qaytadi:
      * ``(-1001234567890, None)`` — raqamli ID;
      * ``("@kanal", None)`` — username (t.me/kanal ham shunga aylantiriladi);
      * ``(None, xato)`` — tushunarsiz yoki yopiq (invite) havola.
    """
    text = (text or "").strip()
    if not text:
        return None, (
            "❌ Bo'sh xabar qabul qilindi. Kanalni <b>forward</b> qiling, "
            "<code>@username</code>, ID yoki <code>t.me/kanal</code> havolasini yuboring."
        )
    if _T_ME_INVITE_RE.match(text):
        return None, (
            "🔒 <b>Yopiq kanal (invite) havolasi orqali ulab bo'lmaydi.</b>\n\n"
            "Bot kanalda administrator bo'lgani uchun <code>@username</code> "
            "yoki kanaldan istalgan xabarni <b>forward</b> qiling — shunda "
            "kanalni aniqlaymiz."
        )
    m = _T_ME_LINK_RE.match(text)
    if m:
        return f"@{m.group(1)}", None
    if text.startswith("@") and len(text) > 1:
        return text, None
    if text.lstrip("-").isdigit():
        return int(text), None
    return None, None  # noma'lum format — chaqiruvchi o'zi yo'naltiradi


def _retry_verify_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Tekshiruvdan o'tmagan kanal uchun 'qayta urinish' tugmasi (uz/ru).

    Foydalanuvchi botni admin qilgach xabarni qayta forward qilmasdan,
    shu tugmani bosish bilan tekshiruvni yangilaydi.
    """
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            safe_t("ch_retry_btn", lang),
            callback_data="add_channel_retry",
        ),
    ]])

# Tarif limiti (FREE vs PRO) tugaganda ko'rsatiladigan xabar va PRO tugmasi.
# (eski chaqiruvlar uchun o'zbekcha konstanta saqlanadi)
CHANNEL_LIMIT_MSG = (
    "🚫 <b>Kanal limiti tugadi!</b>\n\n"
    "Sizda hozir <b>{current}/{max}</b> ta kanal ulangan.\n"
    "Free tarifida maksimal <b>{max}</b> ta kanal ulash mumkin.\n\n"
    "⭐️ Ushbu imkoniyatdan cheksiz foydalanish uchun PRO tarifiga o'ting."
)

PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarifga o'tish", callback_data="sub_open")],
])


def _channel_limit_text(lang: str, current: int, max_ch: int) -> str:
    """Kanal limiti xabari — foydalanuvchi tilida (uz/ru)."""
    return safe_t("ch_limit_msg", normalize_lang(lang), current=current, max=max_ch)


def _pro_upgrade_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """PRO tarifga o'tish inline tugmasi — foydalanuvchi tilida."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_t("ch_pro_btn", lang), callback_data="sub_open")],
    ])


def _empty_channels_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """Kanal yo'q paytda ko'rsatiladigan tugmalar (qo'shish + yopish, uz/ru)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(safe_t("ch_add_btn", lang), callback_data="add_channel_start")],
        [InlineKeyboardButton(safe_t("pend_close_btn", lang), callback_data="close_msg")],
    ])


# ============================================================
# 📢 KANALLARIM — MASTER PLAN STANDARTI (PostAssist V2, 4-mikro qadam)
# ============================================================
# Ekran ierarxiyasi (asosiy menyu → bo'lim → kanal → amal):
#
#   [📢 Kanallarim]            → ulangan kanallar ro'yxati + [➕ Kanal qo'shish]
#     └─ kanal tanlandi        → kanal boshqaruv ekrani:
#            [➕ Post yaratish]
#            [📅 Rejalashtirilgan]   [📊 Statistika]
#            [⚙️ Kanal sozlamalari]  [◀️ Orqaga]
#
# MUHIM UX QOIDASI: kanal ichidagi amallar asosiy menyuga CHIQIB KETMAYDI —
# har bir tugma shu kanal konteksti bilan ishlaydi (``ch_op:``/``ch_sch:``/
# ``ch_st:``/``ch_np:`` callback'lari channel_id payload'ini olib yuradi),
# [◀️ Orqaga] esa kanallar ro'yxatiga qaytaradi.


async def _owned_channel(user_id: int, channel_id: str):
    """Kanal AYNAN shu foydalanuvchiga tegishlimi (fail-closed tekshiruv).

    Qaytadi: ``(channel_id, title, tone)`` yoki topilmasa ``None``.
    Har bir kanal-kontekstli callback shu funksiyadan o'tadi — boshqa
    foydalanuvchining kanali hech qachon ochilmaydi.
    """
    channels = await db.run_db(db.get_user_channels_with_tone, user_id)
    target = str(channel_id or "").strip()
    for ch in channels or []:
        if str(ch[0]) == target:
            return ch
    return None


def _channel_title(channel) -> str:
    """Kanal sarlavhasi — HTML-xavfsiz, bo'sh bo'lsa ham tugma buzilmaydi."""
    title = (channel[1] if channel and len(channel) > 1 else "") or ""
    return html_escape(title.strip() or "Kanal")


async def _send_channels_list(msg, user_id: int, lang: str):
    """📢 Kanallarim ro'yxatini YANGI xabar sifatida yuboradi."""
    channels = await db.run_db(db.get_user_channels_with_tone, user_id)
    if not channels:
        await msg.reply_text(
            channels_queue_t("cq_ch_empty", lang),
            reply_markup=_empty_channels_keyboard(lang),
            parse_mode="HTML",
        )
        return
    await msg.reply_text(
        channels_queue_t("cq_ch_list_title", lang, count=len(channels)),
        reply_markup=render_my_channels_list(channels, lang),
        parse_mode="HTML",
    )


async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📢 Kanallarim — ulangan kanallar ro'yxati + [➕ Kanal qo'shish].

    Ro'yxatdagi har bir kanal BITTA tugma: bosilganda kanal boshqaruv
    ekrani ochiladi (:func:`channel_open_callback`).
    """
    lang = get_lang(context)
    user_id = update.effective_user.id
    await _send_channels_list(update.message, user_id, lang)
    return ConversationHandler.END


async def _safe_edit(query, text: str, markup):
    """Xabarni EDIT qiladi (o'chirmaydi) — xatoda jim qoladi.

    Kanal ekranlari orasidagi navigatsiya bitta xabar ichida bo'ladi:
    chatda "phantom" xabarlar to'planmaydi.
    """
    try:
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:  # pragma: no cover — Telegram "message is not modified" va h.k.
        logger.debug("Kanal ekranini edit qilib bo'lmadi", exc_info=True)
        return False


async def channels_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[◀️ Orqaga] — kanal ekranidan kanallar RO'YXATIGA qaytadi.

    Asosiy menyuga CHIQMAYDI: foydalanuvchi «📢 Kanallarim» bo'limi ichida
    qoladi (master plan 2-band talabi).
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    channels = await db.run_db(db.get_user_channels_with_tone, user_id)
    if not channels:
        await _safe_edit(query, channels_queue_t("cq_ch_empty", lang),
                         _empty_channels_keyboard(lang))
        return ConversationHandler.END
    await _safe_edit(
        query,
        channels_queue_t("cq_ch_list_title", lang, count=len(channels)),
        render_my_channels_list(channels, lang),
    )
    return ConversationHandler.END


async def channel_open_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlandi → KANAL BOSHQARUV EKRANI (speksdagi 5 tugma)."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        await _safe_edit(query, channels_queue_t("cq_ch_not_found", lang),
                         _empty_channels_keyboard(lang))
        return ConversationHandler.END

    await _safe_edit(
        query,
        channels_queue_t("cq_ch_panel_title", lang, channel=_channel_title(channel)),
        render_channel_panel(channel_id, lang),
    )
    return ConversationHandler.END


async def channel_scheduled_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Rejalashtirilgan — FAQAT shu kanal postlari (vaqt bo'yicha).

    Ro'yxat «📅 Rejalashtirilgan» bo'limi bilan BIR XIL formatda chiziladi
    (``handlers.queue._format_queue_item``), har bir post ostida
    [✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish] [🗑 O'chirish].
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        await _safe_edit(query, channels_queue_t("cq_ch_not_found", lang),
                         _empty_channels_keyboard(lang))
        return ConversationHandler.END

    # Lokal import: modul sikli (queue ↔ channels) oldini oladi.
    from handlers.queue import build_channel_scheduled_view

    text, markup = await build_channel_scheduled_view(
        user_id, channel_id, _channel_title(channel), lang,
    )
    await _safe_edit(query, text, markup)
    return ConversationHandler.END


async def channel_stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 Statistika — FAQAT shu kanal bo'yicha dashboard (kanal ichida)."""
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        await _safe_edit(query, channels_queue_t("cq_ch_not_found", lang),
                         _empty_channels_keyboard(lang))
        return ConversationHandler.END

    title = _channel_title(channel)
    try:
        from handlers.analytics import _build_dashboard

        stats = await db.run_db(db.get_channel_post_stats, user_id, channel_id)
        text = _build_dashboard(stats or {}, title, lang)
    except Exception:
        # Statistika o'qilmasa ham foydalanuvchi JAVOB olishi shart —
        # ekran "qotib qolgan" bo'lib ko'rinmasligi kerak.
        logger.exception("Kanal statistikasini qurishda xato (channel=%s)", channel_id)
        text = channels_queue_t("cq_ch_stats_empty", lang, channel=title)

    await _safe_edit(query, text, render_channel_panel(channel_id, lang))
    return ConversationHandler.END


async def channel_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """⚙️ Kanal sozlamalari — uslub / AI ovoz tahlili / kanalni uzish.

    ``ch_set:<id>`` callback'i IKKI ma'noda ishlatiladi (orqaga moslik):
      * kanal boshqaruv ekranidan bosilsa — shu SOZLAMALAR ekrani ochiladi;
      * sozlamalar ekranidagi «🎨 Uslub» tugmasi bosilsa — eski, sinovdan
        o'tgan uslub tanlash oqimi (``tone_menu_callback``) ishga tushadi.
    Farq ``user_data`` dagi bayroq orqali aniqlanadi, ya'ni eski chat
    xabarlaridagi ``ch_set:`` tugmalari avvalgidek uslub menyusini ochadi.
    """
    query = update.callback_query
    lang = get_lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    # 2-bosqich: sozlamalar ekrani ALLAQACHON ochiq → «🎨 Uslub» bosildi.
    if context.user_data.get("ch_settings_open") == channel_id:
        context.user_data.pop("ch_settings_open", None)
        return await tone_menu_callback(update, context)

    try:
        await query.answer()
    except Exception:
        pass

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        # Kanal ro'yxatda yo'q (eski xabar / boshqa foydalanuvchi) — eski
        # uslub oqimiga tushamiz, u o'zi xavfsiz yakunlanadi.
        return await tone_menu_callback(update, context)

    context.user_data["ch_settings_open"] = channel_id
    await _safe_edit(
        query,
        channels_queue_t("cq_ch_settings_title", lang, channel=_channel_title(channel)),
        render_channel_settings(channel_id, lang),
    )
    return ConversationHandler.END


async def channel_new_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """➕ Post yaratish — shu kanal ALLAQACHON tanlangan holda post oqimi.

    Foydalanuvchidan kanalni QAYTA so'ramaymiz: ``new_post`` oqimining
    ``GET_CONTENT`` holatiga to'g'ridan-to'g'ri o'tamiz (kanal konteksti
    ``user_data`` ga yoziladi), ya'ni ortiqcha qadam yo'q.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        await _safe_edit(query, channels_queue_t("cq_ch_not_found", lang),
                         _empty_channels_keyboard(lang))
        return ConversationHandler.END

    from handlers.new_post import GET_CONTENT

    title = _channel_title(channel)
    context.user_data["selected_channel_id"] = str(channel_id)
    context.user_data["selected_channel_title"] = (channel[1] or "Kanal")
    try:
        await query.message.reply_text(
            channels_queue_t("cq_ch_post_intro", lang, channel=title),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
    except Exception:  # pragma: no cover
        logger.debug("Kanal post yo'riqnomasini yuborib bo'lmadi", exc_info=True)
    return GET_CONTENT


async def _send_add_channel_instructions(bot, chat_id: int, lang: str = "uz"):
    bot_obj = await bot.get_me()
    await bot.send_message(
        chat_id=chat_id,
        text=safe_t("ch_add_instructions", lang, bot=bot_obj.username),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )


async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Yangi oqim: oldingi urinishdan qolgan "kutilayotgan kanal"ni tozalaymiz,
    # shunda 🔁 tugma eskirgan manzilni qayta tekshirmaydi.
    context.user_data.pop("add_channel_pending", None)
    await _send_add_channel_instructions(context.bot, update.effective_chat.id, get_lang(context))
    return ADD_CHANNEL


async def add_channel_inline_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali kanal ulash oqimini boshlash (ro'yxat/bo'sh ekran)."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    context.user_data.pop("add_channel_pending", None)
    await _send_add_channel_instructions(context.bot, query.from_user.id, get_lang(context))
    return ADD_CHANNEL


async def _verify_channel_permissions(bot, chat_id, user_id: int, is_admin_user: bool, lang: str = "uz"):
    """Bot va foydalanuvchi huquqlarini fail-closed tekshiradi.

    Qaytadi: (ok, error_html, real_channel_id, title)
    """
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramError as e:
        logger.warning("Kanal topilmadi (%s): %s", chat_id, e)
        return False, safe_t("ch_not_found", lang), None, None

    real_id = str(chat.id)
    title = chat.title or safe_t("ch_default_title", lang)

    try:
        bot_member = await bot.get_chat_member(chat.id, bot.id)
    except TelegramError as e:
        logger.warning("Bot a'zoligini tekshirib bo'lmadi (%s): %s", real_id, e)
        return False, safe_t("ch_cannot_verify", lang), None, None

    if bot_member.status not in ("administrator", "creator"):
        return False, safe_t("ch_not_admin", lang), None, None

    if chat.type == "channel" and bot_member.status == "administrator":
        if not getattr(bot_member, "can_post_messages", False):
            return False, safe_t("ch_no_post_permission", lang), None, None

    if not is_admin_user:
        try:
            user_member = await bot.get_chat_member(chat.id, user_id)
        except TelegramError as e:
            logger.warning("Foydalanuvchi huquqini tekshirib bo'lmadi (%s / %s): %s", real_id, user_id, e)
            return False, safe_t("ch_user_verify_fail", lang), None, None
        if user_member.status not in ("administrator", "creator"):
            return False, safe_t("ch_forbidden", lang), None, None

    return True, "", real_id, title


def _extract_forward_chat_id(msg):
    """Forward qilingan xabardan manba kanal/chat ID sini xavfsiz ajratadi.

    Bot API 7.0+ / python-telegram-bot 20+ da ``Message.forward_from_chat``
    olib tashlangan (o'rniga ``forward_origin`` keldi) — eski atributga
    to'g'ridan-to'g'ri murojaat qilish ``AttributeError`` bilan tugaydi va
    butun ``ADD_CHANNEL`` holati "qotib" qoladi (foydalanuvchiga javob
    yubormay handler ichida yiqiladi). Shu sababli ikkala API'ni ham
    ``getattr`` bilan, xatosiz tekshiramiz.
    """
    origin = getattr(msg, "forward_origin", None)
    if origin is not None:
        chat = getattr(origin, "chat", None)
        if chat is not None:
            return chat.id
        sender_chat = getattr(origin, "sender_chat", None)
        if sender_chat is not None:
            return sender_chat.id
    # Orqaga moslik: juda eski python-telegram-bot versiyalari uchun.
    legacy_chat = getattr(msg, "forward_from_chat", None)
    if legacy_chat is not None:
        return legacy_chat.id
    return None


async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal manba xabari: forward, @username, t.me/havola yoki ID.

    HARDENING: butun tanasi try/except bilan o'ralgan — kutilmagan xatolik
    (masalan, Telegram API'dagi kelajakdagi o'zgarish) botni "qotirmasligi",
    balki foydalanuvchiga tushunarli xabar bilan qayta urinishni taklif
    qilishi kerak (jim qolib ketish — eng yomon UX).
    """
    msg = update.effective_message
    lang = get_lang(context)
    try:
        raw_target = None
        forward_chat_id = _extract_forward_chat_id(msg)
        if forward_chat_id is not None:
            raw_target = forward_chat_id
        elif msg.text:
            target, err = parse_channel_target(msg.text)
            if err:
                await msg.reply_text(
                    err, reply_markup=get_cancel_keyboard(lang), parse_mode="HTML",
                )
                return ADD_CHANNEL
            if target is None:
                await msg.reply_text(
                    safe_t("ch_unknown_target", lang),
                    reply_markup=get_cancel_keyboard(lang),
                    parse_mode="HTML",
                )
                return ADD_CHANNEL
            raw_target = target
        else:
            await msg.reply_text(
                safe_t("ch_empty_target_short", lang),
                reply_markup=get_cancel_keyboard(lang),
            )
            return ADD_CHANNEL

        return await _link_channel(update, context, raw_target)
    except Exception:
        logger.exception("channel_received: kutilmagan xatolik — foydalanuvchi qayta urinishga yo'naltirilmoqda")
        try:
            await msg.reply_text(
                safe_t("ch_unexpected_error", lang),
                reply_markup=get_cancel_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return ADD_CHANNEL


async def add_channel_retry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🔁 «Botni admin qildim — qayta tekshirish» tugmasi.

    Foydalanuvchi botni kanalda administrator qilgach, xabarni qaytadan
    forward qilmasdan shu tugma bilan tekshiruvni yangilaydi.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    raw_target = context.user_data.get("add_channel_pending")
    if raw_target is None:
        # Kutilayotgan manzil yo'q (masalan, sessiya muddati tugagan) —
        # oqimni boshidan so'raymiz.
        await _send_add_channel_instructions(context.bot, query.from_user.id, get_lang(context))
        return ADD_CHANNEL
    return await _link_channel(update, context, raw_target)


async def _link_channel(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_target):
    """Umumiy ulash oqimi: tekshirish → limit → saqlash → natija ro'yxati.

    ``channel_received`` (yangi manba) va ``add_channel_retry`` (qayta
    tekshirish) shu bitta funksiyadan foydalanadi — ikkala yo'l bir xil
    xatolik/omad xabarlarini beradi.
    """
    msg = update.effective_message
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    lang = get_lang(context)

    ok, err, channel_id, channel_title = await _verify_channel_permissions(
        context.bot, raw_target, user_id, is_admin, lang
    )
    if not ok:
        # Manzilni saqlab qo'yamiz: botga ruxsat berilgach 🔁 tugmasi bilan
        # tekshirish mumkin (xabarni qayta yuborish shart emas).
        context.user_data["add_channel_pending"] = raw_target
        await msg.reply_text(
            safe_t("ch_retry_after", lang, error=err),
            reply_markup=_retry_verify_keyboard(lang),
            parse_mode="HTML",
        )
        return ADD_CHANNEL

    # Tarif bo'yicha kanal limiti (FREE vs PRO) — yangi kanal qo'shishdan
    # oldin tekshiriladi. Limit to'lgan bo'lsa xushmuomala xabar va PRO
    # tarifga o'tish tugmasi ko'rsatiladi.
    if not is_admin:
        can_add, current, max_ch = await db.run_db(db.check_channel_limit, user_id)
        if not can_add:
            await msg.reply_text(
                _channel_limit_text(lang, current, max_ch),
                reply_markup=_pro_upgrade_keyboard(lang),
                parse_mode="HTML",
            )
            return ADD_CHANNEL

    success, reason = await db.run_db(db.save_channel, user_id, channel_id, channel_title, is_admin)
    if success:
        context.user_data.pop("add_channel_pending", None)
        # Omad: darhol yangilangan kanal ro'yxatini ko'rsatamiz — foydalanuvchi
        # "ulandi, endi qayerda?" deb qidir maydi; ro'yxatdan qo'shimcha
        # kanal ulash yoki uslub/o'chirish ham mumkin.
        channels = await db.run_db(db.get_user_channels, user_id)
        list_markup = render_channels_list(channels, lang) if channels else None
        # HARDENING: python-telegram-bot'ning Message.reply_text() metodi
        # "inline_keyboard" kalit-argumentini QABUL QILMAYDI (faqat bitta
        # reply_markup bo'ladi — u reply yoki inline klaviatura). Avval shu
        # yerda noto'g'ri kwarg TypeError bilan yiqilib, foydalanuvchiga
        # "✅ ulandi" xabari HECH QACHON yetib bormas edi (bot "qotib"
        # qolganday ko'rinardi). Endi ikkita alohida xabar yuboriladi:
        # 1) reply-klaviatura bilan tasdiq, 2) inline ro'yxat (agar bo'lsa).
        await msg.reply_text(
            safe_t("ch_success", lang, title=html_escape(channel_title),
                     channel_id=channel_id, count=len(channels or [])),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
        if list_markup:
            try:
                await msg.reply_text(
                    safe_t("ch_success_footer", lang),
                    reply_markup=list_markup,
                    parse_mode="HTML",
                )
            except TelegramError:
                pass

    elif reason == "taken":
        context.user_data.pop("add_channel_pending", None)
        await msg.reply_text(
            safe_t("ch_taken", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
    else:
        await msg.reply_text(
            safe_t("ch_save_error", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )

    return ConversationHandler.END


async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Darhol javob — DB so'rovlaridan oldin, tugma muzlab qolmasligi uchun.
    try:
        await query.answer()
    except Exception:
        pass

    channel_id = query.data.split(":")[1]
    user_id = query.from_user.id
    is_admin = (user_id in ADMIN_IDS_SET)

    lang = get_lang(context)
    removed = await db.run_db(db.remove_channel, user_id, channel_id, is_admin)
    channels = await db.run_db(db.get_user_channels, user_id)
    if not removed:
        try:
            await query.message.reply_text(
                safe_t("ch_remove_not_found", lang),
                parse_mode="HTML",
            )
        except Exception:
            pass

    # Ro'yxatni qayta chizamiz — qolgan kanallar va tugmalar ko'rinib tursin
    try:
        if channels:
            await query.edit_message_text(
                safe_t("ch_list_title", lang, count=len(channels)),
                reply_markup=render_channels_list(channels, lang),
                parse_mode="HTML",
            )
        else:
            await query.edit_message_text(
                safe_t("ch_all_removed", lang),
                reply_markup=_empty_channels_keyboard(lang),
                parse_mode="HTML",
            )
    except TelegramError:
        pass


async def on_bot_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Avtomatik aniqlash (Auto-detect): botni kanal/guruhga admin qilib
    qo'shish/olib tashlashni ``my_chat_member`` orqali kuzatadi.

    Foydalanuvchi botni o'z kanaliga ADMIN qilib qo'shishi bilan (xabar
    yuborish — ``can_post_messages`` — huquqi bilan) bot buni darhol
    aniqlaydi va kanal egasiga shaxsiy chatda tabrik xabarini yuboradi —
    forward/username yuborishga hojat qolmaydi.
    """
    result = update.my_chat_member
    if not result:
        return
    chat = result.chat
    new_member = result.new_chat_member
    new_status = new_member.status
    user_id = result.from_user.id

    if chat.type not in ("channel", "supergroup", "group"):
        return

    if new_status in ("administrator", "creator"):
        # Kanallarda xabar yuborish uchun aniq ruxsat (can_post_messages)
        # shart — ``result.new_chat_member`` allaqachon ``get_chat_member``
        # bilan bir xil ma'lumotni o'z ichiga oladi (Telegram shu update'da
        # yuboradi), shuning uchun qo'shimcha API chaqiruvisiz tekshiramiz.
        # Noto'g'ri til uchun uz fallback: get_text buni o'zi hal qiladi.
        lang = normalize_lang(context.user_data.get("lang", "uz"))
        if chat.type == "channel" and new_status == "administrator":
            if not getattr(new_member, "can_post_messages", False):
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=safe_t("ch_no_perm_dm", lang,
                                      channel=html_escape(chat.title or "Kanal")),
                        parse_mode="HTML",
                    )
                except TelegramError:
                    pass
                return

        is_admin = (user_id in ADMIN_IDS_SET)
        # Avtomatik ulashda ham tarif limiti tekshiriladi — free foydalanuvchi
        # maksimal kanal sonidan oshsa, kanal ulab bo'lmaydi.
        if not is_admin:
            can_add, current, max_ch = await db.run_db(db.check_channel_limit, user_id)
            if not can_add:
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=_channel_limit_text(lang, current, max_ch),
                        reply_markup=_pro_upgrade_keyboard(lang),
                        parse_mode="HTML",
                    )
                except TelegramError:
                    pass
                return
        success, reason = await db.run_db(
            db.save_channel, user_id, str(chat.id),
            chat.title or safe_t("ch_default_title", lang), is_admin
        )
        if success:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=safe_t("ch_autoconnect_success", lang,
                                  channel=html_escape(chat.title or "Kanal"),
                                  channel_id=chat.id),
                    parse_mode="HTML",
                )
            except TelegramError:
                pass
        elif reason == "taken":
            logger.info("Kanal %s boshqa foydalanuvchiga tegishli — avto-ulash o'tkazib yuborildi", chat.id)
        return

    if new_status in ("left", "kicked", "member", "restricted"):
        await db.run_db(db.deactivate_channel_by_id, str(chat.id))


# ============================================================
# CHANNEL TONE OF VOICE
# ============================================================

async def tone_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline 'Uslub' tugmasi bosilganda — uslub tanlash menyusini ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    channel_id = query.data.split(":", 1)[1] if ":" in query.data else ""
    if not channel_id:
        return ConversationHandler.END

    context.user_data["tone_channel_id"] = channel_id
    current_tone = await db.run_db(db.get_channel_tone, channel_id)
    labels = tone_labels(lang)
    current_label = labels.get(current_tone, labels["friendly"])

    await query.message.reply_text(
        safe_t("ch_tone_title", lang, current=current_label),
        reply_markup=get_tone_keyboard(lang),
        parse_mode="HTML",
    )
    return SET_TONE


async def tone_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Foydalanuvchi uslub tugmasini bosganda."""
    lang = get_lang(context)
    text = update.message.text.strip()
    channel_id = context.user_data.get("tone_channel_id", "")
    is_admin = update.effective_user.id in ADMIN_IDS_SET
    labels = tone_labels(lang)

    # Uslub tugmalari UCHALA tilda ham qabul qilinadi: klaviatura EN bo'lganda
    # "👔 Formal / Business" bosilса avval "nota'g'ri uslub" deb qaytardi.
    tone = tone_from_text(text)

    if is_menu_text(text, "main_menu", "back", "cancel"):
        await update.message.reply_text(
            safe_t("ch_tone_cancelled", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if not tone:
        await update.message.reply_text(
            safe_t("ch_tone_invalid", lang),
            reply_markup=get_tone_keyboard(lang),
        )
        return SET_TONE

    success = await db.run_db(db.set_channel_tone, channel_id, tone)
    if success:
        await update.message.reply_text(
            safe_t("ch_tone_success", lang, tone=labels[tone]),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            safe_t("ch_tone_error", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )

    context.user_data.pop("tone_channel_id", None)
    return ConversationHandler.END


async def _fetch_public_posts_fallback(context, channel_id: str) -> list:
    """Kanalning public username'i orqali t.me/s/ web-preview postlarini o'qiydi.

    Kanal ovozi tahlilida DB tarixi (channel_posts_history) bo'sh bo'lganda
    chaqiriladi: bot kanal username'ini get_chat orqali aniqlaydi va ochiq
    kanal bo'lsa so'nggi postlarini web-preview dan o'qiydi — kanalda yangi
    postlar hali yozilmagan bo'lsa ham tahlil ishlaydi.

    Xatolarda/yopiq kanalda bo'sh ro'yxat qaytaradi (jim — bu faqat fallback).
    """
    try:
        bot = getattr(context, "bot", None)
        if bot is None:
            return []
        raw_id = str(channel_id).strip()
        if not raw_id.lstrip("-").isdigit():
            return []
        chat = await bot.get_chat(int(raw_id))
        username = getattr(chat, "username", None)
        if not username:
            return []
        result = await read_channel_posts(username, limit=12)
        return result.get("posts") or []
    except Exception as e:
        logger.debug("Web-preview fallback (%s): %s", channel_id, e)
        return []


async def channel_voice_analysis_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """🎙 'Kanal ovozi tahlili' — AI kanal postlari asosida uslubni aniqlaydi.

    Kanal profiliga bog'langan tugma (render_channels_list → ``ch_voice:``):
      1. kanalning so'nggi postlari ``channel_posts_history`` dan olinadi;
      2. AI ularni tahlil qilib kanal ovozi/uslubini (formal | friendly |
         concise | engaging) aniqlaydi;
      3. natija kanalning ``tone_of_voice`` profiliga SAQLANADI — keyingi AI
         generatsiyalar (AI Studio, kontent-reja, rasmdan post) shu uslubda
         yoziladi.

    Bu handler hech qanday ConversationHandler holatiga bog'liq emas — faqat
    kanal ro'yxatidagi inline tugma orqali ishlaydi.
    """
    query = update.callback_query
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    data = query.data or ""
    if not data.startswith(CB_CHANNEL_VOICE):
        return ConversationHandler.END
    channel_id = data[len(CB_CHANNEL_VOICE):].strip()
    if not channel_id:
        return ConversationHandler.END

    # Kanal foydalanuvchining o'z kanali ekanini tekshiramiz (fail-closed).
    channels = await db.run_db(db.get_user_channels_with_tone, user_id)
    owned = any(str(ch[0]) == channel_id for ch in channels)
    if not owned:
        try:
            await query.message.reply_text(
                safe_t("ch_voice_error", lang),
                reply_markup=get_main_keyboard(is_admin, lang=lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return ConversationHandler.END

    # 1) Tahlil jarayoni haqida xabar
    try:
        analyzing_msg = await query.message.reply_text(
            safe_t("ch_voice_analyzing", lang),
            parse_mode="HTML",
        )
    except Exception:
        analyzing_msg = None

    # 2) Kanal postlari tarixini o'qib, AI bilan uslubni aniqlaymiz.
    #    DB tarixi bo'sh bo'lsa — ochiq kanal uchun t.me/s/ web-preview fallback
    #    (bot kanalda admin bo'lmasa ham yoki postlar hali yozilmagan bo'lsa ham).
    posts = await db.run_db(db.get_channel_posts_history, channel_id, 15)
    if not posts:
        posts = await _fetch_public_posts_fallback(context, channel_id)
    try:
        result = await analyze_channel_voice(posts, lang)
    except Exception as e:
        logger.warning("Kanal ovozi tahlili chaqiruv xatosi (%s): %s", channel_id, e)
        result = {"error": safe_t("ch_voice_error", lang)}

    if analyzing_msg is not None:
        try:
            await analyzing_msg.delete()
        except Exception:
            pass

    tone = (result or {}).get("tone")
    if not tone:
        error_text = (result or {}).get("error") or safe_t("ch_voice_error", lang)
        try:
            await query.message.reply_text(
                f"{error_text}",
                reply_markup=get_main_keyboard(is_admin, lang=lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return ConversationHandler.END

    # 3) Natijani kanal profiliga saqlaymiz (tone_of_voice)
    await db.run_db(db.set_channel_tone, channel_id, tone)

    labels = tone_labels(lang)
    tone_label = labels.get(tone, labels["friendly"])
    reason = (result.get("reason") or "").strip()
    try:
        await query.message.reply_text(
            safe_t("ch_voice_result", lang, tone=html_escape(tone_label),
                     reason=html_escape(reason)),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Dialog ICHIDA bo'lmasa kanal ro'yxatini yangilangan uslub bilan qayta
    # ko'rsatamiz (dialog bo'lsa foydalanuvchi holatini buzmaymiz).
    if active_conversation_state(getattr(context, "application", None), update) is None:
        try:
            fresh = await db.run_db(db.get_user_channels_with_tone, user_id)
            if fresh:
                await query.message.reply_text(
                    safe_t("ch_list_title", lang, count=len(fresh)),
                    reply_markup=render_channels_list(fresh, lang),
                    parse_mode="HTML",
                )
        except Exception:
            pass
    return ConversationHandler.END


# ============================================================
# REAL-TIME CHANNEL POST LISTENER
# ============================================================

async def on_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot admin bo'lgan ulangan kanallarga yangi post kelganda channel_posts_history ga yozish."""
    msg = update.channel_post or update.edited_channel_post or update.effective_message
    if not msg or not msg.chat:
        return

    channel_id = str(msg.chat.id)
    message_id = getattr(msg, "message_id", None)
    text = (msg.text or msg.caption or "").strip()
    views = getattr(msg, "views", 0) or 0
    post_date = getattr(msg, "date", None)

    content = text
    if not content:
        if getattr(msg, "photo", None):
            content = "[Rasm]"
        elif getattr(msg, "video", None):
            content = "[Video]"
        elif getattr(msg, "document", None):
            content = "[Hujjat]"
        elif getattr(msg, "audio", None):
            content = "[Audio]"
        elif getattr(msg, "animation", None):
            content = "[GIF]"

    if not content:
        content = ""

    try:
        await db.run_db(
            db.save_channel_post_history,
            channel_id=channel_id,
            message_id=message_id,
            content=content,
            views=views,
            post_date=post_date,
        )
    except Exception as e:
        logger.warning("on_channel_post saqlashda xato (%s): %s", channel_id, e)
