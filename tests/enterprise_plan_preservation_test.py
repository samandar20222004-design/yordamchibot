#!/usr/bin/env python3
"""Enterprise (muddatsiz) tarif to'lov/obuna/promo orqali PRO ga TUSHIB KETMASLIGI (real PostgreSQL).

Mavjud qoida (kod dalili): `users_repository.sync_stars_subscription` — "unlimited enterprise and manually
granted plans (NULL expiry) remain untouched". To'lov yo'llari (Stars/karta, admin `activate/extend`, Payme,
promo) endi shu qoidaga mos:
  * enterprise + muddatsiz (NULL)   -> o'zgarmaydi (tarif ham, muddat ham);
  * enterprise + muddatli           -> tarif saqlanadi, to'langan kunlar muddatga QO'SHILADI;
  * pro / free                      -> avvalgidek (pro, max(muddat, hozir) + kunlar).
Payme qaytarish (revoke) muddatsiz enterprise'ga tegmaydi.

Faqat SINOV bazasi: INTEGRITY_/P0_/STEP5_TEST_DATABASE_URL | MINIAPP_TEST_DATABASE_URL; URL yo'q bo'lsa SKIP.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_enterprise")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_bot"))

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== Enterprise saqlanishi ==")
# 1) Statik: barcha 'plan beruvchi' SQL joylarida qoida bor (runtime'da ishga tushirilmaydigan promo/karta cheki ham)
GUARD = "plan_type = 'enterprise'"
for rel in ("services/payment_service.py", "services/subscription_service.py", "services/promo_service.py",
            "repositories/payme_repository.py"):
    src = (ROOT / "telegram_bot" / rel).read_text(encoding="utf-8")
    src = re.sub(r'"\s*\n\s*"', "", src)  # qo'shni satr literallarini birlashtirish (SQL bo'laklari)
    grants = re.findall(r"UPDATE users SET[^;]*?GREATEST\(\s*COALESCE\(subscription_expires_at", src, flags=re.S)
    guarded = [g for g in grants if GUARD in g]
    # Yagona qoida (services/plan_sql.py) ishlatilsa — himoya o'sha yerda (quyida tekshiriladi).
    via_helper = len(re.findall(r"grant_plan_case\(", src))
    check(f"{rel}: har bir PRO berish SQL'ida enterprise qoidasi bor ({len(guarded)}+{via_helper} helper/{len(grants) + via_helper})",
          (len(grants) + via_helper) >= 1 and len(guarded) == len(grants))

plan_sql_src = (ROOT / "telegram_bot" / "services" / "plan_sql.py").read_text(encoding="utf-8")
check("plan_sql.py: tarif va muddat ifodalarida muddatsiz enterprise himoyasi bor",
      plan_sql_src.count(GUARD) >= 2 and "THEN plan_type" in plan_sql_src and "THEN NULL" in plan_sql_src)
check("plan_sql.py: faol ultra PRO xaridida pasaymaydi", "WHEN plan_type = 'ultra' THEN plan_type" in plan_sql_src)

if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q — runtime qismi o'tkazilmadi")
    skipped += 1
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
    sys.exit(0 if failed == 0 else 1)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

from repositories.payme_repository import PostgresPaymeUnitOfWork  # noqa: E402
from services.payment_service import PaymentService  # noqa: E402
from services.subscription_service import SubscriptionService  # noqa: E402

BASE = 9_400_000
IDS = list(range(BASE, BASE + 100))


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
      f"VALUES (%s, %s, %s, {expires_sql})", (uid, f"p{uid}", plan))  # nosec B608 — ichki literal


def state(uid):
    row = q("SELECT plan_type, subscription_expires_at IS NULL, "
            "ROUND(EXTRACT(EPOCH FROM (subscription_expires_at - NOW())) / 86400.0) "
            "FROM users WHERE user_id = %s", (uid,))[0]
    return row[0], bool(row[1]), (None if row[2] is None else int(row[2]))


def payme(uid):
    with db.db_cursor(commit=True) as cur:
        return PostgresPaymeUnitOfWork(cur).grant_subscription(uid, 30)


def payme_revoke(uid):
    with db.db_cursor(commit=True) as cur:
        PostgresPaymeUnitOfWork(cur).revoke_subscription(uid, 30)


paths = {
    "Stars/karta (process_stars_payment)": lambda uid: PaymentService.process_stars_payment(
        uid, f"ent-charge-{uid}", 0, "legacy", plan="pro", duration_days=30),
    "admin activate": lambda uid: SubscriptionService.activate(uid, "pro", 30),
    "Payme grant": payme,
}
cases = [
    ("enterprise muddatsiz", "enterprise", "NULL", ("enterprise", True, None)),
    ("enterprise muddatli (+10 kun)", "enterprise", "NOW() + interval '10 days'", ("enterprise", False, 40)),
    ("pro muddatli (+10 kun)", "pro", "NOW() + interval '10 days'", ("pro", False, 40)),
    ("free", "free", "NULL", ("pro", False, 30)),
]
cleanup()
try:
    uid = BASE
    for pname, fn in paths.items():
        for cname, plan, exp, expected in cases:
            uid += 1
            mk(uid, plan, exp)
            fn(uid)
            got = state(uid)
            ok = got[0] == expected[0] and got[1] == expected[1] and (expected[2] is None or abs(got[2] - expected[2]) <= 1)
            check(f"{pname} | {cname}: {got} (kutilgan {expected})", ok)
    # extend: faqat muddat
    uid += 1
    mk(uid, "enterprise", "NULL")
    SubscriptionService.extend(uid, 30)
    check("extend | enterprise muddatsiz: o'zgarmaydi", state(uid) == ("enterprise", True, None), str(state(uid)))
    uid += 1
    mk(uid, "pro", "NOW() + interval '10 days'")
    SubscriptionService.extend(uid, 30)
    got = state(uid)
    check("extend | pro: +30 kun", got[0] == "pro" and abs(got[2] - 40) <= 1, str(got))
    # Payme qaytarish
    uid += 1
    mk(uid, "enterprise", "NULL")
    payme_revoke(uid)
    check("Payme revoke | enterprise muddatsiz: tegilmaydi (free ga tushmaydi)", state(uid) == ("enterprise", True, None), str(state(uid)))
    uid += 1
    mk(uid, "pro", "NOW() + interval '40 days'")
    payme_revoke(uid)
    got = state(uid)
    check("Payme revoke | pro (+40 kun): 30 kun ayriladi, pro qoladi", got[0] == "pro" and abs(got[2] - 10) <= 1, str(got))
    uid += 1
    mk(uid, "pro", "NOW() + interval '10 days'")
    payme_revoke(uid)
    check("Payme revoke | pro (+10 kun): muddat tugaydi -> free (avvalgi xulq saqlangan)", state(uid)[0] == "free", str(state(uid)))
    # AUDIT (P-3): muddatsiz PRO (admin cheksiz bergan) Payme qaytarishida free ga tushmasligi kerak
    uid += 1
    mk(uid, "pro", "NULL")
    payme_revoke(uid)
    check("Payme revoke | pro MUDDATSIZ (admin bergan): tegilmaydi (free ga tushmaydi)", state(uid) == ("pro", True, None), str(state(uid)))
    uid += 1
    mk(uid, "free", "NULL")
    payme_revoke(uid)
    check("Payme revoke | free: o'zgarmaydi", state(uid) == ("free", True, None), str(state(uid)))
finally:
    cleanup()
    db.close_pool()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(0 if failed == 0 else 1)
