"""📅 REJALASHTIRILGAN — rejalashtirilgan postlarni ko'rish va boshqarish.

PostAssist V2 · 4-mikro qadam. Bo'lim master plan standartiga keltirildi:

  * **NOMLANISH.** Eskirgan texnik nomlar («Postlar navbati», «Navbatdagi
    postlar», «Очередь постов», «Queued posts») foydalanuvchi ko'radigan
    BARCHA joyda yagona «📅 Rejalashtirilgan» / «📅 Запланированные» /
    «📅 Scheduled» nomiga o'tkazildi (``translations/channels_queue.py``).
    Eski ``queue_*`` lug'at kalitlari, ``btn_queue``/``cab_queue`` yorliqlari
    va ``qview:``/``qdel:``/``qpush:``/``qpage:`` callback'lari ALIAS sifatida
    saqlanadi — chat tarixidagi eski tugmalar buzilmaydi.

  * **FORMAT.** Postlar VAQT BO'YICHA tartiblangan (DB ``ORDER BY
    scheduled_time ASC``) ixcham inline qatorlarda chiqadi::

        1. 🕐 Bugun 18:00 — 📝 Yangi mahsulot chegirmasi | 📢 Mening kanalim

  * **AMALLAR.** Har bir post ostida [✏️ Tahrirlash] · [⏰ Vaqtni o'zgartirish]
    · [🗑 O'chirish] — uchalasi ham mavjud, sinovdan o'tgan oqimlarni
    (``p_edit:`` / ``p_time:`` / ``qdel:``) chaqiradi, ya'ni egalik (ownership)
    tekshiruvi va FSM xavfsizligi o'zgarishsiz qoladi.

Modul slot sozlamalarini (``qslots:``) ham saqlaydi — u avtomatik
rejalashtirish vaqtlarini belgilaydi va o'z ekranida ishlaydi.
"""
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, is_menu_text
from keyboards.callback_data import cb
from keyboards.inline import (
    render_scheduled_actions,
    render_scheduled_full_actions,
    scheduled_btn_react_keyboard,
)
from locales.translations import get_lang, get_text, normalize_lang
from translations import channels_queue_t
from utils.date_format import format_datetime, format_list_datetime
from utils.helpers import html_escape

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

QUEUE_PAGE_SIZE = 5

# Tarif limiti (FREE vs PRO) tugaganda ko'rsatiladigan xabar va PRO tugmasi.
# (eski chaqiruvlar uchun o'zbekcha konstanta saqlanadi)
QUEUE_LIMIT_MSG = (
    "🚫 <b>Navbat limiti tugadi!</b>\n\n"
    "Sizda <b>{current}/{max}</b> ta navbatdagi post bor.\n"
    "Free tarifida maksimal <b>{max}</b> ta post navbatda turishi mumkin.\n\n"
    "⭐️ Cheksiz navbat uchun PRO tarifiga o'ting."
)

PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarif", callback_data="sub_open")],
])

# States
QUEUE_MENU = 200
SLOT_ADD = 201

# Post turlari uchun tarjima kalitlari (queue_view_callback'da ishlatiladi).
_KNOWN_TYPE_KEYS = {
    "np_type_text", "np_type_photo", "np_type_video", "np_type_document",
    "np_type_audio", "np_type_voice", "np_type_sticker", "np_type_album",
    "np_type_animation", "np_type_unknown",
}


def _post_type_icon(post_type: str) -> str:
    icons = {
        "text": "📝", "photo": "🖼", "video": "🎬",
        "document": "📄", "audio": "🎵", "voice": "🎙",
        "sticker": "😀", "album": "🖼", "animation": "🎞",
    }
    return icons.get(post_type, "📝")


