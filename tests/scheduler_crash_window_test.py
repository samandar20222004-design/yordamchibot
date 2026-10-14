#!/usr/bin/env python3
"""Scheduler crash oynalari (real PostgreSQL, faqat sinov bazasi). Telegram'ning exactly-once kafolati YO'Q:
yuborish natijasi noaniq bo'lishi mumkin, shuning uchun bu test dublikat/yo'qotish chegaralarini QOTIRADI va OCHIQ qoldirilganini belgilaydi.

A) XAVFSIZ oynalar (kafolatlangan): crash yuborishdan OLDIN -> post yo'qolmaydi (qayta navbatga); crash `mark_post_as_sent`'dan KEYIN
   ('posted' + delivery 'sent' bitta tranzaksiyada) -> qayta YUBORILMAYDI; recovery 'sent' dalilini hurmat qiladi.
B) Telegram'ga CHIQDI, lekin `mark_post_as_sent` COMMIT bo'lmasdan jarayon o'ldi (AUDIT-008). Exactly-once YO'Q; lekin recovery/stale-reclaim
   delivery'ga AMBIGUOUS_VERIFY markerini qo'yadi va scheduler qayta yuborishdan OLDIN kanalni o'qiydi: post bor -> yuborilmaydi; yo'q -> yuboriladi;
   o'qib bo'lmasa -> 3 urinishdan keyin 'unknown' (admin ko'radi). QOLGAN xavf: kanal o'qilgan, post yo'q deb topilgan, lekin aslida chiqqan
   (probe kechikishi / 15 daqiqadan keyingi restart) -> dublikat mumkin.
C) Crash-loop himoyasi: 5-marta stale 'processing' qayta olinsa delivery 'dead_letter' (post 'failed').
D) Recurring: 'yuborildi' + keyingi davr BITTA tranzaksiyada (TUZATILGAN; oldin KNOWN-OPEN edi)."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
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

    # B) Telegram'ga chiqdi, DB marker YO'Q (AUDIT-008). Exactly-once YO'Q, lekin qayta yuborishdan OLDIN kanal tekshiriladi:
    #    recovery/stale-reclaim delivery'ga AMBIGUOUS_VERIFY markerini qo'yadi, scheduler esa kanalni o'qiydi.
    import asyncio
    import scheduler as sched

    VERIFY = sr.DELIVERY_VERIFY_MARKER
    pid4, t4 = due_post()
    c = claim_as_scheduler(pid4, t4)
    # ... bot Telegram'ga yubordi va crash bo'ldi: DB'da hech narsa yozilmadi ...
    sr.recover_processing_posts_on_startup(0)
    again = sr.claim_post_delivery(pid4, CHAN, t4)
    check("B1: restart recovery postni qayta navbatga qo'yadi (yo'qotmaydi)", st(pid4) == "pending")
    check("B1: keyingi claim verify_pending=True (kanal tekshirilmaguncha ko'r-ko'rona yuborilmaydi)",
          again.get("claimed") is True and again.get("verify_pending") is True and VERIFY in str(again.get("last_error")), str(again))

    # B2) stale reclaim (processing qotib qolgan): marker shu yerda ham qo'yiladi
    pid6, t6 = due_post()
    c6 = claim_as_scheduler(pid6, t6)
    q("UPDATE post_deliveries SET updated_at = NOW() - interval '20 minutes' WHERE idempotency_key = %s", (c6["idempotency_key"],))
    r6 = sr.claim_post_delivery(pid6, CHAN, t6)
    row6 = q("SELECT last_error FROM post_deliveries WHERE idempotency_key = %s", (c6["idempotency_key"],))[0][0]
    check("B2: stale reclaim: claimed + verify_pending=True va DB'da marker bor",
          r6.get("claimed") is True and r6.get("stale_reclaim") is True and r6.get("verify_pending") is True
          and VERIFY in str(row6), f"{r6} {row6}")

    # B3) scheduler darvozasi (_verify_no_duplicate_before_send) kanal natijasiga qarab qaror qiladi
    def gate(pid, claim_key, items, verify_attempt=0, status="ok"):
        async def fake_probe(bot, channel_id, limit=None):
            return {"status": status, "items": items}
        orig = sched._probe_channel_recent_posts
        sched._probe_channel_recent_posts = fake_probe
        try:
            claim = {"last_error": VERIFY + f" attempt={verify_attempt} | restart recovery"}
            ctx = {"delivery_marker_key": claim_key, "delivery_claim": claim, "delivery_claim_verify_attempt": verify_attempt,
                   "post_id": pid, "channel_id": CHAN, "post_type": "text", "file_id": None}
            return asyncio.run(sched._verify_no_duplicate_before_send(None, ctx, "crash"))
        finally:
            sched._probe_channel_recent_posts = orig

    now_iso = datetime.now(timezone.utc).isoformat()
    # B3a) kanalda post BOR -> qayta yuborilmaydi, delivery 'sent'
    pa, ta = due_post()
    ca = claim_as_scheduler(pa, ta)
    sr.recover_processing_posts_on_startup(0)
    ka = ca["idempotency_key"]
    check("B3a: kanalda post bor -> darvoza False (QAYTA YUBORILMAYDI)", gate(pa, ka, [{"text": "crash", "date": now_iso}]) is False)
    check("B3a: delivery 'sent'", q("SELECT status FROM post_deliveries WHERE idempotency_key = %s", (ka,))[0][0] == "sent")
    # B3b) kanal o'qildi va post YO'Q -> xavfsiz yuborish
    pb, tb = due_post()
    cb = claim_as_scheduler(pb, tb)
    check("B3b: kanal o'qildi, post yo'q -> darvoza True (yuborish mumkin)",
          gate(pb, cb["idempotency_key"], [{"text": "boshqa xabar", "date": now_iso}]) is True)
    # B3c) kecha yuborilgan BIR XIL matn (takrorlanuvchi post) bugungisini YO'QOTMAYDI
    pc, tc = due_post()
    cc = claim_as_scheduler(pc, tc)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    check("B3c: kechagi bir xil matn bugungi postni bloklamaydi (vaqt oynasi) -> yuborish mumkin",
          gate(pc, cc["idempotency_key"], [{"text": "crash", "date": yesterday}]) is True)
    # B3d) kanalni o'qib bo'lmaydi -> HECH QACHON True emas; 3-urinishda 'unknown' (admin ko'radi)
    pd_, td = due_post()
    cd = claim_as_scheduler(pd_, td)
    kd = cd["idempotency_key"]
    r1 = gate(pd_, kd, [], 0, status="unavailable")
    r2 = gate(pd_, kd, [], 1, status="unavailable")
    r3 = gate(pd_, kd, [], 2, status="unavailable")
    check("B3d: kanal o'qilmasa darvoza hech qachon True qaytarmaydi (ko'r-ko'rona yuborish yo'q)", (r1, r2, r3) == (False, False, False), str((r1, r2, r3)))
    check("B3d: urinishlar tugagach delivery 'unknown' (avtomatik yuborish taqiqlangan)",
          q("SELECT status FROM post_deliveries WHERE idempotency_key = %s", (kd,))[0][0] == "unknown")

    # C) crash-loop himoyasi: stale 'processing' delivery 5-marta qayta olinsa dead_letter
    pid5, t5 = due_post()
    sr.claim_post_delivery(pid5, CHAN, t5)
    last = None
    for _ in range(5):
        q("UPDATE post_deliveries SET status = 'processing', updated_at = NOW() - interval '20 minutes' WHERE post_id = %s", (pid5,))
        last = sr.claim_post_delivery(pid5, CHAN, t5)
    check("C: 5-stale-reclaim -> dead_letter (crash-loop to'xtatiladi, post avtomatik qayta yuborilmaydi)",
          last.get("dead") is True and last.get("status") == "dead_letter", str(last))

    # D) recurring: yuborildi -> qayta rejalash oralig'i (AUDIT-009 qoldig'i). TUZATILDI: `mark_post_as_sent(next_time=...)`
    #    'posted' markeri va keyingi davrni BITTA tranzaksiyada yozadi -> oraliq yo'q.

    nxt = datetime.now(timezone.utc) + timedelta(days=1)
    rid = int(db.add_post(USER, CHAN, "text", "rec", None, datetime.now(timezone.utc) - timedelta(minutes=3), recurrence_type="daily"))
    rt = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid,))[0][0]
    c = claim_as_scheduler(rid, rt)
    ok = db.mark_post_as_sent(rid, 556, CHAN, 0, None, c["idempotency_key"], next_time=nxt)
    sr.recover_processing_posts_on_startup(0)
    sr.recover_stale_processing_posts()
    row = q("SELECT status, scheduled_time, sent_message_id FROM scheduled_posts WHERE id = %s", (rid,))[0]
    check("D: atomik yozuv: post 'pending' va keyingi davr vaqti, sent_message_id yozilgan (crash oynasi yo'q)",
          ok is True and row[0] == "pending" and abs((row[1] - nxt).total_seconds()) < 1 and row[2] == 556, str(row))
    check("D: delivery shu tranzaksiyada 'sent' (qayta yuborilmaydi)",
          q("SELECT status FROM post_deliveries WHERE idempotency_key = %s", (c["idempotency_key"],))[0][0] == "sent")
    check("D: recovery atomik yozilgan keyingi davrni buzmaydi", st(rid) == "pending")

    # D2) scheduler `_apply_sent_marker` yo'li (daily, haqiqiy marker) — bitta chaqiruvda 'pending' + yangi vaqt
    rid2 = int(db.add_post(USER, CHAN, "text", "rec2", None, datetime.now(timezone.utc) - timedelta(minutes=3),
                           recurrence_type="daily"))
    rt2 = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid2,))[0][0]
    c2 = claim_as_scheduler(rid2, rt2)
    marker = sched._build_sent_marker(rid2, 557, CHAN, 0, None, recurrence_type="daily", recurrence_time=dtime(9, 0),
                                      idempotency_key=c2["idempotency_key"])
    applied = asyncio.run(sched._apply_sent_marker(marker))
    check("D2: _apply_sent_marker recurring uchun True, 'pending', vaqt oldinga surilgan",
          applied is True and st(rid2) == "pending" and q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid2,))[0][0] > rt2
          and marker.get("reschedule_done") is True, f"{applied} {st(rid2)} {marker}")

    # D3) end_date o'tgan: 'completed' ham shu tranzaksiyada
    rid3 = int(db.add_post(USER, CHAN, "text", "rec3", None, datetime.now(timezone.utc) - timedelta(minutes=3), recurrence_type="daily"))
    rt3 = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid3,))[0][0]
    c3 = claim_as_scheduler(rid3, rt3)
    ok3 = db.mark_post_as_sent(rid3, 558, CHAN, 0, None, c3["idempotency_key"], completed=True)
    check("D3: completed=True -> 'completed' (seriya yakunlandi), 'posted'da qolmaydi", ok3 is True and st(rid3) == "completed", st(rid3))

    # D4) oddiy (recurring bo'lmagan) post — xulq o'zgarmagan: 'posted'
    nid, nt = due_post()
    cn = claim_as_scheduler(nid, nt)
    db.mark_post_as_sent(nid, 559, CHAN, 0, None, cn["idempotency_key"])
    check("D4: oddiy post 'posted' (xulq o'zgarmagan)", st(nid) == "posted", st(nid))

    # D5) eski ikki bosqichli yo'l (next_time yo'q) hanuz 'posted'da qoldiradi — legacy adapterlar uchun, scheduler endi ishlatmaydi
    rid5 = int(db.add_post(USER, CHAN, "text", "rec5", None, datetime.now(timezone.utc) - timedelta(minutes=3), recurrence_type="daily"))
    rt5 = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (rid5,))[0][0]
    c5 = claim_as_scheduler(rid5, rt5)
    db.mark_post_as_sent(rid5, 560, CHAN, 0, None, c5["idempotency_key"])
    check("D5: next_time'siz eski chaqiruv 'posted' (faqat legacy yo'l; scheduler recurring uchun next_time uzatadi)",
          st(rid5) == "posted", st(rid5))
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
