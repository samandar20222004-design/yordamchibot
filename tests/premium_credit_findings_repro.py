#!/usr/bin/env python3
"""Premium/kredit bo'yicha 3 ta topilmani REAL PostgreSQL'da takrorlash (qo'lda ishga tushiriladi).

DIQQAT: faqat ALOHIDA SINOV BAZASI. `PREMIUM_REPRO_DATABASE_URL` berilmasa SKIP. Skript
`init_db()` ni shu bazada ishga tushiradi va 9100000+ oralig'idagi user_id'larni yozib/o'chiradi.
`tests/run_tests.sh` ga ULANMAGAN. Holat: A (bonus) VA B (enterprise) VA C (kechagi bron) TUZATILGAN —
bu skript endi `--strict` rejimida regressiya sifatida ishlatilishi mumkin; doimiy regressiyalar: credits_bonus_concurrency_test,
enterprise_plan_preservation_test, ai_refund_period_test.

  A. Kunlik faollik bonusi parallel chaqiruvda ikki marta berilishi (credits_service.py:333-362).
  B. Enterprise (muddatsiz) foydalanuvchi PRO sotib olganda tarifi/muddati o'zgarishi
     (payment_service / subscription_service / payme_repository) — Stars obuna yo'li bilan solishtiriladi.
  C. Kecha yaratilgan bron bugun qaytarilganda bugungi kunlik hisoblagich kamayishi (users_repository.py:1759-1768).

Rejim: sukut — hisobot (exit 0, takrorlangan nuqsonlar `REPRODUCED` deb chiqadi).
`--strict` — nuqson takrorlansa exit 1 (tuzatishdan keyin regressiya sifatida ishlatish uchun).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

URL = os.environ.get("PREMIUM_REPRO_DATABASE_URL", "")
STRICT = "--strict" in sys.argv
if not URL:
    print("[SKIP] PREMIUM_REPRO_DATABASE_URL berilmagan (faqat alohida sinov bazasi)")
    sys.exit(0)

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ["DATABASE_URL"] = URL
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from services.credits_service import (  # noqa: E402
    ACTIVITY_BONUS_THRESHOLD,
    OP_ACTIVITY_BONUS,
    CreditsService,
)

BASE = 9_100_000
reproduced = []


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    ids = list(range(BASE, BASE + 400))
    q("DELETE FROM ai_reservations WHERE user_id = ANY(%s)", (ids,))
    q("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (ids,))
    q("DELETE FROM payments WHERE user_id = ANY(%s)", (ids,))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (ids,))


def mk_user(uid, **cols):
    q("INSERT INTO users (user_id, username) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING",
      (uid, f"repro_{uid}"))
    for k, v in cols.items():
        q(f"UPDATE users SET {k} = %s WHERE user_id = %s", (v, uid))  # nosec B608 — ichki ustun nomlari


def report(tag, bug, detail):
    status = "REPRODUCED (nuqson takrorlandi)" if bug else "NOT REPRODUCED"
    print(f"  [{status}] {tag}: {detail}")
    if bug:
        reproduced.append(tag)


# ----------------------------------------------------------------- A
def seed_bonus_user(uid):
    mk_user(uid, ai_credits=0)
    for _ in range(ACTIVITY_BONUS_THRESHOLD):
        q("INSERT INTO ai_reservations (user_id, operation_type, cost, source, status) "
          "VALUES (%s, 'other', 1, 'daily_quota', 'active')", (uid,))


def bonus_rows(uid):
    return q("SELECT COUNT(*) FROM credits_ledger WHERE user_id = %s AND operation_type = %s",
             (uid, OP_ACTIVITY_BONUS))[0][0]


def race(uids, threads_per_user):
    barrier = threading.Barrier(len(uids) * threads_per_user)

    def work(uid):
        barrier.wait()
        CreditsService.maybe_grant_activity_bonus(uid)

    ts = [threading.Thread(target=work, args=(u,)) for u in uids for _ in range(threads_per_user)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()


print("== A. Kunlik faollik bonusi: parallel chaqiruv ==")
natural_total = natural_doubled = 0
for rnd in range(10):  # 10 raund x 4 foydalanuvchi x 2 parallel chaqiruv
    uids = [BASE + rnd * 4 + i for i in range(4)]
    for u in uids:
        q("DELETE FROM credits_ledger WHERE user_id = %s", (u,))
        q("DELETE FROM ai_reservations WHERE user_id = %s", (u,))
        seed_bonus_user(u)
    race(uids, 2)
    natural_total += len(uids)
    natural_doubled += sum(1 for u in uids if bonus_rows(u) > 1)
report("A-tabiiy", natural_doubled > 0,
       f"{natural_total} foydalanuvchi x 2 parallel chaqiruv (sun'iy kechiktirish YO'Q, per-user update-lock chetlab "
       f"o'tilgan): ikki marta berilgan = {natural_doubled}/{natural_total}")

orig = CreditsService.count_today_ai_requests


def slow_count(user_id, cur=None):
    result = orig(user_id, cur=cur)
    time.sleep(0.2)  # ENG KO'PI: tekshiruv va INSERT orasidagi oynani sun'iy kengaytiradi (boshqa kod o'zgarmagan)
    return result


CreditsService.count_today_ai_requests = staticmethod(slow_count)
try:
    uids2 = [BASE + 100 + i for i in range(4)]
    for u in uids2:
        seed_bonus_user(u)
    race(uids2, 2)
finally:
    CreditsService.count_today_ai_requests = staticmethod(orig)
doubled2 = [u for u in uids2 if bonus_rows(u) > 1]
report("A-kengaytirilgan-oyna", bool(doubled2),
       f"tekshiruv va INSERT orasiga 0.2s sun'iy kechikish qo'yilgan holda: ikki marta berilgan = "
       f"{len(doubled2)}/{len(uids2)}; balans (birinchi user) = "
       f"{q('SELECT ai_credits FROM users WHERE user_id=%s', (uids2[0],))[0][0]}")

# ----------------------------------------------------------------- B
print("\n== B. Enterprise (muddatsiz) foydalanuvchi PRO sotib olganda ==")
from repositories.payme_repository import PostgresPaymeUnitOfWork  # noqa: E402
from repositories.users_repository import sync_stars_subscription  # noqa: E402
from services.payment_service import PaymentService  # noqa: E402
from services.subscription_service import SubscriptionService  # noqa: E402


def plan_of(uid):
    row = q("SELECT plan_type, subscription_expires_at IS NULL FROM users WHERE user_id = %s", (uid,))[0]
    return row[0], bool(row[1])


def paths():
    yield "Stars/karta (PaymentService.process_stars_payment)", lambda uid: PaymentService.process_stars_payment(
        uid, f"repro-charge-{uid}", 0, "legacy", plan="pro", duration_days=30)
    yield "Admin/obuna (SubscriptionService.activate)", lambda uid: SubscriptionService.activate(uid, "pro", 30)

    def payme(uid):
        with db.db_cursor(commit=True) as cur:
            return PostgresPaymeUnitOfWork(cur).grant_subscription(uid, 30)

    yield "Payme (PostgresPaymeUnitOfWork.grant_subscription)", payme
    yield "NAZORAT: Stars obuna holati (sync_stars_subscription)", lambda uid: sync_stars_subscription(
        uid, "active", expires_at=None)


for i, (name, fn) in enumerate(paths()):
    uid = BASE + 200 + i
    mk_user(uid, plan_type="enterprise", subscription_expires_at=None)
    try:
        fn(uid)
    except Exception as exc:  # noqa: BLE001
        print(f"  [ERR] {name}: {type(exc).__name__}")
        continue
    plan, unlimited = plan_of(uid)
    changed = not (plan == "enterprise" and unlimited)
    if name.startswith("NAZORAT"):
        print(f"  [NAZORAT] {name}: plan={plan}, muddatsiz={unlimited} (enterprise saqlanishi kutiladi)")
    else:
        report(f"B-{name.split(' ')[0]}", changed, f"{name}: oldin enterprise/muddatsiz -> keyin plan={plan}, muddatsiz={unlimited}")

# ----------------------------------------------------------------- C
print("\n== C. Kechagi bron bugun qaytarilganda ==")
uid = BASE + 300
mk_user(uid, plan_type="free", ai_requests_today=0, last_limit_reset=None, ai_credits=0)
r1 = db.reserve_ai_request(uid, "other", 1)
q("UPDATE users SET last_limit_reset = CURRENT_DATE - 1 WHERE user_id = %s", (uid,))  # "yarim tundan oldin" holati
q("UPDATE ai_reservations SET created_at = created_at - INTERVAL '1 day' WHERE id = %s", (r1.get("reservation_id"),))
r2 = db.reserve_ai_request(uid, "other", 1)  # YANGI kun: hisoblagich nollanadi, bugungi 1-so'rov
today_before = q("SELECT ai_requests_today FROM users WHERE user_id = %s", (uid,))[0][0]
db.refund_ai_request(uid, r1.get("reservation_id"))  # KECHAGI bron qaytariladi
today_after = q("SELECT ai_requests_today FROM users WHERE user_id = %s", (uid,))[0][0]
report("C-yarim-tun", today_after < today_before,
       f"bugungi hisoblagich: refunddan oldin={today_before}, keyin={today_after} "
       f"(bugungi bron hali faol; kutilgan: o'zgarmaslik). source1={r1.get('source')}, source2={r2.get('source')}")

cleanup()
db.close_pool()
print(f"\n TAKRORLANGAN: {len(reproduced)} {reproduced}")
sys.exit(1 if (STRICT and reproduced) else 0)
