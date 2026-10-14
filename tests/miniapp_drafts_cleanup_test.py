#!/usr/bin/env python3
"""P3: `miniapp_drafts` cheksiz to'planmasligi uchun scheduler tozalashi (cleanup_old_data) 7 kundan eski
qoralamalarni o'chiradi; yangilariga tegmaydi; jadval bo'lmasa qolgan tozalash bekor bo'lmaydi. Real PostgreSQL."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_drafts_cleanup")
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


print("== P3: miniapp_drafts tozalash (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()
from repositories import scheduler_repository as sr  # noqa: E402

OLD, MID, NEW = 9_600_401, 9_600_402, 9_600_403


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def ids():
    return {r[0] for r in q("SELECT user_id FROM miniapp_drafts WHERE user_id = ANY(%s)", ([OLD, MID, NEW],))}


try:
    q("DELETE FROM miniapp_drafts WHERE user_id = ANY(%s)", ([OLD, MID, NEW],))
    for uid, age in ((OLD, "8 days"), (MID, "3 days"), (NEW, "1 hour")):
        q("INSERT INTO miniapp_drafts (user_id, payload, updated_at) VALUES (%s, '{}'::jsonb, NOW() - %s::interval)", (uid, age))
    res = sr.cleanup_old_data()
    check("cleanup natijasida 'miniapp_drafts' hisoblagichi bor", "miniapp_drafts" in res, str(res))
    left = ids()
    check("7 kundan eski qoralama o'chirildi", OLD not in left, str(left))
    check("3 kunlik (TTL o'tgan, lekin <7 kun) va yangi qoralama QOLDI", {MID, NEW} <= left, str(left))
finally:
    q("DELETE FROM miniapp_drafts WHERE user_id = ANY(%s)", ([OLD, MID, NEW],))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
