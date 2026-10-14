#!/usr/bin/env python3
"""AUDIT-005: Stars to'lovi (SuccessfulPayment) validatsiyadan o'tmasa JIM QOLMASLIK kerak.

Telegram pulni allaqachon olgan. Rad etilganda: PRO BERILMAYDI, refund BOSHLANMAYDI (ikkalasi ham admin qarori),
lekin foydalanuvchiga tushunarli xabar (uz/ru/en), adminlarga ogohlantirish (charge_id + xavfsiz sabab kodi) va log
yoziladi. To'g'ri to'lov esa avvalgidek ishlaydi. DB talab qilinmaydi (handler fake'lar bilan).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ADMIN_ID", "111")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from handlers import subscription as sub  # noqa: E402
from locales.translations import get_text  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


UID = 4_242_001
ADMINS = {111, 222}
calls = {"process": 0}


def fake_process(*a, **k):
    calls["process"] += 1
    return {"ok": True, "duplicate": False, "days": 30}


async def fake_run_db(fn, *a, **k):
    if fn is sub.db.process_stars_payment:
        return fake_process(*a, **k)
    if fn is sub.db.get_user_language:
        return "uz"
    raise AssertionError(f"kutilmagan DB chaqiruvi: {getattr(fn, '__name__', fn)}")


def run(payment, lang="uz"):
    replies, sent = [], []

    async def reply_text(text, **kw):
        replies.append(text)

    async def send_message(chat_id, text, **kw):
        sent.append((chat_id, text))

    async def fake_lang(context, user_id):
        return lang

    msg = SimpleNamespace(successful_payment=payment, reply_text=reply_text)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=UID))
    ctx = SimpleNamespace(user_data={"lang": lang}, bot=SimpleNamespace(send_message=send_message))
    saved = (sub.db.run_db, sub.ensure_user_lang, sub.ADMIN_IDS_SET)
    sub.db.run_db, sub.ensure_user_lang, sub.ADMIN_IDS_SET = fake_run_db, fake_lang, ADMINS
    calls["process"] = 0
    try:
        asyncio.run(sub.successful_payment_callback(upd, ctx))
    finally:
        sub.db.run_db, sub.ensure_user_lang, sub.ADMIN_IDS_SET = saved
    return replies, sent


def pay(payload=f"sub_stars_1m_{UID}", amount=None, currency="XTR", charge="tg-charge-1"):
    plan = sub.STARS_PLANS["stars_1m"]
    return SimpleNamespace(invoice_payload=payload, total_amount=plan["stars"] if amount is None else amount,
                           currency=currency, telegram_payment_charge_id=charge)


print("== AUDIT-005: Stars to'lovi validatsiyadan o'tmasa ==")
cases = {
    "summa mos emas": pay(amount=1),
    "boshqa foydalanuvchi payload'i": pay(payload=f"sub_stars_1m_{UID + 9}"),
    "noma'lum payload": pay(payload="hack"),
    "valyuta XTR emas": pay(currency="USD"),
    "charge_id bo'sh": pay(charge=""),
}
for name, payment in cases.items():
    replies, sent = run(payment)
    check(f"[{name}] PRO BERILMADI (process_stars_payment chaqirilmadi)", calls["process"] == 0)
    check(f"[{name}] foydalanuvchiga tushunarli xabar yuborildi", len(replies) == 1 and replies[0] == get_text("sub_pay_activate_error", "uz"), str(replies))
    check(f"[{name}] BARCHA adminlarga ogohlantirish ketdi", {c for c, _ in sent} == ADMINS, str(sent))
    body = " ".join(t for _, t in sent)
    check(f"[{name}] admin xabarida foydalanuvchi ID va xavfsiz sabab kodi bor",
          str(UID) in body and ("validation_rejected" in body or "missing_charge_id" in body), body[:200])
    check(f"[{name}] foydalanuvchi matni (payload) admin xabariga TUSHMADI", "hack" not in body)

for lang in ("ru", "en"):
    replies, _ = run(pay(amount=1), lang=lang)
    check(f"[{lang}] xabar shu tilda", replies == [get_text("sub_pay_activate_error", lang)] and replies[0] != get_text("sub_pay_activate_error", "uz"), str(replies))

replies, sent = run(pay())
check("TO'G'RI to'lov: process_stars_payment AYNAN 1 marta chaqirildi", calls["process"] == 1)
check("TO'G'RI to'lov: admin ogohlantirishi YO'Q", sent == [])
check("TO'G'RI to'lov: muvaffaqiyat xabari (xato xabari emas)", len(replies) == 1 and replies[0] != get_text("sub_pay_activate_error", "uz"), str(replies))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
