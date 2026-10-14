#!/usr/bin/env python3
"""Kvota bronini qaytarish: kecha (kunlik reset'dan OLDIN) yaratilgan bron BUGUNGI hisoblagichni kamaytirmaydi.

Nuqson (tuzatilgan): `refund_ai_request` quota-yo'lida hisoblagich shartsiz kamaytirilardi; yarim tundan keyin
kechagi bron qaytarilsa foydalanuvchi bugun bepul so'rov ortiqcha olardi. Real PostgreSQL (INTEGRITY_/P0_/STEP5_/
MINIAPP_TEST_DATABASE_URL); URL yo'q bo'lsa SKIP.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

URL = ""
for _var in ("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL", "MINIAPP_TEST_DATABASE_URL"):
    _v = os.getenv(_var, "")
    if _v and "user:pass" not in _v:
        URL = _v
        break
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
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


print("== Bronni qaytarish va kunlik davr ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q — o'tkazilmadi")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()
BASE = 9_500_000
IDS = list(range(BASE, BASE + 20))


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM ai_reservations WHERE user_id = ANY(%s)", (IDS,))
    q("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (IDS,))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (IDS,))


def used(uid):
    return q("SELECT COALESCE(ai_requests_today, 0) FROM users WHERE user_id = %s", (uid,))[0][0]


def mk(uid):
    q("INSERT INTO users (user_id, username, plan_type, ai_requests_today, last_limit_reset, ai_credits) "
      "VALUES (%s, %s, 'free', 0, CURRENT_DATE, 0)", (uid, f"r{uid}"))


cleanup()
try:
    a, b = BASE + 1, BASE + 2
    mk(a)
    r = db.reserve_ai_request(a, "other", 1)
    check("bugungi bron: kvota yo'li, hisoblagich 1", r.get("allowed") and r.get("source") == "daily_quota" and used(a) == 1, str(r))
    res = db.refund_ai_request(a, r["reservation_id"])
    check("o'sha kuni qaytarish: hisoblagich 1 -> 0", res.get("success") and used(a) == 0, str(res))
    res2 = db.refund_ai_request(a, r["reservation_id"])
    check("qayta qaytarish: idempotent (already_refunded), hisoblagich o'zgarmaydi", not res2.get("success") and used(a) == 0, str(res2))

    # Yarim tun: kechagi bron + yangi kun
    mk(b)
    old = db.reserve_ai_request(b, "other", 1)
    q("UPDATE users SET last_limit_reset = CURRENT_DATE - 1 WHERE user_id = %s", (b,))
    q("UPDATE ai_reservations SET created_at = created_at - INTERVAL '1 day' WHERE id = %s", (old["reservation_id"],))
    new = db.reserve_ai_request(b, "other", 1)  # yangi kun: hisoblagich nollanadi, bugungi 1-so'rov
    check("yangi kunda bugungi bron: hisoblagich 1", new.get("allowed") and used(b) == 1, f"{new} used={used(b)}")
    res = db.refund_ai_request(b, old["reservation_id"])
    check("KECHAGI bron qaytarildi (muvaffaqiyatli), lekin BUGUNGI hisoblagich o'zgarmadi (1)",
          res.get("success") and used(b) == 1, f"{res} used={used(b)}")
    st = q("SELECT status FROM ai_reservations WHERE id = %s", (old["reservation_id"],))[0][0]
    check("kechagi bron 'refunded' deb belgilandi", st == "refunded", st)
    res = db.refund_ai_request(b, new["reservation_id"])
    check("BUGUNGI bronni qaytarish hisoblagichni kamaytiradi (1 -> 0)", res.get("success") and used(b) == 0, f"{res} used={used(b)}")
finally:
    cleanup()
    db.close_pool()

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(0 if failed == 0 else 1)
