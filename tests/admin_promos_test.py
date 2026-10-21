#!/usr/bin/env python3
"""Admin: promo-kod ro'yxati (ishlatilgan/qolgan), tafsilot, o'chirish/yoqish, tarif berish, tizim va rollar — bot matnlari va Mini App API.

DB'siz qism: matn quruvchilar, 3 til, buyruqlar. Real PostgreSQL qismi (``MINIAPP_TEST_DATABASE_URL`` — FAQAT sinov bazasi; URL bo'lmasa SKIP):
test o'z promo-kodlarini ``ZT_`` prefiksi bilan yozadi va o'chiradi.
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
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_admin_promos")
if URL:
    os.environ["DATABASE_URL"] = URL
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("ADMIN PROMO-KODLAR VA BUYRUQLAR")
ADM, FIN, USR, OWN, TGT = 9_700_000_001, 9_700_000_002, 9_700_000_003, 9_700_000_004, 9_700_000_005
IDS = (ADM, FIN, USR, OWN, TGT)


def offline() -> None:
    print("\n== A. Matnlar va buyruqlar (DB'siz) ==")
    from handlers import admin_promos as AP
    from translations.admin_panel import admin_panel_parity_report

    T.check("admin_panel uz/ru/en pariteti", admin_panel_parity_report()["in_sync"])
    items = [
        {"code": "A1", "plan_type": "pro", "duration_days": 30, "max_uses": 50, "current_uses": 12, "remaining_uses": 38,
         "is_active": True, "status": "active", "expires_at": None, "created_at": None},
        {"code": "B<2>", "plan_type": "ultra", "duration_days": 10, "max_uses": None, "current_uses": 3, "remaining_uses": None,
         "is_active": True, "status": "active", "expires_at": None, "created_at": None},
        {"code": "C3", "plan_type": "pro", "duration_days": 5, "max_uses": 5, "current_uses": 5, "remaining_uses": 0,
         "is_active": True, "status": "used_up", "expires_at": None, "created_at": None},
    ]
    totals = {"total": 3, "active": 2, "used_up": 1, "expired": 0, "disabled": 0, "redemptions": 20, "remaining_uses": 38, "unlimited": 1}
    for lang in ("uz", "ru", "en"):
        text = AP.build_list_text(items, totals, lang)
        T.check(f"[{lang}] ro'yxat: ishlatilgan/qolgan ko'rinadi", "12/50" in text and "38" in text and "∞" in text, text)
        T.check(f"[{lang}] ro'yxat: HTML-escape (B&lt;2&gt;)", "B&lt;2&gt;" in text and "B<2>" not in text)
        T.check(f"[{lang}] bo'sh ro'yxat matni", AP.build_list_text([], {}, lang) != AP.build_list_text(items, totals, lang))
        T.check(f"[{lang}] buyruqlar ro'yxati hamma buyruqni o'z ichiga oladi",
                all(c in AP.commands_text(lang) for c in ("/promos", "/promo_off", "/promo_del", "/grant_pro", "/setrole", "/audit", "/health", "/economics", "/feature_usage", "/broadcast")))
        d = AP.build_detail_text({**items[0], "created_at": None}, [{"user_id": 55, "redeemed_at": None}], lang)
        T.check(f"[{lang}] tafsilot: kim ishlatgani", "55" in d and "12/50" in d, d)
    more = [dict(items[0], code=f"K{i}") for i in range(40)]
    T.check("ro'yxat 15 tagacha qisqartiriladi", AP.build_list_text(more, {**totals, "total": 40}, "uz").count("<code>K") == AP.LIST_LIMIT)

    from services.promo_service import PromoService as PS, normalize_promo_input
    T.check("status: o'chirilgan > muddati o'tgan > tugagan > faol",
            PS.promo_status(False, 5, 5, True) == "disabled" and PS.promo_status(True, 5, 5, True) == "expired"
            and PS.promo_status(True, 5, 5, False) == "used_up" and PS.promo_status(True, None, 999, False) == "active")
    T.check("normalize: probel/belgi", normalize_promo_input(" «ab c»​") == "ABC")

    # buyruqlar: admin bo'lmaganga jim; DB chaqirilmaydi
    import database as db
    import handlers.admin_promos as mod
    calls = []

    async def fake_run_db(fn, *a, **k):
        calls.append(getattr(fn, "__name__", str(fn)))
        return []
    orig_db, orig_perm = db.run_db, mod.has_permission
    db.run_db = fake_run_db
    try:
        sent = []

        class Msg:
            async def reply_text(self, text, **kw):
                sent.append(text)
        upd = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=Msg())
        ctx = SimpleNamespace(user_data={"lang": "uz"}, args=["KOD"])
        mod.has_permission = lambda uid, perm: False
        for fn in (mod.promos_command, mod.promo_detail_command, mod.promo_off_command, mod.promo_on_command):
            asyncio.run(fn(upd, ctx))
        T.check("ruxsatsiz: hech qanday javob/DB chaqiruvi yo'q", sent == [] and calls == [], f"{sent} {calls}")
        mod.has_permission = lambda uid, perm: True
        asyncio.run(mod.promo_detail_command(upd, SimpleNamespace(user_data={"lang": "uz"}, args=[])))
        T.check("/promo argumentsiz: foydalanish ko'rsatiladi", sent and "/promo KOD" in sent[-1], str(sent))
        asyncio.run(mod.promo_off_command(upd, ctx))
        T.check("topilmagan kod: «topilmadi»", "topilmadi" in sent[-1], str(sent))
    finally:
        db.run_db, mod.has_permission = orig_db, orig_perm


def online() -> None:
    if not URL:
        T.skip("real PG qismi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return
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
    from services.promo_service import PromoService as PS

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run = loop.run_until_complete
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def cleanup():
        cur.execute("DELETE FROM promo_redemptions WHERE promo_id IN (SELECT id FROM promo_codes WHERE code LIKE 'ZT\\_%')")
        cur.execute("DELETE FROM promo_codes WHERE code LIKE 'ZT\\_%'")
        cur.execute("DELETE FROM admin_roles WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    cleanup()
    try:
        print("\n== B. Servis (real PG) ==")
        for uid, role in ((ADM, "admin"), (FIN, "finance"), (USR, "user"), (OWN, "owner"), (TGT, "user")):
            cur.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type, role) VALUES (%s,%s,%s,'uz','free',%s)",
                        (uid, f"u{uid}", f"Name{uid}", role))
        T.check("yaratish", PS.create_promo("zt_a", 30, 3, None, "pro", ADM) and PS.create_promo("ZT_B", 10, None, None, "ultra", ADM))
        T.check("takror yaratish rad", not PS.create_promo("ZT_A", 30, 3))
        items = {i["code"]: i for i in PS.list_promos(200)}
        T.check("ro'yxatda ko'rinadi, ishlatilgan 0, qolgan 3", items["ZT_A"]["current_uses"] == 0 and items["ZT_A"]["remaining_uses"] == 3)
        T.check("cheksiz kod: qolgan None", items["ZT_B"]["remaining_uses"] is None and items["ZT_B"]["status"] == "active")
        ok, _ = PS.redeem_promo(USR, " zt_a ")
        T.check("kod bo'shliq/kichik harf bilan ham ishlaydi", ok)
        items = {i["code"]: i for i in PS.list_promos(200)}
        T.check("ishlatilgach hisob yangilandi (1/3, qolgan 2)", items["ZT_A"]["current_uses"] == 1 and items["ZT_A"]["remaining_uses"] == 2)
        who = PS.recent_redemptions("zt_a")
        T.check("kim ishlatgani", who and who[0]["user_id"] == USR, str(who))
        cur.execute("UPDATE promo_codes SET expires_at = NOW() - INTERVAL '1 day' WHERE code = 'ZT_B'")
        T.check("muddati o'tgan holati", {i["code"]: i for i in PS.list_promos(200)}["ZT_B"]["status"] == "expired")
        cur.execute("UPDATE promo_codes SET expires_at = NULL WHERE code = 'ZT_B'")
        T.check("o'chirish", PS.set_promo_active("ZT_A", False, ADM) and {i["code"]: i for i in PS.list_promos(200)}["ZT_A"]["status"] == "disabled")
        ok, msg = PS.redeem_promo(OWN, "ZT_A")
        T.check("o'chirilgan kod ishlamaydi", not ok, msg)
        T.check("qayta yoqish", PS.set_promo_active("ZT_A", True, ADM) and {i["code"]: i for i in PS.list_promos(200)}["ZT_A"]["status"] == "active")
        T.check("yo'q kodni o'chirib bo'lmaydi", not PS.set_promo_active("ZT_NOPE", False))
        tot = PS.promo_totals()
        T.check("jami hisob", tot["total"] >= 2 and tot["redemptions"] >= 1 and tot["unlimited"] >= 1, str(tot))
        T.check("filtr: status=disabled bo'sh", all(i["status"] == "disabled" for i in PS.list_promos(200, 0, "disabled")))
        cur.execute("SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id=%s AND target_id IN ('ZT_A')", (ADM,))
        T.check("audit yozuvi (yaratish/o'chirish)", cur.fetchone()[0] >= 2)

        print("\n== B2. O'chirish va tarifni himoya qilish ==")
        T.check("noma'lum tarif bilan kod yaratib bo'lmaydi (ai/credits/free)", not PS.create_promo("ZT_AI", 5, 5, None, "ai", ADM) and not PS.create_promo("ZT_FR", 5, 5, None, "free", ADM))
        cur.execute("INSERT INTO promo_codes (code, plan_type, duration_days, max_uses) VALUES ('ZT_OLD', 'ai', 30, 5)")
        cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (TGT,))
        before = cur.fetchone()[0]
        ok, msg = PS.redeem_promo(TGT, "ZT_OLD")
        cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s", (TGT,))
        row = cur.fetchone()
        T.check("eski/noto'g'ri tarifli kod tarifni ALMASHTIRMAYDI va ishlatilgan hisoblanmaydi", not ok and row[0] == before and row[1] is None, f"{msg} {row}")
        cur.execute("SELECT COUNT(*) FROM promo_redemptions r JOIN promo_codes p ON p.id = r.promo_id WHERE p.code = 'ZT_OLD'")
        T.check("rad etilgan urinish tarixga yozilmadi", cur.fetchone()[0] == 0)
        PS.create_promo("ZT_DEL", 7, 2, None, "pro", ADM)
        PS.redeem_promo(FIN, "ZT_DEL")
        T.check("ishlatilgan kodni o'chirish: topildi, tarix ham ketdi", PS.delete_promo("zt_del", ADM) and "ZT_DEL" not in {i["code"] for i in PS.list_promos(200)}
                and PS.recent_redemptions("ZT_DEL") == [])
        cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (FIN,))
        T.check("o'chirilgach foydalanuvchining olgan tarifi SAQLANDI", cur.fetchone()[0] == "pro")
        T.check("yo'q kodni o'chirib bo'lmaydi; bo'sh kod rad", not PS.delete_promo("ZT_DEL") and not PS.delete_promo("  "))
        T.check("eski kodni o'chirish ishlaydi", PS.delete_promo("ZT_OLD", ADM))
        cur.execute("SELECT COUNT(*) FROM admin_audit_logs WHERE admin_id=%s AND target_id = 'ZT_DEL' AND new_value::text LIKE '%%deleted%%'", (ADM,))
        T.check("o'chirish auditga yozildi", cur.fetchone()[0] >= 1)
        from services.credits_service import CreditsService
        cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s", (TGT,))
        plan_before = cur.fetchone()
        res = CreditsService.add_credits(TGT, 50, "promo", ref_id="ZT_CR")
        cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s", (TGT,))
        T.check("AI ball (kredit) berilishi tarifni sotib olmaydi va o'zgartirmaydi", res.get("success") and cur.fetchone() == plan_before)

        print("\n== C. Mini App API (real PG) ==")
        settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
        runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4)
        service = MiniAppService(settings, runner)

        class Null:
            async def hit(self, *a, **k):
                return None

        admin = AdminApi(service, settings)
        api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service, admin=admin)
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)
        async def make_client():
            c = TestClient(TestServer(app))
            await c.start_server()
            return c

        client = run(make_client())

        async def call(method, path, uid, body=None):
            r = await client.request(method, "/api/v1" + path, headers={"Authorization": "tma " + make_init_data(uid)},
                                     **({"json": body} if body is not None else {}))
            return r.status, await r.json()

        C = lambda *a, **k: run(call(*a, **k))  # noqa: E731
        for code in ("promo_exists", "user_unknown"):
            T.check(f"xato kodi katalogda: {code}", code in catalog_codes())
        for m, path, body in (("GET", "/admin/promos", None), ("GET", "/admin/promos/ZT_A", None),
                              ("POST", "/admin/promos", {"code": "ZT_X", "days": 5}), ("PATCH", "/admin/promos/ZT_A", {"is_active": False}),
                              ("POST", "/admin/grant", {"user_id": TGT, "days": 5}), ("GET", "/admin/audit", None),
                              ("GET", "/admin/features", None), ("GET", "/admin/system", None), ("GET", "/admin/roles", None),
                              ("POST", "/admin/roles", {"user_id": TGT, "role": "admin"})):
            st, b = C(m, path, USR, body)
            T.check(f"oddiy foydalanuvchi {m} {path} -> 403", st == 403 and b["error"]["code"] == "admin_only", str(b))
        T.check("finance promo ko'ra olmaydi (manage_promos yo'q) -> 403", C("GET", "/admin/promos", FIN)[0] == 403)
        st, lst = C("GET", "/admin/promos", ADM)
        a = next((i for i in lst.get("items", []) if i["code"] == "ZT_A"), None)
        T.check("admin ro'yxatni oladi: ishlatilgan/qolgan", st == 200 and a and a["used"] == 1 and a["left"] == 2 and "redemptions" in lst["totals"], str(lst)[:300])
        T.check("noto'g'ri status filtri -> 400", C("GET", "/admin/promos?status=zzz", ADM)[0] == 400)
        st, det = C("GET", "/admin/promos/zt_a", ADM)
        T.check("tafsilot: kim ishlatgani", st == 200 and det["redeemers"][0]["user_id"] == USR, str(det))
        T.check("topilmagan kod -> 404", C("GET", "/admin/promos/ZT_NOPE", ADM)[0] == 404)
        st, cr = C("POST", "/admin/promos", ADM, {"code": "ZT_NEW", "days": 15, "max_uses": 7, "plan": "ultra"})
        T.check("yaratildi", st in (200, 201) and cr["promo"]["code"] == "ZT_NEW" and cr["promo"]["left"] == 7 and cr["promo"]["plan"] == "ultra", str(cr))
        T.check("takror -> 409 promo_exists", C("POST", "/admin/promos", ADM, {"code": "zt_new", "days": 1})[1].get("error", {}).get("code") == "promo_exists")
        for bad in ({"code": "a b", "days": 5}, {"code": "ab", "days": 5}, {"code": "ZT_Q", "days": 0}, {"code": "ZT_Q", "days": 99999},
                    {"code": "ZT_Q", "days": 5, "max_uses": 0}, {"code": "ZT_Q", "days": True}, {"code": "ZT_Q", "days": 5, "plan": "free"},
                    {"code": "ZT_Q", "days": 5, "x": 1}):
            T.check(f"noto'g'ri kiritish -> 422: {bad}", C("POST", "/admin/promos", ADM, bad)[0] == 422)
        st, off = C("PATCH", "/admin/promos/ZT_NEW", ADM, {"is_active": False})
        T.check("o'chirildi (disabled)", st == 200 and off["promo"]["status"] == "disabled", str(off))
        T.check("is_active bool bo'lmasa -> 422", C("PATCH", "/admin/promos/ZT_NEW", ADM, {"is_active": "ha"})[0] == 422)
        T.check("yo'q kod PATCH -> 404", C("PATCH", "/admin/promos/ZT_NOPE", ADM, {"is_active": True})[0] == 404)
        T.check("DELETE: oddiy foydalanuvchi -> 403, finance (manage_promos yo'q) -> 403", C("DELETE", "/admin/promos/ZT_NEW", USR)[0] == 403 and C("DELETE", "/admin/promos/ZT_NEW", FIN)[0] == 403)
        T.check("DELETE: yo'q kod -> 404", C("DELETE", "/admin/promos/ZT_NOPE", ADM)[0] == 404)
        st, dl = C("DELETE", "/admin/promos/zt_new", ADM)
        T.check("DELETE: kod butunlay o'chdi (ro'yxatda ham, tafsilotda ham yo'q)", st == 200 and dl == {"code": "ZT_NEW", "deleted": True}
                and C("GET", "/admin/promos/ZT_NEW", ADM)[0] == 404 and "ZT_NEW" not in {i["code"] for i in C("GET", "/admin/promos", ADM)[1]["items"]}, str(dl))
        T.check("katta/g'alati kod yo'li 500 bermaydi", C("GET", "/admin/promos/" + "Z" * 300, ADM)[0] in (404, 400))

        st, g = C("POST", "/admin/grant", ADM, {"user_id": TGT, "days": 7, "plan": "pro"})
        cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (TGT,))
        T.check("tarif berildi", st == 200 and cur.fetchone()[0] == "pro", str(g))
        for bad in ({"user_id": TGT, "days": 0}, {"user_id": TGT, "days": 99999}, {"user_id": -1, "days": 5}, {"user_id": TGT, "days": 5, "plan": "free"}):
            T.check(f"tarif berish noto'g'ri -> 422: {bad}", C("POST", "/admin/grant", ADM, bad)[0] == 422)
        T.check("moderator uchun ham ochiq (manage_users) — finance yo'q", C("POST", "/admin/grant", FIN, {"user_id": TGT, "days": 5})[0] == 403)

        T.check("audit: admin (SUPER_ADMIN emas) -> 403", C("GET", "/admin/audit", ADM)[0] == 403)
        st, au = C("GET", "/admin/audit", OWN)
        T.check("audit: owner ko'radi", st == 200 and isinstance(au["items"], list) and au["items"], str(au)[:200])
        st, ft = C("GET", "/admin/features", ADM)
        T.check("funksiyalar hisoboti", st == 200 and "most_used" in ft)
        T.check("tizim holati: admin (system_settings yo'q) -> 403", C("GET", "/admin/system", ADM)[0] == 403)
        st, hl = C("GET", "/admin/system", OWN)
        T.check("tizim holati: owner", st == 200 and "checks" in hl and "database" in hl["checks"], str(hl))
        T.check("rollar: admin -> 403 (faqat OWNER)", C("GET", "/admin/roles", ADM)[0] == 403)
        st, rl = C("POST", "/admin/roles", OWN, {"user_id": TGT, "role": "moderator"})
        T.check("rol berildi", st == 200 and any(i["user_id"] == TGT for i in rl["items"]), str(rl)[:200])
        T.check("noto'g'ri rol -> 422", C("POST", "/admin/roles", OWN, {"user_id": TGT, "role": "root"})[0] == 422)
        st, rl = C("POST", "/admin/roles", OWN, {"user_id": TGT, "role": "user"})
        T.check("rol olib tashlandi", st == 200 and not any(i["user_id"] == TGT for i in rl["items"]), str(rl)[:200])
        run(client.close())
        run(admin.aclose())
    finally:
        cleanup()
        conn.close()


def main() -> int:
    offline()
    online()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
