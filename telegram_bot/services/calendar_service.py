"""🌍 DINAMIK KO'P DAVLATLI KONTENT KALENDARI (``CalendarService``).

Nima uchun bu modul bor
-----------------------
Ilgari barcha bayram/mavsum sanalari :mod:`services.uzbekistan_calendar`
ichida **qattiq kodlangan** Python lug'atlari edi (``_TEXT`` /
``_FIXED_EVENTS``). Bu ikki muammo tug'dirardi:

1. Yangi davlat qo'shish = Python kodini o'zgartirish (reliz talab qiladi);
2. Xalqaro sanalar (Yangi yil, 8-mart, Qora juma, maktabga qaytish) davlat
   bayramlari bilan bitta faylda aralashib ketgan edi.

Endi **ma'lumot** (``locales/calendars/*.json``) va **mantiq**
(``services/calendar_service.py``) ajratilgan::

    locales/calendars/global.json   ← xalqaro sanalar (baza)
    locales/calendars/uz.json       ← O'zbekiston milliy sanalari (inherits: global)
    locales/calendars/<cc>.json     ← yangi davlat = YANGI JSON FAYL (kod o'zgarmaydi)

Yechish (resolution) tartibi
----------------------------
``resolve_country("uzb")`` → ``"UZ"``; ``resolve_country(None)`` → ``"UZ"``
(standart); ``resolve_country("JP")`` → ``"JP"`` (profil yo'q → faqat
``global`` qatlami). So'ngra::

    scopes_for("UZ") == ("global", "uz")     ← global baza + milliy qatlam
    scopes_for("JP") == ("global",)          ← faqat xalqaro (fallback)

Keyinroq kelgan qatlam bir xil ``key`` ni **override** qiladi: ya'ni
``uz.json`` ichidagi ``new_year`` xalqaro ``new_year`` ni almashtiradi.

Xavfsizlik (fail-soft)
----------------------
JSON fayli yo'q/buzilgan bo'lsa servis **hech qachon istisno bermaydi** —
buzilgan fayl o'tkazib yuboriladi, ``global`` qatlami esa doim mavjud
bo'lishi uchun kod ichida ham minimal zaxira (``_BUILTIN_GLOBAL``) bor.
Shu sababli taqvim xatosi botni yoki scheduler job'ini yiqita olmaydi.

Bu modul FAQAT stdlib'ga tayanadi (telegram/database import YO'Q).
"""

from __future__ import annotations

import json
import logging
import math
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping

logger = logging.getLogger(__name__)

#: ``telegram_bot/locales/calendars`` — barcha taqvim JSON fayllari shu yerda.
CALENDARS_DIR = Path(__file__).resolve().parent.parent / "locales" / "calendars"

#: Xalqaro (hech bir davlatga bog'liq bo'lmagan) qatlam nomi.
GLOBAL_SCOPE = "global"

#: Foydalanuvchi davlat tanlamagan bo'lsa ishlatiladigan standart.
DEFAULT_COUNTRY = "UZ"

SUPPORTED_LANGS = ("uz", "ru", "en")

MIN_YEAR = 1900
MAX_YEAR = 2200

#: ``when.type`` qiymatlari uchun ruxsat etilgan turlar (diagnostika uchun).
RULE_TYPES = ("fixed", "nth_weekday", "hijri")


# ---------------------------------------------------------------------------
# Til / sana yordamchilari
# ---------------------------------------------------------------------------
def normalize_calendar_lang(lang: Any) -> str:
    """Har qanday qiymatni ``uz``/``ru``/``en`` ga keltiradi (uz — fallback)."""
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else "uz"


#: Eski nom (orqaga moslik uchun ham saqlanadi).
_lang = normalize_calendar_lang


def coerce_date(value: Any) -> date | None:
    """``date`` yoki ISO ``YYYY-MM-DD`` matnini ``date`` ga aylantiradi."""
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()[:10])
        except (TypeError, ValueError):
            return None
    return None


