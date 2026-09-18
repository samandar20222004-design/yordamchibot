"""📢 REKLAMA GENERATSIYASI DVIGATELI — FAZA 15.

Bitta **reklama brief**idan 4 xil formatdagi reklama varianti yaratadi:

=====  ==============  ====================================================
  #    format          Burchak
=====  ==============  ====================================================
 1     🧬 native       kanalning Channel DNA ohangiga to'liq mos (uzunlik,
                       emoji darajasi, CTA uslubi DNA'dan olinadi)
 2     ⚡ short         qisqa, lo'nda, 5 sekundda o'qiladigan
 3     🎓 educational  muammo → yechim sifatida mahsulot (PAS'ning yumshoq
                       varianti, raqamsiz)
 4     🌿 soft         yumshoq taklif — qadriyatga asoslangan, bosimsiz CTA
=====  ==============  ====================================================

QAT'IY XAVFSIZLIK QOIDASI — NO FABRICATION
------------------------------------------
AI foydalanuvchi BERMAGAN narx, kafolat ("100% natija"), reyting, sertifikat
yoki statistikani o'zidan to'qib qo'sha OLMAYDI. Himoya uch qavatli:

1. **Prompt kontrakti** — brief'dagi faktlar "YAGONA RUXSAT ETILGAN
   MANBA" sifatida beriladi, taqiqlar aniq sanab o'tiladi;
2. **Chiqish filtri** — :func:`services.ads.audit.strip_unsupported_claims`
   har bir javobni faktlar korpusi bilan solishtiradi va faktlarda bo'lmagan
   da'voni jumla darajasida OLIB TASHLAYDI (qanday model bo'lishidan
   qat'i nazar);
3. **Zaxira yo'l** — AI javob bermaganda :mod:`services.ads.templates`
   bankidagi deterministik, raqamsiz shablon ishlatiladi (u ham faqat
   berilgan faktlardan yig'iladi).

Poydevor (noldan yozilmagan):
* ``services.ai.smm_common.SMMFeatureService`` — AIOrchestrator (Phase 3),
  Provider Chain, Phase 2 ATOMIK kvota (butun batch uchun 1 bron),
  sanitize_html + 4096 chunk;
* ``services.channels.dna`` — Channel DNA profili va ``build_dna_system_prompt``;
* ``services.ads.audit`` — yagona "asossiz da'vo" siyosati.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from services.ai.smm_common import (
    CHUNK_SAFE_LIMIT,
    DEFAULT_LANG,
    SMMFeatureService,
    TELEGRAM_TEXT_LIMIT,
    chunk_blocks,
    clip,
    fingerprint,
    lang_text,
    normalize_lang,
    same_content,
    sanitize_html,
    strip_html,
)
from services.ads.audit import (
    SEVERITY_CRITICAL,
    SEVERITY_WARNING,
    ClaimFinding,
    claim_corpus,
    scan_unsupported_claims,
    strip_unsupported_claims,
)
from services.ads.templates import (
    AD_FORMAT_EDUCATIONAL,
    AD_FORMAT_KEYS,
    AD_FORMAT_NATIVE,
    AD_FORMAT_SHORT,
    AD_FORMAT_SOFT,
    build_ad_text,
    clean_lines,
)

logger = logging.getLogger(__name__)


# ===========================================================================
# 1) BRIEF (kiruvchi ma'lumotlar)
# ===========================================================================
BRIEF_PRODUCT_LIMIT = 120
BRIEF_FACT_LIMIT = 240
BRIEF_FACTS_MAX = 8
BRIEF_OFFER_LIMIT = 240
BRIEF_AUDIENCE_LIMIT = 180
BRIEF_CTA_LIMIT = 120
BRIEF_LINK_LIMIT = 300

#: Faqat shu sxemadagi havolalar CTA sifatida qabul qilinadi.
ALLOWED_LINK_SCHEMES = ("http://", "https://", "t.me/", "tg://")

ERROR_EMPTY_PRODUCT = "EMPTY_PRODUCT"
ERROR_NO_FACTS = "NO_FACTS"
ERROR_INVALID_LINK = "INVALID_LINK"


def is_safe_link(link: Any) -> bool:
    """CTA havolasi xavfsizmi (javascript:/data:/bo'sh — rad etiladi)."""
    value = str(link or "").strip().lower()
    if not value:
        return True  # havola ixtiyoriy
    if value.startswith(ALLOWED_LINK_SCHEMES):
        return True
    # "example.com/page" kabi sxemasiz, lekin nuqtali domen — ruxsat.
    return bool(re.fullmatch(r"[\w.-]+\.[a-z]{2,}(?:/[\w./~%\-=?&#+]*)?", value))


@dataclass
class AdBrief:
    """Reklama briefi — generatsiyaning YAGONA fakt manbai."""

    product: str = ""
    facts: tuple[str, ...] = ()
    offer: str = ""
    audience: str = ""
    cta: str = ""
    link: str = ""
    lang: str = DEFAULT_LANG
    tone_note: str = ""
    channel_id: str = ""

    # -- konstruktsiya -----------------------------------------------------
    @classmethod
    def build(cls, product: Any = "", facts: Any = None, offer: Any = "",
              audience: Any = "", cta: Any = "", link: Any = "",
              lang: Any = DEFAULT_LANG, tone_note: Any = "",
              channel_id: Any = "") -> "AdBrief":
        """Ishonchsiz kirishdan toza brief ( chegaralar + escape'siz matn)."""
        items = clean_lines(facts if facts is not None else [],
                            limit=BRIEF_FACT_LIMIT, max_items=BRIEF_FACTS_MAX)
        return cls(
            product=clip(product, BRIEF_PRODUCT_LIMIT),
            facts=tuple(items),
            offer=clip(offer, BRIEF_OFFER_LIMIT),
            audience=clip(audience, BRIEF_AUDIENCE_LIMIT),
            cta=clip(cta, BRIEF_CTA_LIMIT),
            link=str(link or "").strip()[:BRIEF_LINK_LIMIT],
            lang=normalize_lang(lang),
            tone_note=clip(tone_note, 180),
            channel_id=str(channel_id or "").strip()[:64],
        )

    # -- validatsiya -------------------------------------------------------
    def validate(self) -> tuple[bool, str | None]:
        """Brief to'ldirilganmi. Qaytadi: ``(ok, error_code)``."""
        if len(self.product.strip()) < 2:
            return False, ERROR_EMPTY_PRODUCT
        if not self.facts and not self.offer.strip():
            return False, ERROR_NO_FACTS
        if not is_safe_link(self.link):
            return False, ERROR_INVALID_LINK
        return True, None

    # -- fakt korpusi (NO FABRICATION asosi) -------------------------------
    def corpus(self) -> str:
        """Barcha ruxsat etilgan faktlar bitta matnda (audit shu bilan solishtiradi)."""
        return claim_corpus([
            self.product, list(self.facts), self.offer,
            self.audience, self.cta, self.link, self.tone_note,
        ])

    def fact_lines(self, limit: int = BRIEF_FACTS_MAX) -> list[str]:
        return list(self.facts)[:limit]

    def as_dict(self) -> dict:
        return {
            "product": self.product,
            "facts": list(self.facts),
            "offer": self.offer,
            "audience": self.audience,
            "cta": self.cta,
            "link": self.link,
            "lang": self.lang,
            "tone_note": self.tone_note,
            "channel_id": self.channel_id,
        }

    def mock_payload(self) -> dict:
        """MockProvider uchun ixcham (escape qilingan) yuk."""
        return {
            "product": self.product,
            "facts": list(self.facts),
            "offer": self.offer,
            "audience": self.audience,
            "cta": self.cta,
            "link": self.link,
            "lang": self.lang,
        }


# ===========================================================================
# 2) REKLAMA FORMATLARI (4 xil)
# ===========================================================================
@dataclass(frozen=True)
class AdFormat:
    """Bitta reklama formati (burchak)."""

    key: str
    emoji: str
    order: int
    label: dict
    angle: dict
    instruction: dict
    hashtags: tuple
    max_chars: int

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_angle(self, lang: Any) -> str:
        return lang_text(self.angle, lang, "")

    def t_instruction(self, lang: Any) -> str:
        return lang_text(self.instruction, lang, "")


AD_FORMATS: tuple[AdFormat, ...] = (
    AdFormat(
        key=AD_FORMAT_NATIVE, emoji="🧬", order=1,
        label={"uz": "Native (kanal ohangi)", "ru": "Нативный (тон канала)",
               "en": "Native (channel tone)"},
        angle={
            "uz": "Kanalning Channel DNA ohangiga to'liq mos — o'quvchi "
                  "buni reklama deb emas, kanal postidek o'qiydi",
            "ru": "Полностью в тоне Channel DNA — читатель воспринимает это "
                  "как пост канала, а не как рекламу",
            "en": "Fully in the Channel DNA tone — reads like a channel post, "
                  "not an ad",
        },
        instruction={
            "uz": (
                "Kanalning odatiy ohangi, uzunligi va formatlash uslubida "
                "yozing (yuqoridagi CHANNEL DNA bloki — qat'iy me'yor). "
                "Reklama tiliga o'tmang: kirish qator kanal mavzusidan "
                "boshlanadi, mahsulot tabiiy ravishda davomida keladi. "
                "Faktlar • punkt bo'lsin, oxirida BITTA CTA."
            ),
            "ru": (
                "Пишите в привычном тоне, длине и вёрстке канала (блок "
                "CHANNEL DNA выше — жёсткая норма). Не переходите на "
                "рекламный язык: первая строка продолжает тему канала, "
                "продукт появляется естественно. Факты — пункты •, в конце "
                "ОДИН CTA."
            ),
            "en": (
                "Write in the channel's usual tone, length and formatting "
                "(the CHANNEL DNA block above is a hard constraint). Do not "
                "switch to ad-speak: open on the channel's topic and let the "
                "product appear naturally. Facts as • bullets, ONE CTA at "
                "the end."
            ),
        },
        hashtags=("#reklama", "#tanlov", "#kanal"),
        max_chars=2200,
    ),
    AdFormat(
        key=AD_FORMAT_SHORT, emoji="⚡", order=2,
        label={"uz": "Qisqa", "ru": "Короткий", "en": "Short"},
        angle={
            "uz": "5 sekundda o'qiladi: bitta hook, ikki fakt, bitta CTA",
            "ru": "Читается за 5 секунд: один хук, два факта, один CTA",
            "en": "Read in five seconds: one hook, two facts, one CTA",
        },
        instruction={
            "uz": (
                "JAMI 3-5 qisqa qator (120-400 belgi). 1-qator — hook "
                "(mahsulot nomi <b>qalin</b>), keyin eng muhim 1-2 fakt, "
                "so'ng taklif va BITTA CTA. Ortiqcha so'z, kirish va "
                "xabarnoma YO'Q."
            ),
            "ru": (
                "ВСЕГО 3-5 коротких строк (120-400 символов). Первая — хук "
                "(название <b>жирным</b>), затем 1-2 главных факта, потом "
                "оффер и ОДИН CTA. Без вводных и лишних слов."
            ),
            "en": (
                "ONLY 3-5 short lines (120-400 characters). Line one is the "
                "hook (product name in <b>bold</b>), then one or two key "
                "facts, then the offer and ONE CTA. No filler."
            ),
        },
        hashtags=("#qisqa", "#taklif", "#reklama"),
        max_chars=600,
    ),
    AdFormat(
        key=AD_FORMAT_EDUCATIONAL, emoji="🎓", order=3,
        label={"uz": "Ta'limiy", "ru": "Обучающий", "en": "Educational"},
        angle={
            "uz": "Avval muammo va uning oqibati, keyin yechim sifatida mahsulot",
            "ru": "Сначала проблема и её цена, затем продукт как решение",
            "en": "First the problem and its cost, then the product as the fix",
        },
        instruction={
            "uz": (
                "Tuzilma: 1) muammo (o'quvchi tanishi), 2) nega oddiy yechimlar "
                "ishlamaydi, 3) yechim — mahsulot va uning faktlari (• "
                "punktlar), 4) kimlar uchun, 5) taklif + BITTA CTA. "
                "O'rgatuvchi ohang, bosim YO'Q."
            ),
            "ru": (
                "Структура: 1) проблема, которую читатель узнаёт; 2) почему "
                "обычные решения не работают; 3) решение — продукт и его "
                "факты (пункты •); 4) для кого; 5) оффер + ОДИН CTA. Тон "
                "обучающий, без давления."
            ),
            "en": (
                "Structure: 1) the problem the reader recognises; 2) why the "
                "usual fixes fail; 3) the solution — the product and its "
                "facts (• bullets); 4) who it is for; 5) offer + ONE CTA. "
                "Teaching tone, no pressure."
            ),
        },
        hashtags=("#foydali", "#yechim", "#reklama"),
        max_chars=2600,
    ),
    AdFormat(
        key=AD_FORMAT_SOFT, emoji="🌿", order=4,
        label={"uz": "Yumshoq taklif", "ru": "Мягкое предложение",
               "en": "Soft offer"},
        angle={
            "uz": "Qadriyatga asoslangan yumshoq taklif — bosimsiz, ishonchli",
            "ru": "Мягкое предложение на основе ценностей — без давления",
            "en": "A value-led soft offer — no pressure, high trust",
        },
        instruction={
            "uz": (
                "Ohang: xotirjam, hurmatli, bosimsiz. «Shoshiling», «oxirgi "
                "imkoniyat», undov belgilari TAQIQLANADI. Qadriyat → faktlar "
                "(•) → yumshoq taklif → muloyim CTA («yozing», «tanishing»). "
                "1-2 emoji (🌿 🤍 ✨)."
            ),
            "ru": (
                "Тон: спокойный, уважительный, без давления. Слова «спешите», "
                "«последний шанс» и восклицательные знаки ЗАПРЕЩЕНЫ. "
                "Ценность → факты (•) → мягкое предложение → вежливый CTA. "
                "1-2 эмодзи (🌿 🤍 ✨)."
            ),
            "en": (
                "Tone: calm, respectful, pressure-free. Words like "
                "“hurry”, “last chance” and exclamation marks are FORBIDDEN. "
                "Value → facts (•) → soft offer → gentle CTA. 1-2 emojis "
                "(🌿 🤍 ✨)."
            ),
        },
        hashtags=("#qadriyat", "#tanlov", "#reklama"),
        max_chars=1800,
    ),
)

AD_FORMAT_INDEX: dict[str, AdFormat] = {item.key: item for item in AD_FORMATS}
AD_FORMAT_COUNT = len(AD_FORMATS)


def resolve_format(key: Any) -> AdFormat:
    """Kalit bo'yicha format (noma'lum → native)."""
    return AD_FORMAT_INDEX.get(str(key or "").strip().lower(),
                               AD_FORMAT_INDEX[AD_FORMAT_NATIVE])


def formats_for(keys: Sequence[str] | None) -> tuple[AdFormat, ...]:
    """Tanlangan formatlar (bo'sh/None → barcha 4 tasi, tartib saqlanadi)."""
    if not keys:
        return AD_FORMATS
    chosen: list[AdFormat] = []
    for key in keys:
        item = AD_FORMAT_INDEX.get(str(key or "").strip().lower())
        if item and item not in chosen:
            chosen.append(item)
    return tuple(chosen) if chosen else AD_FORMATS


# ===========================================================================
# 3) NATIJA OBYEKTLARI
# ===========================================================================
@dataclass
class AdVariant:
    """Bitta reklama varianti."""

    index: int
    format: str
    emoji: str
    label: str
    angle: str
    content: str
    source: str = "ai"
    cta: str = ""
    link: str = ""
    hashtags: tuple = ()
    removed_claims: tuple = ()
    max_chars: int = TELEGRAM_TEXT_LIMIT

    @property
    def chars(self) -> int:
        return len(strip_html(self.content))

    def render(self) -> str:
        """Yuborishga tayyor, sanitize + chunk qilingan xabar."""
        body = sanitize_html(self.content, self.max_chars)
        pieces = chunk_blocks([body], limit=min(CHUNK_SAFE_LIMIT, self.max_chars))
        return pieces[0] if pieces else body

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "format": self.format,
            "emoji": self.emoji,
            "label": self.label,
            "angle": self.angle,
            "content": self.content,
            "source": self.source,
            "chars": self.chars,
            "cta": self.cta,
            "link": self.link,
            "hashtags": list(self.hashtags),
            "removed_claims": [item.as_dict() for item in self.removed_claims],
            "message": self.render(),
        }


