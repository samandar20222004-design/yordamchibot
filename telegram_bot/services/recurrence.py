"""Takrorlanuvchi post modeli (sof mantiq, DB'siz) — mavjud ustunlarga joylanadi, sxema o'zgarmaydi.

``scheduled_posts`` ustunlari: ``recurrence_type`` (VARCHAR), ``recurrence_day`` (INTEGER), ``recurrence_time`` (TIME).

=================  ==============================================  =====================================
``recurrence_type``  ``recurrence_day``                                Ma'nosi
=================  ==============================================  =====================================
``none``           —                                               bir martalik
``daily``          —                                               har kuni ``recurrence_time`` da
``weekly``         0..6 (dushanba=0)                               haftada bir marta, shu kuni
``interval``       2..30                                           har N kunda (``recurrence_time`` da)
``twice``          0..1439 (ikkinchi vaqt, kun boshidan daqiqa)    har kuni IKKI vaqtda: ``recurrence_time`` (erta) va ``recurrence_day`` (kech)
``weekdays``       1..127 bitmask (bit i = hafta kuni i)           tanlangan hafta kunlari (dam olish, ish kunlari...)
``monthly``        1..31 (oyning kuni)                             har oyning shu kunida; oyda shu kun bo'lmasa (31-fevral) — oyning oxirgi kuni
=================  ==============================================  =====================================

``daily``/``weekly`` eski kod bilan to'liq mos; ``interval``/``weekdays``/``monthly`` faqat yangi (Mini App/AI/bot rejalash) yo'lidan yaratiladi.
Normalizatsiya: ``interval`` N=1 -> ``daily``; ``weekdays`` bitta kun -> ``weekly``, barcha 7 kun -> ``daily``.
Hamma hisob Asia/Tashkent vaqtida (Toshkentda yozgi vaqt yo'q, lekin kod ofsetni baribir qayta normallashtiradi).
"""
from __future__ import annotations

import calendar
from datetime import datetime, time, timedelta

import pytz

TASHKENT = pytz.timezone("Asia/Tashkent")
from services.user_timezone import utz  # noqa: E402 — foydalanuvchi vaqt zonasi (default Toshkent)

RECURRING_TYPES = ("daily", "weekly", "interval", "weekdays", "twice", "monthly")
INTERVAL_MIN_DAYS = 2
INTERVAL_MAX_DAYS = 30
WEEKEND_MASK = (1 << 5) | (1 << 6)            # shanba + yakshanba
WORKDAYS_MASK = sum(1 << d for d in range(5))   # dushanba..juma
ALL_DAYS_MASK = (1 << 7) - 1


def weekdays_to_mask(days) -> int:
    """Hafta kunlari ro'yxati (0..6) -> bitmask. Yaroqsiz qiymat -> ValueError."""
    mask = 0
    for d in days:
        if isinstance(d, bool) or not isinstance(d, int) or not 0 <= d <= 6:
            raise ValueError("weekday")
        mask |= 1 << d
    if mask == 0:
        raise ValueError("weekday")
    return mask


def mask_to_weekdays(mask: int) -> list[int]:
    return [d for d in range(7) if mask & (1 << d)]


def _as_time(value) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0, tzinfo=None)
    if isinstance(value, str):
        parts = value.strip().split(":")
        if len(parts) in (2, 3) and all(p.isdigit() for p in parts):
            h, m = int(parts[0]), int(parts[1])
            if 0 <= h <= 23 and 0 <= m <= 59:
                return time(h, m)
    raise ValueError("time")


def normalize_recurrence(rtype, rday, rtime):
    """(type, day, time) -> kanonik (type, day, time: datetime.time). Yaroqsiz -> ValueError.

    ``none`` / bo'sh turi uchun ``("none", None, None)`` qaytadi.
    """
    if rtype is None:
        rtype = "none"
    if not isinstance(rtype, str):
        raise ValueError("type")
    rtype = rtype.strip().lower()
    if rtype in ("none", ""):
        return "none", None, None
    if rtype not in RECURRING_TYPES:
        raise ValueError("type")
    t = _as_time(rtime)
    if rtype == "daily":
        return "daily", None, t
    if rtype == "weekly":
        if isinstance(rday, bool) or not isinstance(rday, int) or not 0 <= rday <= 6:
            raise ValueError("day")
        return "weekly", rday, t
    if rtype == "monthly":
        if isinstance(rday, bool) or not isinstance(rday, int) or not 1 <= rday <= 31:
            raise ValueError("day")
        return "monthly", rday, t
    if rtype == "interval":
        if isinstance(rday, bool) or not isinstance(rday, int) or not 1 <= rday <= INTERVAL_MAX_DAYS:
            raise ValueError("day")
        if rday == 1:
            return "daily", None, t
        return "interval", rday, t
    if rtype == "twice":
        first, second = twice_times(t, rday)
        return "twice", time_to_minutes(second), first
    # weekdays
    if isinstance(rday, bool) or not isinstance(rday, int) or not 1 <= rday <= ALL_DAYS_MASK:
        raise ValueError("day")
    if rday == ALL_DAYS_MASK:
        return "daily", None, t
    days = mask_to_weekdays(rday)
    if len(days) == 1:
        return "weekly", days[0], t
    return "weekdays", rday, t


