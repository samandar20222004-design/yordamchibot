"""Minimal web endpoints for liveness and authenticated readiness.

``/health/live`` is intentionally public and process-only. The readiness
handler is not an observability/metrics endpoint: it requires a dedicated
``HEALTH_READY_TOKEN`` bearer credential and returns only component status.
"""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime

import pytz
from aiohttp import web
from config import PORT

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")
START_TIME = datetime.now(tashkent_tz)
_READY_TOKEN_ENV_NAME = "HEALTH_READY_TOKEN"


def _expected_ready_token() -> str:
    """Read the independent readiness credential without logging it."""
    return (os.environ.get(_READY_TOKEN_ENV_NAME, "") or "").strip()


def _ready_request_authorized(request, expected: str) -> bool:
    if not expected:
        return False
    headers = getattr(request, "headers", {}) or {}
    authorization = str(headers.get("Authorization", "") or "").strip()
    provided = ""
    if authorization.lower().startswith("bearer "):
        provided = authorization[7:].strip()
    if not provided:
        provided = str(headers.get("X-Health-Token", "") or "").strip()
    try:
        return bool(provided) and hmac.compare_digest(provided, expected)
    except (TypeError, ValueError):
        return False


async def health_live_handler(request):
    """Liveness: process tirikligi — DB/Redis/scheduler'ga murojaat qilmaydi."""
    uptime = max(0.0, (datetime.now(tashkent_tz) - START_TIME).total_seconds())
    return web.json_response(
        {"status": "live", "service": "PostAssist Bot", "uptime_seconds": int(uptime)},
        status=200,
        headers={"Cache-Control": "no-store"},
    )


async def health_ready_handler(request):
    """Authenticated, internal readiness: DB pool, Redis ping, scheduler."""
    expected = _expected_ready_token()
    if not expected:
        # Fail closed if the operator has not provisioned the dedicated token.
        return web.json_response(
            {"status": "not_found"}, status=404,
            headers={"Cache-Control": "no-store"},
        )
    if not _ready_request_authorized(request, expected):
        return web.json_response(
            {"status": "unauthorized"}, status=401,
            headers={
                "Cache-Control": "no-store",
                "WWW-Authenticate": "Bearer",
            },
        )

    try:
        from services.health_service import get_readiness_status
        result = await get_readiness_status()
        status = 200 if result.get("ready") else 503
        # Deliberately return no counters, credentials, DSNs, provider names,
        # exception text, host information, or user-level data.
        payload = {
            "status": "ready" if result.get("ready") else "not_ready",
            "checks": dict(result.get("checks") or {}),
        }
        return web.json_response(
            payload, status=status, headers={"Cache-Control": "no-store"},
        )
    except Exception:
        logger.warning("Authenticated readiness check failed", extra={
            "event": "health_readiness_failed",
            "error_code": "READINESS_CHECK_FAILED",
        })
        return web.json_response(
            {"status": "not_ready", "checks": {
                "database": "error", "redis": "unavailable", "scheduler": "error",
            }}, status=503, headers={"Cache-Control": "no-store"},
        )


async def start_web_server():
    # A separately provisioned auth token should be scrubbed just like the
    # bot/provider credentials. No value is ever added to logs or responses.
    token = _expected_ready_token()
    if token:
        try:
            from utils.sentry_scrubber import register_secret
            register_secret(token, "HEALTH_READY_TOKEN")
        except Exception:
            pass

    app = web.Application()
    app.router.add_get("/", health_live_handler)
    app.router.add_get("/health", health_live_handler)
    app.router.add_get("/health/live", health_live_handler)
    app.router.add_get("/health/ready", health_ready_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info("Web server started", extra={
        "event": "web_server_started",
        "service": "health_endpoints",
        "port": PORT,
    })
    return runner
