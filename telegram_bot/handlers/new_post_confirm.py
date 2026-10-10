"""Tasdiqlash ekrani (``confirm_post:*``) oqimining ajratilgan qismlari.

MONOLIT DEKOMPOZITSIYASI: ``handlers/new_post.py`` dagi
``confirm_post_callback`` 345+ qatorlik bitta funksiyaga aylangan edi —
ichida 6 ta mustaqil amal (kanal tanlash, kanal tasdiqlash, orqaga, bekor
qilish, tahrirlash, navbatga qo'shish, darhol/rejali saqlash) va uch marta
nusxalangan "kanal tanlash" bloki bor edi.

Bu modul shu amallarni kichik, bitta vazifali funksiyalarga ajratadi:

* :func:`channel_picker_markup` / :func:`ask_channel_choice` — ilgari UCH
  marta nusxalangan inline kanal tanlov klaviaturasi (endi bitta nusxa);
* :func:`resolve_selected_channel` — ``selected_channel_id`` aniqlash
  mantiqi (yagona kanal → avto-tanlash, ko'p kanal → ro'yxat, kanal yo'q →
  xabar); ilgari ``queue`` va ``ok`` oqimlarida alohida nusxada edi;
* :func:`find_next_available_slot` — navbat slotini bugun/ertaga/keyingi
  7 kunda izlash;
* :func:`persist_scheduled_posts` — ``db.add_post`` tsikli (``ALL`` uchun
  barcha kanallarga), ilgari ikki marta nusxalangan;
* :func:`handle_channel_action`, :func:`handle_channel_selected`,
  :func:`handle_back`, :func:`handle_cancel`, :func:`handle_edit`,
  :func:`handle_queue`, :func:`handle_ok` — bitta amalni bajaruvchi
  kichik handler'lar.

Xatti-harakat, FSM holatlari, i18n kalitlari va javob matnlari
O'ZGARMAGAN — bu faqat tuzilma refaktoringi. ``database.run_db`` ga
murojaat modul atributi orqali (``db.run_db``) qilinadi, shuning uchun
testlardagi monkeypatch kontrakti saqlanadi.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ConversationHandler

import database as db
from keyboards.callback_data import cb as _cb_safe
from keyboards.default import get_main_keyboard
from keyboards.inline import btn_label
from locales.translations import clear_fsm_data, get_text
from utils.date_format import format_datetime, format_time, weekday_label
from utils.helpers import get_auto_ad_injection_async, html_escape
from utils.silent_errors import log_silent_failure

# ``handlers/new_post.py`` ushbu modulni ``confirm_post_callback`` ICHIDA
# (kechikkan) import qiladi — shu sababli modullik darajadagi bu import
# aylanma bog'liqlik yaratmaydi.
from handlers.new_post import (
    CONFIRM_POST,
    EDIT_CONFIRM_FIELD,
    _content_for_db,
    _get_edit_confirm_keyboard,
    _queue_slot_label,
    _show_confirmation,
    _strip_unsupported_album_options,
    cancel_album_collections,
)

tashkent_tz = pytz.timezone("Asia/Tashkent")

#: Kanal tanlanmagan va umuman kanal yo'q holatida ishlatiladigan sarlavha.
DEFAULT_CHANNEL_TITLE = "Kanal"


# ===========================================================================
# UMUMIY YORDAMCHILAR
# ===========================================================================
def channel_picker_markup(channels, lang: str) -> InlineKeyboardMarkup:
    """Ko'p kanal uchun inline tanlov ro'yxati (+ «Orqaga» tugmasi)."""
    keyboard = []
    for ch_id, ch_title in channels:
        label = btn_label(ch_title, max_length=20)
        keyboard.append([
            InlineKeyboardButton(
                f"📢 {label}",
                callback_data=_cb_safe("confirm_post:ch", ch_id),
            )
        ])
    keyboard.append([
        InlineKeyboardButton(
            get_text("np_edit_back_btn", lang),
            callback_data="confirm_post:back",
        )
    ])
    return InlineKeyboardMarkup(keyboard)


async def ask_channel_choice(query, channels, lang: str) -> None:
    """«Kanalni tanlang» xabarini tanlov klaviaturasi bilan yuboradi."""
    await query.message.reply_text(
        get_text("new_post_choose_channel", lang),
        reply_markup=channel_picker_markup(channels, lang),
        parse_mode="HTML",
    )


async def reply_with_main_menu(query, context, key: str, is_admin: bool,
                               lang: str, **kwargs) -> None:
    """Asosiy menyu klaviaturasi bilan oddiy javob (bekor/xato holatlari)."""
    await query.message.reply_text(
        get_text(key, lang, **kwargs),
        reply_markup=get_main_keyboard(is_admin, context=context),
        parse_mode="HTML",
    )


async def drop_reply_markup(query) -> None:
    """Tugmalarni o'chiradi (xato jim yutiladi — oqim to'xtamasligi kerak)."""
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as _silent_exc:
        log_silent_failure("handlers.new_post_confirm:drop_reply_markup", _silent_exc)


async def resolve_selected_channel(query, context, user_id: int, is_admin: bool,
                                   lang: str):
    """``selected_channel_id`` ni aniqlaydi (barcha oqimlar uchun bitta mantiq).

    Returns:
        ``(status, channel_id, channel_title)`` — ``status``:

        * ``"ready"``  — kanal aniqlandi (davom etish mumkin);
        * ``"picker"`` — bir nechta kanal, tanlov ro'yxati ko'rsatildi
          (chaqiruvchi ``CONFIRM_POST`` qaytarishi kerak);
        * ``"none"``   — kanal yo'q, xabar yuborildi (chaqiruvchi FSM'ni
          tozalab ``ConversationHandler.END`` qaytarishi kerak).
    """
    selected = context.user_data.get("selected_channel_id")
    title = context.user_data.get("selected_channel_title", DEFAULT_CHANNEL_TITLE)
    if selected:
        return "ready", selected, title

    channels = await db.run_db(db.get_user_channels, user_id)
    if channels and len(channels) == 1:
        context.user_data["selected_channel_id"] = channels[0][0]
        context.user_data["selected_channel_title"] = channels[0][1]
        return "ready", channels[0][0], channels[0][1]
    if channels:
        await ask_channel_choice(query, channels, lang)
        return "picker", None, None
    await reply_with_main_menu(query, context, "np_no_channel", is_admin, lang)
    return "none", None, None


async def target_channels(user_id: int, selected_channel_id, channel_title: str):
    """«ALL» tanlangan bo'lsa barcha kanallar, aks holda bitta kanal."""
    if selected_channel_id == "ALL":
        return await db.run_db(db.get_user_channels, user_id)
    return [(selected_channel_id, channel_title)]


