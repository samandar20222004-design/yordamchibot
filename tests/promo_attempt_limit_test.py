#!/usr/bin/env python3
"""Promo-kod: noto'g'ri urinishlar limiti (DB'siz).

Kod taxmin qilishga qarshi: oynada MAX_FAILS ta xatodan keyin DB'ga TEGILMAYDI; muvaffaqiyat hisoblagichni nolga qaytaradi;
foydalanuvchilar bir-biriga ta'sir qilmaydi; oyna o'tgach yana mumkin; xotira chegaralangan; matn uch tilda.
"""
from __future__ import annotations

import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:PROMO_LIMIT_TEST_TOKEN")
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


import database as db  # noqa: E402
import handlers.subscription as SUB  # noqa: E402
from locales.translations import get_text  # noqa: E402
from services.promo_attempts import MAX_FAILS, WINDOW_SECONDS, PromoAttemptLimiter  # noqa: E402

print("== Promo-kod urinish limiti ==")

for lang in ("uz", "ru", "en"):
    t = get_text("sub_promo_blocked", lang, minutes=7)
    check(f"[{lang}] sub_promo_blocked mavjud, daqiqa to'ldirilgan", t != "sub_promo_blocked" and "7" in t and "{minutes}" not in t, t)
check("uz/ru/en matnlari farq qiladi", len({get_text("sub_promo_blocked", lg, minutes=7) for lg in ("uz", "ru", "en")}) == 3)

# --- sof limiter (soxta soat) ---
now = [1000.0]
lim = PromoAttemptLimiter(max_fails=3, window=100, max_tracked=4, clock=lambda: now[0])
check("boshida bloklanmagan", lim.retry_after(1) == 0)
lim.record_failure(1)
lim.record_failure(1)
check("limitdan past: hali bloklanmagan", lim.retry_after(1) == 0)
lim.record_failure(1)
w = lim.retry_after(1)
check("3-xatodan keyin bloklangan, kutish ~100 s", 99 <= w <= 101, str(w))
check("boshqa foydalanuvchi ta'sirlanmaydi", lim.retry_after(2) == 0)
now[0] += 60
check("60 s o'tgach kutish kamaydi (~40 s)", 39 <= lim.retry_after(1) <= 41, str(lim.retry_after(1)))
now[0] += 41
check("oyna o'tgach (101 s) yana mumkin", lim.retry_after(1) == 0)
lim.record_failure(1)
lim.record_failure(1)
lim.record_failure(1)
lim.reset(1)
check("reset (muvaffaqiyat) hisoblagichni nolga qaytaradi", lim.retry_after(1) == 0)
for uid in range(10, 20):
    lim.record_failure(uid)
check("xotira chegaralangan (max_tracked=4)", len(lim._fails) <= 4, str(len(lim._fails)))
for _ in range(50):
    lim.record_failure(99)
check("bitta foydalanuvchi navbati ham chegaralangan", len(lim._fails[99]) <= 3)


# --- handler ---
class Msg:
    def __init__(self, text):
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


def attempt(uid, code, redeem_result, lang="ru"):
    calls = []

    async def fake_run_db(fn, *args, **kw):
        if fn is db.redeem_promo_code:
            calls.append(args)
            return redeem_result
        if fn is db.get_user_plan:
            return {"plan_type": "free"}
        raise AssertionError(f"kutilmagan db chaqiruvi: {getattr(fn, '__name__', fn)}")

    msg = Msg(code)
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=uid), message=msg)
    c = SimpleNamespace(user_data={"lang": lang}, chat_data={}, bot=None)
    orig = db.run_db
    db.run_db = fake_run_db
    try:
        state = asyncio.run(SUB.promo_code_received(upd, c))
    finally:
        db.run_db = orig
    return state, calls, msg


SUB.promo_limiter.reset(501)
SUB.promo_limiter.reset(502)
FAIL = (False, "Promo-kod topilmadi.")
for i in range(MAX_FAILS):
    state, calls, msg = attempt(501, f"X{i}", FAIL)
    assert len(calls) == 1
check(f"{MAX_FAILS} ta xato urinish: har biri DB'ga bordi", True)
state, calls, msg = attempt(501, "YANA", FAIL)
check("limitdan keyin: DB'ga TEGILMADI", calls == [], str(calls))
check("limitdan keyin: foydalanuvchi PROMO_INPUT'da qoladi va ruscha blok xabari oladi",
      state == SUB.PROMO_INPUT and len(msg.sent) == 1 and "мин" in msg.sent[0], str(msg.sent))
state, calls, msg = attempt(502, "BOSHQA", (True, "Promo-kod faollashtirildi! 30 kunlik PRO tarif yoqildi."))
check("boshqa foydalanuvchi ta'sirlanmaydi (muvaffaqiyat)", len(calls) == 1 and state != SUB.PROMO_INPUT, f"{calls} {state}")

# muvaffaqiyat hisoblagichni tozalaydi
SUB.promo_limiter.reset(503)
for i in range(MAX_FAILS - 1):
    attempt(503, f"Z{i}", FAIL)
attempt(503, "TOGRI", (True, "Promo-kod faollashtirildi! 30 kunlik PRO tarif yoqildi."))
check("muvaffaqiyatdan keyin hisoblagich nolga tushdi", SUB.promo_limiter.retry_after(503) == 0)
for i in range(MAX_FAILS - 1):
    attempt(503, f"W{i}", FAIL)
state, calls, msg = attempt(503, "OXIRGI", FAIL)
check("tozalangandan keyin yana to'liq limit beriladi (yana 1 ta urinish DB'ga bordi)", len(calls) == 1, str(calls))

check("oyna konstantasi o'zgarmagan (600 s)", WINDOW_SECONDS == 600)
SUB.promo_limiter.reset(501)
SUB.promo_limiter.reset(503)

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
