"""P0-C — Tizim/retry ko'rsatmalarining post matniga sizib chiqishidan himoya.

Muammo (Phase 0 auditi, P0-C)
-----------------------------
Orkestratorning «kuchaytirilgan retry» ko'rsatmasi
(masalan ``MUHIM: Oldingi javob juda qisqa ... TAQIQLANADI!``) ba'zi hollarda
provayder javobi ICHIDA foydalanuvchiga qaytarilardi:

* :class:`services.ai.providers.MockProvider` promptni sarlavha sifatida
  ko'chirardi — retry prompti bilan chaqirilganda ko'rsatma post matniga
  tushib qolardi;
* real modellar esa promptni «davom ettirib», ko'rsatmani javob boshida
  takrorlashi mumkin.

Yechim — ikki qatlamli himoya
-----------------------------
1. **Kirish tomoni**: provayderga yuboriladigan matn
   (:func:`strip_instruction_leaks`) ko'rsatmalardan tozalanadi — Mock
   endi ko'rsatmani javobiga ko'chirmaydi;
2. **Chiqish tomoni**: har bir provayder javobi foydalanuvchiga
   yetib borishidan OLDIN (:func:`sanitize_output`) tozalanadi va tozalangan
   matn qaytadan :class:`services.ai.validator.AIOutputValidator` dan o'tadi.

Funksiyalar idempotent: toza matnga qayta qo'llanilsa natija o'zgarmaydi.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 1. Ma'lum ko'rsatma BLOKLARI (AIOutputValidator.get_retry_prompt_addon matnlari)
# ---------------------------------------------------------------------------
# Bu bloklar faqat prompt ICHIDA yuborilishi kerak. Ular javob matnida paydo
# bo'lsa — sizib chiqish (leak) va foydalanuvchiga KO'RSATILMAYDI.
LEAK_BLOCK_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        # O'zbekcha — juda qisqa/bo'sh javob uchun retry ko'rsatmasi
        r"MUHIM:\s*Oldingi javob juda qisqa yoki bo'sh bo'ldi!.*?TAQIQLANADI!?",
        # O'zbekcha — til mosligi
        r"DIQQAT:\s*Matn QAT'IY O'ZBEK TILIDA.*?aralashtirmang\.?",
        # O'zbekcha — xavfli belgilar
        r"DIQQAT:\s*Matnda hech qanday maxsus kodlar.*?taqdim eting\.?",
        # O'zbekcha — umumiy qo'shimcha ko'rsatma
        r"Iltimos,\s*ko'rsatmalarga qat'iy amal qilgan holda.*?post yozing\.?",
        # Ruscha
        r"ВАЖНО:\s*Предыдущий ответ был слишком коротким или пустым!.*?фразы!?",
        r"ВНИМАНИЕ:\s*Ответ ОБЯЗАТЕЛЬНО должен быть строго на РУССКОМ языке.*?основного текста\.?",
        # Inglizcha
        r"IMPORTANT:\s*The previous output was too thin or empty!.*?one line!?",
        r"ATTENTION:\s*The response MUST be strictly in ENGLISH!.*?post text\.?",
    )
)

# ---------------------------------------------------------------------------
# 2. Qator (line) darajasidagi belgilar — blok to'liq mos kelmasa ham ushlaydi
# ---------------------------------------------------------------------------
# ATAYLAB ANIQ iboralar tanlangan: oddiy post matni (masalan «Diqqat, aksiya!»)
# o'chib ketmasligi kerak — faqat tizim ko'rsatmalariga xos bo'laklar.
LEAK_LINE_MARKERS: tuple[str, ...] = (
    # O'zbekcha
    "oldingi javob juda qisqa",
    "javob juda qisqa yoki bo'sh",
    "qatorli quruq javob berish taqiqlanadi",
    "qat'iy o'zbek tilida",
    "qat'iy amal qilgan holda",
    "hech qanday maxsus kodlar, skriptlar",
    "boshqa tillarni aralashtirmang",
    # Ruscha
    "предыдущий ответ был слишком коротким",
    "ответ обязательно должен быть строго на русском языке",
    "не используйте односложные фразы",
    "не используйте другие языки для основного текста",
    # Inglizcha
    "the previous output was too thin",
    "the response must be strictly in english",
    "do not reply with one line",
    "do not use russian or other languages in the post text",
    # Umumiy tizim ko'rsatmasi belgilari
    "system prompt",
    "system instruction",
    "tizim ko'rsatmasi",
    "system ko'rsatmasi",
    "instruksiya:",
    "instructions:",
    "<system>",
    "[system]",
    "### instruction",
    "you are a helpful ai",
)

# ---------------------------------------------------------------------------
# 3. Tozalash uchun yordamchi regexlar
# ---------------------------------------------------------------------------
_TAG_REGEX = re.compile(r"<[^>]*>")
_EMPTY_TAG_REGEX = re.compile(
    r"<(b|strong|i|em|u|ins|s|strike|del|code|pre)>\s*</\1>",
    re.IGNORECASE | re.DOTALL,
)
_MULTI_NEWLINE_REGEX = re.compile(r"\n{3,}")
_TRAILING_SPACES_REGEX = re.compile(r"[ \t]+\n")
_APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'"})


def _normalize_for_match(line: str) -> str:
    """Taqqoslash uchun qatorni normallashtiradi (teglar, apostrof, registr)."""
    text = _TAG_REGEX.sub(" ", str(line or ""))
    text = text.translate(_APOSTROPHES)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _is_instruction_line(line: str) -> bool:
    """Qator tizim/retry ko'rsatmasining bir qismimi?"""
    normalized = _normalize_for_match(line)
    if not normalized:
        return False
    return any(marker in normalized for marker in LEAK_LINE_MARKERS)


