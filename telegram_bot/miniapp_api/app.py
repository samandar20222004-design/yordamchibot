"""aiohttp ulanish nuqtasi: ``register_miniapp_routes(app)``.

``MINIAPP_ENABLED=0`` (sukut) yoki xavfsiz bo'lmagan sozlama bo'lsa HECH QANDAY
marshrut ulanmaydi (bot serveri qolgan qismi bilan ishlayveradi).

API ``/api/v1`` ichki-ilovasi (sub-app) sifatida ulanadi: middleware faqat shu
yerga tegishli, shuning uchun ``/health*``, ``/`` va ``/payments/payme`` ga
ta'sir qila olmaydi.

So'rov tartibi (``/api/v1/health`` dan tashqari):
  HTTPS -> IP bo'yicha QAT'IY limit (HMAC'dan OLDIN) -> ``initData`` tekshiruvi ->
  foydalanuvchi bo'yicha limit -> handler (HTTP timeout bilan).

HTTP timeout faqat mijozga javobni qisqartiradi; DB so'rovi (thread) o'zi
to'xtamaydi — qarang ``miniapp_api.db``.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid

from services import user_timezone as _tzs
from datetime import datetime, timedelta, timezone

from aiohttp import web

from .auth import AuthError, parse_authorization, validate_init_data
from . import media_items
from .db import ReadOnlyRunner
from .errors import ApiError, error_response, pick_lang
from .proxy import resolve_client
from .ratelimit import StrictLimiter
from .repository import MAX_OFFSET
from .service import MiniAppService
from .settings import MiniAppSettings, load_settings
from .static import register_static_routes
from . import workspace
from .admin import AdminApi
from .team import TeamApi
from .market import MarketApi
from .writes import PostWriter, read_json_object

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"
_INT_RE = re.compile(r"\A[0-9]{1,7}\Z")
_CHANNEL_ID_RE = re.compile(r"\A-?[0-9]{5,20}\Z")   # Telegram chat_id (kanal: -100...)

_K_SETTINGS = web.AppKey("miniapp_settings", MiniAppSettings)
_K_SERVICE = web.AppKey("miniapp_service", MiniAppService)
_K_LIMITER = web.AppKey("miniapp_limiter", StrictLimiter)
_K_CLOCK = web.AppKey("miniapp_clock", object)
_K_WRITER = web.AppKey("miniapp_writer", PostWriter)
_K_MARKET = web.AppKey("miniapp_market", MarketApi)
_K_ADMIN = web.AppKey("miniapp_admin", AdminApi)
_K_TEAM = web.AppKey("miniapp_team", TeamApi)


def _public(handler):
    handler.miniapp_public = True
    return handler


def _write(handler):
    """Yozuvchi marshrut: foydalanuvchi bo'yicha YOZUV limiti ham qo'llanadi."""
    handler.miniapp_write = True
    return handler


def _ai(handler):
    """AI marshruti: yozuv limiti + AI limiti + uzoqroq HTTP timeout."""
    handler.miniapp_write = True
    handler.miniapp_ai = True
    return handler


def _upload(handler):
    """Fayl yuklash marshruti: yozuv-limiti + qat'iy yuklash limiti + uzoqroq HTTP timeout."""
    handler.miniapp_write = True
    handler.miniapp_upload = True
    return handler


_ws = workspace.mark  # «ish joyi» sarlavhasini hisobga oladigan marshrut (miniapp_api/workspace.py)

#: PATCH /posts/{id} da faqat shu kalitlar bo'lsa — bu «vaqtni o'zgartirish» (scheduler roli ham qila oladi).
_RESCHEDULE_KEYS = frozenset({"scheduled_at", "recurrence_time", "recurrence_time2"})


def _post_channel_sync(owner_id: int, post_id: int):
    from database import db_cursor

    with db_cursor() as cur:
        cur.execute("SELECT channel_id FROM scheduled_posts WHERE id = %s AND user_id = %s", (post_id, owner_id))
        row = cur.fetchone()
    return None if row is None else str(row[0])


