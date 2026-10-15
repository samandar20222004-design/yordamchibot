#!/usr/bin/env python3
"""Telegram Stars `refunded_payment` hodisasi: adminlarga ogohlantirish, natija matni va xatolarga chidamlilik (DB'siz, repository soxta).

Refund'ning o'zi (to'lov `refunded`, PRO'dan kunlar ayrilishi, idempotentlik) — `tests/stars_refund_apply_test.py` (real PG).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("ADMIN_ID", "111")
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


print("== Stars refunded_payment (DB'siz) ==")
import handlers.subscription as sub  # noqa: E402
from translations.admin_panel import admin_t  # noqa: E402

for lang in ("uz", "ru", "en"):
    txt = admin_t("stars_refund_admin", lang, user_id=1, charge_id="x", amount=5, currency="XTR", outcome="o")
    check(f"[{lang}] admin matni mavjud va to'ldirilgan", txt != "stars_refund_admin" and "{" not in txt, txt[:80])
check("uz/ru/en admin matnlari farq qiladi",
      len({admin_t("stars_refund_admin", code, user_id=1, charge_id="x", amount=5, currency="XTR", outcome=admin_t("stars_refund_outcome_error", code)) for code in ("uz", "ru", "en")}) == 3)


class Bot:
    def __init__(self, fail_for=()):
        self.sent = []
        self.fail_for = set(fail_for)

    async def send_message(self, chat_id, text, **kw):
        if chat_id in self.fail_for:
            raise RuntimeError("admin botni bloklagan")
        self.sent.append((chat_id, text))


def make_update(charge="CHG-<1>", amount=250, currency="XTR", user=777):
    rp = SimpleNamespace(telegram_payment_charge_id=charge, total_amount=amount, currency=currency, invoice_payload="sub_stars_1m_777")
    return SimpleNamespace(message=SimpleNamespace(refunded_payment=rp, from_user=SimpleNamespace(id=user)),
                           effective_user=SimpleNamespace(id=user))


records = []


class H(logging.Handler):
    def emit(self, record):
        records.append((record.levelno, record.getMessage()))


handler = H()
logging.getLogger("handlers.subscription").addHandler(handler)
orig_admins = sub.ADMIN_IDS_SET
db_calls = []
orig_run_db = sub.db.run_db


async def spy_run_db(fn, *a, **k):
    db_calls.append(getattr(fn, "__name__", str(fn)))
    if getattr(fn, "__name__", "") == "get_user_language":
        return "uz"
    if getattr(fn, "__name__", "") == "refund_stars_payment":
        return {"result": "unknown_charge", "user_id": None, "days": 0}  # repository testi alohida (real PG)
    raise AssertionError("kutilmagan DB chaqiruvi: " + str(fn))


try:
    sub.ADMIN_IDS_SET = {111, 222}
    sub.db.run_db = spy_run_db
    bot = Bot()
    ctx = SimpleNamespace(bot=bot)
    asyncio.run(sub.refunded_payment_callback(make_update(), ctx))
    check("har bir adminga BITTA ogohlantirish yuborildi", sorted(c for c, _ in bot.sent) == [111, 222], str(bot.sent)[:200])
    text = bot.sent[0][1] if bot.sent else ""
    check("xabarda foydalanuvchi, charge id (HTML-escape) va summa bor",
          "777" in text and "CHG-&lt;1&gt;" in text and "CHG-<1>" not in text and "250" in text and "XTR" in text, text[:300])
    check("xabarda natija bor (to'lov bazada topilmadi -> PRO'ni qo'lda tekshiring)", "PRO" in text and "{" not in text, text[:300])
    check("WARNING log yozildi", any(lvl >= logging.WARNING and "refund" in msg.lower() for lvl, msg in records), str(records)[:200])
    check("handler faqat refund_stars_payment va til o'qishini chaqirdi", set(db_calls) <= {"get_user_language", "refund_stars_payment"} and "refund_stars_payment" in db_calls, str(db_calls))

    # bitta admin botni bloklagan: ikkinchisiga baribir yetib boradi, istisno chiqmaydi
    bot2 = Bot(fail_for={111})
    try:
        asyncio.run(sub.refunded_payment_callback(make_update(), SimpleNamespace(bot=bot2)))
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", type(exc).__name__, exc)
    check("bitta admin xatosi boshqasiga xalaqit bermaydi, handler qulamaydi", ok and [c for c, _ in bot2.sent] == [222], str(bot2.sent))

    # buzuq update: refunded_payment yo'q -> jim
    try:
        asyncio.run(sub.refunded_payment_callback(SimpleNamespace(message=SimpleNamespace(refunded_payment=None, from_user=None), effective_user=None),
                                                  SimpleNamespace(bot=Bot())))
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    check("refunded_payment'siz update handler'ni qulatmaydi", ok)
finally:
    sub.ADMIN_IDS_SET = orig_admins
    sub.db.run_db = orig_run_db
    logging.getLogger("handlers.subscription").removeHandler(handler)

check("PTB filtri mavjud bo'lsa handler ulanadi (refunded_payment_filter)", sub.refunded_payment_filter() is not None)

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