@dataclass
class AdEngineResult:
    """Reklama generatsiyasining yakuniy natijasi."""

    success: bool = False
    variants: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    brief: dict = field(default_factory=dict)
    lang: str = DEFAULT_LANG
    provider_used: str = "none"
    cost: int = 0
    reservation_id: Any = None
    quota: dict = field(default_factory=dict)
    paid: bool = False
    refund_issued: bool = False
    fallback_used: bool = False
    dna_applied: bool = False
    dna_confidence: str = ""
    dna_sample_size: int = 0
    removed_claims: list = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None

    @property
    def count(self) -> int:
        return len(self.variants)

    def formats(self) -> list[str]:
        return [item.format for item in self.variants]

    def by_format(self, key: str) -> AdVariant | None:
        for item in self.variants:
            if item.format == str(key):
                return item
        return None

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "count": self.count,
            "formats": self.formats(),
            "brief": dict(self.brief),
            "lang": self.lang,
            "provider_used": self.provider_used,
            "cost": self.cost,
            "reservation_id": self.reservation_id,
            "quota": dict(self.quota),
            "paid": self.paid,
            "refund_issued": self.refund_issued,
            "fallback_used": self.fallback_used,
            "dna_applied": self.dna_applied,
            "dna_confidence": self.dna_confidence,
            "dna_sample_size": self.dna_sample_size,
            "removed_claims": [item.as_dict() for item in self.removed_claims],
            "error": self.error,
            "error_code": self.error_code,
            "variants": [item.as_dict() for item in self.variants],
            "chunks": list(self.chunks),
        }