async def _ws_post_check(request: web.Request, post_id: int, action: str) -> None:
    """Ish joyida: post kanali ruxsat doirasida va rol amalga yetarli. Oddiy rejimda — hech narsa."""
    if request.get("ws_access") is None:
        return
    channel = await asyncio.to_thread(_post_channel_sync, request["user_id"], post_id)
    if channel is None:
        raise ApiError("not_found")
    workspace.require_action(request, action, channel)


def _post_id(request: web.Request) -> int:
    raw = request.match_info.get("post_id", "")
    if not _INT_RE.match(raw) or int(raw) <= 0:
        raise ApiError("not_found")
    return int(raw)


def _parse_int(raw, *, default: int, lo: int, hi: int) -> int:
    if raw is None:
        return default
    if not _INT_RE.match(raw):
        raise ApiError("bad_request")
    value = int(raw)
    if value < lo or value > hi:
        raise ApiError("bad_request")
    return value


# ---------------------------------------------------------------- handlers
@_public
async def health_handler(request: web.Request):
    return web.json_response({"status": "ok", "api_version": 1},
                             headers={"Cache-Control": "no-store"})


async def me_handler(request: web.Request):
    data = await request.app[_K_SERVICE].me(request["user_id"])
    return web.json_response(data)


@_ws
async def channels_handler(request: web.Request):
    data = await request.app[_K_SERVICE].channels(request["user_id"])
    return web.json_response(data)


def _channel_id(request: web.Request) -> str:
    raw = request.match_info.get("channel_id", "")
    if not _CHANNEL_ID_RE.match(raw):
        raise ApiError("not_found")
    return raw


@_ws
async def channel_analytics_handler(request: web.Request):
    workspace.require_action(request, "analytics", _channel_id(request))
    data = await request.app[_K_SERVICE].channel_analytics(request["user_id"], _channel_id(request))
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_ws
async def scheduled_handler(request: web.Request):
    settings = request.app[_K_SETTINGS]
    limit = _parse_int(request.query.get("limit"), default=20, lo=1, hi=settings.max_page_size)
    offset = _parse_int(request.query.get("offset"), default=0, lo=0, hi=MAX_OFFSET)
    status = request.query.get("status", "pending")
    if status not in ("pending", "history"):
        raise ApiError("bad_request")
    data = await request.app[_K_SERVICE].scheduled_posts(
        request["user_id"], limit, offset, history=(status == "history"))
    return web.json_response(data)


_CALENDAR_MAX_DAYS = 45


def _parse_instant(raw: str | None) -> datetime:
    """ISO-8601 vaqt (zonasi bilan). Zonasiz yoki yaroqsiz qiymat -> 400 (server zonasiga taxmin qilinmaydi)."""
    if not raw or len(raw) > 40:
        raise ApiError("bad_request")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ApiError("bad_request") from None
    if value.tzinfo is None:
        raise ApiError("bad_request")
    return value.astimezone(timezone.utc)


@_ws
async def calendar_handler(request: web.Request):
    start = _parse_instant(request.query.get("from"))
    end = _parse_instant(request.query.get("to"))
    if not start < end or end - start > timedelta(days=_CALENDAR_MAX_DAYS):
        raise ApiError("bad_request")
    data = await request.app[_K_SERVICE].calendar(request["user_id"], start, end)
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_ws
async def post_detail_handler(request: web.Request):
    data = await request.app[_K_SERVICE].post(request["user_id"], _post_id(request))
    return web.json_response({"post": data})


async def draft_handler(request: web.Request):
    data = await request.app[_K_SERVICE].draft(request["user_id"])
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def draft_media_handler(request: web.Request):
    data, mime = await request.app[_K_WRITER].draft_photo(request["user_id"], media_items.parse_index(request.query.get("i")))
    return web.Response(body=data, content_type=mime, headers={
        "Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'"})


