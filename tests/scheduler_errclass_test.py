#!/usr/bin/env python3
"""Telegram xato sinflari bo'yicha qaror (real PostgreSQL, faqat sinov bazasi) — audit D-2.

* `InvalidToken` / `Conflict` — POST xatosi EMAS (token/jarayon muammosi): post `dead_letter` bo'lmasligi, urinish sanalmasligi va
  keyinroq qayta uriniladigan bo'lishi kerak. Oldin ular umumiy `TelegramError` shoxiga tushib postni doimiy 'failed' qilardi.
* `BadRequest` / `Forbidden` — doimiy: o'zgarmagan (regressiya yo'q).
* `ChatMigrated` — avtomatik `channel_id` ko'chirish QILINMAYDI (channel_id 7+ jadvalda FK, ON UPDATE CASCADE yo'q; kanallarda
  uchramaydi, faqat oddiy guruh superguruhga o'tganda). Hozirgi xulq (doimiy 'failed') qotiriladi; bildirishnoma alohida ish (D-4).
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
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_errclass")
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


print("== Telegram xato sinflari (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

from telegram.error import BadRequest, ChatMigrated, Conflict, Forbidden, InvalidToken  # noqa: E402

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

import scheduler as sched  # noqa: E402

USER, CHAN = 9_600_900, "-1009600900"


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


class ErrBot:
    """Har send_message berilgan istisno bilan javob beradi."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    async def send_message(self, *a, **kw):
        self.calls += 1
        raise self.exc

    async def get_chat(self, *a, **kw):
        return SimpleNamespace(username=None)


async def _no_sleep(*_a, **_k):
    return None


def run_round(pid, bot):
    """Bir tick: post due qilinadi -> get_due_posts (processing) -> _execute_send."""
    q("UPDATE scheduled_posts SET status = 'pending', scheduled_time = NOW() - interval '1 minute' WHERE id = %s", (pid,))
    rows = [r for r in db.get_due_posts(datetime.now(timezone.utc)) if r[0] == pid]
    if not rows:
        return
    sched._CHANNEL_FLOOD_UNTIL.clear()
    try:
        asyncio.run(sched._execute_send(bot, rows[0]))
    except Exception as exc:  # noqa: BLE001 — kutilmagan istisno ham post holatini buzmasligi kerak
        print(f"    (istisno tashqariga chiqdi: {type(exc).__name__})")


def state(pid):
    st = q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]
    dead = q("SELECT COUNT(*) FROM post_deliveries WHERE post_id = %s AND status = 'dead_letter'", (pid,))[0][0]
    attempts = q("SELECT COALESCE(MAX(attempt_count), 0) FROM post_deliveries WHERE post_id = %s", (pid,))[0][0]
    return st, dead, attempts


def new_post(text):
    return int(db.add_post(USER, CHAN, "text", text, None, datetime.now(timezone.utc)))


cleanup()
orig_sleep = sched.asyncio.sleep
sched.asyncio.sleep = _no_sleep
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (USER, "errclass"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'EC', TRUE)", (USER, CHAN))

    for name, exc in (("InvalidToken", InvalidToken("Unauthorized")), ("Conflict", Conflict("terminated by other getUpdates"))):
        pid = new_post(name)
        bot = ErrBot(exc)
        for _ in range(7):
            run_round(pid, bot)
        st, dead, attempts = state(pid)
        check(f"{name} x7: post 'pending' (yo'qolmagan, keyinroq qayta uriniladi)", st == "pending", st)
        check(f"{name}: dead_letter YO'Q va urinish sanalmagan", dead == 0 and attempts == 0, f"dead={dead} attempts={attempts}")
        wait = q("SELECT EXTRACT(EPOCH FROM (scheduled_time - NOW())) FROM scheduled_posts WHERE id = %s", (pid,))[0][0]
        check(f"{name}: qayta urinish kechiktirilgan (>= 60 s, shiddatli retry storm yo'q)", float(wait) >= 55, str(wait))

    # Doimiy xatolar o'zgarmagan (regressiya yo'q)
    for name, exc in (("BadRequest", BadRequest("Chat not found")), ("Forbidden", Forbidden("bot was kicked from the channel chat")),
                      ("ChatMigrated", ChatMigrated(-1001234567890))):
        pid = new_post(name)
        run_round(pid, ErrBot(exc))
        st, dead, attempts = state(pid)
        check(f"{name}: doimiy -> post 'failed' va delivery 'dead_letter' (xulq o'zgarmagan)", st == "failed" and dead == 1, f"{st} dead={dead}")
finally:
    sched.asyncio.sleep = orig_sleep
    sched._CHANNEL_FLOOD_UNTIL.clear()
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
