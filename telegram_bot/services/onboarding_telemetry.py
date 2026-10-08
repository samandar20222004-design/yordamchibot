# -*- coding: utf-8 -*-
"""⏱ SPRINT 4 — ONBOARDING VA RETENTION TELEMETRIYASI (TTFP, D1/D7).

Nima o'lchanadi (SPRINT 4, 3-band):

* **TTFP (Time To First Post)** — foydalanuvchi ``/start`` bosgan paytdan
  (``users.created_at``) birinchi postni YARATGAN/REJALASHTIRGAN paytgacha
  (``scheduled_posts.created_at`` ning eng kichigi) o'tgan vaqt;
* **D1 / D7 retention** — ro'yxatdan o'tganidan keyin kamida 1/7 kun o'tgan
  va shundan keyin yana faollik ko'rsatgan foydalanuvchilar ulushi
  (``users.last_active_at`` asosida — bu PASTKI chegara: "kamida bir marta
  qaytgan", aktivlikning butun tarixi emas);
* **activation rate** — ro'yxatdan o'tganlardan nechtasi birinchi postni
  umuman yaratgan.

Manba: mavjud jadvallar (``users`` + ``scheduled_posts``) — YANGI jadval yo'q,
soxta raqam yo'q. Hisob-kitob funksiyalari TOZA (pure): ``now`` tashqaridan
beriladi, shuning uchun testlar deterministik.

Jarayon xotirasidagi hisoblagich (``record_start`` / ``record_first_post``)
qo'shimcha ravishda real vaqtda TTFP'ni kuzatadi (baza agregati esa
``/stats`` ekranida ishlatiladi).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

#: Standart kohorta oynasi (kun) — Sprint 4 yopiq beta davri.
DEFAULT_WINDOW_DAYS = 30
#: "Chaqqon start" chegaralari (soniya).
FAST_TTFP_SECONDS = 3600          # 1 soat
SAME_DAY_TTFP_SECONDS = 24 * 3600  # 1 kun
#: Baza agregati keshining TTL'i (soniya) — /stats ketma-ket bosilganda
#: og'ir so'rovni takrorlamaslik uchun.
FETCH_CACHE_TTL = 60

_LOCK = threading.RLock()


# ---------------------------------------------------------------------------
# Yordamchilar
# ---------------------------------------------------------------------------
def parse_moment(value) -> "datetime | None":
    """Har xil ko'rinishdagi vaqtni UTC ``datetime`` ga keltiradi.

    Qabul qiladi: ``datetime`` (naive → UTC), ISO satr, epoch soniya.
    Tushunilmasa — ``None`` (soxta qiymat qaytarilmaydi).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        text = str(value).strip()
    except Exception:  # noqa: BLE001
        return None
    if not text:
        return None
    candidate = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def ttfp_seconds(created_at, first_post_at) -> "float | None":
    """Ro'yxatdan o'tishdan birinchi postgacha o'tgan sekundlar.

    Manfiy qiymat (post ro'yxatdan oldin — ma'lumot nomuvofiqligi) → ``0.0``
    ("darhol" deb hisoblanadi, soxta manfiy son hisobotga tushmaydi).
    """
    start = parse_moment(created_at)
    first = parse_moment(first_post_at)
    if start is None or first is None:
        return None
    delta = (first - start).total_seconds()
    return 0.0 if delta < 0 else float(delta)