def post_payload(context) -> dict:
    """``db.add_post`` ga uzatiladigan umumiy maydonlar (user_data'dan)."""
    reaction_emojis = context.user_data.get("reaction_emojis")
    return {
        "post_type": context.user_data.get("post_type"),
        "content": _content_for_db(context.user_data.get("content"), reaction_emojis),
        "file_id": context.user_data.get("file_id"),
        "btn_text": context.user_data.get("btn_text"),
        "btn_url": context.user_data.get("btn_url"),
        "enable_reactions": context.user_data.get("enable_reactions", False),
        "reaction_emojis": reaction_emojis,
        "delete_after_hours": context.user_data.get("delete_after_hours", 0),
    }


async def persist_scheduled_posts(user_id: int, channels, payload: dict,
                                  scheduled_time, recurrence: dict) -> int:
    """Postni har bir maqsadli kanalga yozadi; muvaffaqiyatli yozuvlar soni."""
    ok_count = 0
    for ch_id, _ in channels:
        try:
            pid = await db.run_db(
                db.add_post,
                user_id=user_id,
                channel_id=ch_id,
                scheduled_time=scheduled_time,
                **payload,
                **recurrence,
            )
            if pid:
                ok_count += 1
        except Exception as _silent_exc:
            log_silent_failure("handlers.new_post_confirm:persist_scheduled_posts",
                               _silent_exc)
    return ok_count


