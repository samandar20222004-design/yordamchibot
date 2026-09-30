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

PHASE 3 — resurs-ASOSIDAGI RBAC (markazlashuv) va IDOR himoyasi
---------------------------------------------------------------
1-7 bo'limlar (yuqorida) — BOT darajasidagi (global) rollar va admin
ruxsatlari.  Ular **o'zgarmaydi**.

8-bo'lim (fayl oxirida) — RESURS darajasidagi yagona ruxsat nuqtasi::

    from services import rbac_service

    allowed = await rbac_service.can(
        user_id=query.from_user.id,      # FAQAT server-side ID
        resource_type="channel",         # channel | post | member | system
        resource_id=channel_id,          # callback payload'dan olingan ID
        action="publish",                # create/edit/approve/schedule/...
    )
    if not allowed:
        ...  # Permission Denied — so'rov YOPIQ rad etiladi

Resurs rollari: ``owner``, ``editor``, ``scheduler``, ``analyst``
(kanal bo'yicha a'zolik; ``channel_members`` jadvali + kanal egasi).
Har bir rol uchun aniq ruxsat matritsasi — ``RESOURCE_ROLE_PERMISSIONS``.

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

import asyncio
import collections
import dataclasses
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

#: PHASE 3 — resurs (kanal) rollari kesh: ``(user_id, channel_id) → role``.
#: Faqat MUSBAT natijalar keshlanadi (rad etish har doim qayta tekshiriladi).
_RESOURCE_CACHE: dict = {}


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


#: 🧹 FAZA 26 — dekorator ``message`` maydoni uchun i18n belgisi:
#: ``"adm:<kalit>"`` shaklidagi xabarlar yuborishdan OLDIN foydalanuvchi
#: (admin) tilidagi matnga aylantiriladi (``translations.admin_panel.admin_t``).
I18N_MESSAGE_PREFIX = "adm:"


def _resolve_denied_message(message, user_id=None) -> str:
    """``adm:<kalit>`` belgisini admin tilidagi matnga aylantiradi (fail-soft).

    Oddiy satrlar o'zgarmaydi (orqaga moslik). Til aniqlanmasa — ``uz``.
    """
    if not isinstance(message, str) or not message.startswith(I18N_MESSAGE_PREFIX):
        return message if isinstance(message, str) else str(message or "")
    try:
        from translations import admin_t
        from locales.translations import normalize_lang

        lang = "uz"
        if user_id:
            try:
                import database as _db
                lang = normalize_lang(_db.get_user_language(user_id))
            except Exception:  # pragma: no cover — DB/cache xatosi ham o'lmaydi
                lang = "uz"
        return admin_t(message[len(I18N_MESSAGE_PREFIX):], lang)
    except Exception:  # pragma: no cover — i18n ham yiqilsa marker qaytadi
        return message


async def _send_denied(update, message: str) -> None:
    """Rad javobini foydalanuvchiga yetkazadi (xato bo'lsa jim o'tadi).

    🧹 FAZA 26: ``adm:<kalit>`` markerli xabarlar avval foydalanuvchi
    tilidagi matnga aylantiriladi (admin panel i18n pariteti).
    """
    message = _resolve_denied_message(message, _extract_user_id(update))
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


# ============================================================
# 7) ADMIN CALLBACK TAMPERING HIMOYASI (11-bosqich, P0)
# ============================================================
#
# Inline callback ``data`` foydalanuvchi tomonidan SOXTALASHTIRILISHI mumkin
# (Telegram mijozi emas, API orqali istalgan matn yuboriladi). Shuning uchun:
#   * kim bosgani FAQAT ``query.from_user.id`` (server-side) bo'yicha
#     aniqlanadi — payload ichidagi ID'larga ISHONILMAYDI;
#   * admin callback'lari uchun ``ADMIN_IDS_SET``/RBAC roli tekshiriladi;
#   * payload'dagi ID'lar qat'iy musbat butun son bo'lishi shart
#     (``-1``, ``1e3``, ``12;DROP``, bo'sh — hammasi rad).
#
#: Callback payload'idagi ID uchun ruxsat etilgan maksimal qiymat (Telegram
#: ID'lari va BIGSERIAL'lar shu chegaraga sig'adi).
CALLBACK_ID_MAX = 2 ** 62


class CallbackTampering(Exception):
    """Soxtalashtirilgan / ruxsatsiz admin callback aniqlandi."""

    def __init__(self, reason: str, user_id=None, data=None):
        self.reason = reason
        self.user_id = user_id
        self.data = data
        super().__init__(f"callback tampering: {reason} (user={user_id})")


