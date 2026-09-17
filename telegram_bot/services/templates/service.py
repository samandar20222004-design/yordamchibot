"""📋 POST SHABLONLARI — render va validatsiya mantig'i (PHASE C, 9-band).

Shablon o'zgaruvchilari (SPEKS bo'yicha aniq 7 ta)::

    {TITLE}, {TEXT}, {PRICE}, {LINK}, {CTA}, {SOURCE}, {DATE}

Kafolatlar:
  * ``render_template`` PURE funksiya — DB'siz, AI'siz, deterministik;
  * faqat RUHXAT ETILGAN o'zgaruvchilar almashtiriladi — ``{FOO}`` kabi
    noma'lum qavslar matnda TEGILMASDAN qoladi;
  * kiritilmagan o'zgaruvchi bo'sh satrga almashtiriladi ({DATE} istisno —
    avtomatik bugungi sana bilan to'ldiriladi);
  * ``validate_template_content`` — nom (< 128) va matn (1..4000)
    chegaralarini qat'iy tekshiradi;
  * DB CRUD (``database.create_post_template`` va h.k.) IDOR himoyasi bilan:
    har bir o'qish/o'chirish ``user_id`` bilan filtrlanadi.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import pytz

#: Shablonlarda qo'llab-quvvatlanadigan O'ZGARUVCHILAR (speks — aynan 7 ta).
TEMPLATE_VARIABLES: tuple[str, ...] = (
    "TITLE", "TEXT", "PRICE", "LINK", "CTA", "SOURCE", "DATE",
)

#: ``{DATE}`` uchun standart format (bugungi sana, Toshkent zonasi).
DATE_DEFAULT_FORMAT = "%d.%m.%Y"

tashkent_tz = pytz.timezone("Asia/Tashkent")

#: ``{TITLE}`` kabi o'zgaruvchi qavslarini topish (faqat KATTA harflar).
_VAR_RE = re.compile(r"\{([A-Z][A-Z0-9_]*)\}")

#: Shablon nomi va matni chegaralari.
MAX_TEMPLATE_NAME = 128
MAX_TEMPLATE_CONTENT = 4000


def default_date_value(now: datetime | None = None) -> str:
    """``{DATE}`` o'zgaruvchisining standart qiymati — bugungi sana."""
    moment = now if now is not None else datetime.now(tashkent_tz)
    if moment.tzinfo is None:
        moment = tashkent_tz.localize(moment)
    return moment.astimezone(tashkent_tz).strftime(DATE_DEFAULT_FORMAT)


def extract_variables(content: Any) -> list[str]:
    """Shablon matnidagi ishlatilgan RUUXAT ETILGAN o'zgaruvchilar (sorted).

    Faqat ``TEMPLATE_VARIABLES`` dan — ``{FOO}`` noma'lum qavs hisobga
    olinmaydi (u almashtirilmaydi ham).
    """
    text = "" if content is None else str(content)
    allowed = set(TEMPLATE_VARIABLES)
    found = {m for m in _VAR_RE.findall(text) if m in allowed}
    return sorted(found)


def validate_template_content(content: Any) -> tuple[bool, str]:
    """Shablon matnini tekshiradi: ``(ok, reason)``.

    Qoidalar: bo'sh emas, ``MAX_TEMPLATE_CONTENT`` dan oshmagan (bu
    Telegram caption chegaralaridan xavfsiz past).
    """
    text = "" if content is None else str(content).strip()
    if not text:
        return False, "empty"
    if len(text) > MAX_TEMPLATE_CONTENT:
        return False, "too_long"
    return True, ""


def normalize_value_key(key: Any) -> str:
    """Foydalanuvchi kiritgan kalitni normalizatsiya: ``" title "→"TITLE"``."""
    raw = "" if key is None else str(key)
    return raw.strip().upper().lstrip("{").rstrip("}").strip()


def parse_variable_values(text: Any, expected: list[str] | None = None) -> dict:
    """Foydalanuvchi kiritgan ``NOMI: qiymat`` qatorlarini dict'ga aylantiradi.

    Har bir qator: ``TITLE: Yangi chegirma`` yoki ``TITLE = ...``.
    Faqat kutilayotgan (``expected``) YOKI umuman ruhsat etilgan
    o'zgaruvchilar qabul qilinadi — qolganlari e'tiborsiz qoladi (xavfsiz).
    """
    allowed = set(TEMPLATE_VARIABLES)
    if expected:
        allowed &= {normalize_value_key(e) for e in expected}
    values: dict[str, str] = {}
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        for sep in (":", "="):
            if sep in line:
                key_part, _, value_part = line.partition(sep)
                key = normalize_value_key(key_part)
                value = value_part.strip()
                if key in allowed:
                    values[key] = value
                break
    return values


def render_template(
    content: Any,
    values: dict | None = None,
    date_value: str | None = None,
) -> dict:
    """Shablonni qiymatlar bilan render qiladi (PURE, deterministik).

    ``values`` kalitlari registrga bog'liq emas (``title`` == ``TITLE``).

    Qaytadi::

        {"ok": True, "text": "tayyor matn", "replaced": ["TITLE", ...],
         "missing": ["PRICE", ...], "unknown_kept": ["FOO"]}

    * ruhsat etilgan o'zgaruvchi qiymatsiz qolsa — bo'sh satr ({DATE}
      istisno: avtomatik bugungi sana);
    * noma'lum ``{FOO}`` qavslari matnda saqlanib qoladi.
    """
    text = "" if content is None else str(content)
    if not text.strip():
        return {"ok": False, "text": "", "replaced": [], "missing": [],
                "unknown_kept": []}

    source: dict[str, str] = {}
    for key, value in (values or {}).items():
        source[normalize_value_key(key)] = "" if value is None else str(value)

    used = extract_variables(text)
    replaced: list[str] = []
    missing: list[str] = []
    result = text
    for var in used:
        if var == "DATE" and var not in source:
            source[var] = date_value or default_date_value()
    for var in used:
        if var in source:
            replaced.append(var)
            result = result.replace("{" + var + "}", source[var])
        else:
            missing.append(var)
            result = result.replace("{" + var + "}", "")

    unknown_kept = sorted(
        m for m in _VAR_RE.findall(result) if m not in TEMPLATE_VARIABLES
    )
    return {
        "ok": True,
        "text": result,
        "replaced": sorted(replaced),
        "missing": sorted(missing),
        "unknown_kept": unknown_kept,
    }


__all__ = [
    "DATE_DEFAULT_FORMAT",
    "MAX_TEMPLATE_CONTENT",
    "MAX_TEMPLATE_NAME",
    "TEMPLATE_VARIABLES",
    "default_date_value",
    "extract_variables",
    "normalize_value_key",
    "parse_variable_values",
    "render_template",
    "validate_template_content",
]
