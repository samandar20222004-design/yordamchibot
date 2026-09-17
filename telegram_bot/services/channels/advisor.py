"""Weekly channel advisor and AI-report helpers.

The advisor is intentionally descriptive rather than causal.  It reports
observed associations and sample sizes, and every recommendation uses cautious
language ("appears to perform better", "may be associated with").  No claim in
this module says that a metric has a single certain cause.
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

CAUSAL_LANGUAGE = ("may be associated with", "appears to perform better", "could be worth testing")
FORBIDDEN_CAUSAL_PHRASES = ("definitely because", "the exact reason is", "aniq sabab shu", "точная причина")
_FORMAT_ALIASES = {"text": "text", "photo": "photo", "image": "photo", "video": "video", "animation": "animation", "document": "document", "poll": "poll", "media": "media"}


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _published(item: dict) -> bool:
    status = str(item.get("status") or "").lower()
    if item.get("published") or item.get("is_published") or status in {"published", "posted", "sent", "completed"}:
        return True
    if status in {"draft", "pending", "pending_approval", "approved", "scheduled", "cancelled", "failed"}:
        return False
    # channel_posts_history is a published-history source and often has no
    # status column; treat a dated history row as published by default.
    return bool(item.get("post_date") or item.get("published_at"))


def _format(item: dict) -> str:
    raw = item.get("format") or item.get("post_type") or item.get("type") or item.get("media_type")
    if raw:
        return _FORMAT_ALIASES.get(str(raw).lower(), str(raw).lower()[:32])
    return "media" if item.get("has_media") else "text"


def _metric(item: dict) -> float:
    for key in ("engagement_rate", "engagement", "views", "reactions", "score"):
        try:
            if item.get(key) is not None:
                return float(item[key])
        except (TypeError, ValueError):
            continue
    return 0.0


def _hour(item: dict) -> int | None:
    value = item.get("post_hour")
    if value is None:
        dt = _parse_dt(item.get("post_date") or item.get("created_at") or item.get("published_at"))
        return dt.hour if dt else None
    try:
        value = int(value)
        return value if 0 <= value <= 23 else None
    except (TypeError, ValueError):
        return None


def _in_week(item: dict, start: datetime, end: datetime) -> bool:
    raw = item.get("post_date") or item.get("created_at") or item.get("published_at")
    dt = _parse_dt(raw)
    return dt is None or start <= dt <= end


def _safe_mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def compute_weekly_insights(items: Iterable[dict], *, now: datetime | None = None,
                            days: int = 7) -> dict:
    """Compute a deterministic weekly report from published-post records.

    Records without a timestamp are accepted (useful for old history rows) and
    are included rather than silently inventing a date.  Empty data produces an
    honest empty report with no fabricated best time.
    """
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    start = end - timedelta(days=max(1, int(days)))
    source = [dict(item) for item in (items or ()) if isinstance(item, dict)]
    posts = [item for item in source if _published(item) and _in_week(item, start, end)]
    format_groups: dict[str, list[dict]] = defaultdict(list)
    hour_groups: dict[int, list[dict]] = defaultdict(list)
    weekday_groups: dict[int, list[dict]] = defaultdict(list)
    topic_groups: Counter[str] = Counter()
    for item in posts:
        format_groups[_format(item)].append(item)
        hour = _hour(item)
        if hour is not None:
            hour_groups[hour].append(item)
        dt = _parse_dt(item.get("post_date") or item.get("created_at") or item.get("published_at"))
        if dt:
            weekday_groups[dt.weekday()].append(item)
        topic = str(item.get("topic") or item.get("content_topic") or "").strip().lower()
        if topic:
            topic_groups[topic[:64]] += 1

    format_stats = []
    for name, rows in sorted(format_groups.items()):
        metrics = [_metric(row) for row in rows]
        format_stats.append({"format": name, "posts": len(rows), "average_metric": _safe_mean(metrics), "sample_size": len(rows)})
    format_stats.sort(key=lambda row: (-(row["average_metric"] or 0), -row["posts"], row["format"]))

    time_stats = []
    for hour, rows in hour_groups.items():
        metrics = [_metric(row) for row in rows]
        time_stats.append({"hour": hour, "time": f"{hour:02d}:00", "posts": len(rows), "average_metric": _safe_mean(metrics), "sample_size": len(rows)})
    time_stats.sort(key=lambda row: (-(row["average_metric"] or 0), -row["posts"], row["hour"]))

    published_formats = set(format_groups)
    # These are gaps in observed mix, not a claim that a format is inherently
    # better.  Keep the list compact for the weekly card.
    content_gaps = [name for name in ("text", "photo", "video", "poll") if name not in published_formats]
    recommendations: list[str] = []
    if time_stats:
        top = time_stats[0]
        recommendations.append(
            f"{top['time']} vaqti ushbu haftada yaxshiroq ko'rsatkich bilan bog'liq ko'rinadi; "
            "keyingi haftada shu vaqtni sinab ko'rish mumkin."
        )
    if format_stats:
        top = format_stats[0]
        recommendations.append(
            f"{top['format']} formati kichik namuna doirasida yaxshiroq ishlayotganga o'xshaydi; "
            "natijani yana bir necha post bilan tekshirish mumkin."
        )
    if content_gaps:
        recommendations.append("Kontent aralashmasida " + ", ".join(content_gaps[:3]) + " formatlari ko'rinmadi; ularni ehtiyotkorlik bilan test qilish mumkin.")
    if not recommendations:
        recommendations.append("Hali yetarli kuzatuv yo'q; turli vaqt va formatlarni kichik tajribalar bilan solishtirib boring.")

    report = {
        "ok": True,
        "period_days": max(1, int(days)),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "published_posts": len(posts),
        "posts_published": len(posts),
        "formats": format_stats,
        "format_stats": format_stats,
        "format_distribution": {row["format"]: row["posts"] for row in format_stats},
        "best_times": time_stats[:3],
        "best_posting_times": [row["time"] for row in time_stats[:3]],
        "best_time": time_stats[0] if time_stats else None,
        "content_gaps": content_gaps,
        "topic_distribution": dict(topic_groups.most_common(10)),
        "recommendations": recommendations,
        "observations": [
            "Bu natijalar kuzatilgan bog'liqliklarni ko'rsatadi, aniq sababni emas.",
            f"Hisob-kitob {len(posts)} ta e'lon qilingan post namunasi asosida tuzildi.",
        ],
        "sample_size": len(posts),
        "uncertainty_note": "Kichik namuna va tashqi omillar sabab tavsiyalar sinov sifatida ko'rilishi kerak.",
    }
    return report


# Public pure aliases
build_weekly_report = compute_weekly_insights
analyze_weekly = compute_weekly_insights


def render_report_card(report: dict, *, lang: str = "uz", channel_title: str = "Kanal") -> str:
    """Render an intentionally compact Telegram-safe plain/HTML card."""
    if not isinstance(report, dict) or not report.get("ok", True):
        return "📊 Haftalik hisobotni hozircha tuzib bo'lmadi."
    count = int(report.get("published_posts", report.get("posts_published", 0)) or 0)
    # Callers historically passed both raw and already-escaped titles.  Unescape
    # once and escape here so the weekly owner job cannot inject Telegram HTML.
    safe_title = html.escape(html.unescape(str(channel_title or "Kanal")))
    best = report.get("best_time") or ((report.get("best_times") or [None])[0])
    best_line = (f"{best.get('time')} — kichik kuzatuvda yaxshiroq ko'rinadi" if best else "Yetarli vaqt namunasi yo'q")
    formats = report.get("formats") or []
    format_line = ", ".join(f"{x.get('format')}: {x.get('posts')}" for x in formats[:3]) or "ma'lumot yo'q"
    gaps = ", ".join(report.get("content_gaps") or []) or "aniqlanmadi"
    recommendations = "\n".join(f"• {x}" for x in (report.get("recommendations") or [])[:3])
    if lang == "en":
        return (f"📊 <b>{safe_title} — weekly report</b>\n\n📝 Published: <b>{count}</b>\n"
                f"🕐 Best observed time: {best_line}\n🎛 Formats: {format_line}\n🧩 Gaps: {gaps}\n\n"
                f"💡 Recommendations\n{recommendations}\n\n<i>Associations are not proof of causation.</i>")
    if lang == "ru":
        return (f"📊 <b>{safe_title} — отчёт за неделю</b>\n\n📝 Опубликовано: <b>{count}</b>\n"
                f"🕐 Лучшее наблюдаемое время: {best_line}\n🎛 Форматы: {format_line}\n🧩 Пробелы: {gaps}\n\n"
                f"💡 Рекомендации\n{recommendations}\n\n<i>Связь не доказывает причину.</i>")
    return (f"📊 <b>{safe_title} — haftalik hisobot</b>\n\n📝 Chiqqan postlar: <b>{count}</b>\n"
            f"🕐 Yaxshiroq ko'ringan vaqt: {best_line}\n🎛 Formatlar: {format_line}\n🧩 Bo'shliqlar: {gaps}\n\n"
            f"💡 Tavsiyalar\n{recommendations}\n\n<i>Bog'liqlik aniq sababni isbotlamaydi.</i>")


format_weekly_report = render_report_card


async def _db_call(db: Any, name: str, *args, **kwargs):
    fn = getattr(db, name, None) if db is not None else None
    if not callable(fn):
        return None
    runner = getattr(db, "run_db", None)
    if callable(runner):
        return await runner(fn, *args, **kwargs)
    value = fn(*args, **kwargs)
    return await value if asyncio.iscoroutine(value) else value


class ChannelAdvisor:
    def __init__(self, db_module: Any = None):
        self.db = db_module or _load_database()

    async def weekly_report(self, channel_id: str | int, user_id: int, *, now=None, lang="uz") -> dict:
        channel = str(channel_id or "").strip()
        try:
            owner = await _db_call(self.db, "get_channel_owner_id", channel)
            if owner is None or int(owner) != int(user_id):
                from services.channels.team import check_permission
                if not await check_permission(channel, user_id, "view_analytics", self.db):
                    return {"ok": False, "error": "forbidden", "channel_id": channel}
        except Exception:
            return {"ok": False, "error": "forbidden", "channel_id": channel}
        records = await _db_call(self.db, "get_channel_weekly_posts", channel, 7)
        if records is None:
            records = await _db_call(self.db, "get_channel_posts_history", channel, 500)
        result = compute_weekly_insights(records or [], now=now)
        result["channel_id"] = channel
        return result

    async def advice(self, channel_id: str | int, user_id: int, *, now=None, lang="uz") -> dict:
        report = await self.weekly_report(channel_id, user_id, now=now, lang=lang)
        if report.get("ok") is False:
            return report
        report["card"] = render_report_card(report, lang=lang)
        return report


ChannelAdvisorService = ChannelAdvisor


def _load_database():
    try:
        import database
        return database
    except Exception:
        return None


async def build_channel_advice(channel_id, user_id, *, db_module=None, now=None, lang="uz") -> dict:
    return await ChannelAdvisor(db_module).advice(channel_id, user_id, now=now, lang=lang)


build_weekly_advisor_report = compute_weekly_insights
generate_weekly_report = compute_weekly_insights
get_channel_advice = build_channel_advice
report_card = render_report_card


__all__ = [
    "CAUSAL_LANGUAGE", "ChannelAdvisor", "ChannelAdvisorService",
    "FORBIDDEN_CAUSAL_PHRASES", "analyze_weekly", "build_channel_advice",
    "build_weekly_advisor_report", "build_weekly_report", "compute_weekly_insights",
    "format_weekly_report", "generate_weekly_report", "get_channel_advice",
    "render_report_card", "report_card",
]