def parse_callback_id(value, *, allow_zero: bool = False):
    """Payload bo'lagini QAT'IY ``int`` ID'ga aylantiradi; buzilgan bo'lsa ``None``.

    Faqat ``[0-9]+`` (ixtiyoriy oldingi ``-`` YO'Q) qabul qilinadi — manfiy,
    kasr, bo'sh, ``+``, bo'shliq, katta son — hammasi rad etiladi.
    """
    if value is None:
        return None
    text = str(value)
    # Bo'shliq/tab ham RAD — payload aynan raqamlardan iborat bo'lishi shart.
    if not text or not text.isdigit() or not text.isascii():
        return None
    try:
        number = int(text)
    except ValueError:
        return None
    if number > CALLBACK_ID_MAX:
        return None
    if number == 0 and not allow_zero:
        return None
    return number


def parse_callback_parts(data, prefix: str, expected: int = 1, sep: str = ":"):
    """``prefix`` bilan boshlanuvchi callback'dan ``expected`` ta ID'ni oladi.

    Qaytadi: ``list[int]`` yoki ``None`` (prefiks mos emas / soni noto'g'ri /
    biror bo'lak ID emas). Ortiqcha bo'laklar ham RAD etiladi — payload'ga
    qo'shimcha "argument" tiqishtirib bo'lmaydi.
    """
    if data is None or prefix is None:
        return None
    text = str(data)
    head = str(prefix)
    if not text.startswith(head):
        return None
    tail = text[len(head):]
    parts = tail.split(sep) if tail != "" else []
    if len(parts) != int(expected):
        return None
    ids = []
    for part in parts:
        number = parse_callback_id(part)
        if number is None:
            return None
        ids.append(number)
    return ids


def verify_admin_callback(update, permission=None, *, role=None, strict: bool = False) -> bool:
    """Callback'ni bosgan foydalanuvchi (server-side ``from_user.id``) admin
    va (berilsa) kerakli ruxsat/rolga egami?

    Payload ichidagi hech qanday ID'ga qaralmaydi. ``update`` — PTB
    ``Update`` yoki to'g'ridan-to'g'ri ``CallbackQuery``. Xato/DB uzilishida
    XAVFSIZ tomon — ``False`` (fail-closed).
    """
    try:
        query = getattr(update, "callback_query", None) or update
        user = getattr(query, "from_user", None)
        if user is None:
            user = getattr(update, "effective_user", None)
        user_id = _as_int(getattr(user, "id", None))
        if user_id is None or user_id <= 0:
            return False
        # Kim bosgani va xabar kimga tegishli ekani mos bo'lishi shart emas
        # (admin guruh chatidan bosishi mumkin), lekin ID ADMIN bo'lishi shart.
        if not (user_id in ADMIN_IDS_SET or is_admin(user_id)):
            return False
        if permission is not None and not has_permission(user_id, permission):
            return False
        if role is not None and not has_role(user_id, role, strict=strict):
            return False
        return True
    except Exception as e:  # pragma: no cover - DB/mock chekka holatlari
        logger.warning("verify_admin_callback xatosi (fail-closed): %s", e)
        return False


def admin_callback_guard(update, prefix: str, expected_ids: int = 1,
                         permission=None, *, role=None, strict: bool = False):
    """Admin inline callback uchun YAGONA tekshiruv nuqtasi.

    1) ``from_user.id`` server-side admin/RBAC tekshiruvi (payload'ga
       ishonilmaydi);
    2) payload ``prefix`` + aynan ``expected_ids`` ta qat'iy musbat ``int``.

    Muvaffaqiyatda ``list[int]`` (ID'lar) qaytadi, aks holda
    ``CallbackTampering`` ko'tariladi va urinish WARNING bilan loglanadi.
    """
    query = getattr(update, "callback_query", None) or update
    user = getattr(query, "from_user", None) or getattr(update, "effective_user", None)
    user_id = _as_int(getattr(user, "id", None))
    data = getattr(query, "data", None)
    if not verify_admin_callback(update, permission, role=role, strict=strict):
        logger.warning(
            "RBAC: admin callback rad etildi (user=%s, data=%r) — ruxsat yo'q",
            user_id, str(data)[:64] if data is not None else None,
        )
        raise CallbackTampering("not_admin", user_id, data)
    ids = parse_callback_parts(data, prefix, expected_ids)
    if ids is None:
        logger.warning(
            "RBAC: admin callback payload buzilgan/soxta (user=%s, data=%r)",
            user_id, str(data)[:64] if data is not None else None,
        )
        raise CallbackTampering("bad_payload", user_id, data)
    return ids


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