def hijri_to_gregorian(year: int, month: int, day: int) -> date:
    """Tabulyar islom fuqarolik sanasini Grigorian sanaga o'giradi.

    Bu deterministik yaqinlashish ataylab hech qanday kutubxonaga bog'liq
    emas. Kuzatilgan sanalarga yaqin, lekin rasmiy oy-ko'rish e'lonini
    ALMASHTIRMAYDI — farq ``date_overrides`` bilan tuzatiladi.
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


def nth_weekday_of_month(year: int, month: int, weekday: int, nth: int) -> date | None:
    """Oy ichidagi ``nth``-chi ``weekday`` (0=dushanba … 6=yakshanba).

    ``nth`` manfiy bo'lsa oy OXIRIDAN sanaladi (``nth=-1`` — oxirgi).
    Qoida noto'g'ri bo'lsa ``None`` (masalan oyda 5-chi juma yo'q).
    """
    try:
        y, m, wd, n = int(year), int(month), int(weekday), int(nth)
    except (TypeError, ValueError):
        return None
    if not 1 <= m <= 12 or not 0 <= wd <= 6 or n == 0:
        return None
    first = date(y, m, 1)
    if n > 0:
        candidate = first + timedelta(days=(wd - first.weekday()) % 7 + (n - 1) * 7)
    else:
        if m == 12:
            last = date(y, 12, 31)
        else:
            last = date(y, m + 1, 1) - timedelta(days=1)
        candidate = last - timedelta(days=(last.weekday() - wd) % 7 + (-n - 1) * 7)
    return candidate if candidate.month == m else None


#: Kengaytiriladigan qoida reestri: ``when.type`` → ``(when, year) → date|None``.
RULE_RESOLVERS: dict[str, Callable[[Mapping[str, Any], int], date | None]] = {
    "fixed": lambda when, year: _resolve_fixed(when, year),
    "nth_weekday": lambda when, year: nth_weekday_of_month(
        year, when.get("month", 0), when.get("weekday", -1), when.get("nth", 0)
    ),
    "hijri": lambda when, year: _resolve_hijri(when, year),
}


def register_rule(rule_type: str, resolver: Callable[[Mapping[str, Any], int], date | None]) -> None:
    """Yangi ``when.type`` qoidasini ro'yxatga oladi (kengaytirish nuqtasi).

    Misol: ``register_rule("easter", my_easter_resolver)`` — shundan keyin
    JSON'da ``{"type": "easter", "offset": -2}`` ishlay boshlaydi.
    """
    key = str(rule_type or "").strip().lower()
    if key and callable(resolver):
        RULE_RESOLVERS[key] = resolver


def _resolve_fixed(when: Mapping[str, Any], year: int) -> date | None:
    try:
        return date(year, int(when.get("month", 0)), int(when.get("day", 0)))
    except (TypeError, ValueError):
        return None


def _resolve_hijri(when: Mapping[str, Any], year: int) -> date | None:
    """Grigorian ``year`` ichiga tushadigan hijri sanani topadi."""
    try:
        month, day = int(when.get("month", 0)), int(when.get("day", 0))
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12 or day < 1:
        return None
    # Hijri yili ≈ Grigorian yili − 579; yil chegarasini taxminsiz qamrab
    # olish uchun qo'shni yillar ham ko'rib chiqiladi.
    for hijri_year in range(max(1, year - 581), year - 577):
        try:
            candidate = hijri_to_gregorian(hijri_year, month, day)
        except (ValueError, OverflowError):
            continue
        if candidate.year == year:
            return candidate
    return None


def resolve_when(when: Mapping[str, Any] | None, year: int) -> date | None:
    """``when`` qoidasini aniq sanaga aylantiradi (noma'lum tur → ``None``)."""
    if not isinstance(when, Mapping):
        return None
    resolver = RULE_RESOLVERS.get(str(when.get("type") or "").strip().lower())
    if resolver is None:
        return None
    try:
        result = resolver(when, int(year))
    except (TypeError, ValueError, OverflowError):  # pragma: no cover - himoya
        return None
    return result if isinstance(result, date) else None


# ---------------------------------------------------------------------------
# Ma'lumot modellari
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CalendarEvent:
    """Bitta lokalizatsiya qilingan bayram yoki mavsumiy kontent imkoniyati."""

    key: str
    date: date
    names: Mapping[str, str]
    kind: str = "holiday"
    #: Sanani e'lon qilgan davlat kodi (``"UZ"``) yoki xalqaro qatlam uchun ``""``.
    country: str = DEFAULT_COUNTRY

    def name(self, lang: str = "uz") -> str:
        """Tilga mos nom; til topilmasa o'zbekcha, u ham bo'lmasa ``key``."""
        code = normalize_calendar_lang(lang)
        return self.names.get(code) or self.names.get("uz") or self.key

    @property
    def is_holiday(self) -> bool:
        return self.kind == "holiday"


@dataclass(frozen=True)
class EventSpec:
    """JSON'dan o'qilgan, hali sanaga aylantirilmagan sana tavsifi."""

    key: str
    scope: str
    kind: str
    names: Mapping[str, str]
    when: Mapping[str, Any]

    @property
    def is_movable(self) -> bool:
        return str(self.when.get("type") or "") == "hijri"


@dataclass(frozen=True)
class CalendarProfile:
    """Bitta ``locales/calendars/*.json`` faylining normallashtirilgan ko'rinishi."""

    scope: str
    country: str
    names: Mapping[str, str]
    aliases: tuple[str, ...]
    inherits: tuple[str, ...]
    events: tuple[EventSpec, ...]
    labels: Mapping[str, Mapping[str, str]]
    source: str = ""
    #: ISO-3166-1 alpha-3 kodi (``"UZB"``) — davlat normalizatsiyasi uchun.
    alpha3: str = ""

    def movable_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.events if spec.is_movable)


