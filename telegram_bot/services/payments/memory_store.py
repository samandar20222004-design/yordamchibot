"""In-memory Payme store — for tests and local sandboxes only.

It mirrors the PostgreSQL guarantees the provider relies on:

* ``atomic()`` is serialisable (one re-entrant lock) and rolls back every
  change when the block raises — like a real DB transaction;
* ``payme_id`` is unique and only one active (state 1/2) transaction may
  exist per order (``insert_transaction`` returns ``None`` on conflict, just
  like ``INSERT … ON CONFLICT DO NOTHING RETURNING id``);
* the ledger key ``payme:<id>`` is unique, so a second grant is impossible.

Production code uses :class:`repositories.payme_repository.PostgresPaymeStore`.
"""

from __future__ import annotations

import copy
import threading
from contextlib import contextmanager
from dataclasses import replace

from services.payments.payme_provider import (
    STATE_CREATED,
    STATE_PERFORMED,
    PaymeEvent,
    PaymeOrder,
    PaymeTransaction,
)


class _MemoryUnitOfWork:
    def __init__(self, store: "InMemoryPaymeStore") -> None:
        self._s = store

    def get_order(self, order_id, *, lock=False):
        return self._s.orders.get(order_id)

    def get_transaction(self, payme_id, *, lock=False):
        return self._s.transactions.get(payme_id)

    def get_active_transaction_for_order(self, order_id):
        for tx in self._s.transactions.values():
            if tx.order_id == order_id and tx.state in (STATE_CREATED, STATE_PERFORMED):
                return tx
        return None

    def insert_transaction(self, tx):
        if tx.payme_id in self._s.transactions:
            return None
        if self.get_active_transaction_for_order(tx.order_id) is not None:
            return None
        self._s.seq += 1
        stored = replace(tx, id=self._s.seq)
        self._s.transactions[tx.payme_id] = stored
        return stored

    def save_transaction(self, tx):
        current = self._s.transactions[tx.payme_id]
        self._s.transactions[tx.payme_id] = replace(
            current,
            state=tx.state,
            reason=tx.reason,
            perform_time=tx.perform_time,
            cancel_time=tx.cancel_time,
        )

    def set_order_status(self, order_id, status):
        order = self._s.orders.get(order_id)
        if order is not None:
            self._s.orders[order_id] = replace(order, status=status)

    def record_ledger(self, tx, order):
        if tx.ledger_key in self._s.ledger:
            return False
        self._s.ledger[tx.ledger_key] = {
            "user_id": order.user_id,
            "amount": order.amount_uzs,
            "currency": "UZS",
            "status": "succeeded",
            "payload": f"payme:{order.order_id}",
        }
        return True

    def refund_ledger(self, tx):
        row = self._s.ledger.get(tx.ledger_key)
        if row is not None:
            row["status"] = "refunded"

    def grant_subscription(self, user_id, days):
        self._s.subscription_days[user_id] = self._s.subscription_days.get(user_id, 0) + int(days)
        self._s.grants.append((int(user_id), int(days)))
        return True

    def revoke_subscription(self, user_id, days):
        current = self._s.subscription_days.get(user_id, 0)
        self._s.subscription_days[user_id] = max(0, current - int(days))

    def list_transactions(self, from_ms, to_ms):
        rows = [tx for tx in self._s.transactions.values() if from_ms <= tx.payme_time <= to_ms]
        return sorted(rows, key=lambda tx: (tx.payme_time, tx.id or 0))


class InMemoryPaymeStore:
    """Thread-safe, transactional in-memory implementation of ``PaymeStore``."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.orders: dict[str, PaymeOrder] = {}
        self.transactions: dict[str, PaymeTransaction] = {}
        self.ledger: dict[str, dict] = {}
        self.subscription_days: dict[int, int] = {}
        self.grants: list[tuple[int, int]] = []
        self.after_commit_events: list[PaymeEvent] = []
        self.seq = 0

    _STATE = ("orders", "transactions", "ledger", "subscription_days", "grants", "seq")

    @contextmanager
    def atomic(self):
        with self._lock:
            snapshot = {name: copy.deepcopy(getattr(self, name)) for name in self._STATE}
            try:
                yield _MemoryUnitOfWork(self)
            except BaseException:
                for name, value in snapshot.items():
                    setattr(self, name, value)
                raise

    def create_order(self, order: PaymeOrder) -> PaymeOrder:
        with self._lock:
            if order.order_id in self.orders:
                raise ValueError("duplicate order id")
            self.orders[order.order_id] = order
            return order

    def after_commit(self, event: PaymeEvent) -> None:
        self.after_commit_events.append(event)


__all__ = ["InMemoryPaymeStore"]
