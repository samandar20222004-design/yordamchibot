"""Localized Uzbekistan national and seasonal content calendar.

⚠️ 2026-10 REFAKTOR — **BU MODUL ENDI YUPQA ADAPTER (SHIM).**

Bayram/mavsum ma'lumotlari endi Python kodida EMAS, balki
``telegram_bot/locales/calendars/*.json`` fayllarida saqlanadi va ularni
:class:`services.calendar_service.CalendarService` o'qiydi. Bu modul faqat
ESKI chaqiruvchi sirtini (``get_calendar_events`` va h.k.) saqlab qoladi va
har bir funksiyani ``country="UZ"`` bilan servisga delegatsiya qiladi.

Yangi, KO'P DAVLATLI kod uchun to'g'ridan-to'g'ri servisini ishlating::

    from services.calendar_service import get_calendar_service
    get_calendar_service().events(2026, country="JP")

Fixed public dates are generated every year. Ro'za and Qurbon hayit move with
the lunar calendar, so an arithmetic/tabular Hijri date is used as a useful
reminder estimate. Official Uzbek dates can differ by a day; deployments may
pass ``eid_date_overrides`` (``{"eid_al_fitr": date(...), ...}``) after the
annual official announcement.
"""

from __future__ import annotations

from datetime import date
from typing import Mapping

from services.calendar_service import (
    SUPPORTED_LANGS,
    CalendarEvent as UzbekistanCalendarEvent,
    coerce_date as _coerce_date,
    get_calendar_service,
    hijri_to_gregorian as _hijri_to_gregorian,
    normalize_calendar_lang as _lang,
)

#: Bu modul doim O'zbekiston qatlamini yechadi (nom shartnomasi).
COUNTRY = "UZ"


def _service():
    """Jarayon bo'yicha yagona :class:`CalendarService`."""
    return get_calendar_service()


def _overrides(eid_date_overrides: Mapping[str, date | str] | None) -> dict:
    return dict(eid_date_overrides or {})


def get_calendar_events(year: int, *,
                        eid_date_overrides: Mapping[str, date | str] | None = None,
                        country: str = COUNTRY,
                        ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return all fixed and movable Uzbekistan calendar entries for ``year``.

    ``eid_date_overrides`` is the official-date correction hook. Values for
    any event may be ``datetime.date`` or ISO ``YYYY-MM-DD``.
    """
    return _service().events(year, country, date_overrides=_overrides(eid_date_overrides))


def get_events_for_date(target_date: date, *,
                        eid_date_overrides: Mapping[str, date | str] | None = None,
                        country: str = COUNTRY,
                        ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return all entries that fall on ``target_date``."""
    return _service().events_for_date(target_date, country,
                                      date_overrides=_overrides(eid_date_overrides))


def get_events_for_reminder(today: date, days_before: int = 3, *,
                            eid_date_overrides: Mapping[str, date | str] | None = None,
                            country: str = COUNTRY,
                            ) -> tuple[UzbekistanCalendarEvent, ...]:
    """Return events exactly ``days_before`` days ahead of ``today``."""
    return _service().events_for_reminder(today, days_before, country,
                                          date_overrides=_overrides(eid_date_overrides))


def get_calendar_event(key: str, year: int, *,
                       eid_date_overrides: Mapping[str, date | str] | None = None,
                       country: str = COUNTRY,
                       ) -> UzbekistanCalendarEvent | None:
    """Look up a calendar event by stable key for callback validation."""
    return _service().event(key, year, country, date_overrides=_overrides(eid_date_overrides))


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


def _derive_movable_keys() -> tuple[str, ...]:
    """Hijri (oy) taqvimidagi sana kalitlari — JSON'dan olinadi."""
    try:
        return _service().movable_keys(COUNTRY)
    except Exception:  # pragma: no cover - himoya (modul importi yiqilmasin)
        return ("eid_al_fitr", "eid_al_adha", "ramadan_prep")


def _derive_seasonal_movable_keys() -> frozenset[str]:
    """Hijri hisobdagi, lekin ``season`` turidagi sana kalitlari (sanaga bog'liq emas)."""
    try:
        return frozenset(
            spec.key for spec in _service().event_specs(COUNTRY)
            if spec.is_movable and spec.kind == "season"
        )
    except Exception:  # pragma: no cover - himoya (modul importi yiqilmasin)
        return frozenset({"ramadan_prep"})


#: Eski modul darajasidagi konstantalar (orqaga moslik uchun saqlanadi).
#: Endi ular JSON ma'lumotidan KELIB CHIQADI, qattiq kodlanmaydi.
MOVABLE_EVENT_KEYS = _derive_movable_keys()
SEASONAL_MOVABLE_KEYS = _derive_seasonal_movable_keys()


def seasonal_movable_keys() -> frozenset[str]:
    """Hijri hisobdagi, lekin ``season`` turidagi sana kalitlari."""
    return _derive_seasonal_movable_keys()

__all__ = [
    "COUNTRY",
    "MOVABLE_EVENT_KEYS",
    "SEASONAL_MOVABLE_KEYS",
    "SUPPORTED_LANGS",
    "UzbekistanCalendarEvent",
    "calendar_post_topic",
    "calendar_reminder_text",
    "get_calendar_event",
    "get_calendar_events",
    "get_events_for_date",
    "get_events_for_reminder",
    "seasonal_movable_keys",
    # Ichki yordamchilar — eski testlar/monkeypatch sirti uchun qayta eksport.
    "_coerce_date",
    "_hijri_to_gregorian",
    "_lang",
]
