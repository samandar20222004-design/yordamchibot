#!/usr/bin/env python3
"""Payme Merchant API — unit + integration tests.

Covers:
  1) HTTP Basic Auth validation (fail-closed, constant-time helper);
  2) the full JSON-RPC flow (CheckPerform → Create → Perform → Check →
     GetStatement) on the transactional in-memory store;
  3) duplicate / concurrent callbacks never grant PRO twice (state machine,
     UNIQUE payme id, one active transaction per order, ledger key);
  4) cancel / timeout / refund rules and all protocol error codes;
  5) the aiohttp endpoint mounted on the real web app (``build_web_app``):
     transport errors, auth, JSON parsing, body cap, notifications;
  6) the PostgreSQL store's SQL contract (fake cursor) and schema DDL;
  7) bot wiring: checkout link, Payme button, paid notification.

No network, no PostgreSQL, deterministic clock.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

REPO = Path(__file__).resolve().parent.parent
BOT_ROOT = REPO / "telegram_bot"
sys.path.insert(0, str(BOT_ROOT))

from services.payments.memory_store import InMemoryPaymeStore  # noqa: E402
from services.payments.payme_provider import (  # noqa: E402
    ERR_CANNOT_CANCEL,
    ERR_CANNOT_PERFORM,
    ERR_INSUFFICIENT_PRIVILEGE,
    ERR_INVALID_AMOUNT,
    ERR_INVALID_REQUEST,
    ERR_METHOD_NOT_FOUND,
    ERR_ORDER_BUSY,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_NOT_PAYABLE,
    ERR_PARSE,
    ERR_SYSTEM,
    ERR_TRANSACTION_NOT_FOUND,
    ERR_TRANSPORT,
    REASON_TIMEOUT,
    STATE_CANCELLED,
    STATE_CANCELLED_AFTER_PERFORM,
    STATE_CREATED,
    STATE_PERFORMED,
    TRANSACTION_TIMEOUT_MS,
    PaymeConfig,
    PaymeProvider,
    basic_auth_header,
    build_checkout_url,
    verify_basic_auth,
)

PASSED = 0
FAILED = 0

KEY = "test-merchant-key-#1"
CONFIG = PaymeConfig(merchant_id="65f0c0ffee", key=KEY)
AUTH = basic_auth_header("Paycom", KEY)
USER_ID = 5150
PRICE_UZS = 19000
PRICE_TIYIN = PRICE_UZS * 100


def check(label: str, condition, detail: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILED += 1
        print(f"  [XATO] {label}" + (f" — {detail}" if detail else ""))


class Clock:
    def __init__(self, start: int = 1_760_000_000_000) -> None:
        self.now = start

    def __call__(self) -> int:
        return self.now


def make_provider(config: PaymeConfig = CONFIG):
    store = InMemoryPaymeStore()
    clock = Clock()
    provider = PaymeProvider(store, config, clock=clock)
    order = provider.create_order(USER_ID, "1m", 30, PRICE_UZS)
    return provider, store, clock, order


_rpc_seq = 0


def rpc(provider, method, params, *, auth=AUTH):
    global _rpc_seq
    _rpc_seq += 1
    outcome = provider.handle(
        {"jsonrpc": "2.0", "id": _rpc_seq, "method": method, "params": params},
        authorization=auth,
    )
    return outcome.response, outcome


def err_code(response):
    return (response.get("error") or {}).get("code")


def create_params(order, payme_id="6630a1b2c3d4e5f600000001", amount=PRICE_TIYIN, time_ms=1_760_000_000_000):
    return {"id": payme_id, "time": time_ms, "amount": amount, "account": {"order_id": order.order_id}}


# ---------------------------------------------------------------------------
# 1) Basic Auth
# ---------------------------------------------------------------------------
def test_basic_auth():
    print("\n== 1) HTTP Basic Auth (Paycom ID / Key) ==")
    check("to'g'ri login+kalit qabul qilinadi", verify_basic_auth(AUTH, CONFIG))
    check("scheme katta-kichik harfga sezgir emas",
          verify_basic_auth(AUTH.replace("Basic", "basic"), CONFIG))
    check("noto'g'ri kalit rad etiladi",
          not verify_basic_auth(basic_auth_header("Paycom", "wrong"), CONFIG))
    check("noto'g'ri login rad etiladi",
          not verify_basic_auth(basic_auth_header("Hacker", KEY), CONFIG))
    check("header yo'q → rad", not verify_basic_auth(None, CONFIG))
    check("Bearer scheme → rad", not verify_basic_auth("Bearer " + KEY, CONFIG))
    check("base64 emas → rad", not verify_basic_auth("Basic !!!not-base64!!!", CONFIG))
    no_colon = "Basic " + base64.b64encode(b"PaycomOnly").decode()
    check("':' ajratgichsiz token → rad", not verify_basic_auth(no_colon, CONFIG))
    check("kalit prefiksi yetarli emas (to'liq moslik)",
          not verify_basic_auth(basic_auth_header("Paycom", KEY[:-1]), CONFIG))
    unconfigured = PaymeConfig(merchant_id="m", key="")
    check("PAYME_KEY bo'sh → har doim rad (fail-closed)",
          not verify_basic_auth(basic_auth_header("Paycom", ""), unconfigured))
    check("repr kalitni oshkor qilmaydi", KEY not in repr(CONFIG) and "***" in repr(CONFIG))

    provider, store, _clock, order = make_provider()
    resp, _ = rpc(provider, "CheckPerformTransaction",
                  {"amount": PRICE_TIYIN, "account": {"order_id": order.order_id}},
                  auth=basic_auth_header("Paycom", "nope"))
    check("noto'g'ri auth → -32504", err_code(resp) == ERR_INSUFFICIENT_PRIVILEGE, str(resp))
    resp, _ = rpc(provider, "PerformTransaction", {"id": "x"}, auth=None)
    check("auth yo'q → -32504 (metoddan oldin tekshiriladi)",
          err_code(resp) == ERR_INSUFFICIENT_PRIVILEGE)
    check("auth xatosida store'ga tegilmadi", not store.transactions and not store.grants)
    check("xato xabari uz/ru/en lokalizatsiyada",
          set((resp["error"].get("message") or {}).keys()) == {"uz", "ru", "en"})

    with patch.dict(os.environ, {"PAYME_MERCHANT_ID": " m1 ", "PAYME_KEY": " k1 ",
                                 "PAYME_LOGIN": "", "PAYME_ALLOW_REFUNDS": "true"}):
        env_cfg = PaymeConfig.from_env()
    check("from_env: qiymatlar tozalanadi, login standart Paycom",
          env_cfg.merchant_id == "m1" and env_cfg.key == "k1" and env_cfg.login == "Paycom")
    check("from_env: PAYME_ALLOW_REFUNDS=true → refund ruxsat", env_cfg.allow_refunds is True)
    with patch.dict(os.environ, {"PAYME_MERCHANT_ID": "", "PAYME_KEY": ""}):
        check("from_env: sozlanmagan → checkout o'chiq",
              PaymeConfig.from_env().checkout_enabled is False)


# ---------------------------------------------------------------------------
# 2) Happy path
# ---------------------------------------------------------------------------
def test_full_flow():
    print("\n== 2) To'liq JSON-RPC oqimi ==")
    provider, store, clock, order = make_provider()
    check("buyurtma tiyin'da saqlanadi (19 000 so'm → 1 900 000)",
          store.orders[order.order_id].amount_tiyin == PRICE_TIYIN)
    check("order_id taxmin qilib bo'lmaydigan (pm + 20 hex)",
          order.order_id.startswith("pm") and len(order.order_id) == 22)

    resp, _ = rpc(provider, "CheckPerformTransaction",
                  {"amount": PRICE_TIYIN, "account": {"order_id": order.order_id}})
    check("CheckPerformTransaction → allow=true", resp.get("result") == {"allow": True}, str(resp))
    check("javob jsonrpc 2.0 va id saqlanadi", resp.get("jsonrpc") == "2.0" and resp.get("id") == _rpc_seq)

    clock.now += 1000
    resp, _ = rpc(provider, "CreateTransaction", create_params(order))
    result = resp.get("result") or {}
    check("CreateTransaction → state=1", result.get("state") == STATE_CREATED, str(resp))
    check("CreateTransaction → transaction id string", isinstance(result.get("transaction"), str))
    check("CreateTransaction → create_time = server vaqti", result.get("create_time") == clock.now)
    tx = store.transactions["6630a1b2c3d4e5f600000001"]
    check("tranzaksiya status='pending'", tx.status == "pending")
    check("buyurtma hali 'pending'", store.orders[order.order_id].status == "pending")
    check("Create bosqichida PRO berilmaydi", store.grants == [])

    create_time = clock.now
    clock.now += 5000
    resp2, _ = rpc(provider, "CreateTransaction", create_params(order))
    check("takroriy CreateTransaction → xuddi shu natija (idempotent)",
          resp2.get("result") == result, str(resp2))
    check("takroriy Create yangi qator yaratmaydi", len(store.transactions) == 1)

    resp, outcome = rpc(provider, "PerformTransaction", {"id": tx.payme_id})
    presult = resp.get("result") or {}
    check("PerformTransaction → state=2", presult.get("state") == STATE_PERFORMED, str(resp))
    check("PerformTransaction → perform_time", presult.get("perform_time") == clock.now)
    check("PRO aynan 1 marta, 30 kun berildi", store.grants == [(USER_ID, 30)], str(store.grants))
    check("buyurtma 'paid'", store.orders[order.order_id].status == "paid")
    check("tranzaksiya status='paid'", store.transactions[tx.payme_id].status == "paid")
    ledger = store.ledger.get(f"payme:{tx.payme_id}") or {}
    check("ledger: payme:<id>, UZS, so'mda summa",
          ledger.get("amount") == PRICE_UZS and ledger.get("currency") == "UZS", str(ledger))
    check("paid hodisasi (bildirishnoma uchun) 1 ta", len(outcome.paid_events) == 1)
    check("after_commit hook chaqirildi (kesh tozalash)", len(store.after_commit_events) == 1)

    resp, _ = rpc(provider, "CheckTransaction", {"id": tx.payme_id})
    cres = resp.get("result") or {}
    check("CheckTransaction → state=2, vaqtlar, reason=null",
          cres.get("state") == 2 and cres.get("create_time") == create_time
          and cres.get("perform_time") == presult["perform_time"]
          and cres.get("cancel_time") == 0 and cres.get("reason") is None, str(resp))

    resp, _ = rpc(provider, "GetStatement", {"from": 0, "to": 9_999_999_999_999})
    rows = (resp.get("result") or {}).get("transactions") or []
    check("GetStatement → 1 ta tranzaksiya", len(rows) == 1, str(resp))
    check("GetStatement maydonlari (id, amount, account, state)",
          rows and rows[0]["id"] == tx.payme_id and rows[0]["amount"] == PRICE_TIYIN
          and rows[0]["account"] == {"order_id": order.order_id} and rows[0]["state"] == 2)
    resp, _ = rpc(provider, "GetStatement", {"from": 0, "to": 10})
    check("GetStatement oraliqdan tashqari → bo'sh", (resp.get("result") or {}).get("transactions") == [])

    resp, _ = rpc(provider, "CheckPerformTransaction",
                  {"amount": PRICE_TIYIN, "account": {"order_id": order.order_id}})
    check("to'langan buyurtma qayta tekshirilsa → -31051",
          err_code(resp) == ERR_ORDER_NOT_PAYABLE, str(resp))
    check("account xatosi data=maydon nomi", (resp.get("error") or {}).get("data") == "order_id")


# ---------------------------------------------------------------------------
# 3) Duplicates & concurrency
# ---------------------------------------------------------------------------
def test_duplicate_callbacks():
    print("\n== 3) Takroriy / parallel callback'lar — ikki marta PRO YO'Q ==")
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="dup-1"))
    first, o1 = rpc(provider, "PerformTransaction", {"id": "dup-1"})
    clock.now += 60_000
    second, o2 = rpc(provider, "PerformTransaction", {"id": "dup-1"})
    check("takroriy Perform → bir xil natija (perform_time o'zgarmaydi)",
          first.get("result") == second.get("result"), f"{first} vs {second}")
    check("takroriy Perform PRO bermaydi", store.grants == [(USER_ID, 30)])
    check("takroriy Perform bildirishnoma yubormaydi", len(o1.paid_events) == 1 and not o2.paid_events)

    resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="dup-2"))
    check("to'langan buyurtmaga yangi Payme tranzaksiya → -31051",
          err_code(resp) == ERR_ORDER_NOT_PAYABLE, str(resp))

    # Ikkinchi faol tranzaksiya: buyurtma band (-31052).
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="a-1"))
    resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="a-2"))
    check("bitta buyurtmada 2-faol tranzaksiya → -31052",
          err_code(resp) == ERR_ORDER_BUSY, str(resp))

    # Ledger allaqachon mavjud (masalan, qo'lda tiklash) → PRO qayta berilmaydi.
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="ledger-1"))
    store.ledger["payme:ledger-1"] = {"status": "succeeded"}
    resp, outcome = rpc(provider, "PerformTransaction", {"id": "ledger-1"})
    check("ledger qatori mavjud → state=2, lekin PRO berilmaydi",
          (resp.get("result") or {}).get("state") == 2 and store.grants == [] and not outcome.paid_events,
          str(resp))

    # Parallel PerformTransaction (8 ta oqim, bitta id).
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="race-1"))
    barrier = threading.Barrier(8)
    results = []

    def worker():
        barrier.wait()
        results.append(rpc(provider, "PerformTransaction", {"id": "race-1"})[0])

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("8 parallel Perform → hammasi state=2",
          all((r.get("result") or {}).get("state") == 2 for r in results), str(results[:2]))
    check("8 parallel Perform → PRO aynan 1 marta", store.grants == [(USER_ID, 30)], str(store.grants))

    # Parallel CreateTransaction (turli Payme id'lar, bitta buyurtma).
    provider, store, clock, order = make_provider()
    barrier = threading.Barrier(6)
    codes = []

    def creator(i):
        barrier.wait()
        resp = rpc(provider, "CreateTransaction", create_params(order, payme_id=f"pc-{i}"))[0]
        codes.append("ok" if "result" in resp else err_code(resp))

    threads = [threading.Thread(target=creator, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("6 parallel Create → faqat 1 tasi muvaffaqiyatli",
          codes.count("ok") == 1 and codes.count(ERR_ORDER_BUSY) == 5, str(codes))
    active = [tx for tx in store.transactions.values() if tx.state in (1, 2)]
    check("DB holati: buyurtmada bitta faol tranzaksiya", len(active) == 1)

    # Store-level UNIQUE kafolati (ON CONFLICT DO NOTHING muqobili).
    with store.atomic() as uow:
        dup = uow.insert_transaction(active[0])
    check("UNIQUE payme_transaction_id: qayta insert → None", dup is None)

    # Atomiklik: blok ichida xato → hammasi orqaga qaytariladi.
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="atomic-1"))
    with patch.object(InMemoryPaymeStore, "after_commit", lambda self, e: None):
        from services.payments import memory_store as ms
        original = ms._MemoryUnitOfWork.set_order_status

        def boom(self, order_id, status):
            raise RuntimeError("db down")

        ms._MemoryUnitOfWork.set_order_status = boom
        try:
            resp, outcome = rpc(provider, "PerformTransaction", {"id": "atomic-1"})
        finally:
            ms._MemoryUnitOfWork.set_order_status = original
    check("ichki xato → -32400 (Payme qayta urinadi)", err_code(resp) == ERR_SYSTEM, str(resp))
    check("ichki xato → PRO/ledger rollback qilindi",
          store.grants == [] and not store.ledger and store.transactions["atomic-1"].state == 1)
    check("ichki xato → bildirishnoma yo'q", not outcome.events)
    resp, outcome = rpc(provider, "PerformTransaction", {"id": "atomic-1"})
    check("qayta urinish muvaffaqiyatli va PRO 1 marta",
          (resp.get("result") or {}).get("state") == 2 and store.grants == [(USER_ID, 30)])


# ---------------------------------------------------------------------------
# 4) Cancel, timeout, refund and error codes
# ---------------------------------------------------------------------------
def test_cancel_timeout_refund_and_errors():
    print("\n== 4) Cancel / timeout / refund / xato kodlari ==")
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="c-1"))
    clock.now += 1000
    resp, _ = rpc(provider, "CancelTransaction", {"id": "c-1", "reason": 3})
    cres = resp.get("result") or {}
    check("state=1 ni bekor qilish → state=-1", cres.get("state") == STATE_CANCELLED, str(resp))
    check("cancel_time saqlanadi", cres.get("cancel_time") == clock.now)
    check("bekor qilingan tx status='cancelled'", store.transactions["c-1"].status == "cancelled")
    check("buyurtma qayta to'lash uchun ochiq qoladi", store.orders[order.order_id].status == "pending")
    again, _ = rpc(provider, "CancelTransaction", {"id": "c-1", "reason": 3})
    check("takroriy Cancel → idempotent", again.get("result") == cres)
    resp, _ = rpc(provider, "PerformTransaction", {"id": "c-1"})
    check("bekor qilingan tx'ni Perform → -31008", err_code(resp) == ERR_CANNOT_PERFORM)
    resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="c-1"))
    check("bekor qilingan id bilan Create → -31008", err_code(resp) == ERR_CANNOT_PERFORM)
    resp, _ = rpc(provider, "CheckTransaction", {"id": "c-1"})
    check("CheckTransaction reason=3", (resp.get("result") or {}).get("reason") == 3)
    resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="c-2"))
    check("bekor qilingandan keyin yangi tranzaksiya mumkin", (resp.get("result") or {}).get("state") == 1)

    # 12 soatlik timeout.
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="t-1"))
    clock.now += TRANSACTION_TIMEOUT_MS + 1
    resp, _ = rpc(provider, "PerformTransaction", {"id": "t-1"})
    check("12 soatdan keyin Perform → -31008", err_code(resp) == ERR_CANNOT_PERFORM, str(resp))
    tx = store.transactions["t-1"]
    check("timeout → state=-1, reason=4 (saqlangan)", tx.state == -1 and tx.reason == REASON_TIMEOUT)
    check("timeout → PRO berilmadi", store.grants == [])
    provider2, store2, clock2, order2 = make_provider()
    rpc(provider2, "CreateTransaction", create_params(order2, payme_id="t-2"))
    clock2.now += TRANSACTION_TIMEOUT_MS + 1
    resp, _ = rpc(provider2, "CreateTransaction", create_params(order2, payme_id="t-3"))
    check("eskirgan faol tx o'rniga yangi Create ruxsat",
          (resp.get("result") or {}).get("state") == 1 and store2.transactions["t-2"].state == -1, str(resp))

    # Refund o'chiq (standart).
    provider, store, clock, order = make_provider()
    rpc(provider, "CreateTransaction", create_params(order, payme_id="r-1"))
    rpc(provider, "PerformTransaction", {"id": "r-1"})
    resp, _ = rpc(provider, "CancelTransaction", {"id": "r-1", "reason": 5})
    check("refund o'chiq: bajarilgan tx → -31007", err_code(resp) == ERR_CANNOT_CANCEL, str(resp))
    check("refund o'chiq: PRO saqlanadi", store.subscription_days.get(USER_ID) == 30)

    # Refund yoqilgan.
    refund_cfg = PaymeConfig(merchant_id="m", key=KEY, allow_refunds=True)
    provider, store, clock, order = make_provider(refund_cfg)
    rpc(provider, "CreateTransaction", create_params(order, payme_id="r-2"))
    rpc(provider, "PerformTransaction", {"id": "r-2"})
    resp, outcome = rpc(provider, "CancelTransaction", {"id": "r-2", "reason": 5})
    check("refund: state=-2", (resp.get("result") or {}).get("state") == STATE_CANCELLED_AFTER_PERFORM)
    check("refund: PRO kunlari qaytarib olindi", store.subscription_days.get(USER_ID) == 0)
    check("refund: ledger 'refunded', buyurtma 'cancelled'",
          store.ledger["payme:r-2"]["status"] == "refunded"
          and store.orders[order.order_id].status == "cancelled")
    check("refund: 'refunded' hodisasi, 'paid' emas",
          [e.kind for e in outcome.events] == ["refunded"])
    again, _ = rpc(provider, "CancelTransaction", {"id": "r-2", "reason": 5})
    check("takroriy refund → idempotent, PRO ikki marta olinmaydi",
          (again.get("result") or {}).get("state") == -2 and store.subscription_days.get(USER_ID) == 0)

    # Protokol xatolari.
    provider, store, clock, order = make_provider()
    acc = {"order_id": order.order_id}
    cases = [
        ("noto'g'ri summa → -31001",
         "CheckPerformTransaction", {"amount": PRICE_TIYIN - 100, "account": acc}, ERR_INVALID_AMOUNT),
        ("kasr summa → -31001",
         "CheckPerformTransaction", {"amount": 1.5, "account": acc}, ERR_INVALID_AMOUNT),
        ("manfiy summa → -31001",
         "CheckPerformTransaction", {"amount": -1, "account": acc}, ERR_INVALID_AMOUNT),
        ("summa matn → -32600",
         "CheckPerformTransaction", {"amount": "1900000", "account": acc}, ERR_INVALID_REQUEST),
        ("noma'lum buyurtma → -31050",
         "CheckPerformTransaction", {"amount": PRICE_TIYIN, "account": {"order_id": "pm-nope"}},
         ERR_ORDER_NOT_FOUND),
        ("account yo'q → -32600",
         "CheckPerformTransaction", {"amount": PRICE_TIYIN}, ERR_INVALID_REQUEST),
        ("noma'lum tx Perform → -31003", "PerformTransaction", {"id": "ghost"}, ERR_TRANSACTION_NOT_FOUND),
        ("noma'lum tx Cancel → -31003",
         "CancelTransaction", {"id": "ghost", "reason": 1}, ERR_TRANSACTION_NOT_FOUND),
        ("noma'lum tx Check → -31003", "CheckTransaction", {"id": "ghost"}, ERR_TRANSACTION_NOT_FOUND),
        ("id yo'q → -32600", "PerformTransaction", {}, ERR_INVALID_REQUEST),
        ("juda uzun id → -32600", "PerformTransaction", {"id": "x" * 65}, ERR_INVALID_REQUEST),
        ("Create time yo'q → -32600",
         "CreateTransaction", {"id": "z", "amount": PRICE_TIYIN, "account": acc}, ERR_INVALID_REQUEST),
        ("Cancel reason yo'q → -32600", "CancelTransaction", {"id": "z"}, ERR_INVALID_REQUEST),
        ("GetStatement to<from → -32600", "GetStatement", {"from": 10, "to": 1}, ERR_INVALID_REQUEST),
        ("noma'lum metod → -32601", "ChangePassword", {"password": "x"}, ERR_METHOD_NOT_FOUND),
    ]
    for label, method, params, code in cases:
        resp, _ = rpc(provider, method, params)
        check(label, err_code(resp) == code, str(resp))
    resp = provider.handle({"jsonrpc": "2.0", "id": 1, "method": "CheckTransaction"}, authorization=AUTH).response
    check("params yo'q → -32600", err_code(resp) == ERR_INVALID_REQUEST)
    resp = provider.handle(["not", "an", "object"], authorization=AUTH).response
    check("massiv payload → -32600, id=null", err_code(resp) == ERR_INVALID_REQUEST and resp["id"] is None)
    resp, _ = rpc(provider, "CreateTransaction", create_params(order, amount=PRICE_TIYIN + 1))
    check("Create noto'g'ri summa → -31001, tx yaratilmaydi",
          err_code(resp) == ERR_INVALID_AMOUNT and not store.transactions)


# ---------------------------------------------------------------------------
# 5) aiohttp endpoint (real route table)
# ---------------------------------------------------------------------------
def test_webhook_endpoint():
    print("\n== 5) Webhook endpoint (POST /payments/payme) ==")
    from aiohttp.test_utils import TestClient, TestServer

    from services.payments import payme_webhook
    from utils.web_server import build_web_app

    provider, store, clock, order = make_provider()
    notified = []

    async def notifier(event):
        notified.append(event)

    async def scenario():
        payme_webhook.set_provider(provider)
        payme_webhook.set_paid_notifier(notifier)
        client = TestClient(TestServer(build_web_app()))
        await client.start_server()
        try:
            path = payme_webhook.PAYME_WEBHOOK_PATH

            async def post(body, *, auth=AUTH, raw=None):
                headers = {"Content-Type": "application/json"}
                if auth:
                    headers["Authorization"] = auth
                data = raw if raw is not None else json.dumps(body)
                resp = await client.post(path, data=data, headers=headers)
                return resp.status, await resp.json(), resp.headers

            resp = await client.get(path)
            body = await resp.json()
            check("GET → HTTP 200 + -32300", resp.status == 200 and err_code(body) == ERR_TRANSPORT, str(body))

            status, body, headers = await post({"id": 1, "method": "CheckTransaction", "params": {"id": "x"}},
                                               auth=None)
            check("auth yo'q → HTTP 200 + -32504", status == 200 and err_code(body) == ERR_INSUFFICIENT_PRIVILEGE)
            status, body, _ = await post({"id": 1, "method": "CheckTransaction", "params": {"id": "x"}},
                                         auth=basic_auth_header("Paycom", "bad"))
            check("noto'g'ri kalit → -32504", err_code(body) == ERR_INSUFFICIENT_PRIVILEGE)
            check("javob Cache-Control: no-store", headers.get("Cache-Control") == "no-store")

            status, body, _ = await post(None, raw="{not json")
            check("buzilgan JSON → -32700", status == 200 and err_code(body) == ERR_PARSE, str(body))
            status, body, _ = await post(None, raw=b"\xff\xfe")
            check("UTF-8 emas → -32700", err_code(body) == ERR_PARSE)
            status, body, _ = await post(None, raw="x" * (payme_webhook.MAX_BODY_BYTES + 10))
            check("64 KB dan katta body → -32600", err_code(body) == ERR_INVALID_REQUEST, str(body))

            acc = {"order_id": order.order_id}
            status, body, _ = await post({"jsonrpc": "2.0", "id": 11, "method": "CheckPerformTransaction",
                                          "params": {"amount": PRICE_TIYIN, "account": acc}})
            check("HTTP CheckPerformTransaction → allow", body.get("result") == {"allow": True}
                  and body.get("id") == 11, str(body))
            status, body, _ = await post({"jsonrpc": "2.0", "id": 12, "method": "CreateTransaction",
                                          "params": create_params(order, payme_id="http-1")})
            check("HTTP CreateTransaction → state 1", (body.get("result") or {}).get("state") == 1, str(body))
            for _ in range(3):
                status, body, _ = await post({"jsonrpc": "2.0", "id": 13, "method": "PerformTransaction",
                                              "params": {"id": "http-1"}})
            check("HTTP 3× PerformTransaction → state 2", (body.get("result") or {}).get("state") == 2)
            await asyncio.sleep(0.05)  # background notification task
            check("HTTP 3× Perform → PRO 1 marta", store.grants == [(USER_ID, 30)], str(store.grants))
            check("foydalanuvchiga bildirishnoma aynan 1 marta",
                  len(notified) == 1 and notified[0].user_id == USER_ID and notified[0].days == 30)

            async def failing_notifier(event):
                raise RuntimeError("telegram down")

            payme_webhook.set_paid_notifier(failing_notifier)
            p2, s2, _c2, o2 = make_provider()
            payme_webhook.set_provider(p2)
            await post({"id": 1, "method": "CreateTransaction", "params": create_params(o2, payme_id="n-1")})
            status, body, _ = await post({"id": 2, "method": "PerformTransaction", "params": {"id": "n-1"}})
            await asyncio.sleep(0.05)
            check("bildirishnoma xatosi to'lov javobiga ta'sir qilmaydi",
                  (body.get("result") or {}).get("state") == 2 and s2.grants == [(USER_ID, 30)])
            resp = await client.get("/health/live")
            check("mavjud /health/live endpoint buzilmadi", resp.status == 200)
        finally:
            await client.close()
            payme_webhook.set_provider(None)
            payme_webhook.set_paid_notifier(None)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# 6) PostgreSQL store contract + schema
# ---------------------------------------------------------------------------
class FakeCursor:
    def __init__(self, fetchone_results=None, rowcount=1):
        self.calls = []
        self._fetchone = list(fetchone_results or [])
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetchone.pop(0) if self._fetchone else None

    def fetchall(self):
        return []


def test_postgres_store_and_schema():
    print("\n== 6) PostgresPaymeStore SQL shartnomasi + schema.sql ==")
    import database
    from repositories import payme_repository as repo
    from services.payments.payme_provider import PaymeEvent, PaymeOrder, PaymeTransaction

    cur = FakeCursor()
    commits = []

    @contextmanager
    def fake_tx(commit=False):
        commits.append(commit)
        yield cur

    order = PaymeOrder("pm1", USER_ID, "1m", 30, PRICE_TIYIN)
    tx = PaymeTransaction("p-1", "pm1", USER_ID, PRICE_TIYIN, 2, 1, 2, perform_time=3)
    with patch.object(repo, "db_transaction", fake_tx):
        store = repo.PostgresPaymeStore()
        store.create_order(order)
        with store.atomic() as uow:
            uow.get_order("pm1", lock=True)
            uow.get_transaction("p-1", lock=True)
            inserted = uow.insert_transaction(tx)
            uow.record_ledger(tx, order)
            uow.grant_subscription(USER_ID, 30)
            uow.save_transaction(tx)
            uow.set_order_status("pm1", "paid")
    sqls = [c[0] for c in cur.calls]
    check("atomic()/create_order → db_transaction(commit=True)", commits == [True, True])
    check("create_order: INSERT payme_orders 'pending'",
          sqls[0].startswith("INSERT INTO payme_orders") and "'pending'" in sqls[0])
    check("get_order(lock) → SELECT … FOR UPDATE", sqls[1].endswith("FOR UPDATE") and "payme_orders" in sqls[1])
    check("get_transaction(lock) → FOR UPDATE", sqls[2].endswith("FOR UPDATE"))
    check("insert_transaction: ON CONFLICT DO NOTHING RETURNING id (partial UNIQUE ham)",
          "ON CONFLICT DO NOTHING RETURNING id" in sqls[3] and "ON CONFLICT (" not in sqls[3])
    check("insert konflikt → None (ikkinchi qator yo'q)", inserted is None)
    check("ledger: payments ga UZS, payme:<id> kaliti, ON CONFLICT",
          "INSERT INTO payments" in sqls[4] and "ON CONFLICT DO NOTHING" in sqls[4]
          and cur.calls[4][1][3] == "payme:p-1" and cur.calls[4][1][1] == PRICE_UZS)
    check("ledger usuli mavjud PAYMENT_METHODS ichida",
          cur.calls[4][1][4] in database.PAYMENT_METHODS)
    check("grant: GREATEST(COALESCE(..), NOW()) + interval (Stars bilan bir xil)",
          "GREATEST(COALESCE(subscription_expires_at, NOW()), NOW())" in sqls[5] and "plan_type = 'pro'" in sqls[5])
    check("save_transaction: state+status+vaqtlar", "SET state = %s, status = %s" in sqls[6]
          and cur.calls[6][1][1] == "paid")
    check("set_order_status: paid_at belgilanadi", "paid_at" in sqls[7])

    cur2 = FakeCursor(fetchone_results=[(7,), (9,)], rowcount=0)
    with patch.object(repo, "db_transaction", lambda commit=False: _yield(cur2)):
        with repo.PostgresPaymeStore().atomic() as uow:
            got = uow.insert_transaction(PaymeTransaction("p-2", "pm1", USER_ID, PRICE_TIYIN, 1, 1, 2))
            ledger_new = uow.record_ledger(tx, order)
            granted = uow.grant_subscription(USER_ID, 30)
    check("insert muvaffaqiyatli → DB id qaytadi", got is not None and got.id == 7)
    check("ledger yangi qator → True", ledger_new is True)
    check("user qatori yo'q → grant False", granted is False)

    with patch.object(repo, "_invalidate_user") as inv, patch.object(repo, "_cache_clear") as cc:
        repo.PostgresPaymeStore().after_commit(PaymeEvent("paid", USER_ID, 30, "pm1"))
    check("after_commit: user keshi + statistika keshlari tozalanadi",
          inv.call_args.args == (USER_ID,)
          and {c.args[0] for c in cc.call_args_list} == {"system_stats", "admin_dashboard_stats"})

    with patch.object(repo, "PostgresPaymeStore", side_effect=RuntimeError("pool down")):
        check("create_payme_order DB xatosida None (fail-soft)",
              repo.create_payme_order(USER_ID, "1m", 30, PRICE_UZS) is None)

    schema = (BOT_ROOT / "schema.sql").read_text(encoding="utf-8")
    check("schema: payme_orders jadvali (split-line naqsh)", "CREATE TABLE IF\nNOT EXISTS payme_orders" in schema)
    check("schema: payme_transactions jadvali", "CREATE TABLE IF\nNOT EXISTS payme_transactions" in schema)
    check("schema: UNIQUE payme_transaction_id",
          "CONSTRAINT uq_payme_transaction_id UNIQUE (payme_transaction_id)" in schema)
    check("schema: buyurtmada bitta faol tx (partial UNIQUE)",
          "CREATE UNIQUE INDEX IF\nNOT EXISTS uq_payme_tx_active_order ON payme_transactions (order_id) "
          "WHERE state IN (1, 2)" in schema)
    check("schema: status CHECK ('pending','paid','cancelled')",
          schema.count("CHECK (status IN ('pending', 'paid', 'cancelled'))") == 2)
    check("schema: status↔state izchilligi CHECK", "chk_payme_tx_status_state" in schema)
    check("database.PAYME_TABLES / PAYME_INDEXES",
          database.PAYME_TABLES == ("payme_orders", "payme_transactions")
          and all(name in schema for name in database.PAYME_INDEXES))
    check("PAYMENT_METHODS o'zgarmadi", database.PAYMENT_METHODS == ("uzcard_humo", "international_stars"))


@contextmanager
def _yield(cur):
    yield cur


# ---------------------------------------------------------------------------
# 7) Bot wiring
# ---------------------------------------------------------------------------
def test_bot_wiring():
    print("\n== 7) Bot: checkout havola, Payme tugmasi, bildirishnoma ==")
    from services.payments.payme_provider import PaymeOrder

    order = PaymeOrder("pmabc", USER_ID, "1m", 30, PRICE_TIYIN)
    url = build_checkout_url(CONFIG, order, lang="ru", return_url="https://t.me/PostAssistrobot")
    decoded = base64.b64decode(url.rsplit("/", 1)[1]).decode()
    check("checkout URL: m, ac.order_id, a (tiyin), l, c",
          url.startswith("https://checkout.paycom.uz/")
          and decoded == "m=65f0c0ffee;ac.order_id=pmabc;a=1900000;l=ru;c=https://t.me/PostAssistrobot",
          decoded)
    bad = base64.b64decode(build_checkout_url(CONFIG, order, return_url="https://x;m=evil").rsplit("/", 1)[1])
    check("';' bor return_url qo'shilmaydi (parametr in'ektsiyasi yo'q)", b"evil" not in bad)
    try:
        build_checkout_url(PaymeConfig(), order)
        raised = False
    except ValueError:
        raised = True
    check("merchant_id yo'q → ValueError", raised)

    import handlers.subscription as subscription
    from locales.translations import get_text

    plain = subscription._get_card_payment_keyboard("uz", "1m")
    with_payme = subscription._get_card_payment_keyboard("uz", "1m", payme_url=url)
    check("Payme sozlanmagan → klaviatura avvalgidek",
          [b.text for r in plain.inline_keyboard for b in r]
          == [b.text for r in with_payme.inline_keyboard for b in r][1:])
    first = with_payme.inline_keyboard[0][0]
    check("Payme tugmasi birinchi va URL", first.url == url and "Payme" in first.text)
    check("chek yuborish tugmasi saqlangan",
          any("📸" in b.text for r in with_payme.inline_keyboard for b in r))

    with patch.dict(os.environ, {"PAYME_MERCHANT_ID": "", "PAYME_KEY": ""}):
        got = asyncio.run(subscription._payme_checkout_url(USER_ID, "uz", "1m"))
    check("env yo'q → Payme havolasi yo'q (DB'ga tegilmaydi)", got is None)

    made = PaymeOrder("pmxyz", USER_ID, "3m", 90, 45000 * 100)
    run_db = AsyncMock(return_value=made)
    with patch.dict(os.environ, {"PAYME_MERCHANT_ID": "mid", "PAYME_KEY": "k"}), \
         patch.object(subscription.db, "run_db", new=run_db):
        got = asyncio.run(subscription._payme_checkout_url(USER_ID, "en", "3m"))
    payload = base64.b64decode(got.rsplit("/", 1)[1]).decode() if got else ""
    check("sozlangan → har ekran uchun yangi buyurtma (3m, 90 kun, narx config'dan)",
          run_db.await_args.args[1:] == (USER_ID, "3m", 90, subscription.CARD_TARIFFS["3m"]["amount"]))
    check("havola buyurtmaga bog'langan", "ac.order_id=pmxyz" in payload and "a=4500000" in payload, payload)
    with patch.dict(os.environ, {"PAYME_MERCHANT_ID": "mid", "PAYME_KEY": "k"}), \
         patch.object(subscription.db, "run_db", new=AsyncMock(side_effect=RuntimeError("db"))):
        got = asyncio.run(subscription._payme_checkout_url(USER_ID, "uz", "1m"))
    check("DB xatosi → tugma yashiriladi (ekran yiqilmaydi)", got is None)

    for lang in ("uz", "ru", "en"):
        text = get_text("payme_paid_notice", lang, days=30)
        check(f"payme_paid_notice lokalizatsiya ({lang})", "30" in text and "{" not in text)
        check(f"btn_pay_payme lokalizatsiya ({lang})", "Payme" in get_text("btn_pay_payme", lang))

    from services.payments import payme_webhook
    from services.payments.payme_provider import PaymeEvent

    class Bot:
        def __init__(self):
            self.sent = []

        async def send_message(self, **kwargs):
            self.sent.append(kwargs)

    bot = Bot()
    import database as db
    with patch.object(db, "run_db", new=AsyncMock(return_value="ru")):
        asyncio.run(payme_webhook.build_bot_notifier(bot)(PaymeEvent("paid", USER_ID, 30, "pm1")))
    check("bildirishnoma foydalanuvchi tilida yuboriladi",
          len(bot.sent) == 1 and bot.sent[0]["chat_id"] == USER_ID
          and bot.sent[0]["text"] == get_text("payme_paid_notice", "ru", days=30))


# ---------------------------------------------------------------------------
# 8) LIVE PostgreSQL (pgserver) — real locks, UNIQUE and CHECK constraints
# ---------------------------------------------------------------------------
def test_live_postgres():
    print("\n== 8) Real PostgreSQL (pgserver): DB darajasidagi idempotentlik ==")
    try:
        import pgserver
    except ImportError:
        print("  [SKIP] pgserver yo'q — live DB qismi o'tkazib yuborildi (pip install pgserver)")
        return
    import shutil
    import tempfile

    import database as db
    from repositories.payme_repository import PostgresPaymeStore

    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_payme")
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri
    db.DATABASE_URL = uri
    db._reset_pool()
    try:
        db.init_db()
        db.init_db()  # idempotent re-apply
        with db.db_cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")
            tables = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            indexes = {r[0] for r in cur.fetchall()}
        check("real baza: payme jadvallari yaratildi (init_db 2× idempotent)",
              set(db.PAYME_TABLES) <= tables, str(sorted(set(db.PAYME_TABLES) - tables)))
        check("real baza: payme indekslari", set(db.PAYME_INDEXES) <= indexes,
              str(sorted(set(db.PAYME_INDEXES) - indexes)))

        uid = 777001
        with db.db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO users (user_id, username) VALUES (%s, 'payme_live')", (uid,))

        def expiry_days():
            with db.db_cursor() as cur:
                cur.execute("SELECT plan_type, EXTRACT(EPOCH FROM (subscription_expires_at - NOW())) / 86400.0 "
                            "FROM users WHERE user_id = %s", (uid,))
                plan, days = cur.fetchone()
            return plan, float(days or 0)

        store = PostgresPaymeStore()
        clock = Clock()
        provider = PaymeProvider(store, CONFIG, clock=clock)
        order = provider.create_order(uid, "1m", 30, PRICE_UZS)
        acc = {"order_id": order.order_id}
        with patch("repositories.payme_repository._invalidate_user"), \
             patch("repositories.payme_repository._cache_clear"):
            resp, _ = rpc(provider, "CheckPerformTransaction", {"amount": PRICE_TIYIN, "account": acc})
            check("live: CheckPerformTransaction → allow", resp.get("result") == {"allow": True}, str(resp))
            resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="live-1"))
            check("live: CreateTransaction → state 1", (resp.get("result") or {}).get("state") == 1, str(resp))
            resp2, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="live-1"))
            check("live: takroriy Create → bir xil javob", resp2.get("result") == resp.get("result"))
            resp, _ = rpc(provider, "CreateTransaction", create_params(order, payme_id="live-other"))
            check("live: 2-faol tranzaksiya → -31052", err_code(resp) == ERR_ORDER_BUSY, str(resp))

            # 8 parallel PerformTransaction — real FOR UPDATE qulflari.
            barrier = threading.Barrier(8)
            results = []

            def worker():
                barrier.wait()
                results.append(rpc(provider, "PerformTransaction", {"id": "live-1"}))

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            check("live: 8 parallel Perform → hammasi state 2",
                  all((r[0].get("result") or {}).get("state") == 2 for r in results),
                  str([r[0] for r in results][:2]))
            check("live: 8 parallel Perform → faqat 1 ta 'paid' hodisa",
                  sum(len(r[1].paid_events) for r in results) == 1)
            check("live: perform_time hamma javobda bir xil",
                  len({(r[0].get("result") or {}).get("perform_time") for r in results}) == 1)

        plan, days = expiry_days()
        check("live: PRO aynan 30 kunga uzaytirildi (ikki marta emas)",
              plan == "pro" and 29.9 < days < 30.1, f"{plan} {days:.3f}")
        with db.db_cursor() as cur:
            cur.execute("SELECT COUNT(*), MIN(amount), MIN(currency), MIN(payment_method) FROM payments "
                        "WHERE telegram_payment_charge_id = 'payme:live-1'")
            count, amount, currency, method = cur.fetchone()
            cur.execute("SELECT status FROM payme_orders WHERE order_id = %s", (order.order_id,))
            order_status = cur.fetchone()[0]
            cur.execute("SELECT status, state FROM payme_transactions WHERE payme_transaction_id = 'live-1'")
            tx_row = cur.fetchone()
        check("live: payments ledger'da 1 qator (UZS, so'm, uzcard_humo)",
              count == 1 and amount == PRICE_UZS and currency == "UZS" and method == "uzcard_humo",
              f"{count} {amount} {currency} {method}")
        check("live: buyurtma 'paid', tranzaksiya ('paid', 2)",
              order_status == "paid" and tuple(tx_row) == ("paid", 2), f"{order_status} {tx_row}")
        history = db.get_user_payment_history(uid) or []
        check("live: mavjud to'lov tarixi ekranida 'card', UZS, 19 000 bo'lib ko'rinadi",
              any(item.get("method") == "card" and item.get("currency") == "UZS"
                  and item.get("amount") == PRICE_UZS for item in history), str(history))

        # Raw SQL bilan constraint'larni tekshirish (DB darajasidagi himoya).
        import psycopg2

        def violates(sql, params):
            try:
                with db.db_cursor(commit=True) as cur:
                    cur.execute(sql, params)
                return False
            except psycopg2.Error:
                return True

        insert_tx = ("INSERT INTO payme_transactions (payme_transaction_id, order_id, user_id, amount_tiyin, "
                     "status, state, payme_time, create_time) VALUES (%s, %s, %s, %s, %s, %s, 1, 1)")
        check("live DB: takroriy payme_transaction_id → UNIQUE xatosi",
              violates(insert_tx, ("live-1", order.order_id, uid, PRICE_TIYIN, "cancelled", -1)))
        order2 = provider.create_order(uid, "1m", 30, PRICE_UZS)
        check("live DB: status↔state ziddiyati → CHECK xatosi",
              violates(insert_tx, ("live-x", order2.order_id, uid, PRICE_TIYIN, "paid", 1)))
        check("live DB: noma'lum status → CHECK xatosi",
              violates(insert_tx, ("live-y", order2.order_id, uid, PRICE_TIYIN, "succeeded", 2)))
        check("live DB: noma'lum buyurtma → FOREIGN KEY xatosi",
              violates(insert_tx, ("live-z", "pm-missing", uid, PRICE_TIYIN, "pending", 1)))
        check("live DB: bitta buyurtmada 2 faol tx → partial UNIQUE xatosi",
              not violates(insert_tx, ("live-a1", order2.order_id, uid, PRICE_TIYIN, "pending", 1))
              and violates(insert_tx, ("live-a2", order2.order_id, uid, PRICE_TIYIN, "pending", 1)))
        check("live DB: bekor qilingan tx faol indeksni bloklamaydi",
              not violates(insert_tx, ("live-a3", order2.order_id, uid, PRICE_TIYIN, "cancelled", -1)))
        check("live DB: payme_orders status CHECK",
              violates("UPDATE payme_orders SET status = 'refunded' WHERE order_id = %s", (order2.order_id,)))

        # Parallel Create (turli id'lar, yangi buyurtma) — real UNIQUE poygasi.
        order3 = provider.create_order(uid, "1m", 30, PRICE_UZS)
        barrier = threading.Barrier(6)
        codes = []

        def creator(i):
            barrier.wait()
            r = rpc(provider, "CreateTransaction", create_params(order3, payme_id=f"live-pc-{i}"))[0]
            codes.append("ok" if "result" in r else err_code(r))

        threads = [threading.Thread(target=creator, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        check("live: 6 parallel Create → aynan 1 muvaffaqiyatli, 5 ta -31052",
              codes.count("ok") == 1 and codes.count(ERR_ORDER_BUSY) == 5, str(codes))

        # Cancel (state 1) va refund (opt-in) real bazada.
        winner = next(f"live-pc-{i}" for i in range(6)
                      if store_get_state(db, f"live-pc-{i}") == 1)
        resp, _ = rpc(provider, "CancelTransaction", {"id": winner, "reason": 3})
        check("live: Cancel state 1 → -1", (resp.get("result") or {}).get("state") == -1, str(resp))
        check("live: buyurtma 'pending' (qayta to'lash mumkin)",
              store_order_status(db, order3.order_id) == "pending")

        refund_provider = PaymeProvider(store, PaymeConfig(merchant_id="m", key=KEY, allow_refunds=True),
                                        clock=clock)
        with patch("repositories.payme_repository._invalidate_user"), \
             patch("repositories.payme_repository._cache_clear"):
            resp, _ = rpc(refund_provider, "CancelTransaction", {"id": "live-1", "reason": 5})
        plan, days = expiry_days()
        check("live: refund → state -2", (resp.get("result") or {}).get("state") == -2, str(resp))
        check("live: refund → PRO kunlari olindi, plan 'free'", plan == "free" and days < 0.01,
              f"{plan} {days:.3f}")
        with db.db_cursor() as cur:
            cur.execute("SELECT status FROM payments WHERE telegram_payment_charge_id = 'payme:live-1'")
            ledger_status = cur.fetchone()[0]
        check("live: ledger 'refunded'", ledger_status == "refunded")
        resp, _ = rpc(refund_provider, "GetStatement", {"from": 0, "to": 9_999_999_999_999})
        ids = sorted(t["id"] for t in (resp.get("result") or {}).get("transactions") or [])
        check("live: GetStatement = faqat saqlangan 4 tx (rad etilganlar rollback)",
              ids == sorted(["live-1", "live-a1", "live-a3", winner]), str(ids))
    finally:
        db.close_pool()
        try:
            server.cleanup()
        except Exception:  # noqa: BLE001
            pass
        shutil.rmtree(server_dir, ignore_errors=True)


def store_get_state(db, payme_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT state FROM payme_transactions WHERE payme_transaction_id = %s", (payme_id,))
        row = cur.fetchone()
    return row[0] if row else None


def store_order_status(db, order_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT status FROM payme_orders WHERE order_id = %s", (order_id,))
        row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    print("=" * 70)
    print(" PAYME MERCHANT API — unit + integration")
    print("=" * 70)
    test_basic_auth()
    test_full_flow()
    test_duplicate_callbacks()
    test_cancel_timeout_refund_and_errors()
    test_webhook_endpoint()
    test_postgres_store_and_schema()
    test_bot_wiring()
    test_live_postgres()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    print(" PAYME — 100% YASHIL ✔" if FAILED == 0 else " PAYME — XATOLAR BOR ✘")
    print("=" * 70)
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
