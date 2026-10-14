#!/usr/bin/env python3
"""AUDIT-002: `retry_post` `scheduled_time`ni qayta yozadi, delivery kaliti esa (post, kanal, scheduled_time)dan
tuziladi -> retry'dan keyin YANGI kalit/yangi qator. "Kanal tekshiruvi kutilmoqda" (AMBIGUOUS_VERIFY) markeri eski
qatorda qolsa, keyingi claim uni ko'rmaydi va scheduler TimedOut'dan keyin kanalni TEKSHIRMAY ko'r-ko'rona qayta
yuboradi (dublikat). Real PostgreSQL (faqat sinov bazasi).

Tuzatish chegarasi: faqat verify markeri oldingi (failed) qatordan YANGI qatorga ko'chadi; kalit formati, unique
constraint, attempt_count/backoff semantikasi, 'sent' qatorlar va recurring keyingi davr O'ZGARMAYDI.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_retry_idem")
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


print("== AUDIT-002: retry_post + delivery kaliti + verify markeri (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

from datetime import datetime, timedelta, timezone  # noqa: E402

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories import scheduler_repository as sr  # noqa: E402

USER = 9_600_100
CHAN = "-1009600100"


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
    pid = db.add_post(USER, CHAN, "text", "AUDIT-002", None, datetime.now(timezone.utc) - timedelta(minutes=2))
    return int(pid)


def sched_time(pid):
    return q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))[0][0]


def retry(pid, seconds):
    db.retry_post(pid, datetime.now(timezone.utc) + timedelta(seconds=seconds))


def row(key):
    r = q("SELECT status, attempt_count, last_error FROM post_deliveries WHERE idempotency_key = %s", (key,))
    return r[0] if r else None


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "audit002"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'A2', TRUE)", (USER, CHAN))

    # 1) noaniq yuborish -> verify markeri -> retry_post (scheduled_time o'zgaradi) -> keyingi claim markerni KO'RISHI shart
    pid = new_post()
    t1 = sched_time(pid)
    c1 = sr.claim_post_delivery(pid, CHAN, t1)
    key1 = c1["idempotency_key"]
    check("1-claim: claimed=True", c1.get("claimed") is True, str(c1))
    res = sr.mark_post_delivery_verify_pending(key1, "TimedOut", 1, 1.0)
    check("noaniq yuborish: verify markeri yozildi", res.get("ok") is True and sr.delivery_verify_pending(row(key1)[2]), str(res))
    retry(pid, -1)  # retry_post: scheduled_time endi boshqa (o'tgan) vaqt
    t2 = sched_time(pid)
    check("retry_post scheduled_time'ni o'zgartirdi (kalit o'zgaradi)", t2 != t1)
    c2 = sr.claim_post_delivery(pid, CHAN, t2)
    key2 = c2["idempotency_key"]
    check("2-claim yangi kalit bilan olindi", c2.get("claimed") is True and key2 != key1, str(c2))
    check("2-claim verify markerini KO'RADI (kanal tekshiruvisiz ko'r-ko'rona yuborilmaydi)",
          sr.delivery_verify_pending(c2.get("last_error")) and c2.get("verify_pending") is True, str(c2))
    check("verify urinish raqami saqlanadi (attempt=1)", sr.delivery_verify_attempt(c2.get("last_error")) == 1, str(c2.get("last_error")))
    # AUDIT-002: DELIVERY_CARRY_ATTEMPTS sukut YOQILGAN — yangi qator oldingi 'failed' qatorning urinishlar sonini oladi
    # (retry'lar bo'yicha yig'iladi); oshirmaydi va 0 ga tushirmaydi.
    check("attempt_count oldingi urinishdan ko'chadi (kamaymaydi, sakramaydi)",
          row(key2)[1] == row(key1)[1] and row(key2)[1] >= 1, f"{row(key1)} -> {row(key2)}")

    # 2) zanjir: tekshiruv 'post kanalda yo'q' dedi -> marker tozalanadi -> keyingi retry'da marker qaytib kelmaydi
    check("marker tozalandi (clear_post_delivery_verify_pending)", sr.clear_post_delivery_verify_pending(key2) is True)
    retry(pid, -2)
    t3 = sched_time(pid)
    c3 = sr.claim_post_delivery(pid, CHAN, t3)
    check("tozalangan marker keyingi retry'da QAYTA TIRILMAYDI", c3.get("claimed") is True and not sr.delivery_verify_pending(c3.get("last_error")), str(c3))

    # 3) marker yo'q failed qator: yangi qator toza (xulq o'zgarmagan)
    pid2 = new_post()
    k = sr.claim_post_delivery(pid2, CHAN, sched_time(pid2))["idempotency_key"]
    sr.mark_post_delivery_failed(k, "oddiy xato")
    retry(pid2, -1)
    c = sr.claim_post_delivery(pid2, CHAN, sched_time(pid2))
    check("markersiz failed qator: yangi qator toza va claim qilinadi", c.get("claimed") is True and not c.get("verify_pending"), str(c))

    # 4) 'sent' qatordan marker ko'chmaydi (recurring keyingi davr yoki yuborilgan post)
    pid3 = new_post()
    k3 = sr.claim_post_delivery(pid3, CHAN, sched_time(pid3))["idempotency_key"]
    sr.mark_post_delivery_verify_pending(k3, "TimedOut", 1, 1.0)
    q("UPDATE post_deliveries SET status = 'sent', telegram_message_id = 55 WHERE idempotency_key = %s", (k3,))
    retry(pid3, -1)
    c = sr.claim_post_delivery(pid3, CHAN, sched_time(pid3))
    check("'sent' qatordan marker KO'CHMAYDI (keyingi davr toza)", c.get("claimed") is True and not c.get("verify_pending"), str(c))

    # 5) parallel: retry'dan keyin ikki worker bir vaqtda claim qiladi -> faqat BITTASI claim, ikkalasi ham marker ko'radi
    pid4 = new_post()
    k4 = sr.claim_post_delivery(pid4, CHAN, sched_time(pid4))["idempotency_key"]
    sr.mark_post_delivery_verify_pending(k4, "NetworkError", 2, 1.0)
    retry(pid4, -1)
    t4 = sched_time(pid4)
    out, barrier = [], threading.Barrier(2)

    def worker():
        barrier.wait(timeout=20)
        out.append(sr.claim_post_delivery(pid4, CHAN, t4))

    ths = [threading.Thread(target=worker) for _ in range(2)]
    [t.start() for t in ths]
    [t.join(60) for t in ths]
    claimed = [o for o in out if o.get("claimed")]
    check("parallel: AYNAN bitta worker claim qildi (dublikat yuborish yo'q)", len(claimed) == 1, str(out))
    check("parallel: claim qilgan worker verify markerini ko'rdi (attempt=2)",
          bool(claimed) and sr.delivery_verify_attempt(claimed[0].get("last_error")) == 2, str(claimed))
    rows = q("SELECT COUNT(*) FROM post_deliveries WHERE post_id = %s", (pid4,))[0][0]
    check("parallel: post uchun 2 ta delivery qatori (eski + yangi), ortiqcha yo'q", rows == 2, str(rows))
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