#: ``global.json`` o'qilmasa ham xalqaro qatlam ishlashi uchun minimal zaxira.
_BUILTIN_GLOBAL = CalendarProfile(
    scope=GLOBAL_SCOPE,
    country="",
    names={"uz": "Xalqaro", "ru": "Международный", "en": "International"},
    aliases=(),
    inherits=(),
    events=(
        EventSpec("new_year", GLOBAL_SCOPE, "holiday",
                  {"uz": "Yangi yil", "ru": "Новый год", "en": "New Year"},
                  {"type": "fixed", "month": 1, "day": 1}),
        EventSpec("women_day", GLOBAL_SCOPE, "holiday",
                  {"uz": "Xotin-qizlar kuni", "ru": "Международный женский день",
                   "en": "International Women's Day"},
                  {"type": "fixed", "month": 3, "day": 8}),
    ),
    labels={},
    source="<builtin>",
)

#: Keng tarqalgan ISO-3166 qisqartmalari (JSON profili bo'lmasa ham taniladi).
_BUILTIN_ALIASES: Mapping[str, str] = {
    "uz": "UZ", "uzb": "UZ", "uzbekistan": "UZ", "ozbekiston": "UZ",
    "o'zbekiston": "UZ", "o‘zbekiston": "UZ", "узбекистан": "UZ",
}


def _normalize_alias(value: Any) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


