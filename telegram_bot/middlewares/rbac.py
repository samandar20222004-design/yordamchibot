"""Admin RBAC (Role-Based Access Control) Enforcement Middleware & Helpers.

PHASE 2 · 3-QADAM: Admin callbacklarida RBAC (user_id admin ro'yxatida borligi)
qat'iy tekshiriladi (server-side from_user.id asosida).
"""

from __future__ import annotations
import asyncio
import logging
import os
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Any
from telegram import Update
from telegram.ext import (
    ApplicationHandlerStop,
    BaseHandler,
    ContextTypes,
    ConversationHandler,
)

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

        # is_admin_user kesh o'tib ketsa DB'ga sinxron boradi — event loop'ni qotirmaslik uchun thread'da.
        if not await asyncio.to_thread(is_admin_user, user_id):
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


# ============================================================================
# PHASE 3 — RESURS (KANAL/POST) DARAJASIDAGI RBAC VA IDOR HIMOYA QATLAMI
# ============================================================================
#
# Muammo
# ------
# ``user_id`` yoki ``post_id`` ning o'zi YETARLI EMAS: inline callback
# payload'ini foydalanuvchi o'zgartirib, boshqa birovning kanali/post ID'sini
# yuborishi mumkin (IDOR).  Shu sababli HAR BIR state-changing callback
# AVVAL resurs bo'yicha ruxsatni tekshiradi:
#
#   1) "kim bosdi?" — FAQAT server-side ``from_user.id`` (payload'ga
#      ISHONILMAYDI);
#   2) "qaysi resurs?" — callback payload'idagi ID yoki ``context`` dagi
#      (server-side saqlangan) ID;
#   3) "ruxsat bormi?" — ``services.rbac_service.can(...)`` (markaziy nuqta).
#
# Fail-closed: resurs topilmasa, rol aniqlanmasa yoki DB xatosi bo'lsa —
# so'rov yopiq rad etiladi va foydalanuvchiga "Permission Denied" ko'rsatiladi.

from services import rbac_service  # noqa: E402  (pastda ishlatiladi)
from services.rbac_service import (  # noqa: E402
    AccessDecision,
    ResourcePermissionDenied,
    parse_callback_id,
)

#: Resurs tekshiruvi rad etilganda ko'rsatiladigan standart matn (uz).
RBAC_PERMISSION_DENIED_MESSAGE = "⛔ Ruxsat yo'q (Permission Denied)."

#: Tilga mos "Permission Denied" matnlari.
RBAC_DENIED_TEXTS = {
    "uz": "⛔ Ruxsat yo'q (Permission Denied).",
    "ru": "⛔ Нет доступа (Permission Denied).",
    "en": "⛔ Permission denied.",
}

#: Kanal ID uchun ruxsat etilgan maksimal uzunlik (Telegram: ~64 belgi).
RESOURCE_ID_MAX_LEN = 64


def _actor_lang(update: Update, context: Any = None) -> str:
    """Foydalanuvchi tilini arzon yo'l bilan aniqlaydi (DB'siz, fail-safe)."""
    try:
        user_data = getattr(context, "user_data", None) or {}
        lang = str(user_data.get("lang") or "").strip().lower()
        if lang in RBAC_DENIED_TEXTS:
            return lang
    except Exception:
        pass
    return "uz"


def denied_message(lang: str = "uz") -> str:
    """Tilga mos "Permission Denied" matni."""
    return RBAC_DENIED_TEXTS.get(str(lang or "uz").strip().lower(),
                                 RBAC_PERMISSION_DENIED_MESSAGE)


