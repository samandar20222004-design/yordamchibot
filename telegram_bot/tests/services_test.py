#!/usr/bin/env python3
"""Service Layer unit testlari — DB ulanish talab qilinmaydi (mock bilan).

Ishga tushirish:
    cd telegram_bot && python tests/services_test.py

Testlar:
  - SubscriptionService: activate, extend, get_status, revoke, is_premium
  - PaymentService: validate_payload, process_stars_payment, process_receipt
  - PromoService: create_promo, redeem_promo, get_promo_stats
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ============================================================
# MOCK DB CURSOR — faqat fetchone/fetchall navbatlari bilan
# ============================================================

class MockCursor:
    """Minimal psycopg2 cursor mock.

    ``_rows`` — fetchone() navbati (har chaqiruvda bitta pop).
    Har bir execute() uchun rowcount default=1.
    """

    def __init__(self):
        self._rows = []
        self._rc = 1
        self._queries = []
        self._params_list = []

    def execute(self, query, params=None):
        self._queries.append(query)
        self._params_list.append(params)

    def fetchone(self):
        if self._rows:
            return self._rows.pop(0)
        return None

    def fetchall(self):
        rows = list(self._rows)
        self._rows.clear()
        return rows

    @property
    def rowcount(self):
        return self._rc

    @rowcount.setter
    def rowcount(self, val):
        self._rc = val

    def close(self):
        pass


class MockConnection:
    def __init__(self):
        self.cur = MockCursor()

    def cursor(self):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


# Shared mock cursor — barcha testlar uchun
_mock_cur = MockCursor()
_mock_conn = MockConnection()
_mock_conn.cur = _mock_cur


def _make_mock_dc():
    """db_cursor() ni mock qiluvchi context manager."""
    from contextlib import contextmanager

    @contextmanager
    def _dc(commit=False):
        try:
            yield _mock_cur
        except Exception:
            _mock_conn.rollback()
            raise

    return _dc


def _reset_cur(rows=None):
    """Mock cursor'ni yangi test uchun tayyorlaydi."""
    _mock_cur._rows = list(rows) if rows else []
    _mock_cur._rc = 1
    _mock_cur._queries.clear()
    _mock_cur._params_list.clear()


# ============================================================
# SUBSCRIPTION SERVICE TESTLARI
# ============================================================

def test_subscription_activate():
    """SubscriptionService.activate — yangi obuna berish."""
    print("== SubscriptionService.activate ==")
    from services.subscription_service import SubscriptionService

    _reset_cur()
    with patch("services.subscription_service.db_cursor", _make_mock_dc()), \
         patch("services.subscription_service._invalidate_user"), \
         patch("services.subscription_service._cache_clear"):
        result = SubscriptionService.activate(12345, "pro", 30)
        check("activate: muvaffaqiyatli", result is True)
        check("activate: UPDATE query", any("UPDATE" in q for q in _mock_cur._queries))
        check("activate: GREATEST formula", any("GREATEST" in q for q in _mock_cur._queries))

    # Noto'g'ri plan
    result2 = SubscriptionService.activate(12345, "bogus", 30)
    check("activate: noto'g'ri plan → False", result2 is False)

    # Nol kun
    result3 = SubscriptionService.activate(12345, "pro", 0)
    check("activate: 0 kun → False", result3 is False)

    # Manfiy kun
    result4 = SubscriptionService.activate(12345, "pro", -5)
    check("activate: manfiy kun → False", result4 is False)

    # rowcount=0 (UPDATE hech narsa o'zgartirmadi)
    _reset_cur()
    _mock_cur._rc = 0
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        result5 = SubscriptionService.activate(99999, "pro", 30)
        check("activate: user topilmadi → False", result5 is False)


