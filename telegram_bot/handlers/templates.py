"""📋 POST SHABLONLARI — takroriy postlarni shablon qilib saqlash (PHASE C, 9-band).

Oqim (📢 Kanallarim → kanal → [📋 Shablonlar])::

    📋 SHABLONLAR
    [➕ Yangi shablon]     — nom → matn (o'zgaruvchilar bilan) → saqlash
    [📋 Shablonni ishlatish] — shablon → o'zgaruvchilarni to'ldirish →
                               TO'G'RIDAN-TO'G'RI manual preview (universal
                               panel: darhol yuborish / rejalashtirish / ...)
    [🗑 O'chirish]          — shablonni tanlab o'chirish
    [◀️ Orqaga]             — kanal boshqaruv ekraniga qaytish

Shablon o'zgaruvchilari (speks — aynan 7 ta)::
    {TITLE}, {TEXT}, {PRICE}, {LINK}, {CTA}, {SOURCE}, {DATE}

Xavfsizlik (IDOR): barcha shablon amallari ``user_id`` bilan filtrlangan
DB funksiyalari orqali bajariladi — boshqa foydalanuvchining shablonini
ko'rish/ishlatish/o'chirish QAT'IYAN MUMKIN EMAS (``get_post_template``
va ``delete_post_template`` SQL darajasida ``WHERE user_id = ...``).

Shablon orqali post yaratilganda natija TO'G'RIDAN-TO'G'RI oddiy post
(✍️ manual) preview paneliga o'tadi — mavjud, sinovdan o'tgan yuborish /
rejalashtirish / 24 soatlik / takroriy e'lon infratuzilmasi qayta
ishlatiladi (dublikat detektori bilan birga).

FSM holatlari 485–490 — repodagi boshqa oqimlar bilan to'qnashmaydi
(470–472 kalendar, 480–483 avtopilot, 450–454 oddiy post).
"""

from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from keyboards.callback_data import cb
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang
from services.templates import (
    TEMPLATE_VARIABLES,
    extract_variables,
    parse_variable_values,
    render_template,
    validate_template_content,
)
from translations import templates_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# ============================================================
# FSM HOLATLARI (485–490 — mavjud holatlar bilan to'qnashmaydi)
# ============================================================
TPL_MENU = 485           # shablonlar menyusi (3 amal + Orqaga)
TPL_NEW_NAME = 486       # yangi shablon nomi kutilmoqda
TPL_NEW_CONTENT = 487    # yangi shablon matni kutilmoqda
TPL_USE_PICK = 488       # ishlatiladigan shablon tanlanmoqda
TPL_USE_VARS = 489       # o'zgaruvchi qiymatlari kutilmoqda
TPL_DEL_PICK = 490       # o'chiriladigan shablon tanlanmoqda

# ============================================================
# CALLBACK DATA (tpl_ prefiksi — 16 bayt byudjetida)
# ============================================================
CB_TPL_NEW = "tpl_new"        # ➕ Yangi shablon
CB_TPL_USE = "tpl_use"        # 📋 Shablonni ishlatish
CB_TPL_DEL = "tpl_del"        # 🗑 O'chirish
CB_TPL_PICK = "tpl_pick:"     # shablon tanlash (ishlatish uchun)
CB_TPL_RM = "tpl_rmv:"        # shablon o'chirish
CB_TPL_BACK = "tpl_back"      # ◀️ Orqaga (kanal paneliga)
CB_TPL_CANCEL = "tpl_cancel"  # ❌ Bekor qilish

#: user_data kalitlari (yagona manba — tozalash va testlar uchun).
UD_CHANNEL = "tpl_channel_id"
UD_TITLE = "tpl_channel_title"
UD_NAME = "tpl_new_name"
UD_TEMPLATE = "tpl_active"   # tanlangan shablon dict (id, name, content)


def clear_templates_session(context) -> None:
    """Shablonlar sessiyasini toza yopadi."""
    for key in (UD_CHANNEL, UD_TITLE, UD_NAME, UD_TEMPLATE):
        context.user_data.pop(key, None)


def _lang(context) -> str:
    try:
        return get_lang(context)
    except Exception:  # pragma: no cover
        return "uz"


