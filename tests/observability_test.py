#!/usr/bin/env python3
"""PHASE 10 — structured logs, observability counters and protected health probes."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456789:PHASE10_TEST_TOKEN_123456789012345")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name}" + (f" -> {detail}" if detail else ""))


def test_scrubber_and_json_logging():
    print("== PHASE 10: secrets scrubber + JSON log formatter ==")
    from utils.sentry_scrubber import (
        JsonLogFormatter, SecretScrubbingFilter, REDACTED, register_secret,
        scrub_text, scrub_value,
    )

    bot_token = "987654321:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef_123456"
    openai_key = "sk-proj-" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    gemini_key = "AIza" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0"
    db_password = "postgresql://private_user:VerySecretPassw0rd@db.example.test/app"
    card = "8600 0609 5082 5589"
    ready_token = "health-check-secret-0123456789"
    for secret, label in ((ready_token, "HEALTH_READY_TOKEN"),):
        register_secret(secret, label)

    password_phrase = "secret password with spaces"
    dirty = (f"token={bot_token} openai={openai_key} gemini={gemini_key} "
             f"dsn={db_password} card_number={card} Bearer {ready_token} "
             f'password="{password_phrase}"')
    cleaned = scrub_text(dirty)
    leaked = [value for value in (bot_token, openai_key, gemini_key,
                                  "private_user", "VerySecretPassw0rd", card,
                                  ready_token, password_phrase) if value in cleaned]
    check("matn: bot/API token, DB credential, karta va bearer yashiriladi",
          not leaked, str(leaked))
    check("matn: scrub marker mavjud", "[REDACTED" in cleaned, cleaned)
    value = scrub_value({"openai_api_key": openai_key, "user_id": 42,
                         "payment_details": {"cvv": "123"}})
    check("dict: vendor-prefiksli API key va to'lov maydonlari yashiriladi",
          value["openai_api_key"] == REDACTED
          and value["payment_details"] == REDACTED and value["user_id"] == 42,
          str(value))

    record = logging.LogRecord(
        "observability.test", logging.ERROR, __file__, 10,
        "provider request failed token=%s card=%s", (bot_token, card), None,
    )
    record.user_id = 501
    record.channel_id = -100501
    record.latency_ms = 42.5
    record.error_code = "UPSTREAM_FAILED"
    record.api_key = openai_key
    scrub_filter = SecretScrubbingFilter()
    scrub_filter.filter(record)
    payload_text = JsonLogFormatter().format(record)
    try:
        payload = json.loads(payload_text)
        valid_json = True
    except ValueError:
        payload, valid_json = {}, False
    check("logger: har yozuv bir qatorli yaroqli JSON", valid_json, payload_text)
    check("logger: majburiy structured maydonlar mavjud",
          all(key in payload for key in (
              "timestamp", "level", "event", "user_id", "channel_id",
              "latency_ms", "error_code",
          )), str(payload))
    check("logger: context secrets scrub qilinadi",
          payload.get("context", {}).get("api_key") == REDACTED
          and openai_key not in payload_text and bot_token not in payload_text
          and card not in payload_text,
          payload_text)


def test_process_metrics():
    print("== PHASE 10: process metrics counters ==")
    from services import observability as metrics

    metrics.reset_metrics()
    metrics.record_active_user(10)
    metrics.record_active_user(10)
    metrics.record_active_user(11)
    metrics.record_ai_request(success=True, latency_ms=20, cost_usd=0.001)
    metrics.record_ai_request(success=False, latency_ms=40, cost_usd=0)

    class RetryAfter(Exception):
        error_code = 429

    metrics.record_telegram_request(status_code=200, latency_ms=10)
    metrics.record_telegram_request(error=RetryAfter("limited"), latency_ms=30)
    snap = metrics.snapshot()
    check("active users unique hisoblanadi", snap["active_users"]["daily"] == 2, str(snap))
    check("AI request/success/latency/cost yig'iladi",
          snap["ai_requests"] == 2 and snap["ai_success_rate"] == 0.5
          and snap["ai_latency_ms"] == 30 and snap["ai_cost_usd"] == 0.001,
          str(snap))
    check("Telegram API request va 429 hisoblanadi",
          snap["telegram_requests"] == 2 and snap["telegram_429"] == 1,
          str(snap))


def test_ai_and_telegram_instrumentation():
    print("== PHASE 10: AI service + Bot API instrumentation ==")
    from services import observability as metrics
    from services.ai_engine.app_service import AITaskService
    from services.ai_engine.gateway import GatewayResult
    from services.payment_service import PaymentService
    from telegram.ext import ExtBot
    from utils.telegram_delivery import SafeHTMLBot

    metrics.reset_metrics()

    class FakeGateway:
        async def generate(self, *args, **kwargs):
            return GatewayResult(
                ok=True, text="ok", task="simple_post", provider="Gemini",
                model="gemini-2.5-flash", status="success", elapsed=0.017,
            )

    service = AITaskService(gateway=FakeGateway())
    ai_result = asyncio.run(service.run(
        task="simple_post", prompt="safe test prompt", reserve_quota=False,
        persist_usage=False,
    ))

    class TooManyRequests(Exception):
        error_code = 429

    async def fake_post(self, endpoint, data, **kwargs):
        if endpoint == "429-method":
            raise TooManyRequests("limited")
        return {"ok": True}

    bot = object.__new__(SafeHTMLBot)
    with patch.object(ExtBot, "_do_post", fake_post):
        async def requests():
            await bot._do_post("sendMessage", {"text": "safe"})
            try:
                await bot._do_post("429-method", {})
            except TooManyRequests:
                pass
        asyncio.run(requests())

    rejected = PaymentService.process_stars_payment(
        user_id=42, charge_id="", amount=0, payload="", duration_days=0,
    )
    snap = metrics.snapshot()
    check("AITaskService natijasi AI request metrics'ga ulanadi",
          ai_result.ok and snap["ai_requests"] == 1
          and snap["ai_success_rate"] == 1.0
          and snap["ai_latency_ms"] == 17
          and snap["ai_cost_usd"] > 0, str(snap))
    check("SafeHTMLBot barcha API urinishlari va 429'ni qayd etadi",
          snap["telegram_requests"] == 2 and snap["telegram_429"] == 1,
          str(snap))
    check("PaymentService failure path payment counter'ga ulanadi",
          rejected.get("reason") == "invalid_payment"
          and snap["payment_failures"] == 1, str(snap))


def test_database_metric_aggregates():
    print("== PHASE 10: database durable metric aggregates ==")
    import database as db

    metric_row = (3, 8, 12, 9, 55.4, 0.123456, 48, 40, 61.5, 1.234567,
                  4, 30, 2, 1, 6, 3, 2, 5)

    class Cursor:
        def __init__(self, row):
            self.row = row
            self.sql = ""
            self.params = None

        def execute(self, sql, params=None):
            self.sql, self.params = sql, params

        def fetchone(self):
            return self.row

        def fetchall(self):
            return [(501,), (502,)]

    cursor = Cursor(metric_row)

    @contextmanager
    def fake_cursor(commit=False):
        yield cursor

    with patch("database.db_cursor", fake_cursor):
        result = db.get_observability_metrics()
    check("DB aggregates: rolling DAU/MAU", result["available"]
          and result["active_users_daily"] == 3
          and result["active_users_monthly"] == 8, str(result))
    check("DB aggregates: AI requests, latency, cost",
          result["ai_requests"] == 12 and result["ai_successes"] == 9
          and result["ai_latency_ms"] == 55.4 and result["ai_cost_usd"] == 0.123456,
          str(result))
    check("DB aggregates: posts and payment metrics",
          result["scheduled_posts"] == 4 and result["sent_posts"] == 30
          and result["failed_posts"] == 2 and result["delivery_queue_depth"] == 6
          and result["payment_failures"] == 5,
          str(result))
    check("DB metric SQL contains no user/message payload selection",
          "last_active_at" in cursor.sql and "ai_usage_events" in cursor.sql
          and "SELECT *" not in cursor.sql.upper(), cursor.sql[:120])

    with patch("database.db_cursor", side_effect=RuntimeError("db offline")):
        unavailable = db.get_observability_metrics()
    check("DB xatosi metrics query'ni yiqitmaydi", unavailable["available"] is False)


def test_user_activity_batch_flush():
    print("== PHASE 10: debounced active user persistence ==")
    from services import health_service as health
    from services import observability as metrics

    with health._activity_lock:
        health._pending_user_activity.clear()
        health._activity_flush_running = False
        health._activity_flush_done.set()
    metrics.reset_metrics()
    health.record_user_activity(777)
    health.record_user_activity(777)
    seen = {}

    async def fake_run_db(func, *args, **kwargs):
        seen["func"] = func
        seen["ids"] = list(args[0])
        return list(args[0])

    with patch.object(health.db, "run_db", fake_run_db):
        updated = asyncio.run(health.flush_user_activity())
    with health._activity_lock:
        remains = dict(health._pending_user_activity)
    check("activity flush deduplicates ID and persists asynchronously",
          updated == 1 and seen["ids"] == [777] and not remains,
          str({"updated": updated, "seen": seen, "pending": remains}))
    check("activity update does not retain payload", metrics.snapshot()["active_users"]["daily"] == 1)

    import database as db

    class ActivityCursor:
        sql = ""
        params = None

        def execute(self, sql, params=None):
            self.sql, self.params = sql, params

        def fetchall(self):
            return [(777,)]

    cursor = ActivityCursor()
    commit_flags = []

    @contextmanager
    def activity_db_cursor(commit=False):
        commit_flags.append(commit)
        yield cursor

    with patch("database.db_cursor", activity_db_cursor):
        touched = db.touch_user_activity([777, 777, 0])
    check("users repository update uses bounded IDs + RETURNING",
          touched == [777] and commit_flags == [True]
          and "last_active_at" in cursor.sql and cursor.params == ([777],),
          str({"ids": touched, "params": cursor.params, "sql": cursor.sql}))


def test_health_metrics_and_readiness():
    print("== PHASE 10: service metrics + readiness dependency checks ==")
    from services import health_service as health
    from services import observability as metrics
    import database as db

    metrics.reset_metrics()
    health.register_application(SimpleNamespace(
        _lock_manager=SimpleNamespace(_pending=3),
    ))
    persisted = {
        "available": True, "active_users_daily": 5, "active_users_monthly": 20,
        "ai_requests": 10, "ai_successes": 8, "ai_latency_ms": 125.0,
        "ai_cost_usd": 0.25, "ai_requests_monthly": 50,
        "ai_successes_monthly": 40, "ai_latency_ms_monthly": 110.0,
        "ai_cost_usd_monthly": 1.5, "scheduled_posts": 4, "sent_posts": 30,
        "failed_posts": 2, "failed_deliveries": 1,
        "delivery_queue_depth": 6,
        "payment_pending_receipts": 2, "payment_pending_orders": 1,
        "payment_failures": 3,
    }

    async def fake_run_db(func, *args, **kwargs):
        if func is db.get_observability_metrics:
            return persisted
        if func is db.ping_db:
            return True
        if func is db.get_db_pool_status:
            return {"ready": True, "used": 2, "available": 6, "max": 8}
        return {}

    async def healthy_redis():
        return {"status": "ok", "ok": True, "configured": True}

    class Scheduler:
        running = True

    health.register_scheduler(Scheduler())
    with patch.object(db, "_pool", object()), \
         patch.object(db, "run_db", fake_run_db), \
         patch.object(health, "_check_redis", healthy_redis):
        metrics_result = asyncio.run(health.get_observability_metrics(
            {"pool": {"used": 2, "available": 6, "max": 8}},
            {"pending": 4}, {"pending_receipts": 2},
        ))
        readiness = asyncio.run(health.get_readiness_status())

    check("HealthService exposes named production metrics",
          metrics_result["active_users"] == {"daily": 5, "monthly": 20}
          and metrics_result["ai_requests"] == 10
          and metrics_result["ai_success_rate"] == 0.8
          and metrics_result["ai_cost_usd"] == 0.25,
          str(metrics_result))
    check("health metrics include request, delivery, queue, pool, Redis, payments",
          metrics_result["telegram_requests"] == 0
          and metrics_result["scheduled_posts"] == 4
          and metrics_result["queue_depth"] == 9
          and metrics_result["delivery_queue_depth"] == 6
          and metrics_result["db_pool_usage"]["usage_ratio"] == 0.25
          and metrics_result["redis_status"] == "ok"
          and metrics_result["payment_pending"] == 3
          and metrics_result["payment_failures"] == 3,
          str(metrics_result))

    class FallbackRedis:
        async def ping(self):
            return True

        def stats(self):
            return {"backend": "resilient", "primary": "redis",
                    "using_fallback": True, "failures": 3}

    with patch("services.cache_backend.CacheSettings", return_value=SimpleNamespace(
        enabled=True, url="redis://credential-is-never-returned",
    )), patch("services.cache_backend.get_cache_backend", return_value=FallbackRedis()):
        redis_check = asyncio.run(health._check_redis())
    check("Redis fallback degraded holatda belgilanadi, DSN ochilmaydi",
          redis_check["status"] == "degraded"
          and redis_check["using_fallback"] is True
          and redis_check["failures"] == 3
          and "url" not in redis_check
          and "credential" not in str(redis_check), str(redis_check))

    check("readiness requires DB pool + Redis + scheduler",
          readiness["ready"] is True and all(
              readiness["checks"].get(name) in {"ok", "disabled"}
              for name in ("database", "redis", "scheduler")
          ), str(readiness))

    class StoppedScheduler:
        running = False

    health.register_scheduler(StoppedScheduler())
    with patch.object(db, "run_db", fake_run_db), \
         patch.object(health, "_check_redis", AsyncMock(return_value={
             "status": "degraded", "ok": False, "configured": True,
         })):
        not_ready = asyncio.run(health.get_readiness_status())
    check("Redis/scheduler nosoz bo'lsa readiness rad etiladi",
          not_ready["ready"] is False
          and not_ready["checks"]["redis"] == "degraded"
          and not_ready["checks"]["scheduler"] == "error",
          str(not_ready))

    health.register_scheduler(None)
    health.register_application(None)


def test_health_http_endpoints_are_private():
    print("== PHASE 10: public liveness vs authenticated readiness ==")
    from utils import web_server

    old_token = os.environ.pop("HEALTH_READY_TOKEN", None)

    class Request:
        def __init__(self, headers=None):
            self.headers = headers or {}

    try:
        no_config = asyncio.run(web_server.health_ready_handler(Request()))
        check("readiness auth token yo'q bo'lsa endpoint fail-closed",
              no_config.status == 404 and "checks" not in no_config.text,
              no_config.text)

        secret = "internal-ready-secret-0123456789"
        os.environ["HEALTH_READY_TOKEN"] = secret
        unauthorized = asyncio.run(web_server.health_ready_handler(Request({
            "Authorization": "Bearer wrong-token-value",
        })))
        check("noto'g'ri token 401 va metrics bermaydi",
              unauthorized.status == 401 and "metrics" not in unauthorized.text,
              unauthorized.text)

        ready_payload = {"ready": True, "checks": {
            "database": "ok", "redis": "disabled", "scheduler": "ok",
        }}
        with patch("services.health_service.get_readiness_status",
                   AsyncMock(return_value=ready_payload)):
            authorized = asyncio.run(web_server.health_ready_handler(Request({
                "Authorization": f"Bearer {secret}",
            })))
        parsed = json.loads(authorized.text)
        check("valid token internal readiness JSON 200",
              authorized.status == 200 and parsed["status"] == "ready"
              and "metrics" not in parsed and secret not in authorized.text,
              authorized.text)

        live = asyncio.run(web_server.health_live_handler(Request()))
        live_json = json.loads(live.text)
        check("public /health/live 200, faqat process liveness",
              live.status == 200 and live_json.get("status") == "live"
              and "metrics" not in live_json and "checks" not in live_json,
              live.text)
    finally:
        if old_token is None:
            os.environ.pop("HEALTH_READY_TOKEN", None)
        else:
            os.environ["HEALTH_READY_TOKEN"] = old_token


def main():
    test_scrubber_and_json_logging()
    test_process_metrics()
    test_ai_and_telegram_instrumentation()
    test_database_metric_aggregates()
    test_user_activity_batch_flush()
    test_health_metrics_and_readiness()
    test_health_http_endpoints_are_private()
    print("-" * 68)
    print(f"PHASE 10 OBSERVABILITY: passed={passed}, failed={failed}")
    if failed:
        raise SystemExit(1)
    print("PHASE 10 OBSERVABILITY — GREEN")


if __name__ == "__main__":
    main()
