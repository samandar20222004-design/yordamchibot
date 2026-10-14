#!/usr/bin/env python3
"""AUDIT-004: muddati o'tgan PRO'ni 'free'ga tushirish (lazy downgrade) parallel to'lovni BOSMASLIGI kerak.

Real PostgreSQL (faqat sinov bazasi). Poyga aniq tartibga solinadi: downgrade yozuvidan OLDIN (muddat o'qilgach)
boshqa ulanishda to'lov/obuna yangilanishi COMMIT qilinadi. Eski kodda `UPDATE ... SET plan_type='free' WHERE user_id`
shartsiz edi -> yangi muddat + 'free' plan. To'g'ri xulq: faol (kelajak muddatli) obuna 'pro' qoladi;
haqiqatan muddati o'tgan foydalanuvchi esa baribir 'free'ga tushadi.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_downgrade")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== AUDIT-004: lazy downgrade vs parallel to'lov (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories import users_repository as users_repo  # noqa: E402
from services import subscription_service as sub_mod  # noqa: E402
from services.payment_service import PaymentService  # noqa: E402
from services.subscription_service import SubscriptionService  # noqa: E402

BASE = 9_500_000
IDS = list(range(BASE, BASE + 50))


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM payments WHERE user_id = ANY(%s)", (IDS,))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (IDS,))


def mk(uid, plan, expires_sql):
    q("INSERT INTO users (user_id, username, plan_type, subscription_expires_at) "
      f"VALUES (%s, %s, %s, {expires_sql})", (uid, f"d{uid}", plan))  # nosec B608 — ichki literal


def state(uid):
    plan, active = q("SELECT plan_type, subscription_expires_at > NOW() FROM users WHERE user_id = %s", (uid,))[0]
    return plan, bool(active)


def stars_payment(uid):
    return PaymentService.process_stars_payment(uid, f"race-charge-{uid}", 0, "legacy", plan="pro", duration_days=30)


PAYMENTS = {"Stars to'lovi": stars_payment, "admin activate": lambda uid: SubscriptionService.activate(uid, "pro", 30)}

cleanup()
try:
    # ---- 1) SubscriptionService.get_status: o'qish -> (to'lov COMMIT) -> downgrade yozuvi
    for name, pay in PAYMENTS.items():
        uid = BASE + (1 if name.startswith("Stars") else 2)
        mk(uid, "pro", "NOW() - interval '1 day'")
        real_cursor = sub_mod.db_cursor
        state_box = {"calls": 0, "busy": False}

        import contextlib

        @contextlib.contextmanager
        def hooked(commit=False, *a, _uid=uid, _pay=pay, **kw):
            state_box["calls"] += 1
            if commit and not state_box["busy"]:
                # downgrade yozuvi navbati: shu paytda to'lov boshqa ulanishda COMMIT qilinadi
                state_box["busy"] = True
                res = _pay(_uid)
                state_box["pay"] = res
            with real_cursor(commit=commit, *a, **kw) as cur:
                yield cur

        sub_mod.db_cursor = hooked
        try:
            st = SubscriptionService.get_status(uid)
        finally:
            sub_mod.db_cursor = real_cursor
        plan, active = state(uid)
        pay_ok = state_box.get("pay") in (True,) or (isinstance(state_box.get("pay"), dict) and state_box["pay"].get("ok"))
        check(f"[{name}] to'lov interleaving'da muvaffaqiyatli bajarildi", pay_ok, str(state_box.get("pay")))
        check(f"[{name}] get_status: o'qish paytida muddati o'tgan edi (chaqiruv 'free' deydi)", st["plan_type"] == "free", str(st))
        check(f"[{name}] FAOL (yangi muddatli) obuna 'free'ga TUSHMADI", plan == "pro" and active, f"plan={plan} faol={active}")

    # ---- 2) users_repository._effective_plan: o'qish -> (to'lov COMMIT) -> downgrade
    uid = BASE + 3
    mk(uid, "pro", "NOW() - interval '1 day'")
    real_expired = users_repo._subscription_expired
    fired = {"n": 0}

    def expired_then_payment(cur, user_id):
        result = real_expired(cur, user_id)  # muddat o'qildi: o'tgan
        if fired["n"] == 0:
            fired["n"] = 1
            stars_payment(user_id)  # boshqa ulanishda to'lov COMMIT
        return result

    users_repo._subscription_expired = expired_then_payment
    try:
        with db.db_cursor(commit=True) as cur:
            eff = users_repo._effective_plan(cur, "pro", uid)
    finally:
        users_repo._subscription_expired = real_expired
    plan, active = state(uid)
    check("[_effective_plan] chaqiruv paytidagi qiymat 'free' (muddat o'tgan edi)", eff == "free")
    check("[_effective_plan] FAOL (yangi muddatli) obuna 'free'ga TUSHMADI", plan == "pro" and active, f"plan={plan} faol={active}")

    # ---- 3) Xulq saqlanishi: haqiqatan muddati o'tgan foydalanuvchi 'free'ga TUSHADI
    uid = BASE + 4
    mk(uid, "pro", "NOW() - interval '2 days'")
    st = SubscriptionService.get_status(uid)
    plan, _ = state(uid)
    check("muddati o'tgan PRO: get_status 'free' va DB 'free'", st["plan_type"] == "free" and plan == "free")
    uid = BASE + 5
    mk(uid, "pro", "NOW() - interval '2 days'")
    with db.db_cursor(commit=True) as cur:
        eff = users_repo._effective_plan(cur, "pro", uid)
    plan, _ = state(uid)
    check("muddati o'tgan PRO: _effective_plan 'free' va DB 'free'", eff == "free" and plan == "free")
    uid = BASE + 6
    mk(uid, "enterprise", "NULL")
    st = SubscriptionService.get_status(uid)
    plan, _ = state(uid)
    check("muddatsiz enterprise tegilmaydi", st["plan_type"] == "enterprise" and plan == "enterprise")

    # ---- 4) Haqiqiy parallellik: ko'p thread, to'lov va get_status bir vaqtda
    uid = BASE + 7
    mk(uid, "pro", "NOW() - interval '1 day'")
    barrier = threading.Barrier(9)
    errors = []

    def worker(kind):
        try:
            barrier.wait(timeout=20)
            if kind == "pay":
                stars_payment(uid)
            else:
                SubscriptionService.get_status(uid)
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker, args=("pay",))] + [threading.Thread(target=worker, args=("read",)) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    plan, active = state(uid)
    # to'lov hech bo'lmaganda bir marta o'tgan (charge idempotent); yakuniy holat 'pro'+faol bo'lishi shart
    check("8 parallel get_status + to'lov: yakuniy holat 'pro' va muddat faol", plan == "pro" and active, f"plan={plan} faol={active} xatolar={errors[:2]}")
finally:
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(0 if failed == 0 else 1)
