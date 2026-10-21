#!/usr/bin/env python3
"""Promo-kod: «Promo-kod» bosilgach suhbat holati yo'qolsa ham kod qabul qilinadi; kiritish tozalanadi (DB'siz)."""
from __future__ import annotations

import asyncio
import os
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:PROMO_WAIT_TEST_TOKEN")
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
import handlers as H  # noqa: E402
import handlers.subscription as SUB  # noqa: E402
from services.promo_service import normalize_promo_input as norm  # noqa: E402

print("== Kiritishni tozalash ==")
check("oddiy", norm("yangi1") == "YANGI1")
check("zero-width belgi", norm("YAN​GI1‏") == "YANGI1")
check("probel va yangi qator", norm("  YAN GI1\n") == "YANGI1")
check("qo'shtirnoq/qavs", norm("«YANGI1»") == "YANGI1" and norm('"YANGI1".') == "YANGI1")
check("keng harflar (NFKC)", norm("ＹＡＮＧＩ１") == "YANGI1")
check("bo'sh/None", norm("") == "" and norm(None) == "")
check("defis/pastki chiziq saqlanadi", norm("pro-2024_x") == "PRO-2024_X")

print("== Holat yo'qolganda ==")


class Msg:
    def __init__(self, text):
        self.text, self.sent = text, []

    async def reply_text(self, text, **kw):
        self.sent.append(text)


def run_fallback(ud, text, redeem=(True, "Promo-kod faollashtirildi! 30 kunlik PRO tarif yoqildi.")):
    calls = []

    async def fake_run_db(fn, *a, **k):
        if fn is db.redeem_promo_code:
            calls.append(a)
            return redeem
        if fn is db.get_user_plan:
            return {"plan_type": "free"}
        if getattr(fn, "__name__", "") == "get_user_language":
            return "uz"
        return None

    msg = Msg(text)
    upd = SimpleNamespace(effective_user=SimpleNamespace(id=777), effective_message=msg, message=msg)
    ctx = SimpleNamespace(user_data=ud, chat_data={}, bot=None, application=None)
    orig = db.run_db
    db.run_db = fake_run_db
    try:
        asyncio.run(H.unknown_message_fallback(upd, ctx))
    finally:
        db.run_db = orig
    return calls, msg


SUB.promo_limiter.reset(777)
ud = {"lang": "uz"}
calls, msg = run_fallback(ud, "YANGI1")
check("bayroqsiz: promo emas (DB'ga bormaydi)", calls == [])

ud = {"lang": "uz", SUB.UD_PROMO_WAIT: time.time()}
calls, msg = run_fallback(ud, "YANGI1")
check("bayroq bor: kod DB'ga yetdi", len(calls) == 1 and calls[0][1] == "YANGI1", str(calls))
check("muvaffaqiyatda bayroq tozalandi", SUB.UD_PROMO_WAIT not in ud)
check("foydalanuvchiga javob berildi", len(msg.sent) == 1)

ud = {"lang": "uz", SUB.UD_PROMO_WAIT: time.time()}
calls, msg = run_fallback(ud, "NOTOGRI", redeem=(False, "Promo-kod topilmadi."))
check("xato kodda bayroq qoladi (qayta urinish mumkin)", SUB.UD_PROMO_WAIT in ud and len(msg.sent) == 1)
SUB.promo_limiter.reset(777)

ud = {"lang": "uz", SUB.UD_PROMO_WAIT: time.time() - SUB.PROMO_WAIT_SECONDS - 5}
check("eskirgan bayroq faol emas", not SUB.promo_wait_active(SimpleNamespace(user_data=ud)))
check("user_data yo'q bo'lsa ham xato bermaydi", not SUB.promo_wait_active(SimpleNamespace()))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
