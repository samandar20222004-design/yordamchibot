"""Admin RBAC (Role-Based Access Control) Enforcement Middleware & Helpers.

PHASE 2 · 3-QADAM: Admin callbacklarida RBAC (user_id admin ro'yxatida borligi)
qat'iy tekshiriladi (server-side from_user.id asosida).
"""

from __future__ import annotations
import logging
from functools import wraps
from typing import Callable, Any
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

logger = logging.getLogger(__name__)

# Default access denied alert message
RBAC_DENIED_MESSAGE = "⛔ Kirish taqiqlangan! Ushbu amal faqat adminlar uchun."


def is_admin_user(user_id: int | None) -> bool:
    """Strict check whether user_id belongs to an authorized admin."""
    if user_id is None or not isinstance(user_id, int) or user_id <= 0:
        return False

    try:
        from config import ADMIN_IDS_SET
        if user_id in ADMIN_IDS_SET:
            return True
    except Exception:
        pass

    try:
        from services.rbac_service import is_admin as rbac_is_admin
        if rbac_is_admin(user_id):
            return True
    except Exception:
        pass

    return False


def admin_rbac_required(func: Callable) -> Callable:
    """
    Decorator for admin callback queries and handlers to enforce strict RBAC.
    Rejects any non-admin user with an immediate alert and suppresses execution.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args: Any, **kwargs: Any):
        query = getattr(update, "callback_query", None)
        user = getattr(query, "from_user", None) or getattr(update, "effective_user", None)
        user_id = getattr(user, "id", None)

        if not is_admin_user(user_id):
            logger.warning(
                "RBAC VIOLATION: Unauthorized user %s attempted admin callback '%s'",
                user_id,
                getattr(query, "data", None) if query else None,
            )
            if query:
                try:
                    await query.answer(text=RBAC_DENIED_MESSAGE, show_alert=True)
                except Exception:
                    pass
            elif getattr(update, "effective_message", None):
                try:
                    await update.effective_message.reply_text(RBAC_DENIED_MESSAGE)
                except Exception:
                    pass
            return ConversationHandler.END

        return await func(update, context, *args, **kwargs)

    return wrapper


def check_callback_rbac(update: Update) -> bool:
    """Convenience helper to verify callback user RBAC server-side."""
    query = getattr(update, "callback_query", None)
    user = getattr(query, "from_user", None) or getattr(update, "effective_user", None)
    return is_admin_user(getattr(user, "id", None))
