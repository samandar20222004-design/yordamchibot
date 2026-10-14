"""Telegram callbacks for Phase E team approval cards.

The legacy posting FSM is not replaced here.  These callbacks are an additive
entry point for workflow rows created by ``TeamService``.

IDOR himoyasi
-----------------------
Tasdiqlash kartochkasidagi ``post_id`` foydalanuvchi tomonidan
SOXTALASHTIRILISHI mumkin (``team_ok:<boshqa_post_id>``).  Shu sababli har bir
callback:

1. ``from_user.id`` — FAQAT server-side (payload'ga ishonilmaydi);
2. ``post_id`` — qat'iy musbat butun son (``parse_callback_id``);
3. ``services.rbac_service.can(user_id, resource_type="post", ...)`` — post
   AYNAN shu foydalanuvchining kanaliga tegishli ekani va uning roli
   (owner/editor/scheduler/analyst) shu amalga yetarli ekani tekshiriladi;

Ruxsat bo'lmasa — so'rov YOPIQ rad etiladi (Permission Denied alert), hech
qanday holat o'zgarmaydi va hech qanday ma'lumot oshkor qilinmaydi.
"""
from __future__ import annotations

import html
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from keyboards.callback_data import (
    CB_TEAM_APPROVE,
    CB_TEAM_EDIT,
    CB_TEAM_REJECT,
)
from middlewares.rbac import (
    enforce_resource_access,
    post_id_from_callback,
)
from locales.translations import get_lang, get_text
from services.channels.team import TeamService

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

#: Post bo'yicha ish oqimi amali → talab qilinadigan RBAC ruxsati.
_POST_ACTIONS = {
    CB_TEAM_APPROVE: "approve",
    CB_TEAM_REJECT: "reject",
    CB_TEAM_EDIT: "edit",
}


async def _user_lang(context, user_id) -> str:
    """Foydalanuvchi tili (uz/ru/en): keshdan yoki DB'dan; xatoda kesh/uz — handler hech qachon yiqilmaydi."""
    try:
        from handlers.start import ensure_user_lang

        return await ensure_user_lang(context, user_id)
    except Exception as _silent_exc:
        log_silent_failure("handlers.team:_user_lang", _silent_exc)
        return get_lang(context) if context is not None else "uz"


async def _finish(query, text: str):
    try:
        await query.answer(text[:180], show_alert=False)
    except Exception as _silent_exc:
        log_silent_failure("handlers.team:_finish", _silent_exc)
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=None)
    except Exception:
        logger.debug("Approval card edit failed", exc_info=True)


async def _authorized_post_id(update: Update, query, prefix: str, context=None):
    """Callback uchun post ID'sini tekshiradi va RBAC ruxsatini oladi.

    Qaytadi: ``int`` (ruxsat bor) yoki ``None`` (rad etilgan/buzilgan payload).
    """
    post_id = post_id_from_callback(update, prefix)
    if post_id is None:
        logger.warning(
            "RBAC: team callback payload buzilgan (user=%s, data=%r)",
            getattr(getattr(query, "from_user", None), "id", None),
            str(getattr(query, "data", None))[:64],
        )
        lang = await _user_lang(context, getattr(getattr(query, "from_user", None), "id", None))
        await _finish(query, get_text("team_err_post_id", lang))
        return None
    action = _POST_ACTIONS.get(prefix, "view")
    allowed = await enforce_resource_access(
        update, resource_type="post", resource_id=post_id, action=action,
        context=None,
    )
    if not allowed:
        # Rad javobi ``enforce_resource_access`` ichida yuborilgan.
        return None
    return post_id


async def team_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = await _authorized_post_id(update, query, CB_TEAM_APPROVE, context)
    if pid is None:
        return ConversationHandler.END
    # Xizmat qatlami o'z tekshiruvini TAKRORLAYDI (chuqur himoya).
    result = await TeamService(db).approve(pid, query.from_user.id)
    lang = await _user_lang(context, query.from_user.id)
    await _finish(query, get_text("team_approved" if result.get("ok") else "team_approve_denied", lang))
    return ConversationHandler.END


async def team_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = await _authorized_post_id(update, query, CB_TEAM_REJECT, context)
    if pid is None:
        return ConversationHandler.END
    result = await TeamService(db).reject(pid, query.from_user.id)
    lang = await _user_lang(context, query.from_user.id)
    await _finish(query, get_text("team_rejected" if result.get("ok") else "team_reject_failed", lang))
    return ConversationHandler.END


async def team_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # tahrirlash ham resurs ruxsatini talab qiladi — ilgari bu yerda
    # tekshiruv YO'Q edi (har qanday foydalanuvchi post ID'sini user_data'ga
    # yozib, tahrirlash oqimini ochib olardi).
    pid = await _authorized_post_id(update, query, CB_TEAM_EDIT, context)
    if pid is None:
        return ConversationHandler.END
    # Editing remains an explicit FSM entry in the existing bot.  Store only the
    # post id in user_data; the next content handler can safely consume it.
    context.user_data["team_edit_post_id"] = pid
    await _finish(query, get_text("team_edit_prompt", await _user_lang(context, query.from_user.id)))
    return ConversationHandler.END


async def send_approval_request(bot, chat_id: int, post_id: int, preview: str):
    """Send the approval card; callers choose the admin/owner recipient."""
    from services.channels.team import build_approval_keyboard
    safe_preview = html.escape(str(preview or "")[:3500])
    try:
        lang = await db.run_db(db.get_user_language, chat_id) or "uz"
    except Exception as _silent_exc:
        log_silent_failure("handlers.team:send_approval_request:lang", _silent_exc)
        lang = "uz"
    return await bot.send_message(chat_id=chat_id, text=(get_text("team_approval_pending", lang) + "\n\n" + safe_preview),
                                  parse_mode="HTML", reply_markup=build_approval_keyboard(post_id))


__all__ = ["send_approval_request", "team_approve_callback", "team_edit_callback", "team_reject_callback"]
