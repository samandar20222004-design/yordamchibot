"""RBACService — PostAssist V2 (6-bosqich): rollar va ruxsatlar.

Rollar (``Role``)
-----------------
================  =========================================================
Rol               Vazifasi
================  =========================================================
``OWNER``         Bot egasi — barcha ruxsatlar (jumladan tizim sozlamalari).
``SUPER_ADMIN``   Bosh admin — to'lov, promo va foydalanuvchilar boshqaruvi.
``ADMIN``         Promo-kodlar va foydalanuvchilar boshqaruvi.
``MODERATOR``     Faqat foydalanuvchilar boshqaruvi.
``FINANCE``       Faqat to'lovlar (chek tasdiqlash/rad etish).
``USER``          Oddiy foydalanuvchi (admin emas).
================  =========================================================

Ruxsatlar
---------
* ``manage_payments``  → FINANCE, SUPER_ADMIN, OWNER
* ``manage_promos``    → ADMIN, SUPER_ADMIN, OWNER
* ``manage_users``     → MODERATOR, ADMIN, SUPER_ADMIN, OWNER
* ``system_settings``  → OWNER

Orqaga moslik (backward compatibility)
--------------------------------------
Eski ``ADMIN_ID`` / ``ADMIN_IDS`` ro'yxati **o'zgarmaydi**:

* ``ADMIN_ID`` (asosiy admin) — avtomatik ``OWNER``;
* ``ADMIN_IDS`` ichidagi qolgan raqamlar — avtomatik ``SUPER_ADMIN``;
* qo'shimcha rollar DB'da (``admin_roles`` jadvali va ``users.role`` ustuni)
  saqlanadi — ``set_role()`` orqali beriladi;
* DB'dagi rol eski admin rolidan **past** bo'lsa, eski (yuqori) rol saqlanadi —
  legacy admin hech qachon ruxsatdan mahrum bo'lib qolmaydi.

DB mavjud bo'lmaganda ham ishlaydi: rol aniqlanmasa — xavfsiz tomon, ya'ni
``Role.USER`` (yoki legacy admin uchun eski rol) qaytariladi.

Foydalanish::

    from services.rbac_service import (
        Role, require_permission, require_role, has_permission,
        PERM_MANAGE_PAYMENTS,
    )

    @require_permission(PERM_MANAGE_PAYMENTS)
    async def approve_receipt(update, context): ...
"""

from __future__ import annotations

import enum
import functools
import inspect
import logging
import os
import threading
import time

from config import ADMIN_ID, ADMIN_IDS_SET
import database as db

logger = logging.getLogger(__name__)


# ============================================================
# 1) ROLLAR VA RUXSATLAR
# ============================================================

class Role(str, enum.Enum):
    """Tizim rollari (qiymatlar DB'da shu ko'rinishda saqlanadi)."""

    OWNER = "owner"
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MODERATOR = "moderator"
    FINANCE = "finance"
    USER = "user"

    def __str__(self) -> str:  # pragma: no cover - ko'rsatish uchun qulaylik
        return self.value


#: Ruxsat nomlari (bir joyda — handler va testlar shu konstantalarni ishlatadi).
PERM_MANAGE_PAYMENTS = "manage_payments"
PERM_MANAGE_PROMOS = "manage_promos"
PERM_MANAGE_USERS = "manage_users"
PERM_SYSTEM_SETTINGS = "system_settings"

ALL_PERMISSIONS = (
    PERM_MANAGE_PAYMENTS,
    PERM_MANAGE_PROMOS,
    PERM_MANAGE_USERS,
    PERM_SYSTEM_SETTINGS,
)

#: Rol → ruxsatlar to'plami (topshiriqda berilgan matritsa).
ROLE_PERMISSIONS = {
    Role.OWNER: frozenset(ALL_PERMISSIONS),
    Role.SUPER_ADMIN: frozenset({
        PERM_MANAGE_PAYMENTS, PERM_MANAGE_PROMOS, PERM_MANAGE_USERS,
    }),
    Role.ADMIN: frozenset({PERM_MANAGE_PROMOS, PERM_MANAGE_USERS}),
    Role.MODERATOR: frozenset({PERM_MANAGE_USERS}),
    Role.FINANCE: frozenset({PERM_MANAGE_PAYMENTS}),
    Role.USER: frozenset(),
}