# ============================================================
# KLAVIATURALAR
# ============================================================
def templates_menu_keyboard(lang: str = "uz") -> InlineKeyboardMarkup:
    """📋 Shablonlar menyusi (SPEKS: 3 amal + Orqaga)."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(templates_t("btn_new", lang),
                              callback_data=CB_TPL_NEW)],
        [InlineKeyboardButton(templates_t("btn_use", lang),
                              callback_data=CB_TPL_USE)],
        [InlineKeyboardButton(templates_t("btn_delete", lang),
                              callback_data=CB_TPL_DEL)],
        [InlineKeyboardButton(templates_t("btn_back", lang),
                              callback_data=CB_TPL_BACK)],
    ])


def _templates_list_keyboard(templates: list, action_prefix: str,
                             lang: str = "uz") -> InlineKeyboardMarkup:
    """Foydalanuvchining shablonlari ro'yxati (har biri alohida tugma)."""
    rows = []
    for item in templates or []:
        rows.append([InlineKeyboardButton(
            templates_t("tpl_button", lang,
                        name=(item.get("name") or "—")[:40]),
            callback_data=cb(action_prefix, int(item.get("id", 0))),
        )])
    rows.append([InlineKeyboardButton(templates_t("btn_back", lang),
                                      callback_data=CB_TPL_BACK)])
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
        logger.debug("shablonlar: edit ishlamadi", exc_info=True)
    try:
        await query.message.reply_text(text, reply_markup=markup,
                                       parse_mode="HTML")
        return True
    except Exception:
        logger.debug("shablonlar: xabar yuborib bo'lmadi", exc_info=True)
        return False


async def _safe_send(msg, text: str, markup=None) -> bool:
    try:
        await msg.reply_text(text, reply_markup=markup, parse_mode="HTML")
        return True
    except Exception:
        logger.debug("shablonlar: yuborish xatosi", exc_info=True)
        return False


