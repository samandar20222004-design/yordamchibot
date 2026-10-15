#!/usr/bin/env python3
"""Tabiiy til rejalash parseri (uz/ru/en) — deterministik, DB'siz.

Asos: payshanba 2026-10-15 10:00 (Toshkent). Taxmin YO'Q: vaqt aniqlanmasa `no_time`; hech qachon istisno ko'tarmaydi.
"""
from __future__ import annotations

import os
import random
import string
import sys
import warnings
from datetime import datetime, time
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:NLP_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


import pytz  # noqa: E402

from services.recurrence import WEEKEND_MASK, WORKDAYS_MASK  # noqa: E402
from services.schedule_nlp import MAX_TEXT_CHARS, parse_schedule_text, validate_proposal  # noqa: E402

TZ = pytz.timezone("Asia/Tashkent")
NOW = TZ.localize(datetime(2026, 10, 15, 10, 0))   # payshanba
DEF = time(12, 0)


def at(d, h, m=0):
    return TZ.localize(datetime(2026, 10, d, h, m))


def run(text, default=DEF):
    return parse_schedule_text(text, NOW, default)


def rec(r):
    x = r.get("recurrence")
    return None if x is None else (x["type"], x["day"], x["time"])


print("== Tabiiy til rejalash parseri ==")

# (ibora, kutilgan boshlanish, kutilgan takrorlanish)
CASES = [
    # --- o'zbekcha ---
    ("bugun soat 12:00 ga har kuni", at(15, 12), ("daily", None, time(12, 0))),
    ("har kuni soat 9:30 da", at(16, 9, 30), ("daily", None, time(9, 30))),
    ("har kuni 18:00", at(15, 18), ("daily", None, time(18, 0))),
    ("ikki kunda bir marta 18:30", at(15, 18, 30), ("interval", 2, time(18, 30))),
    ("har 3 kunda soat 9:00 da", at(16, 9), ("interval", 3, time(9, 0))),
    ("har ikki kunda 20:00", at(15, 20), ("interval", 2, time(20, 0))),
    ("kunora 20:00", at(15, 20), ("interval", 2, time(20, 0))),
    ("har dam olish kuni shu vaqtda", at(17, 12), ("weekdays", WEEKEND_MASK, time(12, 0))),
    ("dam olish kunlari soat 11:00 da", at(17, 11), ("weekdays", WEEKEND_MASK, time(11, 0))),
    ("ish kunlari 8:15", at(16, 8, 15), ("weekdays", WORKDAYS_MASK, time(8, 15))),
    ("har dushanba soat 9 da", at(19, 9), ("weekly", 0, time(9, 0))),
    ("dushanba va chorshanba kunlari 10:00", at(19, 10), ("weekdays", 5, time(10, 0))),
    ("har hafta soat 15:00 da", at(15, 15), ("weekly", 3, time(15, 0))),
    ("ertaga 18:00", at(16, 18), None),
    ("juma kuni soat 18 da", at(16, 18), None),
    ("bugun 15:30", at(15, 15, 30), None),
    ("5 daqiqadan keyin", NOW.replace(minute=5, hour=10) , None),
    ("kechqurun 8 da ertaga", at(16, 20), None),
    # --- ruscha ---
    ("ежедневно в 9:00", at(16, 9), ("daily", None, time(9, 0))),
    ("каждый день в 21:00", at(15, 21), ("daily", None, time(21, 0))),
    ("каждые 2 дня в 18:30", at(15, 18, 30), ("interval", 2, time(18, 30))),
    ("раз в три дня в 12:00", at(15, 12), ("interval", 3, time(12, 0))),
    ("через день в 20:00", at(15, 20), ("interval", 2, time(20, 0))),
    ("по выходным в то же время", at(17, 12), ("weekdays", WEEKEND_MASK, time(12, 0))),
    ("по будням в 8:15", at(16, 8, 15), ("weekdays", WORKDAYS_MASK, time(8, 15))),
    ("каждый понедельник в 9:00", at(19, 9), ("weekly", 0, time(9, 0))),
    ("по пятницам в 17:00", at(16, 17), ("weekly", 4, time(17, 0))),
    ("завтра в 18:00", at(16, 18), None),
    ("в пятницу в 18:00", at(16, 18), None),
    # --- inglizcha ---
    ("every day at 9:00", at(16, 9), ("daily", None, time(9, 0))),
    ("daily at 6pm", at(15, 18), ("daily", None, time(18, 0))),
    ("every 2 days at 18:30", at(15, 18, 30), ("interval", 2, time(18, 30))),
    ("every other day at 20:00", at(15, 20), ("interval", 2, time(20, 0))),
    ("every weekday at 8:15", at(16, 8, 15), ("weekdays", WORKDAYS_MASK, time(8, 15))),
    ("on weekends at the same time", at(17, 12), ("weekdays", WEEKEND_MASK, time(12, 0))),
    ("every monday at 9am", at(19, 9), ("weekly", 0, time(9, 0))),
    ("every Saturday and Sunday at 11:00", at(17, 11), ("weekdays", WEEKEND_MASK, time(11, 0))),
    ("tomorrow 5pm", at(16, 17), None),
    ("tomorrow at 17:30", at(16, 17, 30), None),
    ("on friday at 6pm", at(16, 18), None),
]
for text, start, r in CASES:
    out = run(text)
    ok = out.get("ok") and out["start"] == start and rec(out) == r
    check(f"'{text}'", ok, f"-> {out}")

