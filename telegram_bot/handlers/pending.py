import logging
from datetime import datetime
import pytz
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
import database as db
from keyboards.inline import (
    normalize_custom_reaction_emojis,
    DEFAULT_REACTION_EMOJIS,
)
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_reactions_keyboard
from locales.translations import clear_fsm_data, get_lang, get_text
from utils.date_format import format_datetime
from utils.security import validate_button_url
from utils.helpers import (
    html_escape, check_rate_limit,
    NAV_RATE_LIMIT_MAX, parse_reactions_input,
    parse_schedule_input, schedule_time_example, SCHEDULE_ERR_PAST,
)

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")
# Eslatma: 201 SLOT_ADD (Queue) bilan to'qnashgan edi — endi 205 unikal.
EDIT_POST_TIME    = 205
EDIT_POST_CONTENT = 202  # Matnni tahrirlash
EDIT_POST_BTN     = 203  # Tugma havolasini o'zgartirish
EDIT_POST_REACT   = 204  # Reaksiyalarni o'zgartirish

# Rate-limit bildirishnomasi (uz fallback; RU uchun get_text("pend_rate_limited")).
_RATE_LIMIT_NOTICE = "⏳ Iltimos, biroz kuting..."


async def _build_pending_view(user_id: int, lang: str = "uz"):
    """DEPRECATED (PostAssist V2 · 2-qadam) — yagona «📅 Rejalashtirilgan».

    B1 birlashtiruvidan oldin bu funksiya «Kutilayotgan postlar» ekranini
    chizardi. Endi u ATAYLAB yagona rejalashtirilgan ekraniga (``queue``
    modulidagi :func:`handlers.queue.scheduled_view`) yo'naltiradi — eski
    ``cab_pending`` va ``pending_refresh`` oqimlari bir xil ro'yxatni
    ko'rsatadi va hech qanday crash bo'lmaydi. Nomi (API) saqlanadi, chunki
    uni chat tarixidagi eski tugmalar ham chaqiradi.
    """
    from handlers.queue import scheduled_view

    return await scheduled_view(user_id, lang)