# ============================================================
# 8) RESURS-ASOSIDAGI RBAC — MARKAZIY RUXSAT NUQTASI (PHASE 3)
# ============================================================
#
# Muammo (Phase 3 topshirig'i)
# ----------------------------
# Bot darajasidagi rollar (1-7 bo'limlar) "kim admin?" savoliga javob beradi,
# lekin "kim AYNAN SHU kanal/post ustida amal bajarishi mumkin?" savoliga
# javob bermaydi.  Har bir handler o'zicha ``user_id`` yoki ``post_id`` ga
# tayanib qaror qabul qilsa — IDOR (Insecure Direct Object Reference) paydo
# bo'ladi: foydalanuvchi o'ziga tegishli BO'LMAGAN kanal/post ID'sini
# callback payload'iga qo'yib, boshqa birovning resursini boshqaradi.
#
# Yechim
# ------
# * Resurs rollari: ``OWNER | EDITOR | SCHEDULER | ANALYST`` (kanal bo'yicha);
# * yagona tekshiruv nuqtasi — :func:`can` (async) va uning batafsil
#   varianti :func:`check`;
# * **fail-closed**: resurs topilmasa, rol aniqlanmasa, DB xatosi bo'lsa yoki
#   amal noma'lum bo'lsa — RUXSAT BERILMAYDI;
# * qaror sababi (``reason``) va WARNING log har bir rad etishda yoziladi.

RESOURCE_TYPE_CHANNEL = "channel"
RESOURCE_TYPE_POST = "post"
RESOURCE_TYPE_MEMBER = "member"
RESOURCE_TYPE_QUEUE = "queue"
RESOURCE_TYPE_SYSTEM = "system"

#: Qo'llab-quvvatlanadigan resurs turlari.
RESOURCE_TYPES = (
    RESOURCE_TYPE_CHANNEL, RESOURCE_TYPE_POST, RESOURCE_TYPE_MEMBER,
    RESOURCE_TYPE_QUEUE, RESOURCE_TYPE_SYSTEM,
)

#: Kanal konteksti orqali tekshiriladigan resurs turlari.
CHANNEL_SCOPED_RESOURCE_TYPES = frozenset({
    RESOURCE_TYPE_CHANNEL, RESOURCE_TYPE_POST, RESOURCE_TYPE_MEMBER,
    RESOURCE_TYPE_QUEUE,
})

#: Amal nomlarining kanonik ko'rinishlari.
ACTION_VIEW = "view"
ACTION_VIEW_ANALYTICS = "view_analytics"
ACTION_CREATE = "create"
ACTION_EDIT = "edit"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_SCHEDULE = "schedule"
ACTION_PUBLISH = "publish"
ACTION_MANAGE_MEMBERS = "manage_members"
ACTION_MANAGE_CHANNEL = "manage_channel"
ACTION_DELETE_CHANNEL = "delete_channel"


class ResourceRole(str, enum.Enum):
    """Kanal (resurs) darajasidagi rollar — PHASE E ``channel_members`` bilan bir xil."""

    OWNER = "owner"
    EDITOR = "editor"
    SCHEDULER = "scheduler"
    ANALYST = "analyst"

    def __str__(self) -> str:  # pragma: no cover - ko'rsatish uchun qulaylik
        return self.value


#: Resurs rollari (matn ko'rinishida).
RESOURCE_ROLES = tuple(role.value for role in ResourceRole)

