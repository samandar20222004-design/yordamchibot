#!/usr/bin/env python3
"""Mini App — REAL PostgreSQL integratsiya testi (ownership, statement_timeout, pool).

Faqat SINOV bazasi: `MINIAPP_TEST_DATABASE_URL` (yoki P0_/STEP5_/INTEGRITY_TEST_DATABASE_URL)
berilmasa butun fayl SKIP/BLOCKED. Test faqat o'z qatorlarini (user_id >= 9_000_000_000)
yozadi va oxirida o'chiradi; production bazaga ULANMAYDI.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

URL = ""
for _var in ("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
             "INTEGRITY_TEST_DATABASE_URL"):
    _v = os.getenv(_var, "")
    if _v and "user:pass" not in _v:
        URL = _v
        break
if URL:
    os.environ["DATABASE_URL"] = URL

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — REAL PostgreSQL (ownership, statement_timeout, pool)")
A, B, C, D, E = (9_000_000_001, 9_000_000_002, 9_000_000_003, 9_000_000_004, 9_000_000_005)
IDS = (A, B, C, D, E)


def main() -> int:
    if not URL:
        T.skip("real PostgreSQL integratsiya testi",
               "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import threading

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.errors import ApiError
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
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM system_settings WHERE key = 'beta_gate_state'")

    cleanup()
    try:
        for uid, plan, exp, deleted in (
                (A, "pro", "now() + interval '10 days'", False), (B, "free", "NULL", False),
                (C, "free", "NULL", False), (D, "pro", "now() - interval '1 day'", False),
                (E, "free", "NULL", True)):
            cur.execute(
                f"INSERT INTO users (user_id, username, full_name, language_code, plan_type, "
                f"subscription_expires_at, deleted_at) VALUES (%s, %s, %s, 'uz', %s, {exp}, "
                f"{'now()' if deleted else 'NULL'})", (uid, f"u{uid}", f"Name{uid}", plan))
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES "
                    "(%s,'-100900001','A1',TRUE),(%s,'-100900002','A2',TRUE),"
                    "(%s,'-100900003','A-off',FALSE),(%s,'-100900004','B1',TRUE)", (A, A, A, B))
        cur.execute("INSERT INTO channels (user_id, channel_id, channel_title, is_active, deleted_at) "
                    "VALUES (%s,'-100900005','A-del',TRUE, now())", (A,))
        for i in range(4):
            cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, "
                        "scheduled_time, status) VALUES (%s,'-100900001','text',%s, now() + %s * interval '1 hour','pending')",
                        (A, f"a-post-{i}", i + 1))
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                    "VALUES (%s,'-100900001','text','a-cancelled', now(),'cancelled')", (A,))
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                    "VALUES (%s,'-100900004','text','B-SECRET', now() + interval '1 hour','pending')", (B,))

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

        async def get(path, uid):
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                r = await client.get(path, headers={"Authorization": "tma " + make_init_data(uid)})
                return r.status, await r.json()
            finally:
                await client.close()

        balance_before = db.conn_balance()
        print("\n== 1. Real SQL: ownership ==")
        st, ch = run(get("/api/v1/channels", A))
        T.check("A: faqat o'z faol kanallari (o'chirilgan/soft-delete yo'q)",
                st == 200 and [c["id"] for c in ch["items"]] == ["-100900001", "-100900002"], str(ch))
        st, ch = run(get("/api/v1/channels", B))
        T.check("B: faqat o'z kanali", [c["id"] for c in ch["items"]] == ["-100900004"])
        st, ch = run(get("/api/v1/channels", C))
        T.check("C: kanallari yo'q -> bo'sh ro'yxat (xato emas)", st == 200 and ch["items"] == [])
        st, sp = run(get("/api/v1/scheduled-posts?limit=2&offset=1", A))
        T.check("A: pending postlar tartib+pagination (total=4)", st == 200 and sp["total"] == 4
                and [i["preview"] for i in sp["items"]] == ["a-post-1", "a-post-2"] and sp["has_more"] is True)
        T.check("A javobida B posti yo'q, 'cancelled' yo'q", "B-SECRET" not in json.dumps(sp) and "a-cancelled" not in json.dumps(sp))
        T.check("kanal nomi egasi bo'yicha qo'shiladi", sp["items"][0]["channel_title"] == "A1")
        st, sp = run(get("/api/v1/scheduled-posts", B))
        T.check("B faqat o'z postini ko'radi", [i["preview"] for i in sp["items"]] == ["B-SECRET"])
        st, me = run(get("/api/v1/me", A))
        T.check("/me: faol PRO (DB vaqti bo'yicha)", st == 200 and me["plan"]["is_pro"] and me["plan"]["type"] == "pro")
        T.check("/me: usage kanallar=2, pending=4", me["usage"]["channels"] == 2 and me["usage"]["pending_posts"] == 4)
        st, me = run(get("/api/v1/me", D))
        T.check("/me: muddati o'tgan PRO -> free", me["plan"]["type"] == "free" and not me["plan"]["is_pro"])
        cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (D,))
        T.check("o'qish yozmadi: users.plan_type 'pro' qoldi", cur.fetchone()[0] == "pro")
        st, err = run(get("/api/v1/me", E))
        T.check("soft-delete qilingan hisob -> 403 not_registered", st == 403 and err["error"]["code"] == "not_registered")
        st, err = run(get("/api/v1/me", 9_000_000_099))
        T.check("users'da yo'q -> 403 va foydalanuvchi YARATILMADI", st == 403)
        cur.execute("SELECT count(*) FROM users WHERE user_id = 9000000099")
        T.check("users jadvaliga yozilmadi", cur.fetchone()[0] == 0)

        print("\n== 2. Real beta holati (system_settings) ==")
        service_beta = MiniAppService(settings, runner, invite_only_getter=lambda: True,
                                      admin_check=lambda u, r: False)
        api2 = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service_beta)
        app2 = web.Application()
        app2.add_subapp(appmod.API_PREFIX, api2)

        async def get2(uid):
            client = TestClient(TestServer(app2))
            await client.start_server()
            try:
                r = await client.get("/api/v1/me", headers={"Authorization": "tma " + make_init_data(uid)})
                return r.status, await r.json()
            finally:
                await client.close()

        state = json.dumps({"version": 1, "enabled": None, "codes": {}, "approved": {str(A): {}},
                            "pending": {str(B): {}}})
        cur.execute("INSERT INTO system_settings (key, value) VALUES ('beta_gate_state', %s) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (state,))
        T.check("approved -> 200", run(get2(A))[0] == 200)
        T.check("pending -> 403", run(get2(B))[0] == 403)
        T.check("ro'yxatda yo'q -> 403", run(get2(C))[0] == 403)
        cur.execute("SELECT value FROM system_settings WHERE key = 'beta_gate_state'")
        T.check("beta holati API tomonidan O'ZGARTIRILMADI", cur.fetchone()[0] == state)
        cur.execute("UPDATE system_settings SET value = '{broken' WHERE key = 'beta_gate_state'")
        st, err = run(get2(A))
        T.check("beta holati JSON buzuq -> 503 (ruxsat yo'q)", st == 503 and err["error"]["code"] == "service_unavailable")
        cur.execute("DELETE FROM system_settings WHERE key = 'beta_gate_state'")

        print("\n== 3. statement_timeout, read-only, pool ==")
        fast = ReadOnlyRunner(statement_timeout_ms=300, max_inflight=2)
        t0 = time.monotonic()
        try:
            run(fast.run(lambda c: c.execute("SELECT pg_sleep(3)")))
            T.check("uzun so'rov statement_timeout bilan to'xtatildi", False)
        except ApiError as err:
            dt = time.monotonic() - t0
            T.check("uzun so'rov (pg_sleep 3s) ~0.3 s da SERVER tomonidan bekor qilindi (503)",
                    err.code == "service_unavailable" and dt < 2.0, f"{dt:.2f}s")
        T.check("timeoutdan keyin inflight=0 (semafor/thread bo'shadi)", fast.inflight == 0)
        # pool ulanishi toza: global timeout o'rnatilmagan, tranzaksiya IDLE
        seen = set()
        for _ in range(db.DB_POOL_MAX + 3):
            with db.db_cursor() as c2:
                c2.execute("SHOW statement_timeout")
                seen.add(c2.fetchone()[0])
                c2.execute("SHOW lock_timeout")
                seen.add("lock:" + c2.fetchone()[0])
        T.check("SET LOCAL pool ulanishiga O'TMADI (bot so'rovlarida timeout=0)", seen == {"0", "lock:0"}, str(seen))
        # read-only: yozishga urinish rad etiladi va hech narsa yozilmaydi
        try:
            run(fast.run(lambda c: c.execute("INSERT INTO users (user_id) VALUES (9000000077)")))
            T.check("read-only tranzaksiya INSERT'ni rad etdi", False)
        except ApiError as err:
            T.check("read-only tranzaksiya INSERT'ni rad etdi (503)", err.code == "service_unavailable")
        cur.execute("SELECT count(*) FROM users WHERE user_id = 9000000077")
        T.check("INSERT yozilmadi", cur.fetchone()[0] == 0)
        # tranzaksiya autocommit emas va SET LOCAL ta'sirli ekani
        probe = {}

        def probe_fn(c):
            c.execute("SHOW statement_timeout")
            probe["timeout"] = c.fetchone()[0]
            c.execute("SHOW transaction_read_only")
            probe["ro"] = c.fetchone()[0]
            c.execute("SELECT now()")
            first = c.fetchone()[0]
            c.execute("SELECT pg_sleep(0.05)")
            c.execute("SELECT now()")
            probe["same_tx"] = first == c.fetchone()[0]
            return True

        probe_runner = ReadOnlyRunner(statement_timeout_ms=1234, max_inflight=1)
        run(probe_runner.run(probe_fn))
        T.check("tranzaksiya ichida statement_timeout=1234ms (SET LOCAL ishladi)", probe["timeout"] == "1234ms", str(probe))
        T.check("tranzaksiya READ ONLY", probe["ro"] == "on")
        T.check("autocommit emas: ikki so'rovda now() bir xil (BEGIN ochilgan, bitta tranzaksiya)",
                probe["same_tx"] is True)
        # parallel so'rovlar + semafor resurs balansi
        hold = threading.Event()
        slow = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=2, queue_wait_seconds=0)  # navbatsiz: tez-503

        async def parallel():
            async def one():
                try:
                    return await slow.run(lambda c: (hold.wait(1.0), c.execute("SELECT 1"), "ok")[2])
                except ApiError as e:
                    return e.code
            tasks = [asyncio.ensure_future(one()) for _ in range(4)]
            await asyncio.sleep(0.2)
            hold.set()
            return await asyncio.gather(*tasks)

        results = run(parallel())
        T.check("parallel: 2 tasi bajarildi, 2 tasi tez 503 (semafor)",
                sorted(results) == ["ok", "ok", "service_unavailable", "service_unavailable"], str(results))
        T.check("parallel tugagach semafor bo'sh", slow.inflight == 0)
        queued = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=2.0, max_queue=64)

        async def real_burst():
            async def one():
                try:
                    return await queued.run(lambda c: (c.execute("SELECT count(*) FROM users"), "ok")[1])
                except ApiError as e:
                    return e.code
            res = await asyncio.gather(*[one() for _ in range(50)])
            return {k: res.count(k) for k in set(res)}

        burst_res = run(real_burst())
        T.check("REAL DB: 50 parallel so'rov, 4 slot + navbat -> hammasi bajariladi (navbatsiz 46 tasi 503 bergan)",
                burst_res == {"ok": 50}, str(burst_res))
        T.check("burstdan keyin slotlar bo'sh", queued.inflight == 0 and queued.waiting == 0)
        T.check("pool ulanish balansi (conn_balance) test boshidagiga teng", db.conn_balance() == balance_before,
                f"{balance_before} -> {db.conn_balance()}")
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND state = 'idle in transaction'")
        T.check("'idle in transaction' ulanish qolmadi", cur.fetchone()[0] == 0)
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
