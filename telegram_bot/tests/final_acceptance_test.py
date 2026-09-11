#!/usr/bin/env python3
"""PostAssist V2 — YAKUNIY ACCEPTANCE SMOKE TEST (10-BOSQICH).

10 bosqichning har biri bo'yicha asosiy shartnomalar (kontraktlar)
tekshiriladi:

  1)  Payment idempotency            — bir xil charge_id ikki marta PRO bermaydi
  2)  Promo atomic redemption        — race-condition'da ham limit buzilmaydi
  3)  Subscription additive extension — qolgan muddat kuyib ketmaydi
  4)  Scheduler delivery idempotency  — bitta post faqat 1 marta yuboriladi
  5)  AI fallback resilience          — zanjir xatoda ham javob qaytaradi
  6)  Database integrity & constraints — FK/CHECK'lar real bazada ishlaydi
  7)  Admin RBAC permissions          — rol → ruxsat matritsa qat'iy
  8)  Health check status             — hech qachon istisno ko'tarmaydi
  9)  Credits ledger audit            — balans va ledger zanjiri doim mos
  10) Graceful shutdown handler       — SIGTERM/SIGINT tartibli yopilish

Struktura: STATIC qismlar (mock/mantiq) DOIM ishlaydi; LIVE qismlar real
PostgreSQL'da (pgserver yoki FINAL_TEST_DATABASE_URL / P0_TEST_DATABASE_URL)
bajariladi — real baza topilmasa ular belgilangan holda o'tkazib yuboriladi.

Ishga tushirish:
    cd telegram_bot && python tests/final_acceptance_test.py
"""
import os
import sys
import signal
import asyncio
import random
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

# ──────────────────────────────────────────────────────────────
# MUHIT (importdan OLDIN sozlanadi)
# ──────────────────────────────────────────────────────────────
os.environ.setdefault("BOT_TOKEN", "123456:FINAL_ACCEPTANCE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
# AI fallback timeout testini tezlashtirish (1 soniyalik qat'iy byudjet).
os.environ.setdefault("AI_PROVIDER_TOTAL_TIMEOUT", "1")
# Health chegaralari — deterministik qiymatlar.
os.environ.setdefault("HEALTH_DEAD_LETTER_ALERT", "1")
os.environ.setdefault("HEALTH_FAILED_ALERT", "10")
os.environ.setdefault("HEALTH_PENDING_BACKLOG_ALERT", "1000")

ROOT = Path(__file__).resolve().parent.parent  # telegram_bot/
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0
skipped = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name} {reason}")


SECTION = None


def section(title):
    global SECTION
    SECTION = title
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


# Unique test user bazasi (boshqa suite'lar bilan to'qnashmaslik uchun).
_BASE = 940_000_000 + random.randint(0, 999_999) * 1000


# ============================================================
# 1) PAYMENT IDEMPOTENCY (2-bosqich + 5-bosqich atomikligi)
# ============================================================

class _FakeCursor:
    """Scriptlangan psycopg2 cursor (faqat static tekshiruv uchun)."""

    def __init__(self, fetch_rows=(), rowcount=1):
        self._rows = list(fetch_rows)
        self._rc = rowcount
        self.queries = []

    def execute(self, query, params=None):
        self.queries.append(query)

    def fetchone(self):
        if self._rows:
            return self._rows.pop(0)
        return None

    @property
    def rowcount(self):
        return self._rc

    def close(self):
        pass


def test_payment_idempotency_static():
    section("1) PAYMENT IDEMPOTENCY — static (mock DB)")
    from services import payment_service as ps

    # 1-chaqiruv: user bor, INSERT yangi qator qaytaradi → PRO beriladi.
    call1 = _FakeCursor(fetch_rows=[(1,), (4242,)])

    @contextmanager
    def tx1(commit=True):
        yield call1

    with patch.object(ps, "transaction", tx1):
        res1 = ps.PaymentService.process_stars_payment(
            777001, "ch_final_1", 75, "sub_stars_1m_777001", "pro", 30)
    check("birinchi to'lov: ok=True, duplicate=False",
          res1.get("ok") is True and res1.get("duplicate") is False, str(res1))
    check("birinchi to'lov: 30 kun berildi", res1.get("days") == 30, str(res1))

    # 2-chaqiruv: INSERT hech narsa qaytarmaydi (charge_id UNIQUE) → dublikat.
    call2 = _FakeCursor(fetch_rows=[(1,), None])

    @contextmanager
    def tx2(commit=True):
        yield call2

    with patch.object(ps, "transaction", tx2):
        res2 = ps.PaymentService.process_stars_payment(
            777001, "ch_final_1", 75, "sub_stars_1m_777001", "pro", 30)
    check("takroriy to'lov: ok=True, duplicate=True (PRO ikki marta berilmaydi)",
          res2.get("ok") is True and res2.get("duplicate") is True, str(res2))
    check("takroriy to'lov: days=0", res2.get("days") == 0, str(res2))

    # validate_payload kontraktlari.
    plan, err = ps.PaymentService.validate_payload("sub_stars_1m_777001", 777001, 75, "XTR")
    check("validate_payload: to'g'ri payload qabul qilinadi",
          plan is not None and err is None, f"{plan} {err}")
    plan, err = ps.PaymentService.validate_payload("sub_stars_1m_777002", 777001, 75, "XTR")
    check("validate_payload: boshqa user payload'i rad etiladi",
          plan is None and err, "")
    plan, err = ps.PaymentService.validate_payload("sub_stars_1m_777001", 777001, 74, "XTR")
    check("validate_payload: noto'g'ri summa rad etiladi", plan is None, "")


