#!/usr/bin/env python3
"""Mini App — `GET /api/v1/channels/{id}/analytics` (real PostgreSQL, faqat sinov bazasi).

Halollik: faqat haqiqiy ma'lumotlar (obunachi snapshot'lari, botning o'z postlari, MANBALI ko'rishlar). Noma'lum = noma'lum.
Xavfsizlik: faqat kanal EGASI; begona/yo'q/noto'g'ri ID -> bir xil 404 (kanal mavjudligi sizdirilmaydi); o'qish yozmaydi.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_an")
if URL:
    os.environ["DATABASE_URL"] = URL

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — kanal analitikasi (real PostgreSQL)")
A, B = 9_100_000_001, 9_100_000_002
CH_A, CH_EMPTY, CH_B = "-1009100001", "-1009100002", "-1009100004"


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
    chans = [CH_A, CH_EMPTY, CH_B]

    def cleanup():
        cur.execute("DELETE FROM channel_member_counts WHERE channel_id = ANY(%s)", (chans,))
        cur.execute("DELETE FROM channel_posts_history WHERE channel_id = ANY(%s)", (chans,))
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
                    "(%s,%s,'Kanal A',TRUE),(%s,%s,'Bo''sh kanal',TRUE),(%s,%s,'Kanal B',TRUE)",
                    (A, CH_A, A, CH_EMPTY, B, CH_B))
        from services.channels.growth import tashkent_today
        today = tashkent_today()
        for days_ago, count in ((30, 1000), (14, 1050), (7, 1100), (3, 1130), (0, 1150)):
            cur.execute("INSERT INTO channel_member_counts (channel_id, snapshot_date, member_count) VALUES (%s,%s,%s)",
                        (CH_A, today - timedelta(days=days_ago), count))
        cur.execute("INSERT INTO channel_member_counts (channel_id, snapshot_date, member_count) VALUES (%s,%s,777)",
                    (CH_B, today))
        for status, n in (("posted", 3), ("pending", 2), ("failed", 1), ("unknown", 1), ("cancelled", 4)):
            for i in range(n):
                cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                            "VALUES (%s,%s,'text',%s, now() - interval '2 days', %s)", (A, CH_A, f"{status}-{i}", status))
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                    "VALUES (%s,%s,'text','B-SECRET', now(), 'posted')", (B, CH_B))
        # ko'rishlar: 2 ta MANBALI, 1 ta eski soxta 0 (manbasiz), 1 ta NULL
        for msg, views, src in ((1, 100, "tme_preview"), (2, 300, "tme_preview"), (3, 0, None), (4, None, None)):
            cur.execute("INSERT INTO channel_posts_history (channel_id, message_id, content, views, views_source, "
                        "views_collected_at, post_date) VALUES (%s,%s,'x',%s,%s, CASE WHEN %s IS NULL THEN NULL ELSE now() END, now())",
                        (CH_A, msg, views, src, src))
        cur.execute("INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date) "
                    "VALUES (%s, 1, 'B-SECRET-HIST', NULL, now())", (CH_B,))

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
                return r.status, await r.json()
            finally:
                await client.close()

        print("\n== 1. Egasi: haqiqiy ma'lumotlar ==")
        st, d = run(get(f"/api/v1/channels/{CH_A}/analytics"))
        T.check("200 va kanal nomi", st == 200 and d["channel"] == {"id": CH_A, "title": "Kanal A"}, str(d)[:200])
        m = d.get("members", {})
        T.check("obunachilar: joriy 1150, 7 kunlik +50, 30 kunlik +150", m.get("current") == 1150 and m.get("delta_7d") == 50 and m.get("delta_30d") == 150, str(m))
        T.check("ishonch darajasi va manba oshkor", m.get("confidence") in ("low", "medium") and m.get("source") == "bot_api_getChatMemberCount", str(m))
        T.check("tarix (sana, soni) yangidan eskiga, 5 nuqta", [h["member_count"] for h in m.get("history", [])] == [1150, 1130, 1100, 1050, 1000], str(m.get("history")))
        p = d.get("posts", {})
        T.check("botning o'z postlari: faqat shu kanal; posted=3, pending=2, failed=1, unknown=1 (cancelled hisobga olinmaydi)",
                (p.get("sent_all"), p.get("pending"), p.get("failed"), p.get("unknown")) == (3, 2, 1, 1), str(p))
        T.check("posted 7/30 kun oynalari", p.get("sent_7d") == 3 and p.get("sent_30d") == 3, str(p))
        v = d.get("views", {})
        T.check("ko'rishlar: faqat MANBALI qatorlar (soxta 0 va NULL hisobga olinmaydi): 2 ta, o'rtacha 200, eng ko'pi 300",
                v.get("with_views") == 2 and v.get("avg") == 200.0 and v.get("max") == 300 and v.get("available") is True, str(v))
        T.check("ko'rishlar manbasi ochiq aytiladi", v.get("sources") == ["tme_preview"], str(v))
        T.check("javobda boshqa foydalanuvchi ma'lumoti yo'q", "B-SECRET" not in json.dumps(d) and "777" not in json.dumps(d))

        print("\n== 2. Ma'lumot yo'q: to'qilmaydi ==")
        st, d = run(get(f"/api/v1/channels/{CH_EMPTY}/analytics"))
        m, v, p = d["members"], d["views"], d["posts"]
        T.check("snapshot yo'q: current=None, delta=None, ishonch 'none', tarix bo'sh",
                st == 200 and m["current"] is None and m["delta_7d"] is None and m["confidence"] == "none" and m["history"] == [], str(m))
        T.check("ko'rishlar mavjud emas: available=False, qiymatlar None (0 emas)", v["available"] is False and v["avg"] is None and v["max"] is None, str(v))
        T.check("postlar nollar (haqiqiy 0)", (p["sent_all"], p["pending"], p["failed"]) == (0, 0, 0), str(p))

        print("\n== 3. Xavfsizlik ==")
        st, e1 = run(get(f"/api/v1/channels/{CH_B}/analytics", A))
        st2, e2 = run(get("/api/v1/channels/-1009199999/analytics", A))
        T.check("begona kanal -> 404 not_found", st == 404 and e1["error"]["code"] == "not_found", str(e1))
        strip = lambda e: {k: v for k, v in e["error"].items() if k != "request_id"}  # noqa: E731 — request_id har so'rovda noyob
        T.check("mavjud begona va umuman yo'q kanal BIR XIL javob (mavjudlik sizdirilmaydi)", strip(e1) == strip(e2) and st == st2)
        st, e = run(get("/api/v1/channels/abc/analytics"))
        T.check("noto'g'ri kanal ID -> 404", st == 404 and e["error"]["code"] == "not_found", str(e))
        st, e = run(get(f"/api/v1/channels/{CH_A}/analytics", auth=False))
        T.check("autentifikatsiyasiz -> 401", st == 401, f"{st} {e}")
        st, d = run(get(f"/api/v1/channels/{CH_B}/analytics", B))
        T.check("kanal egasi B o'z kanalini ko'radi (777)", st == 200 and d["members"]["current"] == 777, str(d)[:200])

        print("\n== 3b. GET /channels: kanal bo'yicha reja soni va obunachilar ==")
        cur.execute("INSERT INTO channel_member_counts (channel_id, snapshot_date, member_count) VALUES (%s,%s,5)",
                    (CH_EMPTY, today - timedelta(days=30)))   # eski snapshot -> 'joriy' deb ko'rsatilmasligi kerak
        st, d = run(get("/api/v1/channels"))
        by = {c["id"]: c for c in d.get("items", [])}
        T.check("200 va faqat o'z kanallari (B ning kanali yo'q)", st == 200 and set(by) == {CH_A, CH_EMPTY}, str(d))
        T.check("CH_A: rejada 2 ta post, obunachilar 1150 (bugungi snapshot), sana bor",
                by[CH_A]["pending_posts"] == 2 and by[CH_A]["members"] == 1150 and by[CH_A]["members_as_of"] == today.isoformat(), str(by[CH_A]))
        T.check("CH_EMPTY: post 0 (haqiqiy 0), eskirgan (30 kunlik) snapshot -> members=None, 0 EMAS",
                by[CH_EMPTY]["pending_posts"] == 0 and by[CH_EMPTY]["members"] is None and by[CH_EMPTY]["members_as_of"] is None, str(by[CH_EMPTY]))
        T.check("B ning 777 raqami va posti A javobida yo'q", "777" not in json.dumps(d) and "B-SECRET" not in json.dumps(d))
        st, d = run(get("/api/v1/channels", B))
        T.check("B o'z kanalini 777 bilan ko'radi", st == 200 and d["items"][0]["members"] == 777 and d["items"][0]["pending_posts"] == 0, str(d))

        print("\n== 4. O'qish yozmaydi ==")
        cur.execute("SELECT COUNT(*) FROM channel_member_counts WHERE channel_id = %s", (CH_A,))
        T.check("snapshot soni o'zgarmadi (5)", cur.fetchone()[0] == 5)
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
