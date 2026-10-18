"""👑 Super admin — Mini App API (``/api/v1/admin/*``).

Faqat adminlar uchun (botdagi admin panel bilan BIR XIL ruxsat: ``rbac_service`` rollari; birja nazoratida ban/blok uchun
``manage_users`` huquqi). Ruxsatsiz foydalanuvchi uchun hamma marshrut ``403 admin_only``: ichki ma'lumot (reklama matni,
sponsor ro'yxati, statistika) HECH QACHON oddiy foydalanuvchiga ko'rinmaydi.

Qoidalar bot bilan bir xil: reklama matni ``validate_ad_html`` (faqat ruxsat etilgan teglar), tugma matni/havolasi
``validate_button_*`` (xavfli protokollar rad), interval 1..100; sponsor kanal qo'shishda bot o'sha kanalda admin bo'lishi
jonli tekshiriladi. Har bir o'zgartirish ``admin_audit_logs`` ga yoziladi (``AuditService``).
"""
from __future__ import annotations

import asyncio
import logging
import re

from . import writes
from .errors import ApiError
from .settings import MiniAppSettings

logger = logging.getLogger(__name__)

AD_SCOPES = ("channel", "reply")
_CHANNEL_TARGET = re.compile(r"\A(?:@[A-Za-z][A-Za-z0-9_]{3,31}|-?[0-9]{5,20}|https://t\.me/[A-Za-z][A-Za-z0-9_]{3,31}/?)\Z")


def _db():
    import database as db

    return db


def parse_scope(value) -> str:
    if value not in AD_SCOPES:
        raise ApiError("invalid_input", field="scope")
    return value


def parse_ad_text(value) -> str:
    from utils.helpers import validate_ad_html

    if not isinstance(value, str):
        raise ApiError("invalid_input", field="text")
    ok, _err = validate_ad_html(value.strip(), max_len=_db().AD_TEXT_MAX_LEN)
    if not ok:
        raise ApiError("invalid_input", field="text")
    return value.strip()


def parse_ad_button(text, url) -> tuple[str, str]:
    """Tugma: ikkalasi ham bo'sh (tugmasiz) yoki ikkalasi ham to'g'ri."""
    from utils.helpers import validate_button_text, validate_button_url

    if text in (None, "") and url in (None, ""):
        return "", ""
    if not isinstance(text, str) or not isinstance(url, str):
        raise ApiError("invalid_input", field="button_text")
    if not validate_button_text(text)[0]:
        raise ApiError("invalid_input", field="button_text")
    if not validate_button_url(url)[0]:
        raise ApiError("invalid_input", field="button_url")
    return text.strip(), url.strip()