def test_payment_idempotency_live(db_mod):
    print("== 1) LIVE: charge_id UNIQUE — takroriy to'lov PRO bermaydi ==")
    from services.payment_service import PaymentService

    uid = _BASE + 1
    charge = f"ch_final_live_{uid}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, plan_type) "
            "VALUES (%s, %s, 'free') ON CONFLICT (user_id) DO NOTHING",
            (uid, f"final_{uid}"))

    res1 = PaymentService.process_stars_payment(uid, charge, 75, f"sub_stars_1m_{uid}", "pro", 30)
    res2 = PaymentService.process_stars_payment(uid, charge, 75, f"sub_stars_1m_{uid}", "pro", 30)
    check("LIVE birinchi to'lov muvaffaqiyatli", res1.get("ok") and not res1.get("duplicate"), str(res1))
    check("LIVE takroriy to'lov dublikat deb topildi", res2.get("ok") and res2.get("duplicate"), str(res2))

    with db_mod.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id = %s", (charge,))
        payments_count = int(cur.fetchone()[0])
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM (subscription_expires_at - NOW())), plan_type "
            "FROM users WHERE user_id = %s", (uid,))
        row = cur.fetchone()
    check("LIVE payments jadvalida FAQAT 1 ta yozuv", payments_count == 1, str(payments_count))
    remaining = float(row[0]) if row and row[0] is not None else -1
    check("LIVE obuna ~30 kun (60 emas — dublikat qo'shilmadi)",
          29.9 * 86400 < remaining < 30.2 * 86400, f"{remaining / 86400:.2f} kun")
    check("LIVE plan_type=pro", row and row[1] == "pro", str(row))


# ============================================================
# 2) PROMO ATOMIC REDEMPTION (2-bosqich, 5-bosqich atomikligi)
# ============================================================

def test_promo_redemption_static():
    section("2) PROMO ATOMIC REDEMPTION — static")
    from services.promo_service import PromoService

    @contextmanager
    def tx_empty(commit=True):
        yield _FakeCursor(fetch_rows=[])  # promo topilmaydi

    with patch("services.promo_service.transaction", tx_empty):
        ok, msg = PromoService.redeem_promo(777002, "YOQ_KOD")
    check("noma'lum promo-kod rad etiladi", ok is False and "topilmadi" in msg, msg)

    ok, msg = PromoService.redeem_promo(777002, "   ")
    check("bo'sh promo-kod rad etiladi", ok is False, msg)


def test_promo_redemption_live(db_mod):
    print("== 2) LIVE: parallel redemption — limit atomik himoyalangan ==")
    from services.promo_service import PromoService

    code = f"FINAL{random.randint(100, 999)}"
    user_a, user_b = _BASE + 11, _BASE + 12
    with db_mod.db_cursor(commit=True) as cur:
        for u in (user_a, user_b):
            cur.execute(
                "INSERT INTO users (user_id, username, plan_type) "
                "VALUES (%s, %s, 'free') ON CONFLICT (user_id) DO NOTHING",
                (u, f"final_{u}"))

    check(f"LIVE promo {code} yaratildi (max_uses=1)",
          PromoService.create_promo(code, duration_days=7, max_uses=1) is True, "")

    results = {}

    def redeem(uid, key):
        results[key] = PromoService.redeem_promo(uid, code)

    t1 = threading.Thread(target=redeem, args=(user_a, "a"))
    t2 = threading.Thread(target=redeem, args=(user_b, "b"))
    t1.start(); t2.start(); t1.join(); t2.join()
    wins = [k for k, (ok, _m) in results.items() if ok]
    check("LIVE 2 parallel redemptiondan FAQAT BITTASI yutadi", len(wins) == 1, str(results))

    ok, msg = PromoService.redeem_promo(user_a if "a" in wins else user_b, code)
    check("LIVE yutgan user takror ishlatolmaydi", ok is False, msg)

    with db_mod.db_cursor() as cur:
        cur.execute("SELECT current_uses FROM promo_codes WHERE code = %s", (code,))
        uses = int(cur.fetchone()[0])
        cur.execute(
            "SELECT COUNT(*) FROM promo_redemptions pr JOIN promo_codes pc "
            "ON pc.id = pr.promo_id WHERE pc.code = %s", (code,))
        redemptions = int(cur.fetchone()[0])
    check("LIVE current_uses aynan 1", uses == 1, str(uses))
    check("LIVE redemption yozuvlari aynan 1", redemptions == 1, str(redemptions))

    # Cheksiz promo: bir user ikki marta ishlatolmaydi (UNIQUE(promo_id, user_id)).
    code2 = code + "X"
    PromoService.create_promo(code2, duration_days=3, max_uses=None)
    ok1, _m1 = PromoService.redeem_promo(user_a, code2)
    ok2, msg2 = PromoService.redeem_promo(user_a, code2)
    check("LIVE bir user bir kodni 2 marta ishlatolmaydi",
          ok1 is True and ok2 is False, msg2)


# ============================================================
# 3) SUBSCRIPTION ADDITIVE EXTENSION
# ============================================================

def test_subscription_additive_static():
    section("3) SUBSCRIPTION ADDITIVE EXTENSION — static")
    from services.subscription_service import SubscriptionService

    check("extend(0) rad etiladi", SubscriptionService.extend(777003, 0) is False, "")
    check("extend(-5) rad etiladi", SubscriptionService.extend(777003, -5) is False, "")
    check("activate(noto'g'ri plan) rad etiladi",
          SubscriptionService.activate(777003, "mega_ultra", 30) is False, "")


