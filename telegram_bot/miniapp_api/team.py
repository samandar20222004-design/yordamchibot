"""👥 Jamoa — Mini App API (``/api/v1/team/*``).

Egasi: yordamchi taklif qiladi (kanal + rol), a'zolarni boshqaradi, o'rindiqlarni ko'radi (ULTRA: egasi + 2 yordamchi;
PRO/FREE: bitta odam — taklif yo'q). Yordamchi: ish joylarini ko'radi, chiqadi. Hammaga: «Men kimman?» rejimi.
Egalik HAR DOIM serverda (``services/team_invites``): kanal ``channels.user_id`` orqali; ``user_id`` faqat tasdiqlangan initData'dan.
"""
from __future__ import annotations

import asyncio
import logging

from . import writes
from .errors import ApiError
from .settings import MiniAppSettings

logger = logging.getLogger(__name__)

_ERRORS = {"no_team": "team_no_seats", "seats_full": "team_seats_full", "too_many_pending": "team_seats_full",
           "not_owner": "channel_not_found", "bad_role": "invalid_input"}


def _iso(value):
    try:
        return value.isoformat()
    except Exception:  # noqa: BLE001
        return None


class TeamApi:
    def __init__(self, service, settings: MiniAppSettings) -> None:
        self._service = service
        self._settings = settings
        self._gate = asyncio.Semaphore(settings.max_inflight_db)

    async def _blocking(self, fn, *args):
        try:
            await asyncio.wait_for(self._gate.acquire(), self._settings.db_queue_wait_seconds or 0.01)
        except asyncio.TimeoutError:
            raise ApiError("service_unavailable", retry_after=2) from None
        try:
            return await asyncio.to_thread(fn, *args)
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("miniapp team: DB xatosi (%s)", type(exc).__name__)
            raise ApiError("service_unavailable", retry_after=3) from None
        finally:
            self._gate.release()

    async def overview(self, user_id: int) -> dict:
        await self._service.authorize(user_id)
        from services import team_invites as TI

        team = await self._blocking(TI.list_team, user_id)
        workspaces = await self._blocking(TI.workspaces_for, user_id)
        mode = await self._blocking(TI.get_mode, user_id)
        seats = team["seats"]
        return {
            "mode": mode,
            "seats": seats,
            "can_invite": seats["limit"] > 0,
            "channels": [{"channel_id": c["channel_id"], "title": c["title"],
                          "members": [{"user_id": m["user_id"], "name": m["name"], "username": m["username"], "role": m["role"],
                                       "active": m["active"], "since": _iso(m["since"])} for m in c["members"]],
                          "invites": [{"id": i["id"], "role": i["role"], "expires_at": _iso(i["expires_at"])} for i in c["invites"]]}
                         for c in team["channels"]],
            "workspaces": workspaces,
        }

    async def set_mode(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("mode",))
        mode = body.get("mode")
        if mode not in ("owner", "helper"):
            raise ApiError("invalid_input", field="mode")
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.set_mode, user_id, mode):
            raise ApiError("save_failed", retry_after=5)
        return {"mode": mode}

    async def create_invite(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel_id", "role"))
        channel_id = writes.parse_channel_id(body.get("channel_id"))
        role = body.get("role")
        if role not in ("editor", "scheduler", "analyst"):
            raise ApiError("invalid_input", field="role")
        await self._service.authorize(user_id)
        from services import team_invites as TI

        res = await self._blocking(TI.create_invite, user_id, channel_id, role)
        if not res.get("ok"):
            raise ApiError(_ERRORS.get(res.get("error"), "save_failed"), **({"field": "channel_id"} if res.get("error") == "not_owner" else {}))
        return {"id": res["id"], "token": res["token"], "role": role, "channel_id": channel_id, "expires_at": _iso(res["expires_at"])}

    async def revoke_invite(self, user_id: int, invite_id: int) -> dict:
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.revoke_invite, user_id, invite_id):
            raise ApiError("not_found")
        return {"id": invite_id, "revoked": True}

    async def update_member(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel_id", "user_id", "role"))
        channel_id = writes.parse_channel_id(body.get("channel_id"))
        member = body.get("user_id")
        if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
            raise ApiError("invalid_input", field="user_id")
        role = body.get("role")
        if role not in ("editor", "scheduler", "analyst"):
            raise ApiError("invalid_input", field="role")
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.set_member_role, user_id, channel_id, member, role):
            raise ApiError("not_found")
        return {"channel_id": channel_id, "user_id": member, "role": role}

    async def remove_member(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel_id", "user_id"))
        channel_id = writes.parse_channel_id(body.get("channel_id"))
        member = body.get("user_id")
        if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
            raise ApiError("invalid_input", field="user_id")
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.remove_member, user_id, channel_id, member):
            raise ApiError("not_found")
        return {"channel_id": channel_id, "user_id": member, "removed": True}

    async def leave(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("owner_id",))
        owner = body.get("owner_id")
        if isinstance(owner, bool) or not isinstance(owner, int) or owner <= 0:
            raise ApiError("invalid_input", field="owner_id")
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.leave, user_id, owner):
            raise ApiError("not_found")
        return {"owner_id": owner, "left": True}
