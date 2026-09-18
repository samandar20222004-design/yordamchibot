"""Model Router — vazifaga qarab model/provayder tanlash (AI ENGINE V2).

DEEP AUDIT (Faza 2): AI chaqiruvlari ikkiga bo'lingan edi — eski modullar
``utils/ai_agent.py`` ga, yangilari ``services/ai/*`` ga murojaat qilardi va
yagona marshrutlash yo'q edi. Bu modul barcha lane'lar uchun YAGONA
marshrutlash qatlamini beradi:

Lane'lar (``Lane``):

    FAST      — oddiy, kechikishka sezgir vazifalar (qayta yozish, oddiy post,
                tuzatish, formatlash, uslub). Maqsad: tezkor javob, PAST
                kechikish. Fast Path: qat'iy umumiy timeout (10-15s) + kesh.
    QUALITY   — sifat talab qiladigan tahlil/audit/javoblar.
    REASONING — chuqur tahlil: kanal tahlili, haftalik kontent-reja, DNA.
    VISION    — rasm tahlili (Gemini Vision).

Router HECH QACHON tarmoqqa chiqmaydi va provayder kodi BILMAYDI — u faqat
kanonik provayder NOMLARI bo'yicha tartib qaytaradi
(:func:`provider_order`). Haqiqiy HTTP ishlari ``services/ai_service.py``
dagi sinovdan o'tgan provayder adapterlarida qoladi (hech narsa noldan
yozilmaydi — yagona shlyuz ularni qayta ishlatadi).

Provayder nomlari ``services/ai_service.py`` kanonik nomlari bilan birxil:
``Gemini, Groq, OpenRouter, Mistral, Cerebras, SambaNova, Cloudflare,
Pollinations``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# ---------------------------------------------------------------------------
# Kanonik provayder nomlari (services/ai_service.py bilan bir xil — yagona
# manba; bu yerda faqat "o'qiydigan" nusxa, o'zgartirish uchun emas).
# ---------------------------------------------------------------------------
PROVIDER_GEMINI = "Gemini"
PROVIDER_GROQ = "Groq"
PROVIDER_OPENROUTER = "OpenRouter"
PROVIDER_MISTRAL = "Mistral"
PROVIDER_CEREBRAS = "Cerebras"
PROVIDER_SAMBANOVA = "SambaNova"
PROVIDER_CLOUDFLARE = "Cloudflare"
PROVIDER_POLLINATIONS = "Pollinations"

#: To'liq chuqur zanjir (oxirgi umumiy qism — har bir lane shu bilan tugaydi).
_DEEP_CHAIN: tuple[str, ...] = (
    PROVIDER_OPENROUTER,
    PROVIDER_MISTRAL,
    PROVIDER_CEREBRAS,
    PROVIDER_SAMBANOVA,
    PROVIDER_CLOUDFLARE,
    PROVIDER_POLLINATIONS,
)


def _with_deep_chain(*preferred: str) -> tuple[str, ...]:
    """Afzal provayderlar + chuqur zanjir (TAKRORSIZ, tartib saqlanadi)."""
    order: list[str] = []
    for name in (*preferred, *_DEEP_CHAIN):
        if name not in order:
            order.append(name)
    return tuple(order)


class Lane(str, Enum):
    """AI vazifa lane'i — qaysi model/provayder sinfi javob beradi."""

    FAST = "FAST"
    QUALITY = "QUALITY"
    REASONING = "REASONING"
    VISION = "VISION"

    @property
    def label(self) -> str:
        return LANE_SPECS[self].label

    @property
    def timeout(self) -> float:
        """Lane standart timeout'i (soniya) — ``gateway`` ishlatadi."""
        return LANE_SPECS[self].default_timeout

    @property
    def default_cache(self) -> bool:
        """Bu lane uchun kesh default holati (FAST = yoqilgan)."""
        return LANE_SPECS[self].cache_by_default

    @property
    def provider_order(self) -> tuple[str, ...]:
        """Bu lane uchun provayderlar tartibi (avto-fallback bilan)."""
        return LANE_SPECS[self].provider_order


@dataclass(frozen=True)
class LaneSpec:
    """Lane tavsifi: qanday vazifa, qaysi provayderlar, qanday chegara."""

    label: str
    description: str
    #: Lane'ga xos provayder tartibi (o'zgarmas). FAST — eng tez provayder
    #: birinchi (past kechikish); QUALITY/REASONING — eng sifatli birinchi.
    provider_order: tuple[str, ...]
    #: Lane standart umumiy timeout'i (soniya).
    default_timeout: float
    #: Javoblar deterministik/keshlanadigan lane (FAST = ha).
    cache_by_default: bool = False
    #: Qisqa tavsif (admin diagnostikasi uchun).
    tags: tuple[str, ...] = field(default_factory=tuple)