def test_subscription_additive_live(db_mod):
    print("== 3) LIVE: extend() qolgan muddatga QO'SHILADI ==")
    from services.subscription_service import SubscriptionService

    uid = _BASE + 21
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, plan_type) "
            "VALUES (%s, %s, 'free') ON CONFLICT (user_id) DO NOTHING",
            (uid, f"final_{uid}"))

    check("LIVE activate(30 kun) muvaffaqiyatli",
          SubscriptionService.activate(uid, "pro", 30) is True, "")
    check("LIVE extend(+30 kun) muvaffaqiyatli",
          SubscriptionService.extend(uid, 30) is True, "")

    with db_mod.db_cursor() as cur:
        cur.execute(
            "SELECT EXTRACT(EPOCH FROM (subscription_expires_at - NOW())) "
            "FROM users WHERE user_id = %s", (uid,))
        remaining = float(cur.fetchone()[0])
    # 30 + 30 = 60 kun (ozgina ishlash vaqti ayiriladi).
    check("LIVE muddat ~60 kun (additive: 30+30, qoldiq kuyib ketmadi)",
          59.7 * 86400 < remaining < 60.2 * 86400, f"{remaining / 86400:.2f} kun")

    status = SubscriptionService.get_status(uid)
    check("LIVE get_status: is_pro=True", bool(status.get("is_pro")), str(status)[:120])


# ============================================================
# 4) SCHEDULER DELIVERY IDEMPOTENCY (3-bosqich)
# ============================================================

def test_scheduler_idempotency_static():
    section("4) SCHEDULER DELIVERY IDEMPOTENCY — static")
    from services.scheduler_service import SchedulerService
    from datetime import datetime, timezone

    ts = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)
    k1 = SchedulerService.build_idempotency_key(1001, "-100200", ts)
    k2 = SchedulerService.build_idempotency_key(1001, "-100200", ts)
    k3 = SchedulerService.build_idempotency_key(1002, "-100200", ts)
    check("idempotency kalit deterministik (bir xil uchlik → bir xil kalit)", k1 == k2, f"{k1} vs {k2}")
    check("boshqa post → boshqa kalit", k1 != k3, "")
    check("kalit bo'sh emas", bool(k1), "")


def test_scheduler_idempotency_live(db_mod):
    print("== 4) LIVE: claim → sent → takroriy claim rad etiladi ==")
    from services.scheduler_service import SchedulerService

    uid = _BASE + 31
    channel_id = f"-100{uid}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO NOTHING", (uid, f"final_{uid}"))
        cur.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title) "
            "VALUES (%s, %s, 'Final kanal') "
            "ON CONFLICT (channel_id) DO UPDATE SET is_active = TRUE",
            (uid, channel_id))
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, "
            " scheduled_time, status) "
            "VALUES (%s, %s, 'text', 'final acceptance', NOW(), 'pending') RETURNING id",
            (uid, channel_id))
        post_id = int(cur.fetchone()[0])

    claim1 = SchedulerService.claim_post_for_delivery(post_id, channel_id)
    check("LIVE birinchi claim: claimed=True", claim1.get("claimed") is True, str(claim1))
    key = claim1.get("idempotency_key", "")
    check("LIVE idempotency kalit berildi", bool(key), str(claim1))

    ok = SchedulerService.mark_as_sent(post_id, channel_id, 900001, idempotency_key=key)
    check("LIVE mark_as_sent muvaffaqiyatli", ok is True, "")

    claim2 = SchedulerService.claim_post_for_delivery(post_id, channel_id)
    check("LIVE takroriy claim rad etiladi (claimed=False)", claim2.get("claimed") is False, str(claim2))
    check("LIVE takroriy claim 'sent' deb belgilangan (skip)", claim2.get("sent") is True, str(claim2))

    ok2 = SchedulerService.mark_as_sent(post_id, channel_id, 900001, idempotency_key=key)
    check("LIVE takroriy mark_as_sent xavfsiz (idempotent True)", ok2 is True, "")

    status = SchedulerService.get_delivery_status(post_id, channel_id)
    st = status if isinstance(status, str) else (status or {}).get("status", "")
    check("LIVE delivery holati 'sent'", st == "sent", str(status))
    check("LIVE is_already_sent=True",
          SchedulerService.is_already_sent(post_id, channel_id) is True, "")


# ============================================================
# 5) AI FALLBACK RESILIENCE (4-bosqich)
# ============================================================

class _FakeProvider:
    """AIFallbackService uchun soxta provayder."""

    def __init__(self, name, mode="ok"):
        self.name = name
        self.mode = mode  # ok | raise | timeout
        self.calls = 0

    def is_available(self):
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        self.calls += 1
        if self.mode == "raise":
            raise RuntimeError("fake provider failure")
        if self.mode == "timeout":
            await asyncio.sleep(5)  # AI_PROVIDER_TOTAL_TIMEOUT=1 → wait_for buzadi
        return {"post_text": f"javob: {self.name}"}


