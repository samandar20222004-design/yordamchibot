#!/usr/bin/env python3
"""Takrorlanish modeli: interval ("har N kunda") va weekdays ("dam olish/ish kunlari") — sof mantiq + scheduler + DB.

daily/weekly xulqi o'zgarmagan (regressiya). Sxema o'zgarmaydi: tur/kun/vaqt mavjud ustunlarda.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_recur")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:RECUR_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
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


import pytz  # noqa: E402

import scheduler as sched  # noqa: E402
from services.recurrence import (  # noqa: E402
    ALL_DAYS_MASK, WEEKEND_MASK, WORKDAYS_MASK, first_occurrence, mask_to_weekdays,
    next_extended_occurrence, normalize_recurrence, weekdays_to_mask,
)

TZ = pytz.timezone("Asia/Tashkent")
T12 = time(12, 0)


def at(y, m, d, h=12, mi=0, s=0):
    return TZ.localize(datetime(y, m, d, h, mi, s))


print("== Takrorlanish modeli ==")
# 2026-10-15 — payshanba (weekday=3)
THU = at(2026, 10, 15, 12, 0, 5)
check("2026-10-15 payshanba (test asosi)", THU.weekday() == 3)

# --- normalizatsiya ---
check("none -> ('none', None, None)", normalize_recurrence(None, None, None) == ("none", None, None) and normalize_recurrence("none", 5, "12:00") == ("none", None, None))
check("daily saqlanadi, vaqt 'HH:MM' matndan", normalize_recurrence("daily", None, "09:05") == ("daily", None, time(9, 5)))
check("weekly: kun 0..6", normalize_recurrence("weekly", 4, T12) == ("weekly", 4, T12))
check("interval 3 saqlanadi; 1 -> daily", normalize_recurrence("interval", 3, "12:00") == ("interval", 3, T12) and normalize_recurrence("interval", 1, "12:00")[0] == "daily")
check("weekdays: dam olish maskasi saqlanadi", normalize_recurrence("weekdays", WEEKEND_MASK, "12:00") == ("weekdays", WEEKEND_MASK, T12))
check("weekdays: bitta kun -> weekly; 7 kun -> daily",
      normalize_recurrence("weekdays", 1 << 2, "12:00") == ("weekly", 2, T12) and normalize_recurrence("weekdays", ALL_DAYS_MASK, "12:00")[0] == "daily")
bad = [("interval", 0, "12:00"), ("interval", 31, "12:00"), ("interval", True, "12:00"), ("interval", "2", "12:00"), ("weekly", 7, "12:00"),
       ("weekly", -1, "12:00"), ("weekdays", 0, "12:00"), ("weekdays", 128, "12:00"), ("weekdays", None, "12:00"), ("monthly", 1, "12:00"),
       ("daily", None, "25:00"), ("daily", None, "12:60"), ("daily", None, None), ("daily", None, "abc"), (5, None, "12:00")]
for args in bad:
    try:
        normalize_recurrence(*args)
        ok = False
    except ValueError:
        ok = True
    check(f"yaroqsiz rad etiladi: {args}", ok)
check("weekdays_to_mask / mask_to_weekdays qaytma", mask_to_weekdays(weekdays_to_mask([5, 6])) == [5, 6] and weekdays_to_mask([5, 6]) == WEEKEND_MASK)
check("ish kunlari maskasi = dushanba..juma", mask_to_weekdays(WORKDAYS_MASK) == [0, 1, 2, 3, 4])

# --- keyingi chiqish ---
n = next_extended_occurrence("interval", 2, "12:00", THU)
check("interval 2: payshanba 12:00:05 yuborildi -> shanba 12:00 (2 kun keyin, soat o'zgarmaydi)", n == at(2026, 10, 17, 12, 0), str(n))
n = next_extended_occurrence("interval", 30, "09:30", THU)
check("interval 30 kun", n == at(2026, 11, 14, 9, 30), str(n))
n = next_extended_occurrence("weekdays", WEEKEND_MASK, "12:00", THU)
check("dam olish: payshanbadan keyin -> shanba 12:00", n == at(2026, 10, 17, 12, 0), str(n))
SAT = at(2026, 10, 17, 12, 0, 3)
check("dam olish: shanba yuborilgach -> yakshanba 12:00", next_extended_occurrence("weekdays", WEEKEND_MASK, "12:00", SAT) == at(2026, 10, 18, 12, 0))
SUN = at(2026, 10, 18, 12, 0, 3)
check("dam olish: yakshanbadan keyin -> KEYINGI shanba", next_extended_occurrence("weekdays", WEEKEND_MASK, "12:00", SUN) == at(2026, 10, 24, 12, 0))
FRI = at(2026, 10, 16, 12, 0, 3)
check("ish kunlari: juma -> dushanba", next_extended_occurrence("weekdays", WORKDAYS_MASK, "12:00", FRI) == at(2026, 10, 19, 12, 0))
check("bugungi vaqt hali kelmagan bo'lsa shu kun (weekdays)", next_extended_occurrence("weekdays", 1 << 3, "18:00", at(2026, 10, 15, 9, 0)) == at(2026, 10, 15, 18, 0))
check("noma'lum tur -> None", next_extended_occurrence("daily", None, "12:00", THU) is None)
check("naive datetime Toshkent deb olinadi", next_extended_occurrence("interval", 2, "12:00", datetime(2026, 10, 15, 12, 0, 5)) == at(2026, 10, 17, 12, 0))
check("UTC kirish Toshkentga o'giriladi",
      next_extended_occurrence("interval", 2, "12:00", datetime(2026, 10, 15, 7, 0, 5, tzinfo=timezone.utc)) == at(2026, 10, 17, 12, 0))
check("oy/yil chegarasidan o'tadi", next_extended_occurrence("interval", 2, "12:00", at(2026, 12, 31, 12, 0, 1)) == at(2027, 1, 2, 12, 0))

# --- birinchi chiqish ---
check("first: dam olish, payshanba 10:00 dan -> shanba 12:00", first_occurrence("weekdays", WEEKEND_MASK, "12:00", at(2026, 10, 15, 10, 0)) == at(2026, 10, 17, 12, 0))
check("first: dam olish, shanba 11:00 dan -> o'sha kuni 12:00", first_occurrence("weekdays", WEEKEND_MASK, "12:00", at(2026, 10, 17, 11, 0)) == at(2026, 10, 17, 12, 0))
check("first: dam olish, shanba 13:00 dan -> yakshanba 12:00", first_occurrence("weekdays", WEEKEND_MASK, "12:00", at(2026, 10, 17, 13, 0)) == at(2026, 10, 18, 12, 0))
check("first: interval/daily -> start o'zi", first_occurrence("interval", 2, "12:00", at(2026, 10, 15, 14, 30)) == at(2026, 10, 15, 14, 30))
check("first: weekly (juma) payshanbadan -> ertasi 12:00", first_occurrence("weekly", 4, "12:00", at(2026, 10, 15, 10, 0)) == at(2026, 10, 16, 12, 0))

# --- scheduler.calculate_next_time (daily/weekly o'zgarmagan + yangi turlar) ---
check("scheduler: daily regressiya (12:00:05 dan keyin ertaga 12:00)", sched.calculate_next_time("daily", None, T12, THU) == at(2026, 10, 16, 12, 0))
check("scheduler: weekly regressiya (payshanba -> keyingi payshanba)", sched.calculate_next_time("weekly", 3, T12, THU) == at(2026, 10, 22, 12, 0))
check("scheduler: interval", sched.calculate_next_time("interval", 2, T12, THU) == at(2026, 10, 17, 12, 0))
check("scheduler: weekdays (dam olish)", sched.calculate_next_time("weekdays", WEEKEND_MASK, T12, THU) == at(2026, 10, 17, 12, 0))
check("scheduler: interval kunsiz -> None (yiqilmaydi)", sched.calculate_next_time("interval", None, T12, THU) is None)
check("scheduler: weekdays buzuq maska -> None (yiqilmaydi)", sched.calculate_next_time("weekdays", "x", T12, THU) is None)
check("scheduler: noma'lum tur -> None", sched.calculate_next_time("monthly", 1, T12, THU) is None)

# --- yuborilgan marker: keyingi vaqt va end_date ---
orig_now = sched.now_tashkent
sched.now_tashkent = lambda: THU
try:
    m = sched._build_sent_marker(1, 10, "-100", 0, [], "interval", 2, T12, None, "k")
    check("marker: interval -> keyingi vaqt yozildi", m["next_time"] == at(2026, 10, 17, 12, 0).isoformat() and not m["completed"], str(m))
    m = sched._build_sent_marker(1, 10, "-100", 0, [], "weekdays", WEEKEND_MASK, T12, None, "k")
    check("marker: weekdays -> keyingi shanba", m["next_time"] == at(2026, 10, 17, 12, 0).isoformat(), str(m))
    m = sched._build_sent_marker(1, 10, "-100", 0, [], "interval", 2, T12, at(2026, 10, 16, 23, 0), "k")
    check("marker: keyingi vaqt end_date'dan keyin -> yakunlanadi (AUDIT-009 qoidasi yangi turlarda ham)", m["completed"] and not m["next_time"], str(m))
    m = sched._build_sent_marker(1, 10, "-100", 0, [], "none", None, None, None, "k")
    check("marker: oddiy post o'zgarmagan (takrorlanmaydi)", not m["next_time"] and not m["completed"])
finally:
    sched.now_tashkent = orig_now

# --- bot ko'rinishi (3 til) ---
from utils.helpers import format_schedule_line  # noqa: E402

for lang, exp_iv, exp_we in (("uz", "Har 2 kunda", "dam olish"), ("ru", "Каждые 2 дн.", "По выходным"), ("en", "Every 2 days", "Weekends")):
    a = format_schedule_line(None, "interval", 2, T12, lang)
    b = format_schedule_line(None, "weekdays", WEEKEND_MASK, T12, lang)
    c = format_schedule_line(None, "weekdays", (1 << 0) | (1 << 2), T12, lang)
    check(f"[{lang}] interval qatori: '{exp_iv}' va vaqt 12:00", exp_iv in a and "12:00" in a, a)
    check(f"[{lang}] dam olish qatori: '{exp_we}'", exp_we.lower() in b.lower() and "12:00" in b, b)
    check(f"[{lang}] aniq kunlar ro'yxati (2 ta kun nomi, vergul bilan)", "," in c and "12:00" in c, c)
check("interval/weekdays uchun uz/ru/en qatorlari farq qiladi", len({format_schedule_line(None, "interval", 2, T12, lg) for lg in ("uz", "ru", "en")}) == 3)
check("daily qatori regressiya", "12:00" in format_schedule_line(None, "daily", None, T12, "uz"))

# --- real PG: yuborilgach qayta rejalash (interval + weekdays) ---
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q — DB qismi o'tkazildi")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=1")
    sys.exit(0 if failed == 0 else 1)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()
USER, CHAN = 9_660_001, "-1009660001"


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


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, 'rec', 'pro')", (USER,))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'R', TRUE)", (USER, CHAN))
    base = datetime.now(timezone.utc) + timedelta(days=1)
    for rtype, rday in (("interval", 2), ("weekdays", WEEKEND_MASK)):
        pid = int(db.add_post(USER, CHAN, "text", rtype, None, base, recurrence_type=rtype, recurrence_day=rday, recurrence_time=T12))
        row = q("SELECT recurrence_type, recurrence_day, recurrence_time FROM scheduled_posts WHERE id = %s", (pid,))[0]
        check(f"DB: {rtype} ustunlarda saqlandi (sxema o'zgarmagan)", row[0] == rtype and row[1] == rday and row[2] == T12, str(row))
        q("UPDATE scheduled_posts SET status = 'processing' WHERE id = %s", (pid,))
        sched.now_tashkent = lambda: THU
        try:
            marker = sched._build_sent_marker(pid, 555, CHAN, 0, [], rtype, rday, T12, None, None)
        finally:
            sched.now_tashkent = orig_now
        ok = asyncio.run(sched._apply_sent_marker(marker))
        st, when = q("SELECT status, scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))[0]
        check(f"DB: {rtype} yuborilgach 'pending' va keyingi vaqt yozildi (seriya tirik)", ok and st == "pending" and when.astimezone(TZ) == at(2026, 10, 17, 12, 0), f"{ok} {st} {when}")
finally:
    sched.now_tashkent = orig_now
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