@_upload
async def draft_media_upload_handler(request: web.Request):
    data = await request.app[_K_WRITER].upload_media(request["user_id"], request, add=request.query.get("add") == "1")
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_write
async def draft_media_delete_handler(request: web.Request):
    data = await request.app[_K_WRITER].delete_draft_media(request["user_id"], media_items.parse_index(request.query.get("i")))
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_write
async def draft_delete_handler(request: web.Request):
    data = await request.app[_K_WRITER].delete_draft(request["user_id"])
    return web.json_response(data)


@_ws
async def post_media_handler(request: web.Request):
    await _ws_post_check(request, _post_id(request), "view")
    data, mime = await request.app[_K_WRITER].post_media(
        request["user_id"], _post_id(request), media_items.parse_index(request.query.get("i")))
    return web.Response(body=data, content_type=mime, headers={
        "Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'"})


@_upload
@_ws
async def post_media_upload_handler(request: web.Request):
    await _ws_post_check(request, _post_id(request), "edit")
    data = await request.app[_K_WRITER].upload_post_media(
        request["user_id"], _post_id(request), request, add=request.query.get("add") == "1", actor=request.get("acting_user"))
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_write
@_ws
async def post_media_delete_handler(request: web.Request):
    await _ws_post_check(request, _post_id(request), "edit")
    index = request.query.get("i")
    data = await request.app[_K_WRITER].delete_post_media(
        request["user_id"], _post_id(request), None if index in (None, "") else media_items.parse_index(index))
    return web.json_response(data)


@_write
@_ws
async def post_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    draft_user = None
    if request.get("ws_access") is not None:
        # Ish joyida: kanal va ruxsat tekshiriladi; qoralama (media) YORDAMCHINING o'zida, post esa egasi nomidan yaratiladi.
        channel = str(body.get("channel_id"))
        workspace.require_action(request, "create", channel)
        if body.get("send_now") is True:
            workspace.require_action(request, "send_now", channel)
        draft_user = request["acting_user"]
    data = await request.app[_K_WRITER].create_post(request["user_id"], body, draft_user=draft_user)
    return web.json_response(data, status=201 if data["created"] else 200)


@_write
@_ws
async def post_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    await _ws_post_check(request, _post_id(request), "reschedule" if body and set(body) <= _RESCHEDULE_KEYS else "edit")
    data = await request.app[_K_WRITER].update_post(request["user_id"], _post_id(request), body)
    return web.json_response(data)


@_write
@_ws
async def post_delete_handler(request: web.Request):
    await _ws_post_check(request, _post_id(request), "delete")
    data = await request.app[_K_WRITER].cancel_post(request["user_id"], _post_id(request))
    return web.json_response(data)


@_write
async def settings_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].update_settings(request["user_id"], body)
    return web.json_response(data)


async def templates_handler(request: web.Request):
    data = await request.app[_K_WRITER].list_templates(request["user_id"])
    return web.json_response(data, headers={"Cache-Control": "no-store"})


@_write
async def template_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].create_template(request["user_id"], body)
    return web.json_response(data, status=201 if data["created"] else 200)


@_write
async def template_delete_handler(request: web.Request):
    raw = request.match_info.get("template_id", "")
    if not _INT_RE.match(raw) or int(raw) <= 0:
        raise ApiError("not_found")
    data = await request.app[_K_WRITER].delete_template(request["user_id"], int(raw))
    return web.json_response(data)


@_ai
@_ws
async def ai_generate_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    workspace.require_any_channel(request, "ai")  # ish joyida AI EGASINING kvotasidan ketadi
    data = await request.app[_K_WRITER].ai_generate(request["user_id"], body)
    return web.json_response(data)


@_ai
@_ws
async def schedule_parse_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    workspace.require_any_channel(request, "create")
    data = await request.app[_K_WRITER].parse_schedule(request["user_id"], body)
    return web.json_response(data, headers={"Cache-Control": "no-store"})