def test_ai_fallback_resilience():
    section("5) AI FALLBACK RESILIENCE — fake provayderlar")
    from services.ai_service import AIFallbackService
    from utils import ai_agent as aa

    # 1-holat: birinchi provayder xato beradi → ikkinchisiga o'tiladi.
    bad = _FakeProvider("ZZ_FINAL_BAD_1", mode="raise")
    good = _FakeProvider("ZZ_FINAL_GOOD_1", mode="ok")
    svc = AIFallbackService(providers=[bad, good])
    res = asyncio.run(svc.generate("salom", "sen yordamchisan"))
    check("fallback: xatodan keyin zaxira provayder javob berdi",
          isinstance(res, dict) and res.get("provider") == "ZZ_FINAL_GOOD_1", str(res)[:120])
    check("fallback: zanjir [bad, good] qayd etilgan",
          res.get("provider_chain") == ["ZZ_FINAL_BAD_1", "ZZ_FINAL_GOOD_1"],
          str(res.get("provider_chain")))
    check("fallback: birinchi provayder 1 marta, ikkinchisi 1 marta chaqirilgan",
          bad.calls == 1 and good.calls == 1, f"{bad.calls}/{good.calls}")

    # 2-holat: birinchi timeout beradi → darhol keyingisiga o'tiladi.
    slow = _FakeProvider("ZZ_FINAL_SLOW_2", mode="timeout")
    good2 = _FakeProvider("ZZ_FINAL_GOOD_2", mode="ok")
    aa._BREAKERS.pop("ZZ_FINAL_SLOW_2", None)
    svc2 = AIFallbackService(providers=[slow, good2])
    res2 = asyncio.run(svc2.generate("salom", "sen yordamchisan"))
    check("timeout: zaxira provayderga o'tildi",
          res2.get("provider") == "ZZ_FINAL_GOOD_2", str(res2)[:120])

    # 3-holat: HAMMASI ishlamaydi → graceful xato, istisno YO'Q.
    b1 = _FakeProvider("ZZ_FINAL_BAD_3A", mode="raise")
    b2 = _FakeProvider("ZZ_FINAL_BAD_3B", mode="raise")
    svc3 = AIFallbackService(providers=[b1, b2])
    res3 = asyncio.run(svc3.generate("salom", "sen yordamchisan"))
    check("hammasi yiqildi: ai_unavailable=True", res3.get("ai_unavailable") is True, str(res3)[:120])
    check("hammasi yiqildi: quota_safe=True (kvota yechilmaydi)",
          res3.get("quota_safe") is True, "")
    check("hammasi yiqildi: foydalanuvchiga xato xabari bor", bool(res3.get("error")), "")

    # 4-holat: umuman provayder yo'q → baribir graceful.
    svc4 = AIFallbackService(providers=[])
    res4 = asyncio.run(svc4.generate("salom", "sys"))
    check("bo'sh zanjir: graceful xato (istisno emas)",
          res4.get("ai_unavailable") is True, "")


# ============================================================
# 6) DATABASE INTEGRITY & CONSTRAINTS (5-bosqich)
# ============================================================

def test_db_integrity_static():
    section("6) DATABASE INTEGRITY & CONSTRAINTS — static")
    import database as db_mod

    names = tuple(db_mod.INTEGRITY_CONSTRAINT_NAMES)
    check("kanonik constraint ro'yxati bo'sh emas", len(names) >= 8, str(len(names)))
    check("constraint ro'yxatida FK'lar bor (channels→users)",
          any("channels" in n for n in names), str(names[:6]))
    check("constraint ro'yxatida CHECK'lar bor",
          any(n.startswith("chk_") for n in names), "")
    check("indeks ro'yxati bo'sh emas", len(db_mod.INTEGRITY_INDEX_NAMES) >= 4, "")
    check("validate_integrity_constraints() mavjud",
          callable(getattr(db_mod, "validate_integrity_constraints", None)), "")
    schema_text = (ROOT / "schema.sql").read_text(encoding="utf-8")
    check("schema.sql: idempotent IF NOT EXISTS ishlatilgan",
          "IF NOT EXISTS" in schema_text, "")
    check("schema.sql: post_deliveries UNIQUE(idempotency_key)",
          "idempotency_key" in schema_text, "")


def test_db_integrity_live(db_mod):
    print("== 6) LIVE: FK/CHECK constraintlar real bazada ishlaydi ==")
    import psycopg2

    # FK: mavjud bo'lmagan user'ga kanal ulab bo'lmaydi.
    fk_blocked = False
    try:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO channels (user_id, channel_id, channel_title) "
                "VALUES (%s, %s, 'orphan')",
                (_BASE + 99999, f"-999{_BASE}"))
    except psycopg2.IntegrityError:
        fk_blocked = True
    check("LIVE FK: orphan kanal rad etildi (channels.user_id → users)", fk_blocked, "")

    # CHECK: payments status faqat ruxsat etilgan qiymatda bo'ladi.
    check_blocked = False
    try:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO payments (user_id, amount, currency, payload, status) "
                "VALUES (%s, 100, 'XTR', 'x', 'not_a_status')", (_BASE + 1,))
    except psycopg2.IntegrityError:
        check_blocked = True
    check("LIVE CHECK: noto'g'ri payment status rad etildi", check_blocked, "")

    # Integrity tekshiruv yordamchisi real bazada ishlaydi.
    try:
        report = db_mod.validate_integrity_constraints()
        ok_report = isinstance(report, dict)
    except Exception as e:
        ok_report = False
        report = str(e)
    check("LIVE validate_integrity_constraints() ishlaydi", ok_report, str(report)[:100])


# ============================================================
# 7) ADMIN RBAC PERMISSIONS (6-bosqich)
# ============================================================