LANE_SPECS: dict[Lane, LaneSpec] = {
    # FAST: kalit so'z — kechikish. Groq (Llama) eng tez javob beradi,
    # keyin Gemini, so'ng qolgan zanjir (avto-fallback oxirigacha).
    Lane.FAST: LaneSpec(
        label="FAST",
        description="Oddiy vazifalar: qayta yozish, oddiy post, tuzatish",
        provider_order=_with_deep_chain(PROVIDER_GROQ, PROVIDER_GEMINI),
        default_timeout=12.0,  # Fast Path: qat'iy 10-15s oyna (default 12s)
        cache_by_default=True,
        tags=("low-latency", "cache-first"),
    ),
    # QUALITY: sifat — Gemini 2.5 Flash birinchi (eng yaxshi bepul sifat).
    Lane.QUALITY: LaneSpec(
        label="QUALITY",
        description="Sifatli generatsiya va audit",
        provider_order=_with_deep_chain(PROVIDER_GEMINI, PROVIDER_GROQ),
        default_timeout=25.0,
        tags=("quality-first",),
    ),
    # REASONING: chuqur tahlil — Gemini (katta kontekst) birinchi, keyin
    # OpenRouter (chuqur modellar), keyin qolganlar.
    Lane.REASONING: LaneSpec(
        label="REASONING",
        description="Murakkab tahlil: kanal tahlili, haftalik reja",
        provider_order=_with_deep_chain(
            PROVIDER_GEMINI, PROVIDER_OPENROUTER, PROVIDER_GROQ),
        default_timeout=30.0,
        tags=("deep-analysis", "planning"),
    ),
    # VISION: rasm tahlili — faqat vision-qobiliyatli provayderlar mazmunli
    # (Gemini Vision asosiy). Zanjir baribir saqlanadi (health fallback).
    Lane.VISION: LaneSpec(
        label="VISION",
        description="Rasm tahlili (Gemini Vision)",
        provider_order=_with_deep_chain(PROVIDER_GEMINI),
        default_timeout=25.0,
        tags=("image", "gemini-vision"),
    ),
}

# ---------------------------------------------------------------------------
# Vazifa nomi → Lane (kanonik xarita). ``gateway.generate(task=...)`` va
# handler'lar shu nomlar bilan lane tanlaydi.
# ---------------------------------------------------------------------------
TASK_LANES: dict[str, Lane] = {
    # --- FAST: oddiy, tez javob talab qiladigan vazifalar -------------------
    "rewrite": Lane.FAST,
    "restyle": Lane.FAST,
    "simple_post": Lane.FAST,
    "short_post": Lane.FAST,
    "fix": Lane.FAST,
    "clarify": Lane.FAST,
    "shorten": Lane.FAST,
    "expand": Lane.FAST,
    "format": Lane.FAST,
    "tone": Lane.FAST,
    "faq": Lane.FAST,
    "extract_time": Lane.FAST,
    # --- QUALITY: sifat talab qiladiganlar ----------------------------------
    "audit": Lane.QUALITY,
    "analyze": Lane.QUALITY,
    "post_score": Lane.QUALITY,
    "improve": Lane.QUALITY,
    "variants": Lane.QUALITY,
    "repurpose": Lane.QUALITY,
    # --- REASONING: murakkab/chuqur tahlil ----------------------------------
    "channel_analysis": Lane.REASONING,
    "channel_voice": Lane.REASONING,
    "channel_dna": Lane.REASONING,
    "weekly_plan": Lane.REASONING,
    "content_plan": Lane.REASONING,
    "content_ideas": Lane.REASONING,
    "deep_analysis": Lane.REASONING,
    "best_time": Lane.REASONING,
    "autopilot_plan": Lane.REASONING,
    # --- VISION: rasm tahlili ------------------------------------------------
    "vision": Lane.VISION,
    "image_analysis": Lane.VISION,
    "image_post": Lane.VISION,
    "photo_post": Lane.VISION,
}

#: Prompt ichidan vazifa tushishiga yordam beruvchi yengil kalit so'zlar
#: (auto-rejim uchun; SMM Intent Router bilan BIRGA ishlaydi).
_PROMPT_REASONING_HINTS: tuple[re.Pattern, ...] = (
    re.compile(r"\bhaftalik\s+(?:reja|plan)\b", re.IGNORECASE),
    re.compile(r"\b7\s*kunlik\s+reja\b", re.IGNORECASE),
    re.compile(r"\bkanal(?:im)?\s+(?:tahlil|analitik|ovozi|dna)\b", re.IGNORECASE),
    re.compile(r"\bchuqur\s+tahlil\b", re.IGNORECASE),
    re.compile(r"\bweekly\s+(?:plan|report)\b", re.IGNORECASE),
    re.compile(r"\bchannel\s+analysis\b", re.IGNORECASE),
    re.compile(r"\bнедельн\w+\s+план\b", re.IGNORECASE),
)