#: Rol darajalari (yuqori raqam — yuqori daraja). ``ADMIN`` va ``FINANCE``
#: ixtisoslashgan rollar bo'lgani uchun taqqoslashda ``role_covers()``
#: (ruxsatlar to'plami) ishlatiladi; bu jadval esa ko'rsatish/tartiblash uchun.
ROLE_LEVELS = {
    Role.OWNER: 50,
    Role.SUPER_ADMIN: 40,
    Role.ADMIN: 30,
    Role.MODERATOR: 20,
    Role.FINANCE: 10,
    Role.USER: 0,
}

#: "admin" hisoblanadigan (noadmin bo'lmagan) rollar.
ADMIN_ROLES = (
    Role.OWNER, Role.SUPER_ADMIN, Role.ADMIN, Role.MODERATOR, Role.FINANCE,
)

_ROLE_BY_VALUE = {role.value: role for role in Role}
#: Eski nomlar/aliaslar (masalan, "superadmin", "mod", "finans").
_ROLE_ALIASES = {
    "superadmin": Role.SUPER_ADMIN,
    "super-admin": Role.SUPER_ADMIN,
    "super_admin": Role.SUPER_ADMIN,
    "admin": Role.ADMIN,
    "moderator": Role.MODERATOR,
    "mod": Role.MODERATOR,
    "finance": Role.FINANCE,
    "finans": Role.FINANCE,
    "user": Role.USER,
    "foydalanuvchi": Role.USER,
    "owner": Role.OWNER,
}


def parse_role(value) -> "Role | None":
    """Qiymatni ``Role`` ga o'giradi (noto'g'ri qiymatda ``None``)."""
    if isinstance(value, Role):
        return value
    if value is None:
        return None
    text = str(value).strip().lower().replace(" ", "_")
    if not text:
        return None
    if text in _ROLE_BY_VALUE:
        return _ROLE_BY_VALUE[text]
    return _ROLE_ALIASES.get(text)


def permissions_for(role) -> frozenset:
    """Rol uchun ruxsatlar to'plami (noto'g'ri rol → bo'sh to'plam)."""
    parsed = parse_role(role)
    return ROLE_PERMISSIONS.get(parsed, frozenset())


def role_covers(role, required) -> bool:
    """``role`` talab qilingan roldan "kuchli yoki teng"mi?

    Taqqoslash RUXSATLAR TO'PLAMI bo'yicha: foydalanuvchi roli talab qilingan
    rolning barcha ruxsatlarini qamrab olsa — ``True``. Shu sababli
    ``SUPER_ADMIN`` ``require_role(ADMIN)`` dan o'tadi, ``FINANCE`` esa
    o'tmaydi (unda promo boshqaruvi yo'q).
    """
    current = parse_role(role)
    target = parse_role(required)
    if target is None or current is None:
        return False
    if current is target:
        return True
    required_perms = ROLE_PERMISSIONS.get(target, frozenset())
    if not required_perms:
        return True  # Role.USER — hamma hech bo'lmasa foydalanuvchi
    return required_perms.issubset(ROLE_PERMISSIONS.get(current, frozenset()))


# ============================================================
# 2) LEGACY (ADMIN_IDS) → ROL
# ============================================================

def legacy_role(user_id) -> "Role | None":
    """Eski ``ADMIN_ID`` / ``ADMIN_IDS`` asosida rolni aniqlaydi (DB'siz).

    * ``ADMIN_ID`` — ``OWNER`` (botning asosiy egasi);
    * ``ADMIN_IDS`` dagi qolgan raqamlar — ``SUPER_ADMIN``;
    * boshqa foydalanuvchilar — ``None``.
    """
    uid = _as_int(user_id)
    if uid is None:
        return None
    try:
        if ADMIN_ID and uid == int(ADMIN_ID):
            return Role.OWNER
    except (TypeError, ValueError):  # pragma: no cover - config himoyasi
        pass
    if uid in ADMIN_IDS_SET:
        return Role.SUPER_ADMIN
    return None


def is_legacy_admin(user_id) -> bool:
    """Foydalanuvchi eski ADMIN_ID/ADMIN_IDS ro'yxatidami?"""
    return legacy_role(user_id) is not None


def resolve_role(user_id, stored_role=None) -> Role:
    """Legacy rol + DB'dagi rolni birlashtiradi (hech qachon pasaytirmaydi)."""
    base = legacy_role(user_id)
    stored = parse_role(stored_role)
    if base is None:
        return stored if stored is not None else Role.USER
    if stored is None or stored is Role.USER:
        return base
    stored_level = ROLE_LEVELS.get(stored, 0)
    base_level = ROLE_LEVELS.get(base, 0)
    return stored if stored_level > base_level else base


