#!/usr/bin/env python3
"""Mini App — YOZUV oqimlari, REAL PostgreSQL + to'liq HTTP (post yaratish/tahrirlash/bekor, til, IDOR).

Faqat SINOV bazasi (`MINIAPP_TEST_DATABASE_URL` yoki P0_/STEP5_/INTEGRITY_TEST_DATABASE_URL). URL yo'q
bo'lsa SKIP/BLOCKED (PASS hisoblanmaydi). Test faqat user_id >= 9_100_000_001 qatorlarini yozadi/o'chiradi.
Haqiqiy kod: aiohttp ilovasi, auth, limiter-dan tashqari barcha qatlamlar, `posts_repository.add_post`,
`cancel_post`, `update_post_content`, `users_repository.set_user_language`, `check_queue_limit`.
Mock: faqat Redis limiter (NullLimiter) va soat; Telegram yuborish yo'q (yuborishni scheduler bajaradi).
"""
from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp")
if URL:
    os.environ["DATABASE_URL"] = URL

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — YOZUV oqimlari (REAL PostgreSQL + HTTP)")
A, B, GHOST, FULL = 9_100_000_001, 9_100_000_002, 9_100_000_003, 9_100_000_004
IDS = (A, B, GHOST, FULL)
CH_A, CH_A2, CH_B, CH_FULL = "-1009100001", "-1009100002", "-1009100003", "-1009100004"


class NullLimiter:
    async def hit(self, bucket, subject, *, limit, window):
        return None


