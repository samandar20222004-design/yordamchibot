#!/usr/bin/env python3
"""Scheduler crash oynalari (real PostgreSQL, faqat sinov bazasi). Telegram'ning exactly-once kafolati YO'Q:
yuborish natijasi noaniq bo'lishi mumkin, shuning uchun bu test dublikat/yo'qotish chegaralarini QOTIRADI va OCHIQ qoldirilganini belgilaydi.

A) XAVFSIZ oynalar (kafolatlangan): crash yuborishdan OLDIN -> post yo'qolmaydi (qayta navbatga); crash `mark_post_as_sent`'dan KEYIN
   ('posted' + delivery 'sent' bitta tranzaksiyada) -> qayta YUBORILMAYDI; recovery 'sent' dalilini hurmat qiladi.
B) OCHIQ oyna (KNOWN-OPEN, hujjatlangan): Telegram'ga CHIQDI, lekin `mark_post_as_sent` COMMIT bo'lmasdan jarayon o'ldi (SENT_JOURNAL_PATH yo'q).
   DB'da yuborilgan dalil YO'Q, shuning uchun restart recovery postni qayta navbatga qo'yadi va keyingi claim kanalni TEKSHIRMAY yuboradi
   (dublikat mumkin). Tuzatish dublikat va "post yo'qolishi" (kanal o'qib bo'lmasa -> 'unknown') o'rtasidagi BIZNES qarori (docs/AUDIT_OPEN_RISKS.md).
C) Crash-loop himoyasi: 5-marta stale 'processing' qayta olinsa delivery 'dead_letter' (post 'failed')."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_crash")
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


print("== scheduler crash oynalari (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories import scheduler_repository as sr  # noqa: E402

USER, CHAN = 9_600_600, "-1009600600"
os.environ.pop("SENT_JOURNAL_PATH", None)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM sent_post_messages WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
    q("DELETE FROM channels WHERE user_id = %s", (USER,))
    q("DELETE FROM users WHERE user_id = %s", (USER,))


def due_post():
    pid = int(db.add_post(USER, CHAN, "text", "crash", None, datetime.now(timezone.utc) - timedelta(minutes=3)))
    return pid, q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))[0][0]


def claim_as_scheduler(pid, t):
    """get_due_posts kabi 'processing' + delivery claim (yuborishdan oldingi holat)."""
    q("UPDATE scheduled_posts SET status = 'processing', processing_started_at = NOW() WHERE id = %s", (pid,))
    return sr.claim_post_delivery(pid, CHAN, t)


def st(pid):
    return q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "crash"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'CR', TRUE)", (USER, CHAN))

    # A1) yuborishdan OLDIN crash: yo'qolmaydi, qayta navbatga, keyin yuboriladi
    pid, t = due_post()
    c = claim_as_scheduler(pid, t)
    check("A1: claim 'processing' (yuborishdan oldin)", c.get("claimed") is True)
    res = sr.recover_processing_posts_on_startup(0)
    check("A1: restart recovery postni YO'QOTMADI — 'pending'", st(pid) == "pending" and res["requeued"] >= 1, str(res))
    c2 = sr.claim_post_delivery(pid, CHAN, t)
    check("A1: keyingi claim yuborishga ruxsat beradi", c2.get("claimed") is True, str(c2))

    # A2) mark_post_as_sent KEYIN crash: qayta YUBORILMAYDI
    pid2, t2 = due_post()
    c = claim_as_scheduler(pid2, t2)
    ok = db.mark_post_as_sent(pid2, 555, CHAN, 0, None, c["idempotency_key"])  # Telegram'ga chiqdi + atomik marker
    check("A2: mark_post_as_sent (posted + delivery sent) bitta tranzaksiyada", ok is True and st(pid2) == "posted")
    sr.recover_processing_posts_on_startup(0)
    check("A2: recovery 'posted' postga tegmaydi", st(pid2) == "posted")
    c3 = sr.claim_post_delivery(pid2, CHAN, t2)
    check("A2: qayta claim: sent=True, claimed=False (QAYTA YUBORILMAYDI)", c3.get("sent") is True and c3.get("claimed") is False, str(c3))

    # A3) 'sent' delivery bor, lekin post 'processing'da qolgan (marker yarim yozilgan): recovery 'posted' qiladi
    pid3, t3 = due_post()
    c = claim_as_scheduler(pid3, t3)
    q("UPDATE post_deliveries SET status = 'sent', telegram_message_id = 777 WHERE idempotency_key = %s", (c["idempotency_key"],))
    sr.recover_processing_posts_on_startup(0)
    check("A3: delivery 'sent' dalili bo'lsa recovery 'posted' qiladi (dublikat yo'q)", st(pid3) == "posted", st(pid3))

    # B) OCHIQ OYNA: Telegram'ga chiqdi, DB marker YO'Q -> recovery qayta navbatga, keyingi claim kanalni tekshirmay yuboradi
    pid4, t4 = due_post()
    c = claim_as_scheduler(pid4, t4)
    # ... bu yerda bot Telegram'ga yubordi va crash bo'ldi: DB'da hech narsa yozilmadi ...
    sr.recover_processing_posts_on_startup(0)
    again = sr.claim_post_delivery(pid4, CHAN, t4)
    check("B [KNOWN-OPEN]: DB'da yuborilgan dalil yo'q -> post qayta navbatga qo'yiladi", st(pid4) == "pending")
    check("B [KNOWN-OPEN]: keyingi claim verify markersiz (kanal tekshirilmaydi) — dublikat MUMKIN (Telegram exactly-once bermaydi)",
          again.get("claimed") is True and not again.get("verify_pending"), str(again))

    # C) crash-loop himoyasi: stale 'processing' delivery 5-marta qayta olinsa dead_letter
    pid5, t5 = due_post()
    sr.claim_post_delivery(pid5, CHAN, t5)
    last = None
    for _ in range(5):
        q("UPDATE post_deliveries SET status = 'processing', updated_at = NOW() - interval '20 minutes' WHERE post_id = %s", (pid5,))
        last = sr.claim_post_delivery(pid5, CHAN, t5)
    check("C: 5-stale-reclaim -> dead_letter (crash-loop to'xtatiladi, post avtomatik qayta yuborilmaydi)",
          last.get("dead") is True and last.get("status") == "dead_letter", str(last))

    # D) recurring: yuborildi -> qayta rejalash oralig'ida crash (AUDIT-003/009 qoldig'i)
    rid = int(db.add_post(USER, CHAN, "text", "rec", None, datetime.now(timezone.utc) - timedelta(minutes=3), recurrence_type="daily"))
    rt = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid,))[0][0]
    c = claim_as_scheduler(rid, rt)
    db.mark_post_as_sent(rid, 556, CHAN, 0, None, c["idempotency_key"])
    # ... crash: reschedule_recurring_post chaqirilmadi ...
    sr.recover_processing_posts_on_startup(0)
    sr.recover_stale_processing_posts()
    check("D [KNOWN-OPEN]: recurring post 'posted'da QOLADI (keyingi davr rejalashtirilmaydi, seriya to'xtaydi) — recovery tuzatmaydi",
          st(rid) == "posted", st(rid))
    nxt = datetime.now(timezone.utc) + timedelta(days=1)
    db.reschedule_recurring_post(rid, nxt)
    check("D: normal oqimda (reschedule chaqirilsa) post 'pending' va keyingi vaqt yozilgan",
          st(rid) == "pending" and abs((q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid,))[0][0] - nxt).total_seconds()) < 1)
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
