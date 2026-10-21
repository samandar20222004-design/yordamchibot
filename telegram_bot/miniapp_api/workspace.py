"""👥 Ish joyi (workspace): yordamchi egasining kanallarida ruxsat etilgan doirada ishlaydi.

Mijoz ``X-Workspace: <egasi_id>`` sarlavhasini yuboradi. FAQAT ``@_ws`` bilan belgilangan marshrutlar uni hisobga oladi
(kanallar, rejalar, post yaratish/tahrirlash). Server:
  1. yordamchining ENG ESKI ``team_seats`` o'rindiqlaridan biri ekanini tekshiradi (``team_invites.workspace_access``);
  2. ``request["user_id"]`` ni egasiga almashtiradi (egasining tarifi, kvotasi va kanallari ishlaydi),
     haqiqiy foydalanuvchi ``request["acting_user"]`` da qoladi (yozuv/AI limitlari yordamchiga hisoblanadi);
  3. ruxsat etilgan kanallar ``ContextVar`` ga yoziladi: repozitoriy SQL'i FAQAT shu kanallarni ko'radi;
  4. amal rolga mos kelishini tekshiradi (``ROLE_ACTIONS``): editor — hammasi, scheduler — yaratish/vaqtni o'zgartirish, analyst — faqat ko'rish.
"""
from __future__ import annotations

import contextvars

from .errors import ApiError

#: Ruxsat etilgan kanal ID'lari (``None`` = cheklov yo'q: foydalanuvchi o'z ish joyida).
_ALLOWED: contextvars.ContextVar = contextvars.ContextVar("miniapp_ws_channels", default=None)


def allowed_channels():
    """Ish joyida bo'lsa — ruxsat etilgan kanal ID'lari ro'yxati; aks holda ``None``."""
    value = _ALLOWED.get()
    return None if value is None else list(value)


def activate(channels) -> contextvars.Token:
    return _ALLOWED.set(tuple(str(c) for c in channels))


def reset(token) -> None:
    try:
        _ALLOWED.reset(token)
    except ValueError:  # boshqa kontekst
        pass


def mark(handler):
    """Marshrut ish joyi sarlavhasini hisobga oladi."""
    handler.miniapp_ws = True
    return handler


def parse_header(raw) -> int | None:
    if raw is None or raw == "":
        return None
    raw = str(raw).strip()
    if not raw.isdigit() or len(raw) > 15 or int(raw) <= 0:
        raise ApiError("bad_request")
    return int(raw)


def require_action(request, action: str, channel_id) -> None:
    """Ish joyida bo'lmasa — hech narsa. Bo'lsa: kanal ruxsat doirasida va rol amalga yetarli bo'lishi shart."""
    access = request.get("ws_access")
    if access is None:
        return
    from services.team_invites import ROLE_ACTIONS

    role = access.get(str(channel_id))
    if role is None or action not in ROLE_ACTIONS.get(role, frozenset()):
        raise ApiError("workspace_denied")