_PROMPT_VISION_HINTS: tuple[re.Pattern, ...] = (
    re.compile(r"\brasm\s+(?:tahlil|qara|yubord)\w*", re.IGNORECASE),
    re.compile(r"\bimage\s+(?:analysis|analyze)\b", re.IGNORECASE),
)

_PROMPT_FAST_HINTS: tuple[re.Pattern, ...] = (
    re.compile(r"\bqayta\s+yoz\b", re.IGNORECASE),
    re.compile(r"\bqisqart\b", re.IGNORECASE),
    re.compile(r"\btuzat\b", re.IGNORECASE),
    re.compile(r"\bshorten\b", re.IGNORECASE),
    re.compile(r"\brewrite\b", re.IGNORECASE),
    re.compile(r"\bсократ\w*\b", re.IGNORECASE),
    re.compile(r"\bперепиши\b", re.IGNORECASE),
)


def lane_for_task(task: str | Lane | None) -> Lane | None:
    """Vazifa nomi bo'yicha lane (topilmasa ``None``).

    ``Lane`` uzatilsa — o'zi qaytariladi (idempotent).
    """
    if isinstance(task, Lane):
        return task
    if not task:
        return None
    key = str(task).strip().lower().replace("-", "_").replace(" ", "_")
    lane = TASK_LANES.get(key)
    if lane is not None:
        return lane
    # Kanonik qiymatlardan biri bo'lsa (masalan "fast"/"quality") — o'zi.
    try:
        return Lane(str(task).strip().upper())
    except ValueError:
        return None


def provider_order(lane: Lane | str | None = Lane.QUALITY) -> tuple[str, ...]:
    """Lane uchun kanonik provayderlar tartibi (noma'lum lane → QUALITY)."""
    resolved = lane if isinstance(lane, Lane) else (lane_for_task(lane) or Lane.QUALITY)
    return LANE_SPECS[resolved].provider_order


def resolve_lane(
    task: str | Lane | None = None,
    lane: Lane | str | None = None,
    prompt: str | None = None,
) -> Lane:
    """Yagona marshrutlash qarori.

    Ustuvorlik:
      1. aniq ``lane`` (chaqiruvchi qarori — eng yuqori);
      2. aniq ``task`` (kanonik vazifa nomi);
      3. prompt signallari (vision/reasoning/fast kalit so'zlari);
      4. SMM Intent Router (``services.ai.router``) — yangi qatlam bilan
         sinxron: IMPROVE/SHORTEN/EXPAND/CREATE → FAST, AUDIT → QUALITY,
         IDEAS → REASONING;
      5. hech narsa mos kelmasa — QUALITY (xavfsiz standart).
    """
    explicit = lane if isinstance(lane, Lane) else lane_for_task(lane)
    if explicit is not None:
        return explicit
    by_task = lane_for_task(task)
    if by_task is not None:
        return by_task

    text = str(prompt or "").strip()
    if text:
        for pattern in _PROMPT_VISION_HINTS:
            if pattern.search(text):
                return Lane.VISION
        for pattern in _PROMPT_REASONING_HINTS:
            if pattern.search(text):
                return Lane.REASONING
        for pattern in _PROMPT_FAST_HINTS:
            if pattern.search(text):
                return Lane.FAST
        # SMM Intent Router (yagona manba — services/ai/router.py).
        try:
            from services.ai.router import SMMIntent, detect_intent

            intent = detect_intent(text)
            if intent in (SMMIntent.IMPROVE_POST, SMMIntent.SHORTEN,
                          SMMIntent.EXPAND, SMMIntent.CREATE_POST):
                return Lane.FAST
            if intent is SMMIntent.POST_AUDIT:
                return Lane.QUALITY
            if intent is SMMIntent.CONTENT_IDEAS:
                return Lane.REASONING
        except Exception:  # pragma: no cover — router bo'lmasa ham ishlaydi
            pass
    return Lane.QUALITY


def lane_task_names(lane: Lane | str) -> tuple[str, ...]:
    """Berilgan lane'ga tegishli barcha kanonik vazifa nomlari (diagnostika)."""
    resolved = lane if isinstance(lane, Lane) else (lane_for_task(lane) or Lane.QUALITY)
    return tuple(sorted(name for name, value in TASK_LANES.items() if value is resolved))


__all__ = [
    "Lane",
    "LaneSpec",
    "LANE_SPECS",
    "TASK_LANES",
    "PROVIDER_GEMINI",
    "PROVIDER_GROQ",
    "PROVIDER_OPENROUTER",
    "PROVIDER_MISTRAL",
    "PROVIDER_CEREBRAS",
    "PROVIDER_SAMBANOVA",
    "PROVIDER_CLOUDFLARE",
    "PROVIDER_POLLINATIONS",
    "lane_for_task",
    "lane_task_names",
    "provider_order",
    "resolve_lane",
]
