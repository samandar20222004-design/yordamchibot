#!/usr/bin/env python3
"""scripts/miniapp_initdata_smoke.py — natija mantiqi va MAXFIYLIK testi (soxta token)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, REPO, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — initData SMOKE VOSITASI")
spec = importlib.util.spec_from_file_location("smoke", REPO / "scripts" / "miniapp_initdata_smoke.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def run(data, token=FAKE_TOKEN):
    lines = []
    code = smoke.run(data, token, now=NOW, out=lines.append)
    return code, "\n".join(lines)


def main() -> int:
    good = make_init_data(8123, extra={"signature": "SIGVALUE_abc-123"})
    code, out = run(good)
    T.check("to'g'ri initData -> kod 0", code == 0)
    T.check("signature bilan hash mos", "BILAN, server qoidasi): True" in out)
    T.check("signature'siz hisob mos EMAS (diagnostika)", "qabul qilinmaydi): False" in out)

    code, out = run(good, "987654321:OTHERtokenZZZZZZZZZZZZZZZZZZZZZZ")
    T.check("boshqa token -> rad (kod 1)", code == 1 and "RAD (unauthorized)" in out)
    code, out = run(make_init_data(1, auth_date=NOW - 7200))
    T.check("eskirgan -> rad auth_expired", code == 1 and "auth_expired" in out)
    code, _ = run("garbage")
    T.check("yaroqsiz kiritma -> kod 1", code == 1)
    code, out = run(good, "bad token")
    T.check("yaroqsiz token formati -> kod 2", code == 2)

    # MAXFIYLIK: chiqishda token, hash, signature, user qiymatlari bo'lmasin
    all_out = "\n".join(run(good)[1:] + run(good, "987654321:OTHERtokenZZZZZZZZZZZZZZZZZZZZZZ")[1:]
                        + run(good, "bad token")[1:])
    hash_value = good.rsplit("hash=", 1)[1]
    for label, secret in (("token", FAKE_TOKEN), ("hash", hash_value),
                          ("signature", "SIGVALUE_abc-123"), ("user.id", "8123"),
                          ("query_id", "AAHdF6IQAAAAAN0XohDhrOrc")):
        T.check(f"chiqishda {label} yo'q", secret not in all_out)
    src = (REPO / "scripts" / "miniapp_initdata_smoke.py").read_text()
    T.check("vosita faylga yozmaydi", "write_text" not in src and "open(" not in src)
    # --api rejimi: lokal aiohttp serveriga qarshi (haqiqiy tarmoq YO'Q)
    import asyncio
    import threading

    from aiohttp import web

    seen = {}

    async def me(request):
        seen["auth"] = request.headers.get("Authorization", "")
        if seen["auth"].startswith("tma ") and "good" in seen["auth"]:
            return web.json_response({"user": {"id": 1, "name": "SECRET-NAME"}, "plan": {}})
        return web.json_response({"error": {"code": "unauthorized", "message": "x"}}, status=401)

    loop = asyncio.new_event_loop()
    app = web.Application()
    app.router.add_get("/api/v1/me", me)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    site = web.TCPSite(runner, "127.0.0.1", 0)
    loop.run_until_complete(site.start())
    port = site._server.sockets[0].getsockname()[1]
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}/api/v1"
        lines = []
        rc = smoke.probe_api("auth_date=1&hash=good", base, out=lines.append)
        T.check("--api: HTTP 200 -> kod 0, faqat javob KALITLARI chop etiladi", rc == 0 and "plan, user" in lines[0])
        T.check("--api: javob QIYMATLARI (ism) chop etilmaydi", "SECRET-NAME" not in "".join(lines))
        T.check("--api: Authorization 'tma <initData>' yuborildi", seen["auth"] == "tma auth_date=1&hash=good")
        lines = []
        rc = smoke.probe_api("auth_date=1&hash=bad", base, out=lines.append)
        T.check("--api: 401 -> kod 1, xato KODI chop etiladi, initData chop etilmaydi",
                rc == 1 and "unauthorized" in lines[0] and "hash=bad" not in "".join(lines))
        lines = []
        T.check("--api: http:// (lokal bo'lmagan) manzil rad (kod 2)",
                smoke.probe_api("x", "http://example.com/api/v1", out=lines.append) == 2)
        T.check("--api: ulanib bo'lmasa kod 1, URL/sarlavha chop etilmaydi",
                smoke.probe_api("tma-secret-initdata", "http://127.0.0.1:1/api/v1", out=lines.append) == 1
                and "tma-secret-initdata" not in "".join(lines))
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.run_until_complete(runner.cleanup())
        loop.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
