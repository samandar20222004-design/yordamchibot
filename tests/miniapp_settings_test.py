#!/usr/bin/env python3
"""Mini App — profil sozlamalari: bildirishnomalar (user_settings) va til; PATCH /me/settings.

* kalitlar/standartlar botdagi ``handlers.settings`` bilan MOS (drift bo'lsa test yiqiladi);
* GET /me ``settings.notifications`` qaytaradi (saqlanmagan kalit uchun standart);
* PATCH: faqat ruxsat etilgan kalitlar va bool qiymatlar; til bilan birga ham; noma'lum kalit / bo'sh tana -> 422.
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

T = Counter("MINI APP — sozlamalar (real PostgreSQL)")
A, B = 9_300_000_081, 9_300_000_082
CH = "-1009300081"
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
    from miniapp_api import prefs

    print("\n== 1. Kalitlar botdagi bilan mos ==")
    try:
        from handlers.settings import NOTIF_SETTING_KEYS, SETTING_DEFAULTS
        T.check("bildirishnoma kalitlari botniki bilan bir xil", tuple(NOTIF_SETTING_KEYS) == prefs.NOTIFICATION_KEYS, str(tuple(NOTIF_SETTING_KEYS)))
        T.check("standart qiymatlar botniki bilan bir xil", all(SETTING_DEFAULTS[k] == prefs.NOTIFICATION_DEFAULTS[k] for k in prefs.NOTIFICATION_KEYS))
    except ImportError as exc:
        T.skip("bot bilan moslik", f"handlers.settings import qilinmadi: {exc}")
    T.check("imzo/tozalash kalitlari Mini App'da YO'Q", not any(k.startswith("post_") for k in prefs.NOTIFICATION_KEYS))

    if not URL:
        T.skip("sozlamalar HTTP", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
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

    cleanup()
    try:
        q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,'a','A','uz','pro'),(%s,'b','B','uz','free')", (A, B))
        print("\n== 2. GET /me: bildirishnomalar ==")
        st, b = call("GET", "/api/v1/me")
        T.check("saqlanmagan: standart qiymatlar", st == 200 and b["settings"]["notifications"] == prefs.NOTIFICATION_DEFAULTS, f"{st} {b.get('settings')}")

        print("\n== 3. PATCH /me/settings ==")
        st, b = call("PATCH", "/api/v1/me/settings", json={"notifications": {"notify_news": True, "notify_scheduled": False}})
        T.check("ikkita kalit yangilandi", st == 200 and b["notifications"] == {"notify_news": True, "notify_scheduled": False}, f"{st} {b}")
        rows = dict(q("SELECT key, value FROM user_settings WHERE user_id=%s", (A,)))
        T.check("user_settings'ga yozildi (bot bilan umumiy jadval)", rows == {"notify_news": True, "notify_scheduled": False}, str(rows))
        st, b = call("GET", "/api/v1/me")
        T.check("/me yangi qiymatlarni qaytaradi (qolganlari standart)", b["settings"]["notifications"] == {**prefs.NOTIFICATION_DEFAULTS, "notify_news": True, "notify_scheduled": False})
        st, b = call("PATCH", "/api/v1/me/settings", json={"language": "ru", "notifications": {"notify_news": False}})
        T.check("til + bildirishnoma bir so'rovda", st == 200 and b == {"language": "ru", "notifications": {"notify_news": False}}, f"{st} {b}")
        st, b = call("PATCH", "/api/v1/me/settings", json={"language": "en"})
        T.check("faqat til: eski javob shakli", st == 200 and b == {"language": "en"}, f"{st} {b}")
        for label, body in (("noma'lum kalit (post_signature)", {"notifications": {"post_signature": True}}),
                            ("bool emas", {"notifications": {"notify_news": "yes"}}),
                            ("1 (int)", {"notifications": {"notify_news": 1}}),
                            ("bo'sh obyekt", {"notifications": {}}),
                            ("ro'yxat", {"notifications": ["notify_news"]}),
                            ("noma'lum maydon", {"role": "admin"}),
                            ("bo'sh tana", {}),
                            ("yaroqsiz til", {"language": "xx"})):
            st, b = call("PATCH", "/api/v1/me/settings", json=body)
            T.check(f"yaroqsiz ({label}) -> 422", st == 422, f"{st} {b}")
        T.check("yaroqsiz so'rovlar hech narsani o'zgartirmadi", dict(q("SELECT key, value FROM user_settings WHERE user_id=%s", (A,))) ==
                {"notify_news": False, "notify_scheduled": False})
        st, b = call("PATCH", "/api/v1/me/settings", uid=B, json={"notifications": {"notify_news": True}})
        T.check("boshqa foydalanuvchi o'z sozlamasini o'zgartiradi, A'nikiga TEGMAYDI", st == 200
                and dict(q("SELECT key, value FROM user_settings WHERE user_id=%s", (A,))) == {"notify_news": False, "notify_scheduled": False}
                and dict(q("SELECT key, value FROM user_settings WHERE user_id=%s", (B,))) == {"notify_news": True})
        st, _b = call("PATCH", "/api/v1/me/settings", uid=None, json={"notifications": {"notify_news": True}})
        T.check("auth'siz -> 401", st == 401, str(st))
    finally:
        q("DELETE FROM user_settings WHERE user_id = ANY(%s)", ([A, B],))
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
