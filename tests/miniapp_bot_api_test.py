#!/usr/bin/env python3
"""Telegram «Menu» tugmasi: HAQIQIY PTB `Bot` -> soxta Bot API serveri (haqiqiy HTTP va serializatsiya).

Tekshiriladi: `main.set_bot_commands` Mini App o'chiq bo'lsa `commands` tugmasini, yoqilgan + to'g'ri HTTPS
MINIAPP_URL bo'lsa `web_app` tugmasini yuboradi; yaroqsiz URL bo'lsa `commands` ga qaytadi; Telegram xato bersa bot
yiqilmaydi. Haqiqiy Telegram'da sinov uchun: scripts/miniapp_menu_smoke.py (test bot tokeni bilan, qo'lda).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_bot_api import TOKEN, FakeBotApi  # noqa: E402
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

T = Counter("MINI APP — «Menu» tugmasi (PTB Bot -> soxta Bot API)")
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

import main as bot_main  # noqa: E402
from telegram import Bot  # noqa: E402


def with_env(**env):
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    return saved


def restore(saved):
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


async def run_case(env, fail_methods=None):
    api = FakeBotApi(fail_methods=fail_methods)
    base = await api.start()
    bot = Bot(TOKEN, base_url=base)
    saved = with_env(**env)
    try:
        await bot.initialize()
        report = await bot_main.set_bot_commands(SimpleNamespace(bot=bot))
        return api, report
    finally:
        restore(saved)
        await bot.shutdown()
        await api.stop()


def run(coro):
    return LOOP.run_until_complete(coro)


def main() -> int:
    common = {"BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test", "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1"}
    api, report = run(run_case({**common, "MINIAPP_ENABLED": "0", "MINIAPP_URL": "https://bot.example.com/app/"}))
    btn = api.calls_of("setChatMenuButton")
    T.check("Mini App O'CHIQ: setChatMenuButton bir marta, turi 'commands'",
            len(btn) == 1 and btn[0]["menu_button"]["type"] == "commands", str(btn))
    T.check("set_my_commands ham yuborildi (bot menyusi o'zgarmagan)", len(api.calls_of("setMyCommands")) >= 1)
    T.check("hisobot: menu_button=True", report["menu_button"] is True)

    api, report = run(run_case({**common, "MINIAPP_ENABLED": "1", "MINIAPP_URL": "https://bot.example.com/app/"}))
    btn = api.calls_of("setChatMenuButton")
    mb = btn[0]["menu_button"] if btn else {}
    T.check("Mini App YOQILGAN + HTTPS URL: tugma turi 'web_app'", len(btn) == 1 and mb.get("type") == "web_app", str(btn))
    T.check("web_app.url aynan MINIAPP_URL", mb.get("web_app", {}).get("url") == "https://bot.example.com/app/")
    T.check("tugma matni 'PostAssist'", mb.get("text") == "PostAssist")
    T.check("hisobot: menu_button=True", report["menu_button"] is True)

    for bad in ("http://bot.example.com/app/", "javascript:alert(1)", "https://u:p@bot.example.com/", ""):
        api, _ = run(run_case({**common, "MINIAPP_ENABLED": "1", "MINIAPP_URL": bad}))
        btn = api.calls_of("setChatMenuButton")
        T.check(f"yaroqsiz URL {bad[:30]!r}: 'commands' ga qaytadi (web_app YO'Q)",
                len(btn) == 1 and btn[0]["menu_button"]["type"] == "commands")

    api, report = run(run_case({**common, "MINIAPP_ENABLED": "1", "MINIAPP_URL": "https://bot.example.com/app/"},
                               fail_methods={"setChatMenuButton": (400, 400, "Bad Request: invalid web app url")}))
    T.check("Telegram tugmani rad etsa: istisno ko'tarilmaydi, hisobot menu_button=False, bot davom etadi",
            report["menu_button"] is False and report["default"] is True, str(report))
    T.check("rad etilgan javob matni logga/xatoga sizmaydi (hisobot faqat bool)",
            all(isinstance(v, bool) for v in (report["default"], report["menu_button"])))
    # scripts/miniapp_menu_smoke.py — soxta Bot API'ga qarshi (haqiqiy Telegram EMAS)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "menu_smoke", Path(__file__).resolve().parent.parent / "scripts" / "miniapp_menu_smoke.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)

    async def smoke_case(url, keep=False, fail=None):
        api = FakeBotApi(fail_methods=fail)
        base = await api.start()
        lines = []
        try:
            rc = await smoke.run(TOKEN, url, keep=keep, api_base=base, out=lines.append)
        finally:
            await api.stop()
        return rc, lines, api

    rc, lines, api = run(smoke_case("https://bot.example.com/app/"))
    T.check("smoke: o'rnatadi, qaytarib o'qiydi, asl holatni tiklaydi (kod 0)",
            rc == 0 and any("moslik: OK" in x for x in lines) and api.menu_button.get("type") in ("default", "commands"), str(lines))
    rc, lines, api = run(smoke_case("https://bot.example.com/app/", keep=True))
    T.check("smoke --keep: tugma web_app bo'lib QOLADI", rc == 0 and api.menu_button.get("type") == "web_app")
    rc, lines, api = run(smoke_case("http://insecure.example.com/"))
    T.check("smoke: http:// URL rad (kod 2), Telegram'ga so'rov yuborilmadi", rc == 2 and api.calls_of("setChatMenuButton") == [])
    rc, lines, api = run(smoke_case("https://bot.example.com/app/", fail={"setChatMenuButton": (400, 400, "Bad Request: secret-detail")}))
    T.check("smoke: Telegram rad etsa kod 1; token va xato matni chop etilmaydi",
            rc == 1 and TOKEN not in "".join(lines) and "secret-detail" not in "".join(lines), str(lines))
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