def _content_preview(content: str, max_len: int = 40) -> str:
    if not content:
        return ""
    text = content.replace("\n", " ").strip()
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _format_queue_item(row, index: int, lang: str = "uz") -> str:
    """Bitta REJALASHTIRILGAN postni ixcham inline qatorga formatlaydi.

    Master plan formati (4-mikro qadam)::

        1. 🕐 Bugun 18:00 — 📝 Yangi mahsulot chegirmasi | 📢 Mening kanalim

    Sana/vaqt foydalanuvchi tilida: avval ``%d-%b`` ishlatilardi va Python
    ``strftime`` C-locale oy nomini qaytargani uchun RU/O'Z foydalanuvchi ham
    "05-Sep" ko'rardi. Endi oy nomi til lug'atidan olinadi va bugun/ertaga
    sanalari "Bugun 18:00" / "Сегодня 18:00" / "Today 18:00" ko'rinishida
    chiqadi. Qator DB'dan ``ORDER BY scheduled_time ASC`` bilan kelgani
    uchun ro'yxat doim VAQT BO'YICHA tartiblangan.
    """
    post_id, ch_title, post_type, content, sched_time, post_num, ch_id = row
    icon = _post_type_icon(post_type)
    preview = _content_preview(content)
    time_str = format_list_datetime(
        sched_time, lang=normalize_lang(lang), now=datetime.now(tashkent_tz)
    ) or "—"
    ch_display = html_escape(ch_title or ch_id or "?")
    # Matn qisqartmasi bo'lmasa (sof media post) — tur ikonkasining o'zi
    # yetarli, chiziqcha "osilib" qolmaydi.
    body = f"{icon} {html_escape(preview)}" if preview else icon
    return f"{index}. 🕐 {time_str} — {body} | 📢 {ch_display}"


def _get_queue_list_keyboard(posts, offset: int, total: int, lang: str = "uz") -> InlineKeyboardMarkup:
    """📅 YAGONA Rejalashtirilgan ro'yxati uchun inline keyboard.

    PostAssist V2 · 2-qadam (B1): «Kutilayotgan postlar» va «Rejalashtirilgan
    postlar» bitta ekranga birlashtirildi, shu sababli har bir post ostida
    BARCHA amallar TO'LIQ jamlangan (``render_scheduled_full_actions``)::

        [👁 Ko'rish]   [✏️ Tahrirlash]
        [⏰ Vaqt]      [🔗 Tugma/Reaksiya]
        [🗑 O'chirish] [⏩ Surish]

    ``⏩ Surish`` — eski (alias) amal, ro'yxat oxirida saqlanadi; barcha
    callback'lar (``qview:`` / ``p_edit:`` / ``p_time:`` / ``sched_br:`` /
    ``qdel:`` / ``qpush:`` / ``qpage:`` / ``qslots:`` / ``qclose``) chat
    tarixidagi eski tugmalar bilan bir xil qoladi.
    """
    rows = []
    for post in posts:
        pid = post[0]
        rows.extend(render_scheduled_full_actions(pid, lang))

    # Pagination tugmalari
    nav = []
    if offset > 0:
        prev_off = max(0, offset - QUEUE_PAGE_SIZE)
        nav.append(InlineKeyboardButton(get_text("queue_btn_prev", lang), callback_data=cb(f"qpage:{prev_off}")))
    if offset + QUEUE_PAGE_SIZE < total:
        next_off = offset + QUEUE_PAGE_SIZE
        nav.append(InlineKeyboardButton(get_text("queue_btn_next", lang), callback_data=cb(f"qpage:{next_off}")))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(get_text("queue_btn_slots", lang), callback_data="qslots:show")])
    rows.append([InlineKeyboardButton(get_text("queue_btn_close", lang), callback_data="qclose")])
    return InlineKeyboardMarkup(rows)


