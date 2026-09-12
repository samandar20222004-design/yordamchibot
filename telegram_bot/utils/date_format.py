"""📅 SANA/VAQT LOCALIZATSIYASI — har bir tilga MOS format (uz / ru / en).

Nima uchun bu modul kerak?
==========================
Avval botning hamma joyida sana ``datetime.strftime("%Y-%m-%d %H:%M")`` yoki
``"%d-%b %H:%M"`` ko'rinishida chiqardi. Uchta jiddiy kamchilik bor edi:

1. **``%b`` / ``%B`` / ``%A`` hech qachon tarjima bo'lmaydi** — Python
   ``strftime`` C-locale (inglizcha) oy nomlaridan foydalanadi. Natijada rus
   foydalanuvchi navbat ro'yxatida "05-Sep" ko'radi (kutgani "05 сент."),
   o'zbek foydalanuvchida ham "Sep" chiqadi.
2. **INGLIZ tilidagi foydalanuvchiga o'zbekcha format** chiqardi: sana
   tartibi (kun/oy vs oy/kun), oy va hafta kunlari nomlari umuman boshqacha.
3. **Hafta kunlari EN'da umuman yo'q edi** — ``WEEKDAY_LABELS_RU if lang=="ru"
   else WEEKDAY_LABELS`` tufayli EN foydalanuvchi "Juma" deb o'qirdi.

Bu modul uchala til uchun ham SANA TARTIBI, OY va HAFTA KUNLARI nomlarini
bitta joyda saqlaydi va xavfsiz (hech qachon istisno ko'tarmaydigan)
formatlagichlar beradi.

Ishlatish::

    from utils.date_format import format_datetime, weekday_label

    format_datetime(dt, lang)                     # "⏰ uchun" to'liq qator
    format_datetime(dt, lang, style="list")       # navbat ro'yxati (qisqa)
    format_list_datetime(dt, lang=lang, now=now)  # "Bugun 14:00" / "Today 14:00"
    weekday_label(4, lang)                        # "Juma" / "Пятница" / "Friday"

``lang`` qanday bo'lmasin (``"ru-RU"``, ``None``, noma'lum til) —
normallashtirilib ``uz`` ga qaytadi va funksiya HECH QACHON qulatmaydi.
"""

from __future__ import annotations

from datetime import date as _date, datetime, time as _time

import pytz

__all__ = (
    "DEFAULT_LANG",
    "MONTH_NAMES",
    "MONTH_NAMES_SHORT",
    "WEEKDAY_NAMES",
    "WEEKDAY_NAMES_SHORT",
    "LOCALE_PATTERNS",
    "locale_for",
    "format_datetime",
    "format_date",
    "format_time",
    "format_list_datetime",
    "weekday_label",
    "day_offset_label",
    "schedule_hint",
    "format_schedule",
)

tashkent_tz = pytz.timezone("Asia/Tashkent")
DEFAULT_LANG = "uz"

# ---------------------------------------------------------------------------
# LUG'ATLAR — oy va hafta kunlari nomlari (index: 0=yanvar / 0=dushanba)
# ---------------------------------------------------------------------------
MONTH_NAMES = {
    "uz": (
        "Yanvar", "Fevral", "Mart", "Aprel", "May", "Iyun",
        "Iyul", "Avgust", "Sentabr", "Oktabr", "Noyabr", "Dekabr",
    ),
    "ru": (
        "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
        "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
    ),
    "en": (
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ),
}

MONTH_NAMES_SHORT = {
    "uz": (
        "Yanv", "Fevr", "Mart", "Apr", "May", "Iyun",
        "Iyul", "Avg", "Sent", "Okt", "Noy", "Dek",
    ),
    "ru": (
        "янв", "фев", "мар", "апр", "май", "июн",
        "июл", "авг", "сент", "окт", "нояб", "дек",
    ),
    "en": (
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ),
}

#: Hafta kunlari — Python ``weekday()`` tartibida (0 = dushanba).
WEEKDAY_NAMES = {
    "uz": (
        "Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma",
        "Shanba", "Yakshanba",
    ),
    "ru": (
        "Понедельник", "Вторник", "Среда", "Четверг", "Пятница",
        "Суббота", "Воскресенье",
    ),
    "en": (
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday",
    ),
}