# --- aniqlanmaydigan / xavfli kirishlar: taxmin yo'q, istisno yo'q ---
for text, reason in [("", "empty"), ("   ", "empty"), ("salom, qalaysiz", "no_time"), ("har kuni", "no_time"), ("dam olish kunlari", "no_time"),
                     ("ertaga", "no_time"), ("a" * (MAX_TEXT_CHARS + 1), "too_long"), ("har kuni soat 25:00 da", None), ("har 0 kunda 12:00", None),
                     ("har 99 kunda 12:00", None), ("bugun 09:00", "past")]:
    out = run(text)
    check(f"rad/aniqlanmadi: {text[:30]!r}", not out["ok"] and (reason is None or out["reason"] == reason), str(out))
check("None / son kirishi yiqilmaydi", parse_schedule_text(None)["ok"] is False and parse_schedule_text(123)["ok"] is False)
check("'shu vaqtda' default_time yo'q bo'lsa taxmin QILINMAYDI (no_time)", run("har dam olish kuni shu vaqtda", default=None).get("reason") == "no_time")
check("o'tib ketgan vaqt: 'bugun 09:00' -> hech qachon o'tmishdagi start qaytmaydi",
      not run("bugun 09:00")["ok"] or run("bugun 09:00")["start"] > NOW)

# --- takrorlanish natijalari kanonik va start doim kelajakda ---
out = run("har kuni soat 12:00")
check("daily start > now", out["ok"] and out["start"] > NOW)
out = run("har 1 kunda 12:00")
check("'har 1 kunda' -> daily (interval=1 normalizatsiya)", out["ok"] and out["recurrence"]["type"] == "daily", str(out))
out = run("shanba va yakshanba 10:00 da har hafta")
check("shanba+yakshanba -> weekdays maskasi", out["ok"] and out["recurrence"]["type"] == "weekdays" and out["recurrence"]["day"] == WEEKEND_MASK, str(out))

# --- fuzz: tasodifiy matn hech qachon istisno ko'tarmaydi, ok=True bo'lsa kelajakda ---
rnd = random.Random(7)
alphabet = string.ascii_letters + string.digits + " :.,-/'" + "ёйцукенгшщзхъфывапролджэячсмитьбю"
pieces = ["har", "kuni", "soat", "12:00", "ertaga", "dam olish", "каждый", "every", "pm", "9", "2", "kunda", "bir", "marta", "по", "будням", "00:00", "24:00", "31.02"]
bad = 0
for i in range(1500):
    if i % 2:
        s = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 60)))
    else:
        s = " ".join(rnd.choice(pieces) for _ in range(rnd.randint(1, 7)))
    try:
        o = parse_schedule_text(s, NOW, DEF)
        if o["ok"] and not o["start"] > NOW:
            bad += 1
            print("   kelajakda emas:", repr(s), o)
    except Exception as exc:  # noqa: BLE001
        bad += 1
        print("   ISTISNO:", repr(s), type(exc).__name__, exc)
check("fuzz: 1500 tasodifiy kirish — istisno yo'q, natija doim kelajakda", bad == 0, str(bad))

# --- validate_proposal (AI zaxirasi chiqishini tekshiradi) ---
ok = validate_proposal(at(20, 12), {"type": "interval", "day": 2, "time": "12:00"}, NOW)
check("AI taklifi: to'g'ri interval qabul", ok["ok"] and ok["recurrence"]["type"] == "interval", str(ok))
check("AI taklifi: o'tmish rad", validate_proposal(at(14, 12), None, NOW) == {"ok": False, "reason": "past"})
check("AI taklifi: 1 yildan uzoq rad", validate_proposal(TZ.localize(datetime(2028, 1, 1, 12)), None, NOW)["ok"] is False)
check("AI taklifi: yaroqsiz takrorlanish rad", validate_proposal(at(20, 12), {"type": "monthly", "day": 3, "time": "12:00"}, NOW)["ok"] is False)
check("AI taklifi: datetime emas rad", validate_proposal("ertaga", None, NOW)["ok"] is False)
check("AI taklifi: takrorlanishsiz bir martalik qabul", validate_proposal(at(20, 12), None, NOW) == {"ok": True, "start": at(20, 12), "recurrence": None})

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
