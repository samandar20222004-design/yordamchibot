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
from datetime import datetime, timedelta, timezone

from aiohttp import web

from .auth import AuthError, parse_authorization, validate_init_data
from .db import ReadOnlyRunner
from .errors import ApiError, error_response, pick_lang
from .proxy import resolve_client
from .ratelimit import StrictLimiter
from .repository import MAX_OFFSET
from .service import MiniAppService
from .settings import MiniAppSettings, load_settings
from .static import register_static_routes
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


async def channels_handler(request: web.Request):
    data = await request.app[_K_SERVICE].channels(request["user_id"])
    return web.json_response(data)


def _channel_id(request: web.Request) -> str:
    raw = request.match_info.get("channel_id", "")
    if not _CHANNEL_ID_RE.match(raw):
        raise ApiError("not_found")
    return raw


async def channel_analytics_handler(request: web.Request):
    data = await request.app[_K_SERVICE].channel_analytics(request["user_id"], _channel_id(request))
    return web.json_response(data, headers={"Cache-Control": "no-store"})


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


async def calendar_handler(request: web.Request):
    start = _parse_instant(request.query.get("from"))
    end = _parse_instant(request.query.get("to"))
    if not start < end or end - start > timedelta(days=_CALENDAR_MAX_DAYS):
        raise ApiError("bad_request")
    data = await request.app[_K_SERVICE].calendar(request["user_id"], start, end)
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def post_detail_handler(request: web.Request):
    data = await request.app[_K_SERVICE].post(request["user_id"], _post_id(request))
    return web.json_response({"post": data})


async def draft_handler(request: web.Request):
    data = await request.app[_K_SERVICE].draft(request["user_id"])
    return web.json_response(data, headers={"Cache-Control": "no-store"})


async def draft_media_handler(request: web.Request):
    data, mime = await request.app[_K_WRITER].draft_photo(request["user_id"])
    return web.Response(body=data, content_type=mime, headers={
        "Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'"})


@_write
async def draft_delete_handler(request: web.Request):
    data = await request.app[_K_WRITER].delete_draft(request["user_id"])
    return web.json_response(data)


@_write
async def post_create_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].create_post(request["user_id"], body)
    return web.json_response(data, status=201 if data["created"] else 200)


@_write
async def post_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].update_post(request["user_id"], _post_id(request), body)
    return web.json_response(data)


@_write
async def post_delete_handler(request: web.Request):
    data = await request.app[_K_WRITER].cancel_post(request["user_id"], _post_id(request))
    return web.json_response(data)


@_write
async def settings_update_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].set_language(request["user_id"], body)
    return web.json_response(data)


@_ai
async def ai_generate_handler(request: web.Request):
    body = await read_json_object(request, request.app[_K_SETTINGS].max_body_bytes)
    data = await request.app[_K_WRITER].ai_generate(request["user_id"], body)
    return web.json_response(data)


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

    timeout = settings.request_timeout_seconds
    if getattr(route_handler, "miniapp_write", False):
        await limiter.hit("write", str(verified.user_id), limit=settings.rate_write_limit,
                          window=settings.rate_write_window)
    if getattr(route_handler, "miniapp_ai", False):
        await limiter.hit("ai", str(verified.user_id), limit=settings.rate_ai_limit,
                          window=settings.rate_ai_window)
        timeout = max(timeout, settings.ai_timeout_seconds)
    return await asyncio.wait_for(handler(request), timeout)


# ------------------------------------------------------------ ulash nuqtasi
def build_api_app(settings: MiniAppSettings, *, runner=None, limiter=None, clock=time.time,
                  service=None, writer=None) -> web.Application:
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

    async def _close_writer(app: web.Application) -> None:
        closer = getattr(app[_K_WRITER], "aclose", None)  # sinov uchun almashtirilgan writer'da bo'lmasligi mumkin
        if closer is not None:
            await closer()

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
    api.router.add_delete("/draft", draft_delete_handler)
    api.router.add_post("/posts", post_create_handler)
    api.router.add_patch("/posts/{post_id}", post_update_handler)
    api.router.add_delete("/posts/{post_id}", post_delete_handler)
    api.router.add_patch("/me/settings", settings_update_handler)
    api.router.add_post("/ai/generate", ai_generate_handler)
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