def test_subscription_extend():
    """SubscriptionService.extend — muddat uzaytirish."""
    print("== SubscriptionService.extend ==")
    from services.subscription_service import SubscriptionService

    _reset_cur()
    with patch("services.subscription_service.db_cursor", _make_mock_dc()), \
         patch("services.subscription_service._invalidate_user"), \
         patch("services.subscription_service._cache_clear"):
        result = SubscriptionService.extend(12345, 30)
        check("extend: muvaffaqiyatli", result is True)
        check("extend: GREATEST formula", any("GREATEST" in q for q in _mock_cur._queries))
        check("extend: COALESCE formula", any("COALESCE" in q for q in _mock_cur._queries))

    result2 = SubscriptionService.extend(12345, 0)
    check("extend: 0 kun → False", result2 is False)

    result3 = SubscriptionService.extend(12345, -1)
    check("extend: manfiy kun → False", result3 is False)


def test_subscription_get_status_active():
    """SubscriptionService.get_status — faol obuna."""
    print("== SubscriptionService.get_status (faol) ==")
    from services.subscription_service import SubscriptionService

    future = datetime.now(timezone.utc) + timedelta(days=15)
    _reset_cur(rows=[("pro", future)])
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        status = SubscriptionService.get_status(12345)
        check("get_status: is_pro True", status["is_pro"] is True)
        check("get_status: plan_type pro", status["plan_type"] == "pro")
        check("get_status: remaining_days > 0", status["remaining_days"] > 0)
        check("get_status: expiry_date bor", status["expiry_date"] is not None)


def test_subscription_get_status_expired():
    """SubscriptionService.get_status — muddati o'tgan obuna."""
    print("== SubscriptionService.get_status (muddati o'tgan) ==")
    from services.subscription_service import SubscriptionService

    past = datetime.now(timezone.utc) - timedelta(days=5)
    # SELECT → ("pro", past), then UPDATE (no fetchone needed)
    _reset_cur(rows=[("pro", past)])
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        status = SubscriptionService.get_status(12345)
        check("expired: is_pro False", status["is_pro"] is False)
        check("expired: plan_type free", status["plan_type"] == "free")
        check("expired: remaining_days 0", status["remaining_days"] == 0)


def test_subscription_get_status_enterprise():
    """SubscriptionService.get_status — enterprise (cheksiz)."""
    print("== SubscriptionService.get_status (enterprise, cheksiz) ==")
    from services.subscription_service import SubscriptionService

    _reset_cur(rows=[("enterprise", None)])
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        status = SubscriptionService.get_status(12345)
        check("enterprise: is_pro True", status["is_pro"] is True)
        check("enterprise: remaining_days -1 (cheksiz)", status["remaining_days"] == -1)
        check("enterprise: expiry_date None", status["expiry_date"] is None)


def test_subscription_get_status_free():
    """SubscriptionService.get_status — bepul foydalanuvchi."""
    print("== SubscriptionService.get_status (free) ==")
    from services.subscription_service import SubscriptionService

    _reset_cur(rows=[("free", None)])
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        status = SubscriptionService.get_status(12345)
        check("free: is_pro False", status["is_pro"] is False)
        check("free: remaining_days 0", status["remaining_days"] == 0)


def test_subscription_get_status_not_found():
    """SubscriptionService.get_status — user topilmadi."""
    print("== SubscriptionService.get_status (user topilmadi) ==")
    from services.subscription_service import SubscriptionService

    _reset_cur(rows=[None])
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        status = SubscriptionService.get_status(12345)
        check("not_found: is_pro False", status["is_pro"] is False)
        check("not_found: plan_type free", status["plan_type"] == "free")


def test_subscription_revoke():
    """SubscriptionService.revoke — obunani bekor qilish."""
    print("== SubscriptionService.revoke ==")
    from services.subscription_service import SubscriptionService

    _reset_cur()
    with patch("services.subscription_service.db_cursor", _make_mock_dc()), \
         patch("services.subscription_service._invalidate_user"), \
         patch("services.subscription_service._cache_clear"):
        result = SubscriptionService.revoke(12345)
        check("revoke: muvaffaqiyatli", result is True)
        check("revoke: plan_type = free", any("'free'" in q for q in _mock_cur._queries))
        check("revoke: expires_at = NULL", any("NULL" in q for q in _mock_cur._queries))

    # rowcount=0
    _reset_cur()
    _mock_cur._rc = 0
    with patch("services.subscription_service.db_cursor", _make_mock_dc()):
        result2 = SubscriptionService.revoke(99999)
        check("revoke: user topilmadi → False", result2 is False)


