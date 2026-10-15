#!/usr/bin/env python3
"""FREE / PRO / ULTRA tariflari (4 muddat: 1/3/6 oy, 1 yil): narx, limit, to'lov, tushish va eski PRO himoyasi (real PostgreSQL).

* katalog (narx so'mda, Stars, kunlar) egasi belgilagan qiymatlar bilan; 6 oylik = 180 kun;
* limitlar tarif bo'yicha (kanal / kunlik AI / navbat) — atomik tekshiruvlar bilan; muddati o'tgan ULTRA -> FREE;
* Stars/karta cheki/Payme/admin berishi: ULTRA ULTRA beradi; faol ULTRA PRO xaridida PASAYMAYDI; PRO -> ULTRA ko'tariladi, muddat qo'shiladi;
* muddatsiz enterprise o'zgarmaydi; Stars refund ULTRA kunlarini ayiradi;
* tarif yangilanishidan OLDIN to'langan PRO muddati eski limitlarda qoladi (bir martalik migratsiya, yangi xaridorlarga tegmaydi).
"""
from __future__ import annotations

import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_tiers")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
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


import config  # noqa: E402

print("== Tarif katalogi ==")
EXPECT = {  # kalit: (tarif, kun, so'm, Stars)
    "1m": ("pro", 30, 19000, 80), "3m": ("pro", 90, 49000, 205), "6m": ("pro", 180, 89000, 375), "1y": ("pro", 365, 159000, 665),
    "u1m": ("ultra", 30, 39000, 165), "u3m": ("ultra", 90, 99000, 415), "u6m": ("ultra", 180, 189000, 790), "u1y": ("ultra", 365, 349000, 1460),
}
for key, (tier, days, uzs, stars) in EXPECT.items():
    c = config.TARIFF_CATALOG[key]
    check(f"{key}: {tier}, {days} kun, {uzs} so'm, {stars} Stars", (c["tier"], c["days"], c["uzs"], c["stars"]) == (tier, days, uzs, stars), str(c))
check("6 oylik = 180 kun (PRO va ULTRA)", config.TARIFF_CATALOG["6m"]["days"] == 180 == config.TARIFF_CATALOG["u6m"]["days"])
check("PRO eski kalitlar ('1m','3m','1y') saqlangan; ULTRA 'u' prefiksi", tuple(config.tariff_keys_for("pro")) == ("1m", "3m", "6m", "1y")
      and tuple(config.tariff_keys_for("ultra")) == ("u1m", "u3m", "u6m", "u1y"))
check("tier_of_key / key_for_days", config.tier_of_key("u6m") == "ultra" and config.tier_of_key("3m") == "pro"
      and config.key_for_days("ultra", 180) == "u6m" and config.key_for_days("pro", 365) == "1y")
check("limitlar: free 3/5/5, pro 10/40/100, ultra 30/100/500",
      [tuple(config.TIER_LIMITS[t][k] for k in ("max_channels", "daily_ai_requests", "queued_posts")) for t in ("free", "pro", "ultra")]
      == [(3, 5, 5), (10, 40, 100), (30, 100, 500)])
from services import voice_schedule_quota as vq  # noqa: E402
check("ovozli rejalash: free butun umr 1; PRO 24 soatda 20; ULTRA/enterprise 100",
      vq.limits_for("free")[:2] == ("lifetime", 1) and vq.limits_for("pro")[:2] == ("day", 20)
      and vq.limits_for("ultra")[:2] == ("day", 100) and vq.limits_for("enterprise")[1] == 100 and vq.limits_for(True)[1] == 20 and vq.limits_for(False)[1] == 1)
from services.ai import budget  # noqa: E402
check("AI byudjeti: ULTRA > PRO > FREE (kunlik token va USD)",
      budget.tier_budget("ultra").daily_tokens > budget.tier_budget("pro").daily_tokens > budget.tier_budget("free").daily_tokens
      and budget.tier_budget("ultra").monthly_usd > budget.tier_budget("pro").monthly_usd > budget.tier_budget("free").monthly_usd)