def minutes_to_time(minutes: int) -> time:
    return time(int(minutes) // 60, int(minutes) % 60)


def time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def twice_times(rtime, rday) -> tuple[time, time]:
    """``twice`` turi: (erta vaqt, kech vaqt). Yaroqsiz -> ValueError."""
    t1 = _as_time(rtime)
    if isinstance(rday, bool) or not isinstance(rday, int) or not 0 <= rday <= 1439:
        raise ValueError("day")
    t2 = minutes_to_time(rday)
    if t1 == t2:
        raise ValueError("day")
    return (t1, t2) if t1 < t2 else (t2, t1)


def _at(date_moment: datetime, t: time) -> datetime:
    """Toshkent vaqtida shu kunning ``t`` vaqti (ofset qayta normallashtiriladi)."""
    naive = datetime(date_moment.year, date_moment.month, date_moment.day, t.hour, t.minute)
    return utz().localize(naive)


def _day_shift(moment: datetime, days: int) -> datetime:
    naive = datetime(moment.year, moment.month, moment.day) + timedelta(days=days)
    return utz().localize(naive.replace(hour=moment.hour, minute=moment.minute))


def _monthly_candidate(year: int, month: int, rday: int, t: time) -> datetime:
    """Shu oyning ``rday``-kuni ``t`` da; oyda shu kun bo'lmasa (masalan 31-fevral) — oyning oxirgi kuni."""
    last = calendar.monthrange(year, month)[1]
    return utz().localize(datetime(year, month, min(int(rday), last), t.hour, t.minute))


def next_monthly_occurrence(rday, rtime, now: datetime):
    """``monthly`` uchun ``now`` DAN KEYINGI chiqish: shu oyning kuni (hali o'tmagan bo'lsa), aks holda keyingi oy."""
    t = _as_time(rtime)
    if now.tzinfo is None:
        now = utz().localize(now)
    now = now.astimezone(utz())
    cand = _monthly_candidate(now.year, now.month, rday, t)
    if cand > now:
        return cand
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return _monthly_candidate(year, month, rday, t)


def next_extended_occurrence(rtype, rday, rtime, now: datetime):
    """``interval`` / ``weekdays`` uchun ``now`` DAN KEYINGI chiqish vaqti (aware, Toshkent). Boshqa tur -> None.

    ``now`` — odatda yuborilgan paytdagi vaqt: ``interval`` shu kundan N kun keyin ``rtime`` da (yuborish kechikib ketsa
    ham, vaqt-soat o'zgarmaydi); ``weekdays`` — ``now`` dan qat'iy keyingi mos kun.
    """
    t = _as_time(rtime)
    if now.tzinfo is None:
        now = utz().localize(now)
    now = now.astimezone(utz())
    if rtype == "monthly":
        return next_monthly_occurrence(int(rday), t, now)
    if rtype == "interval":
        n = int(rday)
        return _day_shift(_at(now, t), n)
    if rtype == "weekdays":
        mask = int(rday)
        for k in range(0, 8):
            cand = _day_shift(_at(now, t), k)
            if (mask >> cand.weekday()) & 1 and cand > now:
                return cand
    return None


def next_twice_occurrence(rtime, rday, now: datetime):
    """``twice`` uchun ``now`` DAN KEYINGI chiqish: bugungi qolgan vaqt, bo'lmasa ertangi birinchi."""
    first, second = twice_times(rtime, rday)
    if now.tzinfo is None:
        now = utz().localize(now)
    now = now.astimezone(utz())
    for k in (0, 1):
        for slot in (first, second):
            cand = _day_shift(_at(now, slot), k)
            if cand > now:
                return cand
    return None


def first_occurrence(rtype, rday, rtime, start: datetime):
    """Yaratish paytida BIRINCHI chiqish: ``start`` dan (kiritilgan) boshlab eng yaqin mos vaqt.

    ``daily``/``interval``: ``start`` o'zi (foydalanuvchi aniq vaqt tanlagan). ``weekly``/``weekdays``: ``start`` kuni mos
    bo'lmasa — keyingi mos kun (``rtime`` da). Hech narsa topilmasa ``None``.
    """
    t = _as_time(rtime)
    if start.tzinfo is None:
        start = utz().localize(start)
    start = start.astimezone(utz())
    if rtype in ("daily", "interval"):
        return start
    if rtype == "monthly":
        # Shu oyning kuni hali o'tmagan bo'lsa shu oy, aks holda keyingi oy.
        cand = _monthly_candidate(start.year, start.month, rday, t)
        if cand >= start:
            return cand
        year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
        return _monthly_candidate(year, month, rday, t)
    if rtype == "twice":
        first, second = twice_times(t, rday)
        for k in (0, 1):
            for slot in (first, second):
                cand = _day_shift(_at(start, slot), k)
                if cand >= start:
                    return cand
        return None
    mask = (1 << int(rday)) if rtype == "weekly" else int(rday)
    for k in range(0, 8):
        cand = _day_shift(_at(start, t), k)
        if (mask >> cand.weekday()) & 1 and cand >= start:
            return cand
    return None
