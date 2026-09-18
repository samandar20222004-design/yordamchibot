"""📢 REKLAMA SHABLON BANKI — FAZA 15 (deterministik, fakt-asosida).

Bu modul **faqat stdlib**'ga tayanadi (``services.ai`` / ``database`` import
YO'Q) — shu sababli uni ham :mod:`services.ads.engine` (AI javob bermaganda
zaxira matn), ham :mod:`services.ai.smm_mock` (``ADS`` rejimi — API kalitsiz
muhitda deterministik javob) xavfsiz import qila oladi. Import sikli yo'q.

QAT'IY QOIDA — NO FABRICATION
-----------------------------
Shablonlarda HECH QANDAY raqam, narx, foiz, kafolat, reyting yoki sertifikat
YO'Q. Postga faqat foydalanuvchi bergan ma'lumotlar tushadi:

* ``product``  — mahsulot/xizmat nomi;
* ``facts``    — berilgan faktlar ro'yxati (• punkt bo'lib chiziladi);
* ``offer``    — taklif/aksiya matni (bo'sh bo'lsa — umumiy, raqamsiz qator);
* ``audience`` — maqsadli auditoriya (kirish qatorida ishlatiladi);
* ``cta``      — harakatga chaqiruv (bo'sh bo'lsa — til bo'yicha standart CTA);
* ``link``     — havola (bo'sh bo'lsa — havola qatori umuman chizilmaydi).

Shu tufayli zaxira yo'l (offline/mock) ham "to'qima" reklama chiqarmaydi.
"""

from __future__ import annotations

import re
from html import escape as _html_escape
from typing import Any, Iterable, Sequence

#: Reklama formatlari (tartib UI tartibi bilan bir xil).
AD_FORMAT_NATIVE = "native"
AD_FORMAT_SHORT = "short"
AD_FORMAT_EDUCATIONAL = "educational"
AD_FORMAT_SOFT = "soft"

AD_FORMAT_KEYS: tuple[str, ...] = (
    AD_FORMAT_NATIVE,
    AD_FORMAT_SHORT,
    AD_FORMAT_EDUCATIONAL,
    AD_FORMAT_SOFT,
)

_LANGS = ("uz", "ru", "en")

#: Bitta faktni punktga aylantirish chegarasi.
FACT_LIMIT = 220
#: Postga tushadigan faktlar soni (format bo'yicha farq qiladi).
FACTS_PER_FORMAT: dict[str, int] = {
    AD_FORMAT_NATIVE: 4,
    AD_FORMAT_SHORT: 2,
    AD_FORMAT_EDUCATIONAL: 4,
    AD_FORMAT_SOFT: 3,
}

# ---------------------------------------------------------------------------
# TIL LUG'ATLARI (uz/ru/en pariteti — repo standarti)
# ---------------------------------------------------------------------------
_DEFAULT_CTA: dict[str, str] = {
    "uz": "Batafsil ma'lumot uchun yozing",
    "ru": "Напишите, чтобы узнать подробности",
    "en": "Message us for the details",
}

_INTRO: dict[str, str] = {
    "uz": "kanalimiz o'quvchilari uchun",
    "ru": "для читателей нашего канала",
    "en": "for the readers of this channel",
}

_OFFER_LEAD: dict[str, str] = {
    "uz": "Taklif",
    "ru": "Предложение",
    "en": "Offer",
}

_NO_OFFER: dict[str, str] = {
    "uz": "Batafsil shartlarni so'rab bilishingiz mumkin.",
    "ru": "Подробные условия можно уточнить в переписке.",
    "en": "You can ask us for the detailed terms.",
}

_EDU_PROBLEM_TITLE: dict[str, str] = {
    "uz": "Muammo tanishmi?",
    "ru": "Знакомая проблема?",
    "en": "Does this problem sound familiar?",
}

_EDU_PROBLEM_BODY: dict[str, str] = {
    "uz": (
        "Ko'pchilik bir xil holatga duch keladi: vaqt ketadi, natija esa "
        "ko'rinmaydi. Sabab — yechim tasodifan tanlanadi."
    ),
    "ru": (
        "Многие сталкиваются с одним и тем же: время уходит, а результата "
        "не видно. Причина — решение выбирают наугад."
    ),
    "en": (
        "Many people hit the same wall: time goes by and nothing changes. "
        "The reason is that the solution gets picked at random."
    ),
}