async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 YAGONA ro'yxat: «⏳ Kutilayotgan postlar» tugmasi ham shu ekranni ochadi.

    PostAssist V2 · 2-qadam (B1): ikkita alohida ekran («Kutilayotgan
    postlar» va «Rejalashtirilgan postlar») o'rniga bitta «📅
    Rejalashtirilgan» ekrani — har bir post ostida barcha amallar to'liq
    ([👁 Ko'rish] [✏️ Tahrirlash] [⏰ Vaqt] [🔗 Tugma/Reaksiya] [🗑 O'chirish]).
    """
    clear_fsm_data(context)
    user_id = update.effective_user.id
    lang = get_lang(context)
    text, markup = await _build_pending_view(user_id, lang)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")


async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_lang(context)
    # Darhol javob — DB ishi tugaguncha tugma muzlab qolmasligi uchun.
    try:
        await query.answer()
    except Exception:
        pass

    try:
        parts = query.data.split(":")
        post_id = int(parts[1])
        await db.run_db(db.cancel_post, post_id, user_id)

        text, markup = await _build_pending_view(user_id, lang)
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        try:
            await query.message.reply_text(get_text("pend_error", lang, error=e))
        except Exception:
            pass


async def refresh_pending_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ro'yxatni qayta chizadi (🔄 Yangilash tugmasi)."""
    query = update.callback_query
    user_id = query.from_user.id
    lang = get_lang(context)
    is_blocked, _ = check_rate_limit(user_id, max_requests=NAV_RATE_LIMIT_MAX, window_seconds=2.0)
    if is_blocked:
        await query.answer(
            get_text("pend_rate_limited", lang) or _RATE_LIMIT_NOTICE,
            show_alert=False)
        return
    try:
        text, markup = await _build_pending_view(user_id, lang)
        await query.answer(get_text("pend_refreshed", lang))
        await query.edit_message_text(text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        await query.answer(get_text("pend_refresh_fail", lang), show_alert=False)
        logger.warning("Pending yangilash xatosi: %s", e)


# ============================================================
# Postni tahrirlash oqimlari
# ============================================================

def _owner_id_of(post) -> "int | None":
    """Post qatoridan egasining user_id sini qaytaradi (get_post_by_id: [1] = user_id)."""
    try:
        return int(post[1])
    except Exception:
        return None


async def _callback_owns_post(query, post_id: int, user_id: int, lang: str) -> bool:
    """FAZA 23 (IDOR): tugma bosilgan ZAHOTI post egaligini tekshiradi (fail-closed).

    Callback'dan olingan ``post_id`` foydalanuvchi yuborgan ixtiyoriy butun
    son — Telegram uni server tomonida tekshirmaydi, shu sababli FSM holati
    o'rnatishdan va tahrirlash so'rovini yuborishdan OLDIN post egasi
    tasdiqlanadi:

    * post topilmasa → rad etiladi;
    * post begonasiniki bo'lsa → rad etiladi (ichki ``post[1] != user_id``);
    * DB xatosi bo'lsa → HAM rad etiladi (fail-closed — hech qachon
      ``except`` ichida "ruxsat" yo'li ochilmaydi).

    Rad etilganda foydalanuvchi faqat lokalizatsiya qilingan xushmuomala
    alert ko'radi (ichki ma'lumotlar sizdirilmaydi) va hech qanday FSM
    holati o'rnatilmaydi.
    """
    try:
        post = await db.run_db(db.get_post_by_id, post_id)
    except Exception:
        # Fail-closed: DB xatosida ham "ruxsat" yo'li ochilmaydi.
        logger.warning(
            "IDOR guard: egalik tekshiruvi xatosi (user_id=%s) — rad etildi",
            user_id)
        post = {}
    if not post or _owner_id_of(post) != user_id:
        try:
            await query.answer(
                get_text("pend_not_owned", lang), show_alert=True)
        except Exception:
            pass
        logger.warning(
            "IDOR urinishi bloklandi: user_id=%s, so'ralgan post_id=%s",
            user_id, post_id)
        return False
    return True


async def _get_owned_post(post_id: int, user_id: int, update: Update, lang: str = "uz"):
    """Post mavjudligi va egasini tekshiradi. Muvaffaqiyatsiz bo'lsa None qaytadi."""
    post = await db.run_db(db.get_post_by_id, post_id)
    if not post:
        await update.message.reply_text(
            get_text("pend_not_found", lang), reply_markup=get_main_keyboard(lang=lang))
        return None
    # post[1] = user_id (get_post_by_id jadvalida 2-ustun)
    if post[1] != user_id:
        await update.message.reply_text(get_text("pend_not_owned", lang))
        return None
    return post


# ------ Vaqt tahrirlash ------

async def edit_post_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_lang(context)
    parts = query.data.split(":")
    post_id = int(parts[1])

    # FAZA 23 (IDOR): post ID olingan zahoti egalik tekshiruvi — begona
    # post uchun FSM holati ham o'rnatilmaydi (fail-closed).
    if not await _callback_owns_post(query, post_id, query.from_user.id, lang):
        return ConversationHandler.END

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "time"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=get_text("pend_time_ask", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML"
    )
    return EDIT_POST_TIME


async def edit_post_time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = getattr(update.message, "text", None)
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update, lang)
    if not post:
        return ConversationHandler.END

    now = datetime.now(tashkent_tz)
    # Yagona, crash-proof parser: "31.12.2026 18:00", "18:00", "ertaga 5 da"...
    new_time, reason = parse_schedule_input(text, now)
    if new_time is None:
        example = schedule_time_example(now)
        key = "np_time_future" if reason == SCHEDULE_ERR_PAST else "pend_time_format"
        await update.message.reply_text(
            get_text(key, lang, example=example, now=format_datetime(now, lang)),
            parse_mode="HTML",
        )
        return EDIT_POST_TIME

    try:
        await db.run_db(
            db.update_post_time, post_id, new_time, user_id=update.effective_user.id
        )
    except Exception:
        logger.exception("Post vaqtini yangilashda xato (Post ID: %s)", post_id)
        await update.message.reply_text(get_text("pend_time_format", lang,
                                                 example=schedule_time_example(now)),
                                        parse_mode="HTML")
        return EDIT_POST_TIME

    await update.message.reply_text(
        get_text("pend_time_success", lang),
        reply_markup=get_main_keyboard(lang=lang),
        parse_mode="HTML"
    )
    clear_fsm_data(context)
    return ConversationHandler.END


# ------ Matn tahrirlash ------