# ============================================================
# 3) KESH (har bir tekshiruvda DB'ga bormaslik uchun)
# ============================================================

_MISS = object()
_ROLE_CACHE: dict = {}
_ROLE_CACHE_LOCK = threading.Lock()


def _cache_ttl() -> float:
    try:
        return max(0.0, float(os.getenv("RBAC_CACHE_TTL", "60") or 60))
    except ValueError:  # pragma: no cover - env himoyasi
        return 60.0


def _db_timeout() -> float:
    try:
        return max(0.1, float(os.getenv("RBAC_DB_TIMEOUT", "2") or 2))
    except ValueError:  # pragma: no cover - env himoyasi
        return 2.0


# RBAC tekshiruvi handler ichida (event loop'da) chaqiriladi, shuning uchun
# DB o'qish alohida thread'da va CHEKLANGAN kutish bilan bajariladi: sekin yoki
# osilib qolgan baza botning boshqa update'larini to'sib qo'ymaydi.
_DB_EXECUTOR = None
_DB_EXECUTOR_LOCK = threading.Lock()


def _read_stored_role(user_id):
    """DB'dan rolni o'qish (xato/timeout bo'lsa ``None``)."""
    global _DB_EXECUTOR
    try:
        with _DB_EXECUTOR_LOCK:
            if _DB_EXECUTOR is None:
                from concurrent.futures import ThreadPoolExecutor
                _DB_EXECUTOR = ThreadPoolExecutor(
                    max_workers=2, thread_name_prefix="rbac-role",
                )
        future = _DB_EXECUTOR.submit(db.get_admin_role, user_id)
        return future.result(timeout=_db_timeout())
    except Exception as e:
        logger.debug("RBAC rol o'qishda xato/timeout (user=%s): %s", user_id, e)
        return None


def _cache_get(user_id):
    with _ROLE_CACHE_LOCK:
        item = _ROLE_CACHE.get(user_id)
    if not item:
        return _MISS
    expires_at, value = item
    if expires_at < time.monotonic():
        with _ROLE_CACHE_LOCK:
            _ROLE_CACHE.pop(user_id, None)
        return _MISS
    return value


def _cache_set(user_id, value):
    ttl = _cache_ttl()
    if ttl <= 0:
        return
    with _ROLE_CACHE_LOCK:
        if len(_ROLE_CACHE) > 2048:  # xotira o'sishini cheklash
            _ROLE_CACHE.clear()
        _ROLE_CACHE[user_id] = (time.monotonic() + ttl, value)


def invalidate_role_cache(user_id=None) -> None:
    """Rol keshini tozalaydi (``user_id`` berilsa — faqat shu foydalanuvchi)."""
    with _ROLE_CACHE_LOCK:
        if user_id is None:
            _ROLE_CACHE.clear()
        else:
            uid = _as_int(user_id)
            _ROLE_CACHE.pop(uid, None)


# ============================================================
# 4) ROLNI ANIQLASH
# ============================================================

def _as_int(value):
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def get_role(user_id, use_cache: bool = True) -> Role:
    """Foydalanuvchi rolini qaytaradi (DB xatosida xavfsiz fallback).

    Tekshirish tartibi:

    1. ``ADMIN_ID`` → darhol ``OWNER`` (eng tez yo'l, DB'siz);
    2. kesh (``RBAC_CACHE_TTL`` soniya);
    3. DB: ``admin_roles`` jadvali → ``users.role`` ustuni;
    4. legacy ``ADMIN_IDS`` → ``SUPER_ADMIN``;
    5. aks holda ``Role.USER``.
    """
    uid = _as_int(user_id)
    if uid is None or uid <= 0:
        return Role.USER

    # 1) Asosiy admin — DB'ga umuman murojaat qilmaymiz.
    try:
        if ADMIN_ID and uid == int(ADMIN_ID):
            return Role.OWNER
    except (TypeError, ValueError):  # pragma: no cover
        pass

    stored = _MISS
    if use_cache:
        stored = _cache_get(uid)
    if stored is _MISS:
        stored = _read_stored_role(uid)  # hech qachon istisno ko'tarmaydi
        if use_cache:
            _cache_set(uid, stored)
    return resolve_role(uid, stored)