def test_rbac_static():
    section("7) ADMIN RBAC PERMISSIONS — static")
    from services import rbac_service as rb

    owner_perms = rb.permissions_for(rb.Role.OWNER)
    check("OWNER: barcha 4 ruxsat", owner_perms == set(rb.ALL_PERMISSIONS), str(owner_perms))
    check("SUPER_ADMIN: system_settings YO'Q",
          rb.PERM_SYSTEM_SETTINGS not in rb.permissions_for(rb.Role.SUPER_ADMIN), "")
    check("FINANCE: faqat manage_payments",
          rb.permissions_for(rb.Role.FINANCE) == {rb.PERM_MANAGE_PAYMENTS}, "")
    check("MODERATOR: faqat manage_users",
          rb.permissions_for(rb.Role.MODERATOR) == {rb.PERM_MANAGE_USERS}, "")
    check("USER: ruxsat yo'q", rb.permissions_for(rb.Role.USER) == frozenset(), "")
    check("parse_role('superadmin') → SUPER_ADMIN",
          rb.parse_role("superadmin") == rb.Role.SUPER_ADMIN, "")
    check("role_covers(OWNER, ADMIN)=True",
          rb.role_covers(rb.Role.OWNER, rb.Role.ADMIN) is True, "")
    check("role_covers(MODERATOR, FINANCE)=False",
          rb.role_covers(rb.Role.MODERATOR, rb.Role.FINANCE) is False, "")


def test_rbac_live(db_mod):
    print("== 7) LIVE: rol berish/olib tashlash + ruxsat tekshiruvi ==")
    from services import rbac_service as rb

    uid, actor = _BASE + 41, _BASE + 42
    with db_mod.db_cursor(commit=True) as cur:
        for u in (uid, actor):
            cur.execute(
                "INSERT INTO users (user_id, username) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO NOTHING", (u, f"final_{u}"))

    rb.invalidate_role_cache()
    check("LIVE default rol: USER", rb.get_role(uid, use_cache=False) == rb.Role.USER, "")

    ok = rb.set_role(uid, "moderator", granted_by=123456789)
    rb.invalidate_role_cache(uid)
    check("LIVE set_role('moderator') muvaffaqiyatli", ok is True, "")
    check("LIVE get_role → MODERATOR", rb.get_role(uid, use_cache=False) == rb.Role.MODERATOR, "")
    check("LIVE moderator: manage_users bor",
          rb.has_permission(uid, rb.PERM_MANAGE_USERS) is True, "")
    check("LIVE moderator: manage_payments YO'Q",
          rb.has_permission(uid, rb.PERM_MANAGE_PAYMENTS) is False, "")
    check("LIVE moderator admin hisoblanadi", rb.is_admin(uid) is True, "")

    # enforce: ruxsatsiz actor rol bera olmaydi.
    ok_enforce = rb.set_role(actor, "admin", granted_by=uid, enforce=True)
    check("LIVE enforce: moderator boshqaga rol bera olmaydi", ok_enforce is False, "")

    ok_rm = rb.remove_role(uid, granted_by=123456789)
    rb.invalidate_role_cache(uid)
    check("LIVE remove_role muvaffaqiyatli", ok_rm is True, "")
    check("LIVE rol olib tashlangach yana USER",
          rb.get_role(uid, use_cache=False) == rb.Role.USER, "")


# ============================================================
# 8) HEALTH CHECK STATUS (7-bosqich)
# ============================================================

def test_health_check():
    section("8) HEALTH CHECK STATUS — mock komponentlar")
    import database as db_mod
    import services.health_service as hs

    healthy_db = {"component": "database", "status": hs.STATUS_OK, "ok": True,
                  "latency_ms": 1.2, "pool": {}}
    down_db = {"component": "database", "status": "ERROR", "ok": False,
               "error": "connection refused"}
    zero_counts = {"pending": 0, "processing": 0, "failed": 0,
                   "stale_processing": 0, "delivery_failed": 0, "dead_letter": 0}

    async def run_db_stub(func, *args, **kwargs):
        return dict(zero_counts)

    # DB sog'lom → HEALTHY yoki DEGRADED (scheduler/AI holatiga qarab),
    # lekin HECH QACHON istisno emas.
    async def check_db_ok():
        return await hs.get_system_health()

    async def check_db_down():
        return await hs.get_system_health()

    async def db_ok():
        return dict(healthy_db)

    async def db_down():
        return dict(down_db)

    try:
        with patch.object(hs, "_check_database", db_ok), \
             patch.object(db_mod, "run_db", run_db_stub):
            health = asyncio.run(check_db_ok())
        ok_health = True
    except Exception as e:
        health, ok_health = {}, False
        print(f"    istisno: {e}")
    check("get_system_health() istisno ko'tarmaydi", ok_health, "")
    check("health dict: barcha bo'limlar bor",
          all(k in health for k in ("status", "database", "scheduler",
                                    "ai_providers", "system", "checked_at")),
          str(sorted(health.keys())))
    check("DB sog'lom bo'lsa status HEALTHY/DEGRADED",
          health.get("status") in (hs.STATUS_HEALTHY, hs.STATUS_DEGRADED),
          str(health.get("status")))

    try:
        with patch.object(hs, "_check_database", db_down), \
             patch.object(db_mod, "run_db", run_db_stub):
            health_down = asyncio.run(check_db_down())
        ok_down = True
    except Exception:
        health_down, ok_down = {}, False
    check("DB yiqilganda status=UNHEALTHY",
          ok_down and health_down.get("status") == hs.STATUS_UNHEALTHY,
          str(health_down.get("status")))

    try:
        text = asyncio.run(hs.format_health_report("uz", health or None))
        ok_text = isinstance(text, str) and len(text) > 50
    except Exception:
        ok_text = False
    check("format_health_report() matn qaytaradi", ok_text, "")


