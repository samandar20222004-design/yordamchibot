#!/usr/bin/env python3
"""Mini App — albom (10 tagacha media): qo'shish, bittasini olib tashlash, element bo'yicha ko'rinish.

* ``media_items`` sof amallari (DB'siz): pack/add/remove, 10 chegarasi, aralash tur qoidalari;
* POST ?add=1 / DELETE ?i= / GET ?i= — rejalangan post va qoralama uchun (real PostgreSQL, faqat sinov bazasi);
* 11-chi fayl, GIF/aralash tur Telegram'ga YUKLASHDAN OLDIN rad etiladi (bot.sent o'zgarmaydi).
"""
from __future__ import annotations

import asyncio
import dataclasses
import json
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

T = Counter("MINI APP — albom (real PostgreSQL)")
A, B = 9_300_000_071, 9_300_000_072
CH = "-1009300071"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200


class NullLimiter:
    async def hit(self, *a, **k):
        return None


GIF = b"GIF89a" + b"\x00" * 100


class FakeBot:
    def __init__(self):
        self.sent, self.deleted = [], []

    async def send_photo(self, chat_id, photo, **kw):
        from types import SimpleNamespace as NS
        self.sent.append(("photo", chat_id))
        return NS(message_id=1, photo=[NS(file_id="S"), NS(file_id=f"P{len(self.sent)}")])

    async def send_video(self, chat_id, video, **kw):
        from types import SimpleNamespace as NS
        self.sent.append(("video", chat_id))
        return NS(message_id=2, video=NS(file_id=f"V{len(self.sent)}"))

    async def send_animation(self, chat_id, animation, **kw):
        from types import SimpleNamespace as NS
        self.sent.append(("animation", chat_id))
        return NS(message_id=3, animation=NS(file_id=f"G{len(self.sent)}"))

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class Fetch:
    def __init__(self, bot):
        self.bot, self.calls = bot, []

    async def get_bot(self):
        return self.bot

    async def __call__(self, file_id):
        self.calls.append(file_id)
        return MP4 if file_id.startswith("V") or file_id == "VID" else (JPEG if file_id.startswith("P") or file_id == "PH" else b"not media")


