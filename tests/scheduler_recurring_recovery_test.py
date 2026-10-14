#!/usr/bin/env python3
"""AUDIT-003: restart/stale recovery recurring postni 'posted'ga o'tkazib SERIYANI o'ldirmasligi kerak.

Recurring postning 2-davridan boshlab `sent_message_id`, `sent_post_messages` va eski 'sent' delivery qatorlari
OLDINGI davrlardan qoladi. Eski recovery ularni "shu davr yuborildi" isboti deb hisoblab 'processing'dagi postni
'posted'ga o'tkazardi (keyingi davr rejalashtirilmaydi). To'g'ri: recurring uchun dalil FAQAT shu davrning
delivery yozuvi (`post_deliveries.status='sent'` va `scheduled_time` = postning joriy scheduled_time). Oddiy
(takrorlanmaydigan) postlar xulqi O'ZGARMAGAN. Real PostgreSQL (faqat sinov bazasi).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_recurring")
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


print("== AUDIT-003: recurring post recovery (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories import scheduler_repository as sr  # noqa: E402

USER = 9_600_200
CHAN = "-1009600200"
NOW = datetime.now(timezone.utc)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    ids = "SELECT id FROM scheduled_posts WHERE user_id = %s"
    q(f"DELETE FROM post_deliveries WHERE post_id IN ({ids})", (USER,))  # nosec B608 — ichki literal
    q(f"DELETE FROM sent_post_messages WHERE post_id IN ({ids})", (USER,))  # nosec B608
    q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
    q("DELETE FROM channels WHERE user_id = %s", (USER,))
    q("DELETE FROM users WHERE user_id = %s", (USER,))


def mk(recurrence="none", sent_message=False, sent_msgs_row=False, delivery=None, delivery_same_time=False):
    """'processing'da qolgan post + dalillar. delivery: None | 'sent' | 'unknown'."""
    t_prev = NOW - timedelta(days=1)
    pid = int(db.add_post(USER, CHAN, "text", "AUDIT-003", None, t_prev, recurrence_type=recurrence))
    cur_time = NOW - timedelta(minutes=1)
    q("UPDATE scheduled_posts SET scheduled_time = %s, status = 'processing', "
      "processing_started_at = NOW() - interval '30 minutes', sent_message_id = %s WHERE id = %s",
      (cur_time, 777 if sent_message else None, pid))
    if sent_msgs_row:
        q("INSERT INTO sent_post_messages (post_id, channel_id, message_id) VALUES (%s, %s, 777)", (pid, CHAN))
    if delivery:
        when = cur_time if delivery_same_time else t_prev
        q("INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, scheduled_time, telegram_message_id) "
          "VALUES (%s, %s, %s, %s, %s, 777)", (pid, int(CHAN), delivery, f"k_{pid}_{delivery}_{int(delivery_same_time)}", when))
    return pid


def status(pid):
    return q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]


def scenario(label, recover):
    print(f"-- {label}")
    # recurring: oldingi davrlar dalillari bor, shu davr YUBORILMAGAN (crash yuborishdan oldin)
    r1 = mk("daily", sent_message=True, sent_msgs_row=True, delivery="sent")
    r2 = mk("weekly", sent_message=True)
    # recurring: shu davr yuborilgan (delivery shu scheduled_time bilan 'sent') — xulq O'ZGARMAGAN: 'posted'
    r3 = mk("daily", sent_message=True, sent_msgs_row=True, delivery="sent", delivery_same_time=True)
    # recurring: oldingi davr 'unknown' (albom) — xulq O'ZGARMAGAN
    r4 = mk("daily", delivery="unknown")
    # oddiy postlar: xulq O'ZGARMAGAN
    n1 = mk("none", sent_message=True)
    n2 = mk("none")
    n3 = mk("none", delivery="sent")
    n4 = mk("none", delivery="unknown")
    n5 = mk("none", sent_msgs_row=True)
    recover()
    check("recurring (oldingi davrlar yuborilgan, shu davr yo'q): 'pending' — SERIYA TIRIK", status(r1) == "pending", status(r1))
    check("recurring (haftalik, faqat eski sent_message_id): 'pending'", status(r2) == "pending", status(r2))
    check("recurring, shu davr yuborilgani delivery bilan isbotlangan: 'posted' (xulq o'zgarmagan)", status(r3) == "posted", status(r3))
    if recover.__name__ == "startup":
        check("recurring, oldingi davr 'unknown': 'unknown' (xulq o'zgarmagan)", status(r4) == "unknown", status(r4))
        check("oddiy post + 'sent' delivery: 'posted'", status(n3) == "posted", status(n3))
        check("oddiy post + 'unknown' delivery: 'unknown'", status(n4) == "unknown", status(n4))
    check("oddiy post + sent_message_id: 'posted' (xulq o'zgarmagan)", status(n1) == "posted", status(n1))
    check("oddiy post, dalilsiz: 'pending' (xulq o'zgarmagan)", status(n2) == "pending", status(n2))
    check("oddiy post + sent_post_messages: 'posted' (xulq o'zgarmagan)", status(n5) == "posted", status(n5))
    left = q("SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = 'processing' AND id = ANY(%s)", (USER, [r1, r2, r3, n1, n2, n5]))[0][0]
    check("'processing'da qotib qolgan post yo'q", left == 0, str(left))


def startup():
    return sr.recover_processing_posts_on_startup(0)


def stale():
    return sr.recover_stale_processing_posts()


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "audit003"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'A3', TRUE)", (USER, CHAN))
    scenario("restart recovery (recover_processing_posts_on_startup)", startup)
    q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM sent_post_messages WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
    scenario("stale recovery (recover_stale_processing_posts)", stale)
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