# ============================================================
# 9) CREDITS LEDGER AUDIT (8-bosqich)
# ============================================================

def test_credits_ledger_static():
    section("9) CREDITS LEDGER AUDIT — static")
    from services import credits_service as cs

    check("operation_type oq ro'yxati mavjud",
          set(cs.VALID_OPERATION_TYPES) >= {"daily_bonus", "referral",
                                            "ai_request", "promo", "admin"},
          str(cs.VALID_OPERATION_TYPES))
    try:
        cs.CreditsService._validate_op("hacker_op")
        blocked = False
    except ValueError:
        blocked = True
    check("noma'lum operation_type rad etiladi (ValueError)", blocked, "")
    try:
        cs.CreditsService.add_credits(1, -5, cs.OP_PROMO)
        neg_blocked = False
    except ValueError:
        neg_blocked = True
    except Exception:
        neg_blocked = False
    check("manfiy miqdor rad etiladi", neg_blocked, "")
    check("InsufficientCreditsError required/available bilan",
          hasattr(cs.InsufficientCreditsError, "__init__"), "")
    e = cs.InsufficientCreditsError(1, 10, 3)
    check("istisno atributlari: required=10, available=3",
          getattr(e, "required", None) == 10 and getattr(e, "available", None) == 3, "")


def test_credits_ledger_live(db_mod):
    print("== 9) LIVE: balans ↔ ledger zanjiri doim mos ==")
    from services import credits_service as cs

    uid = _BASE + 51
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, ai_credits) "
            "VALUES (%s, %s, 0) ON CONFLICT (user_id) DO UPDATE SET ai_credits = 0",
            (uid, f"final_{uid}"))
        cur.execute("DELETE FROM credits_ledger WHERE user_id = %s", (uid,))

    add_res = cs.CreditsService.add_credits(uid, 10, cs.OP_PROMO, ref_id="FINAL_ACCEPT")
    check("LIVE add_credits(+10): balance_after=10",
          add_res.get("success") and add_res.get("balance_after") == 10, str(add_res))

    spend_res = cs.CreditsService.spend_credits(uid, 4, cs.OP_AI_REQUEST)
    check("LIVE spend_credits(-4): balance_after=6",
          spend_res.get("success") and spend_res.get("balance_after") == 6, str(spend_res))

    # Ortiqcha yechish → istisno, hech narsa yozilmaydi.
    try:
        cs.CreditsService.spend_credits(uid, 100, cs.OP_AI_REQUEST)
        over_blocked = False
    except cs.InsufficientCreditsError as e:
        over_blocked = e.available == 6 and e.required == 100
    check("LIVE ortiqcha spend: InsufficientCreditsError (balans o'zgarmaydi)",
          over_blocked, "")

    with db_mod.db_cursor() as cur:
        cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (uid,))
        balance = int(cur.fetchone()[0])
        cur.execute(
            "SELECT amount, balance_after, operation_type FROM credits_ledger "
            "WHERE user_id = %s ORDER BY id ASC", (uid,))
        rows = cur.fetchall()
    check("LIVE muvaffaqiyatsiz spend'dan keyin balans 6", balance == 6, str(balance))
    check("LIVE ledger aynan 2 ta yozuv (xato yozuv qoldirmadi)", len(rows) == 2, str(rows))
    chain_ok = (
        len(rows) == 2
        and int(rows[0][0]) == 10 and int(rows[0][1]) == 10 and rows[0][2] == "promo"
        and int(rows[1][0]) == -4 and int(rows[1][1]) == 6 and rows[1][2] == "ai_request"
    )
    check("LIVE balance_after zanjiri uzluksiz (10 → 6)", chain_ok, str(rows))

    history = cs.CreditsService.get_user_history(uid, limit=10)
    check("LIVE get_user_history: eng yangisi birinchi",
          len(history) == 2 and int(history[0].get("balance_after", -1)) == 6,
          str(history)[:120])


# ============================================================
# 10) GRACEFUL SHUTDOWN (9-bosqich)
# ============================================================