def test_subscription_grant_admin_bonus():
    """SubscriptionService.grant_admin_bonus."""
    print("== SubscriptionService.grant_admin_bonus ==")
    from services.subscription_service import SubscriptionService

    with patch.object(SubscriptionService, "activate", return_value=True) as mock_act:
        result = SubscriptionService.grant_admin_bonus(12345, 30, 999)
        check("grant_admin_bonus: muvaffaqiyatli", result is True)
        # 6-bosqich: admin_id audit uchun activate()ga uzatiladi (PRO berish
        # harakati admin_audit_logs jadvaliga atomik yozilishi kerak).
        mock_act.assert_called_once_with(12345, "pro", 30, admin_id=999)

    with patch.object(SubscriptionService, "activate", return_value=False):
        result2 = SubscriptionService.grant_admin_bonus(12345, 0, 999)
        check("grant_admin_bonus: 0 kun → False", result2 is False)

    result3 = SubscriptionService.grant_admin_bonus(12345, -5, 999)
    check("grant_admin_bonus: manfiy kun → False", result3 is False)


def test_subscription_is_premium():
    """SubscriptionService.is_premium — get_status ga tayanadi."""
    print("== SubscriptionService.is_premium ==")
    from services.subscription_service import SubscriptionService

    with patch.object(SubscriptionService, "get_status") as mock_gs:
        mock_gs.return_value = {"is_pro": True, "plan_type": "pro"}
        check("is_premium: True", SubscriptionService.is_premium(12345) is True)

        mock_gs.return_value = {"is_pro": False, "plan_type": "free"}
        check("is_premium: False", SubscriptionService.is_premium(12345) is False)


# ============================================================
# PAYMENT SERVICE TESTLARI
# ============================================================

def test_payment_validate_payload_valid():
    """PaymentService.validate_payload — to'g'ri payload."""
    print("== PaymentService.validate_payload (to'g'ri) ==")
    from services.payment_service import PaymentService

    plan, err = PaymentService.validate_payload("sub_stars_1m_12345", 12345, 75, "XTR")
    check("valid: plan qaytdi", plan is not None)
    check("valid: err None", err is None)
    check("valid: plan_key stars_1m", plan["plan_key"] == "stars_1m")
    check("valid: stars 75", plan["stars"] == 75)
    check("valid: days 30", plan["days"] == 30)

    plan2, err2 = PaymentService.validate_payload("sub_stars_3m_99", 99, 175, "XTR")
    check("valid: 3 oylik", plan2["days"] == 90 and err2 is None)

    plan3, err3 = PaymentService.validate_payload("sub_stars_1y_77", 77, 550, "XTR")
    check("valid: 1 yillik", plan3["days"] == 365 and err3 is None)


def test_payment_validate_payload_wrong_user():
    """PaymentService.validate_payload — noto'g'ri user ID."""
    print("== PaymentService.validate_payload (noto'g'ri user) ==")
    from services.payment_service import PaymentService

    plan, err = PaymentService.validate_payload("sub_stars_1m_12345", 99999, 75, "XTR")
    check("wrong_user: plan None", plan is None)
    check("wrong_user: xato xabari", "mos emas" in err)


def test_payment_validate_payload_wrong_amount():
    """PaymentService.validate_payload — noto'g'ri summa."""
    print("== PaymentService.validate_payload (noto'g'ri summa) ==")
    from services.payment_service import PaymentService

    plan, err = PaymentService.validate_payload("sub_stars_1m_12345", 12345, 999, "XTR")
    check("wrong_amount: plan None", plan is None)
    check("wrong_amount: xato xabari", "mos emas" in err)