# ----------------------------------------------------------- reklama birjasi
def _market_id(request: web.Request) -> int:
    raw = request.match_info.get("item_id", "")
    if not _INT_RE.match(raw) or int(raw) <= 0:
        raise ApiError("not_found")
    return int(raw)


async def market_summary_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].summary(request["user_id"]), headers={"Cache-Control": "no-store"})


async def market_catalog_handler(request: web.Request):
    page = _parse_int(request.query.get("page"), default=0, lo=0, hi=10000)
    data = await request.app[_K_MARKET].catalog(
        request["user_id"], category=request.query.get("category"), sort=request.query.get("sort", "m"), page=page,
        country=request.query.get("country", "all"))
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def market_listing_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].listing(request["user_id"], _market_id(request)),
                             headers={"Cache-Control": "no-store"})


@_write
async def market_inquire_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_MARKET].inquire(request["user_id"], _market_id(request), body)
    return web.json_response(data, status=201)


@_write
async def market_report_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].report(request["user_id"], _market_id(request)))


async def market_mine_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].mine(request["user_id"]), headers={"Cache-Control": "no-store"})


@_write
async def market_publish_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_MARKET].publish(request["user_id"], body), status=201)


@_write
async def market_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_MARKET].update_listing(request["user_id"], _market_id(request), body))


@_write
async def market_refresh_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].refresh(request["user_id"], _market_id(request)))


@_write
async def market_delete_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].delete_listing(request["user_id"], _market_id(request)))


async def market_threads_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].threads(request["user_id"]), headers={"Cache-Control": "no-store"})


async def market_thread_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].thread(request["user_id"], _market_id(request)),
                             headers={"Cache-Control": "no-store"})


@_write
async def market_reply_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_MARKET].reply(request["user_id"], _market_id(request), body), status=201)


async def market_unread_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].unread(request["user_id"]), headers={"Cache-Control": "no-store"})


@_write
async def market_report_user_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].report_user(request["user_id"], _market_id(request)))


@_write
async def market_close_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].close_thread(request["user_id"], _market_id(request)))


@_write
async def market_block_handler(request: web.Request):
    return web.json_response(await request.app[_K_MARKET].block(request["user_id"], _market_id(request)))



# ------------------------------------------------------------ super admin
_BIG_INT_RE = re.compile(r"\A[0-9]{1,15}\Z")


def _admin_id(request: web.Request, name: str = "item_id") -> int:
    raw = request.match_info.get(name, "")
    if not _BIG_INT_RE.match(raw) or int(raw) <= 0:
        raise ApiError("not_found")
    return int(raw)


async def admin_overview_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].overview(request["user_id"]), headers={"Cache-Control": "no-store"})


async def admin_ads_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].ads(request["user_id"]), headers={"Cache-Control": "no-store"})


@_write
async def admin_ad_settings_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].update_ad_settings(request["user_id"], body))


@_write
async def admin_ad_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].create_ad(request["user_id"], body), status=201)


@_write
async def admin_ad_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].update_ad(request["user_id"], _admin_id(request), body))


@_write
async def admin_ad_delete_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].delete_ad(request["user_id"], _admin_id(request)))


async def admin_sponsors_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].sponsors(request["user_id"]), headers={"Cache-Control": "no-store"})


@_write
async def admin_sponsor_add_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].add_sponsor(request["user_id"], body), status=201)


@_write
async def admin_sponsor_delete_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].delete_sponsor(request["user_id"], _admin_id(request)))


async def admin_market_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].market(request["user_id"], request.query.get("status")),
                             headers={"Cache-Control": "no-store"})


@_write
async def admin_market_status_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].set_listing_status(request["user_id"], _admin_id(request), body))


@_write
async def admin_market_ban_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].set_user_ban(request["user_id"], _admin_id(request), body))


async def admin_promos_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].promos(request["user_id"], request.query.get("status")),
                             headers={"Cache-Control": "no-store"})


