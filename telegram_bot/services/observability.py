"""Bounded, process-local observability counters.

Durable business metrics (users, AI usage, delivery, payments) are aggregated
from PostgreSQL by ``health_service``. This module only holds counters that do
not have a safe existing durable event stream (Telegram API request attempts,
recent unique users before the activity flush, and best-effort fallbacks).
No request bodies, credentials, prompts, payment payloads, or usernames are
stored here.
"""
from __future__ import annotations

import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone


from utils.silent_errors import log_silent_failure

_LOCK = threading.RLock()
_MAX_ACTIVE_USERS = 100_000
_MAX_AGE_SECONDS = 31 * 24 * 60 * 60

_ai_by_hour: OrderedDict[datetime, dict] = OrderedDict()
_payment_failures_by_hour: OrderedDict[datetime, int] = OrderedDict()
_active_users: OrderedDict[int, float] = OrderedDict()
_telegram_requests = 0
_telegram_429 = 0
_telegram_latency_sum_ms = 0.0
_telegram_latency_count = 0


def _hour_bucket(now: datetime | None = None) -> datetime:
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return moment.replace(minute=0, second=0, microsecond=0)


def _number(value, default=0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _prune(now_epoch: float) -> None:
    cutoff = now_epoch - _MAX_AGE_SECONDS
    for user_id, seen_at in tuple(_active_users.items()):
        if seen_at < cutoff:
            _active_users.pop(user_id, None)
    while len(_active_users) > _MAX_ACTIVE_USERS:
        _active_users.popitem(last=False)
    oldest_hour = _hour_bucket(datetime.fromtimestamp(cutoff, tz=timezone.utc))
    for hour in tuple(_ai_by_hour):
        if hour < oldest_hour:
            _ai_by_hour.pop(hour, None)
    for hour in tuple(_payment_failures_by_hour):
        if hour < oldest_hour:
            _payment_failures_by_hour.pop(hour, None)


def record_active_user(user_id) -> None:
    """Record a recent unique active user without retaining message data."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return
    if uid <= 0:
        return
    now = time.time()
    with _LOCK:
        _active_users[uid] = now
        _active_users.move_to_end(uid)
        _prune(now)


def record_ai_request(*, success: bool, latency_ms=0, cost_usd=0.0) -> None:
    """Record one completed gateway request (cached responses count as requests)."""
    now = datetime.now(timezone.utc)
    hour = _hour_bucket(now)
    latency = max(0.0, _number(latency_ms))
    cost = max(0.0, _number(cost_usd))
    with _LOCK:
        bucket = _ai_by_hour.setdefault(hour, {
            "requests": 0, "successes": 0, "latency_sum_ms": 0.0,
            "latency_samples": 0, "cost_usd": 0.0,
        })
        bucket["requests"] += 1
        bucket["successes"] += int(bool(success))
        if latency > 0:
            bucket["latency_sum_ms"] += latency
            bucket["latency_samples"] += 1
        bucket["cost_usd"] += cost
        _ai_by_hour.move_to_end(hour)
        _prune(time.time())


def record_telegram_request(*, status_code=None, error=None, latency_ms=0) -> None:
    """Record a Telegram Bot API attempt and 429 response, without payload data."""
    global _telegram_requests, _telegram_429
    global _telegram_latency_sum_ms, _telegram_latency_count
    is_rate_limited = False
    try:
        is_rate_limited = int(status_code) == 429
    except (TypeError, ValueError) as _silent_exc:
        log_silent_failure("services.observability:record_telegram_request:104", _silent_exc)
    if error is not None:
        is_rate_limited = is_rate_limited or type(error).__name__ in {
            "RetryAfter", "RetryAfterError", "TooManyRequests",
        }
        try:
            is_rate_limited = is_rate_limited or int(getattr(error, "error_code", 0)) == 429
        except (TypeError, ValueError) as _silent_exc:
            log_silent_failure("services.observability:record_telegram_request:112", _silent_exc)
    latency = max(0.0, _number(latency_ms))
    with _LOCK:
        _telegram_requests += 1
        _telegram_429 += int(is_rate_limited)
        if latency > 0:
            _telegram_latency_sum_ms += latency
            _telegram_latency_count += 1


def record_payment_failure() -> None:
    """Best-effort process-local payment failure event (no payment identifiers)."""
    hour = _hour_bucket()
    with _LOCK:
        _payment_failures_by_hour[hour] = _payment_failures_by_hour.get(hour, 0) + 1
        _payment_failures_by_hour.move_to_end(hour)
        _prune(time.time())


def snapshot(now: datetime | None = None) -> dict:
    """Return bounded rolling 24-hour / 30-day process-local metrics."""
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    now_epoch = moment.timestamp()
    daily_cutoff = _hour_bucket(moment - timedelta(hours=24))
    monthly_cutoff = _hour_bucket(moment - timedelta(days=30))
    with _LOCK:
        _prune(now_epoch)
        daily_ai = [dict(bucket) for hour, bucket in _ai_by_hour.items()
                    if hour >= daily_cutoff]
        monthly_ai = [dict(bucket) for hour, bucket in _ai_by_hour.items()
                      if hour >= monthly_cutoff]
        day_payments = sum(count for hour, count in _payment_failures_by_hour.items()
                           if hour >= daily_cutoff)
        month_payments = sum(count for hour, count in _payment_failures_by_hour.items()
                             if hour >= monthly_cutoff)
        active_daily = sum(1 for seen in _active_users.values() if seen >= now_epoch - 86400)
        active_monthly = sum(1 for seen in _active_users.values() if seen >= now_epoch - 30 * 86400)
        telegram = {
            "requests": _telegram_requests,
            "rate_limits": _telegram_429,
            "latency_sum_ms": _telegram_latency_sum_ms,
            "latency_samples": _telegram_latency_count,
        }

    def aggregate(buckets):
        return {
            key: sum(float(bucket.get(key) or 0) for bucket in buckets)
            for key in ("requests", "successes", "latency_sum_ms", "latency_samples", "cost_usd")
        }

    day_ai = aggregate(daily_ai)
    month_ai = aggregate(monthly_ai)
    day_requests = int(day_ai["requests"])
    day_successes = int(day_ai["successes"])
    month_requests = int(month_ai["requests"])
    month_successes = int(month_ai["successes"])
    day_latency_count = int(day_ai["latency_samples"])
    day_latency = (float(day_ai["latency_sum_ms"]) / day_latency_count
                   if day_latency_count else 0.0)
    month_latency_count = int(month_ai["latency_samples"])
    month_latency = (
        float(month_ai["latency_sum_ms"]) / month_latency_count
        if month_latency_count else 0.0
    )
    return {
        "active_users": {"daily": active_daily, "monthly": active_monthly},
        "ai_requests": day_requests,
        "ai_requests_monthly": month_requests,
        "ai_success_rate": day_successes / day_requests if day_requests else 0.0,
        "ai_success_rate_monthly": month_successes / month_requests if month_requests else 0.0,
        "ai_latency_ms": round(day_latency, 1),
        "ai_latency_ms_monthly": round(month_latency, 1),
        "ai_cost_usd": round(float(day_ai.get("cost_usd") or 0.0), 6),
        "ai_cost_usd_monthly": round(float(month_ai["cost_usd"]), 6),
        "telegram_requests": telegram["requests"],
        "telegram_429": telegram["rate_limits"],
        "telegram_latency_ms": round(
            telegram["latency_sum_ms"] / telegram["latency_samples"], 1
        ) if telegram["latency_samples"] else 0.0,
        "payment_failures": int(day_payments),
        "payment_failures_monthly": int(month_payments),
    }


def reset_metrics() -> None:
    """Reset process-local counters (tests/diagnostics only)."""
    global _telegram_requests, _telegram_429
    global _telegram_latency_sum_ms, _telegram_latency_count
    with _LOCK:
        _ai_by_hour.clear()
        _payment_failures_by_hour.clear()
        _active_users.clear()
        _telegram_requests = 0
        _telegram_429 = 0
        _telegram_latency_sum_ms = 0.0
        _telegram_latency_count = 0
