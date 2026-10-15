#!/usr/bin/env python3
"""Mini App'da yaratilgan post HAQIQIY scheduler orqali (bir marta) yuboriladi — real PostgreSQL + soxta Bot API.

Oqim: Mini App HTTP API (`POST /posts`, `DELETE /posts/{id}`) -> `scheduled_posts` -> HAQIQIY
`scheduler.check_and_send_posts(bot)` (ikki parallel tick) -> HAQIQIY PTB `Bot` -> soxta Telegram serveri.
Tekshiriladi: aynan 1 ta sendMessage (to'g'ri kanal/matn), DB `posted` + sent_message_id, kelajakdagi va
bekor qilingan post yuborilmaydi, ikkinchi tick qayta yubormaydi. Haqiqiy Telegram EMAS (u uchun test bot kerak).
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_sched_e2e")
if URL:
    os.environ["DATABASE_URL"] = URL

from fake_bot_api import TOKEN, FakeBotApi  # noqa: E402
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP -> SCHEDULER -> Bot API (real PG + soxta Telegram)")
USER, OTHER = 9_600_000_001, 9_600_000_002
CHAN = "-1009600001"


class NullLimiter:
    async def hit(self, bucket, subject, *, limit, window):
        return None


def main() -> int:
    if not URL:
        T.skip("scheduler e2e", "BLOCKED: real PostgreSQL URL (sinov bazasi) yo'q")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from telegram import Bot

    import database as db
    import scheduler as sched
    from config import BOT_USERNAME
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings
    from miniapp_api.writes import PostWriter
    from utils.helpers import watermark_line

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
        q("DELETE FROM sent_messages WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = ANY(%s))", ([USER, OTHER],)) \
            if q("SELECT to_regclass('sent_messages')")[0][0] else None
        q("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", ([USER, OTHER],))
        q("DELETE FROM channels WHERE user_id = ANY(%s)", ([USER, OTHER],))
        q("DELETE FROM users WHERE user_id = ANY(%s)", ([USER, OTHER],))

    settings = dataclasses.replace(
        load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                       "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"}), db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner)
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW,
                               service=service, writer=PostWriter(service, settings))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    async def http(method, path, **kw):
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            kw["headers"] = {"Authorization": "tma " + make_init_data(USER)}
            resp = await client.request(method, path, **kw)
            return resp.status, await resp.json()
        finally:
            await client.close()

    async def scenario():
        fake = FakeBotApi()
        base = await fake.start()
        bot = Bot(TOKEN, base_url=base)
        await bot.initialize()
        try:
            st, now_post = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "Mini App: hozir yuborilsin", "send_now": True})
            T.check("Mini App: send_now post yaratildi (201)", st == 201, str(now_post))
            st, later = await http("POST", "/api/v1/posts", json={
                "channel_id": CHAN, "text": "Mini App: kelajak posti",
                "scheduled_at": (datetime.now(timezone.utc) + timedelta(hours=3)).replace(microsecond=0).isoformat()})
            T.check("Mini App: kelajak posti yaratildi", st == 201)
            st, cancelled = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "Mini App: bekor qilinadi", "send_now": True})
            st2, _ = await http("DELETE", f"/api/v1/posts/{cancelled['post']['id']}")
            T.check("Mini App: post bekor qilindi", st == 201 and st2 == 200)

            await asyncio.gather(sched.check_and_send_posts(bot), sched.check_and_send_posts(bot))
            sends = fake.calls_of("sendMessage")
            T.check("AYNAN 1 ta sendMessage (ikki parallel tick, bitta post)", len(sends) == 1, str([s.get("text") for s in sends]))
            if sends:
                T.check("to'g'ri kanal", str(sends[0].get("chat_id")) == CHAN, str(sends[0].get("chat_id")))
                # Bepul tarif (test foydalanuvchisi 'free') posti BOSHIDA «🤖 @bot»
                # nishoni turadi (apply_post_watermark), undan keyin Mini App'da
                # yozilgan matn keladi; matn sichqoncha/tekshiruv uchun
                # o'zgarishsiz saqlanadi va nishon faqat BIR marta chiqadi.
                badge, body = watermark_line(BOT_USERNAME), "Mini App: hozir yuborilsin"
                expected = f"{badge}\n\n{body}" if badge else body
                sent_text = str(sends[0].get("text", ""))
                T.check("matn: bepul tarif nishoni BOSHDA, so'ngra Mini App matni",
                        sent_text == expected, sent_text[:80])
                T.check("matn: nishon takrorlanmaydi va matn o'zgarmagan",
                        sent_text.count(body) == 1 and sent_text.endswith(body), sent_text[:80])
            pid = now_post["post"]["id"]
            status, mid = q("SELECT status, sent_message_id FROM scheduled_posts WHERE id = %s", (pid,))[0]
            T.check("DB: yuborilgan post 'posted/published', sent_message_id = soxta Telegram id",
                    status in ("posted", "published") and mid is not None and mid > 5000, f"{status} {mid}")
            T.check("kelajak posti hali 'pending' (yuborilmadi)",
                    q("SELECT status FROM scheduled_posts WHERE id = %s", (later["post"]["id"],))[0][0] == "pending")
            T.check("bekor qilingan post 'cancelled' (yuborilmadi)",
                    q("SELECT status FROM scheduled_posts WHERE id = %s", (cancelled["post"]["id"],))[0][0] == "cancelled")
            await sched.check_and_send_posts(bot)
            T.check("ikkinchi tick qayta YUBORMAYDI (hali 1 ta sendMessage)", len(fake.calls_of("sendMessage")) == 1)
            st, hist = await http("GET", "/api/v1/scheduled-posts?status=history&limit=50")
            ids = {i["id"]: i["status"] for i in hist["items"]}
            T.check("Mini App tarixida yuborilgan va bekor qilingan postlar ko'rinadi",
                    ids.get(pid) in ("posted", "published") and ids.get(cancelled["post"]["id"]) == "cancelled", str(ids))
        finally:
            await bot.shutdown()
            await fake.stop()

    async def failure_scenario():
        """Telegram doimiy xato (kanal topilmadi) qaytarsa: post 'failed', qayta yuborilmaydi, Mini App'da ko'rinadi."""
        fake = FakeBotApi(fail_methods={"sendMessage": (400, 400, "Bad Request: chat not found")})
        base = await fake.start()
        bot = Bot(TOKEN, base_url=base)
        await bot.initialize()
        try:
            st, created = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "Mini App: xato holati", "send_now": True})
            pid = created["post"]["id"]
            await sched.check_and_send_posts(bot)
            first = len(fake.calls_of("sendMessage"))
            status = q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]
            T.check("doimiy Telegram xatosi: post 'failed' bo'ldi", status == "failed", status)
            await sched.check_and_send_posts(bot)
            T.check("'failed' post qayta-qayta yuborilmaydi", len(fake.calls_of("sendMessage")) == first, f"{first} -> {len(fake.calls_of('sendMessage'))}")
            st, me = await http("GET", "/api/v1/me")
            st2, hist = await http("GET", "/api/v1/scheduled-posts?status=history&limit=50")
            T.check("Mini App: /me posts.failed >= 1 va tarixda 'failed' ko'rinadi",
                    me["posts"]["failed"] >= 1 and any(i["id"] == pid and i["status"] == "failed" for i in hist["items"]), str(me["posts"]))
        finally:
            await bot.shutdown()
            await fake.stop()

    cleanup()
    try:
        for uid in (USER, OTHER):
            q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,'uz','free')", (uid, f"s{uid}", f"N{uid}"))
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'E2E kanal',TRUE)", (USER, CHAN))
        started = time.time()
        loop.run_until_complete(asyncio.wait_for(scenario(), 120))
        loop.run_until_complete(asyncio.wait_for(failure_scenario(), 120))
        T.check(f"butun oqim {time.time() - started:.1f}s da tugadi (<120s)", True)
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