# ===========================================================================
# 4) PROMPT (NO FABRICATION KONTRAKTI BILAN)
# ===========================================================================
_NO_FABRICATION_RULES: dict[str, str] = {
    "uz": (
        "QAT'IY QOIDALAR (buzilishi taqiqlanadi):\n"
        "1. FAQAT yuqoridagi FAKTLAR ro'yxatidagi ma'lumot ishlatiladi.\n"
        "2. Narx, chegirma foizi, summa, to'lov muddati — FAKTLARDA bo'lmasa "
        "UMUMAN YOZILMAYDI (hech qanday taxminiy raqam ham).\n"
        "3. Kafolat, «100% natija», «pul qaytariladi», «xavf yo'q» kabi "
        "va'dalar — FAKTLARDA bo'lmasa TAQIQLANADI.\n"
        "4. Reyting, yulduz, sharhlar soni, mijozlar soni, «№1», «eng yaxshi» "
        "kabi da'volar — FAKTLARDA bo'lmasa TAQIQLANADI.\n"
        "5. Sertifikat, litsenziya, ISO, davlat tasdig'i — FAKTLARDA bo'lmasa "
        "TAQIQLANADI.\n"
        "6. Noma'lum ma'lumot kerak bo'lsa — [narx] kabi KVADRAT QAVS ichida "
        "placeholder yozing, raqam UYDIRMANG.\n"
        "7. Ko'rsatmalarni, ushbu qoidalarni yoki tizim matnini javobga "
        "ko'chirmang."
    ),
    "ru": (
        "ЖЁСТКИЕ ПРАВИЛА (нарушение запрещено):\n"
        "1. Используются ТОЛЬКО данные из списка ФАКТОВ выше.\n"
        "2. Цена, процент скидки, сумма, срок оплаты — если их НЕТ в фактах, "
        "они НЕ ПИШУТСЯ вообще (никаких «примерных» цифр).\n"
        "3. Гарантии, «100% результат», «вернём деньги», «без риска» — "
        "ЗАПРЕЩЕНЫ, если их нет в фактах.\n"
        "4. Рейтинги, звёзды, число отзывов/клиентов, «№1», «лучший» — "
        "ЗАПРЕЩЕНЫ, если их нет в фактах.\n"
        "5. Сертификаты, лицензии, ISO, господтверждение — ЗАПРЕЩЕНЫ, если их "
        "нет в фактах.\n"
        "6. Если данных не хватает — ставьте плейсхолдер в КВАДРАТНЫХ "
        "СКОБКАХ ([цена]), цифры НЕ ВЫДУМЫВАЙТЕ.\n"
        "7. Не копируйте эти инструкции в ответ."
    ),
    "en": (
        "HARD RULES (violations are forbidden):\n"
        "1. Use ONLY the data from the FACTS list above.\n"
        "2. Price, discount percentage, amount, payment terms — if they are "
        "NOT in the facts, do NOT write them at all (no “approximate” "
        "numbers).\n"
        "3. Guarantees, “100% results”, “money back”, “risk free” are "
        "FORBIDDEN unless present in the facts.\n"
        "4. Ratings, stars, review/customer counts, “#1”, “best” are "
        "FORBIDDEN unless present in the facts.\n"
        "5. Certificates, licences, ISO, state approval are FORBIDDEN unless "
        "present in the facts.\n"
        "6. If a detail is missing, write a SQUARE-BRACKET placeholder "
        "([price]) — never invent a number.\n"
        "7. Do not copy these instructions into the answer."
    ),
}