#: Rol → ruxsatlar to'plami (resurs darajasi).
#:
#: ``services/channels/team.py`` (Phase E) — ish oqimi o'tishlari uchun
#: HAQIQAT MANBASI: ``approve/reject/create/edit/schedule/manage_members``
#: ruxsatlari o'sha matritsadan AYNAN olingan.  Ushbu jadval faqat ikkita
#: qo'shimcha ruxsatni kiritadi:
#:
#: * ``view`` — har bir rol o'z kanal ekranini ocha olishi uchun minimal o'qish
#:   huquqi (aks holda ``scheduler`` navbatni ko'ra olmaydi);
#: * ``manage_channel`` / ``delete_channel`` — faqat ``owner`` uchun kanal
#:   darajasidagi xavfli amallar (o'chirish, sozlamalar).
RESOURCE_ROLE_PERMISSIONS = {
    ResourceRole.OWNER.value: frozenset({
        ACTION_VIEW, ACTION_VIEW_ANALYTICS, ACTION_CREATE, ACTION_EDIT,
        ACTION_APPROVE, ACTION_REJECT, ACTION_SCHEDULE, ACTION_PUBLISH,
        ACTION_MANAGE_MEMBERS, ACTION_MANAGE_CHANNEL, ACTION_DELETE_CHANNEL,
    }),
    ResourceRole.EDITOR.value: frozenset({
        ACTION_VIEW, ACTION_CREATE, ACTION_EDIT, ACTION_APPROVE, ACTION_REJECT,
    }),
    ResourceRole.SCHEDULER.value: frozenset({ACTION_VIEW, ACTION_SCHEDULE}),
    ResourceRole.ANALYST.value: frozenset({ACTION_VIEW, ACTION_VIEW_ANALYTICS}),
}

#: Amal nomi → talab qilinadigan ruxsat.  Aliaslar bir joyda yig'ilgan:
#: handler eski nom bilan chaqirsa ham, matritsa o'zgarmaydi.
RESOURCE_ACTION_PERMISSION = {
    ACTION_VIEW: ACTION_VIEW,
    "read": ACTION_VIEW,
    "open": ACTION_VIEW,
    "queue": ACTION_VIEW,
    "view_queue": ACTION_VIEW,
    ACTION_VIEW_ANALYTICS: ACTION_VIEW_ANALYTICS,
    "statistics": ACTION_VIEW_ANALYTICS,
    "stats": ACTION_VIEW_ANALYTICS,
    "analytics": ACTION_VIEW_ANALYTICS,
    ACTION_CREATE: ACTION_CREATE,
    "new_post": ACTION_CREATE,
    "autopilot": ACTION_CREATE,
    ACTION_EDIT: ACTION_EDIT,
    "edit_post": ACTION_EDIT,
    "update": ACTION_EDIT,
    ACTION_APPROVE: ACTION_APPROVE,
    "approve_post": ACTION_APPROVE,
    ACTION_REJECT: ACTION_REJECT,
    "reject_post": ACTION_REJECT,
    ACTION_SCHEDULE: ACTION_SCHEDULE,
    "schedule_post": ACTION_SCHEDULE,
    ACTION_PUBLISH: ACTION_PUBLISH,
    "publish_post": ACTION_PUBLISH,
    "send": ACTION_PUBLISH,
    ACTION_MANAGE_MEMBERS: ACTION_MANAGE_MEMBERS,
    "manage": ACTION_MANAGE_MEMBERS,
    "manage_roles": ACTION_MANAGE_MEMBERS,
    ACTION_MANAGE_CHANNEL: ACTION_MANAGE_CHANNEL,
    "settings": ACTION_MANAGE_CHANNEL,
    ACTION_DELETE_CHANNEL: ACTION_DELETE_CHANNEL,
    "delete": ACTION_DELETE_CHANNEL,
    "remove_channel": ACTION_DELETE_CHANNEL,
}

#: Rad etish sabablari (test/loglar shu konstantalarga tayanadi).
REASON_NOT_A_MEMBER = "not_a_channel_member"
REASON_INSUFFICIENT_ROLE = "insufficient_role"
REASON_RESOURCE_NOT_FOUND = "resource_not_found"
REASON_UNKNOWN_ACTION = "unknown_action"
REASON_INVALID_USER = "invalid_user"
REASON_UNKNOWN_RESOURCE = "unknown_resource_type"
REASON_MISSING_RESOURCE_ID = "missing_resource_id"
REASON_ADMIN_OVERRIDE = "admin_override"
REASON_OK = ""

#: Resurs tekshiruvi rad etilganda ko'rsatiladigan standart matn.
RESOURCE_DENIED_MESSAGE = "⛔ Ruxsat yo'q (Permission Denied)."

_RESOURCE_ROLE_BY_VALUE = {role.value: role.value for role in ResourceRole}
_RESOURCE_ROLE_ALIASES = {
    "owner": ResourceRole.OWNER.value,
    "ega": ResourceRole.OWNER.value,
    "editor": ResourceRole.EDITOR.value,
    "muharrir": ResourceRole.EDITOR.value,
    "scheduler": ResourceRole.SCHEDULER.value,
    "rejalashtiruvchi": ResourceRole.SCHEDULER.value,
    "analyst": ResourceRole.ANALYST.value,
    "analitik": ResourceRole.ANALYST.value,
}


