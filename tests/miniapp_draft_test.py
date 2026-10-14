#!/usr/bin/env python3
"""Bot -> Mini App qoralamasi: saqlash, o'qish, media bilan rejalashtirish va yuborish (real PostgreSQL + soxta Bot API).

Tekshiriladi: bot tomoni (`build_payload`, `_save_miniapp_draft`, tasdiqlash tugmasi), `GET /draft` (file_id
mijozga CHIQMAYDI), boshqa foydalanuvchi qoralamani ko'rmaydi, `POST /posts use_draft` (media + tugma + HTML
tozalash), HAQIQIY scheduler soxta Telegram'ga sendPhoto yuboradi (file_id va inline tugma bilan), qoralama
o'chadi, qayta ishlatib bo'lmaydi, xavfli tugma havolasi rad etiladi, rasm proksisi (faqat rasm).
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
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_draft")
if URL:
    os.environ["DATABASE_URL"] = URL

from fake_bot_api import TOKEN, FakeBotApi  # noqa: E402
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("BOT -> MINI APP QORALAMA (real PG + soxta Telegram)")
USER, OTHER = 9_700_000_001, 9_700_000_002
CHAN = "-1009700001"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class NullLimiter:
    async def hit(self, bucket, subject, *, limit, window):
        return None


def main() -> int:
    if not URL:
        T.skip("qoralama", "BLOCKED: real PostgreSQL URL (sinov bazasi) yo'q")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    from telegram import Bot

    import database as db
    import scheduler as sched
    from miniapp_api import app as appmod
    from miniapp_api import drafts
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
        q("DELETE FROM miniapp_drafts WHERE user_id = ANY(%s)", ([USER, OTHER],))
        q("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", ([USER, OTHER],))
        q("DELETE FROM channels WHERE user_id = ANY(%s)", ([USER, OTHER],))
        q("DELETE FROM users WHERE user_id = ANY(%s)", ([USER, OTHER],))

    fetched = []

    async def fake_fetch(file_id):
        fetched.append(file_id)
        return JPEG if file_id == "PHOTO_FILE_ID" else b"not an image"

    settings = dataclasses.replace(
        load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                       "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"}), db_queue_wait_seconds=5.0)
    runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4, queue_wait_seconds=5.0)
    service = MiniAppService(settings, runner, invite_only_getter=lambda: False, admin_check=lambda u, r: False)
    api = appmod.build_api_app(settings, runner=runner, limiter=NullLimiter(), clock=lambda: NOW, service=service,
                               writer=PostWriter(service, settings, media_fetch=fake_fetch))
    app = web.Application()
    app.add_subapp(appmod.API_PREFIX, api)

    async def http(method, path, uid=USER, raw=False, **kw):
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            kw["headers"] = {"Authorization": "tma " + make_init_data(uid)}
            resp = await client.request(method, path, **kw)
            if raw:
                return resp.status, await resp.read(), resp.headers
            return resp.status, await resp.json()
        finally:
            await client.close()

    def bot_side():
        ud = {"post_type": "photo", "content": "<b>Salom</b> kanal", "file_id": "PHOTO_FILE_ID",
              "btn_text": "Eski tugma", "btn_url": "https://example.org/x", "enable_reactions": True,
              "reaction_emojis": ["👍", "🔥"], "delete_after_hours": 24, "selected_channel_id": CHAN}
        payload = drafts.build_payload(ud)
        T.check("build_payload: media qoralama to'g'ri tuzildi",
                payload and payload["post_type"] == "photo" and payload["file_id"] == "PHOTO_FILE_ID"
                and payload["channel_id"] == CHAN and payload["reaction_emojis"] == "👍 🔥", str(payload))
        glyph = drafts.build_payload({"post_type": "text", "content": "👍 🔥\n\nSalom kanal", "reaction_emojis": ["👍", "🔥"],
                                      "selected_channel_id": CHAN})
        T.check("build_payload: sizib chiqqan reaksiya emoji prefiksi olib tashlanadi (botdagi saqlash qoidasi)",
                glyph and glyph["content"] == "Salom kanal", str(glyph))
        plain = drafts.build_payload({"post_type": "text", "content": "👍 Zo'r post", "selected_channel_id": CHAN})
        T.check("reaksiya tanlanmagan bo'lsa matn O'ZGARMAYDI", plain and plain["content"] == "👍 Zo'r post", str(plain))
        T.check("build_payload: bo'sh matnli text -> None", drafts.build_payload({"post_type": "text", "content": " "}) is None)
        T.check("build_payload: file_id'siz rasm -> None", drafts.build_payload({"post_type": "photo", "content": "x"}) is None)
        T.check("build_payload: noma'lum tur -> None", drafts.build_payload({"post_type": "zzz", "content": "x"}) is None)
        drafts.save_draft(USER, payload)
        drafts.save_draft(USER, payload)  # upsert: ikkinchi marta ham xato yo'q
        T.check("save_draft: foydalanuvchiga BITTA qator (upsert)",
                q("SELECT COUNT(*) FROM miniapp_drafts WHERE user_id = %s", (USER,))[0][0] == 1)

    async def bot_button():
        from handlers import new_post as np_mod

        class Chat:
            type = "private"

        class Msg:
            chat = Chat()
            chat_id = USER

        class Ctx:
            user_data = {"post_type": "text", "content": "Matn qoralama", "selected_channel_id": CHAN}

        os.environ.pop("MINIAPP_ENABLED", None)
        T.check("Mini App O'CHIQ: tugma ko'rsatilmaydi, qoralama yozilmaydi",
                await np_mod._save_miniapp_draft(Msg(), Ctx()) is None)
        env = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
               "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0",
               "MINIAPP_URL": "https://example.org/app/"}
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            url = await np_mod._save_miniapp_draft(Msg(), Ctx())
            T.check("Mini App yoqilgan: URL qaytadi va qoralama yoziladi",
                    url == "https://example.org/app/"
                    and q("SELECT payload->>'content' FROM miniapp_drafts WHERE user_id = %s", (USER,))[0][0] == "Matn qoralama")
            kb = np_mod._get_confirm_keyboard("uz", miniapp_url=url)
            buttons = [b for row in kb.inline_keyboard for b in row]
            webapp = [b for b in buttons if b.web_app]
            T.check("tasdiqlash tugmalarida web_app tugmasi bor (HTTPS URL)",
                    len(webapp) == 1 and webapp[0].web_app.url == url and len(webapp[0].text) <= 18, str(webapp))
            kb0 = np_mod._get_confirm_keyboard("uz")
            T.check("URL'siz klaviatura O'ZGARMAGAN (web_app yo'q)",
                    not any(b.web_app for row in kb0.inline_keyboard for b in row))
            Msg.chat = type("G", (), {"type": "group"})()
            T.check("guruh chatida tugma yo'q", await np_mod._save_miniapp_draft(Msg(), Ctx()) is None)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    async def scenario():
        drafts.save_draft(USER, drafts.build_payload({
            "post_type": "photo", "content": "<b>Salom</b> kanal", "file_id": "PHOTO_FILE_ID",
            "enable_reactions": False, "selected_channel_id": CHAN}))
        st, d = await http("GET", "/api/v1/draft")
        view = d.get("draft") or {}
        T.check("GET /draft: qoralama qaytdi, media turi photo", st == 200 and view.get("media", {}).get("type") == "photo", str(d))
        T.check("GET /draft: file_id mijozga CHIQMAYDI", "PHOTO_FILE_ID" not in str(d) and "file_id" not in str(d))
        st, d2 = await http("GET", "/api/v1/draft", uid=OTHER)
        T.check("boshqa foydalanuvchi qoralamani KO'RMAYDI", st == 200 and d2["draft"] is None, str(d2))

        st, body, hdrs = await http("GET", "/api/v1/draft/media", raw=True)
        T.check("rasm proksisi: JPEG qaytdi, nosniff", st == 200 and body == JPEG and hdrs["Content-Type"] == "image/jpeg"
                and hdrs.get("X-Content-Type-Options") == "nosniff", f"{st} {hdrs.get('Content-Type')}")
        st, _b, _h = await http("GET", "/api/v1/draft/media", uid=OTHER, raw=True)
        T.check("boshqa foydalanuvchi uchun media 404", st == 404)

        st, e = await http("POST", "/api/v1/posts", json={
            "channel_id": CHAN, "text": "x", "send_now": True, "button_text": "Ochish", "button_url": "javascript:alert(1)"})
        T.check("xavfli tugma havolasi (javascript:) RAD", st == 422 and e["error"]["field"] == "button_url", str(e))
        st, e = await http("POST", "/api/v1/posts", json={
            "channel_id": CHAN, "text": "x", "send_now": True, "button_text": "Ochish"})
        T.check("faqat tugma matni (havolasiz) RAD", st == 422, str(e))
        st, e = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "x", "send_now": True, "use_draft": "ha"})
        T.check("use_draft bool bo'lmasa RAD", st == 422)
        st, e = await http("POST", "/api/v1/posts", uid=OTHER, json={
            "channel_id": CHAN, "text": "x", "send_now": True, "use_draft": True})
        T.check("boshqa foydalanuvchi: kanal unga tegishli emas (404)", st == 404, str(e))

        st, created = await http("POST", "/api/v1/posts", json={
            "channel_id": CHAN, "text": "<b>Salom</b> kanal <script>x</script>", "send_now": True, "use_draft": True,
            "button_text": "Ochish", "button_url": "https://example.org/go"})
        T.check("use_draft bilan post yaratildi (201)", st == 201, str(created))
        pid = created["post"]["id"]
        row = q("SELECT post_type, file_id, content, inline_button_text, inline_button_url FROM scheduled_posts WHERE id = %s", (pid,))[0]
        T.check("DB: tur=photo, file_id qoralamadan (mijoz yubormagan)", row[0] == "photo" and row[1] == "PHOTO_FILE_ID", str(row))
        T.check("DB: HTML matn o'zgarishsiz saqlandi (tozalash yuborish paytida)", "<b>Salom</b>" in row[2], row[2])
        T.check("DB: inline tugma saqlandi", row[3] == "Ochish" and row[4] == "https://example.org/go", str(row))
        T.check("ishlatilgan qoralama O'CHIRILDI",
                q("SELECT COUNT(*) FROM miniapp_drafts WHERE user_id = %s", (USER,))[0][0] == 0)
        st, e = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "yana", "send_now": True, "use_draft": True})
        T.check("qoralama qayta ishlatilmaydi: 404 draft_not_found", st == 404 and e["error"]["code"] == "draft_not_found", str(e))

        fake = FakeBotApi()
        base = await fake.start()
        bot = Bot(TOKEN, base_url=base)
        await bot.initialize()
        try:
            await sched.check_and_send_posts(bot)
            photos = fake.calls_of("sendPhoto")
            T.check("scheduler AYNAN 1 ta sendPhoto yubordi", len(photos) == 1, str(len(photos)))
            if photos:
                p = photos[0]
                T.check("sendPhoto: to'g'ri kanal va file_id", str(p.get("chat_id")) == CHAN and p.get("photo") == "PHOTO_FILE_ID", str(p))
                T.check("sendPhoto: inline tugma (reply_markup) yuborildi", "Ochish" in str(p.get("reply_markup")) and "example.org/go" in str(p.get("reply_markup")), str(p.get("reply_markup")))
                T.check("sendPhoto: sarlavha HTML sifatida, <script> yuborilmadi",
                        "Salom" in str(p.get("caption")) and p.get("parse_mode") == "HTML" and "<script" not in str(p.get("caption")),
                        str(p.get("caption")))
            T.check("DB: post yuborildi", q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0] in ("posted", "published"))
        finally:
            await bot.shutdown()
            await fake.stop()

        # matnli qoralama + o'chirish
        drafts.save_draft(USER, drafts.build_payload({"post_type": "text", "content": "Faqat matn", "selected_channel_id": CHAN}))
        st, body, _h = await http("GET", "/api/v1/draft/media", raw=True)
        T.check("matnli qoralamada media yo'q: 404", st == 404)
        st, d = await http("DELETE", "/api/v1/draft")
        T.check("DELETE /draft: qoralama o'chirildi", st == 200 and q("SELECT COUNT(*) FROM miniapp_drafts WHERE user_id = %s", (USER,))[0][0] == 0)

        # muddati o'tgan qoralama ko'rinmaydi
        drafts.save_draft(USER, drafts.build_payload({"post_type": "text", "content": "Eski", "selected_channel_id": CHAN}))
        q("UPDATE miniapp_drafts SET updated_at = NOW() - INTERVAL '3 days' WHERE user_id = %s", (USER,))
        st, d = await http("GET", "/api/v1/draft")
        T.check("48 soatdan eski qoralama ko'rinmaydi", st == 200 and d["draft"] is None, str(d))
        # rasm bo'lmagan baytlar
        drafts.save_draft(USER, drafts.build_payload({"post_type": "photo", "content": "", "file_id": "BAD", "selected_channel_id": CHAN}))
        st, _b, _h = await http("GET", "/api/v1/draft/media", raw=True)
        T.check("rasm bo'lmagan baytlar (sniff) -> 404, aynan o'sha ma'lumot berilmaydi", st == 404)
        # media qoralama + bo'sh matn (sarlavhasiz rasm)
        drafts.save_draft(USER, drafts.build_payload({"post_type": "photo", "content": "", "file_id": "PHOTO_FILE_ID", "selected_channel_id": CHAN}))
        st, c2 = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "", "send_now": True, "use_draft": True})
        T.check("sarlavhasiz rasm posti yaratildi", st == 201, str(c2))
        st, e = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "", "send_now": True})
        T.check("use_draft'siz bo'sh matn RAD", st == 422)

        # AUDIT-013: media sarlavhasi (caption) 1024 dan oshsa jimgina kesilmaydi, aniq xato
        drafts.save_draft(USER, drafts.build_payload({"post_type": "photo", "content": "", "file_id": "PHOTO_FILE_ID", "selected_channel_id": CHAN}))
        before = q("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s", (USER,))[0][0]
        st, e = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "a" * 1025, "send_now": True, "use_draft": True})
        T.check("media + 1025 belgi: 422 caption_too_long (field=text)", st == 422 and e["error"]["code"] == "caption_too_long" and e["error"]["field"] == "text", str(e))
        T.check("rad etilganda post yaratilmadi va qoralama saqlanib qoldi",
                q("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s", (USER,))[0][0] == before
                and q("SELECT COUNT(*) FROM miniapp_drafts WHERE user_id = %s", (USER,))[0][0] == 1)
        st, c3 = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "b" * 1024, "send_now": True, "use_draft": True})
        T.check("media + 1024 belgi: qabul qilinadi (201)", st == 201, str(c3))
        media_id = c3["post"]["id"]
        st, e = await http("PATCH", f"/api/v1/posts/{media_id}", json={"text": "c" * 1025})
        T.check("media postni tahrirlash: 1025 belgi RAD (caption_too_long)", st == 422 and e["error"]["code"] == "caption_too_long", str(e))
        st, e = await http("PATCH", f"/api/v1/posts/{media_id}", json={"text": "c" * 1024})
        T.check("media postni tahrirlash: 1024 belgi qabul", st == 200, str(e))
        st, t1 = await http("POST", "/api/v1/posts", json={"channel_id": CHAN, "text": "t" * 4096, "send_now": True})
        T.check("MATNLI post: 4096 belgi hamon qabul (chegara faqat media uchun)", st == 201, str(t1))
        st, e = await http("PATCH", f"/api/v1/posts/{t1['post']['id']}", json={"text": "u" * 4096})
        T.check("matnli postni tahrirlash: 4096 belgi qabul", st == 200, str(e))

    cleanup()
    try:
        for uid in (USER, OTHER):
            q("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,'uz','free')", (uid, f"d{uid}", f"N{uid}"))
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s,%s,'Qoralama kanal',TRUE)", (USER, CHAN))
        bot_side()
        loop.run_until_complete(asyncio.wait_for(bot_button(), 60))
        loop.run_until_complete(asyncio.wait_for(scenario(), 120))
    finally:
        cleanup()
        conn.close()
    _ = (datetime, timedelta, timezone)
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