# ============================================================
# KIRISH — 📢 Kanallarim → kanal → [📋 Shablonlar]
# ============================================================
async def channel_templates_entry(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Shablonlar menyusini ochadi (kanal egaligi — IDOR tekshiruvi)."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    channel_id = (query.data or "").split(":", 1)[1] if ":" in (query.data or "") else ""

    from handlers.channels import _owned_channel, _channel_title
    channel = await _owned_channel(user_id, channel_id)
    if channel is None:
        from keyboards.inline import render_channel_panel
        await _safe_edit(query, templates_t("not_found", lang),
                         render_channel_panel(channel_id, lang))
        return ConversationHandler.END

    clear_templates_session(context)
    context.user_data[UD_CHANNEL] = str(channel_id)
    context.user_data[UD_TITLE] = (channel[1] or "Kanal") if len(channel) > 1 else "Kanal"
    title = _channel_title(channel)

    await _safe_edit(
        query,
        templates_t("menu_title", lang, channel=title),
        templates_menu_keyboard(lang),
    )
    return TPL_MENU


# ============================================================
# TPL_MENU — menyulararo navigatsiya
# ============================================================
async def templates_menu_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE):
    """Menyu amallari: yangi / ishlatish / o'chirish / orqaga / bekor qilish."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return TPL_MENU
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    data = str(getattr(query, "data", "") or "")

    channel_id = str(context.user_data.get(UD_CHANNEL) or "")
    channel_title = str(context.user_data.get(UD_TITLE) or "")

    if data == CB_TPL_BACK:
        # ◀️ Orqaga — kanal boshqaruv ekraniga (kanal ichida qolamiz).
        from keyboards.inline import render_channel_panel
        if channel_id:
            from translations import channels_queue_t
            await _safe_edit(
                query,
                channels_queue_t(
                    "cq_ch_panel_title", lang,
                    channel=html_escape(channel_title or "Kanal")),
                render_channel_panel(channel_id, lang),
            )
        else:
            await _safe_edit(query, templates_t("cancel_done", lang))
        clear_templates_session(context)
        return ConversationHandler.END

    if data == CB_TPL_CANCEL:
        clear_templates_session(context)
        try:
            await query.edit_message_text(templates_t("cancel_done", lang),
                                          parse_mode="HTML")
        except Exception:
            pass
        return ConversationHandler.END

    if data == CB_TPL_NEW:
        count = await db.run_db(db.count_post_templates, user_id)
        if int(count or 0) >= int(db.POST_TEMPLATES_LIMIT):
            await _safe_edit(
                query, templates_t("limit_reached", lang,
                                   limit=db.POST_TEMPLATES_LIMIT),
                templates_menu_keyboard(lang))
            return TPL_MENU
        await _safe_edit(query, templates_t("ask_name", lang),
                         get_cancel_keyboard(lang))
        return TPL_NEW_NAME

    if data == CB_TPL_USE:
        templates = await db.run_db(db.get_post_templates, user_id)
        if not templates:
            await _safe_edit(query, templates_t("empty_list", lang),
                             templates_menu_keyboard(lang))
            return TPL_MENU
        await _safe_edit(query, templates_t("use_pick", lang),
                         _templates_list_keyboard(templates, CB_TPL_PICK,
                                                  lang))
        return TPL_USE_PICK

    if data == CB_TPL_DEL:
        templates = await db.run_db(db.get_post_templates, user_id)
        if not templates:
            await _safe_edit(query, templates_t("empty_list", lang),
                             templates_menu_keyboard(lang))
            return TPL_MENU
        await _safe_edit(query, templates_t("delete_pick", lang),
                         _templates_list_keyboard(templates, CB_TPL_RM, lang))
        return TPL_DEL_PICK

    return TPL_MENU


# ============================================================
# ➕ YANGI SHABLON — nom → matn → saqlash
# ============================================================
async def template_name_received(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """TPL_NEW_NAME: shablon nomi qabul qilinadi."""
    message = getattr(update, "message", None)
    if message is None:
        return TPL_NEW_NAME
    lang = _lang(context)
    text = str(getattr(message, "text", "") or "").strip()
    if not text or text.startswith("/"):
        await _safe_send(message, templates_t("ask_name", lang),
                         get_cancel_keyboard(lang))
        return TPL_NEW_NAME
    if len(text) > 128:
        await _safe_send(message, templates_t("name_too_long", lang),
                         get_cancel_keyboard(lang))
        return TPL_NEW_NAME

    context.user_data[UD_NAME] = text
    await _safe_send(message, templates_t("ask_content", lang),
                     get_cancel_keyboard(lang))
    return TPL_NEW_CONTENT


async def template_content_received(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):
    """TPL_NEW_CONTENT: shablon matni qabul qilinadi → saqlash."""
    message = getattr(update, "message", None)
    if message is None:
        return TPL_NEW_CONTENT
    lang = _lang(context)
    user_id = update.effective_user.id
    text = str(getattr(message, "text", "") or "").strip()

    ok, _reason = validate_template_content(text)
    if not ok:
        await _safe_send(message, templates_t("content_invalid", lang),
                         get_cancel_keyboard(lang))
        return TPL_NEW_CONTENT

    name = str(context.user_data.get(UD_NAME) or "").strip() or "Shablon"
    channel_id = context.user_data.get(UD_CHANNEL)
    variables = extract_variables(text)

    template_id = await db.run_db(
        db.create_post_template, user_id, name, text,
        channel_id=channel_id, variables=variables,
    )
    if not template_id:
        count = await db.run_db(db.count_post_templates, user_id)
        if int(count or 0) >= int(db.POST_TEMPLATES_LIMIT):
            await _safe_send(
                message, templates_t("limit_reached", lang,
                                     limit=db.POST_TEMPLATES_LIMIT),
                templates_menu_keyboard(lang))
            return TPL_MENU
        await _safe_send(message, templates_t("render_error", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU

    logger.info("Yangi post shabloni saqlandi (user=%s, tpl=%s, vars=%s)",
                user_id, template_id, variables)
    context.user_data.pop(UD_NAME, None)
    await _safe_send(
        message,
        templates_t("created", lang, name=html_escape(name))
        + f"\n<i>{', '.join(variables) or '—'}</i>",
        templates_menu_keyboard(lang),
    )
    return TPL_MENU


# ============================================================
# 📋 SHABLONNI ISHLATISH — tanlash → o'zgaruvchilar → manual preview
# ============================================================
async def template_pick_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """TPL_USE_PICK: shablon tanlandi (IDOR: faqat o'ziniki)."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return TPL_USE_PICK
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    data = str(getattr(query, "data", "") or "")
    try:
        template_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return TPL_USE_PICK

    # IDOR: get_post_template FAQAT egasiga qaytaradi (WHERE user_id).
    template = await db.run_db(db.get_post_template, template_id, user_id)
    if not template:
        context.user_data.pop(UD_TEMPLATE, None)  # eskirgan sessiya qoldiqlari yo'q
        await _safe_edit(query, templates_t("not_found", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU

    context.user_data[UD_TEMPLATE] = {
        "id": template["id"],
        "name": template["name"],
        "content": template["content"],
    }
    variables = extract_variables(template["content"])
    if not variables:
        return await _render_and_show_preview(query, context, {}, lang)

    var_lines = "\n".join(f"• <code>{v}</code>" for v in variables)
    await _safe_edit(
        query,
        templates_t("vars_prompt", lang, vars=var_lines),
        get_cancel_keyboard(lang),
    )
    return TPL_USE_VARS


async def template_vars_received(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE):
    """TPL_USE_VARS: o'zgaruvchi qiymatlari qabul qilinadi → render."""
    message = getattr(update, "message", None)
    if message is None:
        return TPL_USE_VARS
    lang = _lang(context)
    active = context.user_data.get(UD_TEMPLATE) or {}
    if not active.get("content"):
        await _safe_send(message, templates_t("stale", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU

    values = parse_variable_values(
        getattr(message, "text", ""),
        expected=extract_variables(active["content"]),
    )
    return await _render_and_show_preview_message(message, context, values,
                                                  lang)


async def _render_and_show_preview(query, context, values: dict,
                                   lang: str) -> int:
    """Render qilib, manual preview paneliga o'tkazadi (inline variant)."""
    active = context.user_data.get(UD_TEMPLATE) or {}
    result = render_template(active.get("content", ""), values)
    if not result.get("ok"):
        await _safe_edit(query, templates_t("render_error", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU
    return await _to_manual_preview(query.message, context, result["text"],
                                    lang)


async def _render_and_show_preview_message(message, context, values: dict,
                                           lang: str) -> int:
    """Render qilib, manual preview paneliga o'tkazadi (message variant)."""
    active = context.user_data.get(UD_TEMPLATE) or {}
    result = render_template(active.get("content", ""), values)
    if not result.get("ok"):
        await _safe_send(message, templates_t("render_error", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU
    return await _to_manual_preview(message, context, result["text"], lang)


async def _to_manual_preview(target_msg, context, post_text: str,
                             lang: str) -> int:
    """Render natijasini TO'G'RIDAN-TO'G'RI ✍️ oddiy post preview paneliga uzatadi.

    Mavjud, sinovdan o'tgan universal panel qayta ishlatiladi: darhol
    yuborish / vaqt belgilash / 24 soatlik / takroriy e'lon / tahrirlash /
    bekor qilish — hammasi shu yerda (dublikat detektori bilan birga).
    """
    from handlers.manual_post import (
        MANUAL_PREVIEW, UD_CONTENT, UD_POST_TYPE, UD_FILE_ID,
        _clear_manual_state,
    )
    from keyboards.inline import get_manual_post_panel

    _clear_manual_state(context)
    context.user_data[UD_CONTENT] = post_text
    context.user_data[UD_POST_TYPE] = "text"
    context.user_data.pop(UD_FILE_ID, None)
    context.user_data.pop(UD_TEMPLATE, None)

    try:
        await target_msg.reply_text(
            templates_t("rendered_title", lang)
            + html_escape(post_text)
            + templates_t("rendered_foot", lang),
            reply_markup=get_manual_post_panel(lang),
            parse_mode="HTML",
        )
    except Exception:
        logger.debug("shablon: preview yuborilmadi", exc_info=True)
    return MANUAL_PREVIEW


# ============================================================
# 🗑 O'CHIRISH
# ============================================================
async def template_remove_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """TPL_DEL_PICK: shablon o'chiriladi (IDOR: faqat egasi)."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return TPL_DEL_PICK
    try:
        await query.answer()
    except Exception:
        pass
    lang = _lang(context)
    user_id = query.from_user.id
    data = str(getattr(query, "data", "") or "")
    try:
        template_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return TPL_DEL_PICK

    # IDOR: delete_post_template FAQAT egasining qatorini o'chiradi.
    template = await db.run_db(db.get_post_template, template_id, user_id)
    deleted = await db.run_db(db.delete_post_template, template_id, user_id)
    if not deleted:
        context.user_data.pop(UD_TEMPLATE, None)
        await _safe_edit(query, templates_t("not_found", lang),
                         templates_menu_keyboard(lang))
        return TPL_MENU

    name = (template or {}).get("name") or "—"
    await _safe_edit(
        query,
        templates_t("deleted", lang, name=html_escape(name)),
        templates_menu_keyboard(lang),
    )
    return TPL_MENU


# ============================================================
# ESKIRGAN TUGMALAR
# ============================================================
async def templates_stale_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE):
    """Eskirgan ``tpl_`` tugmalari (sessiyadan tashqari) — toast, crash yo'q."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer(templates_t("stale", get_lang(context)))
    except Exception:
        pass
    return ConversationHandler.END


__all__ = [
    "TPL_MENU", "TPL_NEW_NAME", "TPL_NEW_CONTENT", "TPL_USE_PICK",
    "TPL_USE_VARS", "TPL_DEL_PICK",
    "CB_TPL_NEW", "CB_TPL_USE", "CB_TPL_DEL", "CB_TPL_PICK", "CB_TPL_RM",
    "CB_TPL_BACK", "CB_TPL_CANCEL",
    "channel_templates_entry", "templates_menu_callback",
    "template_name_received", "template_content_received",
    "template_pick_callback", "template_vars_received",
    "template_remove_callback", "templates_stale_callback",
    "clear_templates_session", "templates_menu_keyboard",
    "TEMPLATE_VARIABLES",
]