_PROMPT_HEADER: dict[str, str] = {
    "uz": "Sen tajribali SMM kopiraytersan. Quyidagi brief ASOSIDA reklama posti yoz.",
    "ru": "Ты опытный SMM-копирайтер. Напиши рекламный пост строго по брифу ниже.",
    "en": "You are an experienced SMM copywriter. Write the ad post strictly "
          "from the brief below.",
}

_PROMPT_LABELS: dict[str, dict[str, str]] = {
    "product": {"uz": "MAHSULOT/XIZMAT", "ru": "ПРОДУКТ/УСЛУГА", "en": "PRODUCT/SERVICE"},
    "facts": {"uz": "FAKTLAR (yagona ruxsat etilgan manba)",
              "ru": "ФАКТЫ (единственный разрешённый источник)",
              "en": "FACTS (the only allowed source)"},
    "offer": {"uz": "TAKLIF/AKSIYA", "ru": "ОФФЕР/АКЦИЯ", "en": "OFFER/PROMO"},
    "audience": {"uz": "MAQSADLI AUDITORIYA", "ru": "ЦЕЛЕВАЯ АУДИТОРИЯ",
                 "en": "TARGET AUDIENCE"},
    "cta": {"uz": "CTA (harakatga chaqiruv)", "ru": "CTA (призыв к действию)",
            "en": "CTA (call to action)"},
    "link": {"uz": "HAVOLA", "ru": "ССЫЛКА", "en": "LINK"},
    "tone": {"uz": "QO'SHIMCHA OHANG", "ru": "ДОПОЛНИТЕЛЬНЫЙ ТОН",
             "en": "EXTRA TONE NOTE"},
    "format": {"uz": "FORMAT", "ru": "ФОРМАТ", "en": "FORMAT"},
    "task": {"uz": "VAZIFA", "ru": "ЗАДАЧА", "en": "TASK"},
}


