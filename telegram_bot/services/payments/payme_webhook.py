"""Lightweight aiohttp endpoint for Payme Merchant API callbacks.

``POST /payments/payme`` — mounted on the existing health web server
(``utils.web_server.start_web_server``), so no extra port or framework is
needed. Behaviour follows the Payme protocol:

* every answer is HTTP 200 with a JSON-RPC body (Payme treats non-200 as a
  transport failure and keeps retrying);
* non-POST → ``-32300``; oversized/invalid JSON → ``-32600`` / ``-32700``;
  wrong/missing Basic Auth → ``-32504`` (checked before any DB access);
* the synchronous provider (psycopg2) runs in a worker thread so the event
  loop — and the bot — never block;
* after a successful ``PerformTransaction`` the user is notified in Telegram
  (best-effort, post-commit; a notification failure never affects Payme).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

from aiohttp import web

from services.payments.payme_provider import (
    ERR_INVALID_REQUEST,
    ERR_PARSE,
    ERR_TRANSPORT,
    PaymeError,
    PaymeEvent,
    PaymeProvider,
    error_response,
)

logger = logging.getLogger(__name__)

PAYME_WEBHOOK_PATH = "/payments/payme"
#: Payme requests are tiny (< 2 KB); anything bigger is rejected unread.
MAX_BODY_BYTES = 64 * 1024

PaidNotifier = Callable[[PaymeEvent], Awaitable[None]]

_provider: PaymeProvider | None = None
_notifier: PaidNotifier | None = None
_background_tasks: set[asyncio.Task] = set()


def get_provider() -> PaymeProvider:
    global _provider
    if _provider is None:
        _provider = PaymeProvider()
    return _provider


def set_provider(provider: PaymeProvider | None) -> None:
    """Override the provider (tests / alternative stores)."""
    global _provider
    _provider = provider


def set_paid_notifier(notifier: PaidNotifier | None) -> None:
    """Register the coroutine that tells the user their PRO is active."""
    global _notifier
    _notifier = notifier


def _json(body: dict) -> web.Response:
    return web.json_response(
        body,
        status=200,
        dumps=lambda obj: json.dumps(obj, ensure_ascii=False),
        headers={"Cache-Control": "no-store"},
    )


async def _read_body(request) -> bytes:
    if request.content_length is not None and request.content_length > MAX_BODY_BYTES:
        raise PaymeError(ERR_INVALID_REQUEST)
    body = await request.content.read(MAX_BODY_BYTES + 1)
    if len(body) > MAX_BODY_BYTES:
        raise PaymeError(ERR_INVALID_REQUEST)
    return body


def _schedule_notifications(events: list[PaymeEvent]) -> None:
    notifier = _notifier
    if notifier is None:
        return
    for event in events:
        if event.kind != "paid":
            continue

        async def _notify(ev: PaymeEvent = event) -> None:
            try:
                await notifier(ev)
            except Exception:  # noqa: BLE001 — never affects the payment
                logger.warning("Payme paid-notification failed", exc_info=True)

        task = asyncio.create_task(_notify())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def payme_webhook_handler(request) -> web.Response:
    if request.method != "POST":
        return _json(error_response(None, PaymeError(ERR_TRANSPORT)))
    try:
        raw = await _read_body(request)
    except PaymeError as exc:
        return _json(error_response(None, exc))
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _json(error_response(None, PaymeError(ERR_PARSE)))

    provider = get_provider()
    outcome = await asyncio.to_thread(
        provider.handle, payload, authorization=request.headers.get("Authorization"),
    )
    _schedule_notifications(outcome.events)
    return _json(outcome.response)


def register_payme_routes(app: web.Application) -> None:
    """Mount the endpoint (all methods → Payme-style ``-32300`` for non-POST)."""
    app.router.add_route("*", PAYME_WEBHOOK_PATH, payme_webhook_handler)


def build_bot_notifier(bot) -> PaidNotifier:
    """Telegram notifier: localized "PRO activated" message to the payer."""

    async def _notify(event: PaymeEvent) -> None:
        import database as db
        from locales.translations import get_text

        try:
            lang = await db.run_db(db.get_user_language, int(event.user_id))
        except Exception:  # noqa: BLE001
            lang = "uz"
        await bot.send_message(
            chat_id=int(event.user_id),
            text=get_text("payme_paid_notice", lang or "uz", days=int(event.days)),
            parse_mode="HTML",
        )

    return _notify


__all__ = [
    "MAX_BODY_BYTES",
    "PAYME_WEBHOOK_PATH",
    "build_bot_notifier",
    "get_provider",
    "payme_webhook_handler",
    "register_payme_routes",
    "set_paid_notifier",
    "set_provider",
]
