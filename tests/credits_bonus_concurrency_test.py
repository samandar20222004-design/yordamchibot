#!/usr/bin/env python3
"""Kunlik faollik bonusi (+2) parallel chaqiruvda FAQAT BIR MARTA beriladi (real PostgreSQL).

Nuqson: `_maybe_grant_activity_bonus_in_tx` da "bugun berilganmi" tekshiruvi va grant orasida
qator qulfi yo'q edi, `credits_ledger`da UNIQUE cheklov ham yo'q -> ikki parallel tranzaksiya
(ikki instance yoki parallel AI bron) bonusni ikki marta berardi. Tuzatish: users qatorini
`FOR UPDATE` bilan qulflash (sxema o'zgarishsiz).

Real PostgreSQL: INTEGRITY_TEST_DATABASE_URL | P0_TEST_DATABASE_URL (faqat SINOV bazasi).
URL yo'q bo'lsa SKIP (natija PASS hisoblanmaydi).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


uri = ""
for var in ("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL"):
    if os.getenv(var) and "user:pass" not in os.getenv(var, ""):
        uri = os.environ[var]
        break
if not uri:
    print("== Bonus parallelligi (real PG) ==")
    print("  [SKIP] INTEGRITY_TEST_DATABASE_URL / P0_TEST_DATABASE_URL yo'q — real PostgreSQL testi o'tkazilmadi")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

os.environ["DATABASE_URL"] = uri
db.DATABASE_URL = uri
db._reset_pool()
db.init_db()

from services.credits_service import (  # noqa: E402
    ACTIVITY_BONUS_AMOUNT,
    ACTIVITY_BONUS_THRESHOLD,
    OP_ACTIVITY_BONUS,
    CreditsService,
)

BASE = 9_300_000
IDS = list(range(BASE, BASE + 200))


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


def seed(uid, reservations=ACTIVITY_BONUS_THRESHOLD):
    q("INSERT INTO users (user_id, username, ai_credits) VALUES (%s, %s, 0)", (uid, f"bonus_{uid}"))
    for _ in range(reservations):
        q("INSERT INTO ai_reservations (user_id, operation_type, cost, source, status) "
          "VALUES (%s, 'other', 1, 'daily_quota', 'active')", (uid,))


def bonus_rows(uid):
    return q("SELECT COUNT(*) FROM credits_ledger WHERE user_id = %s AND operation_type = %s",
             (uid, OP_ACTIVITY_BONUS))[0][0]


def balance(uid):
    return q("SELECT ai_credits FROM users WHERE user_id = %s", (uid,))[0][0]


def race(uids, per_user):
    barrier = threading.Barrier(len(uids) * per_user)
    results = {u: [] for u in uids}

    def work(uid):
        barrier.wait()
        results[uid].append(CreditsService.maybe_grant_activity_bonus(uid))

    threads = [threading.Thread(target=work, args=(u,)) for u in uids for _ in range(per_user)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


cleanup()
try:
    print("== Bonus parallelligi (real PostgreSQL) ==")
    # 10 raund x 4 foydalanuvchi x 3 parallel chaqiruv
    doubled = total = 0
    grants_ok = True
    for rnd in range(10):
        uids = [BASE + rnd * 4 + i for i in range(4)]
        for u in uids:
            seed(u)
        res = race(uids, 3)
        for u in uids:
            total += 1
            doubled += bonus_rows(u) > 1
            granted = sum(1 for r in res[u] if r.get("granted"))
            grants_ok = grants_ok and granted == 1 and balance(u) == ACTIVITY_BONUS_AMOUNT
    check(f"{total} foydalanuvchi x 3 parallel chaqiruv: ikki marta berilgan = 0", doubled == 0, f"({doubled}/{total})")
    check("har bir foydalanuvchida AYNAN 1 ta granted=True va balans = +bonus", grants_ok)

    # Tekshiruv va INSERT orasiga sun'iy kechikish (oyna kengaytirilgan) — qulf bo'lsa baribir 1 marta
    orig = CreditsService.count_today_ai_requests

    def slow(user_id, cur=None):
        result = orig(user_id, cur=cur)
        time.sleep(0.2)
        return result

    CreditsService.count_today_ai_requests = staticmethod(slow)
    try:
        uids = [BASE + 100 + i for i in range(3)]
        for u in uids:
            seed(u)
        race(uids, 2)
    finally:
        CreditsService.count_today_ai_requests = staticmethod(orig)
    check("kengaytirilgan oyna (0.2s): ikki marta berilmagan", all(bonus_rows(u) == 1 for u in uids),
          str([bonus_rows(u) for u in uids]))

    # Xulq-atvor o'zgarmasligi
    u = BASE + 150
    seed(u, reservations=ACTIVITY_BONUS_THRESHOLD - 1)
    r = CreditsService.maybe_grant_activity_bonus(u)
    check("chegaraga yetmagan: granted=False, threshold_not_reached",
          r.get("granted") is False and r.get("reason") == "threshold_not_reached", str(r))
    q("INSERT INTO ai_reservations (user_id, operation_type, cost, source, status) "
      "VALUES (%s, 'other', 1, 'daily_quota', 'active')", (u,))
    r1 = CreditsService.maybe_grant_activity_bonus(u)
    r2 = CreditsService.maybe_grant_activity_bonus(u)
    check("ketma-ket: 1-chaqiruv granted, 2-chaqiruv already_granted_today",
          r1.get("granted") is True and r2.get("granted") is False
          and r2.get("reason") == "already_granted_today", f"{r1} {r2}")
    r3 = CreditsService.maybe_grant_activity_bonus(BASE + 199)
    check("mavjud bo'lmagan foydalanuvchi: granted=False", r3.get("granted") is False, str(r3))
finally:
    cleanup()
    db.close_pool()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(0 if failed == 0 else 1)
