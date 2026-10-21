#!/usr/bin/env python3
"""Mini App — Jamoa API va «ish joyi» (workspace) himoyasi (real PostgreSQL).

Tekshiriladi: ULTRA egasi yordamchi taklif qiladi, PRO — yo'q; yordamchi faqat o'z kanallari/rollari doirasida ishlaydi
(editor / scheduler / analyst); egasining boshqa kanallari va qoralamasi yashirin; begona ish joyi — 403; a'zo olib tashlansa darhol yopiladi.
Faqat SINOV bazasi (``MINIAPP_TEST_DATABASE_URL``; yo'q bo'lsa SKIP). Test qatorlari user_id >= 9_810_000_000.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_miniapp_team")
if URL:
    os.environ["DATABASE_URL"] = URL
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

T = Counter("MINI APP — JAMOA VA ISH JOYI (real PostgreSQL)")
OWN, PROU, ED, SCH, ANA, OUT = 9_810_000_001, 9_810_000_002, 9_810_000_003, 9_810_000_004, 9_810_000_005, 9_810_000_006
USRX = 9_810_000_007
IDS = (OWN, PROU, ED, SCH, ANA, OUT, USRX)
CH1, CH2, CH3, CHP = "-1009810000001", "-1009810000002", "-1009810000003", "-1009810000004"
import time  # noqa: E402

WHEN = datetime.fromtimestamp(time.time() + 7200, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
WHEN2 = datetime.fromtimestamp(time.time() + 9000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    if not URL:
        T.skip("jamoa API testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()
    import psycopg2
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    import config
    import database as db
    from miniapp_api import app as appmod
    from miniapp_api.db import ReadOnlyRunner
    from miniapp_api.errors import catalog_codes
    from miniapp_api.service import MiniAppService
    from miniapp_api.settings import load_settings
    from services import team_invites as TI

    db.init_db()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    run = loop.run_until_complete
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()
    ch_ids = [CH1, CH2, CH3, CHP]

    def cleanup():
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM team_invites WHERE owner_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", (ch_ids,))
        cur.execute("DELETE FROM channels WHERE channel_id = ANY(%s)", (ch_ids,))
        cur.execute("DELETE FROM miniapp_drafts WHERE user_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    cleanup()
    try:
        for uid, plan in ((OWN, "ultra"), (PROU, "pro"), (ED, "free"), (SCH, "free"), (ANA, "free"), (OUT, "free")):
            exp = "NOW() + INTERVAL '30 days'" if plan != "free" else "NULL"
            cur.execute(f"INSERT INTO users (user_id, username, full_name, language_code, plan_type, subscription_expires_at) "  # noqa: S608
                        f"VALUES (%s,%s,%s,'uz',%s,{exp})", (uid, f"u{uid}", f"Name{uid}", plan))
        for ch, owner in ((CH1, OWN), (CH2, OWN), (CH3, OWN), (CHP, PROU)):
            cur.execute("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s,%s,%s)", (owner, ch, f"Kanal{ch[-1]}"))

        settings = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                                  "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
        runner = ReadOnlyRunner(statement_timeout_ms=5000, max_inflight=4)
        service = MiniAppService(settings, runner)

        class Null:
            async def hit(self, *a, **k):
                return None

        api = appmod.build_api_app(settings, runner=runner, limiter=Null(), clock=lambda: NOW, service=service)
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)

        async def make_client():
            c = TestClient(TestServer(app))
            await c.start_server()
            return c

        client = run(make_client())

        async def call(method, path, uid, body=None, ws=None):
            headers = {"Authorization": "tma " + make_init_data(uid)}
            if ws is not None:
                headers["X-Workspace"] = str(ws)
            r = await client.request(method, "/api/v1" + path, headers=headers, **({"json": body} if body is not None else {}))
            try:
                data = await r.json()
            except Exception:  # noqa: BLE001
                data = {}
            return r.status, data

        C = lambda *a, **k: run(call(*a, **k))  # noqa: E731
        code = lambda r: (r[1].get("error") or {}).get("code")  # noqa: E731

        print("\n== 1. Egasi: o'rindiqlar va taklif ==")
        for c in ("workspace_denied", "team_no_seats", "team_seats_full", "invite_invalid"):
            T.check(f"xato kodi katalogda: {c}", c in catalog_codes())
        st, ov = C("GET", "/team", OWN)
        T.check("ULTRA egasi: 2 o'rindiq, taklif mumkin", st == 200 and ov["seats"]["limit"] == 2 and ov["can_invite"] and len(ov["channels"]) == 3, str(ov)[:300])
        st, ov2 = C("GET", "/team", PROU)
        T.check("PRO: o'rindiq 0, taklif yo'q", st == 200 and ov2["seats"]["limit"] == 0 and ov2["can_invite"] is False)
        T.check("PRO taklif qila olmaydi -> team_no_seats", code(C("POST", "/team/invites", PROU, {"channel_id": CHP, "role": "editor"})) == "team_no_seats")
        T.check("begona kanalga taklif -> 404 channel_not_found", code(C("POST", "/team/invites", OWN, {"channel_id": CHP, "role": "editor"})) == "channel_not_found")
        for bad in ({"channel_id": CH1, "role": "owner"}, {"channel_id": "x", "role": "editor"}, {"channel_id": CH1, "perms": ["hack"]}, {"channel_ids": []}, {"channel_id": CH1, "role": "editor", "z": 1}):
            T.check(f"noto'g'ri taklif -> 422: {bad}", C("POST", "/team/invites", OWN, bad)[0] == 422)
        st, i_ed = C("POST", "/team/invites", OWN, {"channel_id": CH1, "role": "editor"})
        T.check("taklif yaratildi (token qaytadi)", st == 201 and len(i_ed["token"]) >= 16, str(i_ed))
        st, i_sch = C("POST", "/team/invites", OWN, {"channel_id": CH2, "role": "scheduler"})
        T.check("ikkinchi taklif", st == 201)
        T.check("uchinchi taklif -> o'rindiq to'lgan", code(C("POST", "/team/invites", OWN, {"channel_id": CH3, "role": "analyst"})) == "team_seats_full")
        st, ov = C("GET", "/team", OWN)
        T.check("kutilayotgan takliflar ko'rinadi", sum(len(c["invites"]) for c in ov["channels"]) == 2)
        T.check("taklifni bekor qilish", C("DELETE", f"/team/invites/{i_sch['id']}", OWN)[0] == 200 and C("DELETE", f"/team/invites/{i_sch['id']}", OWN)[0] == 404)
        st, i_sch = C("POST", "/team/invites", OWN, {"channel_id": CH2, "role": "scheduler"})
        T.check("oddiy foydalanuvchi boshqaning taklifini o'chira olmaydi", C("DELETE", f"/team/invites/{i_sch['id']}", PROU)[0] == 404)

        print("\n== 2. Yordamchilar qo'shildi ==")
        T.check("editor qabul qildi", TI.accept_invite(i_ed["token"], ED)["ok"])
        T.check("scheduler qabul qildi", TI.accept_invite(i_sch["token"], SCH)["ok"])
        st, ov = C("GET", "/team", OWN)
        T.check("a'zolar va o'rindiqlar yangilandi (2/2)", ov["seats"]["used"] == 2 and any(m["user_id"] == ED for c in ov["channels"] for m in c["members"]))
        st, h = C("GET", "/team", ED)
        T.check("yordamchi: ish joylari ro'yxatida egasi va roli", len(h["workspaces"]) == 1 and h["workspaces"][0]["owner_id"] == OWN
                and h["workspaces"][0]["channels"] == [{"channel_id": CH1, "title": "Kanal1", "role": "editor", "perms": ["create", "edit", "reschedule", "delete", "ai"]}], str(h["workspaces"]))
        T.check("yordamchi o'z o'rindiqlarini 0 ko'radi (o'zi egasi emas)", h["seats"]["limit"] == 0)
        T.check("rejim: boshida (taklif orqali) 'helper'", h["mode"] == "helper")
        T.check("rejimni o'zgartirish", C("PATCH", "/team/mode", ED, {"mode": "owner"})[1].get("mode") == "owner" and C("PATCH", "/team/mode", ED, {"mode": "helper"})[0] == 200)
        T.check("noto'g'ri rejim -> 422", C("PATCH", "/team/mode", ED, {"mode": "admin"})[0] == 422)

        print("\n== 3. Ish joyi: kanallar va ko'rish ==")
        st, own_ch = C("GET", "/channels", ED)
        T.check("sarlavhasiz: yordamchining O'Z kanallari (bo'sh)", st == 200 and own_ch["items"] == [], str(own_ch))
        st, chs = C("GET", "/channels", ED, ws=OWN)
        T.check("ish joyi: faqat ruxsat etilgan kanal (CH1)", st == 200 and [c["id"] for c in chs["items"]] == [CH1], str(chs))
        st, chs = C("GET", "/channels", SCH, ws=OWN)
        T.check("scheduler: faqat CH2", [c["id"] for c in chs["items"]] == [CH2], str(chs))
        T.check("begona ish joyi -> 403 workspace_denied", code(C("GET", "/channels", ED, ws=PROU)) == "workspace_denied" and C("GET", "/channels", OUT, ws=OWN)[0] == 403)
        T.check("noto'g'ri sarlavha -> 400", C("GET", "/channels", ED, ws="abc")[0] == 400)
        st, me = C("GET", "/me", ED, ws=OWN)
        T.check("/me sarlavhani e'tiborsiz qoldiradi (yordamchining o'zi)", st == 200 and me["user"]["id"] == ED if "user" in me and "id" in me.get("user", {}) else st == 200, str(me)[:120])
        T.check("egasi o'z ish joyida (sarlavhasiz) hamma 3 kanalni ko'radi", len(C("GET", "/channels", OWN)[1]["items"]) == 3)
        T.check("egasi o'z ID sini sarlavhada yuborsa ham cheklanmaydi", len(C("GET", "/channels", OWN, ws=OWN)[1]["items"]) == 3)

        print("\n== 4. Ish joyi: postlar va rollar ==")
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) VALUES (%s,%s,'text','Egasining CH3 posti', NOW()+INTERVAL '5 hours','pending') RETURNING id", (OWN, CH3))
        p_hidden = cur.fetchone()[0]
        st, cr = C("POST", "/posts", ED, {"channel_id": CH1, "text": "Yordamchi posti", "scheduled_at": WHEN}, ws=OWN)
        pid = cr.get("post", {}).get("id")
        T.check("editor CH1 ga post yaratdi", st in (200, 201) and pid, str(cr)[:200])
        cur.execute("SELECT user_id FROM scheduled_posts WHERE id = %s", (pid,))
        T.check("post egasi nomidan saqlandi (egasi navbati/kvotasi)", cur.fetchone()[0] == OWN)
        T.check("editor CH2 ga yarata olmaydi -> workspace_denied", code(C("POST", "/posts", ED, {"channel_id": CH2, "text": "x", "scheduled_at": WHEN}, ws=OWN)) == "workspace_denied")
        T.check("editor CH3 (ruxsatsiz) ga yarata olmaydi", code(C("POST", "/posts", ED, {"channel_id": CH3, "text": "x", "scheduled_at": WHEN}, ws=OWN)) == "workspace_denied")
        T.check("ish joyida use_draft yordamchining O'Z qoralamasini o'qiydi (yo'q bo'lsa draft_not_found; egasinikini emas)",
                code(C("POST", "/posts", ED, {"channel_id": CH1, "text": "x", "scheduled_at": WHEN, "use_draft": True}, ws=OWN)) == "draft_not_found")
        st, lst = C("GET", "/scheduled-posts", ED, ws=OWN)
        ids = [i["id"] for i in lst.get("items", [])]
        T.check("ro'yxat: faqat CH1 postlari (egasining CH3 posti yashirin)", pid in ids and p_hidden not in ids, str(ids))
        T.check("yashirin post tafsiloti -> 404", C("GET", f"/posts/{p_hidden}", ED, ws=OWN)[0] == 404)
        T.check("o'z kanalidagi post tafsiloti ochiladi", C("GET", f"/posts/{pid}", ED, ws=OWN)[0] == 200)
        T.check("yashirin postni tahrirlab bo'lmaydi", C("PATCH", f"/posts/{p_hidden}", ED, {"text": "hack"}, ws=OWN)[0] in (403, 404))
        T.check("yashirin postni o'chirib bo'lmaydi", C("DELETE", f"/posts/{p_hidden}", ED, ws=OWN)[0] in (403, 404))
        cur.execute("SELECT content, status FROM scheduled_posts WHERE id = %s", (p_hidden,))
        T.check("yashirin post o'zgarmadi", cur.fetchone() == ("Egasining CH3 posti", "pending"))
        st, up = C("PATCH", f"/posts/{pid}", ED, {"text": "Tahrirlandi"}, ws=OWN)
        T.check("editor matnni tahrirlaydi", st == 200 and up["post"]["text"] == "Tahrirlandi", str(up)[:200])
        # scheduler: CH2 da post (egasi yaratgan)
        cur.execute("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) VALUES (%s,%s,'text','CH2 posti', NOW()+INTERVAL '6 hours','pending') RETURNING id", (OWN, CH2))
        p2 = cur.fetchone()[0]
        T.check("scheduler matnni tahrirlay olmaydi -> workspace_denied", code(C("PATCH", f"/posts/{p2}", SCH, {"text": "x"}, ws=OWN)) == "workspace_denied")
        T.check("scheduler vaqtni o'zgartiradi", C("PATCH", f"/posts/{p2}", SCH, {"scheduled_at": WHEN2}, ws=OWN)[0] == 200)
        T.check("scheduler o'chira olmaydi -> workspace_denied", code(C("DELETE", f"/posts/{p2}", SCH, ws=OWN)) == "workspace_denied")
        T.check("scheduler CH2 ga post yaratadi", C("POST", "/posts", SCH, {"channel_id": CH2, "text": "Rejalovchi posti", "scheduled_at": WHEN}, ws=OWN)[0] in (200, 201))
        T.check("scheduler CH1 ga (ruxsatsiz) yarata olmaydi", code(C("POST", "/posts", SCH, {"channel_id": CH1, "text": "x", "scheduled_at": WHEN}, ws=OWN)) == "workspace_denied")
        st, dl = C("DELETE", f"/posts/{pid}", ED, ws=OWN)
        T.check("editor o'chiradi (bekor qiladi)", st == 200, str(dl)[:200])

        print("\n== 5. Analyst: faqat ko'radi ==")
        TI.set_member_role(OWN, CH1, ED, "analyst")
        T.check("rol o'zgardi: endi analyst — yaratolmaydi", code(C("POST", "/posts", ED, {"channel_id": CH1, "text": "x", "scheduled_at": WHEN}, ws=OWN)) == "workspace_denied")
        T.check("analyst ro'yxatni ko'radi", C("GET", "/scheduled-posts", ED, ws=OWN)[0] == 200)
        T.check("analyst kanal tahlilini ko'radi", C("GET", f"/channels/{CH1}/analytics", ED, ws=OWN)[0] == 200)
        T.check("analyst CH2 tahlilini ko'ra olmaydi (kanal ruxsat doirasida emas)", code(C("GET", f"/channels/{CH2}/analytics", ED, ws=OWN)) == "workspace_denied")

        print("\n== 6. A'zoni boshqarish ==")
        st, up = C("PATCH", "/team/members", OWN, {"channel_id": CH1, "user_id": ED, "role": "editor"})
        T.check("egasi rolni o'zgartirdi", st == 200 and C("POST", "/posts", ED, {"channel_id": CH1, "text": "Yana", "scheduled_at": WHEN}, ws=OWN)[0] in (200, 201))
        T.check("boshqa kanaldagi a'zoni o'zgartirib bo'lmaydi -> 404", C("PATCH", "/team/members", OWN, {"channel_id": CH3, "user_id": ED, "role": "editor"})[0] == 404)
        T.check("PRO egasi bu a'zoga tegolmaydi", C("POST", "/team/members/remove", PROU, {"channel_id": CH1, "user_id": ED})[0] == 404)
        T.check("a'zo olib tashlandi", C("POST", "/team/members/remove", OWN, {"channel_id": CH1, "user_id": ED})[0] == 200)
        T.check("olib tashlangach ish joyi DARHOL yopiladi", code(C("GET", "/channels", ED, ws=OWN)) == "workspace_denied")
        T.check("yordamchi o'zi chiqadi", C("POST", "/team/leave", SCH, {"owner_id": OWN})[0] == 200 and C("POST", "/team/leave", SCH, {"owner_id": OWN})[0] == 404)
        T.check("noto'g'ri tanlov -> 422", C("POST", "/team/leave", SCH, {"owner_id": "x"})[0] == 422)

        print("\n== 7. Egasi tarifi tushsa ==")
        TI.accept_invite(C("POST", "/team/invites", OWN, {"channel_id": CH1, "role": "editor"})[1]["token"], ED)
        cur.execute("UPDATE users SET plan_type = 'pro' WHERE user_id = %s", (OWN,))
        T.check("egasi PRO ga tushdi: yordamchi ish joyi yopiladi", code(C("GET", "/channels", ED, ws=OWN)) == "workspace_denied")
        T.check("PRO egasi yangi taklif bera olmaydi", code(C("POST", "/team/invites", OWN, {"channel_id": CH1, "role": "editor"})) == "team_no_seats")
        cur.execute("UPDATE users SET plan_type = 'ultra' WHERE user_id = %s", (OWN,))
        T.check("ULTRA qaytsa ish joyi ochiladi", C("GET", "/channels", ED, ws=OWN)[0] == 200)
        print("\n== 8. Ruxsatlar: har bir yordamchiga alohida ==")
        from miniapp_api import drafts as drafts_mod

        TI.leave(ED, OWN)
        cur.execute("UPDATE team_invites SET revoked_at = NOW() WHERE used_at IS NULL AND revoked_at IS NULL")
        st, mi = C("POST", "/team/invites", OWN, {"channel_ids": [CH1, CH2], "perms": ["create", "ai", "send_now"]})
        T.check("ikki kanalga bitta taklif, ruxsatlar ro'yxati bilan", st == 201 and mi["perms"] == ["create", "send_now", "ai"] and mi["channel_ids"] == [CH1, CH2], str(mi))
        st, mi_default = C("POST", "/team/invites", OWN, {"channel_id": CH3})
        T.check("ruxsat berilmasa — hamma ruxsat (kengroq standart)", st == 201 and len(mi_default["perms"]) == 7, str(mi_default))
        C("DELETE", f"/team/invites/{mi_default['id']}", OWN)
        T.check("shablon nomi ham qabul: perms='scheduler'", C("POST", "/team/invites", OWN, {"channel_id": CH3, "perms": "scheduler"})[1].get("perms") == ["create", "reschedule"])
        cur.execute("UPDATE team_invites SET revoked_at = NOW() WHERE used_at IS NULL AND revoked_at IS NULL AND id <> %s", (mi["id"],))
        T.check("ED qabul qildi", TI.accept_invite(mi["token"], ED)["ok"])
        st, h = C("GET", "/team", ED)
        wch = h["workspaces"][0]["channels"]
        T.check("yordamchi ish joyida ruxsatlarini ko'radi", {c["channel_id"] for c in wch} == {CH1, CH2} and all(c["perms"] == ["create", "send_now", "ai"] for c in wch), str(wch))
        st, ow = C("GET", "/team", OWN)
        T.check("egasi a'zo ruxsatlarini ko'radi", any(m["perms"] == ["create", "send_now", "ai"] for c in ow["channels"] for m in c["members"]))
        T.check("ruxsat bor: yaratadi", C("POST", "/posts", ED, {"channel_id": CH1, "text": "Faqat yaratish", "scheduled_at": WHEN}, ws=OWN)[0] in (200, 201))
        cur.execute("SELECT id FROM scheduled_posts WHERE user_id = %s AND channel_id = %s AND content = 'Faqat yaratish'", (OWN, CH1))
        pid2 = cur.fetchone()[0]
        T.check("tahrirlash ruxsati yo'q -> workspace_denied", code(C("PATCH", f"/posts/{pid2}", ED, {"text": "x"}, ws=OWN)) == "workspace_denied")
        T.check("vaqt ruxsati yo'q -> workspace_denied", code(C("PATCH", f"/posts/{pid2}", ED, {"scheduled_at": WHEN2}, ws=OWN)) == "workspace_denied")
        T.check("o'chirish ruxsati yo'q -> workspace_denied", code(C("DELETE", f"/posts/{pid2}", ED, ws=OWN)) == "workspace_denied")
        T.check("statistika ruxsati yo'q -> workspace_denied", code(C("GET", f"/channels/{CH1}/analytics", ED, ws=OWN)) == "workspace_denied")
        T.check("send_now ruxsati bor: darhol yuborishga rejalash mumkin", C("POST", "/posts", ED, {"channel_id": CH1, "text": "Hozir", "send_now": True}, ws=OWN)[0] in (200, 201))
        T.check("AI ruxsati bor — darvoza ochiq (AI chaqirilmaydi: matn bo'sh -> 422)", C("POST", "/ai/generate", ED, {"text": "", "style": "casual"}, ws=OWN)[0] == 422)
        # egasi ruxsatlarni o'zgartiradi (markaz usuli): send_now va ai olib tashlanadi, edit/delete qo'shiladi
        st, up = C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": [CH1, CH2], "perms": ["create", "edit", "delete", "reschedule"]})
        T.check("egasi yordamchini sozladi", st == 200 and up["perms"] == ["create", "reschedule", "edit", "delete"] or up["perms"] == ["create", "edit", "reschedule", "delete"], str(up))
        T.check("endi send_now -> workspace_denied", code(C("POST", "/posts", ED, {"channel_id": CH1, "text": "Yana", "send_now": True}, ws=OWN)) == "workspace_denied")
        T.check("endi AI -> workspace_denied", code(C("POST", "/ai/generate", ED, {"text": "salom dunyo", "style": "casual"}, ws=OWN)) == "workspace_denied")
        T.check("endi tahrirlaydi, vaqtini o'zgartiradi va o'chiradi",
                C("PATCH", f"/posts/{pid2}", ED, {"text": "Tahrir"}, ws=OWN)[0] == 200 and C("PATCH", f"/posts/{pid2}", ED, {"scheduled_at": WHEN2}, ws=OWN)[0] == 200
                and C("DELETE", f"/posts/{pid2}", ED, ws=OWN)[0] == 200)
        T.check("markaz usuli: kanallar to'plami o'zgaradi (CH2 olib tashlanadi)", C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": [CH1], "perms": ["create"]})[0] == 200
                and [c["id"] for c in C("GET", "/channels", ED, ws=OWN)[1]["items"]] == [CH1])
        T.check("markaz usuli: begona kanal -> 404", C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": [CHP], "perms": ["create"]})[0] == 404)
        T.check("markaz usuli: yordamchi emas -> 404", C("PATCH", "/team/helpers", OWN, {"user_id": USRX, "channel_ids": [CH1], "perms": []})[0] == 404)
        T.check("markaz usuli: noto'g'ri ruxsat/tur -> 422", C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": [CH1], "perms": ["hack"]})[0] == 422
                and C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": "x", "perms": []})[0] == 422 and C("PATCH", "/team/helpers", OWN, {"user_id": ED, "channel_ids": [CH1]})[0] == 422)
        T.check("PRO egasi yordamchini sozlay olmaydi", C("PATCH", "/team/helpers", PROU, {"user_id": ED, "channel_ids": [], "perms": []})[0] == 404)

        print("\n== 9. Media: qoralama yordamchida, post egasi nomidan; limit egasidan ==")
        TI.set_helper(OWN, ED, [CH1], ["create", "edit"])
        drafts_mod.save_draft(OWN, {"post_type": "text", "content": "EGASINING QORALAMASI"})
        drafts_mod.save_draft(ED, {"post_type": "photo", "file_id": "AgACAgIAAxkBAAFAKEFILEID1", "content": "Rasm sarlavhasi"})
        st, mp = C("POST", "/posts", ED, {"channel_id": CH1, "text": "Rasm sarlavhasi", "scheduled_at": WHEN, "use_draft": True}, ws=OWN)
        T.check("yordamchi o'z qoralamasi (media) bilan post yaratdi", st in (200, 201) and mp["post"]["post_type"] == "photo", str(mp)[:200])
        cur.execute("SELECT user_id, file_id FROM scheduled_posts WHERE id = %s", (mp["post"]["id"],))
        T.check("post EGASI nomidan, media fayli saqlangan", cur.fetchone() == (OWN, "AgACAgIAAxkBAAFAKEFILEID1"))
        cur.execute("SELECT COUNT(*) FROM miniapp_drafts WHERE user_id = %s", (ED,))
        T.check("yordamchining qoralamasi tozalandi", cur.fetchone()[0] == 0)
        cur.execute("SELECT payload->>'content' FROM miniapp_drafts WHERE user_id = %s", (OWN,))
        T.check("egasining qoralamasi O'ZGARMADI", cur.fetchone()[0] == "EGASINING QORALAMASI")
        T.check("qoralama bo'lmasa -> draft_not_found", code(C("POST", "/posts", ED, {"channel_id": CH1, "text": "x", "scheduled_at": WHEN, "use_draft": True}, ws=OWN)) == "draft_not_found")
        cur.execute("UPDATE users SET plan_type = 'ultra', subscription_expires_at = NOW() + INTERVAL '30 days' WHERE user_id = %s", (OWN,))
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = 'pending'", (OWN,))
        pend_owner = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s", (ED,))
        T.check("yordamchi nomidan post YO'Q — hammasi egasining navbatida (limit egasidan)", cur.fetchone()[0] == 0 and pend_owner >= 3)
        print("\n== Z. Qidirish va to'g'ridan-to'g'ri qo'shish (kontakt / @username) ==")
        import handlers.team_ui as team_ui_mod

        sent = []

        async def fake_notify(bot, owner_id, member_id, channel_ids, perms):
            sent.append((owner_id, member_id, list(channel_ids), list(perms)))
            return True

        real_notify = team_ui_mod.notify_helper_added
        team_ui_mod.notify_helper_added = fake_notify
        try:
            cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", ([CH1, CH2, CH3],))
            cur.execute("DELETE FROM team_invites WHERE owner_id = %s", (OWN,))
            st, res = C("GET", f"/team/people?q=u{OUT}", OWN)
            T.check("GET /team/people: username bo'yicha topadi (member=false)", st == 200 and [x["user_id"] for x in res["items"]] == [OUT] and res["items"][0]["member"] is False, str(res))
            T.check("qisqa so'rov -> bo'sh ro'yxat; auth'siz 401", C("GET", "/team/people?q=u9", OWN)[1]["items"] == [] and run(client.request("GET", "/api/v1/team/people?q=abcd")).status == 401)
            T.check("juda uzun so'rov -> 422", C("GET", "/team/people?q=" + "x" * 80, OWN)[0] == 422)
            st, add = C("POST", "/team/invites", OWN, {"user_id": OUT, "channel_ids": [CH1, CH2], "perms": ["create", "analytics"]})
            T.check("tanlangan odam to'g'ridan-to'g'ri qo'shildi (201), unga xabar ketdi", st == 201 and add["user_id"] == OUT and add["perms"] == ["create", "analytics"] and add["notified"] is True
                    and sent == [(OWN, OUT, [CH1, CH2], ["create", "analytics"])], str((st, add, sent)))
            st, ov = C("GET", "/team", OWN)
            T.check("a'zo har ikki kanalda ruxsatlari bilan ko'rinadi", sum(1 for c in ov["channels"] for m in c["members"] if m["user_id"] == OUT and m["perms"] == ["create", "analytics"]) == 2)
            st, res = C("GET", f"/team/people?q={OUT}", OWN)
            T.check("endi qidiruvda member=true", res["items"][0]["member"] is True)
            T.check("qo'shilgan yordamchi ish joyiga kira oladi (X-Workspace)", C("GET", "/channels", OUT, ws=OWN)[0] == 200)
            T.check("o'zini qo'shish -> 422", C("POST", "/team/invites", OWN, {"user_id": OWN, "channel_ids": [CH1], "perms": ["create"]})[0] == 422)
            T.check("botda yo'q odam -> 404 user_unknown", code(C("POST", "/team/invites", OWN, {"user_id": 9_899_999_999, "channel_ids": [CH1], "perms": ["create"]})) == "user_unknown")
            T.check("begona kanal -> 404 channel_not_found", code(C("POST", "/team/invites", OWN, {"user_id": ED, "channel_ids": [CHP], "perms": ["create"]})) == "channel_not_found")
            for bad in ({"user_id": ED, "channel_ids": [CH1], "perms": ["hack"]}, {"user_id": ED, "channel_ids": []}, {"user_id": "x", "channel_ids": [CH1]}, {"user_id": ED, "channel_ids": [CH1], "z": 1}, {"user_id": True, "channel_ids": [CH1]}):
                T.check(f"noto'g'ri qo'shish -> 422: {bad}", C("POST", "/team/invites", OWN, bad)[0] == 422)
            T.check("PRO egasi qo'sha olmaydi -> team_no_seats", code(C("POST", "/team/invites", PROU, {"user_id": ED, "channel_ids": [CHP], "perms": ["create"]})) == "team_no_seats")
            T.check("yordamchi boshqani qo'sha olmaydi (o'z kanali yo'q) -> channel_not_found", code(C("POST", "/team/invites", OUT, {"user_id": ED, "channel_ids": [CH1], "perms": ["create"]})) == "channel_not_found")
            C("POST", "/team/invites", OWN, {"user_id": ED, "channel_ids": [CH1], "perms": ["create"]})
            T.check("o'rindiqlar to'lgach yana qo'shish -> team_seats_full", code(C("POST", "/team/invites", OWN, {"user_id": SCH, "channel_ids": [CH1], "perms": ["create"]})) == "team_seats_full")
        finally:
            team_ui_mod.notify_helper_added = real_notify
        T.check("oddiy foydalanuvchi /team auth'siz -> 401", run(client.request("GET", "/api/v1/team")).status == 401)
        run(client.close())
        _ = config
    finally:
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
