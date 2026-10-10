# -*- coding: utf-8 -*-
"""
=====================================================================
 💳 PAYME — merchant orders, transactions and the PRO grant (PostgreSQL)
=====================================================================

Persistence for :mod:`services.payments.payme_provider`. Every provider
method runs inside ONE ``db_transaction`` (``PostgresPaymeStore.atomic``):

* rows are locked in a fixed order — ``payme_orders`` → ``payme_transactions``
  → ``payments`` (insert) → ``users`` (update) — so concurrent duplicate
  callbacks serialise instead of deadlocking;
* ``payme_transactions.payme_transaction_id`` is UNIQUE and the partial
  UNIQUE index ``uq_payme_tx_active_order`` allows only one active (state
  1/2) transaction per order — ``INSERT … ON CONFLICT DO NOTHING`` turns a
  lost race into "no row" instead of an exception;
* the ledger row in ``payments`` uses the existing UNIQUE
  ``telegram_payment_charge_id`` (``payme:<id>``): PRO is only extended when
  that insert really created a row.

Ledger compatibility: rows are written with ``currency='UZS'`` and
``payment_method='uzcard_humo'`` (Payme settles local Uzcard/Humo cards in
so'm), so existing history screens, reports and the frozen
``PAYMENT_METHODS`` tuple keep working unchanged; the ``payme:`` charge-key
prefix identifies the provider.

Like the other repositories, the core helpers are late-bound through
``repositories.runtime`` so ``patch("database.db_transaction")`` still works.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import replace

from repositories.runtime import (  # noqa: F401
    _cache_clear, _invalidate_user, db_transaction
)
from services.payments.payme_provider import (
    STATE_TO_STATUS,
    PaymeEvent,
    PaymeOrder,
    PaymeTransaction,
)

logger = logging.getLogger(__name__)

#: Ledger usul ajratgichi — mavjud PAYMENT_METHODS to'plamidan (o'zgarmaydi).
PAYME_LEDGER_METHOD = "uzcard_humo"

_TX_COLUMNS = (
    "id, payme_transaction_id, order_id, user_id, amount_tiyin, state, reason, "
    "payme_time, create_time, perform_time, cancel_time"
)
_ORDER_COLUMNS = "order_id, user_id, plan_key, days, amount_tiyin, status"


def _row_to_order(row) -> PaymeOrder | None:
    if not row:
        return None
    return PaymeOrder(
        order_id=str(row[0]),
        user_id=int(row[1]),
        plan_key=str(row[2]),
        days=int(row[3]),
        amount_tiyin=int(row[4]),
        status=str(row[5]),
    )


def _row_to_transaction(row) -> PaymeTransaction | None:
    if not row:
        return None
    return PaymeTransaction(
        id=int(row[0]),
        payme_id=str(row[1]),
        order_id=str(row[2]),
        user_id=int(row[3]),
        amount_tiyin=int(row[4]),
        state=int(row[5]),
        reason=None if row[6] is None else int(row[6]),
        payme_time=int(row[7]),
        create_time=int(row[8]),
        perform_time=int(row[9] or 0),
        cancel_time=int(row[10] or 0),
    )


class PostgresPaymeUnitOfWork:
    """All operations share the cursor of the surrounding transaction."""

    def __init__(self, cur) -> None:
        self.cur = cur

    def get_order(self, order_id: str, *, lock: bool = False) -> PaymeOrder | None:
        self.cur.execute(
            f"SELECT {_ORDER_COLUMNS} FROM payme_orders WHERE order_id = %s"  # nosec B608 — jadval/ustun nomlari kod-konstanta; qiymatlar parametrlangan
            + (" FOR UPDATE" if lock else ""),
            (order_id,),
        )
        return _row_to_order(self.cur.fetchone())

    def get_transaction(self, payme_id: str, *, lock: bool = False) -> PaymeTransaction | None:
        self.cur.execute(
            f"SELECT {_TX_COLUMNS} FROM payme_transactions WHERE payme_transaction_id = %s"  # nosec B608 — jadval/ustun nomlari kod-konstanta; qiymatlar parametrlangan
            + (" FOR UPDATE" if lock else ""),
            (payme_id,),
        )
        return _row_to_transaction(self.cur.fetchone())

    def get_active_transaction_for_order(self, order_id: str) -> PaymeTransaction | None:
        self.cur.execute(
            f"SELECT {_TX_COLUMNS} FROM payme_transactions "  # nosec B608 — jadval/ustun nomlari kod-konstanta; qiymatlar parametrlangan
            "WHERE order_id = %s AND state IN (1, 2) ORDER BY id LIMIT 1 FOR UPDATE",
            (order_id,),
        )
        return _row_to_transaction(self.cur.fetchone())

    def insert_transaction(self, tx: PaymeTransaction) -> PaymeTransaction | None:
        # No conflict target: covers BOTH the UNIQUE payme id and the partial
        # UNIQUE "one active transaction per order" index.
        self.cur.execute(
            "INSERT INTO payme_transactions (payme_transaction_id, order_id, user_id, "
            "amount_tiyin, status, state, payme_time, create_time) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (tx.payme_id, tx.order_id, int(tx.user_id), int(tx.amount_tiyin),
             tx.status, int(tx.state), int(tx.payme_time), int(tx.create_time)),
        )
        row = self.cur.fetchone()
        if not row:
            return None
        return replace(tx, id=int(row[0]))

    def save_transaction(self, tx: PaymeTransaction) -> None:
        self.cur.execute(
            "UPDATE payme_transactions SET state = %s, status = %s, reason = %s, "
            "perform_time = %s, cancel_time = %s, updated_at = NOW() "
            "WHERE payme_transaction_id = %s",
            (int(tx.state), STATE_TO_STATUS[tx.state], tx.reason,
             int(tx.perform_time), int(tx.cancel_time), tx.payme_id),
        )

    def set_order_status(self, order_id: str, status: str) -> None:
        self.cur.execute(
            "UPDATE payme_orders SET status = %s, "
            "paid_at = CASE WHEN %s = 'paid' THEN NOW() ELSE paid_at END, "
            "cancelled_at = CASE WHEN %s = 'cancelled' THEN NOW() ELSE cancelled_at END "
            "WHERE order_id = %s",
            (status, status, status, order_id),
        )

    def record_ledger(self, tx: PaymeTransaction, order: PaymeOrder) -> bool:
        self.cur.execute(
            "INSERT INTO payments (user_id, amount, currency, payload, "
            "telegram_payment_charge_id, status, payment_method) "
            "VALUES (%s, %s, 'UZS', %s, %s, 'succeeded', %s) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (int(order.user_id), int(order.amount_uzs), f"payme:{order.order_id}",
             tx.ledger_key, PAYME_LEDGER_METHOD),
        )
        return bool(self.cur.fetchone())

    def refund_ledger(self, tx: PaymeTransaction) -> None:
        self.cur.execute(
            "UPDATE payments SET status = 'refunded' WHERE telegram_payment_charge_id = %s",
            (tx.ledger_key,),
        )

    def grant_subscription(self, user_id: int, days: int) -> bool:
        # Same additive formula as Stars / approved receipts.
        self.cur.execute(
            "UPDATE users SET plan_type = 'pro', "
            "subscription_expires_at = GREATEST("
            "COALESCE(subscription_expires_at, NOW()), NOW()) "
            "+ (%s || ' days')::INTERVAL "
            "WHERE user_id = %s",
            (str(int(days)), int(user_id)),
        )
        granted = (self.cur.rowcount or 0) > 0
        if not granted:
            logger.warning("Payme grant: user row missing", extra={"event": "payme_grant_no_user"})
        return granted

    def revoke_subscription(self, user_id: int, days: int) -> None:
        self.cur.execute(
            "UPDATE users SET "
            "plan_type = CASE WHEN subscription_expires_at IS NULL "
            "  OR subscription_expires_at - (%s || ' days')::INTERVAL <= NOW() "
            "  THEN 'free' ELSE plan_type END, "
            "subscription_expires_at = CASE WHEN subscription_expires_at IS NULL THEN NULL "
            "  ELSE GREATEST(NOW(), subscription_expires_at - (%s || ' days')::INTERVAL) END "
            "WHERE user_id = %s",
            (str(int(days)), str(int(days)), int(user_id)),
        )

    def list_transactions(self, from_ms: int, to_ms: int) -> list[PaymeTransaction]:
        self.cur.execute(
            f"SELECT {_TX_COLUMNS} FROM payme_transactions "  # nosec B608 — jadval/ustun nomlari kod-konstanta; qiymatlar parametrlangan
            "WHERE payme_time BETWEEN %s AND %s ORDER BY payme_time, id",
            (int(from_ms), int(to_ms)),
        )
        return [_row_to_transaction(r) for r in self.cur.fetchall()]


class PostgresPaymeStore:
    """Production ``PaymeStore`` backed by the shared psycopg2 pool."""

    @contextmanager
    def atomic(self):
        with db_transaction(commit=True) as cur:
            yield PostgresPaymeUnitOfWork(cur)

    def create_order(self, order: PaymeOrder) -> PaymeOrder:
        with db_transaction(commit=True) as cur:
            cur.execute(
                "INSERT INTO payme_orders (order_id, user_id, plan_key, days, amount_tiyin, status) "
                "VALUES (%s, %s, %s, %s, %s, 'pending')",
                (order.order_id, int(order.user_id), order.plan_key,
                 int(order.days), int(order.amount_tiyin)),
            )
        return order

    def after_commit(self, event: PaymeEvent) -> None:
        _invalidate_user(int(event.user_id))
        _cache_clear("system_stats")
        _cache_clear("admin_dashboard_stats")


def create_payme_order(user_id: int, plan_key: str, days: int, amount_uzs: int):
    """Sync helper for handlers (``await db.run_db(create_payme_order, ...)``).

    Returns the :class:`PaymeOrder` or ``None`` on any database failure — the
    payment screen then simply omits the Payme button (fail-soft).
    """
    from services.payments.payme_provider import PaymeProvider

    try:
        return PaymeProvider(PostgresPaymeStore()).create_order(user_id, plan_key, days, amount_uzs)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Payme order yaratilmadi: %s", type(exc).__name__)
        return None


__all__ = [
    "PAYME_LEDGER_METHOD",
    "PostgresPaymeStore",
    "PostgresPaymeUnitOfWork",
    "create_payme_order",
]