async def admin_promo_detail_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].promo_detail(request["user_id"], request.match_info["code"]),
                             headers={"Cache-Control": "no-store"})


@_write
async def admin_promo_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].create_promo(request["user_id"], body), status=201)


@_write
async def admin_promo_active_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].set_promo_active(request["user_id"], request.match_info["code"], body))


@_write
async def admin_grant_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].grant_plan(request["user_id"], body))


async def admin_audit_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].audit(request["user_id"]), headers={"Cache-Control": "no-store"})


async def admin_features_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].feature_usage(request["user_id"]), headers={"Cache-Control": "no-store"})


async def admin_health_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].system_health(request["user_id"]), headers={"Cache-Control": "no-store"})


async def admin_roles_handler(request: web.Request):
    return web.json_response(await request.app[_K_ADMIN].roles(request["user_id"]), headers={"Cache-Control": "no-store"})


@_write
async def admin_role_set_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_ADMIN].set_role(request["user_id"], body))


# ------------------------------------------------------------ jamoa
async def team_handler(request: web.Request):
    return web.json_response(await request.app[_K_TEAM].overview(request["user_id"]), headers={"Cache-Control": "no-store"})


async def team_people_handler(request: web.Request):
    return web.json_response(await request.app[_K_TEAM].people(request["user_id"], request.query.get("q", "")),
                             headers={"Cache-Control": "no-store"})


@_write
async def team_mode_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].set_mode(request["user_id"], body))


@_write
async def team_invite_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].create_invite(request["user_id"], body), status=201)


@_write
async def team_invite_delete_handler(request: web.Request):
    return web.json_response(await request.app[_K_TEAM].revoke_invite(request["user_id"], _admin_id(request)))


@_write
async def team_member_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].update_member(request["user_id"], body))


@_write
async def team_helper_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].update_helper(request["user_id"], body))


@_write
async def team_member_remove_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].remove_member(request["user_id"], body))


@_write
async def team_leave_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    return web.json_response(await request.app[_K_TEAM].leave(request["user_id"], body))


# -------------------------------------------------------------- middleware
@web.middleware
async def api_middleware(request: web.Request, handler):
    started = time.monotonic()
    request_id = uuid.uuid4().hex[:16]
    request["request_id"] = request_id
    lang = pick_lang(request.headers.get("Accept-Language"))
    status = 500
    try:
        try:
            response = await _guarded(request, handler)
        except ApiError as err:
            lang = request.get("lang", lang)
            response = error_response(err, request_id=request_id, lang=lang)
        except web.HTTPNotFound:
            response = error_response(ApiError("not_found"), request_id=request_id, lang=lang)
        except web.HTTPMethodNotAllowed:
            response = error_response(ApiError("method_not_allowed"), request_id=request_id, lang=lang)
        except web.HTTPException:
            response = error_response(ApiError("bad_request"), request_id=request_id, lang=lang)
        except asyncio.TimeoutError:
            response = error_response(ApiError("service_unavailable", retry_after=5),
                                      request_id=request_id, lang=lang)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Faqat sinf nomi: istisno matni maxfiy bo'lishi mumkin.
            logger.error("miniapp: kutilmagan xato (%s) request_id=%s",
                         type(exc).__name__, request_id)
            response = error_response(ApiError("internal_error"), request_id=request_id, lang=lang)
        status = response.status
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    finally:
        # Authorization/initData/token hech qachon yozilmaydi.
        logger.info("miniapp %s %s -> %s %.0fms request_id=%s", request.method,
                    request.path, status, (time.monotonic() - started) * 1000, request_id)