def _label(key: str, lang: str) -> str:
    return lang_text(_PROMPT_LABELS.get(key), lang, key.upper())


def build_ad_prompt(brief: AdBrief, fmt: AdFormat, lang: Any = DEFAULT_LANG,
                    *, dna_block: str = "") -> str:
    """Bitta format uchun to'liq prompt (faktlar + taqiqlar + DNA)."""
    code = normalize_lang(lang)
    lines: list[str] = [_PROMPT_HEADER[code], ""]

    if dna_block:
        lines += [dna_block, ""]

    lines.append(f"{_label('product', code)}: {brief.product}")
    facts = brief.fact_lines()
    if facts:
        lines.append(f"{_label('facts', code)}:")
        lines += [f"- {item}" for item in facts]
    else:
        lines.append(f"{_label('facts', code)}: (berilmagan — narx/raqam yozmang)")
    if brief.offer:
        lines.append(f"{_label('offer', code)}: {brief.offer}")
    if brief.audience:
        lines.append(f"{_label('audience', code)}: {brief.audience}")
    lines.append(f"{_label('cta', code)}: {brief.cta or '—'}")
    if brief.link:
        lines.append(f"{_label('link', code)}: {brief.link}")
    if brief.tone_note:
        lines.append(f"{_label('tone', code)}: {brief.tone_note}")
    lines += [
        "",
        f"{_label('format', code)}: {fmt.emoji} {fmt.t_label(code)} — {fmt.t_angle(code)}",
        f"{_label('task', code)}: {fmt.t_instruction(code)}",
        f"MAX: {fmt.max_chars} belgi.",
        "",
        _NO_FABRICATION_RULES[code],
    ]
    return "\n".join(lines)