class CalendarService:
    """Davlat bo'yicha dinamik taqvim yechuvchi (JSON ma'lumot, kodsiz kengayadi).

    Misol::

        cal = CalendarService()
        cal.resolve_country("uzb")                      # 'UZ'
        cal.scopes_for("UZ")                            # ('global', 'uz')
        cal.events(2026, country="UZ")                  # global + UZ sanalari
        cal.events(2026, country="JP")                  # faqat global sanalar
        cal.upcoming(date(2026, 11, 1), country="UZ")   # yaqin sanalar
        cal.prompt_block(country="UZ", lang="uz")       # AI prompt bloki

    Servis thread-safe: profillar bir marta o'qiladi va keshlanadi;
    :meth:`reload` keshni tozalaydi.
    """

    def __init__(self, base_dir: str | Path | None = None,
                 default_country: str | None = DEFAULT_COUNTRY) -> None:
        self.base_dir = Path(base_dir) if base_dir else CALENDARS_DIR
        self.default_country = self._coerce_code(default_country) or DEFAULT_COUNTRY
        self._profiles: dict[str, CalendarProfile] | None = None
        self._aliases: dict[str, str] | None = None
        self._lock = threading.Lock()

    # -- yuklash / kesh -------------------------------------------------
    def reload(self) -> "CalendarService":
        """JSON fayllarini qayta o'qiydi (testlar va hot-reload uchun)."""
        with self._lock:
            self._profiles = None
            self._aliases = None
        self.profiles  # darhol yuklab, xato bo'lsa log qilamiz
        return self

    @property
    def profiles(self) -> dict[str, CalendarProfile]:
        """Scope → :class:`CalendarProfile` (birinchi murojaatda o'qiladi)."""
        cached = self._profiles
        if cached is not None:
            return cached
        with self._lock:
            if self._profiles is None:
                self._profiles = self._load_profiles()
            return self._profiles

    def _load_profiles(self) -> dict[str, CalendarProfile]:
        loaded: dict[str, CalendarProfile] = {GLOBAL_SCOPE: _BUILTIN_GLOBAL}
        try:
            paths = sorted(self.base_dir.glob("*.json"))
        except OSError:  # pragma: no cover - himoya
            logger.warning("Calendar directory unreadable: %s", self.base_dir, exc_info=True)
            paths = []
        for path in paths:
            profile = self._load_profile(path)
            if profile is not None:
                # global.json mavjud bo'lsa ichidagi zaxirani almashtiradi.
                loaded[profile.scope] = profile
        return loaded

    @staticmethod
    def _load_profile(path: Path) -> CalendarProfile | None:
        """Bitta JSON faylini o'qiydi; buzilgan fayl ``None`` (fail-soft)."""
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Calendar file skipped (unreadable/invalid JSON): %s", path.name,
                           exc_info=True)
            return None
        if not isinstance(payload, dict):
            logger.warning("Calendar file skipped (top level is not an object): %s", path.name)
            return None

        country_block = payload.get("country") if isinstance(payload.get("country"), dict) else {}
        events: list[EventSpec] = []
        raw_events = payload.get("events")
        for entry in raw_events if isinstance(raw_events, list) else []:
            spec = _event_spec(entry, str(payload.get("scope") or path.stem))
            if spec is not None:
                events.append(spec)
        return CalendarProfile(
            scope=str(payload.get("scope") or path.stem).strip().lower() or path.stem,
            country=CalendarService._coerce_code(country_block.get("code")) or "",
            names=_str_map(country_block.get("names")),
            aliases=tuple(_normalize_alias(a) for a in country_block.get("aliases", ())
                          if _normalize_alias(a)),
            alpha3=CalendarService._coerce_code(country_block.get("alpha3")) or "",
            inherits=tuple(str(s).strip().lower() for s in payload.get("inherits", ())
                           if str(s).strip()),
            events=tuple(events),
            labels=_label_map(payload.get("labels")),
            source=str(path),
        )

    @staticmethod
    def _coerce_code(value: Any) -> str:
        code = "".join(ch for ch in str(value or "") if ch.isalpha()).upper()
        return code[:2] if len(code) == 2 else (code if len(code) == 3 else "")

    # -- davlat normalizatsiyasi ---------------------------------------
    @property
    def aliases(self) -> dict[str, str]:
        """Alias/ISO-3 kod → ISO-2 davlat kodi indeksi."""
        cached = self._aliases
        if cached is not None:
            return cached
        index = {alias: code for alias, code in _BUILTIN_ALIASES.items()}
        for profile in self.profiles.values():
            if not profile.country:
                continue
            candidates = (profile.country, profile.alpha3, profile.scope, *profile.aliases)
            for candidate in candidates:
                key = _normalize_alias(candidate)
                if key:
                    index.setdefault(key, profile.country)
        with self._lock:
            if self._aliases is None:
                self._aliases = index
            return self._aliases

    def resolve_country(self, country: Any) -> str:
        """Har qanday kirishni ISO-2 davlat kodiga keltiradi.

        * ``None`` / bo'sh → :data:`DEFAULT_COUNTRY` (``"UZ"``);
        * tanilgan alias yoki ISO-3 (``"uzb"``, ``"o'zbekiston"``) → ``"UZ"``;
        * noma'lum, lekin ISO-2 shaklidagi kod (``"jp"``) → ``"JP"``
          (profili yo'q → faqat xalqaro qatlam);
        * tushunarsiz qiymat → :data:`DEFAULT_COUNTRY` (fail-safe).
        """
        raw = str(country if country is not None else "").strip()
        if not raw:
            return self.default_country
        compact = _normalize_alias(raw)
        if not compact:
            return self.default_country
        if compact == GLOBAL_SCOPE:
            # "global" — faqat xalqaro qatlam (davlat profili yo'q). Bu
            # fallback zanjirining oxirgi halqasi sifatida ishlatiladi.
            return ""
        known = self.aliases.get(compact)
        if known:
            return known
        letters = "".join(ch for ch in raw.upper() if ch.isalpha())
        if len(letters) == 2:
            return letters
        return self.default_country

    # -- qatlamlar (scopes) --------------------------------------------
    def available_countries(self) -> tuple[str, ...]:
        """Tanlash uchun taklif qilinadigan davlat kodlari.

        Faqat **kamida bitta yaroqli sanasi** bo'lgan profillar ko'rsatiladi
        (buzilgan/yaroqsiz JSON yozuvlari "o'lik" davlatni taklif qildirmaydi).
        Standart davlat ro'yxatda doim birinchi turadi.
        """
        codes = {p.country for p in self.profiles.values() if p.country and p.events}
        codes.add(self.default_country)
        return tuple(sorted(codes, key=lambda code: (code != self.default_country, code)))

    def available_scopes(self) -> tuple[str, ...]:
        return tuple(sorted(self.profiles))

    def has_profile(self, country: Any) -> bool:
        """Davlat uchun maxsus JSON profili bormi? (xalqaro qatlam — davlat emas)"""
        code = self.resolve_country(country)
        return bool(code) and self._profile_by_code(code) is not None

    def _profile_by_code(self, code: str) -> CalendarProfile | None:
        """Allaqachon normalizatsiya qilingan kod bo'yicha profil (qayta
        normalizatsiya QILMAYDI — ``""`` xalqaro qatlamni anglatadi)."""
        return next((p for p in self.profiles.values() if p.country == code), None)

    def profile_for(self, country: Any) -> CalendarProfile | None:
        return self._profile_by_code(self.resolve_country(country))

    def scopes_for(self, country: Any = None) -> tuple[str, ...]:
        """Davlat uchun qo'llaniladigan qatlamlar tartibi (inheritance zanjiri)."""
        profile = self._profile_by_code(self.resolve_country(country))
        if profile is None:
            # Profili yo'q davlat → faqat xalqaro baza (fallback).
            return (GLOBAL_SCOPE,)
        chain: list[str] = []
        for parent in profile.inherits:
            if parent not in chain:
                chain.append(parent)
        if profile.scope not in chain:
            chain.append(profile.scope)
        return tuple(scope for scope in chain if scope in self.profiles)

    def resolve_chain(self, country: Any = None) -> tuple[str, ...]:
        """Davlat uchun yechish zanjiri, oxirida xalqaro qatlam (fallback).

        Misol: ``resolve_chain("UZ") == ("global", "uz")``; profili yo'q
        davlat uchun ``("global",)``. Callback validatsiyasi shu zanjir
        bo'ylab izlaydi — sana biror qatlamda bo'lsa topiladi.
        """
        chain = [scope for scope in self.scopes_for(country)]
        if GLOBAL_SCOPE not in chain:
            chain.append(GLOBAL_SCOPE)
        return tuple(scope for scope in chain if scope in self.profiles)

    def event_any_scope(self, key: str, year: int, country: Any = None, *,
                        date_overrides: Mapping[str, date | str] | None = None,
                        ) -> CalendarEvent | None:
        """Sana kalitini davlat zanjiri BO'YLAB izlaydi (xalqaro qatlamgacha).

        Foydalanuvchi davlatini o'zgartirgan bo'lsa ham eski eslatma
        tugmasi ishlashi uchun (masalan UZ'da yuborilgan ``black_friday``
        tugmasi keyin JP'da bosilsa).
        """
        event_key = str(key or "").strip()
        if not event_key:
            return None
        for scope in self.resolve_chain(country):
            profile = self.profiles.get(scope)
            if profile is None:
                continue
            for event in self.events_in_scope(year, scope, date_overrides=date_overrides):
                if event.key == event_key:
                    return event
        return None

    # -- sana yechish (resolution) -------------------------------------
    def _event_specs_for_code(self, code: str) -> tuple[EventSpec, ...]:
        """Allaqachon normalizatsiya qilingan kod uchun qatlamlar birlashmasi."""
        merged: dict[str, EventSpec] = {}
        profile = self._profile_by_code(code)
        scopes = self.scopes_for(profile.scope if profile else GLOBAL_SCOPE)
        for scope in scopes:
            for spec in self.profiles[scope].events:
                merged[spec.key] = spec
        return tuple(merged.values())

    def event_specs(self, country: Any = None) -> tuple[EventSpec, ...]:
        """Barcha qatlamlarni birlashtiradi; keyinroq qatlam ``key`` ni override qiladi."""
        return self._event_specs_for_code(self.resolve_country(country))

    def events(self, year: int, country: Any = None, *,
               date_overrides: Mapping[str, date | str] | None = None,
               ) -> tuple[CalendarEvent, ...]:
        """``year`` uchun davlatga mos barcha sanalar (sana bo'yicha saralangan).

        ``date_overrides`` — rasmiy sana tuzatish ilgagi (hook). Qiymatlar
        ``datetime.date`` yoki ISO ``YYYY-MM-DD`` bo'lishi mumkin.

        .. note::
           Boshqa yilga tegishli yoki buzilgan override qiymati **e'tiborga
           olinmaydi** va hisoblangan sana saqlanadi. (Eski
           ``services.uzbekistan_calendar`` bunday qiymatda sanani butunlay
           O'CHIRIB tashlardi — noto'g'ri sozlama tufayli Navro'z yo'qolib
           qolishi mumkin edi. Bu ataylab o'zgartirilgan, xavfsizroq
           xatti-harakat.)
        """
        year = int(year)
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
        overrides = dict(date_overrides or {})
        code = self.resolve_country(country)
        resolved: list[CalendarEvent] = []
        for spec in self._event_specs_for_code(code):
            event_date = self._resolve_event_date(spec, year, overrides)
            if event_date is None:
                continue
            resolved.append(CalendarEvent(spec.key, event_date, spec.names, spec.kind,
                                          self._spec_country(spec)))
        return tuple(sorted(resolved, key=lambda item: (item.date, item.key)))

    @staticmethod
    def _resolve_event_date(spec: EventSpec, year: int,
                            overrides: Mapping[str, date | str] | None = None) -> date | None:
        """Bitta sana uchun: rasmiy override (agar yilga to'g'ri kelsa) → qoida.

        Noto'g'ri yildagi yoki buzilgan override HISOBGA OLINMAYDI — aks
        holda xato sozlama bayramni butunlay yo'q qilib yuborardi.
        """
        override = coerce_date((overrides or {}).get(spec.key))
        if override is not None and override.year == year:
            return override
        computed = resolve_when(spec.when, year)
        return computed if computed is not None and computed.year == year else None

    def events_in_scope(self, year: int, scope: Any, *,
                        date_overrides: Mapping[str, date | str] | None = None,
                        ) -> tuple[CalendarEvent, ...]:
        """FAQAT bitta qatlam (``"global"`` yoki ``"uz"``) sanalari.

        ``resolve_chain`` bo'ylab izlashda ishlatiladi — inheritance
        zanjirisiz, sof qatlam ma'lumoti.
        """
        year = int(year)
        if not MIN_YEAR <= year <= MAX_YEAR:
            raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}")
        profile = self.profiles.get(str(scope or "").strip().lower())
        if profile is None:
            return ()
        overrides = dict(date_overrides or {})
        resolved: list[CalendarEvent] = []
        for spec in profile.events:
            event_date = self._resolve_event_date(spec, year, overrides)
            if event_date is None:
                continue
            resolved.append(CalendarEvent(spec.key, event_date, spec.names, spec.kind,
                                          profile.country))
        return tuple(sorted(resolved, key=lambda item: (item.date, item.key)))

    def _spec_country(self, spec: EventSpec) -> str:
        profile = self.profiles.get(spec.scope)
        return profile.country if profile else ""

    def events_for_date(self, target_date: date, country: Any = None, *,
                        date_overrides: Mapping[str, date | str] | None = None,
                        ) -> tuple[CalendarEvent, ...]:
        """``target_date`` ga to'g'ri keladigan barcha sanalar."""
        target = coerce_date(target_date)
        if target is None:
            return ()
        return tuple(
            event for event in self.events(target.year, country, date_overrides=date_overrides)
            if event.date == target
        )

    def events_for_reminder(self, today: date, days_before: int = 3, country: Any = None, *,
                            date_overrides: Mapping[str, date | str] | None = None,
                            ) -> tuple[CalendarEvent, ...]:
        """``today`` dan roppa-rosa ``days_before`` kun keyingi sanalar."""
        current = coerce_date(today)
        if current is None:
            return ()
        try:
            target = current + timedelta(days=max(0, int(days_before)))
        except (TypeError, ValueError, OverflowError):
            return ()
        return self.events_for_date(target, country, date_overrides=date_overrides)

    def event(self, key: str, year: int, country: Any = None, *,
              date_overrides: Mapping[str, date | str] | None = None,
              ) -> CalendarEvent | None:
        """Barqaror ``key`` bo'yicha sana (callback validatsiyasi uchun)."""
        event_key = str(key or "").strip()
        if not event_key:
            return None
        return next(
            (item for item in self.events(year, country, date_overrides=date_overrides)
             if item.key == event_key),
            None,
        )

    def upcoming(self, today: date, days: int = 30, country: Any = None, *,
                 date_overrides: Mapping[str, date | str] | None = None,
                 ) -> tuple[CalendarEvent, ...]:
        """``today`` dan boshlab ``days`` kun ichidagi sanalar (yil chegarasi bilan)."""
        current = coerce_date(today)
        if current is None:
            return ()
        try:
            horizon = current + timedelta(days=max(0, int(days)))
        except (TypeError, ValueError, OverflowError):
            return ()
        # Diqqat: ``CalendarEvent.names`` — ``dict`` (unhashable), shuning uchun
        # takrorlanmaslik to'plam (set) emas, (key, date) juftligi bilan
        # tekshiriladi.
        found: dict[tuple[str, date], CalendarEvent] = {}
        for year in sorted({current.year, horizon.year}):
            for event in self.events(year, country, date_overrides=date_overrides):
                if current <= event.date <= horizon:
                    found.setdefault((event.key, event.date), event)
        return tuple(sorted(found.values(), key=lambda item: (item.date, item.key)))

    def movable_keys(self, country: Any = None) -> tuple[str, ...]:
        """Hijri (oy) taqvimi bo'yicha siljiydigan sana kalitlari."""
        return tuple(spec.key for spec in self.event_specs(country) if spec.is_movable)

    # -- lokalizatsiya yordamchilari -----------------------------------
    def country_name(self, country: Any = None, lang: str = "uz") -> str:
        code = self.resolve_country(country)
        profile = self._profile_by_code(code)
        names = profile.names if profile else self.profiles[GLOBAL_SCOPE].names
        return names.get(normalize_calendar_lang(lang)) or names.get("uz") or code

    def label(self, key: str, lang: str = "uz", country: Any = None) -> str:
        """Davlatga xos yorliq, topilmasa xalqaro yorliq, u ham bo'lmasa ``key``."""
        code = normalize_calendar_lang(lang)
        profile = self._profile_by_code(self.resolve_country(country))
        for source in (profile, self.profiles.get(GLOBAL_SCOPE)):
            if source is None:
                continue
            value = (source.labels.get(key) or {}).get(code) \
                or (source.labels.get(key) or {}).get("uz")
            if value:
                return value
        return key

    # -- AI prompt konteksti -------------------------------------------
    def prompt_block(self, country: Any = None, lang: str = "uz", *,
                     today: date | None = None, days: int = 90,
                     max_events: int = 8) -> str:
        """AI promptiga qo'yiladigan, davlatga mos kelgusi sanalar bloki.

        Bo'sh blok (sana topilmasa) qaytarmaydi — ``""`` qaytadi, shunda
        chaqiruvchi prompt'ni keraksiz matn bilan to'ldirmaydi.
        """
        anchor = coerce_date(today) or date.today()
        code = normalize_calendar_lang(lang)
        found = self.upcoming(anchor, days, country)[: max(1, int(max_events))]
        if not found:
            return ""
        title = self.label("title", code, country) or self.label("title", "uz", country)
        header = self._prompt_header(code)
        lines = [header, f"{title} — {self.country_name(country, code)}:"]
        for event in found:
            delta = (event.date - anchor).days
            lines.append(
                f"- {event.date.isoformat()} ({self._days_word(delta, code)}): "
                f"{event.name(code)} [{self.label(event.kind, code, country)}]"
            )
        lines.append(self._prompt_rule(code))
        return "\n".join(lines)

    @staticmethod
    def _prompt_header(code: str) -> str:
        return {
            "uz": "KONTENT KALENDARI (foydalanuvchi davlati bo'yicha):",
            "ru": "КОНТЕНТ-КАЛЕНДАРЬ (по стране пользователя):",
            "en": "CONTENT CALENDAR (for the user's country):",
        }.get(code, "KONTENT KALENDARI (foydalanuvchi davlati bo'yicha):")

    @staticmethod
    def _prompt_rule(code: str) -> str:
        return {
            "uz": ("Bu sanalarni faqat MAVZU TAKLIFI sifatida ishlat; sana yoki "
                   "bayram nomini O'YLAB TOPMA va rasmiy deb taqdim etma."),
            "ru": ("Используй эти даты только как ПРЕДЛОЖЕНИЕ ТЕМ; не выдумывай "
                   "даты и не подавай названия как официально подтверждённые."),
            "en": ("Use these dates only as TOPIC SUGGESTIONS; never invent dates "
                   "or present the names as officially confirmed."),
        }.get(code, "Bu sanalarni faqat MAVZU TAKLIFI sifatida ishlat.")

    @staticmethod
    def _days_word(delta: int, code: str) -> str:
        if delta <= 0:
            return {"uz": "bugun", "ru": "сегодня", "en": "today"}.get(code, "bugun")
        return {"uz": f"{delta} kundan keyin",
                "ru": f"через {delta} дн.",
                "en": f"in {delta} day" + ("" if delta == 1 else "s")}.get(code, f"{delta} kun")


