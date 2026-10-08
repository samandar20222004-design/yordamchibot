"""Localized Uzbekistan national and seasonal content calendar.

Fixed public dates are generated every year. Ro'za and Qurbon hayit move with
the lunar calendar, so an arithmetic/tabular Hijri date is used as a useful
reminder estimate. Official Uzbek dates can differ by a day; deployments may
pass ``eid_date_overrides`` (``{"eid_al_fitr": date(...), ...}``) after the
annual official announcement.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping


@dataclass(frozen=True)
class UzbekistanCalendarEvent:
    """One localized event or seasonal content opportunity."""

    key: str
    date: date
    names: Mapping[str, str]
    kind: str = "holiday"

    def name(self, lang: str = "uz") -> str:
        return self.names.get(_lang(lang), self.names["uz"])


_TEXT = {
    "new_year": {
        "uz": "Yangi yil", "ru": "Новый год", "en": "New Year",
    },
    "navruz": {
        "uz": "Navro'z", "ru": "Навруз", "en": "Navruz",
    },
    "remembrance_day": {
        "uz": "Xotira va qadrlash kuni", "ru": "День памяти и почестей",
        "en": "Day of Remembrance and Honor",
    },
    "admission_exam_season": {
        "uz": "Qabul va imtihon mavsumi", "ru": "Сезон поступления и экзаменов",
        "en": "Admissions and exam season",
    },
    "independence_day": {
        "uz": "Mustaqillik kuni", "ru": "День независимости",
        "en": "Independence Day",
    },
    "teachers_day": {
        "uz": "O'qituvchi va murabbiylar kuni", "ru": "День учителя и наставника",
        "en": "Teachers' and Mentors' Day",
    },
    "eid_al_fitr": {
        "uz": "Ro'za hayiti", "ru": "Рамазан-хайит (Ураза-байрам)",
        "en": "Eid al-Fitr",
    },
    "eid_al_adha": {
        "uz": "Qurbon hayiti", "ru": "Курбан-хайит (Курбан-байрам)",
        "en": "Eid al-Adha",
    },
}

_FIXED_EVENTS = (
    ("new_year", 1, 1, "holiday"),
    ("navruz", 3, 21, "holiday"),
    ("remembrance_day", 5, 9, "holiday"),
    # Start-of-season marker for useful admissions, exam-prep and student
    # guidance posts; it is intentionally not presented as a public holiday.
    ("admission_exam_season", 6, 1, "season"),
    ("independence_day", 9, 1, "holiday"),
    ("teachers_day", 10, 1, "holiday"),
)

SUPPORTED_LANGS = ("uz", "ru", "en")
MOVABLE_EVENT_KEYS = ("eid_al_fitr", "eid_al_adha")


def _lang(lang: str | None) -> str:
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else "uz"


def _hijri_to_gregorian(year: int, month: int, day: int) -> date:
    """Convert a tabular Islamic civil date to Gregorian (proleptic) date.

    This deterministic approximation is deliberately dependency-free. It is
    close to observed dates but is not a substitute for an official moon-sighting
    announcement.
    """
    y, m, d = int(year), int(month), int(day)
    if y < 1 or not 1 <= m <= 12 or d < 1:
        raise ValueError("invalid Hijri date")
    julian_day = (
        d
        + math.ceil(29.5 * (m - 1))
        + (y - 1) * 354
        + math.floor((3 + 11 * y) / 30)
        + 1948439.5
        - 1
    )
    ordinal = math.floor(julian_day + 0.5) - 1721425
    return date.fromordinal(ordinal)


def _coerce_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except (TypeError, ValueError):
            return None
    return None


def get_calendar_events(year: int, *,
                        eid_date_overrides: Mapping[str, date | str] | None = None
                        ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return all fixed and movable Uzbekistan calendar entries for ``year``.

    ``eid_date_overrides`` is the official-date correction hook. Values for
    either movable event may be ``datetime.date`` or ISO ``YYYY-MM-DD``.
    """
    year = int(year)
    if not 1900 <= year <= 2200:
        raise ValueError("year must be between 1900 and 2200")
    events = [
        UzbekistanCalendarEvent(key, date(year, month, day), _TEXT[key], kind)
        for key, month, day, kind in _FIXED_EVENTS
    ]

    overrides = dict(eid_date_overrides or {})
    # Hijri year ~= Gregorian year - 579; inspect adjacent years so the
    # Gregorian year boundary is handled without assumptions about month.
    computed: dict[str, date] = {}
    for hijri_year in range(max(1, year - 581), year - 577):
        for key, month, day in (
            ("eid_al_fitr", 10, 1),
            ("eid_al_adha", 12, 10),
        ):
            candidate = _hijri_to_gregorian(hijri_year, month, day)
            if candidate.year == year:
                computed.setdefault(key, candidate)

    for key in MOVABLE_EVENT_KEYS:
        event_date = _coerce_date(overrides.get(key)) or computed.get(key)
        if event_date is not None and event_date.year == year:
            events.append(UzbekistanCalendarEvent(key, event_date, _TEXT[key], "movable"))

    return tuple(sorted(events, key=lambda item: (item.date, item.key)))