def parse_resource_role(value) -> "str | None":
    """Qiymatni resurs roliga aylantiradi (noma'lum qiymatda ``None``)."""
    if isinstance(value, ResourceRole):
        return value.value
    if value is None:
        return None
    text = str(value).strip().lower().replace(" ", "_")
    if text in _RESOURCE_ROLE_BY_VALUE:
        return text
    return _RESOURCE_ROLE_ALIASES.get(text)


def normalize_resource_type(resource_type) -> "str | None":
    """Resurs turini normallashtiradi (noma'lum turda ``None``)."""
    if resource_type is None:
        return None
    text = str(resource_type).strip().lower()
    return text if text in RESOURCE_TYPES else None


def _action_text(action) -> str:
    """Amal nomini matnga aylantiradi (bo'shliqlar ``_`` ga)."""
    if action is None:
        return ""
    return str(action).strip().lower().replace(" ", "_")


def normalize_resource_action(action) -> "str | None":
    """Amalni kanonik nomga keltiradi (noma'lum amalda ``None``)."""
    text = _action_text(action)
    return text if text in RESOURCE_ACTION_PERMISSION else None


def permission_for_action(action) -> "str | None":
    """Amal uchun talab qilinadigan ruxsat nomi."""
    normalized = normalize_resource_action(action)
    return RESOURCE_ACTION_PERMISSION.get(normalized) if normalized else None


def resource_role_permissions(role) -> frozenset:
    """Resurs roli uchun ruxsatlar to'plami (noma'lum rol → bo'sh to'plam)."""
    parsed = parse_resource_role(role)
    return RESOURCE_ROLE_PERMISSIONS.get(parsed, frozenset())


def resource_role_covers(role, required_role) -> bool:
    """``role`` talab qilingan resurs rolini qamrab oladimi (ruxsatlar bo'yicha)?"""
    target = parse_resource_role(required_role)
    if target is None:
        return False
    required_perms = RESOURCE_ROLE_PERMISSIONS.get(target, frozenset())
    if not required_perms:
        return False
    return required_perms.issubset(resource_role_permissions(role))


@dataclasses.dataclass(frozen=True)
class AccessDecision:
    """Resurs tekshiruvi natijasi (``bool`` sifatida ham ishlaydi)."""

    allowed: bool
    user_id: "int | None" = None
    resource_type: "str | None" = None
    resource_id: "str | None" = None
    action: "str | None" = None
    permission: "str | None" = None
    role: "str | None" = None
    channel_id: "str | None" = None
    reason: str = REASON_OK

    def __bool__(self) -> bool:  # pragma: no cover - qulaylik
        return bool(self.allowed)

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed, "user_id": self.user_id,
            "resource_type": self.resource_type, "resource_id": self.resource_id,
            "action": self.action, "permission": self.permission,
            "role": self.role, "channel_id": self.channel_id,
            "reason": self.reason,
        }


def _deny(**kwargs) -> AccessDecision:
    kwargs.setdefault("allowed", False)
    kwargs["allowed"] = False
    decision = AccessDecision(**kwargs)
    _remember_denial(decision)
    return decision


class ResourcePermissionDenied(PermissionDenied):
    """Resurs (kanal/post) bo'yicha ruxsat rad etildi."""

    def __init__(self, decision: AccessDecision):
        self.decision = decision
        super().__init__(
            user_id=decision.user_id,
            permission=decision.permission,
            role=decision.role,
        )


# --- Rad etishlar audit izi (xotira, cheklangan) ---------------------------
_DENIAL_LOG: "collections.deque" = collections.deque(maxlen=200)
_DENIAL_LOCK = threading.Lock()


def _remember_denial(decision: AccessDecision) -> None:
    with _DENIAL_LOCK:
        _DENIAL_LOG.append((time.time(), decision))


def recent_denials(limit: int = 20) -> list:
    """Oxirgi rad etilgan resurs so'rovlari (diagnostika/test uchun)."""
    with _DENIAL_LOCK:
        items = list(_DENIAL_LOG)[-max(1, int(limit)):]
    return [d.as_dict() for _ts, d in items]


def clear_denial_log() -> None:
    """Rad etishlar jurnalini tozalaydi (testlar uchun)."""
    with _DENIAL_LOCK:
        _DENIAL_LOG.clear()


# --- Resurs rolini aniqlash ------------------------------------------------

