#!/usr/bin/env python3
"""Mini App — qurilmadan media yuklash (`POST /api/v1/draft/media`) (real PostgreSQL, faqat sinov bazasi).

* tur BAYTLARDAN aniqlanadi (Content-Type yolg'on bo'lsa ham); noma'lum/zararli fayl -> 415; hajm chegarasi -> 413;
* Telegram'ga foydalanuvchining O'Z chatiga yuboriladi va darhol o'chiriladi; file_id mijozga qaytmaydi;
* mavjud qoralamaning sozlamalari (reaksiya, avto-o'chirish, kanal) saqlanadi; matn/tugma formadan yangilanadi;
* Telegram xatosi -> 503 upload_failed, qoralama o'zgarmaydi; yuklangan media bilan post yaratiladi.
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

T = Counter("MINI APP — media yuklash (real PostgreSQL)")
A = 9_300_000_031
CH = "-1009300031"


class NullLimiter:
    async def hit(self, *a, **k):
        return None

class FakeBot:
    def __init__(self):
        self.sent, self.deleted, self.fail = [], [], False

    async def _send(self, kind, chat_id, data, **kw):
        if self.fail:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.sent.append((kind, chat_id, len(data)))
        mid = 1000 + len(self.sent)
        from types import SimpleNamespace as NS
        if kind == "photo":
            return NS(message_id=mid, photo=[NS(file_id="SMALL"), NS(file_id="PHOTO_FILE_ID")])
        if kind == "video":
            return NS(message_id=mid, video=NS(file_id="VIDEO_FILE_ID"))
        return NS(message_id=mid, animation=NS(file_id="GIF_FILE_ID"))

    async def send_photo(self, chat_id, photo, **kw):
        return await self._send("photo", chat_id, photo)

    async def send_video(self, chat_id, video, **kw):
        return await self._send("video", chat_id, video)

    async def send_animation(self, chat_id, animation, **kw):
        return await self._send("animation", chat_id, animation)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


class FakeFetch:
    def __init__(self, bot):
        self.bot = bot

    async def get_bot(self):
        return self.bot

    async def __call__(self, file_id):
        raise RuntimeError("kerak emas")


JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200
GIF = b"GIF89a" + b"\x00" * 100


def main() -> int:
    if not URL:
        T.skip("real PostgreSQL media yuklash testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import aiohttp
    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api import writes
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
        q("DELETE FROM scheduled_posts WHERE user_id = %s", (A,))
        q("DELETE FROM miniapp_drafts WHERE user_id = %s", (A,))
        q("DELETE FROM channels WHERE user_id = %s", (A,))
        q("DELETE FROM users WHERE user_id = %s", (A,))

    settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                              "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    settings = dataclasses.replace(settings, db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner)
    bot = FakeBot()
    writer = PostWriter(service, settings, media_fetch=FakeFetch(bot))
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW,
                               service=service, writer=writer)
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    def upload(data, fields=None, ctype="image/jpeg", uid=A, filename="f.bin", raw_headers=None):
        async def go():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                form = aiohttp.FormData()
                for k, v in (fields or {}).items():
                    form.add_field(k, v, content_type="text/plain; charset=utf-8")
                if data is not None:
                    form.add_field("file", data, filename=filename, content_type=ctype)
                headers = {"Authorization": "tma " + make_init_data(uid)} if uid else {}
                headers.update(raw_headers or {})
                r = await client.post("/api/v1/draft/media", data=form, headers=headers)
                try:
                    return r.status, await r.json()
                except Exception:  # noqa: BLE001
                    return r.status, None
            finally:
                await client.close()

        return loop.run_until_complete(go())

    def get_draft():
        async def go():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                r = await client.get("/api/v1/draft", headers={"Authorization": "tma " + make_init_data(A)})
                return await r.json()
            finally:
                await client.close()

        return loop.run_until_complete(go())

    def raw():
        r = q("SELECT payload FROM miniapp_drafts WHERE user_id = %s", (A,))
        return r[0][0] if r else None

    cleanup()
    try:
        q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,'u','N','uz','free')", (A,))
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'Kanal',TRUE)", (A, CH))

        print("\n== 1. Rasm ==")
        st, b = upload(JPEG, {"text": "Sarlavha <b>x</b>"})
        d = b.get("draft") or {}
        T.check("200; draft.media.type=photo, previewable, matn saqlandi", st == 200 and d.get("media", {}).get("type") == "photo"
                and d["media"]["previewable"] is True and d["text"] == "Sarlavha <b>x</b>", f"{st} {b}")
        T.check("javobda file_id YO'Q", "PHOTO_FILE_ID" not in json.dumps(b))
        T.check("bazada file_id saqlandi, post_type=photo", raw()["file_id"] == "PHOTO_FILE_ID" and raw()["post_type"] == "photo")
        T.check("Telegram'ga foydalanuvchining O'Z chatiga yuborildi va xabar o'chirildi",
                bot.sent[-1][:2] == ("photo", A) and bot.deleted[-1][0] == A, str((bot.sent, bot.deleted)))

        print("\n== 2. Qoralama sozlamalari saqlanadi ==")
        q("UPDATE miniapp_drafts SET payload = payload || %s::jsonb WHERE user_id = %s",
          (json.dumps({"enable_reactions": True, "reaction_emojis": "👍 🔥", "delete_after_hours": 24, "channel_id": CH}), A))
        st, b = upload(PNG, {"text": "Yangi", "button_text": "Ochish", "button_url": "https://example.com"}, ctype="application/octet-stream")
        r = raw()
        T.check("PNG: Content-Type yolg'on bo'lsa ham baytdan aniqlandi; sozlamalar (reaksiya/avto-o'chirish/kanal) saqlandi",
                st == 200 and r["post_type"] == "photo" and r["enable_reactions"] is True and r["delete_after_hours"] == 24
                and r["channel_id"] == CH and r["btn_text"] == "Ochish" and r["content"] == "Yangi", f"{st} {r}")
        st, b = upload(PNG)
        T.check("formada matn yo'q bo'lsa mavjud matn/tugma saqlanadi", st == 200 and raw()["content"] == "Yangi" and raw()["btn_url"] == "https://example.com", str(raw()))

        print("\n== 3. Video va GIF ==")
        st, b = upload(MP4, ctype="video/mp4")
        T.check("MP4 -> video, previewable=False", st == 200 and b["draft"]["media"]["type"] == "video" and b["draft"]["media"]["previewable"] is False
                and raw()["file_id"] == "VIDEO_FILE_ID", f"{st} {b}")
        st, b = upload(GIF, ctype="image/gif")
        T.check("GIF -> animation", st == 200 and raw()["post_type"] == "animation" and raw()["file_id"] == "GIF_FILE_ID")

        print("\n== 4. Rad etiladiganlar (Telegram'ga umuman yuborilmaydi) ==")
        before = len(bot.sent)
        for label, data, kw, code in (
            ("HTML/skript (rasm deb yuborilgan)", b"<script>alert(1)</script>" * 10, {"ctype": "image/jpeg"}, 415),
            ("EXE", b"MZ\x90\x00" + b"\x00" * 100, {"ctype": "image/png"}, 415),
            ("bo'sh fayl", b"", {}, 422),
            ("fayl yo'q", None, {"fields": {"text": "x"}}, 422),
            ("rasm > 10 MB", JPEG + b"\x00" * (writes.MAX_UPLOAD_PHOTO + 10), {}, 413),
            ("sarlavha > 1024", JPEG, {"fields": {"text": "x" * 1025}}, 422),
            ("noto'g'ri tugma havolasi", JPEG, {"fields": {"button_text": "t", "button_url": "javascript:alert(1)"}}, 422),
        ):
            st, b = upload(data, **kw)
            T.check(f"{label} -> {code}", st == code, f"{st} {b}")
        T.check("rad etilganlarda Telegram'ga hech narsa yuborilmadi", len(bot.sent) == before)
        st, b = upload(JPEG, raw_headers={"X-Nothing": "1"}, uid=None)
        T.check("autentifikatsiyasiz -> 401", st == 401)

        print("\n== 5. Telegram xatosi ==")
        snap = raw()
        bot.fail = True
        st, b = upload(JPEG, {"text": "o'zgarmasin"})
        T.check("503 upload_failed, qoralama O'ZGARMADI", st == 503 and b["error"]["code"] == "upload_failed" and raw() == snap, f"{st} {b}")
        bot.fail = False

        print("\n== 6. Yuklangan media bilan post ==")
        st, _ = upload(JPEG, {"text": "Media post"})
        async def post():
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                r = await client.post("/api/v1/posts", headers={"Authorization": "tma " + make_init_data(A)},
                                      json={"channel_id": CH, "text": "Media post", "send_now": True, "use_draft": True})
                return r.status, await r.json()
            finally:
                await client.close()

        st, b = loop.run_until_complete(post())
        rows = q("SELECT post_type, file_id, content FROM scheduled_posts WHERE user_id = %s", (A,))
        T.check("post yaratildi: post_type=photo, file_id=Telegram file_id, sarlavha", st in (200, 201) and rows == [("photo", "PHOTO_FILE_ID", "Media post")], f"{st} {rows}")
        T.check("post yaratilgach qoralama o'chdi", get_draft()["draft"] is None)
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