def get_events_for_date(target_date: date, *,
                        eid_date_overrides: Mapping[str, date | str] | None = None
                        ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return all entries that fall on ``target_date``."""
    target = _coerce_date(target_date)
    if target is None:
        return ()
    return tuple(
        event for event in get_calendar_events(target.year,
                                                eid_date_overrides=eid_date_overrides)
        if event.date == target
    )


def get_events_for_reminder(today: date, days_before: int = 3, *,
                            eid_date_overrides: Mapping[str, date | str] | None = None
                            ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return events exactly ``days_before`` days ahead of ``today``."""
    current = _coerce_date(today)
    if current is None:
        return ()
    try:
        target = current + timedelta(days=max(0, int(days_before)))
    except (TypeError, ValueError, OverflowError):
        return ()
    return get_events_for_date(target, eid_date_overrides=eid_date_overrides)


def get_calendar_event(key: str, year: int, *,
                       eid_date_overrides: Mapping[str, date | str] | None = None
                       ) -> UzbekistanCalendarEvent | None:
    """Look up a calendar event by stable key for callback validation."""
    event_key = str(key or "").strip()
    return next((event for event in get_calendar_events(
        year, eid_date_overrides=eid_date_overrides) if event.key == event_key), None)


def calendar_reminder_text(event: UzbekistanCalendarEvent, lang: str = "uz") -> str:
    """Build the exact localized three-days-to-go suggestion."""
    code = _lang(lang)
    if code == "ru":
        return f"🗓 Через 3 дня — <b>{event.name(code)}</b>! Подготовим для канала поздравление или тематический пост?"
    if code == "en":
        return f"🗓 <b>{event.name(code)}</b> is in 3 days! Shall we prepare a greeting or themed post for your channel?"
    return f"🗓 3 kundan keyin <b>{event.name(code)}</b>! Kanalga tabrik yoki mavzuviy post tayyorlaymizmi?"


def calendar_post_topic(event: UzbekistanCalendarEvent, lang: str = "uz") -> str:
    """Localized, safe prompt seed used to open the existing Magic Post flow."""
    name = event.name(lang)
    code = _lang(lang)
    if code == "ru":
        return f"Подготовь для канала тёплое поздравление или тематический пост к событию «{name}»."
    if code == "en":
        return f"Write a warm greeting or themed channel post for {name}."
    return f"{name} munosabati bilan kanal uchun samimiy tabrik yoki mavzuviy post yoz."


__all__ = [
    "MOVABLE_EVENT_KEYS",
    "UzbekistanCalendarEvent",
    "calendar_post_topic",
    "calendar_reminder_text",
    "get_calendar_event",
    "get_calendar_events",
    "get_events_for_date",
    "get_events_for_reminder",
]