def test_payment_validate_payload_wrong_currency():
    """PaymentService.validate_payload — noto'g'ri valyuta."""
    print("== PaymentService.validate_payload (noto'g'ri valyuta) ==")
    from services.payment_service import PaymentService

    plan, err = PaymentService.validate_payload("sub_stars_1m_12345", 12345, 75, "USD")
    check("wrong_currency: plan None", plan is None)
    check("wrong_currency: xato xabari", "valyutasi" in err)


def test_payment_validate_payload_bogus():
    """PaymentService.validate_payload — noto'g'ri format."""
    print("== PaymentService.validate_payload (bogus format) ==")
    from services.payment_service import PaymentService

    for bad in ("", "garbage", "sub_stars_4m_123"):
        plan, err = PaymentService.validate_payload(bad, 1, 1, "XTR")
        check(f"bogus {bad!r}: plan None", plan is None)

    plan, err = PaymentService.validate_payload(None, 1, 1, "XTR")
    check("bogus None: plan None", plan is None)


def test_payment_process_stars_payment():
    """PaymentService.process_stars_payment — to'g'ri to'lov."""
    print("== PaymentService.process_stars_payment ==")
    from services.payment_service import PaymentService

    # SELECT 1 (fetchone) → (1,), INSERT RETURNING id (fetchone) → (1,)
    _reset_cur(rows=[(1,), (1,)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()), \
         patch("services.payment_service._invalidate_user"), \
         patch("services.payment_service._cache_clear"):
        result = PaymentService.process_stars_payment(
            12345, "charge_abc", 75, "sub_stars_1m_12345", "pro", 30
        )
        check("stars: ok True", result["ok"] is True)
        check("stars: duplicate False", result["duplicate"] is False)
        check("stars: days 30", result["days"] == 30)
        check("stars: GREATEST", any("GREATEST" in q for q in _mock_cur._queries))
        check("stars: COALESCE", any("COALESCE" in q for q in _mock_cur._queries))


def test_payment_process_stars_user_not_found():
    """PaymentService.process_stars_payment — user topilmadi."""
    print("== PaymentService.process_stars_payment (user topilmadi) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[None])  # SELECT 1 → None
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_stars_payment(
            99999, "charge_xyz", 75, "payload", "pro", 30
        )
        check("user_not_found: ok False", result["ok"] is False)
        check("user_not_found: reason", "user_not_found" in result["reason"])


def test_payment_process_stars_duplicate():
    """PaymentService.process_stars_payment — takroriy to'lov."""
    print("== PaymentService.process_stars_payment (takroriy) ==")
    from services.payment_service import PaymentService

    # SELECT 1 → (1,), INSERT RETURNING → None (UNIQUE conflict)
    _reset_cur(rows=[(1,), None])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_stars_payment(
            12345, "charge_dup", 75, "sub_stars_1m_12345", "pro", 30
        )
        check("duplicate: ok True", result["ok"] is True)
        check("duplicate: duplicate True", result["duplicate"] is True)
        check("duplicate: days 0", result["days"] == 0)


def test_payment_process_stars_empty_charge():
    """PaymentService.process_stars_payment — bo'sh charge_id."""
    print("== PaymentService.process_stars_payment (bo'sh charge) ==")
    from services.payment_service import PaymentService

    result = PaymentService.process_stars_payment(12345, "", 75, "payload")
    check("empty_charge: ok False", result["ok"] is False)
    check("empty_charge: reason invalid", "invalid" in result["reason"])


def test_payment_process_stars_zero_days():
    """PaymentService.process_stars_payment — 0 kun."""
    print("== PaymentService.process_stars_payment (0 kun) ==")
    from services.payment_service import PaymentService

    result = PaymentService.process_stars_payment(12345, "charge", 75, "payload", "pro", 0)
    check("zero_days: ok False", result["ok"] is False)


def test_payment_process_receipt_approve():
    """PaymentService.process_receipt — tasdiqlash."""
    print("== PaymentService.process_receipt (approve) ==")
    from services.payment_service import PaymentService

    # _approve_receipt: SELECT → ("pending", uid, 30), SELECT lang → ("uz",)
    _reset_cur(rows=[("pending", 12345, 30), ("uz",)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()), \
         patch("services.payment_service._invalidate_user"), \
         patch("services.payment_service._cache_clear"), \
         patch("services.payment_service._normalize_language_code", return_value="uz"):
        result = PaymentService.process_receipt(1, 999, True)
        check("approve: ok True", result["ok"] is True)
        check("approve: user_id 12345", result["user_id"] == 12345)
        check("approve: days 30", result["days"] == 30)
        check("approve: lang uz", result["language_code"] == "uz")


def test_payment_process_receipt_approve_default_days():
    """PaymentService.process_receipt — days_granted=0 → default 30."""
    print("== PaymentService.process_receipt (default days) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[("pending", 55555, 0), ("ru",)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()), \
         patch("services.payment_service._invalidate_user"), \
         patch("services.payment_service._cache_clear"), \
         patch("services.payment_service._normalize_language_code", return_value="ru"):
        result = PaymentService.process_receipt(1, 999, True)
        check("default_days: days 30", result["days"] == 30)


def test_payment_process_receipt_reject():
    """PaymentService.process_receipt — rad etish."""
    print("== PaymentService.process_receipt (reject) ==")
    from services.payment_service import PaymentService

    # _reject_receipt: SELECT → ("pending", uid)
    _reset_cur(rows=[("pending", 12345)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_receipt(1, 999, False)
        check("reject: ok True", result["ok"] is True)
        check("reject: user_id 12345", result["user_id"] == 12345)
        check("reject: rejected query", any("rejected" in q for q in _mock_cur._queries))


def test_payment_process_receipt_reject_already_reviewed():
    """PaymentService.process_receipt (reject) — allaqachon ko'rilgan."""
    print("== PaymentService.process_receipt (reject: allaqachon) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[("approved", 12345)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_receipt(1, 999, False)
        check("already_reviewed: ok False", result["ok"] is False)
        check("already_reviewed: reason", "already_reviewed" in result["reason"])


def test_payment_process_receipt_already_approved():
    """PaymentService.process_receipt (approve) — allaqachon tasdiqlangan."""
    print("== PaymentService.process_receipt (approve: allaqachon) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[("approved", 12345, 30)])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_receipt(1, 999, True)
        check("already_approved: ok False", result["ok"] is False)
        check("already_approved: reason", "already_approved" in result["reason"])


def test_payment_process_receipt_not_found():
    """PaymentService.process_receipt — topilmadi."""
    print("== PaymentService.process_receipt (topilmadi) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[None])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        result = PaymentService.process_receipt(999, 1, True)
        check("not_found: ok False", result["ok"] is False)
        check("not_found: reason", "not_found" in result["reason"])


def test_payment_get_history():
    """PaymentService.get_user_payment_history."""
    print("== PaymentService.get_user_payment_history ==")
    from services.payment_service import PaymentService

    now = datetime.now(timezone.utc)
    _reset_cur()
    _mock_cur._rows = [
        (1, 75, "XTR", "payload1", "charge_1", now),
        (2, 175, "XTR", "payload2", "charge_2", now),
    ]
    # fetchall() uses _rows
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        history = PaymentService.get_user_payment_history(12345)
        check("history: 2 ta yozuv", len(history) == 2)
        check("history: id 1", history[0]["id"] == 1)
        check("history: amount 75", history[0]["amount"] == 75)
        check("history: charge_id", history[0]["charge_id"] == "charge_1")
        check("history: currency XTR", history[0]["currency"] == "XTR")


def test_payment_get_history_empty():
    """PaymentService.get_user_payment_history — bo'sh."""
    print("== PaymentService.get_user_payment_history (bo'sh) ==")
    from services.payment_service import PaymentService

    _reset_cur(rows=[])
    with patch("services.payment_service.db_cursor", _make_mock_dc()):
        history = PaymentService.get_user_payment_history(12345)
        check("history_empty: bo'sh", len(history) == 0)


# ============================================================
# PROMO SERVICE TESTLARI
# ============================================================

def test_promo_create():
    """PromoService.create_promo — promo-kod yaratish."""
    print("== PromoService.create_promo ==")
    from services.promo_service import PromoService

    _reset_cur()
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        result = PromoService.create_promo("TEST30", 30, 50)
        check("create: muvaffaqiyatli", result is True)
        check("create: INSERT query", any("INSERT" in q for q in _mock_cur._queries))
        check("create: promo_codes jadvaliga", any("promo_codes" in q for q in _mock_cur._queries))

    # rowcount=0 → CONFLICT DO NOTHING
    _reset_cur()
    _mock_cur._rc = 0
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        result2 = PromoService.create_promo("EXISTING", 30)
        check("conflict: False (allaqachon bor)", result2 is False)

    # Bo'sh kod
    result3 = PromoService.create_promo("", 30)
    check("create: bo'sh kod → False", result3 is False)

    # 0 kun
    result4 = PromoService.create_promo("KOD", 0)
    check("create: 0 kun → False", result4 is False)

    # max_uses <= 0
    result5 = PromoService.create_promo("KOD", 30, max_uses=0)
    check("create: max_uses=0 → False", result5 is False)


def test_promo_redeem_success():
    """PromoService.redeem_promo — muvaffaqiyatli faollashtirish."""
    print("== PromoService.redeem_promo (muvaffaqiyatli) ==")
    from services.promo_service import PromoService

    # SELECT promo → (id, plan_type, days, max_uses, current_uses, is_active, expires_at)
    # INSERT redemption → (id,)
    # No more fetchone needed
    _reset_cur(rows=[(1, "pro", 30, 10, 2, True, None), (1,)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()), \
         patch("services.promo_service._invalidate_user"), \
         patch("services.promo_service._cache_clear"):
        success, msg = PromoService.redeem_promo(12345, "TEST30")
        check("redeem: success True", success is True)
        check("redeem: xabar kaliti", "faollashtirildi" in msg or "kunlik" in msg)
        check("redeem: promo_redemptions INSERT",
              any("promo_redemptions" in q for q in _mock_cur._queries))


def test_promo_redeem_not_found():
    """PromoService.redeem_promo — topilmadi."""
    print("== PromoService.redeem_promo (topilmadi) ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[None])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        success, msg = PromoService.redeem_promo(12345, "YOQ")
        check("not_found: False", success is False)
        check("not_found: xabar", "topilmadi" in msg)


def test_promo_redeem_inactive():
    """PromoService.redeem_promo — o'chirilgan kod."""
    print("== PromoService.redeem_promo (o'chirilgan) ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[(1, "pro", 30, None, 0, False, None)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        success, msg = PromoService.redeem_promo(12345, "OFF")
        check("inactive: False", success is False)
        check("inactive: xabar", "o'chirilgan" in msg)


def test_promo_redeem_expired():
    """PromoService.redeem_promo — muddati o'tgan kod."""
    print("== PromoService.redeem_promo (muddati o'tgan) ==")
    from services.promo_service import PromoService

    past = datetime.now(timezone.utc) - timedelta(days=5)
    # SELECT promo → (id, plan, days, max, cur, active, expires_at)
    # SELECT (%s <= now()) → (True,)
    _reset_cur(rows=[(1, "pro", 30, None, 0, True, past), (True,)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        success, msg = PromoService.redeem_promo(12345, "OLD")
        check("expired: False", success is False)
        check("expired: xabar", "muddati o'tgan" in msg)


def test_promo_redeem_expired_not():
    """PromoService.redeem_promo — muddati o'tmagan (faqat expires_at bor)."""
    print("== PromoService.redeem_promo (muddati o'tmagan) ==")
    from services.promo_service import PromoService

    future = datetime.now(timezone.utc) + timedelta(days=30)
    # SELECT promo → row, SELECT (%s <= NOW()) → (False,), INSERT RETURNING → (1,)
    _reset_cur(rows=[
        (1, "pro", 30, None, 0, True, future),
        (False,),
        (1,),
    ])
    with patch("services.promo_service.db_cursor", _make_mock_dc()), \
         patch("services.promo_service._invalidate_user"), \
         patch("services.promo_service._cache_clear"):
        success, msg = PromoService.redeem_promo(12345, "GOOD")
        check("not_expired: success True", success is True)


def test_promo_redeem_max_uses():
    """PromoService.redeem_promo — tugagan (max_uses)."""
    print("== PromoService.redeem_promo (tugagan) ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[(1, "pro", 30, 5, 5, True, None)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        success, msg = PromoService.redeem_promo(12345, "FULL")
        check("max_uses: False", success is False)
        check("max_uses: xabar", "ishlatib bo'lingan" in msg)


def test_promo_redeem_already_used():
    """PromoService.redeem_promo — qayta ishlatish bloklanishi."""
    print("== PromoService.redeem_promo (qayta ishlatish) ==")
    from services.promo_service import PromoService

    # SELECT promo → (id, plan, days, max_uses, cur, active, expires)
    # INSERT RETURNING → None (UNIQUE constraint)
    _reset_cur(rows=[(1, "pro", 30, None, 0, True, None), None])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        success, msg = PromoService.redeem_promo(12345, "DUP")
        check("already_used: False", success is False)
        check("already_used: xabar", "avval ishlatgansiz" in msg)


def test_promo_get_stats():
    """PromoService.get_promo_stats — statistika."""
    print("== PromoService.get_promo_stats ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[("TEST30", "pro", 30, 10, 3, True, None)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        stats = PromoService.get_promo_stats("TEST30")
        check("stats: code TEST30", stats["code"] == "TEST30")
        check("stats: plan_type pro", stats["plan_type"] == "pro")
        check("stats: duration_days 30", stats["duration_days"] == 30)
        check("stats: max_uses 10", stats["max_uses"] == 10)
        check("stats: current_uses 3", stats["current_uses"] == 3)
        check("stats: remaining_uses 7", stats["remaining_uses"] == 7)
        check("stats: is_active True", stats["is_active"] is True)


def test_promo_get_stats_not_found():
    """PromoService.get_promo_stats — topilmadi."""
    print("== PromoService.get_promo_stats (topilmadi) ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[None])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        stats = PromoService.get_promo_stats("YOQ")
        check("stats_not_found: bo'sh dict", stats == {})


def test_promo_get_stats_unlimited():
    """PromoService.get_promo_stats — cheksiz (max_uses=None)."""
    print("== PromoService.get_promo_stats (cheksiz) ==")
    from services.promo_service import PromoService

    _reset_cur(rows=[("CHEKSIZ", "pro", 30, None, 5, True, None)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        stats = PromoService.get_promo_stats("CHEKSIZ")
        check("unlimited: max_uses None", stats["max_uses"] is None)
        check("unlimited: remaining_uses None", stats["remaining_uses"] is None)
        check("unlimited: current_uses 5", stats["current_uses"] == 5)


def test_promo_get_stats_expired():
    """PromoService.get_promo_stats — muddati o'tgan promo."""
    print("== PromoService.get_promo_stats (muddati o'tgan) ==")
    from services.promo_service import PromoService

    past = datetime.now(timezone.utc) - timedelta(days=5)
    _reset_cur(rows=[("OLD", "pro", 30, 10, 5, True, past)])
    with patch("services.promo_service.db_cursor", _make_mock_dc()):
        stats = PromoService.get_promo_stats("OLD")
        check("expired_stats: expires_at bor", stats["expires_at"] is not None)


# ============================================================
# BACKWARD COMPATIBILITY — database.py eskilarini tekshirish
# ============================================================

def test_backward_compatibility():
    """Eski database.py funksiyalari hali ishlaydi."""
    print("== Backward compatibility (database.py) ==")
    import database as db

    check("db.is_premium mavjud", hasattr(db, "is_premium"))
    check("db.set_user_plan mavjud", hasattr(db, "set_user_plan"))
    check("db.create_promo_code mavjud", hasattr(db, "create_promo_code"))
    check("db.redeem_promo_code mavjud", hasattr(db, "redeem_promo_code"))
    check("db.process_stars_payment mavjud", hasattr(db, "process_stars_payment"))
    check("db.approve_payment_receipt mavjud", hasattr(db, "approve_payment_receipt"))
    check("db.reject_payment_receipt mavjud", hasattr(db, "reject_payment_receipt"))
    check("db.log_stars_payment mavjud", hasattr(db, "log_stars_payment"))
    check("db.is_premium callable", callable(db.is_premium))
    check("db.set_user_plan callable", callable(db.set_user_plan))
    check("db.process_stars_payment callable", callable(db.process_stars_payment))
    check("db.create_promo_code callable", callable(db.create_promo_code))
    check("db.redeem_promo_code callable", callable(db.redeem_promo_code))

    # Servis importlari ishlaydi
    from services import SubscriptionService, PaymentService, PromoService
    check("services import: SubscriptionService", SubscriptionService is not None)
    check("services import: PaymentService", PaymentService is not None)
    check("services import: PromoService", PromoService is not None)


def test_service_class_methods():
    """Servis klasslari to'g'ri methodlarga ega."""
    print("== Service class methods ==")
    from services.subscription_service import SubscriptionService
    from services.payment_service import PaymentService
    from services.promo_service import PromoService

    # SubscriptionService
    for m in ("activate", "extend", "get_status", "grant_admin_bonus",
              "revoke", "is_premium", "get_user_plan"):
        check(f"Sub.{m}", callable(getattr(SubscriptionService, m, None)))

    # PaymentService
    for m in ("validate_payload", "process_stars_payment", "process_receipt",
              "get_user_payment_history"):
        check(f"Pay.{m}", callable(getattr(PaymentService, m, None)))

    # PromoService
    for m in ("create_promo", "redeem_promo", "get_promo_stats"):
        check(f"Promo.{m}", callable(getattr(PromoService, m, None)))


# ============================================================
# MAIN
# ============================================================

def main():
    # SubscriptionService
    test_subscription_activate()
    test_subscription_extend()
    test_subscription_get_status_active()
    test_subscription_get_status_expired()
    test_subscription_get_status_enterprise()
    test_subscription_get_status_free()
    test_subscription_get_status_not_found()
    test_subscription_revoke()
    test_subscription_grant_admin_bonus()
    test_subscription_is_premium()

    # PaymentService
    test_payment_validate_payload_valid()
    test_payment_validate_payload_wrong_user()
    test_payment_validate_payload_wrong_amount()
    test_payment_validate_payload_wrong_currency()
    test_payment_validate_payload_bogus()
    test_payment_process_stars_payment()
    test_payment_process_stars_user_not_found()
    test_payment_process_stars_duplicate()
    test_payment_process_stars_empty_charge()
    test_payment_process_stars_zero_days()
    test_payment_process_receipt_approve()
    test_payment_process_receipt_approve_default_days()
    test_payment_process_receipt_reject()
    test_payment_process_receipt_reject_already_reviewed()
    test_payment_process_receipt_already_approved()
    test_payment_process_receipt_not_found()
    test_payment_get_history()
    test_payment_get_history_empty()

    # PromoService
    test_promo_create()
    test_promo_redeem_success()
    test_promo_redeem_not_found()
    test_promo_redeem_inactive()
    test_promo_redeem_expired()
    test_promo_redeem_expired_not()
    test_promo_redeem_max_uses()
    test_promo_redeem_already_used()
    test_promo_get_stats()
    test_promo_get_stats_not_found()
    test_promo_get_stats_unlimited()
    test_promo_get_stats_expired()

    # Backward compatibility
    test_backward_compatibility()
    test_service_class_methods()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha Service Layer testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