def _get_post_detail_keyboard(post_id: int, lang: str = "uz") -> InlineKeyboardMarkup:
    """Bitta rejalashtirilgan postni ko'rish ekrani keyboardi.

    ATAYLAB o'zgarishsiz qoldirildi (``qdel:`` / ``qpush:`` / ``qpage:0``):
    kartochka ekrani chat tarixidagi eski xabarlarda ham yashaydi. Master
    plan speksidagi 3 ta amal ([✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish]
    [🗑 O'chirish]) RO'YXAT ekranida har bir post ostida turadi
    (:func:`_get_queue_list_keyboard`).
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(get_text("queue_btn_delete", lang), callback_data=cb(f"qdel:{post_id}")),
            InlineKeyboardButton(get_text("queue_btn_push", lang), callback_data=cb(f"qpush:{post_id}")),
        ],
        [InlineKeyboardButton(get_text("queue_btn_back", lang), callback_data="qpage:0")],
    ])


def _get_slots_keyboard(slots: list, lang: str = "uz") -> InlineKeyboardMarkup:
    """Slot sozlamalari keyboard."""
    rows = []
    for i, slot in enumerate(slots):
        rows.append([
            InlineKeyboardButton(f"🕐 {slot}", callback_data="qslots:noop"),
            InlineKeyboardButton("❌", callback_data=cb(f"qslots:rm:{i}")),
        ])
    rows.append([InlineKeyboardButton(get_text("queue_btn_add_slot", lang), callback_data="qslots:add")])
    rows.append([InlineKeyboardButton(get_text("queue_btn_reset_slots", lang), callback_data="qslots:reset")])
    rows.append([InlineKeyboardButton(get_text("queue_btn_back", lang), callback_data="qpage:0")])
    return InlineKeyboardMarkup(rows)


# ============================================================
# HANDLERS
# ============================================================

async def _build_queue_view(user_id: int, is_admin: bool, lang: str = "uz") -> tuple:
    """Queue view matni va markup'ni tuzadi (cabinet'dan ham chaqiriladi)."""
    total = await db.run_db(db.get_queue_post_count, user_id)

    # Free foydalanuvchi navbat limitiga yetganda PRO taklifi ko'rsatiladi.
    # DB nostandart javob qaytarsa (None/istisno) — upsell ko'rsatilmaydi va
    # ro'yxat ASLO yiqilmaydi (eski kabinet aliaslari ham shunga tayanadi).
    show_upsell = False
    max_q = 0
    if not is_admin:
        try:
            can_add, current, max_q = await db.run_db(db.check_queue_limit, user_id)
            if not can_add:
                show_upsell = True
        except Exception:
            logger.debug("check_queue_limit ishlamadi (user=%s)", user_id, exc_info=True)

    if total == 0:
        # get_cabinet_back_keyboard keyboards.INLINE'da (default'da emas) —
        # noto'g'ri import tufayli tugma bosilganda ImportError chiqar va
        # foydalanuvchi hech qanday javob olmasdi ("qotib qolish").
        from keyboards.inline import get_cabinet_back_keyboard
        text = channels_queue_t("cq_sch_empty", lang)
        markup = get_cabinet_back_keyboard(lang)
        return text, markup

    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [channels_queue_t("cq_sch_title", lang, count=total) + "\n"]
    for i, post in enumerate(posts, 1):
        text_lines.append(_format_queue_item(post, i, lang))
    text = "\n".join(text_lines)

    # Limit to'lgan bo'lsa — banner + PRO tugmasi (navbat ko'rish qoladi).
    if show_upsell:
        text = get_text("queue_limit_msg", lang, current=total, max=max_q) + "\n\n" + text

    keyboard = _get_queue_list_keyboard(posts, 0, total, lang)
    if show_upsell:
        existing = keyboard.inline_keyboard
        existing = [row for row in existing if not any(
            b.callback_data == "sub_open" for b in row
        )]
        existing.append([InlineKeyboardButton(get_text("ch_pro_btn", lang), callback_data="sub_open")])
        keyboard = InlineKeyboardMarkup(existing)
    return text, keyboard


async def build_channel_scheduled_view(user_id: int, channel_id, channel_title: str,
                                       lang: str = "uz") -> tuple:
    """📢 Kanal ichidagi «📅 Rejalashtirilgan» ekrani (matn + markup).

    ``handlers/channels.py:channel_scheduled_callback`` shu funksiyani
    chaqiradi. Ro'yxat umumiy bo'lim bilan AYNAN bir xil formatda chiziladi
    (``_format_queue_item`` — vaqt bo'yicha tartiblangan, "🕐 Bugun 18:00 —
    [Matn qisqartmasi]"), lekin FAQAT shu kanalning postlari ko'rsatiladi va
    ostida [◀️ Orqaga] kanal boshqaruv ekraniga qaytaradi — asosiy menyuga
    chiqib ketilmaydi.
    """
    from keyboards.inline import render_channel_panel
    from translations import channels_queue_t as _t

    target = str(channel_id)
    # Barcha pending postlar (DB'dan vaqt bo'yicha tartiblangan holda keladi)
    # ichidan shu kanalnikini ajratamiz — qo'shimcha DB so'rovi kerak emas.
    total_all = await db.run_db(db.get_queue_post_count, user_id)
    rows = await db.run_db(db.get_queue_posts, user_id, 0, max(int(total_all or 0), 1))
    posts = [r for r in (rows or []) if str(r[6]) == target][:QUEUE_PAGE_SIZE]

    if not posts:
        text = _t("cq_sch_channel_empty", lang, channel=channel_title)
        markup = render_channel_panel(target, lang)
        return text, markup

    text_lines = [_t("cq_sch_channel_title", lang, channel=channel_title,
                     count=len(posts)) + "\n"]
    keyboard = []
    for i, post in enumerate(posts, 1):
        text_lines.append(_format_queue_item(post, i, lang))
        keyboard.append(render_scheduled_actions(post[0], lang))
    keyboard.append([InlineKeyboardButton(
        _t("cq_ch_btn_back", lang), callback_data=cb("ch_op:", target))])
    return "\n".join(text_lines), InlineKeyboardMarkup(keyboard)


async def scheduled_view(user_id: int, lang: str = "uz", is_admin=None) -> tuple:
    """YAGONA «📅 Rejalashtirilgan» ekrani (matn + markup) — B1 birlashtiruv.

    Butun bot uchun BITTA manba: asosiy menyudagi «📅 Rejalashtirilgan»,
    eski «⏳ Kutilayotgan postlar» reply-tugmasi va kabinetdagi eski
    ``cab_pending`` / ``cab_queue`` callback'lari hammasi shu funksiyani
    chaqiradi. Hech qachon istisno tashlamaydi (fail-safe): DB yiqilsa
    foydalanuvchi ``cq_sch_empty`` xabari va ❌ Yopish tugmasini oladi —
    tugma hech qachon "qotib" qolmaydi.
    """
    if is_admin is None:
        is_admin = user_id in ADMIN_IDS_SET
    try:
        return await _build_queue_view(user_id, is_admin, lang)
    except Exception:
        logger.exception("Rejalashtirilgan ekranini qurishda xato (user=%s)", user_id)
        return (
            channels_queue_t("cq_sch_empty", lang),
            InlineKeyboardMarkup([[InlineKeyboardButton(
                get_text("queue_btn_close", lang), callback_data="qclose")]]),
        )


async def queue_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📅 Rejalashtirilgan postlar ro'yxatini ko'rsatadi."""
    user_id = update.effective_user.id
    is_admin = (user_id in ADMIN_IDS_SET)
    text, markup = await _build_queue_view(user_id, is_admin, get_lang(context))
    await update.message.reply_text(text, reply_markup=markup, parse_mode="HTML")
    return QUEUE_MENU


async def queue_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sahifalash tugmasi."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    user_id = query.from_user.id
    offset = int(query.data.split(":")[1])

    total = await db.run_db(db.get_queue_post_count, user_id)
    if total == 0:
        try:
            await query.edit_message_text(
                channels_queue_t("cq_sch_empty", lang),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    get_text("queue_btn_close", lang), callback_data="qclose")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return QUEUE_MENU

    posts = await db.run_db(db.get_queue_posts, user_id, offset, QUEUE_PAGE_SIZE)
    text_lines = [channels_queue_t("cq_sch_title_range", lang, count=total,
                           start=offset + 1,
                           end=min(offset + QUEUE_PAGE_SIZE, total)) + "\n"]
    for i, post in enumerate(posts, offset + 1):
        text_lines.append(_format_queue_item(post, i, lang))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, offset, total, lang)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bitta postni ko'rish."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    post = await db.run_db(db.get_queue_post_detail, post_id, user_id)
    if not post:
        try:
            await query.edit_message_text(channels_queue_t("cq_sch_not_found", lang))
        except Exception:
            pass
        return QUEUE_MENU

    (pid, uid, ch_id, ch_title, post_type, content, file_id,
     btn_text, btn_url, enable_reactions, delete_after_hours,
     sched_time, post_num) = post

    time_str = format_datetime(sched_time, normalize_lang(lang)) or "—"
    ch_display = html_escape(ch_title or ch_id or "?")
    type_key = "np_type_" + post_type if ("np_type_" + post_type) in _KNOWN_TYPE_KEYS else "np_type_unknown"
    type_text = get_text(type_key, lang)

    text = get_text("queue_view_title", lang, id=pid) + "\n\n"
    text += get_text("queue_view_channel", lang, channel=ch_display) + "\n"
    text += get_text("queue_view_type", lang, type=type_text) + "\n"
    text += get_text("queue_view_time", lang, time=time_str) + "\n"
    if content:
        preview = content[:300]
        if len(content) > 300:
            preview += "…"
        text += "\n" + get_text("queue_view_content", lang, content=html_escape(preview))
    if btn_text and btn_url:
        text += "\n" + get_text("queue_view_button", lang, text=html_escape(btn_text))
    if enable_reactions:
        text += "\n" + get_text("queue_view_reactions", lang)
    if delete_after_hours > 0:
        text += "\n" + get_text("queue_view_auto_delete", lang, hours=delete_after_hours)

    keyboard = _get_post_detail_keyboard(pid, lang)
    try:
        await query.edit_message_text(text[:4096], reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postni navbatdan o'chirish."""
    query = update.callback_query
    lang = get_lang(context)
    await query.answer(channels_queue_t("cq_sch_deleted_alert", lang))
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    await db.run_db(db.cancel_post, post_id, user_id)

    # Ro'yxatni yangilash
    total = await db.run_db(db.get_queue_post_count, user_id)
    if total == 0:
        try:
            await query.edit_message_text(
                channels_queue_t("cq_sch_empty", lang),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                    get_text("queue_btn_close", lang), callback_data="qclose")]]),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return QUEUE_MENU

    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [channels_queue_t("cq_sch_title", lang, count=total) + "\n"]
    for i, post in enumerate(posts, 1):
        text_lines.append(_format_queue_item(post, i, lang))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, 0, total, lang)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