async def _maybe_await(value):
    """Qiymat awaitable bo'lsa — await qiladi, aks holda o'zini qaytaradi."""
    if inspect.isawaitable(value):
        return await value
    return value


async def _db_call(db_module, name: str, *args):
    """``database`` funksiyasini XAVFSIZ chaqiradi (xatoda ``None``).

    MUHIM: chaqiruv har doim ``db.run_db`` orqali ketadi — handlerlar
    ishlatadigan AYNAN shu yo'l (shu sababli testlardagi ``run_db``
    mock'lari ham qamrab olinadi) va event loop bloklanmaydi.
    """
    fn = getattr(db_module, name, None) if db_module is not None else None
    if not callable(fn):
        # Ba'zi (test) adapterlari faqat ``run_db`` ni almashtiradi — funksiya
        # obyekti esa haqiqiy ``database`` modulidan olinadi (nom bo'yicha
        # dispatch qilinadi).  Shu sababli atribut topilmasa — zaxira manba.
        fn = getattr(db, name, None)
    if not callable(fn):
        return None
    runner = getattr(db_module, "run_db", None) if db_module is not None else None
    try:
        if callable(runner):
            return await _maybe_await(runner(fn, *args))
        import asyncio as _asyncio
        return await _asyncio.to_thread(fn, *args)
    except Exception as e:  # fail-closed: xato — "ma'lumot yo'q" degani
        logger.debug("RBAC: %s chaqiruvida xato (fail-closed): %s", name, e)
        return None


def _member_row_role(row) -> "str | None":
    """``channel_members`` qatoridan rolni ajratib oladi (tuple/dict)."""
    if not row:
        return None
    try:
        if isinstance(row, dict):
            value = row.get("role")
        elif len(row) >= 4:
            value = row[3]
        else:
            value = None
    except (TypeError, IndexError):
        return None
    return parse_resource_role(value)


def _post_channel_id(post) -> "str | None":
    """Post yozuvidan ``channel_id`` ni ajratib oladi (dict yoki tuple)."""
    if not post:
        return None
    value = None
    try:
        if isinstance(post, dict):
            value = post.get("channel_id")
        elif len(post) >= 3:
            value = post[2]
        else:
            value = getattr(post, "channel_id", None)
    except (TypeError, IndexError):
        value = getattr(post, "channel_id", None)
    text = str(value).strip() if value not in (None, "") else ""
    return text or None


async def _is_channel_owner(db_module, user_id: int, channel_id: str) -> bool:
    """Kanal foydalanuvchining O'Z kanallari ro'yxatidami? (user-scoped so'rov)."""
    for fn_name in ("get_user_channels_with_tone", "get_user_channels"):
        rows = await _db_call(db_module, fn_name, user_id)
        if not rows:
            # None yoki bo'sh — keyingi manba (ikkalasi ham ``user_id`` ga
            # bog'langan so'rov, shu sababli bu faqat moslik uchun fallback).
            continue
        try:
            for row in rows:
                if str(row[0]) == channel_id:
                    return True
        except (TypeError, IndexError):
            continue
    return False


async def resolve_resource_role(user_id, channel_id, *, db_module=None,
                                use_cache: bool = True) -> "str | None":
    """Foydalanuvchining kanal bo'yicha resurs rolini qaytaradi (yoki ``None``).

    Tekshirish tartibi (hammasi fail-closed):

    1. kesh (faqat musbat natijalar, ``RBAC_RESOURCE_CACHE_TTL``);
    2. kanal foydalanuvchining o'z kanallari ro'yxatida → ``owner``;
    3. ``channel_members`` qatori → ``editor | scheduler | analyst``;
    4. ``channels.user_id == user_id`` → ``owner`` (birlamchi manbaning
       zaxira tekshiruvi);
    5. aks holda ``None``.
    """
    uid = _as_int(user_id)
    ch = str(channel_id or "").strip()
    if uid is None or uid <= 0 or not ch:
        return None
    dbm = db_module if db_module is not None else db

    if use_cache:
        cached = _resource_cache_get(uid, ch)
        if cached is not _MISS:
            return cached

    role = None
    if await _is_channel_owner(dbm, uid, ch):
        role = ResourceRole.OWNER.value
    if role is None:
        role = _member_row_role(
            await _db_call(dbm, "get_channel_member", ch, uid))
        if role == ResourceRole.OWNER.value:
            # ``channel_members`` da owner qatori bo'lmasligi kerak, lekin
            # bo'lsa ham ishonchsiz deb hisoblaymiz — egalik 2/4-qadamda.
            role = None
    if role is None:
        owner = await _db_call(dbm, "get_channel_owner_id", ch)
        if owner is not None and _as_int(owner) == uid:
            role = ResourceRole.OWNER.value

    if use_cache and role is not None:
        _resource_cache_set(uid, ch, role)
    return role


