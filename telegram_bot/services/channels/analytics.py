# -*- coding: utf-8 -*-
"""📊 CHANNEL ANALYTICS SERVICE — N+1'siz kanal tahlili (P1 / 5-qadam).

Muammo (topshiriq)
------------------
Kanalning oxirgi 50–100 ta posti o'rganilganda har bir post uchun
alohida SQL SELECT (reaksiyalar, ko'rishlar, metrikalar) yuborilar edi
— klassik **N+1 query**. Foydalanuvchilar soni oshganda bu DB
connection pool'ini to'ldirib, botning javob tezligini tushiradi.

Yechim
------
Barcha metrikalar ``repositories.analytics_repository`` orqali **batch**
ko'rinishida olinadi:

    * postlar metrikasi  → 1 SQL (``LEFT JOIN`` + ``GROUP BY``);
    * kanal xulosasi     → 1 SQL (DB darajasidagi agregatsiya).

``analyze_channel_posts`` shu sababli 50 ta post uchun ham, 100 ta post
uchun ham **ko'pi bilan 2 ta DB chaqiruvi** qiladi (50 emas, 100 emas).

Qatlam: SERVICE — API/DB detallarini yashiradi, RBAC/IDOR tekshiradi.
"""

from __future__ import annotations

import logging
from typing import Any

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

#: Ishonchli xulosa chiqarish uchun minimal postlar soni (soxta raqam YO'Q).
MIN_POSTS_FOR_ANALYTICS = 5

#: Bitta tahlil oynasida o'qiladigan standart postlar soni.
DEFAULT_ANALYTICS_LIMIT = 100

#: Agregatsiya oynasi (kun).
DEFAULT_ANALYTICS_DAYS = 30


# ---------------------------------------------------------------------------
# Ichki yordamchilar
# ---------------------------------------------------------------------------

def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    """``run_db`` (thread offload) orqali yoki to'g'ridan-to'g'ri chaqiradi."""
    run_db = getattr(db, "run_db", None)
    if run_db is not None:
        return await run_db(fn, *args, **kwargs)
    return fn(*args, **kwargs)


def _has(db: Any, name: str) -> bool:
    return db is not None and callable(getattr(db, name, None))


def _empty_summary() -> dict:
    return {
        "posts": 0,
        "total_views": 0,
        "avg_views": 0.0,
        "max_views": 0,
        "total_reactions": 0,
        "events": 0,
        "media_posts": 0,
        "cta_posts": 0,
        "best_hour": None,
        "best_weekday": None,
        "best_format": None,
        "best_formats": [],
        "format_distribution": {},
    }