from services.plan_sql import grant_plan_case  # noqa: E402
try:
    grant_plan_case("pro'; DROP TABLE users; --")
    check("plan_sql: noma'lum tarif nomi rad etiladi (SQL inyeksiyasi yo'q)", False)
except ValueError:
    check("plan_sql: noma'lum tarif nomi rad etiladi (SQL inyeksiyasi yo'q)", True)

# Mini App
from miniapp_api.service import resolve_plan, tier_catalog  # noqa: E402
now = datetime.now(timezone.utc)
acct = {"plan_type": "ultra", "subscription_expires_at": now + timedelta(days=5), "db_now": now}
p = resolve_plan(acct)
check("Mini App: ULTRA -> type=ultra, is_pro, 30/100/500", p["type"] == "ultra" and p["is_pro"] and (p["limits"]["max_channels"], p["limits"]["daily_ai_requests"], p["limits"]["queued_posts"]) == (30, 100, 500), str(p))
p = resolve_plan({"plan_type": "pro", "subscription_expires_at": now + timedelta(days=5), "db_now": now})
check("Mini App: yangi PRO -> 10/40/100", (p["limits"]["max_channels"], p["limits"]["daily_ai_requests"]) == (10, 40), str(p))
p = resolve_plan({"plan_type": "pro", "subscription_expires_at": now + timedelta(days=5), "db_now": now, "pro_legacy_until": now + timedelta(days=3)})
check("Mini App: eski PRO (legacy muddati faol) -> eski limitlar 999", p["limits"]["max_channels"] == 999, str(p))
p = resolve_plan({"plan_type": "pro", "subscription_expires_at": now + timedelta(days=5), "db_now": now, "pro_legacy_until": now - timedelta(days=1)})
check("Mini App: legacy muddati o'tgach (yangi to'lov) -> 10/40", p["limits"]["max_channels"] == 10, str(p))
p = resolve_plan({"plan_type": "ultra", "subscription_expires_at": now - timedelta(days=1), "db_now": now})
check("Mini App: muddati o'tgan ULTRA -> free", p["type"] == "free" and not p["is_pro"] and p["limits"]["max_channels"] == 3, str(p))
tc = tier_catalog()
check("Mini App /me tiers: limitlar va 1 oylik narx config'dan", tc["pro"]["price_from_uzs"] == 19000 and tc["ultra"]["price_from_uzs"] == 39000
      and tc["ultra"]["limits"]["queued_posts"] == 500)

if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q (DB qismi)")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=1")
    sys.exit(0 if failed == 0 else 1)

import database as db  # noqa: E402
from services.payment_service import PaymentService  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

B = 9_600_000_000
FREE, PRO, ULTRA, LEG, ENT, EXPU, SUBS, RCPT, PAYME, REFD = (B + i for i in range(1, 11))
UP, DOWN = B + 11, B + 12
USERS = (FREE, PRO, ULTRA, LEG, ENT, EXPU, SUBS, RCPT, PAYME, REFD, UP, DOWN)


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def user(uid):
    return q("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s", (uid,))[0]


def days_left(uid):
    return (q("SELECT subscription_expires_at - NOW() FROM users WHERE user_id = %s", (uid,))[0][0]).total_seconds() / 86400


def cleanup():
    q("DELETE FROM payment_receipts WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM payments WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM channels WHERE user_id = ANY(%s)", (list(USERS),))
    q("DELETE FROM users WHERE user_id = ANY(%s)", (list(USERS),))


def seed(uid, plan, expires_days=None, legacy_days=None):
    exp = None if expires_days is None else now + timedelta(days=expires_days)
    leg = None if legacy_days is None else now + timedelta(days=legacy_days)
    q("INSERT INTO users (user_id, username, plan_type, subscription_expires_at, pro_legacy_until) VALUES (%s, %s, %s, %s, %s)",
      (uid, f"t{uid}", plan, exp, leg))


