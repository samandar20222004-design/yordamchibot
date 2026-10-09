"""Payme Merchant API provider — JSON-RPC state machine.

Payme (paycom.uz) drives the payment by calling the merchant's endpoint with
JSON-RPC requests authenticated by HTTP Basic Auth (``Paycom:<merchant key>``).
This module implements the merchant side:

==========================  ==================================================
``CheckPerformTransaction``  can this order be paid with this amount?
``CreateTransaction``        reserve the order for one Payme transaction
``PerformTransaction``       money captured → grant PRO **exactly once**
``CancelTransaction``        cancel (state 1) or refund (state 2, opt-in)
``CheckTransaction``         read-only status (required by the Payme sandbox)
``GetStatement``             reconciliation list (required by the sandbox)
==========================  ==================================================

Idempotency is enforced at three levels, so duplicate callbacks can never
grant a second subscription:

1. **State machine** — ``PerformTransaction`` on an already performed
   transaction returns the stored result without touching the subscription.
2. **Row locks** — every mutating method runs in ONE database transaction
   and locks ``payme_orders`` → ``payme_transactions`` (always in that order,
   so concurrent callbacks serialise without deadlocks).
3. **Database constraints** — ``payme_transactions.payme_transaction_id`` is
   UNIQUE, a partial UNIQUE index allows only one active (state 1/2)
   transaction per order, and the ``payments`` ledger row uses the UNIQUE
   ``telegram_payment_charge_id = 'payme:<id>'`` key; the subscription is only
   extended when that ledger insert actually created a new row.

Transaction ``status`` mirrors the Payme ``state`` for humans/reporting:
``pending`` (1) → ``paid`` (2) → ``cancelled`` (-1 / -2).

The module is pure standard library: persistence goes through a small store
protocol (``PostgresPaymeStore`` in production, ``InMemoryPaymeStore`` in
tests), and it never logs credentials, card data or raw request bodies.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os
import secrets
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Protocol

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Payme protocol constants
# ---------------------------------------------------------------------------
STATE_CREATED = 1
STATE_PERFORMED = 2
STATE_CANCELLED = -1
STATE_CANCELLED_AFTER_PERFORM = -2
VALID_STATES = (STATE_CREATED, STATE_PERFORMED, STATE_CANCELLED, STATE_CANCELLED_AFTER_PERFORM)

STATUS_PENDING = "pending"
STATUS_PAID = "paid"
STATUS_CANCELLED = "cancelled"
STATUSES = (STATUS_PENDING, STATUS_PAID, STATUS_CANCELLED)

STATE_TO_STATUS = {
    STATE_CREATED: STATUS_PENDING,
    STATE_PERFORMED: STATUS_PAID,
    STATE_CANCELLED: STATUS_CANCELLED,
    STATE_CANCELLED_AFTER_PERFORM: STATUS_CANCELLED,
}

#: Payme cancel reasons used by the merchant itself.
REASON_TIMEOUT = 4
REASON_REFUND = 5

#: A created transaction must be performed within 12 hours (Payme spec).
TRANSACTION_TIMEOUT_MS = 12 * 60 * 60 * 1000

#: Payme identifiers are 24-char hex strings; keep a generous safety cap.
MAX_ID_LENGTH = 64

ERR_TRANSPORT = -32300
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INSUFFICIENT_PRIVILEGE = -32504
ERR_SYSTEM = -32400
ERR_INVALID_AMOUNT = -31001
ERR_TRANSACTION_NOT_FOUND = -31003
ERR_CANNOT_CANCEL = -31007
ERR_CANNOT_PERFORM = -31008
# -31050 … -31099: account (order) errors — ``data`` carries the field name.
ERR_ORDER_NOT_FOUND = -31050
ERR_ORDER_NOT_PAYABLE = -31051
ERR_ORDER_BUSY = -31052

_ERROR_MESSAGES: dict[int, dict[str, str]] = {
    ERR_TRANSPORT: {
        "uz": "So'rov usuli POST emas.",
        "ru": "Метод запроса не POST.",
        "en": "Request method must be POST.",
    },
    ERR_PARSE: {
        "uz": "JSON so'rovni o'qib bo'lmadi.",
        "ru": "Ошибка разбора JSON.",
        "en": "Could not parse JSON.",
    },
    ERR_INVALID_REQUEST: {
        "uz": "So'rov maydonlari noto'g'ri.",
        "ru": "Неверные поля запроса.",
        "en": "Invalid request fields.",
    },
    ERR_METHOD_NOT_FOUND: {
        "uz": "Metod topilmadi.",
        "ru": "Метод не найден.",
        "en": "Method not found.",
    },
    ERR_INSUFFICIENT_PRIVILEGE: {
        "uz": "Ruxsat yetarli emas.",
        "ru": "Недостаточно привилегий.",
        "en": "Insufficient privileges.",
    },
    ERR_SYSTEM: {
        "uz": "Ichki tizim xatosi.",
        "ru": "Внутренняя ошибка системы.",
        "en": "Internal system error.",
    },
    ERR_INVALID_AMOUNT: {
        "uz": "To'lov summasi noto'g'ri.",
        "ru": "Неверная сумма платежа.",
        "en": "Invalid amount.",
    },
    ERR_TRANSACTION_NOT_FOUND: {
        "uz": "Tranzaksiya topilmadi.",
        "ru": "Транзакция не найдена.",
        "en": "Transaction not found.",
    },
    ERR_CANNOT_CANCEL: {
        "uz": "Xizmat ko'rsatilgan, tranzaksiyani bekor qilib bo'lmaydi.",
        "ru": "Услуга оказана, отмена транзакции невозможна.",
        "en": "Service already delivered; the transaction cannot be cancelled.",
    },
    ERR_CANNOT_PERFORM: {
        "uz": "Ushbu amalni bajarib bo'lmaydi.",
        "ru": "Невозможно выполнить операцию.",
        "en": "Unable to perform the operation.",
    },
    ERR_ORDER_NOT_FOUND: {
        "uz": "Buyurtma topilmadi.",
        "ru": "Заказ не найден.",
        "en": "Order not found.",
    },
    ERR_ORDER_NOT_PAYABLE: {
        "uz": "Buyurtma allaqachon to'langan yoki bekor qilingan.",
        "ru": "Заказ уже оплачен или отменён.",
        "en": "Order is already paid or cancelled.",
    },
    ERR_ORDER_BUSY: {
        "uz": "Buyurtma bo'yicha boshqa to'lov jarayonda.",
        "ru": "По заказу уже выполняется другой платёж.",
        "en": "Another payment for this order is in progress.",
    },
}


class PaymeError(Exception):
    """A Payme JSON-RPC error (always answered with HTTP 200)."""

    def __init__(self, code: int, data: Any = None) -> None:
        self.code = int(code)
        self.data = data
        super().__init__(f"Payme error {self.code}")

    @property
    def message(self) -> dict[str, str]:
        return dict(_ERROR_MESSAGES.get(self.code, _ERROR_MESSAGES[ERR_SYSTEM]))

    def to_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            error["data"] = self.data
        return error


def error_response(request_id: Any, error: PaymeError) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": error.to_dict()}


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


# ---------------------------------------------------------------------------
# Configuration & authentication
# ---------------------------------------------------------------------------
def _env_flag(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PaymeConfig:
    """Merchant settings. ``key`` is a secret and is never logged or echoed."""

    merchant_id: str = ""
    key: str = ""
    login: str = "Paycom"
    account_field: str = "order_id"
    checkout_url: str = "https://checkout.paycom.uz"
    allow_refunds: bool = False
    timeout_ms: int = TRANSACTION_TIMEOUT_MS

    @classmethod
    def from_env(cls) -> "PaymeConfig":
        return cls(
            merchant_id=(os.getenv("PAYME_MERCHANT_ID", "") or "").strip(),
            key=(os.getenv("PAYME_KEY", "") or "").strip(),
            login=(os.getenv("PAYME_LOGIN", "") or "").strip() or "Paycom",
            account_field=(os.getenv("PAYME_ACCOUNT_FIELD", "") or "").strip() or "order_id",
            checkout_url=(os.getenv("PAYME_CHECKOUT_URL", "") or "").strip()
            or "https://checkout.paycom.uz",
            allow_refunds=_env_flag(os.getenv("PAYME_ALLOW_REFUNDS", "0")),
        )

    @property
    def auth_configured(self) -> bool:
        """Callbacks are accepted only when a merchant key is provisioned."""
        return bool(self.key)

    @property
    def checkout_enabled(self) -> bool:
        """The bot offers the Payme button only when both halves are set."""
        return bool(self.merchant_id and self.key)

    def __repr__(self) -> str:  # never leak the key through repr/logging
        return (
            f"PaymeConfig(merchant_id={self.merchant_id!r}, key={'***' if self.key else ''!r}, "
            f"login={self.login!r}, account_field={self.account_field!r}, "
            f"allow_refunds={self.allow_refunds!r})"
        )


def verify_basic_auth(authorization: str | None, config: PaymeConfig) -> bool:
    """Constant-time check of ``Authorization: Basic base64(login:key)``.

    Fails closed when no key is configured, the scheme is not Basic, the
    token is not valid base64/UTF-8, or either half does not match.
    """
    if not config.auth_configured:
        return False
    raw = str(authorization or "").strip()
    scheme, _, token = raw.partition(" ")
    token = token.strip()
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False
    login, sep, password = decoded.partition(":")
    if not sep:
        return False
    # Evaluate both comparisons (no short-circuit) to keep timing uniform.
    login_ok = hmac.compare_digest(login.encode("utf-8"), config.login.encode("utf-8"))
    key_ok = hmac.compare_digest(password.encode("utf-8"), config.key.encode("utf-8"))
    return bool(login_ok & key_ok)


def basic_auth_header(login: str, key: str) -> str:
    """Build the header value Payme sends (handy for tests and smoke checks)."""
    token = base64.b64encode(f"{login}:{key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


# ---------------------------------------------------------------------------
# Domain records
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class PaymeOrder:
    order_id: str
    user_id: int
    plan_key: str
    days: int
    amount_tiyin: int
    status: str = STATUS_PENDING

    @property
    def amount_uzs(self) -> int:
        return int(self.amount_tiyin) // 100


@dataclass(frozen=True)
class PaymeTransaction:
    payme_id: str
    order_id: str
    user_id: int
    amount_tiyin: int
    state: int
    payme_time: int
    create_time: int
    perform_time: int = 0
    cancel_time: int = 0
    reason: int | None = None
    id: int | None = None

    @property
    def status(self) -> str:
        return STATE_TO_STATUS[self.state]

    @property
    def ledger_key(self) -> str:
        """UNIQUE ``payments.telegram_payment_charge_id`` for this payment."""
        return f"payme:{self.payme_id}"


@dataclass(frozen=True)
class PaymeEvent:
    """Post-commit side effect (user notification / cache invalidation)."""

    kind: str  # "paid" | "refunded"
    user_id: int
    days: int
    order_id: str


@dataclass
class PaymeOutcome:
    response: dict[str, Any] = field(default_factory=dict)
    events: list[PaymeEvent] = field(default_factory=list)

    @property
    def paid_events(self) -> list[PaymeEvent]:
        return [e for e in self.events if e.kind == "paid"]


# ---------------------------------------------------------------------------
# Persistence protocol
# ---------------------------------------------------------------------------
class PaymeUnitOfWork(Protocol):  # pragma: no cover - typing contract only
    def get_order(self, order_id: str, *, lock: bool = False) -> PaymeOrder | None: ...
    def get_transaction(self, payme_id: str, *, lock: bool = False) -> PaymeTransaction | None: ...
    def get_active_transaction_for_order(self, order_id: str) -> PaymeTransaction | None: ...
    def insert_transaction(self, tx: PaymeTransaction) -> PaymeTransaction | None: ...
    def save_transaction(self, tx: PaymeTransaction) -> None: ...
    def set_order_status(self, order_id: str, status: str) -> None: ...
    def record_ledger(self, tx: PaymeTransaction, order: PaymeOrder) -> bool: ...
    def refund_ledger(self, tx: PaymeTransaction) -> None: ...
    def grant_subscription(self, user_id: int, days: int) -> bool: ...
    def revoke_subscription(self, user_id: int, days: int) -> None: ...
    def list_transactions(self, from_ms: int, to_ms: int) -> list[PaymeTransaction]: ...


class PaymeStore(Protocol):  # pragma: no cover - typing contract only
    def atomic(self) -> AbstractContextManager[PaymeUnitOfWork]: ...
    def create_order(self, order: PaymeOrder) -> PaymeOrder: ...
    def after_commit(self, event: PaymeEvent) -> None: ...


def _default_store() -> PaymeStore:
    from repositories.payme_repository import PostgresPaymeStore

    return PostgresPaymeStore()


# ---------------------------------------------------------------------------
# Parameter validation helpers
# ---------------------------------------------------------------------------
def _require_int(params: dict, name: str, *, positive: bool = False) -> int:
    value = params.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaymeError(ERR_INVALID_REQUEST, data=name)
    if isinstance(value, float):
        if not value.is_integer():
            raise PaymeError(ERR_INVALID_REQUEST, data=name)
        value = int(value)
    if positive and value <= 0:
        raise PaymeError(ERR_INVALID_REQUEST, data=name)
    return int(value)


def _require_amount(params: dict) -> int:
    value = params.get("amount")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PaymeError(ERR_INVALID_REQUEST, data="amount")
    if isinstance(value, float) and not value.is_integer():
        raise PaymeError(ERR_INVALID_AMOUNT, data="amount")
    if int(value) <= 0:
        raise PaymeError(ERR_INVALID_AMOUNT, data="amount")
    return int(value)


def _require_payme_id(params: dict) -> str:
    value = params.get("id")
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_ID_LENGTH:
        raise PaymeError(ERR_INVALID_REQUEST, data="id")
    return value.strip()


def new_order_id() -> str:
    """Opaque, unguessable order identifier used in ``ac.order_id``."""
    return "pm" + secrets.token_hex(10)


def build_checkout_url(
    config: PaymeConfig,
    order: PaymeOrder,
    *,
    lang: str = "uz",
    return_url: str | None = None,
) -> str:
    """Payme checkout link: ``<checkout>/<base64(m=..;ac.order_id=..;a=..)>``."""
    if not config.merchant_id:
        raise ValueError("PAYME_MERCHANT_ID is not configured")
    parts = [
        f"m={config.merchant_id}",
        f"ac.{config.account_field}={order.order_id}",
        f"a={int(order.amount_tiyin)}",
    ]
    code = str(lang or "uz").strip().lower().split("-")[0]
    if code in {"uz", "ru", "en"}:
        parts.append(f"l={code}")
    if return_url and ";" not in return_url:
        parts.append(f"c={return_url}")
    encoded = base64.b64encode(";".join(parts).encode("utf-8")).decode("ascii")
    return f"{config.checkout_url.rstrip('/')}/{encoded}"


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------
class PaymeProvider:
    """Stateless JSON-RPC dispatcher over a :class:`PaymeStore`.

    ``handle`` is synchronous (psycopg2) — async callers should run it in a
    worker thread (see :mod:`services.payments.payme_webhook`).
    """

    METHODS = (
        "CheckPerformTransaction",
        "CreateTransaction",
        "PerformTransaction",
        "CancelTransaction",
        "CheckTransaction",
        "GetStatement",
    )

    def __init__(
        self,
        store: PaymeStore | None = None,
        config: PaymeConfig | None = None,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self._store = store
        self.config = config if config is not None else PaymeConfig.from_env()
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._dispatch: dict[str, Callable[[dict, PaymeOutcome], dict]] = {
            "CheckPerformTransaction": self.check_perform_transaction,
            "CreateTransaction": self.create_transaction,
            "PerformTransaction": self.perform_transaction,
            "CancelTransaction": self.cancel_transaction,
            "CheckTransaction": self.check_transaction,
            "GetStatement": self.get_statement,
        }

    # -- plumbing ---------------------------------------------------------
    @property
    def store(self) -> PaymeStore:
        if self._store is None:
            self._store = _default_store()
        return self._store

    def now_ms(self) -> int:
        return int(self._clock())

    def handle(self, payload: Any, *, authorization: str | None) -> PaymeOutcome:
        """Authenticate, validate and dispatch one JSON-RPC request.

        Never raises: every failure becomes a JSON-RPC error object.
        """
        request_id = payload.get("id") if isinstance(payload, dict) else None
        if isinstance(request_id, (dict, list)):
            request_id = None
        method = payload.get("method") if isinstance(payload, dict) else None
        try:
            if not verify_basic_auth(authorization, self.config):
                raise PaymeError(ERR_INSUFFICIENT_PRIVILEGE)
            if not isinstance(payload, dict) or not isinstance(method, str) or not method:
                raise PaymeError(ERR_INVALID_REQUEST)
            handler = self._dispatch.get(method)
            if handler is None:
                raise PaymeError(ERR_METHOD_NOT_FOUND, data=method[:64])
            params = payload.get("params")
            if not isinstance(params, dict):
                raise PaymeError(ERR_INVALID_REQUEST, data="params")
            outcome = PaymeOutcome()
            result = handler(params, outcome)
            outcome.response = result_response(request_id, result)
            self._run_after_commit(outcome)
            return outcome
        except PaymeError as exc:
            logger.info("Payme RPC rejected", extra={
                "event": "payme_rpc_error",
                "method": str(method or "")[:64],
                "error_code": exc.code,
            })
            return PaymeOutcome(response=error_response(request_id, exc))
        except Exception:  # noqa: BLE001 — Payme must always get a JSON answer
            logger.exception("Payme RPC internal failure", extra={
                "event": "payme_rpc_failure",
                "method": str(method or "")[:64],
            })
            return PaymeOutcome(response=error_response(request_id, PaymeError(ERR_SYSTEM)))

    def _run_after_commit(self, outcome: PaymeOutcome) -> None:
        hook = getattr(self.store, "after_commit", None)
        if not callable(hook):
            return
        for event in outcome.events:
            try:
                hook(event)
            except Exception:  # noqa: BLE001 — cache hygiene must not fail payment
                logger.warning("Payme after-commit hook failed", exc_info=True)

    def _account_order_id(self, params: dict) -> str:
        account = params.get("account")
        if not isinstance(account, dict):
            raise PaymeError(ERR_INVALID_REQUEST, data="account")
        field_name = self.config.account_field
        raw = account.get(field_name)
        if isinstance(raw, bool) or not isinstance(raw, (str, int)):
            raise PaymeError(ERR_ORDER_NOT_FOUND, data=field_name)
        order_id = str(raw).strip()
        if not order_id or len(order_id) > MAX_ID_LENGTH:
            raise PaymeError(ERR_ORDER_NOT_FOUND, data=field_name)
        return order_id

    def _validate_order(self, order: PaymeOrder | None, amount: int) -> PaymeOrder:
        field_name = self.config.account_field
        if order is None:
            raise PaymeError(ERR_ORDER_NOT_FOUND, data=field_name)
        if order.status != STATUS_PENDING:
            raise PaymeError(ERR_ORDER_NOT_PAYABLE, data=field_name)
        if int(amount) != int(order.amount_tiyin):
            raise PaymeError(ERR_INVALID_AMOUNT, data="amount")
        return order

    def _is_expired(self, tx: PaymeTransaction, now: int) -> bool:
        return tx.state == STATE_CREATED and now - int(tx.create_time) > int(self.config.timeout_ms)

    @staticmethod
    def _cancel_created(uow: PaymeUnitOfWork, tx: PaymeTransaction, reason: int | None,
                        now: int) -> PaymeTransaction:
        cancelled = replace(tx, state=STATE_CANCELLED, cancel_time=now, reason=reason)
        uow.save_transaction(cancelled)
        return cancelled

    @staticmethod
    def _create_result(tx: PaymeTransaction) -> dict:
        return {"create_time": tx.create_time, "transaction": str(tx.id), "state": tx.state}

    @staticmethod
    def _perform_result(tx: PaymeTransaction) -> dict:
        return {"transaction": str(tx.id), "perform_time": tx.perform_time, "state": tx.state}

    @staticmethod
    def _cancel_result(tx: PaymeTransaction) -> dict:
        return {"transaction": str(tx.id), "cancel_time": tx.cancel_time, "state": tx.state}

    def _lock_transaction(self, uow: PaymeUnitOfWork, payme_id: str):
        """Lock order → transaction (fixed order prevents deadlocks)."""
        peek = uow.get_transaction(payme_id)
        if peek is None:
            raise PaymeError(ERR_TRANSACTION_NOT_FOUND, data="id")
        order = uow.get_order(peek.order_id, lock=True)
        tx = uow.get_transaction(payme_id, lock=True)
        if tx is None:  # pragma: no cover - rows are never deleted
            raise PaymeError(ERR_TRANSACTION_NOT_FOUND, data="id")
        return order, tx

    # -- public helpers ---------------------------------------------------
    def create_order(self, user_id: int, plan_key: str, days: int, amount_uzs: int) -> PaymeOrder:
        """Create a fresh, single-use order for the checkout link."""
        days = int(days)
        amount_uzs = int(amount_uzs)
        if days <= 0 or amount_uzs <= 0:
            raise ValueError("days and amount must be positive")
        order = PaymeOrder(
            order_id=new_order_id(),
            user_id=int(user_id),
            plan_key=str(plan_key)[:16],
            days=days,
            amount_tiyin=amount_uzs * 100,
        )
        return self.store.create_order(order)

    # -- JSON-RPC methods -------------------------------------------------
    def check_perform_transaction(self, params: dict, outcome: PaymeOutcome) -> dict:
        amount = _require_amount(params)
        order_id = self._account_order_id(params)
        with self.store.atomic() as uow:
            self._validate_order(uow.get_order(order_id), amount)
        return {"allow": True}

    def create_transaction(self, params: dict, outcome: PaymeOutcome) -> dict:
        payme_id = _require_payme_id(params)
        payme_time = _require_int(params, "time", positive=True)
        amount = _require_amount(params)
        order_id = self._account_order_id(params)
        now = self.now_ms()
        timed_out = False
        result: dict | None = None
        with self.store.atomic() as uow:
            order = uow.get_order(order_id, lock=True)
            existing = uow.get_transaction(payme_id, lock=True)
            if existing is not None:
                if existing.state != STATE_CREATED:
                    raise PaymeError(ERR_CANNOT_PERFORM, data="id")
                if self._is_expired(existing, now):
                    # Persist the timeout cancel, then report -31008 after COMMIT.
                    self._cancel_created(uow, existing, REASON_TIMEOUT, now)
                    timed_out = True
                else:
                    result = self._create_result(existing)
            else:
                order = self._validate_order(order, amount)
                active = uow.get_active_transaction_for_order(order.order_id)
                if active is not None:
                    if self._is_expired(active, now):
                        self._cancel_created(uow, active, REASON_TIMEOUT, now)
                    else:
                        raise PaymeError(ERR_ORDER_BUSY, data=self.config.account_field)
                inserted = uow.insert_transaction(PaymeTransaction(
                    payme_id=payme_id,
                    order_id=order.order_id,
                    user_id=order.user_id,
                    amount_tiyin=amount,
                    state=STATE_CREATED,
                    payme_time=payme_time,
                    create_time=now,
                ))
                if inserted is None:
                    # A concurrent duplicate won the UNIQUE race: answer with
                    # its row if it is the same Payme id, otherwise "busy".
                    again = uow.get_transaction(payme_id)
                    if again is None or again.state != STATE_CREATED:
                        raise PaymeError(ERR_ORDER_BUSY, data=self.config.account_field)
                    inserted = again
                result = self._create_result(inserted)
        if timed_out:
            raise PaymeError(ERR_CANNOT_PERFORM, data="id")
        return result or {}

    def perform_transaction(self, params: dict, outcome: PaymeOutcome) -> dict:
        payme_id = _require_payme_id(params)
        now = self.now_ms()
        timed_out = False
        result: dict | None = None
        with self.store.atomic() as uow:
            order, tx = self._lock_transaction(uow, payme_id)
            if tx.state == STATE_PERFORMED:
                # Duplicate callback: return the stored result, grant nothing.
                result = self._perform_result(tx)
            elif tx.state != STATE_CREATED:
                raise PaymeError(ERR_CANNOT_PERFORM, data="id")
            elif self._is_expired(tx, now):
                self._cancel_created(uow, tx, REASON_TIMEOUT, now)
                timed_out = True
            else:
                if order is None or order.status != STATUS_PENDING:
                    raise PaymeError(ERR_CANNOT_PERFORM, data="id")
                performed = replace(tx, state=STATE_PERFORMED, perform_time=now)
                if uow.record_ledger(performed, order):
                    uow.grant_subscription(order.user_id, order.days)
                    outcome.events.append(PaymeEvent("paid", order.user_id, order.days, order.order_id))
                else:
                    logger.warning("Payme ledger row already exists — subscription NOT re-granted", extra={
                        "event": "payme_duplicate_ledger", "transaction": tx.id,
                    })
                uow.save_transaction(performed)
                uow.set_order_status(order.order_id, STATUS_PAID)
                result = self._perform_result(performed)
        if timed_out:
            raise PaymeError(ERR_CANNOT_PERFORM, data="id")
        return result or {}

    def cancel_transaction(self, params: dict, outcome: PaymeOutcome) -> dict:
        payme_id = _require_payme_id(params)
        reason = _require_int(params, "reason")
        now = self.now_ms()
        with self.store.atomic() as uow:
            order, tx = self._lock_transaction(uow, payme_id)
            if tx.state in (STATE_CANCELLED, STATE_CANCELLED_AFTER_PERFORM):
                return self._cancel_result(tx)  # idempotent repeat
            if tx.state == STATE_CREATED:
                # The order stays payable: the user may retry the same link.
                return self._cancel_result(self._cancel_created(uow, tx, reason, now))
            # STATE_PERFORMED → refund (opt-in; PRO is a delivered service).
            if not self.config.allow_refunds:
                raise PaymeError(ERR_CANNOT_CANCEL, data="id")
            refunded = replace(tx, state=STATE_CANCELLED_AFTER_PERFORM, cancel_time=now, reason=reason)
            uow.refund_ledger(refunded)
            if order is not None:
                uow.revoke_subscription(order.user_id, order.days)
                uow.set_order_status(order.order_id, STATUS_CANCELLED)
                outcome.events.append(PaymeEvent("refunded", order.user_id, order.days, order.order_id))
            uow.save_transaction(refunded)
            return self._cancel_result(refunded)

    def check_transaction(self, params: dict, outcome: PaymeOutcome) -> dict:
        payme_id = _require_payme_id(params)
        with self.store.atomic() as uow:
            tx = uow.get_transaction(payme_id)
        if tx is None:
            raise PaymeError(ERR_TRANSACTION_NOT_FOUND, data="id")
        return {
            "create_time": tx.create_time,
            "perform_time": tx.perform_time,
            "cancel_time": tx.cancel_time,
            "transaction": str(tx.id),
            "state": tx.state,
            "reason": tx.reason,
        }

    def get_statement(self, params: dict, outcome: PaymeOutcome) -> dict:
        from_ms = _require_int(params, "from")
        to_ms = _require_int(params, "to")
        if to_ms < from_ms:
            raise PaymeError(ERR_INVALID_REQUEST, data="to")
        with self.store.atomic() as uow:
            rows = uow.list_transactions(from_ms, to_ms)
        field_name = self.config.account_field
        return {"transactions": [
            {
                "id": tx.payme_id,
                "time": tx.payme_time,
                "amount": tx.amount_tiyin,
                "account": {field_name: tx.order_id},
                "create_time": tx.create_time,
                "perform_time": tx.perform_time,
                "cancel_time": tx.cancel_time,
                "transaction": str(tx.id),
                "state": tx.state,
                "reason": tx.reason,
            }
            for tx in rows
        ]}


__all__ = [
    "ERR_CANNOT_CANCEL", "ERR_CANNOT_PERFORM", "ERR_INSUFFICIENT_PRIVILEGE",
    "ERR_INVALID_AMOUNT", "ERR_INVALID_REQUEST", "ERR_METHOD_NOT_FOUND",
    "ERR_ORDER_BUSY", "ERR_ORDER_NOT_FOUND", "ERR_ORDER_NOT_PAYABLE", "ERR_PARSE",
    "ERR_SYSTEM", "ERR_TRANSACTION_NOT_FOUND", "ERR_TRANSPORT",
    "PaymeConfig", "PaymeError", "PaymeEvent", "PaymeOrder", "PaymeOutcome",
    "PaymeProvider", "PaymeTransaction", "REASON_REFUND", "REASON_TIMEOUT",
    "STATE_CANCELLED", "STATE_CANCELLED_AFTER_PERFORM", "STATE_CREATED",
    "STATE_PERFORMED", "STATUSES", "STATUS_CANCELLED", "STATUS_PAID",
    "STATUS_PENDING", "TRANSACTION_TIMEOUT_MS", "basic_auth_header",
    "build_checkout_url", "error_response", "new_order_id", "result_response",
    "verify_basic_auth",
]