def has_permission(user_id, permission) -> bool:
    """Foydalanuvchida ruxsat bormi?"""
    perm = str(permission or "").strip()
    if not perm:
        return False
    return perm in ROLE_PERMISSIONS.get(get_role(user_id), frozenset())


def has_role(user_id, role, strict: bool = False) -> bool:
    """Foydalanuvchi roli talab qilinganga mos keladimi?

    ``strict=True`` — faqat aynan shu rol (masalan, faqat ``OWNER``).
    """
    target = parse_role(role)
    if target is None:
        return False
    current = get_role(user_id)
    if strict:
        return current is target
    return role_covers(current, target)


def is_admin(user_id) -> bool:
    """Foydalanuvchi har qanday admin rolida (yoki legacy admin)mi?"""
    return get_role(user_id) in ADMIN_ROLES


def required_permissions(role) -> tuple:
    """Rol uchun ruxsatlar ro'yxati (ko'rsatish/log uchun)."""
    return tuple(sorted(permissions_for(role)))


# ============================================================
# 5) ROLLARNI BOSHQARISH (DB)
# ============================================================

def set_role(user_id, role, granted_by=None, enforce: bool = False,
             metadata=None) -> bool:
    """Foydalanuvchiga rol beradi (yoki ``user`` berilsa — olib tashlaydi).

    Args:
        user_id: rol beriladigan foydalanuvchi.
        role: ``Role`` yoki matn (``"admin"``, ``"finance"``, ...).
        granted_by: amalni bajargan admin ID (audit uchun).
        enforce: ``True`` bo'lsa, ``granted_by`` da ``system_settings``
            ruxsati bo'lishi shart (aks holda ``False``).
        metadata: audit yozuviga qo'shiladigan qo'shimcha ma'lumot (JSONB).

    Returns:
        bool: DB yozuvi muvaffaqiyatli bo'ldi.
    """
    uid = _as_int(user_id)
    target = parse_role(role)
    if uid is None or target is None:
        return False
    actor = _as_int(granted_by)

    if enforce:
        if actor is None or not has_permission(actor, PERM_SYSTEM_SETTINGS):
            logger.warning("set_role rad etildi: actor=%s ruxsati yo'q", actor)
            return False

    if target is Role.USER:
        return remove_role(uid, granted_by=actor, enforce=enforce, metadata=metadata)

    old_role = db.get_admin_role(uid)
    ok = db.set_admin_role(uid, target.value, granted_by=actor)
    if not ok:
        return False

    invalidate_role_cache(uid)

    # Audit — yozuv muvaffaqiyatli bo'lgach (o'z tranzaksiyasida).
    try:
        from services.audit_service import AuditService, ACTION_SET_ROLE
        AuditService.log_action(
            actor if actor is not None else uid,
            ACTION_SET_ROLE,
            target_type="admin_role",
            target_id=uid,
            old_value={"role": old_role},
            new_value={"role": target.value},
            ip_or_metadata=metadata,
        )
    except Exception as e:  # audit hech qachon rol berishni buzmaydi
        logger.warning("Rol auditi yozilmadi (user=%s): %s", uid, e)
    return True


def remove_role(user_id, granted_by=None, enforce: bool = False,
                metadata=None) -> bool:
    """Foydalanuvchidan rolni olib tashlaydi (``Role.USER`` holatiga qaytaradi)."""
    uid = _as_int(user_id)
    if uid is None:
        return False
    actor = _as_int(granted_by)
    if enforce:
        if actor is None or not has_permission(actor, PERM_SYSTEM_SETTINGS):
            logger.warning("remove_role rad etildi: actor=%s ruxsati yo'q", actor)
            return False

    old_role = db.get_admin_role(uid)
    ok = db.delete_admin_role(uid)
    if not ok:
        return False
    invalidate_role_cache(uid)
    try:
        from services.audit_service import AuditService, ACTION_REMOVE_ROLE
        AuditService.log_action(
            actor if actor is not None else uid,
            ACTION_REMOVE_ROLE,
            target_type="admin_role",
            target_id=uid,
            old_value={"role": old_role},
            new_value={"role": Role.USER.value},
            ip_or_metadata=metadata,
        )
    except Exception as e:
        logger.warning("Rol o'chirish auditi yozilmadi (user=%s): %s", uid, e)
    return True


def list_admins(limit: int = 100) -> list:
    """DB'dagi qo'shimcha rollar ro'yxati (legacy adminlar bundan mustasno)."""
    return db.list_admin_roles(limit=limit)


# ============================================================
# 6) DEKORATORLAR
# ============================================================

