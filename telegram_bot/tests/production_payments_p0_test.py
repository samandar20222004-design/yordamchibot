"""PostAssist V2 1-bosqich: to'lov SSOT, Stars idempotency, receipt pending-only."""
import os
import sys
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

# psycopg2 ixtiyoriy (CI mock)
if "psycopg2" not in sys.modules:
    import types
    fake = types.ModuleType("psycopg2")
    fake.OperationalError = type("OperationalError", (Exception,), {})
    fake.InterfaceError = type("InterfaceError", (Exception,), {})
    pool = types.ModuleType("psycopg2.pool")
    class ThreadedConnectionPool:  # noqa: D401
        def __init__(self, *a, **k):
            pass
    pool.ThreadedConnectionPool = ThreadedConnectionPool
    fake.pool = pool
    sys.modules["psycopg2"] = fake
    sys.modules["psycopg2.pool"] = pool
    sys.modules.setdefault("pytz", types.SimpleNamespace(timezone=lambda n: None, UTC=None))

import importlib.util  # noqa: E402

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

config = _load("config", os.path.join(ROOT, "config.py"))
STARS_PLANS = config.STARS_PLANS
SUBSCRIPTION_PLANS = config.SUBSCRIPTION_PLANS
PLAN_LIMITS = config.PLAN_LIMITS

# database stub for payment_service
import types
dbstub = types.ModuleType("database")
@contextmanager
def _tx(**k):
    yield MagicMock()
dbstub.db_cursor = _tx
dbstub.PAYMENT_STATUS_SUCCEEDED = "succeeded"
dbstub.PAYMENT_METHOD_UZCARD_HUMO = "uzcard_humo"
dbstub.PAYMENT_METHOD_INTERNATIONAL_STARS = "international_stars"
dbstub.PAYMENT_METHODS = ("uzcard_humo", "international_stars")
dbstub._invalidate_user = lambda *a, **k: None
dbstub._cache_clear = lambda *a, **k: None
dbstub._normalize_language_code = lambda x: "uz"
dbstub.PLAN_LIMITS = PLAN_LIMITS
sys.modules["database"] = dbstub

audit = types.ModuleType("services.audit_service")
class AuditService:
    @staticmethod
    def log_receipt_decision(*a, **k):
        return True
audit.AuditService = AuditService
sys.modules["services.audit_service"] = audit
sys.modules.setdefault("services", types.ModuleType("services"))

ps = _load("services.payment_service", os.path.join(ROOT, "services/payment_service.py"))
PaymentService = ps.PaymentService
RECEIPT_STATUS_PENDING = ps.RECEIPT_STATUS_PENDING

sub = types.SimpleNamespace(
    STARS_PLANS=STARS_PLANS,
    INTL_STARS_AMOUNTS={k: int(SUBSCRIPTION_PLANS[k]["stars"]) for k in ("1m", "3m", "1y")},
)


class TestSsotPlans(unittest.TestCase):
    def test_stars_plans_match_subscription(self):
        self.assertEqual(STARS_PLANS["stars_1m"]["stars"], SUBSCRIPTION_PLANS["1m"]["stars"])
        self.assertEqual(STARS_PLANS["stars_3m"]["stars"], SUBSCRIPTION_PLANS["3m"]["stars"])
        self.assertEqual(STARS_PLANS["stars_1y"]["stars"], SUBSCRIPTION_PLANS["1y"]["stars"])
        self.assertEqual(PaymentService.STARS_PLANS["stars_1m"]["stars"], STARS_PLANS["stars_1m"]["stars"])
        self.assertEqual(sub.STARS_PLANS["stars_1m"]["stars"], STARS_PLANS["stars_1m"]["stars"])
        self.assertEqual(sub.INTL_STARS_AMOUNTS["1m"], STARS_PLANS["stars_1m"]["stars"])

    def test_plan_limits_ssot(self):
        import database as db
        self.assertEqual(db.PLAN_LIMITS["free"]["max_channels"], PLAN_LIMITS["free"]["max_channels"])
        self.assertEqual(db.PLAN_LIMITS["pro"]["daily_ai_requests"], PLAN_LIMITS["pro"]["daily_ai_requests"])


class TestPayloadManipulation(unittest.TestCase):
    """TEST14 — payload/amount/currency soxtalashtirish."""

    def test_wrong_amount(self):
        uid = 111
        payload = f"sub_stars_1m_{uid}"
        info, err = PaymentService.validate_payload(
            payload, user_id=uid, amount=1, currency="XTR",
        )
        self.assertIsNone(info)
        self.assertTrue(err)

    def test_wrong_user(self):
        info, err = PaymentService.validate_payload(
            "sub_stars_1m_111", user_id=222, amount=STARS_PLANS["stars_1m"]["stars"], currency="XTR",
        )
        self.assertIsNone(info)

    def test_wrong_currency(self):
        uid = 111
        info, err = PaymentService.validate_payload(
            f"sub_stars_1m_{uid}", user_id=uid,
            amount=STARS_PLANS["stars_1m"]["stars"], currency="USD",
        )
        self.assertIsNone(info)

    def test_ok(self):
        uid = 111
        stars = STARS_PLANS["stars_1m"]["stars"]
        info, err = PaymentService.validate_payload(
            f"sub_stars_1m_{uid}", user_id=uid, amount=stars, currency="XTR",
        )
        self.assertIsNotNone(info)
        self.assertIsNone(err)
        self.assertEqual(info["days"], 30)

    def test_process_rejects_bad_payload(self):
        res = PaymentService.process_stars_payment(
            111, "chg-bad", 1, "sub_stars_1m_111", "pro", 30, currency="XTR",
        )
        self.assertFalse(res.get("ok"))