def fill(uid, channels=0, posts=0):
    for i in range(channels):
        q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'T', TRUE)", (uid, f"-100{uid}{i}"))
    for i in range(posts):
        q("INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) VALUES (%s, %s, 'text', %s, %s, 'pending')",
          (uid, "-1009600000001", f"p{i}", now + timedelta(days=1 + i)))


cleanup()
try:
    print("\n== Limitlar tarif bo'yicha (haqiqiy tekshiruvlar) ==")
    seed(FREE, "free"); seed(PRO, "pro", 10); seed(ULTRA, "ultra", 10); seed(LEG, "pro", 10, legacy_days=10); seed(ENT, "enterprise", None)
    seed(EXPU, "ultra", -1)
    for uid, n_ch in ((FREE, 3), (PRO, 10), (ULTRA, 30), (LEG, 30), (ENT, 40), (EXPU, 5)):
        fill(uid, channels=n_ch)
    ok, cur_n, mx = db.check_channel_limit(FREE)
    check("FREE: 3 kanal bor -> to'ldi (False, 3, 3)", (ok, cur_n, mx) == (False, 3, 3), str((ok, cur_n, mx)))
    ok, cur_n, mx = db.check_channel_limit(PRO)
    check("PRO: 10 kanal bor -> to'ldi (False, 10, 10)", (ok, cur_n, mx) == (False, 10, 10), str((ok, cur_n, mx)))
    ok, cur_n, mx = db.check_channel_limit(ULTRA)
    check("ULTRA: 30 kanal bor -> to'ldi (False, 30, 30)", (ok, cur_n, mx) == (False, 30, 30), str((ok, cur_n, mx)))
    ok, cur_n, mx = db.check_channel_limit(LEG)
    check("ESKI PRO (to'langan muddat): 30 kanal bor, hali limit yo'q (True, 30, 999)", (ok, cur_n, mx) == (True, 30, 999), str((ok, cur_n, mx)))
    ok, cur_n, mx = db.check_channel_limit(ENT)
    check("enterprise: cheksiz (True, 40, 999)", (ok, cur_n, mx) == (True, 40, 999), str((ok, cur_n, mx)))
    ok, cur_n, mx = db.check_channel_limit(EXPU)
    check("muddati o'tgan ULTRA: FREE limiti (5 kanal >= 3 -> False)", (ok, mx) == (False, 3), str((ok, cur_n, mx)))
    check("muddati o'tgan ULTRA lazy ravishda 'free' qilindi", user(EXPU)[0] == "free")

    # kunlik AI (atomik bron)
    q("UPDATE users SET ai_requests_today = 39 WHERE user_id = %s", (PRO,))
    q("UPDATE users SET ai_requests_today = 99 WHERE user_id = %s", (ULTRA,))
    check("PRO: 40-chi AI so'rov o'tadi, 41-chisi rad (40/kun)", db.check_ai_limit(PRO)[0] is True and db.check_ai_limit(PRO)[0] is False)
    check("ULTRA: 100-chi AI so'rov o'tadi, 101-chisi rad (100/kun)", db.check_ai_limit(ULTRA)[0] is True and db.check_ai_limit(ULTRA)[0] is False)
    q("UPDATE users SET ai_requests_today = 500 WHERE user_id = %s", (LEG,))
    check("ESKI PRO: AI limiti 999 (500 dan keyin ham o'tadi)", db.check_ai_limit(LEG)[0] is True)

    # navbat
    q("UPDATE channels SET channel_id = '-1009600000001' WHERE user_id = %s AND channel_id = %s", (FREE, f"-100{FREE}0"))
    for uid, posts, expect in ((PRO, 100, (False, 100, 100)), (ULTRA, 100, (True, 100, 500)), (LEG, 100, (True, 100, 999))):
        fill(uid, posts=posts)
        check(f"navbat {uid - B}: {posts} post -> {expect}", db.check_queue_limit(uid) == expect, str(db.check_queue_limit(uid)))
    check("db.get_plan_tier: free/pro/ultra/enterprise/muddati o'tgan -> free",
          [db.get_plan_tier(u) for u in (FREE, PRO, ULTRA, ENT, EXPU)] == ["free", "pro", "ultra", "enterprise", "free"])

    print("\n== To'lov: tarif berish qoidalari ==")
    seed(SUBS, "free"); seed(UP, "pro", 10); seed(DOWN, "ultra", 10)

    def stars(uid, key, charge):
        info = config.TARIFF_CATALOG[key]
        return PaymentService.process_stars_payment(uid, charge, info["stars"], f"sub_{info['stars_key']}_{uid}", "pro", info["days"])

    for key in ("u1m", "u3m", "u6m", "u1y"):
        uid = SUBS
        q("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL WHERE user_id = %s", (uid,))
        r = stars(uid, key, f"tier-{key}-{uid}")
        check(f"Stars {key}: ok, plan_type=ultra, muddat {config.TARIFF_CATALOG[key]['days']} kun", r.get("ok") and user(uid)[0] == "ultra"
              and abs(days_left(uid) - config.TARIFF_CATALOG[key]["days"]) < 0.1, f"{r} {user(uid)}")
    for key in ("1m", "3m", "6m", "1y"):
        q("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL WHERE user_id = %s", (SUBS,))
        r = stars(SUBS, key, f"tier-{key}-{SUBS}")
        check(f"Stars {key}: ok, plan_type=pro, muddat {config.TARIFF_CATALOG[key]['days']} kun", r.get("ok") and user(SUBS)[0] == "pro"
              and abs(days_left(SUBS) - config.TARIFF_CATALOG[key]["days"]) < 0.1, f"{r} {user(SUBS)}")
    r = PaymentService.process_stars_payment(SUBS, "tier-cheat", config.TARIFF_CATALOG["1m"]["stars"], f"sub_stars_u1y_{SUBS}", "pro", 365)
    check("ULTRA 1 yillik payload PRO 1 oylik narxda -> RAD (summa tarifga mos emas)", not r.get("ok"), str(r))
    r = PaymentService.process_stars_payment(SUBS, "tier-ok-dup", 80, f"sub_stars_1m_{SUBS}", "pro", 30)
    r2 = PaymentService.process_stars_payment(SUBS, "tier-ok-dup", 80, f"sub_stars_1m_{SUBS}", "pro", 30)
    check("takroriy charge: ikkinchisi duplicate (kun qo'shilmaydi)", r.get("ok") and r2.get("duplicate") is True, f"{r} {r2}")

    before = days_left(UP)
    r = stars(UP, "u1m", "tier-up-1")
    check("PRO -> ULTRA xaridi: tarif ULTRA, qolgan PRO kunlari yo'qolmaydi (10 + 30 kun)",
          user(UP)[0] == "ultra" and abs(days_left(UP) - (before + 30)) < 0.1, f"{user(UP)} {days_left(UP)}")
    before = days_left(DOWN)
    r = stars(DOWN, "1m", "tier-down-1")
    check("faol ULTRA PRO xarid qilsa tarif PASAYMAYDI, muddat qo'shiladi (10 + 30 kun)",
          user(DOWN)[0] == "ultra" and abs(days_left(DOWN) - (before + 30)) < 0.1, f"{user(DOWN)} {days_left(DOWN)}")
    q("UPDATE users SET plan_type = 'enterprise', subscription_expires_at = NULL WHERE user_id = %s", (SUBS,))
    stars(SUBS, "u1y", "tier-ent-1")
    check("muddatsiz enterprise xarid bilan o'zgarmaydi", user(SUBS) == ("enterprise", None), str(user(SUBS)))

    # admin berishi
    from services.subscription_service import SubscriptionService
    q("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL WHERE user_id = %s", (SUBS,))
    check("admin: ULTRA 30 kun beradi", SubscriptionService.activate(SUBS, "ultra", 30) and user(SUBS)[0] == "ultra")
    SubscriptionService.activate(SUBS, "pro", 30)
    check("admin: ULTRA ustiga PRO berish tarifni tushirmaydi, muddat qo'shiladi", user(SUBS)[0] == "ultra" and abs(days_left(SUBS) - 60) < 0.1, f"{user(SUBS)} {days_left(SUBS)}")
    check("set_user_plan('ultra') qabul qilinadi", db.set_user_plan(SUBS, "ultra", 5) is True)

    # karta cheki
    seed(RCPT, "free")
    rid = db.save_payment_receipt(RCPT, "photo", "FID", "", "u", "N", "uz", 90, amount_uzs=99000, file_unique_id="TIER-1", plan_key="u3m")
    res = db.approve_payment_receipt(rid, 1)
    check("karta cheki (u3m): ULTRA, 90 kun, javobda tier=ultra", res.get("ok") and res.get("tier") == "ultra" and user(RCPT)[0] == "ultra"
          and abs(days_left(RCPT) - 90) < 0.1, f"{res} {user(RCPT)}")
    rid2 = db.save_payment_receipt(RCPT, "photo", "FID2", "", "u", "N", "uz", 30, amount_uzs=19000, file_unique_id="TIER-2")
    res2 = db.approve_payment_receipt(rid2, 1)
    check("eski chek (plan_key yo'q) = PRO; ULTRA'ni pasaytirmaydi", res2.get("ok") and res2.get("tier") == "pro" and user(RCPT)[0] == "ultra", f"{res2} {user(RCPT)}")

    # Payme
    seed(PAYME, "free")
    from repositories.payme_repository import PostgresPaymeUnitOfWork
    with db.db_cursor(commit=True) as cur:
        uow = PostgresPaymeUnitOfWork(cur)
        okg = uow.grant_subscription(PAYME, 180, "ultra")
    check("Payme: ULTRA 180 kun", okg and user(PAYME)[0] == "ultra" and abs(days_left(PAYME) - 180) < 0.1, str(user(PAYME)))

    # Stars refund ULTRA
    seed(REFD, "free")
    stars(REFD, "u1m", "tier-refund-1")
    r = db.refund_stars_payment("tier-refund-1")
    check("refund (ULTRA 1 oy): kunlar ayrildi, qolgan muddat <= 0 -> free", r["result"] == "revoked" and r["days"] == 30 and user(REFD)[0] == "free", f"{r} {user(REFD)}")

    print("\n== Eski PRO himoyasi (bir martalik migratsiya) ==")
    q("DELETE FROM system_settings WHERE key = 'tariff_v2_legacy_marked'")
    seed(LEG + 100, "pro", 20)
    seed(LEG + 101, "pro", None)
    seed(LEG + 102, "ultra", 20)
    USERS_EXTRA = (LEG + 100, LEG + 101, LEG + 102)
    db.init_db()
    rows = {uid: q("SELECT pro_legacy_until FROM users WHERE user_id = %s", (uid,))[0][0] for uid in USERS_EXTRA}
    check("migratsiya: faol PRO ga legacy muddati = to'langan muddat tugashi", rows[LEG + 100] is not None and abs((rows[LEG + 100] - (now + timedelta(days=20))).total_seconds()) < 5, str(rows))
    check("migratsiya: muddatsiz PRO (admin bergan) cheksiz legacy", rows[LEG + 101] is not None and rows[LEG + 101].year == 9999, str(rows))
    check("migratsiya: ULTRA ga tegilmaydi", rows[LEG + 102] is None, str(rows))
    ok, _c, mx = db.check_channel_limit(LEG + 100)
    check("migratsiya: eski PRO limiti 999", mx == 999, str(mx))
    seed(LEG + 103, "pro", 20)
    db.init_db()
    check("keyingi startup'da YANGI PRO xaridorga legacy qo'yilmaydi (bir martalik)", q("SELECT pro_legacy_until FROM users WHERE user_id = %s", (LEG + 103,))[0][0] is None)
    check("yangi PRO xaridor: limit 10 kanal", db.check_channel_limit(LEG + 103)[2] == 10)
    q("DELETE FROM users WHERE user_id >= %s AND user_id <= %s", (LEG + 100, LEG + 103))
finally:
    cleanup()
    q("DELETE FROM users WHERE user_id >= %s AND user_id <= %s", (B + 100, B + 103))

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(0 if failed == 0 else 1)