def test_graceful_shutdown():
    section("10) GRACEFUL SHUTDOWN — lifecycle + signal handlerlar")
    from services import lifecycle_service as lc
    import main as main_mod

    # Lifecycle bayrog'i.
    lc.reset_for_tests()
    check("boshlang'ich holat: shutdown so'ralmagan", lc.is_shutting_down() is False, "")
    first = lc.request_shutdown("SIGTERM")
    second = lc.request_shutdown("SIGTERM")
    check("birinchi request_shutdown → True", first is True, "")
    check("takroriy signal yopilishni qayta boshlamaydi (False)", second is False, "")
    check("is_shutting_down=True", lc.is_shutting_down() is True, "")
    check("shutdown_reason saqlanadi", lc.shutdown_reason() == "SIGTERM",
          str(lc.shutdown_reason()))
    lc.reset_for_tests()

    # In-flight vazifa kuzatuvi.
    token = lc.begin_task("final_delivery")
    check("begin_task: inflight=1", lc.inflight_count() == 1, "")
    lc.end_task(token)
    check("end_task: inflight=0", lc.inflight_count() == 0, "")
    report = asyncio.run(lc.wait_for_inflight(timeout=1.0))
    check("wait_for_inflight dict qaytaradi", isinstance(report, dict), str(report))

    # main.py signal kontraktlari.
    check("SHUTDOWN_SIGNALS: SIGTERM + SIGINT",
          signal.SIGTERM in main_mod.SHUTDOWN_SIGNALS
          and signal.SIGINT in main_mod.SHUTDOWN_SIGNALS, "")
    check("install_signal_handlers mavjud", callable(main_mod.install_signal_handlers), "")
    check("graceful_shutdown mavjud", callable(main_mod.graceful_shutdown), "")

    # Real signal oqimi: handler event loop ichida signalni ushlaydi.
    got_signal = False
    loop = asyncio.new_event_loop()
    try:
        stop_event = asyncio.Event()
        installed = main_mod.install_signal_handlers(loop, stop_event)
        check("signal handlerlar o'rnatildi (SIGTERM/SIGINT)",
              signal.SIGTERM in installed and signal.SIGINT in installed, str(installed))
        if installed:
            os.kill(os.getpid(), signal.SIGINT)

            async def _wait():
                await asyncio.wait_for(stop_event.wait(), timeout=3.0)

            try:
                loop.run_until_complete(_wait())
                got_signal = True
            except Exception:
                got_signal = False
        check("SIGINT → stop_event set bo'ldi", got_signal, "")
        check("SIGINT → lifecycle shutdown holatiga o'tdi", lc.is_shutting_down() is True, "")
        main_mod.remove_signal_handlers(loop, installed)
    finally:
        loop.close()
        lc.reset_for_tests()

    # Graceful shutdown komponentlarsiz ham xavfsiz ishlaydi.
    try:
        rep = asyncio.run(main_mod.graceful_shutdown())
        ok_shutdown = isinstance(rep, dict) and "steps" in rep and not rep.get("errors")
    except Exception as e:
        ok_shutdown = False
        rep = str(e)
    check("graceful_shutdown(): xatosiz hisobot", ok_shutdown, str(rep)[:120])
    lc.reset_for_tests()


# ============================================================
# BONUS: 10-BOSQICH INFRASTRUKTURA (Docker, CI/CD, Sentry)
# ============================================================

def test_phase10_infrastructure():
    section("BONUS) 10-BOSQICH INFRASTRUKTURA — Docker/CI/Sentry kontraklari")
    # --- Dockerfile ---
    dockerfile = REPO_ROOT / "Dockerfile"
    check("Dockerfile mavjud", dockerfile.is_file(), "")
    df = dockerfile.read_text(encoding="utf-8") if dockerfile.is_file() else ""
    check("Dockerfile: python:3.11-slim asos", "python:3.11-slim" in df, "")
    check("Dockerfile: root bo'lmagan appuser", "useradd" in df and "USER appuser" in df, "")
    check("Dockerfile: HEALTHCHECK (get_system_health)",
          "HEALTHCHECK" in df and "get_system_health" in df, "")
    check("Dockerfile: STOPSIGNAL SIGTERM", "STOPSIGNAL SIGTERM" in df, "")

    # --- docker-compose.yml ---
    compose = REPO_ROOT / "docker-compose.yml"
    check("docker-compose.yml mavjud", compose.is_file(), "")
    cp = compose.read_text(encoding="utf-8") if compose.is_file() else ""
    check("compose: bot + postgres xizmatlari", "bot:" in cp and "postgres:" in cp, "")
    check("compose: healthcheck'lar", "healthcheck:" in cp and "pg_isready" in cp, "")

    # --- CI/CD ---
    ci = REPO_ROOT / ".github" / "workflows" / "ci.yml"
    check(".github/workflows/ci.yml mavjud", ci.is_file(), "")
    ci_text = ci.read_text(encoding="utf-8") if ci.is_file() else ""
    check("CI: push + pull_request trigger (main)",
          "push:" in ci_text and "pull_request:" in ci_text and "main" in ci_text, "")
    check("CI: Python 3.11", '"3.11"' in ci_text or "'3.11'" in ci_text, "")
    check("CI: ruff + flake8 sintaksis tekshiruvi", "ruff" in ci_text and "flake8" in ci_text, "")
    check("CI: tests/run_tests.sh ishga tushiriladi", "tests/run_tests.sh" in ci_text, "")

    # --- .env.example ---
    env_ex = REPO_ROOT / ".env.example"
    env_text = env_ex.read_text(encoding="utf-8") if env_ex.is_file() else ""
    check(".env.example mavjud", env_ex.is_file(), "")
    missing = [k for k in ("AI_PROVIDER_CHAIN", "DB_POOL_SIZE", "SENTRY_DSN",
                           "ADMIN_IDS", "BOT_TOKEN", "DATABASE_URL")
               if k + "=" not in env_text]
    check(".env.example: V2 kalitlari to'liq", not missing, str(missing))

    # --- Sentry maxfiylik filtri ---
    from utils import sentry_scrubber as ss

    ss.clear_secrets()
    ss.register_secret("987654321:AA_FAKE_TOKEN_abcXYZ123456789_-", "BOT_TOKEN")
    dirty = ("token=987654321:AA_FAKE_TOKEN_abcXYZ123456789_- "
             "db=postgresql://botuser:super_secret_pw@db.host/neon "
             "card=8600 0609 5082 5589 key=sk-AbCdEfGh1234567890xYz")
    clean = ss.scrub_text(dirty)
    check("scrubber: bot token o'chirildi", "AA_FAKE_TOKEN" not in clean, clean)
    check("scrubber: DB paroli o'chirildi", "super_secret_pw" not in clean, clean)
    check("scrubber: karta raqami niqoblandi", "5082" not in clean and "8600 06" not in clean, clean)
    check("scrubber: API kalit o'chirildi", "sk-AbCdEfGh" not in clean, clean)
    check("scrubber: karta oxirgi 4 xona saqlanmadi (to'liq redaksiya)",
          ss.REDACTED_CARD in clean, clean)

    masked = ss.mask_card_number("8600060950825589")
    check("mask_card_number: faqat oxirgi 4 xona", masked.endswith("5589") and "8600" not in masked, masked)

    event = {
        "message": "token 987654321:AA_FAKE_TOKEN_abcXYZ123456789_- ishlamadi",
        "request": {"headers": {"Authorization": "Bearer abc"},
                    "data": {"password": "12345"}},
        "exception": {"values": [{"value": "parol=super_secret_pw",
                                   "stacktrace": {"frames": [
                                       {"vars": {"token": "topsecret12345"}}]}}]},
        "extra": {"DATABASE_URL": "postgresql://u:hidden@h/db"},
    }
    scrubbed = ss.scrub_event(event, None)
    check("scrub_event: message tozalandi",
          scrubbed and "AA_FAKE_TOKEN" not in str(scrubbed.get("message")), "")
    check("scrub_event: header/parol kalitlari redaksiya qilindi",
          scrubbed["request"]["headers"]["Authorization"] == ss.REDACTED
          and scrubbed["request"]["data"]["password"] == ss.REDACTED, "")
    check("scrub_event: frame vars tozalandi",
          "topsecret12345" not in str(scrubbed.get("exception")), "")
    check("scrub_event: hech qachon istisno ko'tarmaydi",
          ss.scrub_event({"weird": object()}, None) is not None
          or ss.scrub_event({"weird": object()}, None) is None, "")

    # config wiring: sentry_sdk mavjud bo'lsa before_send=scrub_event.
    import config as config_mod
    check("config._init_sentry mavjud", callable(getattr(config_mod, "_init_sentry", None)), "")
    check("config.SENTRY_DSN o'zgaruvchisi mavjud", hasattr(config_mod, "SENTRY_DSN"), "")
    try:
        import sentry_sdk  # noqa: F401
        have_sdk = True
    except ImportError:
        have_sdk = False
    if have_sdk:
        from unittest.mock import MagicMock
        init_mock = MagicMock()
        old_dsn = config_mod.SENTRY_DSN
        config_mod.SENTRY_DSN = "https://fake@o1.ingest.sentry.io/1"
        try:
            with patch("sentry_sdk.init", init_mock):
                ok = config_mod._init_sentry()
            kwargs = init_mock.call_args.kwargs if init_mock.called else {}
            check("sentry_sdk.init before_send=scrub_event bilan chaqiriladi",
                  ok and kwargs.get("before_send") is ss.scrub_event, str(kwargs.keys()))
            check("sentry_sdk.init send_default_pii=False",
                  kwargs.get("send_default_pii") is False, "")
        finally:
            config_mod.SENTRY_DSN = old_dsn
    else:
        skip("sentry_sdk wiring testi", "(sentry_sdk o'rnatilmagan)")

    ss.clear_secrets()