class TestStarsIdempotencyMock(unittest.TestCase):
    """TEST1 — 10 parallel: 1 payment, 1 PRO (mock UNIQUE)."""

    def test_ten_parallel_one_insert(self):
        inserted = {"n": 0}

        class Cur:
            def execute(self, sql, params=None):
                self._sql = sql
                self.rowcount = 1
                sql_s = str(sql)
                if "FROM payments WHERE telegram_payment_charge_id" in sql_s and "FOR UPDATE" in sql_s:
                    # PHASE 9: first SELECT returns None (new charge), subsequent returns id
                    if inserted["n"] == 0:
                        self._ret = None
                    else:
                        self._ret = (1,)
                elif "INSERT INTO payments" in sql_s:
                    if inserted["n"] == 0:
                        inserted["n"] = 1
                        self._ret = (1,)
                    else:
                        self._ret = None
                        self.rowcount = 0
                elif "SELECT 1 FROM users" in sql_s:
                    self._ret = (1,)
                else:
                    self._ret = (1,)

            def fetchone(self):
                return self._ret

        class Ctx:
            def __enter__(self):
                return Cur()

            def __exit__(self, *a):
                return False

        with patch("services.payment_service.transaction", lambda: Ctx()), \
             patch("services.payment_service._invalidate_user"), \
             patch("services.payment_service._cache_clear"):
            uid = 4242
            payload = f"sub_stars_1m_{uid}"
            stars = STARS_PLANS["stars_1m"]["stars"]
            charge = "same-charge-id"

            def once(_):
                return PaymentService.process_stars_payment(
                    uid, charge, stars, payload, "pro", 30, currency="XTR",
                )

            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(once, range(10)))
        oks = [r for r in results if r.get("ok") and not r.get("duplicate")]
        dups = [r for r in results if r.get("duplicate")]
        self.assertEqual(len(oks), 1)
        self.assertEqual(len(dups), 9)
        self.assertEqual(inserted["n"], 1)


class TestReceiptPendingOnly(unittest.TestCase):
    """TEST8 — 10× approve: faqat pending, qolganlari rad."""

    def test_second_approve_rejected(self):
        state = {"status": RECEIPT_STATUS_PENDING, "updates": 0}

        class Cur:
            def execute(self, sql, params=None):
                self._sql = sql
                sql_l = str(sql)
                if "FROM payment_receipts" in sql_l and "FOR UPDATE" in sql_l:
                    # PHASE 9: now returns 5 cols (status, user_id, days, amount, order_id)
                    self._ret = (state["status"], 99, 30, 19000, "order-123")
                elif "FROM payment_orders" in sql_l and "FOR UPDATE" in sql_l:
                    self._ret = (state.get("order_status", "pending"),)
                elif "SELECT order_id, status FROM payment_orders" in sql_l:
                    self._ret = None
                    self._rows = []
                elif "UPDATE payment_receipts SET status = 'approved'" in sql_l:
                    if state["status"] != RECEIPT_STATUS_PENDING:
                        self.rowcount = 0
                        self._ret = None
                    else:
                        state["status"] = "approved"
                        state["updates"] += 1
                        self.rowcount = 1
                        self._ret = None
                elif "UPDATE payment_orders SET status = 'approved'" in sql_l:
                    self.rowcount = 1
                    self._ret = None
                elif "UPDATE users SET plan_type" in sql_l:
                    self.rowcount = 1
                    self._ret = None
                elif "SELECT language_code" in sql_l:
                    self._ret = ("uz",)
                else:
                    self.rowcount = 1
                    self._ret = None

            def fetchall(self):
                return getattr(self, "_rows", [])

            def fetchone(self):
                return self._ret

        class Ctx:
            def __enter__(self):
                return Cur()

            def __exit__(self, *a):
                return False

        with patch("services.payment_service.transaction", lambda: Ctx()), \
             patch("services.payment_service.AuditService.log_receipt_decision"), \
             patch("services.payment_service.PaymentService._insert_card_ledger_row", return_value=True), \
             patch("services.payment_service._invalidate_user"), \
             patch("services.payment_service._cache_clear"):
            def once(_):
                return PaymentService.process_receipt(7, 1, True)

            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(once, range(10)))
        ok = [r for r in results if r.get("ok")]
        denied = [r for r in results if not r.get("ok")]
        self.assertEqual(len(ok), 1)
        self.assertEqual(len(denied), 9)
        self.assertEqual(state["updates"], 1)
        self.assertTrue(all(
            r.get("reason") in ("already_approved", "already_reviewed") for r in denied
        ))


if __name__ == "__main__":
    unittest.main()
