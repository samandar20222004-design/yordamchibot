#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💰 UMUMIY AI BYUDJETI — PostgreSQL'da ATOMIK rezervatsiya (jonli DB testi).

Haqiqiy PostgreSQL kerak: ``AI_BUDGET_TEST_DATABASE_URL`` berilmasa barcha
tekshiruvlar [SKIP] bo'ladi (o'tgan deb sanalmaydi).

Qamrov: bir process ichida parallel thread'lar, bir nechta alohida jarayon
(har biri o'z DB pool'i), settle/release/unknown holatlari, TTL eskirishi va
kechikkan yakunlash, idempotentlik, qabr belgisi, restart, kun chegarasi.

Ishga tushirish:
    AI_BUDGET_TEST_DATABASE_URL=postgresql://... BOT_TOKEN=123456789:TEST_MOCK_TOKEN \\
        PYTHONPATH=telegram_bot python3 tests/ai_budget_reservation_test.py
"""
import json
import os
import subprocess
import sys
import threading
import uuid
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:BUDGET_RESERVATION_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = failures = skipped = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


LIVE_URL = os.environ.get("AI_BUDGET_TEST_DATABASE_URL", "").strip()
if not LIVE_URL:
    print("  [SKIP] AI_BUDGET_TEST_DATABASE_URL berilmagan — jonli PostgreSQL testlari o'tkazildi")
    print("\nNATIJA: [OK]=0  [FAIL]=0  [SKIP]=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = LIVE_URL
db._reset_pool()
db.init_db()


def tid():
    return "T-" + uuid.uuid4().hex


def status():
    return db.get_ai_budget_status()


def used():
    return status()["used_usd"]


def reserve(cap, est=0.01, ttl=180.0, ticket=None):
    return db.reserve_ai_budget(ticket or tid(), 1, est, cap, ttl)


print("\n== 1) Jadval va ketma-ket bron ==")
with db.db_cursor() as cur:
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
    tables = {r[0] for r in cur.fetchall()}
check("migratsiya: ikkala jadval mavjud", {"ai_budget_days", "ai_budget_reservations"} <= tables)
db.init_db()   # takroriy ishga tushirish xavfsiz (idempotent)
check("migratsiya takror ishga tushirilganda xatosiz", True)

base = used()
cap = base + 0.03
a, b, c, d = reserve(cap), reserve(cap), reserve(cap), reserve(cap)
check("chegara ichida 3 ta bron o'tadi, to'rtinchisi rad", [x["granted"] for x in (a, b, c, d)] == [True, True, True, False],
      str([x["granted"] for x in (a, b, c, d)]))
check("rad sababi global_daily_usd", d["reason"] == "global_daily_usd")
check("used = base + 3 ta bron", abs(used() - (base + 0.03)) < 1e-6, str(used()))
same = tid()
r1, r2 = reserve(cap + 1, ticket=same), reserve(cap + 1, ticket=same)
check("bir xil ticket ikki marta bron qilinmaydi (idempotent)",
      r1["granted"] and r2["granted"] and abs(used() - (base + 0.04)) < 1e-6, str(used()))

print("\n== 2) Bir process ichida parallel (threadlar, har biri o'z DB ulanishi) ==")
base = used()
cap = base + 0.20
results = []
lock = threading.Lock()


def worker():
    r = reserve(cap)
    with lock:
        results.append(r["granted"])


threads = [threading.Thread(target=worker) for _ in range(40)]
for t in threads:
    t.start()
for t in threads:
    t.join()
granted = sum(1 for g in results if g)
check("40 parallel so'rov, chegara 0.20 / 0.01 → aynan 20 ta o'tdi", granted == 20, f"granted={granted}")
check("used chegaradan oshmadi", used() <= cap + 1e-6, f"{used()} > {cap}")

print("\n== 3) Bir nechta alohida jarayon (har biri o'z pool'i) ==")
base = used()
cap = base + 0.30
CHILD = r"""
import json, os, sys, uuid
sys.path.insert(0, os.environ["ROOT_DIR"])
import database as db
db.DATABASE_URL = os.environ["LIVE_URL"]
db._reset_pool()
cap = float(os.environ["CAP"])
granted = 0
for _ in range(10):
    r = db.reserve_ai_budget("P-" + uuid.uuid4().hex, 1, 0.01, cap, 180.0)
    granted += 1 if r["granted"] else 0