def summarize_posts_locally(posts, days: int = DEFAULT_ANALYTICS_DAYS) -> dict:
    """Postlar ro'yxatidan xulosani Python'da hisoblaydi (PURE, fallback).

    DB darajasidagi agregatsiya mavjud bo'lmaganda ishlatiladi — natija
    :func:`get_channel_analytics_summary` bilan bir xil kalitlarga ega.
    Hech qachon istisno ko'tarmaydi.
    """
    summary = _empty_summary()
    summary["days"] = max(1, int(days or DEFAULT_ANALYTICS_DAYS))
    rows = [p for p in (posts or ()) if isinstance(p, dict)]
    if not rows:
        return summary
    views = []
    hour_counts: dict = {}
    weekday_counts: dict = {}
    total_reactions = 0
    format_distribution: dict = {}
    for post in rows:
        try:
            post_views = int(post.get("views") or 0)
        except (TypeError, ValueError):
            post_views = 0
        views.append(post_views)
        try:
            total_reactions += int(post.get("reactions") or 0)
        except (TypeError, ValueError) as _silent_exc:
            log_silent_failure("services.channels.analytics:summarize_posts_locally", _silent_exc)
        fmt = str(post.get("format") or "text").strip().lower() or "text"
        format_distribution[fmt] = format_distribution.get(fmt, 0) + 1
        hour = post.get("post_hour")
        if isinstance(hour, int):
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
        weekday = post.get("post_weekday")
        if isinstance(weekday, int):
            weekday_counts[weekday] = weekday_counts.get(weekday, 0) + 1
    summary["posts"] = len(rows)
    summary["total_views"] = sum(views)
    summary["avg_views"] = round(sum(views) / len(views), 1) if views else 0.0
    summary["max_views"] = max(views) if views else 0
    summary["total_reactions"] = total_reactions
    summary["events"] = sum(
        1 for p in rows if p.get("post_hour") is not None or p.get("post_weekday") is not None
    )
    summary["media_posts"] = sum(1 for p in rows if p.get("has_media"))
    summary["cta_posts"] = sum(1 for p in rows if p.get("cta_detected"))
    if hour_counts:
        summary["best_hour"] = sorted(hour_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    if weekday_counts:
        summary["best_weekday"] = sorted(
            weekday_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )[0][0]
    if format_distribution:
        ranked = sorted(format_distribution.items(), key=lambda kv: (-kv[1], kv[0]))
        summary["best_format"] = ranked[0][0]
        views_by_format: dict = {}
        for post in rows:
            fmt = str(post.get("format") or "text").strip().lower() or "text"
            try:
                post_views = int(post.get("views") or 0)
            except (TypeError, ValueError):
                post_views = 0
            bucket = views_by_format.setdefault(fmt, [0, 0])
            bucket[0] += post_views
            bucket[1] += 1
        summary["best_formats"] = [
            fmt for fmt, _ in sorted(
                ((fmt, acc[0] / acc[1] if acc[1] else 0) for fmt, acc in views_by_format.items()),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ]
    summary["format_distribution"] = format_distribution
    return summary


# ---------------------------------------------------------------------------
# 1) DB DARAJASIDAGI XULOSA — 1 DB chaqiruvi
# ---------------------------------------------------------------------------

async def get_channel_analytics_snapshot(
    channel_id: str | int,
    user_id: int | None = None,
    *,
    days: int = DEFAULT_ANALYTICS_DAYS,
    db_module: Any = None,
) -> dict:
    """Kanal bo'yicha agregatlangan xulosa — **1 DB chaqiruvi**.

    Kanal DNA va Content Learning Loop uchun o'rtacha ko'rishlar,
    eng yaxshi formatlar va eng faol soat DB darajasida hisoblanadi
    (``analytics_repository.get_channel_analytics_summary``).

    RBAC/IDOR: ``user_id`` berilganda kanal egasi AYNAN shu
    foydalanuvchi bo'lishi shart — aks holda ``FORBIDDEN``.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL",
                "message": "Kanal ID bo'sh"}
    db = db_module if db_module is not None else _import_database()
    if db is None:
        return {"ok": False, "error_code": "DB_UNAVAILABLE",
                "message": "Baza mavjud emas"}

    if user_id is not None:
        owner_ok = await _check_owner(db, ch_id, user_id)
        if not owner_ok:
            return {
                "ok": False,
                "error_code": "FORBIDDEN",
                "channel_id": ch_id,
                "message": "Bu kanal sizga tegishli emas — tahlil faqat "
                           "kanal egasiga ochiladi.",
            }

    if _has(db, "get_channel_analytics_summary"):
        try:
            summary = await _db_call(db, db.get_channel_analytics_summary, ch_id, days)
        except Exception as e:  # pragma: no cover — fail-soft
            logger.warning("analytics snapshot xatosi (%s): %s", ch_id, e)
            summary = None
        if isinstance(summary, dict) and summary:
            return {"ok": True, "channel_id": ch_id, "summary": summary,
                    "query_count": 1, "batched": True, "source": "db_aggregate"}

    # Zaxira: db_aggregate yo'q — bo'sh (nolli) xulosa (soxta raqam YO'Q).
    return {"ok": True, "channel_id": ch_id, "summary": _empty_summary(),
            "query_count": 0, "batched": False, "source": "unavailable"}


async def _check_owner(db: Any, channel_id: str, user_id: int) -> bool:
    """Kanal egasini tekshiradi (fail-closed: xato bo'lsa — ruxsat yo'q)."""
    if not _has(db, "get_channel_owner_id"):
        return False
    try:
        owner = await _db_call(db, db.get_channel_owner_id, channel_id)
    except Exception:
        return False
    if owner is None:
        return False
    try:
        return int(owner) == int(user_id)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# 2) TO'LIQ KANAL TAHLILI — ko'pi bilan 2 DB chaqiruvi
# ---------------------------------------------------------------------------

async def analyze_channel_posts(
    channel_id: str | int,
    user_id: int | None = None,
    *,
    limit: int = DEFAULT_ANALYTICS_LIMIT,
    days: int = DEFAULT_ANALYTICS_DAYS,
    db_module: Any = None,
) -> dict:
    """Kanalning oxirgi ``limit`` postini BATCH ko'rinishida tahlil qiladi.

    DB chaqiruvlari soni **qat'iy cheklangan**: postlar soni qancha
    bo'lishidan qat'i nazar 2 tadan oshmaydi (1 ta JOIN/GROUP BY +
    1 ta agregatsiya) — N+1 query yo'q.

    Qaytadi::

        {"ok": True, "channel_id", "posts": [...], "summary": {...},
         "query_count": 2, "batched": True, "insufficient": bool,
         "formats": {...}, "avg_views": float}
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL",
                "message": "Kanal ID bo'sh"}
    try:
        safe_limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        safe_limit = DEFAULT_ANALYTICS_LIMIT
    try:
        safe_days = max(1, int(days))
    except (TypeError, ValueError):
        safe_days = DEFAULT_ANALYTICS_DAYS

    db = db_module if db_module is not None else _import_database()
    if db is None:
        return {"ok": False, "error_code": "DB_UNAVAILABLE",
                "message": "Baza mavjud emas"}

    if user_id is not None and not await _check_owner(db, ch_id, user_id):
        return {
            "ok": False,
            "error_code": "FORBIDDEN",
            "channel_id": ch_id,
            "message": "Bu kanal sizga tegishli emas — tahlil faqat "
                       "kanal egasiga ochiladi.",
        }

    posts: list = []
    summary: dict | None = None
    query_count = 0

    # BATCH #1 — postlar metrikasi (JOIN + GROUP BY, 1 SQL).
    if _has(db, "get_channel_posts_metrics_batch"):
        try:
            rows = await _db_call(db, db.get_channel_posts_metrics_batch, ch_id, safe_limit)
            posts = [r for r in (rows or []) if isinstance(r, dict)]
            query_count += 1
        except Exception as e:  # pragma: no cover — fail-soft
            logger.warning("analyze_channel_posts: postlar metrikasi xatosi %s", e)
    elif _has(db, "get_channel_posts_history"):
        # Zaxira yo'l (eski API): 1 chaqiruv, metrikalar nolga to'ldiriladi.
        try:
            rows = await _db_call(db, db.get_channel_posts_history, ch_id, safe_limit)
            posts = [_legacy_row_to_metric(r) for r in (rows or [])]
            query_count += 1
        except Exception as e:  # pragma: no cover — fail-soft
            logger.warning("analyze_channel_posts: history xatosi %s", e)

    # BATCH #2 — DB darajasidagi agregatsiya (1 SQL).
    if _has(db, "get_channel_analytics_summary"):
        try:
            result = await _db_call(db, db.get_channel_analytics_summary, ch_id, safe_days)
            if isinstance(result, dict) and result:
                summary = result
                query_count += 1
        except Exception as e:  # pragma: no cover — fail-soft
            logger.warning("analyze_channel_posts: xulosa xatosi %s", e)

    if summary is None:
        summary = summarize_posts_locally(posts, days=safe_days)

    formats: dict = {}
    for post in posts:
        fmt = str(post.get("format") or "text").strip().lower() or "text"
        formats[fmt] = formats.get(fmt, 0) + 1

    return {
        "ok": True,
        "channel_id": ch_id,
        "posts": posts,
        "summary": summary,
        "formats": formats,
        "avg_views": summary.get("avg_views", 0.0),
        "best_formats": list(summary.get("best_formats") or []),
        "insufficient": len(posts) < MIN_POSTS_FOR_ANALYTICS,
        "query_count": query_count,
        "batched": query_count <= 2,
        "limit": safe_limit,
        "days": safe_days,
    }


def _legacy_row_to_metric(row) -> dict:
    """Eski ``get_channel_posts_history`` qatorini metrika dict'iga o'giradi."""
    if isinstance(row, dict):
        return {
            "post_id": row.get("id"),
            "message_id": row.get("message_id"),
            "content": row.get("content") or row.get("text") or "",
            "views": int(row.get("views") or 0),
            "post_date": row.get("post_date") or row.get("date") or "",
            "reactions": 0,
            "reactors": 0,
            "format": "text",
            "has_media": False,
            "media_type": None,
            "post_hour": None,
            "post_weekday": None,
            "length": 0,
            "cta_detected": False,
            "emoji_density": 0.0,
            "engagement_rate": 0.0,
        }
    values = list(row or []) + [None] * 7
    return {
        "post_id": values[0],
        "message_id": values[2],
        "content": values[3] or "",
        "views": int(values[4] or 0) if values[4] is not None else 0,
        "post_date": values[5].isoformat() if hasattr(values[5], "isoformat") else "",
        "reactions": 0,
        "reactors": 0,
        "format": "text",
        "has_media": False,
        "media_type": None,
        "post_hour": None,
        "post_weekday": None,
        "length": 0,
        "cta_detected": False,
        "emoji_density": 0.0,
        "engagement_rate": 0.0,
    }


def attach_analytics_summary(profile: dict | None, summary: dict | None) -> dict:
    """DNA profiliga xulosani QO'SHIMCHA kalit sifatida ulaydi (PURE).

    Mavjud kalitlar o'zgartirilmaydi — orqaga moslik 100% (eski
    iste'molchilar ``analytics_summary`` ni ko'rmasa ham ishlayveradi).
    """
    result = dict(profile) if isinstance(profile, dict) else {}
    if isinstance(summary, dict) and summary:
        result["analytics_summary"] = summary
        if summary.get("best_formats") and "high_performing_formats_value" not in result:
            result["high_performing_formats_value"] = list(summary["best_formats"])
        if not result.get("avg_views") and summary.get("avg_views") is not None:
            result["avg_views"] = summary.get("avg_views")
    return result


__all__ = [
    "DEFAULT_ANALYTICS_DAYS",
    "DEFAULT_ANALYTICS_LIMIT",
    "MIN_POSTS_FOR_ANALYTICS",
    "analyze_channel_posts",
    "attach_analytics_summary",
    "get_channel_analytics_snapshot",
    "summarize_posts_locally",
]