async def edit_post_content_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post matnini tahrirlash boshlash."""
    query = update.callback_query
    lang = get_lang(context)
    parts = query.data.split(":")
    post_id = int(parts[1])

    # FAZA 23 (IDOR): post ID olingan zahoti egalik tekshiruvi — begona
    # post uchun FSM holati ham o'rnatilmaydi (fail-closed).
    if not await _callback_owns_post(query, post_id, query.from_user.id, lang):
        return ConversationHandler.END

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "content"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=get_text("pend_content_ask", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return EDIT_POST_CONTENT


async def edit_post_content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    new_content = update.message.text
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update, lang)
    if not post:
        return ConversationHandler.END

    updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, content=new_content)
    if updated:
        await update.message.reply_text(
            get_text("pend_content_success", lang),
            reply_markup=get_main_keyboard(lang=lang),
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            get_text("pend_update_fail", lang), reply_markup=get_main_keyboard(lang=lang))
    clear_fsm_data(context)
    return ConversationHandler.END


# ------ Tugma URL tahrirlash ------

async def edit_post_btn_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post tugmasini tahrirlash."""
    query = update.callback_query
    lang = get_lang(context)
    parts = query.data.split(":")
    post_id = int(parts[1])

    # FAZA 23 (IDOR): post ID olingan zahoti egalik tekshiruvi — begona
    # post uchun FSM holati ham o'rnatilmaydi (fail-closed).
    if not await _callback_owns_post(query, post_id, query.from_user.id, lang):
        return ConversationHandler.END

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "btn"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=get_text("pend_btn_ask", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return EDIT_POST_BTN


async def edit_post_btn_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text.strip()
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update, lang)
    if not post:
        return ConversationHandler.END

    if text.lower() in ("yo'q", "yoq", "none", "-", "o'chir", "нет", "удалить"):
        updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, btn_text="", btn_url="")
        msg = get_text("pend_btn_removed", lang)
    elif "|" in text:
        parts = text.split("|", 1)
        btn_title = parts[0].strip()
        btn_link = parts[1].strip()
        if btn_link.startswith("@"):
            btn_link = f"https://t.me/{btn_link.lstrip('@')}"
        elif not btn_link.startswith(("http://", "https://", "t.me/")):
            btn_link = "https://" + btn_link
        # FAZA 23 (SSRF): havolali tugma manzili saqlashdan OLDIN qat'iy
        # tekshiriladi — javascript:/data: kabi xavfli sxemalar va ichki
        # tarmoq manzillari (localhost, 127.0.0.1, 10.*, 192.168.*,
        # 169.254.* metadata) saqlanmaydi.
        if not validate_button_url(btn_link):
            await update.message.reply_text(
                get_text("pend_btn_unsafe", lang)
                or get_text("pend_btn_format", lang),
                parse_mode="HTML",
            )
            return EDIT_POST_BTN
        updated = await db.run_db(db.update_post_content, post_id, update.effective_user.id, btn_text=btn_title, btn_url=btn_link)
        msg = get_text("pend_btn_updated", lang, text=html_escape(btn_title))
    else:
        await update.message.reply_text(
            get_text("pend_btn_format", lang),
            parse_mode="HTML",
        )
        return EDIT_POST_BTN

    if updated:
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(lang=lang), parse_mode="HTML")
    else:
        await update.message.reply_text(
            get_text("pend_update_fail", lang), reply_markup=get_main_keyboard(lang=lang))
    clear_fsm_data(context)
    return ConversationHandler.END


# ------ Reaksiya tahrirlash ------

async def edit_post_react_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Inline tugma orqali post reaksiyalarini yoqish/o'chirish."""
    query = update.callback_query
    lang = get_lang(context)
    parts = query.data.split(":")
    post_id = int(parts[1])

    # FAZA 23 (IDOR): post ID olingan zahoti egalik tekshiruvi — begona
    # post uchun FSM holati ham o'rnatilmaydi (fail-closed).
    if not await _callback_owns_post(query, post_id, query.from_user.id, lang):
        return ConversationHandler.END

    context.user_data["editing_post_id"] = post_id
    context.user_data["edit_mode"] = "react"
    await query.answer()
    await context.bot.send_message(
        chat_id=query.from_user.id,
        text=get_text("pend_react_ask", lang),
        reply_markup=get_reactions_keyboard(lang),
        parse_mode="HTML",
    )
    return EDIT_POST_REACT


async def edit_post_react_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_lang(context)
    text = update.message.text
    post_id = context.user_data.get("editing_post_id")
    post = await _get_owned_post(post_id, update.effective_user.id, update, lang)
    if not post:
        return ConversationHandler.END

    parsed = parse_reactions_input(text)
    if parsed is None:
        await update.message.reply_text(
            get_text("pend_react_invalid", lang),
            reply_markup=get_reactions_keyboard(lang)
        )
        return EDIT_POST_REACT

    # Foydalanuvchi emojilarni QO'LDA kiritgan bo'lsa (masalan "👍 ❤️ 🔥") —
    # o'sha emojilar saqlanib, kanal postida tugma sifatida chiqishi shart.
    # Faqat "ha/yoqish" kabi matnli tasdiq bo'lsa — standart to'plam yoqiladi.
    custom = normalize_custom_reaction_emojis(text) if parsed else []
    if not parsed:
        # Reaksiyalar o'chirildi.
        updated = await db.run_db(
            db.update_post_content, post_id, update.effective_user.id,
            enable_reactions=False,
        )
        msg = get_text("pend_react_off", lang)
    elif custom:
        # Qo'lda kiritilgan aniq emojilar saqlanadi (kanonik + boshqa emojilar).
        updated = await db.run_db(
            db.update_post_content, post_id, update.effective_user.id,
            enable_reactions=True, reaction_emojis=" ".join(custom),
        )
        msg = get_text("pend_react_updated", lang, emojis=" ".join(custom))
    else:
        # "ha/yoqish/yes" — standart to'plam (👍 ❤️ 🔥 👏) yoqiladi.
        updated = await db.run_db(
            db.update_post_content, post_id, update.effective_user.id,
            enable_reactions=True,
            reaction_emojis=" ".join(DEFAULT_REACTION_EMOJIS),
        )
        msg = get_text("pend_react_on", lang)
    if updated:
        await update.message.reply_text(msg, reply_markup=get_main_keyboard(lang=lang), parse_mode="HTML")
    else:
        await update.message.reply_text(
            get_text("pend_update_fail", lang), reply_markup=get_main_keyboard(lang=lang))
    clear_fsm_data(context)
    return ConversationHandler.END
