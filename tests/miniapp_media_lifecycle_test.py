#!/usr/bin/env python3
"""AUDIT-014: rasm olish uchun PTB `Bot` har so'rovda yangi yaratilmaydi (HTTP client oqib ketmaydi) va ilova
to'xtaganda yopiladi. AUDIT-013: frontend/backend/scheduler limit konstantalari mos (kontrakt testi). DB talab qilinmaydi."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "telegram_bot"))
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

T = Counter("MINI APP: media Bot lifecycle + limit kontrakti")
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class StubBot:
    created = 0

    def __init__(self):
        StubBot.created += 1
        self.init_calls = self.shutdown_calls = 0
        self.files = 0

    async def initialize(self):
        await asyncio.sleep(0.01)  # parallel chaqiruvlar poygasini ochish uchun
        self.init_calls += 1

    async def shutdown(self):
        self.shutdown_calls += 1

    async def get_file(self, file_id):
        self.files += 1

        async def download_as_bytearray():
            return bytearray(JPEG)

        return SimpleNamespace(file_size=len(JPEG), download_as_bytearray=download_as_bytearray)


async def lifecycle():
    from aiohttp import web
    from aiohttp.test_utils import TestServer

    from miniapp_api import app as appmod
    from miniapp_api.settings import load_settings
    from miniapp_api.writes import PostWriter, default_media_fetch

    fetcher = default_media_fetch(FAKE_TOKEN, bot_factory=StubBot)
    results = await asyncio.gather(*[fetcher(f"F{i}") for i in range(5)])
    T.check("5 PARALLEL rasm olish: faqat BITTA Bot yaratildi", StubBot.created == 1, str(StubBot.created))
    T.check("Bot AYNAN 1 marta initialize qilindi", fetcher._bot.init_calls == 1)
    T.check("barcha so'rovlar bayt qaytardi", all(r == JPEG for r in results))
    for i in range(3):
        await fetcher(f"G{i}")
    T.check("keyingi so'rovlar ham o'sha Bot'dan (yangi Bot yo'q)", StubBot.created == 1 and fetcher._bot.files == 8)
    bot = fetcher._bot
    await fetcher.aclose()
    T.check("aclose: Bot.shutdown chaqirildi (HTTP client yopildi)", bot.shutdown_calls == 1)
    await fetcher.aclose()
    T.check("aclose takror chaqirilsa xavfsiz (qayta shutdown yo'q)", bot.shutdown_calls == 1)
    await fetcher("H")
    T.check("yopilgandan keyin yangi so'rov yangi Bot oladi (xatosiz)", StubBot.created == 2)
    await fetcher.aclose()

    # ilova to'xtaganda writer.aclose -> Bot yopiladi
    settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                              "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    fetch2 = default_media_fetch(FAKE_TOKEN, bot_factory=StubBot)
    service = SimpleNamespace()
    writer = PostWriter(service, settings, media_fetch=fetch2)
    api = appmod.build_api_app(settings, service=service, writer=writer)
    root = web.Application()
    root.add_subapp(appmod.API_PREFIX, api)
    server = TestServer(root)
    await server.start_server()
    await fetch2("X")
    bot2 = fetch2._bot
    await server.close()
    T.check("ilova to'xtaganda (on_cleanup) rasm Bot'i yopildi", bot2.shutdown_calls == 1, str(bot2.shutdown_calls))

    # sinov uchun almashtirilgan (aclose'siz) writer ilova to'xtashini buzmaydi
    class PlainWriter:
        pass

    api2 = appmod.build_api_app(settings, service=service, writer=PlainWriter())
    root2 = web.Application()
    root2.add_subapp(appmod.API_PREFIX, api2)
    server2 = TestServer(root2)
    await server2.start_server()
    try:
        await server2.close()
        T.check("aclose'siz writer: to'xtash xatosiz", True)
    except Exception as exc:  # noqa: BLE001
        T.check("aclose'siz writer: to'xtash xatosiz", False, repr(exc))


def contract():
    from miniapp_api import writes
    from scheduler import TELEGRAM_CAPTION_LIMIT

    cfg = (ROOT / "miniapp/src/config.ts").read_text(encoding="utf-8")

    def fe(name):
        m = re.search(rf"{name}:\s*(\d[\d_]*)", cfg)
        return int(m.group(1).replace("_", "")) if m else None

    T.check("frontend maxPostChars == backend MAX_POST_CHARS", fe("maxPostChars") == writes.MAX_POST_CHARS)
    T.check("frontend maxCaptionChars == backend MAX_CAPTION_CHARS == scheduler TELEGRAM_CAPTION_LIMIT (1024)",
            fe("maxCaptionChars") == writes.MAX_CAPTION_CHARS == TELEGRAM_CAPTION_LIMIT == 1024,
            f"{fe('maxCaptionChars')} {writes.MAX_CAPTION_CHARS} {TELEGRAM_CAPTION_LIMIT}")
    T.check("frontend maxButtonTextChars == backend MAX_BUTTON_TEXT", fe("maxButtonTextChars") == writes.MAX_BUTTON_TEXT == 64)
    T.check("frontend maxButtonUrlChars == backend MAX_BUTTON_URL", fe("maxButtonUrlChars") == writes.MAX_BUTTON_URL == 2000)
    from utils.helpers import validate_button_url

    ok, _ = validate_button_url("https://example.org/" + "a" * (writes.MAX_BUTTON_URL - len("https://example.org/")))
    T.check("Mini App URL chegarasi botning umumiy validatori (<=2048) ichida", ok)
    # backend: sarlavha chegarasi
    try:
        writes.check_caption("a" * 1024)
        writes.check_caption("😀" * 512)  # 512 * 2 = 1024 UTF-16 birlik
        ok1 = True
    except Exception:  # noqa: BLE001
        ok1 = False
    T.check("check_caption: 1024 UTF-16 birlik o'tadi", ok1)
    for bad, name in (("a" * 1025, "1025 belgi"), ("😀" * 513, "513 emoji (1026 UTF-16)")):
        try:
            writes.check_caption(bad)
            T.check(f"check_caption: {name} rad", False)
        except writes.ApiError as exc:
            T.check(f"check_caption: {name} rad (caption_too_long, field=text)", exc.code == "caption_too_long" and exc.field == "text" and exc.status == 422)


def main() -> int:
    asyncio.run(lifecycle())
    contract()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
