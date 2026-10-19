"""Foydalanuvchi vaqt mintaqasi: har davlat o'z vaqtida rejalaydi va ko'radi.

Manba tartibi: ``users.timezone`` (qo'lda tanlangan) -> telefon mamlakatining asosiy zonasi -> ``Asia/Tashkent``.
Saqlangan vaqtlar UTC lahzasi (timestamptz) — mintaqa faqat KIRITISH va KO'RSATISH uchun. Joriy zona ``ContextVar``da
turadi: har yangilanish boshida o'rnatiladi (``handlers/timezone_flow.py``), fon vazifalar ``use_tz`` bilan egasining zonasini oladi.
"""

from __future__ import annotations

import contextlib
import contextvars
import re
import time
from datetime import datetime

import pytz

DEFAULT_TZ_NAME = "Asia/Tashkent"
_DEFAULT = pytz.timezone(DEFAULT_TZ_NAME)

# Ko'p zonali davlatlarda asosiy (eng ko'p aholi) zona; qolganlari pytz.country_timezones dan.
_MAIN_ZONE = {
    "US": "America/New_York", "RU": "Europe/Moscow", "CA": "America/Toronto", "BR": "America/Sao_Paulo",
    "AU": "Australia/Sydney", "MX": "America/Mexico_City", "KZ": "Asia/Almaty", "ID": "Asia/Jakarta",
    "CN": "Asia/Shanghai", "AR": "America/Argentina/Buenos_Aires", "CL": "America/Santiago", "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon", "DE": "Europe/Berlin", "UA": "Europe/Kyiv", "MN": "Asia/Ulaanbaatar", "EC": "America/Guayaquil",
    "PF": "Pacific/Tahiti", "FM": "Pacific/Pohnpei", "KI": "Pacific/Tarawa", "NZ": "Pacific/Auckland", "CD": "Africa/Kinshasa",
    "GL": "America/Nuuk", "UZ": "Asia/Tashkent",
}
_OFFSET_RE = re.compile(r"^UTC([+-])(\d{1,2})$")
#: Davlati noma'lum foydalanuvchi uchun UTC siljish tanlovi (soat).
OFFSET_CHOICES = (-8, -7, -6, -5, -4, -3, -2, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)

_current: contextvars.ContextVar = contextvars.ContextVar("user_tz", default=None)
_cache: dict[int, tuple[str, float]] = {}
_CACHE_TTL = 600.0


def valid_tz(name) -> bool:
    return isinstance(name, str) and name in pytz.all_timezones_set


def country_zones(country: str | None) -> list[str]:
    """Davlatdagi IANA zonalar (asosiysi birinchi). Noma'lum davlat -> ``[]``."""
    cc = (country or "").upper()
    zones = list(pytz.country_timezones.get(cc.lower(), []))
    main = _MAIN_ZONE.get(cc)
    if main and main in zones:
        zones.remove(main)
        zones.insert(0, main)
    return zones


def country_default_tz(country: str | None) -> str | None:
    zones = country_zones(country)
    return zones[0] if zones else None


def offset_zone(hours: int) -> str:
    """UTC+h uchun Etc zonasi (POSIX belgisi teskari: UTC+5 = Etc/GMT-5)."""
    h = int(hours)
    return "Etc/GMT" if h == 0 else f"Etc/GMT{'-' if h > 0 else '+'}{abs(h)}"


def resolve(timezone_name: str | None, phone_country: str | None) -> str:
    """Saqlangan zona yaroqli bo'lsa o'sha, bo'lmasa davlat zonasi, bo'lmasa standart."""
    if valid_tz(timezone_name):
        return timezone_name
    return country_default_tz(phone_country) or DEFAULT_TZ_NAME


def get_tz(name: str | None) -> pytz.BaseTzInfo:
    return pytz.timezone(name) if valid_tz(name) else _DEFAULT


def utz() -> pytz.BaseTzInfo:
    """Joriy yangilanish/vazifa uchun foydalanuvchi zonasi (o'rnatilmagan bo'lsa Toshkent)."""
    return _current.get() or _DEFAULT


def set_current(tz) -> None:
    _current.set(tz)


@contextlib.contextmanager
def use_tz(tz):
    """Blok ichida ``utz()`` shu zonani qaytaradi (fon vazifa egasining zonasida hisoblaydi)."""
    token = _current.set(get_tz(tz) if isinstance(tz, str) else tz)
    try:
        yield
    finally:
        _current.reset(token)


def cached_name(user_id: int | None) -> str | None:
    """Keshdagi zona nomi (DB'ga bormaydi); yo'q yoki eskirgan bo'lsa ``None``."""
    hit = _cache.get(int(user_id)) if user_id else None
    return hit[0] if hit and time.monotonic() - hit[1] < _CACHE_TTL else None


def shift_local(moment: datetime, **delta) -> datetime:
    """Devor-soat (wall-clock) siljishi: yozgi/qishki vaqt o'tishida ham «ertaga 18:30» mahalliy 18:30 bo'lib qoladi
    (``normalize(x + timedelta)`` esa mutlaq 24 soat qo'shib, bir soat siljitib yuborardi)."""
    from datetime import timedelta

    zone = utz()
    return zone.localize(moment.astimezone(zone).replace(tzinfo=None) + timedelta(**delta))


def tz_name_for(user_id: int | None) -> str:
    """Foydalanuvchi zonasi nomi (10 daqiqalik xotira keshi; DB xatosida standart)."""
    if not user_id:
        return DEFAULT_TZ_NAME
    now = time.monotonic()
    hit = _cache.get(int(user_id))
    if hit and now - hit[1] < _CACHE_TTL:
        return hit[0]
    try:
        from repositories.users_repository import get_timezone_row
        name = resolve(*get_timezone_row(int(user_id)))
    except Exception:  # noqa: BLE001
        return DEFAULT_TZ_NAME
    if len(_cache) > 50000:
        _cache.clear()
    _cache[int(user_id)] = (name, now)
    return name


def tz_for(user_id: int | None):
    return get_tz(tz_name_for(user_id))


def invalidate(user_id: int) -> None:
    _cache.pop(int(user_id), None)


def offset_label(tz=None, at: datetime | None = None) -> str:
    """«UTC+5», «UTC-3:30» ko'rinishi."""
    zone = tz or utz()
    moment = at or datetime.now(pytz.utc)
    off = moment.astimezone(zone).utcoffset()
    minutes = int(off.total_seconds() // 60) if off else 0
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(minutes), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


def city(name: str) -> str:
    return name.split("/")[-1].replace("_", " ")


def parse_offset_choice(code: str):
    """``UTC+5`` -> Etc zonasi (yaroqsiz bo'lsa ``None``)."""
    m = _OFFSET_RE.match(code or "")
    if not m:
        return None
    h = int(m.group(2)) * (1 if m.group(1) == "+" else -1)
    return offset_zone(h) if h in OFFSET_CHOICES else None
