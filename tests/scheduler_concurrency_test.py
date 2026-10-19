#!/usr/bin/env python3
"""Rejalangan postlarni yuborish: turli kanallarga cheklangan parallel, bitta kanalga ketma-ket (DB'siz, soxta yuborish)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

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


import scheduler as sched  # noqa: E402


def run_batch(posts, send, concurrency):
    """posts: [(id, user, channel)...]; qaytaradi: (yuborilganlar, qayta navbatga qo'yilganlar)."""
    sent, requeued = [], []

    async def fake_run_db(func, *a, **k):
        if getattr(func, "__name__", "") == "get_due_posts":
            return list(posts)
        return None

    async def fake_requeue(post, delay):
        requeued.append(post[0])

    async def noflush():
        return None

    orig = (sched.db.run_db, sched._execute_send, sched._requeue_post, sched.flush_unpersisted_sent_markers,
            sched.stagger_quiet_hour_posts, sched.SEND_MICRO_DELAY, sched.SEND_CONCURRENCY)
    sched.db.run_db = fake_run_db
    sched._execute_send = send
    sched._requeue_post = fake_requeue
    sched.flush_unpersisted_sent_markers = noflush
    sched.stagger_quiet_hour_posts = lambda due, now: [(p, None) for p in due]
    sched.SEND_MICRO_DELAY = 0.001
    sched.SEND_CONCURRENCY = concurrency
    try:
        asyncio.run(sched.check_and_send_posts(SimpleNamespace()))
    finally:
        (sched.db.run_db, sched._execute_send, sched._requeue_post, sched.flush_unpersisted_sent_markers,
         sched.stagger_quiet_hour_posts, sched.SEND_MICRO_DELAY, sched.SEND_CONCURRENCY) = orig
    return sent, requeued


def run_rounds(batches, send, batch_size):
    """get_due_posts har chaqiruvda keyingi paketni qaytaradi; qaytadi: nechta marta so'raldi."""
    calls = {"n": 0}

    async def fake_run_db(func, *a, **k):
        if getattr(func, "__name__", "") == "get_due_posts":
            i = calls["n"]
            calls["n"] += 1
            return list(batches[i]) if i < len(batches) else []
        return None

    async def noflush():
        return None

    async def noreq(post, delay):
        return None

    orig = (sched.db.run_db, sched._execute_send, sched._requeue_post, sched.flush_unpersisted_sent_markers,
            sched.stagger_quiet_hour_posts, sched.SEND_MICRO_DELAY, sched.SEND_CONCURRENCY, sched.db.POST_BATCH_SIZE)
    sched.db.run_db, sched._execute_send, sched._requeue_post = fake_run_db, send, noreq
    sched.flush_unpersisted_sent_markers = noflush
    sched.stagger_quiet_hour_posts = lambda due, now: [(p, None) for p in due]
    sched.SEND_MICRO_DELAY, sched.SEND_CONCURRENCY, sched.db.POST_BATCH_SIZE = 0.001, 4, batch_size
    try:
        asyncio.run(sched.check_and_send_posts(SimpleNamespace()))
    finally:
        (sched.db.run_db, sched._execute_send, sched._requeue_post, sched.flush_unpersisted_sent_markers,
         sched.stagger_quiet_hour_posts, sched.SEND_MICRO_DELAY, sched.SEND_CONCURRENCY, sched.db.POST_BATCH_SIZE) = orig
    return calls["n"]


def make_sender(delay=0.05, fail_ids=()):
    state = {"now": 0, "peak": 0, "per_chan": {}, "peak_chan": 0, "done": []}

    async def send(bot, post):
        ch = post[2]
        state["now"] += 1
        state["peak"] = max(state["peak"], state["now"])
        state["per_chan"][ch] = state["per_chan"].get(ch, 0) + 1
        state["peak_chan"] = max(state["peak_chan"], state["per_chan"][ch])
        await asyncio.sleep(delay)
        state["now"] -= 1
        state["per_chan"][ch] -= 1
        if post[0] in fail_ids:
            raise RuntimeError("yuborib bo'lmadi")
        state["done"].append(post[0])

    return send, state


print("== Parallel yuborish ==")
posts = [(i, 1, f"-100{i}") for i in range(1, 13)]  # 12 ta post, 12 ta turli kanal
send, st = make_sender()
_, requeued = run_batch(posts, send, 4)
check("12 post ham yuborildi", sorted(st["done"]) == list(range(1, 13)), str(st["done"]))
check("turli kanallar parallel ketdi (cho'qqi > 1)", st["peak"] > 1, str(st["peak"]))
check("parallellik SEND_CONCURRENCY dan oshmadi (<= 4)", st["peak"] <= 4, str(st["peak"]))
check("hech narsa qayta navbatga tushmadi", requeued == [])

send, st = make_sender()
run_batch(posts, send, 1)
check("SEND_CONCURRENCY=1: eski ketma-ket xulq (cho'qqi == 1)", st["peak"] == 1 and len(st["done"]) == 12, str(st))

print("== Bitta kanal ketma-ket ==")
same = [(i, 1, "-1001") for i in range(1, 9)]
send, st = make_sender()
run_batch(same, send, 4)
check("bitta kanalga bir vaqtda faqat bitta post (kanal qulfi)", st["peak_chan"] == 1 and len(st["done"]) == 8, str(st))
check("bitta kanal postlari tartibi saqlandi", st["done"] == list(range(1, 9)), str(st["done"]))

print("== Xato izolyatsiyasi ==")
send, st = make_sender(fail_ids={3, 7})
_, requeued = run_batch(posts, send, 4)
check("xatoli postlar 'pending'ga qaytarildi (qayta navbat)", sorted(requeued) == [3, 7], str(requeued))
check("boshqa postlar to'xtamasdan yuborildi", sorted(st["done"]) == [i for i in range(1, 13) if i not in (3, 7)], str(st["done"]))

print("== Ommaviy vaqt: paket-paket (bitta tick'da navbat bo'shaguncha) ==")
b1 = [(i, 1, f"-100{i}") for i in range(1, 6)]
b2 = [(i, 1, f"-100{i}") for i in range(6, 11)]
b3 = [(i, 1, f"-100{i}") for i in range(11, 13)]
send, st = make_sender(delay=0.001)
n = run_rounds([b1, b2, b3], send, 5)
check("3 paket (5+5+2) bitta tick'da yuborildi", sorted(st["done"]) == list(range(1, 13)), str(st["done"]))
check("keyingi paket faqat to'liq paketdan keyin so'raladi (3 marta, 4-chi emas)", n == 3, str(n))
send, st = make_sender(delay=0.001)
n = run_rounds([b3], send, 5)
check("to'liq bo'lmagan paket: navbat bo'sh -> qayta so'ramaydi (1 marta)", n == 1 and len(st["done"]) == 2, f"{n} {st['done']}")
check("SEND_MAX_ROUNDS sukut 30", sched.SEND_MAX_ROUNDS == 30, str(sched.SEND_MAX_ROUNDS))

print("== Sozlama ==")
check("sukut parallellik 1..16 oralig'ida", 1 <= sched.SEND_CONCURRENCY <= 16, str(sched.SEND_CONCURRENCY))

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(1 if failed else 0)