async def queue_push_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Postni keyingi slotga surish."""
    query = update.callback_query
    lang = get_lang(context)
    user_id = query.from_user.id
    post_id = int(query.data.split(":")[1])

    # Darhol javob — bir nechta DB so'rovi bajarilguniga qadar tugma muzlab
    # qolmasligi uchun (surish jarayoni bir necha marta DB'ga murojaat qiladi).
    try:
        await query.answer()
    except Exception:
        pass

    post = await db.run_db(db.get_queue_post_detail, post_id, user_id)
    if not post:
        try:
            await query.message.reply_text(
                channels_queue_t("cq_sch_not_found", lang), parse_mode="HTML")
        except Exception:
            pass
        return QUEUE_MENU

    ch_id = post[2]
    now = datetime.now(tashkent_tz)
    slots = await db.run_db(db.get_queue_slots, user_id)

    # Hozirgi vaqtdan keyingi bo'sh slotni topish
    occupied = await db.run_db(db.get_queue_occupied_times, user_id, ch_id, now.date())
    # Hozirgi postning vaqtini occupied dan olib tashlash (chunki u suriladi)
    current_time = post[11].astimezone(tashkent_tz)
    occupied = [(h, m) for h, m in occupied if not (h == current_time.hour and m == current_time.minute)]

    slot_dt, label = db.find_next_queue_slot(slots, occupied, now)
    if not slot_dt:
        # Ertaga urinish
        tomorrow = now + timedelta(days=1)
        tomorrow_start = tashkent_tz.localize(
            datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
        )
        occ_tom = await db.run_db(db.get_queue_occupied_times, user_id, ch_id, tomorrow.date())
        slot_dt, label = db.find_next_queue_slot(slots, occ_tom, tomorrow_start)

    if not slot_dt:
        try:
            await query.message.reply_text(
                get_text("queue_no_slot", lang), parse_mode="HTML")
        except Exception:
            pass
        return QUEUE_MENU

    await db.run_db(db.update_post_time, post_id, slot_dt, user_id=user_id)

    # Ro'yxatni yangilash (surilgan vaqt ro'yxatda ko'rinadi — natija shu orqali bildiriladi)
    total = await db.run_db(db.get_queue_post_count, user_id)
    posts = await db.run_db(db.get_queue_posts, user_id, 0, QUEUE_PAGE_SIZE)
    text_lines = [channels_queue_t("cq_sch_title", lang, count=total) + "\n"]
    for i, p in enumerate(posts, 1):
        text_lines.append(_format_queue_item(p, i, lang))
    text = "\n".join(text_lines)

    keyboard = _get_queue_list_keyboard(posts, 0, total, lang)
    try:
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        pass
    return QUEUE_MENU


# ============================================================
# 🔗 TUGMA / REAKSIYA — yagona ro'yxatdagi 4-amal
# ============================================================
async def scheduled_btn_react_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """[🔗 Tugma/Reaksiya] — mavjud ``p_btn:`` / ``p_react:`` oqimlari tanlagichi.

    Yangi FSM holati YARATILMAYDI: tanlangan tugma o'z (allaqachon entry
    point bo'lgan) oqimini ochadi. Egalik tekshiruvi shu yerda bajariladi —
    begona postning tugmasi ochilmaydi (fail-closed), xato bo'lsa ham
    foydalanuvchi JAVOB oladi va handler qulamaydi.
    """
    query = update.callback_query
    if query is None:
        return QUEUE_MENU
    try:
        await query.answer()
    except Exception:
        pass
    lang = get_lang(context)
    user_id = query.from_user.id
    try:
        post_id = int(str(query.data).split(":", 1)[1])
    except (IndexError, ValueError):
        return QUEUE_MENU

    owned = False
    try:
        owned = bool(await db.run_db(db.get_queue_post_detail, post_id, user_id))
    except Exception:
        logger.debug("get_queue_post_detail ishlamadi (post=%s)", post_id, exc_info=True)
    if not owned:
        try:
            await query.edit_message_text(
                channels_queue_t("cq_sch_not_found", lang), parse_mode="HTML")
        except Exception:
            pass
        return QUEUE_MENU

    try:
        await query.edit_message_text(
            channels_queue_t("cq_sch_br_title", lang),
            reply_markup=scheduled_btn_react_keyboard(post_id, lang),
            parse_mode="HTML",
        )
    except Exception:
        pass
    return QUEUE_MENU


async def queue_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Queue oynasini yopish."""
    query = update.callback_query
    await query.answer()
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    return ConversationHandler.END


