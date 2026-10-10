# -*- coding: utf-8 -*-
"""=====================================================================
 🧪 MOCK TELEGRAM BOT API SERVER — STAGING / LOAD SINOVLARI UCHUN
=====================================================================

Maqsad: yuklama (load), stress va chaos sinovlarida botni **haqiqiy
Telegram Bot API'ga hech qanday so'rov yubormasdan** to'liq tarmoq zanjiri
bilan sinash (PTB → HTTPX → HTTP → JSON).

Mock server Bot API'ning shimoli:
  * ``POST /bot<TOKEN>/<method>`` — barcha metodlar uchun umumiy handler
    (``sendMessage``, ``sendPhoto``, ``getUpdates``, ``deleteMessage``,
    ``answerCallbackQuery``, ``setMyCommands``, ``getMe``, ``setWebhook``,
    ``getWebhookInfo``, ``deleteWebhook`` ...);
  * ``GET  /__stats``  — to'plangan metrikalar (JSON): so'rovlar soni,
    metodlar kesimi, HTTP status gistogrammasi, latency p50/p95/p99;
  * ``POST /__reset``  — metrikalar va holatni nolga qaytarish;
  * ``POST /__inject_update`` — navbatga sun'iy update qo'yish (``getUpdates``
    shuni qaytaradi) — staging'da to'liq polling oqimini simulyatsiya qiladi;
  * ``POST /__fault``  — NOSOZLIK IN'YEKSIYASI (chaos):
      ``{"mode": "429"|"500"|"timeout"|"network"|"off", ...}``.

Xavfsizlik (fail-closed): modul ``ENVIRONMENT=production`` bo'lganda
ISHGA TUSHMAYDI — u faqat staging/development/test muhiti uchun. Production
bot API'ga to'g'ridan-to'g'ri murojaat qiladi (``TELEGRAM_API_BASE_URL``
bo'sh qoladi).

Ishga tushirish (staging, docker-compose.staging.yml ham shundan foydalanadi)::

    python -m staging.mock_telegram_server --port 8080

Testlarda (in-process, ayni event loop ichida)::

    server = await MockTelegramServer(port=0).start()
    base_url = server.base_url          # http://127.0.0.1:<port>/bot
    ...
    await server.stop()
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random  # noqa: F401
import statistics
import sys
import time
from typing import Any

logger = logging.getLogger("mock_telegram")

#: Mock server qaytaradigan maksimal update (cheksiz navbat o'sishining oldini
#: oladi — staging'da uzoq muddat ishlaganda ham xotira cheklangan qoladi).
MAX_QUEUED_UPDATES = 5000
#: Latency gistogrammasi uchun saqlanadigan so'nggi o'lchovlar soni.
MAX_LATENCY_SAMPLES = 20000


class MockTelegramState:
    """Mock server'ning umumiy holati va metrikalari (thread-safe emas —
    aiohttp bir event loop ichida ishlaydi)."""

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.message_id = 1000
        self.update_id = 0
        self.requests_total = 0
        self.methods: dict[str, int] = {}
        self.statuses: dict[str, int] = {}
        self.errors_429 = 0
        self.errors_5xx = 0
        self.latencies_ms: list[float] = []
        self.updates: list[dict] = []
        self.fault: dict[str, Any] = {"mode": "off"}
        self.sent_messages: dict[str, int] = {}
        self.deleted_messages = 0
        #: Oxirgi o'rnatilgan webhook manzili (``setWebhook`` → ``getWebhookInfo``
        #: → ``deleteWebhook`` kontraktini real sinash uchun).
        self.webhook_url: str = ""
        #: Oxirgi (sanitizatsiyadan o'tgan) matnlar — yuklama testlari bot
        #: yuborgan ANIQ matnni tekshirishi uchun (cheklangan uzunlikda).
        self.last_texts: list[str] = []

    # ---- metrikalar -------------------------------------------------
    def record(self, method: str, status: int, latency_ms: float) -> None:
        self.requests_total += 1
        self.methods[method] = self.methods.get(method, 0) + 1
        key = str(status)
        self.statuses[key] = self.statuses.get(key, 0) + 1
        if len(self.latencies_ms) < MAX_LATENCY_SAMPLES:
            self.latencies_ms.append(latency_ms)

    def percentiles(self) -> dict:
        samples = sorted(self.latencies_ms)
        if not samples:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0}
        def _pct(p: float) -> float:
            idx = min(len(samples) - 1, int(round(p / 100.0 * (len(samples) - 1))))
            return round(samples[idx], 3)
        return {
            "p50": _pct(50), "p95": _pct(95), "p99": _pct(99),
            "max": round(samples[-1], 3),
            "avg": round(statistics.fmean(samples), 3),
        }

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": round(time.monotonic() - self.started_at, 2),
            "requests_total": self.requests_total,
            "methods": dict(sorted(self.methods.items())),
            "statuses": dict(sorted(self.statuses.items())),
            "errors_429": self.errors_429,
            "errors_5xx": self.errors_5xx,
            "latency_ms": self.percentiles(),
            "queued_updates": len(self.updates),
            "fault": dict(self.fault),
            "sent_messages": dict(self.sent_messages),
            "deleted_messages": self.deleted_messages,
            "webhook_url": self.webhook_url,
        }

    def reset(self) -> None:
        self.requests_total = 0
        self.methods.clear()
        self.statuses.clear()
        self.errors_429 = 0
        self.errors_5xx = 0
        self.latencies_ms.clear()
        self.updates.clear()
        self.fault = {"mode": "off"}
        self.sent_messages.clear()
        self.deleted_messages = 0
        self.webhook_url = ""

    # ---- Bot API semantikasi ---------------------------------------
    def next_message_id(self) -> int:
        self.message_id += 1
        return self.message_id

    def enqueue_update(self, update: dict) -> int:
        self.update_id += 1
        update = dict(update or {})
        update.setdefault("update_id", self.update_id)
        if len(self.updates) >= MAX_QUEUED_UPDATES:
            self.updates.pop(0)
        self.updates.append(update)
        return int(update["update_id"])

    def take_updates(self, offset: int | None = None, limit: int = 100) -> list[dict]:
        if offset:
            self.updates = [u for u in self.updates if int(u.get("update_id", 0)) >= int(offset)]
        batch = self.updates[: max(1, min(int(limit or 100), 100))]
        self.updates = self.updates[len(batch):]
        return batch


def _message(chat_id: Any, text: str, message_id: int) -> dict:
    return {
        "message_id": message_id,
        "date": int(time.time()),
        "chat": {"id": chat_id, "type": "private"},
        "text": text,
    }


class MockTelegramServer:
    """aiohttp asosidagi mock Bot API (in-process yoki alohida jarayon)."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080,  # nosec B104 — bu bind emas: standart host parametri (staging mock server)
                 *, state: MockTelegramState | None = None) -> None:
        self.host = host
        self.port = int(port)
        self.state = state or MockTelegramState()
        self._runner = None

    # ---- to'liq URL ------------------------------------------------
    @property
    def base_url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "", "::") else self.host  # nosec B104 — bu bind emas: faqat URL uchun solishtirish
        return f"http://{host}:{self.port}/bot"

    @property
    def stats_url(self) -> str:
        host = "127.0.0.1" if self.host in ("0.0.0.0", "", "::") else self.host  # nosec B104 — bu bind emas: faqat URL uchun solishtirish
        return f"http://{host}:{self.port}/__stats"

    # ---- handlerlar -------------------------------------------------
    def _fault_mode(self, method: str) -> str:
        """Nosozlik in'yeksiyasi rejimi (``off`` | ``429`` | ``500`` |
        ``network`` | ``timeout``) — ``every``/``methods``/``times``
        filtrlari bilan.

        ``times=N`` — bir martalik in'yeksiya: xato faqat keyingi ``N`` ta
        so'rovga tegadi, so'ng rejim AVTOMATIK o'chadi (retry keyin muvaffaqiyatli
        bo'lishi kerak bo'lgan deterministik stsenariylar uchun).
        """
        fault = self.state.fault or {}
        mode = str(fault.get("mode") or "off")
        if mode == "off":
            return "off"
        methods = fault.get("methods")
        if methods and method not in methods:
            return "off"
        every = int(fault.get("every") or 1)
        if every > 1 and self.state.requests_total % every != 0:
            return "off"
        times = fault.get("times")
        if times is not None:
            remaining = int(times)
            if remaining <= 0:
                return "off"
            fault["times"] = remaining - 1
        return mode

    async def _handle_bot_api(self, request):
        from aiohttp import web

        started = time.perf_counter()
        token = request.match_info.get("token", "")
        method = request.match_info.get("method", "")
        if not token or not method:
            return web.json_response({"ok": False, "error_code": 404,
                                      "description": "Not Found"}, status=404)
        payload: dict[str, Any] = {}
        try:
            content_type = str(request.content_type or "")
            if content_type.startswith(("multipart/", "application/x-www-form-urlencoded")):
                # PTB (httpx) Bot API so'rovlarini form-encoded / multipart
                # yuboradi — `request.json()` bunday tanani O'QIMAYDI.
                form = await request.post()
                payload = {str(key): value for key, value in form.items()
                           if isinstance(value, str)}
            else:
                payload = await request.json()
        except Exception:
            payload = {}

        mode = self._fault_mode(method)
        fault = self.state.fault or {}
        if mode == "timeout":
            # Sekin javob: mijoz (PTB) read-timeout'da TimedOut oladi.
            await asyncio.sleep(float(fault.get("delay") or 30.0))
            mode = "off"
        if mode == "network":
            # Tarmoq uzilishi: ulanish javobsiz yopiladi (PTB → NetworkError).
            await asyncio.sleep(float(fault.get("delay") or 0.0))
            self.state.record(method, 0, (time.perf_counter() - started) * 1000)
            self.state.errors_5xx += 1
            request.transport.close()
            return web.Response(status=499)
        if mode == "429":
            retry_after = int(self.state.fault.get("retry_after") or 1)
            self.state.errors_429 += 1
            self.state.record(method, 429, (time.perf_counter() - started) * 1000)
            response = web.json_response(
                {"ok": False, "error_code": 429, "description":
                 f"Too Many Requests: retry after {retry_after}",
                 "parameters": {"retry_after": retry_after}},
                status=429,
            )
            response.headers["Retry-After"] = str(retry_after)
            return response
        if mode == "500":
            self.state.errors_5xx += 1
            self.state.record(method, 500, (time.perf_counter() - started) * 1000)
            return web.json_response(
                {"ok": False, "error_code": 500, "description": "Internal Server Error"},
                status=500,
            )

        delay_ms = float(fault.get("latency_ms") or 0.0)
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000.0)

        result = self._dispatch(method, payload)
        if result is None:
            self.state.record(method, 404, (time.perf_counter() - started) * 1000)
            return web.json_response(
                {"ok": False, "error_code": 404,
                 "description": f"Not Found: method not found ({method})"},
                status=404,
            )
        self.state.record(method, 200, (time.perf_counter() - started) * 1000)
        return web.json_response({"ok": True, "result": result})

    def _dispatch(self, method: str, payload: dict):
        """Bot API metodi → natija. Noma'lum metod → ``None`` (404)."""
        chat_id = payload.get("chat_id")
        if method == "getMe":
            return {"id": 777000, "is_bot": True, "first_name": "MockPostAssist",
                    "username": "mock_postassist_bot", "can_join_groups": True,
                    "can_read_all_group_messages": False, "supports_inline_queries": False}
        if method == "getUpdates":
            return self.state.take_updates(payload.get("offset"), payload.get("limit", 100))
        if method in ("sendMessage", "sendPhoto", "sendVideo", "sendAnimation",
                      "sendDocument", "sendAudio", "sendVoice", "sendSticker",
                      "editMessageText", "editMessageCaption", "editMessageMedia"):
            mid = self.state.next_message_id()
            text = str(payload.get("text") or payload.get("caption") or "")
            self.state.last_texts.append(text)
            del self.state.last_texts[:-200]   # xotira chegarasi
            if chat_id is not None:
                key = str(chat_id)
                self.state.sent_messages[key] = self.state.sent_messages.get(key, 0) + 1
            return _message(chat_id, text, mid)
        if method == "sendMediaGroup":
            return [_message(chat_id, "", self.state.next_message_id())
                    for _ in (payload.get("media") or [{}])]
        if method == "deleteMessage":
            self.state.deleted_messages += 1
            return True
        if method == "answerCallbackQuery":
            return True
        if method == "setWebhook":
            self.state.webhook_url = str(payload.get("url") or "")
            return True
        if method == "deleteWebhook":
            self.state.webhook_url = ""
            return True
        if method == "getWebhookInfo":
            return {"url": self.state.webhook_url, "has_custom_certificate": False,
                    "pending_update_count": len(self.state.updates),
                    "max_connections": 40, "allowed_updates": None}
        if method in ("setMyCommands", "sendChatAction", "deleteMessage",
                      "close", "logOut",
                      "getChat", "getChatMember", "leaveChat",
                      "pinChatMessage", "unpinChatMessage",
                      "setChatMenuButton", "promoteChatMember",
                      "restrictChatMember", "getMyCommands", "getFile"):
            if method == "getChat":
                return {"id": chat_id, "type": "private"}
            if method == "getChatMember":
                return {"status": "administrator", "user": {"id": 1, "is_bot": False,
                                                            "first_name": "Admin"}}
            if method == "getFile":
                return {"file_id": payload.get("file_id") or "mock_file",
                        "file_unique_id": "mock_unique", "file_size": 128}
            return True
        # Test/telemetriya uchun ochiq "echo" metodi.
        if method == "mockEcho":
            return {"echo": payload}
        return None

    async def _handle_stats(self, request):
        from aiohttp import web
        return web.json_response(self.state.snapshot())

    async def _handle_reset(self, request):
        from aiohttp import web
        self.state.reset()
        return web.json_response({"ok": True})

    async def _handle_inject_update(self, request):
        from aiohttp import web
        try:
            update = await request.json()
        except Exception:
            update = {}
        update_id = self.state.enqueue_update(update or {})
        return web.json_response({"ok": True, "update_id": update_id})

    async def _handle_fault(self, request):
        from aiohttp import web
        try:
            fault = await request.json()
        except Exception:
            fault = {}
        if not isinstance(fault, dict):
            fault = {}
        allowed = {"mode", "every", "times", "retry_after", "latency_ms",
                   "methods", "delay"}
        self.state.fault = {k: v for k, v in fault.items() if k in allowed}
        self.state.fault.setdefault("mode", "off")
        return web.json_response({"ok": True, "fault": dict(self.state.fault)})

    def build_app(self):
        from aiohttp import web

        app = web.Application(client_max_size=8 * 1024 * 1024)
        app.router.add_get("/__stats", self._handle_stats)
        app.router.add_get("/__health", lambda r: web.json_response({"status": "ok"}))
        app.router.add_post("/__reset", self._handle_reset)
        app.router.add_post("/__inject_update", self._handle_inject_update)
        app.router.add_post("/__fault", self._handle_fault)
        app.router.add_route("*", "/bot{token}/{method}", self._handle_bot_api)
        app.router.add_route("*", "/bot{token}/{method}/", self._handle_bot_api)
        return app

    async def start(self) -> "MockTelegramServer":
        from aiohttp import web

        runner = web.AppRunner(self.build_app())
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner
        # port=0 → OS bo'sh portni beradi; haqiqiy portni aniqlaymiz.
        server = getattr(site, "_server", None)
        if server is not None and getattr(server, "sockets", None):
            try:
                self.port = int(server.sockets[0].getsockname()[1])
            except Exception:
                pass
        logger.info("Mock Telegram server: %s", self.base_url)
        return self

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def snapshot(self) -> dict:
        return self.state.snapshot()