async def find_next_available_slot(user_id: int, ch_id_for_q):
    """Navbat slotini izlaydi: bugun → ertaga → keyingi 2..7 kun."""
    now = datetime.now(tashkent_tz)
    slots = await db.run_db(db.get_queue_slots, user_id)
    occupied = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q, now.date())

    slot_dt, label = db.find_next_queue_slot(slots, occupied, now)
    if slot_dt:
        return slot_dt, label

    tomorrow = now + timedelta(days=1)
    tomorrow_start = tashkent_tz.localize(
        datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0)
    )
    occ_tom = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q,
                              tomorrow.date())
    slot_dt, label = db.find_next_queue_slot(slots, occ_tom, tomorrow_start)
    if slot_dt:
        return slot_dt, label

    for day_off in range(2, 8):
        future_date = now.date() + timedelta(days=day_off)
        occ = await db.run_db(db.get_queue_occupied_times, user_id, ch_id_for_q,
                              future_date)
        future_start = tashkent_tz.localize(
            datetime(future_date.year, future_date.month, future_date.day, 0, 0)
        )
        slot_dt, label = db.find_next_queue_slot(slots, occ, future_start)
        if slot_dt:
            return slot_dt, label
    return None, None


# ===========================================================================
# AMALLAR (har biri bitta callback harakatini bajaradi)
# ===========================================================================
async def handle_channel_action(query, context, user_id: int, is_admin: bool, lang: str):
    """``confirm_post:channel`` — kanal tanlash tugmasi."""
    channels = await db.run_db(db.get_user_channels, user_id)
    if not channels:
        await reply_with_main_menu(query, context, "new_post_no_channels", is_admin, lang)
        return ConversationHandler.END
    if len(channels) == 1:
        context.user_data["selected_channel_id"] = channels[0][0]
        context.user_data["selected_channel_title"] = channels[0][1]
        await _show_confirmation(query.message, context)
        return CONFIRM_POST
    await ask_channel_choice(query, channels, lang)
    return CONFIRM_POST


async def handle_channel_selected(query, context, raw_id: str):
    """``confirm_post:ch:<id>`` — aniq kanal tanlandi."""
    channels = await db.run_db(db.get_user_channels, query.from_user.id) or []
    found = None
    for cid, ctitle in channels:
        if str(cid) == raw_id:
            found = (cid, ctitle)
            break
    if not found:
        try:
            int_id = int(raw_id)
            for cid, ctitle in channels:
                if cid == int_id:
                    found = (cid, ctitle)
                    break
        except Exception as _silent_exc:
            log_silent_failure("handlers.new_post_confirm:handle_channel_selected",
                               _silent_exc)
    if found:
        context.user_data["selected_channel_id"] = found[0]
        context.user_data["selected_channel_title"] = found[1]
    await _show_confirmation(query.message, context)
    return CONFIRM_POST


async def handle_back(query, context):
    """``confirm_post:back`` — tasdiqlash ekraniga qaytish."""
    await _show_confirmation(query.message, context)
    return CONFIRM_POST


async def handle_cancel(query, context, user_id: int, is_admin: bool, lang: str):
    """``confirm_post:cancel`` — oqimni bekor qilish."""
    clear_fsm_data(context)
    cancel_album_collections(user_id)
    await drop_reply_markup(query)
    await reply_with_main_menu(query, context, "np_cancelled", is_admin, lang)
    return ConversationHandler.END


async def handle_edit(query, lang: str):
    """``confirm_post:edit`` — tahrirlash menyusini ochish."""
    await query.message.reply_text(
        get_text("np_edit_menu_title", lang),
        reply_markup=_get_edit_confirm_keyboard(lang),
        parse_mode="HTML",
    )
    return EDIT_CONFIRM_FIELD


async def handle_queue(query, context, user_id: int, is_admin: bool, lang: str):
    """``confirm_post:queue`` — eng yaqin bo'sh navbat slotiga qo'shish."""
    status, selected_channel_id, channel_title = await resolve_selected_channel(
        query, context, user_id, is_admin, lang)
    if status == "picker":
        return CONFIRM_POST
    if status == "none":
        clear_fsm_data(context)
        return ConversationHandler.END

    ch_id_for_q = selected_channel_id if selected_channel_id != "ALL" else "ALL"
    slot_dt, label = await find_next_available_slot(user_id, ch_id_for_q)
    if not slot_dt:
        await reply_with_main_menu(query, context, "np_no_slot", is_admin, lang)
        clear_fsm_data(context)
        return ConversationHandler.END

    # 🖼 ALBOM: sendMediaGroup'ga inline_keyboard ulanmaydi — albom uchun
    # tugma/reaksiya opsiyalari DB'ga yozilmaydi.
    _strip_unsupported_album_options(context)
    payload = post_payload(context)
    channels = await target_channels(user_id, selected_channel_id, channel_title)
    ok_count = await persist_scheduled_posts(
        user_id, channels, payload, slot_dt,
        {"recurrence_type": "none", "recurrence_day": None,
         "recurrence_time": None, "end_date": None},
    )

    await drop_reply_markup(query)

    if ok_count:
        # db.find_next_queue_slot "Bugun"/"Ertaga" qaytaradi — bu yorliq
        # har bir tilga (uz/ru/en) o'giriladi.
        await reply_with_main_menu(
            query, context, "np_queue_added", is_admin, lang,
            label=_queue_slot_label(label, lang),
            time=format_time(slot_dt, lang),
            channel=html_escape(channel_title),
            ad_line=await get_auto_ad_injection_async(user_id) or "",
        )
    else:
        await reply_with_main_menu(query, context, "np_queue_error", is_admin, lang)
    clear_fsm_data(context)
    return ConversationHandler.END