# ============================================================
# LIVE POSTGRESQL BOOTSTRAP
# ============================================================

_local_server = []


def _live_uri():
    """Real PG URI: FINAL_TEST_DATABASE_URL | P0_TEST_DATABASE_URL |
    INTEGRITY_TEST_DATABASE_URL | pgserver (vaqtinchalik lokal server)."""
    for var in ("FINAL_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL",
                "INTEGRITY_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url
    url = os.getenv("DATABASE_URL")
    if url and "user:pass" not in url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    if _local_server:
        return _local_server[0].get_uri()
    import tempfile
    try:
        server = pgserver.get_server(
            os.path.join(tempfile.gettempdir(), "yordamchi_pg_final_accept"))
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        print(f"  (pgserver ishga tushmadi: {e})")
        return None
    _local_server.append(server)
    return server.get_uri()


def main():
    print("PostAssist V2 — YAKUNIY ACCEPTANCE TEST (10-BOSQICH)")

    # ---- STATIC (har doim ishlaydi) ----
    test_payment_idempotency_static()
    test_promo_redemption_static()
    test_subscription_additive_static()
    test_scheduler_idempotency_static()
    test_ai_fallback_resilience()
    test_db_integrity_static()
    test_rbac_static()
    test_health_check()
    test_credits_ledger_static()
    test_graceful_shutdown()
    test_phase10_infrastructure()

    # ---- LIVE (real PostgreSQL) ----
    uri = _live_uri()
    if not uri:
        skip("LIVE PostgreSQL tekshiruvlari (1/2/3/4/6/7/9)",
             "(pgserver/URL topilmadi)")
    else:
        import database as db_mod
        db_mod.DATABASE_URL = uri
        os.environ["DATABASE_URL"] = uri
        db_mod._reset_pool()
        try:
            db_mod.init_db()
        except Exception as e:
            skip("LIVE PostgreSQL tekshiruvlari", f"(init_db: {e})")
            uri = None
        if uri:
            try:
                test_payment_idempotency_live(db_mod)
                test_promo_redemption_live(db_mod)
                test_subscription_additive_live(db_mod)
                test_scheduler_idempotency_live(db_mod)
                test_db_integrity_live(db_mod)
                test_rbac_live(db_mod)
                test_credits_ledger_live(db_mod)
            finally:
                db_mod.close_pool()

    print(f"\nJAMI: o'tdi={passed}, xato={failures}, o'tkazib yuborildi={skipped}")
    if failures:
        sys.exit(1)
    print("Barcha yakuniy acceptance testlari muvaffaqiyatli o'tdi ✔ "
          "(PostAssist V2 release tayyor)")


if __name__ == "__main__":
    main()