_EDU_SOLUTION_TITLE: dict[str, str] = {
    "uz": "Yechim",
    "ru": "Решение",
    "en": "The solution",
}

_SOFT_VALUE: dict[str, str] = {
    "uz": "shoshiltirmasdan, o'zingizga qulay tarzda tanlang",
    "ru": "выбирайте спокойно и в удобном для вас темпе",
    "en": "choose it calmly, at your own pace",
}

_AUDIENCE_LEAD: dict[str, str] = {
    "uz": "Kimlar uchun",
    "ru": "Для кого",
    "en": "Who it is for",
}

_HASHTAGS: dict[str, tuple[str, ...]] = {
    AD_FORMAT_NATIVE: ("#reklama", "#tanlov", "#kanal"),
    AD_FORMAT_SHORT: ("#qisqa", "#taklif", "#reklama"),
    AD_FORMAT_EDUCATIONAL: ("#foydali", "#yechim", "#reklama"),
    AD_FORMAT_SOFT: ("#qadriyat", "#tanlov", "#reklama"),
}

_WS_RE = re.compile(r"\s+")
_TAG_WORD_RE = re.compile(r"[^\W\d_]{3,}", re.UNICODE)


# ---------------------------------------------------------------------------
# YORDAMCHILAR
# ---------------------------------------------------------------------------
def esc(value: Any) -> str:
    """Foydalanuvchi matnini HTML'ga qo'yishdan oldin xavfsiz escape qilish."""
    return _html_escape(str(value if value is not None else ""), quote=False)


def _lang(lang: Any) -> str:
    code = str(lang or "uz").strip().lower().split("-", 1)[0]
    return code if code in _LANGS else "uz"


