"""Erkin tildagi rejalash iborasini tuzilma ko'rinishiga o'giradi (uz/ru/en), AI'siz va DETERMINISTIK.

Misollar::

    "bugun soat 12:00 ga har kuni"            -> har kuni 12:00, boshlanishi: bugun (o'tgan bo'lsa ertaga)
    "ikki kunda bir marta 18:30"              -> har 2 kunda 18:30
    "har dam olish kuni shu vaqtda"           -> shanba+yakshanba, `default_time` (tahrirlagichdagi vaqt) da
    "каждый понедельник в 9"                  -> haftada bir marta (dushanba) 09:00
    "every weekday at 8:15"                   -> ish kunlari 08:15
    "ertaga 18:00" / "tomorrow 5pm"           -> bir martalik

Natija HECH QACHON taxminga tayanmaydi: vaqt aniqlanmasa ``ok=False`` (``no_time``) — foydalanuvchidan so'raladi.
Chiqish: ``{"ok": True, "start": aware datetime (Toshkent), "recurrence": None | {"type","day","time"}}`` yoki
``{"ok": False, "reason": ...}``. Takrorlanish ``services.recurrence.normalize_recurrence`` orqali tekshirilgan.
Qamrab olinmagan iboralar uchun chaqiruvchi (API) AI zaxirasiga o'tishi mumkin; AI natijasi ham ``validate_proposal`` dan o'tadi.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from services.recurrence import (
    INTERVAL_MAX_DAYS,
    TASHKENT,
    WEEKEND_MASK,
    WORKDAYS_MASK,
    first_occurrence,
    normalize_recurrence,
    time_to_minutes,
    weekdays_to_mask,
)

MAX_TEXT_CHARS = 300

# hafta kunlari: (regex, indeks) — dushanba=0
_WEEKDAY_PATTERNS = (
    (r"\bdushanba\w*|\bпонедельник\w*|\bmonday\w*|\bmon\b", 0),
    (r"\bseshanba\w*|\bвторник\w*|\btuesday\w*|\btue\b", 1),
    (r"\bchorshanba\w*|\bсред(?:а|ам|у|ы|е|ой)\b|\bwednesday\w*|\bwed\b", 2),
    (r"\bpayshanba\w*|\bчетверг\w*|\bthursday\w*|\bthu\b", 3),
    (r"\bjuma\w*|\bпятниц\w*|\bfriday\w*|\bfri\b", 4),
    (r"\bshanba\w*|\bсуббот\w*|\bsaturday\w*|\bsat\b", 5),
    (r"\byakshanba\w*|\bвоскресень\w*|\bsunday\w*|\bsun\b", 6),
)
_NUM_WORDS = {
    "bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "to‘rt": 4, "tort": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9, "o'n": 10,
    "один": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5, "шесть": 6, "семь": 7, "десять": 10,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "ten": 10,
}
_NUM = r"(\d{1,2}|" + "|".join(sorted((re.escape(w) for w in _NUM_WORDS), key=len, reverse=True)) + r")"

_WEEKEND = re.compile(
    r"dam olish kun\w*|dam olish\b|shanba[\s,-]+(?:va\s+)?yakshanba|по выходным|выходн\w*|\bweekends?\b|saturdays? (?:and|&) sundays?"
)
_WORKDAYS = re.compile(r"ish kun\w*|har ish kuni|по будням|будн\w*|\bweekdays?\b|\bworkdays?\b|\bbusiness days?\b")
_DAILY = re.compile(
    r"\bhar\s+kuni\b|\bhar\s+kun\b|\bhar\s+bir\s+kun\b|\bkundalik\b|\bkunda\s+bir\s+marta\b|\bhamma\s+kun\b"
    r"|ежедневно|кажд\w+\s+(?:день|сутки)|\bevery\s*day\b|\bdaily\b"
)
_TWICE_CUE = re.compile(
    r"\bkuniga\s+(?:ikki|2)\s+(?:marta|mahal|bor)\b|\bkuniga\s+ikki\s+marotaba\b|два\s+раза\s+в\s+(?:день|сутки)|\b2\s+раза\s+в\s+день\b"
    r"|\btwice\s+(?:a\s+day|daily|per\s+day)\b|\b(?:2|two)\s+times\s+(?:a|per)\s+day\b"
)
_MORNING = re.compile(r"\bertalab\w*|\btongda\b|\bтонгда\b|\bутр(?:ом|а)\b|\bmorning\b")
_EVENING = re.compile(r"\bkechqurun\w*|\bkechga\b|\bkechasi\b|\boqshom\w*|\bвечер(?:ом|а)?\b|\bevening\b")
_TIME_TOKEN = re.compile(
    r"(?:(?P<mp>ertalab|tongda|утром|morning)\s+)?(?:(?P<ep>kechqurun|kechga|kechasi|oqshom|вечером|evening)\s+)?"
    r"(?:soat\s+|в\s+|at\s+)?(?<![\d:])(?P<h>\d{1,2})(?:\s*[:.h]\s*(?P<m>\d{2}))?\s*(?P<ap>am|pm)?(?![\d:])"
)
MORNING_DEFAULT = time(9, 0)
EVENING_DEFAULT = time(19, 0)
_WEEKLY = re.compile(r"\bhar\s+hafta\b|\bhaftada\s+bir\b|еженедельно|раз\s+в\s+неделю|кажд\w+\s+недел\w+|\bevery\s+week\b|\bweekly\b|\bonce\s+a\s+week\b")
_EVERY_OTHER = re.compile(r"\bkunora\b|через\s+день|\bevery\s+other\s+day\b|\bevery\s+second\s+day\b|\bday\s+after\s+day\b")
_INTERVAL = (
    re.compile(r"\bhar\s+" + _NUM + r"\s*(?:kun|kunda|kunlik)\w*(?:\s+bir(?:\s+marta)?)?"),          # har 2 kunda (bir marta)
    re.compile(r"\b" + _NUM + r"\s*kunda\s+bir(?:\s+marta)?"),                                       # 2 kunda bir marta
    re.compile(r"кажд\w+\s+" + _NUM + r"\s*(?:дн|день|дня|дней|суток)\w*"),                        # каждые 2 дня
    re.compile(r"раз\s+в\s+" + _NUM + r"\s*(?:дн|день|дня|дней)\w*"),                               # раз в 2 дня
    re.compile(r"\bevery\s+" + _NUM + r"\s*days?\b"),                                                # every 2 days
)
_RECUR_CUE = re.compile(r"\bhar\b|kunlari|kunlarida|кажд|по\s+\w+ам\b|по\s+(?:сред|пятниц|суббот)\w*|раз\s+в|\bevery\b|\beach\b|\b\w+days\b|\bweekly\b")
_SAME_TIME = re.compile(r"\bshu\s+vaqt\w*|\bshu\s+soat\w*|в\s+(?:то|это)\s+же\s+время|в\s+то\s+же\s+время|\bat\s+the\s+same\s+time\b|\bsame\s+time\b")
_DAY_WORDS = (
    (re.compile(r"\bindinga\b|\bindini\b|послезавтра|day\s+after\s+tomorrow"), 2),
    (re.compile(r"\bertaga\b|\bertasiga\b|завтра|\btomorrow\b"), 1),
    (re.compile(r"\bbugun\b|\bbugunga\b|сегодня|\btoday\b|\btonight\b"), 0),
)


def _norm(text: str) -> str:
    t = (text or "").lower().replace("’", "'").replace("ʻ", "'").replace("`", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", t).strip()


def _num(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


def _weekdays_in(t: str) -> list[int]:
    found = []
    for pat, idx in _WEEKDAY_PATTERNS:
        if re.search(pat, t):
            found.append(idx)
    return sorted(set(found))


def extract_time(t: str):
    """Matndan soat:daqiqa (datetime.time) yoki None. Taxmin qilinmaydi: aniq raqam yoki 'tushda/yarim tunda' kerak."""
    # 12:30 / 12.30 / 12-30 emas (sana bilan chalkashmasin): faqat ':' yoki 'h' ajratgich
    m = re.search(r"(?<!\d)(\d{1,2})\s*[:h]\s*(\d{2})\s*(am|pm)?(?!\d)", t)
    ampm = None
    if m:
        h, mi, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"(?<!\d)(\d{1,2})\s*(am|pm)\b", t)
        if m:
            h, mi, ampm = int(m.group(1)), 0, m.group(2)
        else:
            m = re.search(r"(?:\bsoat\b|\bв\b|\bat\b|\bк\b)\s*(\d{1,2})(?!\d|\s*[:.]\d)", t) or re.search(r"(?<![\d:.])(\d{1,2})\s*(?:ga|da|dan)\b", t)
            if m:
                h, mi = int(m.group(1)), 0
            elif re.search(r"\btushda\b|\btush payti\b|в полдень|\bnoon\b|\bmidday\b", t):
                return time(12, 0)
            elif re.search(r"yarim tunda|в полночь|\bmidnight\b", t):
                return time(0, 0)
            else:
                return None
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = (h % 12) + (12 if ampm == "pm" else 0)
    else:
        # kun qismi so'zlari: "kechqurun 8" -> 20:00, "ertalab 9" -> 09:00
        if re.search(r"kechqurun|kechasi|oqshom|вечером|ночью|\bevening\b|\bnight\b|\btonight\b", t) and h < 12:
            h += 12
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return time(h, mi)


def extract_two_times(t: str):
    """Matndan IKKI vaqt (ertalab va kechqurun...): ``[time, time]`` (erta -> kech) yoki None.

    Aniq raqamlar ("9 va 18:30", "ertalab 9 va kechqurun 7") ustun; faqat kun qismi so'zi ("ertalab va kechqurun")
    bo'lsa 09:00 va 19:00 taklif qilinadi (foydalanuvchi tasdiqlash kartasida ko'radi va o'zgartira oladi).
    """
    slots: list[time] = []
    for m in _TIME_TOKEN.finditer(t):
        h = int(m.group("h"))
        mi = int(m.group("m")) if m.group("m") else 0
        if m.group("ap"):
            if not 1 <= h <= 12:
                continue
            h = (h % 12) + (12 if m.group("ap") == "pm" else 0)
        elif m.group("ep") and h < 12:
            h += 12
        if not (0 <= h <= 23 and 0 <= mi <= 59):
            continue
        slots.append(time(h, mi))
    if _MORNING.search(t) and not any(s_.hour < 12 for s_ in slots):
        slots.append(MORNING_DEFAULT)
    if _EVENING.search(t) and not any(s_.hour >= 15 for s_ in slots):
        slots.append(EVENING_DEFAULT)
    slots = sorted(set(slots))
    return slots if len(slots) == 2 else None


def _strip_recurrence(t: str):
    """Takrorlanish iborasini topadi va matndan olib tashlaydi. -> (rec_kind, rec_payload, qolgan matn)."""
    m = _TWICE_CUE.search(t)
    if m:
        return "daily", None, (t[:m.start()] + " " + t[m.end():])
    for pat in _INTERVAL:
        m = pat.search(t)
        if m:
            n = _num(m.group(1))
            return "interval", n, (t[:m.start()] + " " + t[m.end():])
    m = _EVERY_OTHER.search(t)
    if m:
        return "interval", 2, (t[:m.start()] + " " + t[m.end():])
    m = _WEEKEND.search(t)
    if m:
        return "weekdays", WEEKEND_MASK, (t[:m.start()] + " " + t[m.end():])
    m = _WORKDAYS.search(t)
    if m:
        return "weekdays", WORKDAYS_MASK, (t[:m.start()] + " " + t[m.end():])
    m = _DAILY.search(t)
    if m:
        return "daily", None, (t[:m.start()] + " " + t[m.end():])
    days = _weekdays_in(t)
    if days and _RECUR_CUE.search(t):
        return "days", days, t
    m = _WEEKLY.search(t)
    if m:
        return "weekly", None, (t[:m.start()] + " " + t[m.end():])
    return None, None, t


def _date_offset(t: str) -> int | None:
    for pat, off in _DAY_WORDS:
        if pat.search(t):
            return off
    return None


def _en_to_24h_text(t: str) -> str:
    """parse_future_time uchun: inglizcha so'zlarni mavjud parser tushunadigan shaklga o'giradi."""
    t = re.sub(r"\bday\s+after\s+tomorrow\b", "indinga", t)
    t = re.sub(r"\btomorrow\b", "ertaga", t)
    t = re.sub(r"\btoday\b|\btonight\b", "bugun", t)
    t = re.sub(r"\bin\s+(\d+)\s*hours?\b", r"\1 soat", t)
    t = re.sub(r"\bin\s+(\d+)\s*days?\b", r"\1 kun", t)
    t = re.sub(r"\bin\s+(\d+)\s*min(?:ute)?s?\b", r"\1 daqiqa", t)

    def ampm(m):
        h = int(m.group(1)) % 12 + (12 if m.group(3) == "pm" else 0)
        return f"{h:02d}:{m.group(2) or '00'}"

    return re.sub(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", ampm, t)


def parse_schedule_text(text: str, now: datetime | None = None, default_time: time | None = None) -> dict:
    """Iborani tuzilmaga o'giradi. ``now`` — Toshkent (aware); ``default_time`` — "shu vaqtda" uchun."""
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "reason": "empty"}
    if len(text) > MAX_TEXT_CHARS:
        return {"ok": False, "reason": "too_long"}
    now = now or datetime.now(TASHKENT)
    if now.tzinfo is None:
        now = TASHKENT.localize(now)
    now = now.astimezone(TASHKENT)
    t = _norm(text)

    kind, payload, rest = _strip_recurrence(t)
    if kind is None:
        # --- bir martalik: mavjud sinalgan parser ---
        weekdays = _weekdays_in(t)
        if len(weekdays) == 1 and _date_offset(t) is None:
            tm = extract_time(t) or (default_time if _SAME_TIME.search(t) else None)
            if tm is None:
                return {"ok": False, "reason": "no_time"}
            cand = first_occurrence("weekly", weekdays[0], tm, now)
            if cand is not None and cand <= now:
                cand = first_occurrence("weekly", weekdays[0], tm, now + timedelta(days=1))
            return {"ok": True, "start": cand, "recurrence": None} if cand else {"ok": False, "reason": "unrecognized"}
        from utils.helpers import parse_future_time

        tm_hint = extract_time(t)
        if tm_hint is None and default_time is not None and _SAME_TIME.search(t):
            t = f"{t} {default_time.hour:02d}:{default_time.minute:02d}"
        when = parse_future_time(_en_to_24h_text(t), now)
        if when is None:
            if extract_time(t) is None and not re.search(r"\d+\s*(daqiqa|minut|мин|soat|час|kun|день|дня)", _en_to_24h_text(t)):
                return {"ok": False, "reason": "no_time"}
            return {"ok": False, "reason": "unrecognized"}
        when = when.astimezone(TASHKENT)
        if when <= now:
            # masalan "12:00 kunda" -> mavjud parser "00 kun" deb 0 kun keyin (= hozir) qaytaradi: hech qachon o'tmish/hozirga rejalanmaydi
            return {"ok": False, "reason": "unrecognized"}
        if _date_offset(t) == 0 and when.date() != now.date():
            # "bugun 09:00" soat 10:00 da: parser jimgina ertaga 09:00 ga ko'chiradi — foydalanuvchi "bugun" degan edi
            return {"ok": False, "reason": "past"}
        return {"ok": True, "start": when, "recurrence": None}

    # --- takrorlanuvchi ---
    two = extract_two_times(rest) if kind == "daily" else None
    tm = two[0] if two else extract_time(rest)
    if tm is None and _SAME_TIME.search(rest) and default_time is not None:
        tm = default_time
    if tm is None:
        return {"ok": False, "reason": "no_time"}
    try:
        if kind == "interval":
            if payload is None or not 1 <= payload <= INTERVAL_MAX_DAYS:
                return {"ok": False, "reason": "unrecognized"}
            rtype, rday, rtime = normalize_recurrence("interval", payload, tm)
        elif kind == "weekdays":
            rtype, rday, rtime = normalize_recurrence("weekdays", payload, tm)
        elif kind == "daily":
            rtype, rday, rtime = normalize_recurrence("daily", None, tm)
            if two is not None:
                rtype, rday, rtime = normalize_recurrence("twice", time_to_minutes(two[1]), two[0])
        elif kind == "weekly":
            rtype, rday, rtime = normalize_recurrence("weekly", now.weekday() if _date_offset(rest) is None else (now + timedelta(days=_date_offset(rest))).weekday(), tm)
        else:  # "days"
            mask = weekdays_to_mask(payload)
            rtype, rday, rtime = normalize_recurrence("weekdays", mask, tm)
    except ValueError:
        return {"ok": False, "reason": "unrecognized"}

    off = _date_offset(rest)
    if rtype == "twice":
        base = now + timedelta(days=off or 0)
        start = first_occurrence(rtype, rday, rtime, base if off else now)
        if start is not None and start <= now:
            if off:
                return {"ok": False, "reason": "past"}
            start = first_occurrence(rtype, rday, rtime, now + timedelta(minutes=1))
    elif rtype in ("daily", "interval"):
        # Kun so'zi ("bugun/ertaga") bo'lsa — shu kun; bo'lmasa bugun, vaqt o'tib ketgan bo'lsa ertaga.
        naive = datetime(now.year, now.month, now.day, rtime.hour, rtime.minute) + timedelta(days=off or 0)
        start = TASHKENT.localize(naive)
        if start <= now:
            if off:
                return {"ok": False, "reason": "past"}
            start = TASHKENT.localize(naive + timedelta(days=1))
    else:
        base = now + timedelta(days=off or 0)
        start = first_occurrence(rtype, rday, rtime, base if off else now)
        if start is not None and start <= now:
            start = first_occurrence(rtype, rday, rtime, now + timedelta(minutes=1))
    if start is None:
        return {"ok": False, "reason": "unrecognized"}
    return {"ok": True, "start": start, "recurrence": {"type": rtype, "day": rday, "time": rtime}}


def validate_proposal(start, recurrence, now: datetime | None = None) -> dict:
    """Tashqi manbadan (AI) kelgan taklifni tekshiradi. -> ``{"ok": True, "start", "recurrence"}`` yoki ``{"ok": False, "reason"}``."""
    now = now or datetime.now(TASHKENT)
    if not isinstance(start, datetime):
        return {"ok": False, "reason": "unrecognized"}
    if start.tzinfo is None:
        start = TASHKENT.localize(start)
    start = start.astimezone(TASHKENT)
    if start <= now:
        return {"ok": False, "reason": "past"}
    if start > now + timedelta(days=366):
        return {"ok": False, "reason": "unrecognized"}
    rec = None
    if recurrence:
        try:
            rtype, rday, rtime = normalize_recurrence(recurrence.get("type"), recurrence.get("day"), recurrence.get("time"))
        except (ValueError, AttributeError):
            return {"ok": False, "reason": "unrecognized"}
        if rtype != "none":
            rec = {"type": rtype, "day": rday, "time": rtime}
    return {"ok": True, "start": start, "recurrence": rec}
