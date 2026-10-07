#!/usr/bin/env python3
"""VAZIFA 4: 08:00 staggering va kanalga xos 429 freeze testlari."""
import os
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:QUIET_TEST")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

import pytz
import scheduler as sch

passed = failures = 0

def check(name, condition, detail=""):
    global passed, failures
    if condition:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name}: {detail}")


def post(post_id, channel, scheduled):
    row = [None] * 16
    row[0], row[2], row[9] = post_id, channel, scheduled
    return tuple(row)


def test_ten_post_stagger():
    print("== 08:00 da 10 post staggering ==")
    tz = pytz.timezone("Asia/Tashkent")
    base = tz.localize(datetime(2026, 10, 8, 8, 0, 0))
    posts = [post(i, "A" if i % 2 else "B", base) for i in range(10)]
    planned = sch.stagger_quiet_hour_posts(posts, base, uniform=lambda _a, _b: 30)
    offsets = [0.0 if target is None else (target - base).total_seconds()
               for _, target in planned]
    check("10 postning hammasi saqlandi", len(planned) == 10, offsets)
    check("birinchi post 08:00 da", offsets[0] == 0, offsets)
    check("global qo'shni slotlar 30..180s", all(
        sch.QUIET_STAGGER_MIN_SECONDS <= b - a <= sch.QUIET_STAGGER_MAX_SECONDS
        for a, b in zip(offsets, offsets[1:])), offsets)
    by_channel = {}
    for (row, _), offset in zip(planned, offsets):
        by_channel.setdefault(row[2], []).append(offset)
    check("har bir kanal oralig'i kamida 60s", all(
        b - a >= sch.CHANNEL_STAGGER_MIN_SECONDS
        for values in by_channel.values() for a, b in zip(values, values[1:])), by_channel)


def test_429_channel_freeze_isolated():
    print("== RetryAfter + 5s kanal freeze ==")
    sch.clear_channel_flood()
    clock = [1000.0]
    with patch("time.monotonic", side_effect=lambda: clock[0]):
        sch.mark_channel_flood("A", 20 + sch.FLOOD_WAIT_SAFETY_SECONDS)
        remaining_a = sch.channel_flood_remaining("A")
        remaining_b = sch.channel_flood_remaining("B")
        check("429 kanali RetryAfter + 5s muzladi", remaining_a == 25.0, remaining_a)
        check("boshqa kanal bloklanmadi", remaining_b == 0.0, remaining_b)
        clock[0] += 24
        check("buffer tugamaguncha freeze faol", sch.channel_flood_remaining("A") == 1.0)
        clock[0] += 1
        check("muddat tugagach kanal ochildi", sch.channel_flood_remaining("A") == 0.0)
    sch.clear_channel_flood()


if __name__ == "__main__":
    test_ten_post_stagger()
    test_429_channel_freeze_isolated()
    print(f"\nNatija: {passed} [OK], {failures} [FAIL]")
    raise SystemExit(1 if failures else 0)