# ---------------------------------------------------------------------------
# JSON normalizatsiya yordamchilari
# ---------------------------------------------------------------------------
def _str_map(value: Any) -> Mapping[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if isinstance(v, (str, int, float))}


def _label_map(value: Any) -> Mapping[str, Mapping[str, str]]:
    if not isinstance(value, dict):
        return {}
    return {str(k): _str_map(v) for k, v in value.items() if isinstance(v, dict)}


def _event_spec(entry: Any, scope: str) -> EventSpec | None:
    """JSON yozuvini :class:`EventSpec` ga aylantiradi; yaroqsiz → ``None``."""
    if not isinstance(entry, dict):
        return None
    key = str(entry.get("key") or "").strip()
    when = entry.get("when")
    if not key or not isinstance(when, dict) or not str(when.get("type") or "").strip():
        logger.warning("Calendar event skipped (missing key/when) in scope %s: %r", scope, entry)
        return None
    names = _str_map(entry.get("names"))
    if not names:
        logger.warning("Calendar event skipped (no localized names) in scope %s: %s", scope, key)
        return None
    return EventSpec(
        key=key,
        scope=scope,
        kind=str(entry.get("kind") or "holiday").strip().lower() or "holiday",
        names=names,
        when=dict(when),
    )


# ---------------------------------------------------------------------------
# Jarayon darajasidagi yagona servis (singleton)
# ---------------------------------------------------------------------------
_default_service: CalendarService | None = None
_default_lock = threading.Lock()


