# -*- coding: utf-8 -*-
"""Kanal obunachilari o'sishi — kunlik snapshot'lardan HALOL hisob.

Telegram ``getChatMemberCount`` faqat JORIY sonni beradi; tarix bot yig'gan kunlik snapshot'lardan quriladi
(:func:`repositories.channels_repository.get_channel_member_history`). Qoidalar:

* faqat HAQIQIY snapshot'lar; mos eski snapshot yo'q bo'lsa ``delta = None`` (extrapolyatsiya / yaqin qiymatga taxmin YO'Q);
* ma'lumot kam yoki eskirgan bo'lsa ishonch darajasi (``confidence``) pasayadi;
* manba (``source``) va yig'ilgan vaqt (``collected_at``) har doim oshkor qilinadi.

Sof funksiya: DB/tarmoqqa tegmaydi (testlash oson).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

#: Delta uchun snapshot qancha "yaqin" bo'lishi mumkin (kun): ``{davr: ruxsat etilgan qo'shimcha kunlar}``.
DELTA_TOLERANCE_DAYS = {7: 3, 30: 7}
#: Oxirgi snapshot shundan eski bo'lsa ma'lumot "eskirgan" hisoblanadi.
STALE_AFTER_DAYS = 3


def _parse(entry):
    try:
        day = date.fromisoformat(str(entry["date"])[:10])
        count = int(entry["member_count"])
    except (KeyError, TypeError, ValueError):
        return None
    if count < 0:
        return None
    return day, count, entry.get("source"), entry.get("collected_at")


def compute_member_growth(history, *, today: date | None = None) -> dict:
    """``history`` — snapshot dict'lari (``date``, ``member_count``, ``source``, ``collected_at``), tartibi ixtiyoriy.

    Qaytadi: ``current``, ``as_of``, ``delta_7d``, ``delta_30d``, ``points``, ``span_days``, ``confidence``
    (``none|low|medium|high``), ``stale``, ``source``, ``collected_at``.
    """
    today = today or datetime.now().date()
    points = sorted((p for p in map(_parse, history or []) if p), key=lambda p: p[0], reverse=True)
    result = {"current": None, "as_of": None, "delta_7d": None, "delta_30d": None, "points": len(points),
              "span_days": 0, "confidence": "none", "stale": False, "source": None, "collected_at": None}
    if not points:
        return result

    latest_day, latest_count, source, collected_at = points[0]
    result.update({"current": latest_count, "as_of": latest_day.isoformat(), "source": source,
                   "collected_at": collected_at})
    result["span_days"] = (latest_day - points[-1][0]).days
    result["stale"] = (today - latest_day).days > STALE_AFTER_DAYS

    for days, tolerance in DELTA_TOLERANCE_DAYS.items():
        newest_allowed = latest_day - timedelta(days=days)
        oldest_allowed = latest_day - timedelta(days=days + tolerance)
        match = next((p for p in points[1:] if oldest_allowed <= p[0] <= newest_allowed), None)
        if match is not None:
            result[f"delta_{days}d"] = latest_count - match[1]

    n, span = len(points), result["span_days"]
    if n >= 15 and span >= 30:
        confidence = "high"
    elif n >= 4 and span >= 7:
        confidence = "medium"
    else:
        confidence = "low"
    if result["stale"] and confidence in ("medium", "high"):
        confidence = "low"
    result["confidence"] = confidence
    return result