def _scheduled_when_text(context, lang: str, post_time_tz) -> str:
    """Rejalashtirish takrorlanishiga mos «qachon» matni."""
    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_day = context.user_data.get("confirm_recurrence_day")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")

    if recurrence_type == "daily" and recurrence_time_str:
        return get_text("np_scheduled_when_daily", lang,
                        time=format_time(recurrence_time_str, lang))
    if recurrence_type == "weekly" and recurrence_time_str:
        return get_text("np_scheduled_when_weekly", lang,
                        day=weekday_label(recurrence_day, lang),
                        time=format_time(recurrence_time_str, lang))
    return get_text("np_scheduled_when_single", lang,
                    time=format_datetime(post_time_tz, lang))


async def handle_ok(query, context, user_id: int, is_admin: bool, lang: str):
    """``confirm_post:ok`` — tanlangan vaqtga (yoki takrorlanish bilan) saqlash."""
    post_time = context.user_data.get("confirm_post_time")
    if not post_time:
        await reply_with_main_menu(query, context, "np_no_time", is_admin, lang)
        clear_fsm_data(context)
        return ConversationHandler.END

    status, selected_channel_id, channel_title = await resolve_selected_channel(
        query, context, user_id, is_admin, lang)
    if status == "picker":
        return CONFIRM_POST
    if status == "none":
        clear_fsm_data(context)
        return ConversationHandler.END

    recurrence_type = context.user_data.get("confirm_recurrence_type", "none")
    recurrence_day = context.user_data.get("confirm_recurrence_day")
    recurrence_time_str = context.user_data.get("confirm_recurrence_time_str")
    end_date = context.user_data.get("confirm_end_date")

    # 🖼 ALBOM: sendMediaGroup'ga inline_keyboard ulanmaydi — albom uchun
    # tugma/reaksiya opsiyalari DB'ga yozilmaydi.
    _strip_unsupported_album_options(context)
    payload = post_payload(context)
    delete_after_hours = payload["delete_after_hours"]

    post_time_tz = post_time.astimezone(tashkent_tz)
    channels = await target_channels(user_id, selected_channel_id, channel_title)
    ok_count = await persist_scheduled_posts(
        user_id, channels, payload, post_time_tz,
        {"recurrence_type": recurrence_type, "recurrence_day": recurrence_day,
         "recurrence_time": recurrence_time_str, "end_date": end_date},
    )

    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception as _silent_exc:
        log_silent_failure("handlers.new_post_confirm:handle_ok", _silent_exc,
                           user_id=user_id, lang=lang)

    if ok_count:
        when_text = _scheduled_when_text(context, lang, post_time_tz)
        del_info = (get_text("np_scheduled_del", lang, hours=delete_after_hours)
                    if delete_after_hours > 0 else "")
        ad_line = await get_auto_ad_injection_async(user_id)
        await query.message.reply_text(
            get_text("np_scheduled_ok", lang,
                     channel=html_escape(channel_title), when=when_text,
                     del_info=del_info) + (ad_line or ""),
            reply_markup=get_main_keyboard(is_admin, context=context),
            parse_mode="HTML",
        )
    else:
        await reply_with_main_menu(query, context, "np_save_error_bold", is_admin, lang)
    cancel_album_collections(user_id)
    clear_fsm_data(context)
    return ConversationHandler.END