# ============================================================
# SLOT SETTINGS
# ============================================================

async def queue_slots_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Slot sozlamalari: ko'rish, qo'shish, o'chirish, reset."""
    query = update.callback_query
    lang = get_lang(context)
    data = query.data  # "qslots:show", "qslots:add", "qslots:rm:2", "qslots:reset", "qslots:noop"
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else "show"
    user_id = query.from_user.id

    if action == "noop":
        await query.answer()
        return SLOT_ADD

    if action == "show":
        await query.answer()
        slots = await db.run_db(db.get_queue_slots, user_id)
        text = get_text("queue_slots_title", lang, slots=", ".join(slots))
        keyboard = _get_slots_keyboard(slots, lang)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    if action == "rm":
        # Bu SLOT o'chirish (post emas) — eski toast o'z joyida qoladi.
        await query.answer(get_text("queue_deleted_alert", lang))
        idx = int(parts[2])
        slots = await db.run_db(db.get_queue_slots, user_id)
        if 0 <= idx < len(slots):
            slots.pop(idx)
            if slots:  # Kamida bitta slot qolishi kerak
                await db.run_db(db.set_queue_slots, user_id, slots)
            else:
                # Oxirgi slotni o'chirib bo'lmaydi — default qaytaramiz
                await query.answer(get_text("queue_slot_min", lang), show_alert=True)
                slots = await db.run_db(db.get_queue_slots, user_id)

        text = get_text("queue_slots_title", lang, slots=", ".join(slots))
        keyboard = _get_slots_keyboard(slots, lang)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    if action == "add":
        await query.answer()
        await query.message.reply_text(
            get_text("queue_slot_add_ask", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        context.user_data["slot_add_pending"] = True
        return SLOT_ADD

    if action == "reset":
        await query.answer(get_text("queue_slot_reset_alert", lang))
        await db.run_db(db.set_queue_slots, user_id, list(db.DEFAULT_QUEUE_SLOTS))
        slots = list(db.DEFAULT_QUEUE_SLOTS)
        text = get_text("queue_slots_reset", lang, slots=", ".join(slots))
        keyboard = _get_slots_keyboard(slots, lang)
        try:
            await query.edit_message_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            pass
        return SLOT_ADD

    return SLOT_ADD


async def slot_add_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi slot qo'shish uchun matn qabul qilish."""
    lang = get_lang(context)
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id

    # "Orqaga/Asosiy menyu" tugmalari — registry orqali UCHALA tilda (uz/ru/en),
    # shunda EN klaviatura bilan ham slot qo'shish bekor qilinadi.
    if is_menu_text(text, "back", "main_menu", "np_back_confirm"):
        context.user_data.pop("slot_add_pending", None)
        slots = await db.run_db(db.get_queue_slots, user_id)
        slot_text = get_text("queue_slots_title", lang, slots=", ".join(slots))
        keyboard = _get_slots_keyboard(slots, lang)
        await update.message.reply_text(slot_text, reply_markup=keyboard, parse_mode="HTML")
        return SLOT_ADD

    # Vaqt formatini tekshirish
    try:
        hh, mm = text.split(":")
        hh, mm = int(hh), int(mm)
        assert 0 <= hh < 24 and 0 <= mm < 60
    except Exception:
        await update.message.reply_text(
            get_text("queue_slot_format", lang),
            parse_mode="HTML",
        )
        return SLOT_ADD

    new_slot = f"{hh:02d}:{mm:02d}"
    slots = await db.run_db(db.get_queue_slots, user_id)

    if new_slot in slots:
        await update.message.reply_text(
            get_text("queue_slot_exists", lang, slot=new_slot), parse_mode="HTML")
        return SLOT_ADD

    if len(slots) >= 10:
        await update.message.reply_text(
            get_text("queue_slot_max", lang), parse_mode="HTML")
        return SLOT_ADD

    slots.append(new_slot)
    slots.sort()
    await db.run_db(db.set_queue_slots, user_id, slots)
    context.user_data.pop("slot_add_pending", None)

    slot_text = get_text("queue_slot_added", lang, slot=new_slot, slots=", ".join(slots))
    keyboard = _get_slots_keyboard(slots, lang)
    await update.message.reply_text(slot_text, reply_markup=keyboard, parse_mode="HTML")
    return SLOT_ADD