def get_calendar_service() -> CalendarService:
    """Jarayon bo'yicha yagona :class:`CalendarService` (lazy, thread-safe)."""
    global _default_service
    if _default_service is None:
        with _default_lock:
            if _default_service is None:
                _default_service = CalendarService()
    return _default_service


def set_calendar_service(service: CalendarService | None) -> CalendarService:
    """Standart servisini almashtiradi (testlar / maxsus katalogni sinash uchun)."""
    global _default_service
    with _default_lock:
        _default_service = service or CalendarService()
    return _default_service


def reload_calendar_service() -> CalendarService:
    """Keshni tozalab JSON fayllarini qayta o'qiydi."""
    return get_calendar_service().reload()


# ---------------------------------------------------------------------------
# Modul darajasidagi qulay funksiyalar (davlat parametrik)
# ---------------------------------------------------------------------------
def calendar_events(year: int, country: Any = None, *,
                    date_overrides: Mapping[str, date | str] | None = None,
                    ) -> tuple[CalendarEvent, ...]:
    return get_calendar_service().events(year, country, date_overrides=date_overrides)


def calendar_events_for_date(target_date: date, country: Any = None, *,
                             date_overrides: Mapping[str, date | str] | None = None,
                             ) -> tuple[CalendarEvent, ...]:
    return get_calendar_service().events_for_date(target_date, country,
                                                  date_overrides=date_overrides)


