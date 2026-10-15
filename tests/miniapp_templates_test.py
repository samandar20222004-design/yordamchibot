#!/usr/bin/env python3
"""Mini App — shablonlar (`/templates`) va tozalagich (`POST /tools/clean`) (real PostgreSQL, faqat sinov bazasi).

* shablon: ro'yxat faqat o'zinikini ko'rsatadi, yaratish/takror/limit (20), o'chirish (IDOR: begona id -> 404), kirish validatsiyasi;
* tozalagich: oxirgi begona havola/reklama qatori olinadi, matn o'zgarmaydi, saqlangan imzo qo'shiladi, hech narsa yozilmaydi.
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_tpl")
if URL:
    os.environ["DATABASE_URL"] = URL

from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — shablonlar va tozalagich (real PostgreSQL)")
A, B = 9_200_000_021, 9_200_000_022


class NullLimiter:
    async def hit(self, *a, **k):
        return None


def main() -> int:
    if not URL:
        T.skip("real PostgreSQL shablon testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings
    from miniapp_api.writes import PostWriter

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def q(sql, params=()):
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except psycopg2.ProgrammingError:
            return []

    def cleanup():
        q("DELETE FROM post_templates WHERE user_id = ANY(%s)", ([A, B],))
        q("DELETE FROM users WHERE user_id = ANY(%s)", ([A, B],))

    settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                              "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    settings = dataclasses.replace(settings, db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner, invite_only_getter=lambda: False)
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW,
                               service=service, writer=PostWriter(service, settings))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    def call(method, path, uid=None, body=None):
        async def go():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                kw = {}
                if uid is not None:
                    kw["headers"] = {"Authorization": "tma " + make_init_data(uid)}
                if body is not None:
                    kw["json"] = body
                r = await client.request(method, path, **kw)
                try:
                    return r.status, await r.json()
                except Exception:  # noqa: BLE001
                    return r.status, None
            finally:
                await client.close()

        return loop.run_until_complete(go())

    cleanup()
    try:
        for uid in (A, B):
            q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,'uz','free')",
              (uid, f"t{uid}", f"N{uid}"))

        print("\n== 1. Shablonlar ==")
        st, b = call("GET", "/api/v1/templates", A)
        T.check("bo'sh ro'yxat, limit 20", st == 200 and b["items"] == [] and b["limit"] == 20, str(b))
        st, b = call("POST", "/api/v1/templates", A, {"name": "Salom", "text": "<b>Salom</b> dunyo"})
        tid = b.get("id")
        T.check("yaratildi (201)", st == 201 and b["created"] is True and isinstance(tid, int), f"{st} {b}")
        st, b2 = call("POST", "/api/v1/templates", A, {"name": "Salom", "text": "<b>Salom</b> dunyo"})
        T.check("aynan bir xil takror -> yangi qator yaratilmaydi (200, created=False)", st == 200 and b2["created"] is False and b2["id"] == tid, f"{st} {b2}")
        st, b = call("GET", "/api/v1/templates", A)
        T.check("ro'yxatda matn va nom bor", b["items"][0]["name"] == "Salom" and b["items"][0]["text"] == "<b>Salom</b> dunyo" and len(b["items"]) == 1, str(b))
        st, b = call("GET", "/api/v1/templates", B)
        T.check("B ning ro'yxati bo'sh (A shabloni ko'rinmaydi)", b["items"] == [], str(b))
        st, b = call("DELETE", f"/api/v1/templates/{tid}", B)
        T.check("IDOR: B A shablonini o'chira olmaydi (404), A'da qoladi", st == 404 and q("SELECT COUNT(*) FROM post_templates WHERE user_id=%s", (A,))[0][0] == 1, f"{st} {b}")
        st, _ = call("GET", "/api/v1/templates")
        T.check("autentifikatsiyasiz -> 401", st == 401)

        print("\n== 2. Validatsiya ==")
        for label, body in (("nom yo'q", {"text": "x"}), ("matn bo'sh", {"name": "n", "text": "  "}),
                            ("nom uzun", {"name": "n" * 65, "text": "x"}), ("matn uzun", {"name": "n", "text": "x" * 4097}),
                            ("ortiqcha maydon", {"name": "n", "text": "x", "admin": 1}), ("nom raqam", {"name": 5, "text": "x"})):
            st, b = call("POST", "/api/v1/templates", A, body)
            T.check(f"422 invalid_input: {label}", st == 422 and b["error"]["code"] == "invalid_input", f"{st} {b}")
        st, b = call("DELETE", "/api/v1/templates/abc", A)
        T.check("yaroqsiz id -> 404", st == 404)

        print("\n== 3. Limit (20) ==")
        for i in range(19):
            st, _ = call("POST", "/api/v1/templates", A, {"name": f"n{i}", "text": f"matn {i}"})
        T.check("jami 20 ta saqlandi", q("SELECT COUNT(*) FROM post_templates WHERE user_id=%s", (A,))[0][0] == 20)
        st, b = call("POST", "/api/v1/templates", A, {"name": "ortiqcha", "text": "yana"})
        T.check("21-chisi -> 403 templates_limit_reached, qator qo'shilmadi", st == 403 and b["error"]["code"] == "templates_limit_reached"
                and q("SELECT COUNT(*) FROM post_templates WHERE user_id=%s", (A,))[0][0] == 20, f"{st} {b}")
        st, b = call("DELETE", f"/api/v1/templates/{tid}", A)
        T.check("egasi o'chiradi (200), keyin yana qo'shsa bo'ladi", st == 200 and b["deleted"] is True
                and call("POST", "/api/v1/templates", A, {"name": "yangi", "text": "yangi"})[0] == 201)

        print("\n== 4. Tozalagich ==")
        st, b = call("POST", "/api/v1/tools/clean", A, {"text": "Asosiy matn\nReklama: t.me/spam\nObuna bo'ling @spam"})
        T.check("begona qatorlar olindi, asosiy matn qoldi, imzo yo'q", st == 200 and b["text"] == "Asosiy matn" and b["removed_lines"] == 2
                and b["has_signature"] is False and b["signature_added"] is False and b["changed"] is True, str(b))
        q("UPDATE users SET post_signature_html = %s WHERE user_id = %s", ('<a href="https://t.me/mening">Mening kanalim</a>', A))
        st, b = call("POST", "/api/v1/tools/clean", A, {"text": "<b>Muhim</b> xabar\nManba: t.me/boshqa"})
        T.check("format saqlandi + imzo qo'shildi", st == 200 and b["text"].startswith("<b>Muhim</b> xabar")
                and 'href="https://t.me/mening"' in b["text"] and b["signature_added"] and b["has_signature"], str(b))
        st, b2 = call("POST", "/api/v1/tools/clean", A, {"text": b["text"]})
        T.check("qayta tozalash natijani o'zgartirmaydi (idempotent, imzo bitta)", st == 200 and b2["text"].count("Mening kanalim") == 1 and b2["text"] == b["text"] and b2["changed"] is False, str(b2))
        st, b = call("POST", "/api/v1/tools/clean", B, {"text": "Matn\nt.me/spam"})
        T.check("B uchun A imzosi qo'shilmaydi", st == 200 and "mening" not in b["text"].lower() and b["has_signature"] is False, str(b))
        st, b = call("POST", "/api/v1/tools/clean", A, {"text": ""})
        T.check("bo'sh matn -> 422", st == 422)
        st, b = call("POST", "/api/v1/tools/clean", A, {"text": "x", "signature": "<b>o'zim</b>"})
        T.check("mijoz imzo yubora olmaydi (ortiqcha maydon -> 422)", st == 422)
        T.check("tozalash bazaga yozmadi (imzo o'zgarmagan)", q("SELECT post_signature_html FROM users WHERE user_id=%s", (A,))[0][0].startswith('<a href="https://t.me/mening"'))
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
