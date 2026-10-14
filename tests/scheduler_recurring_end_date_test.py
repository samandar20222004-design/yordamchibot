#!/usr/bin/env python3
"""AUDIT-009: (a) recurring post `end_date`dan KEYIN ortiqcha post chiqarmaydi; (b) keyingi davrni rejalash
(vaqt + 'pending') BITTA UPDATE'da (atomik). (a) DB'siz, (b) real PostgreSQL (faqat sinov bazasi)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_enddate")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import scheduler as sched  # noqa: E402
from database import tashkent_tz  # noqa: E402

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


NOW = tashkent_tz.localize(datetime(2026, 10, 14, 10, 0, 0))  # chorshanba (weekday=2)
sched.now_tashkent = lambda: NOW


def marker(rtype, day, rtime, end):
    return sched._build_sent_marker(1, 55, "-100", 0, [], recurrence_type=rtype, recurrence_day=day,
                                    recurrence_time=rtime, end_date=end)


print("== AUDIT-009 (a): end_date chegarasi ==")
m = marker("daily", None, time(10, 0), None)
check("end_date yo'q: keyingi kun rejalashtiriladi (xulq o'zgarmagan)", m["next_time"] and not m["completed"], str(m))
m = marker("daily", None, time(10, 0), NOW + timedelta(days=5))
check("end_date uzoq: keyingi davr rejalashtiriladi", m["next_time"] and not m["completed"], str(m))
m = marker("daily", None, time(10, 0), NOW + timedelta(days=1))
check("keyingi davr == end_date (chegarada): hali rejalashtiriladi", m["next_time"] and not m["completed"], str(m))
m = marker("daily", None, time(10, 0), NOW + timedelta(hours=20))
check("keyingi davr end_date'dan KEYIN: rejalashtirilmaydi, post yakunlanadi", m["next_time"] is None and m["completed"] is True, str(m))
m = marker("daily", None, time(10, 0), NOW - timedelta(minutes=1))
check("end_date o'tgan: yakunlanadi (xulq o'zgarmagan)", m["next_time"] is None and m["completed"] is True, str(m))
m = marker("daily", None, time(10, 0), (NOW + timedelta(hours=20)).replace(tzinfo=None))
check("naive end_date (Toshkent deb olinadi): keyingi davr undan keyin — yakunlanadi", m["completed"] is True, str(m))
m = marker("weekly", 2, time(10, 0), NOW + timedelta(days=3))
check("haftalik: keyingi davr (7 kun) end_date'dan keyin — yakunlanadi", m["completed"] is True and m["next_time"] is None, str(m))
m = marker("weekly", 2, time(10, 0), NOW + timedelta(days=7))
check("haftalik: keyingi davr end_date'da — rejalashtiriladi", bool(m["next_time"]) and not m["completed"], str(m))
m = marker("none", None, None, NOW - timedelta(days=1))
check("oddiy post: recurring mantiqiga tegilmaydi", m["next_time"] is None and m["completed"] is False, str(m))

print("== AUDIT-009 (b): reschedule_recurring_post atomik (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    skipped += 1
else:
    import database as db  # noqa: E402

    db.DATABASE_URL = URL
    db._reset_pool()
    db.init_db()
    from repositories import posts_repository as posts  # noqa: E402

    USER, CHAN = 9_600_300, "-1009600300"

    def q(sql, params=()):
        with db.db_cursor(commit=True) as cur:
            cur.execute(sql, params)
            try:
                return cur.fetchall()
            except Exception:  # noqa: BLE001
                return []

    def cleanup():
        q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
        q("DELETE FROM channels WHERE user_id = %s", (USER,))
        q("DELETE FROM users WHERE user_id = %s", (USER,))

    cleanup()
    try:
        q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "audit009"))
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'A9', TRUE)", (USER, CHAN))
        pid = int(db.add_post(USER, CHAN, "text", "AUDIT-009", None, datetime.now(timezone.utc) - timedelta(days=1), recurrence_type="daily"))
        q("UPDATE scheduled_posts SET status = 'posted', sent_message_id = 5, processing_started_at = NOW() WHERE id = %s", (pid,))
        nxt = datetime.now(timezone.utc) + timedelta(days=1)

        # bitta UPDATE bajarilishi sanaladi
        executed = []
        real = posts.db_cursor

        class Spy:
            def __init__(self, cm):
                self.cm = cm

            def __enter__(self):
                cur = self.cm.__enter__()
                orig = cur.execute

                def counted(sql, params=None):
                    executed.append(str(sql))
                    return orig(sql, params)

                class Wrap:
                    def __getattr__(self, n):
                        return getattr(cur, n)

                    execute = staticmethod(counted)

                return Wrap()

            def __exit__(self, *a):
                return self.cm.__exit__(*a)

        posts.db_cursor = lambda *a, **k: Spy(real(*a, **k))
        try:
            posts.reschedule_recurring_post(pid, nxt)
        finally:
            posts.db_cursor = real
        status, st, started = q("SELECT status, scheduled_time, processing_started_at FROM scheduled_posts WHERE id = %s", (pid,))[0]
        check("reschedule_recurring_post AYNAN 1 ta SQL bajardi", len([e for e in executed if "UPDATE" in e.upper()]) == 1, str(executed))
        check("BITTA UPDATE'dan keyin holat 'pending' (oraliq crash'da 'posted' qolmaydi)", status == "pending", status)
        check("keyingi vaqt yozildi", abs((st - nxt).total_seconds()) < 1, str(st))
        check("processing_started_at tozalandi", started is None, str(started))
        check("scheduler.mark_post_status('pending') ketma-ketligi baribir xavfsiz (idempotent)",
              db.mark_post_status(pid, "pending") in (True, None) and q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0] == "pending")
    finally:
        cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(0 if failed == 0 else 1)