print(json.dumps({"granted": granted}))
"""
env = dict(os.environ, ROOT_DIR=str(ROOT), LIVE_URL=LIVE_URL, CAP=str(cap),
           DATABASE_URL=LIVE_URL, PYTHONPATH=str(ROOT))
procs = [subprocess.Popen([sys.executable, "-c", CHILD], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) for _ in range(8)]
total = 0
for p in procs:
    out, err = p.communicate(timeout=120)
    try:
        total += json.loads(out.strip().splitlines()[-1])["granted"]
    except Exception:
        check("jarayon natijasi o'qildi", False, (out + err)[-300:])
check("8 jarayon x 10 so'rov, chegara 0.30 / 0.01 → aynan 30 ta o'tdi", total == 30, f"granted={total}")
check("jarayonlar bo'yicha used chegaradan oshmadi", used() <= cap + 1e-6, f"{used()} > {cap}")

print("\n== 4) Yakunlash: settle / release / unknown, idempotentlik ==")
base = used()
cap = base + 0.05
t1 = tid()
check("bron", reserve(cap, est=0.02, ticket=t1)["granted"])
st = status()
check("settle: haqiqiy 0.005 + taxmin 0.003 alohida yoziladi",
      db.settle_ai_budget(t1, 0.005, 0.003) == "settled")
after = status()
check("spent va assumed ALOHIDA ustunlarda",
      abs((after["spent_usd"] - st["spent_usd"]) - 0.005) < 1e-6
      and abs((after["assumed_usd"] - st["assumed_usd"]) - 0.003) < 1e-6, str((st, after)))
check("bron (0.02) o'rniga faqat haqiqiy+taxmin (0.008) hisobda qoldi",
      abs(after["used_usd"] - (st["used_usd"] - 0.02 + 0.008)) < 1e-6, str((st, after)))
check("settle takror chaqirilsa o'zgarmaydi (idempotent)",
      db.settle_ai_budget(t1, 0.005, 0.003) == "noop" and abs(status()["used_usd"] - after["used_usd"]) < 1e-9)
check("settle'dan keyin release hech narsani o'zgartirmaydi", db.release_ai_budget(t1) == "noop"
      and abs(status()["used_usd"] - after["used_usd"]) < 1e-9)

t2 = tid()
reserve(cap, est=0.02, ticket=t2)
before = used()
check("release: bron qaytariladi", db.release_ai_budget(t2) == "released" and abs(used() - (before - 0.02)) < 1e-6)
check("release takror → noop, ikki marta qaytarilmaydi",
      db.release_ai_budget(t2) == "noop" and abs(used() - (before - 0.02)) < 1e-6)

t3 = tid()
reserve(cap, est=0.02, ticket=t3)
before = used()
check("timeout: mark_unknown bronni hisobda QOLDIRADI",
      db.mark_ai_budget_unknown(t3) == "unknown" and abs(used() - before) < 1e-6)
check("unknown ticket keyin settle/release bilan o'zgarmaydi",
      db.settle_ai_budget(t3, 0.0, 0.0) == "noop" and db.release_ai_budget(t3) == "noop"
      and abs(used() - before) < 1e-6)
check("unknown takror → noop", db.mark_ai_budget_unknown(t3) == "noop")
check("mavjud bo'lmagan ticket: settle 'missing' (xatosiz)", db.settle_ai_budget(tid(), 1.0) == "missing")

print("\n== 5) Qabr belgisi: release bron yetib kelmasdan oldin ==")
ghost = tid()
check("bron yo'q ticket'ni release → tombstone", db.release_ai_budget(ghost) == "tombstone")
late = db.reserve_ai_budget(ghost, 1, 0.01, 999.0, 180.0)
check("keyin kelgan bron rad etiladi (sizib qolmaydi)",
      late["granted"] is False and late["reason"] == "released")

print("\n== 6) TTL eskirishi va kechikkan yakunlash ==")
base = used()
cap = base + 0.10
te = tid()
check("TTL=-1 (darhol eskiradi) bron", reserve(cap, est=0.04, ttl=-1.0, ticket=te)["granted"])
st = status()
reserve(cap, est=0.001)         # keyingi bron eskirganlarni supuradi
st2 = status()
check("eskirgan bron O'CHIRILMADI: unknown_usd ga o'tdi, used kamaymadi",
      st2["unknown_usd"] >= st["unknown_usd"] + 0.04 - 1e-6 and st2["used_usd"] >= st["used_usd"] - 1e-6,
      str((st, st2)))
with db.db_cursor() as cur:
    cur.execute("SELECT state FROM ai_budget_reservations WHERE ticket_id=%s", (te,))
    check("holat 'expired'", cur.fetchone()[0] == "expired")
before = status()
check("kechikkan settle: bron summasi (0.04) o'rniga haqiqiy 0.01",
      db.settle_ai_budget(te, 0.01, 0.0) == "settled")
after = status()
check("unknown 0.04 ga kamaydi, spent 0.01 ga oshdi",
      abs((before["unknown_usd"] - after["unknown_usd"]) - 0.04) < 1e-6
      and abs((after["spent_usd"] - before["spent_usd"]) - 0.01) < 1e-6, str((before, after)))
check("kechikkan settle takror → noop", db.settle_ai_budget(te, 0.01) == "noop")
te2 = tid()
reserve(cap + 1, est=0.03, ttl=-1.0, ticket=te2)
reserve(cap + 1, est=0.001)
b4 = status()
check("kechikkan release (sarf yo'qligi aniq) bronni qaytaradi",
      db.release_ai_budget(te2) == "released"
      and abs((b4["unknown_usd"] - status()["unknown_usd"]) - 0.03) < 1e-6)

print("\n== 7) Restart (pool qayta yaratiladi) va kun chegarasi ==")
snap = status()
db.close_pool()
db._reset_pool()
check("restartdan keyin hisob DB'dan tiklanadi", abs(status()["used_usd"] - snap["used_usd"]) < 1e-9)
with db.db_cursor(commit=True) as cur:
    cur.execute("INSERT INTO ai_budget_days (day, spent_usd) VALUES (CURRENT_DATE - 30, 9999) "
                "ON CONFLICT (day) DO UPDATE SET spent_usd = 9999")
    cur.execute("INSERT INTO ai_budget_reservations (ticket_id, day, est_usd, state, expires_at) "
                "VALUES (%s, CURRENT_DATE - 30, 9999, 'reserved', NOW() + interval '1 hour')", (tid(),))
cap = used() + 0.05
check("boshqa kunning sarfi/broni bugungi hisobga kirmaydi", reserve(cap, est=0.01)["granted"])

print("\n== 8) Chegara o'chirilgan / nolga yaqin ==")
check("cap=0 bo'lsa (store darajasida) har qanday bron rad: o'chirish guard darajasida hal qilinadi",
      reserve(0.0, est=0.001)["granted"] is False)

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}  [SKIP]={skipped}")
db.close_pool()
sys.exit(1 if failures else 0)