async def _guarded(request: web.Request, handler):
    app = request.app
    # Marshrut topilmadi / usul mos emas: auth'siz ham aniq 404/405 (JSON).
    if request.match_info.http_exception is not None:
        raise request.match_info.http_exception
    settings: MiniAppSettings = app[_K_SETTINGS]
    limiter: StrictLimiter = app[_K_LIMITER]
    route_handler = getattr(request.match_info.route, "handler", None)
    is_public = bool(getattr(route_handler, "miniapp_public", False))

    transport = request.transport
    peername = transport.get_extra_info("peername") if transport else None
    scheme = "https" if (transport and transport.get_extra_info("sslcontext")) else "http"
    client = resolve_client(peername, request.headers, scheme, settings)
    request["client_ip"] = client.ip

    if not is_public:
        if settings.require_https and client.scheme != "https":
            raise ApiError("https_required")
        # 1) HMAC'dan OLDIN: IP bo'yicha qat'iy limit (xatoda 503).
        await limiter.hit("auth_ip", client.ip, limit=settings.rate_auth_limit,
                          window=settings.rate_auth_window)
        # 2) Telegram initData (har so'rovda qayta tekshiriladi).
        try:
            init_data = parse_authorization(request.headers.get("Authorization"))
            verified = validate_init_data(
                init_data, settings.bot_token, now=app[_K_CLOCK](),
                max_age=settings.auth_max_age_seconds,
                future_skew=settings.auth_future_skew_seconds,
                max_bytes=settings.init_data_max_bytes,
            )
        except AuthError as exc:
            raise ApiError(exc.code) from None
        request["user_id"] = verified.user_id  # YAGONA ishonchli manba
        if verified.language_code:
            request["lang"] = pick_lang(request.headers.get("Accept-Language"),
                                        verified.language_code)
        # 3) Foydalanuvchi bo'yicha limit.
        await limiter.hit("user", str(verified.user_id), limit=settings.rate_user_limit,
                          window=settings.rate_user_window)
        # 4) Foydalanuvchi vaqt zonasi (kiritish/ko'rsatish shu zonada; xatoda Toshkent).
        _tzs.set_current(_tzs.get_tz(_tzs.cached_name(verified.user_id) or await asyncio.to_thread(_tzs.tz_name_for, verified.user_id)))

    ws_token = None
    if not is_public and getattr(route_handler, "miniapp_ws", False):
        ws_owner = workspace.parse_header(request.headers.get("X-Workspace"))
        if ws_owner is not None and ws_owner != verified.user_id:
            from services import team_invites

            access = await asyncio.to_thread(team_invites.workspace_access, verified.user_id, ws_owner)
            if not access:
                raise ApiError("workspace_denied")
            request["acting_user"] = verified.user_id
            request["user_id"] = ws_owner  # egasining tarifi, kvotasi va kanallari; yozuv/AI limiti yordamchiga hisoblanadi
            request["ws_access"] = access
            ws_token = workspace.activate(access)

    timeout = settings.request_timeout_seconds
    if getattr(route_handler, "miniapp_write", False):
        await limiter.hit("write", str(verified.user_id), limit=settings.rate_write_limit,
                          window=settings.rate_write_window)
    if getattr(route_handler, "miniapp_upload", False):
        await limiter.hit("upload", str(verified.user_id), limit=settings.rate_upload_limit,
                          window=settings.rate_upload_window)
        timeout = max(timeout, settings.upload_timeout_seconds)  # 50 MB video sekin tarmoqda 60 s ga sig'maydi
    if getattr(route_handler, "miniapp_ai", False):
        await limiter.hit("ai", str(verified.user_id), limit=settings.rate_ai_limit,
                          window=settings.rate_ai_window)
        timeout = max(timeout, settings.ai_timeout_seconds)
    try:
        return await asyncio.wait_for(handler(request), timeout)
    finally:
        if ws_token is not None:
            workspace.reset(ws_token)


