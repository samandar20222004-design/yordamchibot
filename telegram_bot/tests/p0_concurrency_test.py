"""PostAssist V2 P0 regression/concurrency tests.

These tests use a real PostgreSQL instance because row locks and unique
constraints cannot be faithfully tested with a mock.  Set P0_TEST_DATABASE_URL
(or DATABASE_URL) to run them, for example::

    P0_TEST_DATABASE_URL=postgresql://... pytest tests/p0_concurrency_test.py -q

Without a PostgreSQL URL the integration tests are skipped rather than making
local unit-test runs fail.  Each test uses random IDs/codes and cleans up its
own rows.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
import sys
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

import database as db  # noqa: E402


@pytest.fixture(scope="session")
def p0_db():
    url = os.getenv("P0_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url or "user:pass" in url:
        pytest.skip("P0_TEST_DATABASE_URL is not configured")
    db.DATABASE_URL = url
    db._reset_pool()
    try:
        db.init_db()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"PostgreSQL is unavailable: {exc}")
    yield db
    db.close_pool()


def _user(db_mod, user_id):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, plan_type) VALUES (%s, %s, 'free') "
            "ON CONFLICT (user_id) DO UPDATE SET plan_type = 'free', subscription_expires_at = NULL",
            (user_id, f"p0_{user_id}"),
        )


def _cleanup(db_mod, user_ids=(), code=None):
    with db_mod.db_cursor(commit=True) as cur:
        if user_ids:
            cur.execute("DELETE FROM promo_redemptions WHERE user_id = ANY(%s)", (list(user_ids),))
            cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (list(user_ids),))
        if code:
            cur.execute("DELETE FROM promo_codes WHERE code = %s", (code,))


def test_one_payment_replayed_five_times_grants_once(p0_db):
    user_id = 810000000 + (os.getpid() % 100000)
    charge = f"p0-charge-{uuid.uuid4().hex}"
    _user(p0_db, user_id)
    try:
        def pay(_):
            return p0_db.process_stars_payment(
                user_id, 75, "XTR", f"sub_stars_1m_{user_id}", charge,
                "pro", 30,
            )

        with ThreadPoolExecutor(max_workers=5) as pool:
            results = list(pool.map(pay, range(5)))
        assert sum(bool(r.get("ok") and not r.get("duplicate")) for r in results) == 1
        assert sum(bool(r.get("duplicate")) for r in results) == 4
        with p0_db.db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*), subscription_expires_at FROM payments p "
                "JOIN users u ON u.user_id = p.user_id "
                "WHERE p.telegram_payment_charge_id = %s GROUP BY subscription_expires_at",
                (charge,),
            )
            count, _expiry = cur.fetchone()
        assert count == 1
    finally:
        _cleanup(p0_db, [user_id])


def test_ten_users_race_for_one_promo_only_one_wins(p0_db):
    code = f"P0_{uuid.uuid4().hex[:20]}".upper()
    user_ids = [820000000 + i + (os.getpid() % 1000) * 100 for i in range(10)]
    for uid in user_ids:
        _user(p0_db, uid)
    assert p0_db.create_promo_code(code, "pro", 30, 1)
    try:
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda uid: p0_db.redeem_promo_code(uid, code), user_ids))
        assert sum(ok for ok, _message in results) == 1
        with p0_db.db_cursor() as cur:
            cur.execute("SELECT current_uses FROM promo_codes WHERE code = %s", (code,))
            assert cur.fetchone()[0] == 1
    finally:
        _cleanup(p0_db, user_ids, code)


def test_same_user_cannot_redeem_same_promo_twice(p0_db):
    code = f"P0_{uuid.uuid4().hex[:20]}".upper()
    user_id = 830000000 + (os.getpid() % 100000)
    _user(p0_db, user_id)
    assert p0_db.create_promo_code(code, "pro", 30, 10)
    try:
        first = p0_db.redeem_promo_code(user_id, code)
        second = p0_db.redeem_promo_code(user_id, code)
        assert first[0] is True
        assert second[0] is False
        assert "avval" in second[1]
    finally:
        _cleanup(p0_db, [user_id], code)


def test_scheduler_restart_does_not_send_sent_delivery_twice(p0_db):
    post_id = 840000000 + (os.getpid() % 100000)
    channel_id = -1000000000000 - (os.getpid() % 100000)
    scheduled = datetime.now(timezone.utc)
    first = p0_db.claim_post_delivery(post_id, channel_id, scheduled)
    assert first["claimed"] is True
    key = first["idempotency_key"]
    assert p0_db.mark_post_delivery_sent(key, 991337)

    # A second scheduler process/restart sees the durable sent marker and must
    # skip before calling Telegram.
    second = p0_db.claim_post_delivery(post_id, channel_id, scheduled)
    assert second["sent"] is True
    assert second["claimed"] is False
    with p0_db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM post_deliveries WHERE idempotency_key = %s", (key,))