def calendar_events_for_reminder(today: date, days_before: int = 3, country: Any = None, *,
                                 date_overrides: Mapping[str, date | str] | None = None,
                                 ) -> tuple[CalendarEvent, ...]:
    return get_calendar_service().events_for_reminder(today, days_before, country,
                                                      date_overrides=date_overrides)


def calendar_event(key: str, year: int, country: Any = None, *,
                   date_overrides: Mapping[str, date | str] | None = None,
                   ) -> CalendarEvent | None:
    return get_calendar_service().event(key, year, country, date_overrides=date_overrides)


def upcoming_calendar_events(today: date, days: int = 30, country: Any = None, *,
                             date_overrides: Mapping[str, date | str] | None = None,
                             ) -> tuple[CalendarEvent, ...]:
    return get_calendar_service().upcoming(today, days, country, date_overrides=date_overrides)


def calendar_prompt_block(country: Any = None, lang: str = "uz", **kwargs: Any) -> str:
    return get_calendar_service().prompt_block(country, lang, **kwargs)


__all__ = [
    "CALENDARS_DIR",
    "DEFAULT_COUNTRY",
    "GLOBAL_SCOPE",
    "MAX_YEAR",
    "MIN_YEAR",
    "RULE_RESOLVERS",
    "RULE_TYPES",
    "SUPPORTED_LANGS",
    "CalendarEvent",
    "CalendarProfile",
    "CalendarService",
    "EventSpec",
    "calendar_event",
    "calendar_events",
    "calendar_events_for_date",
    "calendar_events_for_reminder",
    "calendar_prompt_block",
    "coerce_date",
    "get_calendar_service",
    "hijri_to_gregorian",
    "normalize_calendar_lang",
    "nth_weekday_of_month",
    "register_rule",
    "reload_calendar_service",
    "resolve_when",
    "set_calendar_service",
    "upcoming_calendar_events",
]