#: Ikkala jadval ham ``datetime.weekday()`` tartibida (0 = dushanba).
WEEKDAY_NAMES_SHORT = {
    "uz": ("Dush", "Sesh", "Chor", "Pay", "Juma", "Shan", "Yak"),
    "ru": ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}

# ---------------------------------------------------------------------------
# HAR TIL uchun FORMAT SHABLONLARI
# ---------------------------------------------------------------------------
# • "schedule" — post rejalashtirish/preview kartasidagi to'liq sana+vaqt.
#   UZ/RU uchun ISO (``2026-09-05 14:00``) saqlanadi: bu — amaliyotdagi
#   texnik/qaytariladigan ko'rinish va klaviaturaga yoziladigan format bilan
#   ziddiyatga kirishmaydi (bot ``31.12.2026 18:00`` ni ham,
#   ``2026-12-31 18:00`` ni ham o'qiydi).
# • "list"     — navbat ro'yxatidagi ixcham qator (oy nomi TILDA).
# • "day"      — faqat sana; • "month_day" — oy kuni (kontent-reja).
#
# ``%b``/``%B``/``%a``/``%A`` tokenlari ``_render`` ichida til lug'ati bilan
# almashtiriladi — shu sababli ular C-locale'dan mustaqil.
LOCALE_PATTERNS = {
    "uz": {
        "schedule": "%Y-%m-%d %H:%M",
        "datetime": "%Y-%m-%d %H:%M",
        "list": "%d %b %H:%M",
        "day": "%d.%m.%Y",
        "month_day": "%d %b",
        "clock": "%H:%M",
        "hint": "DD.MM.YYYY HH:MM",
    },
    "ru": {
        "schedule": "%Y-%m-%d %H:%M",
        "datetime": "%Y-%m-%d %H:%M",
        "list": "%d %b %H:%M",
        "day": "%d.%m.%Y",
        "month_day": "%d %b",
        "clock": "%H:%M",
        "hint": "DD.MM.YYYY HH:MM",
    },
    "en": {
        "schedule": "%b %d, %Y %H:%M",
        "datetime": "%b %d, %Y %H:%M",
        "list": "%b %d %H:%M",
        "day": "%b %d, %Y",
        "month_day": "%b %d",
        "clock": "%H:%M",
        # Kiritish formati uchala tilda BIR XIL: ``parse_schedule_input``
        # aynan shu formatni (va 2026-09-05 / 05-09-2026 ko'rinishlarini)
        # o'qiydi. EN'da "MM/DD/YYYY" taklif qilish xato maslahat bo'lardi.
        "hint": "DD.MM.YYYY HH:MM",
    },
}


# ---------------------------------------------------------------------------
# Ichki yordamchilar
# ---------------------------------------------------------------------------

def locale_for(lang) -> str:
    """``lang`` ni 'uz'|'ru'|'en' ga normallashtiradi (xatosiz)."""
    try:
        from locales.translations import normalize_lang
        return normalize_lang(lang)
    except Exception:  # pragma: no cover - lug'at importi sinsa ham ishlasin
        code = str(lang or "").lower()
        if code.startswith("ru"):
            return "ru"
        if code.startswith("en"):
            return "en"
        return DEFAULT_LANG


