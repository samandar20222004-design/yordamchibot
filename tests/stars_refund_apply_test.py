#!/usr/bin/env python3
"""Telegram Stars refund: to'lov `refunded` bo'ladi va shu to'lovning kunlari PRO'dan ayriladi (real PostgreSQL, faqat sinov bazasi).

* idempotent: takroriy refund hodisasi ikkinchi marta kun ayirmaydi;
* boshqa to'lovlardan qo'shilgan muddat saqlanadi; qolgan muddat <= hozir bo'lsa `free`;
* muddatsiz (admin bergan) pro/enterprise'ga tegilmaydi; noma'lum charge hech narsani o'zgartirmaydi;
* handler: foydalanuvchiga va adminlarga xabar, DB xatosida ham qulamaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_refund")
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


print("== Stars refund (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import config  # noqa: E402
import database as db  # noqa: E402
from services.payment_service import PaymentService  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

U1, U2, U3, U4, U5 = (9_400_000_041 + i for i in range(5))
USERS = (U1, U2, U3, U4, U5)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def user(uid):
    return q("SELECT plan_type, subscription_expires_at, (subscription_expires_at - NOW()) FROM users WHERE user_id = %s", (uid,))[0]


def pay(uid, charge, key="stars_1m"):
    return PaymentService.process_stars_payment(uid, charge, config.STARS_PLANS[key]["stars"], f"sub_{key}_{uid}", "pro", config.STARS_PLANS[key]["days"])


def cleanup():
    q("DELETE FROM payments WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (list(USERS),))


cleanup()
try:
    for uid in USERS:
        q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free')", (uid, f"r{uid}"))

    # 1) bitta 30 kunlik to'lov -> refund -> free
    check("to'lov o'tdi", pay(U1, "CH-1")["ok"] and user(U1)[0] == "pro")
    r = db.refund_stars_payment("CH-1")
    check("refund: revoked, 30 kun", r["result"] == "revoked" and r["days"] == 30 and r["user_id"] == U1, str(r))
    check("PRO -> free (qolgan muddat <= hozir)", user(U1)[0] == "free")
    check("to'lov holati refunded", q("SELECT status FROM payments WHERE telegram_payment_charge_id='CH-1'")[0][0] == "refunded")
    check("takroriy hodisa: already, hech narsa o'zgarmadi", db.refund_stars_payment("CH-1")["result"] == "already" and user(U1)[0] == "free")

    # 2) ikki to'lov: bittasi qaytarilsa ikkinchisining muddati qoladi
    pay(U2, "CH-2a")
    pay(U2, "CH-2b")
    before = user(U2)[2]
    r = db.refund_stars_payment("CH-2a")
    after = user(U2)
    check("ikki to'lovdan bittasi qaytdi: PRO qoladi, ~30 kun ayrildi", r["result"] == "revoked" and after[0] == "pro"
          and 29.5 < (before - after[2]).total_seconds() / 86400 - 0 < 30.5 + 0.01, f"{before} -> {after[2]}")
    db.refund_stars_payment("CH-2a")
    check("qayta yuborilgan refund ikkinchi marta kun ayirmaydi", abs((user(U2)[2] - after[2]).total_seconds()) < 5)

    # 3) muddatsiz tariflar
    q("UPDATE users SET plan_type='enterprise', subscription_expires_at=NULL WHERE user_id=%s", (U3,))
    pay(U3, "CH-3")
    r = db.refund_stars_payment("CH-3")
    check("muddatsiz enterprise'ga tegilmadi", r["result"] == "revoked" and user(U3)[0] == "enterprise" and user(U3)[1] is None, str(user(U3)))
    q("UPDATE users SET plan_type='pro', subscription_expires_at=NULL WHERE user_id=%s", (U4,))
    q("INSERT INTO payments (user_id, amount, currency, payload, telegram_payment_charge_id, status, payment_method) "
      "VALUES (%s, %s, 'XTR', %s, 'CH-4', 'succeeded', 'international_stars')",
      (U4, config.STARS_PLANS['stars_1m']['stars'], f"sub_stars_1m_{U4}"))
    db.refund_stars_payment("CH-4")
    check("muddatsiz (admin bergan) pro'ga tegilmadi", user(U4)[0] == "pro" and user(U4)[1] is None)

    # 4) noma'lum charge / payload
    check("noma'lum charge: unknown_charge, hech narsa o'zgarmadi", db.refund_stars_payment("NOPE")["result"] == "unknown_charge")
    check("bo'sh charge: unknown_charge", db.refund_stars_payment("")["result"] == "unknown_charge")
    q("INSERT INTO payments (user_id, amount, currency, payload, telegram_payment_charge_id, status, payment_method) "
      "VALUES (%s, 5, 'XTR', 'erkin_payload', 'CH-5', 'succeeded', 'international_stars')", (U5,))
    q("UPDATE users SET plan_type='pro', subscription_expires_at = NOW() + INTERVAL '20 days' WHERE user_id=%s", (U5,))
    r = db.refund_stars_payment("CH-5")
    check("payload tarifga mos kelmasa: no_days, to'lov refunded, PRO tegilmadi (admin qo'lda ko'radi)",
          r["result"] == "no_days" and user(U5)[0] == "pro", str(r))

    # 5) handler
    import handlers.subscription as sub

    class Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))

    def upd(charge, uid):
        rp = SimpleNamespace(telegram_payment_charge_id=charge, total_amount=250, currency="XTR", invoice_payload="")
        return SimpleNamespace(message=SimpleNamespace(refunded_payment=rp, from_user=SimpleNamespace(id=uid)), effective_user=SimpleNamespace(id=uid))

    pay(U1, "CH-6")
    orig = sub.ADMIN_IDS_SET
    sub.ADMIN_IDS_SET = {111}
    try:
        bot = Bot()
        asyncio.run(sub.refunded_payment_callback(upd("CH-6", U1), SimpleNamespace(bot=bot)))
        targets = sorted(c for c, _ in bot.sent)
        check("handler: foydalanuvchiga va adminga xabar ketdi, PRO ayrildi", targets == sorted([111, U1]) and user(U1)[0] == "free", str(bot.sent)[:200])
        admin_text = next(t for c, t in bot.sent if c == 111)
        check("admin xabarida natija (30 kun ayrildi)", "30" in admin_text, admin_text[:200])
        bot = Bot()
        asyncio.run(sub.refunded_payment_callback(upd("CH-6", U1), SimpleNamespace(bot=bot)))
        check("takroriy hodisada foydalanuvchiga YANA xabar yuborilmaydi (faqat admin)", [c for c, _ in bot.sent] == [111], str(bot.sent)[:200])
        orig_run = sub.db.run_db

        async def boom(fn, *a, **k):
            if getattr(fn, "__name__", "") == "refund_stars_payment":
                raise RuntimeError("DB yiqildi")
            return await orig_run(fn, *a, **k)

        sub.db.run_db = boom
        bot = Bot()
        try:
            asyncio.run(sub.refunded_payment_callback(upd("CH-7", U1), SimpleNamespace(bot=bot)))
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        finally:
            sub.db.run_db = orig_run
        check("DB xatosida handler qulamaydi, admin baribir xabar oladi", ok and [c for c, _ in bot.sent] == [111], str(bot.sent)[:200])
    finally:
        sub.ADMIN_IDS_SET = orig
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