DEFAULT_DENIED_MESSAGE = "❌ Sizda bu amal uchun ruxsat yo'q."


class PermissionDenied(Exception):
    """Ruxsat bo'lmaganda ko'tariladigan istisno (``raise_error=True`` uchun)."""

    def __init__(self, user_id=None, permission=None, role=None):
        self.user_id = user_id
        self.permission = permission
        self.role = role
        detail = permission if permission is not None else role
        super().__init__(f"Ruxsat yo'q: user={user_id} talab={detail}")


def _extract_user_id(update):
    """Update (yoki Message/CallbackQuery) ichidan foydalanuvchi ID'sini oladi."""
    if update is None:
        return None
    user = getattr(update, "effective_user", None)
    if user is None:
        user = getattr(getattr(update, "callback_query", None), "from_user", None)
    if user is None:
        user = getattr(getattr(update, "message", None), "from_user", None)
    return _as_int(getattr(user, "id", None))


async def _send_denied(update, message: str) -> None:
    """Rad javobini foydalanuvchiga yetkazadi (xato bo'lsa jim o'tadi)."""
    try:
        query = getattr(update, "callback_query", None)
        if query is not None:
            try:
                await query.answer(message, show_alert=True)
            except TypeError:  # eski mock'lar kwargs'ni qabul qilmasligi mumkin
                await query.answer(message)
            return
        msg = getattr(update, "message", None) or getattr(update, "effective_message", None)
        if msg is not None:
            await msg.reply_text(message)
    except Exception as e:  # pragma: no cover - tarmoq/mock holatlari
        logger.debug("Rad javobini yuborib bo'lmadi: %s", e)


def _guard(checker, *, message: str, raise_error: bool, tag, value):
    """Umumiy dekorator qobig'i (``require_permission``/``require_role`` uchun)."""

    def decorator(func):
        is_coro = inspect.iscoroutinefunction(func)

        async def _call(update, context=None, *args, **kwargs):
            user_id = _extract_user_id(update)
            if user_id is not None and checker(user_id):
                if is_coro:
                    return await func(update, context, *args, **kwargs)
                return func(update, context, *args, **kwargs)
            logger.warning(
                "RBAC: %s rad etildi (user=%s, %s=%s)",
                getattr(func, "__name__", "handler"), user_id, tag, value,
            )
            await _send_denied(update, message)
            if raise_error:
                raise PermissionDenied(
                    user_id=user_id,
                    permission=value if tag == "permission" else None,
                    role=value if tag == "role" else None,
                )
            return None

        @functools.wraps(func)
        async def wrapper(update, context=None, *args, **kwargs):
            return await _call(update, context, *args, **kwargs)

        setattr(wrapper, f"__rbac_{tag}__", value)
        wrapper.__rbac_original__ = func
        wrapper.__wrapped__ = func
        return wrapper

    return decorator


def require_permission(permission, *, message: str = DEFAULT_DENIED_MESSAGE,
                       raise_error: bool = False):
    """Dekorator: handler faqat shu ruxsatga ega foydalanuvchiga ishlaydi.

    Foydalanish::

        @require_permission(PERM_MANAGE_PAYMENTS)
        async def approve(update, context): ...

    Ruxsat bo'lmasa: callback'ga ``answer(..., show_alert=True)`` yoki
    xabarga rad javobi yuboriladi va handler **chaqirilmaydi**.
    """
    return _guard(
        lambda uid: has_permission(uid, permission),
        message=message, raise_error=raise_error,
        tag="permission", value=permission,
    )


def require_role(role, *, strict: bool = False,
                 message: str = DEFAULT_DENIED_MESSAGE, raise_error: bool = False):
    """Dekorator: handler faqat shu rol (yoki undan kuchli rol) uchun ishlaydi.

    Foydalanish::

        @require_role(Role.OWNER, strict=True)   # faqat egasi
        async def system_settings(update, context): ...

    ``strict=False`` (default) — ruxsatlar to'plami bo'yicha "kuchli yoki teng"
    (masalan ``SUPER_ADMIN`` ``require_role(Role.ADMIN)`` dan o'tadi).
    """
    return _guard(
        lambda uid: has_role(uid, role, strict=strict),
        message=message, raise_error=raise_error,
        tag="role", value=parse_role(role) or role,
    )


#: Qulaylik: eski nom (ba'zi loyihalarda shu ko'rinishda ishlatiladi).
permission_required = require_permission
role_required = require_role