# ------------------------------------------------------------ ulash nuqtasi
def build_api_app(settings: MiniAppSettings, *, runner=None, limiter=None, clock=time.time,
                  service=None, writer=None, market=None, admin=None, team=None) -> web.Application:
    api = web.Application(middlewares=[api_middleware])
    runner = runner or ReadOnlyRunner(
        statement_timeout_ms=settings.db_statement_timeout_ms,
        max_inflight=settings.max_inflight_db,
        queue_wait_seconds=settings.db_queue_wait_seconds,
        max_queue=settings.db_max_queue)
    api[_K_SETTINGS] = settings
    api[_K_SERVICE] = service or MiniAppService(settings, runner)
    api[_K_LIMITER] = limiter or StrictLimiter(require_shared=settings.rate_require_shared,
                                       max_concurrency=settings.rate_redis_concurrency)
    api[_K_CLOCK] = clock
    api[_K_WRITER] = writer or PostWriter(api[_K_SERVICE], settings)
    api[_K_MARKET] = market or MarketApi(api[_K_SERVICE], settings)
    api[_K_ADMIN] = admin or AdminApi(api[_K_SERVICE], settings)
    api[_K_TEAM] = team or TeamApi(api[_K_SERVICE], settings)

    async def _close_writer(app: web.Application) -> None:
        closer = getattr(app[_K_WRITER], "aclose", None)  # sinov uchun almashtirilgan writer'da bo'lmasligi mumkin
        if closer is not None:
            await closer()
        for key in (_K_MARKET, _K_ADMIN, _K_TEAM):
            closer2 = getattr(app[key], "aclose", None)
            if closer2 is not None:
                await closer2()

    api.on_cleanup.append(_close_writer)
    api.router.add_get("/health", health_handler)
    api.router.add_get("/me", me_handler)
    api.router.add_get("/channels", channels_handler)
    api.router.add_get("/channels/{channel_id}/analytics", channel_analytics_handler)
    api.router.add_get("/scheduled-posts", scheduled_handler)
    api.router.add_get("/scheduled-posts/calendar", calendar_handler)
    api.router.add_get("/posts/{post_id}", post_detail_handler)
    api.router.add_get("/draft", draft_handler)
    api.router.add_get("/draft/media", draft_media_handler)
    api.router.add_post("/draft/media", draft_media_upload_handler)
    api.router.add_delete("/draft/media", draft_media_delete_handler)
    api.router.add_delete("/draft", draft_delete_handler)
    api.router.add_post("/posts", post_create_handler)
    api.router.add_patch("/posts/{post_id}", post_update_handler)
    api.router.add_get("/posts/{post_id}/media", post_media_handler)
    api.router.add_post("/posts/{post_id}/media", post_media_upload_handler)
    api.router.add_delete("/posts/{post_id}/media", post_media_delete_handler)
    api.router.add_delete("/posts/{post_id}", post_delete_handler)
    api.router.add_patch("/me/settings", settings_update_handler)
    api.router.add_post("/ai/generate", ai_generate_handler)
    api.router.add_post("/schedule/parse", schedule_parse_handler)
    api.router.add_get("/templates", templates_handler)
    api.router.add_post("/templates", template_create_handler)
    api.router.add_delete("/templates/{template_id}", template_delete_handler)
    api.router.add_get("/market/summary", market_summary_handler)
    api.router.add_get("/market/listings", market_catalog_handler)
    api.router.add_get("/market/listings/{item_id}", market_listing_handler)
    api.router.add_post("/market/listings/{item_id}/inquiries", market_inquire_handler)
    api.router.add_post("/market/listings/{item_id}/report", market_report_handler)
    api.router.add_get("/market/mine", market_mine_handler)
    api.router.add_post("/market/mine", market_publish_handler)
    api.router.add_patch("/market/mine/{item_id}", market_update_handler)
    api.router.add_post("/market/mine/{item_id}/refresh", market_refresh_handler)
    api.router.add_delete("/market/mine/{item_id}", market_delete_handler)
    api.router.add_get("/market/threads", market_threads_handler)
    api.router.add_get("/market/threads/{item_id}", market_thread_handler)
    api.router.add_post("/market/threads/{item_id}/messages", market_reply_handler)
    api.router.add_post("/market/threads/{item_id}/close", market_close_handler)
    api.router.add_post("/market/threads/{item_id}/block", market_block_handler)
    api.router.add_post("/market/threads/{item_id}/report", market_report_user_handler)
    api.router.add_get("/market/unread", market_unread_handler)
    api.router.add_get("/admin/overview", admin_overview_handler)
    api.router.add_get("/admin/ads", admin_ads_handler)
    api.router.add_patch("/admin/ads/settings", admin_ad_settings_handler)
    api.router.add_post("/admin/ads", admin_ad_create_handler)
    api.router.add_patch("/admin/ads/{item_id}", admin_ad_update_handler)
    api.router.add_delete("/admin/ads/{item_id}", admin_ad_delete_handler)
    api.router.add_get("/admin/sponsors", admin_sponsors_handler)
    api.router.add_post("/admin/sponsors", admin_sponsor_add_handler)
    api.router.add_delete("/admin/sponsors/{item_id}", admin_sponsor_delete_handler)
    api.router.add_get("/admin/market", admin_market_handler)
    api.router.add_post("/admin/market/listings/{item_id}/status", admin_market_status_handler)
    api.router.add_post("/admin/market/users/{item_id}/ban", admin_market_ban_handler)
    api.router.add_get("/team", team_handler)
    api.router.add_get("/team/people", team_people_handler)
    api.router.add_patch("/team/mode", team_mode_handler)
    api.router.add_post("/team/invites", team_invite_create_handler)
    api.router.add_delete("/team/invites/{item_id}", team_invite_delete_handler)
    api.router.add_patch("/team/members", team_member_update_handler)
    api.router.add_patch("/team/helpers", team_helper_update_handler)
    api.router.add_post("/team/members/remove", team_member_remove_handler)
    api.router.add_post("/team/leave", team_leave_handler)
    api.router.add_get("/admin/promos", admin_promos_handler)
    api.router.add_post("/admin/promos", admin_promo_create_handler)
    api.router.add_get("/admin/promos/{code}", admin_promo_detail_handler)
    api.router.add_patch("/admin/promos/{code}", admin_promo_active_handler)
    api.router.add_post("/admin/grant", admin_grant_handler)
    api.router.add_get("/admin/audit", admin_audit_handler)
    api.router.add_get("/admin/features", admin_features_handler)
    api.router.add_get("/admin/system", admin_health_handler)
    api.router.add_get("/admin/roles", admin_roles_handler)
    api.router.add_post("/admin/roles", admin_role_set_handler)
    return api


