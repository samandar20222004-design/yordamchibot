#!/usr/bin/env python3
"""FloodWait (Telegram 429 / RetryAfter) postni YO'QOTMASLIGI kerak (real PostgreSQL, faqat sinov bazasi).

Muammo (audit D-1): `RetryAfter` ham `attempt_count` ni oshirardi va kutish 60 s ga qirqilardi. `DELIVERY_CARRY_ATTEMPTS` (sukut yoqilgan)
bilan urinishlar retry'lar bo'yicha yig'iladi, shuning uchun 5 marta 429 olgan post `dead_letter` -> 'failed' bo'lardi.

Kutilgan xulq: 429 vaqtinchalik tirbandlik, xato emas -> urinish SANALMAYDI, post Telegram bergan TO'LIQ muddatdan keyin qayta yuboriladi.
Telegram yuborish natijasi noaniq bo'lishi mumkin; bu test exactly-once VA'DA QILMAYDI.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_flood")
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


print("== FloodWait: urinish sanalmaydi, to'liq muddat kutiladi (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

from telegram.error import RetryAfter  # noqa: E402

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

import scheduler as sched  # noqa: E402

USER, CHAN = 9_600_800, "-1009600800"


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


class FloodBot:
    """Har send_message RetryAfter(300) bilan javob beradi."""

    def __init__(self, retry_after=300):
        self.retry_after = retry_after
        self.calls = 0

    async def send_message(self, *a, **kw):
        self.calls += 1
        raise RetryAfter(self.retry_after)

    async def get_chat(self, *a, **kw):
        return SimpleNamespace(username=None)


async def _no_sleep(*_a, **_k):
    return None


def run_round(pid, bot):
    """Bir tick: post due qilinadi -> get_due_posts (processing) -> _execute_send."""
    q("UPDATE scheduled_posts SET status = 'pending', scheduled_time = NOW() - interval '1 minute' WHERE id = %s", (pid,))
    rows = [r for r in db.get_due_posts(datetime.now(timezone.utc)) if r[0] == pid]
    if not rows:
        return None
    sched._CHANNEL_FLOOD_UNTIL.clear()
    asyncio.run(sched._execute_send(bot, rows[0]))
    return rows[0]


cleanup()
orig_sleep = sched.asyncio.sleep
sched.asyncio.sleep = _no_sleep
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "flood"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'FL', TRUE)", (USER, CHAN))
    pid = int(db.add_post(USER, CHAN, "text", "flood", None, datetime.now(timezone.utc)))

    # 1) 7 ta ketma-ket 429: post 'failed'/'dead_letter' bo'lmaydi, urinish sanagichi o'smaydi
    bot = FloodBot(300)
    for _ in range(7):
        run_round(pid, bot)
    st = q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]
    attempts = q("SELECT COALESCE(MAX(attempt_count), 0) FROM post_deliveries WHERE post_id = %s", (pid,))[0][0]
    dead = q("SELECT COUNT(*) FROM post_deliveries WHERE post_id = %s AND status = 'dead_letter'", (pid,))[0][0]
    check("7 ta ketma-ket 429 dan keyin post 'pending' (qayta uriniladi, YO'QOLMAGAN)", st == "pending", st)
    check("429 urinish sanagichini OSHIRMAYDI (attempt_count=0)", attempts == 0, str(attempts))
    check("dead_letter yozuvi YO'Q", dead == 0, str(dead))
    check("bot har safar chaqirildi (7 marta urinildi)", bot.calls == 7, str(bot.calls))

    # 2) kutish Telegram bergan TO'LIQ muddat (300 s) — 60 s ga qirqilmaydi
    pid2 = int(db.add_post(USER, CHAN, "text", "flood2", None, datetime.now(timezone.utc)))
    run_round(pid2, FloodBot(300))
    wait = q("SELECT EXTRACT(EPOCH FROM (scheduled_time - NOW())) FROM scheduled_posts WHERE id = %s", (pid2,))[0][0]
    check("qayta yuborish vaqti ~300 s (+5 s zaxira) keyin, 60 s emas", 295 <= float(wait) <= 320, str(wait))

    # 3) o'ta katta qiymat (soatlar) — oqilona yuqori chegara (1 soat) bilan cheklanadi
    pid3 = int(db.add_post(USER, CHAN, "text", "flood3", None, datetime.now(timezone.utc)))
    run_round(pid3, FloodBot(99999))
    wait3 = q("SELECT EXTRACT(EPOCH FROM (scheduled_time - NOW())) FROM scheduled_posts WHERE id = %s", (pid3,))[0][0]
    check("o'ta katta retry_after 1 soatgacha cheklanadi", 3590 <= float(wait3) <= 3620, str(wait3))

    # 4) oddiy tarmoq xatosi (sanaladigan) oldingidek 5-urinishda dead_letter — regressiya yo'q
    from services.scheduler_service import SchedulerService
    pid4 = int(db.add_post(USER, CHAN, "text", "net", None, datetime.now(timezone.utc)))
    t4 = q("SELECT scheduled_time FROM scheduled_posts WHERE id = %s", (pid4,))[0][0]
    from repositories import scheduler_repository as sr
    claim = sr.claim_post_delivery(pid4, CHAN, t4)
    res = SchedulerService.mark_as_failed(pid4, CHAN, "NetworkError: reset", True,
                                          scheduled_time=t4, idempotency_key=claim["idempotency_key"])
    check("oddiy tarmoq xatosi hamon sanaladi (attempt_count=1, backoff bor)",
          res.get("status") == "failed" and res.get("attempt_count") == 1 and res.get("backoff_seconds") == 30, str(res))
finally:
    sched.asyncio.sleep = orig_sleep
    sched._CHANNEL_FLOOD_UNTIL.clear()
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
