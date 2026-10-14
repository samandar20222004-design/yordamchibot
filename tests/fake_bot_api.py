"""Soxta Telegram Bot API serveri (lokal aiohttp) — HAQIQIY python-telegram-bot `Bot` obyekti bilan so'rovlarni tekshirish.

PTB `base_url` orqali shu serverga yo'naltiriladi: haqiqiy HTTP so'rov, PTB'ning haqiqiy serializatsiyasi va
javob tahlili ishlaydi; faqat Telegram o'zi soxta. (Haqiqiy Telegram'da ishlashining kafolati EMAS.)
"""
from __future__ import annotations

import json
import time

from aiohttp import web
from aiohttp.test_utils import TestServer

TOKEN = "123456789:FAKEtokenABCDEFGHIJKLMNOPQRSTUVW"


async def _read_body(request: web.Request) -> dict:
    """PTB so'rovni JSON yoki form/multipart ko'rinishida yuboradi; ichki JSON qiymatlar (reply_markup, media,
    menu_button) satr bo'lib keladi — ochib beramiz."""
    ctype = (request.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if ctype == "application/json":
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:  # noqa: BLE001
            return {}
    out: dict = {}
    try:
        form = await request.post()
    except Exception:  # noqa: BLE001
        return {}
    for key, value in form.items():
        if isinstance(value, str) and value[:1] in "{[":
            try:
                out[key] = json.loads(value)
                continue
            except ValueError:
                pass
        out[key] = value if isinstance(value, str) else "<file>"
    return out


class FakeBotApi:
    def __init__(self, *, fail_methods: dict | None = None):
        self.calls: list[tuple[str, dict]] = []
        self.fail_methods = dict(fail_methods or {})  # method -> (http_status, error_code, description)
        self._mid = 5000
        self.menu_button = {"type": "default"}
        self.server: TestServer | None = None

    async def _handle(self, request: web.Request) -> web.Response:
        method = request.match_info["method"]
        if request.match_info["token"] != TOKEN:
            return web.json_response({"ok": False, "error_code": 401, "description": "Unauthorized"}, status=401)
        body = await _read_body(request)
        self.calls.append((method, body))
        if method in self.fail_methods:
            status, code, desc = self.fail_methods[method]
            return web.json_response({"ok": False, "error_code": code, "description": desc}, status=status)
        return web.json_response({"ok": True, "result": self._result(method, body)})

    def _result(self, method: str, body: dict):
        chat_id = body.get("chat_id")
        if method == "getMe":
            return {"id": 123456789, "is_bot": True, "first_name": "Fake", "username": "fake_bot"}
        if method in ("sendMessage", "sendPhoto", "sendVideo", "sendDocument", "sendAnimation", "sendAudio", "sendVoice"):
            self._mid += 1
            msg = {"message_id": self._mid, "date": int(time.time()),
                   "chat": {"id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else 0, "type": "channel", "title": "Fake"}}
            if method == "sendMessage":
                msg["text"] = body.get("text", "")
            return msg
        if method == "sendMediaGroup":
            out = []
            for _ in body.get("media") or []:
                self._mid += 1
                out.append({"message_id": self._mid, "date": int(time.time()),
                            "chat": {"id": int(chat_id), "type": "channel", "title": "Fake"}})
            return out
        if method == "setChatMenuButton":
            self.menu_button = body.get("menu_button") or {"type": "default"}
            return True
        if method == "getChatMenuButton":
            return self.menu_button
        return True

    def calls_of(self, method: str) -> list[dict]:
        return [b for m, b in self.calls if m == method]

    async def start(self) -> str:
        app = web.Application()
        app.router.add_post("/bot{token}/{method}", self._handle)
        self.server = TestServer(app)
        await self.server.start_server()
        return f"http://127.0.0.1:{self.server.port}/bot"

    async def stop(self) -> None:
        if self.server:
            await self.server.close()
