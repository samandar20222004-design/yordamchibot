"""SMM Intent Router.

Foydalanuvchi murojaatidan SMM intentini aniqlovchi Router:
- CREATE_POST: yangi post yaratish
- IMPROVE_POST: postni yaxshilash/sayqallash
- SHORTEN: postni qisqartirish/ixchamlashtirish
- EXPAND: postni kengaytirish/batafsil yozish
- GENERATE_VARIANTS: bir nechta variantlar yaratish
- POST_AUDIT: postni tahlil qilish va baholash
- CONTENT_IDEAS: kontent g'oyalari va mavzular taklif qilish
- UNKNOWN: aniqlanmagan boshqa murojaatlar
"""

from __future__ import annotations
import re
from enum import Enum


class SMMIntent(str, Enum):
    CREATE_POST = "CREATE_POST"
    IMPROVE_POST = "IMPROVE_POST"
    SHORTEN = "SHORTEN"
    EXPAND = "EXPAND"
    GENERATE_VARIANTS = "GENERATE_VARIANTS"
    POST_AUDIT = "POST_AUDIT"
    CONTENT_IDEAS = "CONTENT_IDEAS"
    UNKNOWN = "UNKNOWN"


# Patternlar: (Intent, regular expressions list)
INTENT_PATTERNS: list[tuple[SMMIntent, list[re.Pattern]]] = [
    (
        SMMIntent.GENERATE_VARIANTS,
        [
            re.compile(r"\b\d+\s*(?:ta|xil)?\s*variant\w*", re.IGNORECASE),
            re.compile(r"\bvariant\w*(?:\s+ber|\s+yoz)?\b", re.IGNORECASE),
            re.compile(r"\b\d+\s*variants?\b", re.IGNORECASE),
            re.compile(r"\b\d+\s*вариант\w*", re.IGNORECASE),
            re.compile(r"\bвариант\w*", re.IGNORECASE),
            re.compile(r"\balternative\w*", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.CONTENT_IDEAS,
        [
            re.compile(r"\bg['’`ʻ]?oya\w*", re.IGNORECASE),
            re.compile(r"\bmavzu\w*\s*(?:ber|kerak|topib|taklif)?\b", re.IGNORECASE),
            re.compile(r"\bnima\s+haqida\s+yoz\w*", re.IGNORECASE),
            re.compile(r"\bcontent\s+ideas?\b", re.IGNORECASE),
            re.compile(r"\bpost\s+ideas?\b", re.IGNORECASE),
            re.compile(r"\bwhat\s+should\s+i\s+post\b", re.IGNORECASE),
            re.compile(r"\bиде[еия]\w*\b", re.IGNORECASE),
            re.compile(r"\bтем[ыа]\w*\s*(?:для\s+)?пост\w*", re.IGNORECASE),
            re.compile(r"\bо\s+чем\s+написать\b", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.POST_AUDIT,
        [
            re.compile(r"\baudit\b", re.IGNORECASE),
            re.compile(r"\btahlil\s*(?:qil|et)?\b", re.IGNORECASE),
            re.compile(r"\bbahola\w*\b", re.IGNORECASE),
            re.compile(r"\btekshir\w*\b", re.IGNORECASE),
            re.compile(r"\banalyze\b", re.IGNORECASE),
            re.compile(r"\bevaluate\b", re.IGNORECASE),
            re.compile(r"\brate\s+(?:this\s+)?post\b", re.IGNORECASE),
            re.compile(r"\bcheck\s+(?:this\s+)?post\b", re.IGNORECASE),
            re.compile(r"\bаудит\b", re.IGNORECASE),
            re.compile(r"\bпроанализируй\b", re.IGNORECASE),
            re.compile(r"\bоцени\s+пост\b", re.IGNORECASE),
            re.compile(r"\bразбор\s+поста\b", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.SHORTEN,
        [
            re.compile(r"\bqisqart\w*\b", re.IGNORECASE),
            re.compile(r"\bqisqa\s*(?:roq)?\s*(?:qilib|yoz|qil)?\b", re.IGNORECASE),
            re.compile(r"\bixcham\w*\b", re.IGNORECASE),
            re.compile(r"\blo['’`ʻ]?nda\b", re.IGNORECASE),
            re.compile(r"\bshorten\b", re.IGNORECASE),
            re.compile(r"\bmake\s+(?:it\s+)?shorter\b", re.IGNORECASE),
            re.compile(r"\bconcise\b", re.IGNORECASE),
            re.compile(r"\bsummarize\b", re.IGNORECASE),
            re.compile(r"\bсократ\w*\b", re.IGNORECASE),
            re.compile(r"\bкороче\b", re.IGNORECASE),
            re.compile(r"\bсделай\s+короче\b", re.IGNORECASE),
            re.compile(r"\bкратко\b", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.EXPAND,
        [
            re.compile(r"\bkengayt\w*\b", re.IGNORECASE),
            re.compile(r"\bbatafsil\w*\b", re.IGNORECASE),
            re.compile(r"\bkattalashtir\w*\b", re.IGNORECASE),
            re.compile(r"\buzunroq\b", re.IGNORECASE),
            re.compile(r"\byoyib\s+yoz\b", re.IGNORECASE),
            re.compile(r"\bexpand\b", re.IGNORECASE),
            re.compile(r"\belaborate\b", re.IGNORECASE),
            re.compile(r"\bmake\s+(?:it\s+)?longer\b", re.IGNORECASE),
            re.compile(r"\bрасшир\w*\b", re.IGNORECASE),
            re.compile(r"\bподробн\w*\b", re.IGNORECASE),
            re.compile(r"\bразверни\b", re.IGNORECASE),
            re.compile(r"\bдлиннее\b", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.IMPROVE_POST,
        [
            re.compile(r"\byaxshila\w*\b", re.IGNORECASE),
            re.compile(r"\bsayqalla\w*\b", re.IGNORECASE),
            re.compile(r"\btuzat\w*\b", re.IGNORECASE),
            re.compile(r"\bchiroyli\s+qilib\b", re.IGNORECASE),
            re.compile(r"\bimprove\b", re.IGNORECASE),
            re.compile(r"\bmake\s+(?:it\s+)?better\b", re.IGNORECASE),
            re.compile(r"\benhance\b", re.IGNORECASE),
            re.compile(r"\brefine\b", re.IGNORECASE),
            re.compile(r"\bулучш\w*\b", re.IGNORECASE),
            re.compile(r"\bдоработай\w*\b", re.IGNORECASE),
            re.compile(r"\bперепиши\s+лучше\b", re.IGNORECASE),
            re.compile(r"\bотредактируй\b", re.IGNORECASE),
        ],
    ),
    (
        SMMIntent.CREATE_POST,
        [
            re.compile(r"\bpost\s+yoz\w*\b", re.IGNORECASE),
            re.compile(r"\bpost\s+yarat\w*\b", re.IGNORECASE),
            re.compile(r"\bpost\s+tayyorla\w*\b", re.IGNORECASE),
            re.compile(r"\bhaqida\s+post\b", re.IGNORECASE),
            re.compile(r"\byozib\s+ber\b", re.IGNORECASE),
            re.compile(r"\bcreate\s+(?:a\s+)?post\b", re.IGNORECASE),
            re.compile(r"\bwrite\s+(?:a\s+)?post\b", re.IGNORECASE),
            re.compile(r"\bdraft\s+(?:a\s+)?post\b", re.IGNORECASE),
            re.compile(r"\bpost\s+about\b", re.IGNORECASE),
            re.compile(r"\bнапиши\s+пост\b", re.IGNORECASE),
            re.compile(r"\bсоздай\s+пост\b", re.IGNORECASE),
            re.compile(r"\bпост\s+(?:про|о|об)\b", re.IGNORECASE),
        ],
    ),
]


class SMMIntentRouter:
    """SMM Intent Router - foydalanuvchi so'rovidan intentni aniqlaydi."""

    @classmethod
    def detect_intent(cls, prompt: str | None) -> SMMIntent:
        """Matndan SMM intentini aniqlaydi."""
        if not prompt or not prompt.strip():
            return SMMIntent.UNKNOWN

        text = prompt.strip()

        # Prioritetli pattern moslashuvini tekshirish
        for intent, patterns in INTENT_PATTERNS:
            for pattern in patterns:
                if pattern.search(text):
                    return intent

        # Agar maxsus kalit so'z topilmasa, lekin reklama/post bilan bog'liq bo'lsa
        lower_text = text.lower()
        if any(w in lower_text for w in ["reklama", "sotuv", "aksiya", "chegirma", "announcement", "реклама", "скидки", "акция"]):
            return SMMIntent.CREATE_POST

        return SMMIntent.UNKNOWN


def detect_intent(prompt: str | None) -> SMMIntent:
    """Convenience helper function for intent routing."""
    return SMMIntentRouter.detect_intent(prompt)