def has_instruction_leak(text: str | None) -> bool:
    """Matnda tizim/retry ko'rsatmasi sizib chiqqanini aniqlaydi."""
    if not text:
        return False
    if any(pattern.search(text) for pattern in LEAK_BLOCK_PATTERNS):
        return True
    return any(_is_instruction_line(line) for line in str(text).splitlines())


def strip_instruction_leaks(text: str | None) -> str:
    """Matndan tizim/retry ko'rsatmalarini olib tashlaydi (idempotent).

    - ma'lum ko'rsatma bloklari butunlay o'chiriladi;
    - ko'rsatma belgisiga ega qatorlar olib tashlanadi;
    - bo'sh qolgan HTML teglar, ortiqcha bo'sh qatorlar tozalanadi.
    """
    if not text:
        return ""

    cleaned = str(text)
    for pattern in LEAK_BLOCK_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)

    kept_lines = [line for line in cleaned.splitlines() if not _is_instruction_line(line)]
    cleaned = "\n".join(kept_lines)

    # <b></b> kabi bo'sh qolgan teglarni (ichma-ich bo'lsa ham) tozalaymiz
    for _ in range(3):
        updated = _EMPTY_TAG_REGEX.sub("", cleaned)
        if updated == cleaned:
            break
        cleaned = updated

    cleaned = _TRAILING_SPACES_REGEX.sub("\n", cleaned)
    cleaned = _MULTI_NEWLINE_REGEX.sub("\n\n", cleaned)
    return cleaned.strip()


def sanitize_output(text: str | None) -> tuple[str, bool]:
    """Provayder javobini tozalaydi: ``(toza_matn, sizib_chiqish_topildi)``.

    ``True`` bayrog'i — javobda tizim/retry ko'rsatmasi bo'lgan (ya'ni matn
    o'zgargan) holat; monitoring/logging uchun.
    """
    raw = "" if text is None else str(text)
    from services.ai_engine.safety import contains_leak
    if contains_leak(raw):
        return "", True
    if not has_instruction_leak(raw):
        return raw.strip(), False
    return strip_instruction_leaks(raw), True


#: Modulning ommaviy API'si.
__all__ = [
    "LEAK_BLOCK_PATTERNS",
    "LEAK_LINE_MARKERS",
    "has_instruction_leak",
    "sanitize_output",
    "strip_instruction_leaks",
]