def production_guard() -> None:
    """Fail-closed: mock server production'da ishga tushmaydi."""
    env = (os.getenv("ENVIRONMENT", "") or "").strip().lower()
    if env in ("production", "prod"):
        raise SystemExit(
            "Mock Telegram server PRODUCTION muhitida ishga tushmaydi "
            "(ENVIRONMENT=production). Bu faqat staging/test uchun."
        )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """CLI argumentlari (env o'qilmaydi — staging sozlamasi faqat buyruq satrida,
    shu sababli production `.env` namunasi staging kalitlari bilan ifloslanmaydi)."""
    parser = argparse.ArgumentParser(description="Mock Telegram Bot API server (staging)")
    parser.add_argument("--host", default="0.0.0.0",  # nosec B104 — staging konteyner tarmog'i uchun ataylab (argparse standarti)
                        help="Bind manzili (standart: 0.0.0.0 — konteyner tarmog'i)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Bind porti (standart: 8080)")
    return parser.parse_args(argv)


async def _serve_forever(args: argparse.Namespace) -> None:
    server = await MockTelegramServer(host=args.host, port=args.port).start()
    print(json.dumps({"event": "mock_telegram_started", "base_url": server.base_url}),
          flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await server.stop()


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    production_guard()
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        asyncio.run(_serve_forever(args))
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