def main() -> int:
    from miniapp_api import media_items as mi
    from miniapp_api.errors import ApiError

    print("\n== 1. media_items: sof amallar ==")
    T.check("matn: bo'sh ro'yxat", mi.items_of("text", None) == [] and mi.pack([]) == ("text", None))
    T.check("yakka media: bitta element", mi.items_of("photo", "A") == [{"type": "photo", "file_id": "A", "caption": ""}])
    pt, fid = mi.add_item("photo", "A", "video", "B")
    T.check("yakka + yangi = albom (2)", pt == "album" and [i["file_id"] for i in mi.items_of(pt, fid)] == ["A", "B"])
    T.check("1 ta qolsa yana yakka media", mi.remove_item(pt, fid, 0) == ("video", "B"))
    T.check("oxirgisi olib tashlansa matnli post", mi.remove_item("photo", "A", 0) == ("text", None))
    pt, fid = "photo", "F0"
    for n in range(1, 10):
        pt, fid = mi.add_item(pt, fid, "photo", f"F{n}")
    T.check("10 ta albom", len(mi.items_of(pt, fid)) == 10)
    for label, args in (("11-chi fayl", (pt, fid, "photo", "X")), ("GIF albomga", ("photo", "A", "animation", "G")),
                        ("albom + hujjat", ("photo", "A", "document", "D")), ("GIF ustiga rasm", ("animation", "G", "photo", "A"))):
        try:
            mi.add_item(*args)
            T.check(f"{label}: rad etiladi", False)
        except ApiError as exc:
            T.check(f"{label}: rad etiladi ({exc.code})", exc.code in ("album_full", "album_mixed"))
    T.check("botning albom formati (caption bilan) saqlanadi", mi.items_of("album", '[{"type":"photo","file_id":"A","caption":"c"},{"type":"video","file_id":"B"}]')[0]["caption"] == "c")
    T.check("public_items: file_id YO'Q", "file_id" not in str(mi.public_items(pt, fid)))
    T.check("file_id_at: aniq o'rin / birinchi ko'rinadigan", mi.file_id_at(pt, fid, 3) == "F3" and mi.file_id_at("album", '[{"type":"audio","file_id":"A"},{"type":"photo","file_id":"B"}]') == "B")
    T.check("parse_index: 0..9, yaroqsiz -> bad_request", mi.parse_index("3") == 3 and mi.parse_index(None) is None)
    for bad in ("10", "-1", "x"):
        try:
            mi.parse_index(bad)
            T.check(f"parse_index({bad}) rad", False)
        except ApiError:
            T.check(f"parse_index({bad}) rad", True)

    if not URL:
        T.skip("albom HTTP", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
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

        print("\n== 2. Rejalangan post: albom qo'shish / olib tashlash ==")
        pid = mk("photo", "Albom sarlavhasi", "PH")
        st, b = call("POST", f"/api/v1/posts/{pid}/media?add=1", form=form_file(JPEG))
        row = q("SELECT post_type, file_id FROM scheduled_posts WHERE id=%s", (pid,))[0]
        T.check("rasm qo'shildi: albom (2), matn saqlandi", st == 200 and row[0] == "album" and len(json.loads(row[1])) == 2, f"{st} {row}")
        T.check("javobda media_items (file_id yo'q)", len(b["post"]["media_items"]) == 2 and "file_id" not in str(b), str(b)[:200])
        st, b = call("POST", f"/api/v1/posts/{pid}/media?add=1", form=form_file(MP4))
        T.check("video qo'shildi (rasm+video aralash mumkin): 3 ta", st == 200 and len(b["post"]["media_items"]) == 3, f"{st}")
        for _ in range(7):
            call("POST", f"/api/v1/posts/{pid}/media?add=1", form=form_file(JPEG))
        row = q("SELECT file_id FROM scheduled_posts WHERE id=%s", (pid,))[0]
        T.check("10 taga to'ldirildi", len(json.loads(row[0])) == 10)
        n_sent = len(bot.sent)
        st, b = call("POST", f"/api/v1/posts/{pid}/media?add=1", form=form_file(JPEG))
        T.check("11-chi fayl: 422 album_full, Telegram'ga yuklanmadi", st == 422 and b["error"]["code"] == "album_full" and len(bot.sent) == n_sent, f"{st} {b}")
        st, b = call("POST", f"/api/v1/posts/{pid}/media?add=1", form=form_file(GIF))
        T.check("to'liq albomga GIF: album_full/album_mixed, yuklanmadi", st == 422 and len(bot.sent) == n_sent, f"{st} {b}")
        st, body, h = call("GET", f"/api/v1/posts/{pid}/media?i=3", raw=True)
        T.check("GET ?i=3: shu elementning baytlari", st == 200 and (body in (JPEG, MP4)), f"{st}")
        st, _b, _h = call("GET", f"/api/v1/posts/{pid}/media?i=10", raw=True)
        T.check("?i=10 -> 400", st == 400, str(st))
        st, _b, _h = call("GET", f"/api/v1/posts/{pid}/media?i=x", raw=True)
        T.check("?i=x -> 400", st == 400, str(st))
        st, _b, _h = call("GET", f"/api/v1/posts/{pid}/media?i=3", uid=B, raw=True)
        T.check("boshqa foydalanuvchi: 404", st == 404, str(st))
        st, b = call("DELETE", f"/api/v1/posts/{pid}/media?i=0")
        T.check("bittasi olib tashlandi: 9 ta", st == 200 and len(b["post"]["media_items"]) == 9, f"{st} {b}")
        st, b = call("DELETE", f"/api/v1/posts/{pid}/media?i=9")
        T.check("mavjud bo'lmagan o'rin -> 404", st == 404, f"{st}")
        st, b = call("DELETE", f"/api/v1/posts/{pid}/media?i=0", uid=B)
        T.check("DELETE ?i: boshqa foydalanuvchi 404", st == 404, f"{st}")
        for _ in range(8):
            st, b = call("DELETE", f"/api/v1/posts/{pid}/media?i=0")
        row = q("SELECT post_type, file_id, content FROM scheduled_posts WHERE id=%s", (pid,))[0]
        T.check("1 ta qolsa yana yakka media, matn saqlandi", row[0] in ("photo", "video") and not row[1].startswith("[") and row[2] == "Albom sarlavhasi", f"{row}")
        st, b = call("DELETE", f"/api/v1/posts/{pid}/media?i=0")
        row = q("SELECT post_type, file_id FROM scheduled_posts WHERE id=%s", (pid,))[0]
        T.check("oxirgisi olib tashlansa oddiy matnli post", st == 200 and row[0] == "text" and row[1] is None, f"{st} {row}")
        gp = mk("animation", "GIF", "G1")
        st, b = call("POST", f"/api/v1/posts/{gp}/media?add=1", form=form_file(JPEG))
        T.check("GIF ustiga rasm qo'shilmaydi (album_mixed)", st == 422 and b["error"]["code"] == "album_mixed", f"{st} {b}")
        sent = mk("photo", "Yuborilgan", "PH", status="posted")
        st, b = call("POST", f"/api/v1/posts/{sent}/media?add=1", form=form_file(JPEG))
        T.check("yuborilgan postga qo'shib bo'lmaydi (409)", st == 409, f"{st}")

        print("\n== 3. Qoralama (bot -> Mini App): albom ==")
        from miniapp_api import drafts

        def draft_payload(post_type, file_id, content="Qoralama"):
            return {"post_type": post_type, "content": content, "file_id": file_id, "btn_text": None, "btn_url": None,
                    "enable_reactions": False, "reaction_emojis": None, "delete_after_hours": 0, "channel_id": CH}

        drafts.save_draft(A, draft_payload("photo", "PH"))
        st, b = call("POST", "/api/v1/draft/media?add=1", form=form_file(MP4))
        m = b["draft"]["media"]
        T.check("qoralamaga qo'shildi: albom, 2 element, matn saqlandi", st == 200 and m["type"] == "album" and m["count"] == 2
                and len(m["items"]) == 2 and b["draft"]["text"] == "Qoralama" and "file_id" not in str(b), f"{st} {b}")
        st, body, _h = call("GET", "/api/v1/draft/media?i=1", raw=True)
        T.check("GET /draft/media?i=1: 2-element baytlari (video)", st == 200 and body == MP4, f"{st}")
        st, b = call("POST", "/api/v1/draft/media", form=form_file(JPEG))
        T.check("?add yo'q: ESKI xulq — butun media almashtiriladi (yakka rasm)", st == 200 and b["draft"]["media"]["type"] == "photo", f"{st} {b}")
        call("POST", "/api/v1/draft/media?add=1", form=form_file(JPEG))
        st, b = call("DELETE", "/api/v1/draft/media?i=0")
        T.check("DELETE /draft/media?i=0: albom qisqardi (yakka)", st == 200 and b["draft"]["media"]["type"] == "photo", f"{st} {b}")
        st, b = call("DELETE", "/api/v1/draft/media")
        T.check("?i yo'q -> 400", st == 400, f"{st} {b}")
        st, b = call("DELETE", "/api/v1/draft/media?i=0")
        T.check("oxirgi media olib tashlandi, matn bor: matnli qoralama", st == 200 and b["draft"]["media"] is None and b["draft"]["text"] == "Qoralama", f"{st} {b}")
        drafts.save_draft(A, draft_payload("photo", "PH", content=""))
        st, b = call("DELETE", "/api/v1/draft/media?i=0")
        T.check("media ham, matn ham bo'sh: qoralama o'chadi", st == 200 and b["draft"] is None and call("GET", "/api/v1/draft")[1]["draft"] is None, f"{st} {b}")
        st, b = call("DELETE", "/api/v1/draft/media?i=0", uid=B)
        T.check("qoralamasiz foydalanuvchi: 404", st == 404, f"{st} {b}")
        st, _b, _h = call("DELETE", "/api/v1/draft/media?i=0", uid=None, raw=True)
        T.check("auth'siz -> 401", st == 401, str(st))
    finally:
        cleanup()
        q("DELETE FROM miniapp_drafts WHERE user_id = ANY(%s)", ([A, B],))
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
