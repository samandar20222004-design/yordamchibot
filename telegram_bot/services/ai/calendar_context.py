"""🌍 AI PROMPT KALENDAR KONTEKSTI — foydalanuvchi davlatiga mos sanalar bloki.

Nima uchun
----------
AI post generatsiyasi ilgari faqat O'zbekiston taqvimini bilardi (chunki
bayramlar :mod:`services.uzbekistan_calendar` ichida qattiq kodlangan edi).
Endi :class:`services.calendar_service.CalendarService` davlat bo'yicha
dinamik yechadi va bu modul o'sha ma'lumotni **AI tizim promptiga xavfsiz
qo'shish** uchun yagona kirish nuqtasi:

    from services.ai.calendar_context import with_calendar_context

    system = with_calendar_context(base_prompt, country="UZ", lang="uz")

Shartnoma (:func:`utils.ai_agent.with_language` bilan bir xil):

* **idempotent** — bir xil davlat/kontekst qayta qo'shilsa blok ko'paymaydi;
* **davlat almashsa yangilanadi** — eski blok olib tashlanib yangi davlatniki
  qo'yiladi (prompt hech qachon ikki davlat taqvimini bir vaqtda saqlamaydi);
* **fail-soft** — sana topilmasa yoki xato bo'lsa asl prompt O'ZGARISHSIZ
  qaytadi (hech qachon istisno bermaydi);
* **gallyutsinatsiya qo'riqchisi** — blok oxirida "bu sanalarni faqat mavzu
  taklifi sifatida ishlat, o'ylab topma" qoidasi bor.

Bu modul FAQAT stdlib + :mod:`services.calendar_service` ga tayanadi
(telegram/database import YO'Q).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Mapping

from services.calendar_service import (
    DEFAULT_COUNTRY,
    coerce_date,
    get_calendar_service,
    normalize_calendar_lang,
)

#: ``with_calendar_context()`` qo'llanilganligini bildiruvchi marker
#: (idempotentlik va davlat almashishini aniqlash uchun).
AI_CALENDAR_MARKER = "TARGET COUNTRY CALENDAR"

#: Blok sarlavhasidagi davlat nomi uchun (idempotentlik solishtiruvida ishlatiladi).
DEFAULT_PROMPT_DAYS = 90
DEFAULT_PROMPT_MAX_EVENTS = 8


def calendar_directive(country: Any = None, lang: str = "uz", *,
                       today: date | None = None,
                       days: int = DEFAULT_PROMPT_DAYS,
                       max_events: int = DEFAULT_PROMPT_MAX_EVENTS) -> str:
    """AI tizim promptiga qo'yiladigan, davlatga mos kalendar bloki.

    Sana topilmasa ``""`` qaytadi (prompt'ni keraksiz matn bilan to'ldirmaydi).

    Misol (``country="UZ"``, ``lang="en"``)::

        ============ TARGET COUNTRY CALENDAR (Uzbekistan) ============
        CONTENT CALENDAR (for the user's country):
        Uzbekistan content calendar — Uzbekistan:
        - 2026-11-27 (in 48 days): Black Friday [Shopping season]
        Use these dates only as TOPIC SUGGESTIONS; ...
        ============ END OF CALENDAR CONTEXT ============
    """
    try:
        code = normalize_calendar_lang(lang)
        service = get_calendar_service()
        resolved = service.resolve_country(country)
        anchor = coerce_date(today) or date.today()
        body = service.prompt_block(resolved, code, today=anchor,
                                    days=days, max_events=max_events)
        if not body:
            return ""
        label = service.country_name(resolved, code) or resolved or DEFAULT_COUNTRY
        return (
            f"============ {AI_CALENDAR_MARKER} ({label}) ============\n"
            f"{body}\n"
            f"============ END OF CALENDAR CONTEXT ============"
        )
    except Exception:  # noqa: BLE001 — prompt konteksti hech qachon generatsiyani buzmaydi
        return ""


#: Prompt ichidagi avval qo'shilgan kalendar blokini topib olib tashlash uchun.
_CALENDAR_DIRECTIVE_RX = re.compile(
    r"=+[ \t]*" + AI_CALENDAR_MARKER + r".*?=+[ \t]*END OF CALENDAR CONTEXT[ \t]*=+[ \t]*\n?",
    re.DOTALL | re.IGNORECASE,
)


def strip_calendar_directive(text: Any) -> str:
    """Prompt ichidagi eski kalendar blokini olib tashlaydi (davlat almashganda)."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    return _CALENDAR_DIRECTIVE_RX.sub("", text).strip()


def with_calendar_context(system_instruction: Any, country: Any = None, lang: str = "uz",
                          **kwargs: Any) -> str:
    """``system_instruction`` ga davlatga mos kalendar blokini qo'shadi.

    Xususiyatlar:

    * **idempotent** — aynan shu blok allaqachon bor bo'lsa matn O'ZGARISHSIZ
      qaytadi;
    * **davlat almashsa yangilanadi** — eski blok o'chirilib yangisi qo'yiladi;
    * **sana yo'q bo'lsa toza** — bo'sh blok qo'shilmaydi (va eski blok
      o'chiriladi, chunki endi noto'g'ri bo'lib qolgan);
    * hech qachon istisno bermaydi.
    """
    try:
        base = system_instruction if isinstance(system_instruction, str) \
            else str(system_instruction or "")
    except Exception:  # pragma: no cover - himoya
        base = ""
    directive = calendar_directive(country, lang, **kwargs)
    had_block = AI_CALENDAR_MARKER in base
    stripped = strip_calendar_directive(base) if had_block else base.strip()
    if not directive:
        # Kontekst mavjud emas: eski (endi noto'g'ri) blok ham olib tashlanadi.
        return stripped if stripped else base.strip()
    if had_block and directive in base:
        return base
    if not stripped:
        return directive
    return f"{directive}\n\n{stripped}"


def calendar_context_lines(country: Any = None, lang: str = "uz", *,
                           today: date | None = None,
                           days: int = DEFAULT_PROMPT_DAYS,
                           max_events: int = DEFAULT_PROMPT_MAX_EVENTS) -> tuple[str, ...]:
    """Prompt bloki ichidagi faqat sana qatorlari (testlar/telemetriya uchun)."""
    try:
        service = get_calendar_service()
        anchor = coerce_date(today) or date.today()
        return tuple(
            f"{event.date.isoformat()}\t{event.name(normalize_calendar_lang(lang))}"
            for event in service.upcoming(anchor, days, country)[:max(1, int(max_events))]
        )
    except Exception:  # noqa: BLE001 — himoya
        return ()


def supported_countries() -> tuple[str, ...]:
    """AI konteksti uchun mavjud davlat kodlari (JSON profillari asosida)."""
    try:
        return get_calendar_service().available_countries()
    except Exception:  # noqa: BLE001 — himoya
        return (DEFAULT_COUNTRY,)


def resolve_prompt_country(country: Any = None) -> str:
    """Prompt uchun davlat kodini normalizatsiya qiladi (hech qachon yiqilmaydi)."""
    try:
        return get_calendar_service().resolve_country(country)
    except Exception:  # noqa: BLE001 — himoya
        return DEFAULT_COUNTRY


def calendar_prompt_context(country: Any = None, lang: str = "uz",
                            **kwargs: Any) -> Mapping[str, Any]:
    """Telemetriya/audit uchun ixcham kontekst (prompt matni emas)."""
    resolved = resolve_prompt_country(country)
    lines = calendar_context_lines(resolved, lang, **kwargs)
    return {
        "country": resolved,
        "lang": normalize_calendar_lang(lang),
        "events": len(lines),
    }


__all__ = [
    "AI_CALENDAR_MARKER",
    "DEFAULT_PROMPT_DAYS",
    "DEFAULT_PROMPT_MAX_EVENTS",
    "calendar_context_lines",
    "calendar_directive",
    "calendar_prompt_context",
    "resolve_prompt_country",
    "strip_calendar_directive",
    "supported_countries",
    "with_calendar_context",
]