def _as_datetime(value):
    """Har qanday kirishni Toshkent vaqtidagi ``datetime`` ga aylantiradi.

    Qo'llab-quvvatlanadi: ``datetime`` (naive/aware), ``date``, ``time``,
    ``"HH:MM"`` / ``"HH:MM:SS"`` satrlari, epoch soni. Aniqlanmasa — ``None``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            try:
                dt = tashkent_tz.localize(dt)
            except Exception:  # pragma: no cover
                return dt.replace(tzinfo=None)
        try:
            return dt.astimezone(tashkent_tz)
        except Exception:  # pragma: no cover
            return dt
    if isinstance(value, _date):
        try:
            return tashkent_tz.localize(
                datetime(value.year, value.month, value.day)
            )
        except Exception:  # pragma: no cover
            return None
    if isinstance(value, _time):
        try:
            today = datetime.now(tashkent_tz)
            return tashkent_tz.localize(
                datetime(today.year, today.month, today.day,
                         value.hour, value.minute, value.second)
            )
        except Exception:  # pragma: no cover
            return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(float(value), tz=tashkent_tz)
        except Exception:  # pragma: no cover
            return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        import re
        m = re.match(r"^(\d{1,2})[:.](\d{2})(?::(\d{2}))?$", raw)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                # Soat/daqiqa — sana kerak emas, lekin ``datetime`` qaytaramiz
                # ( chaqiruv nuqtalari bir xil tur bilan ishlaydi).
                return tashkent_tz.localize(
                    datetime(2000, 1, 1, hh, mm, int(m.group(3) or 0))
                )
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return _as_datetime(datetime.strptime(raw, fmt))
            except ValueError:
                continue
        return None
    return None


def _render(fmt: str, dt: datetime, code: str) -> str:
    """``%b/%B/%a/%A`` ni TIL lug'ati bilan almashtirib, ``strftime`` qiladi.

    Python ``strftime`` C-locale dan foydalanadi — shu tokenlarni oldin
    qo'lda almashtirish orqali oy/hafta kunlari har doim foydalanuvchi
    tilida chiqadi.
    """
    months = MONTH_NAMES.get(code) or MONTH_NAMES[DEFAULT_LANG]
    months_s = MONTH_NAMES_SHORT.get(code) or MONTH_NAMES_SHORT[DEFAULT_LANG]
    days = WEEKDAY_NAMES.get(code) or WEEKDAY_NAMES[DEFAULT_LANG]
    days_s = WEEKDAY_NAMES_SHORT.get(code) or WEEKDAY_NAMES_SHORT[DEFAULT_LANG]
    try:
        out = fmt.replace("%B", months[dt.month - 1]).replace("%b", months_s[dt.month - 1])
        # %A — to'liq, %a — qisqartirilgan hafta kuni (ikkalam ham
        # weekday() tartibidagi jadvallardan olinadi).
        out = out.replace("%A", days[dt.weekday()]).replace("%a", days_s[dt.weekday()])
        return dt.strftime(out)
    except Exception:  # pragma: no cover - himoya: hech qachon qulatmaymiz
        try:
            return dt.strftime(fmt)
        except Exception:
            return str(dt)


# ---------------------------------------------------------------------------
# OMBOR (public) API
# ---------------------------------------------------------------------------

def format_datetime(value, lang=DEFAULT_LANG, style: str = "schedule") -> str:
    """Sana+vaqtni foydalanuvchi tilida qator qilib qaytaradi.

    Args:
        value: ``datetime``/``date``/``time``/``"HH:MM"`` satr yoki ``None``.
        lang:  ``"uz" | "ru" | "en"`` (boshqa qiymat ``uz`` ga tushadi).
        style: ``"schedule"`` (to'liq) | ``"list"`` (navbat ro'yxati) |
               ``"day"`` (faqat sana) | ``"month_day"`` | ``"clock"``.

    Returns:
        Formatlangan satr; ``value`` o'qib bo'lmasa — bo'sh satr (hech
        qachon ``None`` va hech qachon istisno emas).
    """
    code = locale_for(lang)
    patterns = LOCALE_PATTERNS.get(code) or LOCALE_PATTERNS[DEFAULT_LANG]
    fmt = patterns.get(style) or patterns["schedule"]
    dt = _as_datetime(value)
    if dt is None:
        return ""
    return _render(fmt, dt, code)


def format_date(value, lang=DEFAULT_LANG) -> str:
    """Faqat sana — ``05.09.2026`` (uz/ru) / ``Sep 05, 2026`` (en)."""
    return format_datetime(value, lang, style="day")


def format_time(value, lang=DEFAULT_LANG) -> str:
    """Faqat soat:daqiqa — ``14:00`` (uchala tilda ham 24 soatlik)."""
    dt = _as_datetime(value)
    if dt is None:
        return ""
    return dt.strftime("%H:%M")


def format_list_datetime(value, lang=DEFAULT_LANG, now=None) -> str:
    """Navbat ro'yxati uchun IXCHAM qator — "Bugun 14:00" / "Today 14:00".

    Bugun/ertaga bo'lsa sana o'rniga tilga mos nisbiy yorliq ko'rsatiladi
    (foydalanuvchi sana bilan mathlab bo'lishi shart emas), qolgan
    hollarda til formatidagi qisqa sana + vaqt chiqadi.
    """
    code = locale_for(lang)
    dt = _as_datetime(value)
    if dt is None:
        return ""
    ref = _as_datetime(now) or datetime.now(tashkent_tz)
    try:
        delta_days = (dt.date() - ref.date()).days
    except Exception:  # pragma: no cover
        delta_days = 99
    if delta_days == 0:
        prefix = _today_word(code)
    elif delta_days == 1:
        prefix = _tomorrow_word(code)
    else:
        prefix = ""
    time_part = dt.strftime("%H:%M")
    if prefix:
        return f"{prefix} {time_part}"
    return format_datetime(dt, code, style="list")


def _today_word(code: str) -> str:
    """\"Bugun\" / \"Сегодня\" / \"Today\" — lug'atdan (fallback ichida)."""
    try:
        from locales.translations import get_text
        text = get_text("dt_today", code)
        if text and text != "dt_today":
            return text
    except Exception:  # pragma: no cover
        pass
    return {"ru": "Сегодня", "en": "Today"}.get(code, "Bugun")


def _tomorrow_word(code: str) -> str:
    try:
        from locales.translations import get_text
        text = get_text("dt_tomorrow", code)
        if text and text != "dt_tomorrow":
            return text
    except Exception:  # pragma: no cover
        pass
    return {"ru": "Завтра", "en": "Tomorrow"}.get(code, "Ertaga")


def weekday_label(day_index, lang=DEFAULT_LANG) -> str:
    """Hafta kuni nomi — foydalanuvchi tilida (0 = dushanba ... 6 = yakshanba).

    ``keyboards.default`` dagi klaviatura xaritalari (``WEEKDAY_LABELS*``)
    ustuvor ishlatiladi — shunda tugma yorlig'i va preview qatori HAR DOIM
    bir xil so'z bilan chiqadi. Lug'at topilmasa moduldagi nomlar ishlatiladi.
    """
    code = locale_for(lang)
    try:
        idx = int(day_index)
    except (TypeError, ValueError):
        return "?"
    if not 0 <= idx <= 6:
        return "?"
    # 1) Klaviatura bilan bir xil manba (husbat: tugma "Juma" → preview "Juma").
    try:
        from keyboards.default import (
            WEEKDAY_LABELS, WEEKDAY_LABELS_RU, WEEKDAY_LABELS_EN,
        )
        table = {"ru": WEEKDAY_LABELS_RU, "en": WEEKDAY_LABELS_EN}.get(code, WEEKDAY_LABELS)
        label = (table or {}).get(idx)
        if label:
            return str(label)
    except Exception:  # pragma: no cover - keyboards importi sinsa
        pass
    # 2) Zaxira: shu modulning o'zidagi nomlar.
    names = WEEKDAY_NAMES.get(code) or WEEKDAY_NAMES[DEFAULT_LANG]
    return names[idx]


def day_offset_label(day_index, lang=DEFAULT_LANG) -> str:
    """``weekday_label`` ning semantik taxallusi — o'qish qulayligi uchun."""
    return weekday_label(day_index, lang)


# Qisqa aliaslar — chaqiruv nuqtalari o'qiladigan bo'lsin.
format_schedule = format_datetime


def schedule_hint(lang=DEFAULT_LANG) -> str:
    """Ushbu tilda foydalanuvchiga ko'rsatiladigan KIRITISH namunasi.

    Diqqat: namuna FAQAT ko'zgal tashlanadi — uni qayta yozib yuborish
    mumkin bo'lishi uchun ``utils.helpers.parse_schedule_input`` bu
    formatni ALBATTA o'qiy oladigan bo'lishi shart.
    """
    patterns = LOCALE_PATTERNS.get(locale_for(lang)) or LOCALE_PATTERNS[DEFAULT_LANG]
    return patterns["hint"]
