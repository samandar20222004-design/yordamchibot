"""Telegram callbacks for Phase E team approval cards.

The legacy posting FSM is not replaced here.  These callbacks are an additive
entry point for workflow rows created by ``TeamService``.
"""
from __future__ import annotations

import html
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from locales.translations import get_lang
from services.channels.team import TeamService

logger = logging.getLogger(__name__)


def _post_id(query) -> int | None:
    try:
        return int((query.data or "").split(":", 1)[1])
    except (TypeError, ValueError, IndexError):
        return None


async def _finish(query, text: str):
    try:
        await query.answer(text[:180], show_alert=False)
    except Exception:
        pass
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=None)
    except Exception:
        logger.debug("Approval card edit failed", exc_info=True)


async def team_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = _post_id(query)
    if pid is None:
        await _finish(query, "❌ Post identifikatori noto'g'ri.")
        return ConversationHandler.END
    result = await TeamService(db).approve(pid, query.from_user.id)
    await _finish(query, "✅ Post tasdiqlandi. Endi schedulerga rejalashtirish mumkin." if result.get("ok")
                  else "⛔ Sizda bu postni tasdiqlash huquqi yo'q yoki post holati o'zgargan.")
    return ConversationHandler.END


async def team_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = _post_id(query)
    result = await TeamService(db).reject(pid, query.from_user.id) if pid is not None else {"ok": False}
    await _finish(query, "❌ Post rad etildi va qoralamaga qaytarildi." if result.get("ok")
                  else "⛔ Rad etish amalga oshmadi.")
    return ConversationHandler.END


async def team_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    pid = _post_id(query)
    if pid is None:
        await _finish(query, "❌ Post identifikatori noto'g'ri.")
        return ConversationHandler.END
    # Editing remains an explicit FSM entry in the existing bot.  Store only the
    # post id in user_data; the next content handler can safely consume it.
    context.user_data["team_edit_post_id"] = pid
    await _finish(query, "✏️ Yangi matnni yuboring. Post qayta tasdiqlashga qaytadi.")
    return ConversationHandler.END


async def send_approval_request(bot, chat_id: int, post_id: int, preview: str):
    """Send the approval card; callers choose the admin/owner recipient."""
    from services.channels.team import build_approval_keyboard
    safe_preview = html.escape(str(preview or "")[:3500])
    return await bot.send_message(chat_id=chat_id, text=("📝 <b>Tasdiqlash kutilmoqda</b>\n\n" + safe_preview),
                                  parse_mode="HTML", reply_markup=build_approval_keyboard(post_id))


__all__ = ["send_approval_request", "team_approve_callback", "team_edit_callback", "team_reject_callback"]
