#!/usr/bin/env python3
"""Scheduler: `attempt_count` retry'lar orasida (real PostgreSQL, faqat sinov bazasi).

Muammo (AUDIT-002 qoldig'i): `retry_post` scheduled_time'ni o'zgartiradi -> delivery kaliti yangilanadi -> HAR retry yangi qator va
`attempt_count` 0 dan. Natija: backoff (30s/2m/5m/15m) o'smaydi va "5-urinishdan keyin dead_letter" qoidasi tarmoq-xatosi retry
yo'lida ishlamaydi (cheksiz retry, har safar yangi qator).

Tuzatish OPT-IN (`DELIVERY_CARRY_ATTEMPTS=1`, sukut O'CHIQ): sukut xulq O'ZGARMAGAN, chunki dead_letter'ga tushish uzoq Telegram uzilishida
(~22 daqiqa) postni 'failed' qilib YO'QOTADI — bu biznes qarori. Bu test ikkala rejimni qotiradi.

Telegram yuborish natijasi noaniq bo'lishi mumkin; bu test exactly-once VA'DA QILMAYDI — faqat sanagich/backoff/dead_letter mantig'ini tekshiradi.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_attempts")
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


print("== scheduler attempt_count retry'lar orasida (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories import scheduler_repository as sr  # noqa: E402
from services.scheduler_service import SchedulerService  # noqa: E402

USER, CHAN = 9_600_500, "-1009600500"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
    q("DELETE FROM channels WHERE user_id = %s", (USER,))
    q("DELETE FROM users WHERE user_id = %s", (USER,))


def new_post():
    return int(db.add_post(USER, CHAN, "text", "attempts", None, datetime.now(timezone.utc) - timedelta(minutes=5)))


def loop(pid, rounds):
    """Scheduler sikli: claim -> tarmoq xatosi (mark_as_failed) -> retry_post (o'tgan vaqt, ya'ni darhol yana navbatda)."""
    out = []
    for n in range(rounds):
        t = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))[0][0]
        claim = sr.claim_post_delivery(pid, CHAN, t)
        if not claim.get("claimed"):
            out.append({"claimed": False, "claim": claim})
            break
        res = SchedulerService.mark_as_failed(pid, CHAN, "NetworkError: connection reset", True,
                                              scheduled_time=t, idempotency_key=claim["idempotency_key"])
        out.append({"claimed": True, "res": res})
        if res.get("status") == "dead_letter":
            break
        db.retry_post(pid, datetime.now(timezone.utc) - timedelta(seconds=1 + n))  # vaqt har safar boshqa -> yangi kalit
    return out


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "attempts"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'AT', TRUE)", (USER, CHAN))

    # 1) SUKUT (flag o'chiq): hozirgi xulq qotiriladi
    os.environ.pop("DELIVERY_CARRY_ATTEMPTS", None)
    pid = new_post()
    out = loop(pid, 7)
    counts = [o["res"].get("attempt_count") for o in out if o.get("claimed")]
    backs = [o["res"].get("backoff_seconds") for o in out if o.get("claimed")]
    check("SUKUT: 7 ta ketma-ket tarmoq xatosidan keyin ham dead_letter YO'Q (hozirgi xulq)",
          all(o.get("claimed") and o["res"].get("status") == "failed" for o in out) and len(out) == 7, str(out)[:200])
    check("SUKUT: attempt_count har retry'da 1 ga qaytadi (yig'ilmaydi)", counts == [1] * 7, str(counts))
    check("SUKUT: backoff o'smaydi (har safar 30 s)", backs == [30] * 7, str(backs))
    check("SUKUT: har retry yangi delivery qatori", q("SELECT COUNT(*) FROM post_deliveries WHERE post_id = %s", (pid,))[0][0] == 7)
    check("SUKUT: post yo'qolmadi — hali 'pending' (retry qilinadi)", q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0] == "pending")

    # 2) OPT-IN (DELIVERY_CARRY_ATTEMPTS=1): hujjatlangan qoida — sanagich yig'iladi, backoff o'sadi, 5-urinishda dead_letter
    os.environ["DELIVERY_CARRY_ATTEMPTS"] = "1"
    pid2 = new_post()
    out = loop(pid2, 7)
    counts = [o["res"].get("attempt_count") for o in out if o.get("claimed")]
    backs = [o["res"].get("backoff_seconds") for o in out if o.get("claimed") and o["res"].get("status") == "failed"]
    last = out[-1]["res"] if out and out[-1].get("claimed") else {}
    check("OPT-IN: attempt_count yig'iladi 1,2,3,4,5", counts == [1, 2, 3, 4, 5], str(counts))
    check("OPT-IN: backoff 30 -> 120 -> 300 -> 900 o'sadi", backs == [30, 120, 300, 900], str(backs))
    check("OPT-IN: 5-urinishda dead_letter (attempts_exhausted), sikl to'xtaydi", last.get("status") == "dead_letter" and len(out) == 5, str(out)[-200:])
    # 'sent' predecessor'dan hech narsa ko'chmasligi
    pid3 = new_post()
    t = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid3,))[0][0]
    c1 = sr.claim_post_delivery(pid3, CHAN, t)
    SchedulerService.mark_as_failed(pid3, CHAN, "NetworkError", True, scheduled_time=t, idempotency_key=c1["idempotency_key"])
    q("UPDATE post_deliveries SET status = 'sent', telegram_message_id = 9 WHERE idempotency_key = %s", (c1["idempotency_key"],))
    db.retry_post(pid3, datetime.now(timezone.utc) - timedelta(seconds=3))
    t2 = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid3,))[0][0]
    c2 = sr.claim_post_delivery(pid3, CHAN, t2)
    n2 = q("SELECT attempt_count FROM post_deliveries WHERE idempotency_key = %s", (c2["idempotency_key"],))[0][0]
    check("OPT-IN: 'sent' predecessor'dan attempt_count ko'chmaydi (0)", n2 == 0, str(n2))
    # verify markeri ham flagdan mustaqil ko'chadi
    pid4 = new_post()
    t = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid4,))[0][0]
    k = sr.claim_post_delivery(pid4, CHAN, t)["idempotency_key"]
    sr.mark_post_delivery_verify_pending(k, "TimedOut", 1, 1.0)
    db.retry_post(pid4, datetime.now(timezone.utc) - timedelta(seconds=3))
    c = sr.claim_post_delivery(pid4, CHAN, q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid4,))[0][0])
    check("OPT-IN: verify markeri (AUDIT-002) flag yoqilganda ham ko'chadi", c.get("verify_pending") is True, str(c))
finally:
    os.environ.pop("DELIVERY_CARRY_ATTEMPTS", None)
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