async def _api_not_found(request: web.Request):
    # /api/v1 tashqarisidagi /api/* yo'llari uchun JSON 404 (HTML emas).
    request_id = uuid.uuid4().hex[:16]
    return error_response(ApiError("not_found"), request_id=request_id,
                          lang=pick_lang(request.headers.get("Accept-Language")))


def register_miniapp_routes(app: web.Application, *, env=None, **overrides) -> bool:
    """Mini App marshrutlarini ulaydi. Ulangan bo'lsa ``True``."""
    settings = load_settings(env)
    if not settings.enabled:
        return False
    if settings.config_errors:
        logger.error("Mini App ULANMADI (xavfsiz konfiguratsiya emas): %s",
                     "; ".join(settings.config_errors))
        return False
    app.add_subapp(API_PREFIX, build_api_app(settings, **overrides))
    app.router.add_route("*", "/api/{tail:.*}", _api_not_found)
    register_static_routes(app, settings.dist_dir)
    if not os.path.isfile(os.path.join(settings.dist_dir, "index.html")):
        # /app/ shunda 404 beradi: frontend build image'ga tushmagan (Docker runtime kerak).
        logger.error("Mini App: %s/index.html TOPILMADI — /app/ 404 beradi "
                     "(Dockerfile orqali build qiling yoki MINIAPP_DIST_DIR ni belgilang)",
                     settings.dist_dir)
    logger.info("Mini App marshrutlari ulandi (%s, /app)", API_PREFIX)
    return True