def parse_interval(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or value > 100:
        raise ApiError("invalid_input", field=field)
    return value


def public_ad(row: dict) -> dict:
    return {"id": row["id"], "scope": row["scope"], "text": row["text"], "button_text": row.get("button_text") or "",
            "button_url": row.get("button_url") or "", "is_active": bool(row.get("is_active", True))}


class AdminApi:
    def __init__(self, service, settings: MiniAppSettings, *, bot_factory=None) -> None:
        self._service = service
        self._settings = settings
        self._gate = asyncio.Semaphore(settings.max_inflight_db)
        self._bot_holder = writes.MediaFetcher(settings.bot_token, bot_factory)

    # ------------------------------------------------------------ yordamchilar
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
            logger.warning("miniapp admin: DB xatosi (%s)", type(exc).__name__)
            raise ApiError("service_unavailable", retry_after=3) from None
        finally:
            self._gate.release()

    async def aclose(self) -> None:
        await self._bot_holder.aclose()

    async def require_admin(self, user_id: int) -> None:
        """Botdagi admin panel bilan bir xil qoida (``ADMIN_ROLES``); aks holda 403 ``admin_only``."""
        ctx = await self._service.authorize(user_id)
        if not ctx.get("is_admin"):
            raise ApiError("admin_only")

    async def _audit(self, admin_id: int, action: str, target_type: str, target_id, new_value=None) -> None:
        try:
            from services.audit_service import AuditService

            await self._blocking(lambda: AuditService.log_action(admin_id, action, target_type=target_type,
                                                                 target_id=str(target_id), new_value=new_value))
        except ApiError:
            pass
        except Exception:  # noqa: BLE001 — audit xatosi amalni bekor qilmasin
            logger.debug("miniapp admin: audit yozilmadi", exc_info=True)

    # ---------------------------------------------------------------- umumiy
    async def overview(self, user_id: int) -> dict:
        await self.require_admin(user_id)
        db = _db()
        dash = await self._blocking(db.get_admin_dashboard_stats)
        system = await self._blocking(db.get_system_stats)
        from repositories import ad_market_repository as market

        mk = await self._blocking(market.admin_market_totals)
        countries = await self._blocking(db.country_stats)
        return {
            "stats": {"users": dash.get("users", 0), "pro_subscribers": dash.get("pro_subscribers", 0),
                      "channels": dash.get("channels", 0), "posts_today": dash.get("posts_today", 0),
                      "pending_posts": dash.get("pending_posts", 0), "stars_revenue": dash.get("stars_revenue", 0),
                      "sent": system.get("sent", 0), "failed": system.get("failed", 0),
                      "cancelled": system.get("cancelled", 0), "sponsors": system.get("sponsors", 0)},
            "market": mk,
            "countries": countries,
        }

    # ---------------------------------------------------------------- reklama
    async def ads(self, user_id: int) -> dict:
        await self.require_admin(user_id)
        db = _db()
        settings = await self._blocking(db.get_ad_settings)
        out = {"settings": {
            "reply": {"enabled": bool(settings.get("auto_ad_status", False)), "interval": int(settings.get("auto_ad_interval", 4))},
            "channel": {"enabled": bool(settings.get("channel_ad_status", True)), "interval": int(settings.get("channel_ad_interval", 3))},
        }, "items": {}}
        for scope in AD_SCOPES:
            rows = await self._blocking(db.get_ads_full, scope, True)
            out["items"][scope] = [public_ad(r) for r in rows or []]
        return out

    async def update_ad_settings(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("reply_enabled", "reply_interval", "channel_enabled", "channel_interval"))
        if not body:
            raise ApiError("invalid_input")
        await self.require_admin(user_id)
        db = _db()
        for key in ("reply_enabled", "channel_enabled"):
            if key in body and not isinstance(body[key], bool):
                raise ApiError("invalid_input", field=key)
        ops = []
        if "reply_enabled" in body:
            ops.append((db.set_ad_status, body["reply_enabled"]))
        if "reply_interval" in body:
            ops.append((db.set_ad_interval, parse_interval(body["reply_interval"], "reply_interval")))
        if "channel_enabled" in body:
            ops.append((db.set_channel_ad_status, body["channel_enabled"]))
        if "channel_interval" in body:
            ops.append((db.set_channel_ad_interval, parse_interval(body["channel_interval"], "channel_interval")))
        for fn, value in ops:
            if not await self._blocking(fn, value):
                raise ApiError("save_failed", retry_after=5)
        await self._audit(user_id, "ad_update", "ad_settings", "global", body)
        return await self.ads(user_id)

    async def create_ad(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("scope", "text", "button_text", "button_url"))
        scope = parse_scope(body.get("scope"))
        text = parse_ad_text(body.get("text"))
        btn_text, btn_url = parse_ad_button(body.get("button_text"), body.get("button_url"))
        await self.require_admin(user_id)
        db = _db()
        ad_id = await self._blocking(lambda: db.add_ad(scope, text, btn_text, btn_url))
        if not ad_id:
            raise ApiError("save_failed", retry_after=5)
        await self._audit(user_id, "ad_update", "ad", ad_id, {"action": "create", "scope": scope})
        row = await self._blocking(db.get_ad, ad_id)
        return {"ad": public_ad(row)}

    async def update_ad(self, user_id: int, ad_id: int, body: dict) -> dict:
        writes._only_keys(body, ("text", "button_text", "button_url", "is_active"))
        if not body:
            raise ApiError("invalid_input")
        text = parse_ad_text(body["text"]) if "text" in body else None
        button = None
        if "button_text" in body or "button_url" in body:
            button = parse_ad_button(body.get("button_text"), body.get("button_url"))
        if "is_active" in body and not isinstance(body["is_active"], bool):
            raise ApiError("invalid_input", field="is_active")
        await self.require_admin(user_id)
        db = _db()
        if await self._blocking(db.get_ad, ad_id) is None:
            raise ApiError("not_found")
        if text is not None or button is not None:
            ok = await self._blocking(lambda: db.update_ad(ad_id, text, button[0] if button else None, button[1] if button else None))
            if not ok:
                raise ApiError("save_failed", retry_after=5)
        if "is_active" in body and not await self._blocking(lambda: db.set_ad_active(ad_id, body["is_active"])):
            raise ApiError("save_failed", retry_after=5)
        await self._audit(user_id, "ad_update", "ad", ad_id, {k: v for k, v in body.items() if k != "text"})
        return {"ad": public_ad(await self._blocking(db.get_ad, ad_id))}

    async def delete_ad(self, user_id: int, ad_id: int) -> dict:
        await self.require_admin(user_id)
        db = _db()
        if not await self._blocking(db.delete_ad, ad_id):
            raise ApiError("not_found")
        await self._audit(user_id, "ad_update", "ad", ad_id, {"action": "delete"})
        return {"id": ad_id, "deleted": True}

    # ---------------------------------------------------------------- majburiy obuna
    @staticmethod
    def _sponsor(row) -> dict:
        s_id, ch_id, title, username, link = row[:5]
        return {"id": int(s_id), "channel_id": str(ch_id), "title": title or "", "username": username or "", "invite_link": link or ""}

    async def sponsors(self, user_id: int) -> dict:
        await self.require_admin(user_id)
        rows = await self._blocking(_db().get_sponsor_channels)
        if rows is None:
            raise ApiError("service_unavailable", retry_after=3)
        return {"items": [self._sponsor(r) for r in rows]}

    async def add_sponsor(self, user_id: int, body: dict) -> dict:
        writes._only_keys(body, ("channel",))
        raw = body.get("channel")
        if not isinstance(raw, str) or not _CHANNEL_TARGET.match(raw.strip()):
            raise ApiError("invalid_input", field="channel")
        target = raw.strip()
        if target.startswith("https://t.me/"):
            target = "@" + target.removeprefix("https://t.me/").strip("/")
        await self.require_admin(user_id)
        from telegram.error import BadRequest, Forbidden, TelegramError

        bot = await self._bot_holder.get_bot()
        chat_ref = int(target) if target.lstrip("-").isdigit() else target
        try:
            chat = await bot.get_chat(chat_ref)
            member = await bot.get_chat_member(chat.id, bot.id)
        except (BadRequest, Forbidden):
            raise ApiError("sponsor_not_found") from None
        except TelegramError:
            raise ApiError("service_unavailable", retry_after=5) from None
        if member.status not in ("administrator", "creator"):
            raise ApiError("sponsor_not_admin")
        link = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "")
        if not link:
            try:
                link = await bot.export_chat_invite_link(chat.id)
            except TelegramError:
                link = f"https://t.me/c/{str(chat.id).replace('-100', '')}"
        db = _db()
        ok = await self._blocking(lambda: db.add_sponsor_channel(channel_id=chat.id, title=chat.title or "", username=chat.username or "",
                                                                 invite_link=link))
        if not ok:
            raise ApiError("save_failed", retry_after=5)
        await self._audit(user_id, "sponsor_update", "sponsor", chat.id, {"action": "add"})
        return await self.sponsors(user_id)

    async def delete_sponsor(self, user_id: int, sponsor_id: int) -> dict:
        await self.require_admin(user_id)
        if not await self._blocking(_db().remove_sponsor_channel, sponsor_id):
            raise ApiError("not_found")
        await self._audit(user_id, "sponsor_update", "sponsor", sponsor_id, {"action": "delete"})
        return {"id": sponsor_id, "deleted": True}

    # ---------------------------------------------------------------- birja nazorati
    async def _require_moderator(self, user_id: int) -> None:
        await self.require_admin(user_id)
        from services.rbac_service import PERM_MANAGE_USERS, has_permission

        if not has_permission(user_id, PERM_MANAGE_USERS):
            raise ApiError("admin_only")

    async def market(self, user_id: int, status: str | None) -> dict:
        await self.require_admin(user_id)
        if status not in (None, "", "active", "paused", "blocked"):
            raise ApiError("bad_request")
        from repositories import ad_market_repository as market

        totals = await self._blocking(market.admin_market_totals)
        items = await self._blocking(market.admin_list_listings, 30, status or None)
        return {"totals": totals, "items": items}

    async def set_listing_status(self, user_id: int, listing_id: int, body: dict) -> dict:
        writes._only_keys(body, ("status",))
        if body.get("status") not in ("active", "blocked"):
            raise ApiError("invalid_input", field="status")
        await self._require_moderator(user_id)
        from repositories import ad_market_repository as market

        if not await self._blocking(market.admin_set_listing_status, listing_id, body["status"]):
            raise ApiError("not_found")
        await self._audit(user_id, "system_settings", "market_listing", listing_id, {"status": body["status"]})
        return {"id": listing_id, "status": body["status"]}

    async def set_user_ban(self, user_id: int, target_id: int, body: dict) -> dict:
        writes._only_keys(body, ("banned",))
        if not isinstance(body.get("banned"), bool):
            raise ApiError("invalid_input", field="banned")
        await self._require_moderator(user_id)
        from repositories import ad_market_repository as market

        await self._blocking(market.admin_set_ban, target_id, body["banned"])
        await self._audit(user_id, "system_settings", "market_user", target_id, {"banned": body["banned"]})
        return {"user_id": target_id, "banned": body["banned"]}
