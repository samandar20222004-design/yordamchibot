#!/usr/bin/env python3
"""Mini App — rejalangan postni TO'LIQ tahrirlash va ro'yxat rasmi (real PostgreSQL, faqat sinov bazasi).

* PATCH /posts/{id}: matn, vaqt (bir martalik), tugma (qo'shish/olib tashlash), takrorlanuvchida kun vaqtlari (twice ham);
* GET /posts/{id}/media: faqat egasi, tur baytlardan, keshlangan; boshqa foydalanuvchi 404; hujjat/audio -> 404;
* POST /posts/{id}/media: qurilmadagi fayl bilan almashtirish (faqat 'pending'); DELETE: matnli postga aylanadi (matn bo'sh bo'lsa rad).
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

T = Counter("MINI APP — post tahrirlash va ro'yxat rasmi (real PostgreSQL)")
A, B = 9_300_000_061, 9_300_000_062
CH = "-1009300061"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200


class NullLimiter:
    async def hit(self, *a, **k):
        return None


class FakeBot:
    def __init__(self):
        self.sent, self.deleted = [], []

    async def send_photo(self, chat_id, photo, **kw):
        from types import SimpleNamespace as NS
        self.sent.append(("photo", chat_id))
        return NS(message_id=1, photo=[NS(file_id="S"), NS(file_id="NEW_PHOTO")])

    async def send_video(self, chat_id, video, **kw):
        from types import SimpleNamespace as NS
        self.sent.append(("video", chat_id))
        return NS(message_id=2, video=NS(file_id="NEW_VIDEO"))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class Fetch:
    def __init__(self, bot):
        self.bot, self.calls = bot, []

    async def get_bot(self):
        return self.bot

    async def __call__(self, file_id):
        self.calls.append(file_id)
        return {"PH": JPEG, "VID": MP4}.get(file_id, b"not media")


def main() -> int:
    if not URL:
        T.skip("post tahrirlash", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import aiohttp
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
        q("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", ([A, B],))
        q("DELETE FROM channels WHERE user_id = ANY(%s)", ([A, B],))
        q("DELETE FROM users WHERE user_id = ANY(%s)", ([A, B],))

    settings = dataclasses.replace(load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"}), db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner)
    bot = FakeBot()
    fetch = Fetch(bot)
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW, service=service,
                               writer=PostWriter(service, settings, media_fetch=fetch))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    def call(method, path, uid=A, json=None, raw=False, form=None):
        async def go():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                headers = {"Authorization": "tma " + make_init_data(uid)} if uid else {}
                r = await client.request(method, path, json=json, data=form, headers=headers)
                if raw:
                    return r.status, await r.read(), r.headers
                try:
                    return r.status, await r.json()
                except Exception:  # noqa: BLE001
                    return r.status, None
            finally:
                await client.close()

        return loop.run_until_complete(go())

    def mk(post_type="text", content="Matn", file_id=None, status="pending", rtype="none", rday=None, rtime=None, hours=30):
        from datetime import datetime, timedelta, timezone
        when = datetime.now(timezone.utc) + timedelta(hours=hours)
        pid = int(db.add_post(A, CH, post_type, content, file_id, when, recurrence_type=rtype, recurrence_day=rday, recurrence_time=rtime))
        if status != "pending":
            q("UPDATE scheduled_posts SET status = %s WHERE id = %s", (status, pid))
        return pid

    def form_file(data):
        f = aiohttp.FormData()
        f.add_field("file", data, filename="x.bin", content_type="application/octet-stream")
        return f

    cleanup()
    try:
        q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,'a','A','uz','pro'),(%s,'b','B','uz','pro')", (A, B))
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'Kanal',TRUE)", (A, CH))

        print("\n== 1. PATCH: matn, tugma, vaqt ==")
        pid = mk()
        st, b = call("PATCH", f"/api/v1/posts/{pid}", json={"text": "<b>Yangi</b> matn", "button_text": "Ochish", "button_url": "https://example.org/x"})
        T.check("matn + tugma bir so'rovda yangilandi", st == 200 and b["post"]["text"] == "<b>Yangi</b> matn" and b["post"]["button_text"] == "Ochish"
                and b["post"]["button_url"] == "https://example.org/x", f"{st} {b}")
        st, b = call("PATCH", f"/api/v1/posts/{pid}", json={"button_text": "", "button_url": ""})
        T.check("tugma olib tashlandi (ikkalasi bo'sh)", st == 200 and b["post"]["button_text"] is None and b["post"]["button_url"] is None, f"{st} {b}")
        for label, body in (("faqat tugma matni", {"button_text": "Ochish"}), ("javascript: havola", {"button_text": "x", "button_url": "javascript:alert(1)"}),
                            ("noma'lum kalit", {"file_id": "X"}), ("bo'sh tana", {})):
            st, b = call("PATCH", f"/api/v1/posts/{pid}", json=body)
            T.check(f"yaroqsiz PATCH ({label}) -> 422", st == 422, f"{st} {b}")
        from datetime import datetime, timedelta, timezone
        new_when = (datetime.now(timezone.utc) + timedelta(days=5)).replace(second=0, microsecond=0)
        st, b = call("PATCH", f"/api/v1/posts/{pid}", json={"scheduled_at": new_when.strftime("%Y-%m-%dT%H:%M:%SZ")})
        T.check("vaqt o'zgartirildi (bir martalik)", st == 200 and b["post"]["scheduled_time"].startswith(new_when.strftime("%Y-%m-%dT%H:%M")), f"{st} {b}")
        st, b = call("PATCH", f"/api/v1/posts/{pid}", uid=B, json={"text": "buzish"})
        T.check("boshqa foydalanuvchi: 404, matn o'zgarmadi", st == 404 and q("SELECT content FROM scheduled_posts WHERE id=%s", (pid,))[0][0] == "<b>Yangi</b> matn", f"{st}")
        sent = mk(status="posted")
        st, b = call("PATCH", f"/api/v1/posts/{sent}", json={"text": "kech"})
        T.check("yuborilgan post tahrirlanmaydi (409 not_editable)", st == 409, f"{st} {b}")

        print("\n== 2. Takrorlanuvchi: kun vaqtlari ==")
        from datetime import time
        rp = mk(rtype="daily", rtime=time(9, 0))
        st, b = call("PATCH", f"/api/v1/posts/{rp}", json={"recurrence_time": "10:30"})
        row = q("SELECT recurrence_type, recurrence_day, recurrence_time FROM scheduled_posts WHERE id=%s", (rp,))[0]
        T.check("daily: kun vaqti o'zgardi", st == 200 and row[0] == "daily" and str(row[2]) == "10:30:00", f"{st} {row} {b}")
        st, b = call("PATCH", f"/api/v1/posts/{rp}", json={"recurrence_time": "09:00", "recurrence_time2": "18:00"})
        row = q("SELECT recurrence_type, recurrence_day, recurrence_time FROM scheduled_posts WHERE id=%s", (rp,))[0]
        T.check("daily -> twice (ertalab va kechqurun)", st == 200 and row[0] == "twice" and row[1] == 1080 and str(row[2]) == "09:00:00", f"{st} {row}")
        T.check("javobda ikkala vaqt", b["post"]["recurrence_time"] == "09:00" and b["post"]["recurrence_time2"] == "18:00", str(b["post"]))
        st, b = call("PATCH", f"/api/v1/posts/{rp}", json={"recurrence_time": "08:00"})
        row = q("SELECT recurrence_type, recurrence_day, recurrence_time FROM scheduled_posts WHERE id=%s", (rp,))[0]
        T.check("twice -> ikkinchi vaqt olib tashlandi: daily", st == 200 and row[0] == "daily" and row[1] is None and str(row[2]) == "08:00:00", f"{st} {row}")
        once = mk()
        st, b = call("PATCH", f"/api/v1/posts/{once}", json={"recurrence_time": "10:00"})
        T.check("bir martalik postda recurrence_time -> 422", st == 422, f"{st} {b}")
        st, b = call("PATCH", f"/api/v1/posts/{rp}", json={"recurrence_time": "25:00"})
        T.check("yaroqsiz vaqt -> 422", st == 422, f"{st} {b}")
        st, b = call("PATCH", f"/api/v1/posts/{rp}", json={"recurrence_time2": "18:00"})
        T.check("recurrence_time2 yolg'iz -> 422", st == 422, f"{st} {b}")

        print("\n== 3. Ro'yxat rasmi (GET /posts/{id}/media) ==")
        ph = mk("photo", "Rasmli", "PH")
        st, body, h = call("GET", f"/api/v1/posts/{ph}/media", raw=True)
        T.check("egasi: JPEG, nosniff, kesh sarlavhasi", st == 200 and body == JPEG and h["Content-Type"] == "image/jpeg"
                and h.get("X-Content-Type-Options") == "nosniff" and "private" in h.get("Cache-Control", ""), f"{st} {h.get('Content-Type')}")
        n_before = len(fetch.calls)
        call("GET", f"/api/v1/posts/{ph}/media", raw=True)
        T.check("ikkinchi so'rov keshdan (Telegram'ga qayta murojaat yo'q)", len(fetch.calls) == n_before, str(fetch.calls))
        st, _b, _h = call("GET", f"/api/v1/posts/{ph}/media", uid=B, raw=True)
        T.check("boshqa foydalanuvchi: 404", st == 404, str(st))
        vid = mk("video", "Video", "VID")
        st, body, h = call("GET", f"/api/v1/posts/{vid}/media", raw=True)
        T.check("video: video/mp4", st == 200 and h["Content-Type"] == "video/mp4", f"{st}")
        doc = mk("document", "Fayl", "DOC")
        st, _b, _h = call("GET", f"/api/v1/posts/{doc}/media", raw=True)
        T.check("rasm/video bo'lmagan hujjat: 404", st == 404, str(st))
        st, _b, _h = call("GET", f"/api/v1/posts/{once}/media", raw=True)
        T.check("matnli post: 404", st == 404, str(st))
        st, b = call("GET", f"/api/v1/posts/{ph}")
        T.check("post javobida file_id YO'Q", "PH" not in str(b) and "file_id" not in str(b), str(b)[:200])

        print("\n== 4. Media almashtirish / olib tashlash ==")
        st, b = call("POST", f"/api/v1/posts/{ph}/media", form=form_file(MP4))
        row = q("SELECT post_type, file_id FROM scheduled_posts WHERE id=%s", (ph,))[0]
        T.check("MP4 bilan almashtirildi: tur video, yangi file_id", st == 200 and row[0] == "video" and row[1] == "NEW_VIDEO", f"{st} {row} {b}")
        T.check("vaqtinchalik xabar o'chirildi (chatda iz yo'q)", len(bot.deleted) >= 1)
        st, b = call("POST", f"/api/v1/posts/{once}/media", form=form_file(JPEG))
        row = q("SELECT post_type, file_id FROM scheduled_posts WHERE id=%s", (once,))[0]
        T.check("matnli postga rasm qo'shildi", st == 200 and row[0] == "photo" and row[1] == "NEW_PHOTO", f"{st} {row}")
        st, b = call("POST", f"/api/v1/posts/{ph}/media", form=form_file(b"zararli fayl"))
        T.check("noma'lum fayl -> 415, post o'zgarmadi", st == 415 and q("SELECT file_id FROM scheduled_posts WHERE id=%s", (ph,))[0][0] == "NEW_VIDEO", f"{st}")
        st, b = call("POST", f"/api/v1/posts/{ph}/media", uid=B, form=form_file(JPEG))
        T.check("boshqa foydalanuvchi: 404", st == 404, f"{st}")
        st, b = call("POST", f"/api/v1/posts/{sent}/media", form=form_file(JPEG))
        T.check("yuborilgan postga media o'zgartirib bo'lmaydi (409)", st == 409, f"{st}")
        st, b = call("DELETE", f"/api/v1/posts/{ph}/media")
        row = q("SELECT post_type, file_id, content FROM scheduled_posts WHERE id=%s", (ph,))[0]
        T.check("media olib tashlandi: oddiy matnli post, matn saqlandi", st == 200 and row[0] == "text" and row[1] is None and row[2] == "Rasmli", f"{st} {row}")
        nomedia_text = mk("photo", "", "PH")
        st, b = call("DELETE", f"/api/v1/posts/{nomedia_text}/media")
        T.check("matni bo'sh postdan media olib tashlanmaydi (bo'sh post bo'lib qolmasin) -> 422", st == 422, f"{st} {b}")
        st, b = call("DELETE", f"/api/v1/posts/{ph}/media", uid=B)
        T.check("DELETE: boshqa foydalanuvchi 404", st == 404, f"{st}")
        st, _b, _h = call("GET", f"/api/v1/posts/{ph}/media", uid=None, raw=True)
        T.check("auth'siz -> 401", st == 401, str(st))
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