# --- Resurs kesh (faqat musbat natijalar) ----------------------------------

def _resource_cache_ttl() -> float:
    try:
        return max(0.0, float(os.getenv("RBAC_RESOURCE_CACHE_TTL", "15") or 15))
    except ValueError:  # pragma: no cover - env himoyasi
        return 15.0


def _resource_cache_get(user_id: int, channel_id: str):
    ttl = _resource_cache_ttl()
    if ttl <= 0:
        return _MISS
    key = (int(user_id), str(channel_id))
    with _ROLE_CACHE_LOCK:
        item = _RESOURCE_CACHE.get(key)
    if not item:
        return _MISS
    expires_at, value = item
    if expires_at < time.monotonic():
        with _ROLE_CACHE_LOCK:
            _RESOURCE_CACHE.pop(key, None)
        return _MISS
    return value


def _resource_cache_set(user_id: int, channel_id: str, role: str) -> None:
    if _resource_cache_ttl() <= 0:
        return
    key = (int(user_id), str(channel_id))
    with _ROLE_CACHE_LOCK:
        if len(_RESOURCE_CACHE) > 4096:  # xotira o'sishini cheklash
            _RESOURCE_CACHE.clear()
        _RESOURCE_CACHE[key] = (time.monotonic() + _resource_cache_ttl(), role)


def invalidate_resource_cache(user_id=None, channel_id=None) -> None:
    """Resurs-rollar keshini tozalaydi (user/channel bo'yicha filtr bilan)."""
    uid = _as_int(user_id) if user_id is not None else None
    ch = str(channel_id).strip() if channel_id not in (None, "") else None
    with _ROLE_CACHE_LOCK:
        if uid is None and ch is None:
            _RESOURCE_CACHE.clear()
            return
        for key in [k for k in _RESOURCE_CACHE
                    if (uid is None or k[0] == uid) and (ch is None or k[1] == ch)]:
            _RESOURCE_CACHE.pop(key, None)


# --- MARKAZIY TEKSHIRUV NUQTASI --------------------------------------------

async def check(user_id, resource_type=RESOURCE_TYPE_CHANNEL, resource_id=None,
                action=ACTION_VIEW, *, db_module=None, use_cache: bool = True,
                allow_admin: bool = False) -> AccessDecision:
    """Resurs bo'yicha batafsil ruxsat qarori (sabab bilan).

    ``can()`` shu funksiyaning ``bool`` qobig'i; handlerlarga "nega rad
    etildi?" kerak bo'lsa — shu ishlatiladi.

    Fail-closed: noma'lum resurs/amal, topilmagan post, aniqlanmagan rol,
    DB uzilishi — barchasi ``allowed=False``.
    """
    uid = _as_int(user_id)
    rtype = normalize_resource_type(resource_type)
    raw_act = _action_text(action)
    base = dict(user_id=uid, resource_type=str(resource_type)[:32] if resource_type else None,
                resource_id=str(resource_id)[:64] if resource_id not in (None, "") else None,
                action=raw_act[:32] or None)

    if uid is None or uid <= 0:
        return _deny(**base, reason=REASON_INVALID_USER)
    if rtype is None:
        return _deny(**base, reason=REASON_UNKNOWN_RESOURCE)
    permission = RESOURCE_ACTION_PERMISSION.get(raw_act)
    if permission is None:
        # ``system`` resursi uchun global ruxsat nomlari ham qabul qilinadi
        # (masalan ``manage_payments``/``system_settings``).
        if rtype == RESOURCE_TYPE_SYSTEM and raw_act in ALL_PERMISSIONS:
            permission = raw_act
        else:
            return _deny(**base, reason=REASON_UNKNOWN_ACTION)
    base["resource_type"] = rtype
    base["permission"] = permission

    dbm = db_module if db_module is not None else db

    # 1) TIZIM resursi — bot darajasidagi (global) ruxsat matritsasi.
    if rtype == RESOURCE_TYPE_SYSTEM:
        if has_permission(uid, permission):
            return AccessDecision(True, **base, reason=REASON_OK)
        return _deny(**base, reason=REASON_INSUFFICIENT_ROLE)

    # 2) Ixtiyoriy admin override (faqat eski xulq-atvorni SAQLASH uchun
    #    aniq so'ralganda; yangi handlerlar buni ishlatmaydi).
    if allow_admin and await _maybe_await(asyncio.to_thread(is_admin, uid)):
        return AccessDecision(True, **base, role="admin",
                              reason=REASON_ADMIN_OVERRIDE)

    # 3) Kanal kontekstini aniqlash (post bo'lsa — post orqali).
    if rtype == RESOURCE_TYPE_POST:
        if resource_id in (None, ""):
            return _deny(**base, reason=REASON_MISSING_RESOURCE_ID)
        post = await _db_call(dbm, "get_workflow_post", _as_int(resource_id))
        channel_id = _post_channel_id(post)
        if not channel_id:
            return _deny(**base, reason=REASON_RESOURCE_NOT_FOUND)
    else:
        channel_id = str(resource_id or "").strip()
        if not channel_id:
            return _deny(**base, reason=REASON_MISSING_RESOURCE_ID)

    base["channel_id"] = channel_id

    # 4) Rolni aniqlash va ruxsatni tekshirish.
    role = await resolve_resource_role(uid, channel_id, db_module=dbm,
                                       use_cache=use_cache)
    if role is None:
        return _deny(**base, reason=REASON_NOT_A_MEMBER)

    if permission not in RESOURCE_ROLE_PERMISSIONS.get(role, frozenset()):
        return _deny(**base, role=role, reason=REASON_INSUFFICIENT_ROLE)

    return AccessDecision(True, **base, role=role, reason=REASON_OK)