def actor_id(update: Update) -> int | None:
    """So'rovni yuborgan foydalanuvchi ID'si — FAQAT server-side maydonlardan."""
    query = getattr(update, "callback_query", None)
    user = getattr(query, "from_user", None) if query is not None else None
    if user is None:
        user = getattr(update, "effective_user", None)
    user_id = getattr(user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        return None
    return user_id


def callback_data_of(update: Update) -> str | None:
    """Callback payload'i (bo'lmasa ``None``)."""
    query = getattr(update, "callback_query", None)
    data = getattr(query, "data", None) if query is not None else None
    return str(data) if data is not None else None


def parse_resource_id(value, *, numeric: bool = False):
    """Resurs ID'sini QAT'IY tekshiradi.

    ``numeric=True`` (post/receipt ID) — faqat musbat butun son.
    ``numeric=False`` (kanal ID) — ``-1001234567890`` ko'rinishidagi butun son
    yoki ``@username``.  Bo'shliq/nazorat belgilari/uzun payload — rad.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or len(text) > RESOURCE_ID_MAX_LEN:
        return None
    if numeric:
        return parse_callback_id(text)
    if text.startswith("@"):
        body = text[1:]
        if not body or not all(c.isalnum() or c == "_" for c in body):
            return None
        return text
    body = text[1:] if text.startswith("-") else text
    if body.isdigit() and body.isascii():
        return text
    return None


def resource_id_from_callback(update: Update, prefix: str, *, index: int = 0,
                              sep: str = ":", numeric: bool = False):
    """Callback payload'idan resurs ID'sini ajratib oladi (``prefix`` + ID).

    ``index`` — ``prefix`` dan keyingi bo'laklar indeksi
    (masalan ``set_style:<channel_id>:<tone>`` uchun ``index=0``).
    """
    data = callback_data_of(update)
    if data is None or prefix is None:
        return None
    head = str(prefix)
    if not data.startswith(head):
        return None
    tail = data[len(head):]
    parts = tail.split(sep)
    if index < 0 or index >= len(parts):
        return None
    return parse_resource_id(parts[index], numeric=numeric)


def post_id_from_callback(update: Update, prefix: str, **kwargs):
    """Post ID'sini callback payload'idan oladi (qat'iy musbat butun son)."""
    return resource_id_from_callback(update, prefix, numeric=True, **kwargs)


async def _notify_denied(update: Update, context: Any = None, message: str | None = None,
                         show_alert: bool = True) -> None:
    """Rad javobini foydalanuvchiga yetkazadi (xato bo'lsa jim o'tadi)."""
    text = message or denied_message(_actor_lang(update, context))
    query = getattr(update, "callback_query", None)
    if query is not None:
        try:
            await query.answer(text[:190], show_alert=show_alert)
            return
        except TypeError:  # eski mock'lar kwargs'ni qabul qilmasligi mumkin
            try:
                await query.answer(text[:190])
                return
            except Exception:
                pass
        except Exception:
            pass
    msg = getattr(update, "effective_message", None) or getattr(update, "message", None)
    if msg is not None:
        try:
            await msg.reply_text(text)
        except Exception:
            logger.debug("RBAC rad javobini yuborib bo'lmadi", exc_info=True)


async def enforce_resource_access(update: Update, *, resource_type: str = "channel",
                                  resource_id=None, action: str = "view",
                                  allow_admin: bool = False, notify: bool = True,
                                  message: str | None = None,
                                  show_alert: bool = True,
                                  context: Any = None,
                                  db_module: Any = None) -> bool:
    """YAGONA IDOR himoya nuqtasi: resurs ustida amalga ruxsat bormi?

    Args:
        update: PTB ``Update`` (yoki to'g'ridan-to'g'ri ``CallbackQuery``).
        resource_type: ``channel`` | ``post`` | ``member`` | ``system``.
        resource_id: kanal ID (yoki post ID) — odatda callback payload'idan
            olingan, ``parse_resource_id`` bilan tekshirilgan qiymat.
        action: ``create`` | ``edit`` | ``approve`` | ``schedule`` | ``publish``
            | ``view`` | ``view_analytics`` | ``manage_members`` | ...
        allow_admin: eski xulq-atvorni saqlash uchun admin override (default
            ``False`` — yangi kodda ishlatilmasin).
        notify: rad etilganda foydalanuvchiga "Permission Denied" ko'rsatilsinmi.
        show_alert: callback javobi alert (modal) ko'rinishida bo'lsinmi.

    Returns:
        ``True`` — ruxsat bor; ``False`` — so'rov YOPIQ rad etildi (handler
        davom etmasligi shart).
    """
    user_id = actor_id(update)
    resource_text = (parse_resource_id(resource_id)
                     if getattr(resource_id, "__class__", None) is not int
                     else parse_resource_id(str(resource_id)))
    if resource_type not in ("system", None):  # system — resurs ID talab qilmaydi
        if resource_text is None:
            logger.warning(
                "RBAC/IDOR: resurs ID buzilgan/yo'q (user=%s, type=%s, action=%s, id=%r)",
                user_id, resource_type, action, str(resource_id)[:64],
            )
            if notify:
                await _notify_denied(update, context, message, show_alert)
            return False
    else:
        resource_text = None if resource_id in (None, "") else str(resource_id)[:64]

    if user_id is None:
        logger.warning("RBAC/IDOR: so'rov egasi aniqlanmadi (type=%s, action=%s)",
                       resource_type, action)
        if notify:
            await _notify_denied(update, context, message, show_alert)
        return False

    decision: AccessDecision = await rbac_service.check(
        user_id, resource_type=resource_type, resource_id=resource_text,
        action=action, db_module=db_module, allow_admin=allow_admin,
    )
    if decision.allowed:
        return True

    logger.warning(
        "RBAC/IDOR rad etildi: user=%s resource=%s:%s action=%s role=%s sabab=%s",
        user_id, resource_type, resource_text, action, decision.role,
        decision.reason,
    )
    if notify:
        await _notify_denied(update, context, message, show_alert)
    return False


async def require_resource_access(update: Update, **kwargs) -> bool:
    """:func:`enforce_resource_access` — rad etilganda istisno ko'taradi."""
    notify = kwargs.pop("notify", True)
    context = kwargs.pop("context", None)
    allowed = await enforce_resource_access(update, context=context,
                                            notify=notify, **kwargs)
    if not allowed:
        user_id = actor_id(update)
        raise ResourcePermissionDenied(AccessDecision(
            False, user_id=user_id, resource_type=kwargs.get("resource_type"),
            resource_id=str(kwargs.get("resource_id") or "")[:64] or None,
            action=kwargs.get("action"), reason="denied",
        ))
    return True


def resource_guard(*, resource_type: str = "channel", action: str = "view",
                   resource_id=None, prefix: str | None = None,
                   id_index: int = 0, numeric_id: bool = False,
                   context_key: str | None = None, allow_admin: bool = False,
                   notify: bool = True, message: str | None = None,
                   raise_error: bool = False):
    """Dekorator: handlerni resurs ruxsatidan O'TKAZIB ishga tushiradi.

    Resurs ID manbasi (birinchi topilgani ishlatiladi):

    * ``resource_id`` — aniq qiymat yoki ``(update, context) -> id`` callable;
    * ``prefix`` — callback payload'i (``ch_np:<channel_id>``);
    * ``context_key`` — server-side saqlangan ID (``context.user_data``).

    Misol::

        @resource_guard(resource_type="channel", action="create",
                        prefix=CB_CHANNEL_NEW_POST)
        async def channel_new_post_callback(update, context): ...
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(update: Update, context: Any = None, *args: Any, **kwargs: Any):
            rid = None
            if callable(resource_id):
                try:
                    rid = resource_id(update, context)
                except Exception:  # fail-closed
                    rid = None
            elif resource_id is not None:
                rid = resource_id
            if rid is None and prefix:
                rid = resource_id_from_callback(update, prefix, index=id_index,
                                                numeric=numeric_id)
            if rid is None and context_key:
                try:
                    rid = (getattr(context, "user_data", None) or {}).get(context_key)
                except Exception:
                    rid = None
            allowed = await enforce_resource_access(
                update, resource_type=resource_type, resource_id=rid,
                action=action, allow_admin=allow_admin, notify=notify,
                message=message, context=context,
            )
            if not allowed:
                if raise_error:
                    raise ResourcePermissionDenied(AccessDecision(
                        False, user_id=actor_id(update), resource_type=resource_type,
                        resource_id=str(rid)[:64] if rid else None, action=action,
                        reason="denied",
                    ))
                return None
            return await func(update, context, *args, **kwargs)

        wrapper.__rbac_resource__ = {
            "resource_type": resource_type, "action": action,
            "prefix": prefix, "allow_admin": allow_admin,
        }
        return wrapper

    return decorator


# --- PTB middleware (ixtiyoriy, qatlamli himoya) ---------------------------

@dataclass(frozen=True)
class ResourceRule:
    """Callback prefiksi → resurs/amal qoidasi (middleware uchun)."""

    prefix: str
    resource_type: str
    action: str
    id_index: int = 0
    numeric_id: bool = False
    allow_admin: bool = False
    answer_alert: bool = True


def default_resource_rules() -> tuple:
    """Standart qoidalar — eng xavfli (state-changing) callback'lar.

    Ro'yxat ataylab QISQA: faqat yozuvchi amallar.  O'qish callback'lari
    (masalan ``ch_op:``) handler ichida o'z tekshiruvidan o'tadi — middleware
    ularni ikkinchi marta DB'ga bormasdan qoldiradi.
    """
    from keyboards.callback_data import (
        CB_CHANNEL_DELETE, CB_CHANNEL_NEW_POST, CB_CHANNEL_AUTOPILOT,
        CB_CHANNEL_VOICE, CB_SET_STYLE, CB_TEAM_APPROVE, CB_TEAM_EDIT,
        CB_TEAM_REJECT,
    )
    return (
        ResourceRule(CB_CHANNEL_DELETE, "channel", "delete_channel", allow_admin=True),
        ResourceRule(CB_CHANNEL_NEW_POST, "channel", "create"),
        ResourceRule(CB_CHANNEL_AUTOPILOT, "channel", "create"),
        ResourceRule(CB_CHANNEL_VOICE, "channel", "edit", allow_admin=True),
        # ``set_style:<channel_id>:<tone>`` — ID birinchi bo'lak.
        ResourceRule(CB_SET_STYLE, "channel", "edit", id_index=0, allow_admin=True),
        ResourceRule(CB_TEAM_APPROVE, "post", "approve", numeric_id=True),
        ResourceRule(CB_TEAM_REJECT, "post", "reject", numeric_id=True),
        ResourceRule(CB_TEAM_EDIT, "post", "edit", numeric_id=True),
    )


def match_resource_rule(update: Update, rules: tuple | None = None):
    """Update'ga mos keladigan birinchi qoidani qaytaradi (aks holda ``None``)."""
    data = callback_data_of(update)
    if not data:
        return None
    for rule in (rules if rules is not None else default_resource_rules()):
        if data.startswith(rule.prefix):
            return rule
    return None


def check_resource_rule(update: Update, rules: tuple | None = None):
    """Middleware ``check_update`` qobig'i: mos qoida + resurs ID'si."""
    if actor_id(update) is None:
        return None
    rule = match_resource_rule(update, rules)
    if rule is None:
        return None
    rid = resource_id_from_callback(update, rule.prefix, index=rule.id_index,
                                    numeric=rule.numeric_id)
    return (rule, rid)


class ResourceRBACMiddleware(BaseHandler):
    """PTB middleware — callback'larni handler'dan OLDIN resurs bo'yicha tekshiradi.

    ``application.add_handler(ResourceRBACMiddleware(), group=-2)``

    * mos kelmagan update → ``None`` (zanjir o'zgarmaydi);
    * ruxsat bor → oddiy davom (keyingi guruhlar ishlaydi);
    * ruxsat yo'q → "Permission Denied" alert + ``ApplicationHandlerStop``
      (handler UMUMAN chaqirilmaydi).

    Fail-closed: ID buzilgan/yo'q bo'lsa ham rad etiladi.
    """

    def __init__(self, rules: tuple | None = None, enabled: bool = True):
        super().__init__(callback=self._dispatch, block=True)
        self.rules = tuple(rules) if rules is not None else None
        self.enabled = bool(enabled)

    # --- PTB interfeysi -------------------------------------------------
    def check_update(self, update: Update):
        if not self.enabled:
            return None
        return check_resource_rule(update, self.rules)

    async def _dispatch(self, update: Update, context: Any = None) -> None:
        matched = check_resource_rule(update, self.rules)
        if matched is None:
            return
        rule, rid = matched
        allowed = await enforce_resource_access(
            update, resource_type=rule.resource_type, resource_id=rid,
            action=rule.action, allow_admin=rule.allow_admin,
            context=context, show_alert=rule.answer_alert,
        )
        if not allowed:
            # Handler'lar UMUMAN ishlamaydi: guruh zanjiri shu yerda to'xtaydi.
            raise ApplicationHandlerStop


def install_resource_middleware(app, rules: tuple | None = None, group: int = -2,
                                enabled: bool | None = None):
    """Middleware'ni Application'ga qo'shadi (env bilan o'chirish mumkin).

    ``RBAC_RESOURCE_MIDDLEWARE=0`` — qatlamli himoyani o'chiradi (handler
    ichidagi tekshiruvlar BARIBIR ishlaydi).
    """
    if enabled is None:
        enabled = os.getenv("RBAC_RESOURCE_MIDDLEWARE", "1").strip().lower() not in (
            "0", "false", "no", "off", "disabled",
        )
    if not enabled:
        logger.info("ResourceRBACMiddleware o'chirilgan (RBAC_RESOURCE_MIDDLEWARE=0)")
        return None
    middleware = ResourceRBACMiddleware(rules)
    app.add_handler(middleware, group=group)
    return middleware
