#!/usr/bin/env python3
"""Ovozli rejalash kvotasi (real PostgreSQL, faqat sinov bazasi): free bir martalik, PRO kuniga cheklangan, atomik.

* free: butun umr bo'yicha 1 ta; qaytarilgan bron imkoniyatni qaytaradi; 10 ta parallel so'rovdan AYNAN bittasi o'tadi;
* PRO: oxirgi 24 soatda 20 ta; 24 soatdan eski qatorlar hisobga kirmaydi; admin cheksiz va qator yozmaydi;
* DB xatosida fail-closed; foydalanuvchilar mustaqil; boshqa foydalanuvchi bronini qaytara olmaydi;
* tozalash: faqat PRO'ning 3 kundan eski qatorlari; free'ning butun-umr hisobi saqlanadi; hisob o'chirilsa qatorlar ham ketadi.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_voice")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:VOICE_QUOTA_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== Ovozli rejalash kvotasi (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import config  # noqa: E402
import database as db  # noqa: E402
from services import voice_schedule_quota as vq  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

FREE, FREE2, PRO, PRO_OLD, ADM, GONE = 9_700_001, 9_700_002, 9_700_003, 9_700_004, 9_700_005, 9_700_006
USERS = (FREE, FREE2, PRO, PRO_OLD, ADM, GONE)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def count(uid):
    return q("SELECT COUNT(*) FROM voice_schedule_usage WHERE user_id = %s", (uid,))[0][0]


def cleanup():
    q("DELETE FROM voice_schedule_usage WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (list(USERS),))


def R(uid, pro=False, admin=False):
    return asyncio.run(vq.reserve(db, uid, pro, admin))


cleanup()
try:
    for uid, plan in ((FREE, "free"), (FREE2, "free"), (PRO, "pro"), (PRO_OLD, "pro"), (ADM, "free"), (GONE, "free")):
        q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, %s)", (uid, f"v{uid}", plan))

    check("config: free 1 ta (butun umr), PRO 20 ta (kuniga)", config.FREE_VOICE_SCHEDULE_TOTAL == 1 and config.PRO_VOICE_SCHEDULE_DAILY == 20)

    # --- free: bir martalik ---
    a = R(FREE)
    check("free: birinchi imkoniyat beriladi (scope=lifetime, 1/1)", a["allowed"] and a["scope"] == "lifetime" and a["used"] == 1 and a["limit"] == 1, str(a))
    b = R(FREE)
    check("free: ikkinchisi rad etiladi (reason=limit)", not b["allowed"] and b["reason"] == "limit" and count(FREE) == 1, str(b))
    asyncio.run(vq.release(db, FREE, a["reservation_id"]))
    check("transkripsiya muvaffaqiyatsiz -> bron qaytarildi -> imkoniyat yana bor", count(FREE) == 0 and R(FREE)["allowed"])
    q("UPDATE voice_schedule_usage SET used_at = NOW() - INTERVAL '400 days' WHERE user_id = %s", (FREE,))
    check("free: butun umr — 400 kun oldingi foydalanish ham hisobda (qayta berilmaydi)", not R(FREE)["allowed"])
    check("boshqa free foydalanuvchi mustaqil", R(FREE2)["allowed"])

    # --- parallel: AYNAN bitta ---
    q("DELETE FROM voice_schedule_usage WHERE user_id = %s", (FREE,))

    async def burst():
        return await asyncio.gather(*[vq.reserve(db, FREE, False) for _ in range(12)])

    res = asyncio.run(burst())
    check("12 ta parallel so'rovdan AYNAN bittasi o'tdi (free bir martalik ikki marta berilmaydi)",
          sum(1 for r in res if r["allowed"]) == 1 and count(FREE) == 1, str([r["allowed"] for r in res]))

    # --- boshqa foydalanuvchi bronini qaytara olmaydi ---
    rid = q("SELECT id FROM voice_schedule_usage WHERE user_id = %s", (FREE,))[0][0]
    asyncio.run(vq.release(db, FREE2, rid))
    check("begona foydalanuvchi bronni o'chira olmaydi (IDOR)", count(FREE) == 1)

    # --- PRO: 24 soatda 20 ta ---
    got = [R(PRO, pro=True) for _ in range(20)]
    check("PRO: 20 ta imkoniyat beriladi (scope=day)", all(g["allowed"] for g in got) and got[-1]["used"] == 20 and got[-1]["scope"] == "day")
    over = R(PRO, pro=True)
    check("PRO: 21-chisi rad etiladi", not over["allowed"] and over["reason"] == "limit" and count(PRO) == 20, str(over))
    q("UPDATE voice_schedule_usage SET used_at = NOW() - INTERVAL '25 hours' WHERE id = (SELECT id FROM voice_schedule_usage WHERE user_id = %s LIMIT 1)", (PRO,))
    check("PRO: 24 soatdan eski qator hisobga kirmaydi -> yana 1 ta bo'sh joy", R(PRO, pro=True)["allowed"])

    # --- admin ---
    adm = [R(ADM, admin=True) for _ in range(30)]
    check("admin: cheksiz va qator yozilmaydi", all(a_["allowed"] for a_ in adm) and count(ADM) == 0)

    # --- fail-closed ---
    orig = db.reserve_voice_schedule
    db.reserve_voice_schedule = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
    try:
        r = R(FREE2)
    finally:
        db.reserve_voice_schedule = orig
    check("DB xatosi: FAIL-CLOSED (imkoniyat berilmaydi, reason=unavailable)", not r["allowed"] and r["reason"] == "unavailable", str(r))

    # --- o'chirilgan sozlama ---
    old = config.FREE_VOICE_SCHEDULE_TOTAL
    config.FREE_VOICE_SCHEDULE_TOTAL = 0
    try:
        check("FREE_VOICE_SCHEDULE_TOTAL=0: o'chiq (reason=disabled)", R(GONE)["reason"] == "disabled" and count(GONE) == 0)
    finally:
        config.FREE_VOICE_SCHEDULE_TOTAL = old

    # --- tozalash ---
    q("INSERT INTO voice_schedule_usage (user_id, used_at) VALUES (%s, NOW() - INTERVAL '10 days'), (%s, NOW() - INTERVAL '10 days'), (%s, NOW() - INTERVAL '1 day')",
      (PRO_OLD, FREE2, PRO_OLD))
    q("UPDATE voice_schedule_usage SET used_at = NOW() - INTERVAL '10 days' WHERE user_id = %s", (FREE,))
    out = db.cleanup_old_data()
    check("cleanup natijasida 'voice_schedule_usage' hisoblagichi bor", "voice_schedule_usage" in out, str(out)[:200])
    check("tozalash: PRO'ning 10 kunlik qatori o'chdi, 1 kunligi qoldi", count(PRO_OLD) == 1)
    check("tozalash: FREE'ning eski qatorlari SAQLANDI (butun umr hisobi buzilmaydi)", count(FREE2) >= 1 and count(FREE) >= 1)

    # --- hisobni o'chirish ---
    q("INSERT INTO voice_schedule_usage (user_id) VALUES (%s)", (GONE,))
    res = db.delete_user_data(GONE)
    check("hisob o'chirilganda kvota qatorlari ham o'chadi", res.get("ok") and count(GONE) == 0 and "voice_schedule_usage" in res.get("cleaned", {}), str(res)[:200])
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