def clean_lines(values: Iterable[Any], limit: int = FACT_LIMIT,
                max_items: int = 6) -> list[str]:
    """Ishonchsiz ro'yxatdan toza, takrorlanmas, chegaralangan satrlar."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if isinstance(value, dict):
            value = (value.get("text") or value.get("value") or value.get("fact")
                     or value.get("note") or "")
        item = _WS_RE.sub(" ", str(value or "")).strip(" \t-*•—:\u00a0")
        if len(item) < 3:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item if len(item) <= limit else item[: limit - 1].rstrip() + "…")
        if len(out) >= max_items:
            break
    return out


def product_hashtag(product: Any) -> str:
    """Mahsulot nomidan bitta xavfsiz hashtag yasash (raqamsiz, lotin/kirill)."""
    words = _TAG_WORD_RE.findall(str(product or "").lower())
    if not words:
        return "#mahsulot"
    return f"#{words[0]}"


def hashtags_for(format_key: str, product: Any, maximum: int = 3) -> str:
    bank = list(_HASHTAGS.get(format_key, _HASHTAGS[AD_FORMAT_NATIVE]))
    tag = product_hashtag(product)
    if tag not in bank:
        bank.append(tag)
    return " ".join(bank[:maximum])


def fact_bullets(facts: Sequence[str], format_key: str) -> str:
    limit = FACTS_PER_FORMAT.get(format_key, 3)
    return "\n".join(f"• {esc(item)}" for item in list(facts)[:limit])


# ---------------------------------------------------------------------------
# FORMAT BO'YICHA MATN (faqat berilgan faktlar!)
# ---------------------------------------------------------------------------
def _cta_line(brief_cta: Any, lang: str) -> str:
    text = _WS_RE.sub(" ", str(brief_cta or "")).strip()
    return text or _DEFAULT_CTA[_lang(lang)]


def build_ad_text(format_key: str, product: Any, facts: Sequence[str],
                  offer: Any = "", audience: Any = "", cta: Any = "",
                  link: Any = "", lang: Any = "uz") -> str:
    """Bitta reklama formati uchun deterministik (fakt-asosidagi) matn.

    Hech qachon istisno ko'tarmaydi va hech qachon raqam/narx/kafolat
    UYDIRMAYDI — bo'sh maydonlar uchun raqamsiz, neytral qatorlar ishlatiladi.
    """
    code = _lang(lang)
    fmt = format_key if format_key in AD_FORMAT_KEYS else AD_FORMAT_NATIVE
    name = esc(_WS_RE.sub(" ", str(product or "")).strip()) or esc("Mahsulot")
    items = clean_lines(facts)
    bullets = fact_bullets(items, fmt)
    offer_text = _WS_RE.sub(" ", str(offer or "")).strip()
    offer_line = (f"<b>{esc(_OFFER_LEAD[code])}:</b> {esc(offer_text)}"
                  if offer_text else esc(_NO_OFFER[code]))
    cta_text = esc(_cta_line(cta, code))
    link_text = _WS_RE.sub(" ", str(link or "")).strip()
    link_line = f"🔗 {esc(link_text)}" if link_text else ""
    audience_text = _WS_RE.sub(" ", str(audience or "")).strip()
    tags = hashtags_for(fmt, product)

    if fmt == AD_FORMAT_SHORT:
        first_fact = esc(items[0]) if items else esc(_NO_OFFER[code])
        blocks = [
            f"⚡ <b>{name}</b>",
            first_fact,
            offer_line,
            f"👉 {cta_text}",
        ]
        if link_line:
            blocks.append(link_line)
        blocks.append(tags)
        return "\n\n".join(block for block in blocks if block)

    if fmt == AD_FORMAT_EDUCATIONAL:
        blocks = [
            f"🎓 <b>{esc(_EDU_PROBLEM_TITLE[code])}</b>",
            esc(_EDU_PROBLEM_BODY[code]),
            f"<b>{esc(_EDU_SOLUTION_TITLE[code])}: {name}</b>",
        ]
        if bullets:
            blocks.append(bullets)
        if audience_text:
            blocks.append(f"<b>{esc(_AUDIENCE_LEAD[code])}:</b> {esc(audience_text)}")
        blocks.append(offer_line)
        blocks.append(f"👉 {cta_text}")
        if link_line:
            blocks.append(link_line)
        blocks.append(tags)
        return "\n\n".join(block for block in blocks if block)

    if fmt == AD_FORMAT_SOFT:
        blocks = [
            f"🌿 <b>{name}</b> — {esc(_SOFT_VALUE[code])}.",
        ]
        if bullets:
            blocks.append(bullets)
        if audience_text:
            blocks.append(f"<b>{esc(_AUDIENCE_LEAD[code])}:</b> {esc(audience_text)}")
        blocks.append(offer_line)
        blocks.append(f"🤍 {cta_text}")
        if link_line:
            blocks.append(link_line)
        blocks.append(tags)
        return "\n\n".join(block for block in blocks if block)

    # NATIVE — kanal ohangiga mos, o'rtacha hajmli, tuzilmali.
    blocks = [
        f"🧬 <b>{name}</b> — {esc(_INTRO[code])}.",
    ]
    if bullets:
        blocks.append(bullets)
    if audience_text:
        blocks.append(f"<b>{esc(_AUDIENCE_LEAD[code])}:</b> {esc(audience_text)}")
    blocks.append(offer_line)
    blocks.append(f"👉 {cta_text}")
    if link_line:
        blocks.append(link_line)
    blocks.append(tags)
    return "\n\n".join(block for block in blocks if block)


def build_ad_text_from_payload(payload: dict | None, format_key: str,
                              lang: Any = "uz") -> str:
    """``smm_mock`` uchun: kontekst lug'atidan reklama matnini yig'ish."""
    data = payload if isinstance(payload, dict) else {}
    return build_ad_text(
        format_key,
        data.get("product") or "",
        clean_lines(data.get("facts") or []),
        offer=data.get("offer") or "",
        audience=data.get("audience") or "",
        cta=data.get("cta") or "",
        link=data.get("link") or "",
        lang=lang or data.get("lang") or "uz",
    )


__all__ = [
    "AD_FORMAT_KEYS",
    "AD_FORMAT_EDUCATIONAL",
    "AD_FORMAT_NATIVE",
    "AD_FORMAT_SHORT",
    "AD_FORMAT_SOFT",
    "FACTS_PER_FORMAT",
    "build_ad_text",
    "build_ad_text_from_payload",
    "clean_lines",
    "esc",
    "fact_bullets",
    "hashtags_for",
    "product_hashtag",
]