def main() -> int:
    if not URL:
        T.skip("real PostgreSQL yozuv testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
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
        q("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(IDS),))
        q("DELETE FROM channels WHERE user_id = ANY(%s)", (list(IDS),))
        q("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                              "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    settings = dataclasses.replace(settings, db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner)
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW,
                               service=service, writer=PostWriter(service, settings))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    def hdr(uid):
        return {"Authorization": "tma " + make_init_data(uid)}

    async def call_many(reqs):
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            async def one(method, path, kw):
                resp = await client.request(method, path, **kw)
                try:
                    body = await resp.json()
                except Exception:  # noqa: BLE001
                    body = None
                return resp.status, body

            return await asyncio.gather(*[one(m, p, kw) for m, p, kw in reqs])
        finally:
            await client.close()

    def call(method, path, uid=None, json_body=None, **kw):
        if uid is not None:
            kw["headers"] = {**hdr(uid), **kw.get("headers", {})}
        if json_body is not None:
            kw["json"] = json_body
        return loop.run_until_complete(call_many([(method, path, kw)]))[0]

    def at(hours=2):
        return (datetime.now(timezone.utc) + timedelta(hours=hours)).replace(microsecond=0).isoformat()

    def rows(uid, status=None):
        sql = "SELECT id, channel_id, content, status, post_type, scheduled_time FROM scheduled_posts WHERE user_id = %s"
        params = [uid]
        if status:
            sql += " AND status = %s"
            params.append(status)
        return q(sql + " ORDER BY id", params)

    cleanup()
    try:
        for uid in (A, B, FULL):
            q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) "
              "VALUES (%s, %s, %s, 'uz', 'free')", (uid, f"w{uid}", f"Name{uid}"))
        for uid, ch in ((A, CH_A), (A, CH_A2), (B, CH_B), (FULL, CH_FULL)):
            q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,%s,TRUE)",
              (uid, ch, f"T{ch}"))

        print("\n== 1. Yaratish ==")
        st, body = call("POST", "/api/v1/posts", A, {"channel_id": CH_A, "text": "Salom <b>dunyo</b> & co", "scheduled_at": at(2)})
        T.check("201 created + delivery=scheduled", st == 201 and body["created"] is True and body["delivery"] == "scheduled", f"{st} {body}")
        pid = body["post"]["id"] if st == 201 else 0
        r = rows(A)
        T.check("DB'da AYNAN 1 qator: egasi A, pending, text, kanal, matn o'zgarmagan",
                len(r) == 1 and r[0][1] == CH_A and r[0][2] == "Salom <b>dunyo</b> & co"
                and r[0][3] == "pending" and r[0][4] == "text", str(r))
        T.check("javobdagi post_id DB bilan mos, status pending", body["post"]["status"] == "pending" and r and r[0][0] == pid)

        st, body = call("POST", "/api/v1/posts", A, {"channel_id": CH_A, "text": "Salom <b>dunyo</b> & co", "scheduled_at": at(2)})
        T.check("takroriy yuborish: 200, created=false, yangi qator YO'Q", st == 200 and body["created"] is False and len(rows(A)) == 1, f"{st} {body}")

        reqs = [("POST", "/api/v1/posts", {"headers": hdr(A), "json": {"channel_id": CH_A2, "text": "parallel", "scheduled_at": at(3)}})
                for _ in range(6)]
        res = loop.run_until_complete(call_many(reqs))
        T.check("6 ta bir vaqtdagi bir xil so'rov: DB'da AYNAN 1 ta qator",
                len(rows(A, "pending")) == 2 and sum(1 for s, _ in res if s == 201) == 1
                and all(s in (200, 201) for s, _ in res), f"{[s for s, _ in res]} {len(rows(A))}")

        st, body = call("POST", "/api/v1/posts", A, {"channel_id": CH_A, "text": "hozir", "send_now": True})
        r2 = [x for x in rows(A) if x[2] == "hozir"]
        T.check("send_now: 201, delivery=immediate, scheduled_time <= hozir, status pending (scheduler yuboradi)",
                st == 201 and body["delivery"] == "immediate" and r2 and r2[0][3] == "pending"
                and r2[0][5] <= datetime.now(timezone.utc) + timedelta(seconds=2), f"{st} {body}")

        print("\n== 2. Validatsiya ==")
        base = {"channel_id": CH_A, "text": "x1"}
        cases = [
            ("bo'sh matn", {**base, "text": "  ", "scheduled_at": at()}, "invalid_input"),
            ("4097 belgi", {**base, "text": "a" * 4097, "scheduled_at": at()}, "invalid_input"),
            ("boshqarish belgisi", {**base, "text": "a\x00b", "scheduled_at": at()}, "invalid_input"),
            ("vaqt ham send_now ham yo'q", dict(base), "invalid_input"),
            ("ikkalasi ham bor", {**base, "scheduled_at": at(), "send_now": True}, "invalid_input"),
            ("zona yo'q (naive)", {**base, "scheduled_at": "2030-01-01T10:00:00"}, "invalid_input"),
            ("o'tmish", {**base, "scheduled_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, "schedule_in_past"),
            ("30 soniya keyin (< 1 daqiqa)", {**base, "scheduled_at": (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()}, "schedule_in_past"),
            ("400 kun keyin", {**base, "scheduled_at": at(24 * 400)}, "invalid_input"),
            ("noma'lum maydon user_id", {**base, "scheduled_at": at(), "user_id": B}, "invalid_input"),
            ("channel_id turi noto'g'ri", {**base, "channel_id": 5, "scheduled_at": at()}, "invalid_input"),
            ("channel_id SQL-shakl", {**base, "channel_id": "-1' OR '1'='1", "scheduled_at": at()}, "invalid_input"),
        ]
        n_before = len(rows(A))
        for label, payload, code in cases:
            st, body = call("POST", "/api/v1/posts", A, payload)
            T.check(f"{label} -> {code}", body and body.get("error", {}).get("code") == code and st in (422,), f"{st} {body}")
        T.check("rad etilgan so'rovlar DB'ga qator yozmadi", len(rows(A)) == n_before)
        st, body = call("POST", "/api/v1/posts", A, data="x=1", headers={"Content-Type": "application/x-www-form-urlencoded"})
        T.check("Content-Type JSON emas -> 415", st == 415 and body["error"]["code"] == "unsupported_media_type")
        st, body = call("POST", "/api/v1/posts", A, data="{not json", headers={"Content-Type": "application/json"})
        T.check("buzilgan JSON -> 400", st == 400 and body["error"]["code"] == "bad_request")
        st, body = call("POST", "/api/v1/posts", A, data="[1,2]", headers={"Content-Type": "application/json"})
        T.check("JSON massiv (obyekt emas) -> 400", st == 400)
        st, body = call("POST", "/api/v1/posts", A, data="x" * 40000, headers={"Content-Type": "application/json"})
        T.check("juda katta tana -> 413", st == 413 and body["error"]["code"] == "payload_too_large")
        st, body = call("POST", "/api/v1/posts", None, {"channel_id": CH_A, "text": "x", "send_now": True})
        T.check("Authorization yo'q -> 401, qator yo'q", st == 401 and len(rows(A)) == n_before)

        print("\n== 3. Egalik (IDOR) ==")
        st, body = call("POST", "/api/v1/posts", B, {"channel_id": CH_A, "text": "hujum", "send_now": True})
        T.check("B, A kanaliga post yarata olmaydi -> 404 channel_not_found", st == 404 and body["error"]["code"] == "channel_not_found")
        T.check("B uchun qator yaratilmadi", rows(B) == [])
        st, body = call("POST", "/api/v1/posts", B, {"channel_id": CH_B, "text": "B post", "scheduled_at": at(4)})
        bid = body["post"]["id"] if st == 201 else 0
        T.check("B o'z kanaliga yarata oladi", st == 201 and len(rows(B)) == 1)
        before = rows(A)
        for method, extra in (("GET", None), ("PATCH", {"text": "buzildi"}), ("DELETE", None)):
            st, body = call(method, f"/api/v1/posts/{pid}", B, extra)
            T.check(f"B -> A postiga {method}: 404 not_found (mavjudligi sezdirilmaydi)", st == 404 and body["error"]["code"] == "not_found", f"{st}")
        T.check("A postlari o'zgarmadi", rows(A) == before)
        st, body = call("GET", f"/api/v1/posts/{pid}", A)
        T.check("A o'z postini ko'ra oladi", st == 200 and body["post"]["id"] == pid)
        big = "uzun matn " * 300  # 3000 belgi: ro'yxatda 200 belgiga qisqartiriladi, detalda TO'LIQ
        st, body = call("POST", "/api/v1/posts", A, {"channel_id": CH_A2, "text": big.strip(), "scheduled_at": at(8)})
        bigid = body["post"]["id"] if st == 201 else 0
        st, det = call("GET", f"/api/v1/posts/{bigid}", A)
        st2, lst = call("GET", "/api/v1/scheduled-posts?limit=50", A)
        item = next((i for i in lst["items"] if i["id"] == bigid), None)
        T.check("detalda to'liq matn (3000 belgi), ro'yxatda faqat qisqa ko'rinish (<= 200)",
                st == 200 and len(det["post"]["text"]) == len(big.strip()) and item and len(item["preview"]) <= 200 and "text" not in item)
        q("DELETE FROM scheduled_posts WHERE id = %s", (bigid,))
        st, body = call("GET", "/api/v1/scheduled-posts", B)
        T.check("B ro'yxatida A postlari yo'q", st == 200 and all(i["id"] == bid for i in body["items"]))
        st, body = call("POST", "/api/v1/posts", GHOST, {"channel_id": CH_A, "text": "x", "send_now": True})
        T.check("ro'yxatdan o'tmagan foydalanuvchi -> 403 not_registered", st == 403 and body["error"]["code"] == "not_registered")

        print("\n== 4. Tahrirlash ==")
        st, body = call("PATCH", f"/api/v1/posts/{pid}", A, {"text": "Yangilangan matn", "scheduled_at": at(5)})
        row = [x for x in rows(A) if x[0] == pid][0]
        T.check("PATCH matn+vaqt: 200, DB yangilandi", st == 200 and row[2] == "Yangilangan matn"
                and abs((row[5] - (datetime.now(timezone.utc) + timedelta(hours=5))).total_seconds()) < 120, f"{st} {body}")
        for label, payload in (("bo'sh tana", {}), ("noma'lum maydon", {"status": "posted"}), ("o'tmish vaqt", {"scheduled_at": at(-3)}), ("bo'sh matn", {"text": ""})):
            st, body = call("PATCH", f"/api/v1/posts/{pid}", A, payload)
            T.check(f"PATCH {label} -> 4xx, DB o'zgarmadi", st in (400, 422) and [x for x in rows(A) if x[0] == pid][0][2] == "Yangilangan matn", f"{st}")
        q("UPDATE scheduled_posts SET status = 'posted' WHERE id = %s", (pid,))
        st, body = call("PATCH", f"/api/v1/posts/{pid}", A, {"text": "kech"})
        T.check("yuborilgan postni tahrirlash -> 409 not_editable", st == 409 and body["error"]["code"] == "not_editable")
        st, body = call("DELETE", f"/api/v1/posts/{pid}", A)
        T.check("yuborilgan postni bekor qilish -> 409", st == 409)
        q("UPDATE scheduled_posts SET status = 'pending', recurrence_type = 'daily' WHERE id = %s", (pid,))
        st, body = call("PATCH", f"/api/v1/posts/{pid}", A, {"scheduled_at": at(6)})
        T.check("takrorlanuvchi postning vaqtini o'zgartirish -> 409", st == 409)
        st, body = call("PATCH", "/api/v1/posts/999999999", A, {"text": "x"})
        T.check("mavjud bo'lmagan post -> 404", st == 404)
        st, body = call("PATCH", "/api/v1/posts/abc", A, {"text": "x"})
        T.check("post id raqam emas -> 404", st == 404)

        print("\n== 5. Bekor qilish va tarix ==")
        q("UPDATE scheduled_posts SET recurrence_type = 'none' WHERE id = %s", (pid,))
        st, body = call("DELETE", f"/api/v1/posts/{pid}", A)
        T.check("DELETE: 200 cancelled, DB'da status=cancelled (qator saqlanadi)", st == 200 and [x for x in rows(A) if x[0] == pid][0][3] == "cancelled")
        st, body = call("DELETE", f"/api/v1/posts/{pid}", A)
        T.check("qayta DELETE -> 409 not_editable", st == 409)
        st, body = call("GET", "/api/v1/scheduled-posts?status=history", A)
        T.check("tarix: bekor qilingan post ko'rinadi, status maydoni bor",
                st == 200 and any(i["id"] == pid and i["status"] == "cancelled" for i in body["items"]), f"{st}")
        st, body = call("GET", "/api/v1/scheduled-posts", A)
        T.check("kutilayotganlar ro'yxatida bekor qilingani YO'Q", st == 200 and all(i["id"] != pid for i in body["items"]))
        st, body = call("GET", "/api/v1/scheduled-posts?status=hack", A)
        T.check("noto'g'ri status filtri -> 400", st == 400)
        st, me = call("GET", "/api/v1/me", A)
        counts = me["posts"]
        real = {k: v for k, v in q("SELECT status, COUNT(*) FROM scheduled_posts WHERE user_id = %s GROUP BY status", (A,))}
        T.check("/me posts hisobi DB bilan mos (pending/cancelled)",
                counts["pending"] == real.get("pending", 0) and counts["cancelled"] == real.get("cancelled", 0)
                and counts["failed"] == 0, f"{counts} {real}")

        print("\n== 6. Navbat limiti (bepul tarif) ==")
        for i in range(5):
            st, body = call("POST", "/api/v1/posts", FULL, {"channel_id": CH_FULL, "text": f"limit {i}", "scheduled_at": at(10 + i)})
        T.check("5 ta post yaratildi", len(rows(FULL, "pending")) == 5)
        st, body = call("POST", "/api/v1/posts", FULL, {"channel_id": CH_FULL, "text": "oltinchi", "scheduled_at": at(30)})
        T.check("6-post -> 403 queue_limit_reached, qator yozilmadi", st == 403 and body["error"]["code"] == "queue_limit_reached" and len(rows(FULL, "pending")) == 5)

        print("\n== 7. Til sozlamasi ==")
        st, body = call("PATCH", "/api/v1/me/settings", A, {"language": "ru"})
        T.check("PATCH language=ru: DB'da saqlandi", st == 200 and q("SELECT language_code FROM users WHERE user_id = %s", (A,))[0][0] == "ru")
        for bad in ({"language": "xx"}, {"language": 5}, {}, {"language": "en", "role": "admin"}):
            st, body = call("PATCH", "/api/v1/me/settings", A, bad)
            T.check(f"PATCH {bad} -> 422, til o'zgarmadi", st == 422 and q("SELECT language_code FROM users WHERE user_id = %s", (A,))[0][0] == "ru", f"{st}")
        st, me = call("GET", "/api/v1/me", A)
        T.check("/me yangi tilni qaytaradi", me["user"]["language"] == "ru")
        T.check("B tili o'zgarmadi", q("SELECT language_code FROM users WHERE user_id = %s", (B,))[0][0] == "uz")
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
