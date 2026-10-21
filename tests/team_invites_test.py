#!/usr/bin/env python3
"""Jamoa: taklif havolasi, o'rindiqlar (ULTRA 2 ta yordamchi, PRO/FREE — 0), rollar, ish joyi (real PostgreSQL).

Faqat SINOV bazasi (``MINIAPP_TEST_DATABASE_URL``; yo'q bo'lsa SKIP). Test o'z qatorlarini (user_id >= 9_800_000_000) yozadi va o'chiradi.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_team")
if URL:
    os.environ["DATABASE_URL"] = URL
from miniapp_testkit import Counter  # noqa: E402

T = Counter("JAMOA: TAKLIF, O'RINDIQLAR, ROLLAR, ISH JOYI")
OWN, PRO, HA, HB, HC, STR = 9_800_000_001, 9_800_000_002, 9_800_000_003, 9_800_000_004, 9_800_000_005, 9_800_000_006
IDS = (OWN, PRO, HA, HB, HC, STR)
CH1, CH2, CHP = "-1009800000001", "-1009800000002", "-1009800000003"


R = lambda access: {k: v["role"] for k, v in access.items()}  # noqa: E731


def main() -> int:
    if not URL:
        T.skip("jamoa testi", "BLOCKED: MINIAPP_TEST_DATABASE_URL (sinov bazasi) berilmagan")
        return T.finish()
    import psycopg2

    import config
    import database as db
    from services import team_invites as TI

    db.init_db()
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur = conn.cursor()

    def cleanup():
        cur.execute("DELETE FROM team_invites WHERE owner_id = ANY(%s)", (list(IDS),))
        cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", ([CH1, CH2, CHP],))
        cur.execute("DELETE FROM channels WHERE channel_id = ANY(%s)", ([CH1, CH2, CHP],))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(IDS),))

    cleanup()
    old_seats = config.TIER_LIMITS["ultra"]["team_seats"]
    try:
        for uid, plan in ((OWN, "ultra"), (PRO, "pro"), (HA, "free"), (HB, "free"), (HC, "free"), (STR, "free")):
            exp = "NOW() + INTERVAL '30 days'" if plan != "free" else "NULL"
            cur.execute(f"INSERT INTO users (user_id, username, full_name, language_code, plan_type, subscription_expires_at) "  # noqa: S608
                        f"VALUES (%s,%s,%s,'uz',%s,{exp})", (uid, f"u{uid}", f"Name{uid}", plan))
        for ch, owner in ((CH1, OWN), (CH2, OWN), (CHP, PRO)):
            cur.execute("INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s,%s,%s)", (owner, ch, f"T{ch[-1]}"))

        print("\n== 1. Tarif qoidalari ==")
        T.check("TIER_LIMITS: FREE/PRO = 0, ULTRA = 2, pro_legacy = 0",
                all(config.TIER_LIMITS[k]["team_seats"] == 0 for k in ("free", "pro", "pro_legacy")) and config.TIER_LIMITS["ultra"]["team_seats"] == 2)
        r = TI.create_invite(PRO, CHP, "editor")
        T.check("PRO: yordamchi taklif qilib bo'lmaydi (no_team)", r == {"ok": False, "error": "no_team"}, str(r))
        T.check("PRO o'rindiqlari: limit 0", TI.seat_status(PRO)["limit"] == 0)
        T.check("noto'g'ri rol -> bad_role", TI.create_invite(OWN, CH1, "owner")["error"] == "bad_role")
        T.check("begona kanal -> not_owner", TI.create_invite(OWN, CHP, "editor")["error"] == "not_owner")
        T.check("ULTRA: o'rindiqlar limit 2", TI.seat_status(OWN) == {"plan": "ultra", "limit": 2, "used": 0, "pending": 0, "free": 2})

        print("\n== 2. Taklif va qabul ==")
        i1 = TI.create_invite(OWN, CH1, "editor")
        T.check("taklif yaratildi", i1["ok"] and len(i1["token"]) >= 16, str(i1))
        cur.execute("SELECT token_hash FROM team_invites WHERE id = %s", (i1["id"],))
        T.check("token bazada faqat HASH (ochiq token yo'q)", cur.fetchone()[0] != i1["token"])
        cur.execute("SELECT COUNT(*) FROM team_invites WHERE token_hash = %s", (i1["token"],))
        T.check("ochiq token bo'yicha qator topilmaydi", cur.fetchone()[0] == 0)
        i2 = TI.create_invite(OWN, CH2, "analyst")
        T.check("ikkinchi taklif ham bor", i2["ok"])
        T.check("kutilayotganlar o'rindiqni band qiladi: uchinchisi -> seats_full", TI.create_invite(OWN, CH1, "editor")["error"] == "seats_full")
        T.check("o'rindiqlar: pending 2, free 0", TI.seat_status(OWN)["pending"] == 2 and TI.seat_status(OWN)["free"] == 0)
        T.check("egasi o'zini qabul qila olmaydi", TI.accept_invite(i1["token"], OWN)["error"] == "self")
        T.check("noto'g'ri/qisqa token -> invalid", TI.accept_invite("x", HA)["error"] == "invalid" and TI.accept_invite("a" * 20, HA)["error"] == "invalid")
        a = TI.accept_invite(i1["token"], HA)
        T.check("A qabul qildi (editor, CH1)", a["ok"] and a["owner_id"] == OWN and a["channel_id"] == CH1 and a["role"] == "editor", str(a))
        T.check("bir martalik: qayta -> used", TI.accept_invite(i1["token"], HB)["error"] == "used")
        cur.execute("SELECT work_mode FROM users WHERE user_id = %s", (HA,))
        T.check("yordamchi rejimi avtomatik 'helper'", cur.fetchone()[0] == "helper")
        T.check("A ish joyi: faqat CH1 editor", R(TI.workspace_access(HA, OWN)) == {CH1: "editor"})
        T.check("A boshqa egaga kira olmaydi", TI.workspace_access(HA, PRO) == {})
        b = TI.accept_invite(i2["token"], HB)
        T.check("B qabul qildi (analyst, CH2)", b["ok"] and b["role"] == "analyst")
        T.check("o'rindiqlar: used 2, pending 0, free 0", TI.seat_status(OWN) == {"plan": "ultra", "limit": 2, "used": 2, "pending": 0, "free": 0})
        T.check("uchinchi odam uchun taklif -> seats_full", TI.create_invite(OWN, CH1, "scheduler")["error"] == "seats_full")
        cur.execute("UPDATE channel_members SET created_at = created_at - INTERVAL '1 day' WHERE user_id = %s", (HA,))

        print("\n== 3. Bir yordamchi — bir nechta kanal (qo'shimcha o'rindiq yemaydi) ==")
        cur.execute("UPDATE team_invites SET revoked_at = NULL")
        TI.remove_member(OWN, CH2, HB)
        T.check("B olib tashlandi, o'rindiq bo'shadi", TI.seat_status(OWN)["used"] == 1 and TI.workspace_access(HB, OWN) == {})
        i3 = TI.create_invite(OWN, CH2, "scheduler")
        a2 = TI.accept_invite(i3["token"], HA)
        T.check("A ikkinchi kanalga ham (rol scheduler)", a2["ok"] and R(TI.workspace_access(HA, OWN)) == {CH1: "editor", CH2: "scheduler"})
        T.check("o'rindiq o'zgarmadi (A noyob)", TI.seat_status(OWN)["used"] == 1)
        T.check("rol o'zgartirish", TI.set_member_role(OWN, CH2, HA, "analyst") and TI.workspace_access(HA, OWN)[CH2]["role"] == "analyst")
        T.check("noto'g'ri rolga o'zgartirib bo'lmaydi", not TI.set_member_role(OWN, CH2, HA, "owner"))
        T.check("begona egasi rolni o'zgartira olmaydi", not TI.set_member_role(PRO, CH2, HA, "editor") and not TI.remove_member(PRO, CH2, HA))

        print("\n== 4. Muddati, bekor qilish ==")
        i4 = TI.create_invite(OWN, CH1, "editor")
        cur.execute("UPDATE team_invites SET expires_at = NOW() - INTERVAL '1 minute' WHERE id = %s", (i4["id"],))
        T.check("muddati o'tgan -> expired", TI.accept_invite(i4["token"], HC)["error"] == "expired")
        i5 = TI.create_invite(OWN, CH1, "editor")
        T.check("bekor qilindi", TI.revoke_invite(OWN, i5["id"]) and not TI.revoke_invite(OWN, i5["id"]))
        T.check("bekor qilingan -> revoked", TI.accept_invite(i5["token"], HC)["error"] == "revoked")
        i6 = TI.create_invite(OWN, CH1, "editor")
        T.check("begona egasi bekor qila olmaydi", not TI.revoke_invite(PRO, i6["id"]))

        print("\n== 5. Egasi tarifi tushsa / o'rindiq kamaysa ==")
        c = TI.accept_invite(i6["token"], HB)
        T.check("B qayta qo'shildi (2/2)", c["ok"])
        cur.execute("UPDATE channel_members SET created_at = created_at + INTERVAL '1 hour' WHERE user_id = %s", (HB,))
        config.TIER_LIMITS["ultra"]["team_seats"] = 1
        T.check("o'rindiq 1 ga kamaysa: faqat ENG ESKI yordamchi (A) ishlaydi", bool(TI.workspace_access(HA, OWN)) and TI.workspace_access(HB, OWN) == {})
        lt = TI.list_team(OWN)
        by = {m["user_id"]: m["active"] for ch in lt["channels"] for m in ch["members"]}
        T.check("ro'yxatda B «faol emas» deb ko'rinadi", by.get(HA) is True and by.get(HB) is False, str(by))
        config.TIER_LIMITS["ultra"]["team_seats"] = 2
        cur.execute("UPDATE users SET plan_type = 'pro' WHERE user_id = %s", (OWN,))
        T.check("egasi PRO ga tushdi: yordamchilarga ruxsat yopiladi, a'zolik saqlanadi",
                TI.workspace_access(HA, OWN) == {} and TI.seat_status(OWN)["used"] == 2)
        ws = TI.workspaces_for(HA)
        T.check("A ish joylari ro'yxatida «to'xtatilgan» deb ko'rinadi", len(ws) == 1 and ws[0]["suspended"] is True, str(ws))
        i7 = None
        T.check("PRO egasi yangi taklif bera olmaydi", TI.create_invite(OWN, CH1, "editor")["error"] == "no_team")
        cur.execute("UPDATE users SET plan_type = 'ultra' WHERE user_id = %s", (OWN,))
        T.check("ULTRA qaytsa ruxsat qaytadi", bool(TI.workspace_access(HA, OWN)))
        cur.execute("UPDATE users SET subscription_expires_at = NOW() - INTERVAL '1 day' WHERE user_id = %s", (OWN,))
        T.check("ULTRA muddati o'tsa — ruxsat yopiq", TI.workspace_access(HA, OWN) == {})
        cur.execute("UPDATE users SET plan_type = 'ultra', subscription_expires_at = NOW() + INTERVAL '30 days' WHERE user_id = %s", (OWN,))
        del i7

        print("\n== 6. Ro'yxat, chiqish, rejim ==")
        lt = TI.list_team(OWN)
        T.check("ro'yxat: 2 kanal, a'zolar va o'rindiqlar", len(lt["channels"]) == 2 and lt["seats"]["limit"] == 2
                and any(m["user_id"] == HA for ch in lt["channels"] for m in ch["members"]), str(lt)[:300])
        T.check("A chiqdi (barcha kanallardan)", TI.leave(HA, OWN) == 2 and TI.workspace_access(HA, OWN) == {} and TI.workspaces_for(HA) == [])
        T.check("rejim: boshida None", TI.get_mode(STR) is None)
        T.check("rejim: o'rnatish/o'qish", TI.set_mode(STR, "owner") and TI.get_mode(STR) == "owner" and TI.set_mode(STR, "helper") and TI.get_mode(STR) == "helper")
        T.check("noto'g'ri rejim rad", not TI.set_mode(STR, "admin") and TI.get_mode(STR) == "helper")
        T.check("yo'q foydalanuvchi rejimi o'rnatilmaydi", not TI.set_mode(9_899_999_999, "owner"))
        print("\n== 5b. Ruxsatlar (har bir yordamchiga alohida) ==")
        T.check("PRESETS: full = hamma ruxsat; analyst = faqat statistika",
                TI.PRESETS["full"] == TI.PERMS and TI.PRESETS["analyst"] == ("analytics",))
        T.check("normalize_perms: noma'lum kalit -> None, bo'sh ro'yxat -> [] (faqat ko'rish), None -> hammasi",
                TI.normalize_perms(["hack"]) is None and TI.normalize_perms([]) == [] and TI.normalize_perms(None) == list(TI.PERMS)
                and TI.normalize_perms(["ai", "create", "create"]) == ["create", "ai"] and TI.normalize_perms("scheduler") == ["create", "reschedule"])
        T.check("can(): view har doim, qolganlari ruxsatga bog'liq", TI.can([], "view") and not TI.can([], "create") and TI.can(["edit"], "edit"))
        T.check("rol belgisi ruxsatlardan hosil bo'ladi", TI.role_for_perms(["edit"]) == "editor" and TI.role_for_perms(["create"]) == "scheduler" and TI.role_for_perms(["analytics"]) == "analyst")
        cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", ([CH1, CH2],))
        cur.execute("UPDATE team_invites SET revoked_at = NOW() WHERE used_at IS NULL AND revoked_at IS NULL")
        T.check("noto'g'ri ruxsat bilan taklif rad", TI.create_invite(OWN, CH1, ["hack"])["error"] == "bad_role")
        T.check("bir nechta kanalga bitta taklif; begona kanal aralashsa rad", TI.create_invite(OWN, [CH1, CHP], ["create"])["error"] == "not_owner")
        mi = TI.create_invite(OWN, [CH1, CH2], ["create", "ai"])
        T.check("ikki kanalga bitta taklif yaratildi", mi["ok"])
        T.check("kutilayotgan taklif ikkala kanalda ko'rinadi", sum(len(c["invites"]) for c in TI.list_team(OWN)["channels"]) == 2)
        acc = TI.accept_invite(mi["token"], HC)
        T.check("qabul: ikkala kanalga a'zo, ruxsatlar [create, ai]", acc["ok"] and acc["channel_ids"] == [CH1, CH2] and acc["perms"] == ["create", "ai"], str(acc))
        wa = TI.workspace_access(HC, OWN)
        T.check("ish joyi: ikkala kanalda [create, ai]; bitta o'rindiq", set(wa) == {CH1, CH2} and wa[CH1]["perms"] == ["create", "ai"] and TI.seat_status(OWN)["used"] == 1)
        T.check("set_member_perms: bitta kanalda o'zgartirish", TI.set_member_perms(OWN, CH2, HC, ["create", "edit", "delete"]) and TI.workspace_access(HC, OWN)[CH2]["perms"] == ["create", "edit", "delete"] and TI.workspace_access(HC, OWN)[CH1]["perms"] == ["create", "ai"])
        T.check("set_helper: kanallar to'plami va ruxsatlar (CH2 olib tashlanadi)", TI.set_helper(OWN, HC, [CH1], ["create", "edit", "send_now"]) and set(TI.workspace_access(HC, OWN)) == {CH1} and TI.workspace_access(HC, OWN)[CH1]["perms"] == ["create", "edit", "send_now"])
        T.check("set_helper: bo'sh ruxsat = faqat ko'rish", TI.set_helper(OWN, HC, [CH1, CH2], []) and TI.workspace_access(HC, OWN)[CH2]["perms"] == [])
        T.check("set_helper: yordamchi bo'lmagan odam/begona kanal/noto'g'ri ruxsat rad", not TI.set_helper(OWN, STR, [CH1], ["create"]) and not TI.set_helper(OWN, HC, [CHP], ["create"]) and not TI.set_helper(OWN, HC, [CH1], ["hack"]))
        cur.execute("UPDATE channel_members SET perms = NULL, role = 'scheduler' WHERE user_id = %s AND channel_id = %s", (HC, CH1))
        T.check("eski a'zo (perms NULL) — rol shablonidan: scheduler = create+reschedule", TI.workspace_access(HC, OWN)[CH1]["perms"] == ["create", "reschedule"])
        TI.leave(HC, OWN)

        print("\n== Z. Qidirish va to'g'ridan-to'g'ri qo'shish (kontakt / @username) ==")
        cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", ([CH1, CH2],))
        cur.execute("DELETE FROM team_invites WHERE owner_id = %s", (OWN,))
        T.check("qidiruv: @username prefiksi (>=3 belgi) topadi", [p["user_id"] for p in TI.search_people(OWN, "@u98000000")] and all(p["user_id"] != OWN for p in TI.search_people(OWN, "u98000000")))
        T.check("qidiruv: aniq username", [p["user_id"] for p in TI.search_people(OWN, f"u{HA}")] == [HA])
        T.check("qidiruv: Telegram ID bo'yicha aniq", [p["user_id"] for p in TI.search_people(OWN, str(HA))] == [HA])
        T.check("qidiruv: 3 belgidan qisqa/bo'sh/juda uzun -> bo'sh", TI.search_people(OWN, "u9") == [] and TI.search_people(OWN, "  ") == [] and TI.search_people(OWN, "x" * 80) == [])
        T.check("qidiruv: egasining o'zi chiqmaydi, % va _ belgilar shablon emas", TI.search_people(OWN, str(OWN)) == [] and TI.search_people(OWN, "%%%") == [] and TI.search_people(OWN, "u_9800") == [])
        T.check("qidiruv: ism bo'yicha EMAS (maxfiylik)", TI.search_people(OWN, "Name9800000003") == [])
        r = TI.add_helper(OWN, HA, [CH1, CH2], ["create", "analytics"])
        T.check("add_helper: ikki kanalga qo'shildi, ruxsatlar to'g'ri", r["ok"] and r["perms"] == ["create", "analytics"] and set(TI.workspace_access(HA, OWN)) == {CH1, CH2} and TI.workspace_access(HA, OWN)[CH1]["perms"] == ["create", "analytics"], str(r))
        T.check("add_helper: o'rindiq band, qidiruvda «member» belgisi", TI.seat_status(OWN)["used"] == 1 and TI.search_people(OWN, str(HA))[0]["member"] is True)
        T.check("add_helper: mavjud yordamchiga qayta — huquqlar yangilanadi, o'rindiq oshmaydi", TI.add_helper(OWN, HA, [CH1], ["ai"])["ok"] and TI.seat_status(OWN)["used"] == 1 and TI.workspace_access(HA, OWN)[CH1]["perms"] == ["ai"])
        T.check("add_helper: o'zini qo'shib bo'lmaydi", TI.add_helper(OWN, OWN, [CH1], ["create"])["error"] == "self")
        T.check("add_helper: botda yo'q odam -> user_unknown", TI.add_helper(OWN, 9_899_999_999, [CH1], ["create"])["error"] == "user_unknown")
        T.check("add_helper: begona kanal -> not_owner, noto'g'ri huquq -> bad_role", TI.add_helper(OWN, HB, [CHP], ["create"])["error"] == "not_owner" and TI.add_helper(OWN, HB, [CH1], ["hack"])["error"] == "bad_role")
        T.check("add_helper: PRO egasi -> no_team", TI.add_helper(PRO, HB, [CHP], ["create"])["error"] == "no_team")
        T.check("add_helper: ikkinchi yordamchi sig'adi, uchinchisi -> seats_full", TI.add_helper(OWN, HB, [CH1], ["create"])["ok"] and TI.add_helper(OWN, HC, [CH1], ["create"])["error"] == "seats_full")
        cur.execute("DELETE FROM channel_members WHERE channel_id = ANY(%s)", ([CH1, CH2],))
        cur.execute("DELETE FROM team_invites WHERE owner_id = %s", (OWN,))
        old_cap = TI.MAX_JOINS_PER_DAY
        TI.MAX_JOINS_PER_DAY = 1
        try:
            T.check("kunlik chegara: birinchi qo'shish o'tadi, ikkinchi yangi odam -> too_many_pending", TI.add_helper(OWN, HA, [CH1], ["create"])["ok"] and TI.add_helper(OWN, HB, [CH1], ["create"])["error"] == "too_many_pending")
        finally:
            TI.MAX_JOINS_PER_DAY = old_cap
        T.check("qo'shilgan odam yordamchi sifatida ish joyini ko'radi (workspaces_for)", [w["owner_id"] for w in TI.workspaces_for(HA)] == [OWN])

    finally:
        config.TIER_LIMITS["ultra"]["team_seats"] = old_seats
        cleanup()
        conn.close()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