def _percentile(values: list, fraction: float) -> float:
    """Chiziqli interpolyatsiyasiz (nearest-rank) persentil — deterministik."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(math.ceil(fraction * len(ordered))) - 1
    index = max(0, min(index, len(ordered) - 1))
    return float(ordered[index])


def summarize_ttfp(seconds) -> dict:
    """TTFP qiymatlari bo'yicha yig'indi ko'rsatkichlar (pure).

    Bo'sh ro'yxat → nollar va ``available=False``.
    """
    values = [float(v) for v in (seconds or []) if v is not None and float(v) >= 0]
    if not values:
        return {
            "available": False, "count": 0, "avg_seconds": 0.0,
            "median_seconds": 0.0, "p90_seconds": 0.0, "min_seconds": 0.0,
            "max_seconds": 0.0, "within_1h_rate": 0.0, "within_24h_rate": 0.0,
        }
    count = len(values)
    return {
        "available": True,
        "count": count,
        "avg_seconds": round(sum(values) / count, 1),
        "median_seconds": round(_percentile(values, 0.5), 1),
        "p90_seconds": round(_percentile(values, 0.9), 1),
        "min_seconds": round(min(values), 1),
        "max_seconds": round(max(values), 1),
        "within_1h_rate": round(
            sum(1 for v in values if v <= FAST_TTFP_SECONDS) / count, 4),
        "within_24h_rate": round(
            sum(1 for v in values if v <= SAME_DAY_TTFP_SECONDS) / count, 4),
    }


def retention_rates(rows, *, now=None, day: int = 1) -> dict:
    """D-``day`` qaytish darajasi (``rows`` — ``get_retention_cohort`` natijasi).

    Formula (ochiq va deterministik):
        * bazadan faqat ro'yxatdan o'tganiga ``day`` kundan ko'p bo'lgan
          foydalanuvchilar kiradi;
        * "qaytdi" = ``last_active_at >= created_at + day kun``.

    Returns: ``{"rate", "returned", "eligible", "day"}`` (yaroqli emas →
    ``rate=0.0``, ``eligible=0`` — "ma'lumot yo'q" ma'nosi).
    """
    moment = parse_moment(now) or datetime.now(timezone.utc)
    day_delta = timedelta(days=int(day))
    eligible = 0
    returned = 0
    for row in rows or []:
        created = parse_moment(_row_get(row, "created_at"))
        if created is None:
            continue
        if created > moment - day_delta:
            continue  # kohorta hali yetilmagan
        eligible += 1
        last_active = parse_moment(_row_get(row, "last_active_at"))
        if last_active is not None and last_active >= created + day_delta:
            returned += 1
    return {
        "day": int(day),
        "eligible": eligible,
        "returned": returned,
        "rate": round(returned / eligible, 4) if eligible else 0.0,
    }


def _row_get(row, key):
    """Qator (dict / tuple) dan maydonni oladi (repository namunasiga mos)."""
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    index = {"user_id": 0, "created_at": 1, "last_active_at": 2,
             "first_post_at": 3}.get(key)
    if index is None:
        return None
    try:
        return row[index]
    except (IndexError, KeyError, TypeError):
        return None


def build_report(rows, *, now=None, window_days: int = DEFAULT_WINDOW_DAYS) -> dict:
    """Kohorta ma'lumotidan to'liq onboarding hisoboti (pure, deterministik).

    Returns::

        {"available": bool, "window_days": int, "registered": int,
         "activated": int, "activation_rate": float,
         "ttfp": {...summarize_ttfp...},
         "retention": {"d1": {...}, "d7": {...}},
         "generated_at": iso}
    """
    moment = parse_moment(now) or datetime.now(timezone.utc)
    total = 0
    activated = 0
    ttfp_values = []
    for row in rows or []:
        created = parse_moment(_row_get(row, "created_at"))
        if created is None:
            continue
        total += 1
        first_post = parse_moment(_row_get(row, "first_post_at"))
        if first_post is None:
            continue
        activated += 1
        value = ttfp_seconds(created, first_post)
        if value is not None:
            ttfp_values.append(value)
    return {
        "available": bool(rows),
        "window_days": int(window_days),
        "registered": total,
        "activated": activated,
        "activation_rate": round(activated / total, 4) if total else 0.0,
        "ttfp": summarize_ttfp(ttfp_values),
        "retention": {
            "d1": retention_rates(rows, now=moment, day=1),
            "d7": retention_rates(rows, now=moment, day=7),
        },
        "generated_at": moment.isoformat(),
    }


# ---------------------------------------------------------------------------
# Jarayon xotirasi (real vaqt) — baza bo'lmasa ham TTFP kuzatiladi
# ---------------------------------------------------------------------------
_MAX_EVENTS = 5_000
_starts: "dict[int, float]" = {}
_first_posts: "dict[int, float]" = {}


def record_start(user_id, ts: float | None = None) -> None:
    """``/start`` bosilgan paytni qayd etadi (birinchi marta — saqlanadi)."""
    if user_id is None:
        return
    with _LOCK:
        _starts.setdefault(int(user_id), float(ts if ts is not None else time.time()))
        _trim(_starts)


def record_first_post(user_id, ts: float | None = None) -> None:
    """Birinchi post yaratilgan paytni qayd etadi (keyingilar e'tiborsiz)."""
    if user_id is None:
        return
    with _LOCK:
        _first_posts.setdefault(int(user_id), float(ts if ts is not None else time.time()))
        _trim(_first_posts)


def _trim(store: dict) -> None:
    while len(store) > _MAX_EVENTS:
        store.pop(next(iter(store)))


def in_memory_report(*, now=None) -> dict:
    """Jarayon xotirasidagi TTFP hisoboti (birinchi post kutayotganlar ham)."""
    moment = parse_moment(now) or datetime.now(timezone.utc)
    with _LOCK:
        starts = dict(_starts)
        posts = dict(_first_posts)
    values = []
    waiting = 0
    for uid, started in starts.items():
        first = posts.get(uid)
        if first is None:
            waiting += 1
            continue
        value = ttfp_seconds(started, first)
        if value is not None:
            values.append(value)
    summary = summarize_ttfp(values)
    summary.update({
        "started": len(starts),
        "activated": len(values),
        "waiting": waiting,
        "activation_rate": round(len(values) / len(starts), 4) if starts else 0.0,
        "generated_at": moment.isoformat(),
        "source": "memory",
    })
    return summary


def reset() -> None:
    """Faqat testlar uchun — jarayon xotirasini tozalaydi."""
    with _LOCK:
        _starts.clear()
        _first_posts.clear()


# ---------------------------------------------------------------------------
# Baza agregati (TTL kesh bilan)
# ---------------------------------------------------------------------------
_cache: dict = {"at": 0.0, "days": None, "rows": None}


def reset_cache() -> None:
    """Keshni tozalaydi (testlar / yangi ma'lumot uchun)."""
    with _LOCK:
        _cache.update({"at": 0.0, "days": None, "rows": None})


def fetch_cohort(db_module, days: int = DEFAULT_WINDOW_DAYS,
                 *, ttl: int = FETCH_CACHE_TTL) -> list:
    """``users`` + ``scheduled_posts`` kohortasini o'qiydi (TTL kesh bilan).

    Baza xatosida ``[]`` qaytadi — statistika ekrani HECH QACHON yiqilmaydi.
    """
    if db_module is None or not hasattr(db_module, "get_retention_cohort"):
        return []
    moment = time.time()
    with _LOCK:
        if (_cache["rows"] is not None and _cache["days"] == int(days)
                and (moment - float(_cache["at"])) < max(0, int(ttl))):
            return list(_cache["rows"])
    try:
        rows = db_module.get_retention_cohort(int(days))
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("Onboarding kohortasini olishda xato: %s", exc)
        return []
    rows = list(rows or [])
    with _LOCK:
        _cache.update({"at": moment, "days": int(days), "rows": rows})
    return rows


def fetch_report(db_module, days: int = DEFAULT_WINDOW_DAYS, *, now=None,
                 ttl: int = FETCH_CACHE_TTL) -> dict:
    """Kohortadan to'liq hisobot (baza + jarayon xotirasi)."""
    rows = fetch_cohort(db_module, days, ttl=ttl)
    report = build_report(rows, now=now, window_days=days)
    report["source"] = "db"
    memory = in_memory_report(now=now)
    if memory.get("started"):
        report["memory"] = memory
    return report


__all__ = [
    "DEFAULT_WINDOW_DAYS",
    "FAST_TTFP_SECONDS",
    "FETCH_CACHE_TTL",
    "SAME_DAY_TTFP_SECONDS",
    "build_report",
    "fetch_cohort",
    "fetch_report",
    "in_memory_report",
    "parse_moment",
    "record_first_post",
    "record_start",
    "reset",
    "reset_cache",
    "retention_rates",
    "summarize_ttfp",
    "ttfp_seconds",
]
