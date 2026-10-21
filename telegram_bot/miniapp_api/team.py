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
                          "members": [{"user_id": m["user_id"], "name": m["name"], "username": m["username"], "role": m["role"], "perms": m["perms"],
                                       "active": m["active"], "since": _iso(m["since"])} for m in c["members"]],
                          "invites": [{"id": i["id"], "role": i["role"], "perms": i["perms"], "expires_at": _iso(i["expires_at"])} for i in c["invites"]]}
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

    @staticmethod
    def _parse_perms(body: dict):
        """``perms`` (ro'yxat yoki shablon nomi) yoki eski ``role``; ikkalasi ham yo'q = hammasi."""
        from services import team_invites as TI

        raw = body.get("perms", body.get("role"))
        if raw is None and "perms" not in body and "role" not in body:
            return list(TI.PRESETS["full"])
        if isinstance(raw, str) and raw not in TI.PRESETS:
            raise ApiError("invalid_input", field="perms")
        if isinstance(raw, list) and not all(isinstance(x, str) for x in raw):
            raise ApiError("invalid_input", field="perms")
        got = TI.normalize_perms(raw)
        if got is None:
            raise ApiError("invalid_input", field="perms")
        return got

    async def create_invite(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel_id", "channel_ids", "perms", "role"))
        raw_ids = body.get("channel_ids") if "channel_ids" in body else [body.get("channel_id")]
        if not isinstance(raw_ids, list) or not 1 <= len(raw_ids) <= 10:
            raise ApiError("invalid_input", field="channel_ids")
        channel_ids = [writes.parse_channel_id(c) for c in raw_ids]
        perms = self._parse_perms(body)
        await self._service.authorize(user_id)
        from services import team_invites as TI

        res = await self._blocking(TI.create_invite, user_id, channel_ids, perms)
        if not res.get("ok"):
            raise ApiError(_ERRORS.get(res.get("error"), "save_failed"), **({"field": "channel_ids"} if res.get("error") == "not_owner" else {}))
        return {"id": res["id"], "token": res["token"], "perms": perms, "channel_ids": channel_ids, "expires_at": _iso(res["expires_at"])}

    async def revoke_invite(self, user_id: int, invite_id: int) -> dict:
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.revoke_invite, user_id, invite_id):
            raise ApiError("not_found")
        return {"id": invite_id, "revoked": True}

    async def update_member(self, user_id: int, body: dict) -> dict:
        """Bitta kanaldagi a'zoning ruxsatlarini o'zgartiradi (``perms`` yoki eski ``role`` shabloni)."""
        writes._only_keys(body, ("channel_id", "user_id", "perms", "role"))
        channel_id = writes.parse_channel_id(body.get("channel_id"))
        member = body.get("user_id")
        if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
            raise ApiError("invalid_input", field="user_id")
        if "perms" not in body and "role" not in body:
            raise ApiError("invalid_input", field="perms")
        perms = self._parse_perms(body)
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.set_member_perms, user_id, channel_id, member, perms):
            raise ApiError("not_found")
        return {"channel_id": channel_id, "user_id": member, "perms": perms}

    async def update_helper(self, user_id: int, body: dict) -> dict:
        """Yordamchini markaz qilib sozlaydi: u ishlaydigan kanallar to'plami + ruxsatlari (hammasiga bir xil)."""
        writes._only_keys(body, ("user_id", "channel_ids", "perms"))
        member = body.get("user_id")
        if isinstance(member, bool) or not isinstance(member, int) or member <= 0:
            raise ApiError("invalid_input", field="user_id")
        raw_ids = body.get("channel_ids")
        if not isinstance(raw_ids, list) or len(raw_ids) > 50:
            raise ApiError("invalid_input", field="channel_ids")
        channel_ids = [writes.parse_channel_id(c) for c in raw_ids]
        if "perms" not in body:
            raise ApiError("invalid_input", field="perms")
        perms = self._parse_perms(body)
        await self._service.authorize(user_id)
        from services import team_invites as TI

        if not await self._blocking(TI.set_helper, user_id, member, channel_ids, perms):
            raise ApiError("not_found")
        return {"user_id": member, "channel_ids": channel_ids, "perms": perms}

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