def build_dna_block(profile: Any, lang: Any = DEFAULT_LANG) -> str:
    """Channel DNA profilidan prompt bloki (fail-soft — bo'sh qaytishi mumkin)."""
    if not isinstance(profile, dict) or not profile:
        return ""
    try:
        from services.channels.dna import build_dna_system_prompt
        block = str(build_dna_system_prompt(profile, lang=normalize_lang(lang)) or "")
        return block.strip()
    except Exception as exc:  # noqa: BLE001 — DNA bo'lmasa generatsiya davom etadi
        logger.debug("build_dna_block xatosi: %s", exc)
        return ""


# ===========================================================================
# 5) DVIGATEL
# ===========================================================================
class AdEngine(SMMFeatureService):
    """4 xil formatdagi reklama generatori (FAZA 15).

    Kvota: butun batch (4 ta AI chaqiruvi) uchun BITTA atomik bron — Phase 2
    standarti. Xatoda bron qaytariladi (fail-closed refund).
    """

    feature = "ads"
    #: ``database.AI_OPERATION_TYPES`` dagi ``magic_post`` asosi + ``:ads`` belgisi.
    quota_operation = "magic_post:ads"
    quota_cost = 1

    #: AI javobidan keyin qo'llanadigan minimal matn hajmi.
    MIN_BODY_CHARS = 40

    # -- public API --------------------------------------------------------
    async def generate(self, user_id: int | None, brief: AdBrief | dict | None,
                       lang: Any = DEFAULT_LANG, *, db_module: Any = None,
                       channel_id: Any = None, formats: Sequence[str] | None = None,
                       dna: Any = None, channel_events: Sequence[dict] | None = None,
                       orchestrator: Any = None) -> AdEngineResult:
        """Brief bo'yicha 4 xil reklama variantini yaratadi.

        Args:
            user_id: foydalanuvchi ID (kvota/IDOR uchun).
            brief: ``AdBrief`` yoki lug'at (``AdBrief.build`` orqali tozalanadi).
            lang: til kodi (uz/ru/en).
            db_module: DB moduli (kvota va Channel DNA uchun; ``None`` → skip).
            channel_id: kanal ID (DNA olish uchun; ownership tekshiriladi).
            formats: kerakli format kalitlari (bo'sh → barcha 4 tasi).
            dna: tayyor DNA profili/``get_channel_dna()`` javobi (ixtiyoriy).
            channel_events: DNA'ni joyida hisoblash uchun post eventlari.
            orchestrator: test/injector uchun AIOrchestrator.
        """
        code = normalize_lang(lang)
        if isinstance(brief, AdBrief):
            item = brief
        elif isinstance(brief, dict):
            allowed = {"product", "facts", "offer", "audience", "cta", "link",
                       "lang", "tone_note", "channel_id"}
            item = AdBrief.build(**{k: v for k, v in brief.items() if k in allowed})
        else:
            item = AdBrief.build(lang=code)
        item.lang = code
        ok, error_code = item.validate()
        base = AdEngineResult(lang=code, brief=item.as_dict())
        if not ok:
            base.error = error_code
            base.error_code = "INVALID_INPUT"
            return base

        if orchestrator is not None:
            self._injected_orchestrator = orchestrator

        ticket = await self.acquire_quota(db_module, user_id)
        if not ticket.allowed:
            base.error = ticket.reason or "quota_denied"
            base.error_code = ("QUOTA_EXCEEDED" if not ticket.reason or ticket.reason in
                               {"insufficient_balance", "user_not_found"}
                               else "QUOTA_UNAVAILABLE")
            base.quota = ticket.as_dict()
            return base

        # --- Channel DNA (native format uchun me'yor) ---------------------
        dna_profile = await self._resolve_dna(dna, channel_events,
                                              channel_id or item.channel_id,
                                              user_id, db_module)
        dna_block = build_dna_block(dna_profile, code)
        base.dna_applied = bool(dna_block)
        if isinstance(dna_profile, dict):
            base.dna_confidence = str(dna_profile.get("confidence") or "")
            base.dna_sample_size = int(dna_profile.get("sample_size") or 0)

        corpus = item.corpus()
        chosen = formats_for(formats)
        variants: list[AdVariant] = []
        removed_all: list[ClaimFinding] = []
        used_providers: list[str] = []
        fatal_code: str | None = None
        fatal_error: str | None = None

        for position, fmt in enumerate(chosen, start=1):
            prompt = build_ad_prompt(item, fmt, code, dna_block=dna_block)
            outcome = await self.ask(
                prompt, user_id=user_id, lang=code,
                context={
                    "smm_mode": "ADS",
                    "smm_topic": clip(item.product, 120),
                    "smm_ads_format": fmt.key,
                    "smm_ads_brief": item.mock_payload(),
                    "channel_id": str(channel_id or item.channel_id or ""),
                    "system_prompt": dna_block,
                },
            )
            if outcome.provider and outcome.provider != "none":
                used_providers.append(outcome.provider)

            body = outcome.text if outcome.usable else ""
            source = "ai"
            removed: list[ClaimFinding] = []
            if body:
                body, removed = self._enforce_no_fabrication(body, corpus, code, fmt)
            if not body:
                body = self._fallback(fmt, item, code)
                source = "fallback"
                body, removed = self._enforce_no_fabrication(body, corpus, code, fmt)
            if not body:
                continue

            if body and any(self._collides(body, other) for other in variants):
                swapped = self._fallback(fmt, item, code)
                swapped, _ = self._enforce_no_fabrication(swapped, corpus, code, fmt)
                if swapped and not any(self._collides(swapped, other)
                                       for other in variants):
                    body, source = swapped, "fallback"

            variants.append(AdVariant(
                index=position, format=fmt.key, emoji=fmt.emoji,
                label=fmt.t_label(code), angle=fmt.t_angle(code),
                content=body, source=source,
                cta=item.cta, link=item.link,
                hashtags=fmt.hashtags,
                removed_claims=tuple(removed),
                max_chars=min(TELEGRAM_TEXT_LIMIT, fmt.max_chars),
            ))
            removed_all.extend(removed)

            if outcome.error_code in {"CANCELLED", "QUEUE_FULL"}:
                fatal_code, fatal_error = outcome.error_code, outcome.error
                break

        if not variants:
            await self.release_quota(ticket)
            base.provider_used = used_providers[0] if used_providers else "none"
            base.error = fatal_error or "generation_failed"
            base.error_code = fatal_code or "GENERATION_FAILED"
            base.quota = ticket.as_dict()
            base.reservation_id = ticket.reservation_id
            base.cost = ticket.cost
            base.refund_issued = True
            return base

        base.success = True
        base.variants = variants
        base.removed_claims = removed_all
        base.provider_used = used_providers[0] if used_providers else "MockFallback"
        base.fallback_used = any(v.source == "fallback" for v in variants)
        base.paid = any(v.source == "ai" for v in variants)
        base.cost = ticket.cost
        base.reservation_id = ticket.reservation_id
        base.quota = ticket.as_dict()
        if not base.paid:
            base.refund_issued = await self.release_quota(ticket)
            if base.refund_issued:
                ticket.cost = 0
                base.cost = 0
        base.chunks = self.render([v.render() for v in variants],
                                  limit=CHUNK_SAFE_LIMIT)
        base.error = fatal_error
        base.error_code = fatal_code
        self._log("reklama variantlari tayyor (user=%s, count=%s, dna=%s)",
                  user_id, len(variants), base.dna_applied)
        return base

    # -- ichki mexanizm ----------------------------------------------------
    async def _resolve_dna(self, dna: Any, events: Sequence[dict] | None,
                           channel_id: Any, user_id: int | None,
                           db_module: Any) -> dict:
        """DNA profilini topadi: tayyor → eventlardan → DB'dan (fail-soft)."""
        if isinstance(dna, dict) and dna:
            profile = dna.get("profile") if isinstance(dna.get("profile"), dict) else dna
            return profile or {}
        if events:
            try:
                from services.channels.dna import compute_channel_dna
                computed = compute_channel_dna(list(events))
                if not computed.get("insufficient"):
                    return computed.get("profile") or {}
                return {}
            except Exception as exc:  # noqa: BLE001
                logger.debug("compute_channel_dna xatosi: %s", exc)
                return {}
        ch_id = str(channel_id or "").strip()
        if not ch_id or db_module is None or db_module is False:
            return {}
        try:
            from services.channels.dna import get_channel_dna
            result = await get_channel_dna(ch_id, user_id, db_module)
        except Exception as exc:  # noqa: BLE001 — DNA bo'lmasa ham reklama bor
            logger.debug("get_channel_dna xatosi: %s", exc)
            return {}
        if not isinstance(result, dict) or not result.get("ok") or result.get("insufficient"):
            return {}
        return result.get("profile") or {}

    @staticmethod
    def _enforce_no_fabrication(body: Any, corpus: str, lang: str,
                                fmt: AdFormat) -> tuple[str, list[ClaimFinding]]:
        """AI javobini fakt-asosida tozalash + sanitizer + hashtag kafolati.

        Qaytadi: ``(toza matn, olib tashlangan da'volar)``. Agar tozalashdan
        keyin matn yaroqsiz bo'lib qolsa — bo'sh satr (chaqiruvchi zaxira
        shablonga o'tadi).
        """
        text = str(body or "").strip()
        if not text:
            return "", []
        text = sanitize_html(text, min(TELEGRAM_TEXT_LIMIT, fmt.max_chars))
        cleaned, removed = strip_unsupported_claims(text, corpus, lang=lang,
                                                    min_severity=SEVERITY_WARNING)
        cleaned = sanitize_html(cleaned, min(TELEGRAM_TEXT_LIMIT, fmt.max_chars))
        plain = strip_html(cleaned).strip()
        if len(plain) < AdEngine.MIN_BODY_CHARS:
            return "", removed
        # Kritik da'vo hali ham qolgan bo'lsa (jumla chegarasi buzilgan) —
        # matn ISHLATILMAYDI: zaxira shablon xavfsizroq.
        if any(f.severity == SEVERITY_CRITICAL
               for f in scan_unsupported_claims(cleaned, corpus, lang=lang)):
            return "", removed
        body_text = ensure_ad_hashtags(cleaned, fmt.hashtags)
        return body_text, removed

    @staticmethod
    def _fallback(fmt: AdFormat, brief: AdBrief, lang: str) -> str:
        """Deterministik (fakt-asosidagi, raqamsiz) zaxira reklama."""
        text = build_ad_text(fmt.key, brief.product, list(brief.facts),
                             offer=brief.offer, audience=brief.audience,
                             cta=brief.cta, link=brief.link, lang=lang)
        return sanitize_html(text, min(TELEGRAM_TEXT_LIMIT, fmt.max_chars))

    @staticmethod
    def _collides(body: str, existing: AdVariant) -> bool:
        """Ikki variant mazmunan bir xilmi (sinonim bo'lishi taqiqlangan)."""
        if fingerprint(body) == fingerprint(existing.content):
            return True
        return same_content(body, existing.content, threshold=0.9)


