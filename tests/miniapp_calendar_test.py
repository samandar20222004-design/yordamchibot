#!/usr/bin/env python3
"""Mini App — `GET /api/v1/scheduled-posts/calendar` (real PostgreSQL, faqat sinov bazasi).

Faqat egasining KUTILAYOTGAN postlari, [from, to) oralig'ida; zonasiz/yaroqsiz/katta oraliq -> 400; kesilsa `truncated`; o'qish yozmaydi.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_cal")
if URL:
    os.environ["DATABASE_URL"] = URL

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — kalendar (real PostgreSQL)")
A, B = 9_100_000_011, 9_100_000_012
CH_A, CH_B = "-1009100011", "-1009100012"


def main() -> int:
    if not URL:
        T.skip("real PostgreSQL analitika testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def run(coro):
        return loop.run_until_complete(coro)

    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()
    
    def cleanup():
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", ([A, B],))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", ([A, B],))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", ([A, B],))
        cur.execute("DELETE FROM system_settings WHERE key = 'beta_gate_state'")

    cleanup()
    try:
        for uid in (A, B):
            cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type) "
                        "VALUES (%s, %s, %s, 'uz', 'free')", (uid, f"u{uid}", f"Name{uid}"))
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES "
                    "(%s,%s,'Kanal A',TRUE),(%s,%s,'Kanal B',TRUE)", (A, CH_A, B, CH_B))
        base = datetime(2031, 3, 10, 12, 0, tzinfo=timezone.utc)

        def add(uid, ch, text, when, status="pending"):
            cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                        "VALUES (%s,%s,'text',%s,%s,%s)", (uid, ch, text, when, status))

        add(A, CH_A, "ichkarida-1", base)
        add(A, CH_A, "ichkarida-2", base + timedelta(days=3))
        add(A, CH_A, "chegara-to", base + timedelta(days=10))          # to = base+10d -> kirmaydi ([from, to))
        add(A, CH_A, "chegara-from", base - timedelta(days=5))          # from = base-5d -> kiradi
        add(A, CH_A, "tashqarida", base - timedelta(days=6))
        add(A, CH_A, "yuborilgan", base + timedelta(days=1), "posted")
        add(A, CH_A, "bekor", base + timedelta(days=2), "cancelled")
        add(B, CH_B, "B-SECRET", base + timedelta(days=1))

        settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
        runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4)
        service = MiniAppService(settings, runner, invite_only_getter=lambda: False)

        class Null:
            async def hit(self, *a, **k):
                return None

        api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service)
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)

        async def get(path, uid=A, auth=True):
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                headers = {"Authorization": "tma " + make_init_data(uid)} if auth else {}
                r = await client.get(path, headers=headers)
                return r.status, await r.json(), r.headers
            finally:
                await client.close()

        def q(frm, to):
            return f"/api/v1/scheduled-posts/calendar?from={frm.isoformat().replace('+00:00', 'Z')}&to={to.isoformat().replace('+00:00', 'Z')}"

        print("\n== 1. Oraliq va holat ==")
        st, d, h = run(get(q(base - timedelta(days=5), base + timedelta(days=10))))
        texts = [i["preview"] for i in d.get("items", [])]
        T.check("200; faqat 'pending', [from, to): chegara-from kiradi, chegara-to kirmaydi, tashqarida/yuborilgan/bekor yo'q",
                st == 200 and texts == ["chegara-from", "ichkarida-1", "ichkarida-2"], str(texts))
        T.check("vaqt bo'yicha o'sish tartibida, UTC ISO", d["items"][0]["scheduled_time"].endswith("+00:00") or d["items"][0]["scheduled_time"].endswith("Z"), str(d["items"][0]))
        T.check("truncated=False va no-store", d["truncated"] is False and h.get("Cache-Control") == "no-store")
        T.check("tahrirlash uchun kerakli maydonlar bor (id, channel_title, status, has_media)",
                all(k in d["items"][0] for k in ("id", "channel_title", "status", "has_media", "recurrence")), str(d["items"][0]))

        print("\n== 2. Xavfsizlik ==")
        T.check("B ning posti A javobida yo'q", "B-SECRET" not in json.dumps(d))
        st, d, _ = run(get(q(base - timedelta(days=5), base + timedelta(days=10)), B))
        T.check("B faqat o'zinikini ko'radi", [i["preview"] for i in d["items"]] == ["B-SECRET"], str(d))
        st, _, _ = run(get(q(base, base + timedelta(days=1)), auth=False))
        T.check("autentifikatsiyasiz -> 401", st == 401)

        print("\n== 3. Noto'g'ri kirish -> 400 ==")
        bad = [
            "/api/v1/scheduled-posts/calendar",
            "/api/v1/scheduled-posts/calendar?from=2031-03-10T00:00:00&to=2031-03-11T00:00:00",   # zonasiz
            "/api/v1/scheduled-posts/calendar?from=abc&to=def",
            q(base, base),                                                                        # bo'sh oraliq
            q(base + timedelta(days=1), base),                                                    # teskari
            q(base, base + timedelta(days=46)),                                                   # juda katta
            "/api/v1/scheduled-posts/calendar?from=" + "9" * 60 + "&to=2031-03-11T00:00:00Z",
        ]
        for path in bad:
            st, e, _ = run(get(path))
            T.check(f"400 bad_request: {path[40:100]}", st == 400 and e["error"]["code"] == "bad_request", f"{st} {e}")
        st, _, _ = run(get(q(base, base + timedelta(days=45))))
        T.check("aynan 45 kun ruxsat", st == 200)

        print("\n== 4. Kesish (limit) ==")
        from miniapp_api import repository as repo
        old = repo.CALENDAR_LIMIT
        repo.CALENDAR_LIMIT = 2
        try:
            st, d, _ = run(get(q(base - timedelta(days=5), base + timedelta(days=10))))
        finally:
            repo.CALENDAR_LIMIT = old
        T.check("limit 2 < 3 post: 2 ta qaytadi va truncated=True (jim kesilmaydi)", len(d["items"]) == 2 and d["truncated"] is True, str(d)[:200])

        print("\n== 5. O'qish yozmaydi ==")
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s", (A,))
        T.check("A postlari soni o'zgarmadi (7)", cur.fetchone()[0] == 7)
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
