#!/usr/bin/env python3
"""Mini App — Super admin API (real PostgreSQL, soxta Telegram Bot): ruxsat, reklama, majburiy obuna, birja nazorati.

Faqat SINOV bazasi (URL bo'lmasa SKIP). Test o'z qatorlarini (user_id >= 9_600_000_000) yozadi va o'chiradi;
reklama sozlamalari test oxirida qaytariladi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_admin")
if URL:
    os.environ["DATABASE_URL"] = URL
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — SUPER ADMIN API (real PostgreSQL)")
ADM, FIN, USR, OWN = 9_600_000_001, 9_600_000_002, 9_600_000_003, 9_600_000_004
IDS = (ADM, FIN, USR, OWN)
SP_CH = -1009600000001


def main() -> int:
    if not URL:
        T.skip("admin API testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()

    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.admin import AdminApi
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.errors import catalog_codes
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
    old_settings = db.get_ad_settings()

    def cleanup():
        cur.execute("DELETE FROM ad_market_bans WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM ad_market_listings WHERE owner_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM sponsor_channels WHERE channel_id = %s", (str(SP_CH),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    class FakeBot:
        id = 777
        admin_in = True

        async def initialize(self):
            return None

        async def shutdown(self):
            return None

        async def get_chat(self, ref):
            if str(ref) in ("@nosuchch", "@sponsorch", str(SP_CH)):
                if str(ref) == "@nosuchch":
                    from telegram.error import BadRequest
                    raise BadRequest("Chat not found")
                return SimpleNamespace(id=SP_CH, username="sponsorch", title="Homiy kanal", invite_link=None)
            from telegram.error import BadRequest
            raise BadRequest("Chat not found")

        async def get_chat_member(self, chat_id, user_id):
            return SimpleNamespace(status="administrator" if FakeBot.admin_in else "member")

    cleanup()
    try:
        for uid, role in ((ADM, "admin"), (FIN, "finance"), (USR, "user"), (OWN, "user")):
            cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type, role) VALUES (%s,%s,%s,'uz','free',%s)",
                        (uid, f"u{uid}", f"Name{uid}", role))
        cur.execute("INSERT INTO ad_market_listings (owner_id, channel_id, username, title, category, status, members) "
                    "VALUES (%s,'-1009600000009','admlisting','Nazorat kanal','tech','active',1000) RETURNING id", (OWN,))
        lid = cur.fetchone()[0]

        settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
        runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4)
        service = MiniAppService(settings, runner)

        class Null:
            async def hit(self, *a, **k):
                return None

        admin = AdminApi(service, settings, bot_factory=FakeBot)
        api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service, admin=admin)
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)

        async def make_client():
            c = TestClient(TestServer(app))
            await c.start_server()
            return c

        client = run(make_client())

        async def call(method, path, uid, body=None, auth=True):
            headers = {"Authorization": "tma " + make_init_data(uid)} if auth else {}
            r = await client.request(method, "/api/v1" + path, headers=headers, **({"json": body} if body is not None else {}))
            return r.status, await r.json()

        def C(*a, **k):
            return run(call(*a, **k))

        print("\n== 1. Ruxsat ==")
        for code in ("admin_only", "sponsor_not_found", "sponsor_not_admin"):
            T.check(f"xato kodi katalogda: {code}", code in catalog_codes())
        T.check("auth'siz -> 401", C("GET", "/admin/overview", ADM, auth=False)[0] == 401)
        for path in ("/admin/overview", "/admin/ads", "/admin/sponsors", "/admin/market"):
            st, body = C("GET", path, USR)
            T.check(f"oddiy foydalanuvchi {path} -> 403 admin_only", st == 403 and body["error"]["code"] == "admin_only", str(body))
        T.check("oddiy foydalanuvchi yoza olmaydi (POST /admin/ads -> 403)",
                C("POST", "/admin/ads", USR, {"scope": "reply", "text": "x"})[1].get("error", {}).get("code") == "admin_only")
        T.check("/me: is_admin admin uchun True, oddiy uchun False",
                C("GET", "/me", ADM)[1].get("is_admin") is True and C("GET", "/me", USR)[1].get("is_admin") is False)

        print("\n== 2. Umumiy ko'rinish ==")
        st, ov = C("GET", "/admin/overview", ADM)
        T.check("overview: statistika va birja hisobi", st == 200 and "users" in ov["stats"] and ov["market"]["active"] >= 1, str(ov))

        print("\n== 3. Reklama ==")
        st, ads = C("GET", "/admin/ads", ADM)
        T.check("reklama: sozlamalar va ikki ro'yxat", st == 200 and set(ads["items"]) == {"channel", "reply"}, str(ads)[:200])
        st, up = C("PATCH", "/admin/ads/settings", ADM, {"reply_enabled": True, "reply_interval": 7, "channel_interval": 9})
        T.check("sozlamalar saqlandi", st == 200 and up["settings"]["reply"] == {"enabled": True, "interval": 7}
                and up["settings"]["channel"]["interval"] == 9, str(up))
        T.check("interval 0 / 101 / bool / noma'lum kalit -> 422",
                all(C("PATCH", "/admin/ads/settings", ADM, b)[0] == 422 for b in
                    ({"reply_interval": 0}, {"reply_interval": 101}, {"reply_interval": True}, {"x": 1}, {})))
        T.check("enabled bool bo'lmasa -> 422", C("PATCH", "/admin/ads/settings", ADM, {"reply_enabled": "ha"})[0] == 422)
        good = {"scope": "channel", "text": "<b>Reklama</b> matni", "button_text": "Ochish", "button_url": "https://example.com"}
        st, new = C("POST", "/admin/ads", ADM, good)
        aid = new.get("ad", {}).get("id")
        T.check("reklama yaratildi (200/201)", st in (200, 201) and new["ad"]["button_url"] == "https://example.com", str(new))
        T.check("noto'g'ri scope / xavfli teg / javascript: havola / yarim tugma -> 422",
                all(C("POST", "/admin/ads", ADM, b)[0] == 422 for b in
                    ({**good, "scope": "x"}, {**good, "text": "<script>1</script>"},
                     {**good, "button_url": "javascript:alert(1)"}, {**good, "button_url": ""}, {**good, "status": 1})))
        st, upd = C("PATCH", f"/admin/ads/{aid}", ADM, {"text": "Yangi matn", "is_active": False})
        T.check("reklama tahrirlandi va o'chirib qo'yildi", st == 200 and upd["ad"]["text"] == "Yangi matn" and upd["ad"]["is_active"] is False, str(upd))
        T.check("mavjud emas -> 404", C("PATCH", "/admin/ads/99999999", ADM, {"text": "x"})[0] == 404)
        T.check("katta ID -> 4xx (500 emas)", C("PATCH", "/admin/ads/99999999999999999999", ADM, {"text": "x"})[0] in (400, 404, 422))
        st, dl = C("DELETE", f"/admin/ads/{aid}", ADM)
        T.check("reklama o'chirildi, qayta -> 404", st == 200 and C("DELETE", f"/admin/ads/{aid}", ADM)[0] == 404)
        cur.execute("SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id = %s", (ADM,))
        T.check("audit jurnaliga yozildi", cur.fetchone()[0] >= 3)

        print("\n== 4. Majburiy obuna ==")
        T.check("noto'g'ri kanal formati -> 422", C("POST", "/admin/sponsors", ADM, {"channel": "salom dunyo"})[0] == 422)
        T.check("topilmagan kanal -> sponsor_not_found", C("POST", "/admin/sponsors", ADM, {"channel": "@nosuchch"})[1]["error"]["code"] == "sponsor_not_found")
        FakeBot.admin_in = False
        T.check("bot admin emas -> sponsor_not_admin", C("POST", "/admin/sponsors", ADM, {"channel": "@sponsorch"})[1]["error"]["code"] == "sponsor_not_admin")
        FakeBot.admin_in = True
        st, sp = C("POST", "/admin/sponsors", ADM, {"channel": "https://t.me/sponsorch"})
        item = next((i for i in sp.get("items", []) if i["channel_id"] == str(SP_CH)), None)
        T.check("sponsor qo'shildi (t.me havola ham qabul)", st in (200, 201) and item is not None, str(sp))
        st, lst = C("GET", "/admin/sponsors", ADM)
        T.check("ro'yxatda ko'rinadi", st == 200 and any(i["channel_id"] == str(SP_CH) for i in lst["items"]))
        T.check("sponsor o'chirildi; qayta -> 404", C("DELETE", f"/admin/sponsors/{item['id']}", ADM)[0] == 200
                and C("DELETE", f"/admin/sponsors/{item['id']}", ADM)[0] == 404)

        print("\n== 5. Birja nazorati ==")
        st, mk = C("GET", "/admin/market", ADM)
        T.check("nazorat: e'lonlar va hisob", st == 200 and any(i["id"] == lid for i in mk["items"]) and "banned_users" in mk["totals"], str(mk)[:200])
        T.check("noto'g'ri status filtri -> 400", C("GET", "/admin/market?status=zzz", ADM)[0] == 400)
        T.check("moderator huquqi: finance e'lonni blokla olmaydi -> 403",
                C("POST", f"/admin/market/listings/{lid}/status", FIN, {"status": "blocked"})[1].get("error", {}).get("code") == "admin_only")
        T.check("finance ko'ra oladi (GET /admin/market 200)", C("GET", "/admin/market", FIN)[0] == 200)
        T.check("noto'g'ri status -> 422", C("POST", f"/admin/market/listings/{lid}/status", ADM, {"status": "paused"})[0] == 422)
        st, bl = C("POST", f"/admin/market/listings/{lid}/status", ADM, {"status": "blocked"})
        cur.execute("SELECT status FROM ad_market_listings WHERE id = %s", (lid,))
        T.check("e'lon bloklandi", st == 200 and cur.fetchone()[0] == "blocked")
        T.check("mavjud emas e'lon -> 404", C("POST", "/admin/market/listings/99999999/status", ADM, {"status": "active"})[0] == 404)
        st, bn = C("POST", f"/admin/market/users/{OWN}/ban", ADM, {"banned": True})
        cur.execute("SELECT COUNT(*) FROM ad_market_bans WHERE user_id = %s", (OWN,))
        T.check("foydalanuvchi chetlatildi", st == 200 and cur.fetchone()[0] == 1)
        T.check("banned bool bo'lmasa -> 422", C("POST", f"/admin/market/users/{OWN}/ban", ADM, {"banned": "1"})[0] == 422)
        st, ub = C("POST", f"/admin/market/users/{OWN}/ban", ADM, {"banned": False})
        cur.execute("SELECT COUNT(*) FROM ad_market_bans WHERE user_id = %s", (OWN,))
        T.check("chetlatish bekor qilindi", st == 200 and cur.fetchone()[0] == 0)
        run(client.close())
        run(admin.aclose())
    finally:
        try:
            db.set_ad_status(bool(old_settings.get("auto_ad_status", False)))
            db.set_ad_interval(int(old_settings.get("auto_ad_interval", 4)))
            db.set_channel_ad_status(bool(old_settings.get("channel_ad_status", True)))
            db.set_channel_ad_interval(int(old_settings.get("channel_ad_interval", 3)))
        except Exception:  # noqa: BLE001
            pass
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