def ensure_ad_hashtags(text: Any, bank: Sequence[str], minimum: int = 2,
                       maximum: int = 4) -> str:
    """Postda kamida ``minimum`` ta hashtag bo'lishini kafolatlaydi."""
    from services.ai.smm_common import ensure_hashtags, extract_hashtags
    body = str(text or "").strip()
    if len(extract_hashtags(body)) >= minimum:
        return body
    return ensure_hashtags(body, bank, minimum=minimum, maximum=maximum)


#: Modul darajasidagi standart dvigatel.
default_engine = AdEngine()


async def generate_ad_variants(user_id: int | None, brief: AdBrief | dict,
                               lang: Any = DEFAULT_LANG,
                               **kwargs: Any) -> AdEngineResult:
    """Yordamchi: ``AdEngine().generate(...)``."""
    return await AdEngine().generate(user_id, brief, lang, **kwargs)


__all__ = [
    "AD_FORMATS",
    "AD_FORMAT_COUNT",
    "AD_FORMAT_INDEX",
    "AD_FORMAT_KEYS",
    "ALLOWED_LINK_SCHEMES",
    "AdBrief",
    "AdEngine",
    "AdEngineResult",
    "AdFormat",
    "AdVariant",
    "build_ad_prompt",
    "build_dna_block",
    "default_engine",
    "ensure_ad_hashtags",
    "formats_for",
    "generate_ad_variants",
    "is_safe_link",
    "resolve_format",
]
