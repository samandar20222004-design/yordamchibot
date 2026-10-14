#!/usr/bin/env python3
"""Qotib qolgan 'processing' post har tick'da tiklanadi (real PostgreSQL, faqat sinov bazasi) — audit D-5.

Muammo: `recover_stale_processing_posts` faqat `cleanup_old_data` (har 6 soatda) va startup'da ishlardi. Boshqa worker 'processing'
postni ko'rsa `claimed=False` qaytadi; o'sha worker o'lsa post 6 soatgacha yotardi.
Tuzatish: har tick boshida (10 daqiqalik chegara o'zgarmagan). Yuborilgani dalili bor post 'posted' qilinadi (QAYTA YUBORILMAYDI).
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
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_stale")
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


print("== Stale 'processing' har tick'da tiklanadi (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

import scheduler as sched  # noqa: E402

USER, CHAN = 9_601_100, "-1009601100"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM sent_post_messages WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (USER,))
    q("DELETE FROM scheduled_posts WHERE user_id = %s", (USER,))
    q("DELETE FROM channels WHERE user_id = %s", (USER,))
    q("DELETE FROM users WHERE user_id = %s", (USER,))


class Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return SimpleNamespace(message_id=700 + len(self.sent))

    async def get_chat(self, *a, **kw):
        return SimpleNamespace(username=None)


def stuck_post(text, minutes_ago):
    pid = int(db.add_post(USER, CHAN, "text", text, None, datetime.now(timezone.utc)))
    q("UPDATE scheduled_posts SET status = 'processing', scheduled_time = NOW() - interval '1 hour', "
      "processing_started_at = NOW() - (%s || ' minutes')::INTERVAL WHERE id = %s", (str(minutes_ago), pid))
    return pid


def status(pid):
    return q("SELECT status FROM scheduled_posts WHERE id = %s", (pid,))[0][0]


async def _no_sleep(*_a, **_k):
    return None


cleanup()
orig_sleep = sched.asyncio.sleep
sched.asyncio.sleep = _no_sleep
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'pro')", (USER, "stale"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'ST', TRUE)", (USER, CHAN))

    p_old = stuck_post("eski qotgan", 20)       # 20 daqiqa 'processing' — worker o'lgan
    p_fresh = stuck_post("hozir ishlanayotgan", 2)   # 2 daqiqa — boshqa worker hali ishlayapti
    p_sent = stuck_post("yuborilgan edi", 20)     # yuborilgan dalili bor (marker yozilmagan)
    q("INSERT INTO sent_post_messages (post_id, channel_id, message_id) VALUES (%s, %s, 5551)", (p_sent, CHAN))

    bot = Bot()
    asyncio.run(sched.check_and_send_posts(bot))

    check("20 daqiqa qotgan post BIR tick ichida tiklandi va yuborildi (6 soat kutilmadi)",
          status(p_old) == "posted" and any("eski qotgan" in t for t in bot.sent), f"{status(p_old)} {bot.sent}")
    check("2 daqiqalik 'processing' (boshqa worker ishlayapti) TEGILMADI", status(p_fresh) == "processing", status(p_fresh))
    check("yuborilgani dalili bor post 'posted' qilindi va QAYTA YUBORILMADI",
          status(p_sent) == "posted" and not any("yuborilgan edi" in t for t in bot.sent), f"{status(p_sent)} {bot.sent}")
finally:
    sched.asyncio.sleep = orig_sleep
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