async def can(user_id, resource_type=RESOURCE_TYPE_CHANNEL, resource_id=None,
              action=ACTION_VIEW, *, db_module=None, use_cache: bool = True,
              allow_admin: bool = False) -> bool:
    """MARKAZIY ruxsat tekshiruvi: foydalanuvchi resurs ustida amal bajara oladimi?

    Foydalanish (topshiriq talab qilgan shakl)::

        allowed = await rbac_service.can(
            user_id=query.from_user.id,   # server-side ``from_user.id``
            resource_type="channel",
            resource_id=channel_id,
            action="publish",
        )

    Qaytadi: ``True``/``False`` (fail-closed).  Har bir rad etish WARNING
    bilan loglanadi va ``recent_denials()`` jurnaliga yoziladi.
    """
    decision = await check(
        user_id, resource_type=resource_type, resource_id=resource_id,
        action=action, db_module=db_module, use_cache=use_cache,
        allow_admin=allow_admin,
    )
    if not decision.allowed:
        _log_denied(decision)
    return bool(decision.allowed)


#: Qulaylik aliaslar (o'qish uchun tabiiy nomlar).
async def check_resource_access(user_id, resource_type=RESOURCE_TYPE_CHANNEL,
                                resource_id=None, action=ACTION_VIEW, **kwargs):
    """:func:`check` bilan bir xil (nom boshqa modullarda qulayroq)."""
    return await check(user_id, resource_type=resource_type,
                       resource_id=resource_id, action=action, **kwargs)


async def require_resource(user_id, resource_type=RESOURCE_TYPE_CHANNEL,
                           resource_id=None, action=ACTION_VIEW, **kwargs) -> bool:
    """:func:`can` — ruxsat bo'lmasa ``ResourcePermissionDenied`` ko'taradi."""
    decision = await check(user_id, resource_type=resource_type,
                           resource_id=resource_id, action=action, **kwargs)
    if not decision.allowed:
        _log_denied(decision)
        raise ResourcePermissionDenied(decision)
    return True


def _log_denied(decision: AccessDecision) -> None:
    """Rad etilgan resurs so'rovini WARNING sifatida yozadi (audit izi)."""
    logger.warning(
        "RBAC/IDOR rad etildi: user=%s resource=%s:%s action=%s role=%s sabab=%s",
        decision.user_id, decision.resource_type, decision.resource_id,
        decision.action, decision.role, decision.reason,
    )


async def can_any(user_id, resource_ids, resource_type=RESOURCE_TYPE_CHANNEL,
                  action=ACTION_VIEW, **kwargs) -> bool:
    """Berilgan resurslardan KAMIDA BITTASI uchun ruxsat bormi?"""
    for resource_id in resource_ids or ():
        if await can(user_id, resource_type=resource_type,
                     resource_id=resource_id, action=action, **kwargs):
            return True
    return False
