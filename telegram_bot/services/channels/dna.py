"""🧠 CHANNEL DNA — uslubiy profil (PostAssist V2 — PHASE B, 2-band + FAZA 8,9,22 kengaytma).

Kanalning kuzatilgan postlari (``channel_post_events``) asosida Channel DNA
profili hisoblanadi:

    average_post_length, emoji_level (kam / o'rtacha / ko'p), cta_style,
    formatting_style, sample_size, confidence_score

Kengaytirilgan profil (FAZA 8,9,22):
    language, tone, topics, avg_length, emoji_density, best_hours,
    best_weekdays, high_performing_formats — har bir metrika
    sample_size, confidence (0.0-1.0) va updated_at bilan.

Kafolatlari:
  * Natija ``channel_intelligence_profiles`` va ``channel_dna`` jadvallarida
    saqlanadi (UPSERT);
  * Postlar soni **5 tadan kam** bo'lsa — profil hisoblanmaydi:
    ``confidence='low'`` va ``"Yetarli ma'lumot yo'q (kamida 5 ta post
    kerak)"`` holati qaytadi (soxta raqamlar uydirmaslik);
  * AI orkestrator post generatsiya qilganda (``context`` da ``channel_id``
    bo'lsa va kanal AYNAN shu foydalanuvchining bo'lsa — IDOR himoyasi) DNA
    ixcham system-prompt bloki sifatida ulanadi;
  * Barcha hisob funksiyalari PURE (DB'siz) — deterministik va testlanadi.
  * Kichik sample_size da PAST confidence (0.0-1.0) — soxta yuqori confidence yo'q!
"""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

#: DNA hisoblash uchun minimal post soni.
MIN_POSTS_FOR_DNA = 5

#: Yetarli ma'lumot bo'lmaganda qaytariladigan qat'iy xabar (uz).
INSUFFICIENT_DATA_MESSAGE = "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)"


# ---------------------------------------------------------------------------
# Hisoblash (PURE funksiya — deterministik) — LEGACY
# ---------------------------------------------------------------------------
def classify_emoji_level(average_density: float) -> str:
    """O'rtacha emoji zichligidan emoji darajasi: ``low``/``medium``/``high``.

    (kuzatuvlarga mos: ~450 belgili o'rtacha postda 4-6 ta emoji — "o'rtacha".)
    """
    d = float(average_density or 0.0)
    if d < 0.004:
        return "low"
    if d < 0.012:
        return "medium"
    return "high"


def classify_cta_style(events: list[dict]) -> str:
    """CTA aniqlanish tezkorligi: ``always``/``most``/``sometimes``/``none``."""
    events = [e for e in (events or []) if isinstance(e, dict)]
    n = len(events)
    if n == 0:
        return "none"
    cta = sum(1 for e in events if e.get("cta_detected"))
    if cta == 0:
        return "none"
    if cta == n:
        return "always"
    if cta / n >= 0.5:
        return "most"
    return "sometimes"


def classify_formatting_style(events: list[dict], avg_length: int) -> str:
    """Media ulushi + uzunlik bo'yicha format uslubi.

    ``media_rich`` (rasmli) / ``long_form`` / ``short`` / ``balanced``.
    """
    events = [e for e in (events or []) if isinstance(e, dict)]
    n = len(events)
    if n == 0:
        return "balanced"
    media_ratio = sum(1 for e in events if e.get("has_media")) / n
    if media_ratio >= 0.5:
        return "media_rich"
    if avg_length >= 400:
        return "long_form"
    if avg_length <= 120:
        return "short"
    return "balanced"


def confidence_from_sample(sample_size: int) -> int:
    """Namuna hajmiga qarab ishonchlilik balli (0..100)."""
    n = int(sample_size or 0)
    if n >= 20:
        return 90
    if n >= 10:
        return 70
    return 50  # 5..9


def _confidence_level(sample_size: int) -> str:
    n = int(sample_size or 0)
    if n < MIN_POSTS_FOR_DNA:
        return "low"
    if n < 10:
        return "low"
    if n < 20:
        return "medium"
    return "high"


def compute_channel_dna(events: list[dict]) -> dict:
    """Eventlar ro'yxatidan Channel DNA profilini hisoblaydi (PURE).

    Qaytadi (yetarli ma'lumotda)::

        {"insufficient": False, "confidence": "medium",
         "confidence_score": 70, "sample_size": 12, "message": None,
         "profile": {"average_post_length": 450, "emoji_level": "medium",
                     "cta_style": "always", "formatting_style": "media_rich",
                     "sample_size": 12, "confidence_score": 70}}

    Kam ma'lumotda (``< 5`` post) soxta raqamlar UYDIRILMAYDI::

        {"insufficient": True, "confidence": "low", "confidence_score": 0,
         "sample_size": 3, "message": "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)",
         "profile": None}
    """
    events = [e for e in (events or []) if isinstance(e, dict)]
    n = len(events)
    if n < MIN_POSTS_FOR_DNA:
        return {
            "insufficient": True,
            "confidence": "low",
            "confidence_score": 0,
            "sample_size": n,
            "message": INSUFFICIENT_DATA_MESSAGE,
            "profile": None,
        }

    lengths = [max(0, int(e.get("length") or 0)) for e in events]
    avg_length = int(round(sum(lengths) / n))
    densities = [max(0.0, float(e.get("emoji_density") or 0.0)) for e in events]
    avg_density = sum(densities) / n

    profile = {
        "average_post_length": avg_length,
        "emoji_level": classify_emoji_level(avg_density),
        "cta_style": classify_cta_style(events),
        "formatting_style": classify_formatting_style(events, avg_length),
        "sample_size": n,
        "confidence_score": confidence_from_sample(n),
    }
    return {
        "insufficient": False,
        "confidence": _confidence_level(n),
        "confidence_score": profile["confidence_score"],
        "sample_size": n,
        "message": None,
        "profile": profile,
    }


# ---------------------------------------------------------------------------
# FAZA 8,9,22 — KENGAYTIRILGAN CHANNEL DNA
# Har bir metrika: sample_size, confidence (0.0-1.0), updated_at
# ---------------------------------------------------------------------------

def confidence_float(sample_size: int) -> float:
    """Namuna hajmiga qarab ishonchlilik (0.0-1.0) — soxta yuqori confidence yo'q!

    Qat'iy qoida:
      * <5  -> 0.0 (yetarli emas)
      * 5-9 -> 0.25-0.49 (past)
      * 10-19 -> 0.55-0.73 (o'rtacha-past)
      * 20-49 -> 0.75-0.90 (o'rtacha-yuqori)
      * 50+ -> 0.92-0.95 (yuqori, lekin 1.0 emas — hech qachon soxta 100% yo'q)
    """
    n = int(sample_size or 0)
    if n < MIN_POSTS_FOR_DNA:
        return 0.0
    if n < 10:
        # 5 -> 0.25, 9 -> 0.49
        return round(0.25 + (n - 5) * 0.06, 3)
    if n < 20:
        # 10 -> 0.55, 19 -> 0.73
        return round(0.55 + (n - 10) * 0.02, 3)
    if n < 50:
        # 20 -> 0.75, 49 -> ~0.895
        return round(0.75 + (n - 20) * 0.005, 3)
    if n < 100:
        return 0.92
    return 0.95


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrap_metric(value: Any, sample_size: int, confidence: float | None = None, updated_at: str | None = None) -> dict:
    """Har bir metrika uchun standart o'ram: value, sample_size, confidence, updated_at."""
    n = int(sample_size or 0)
    conf = float(confidence) if confidence is not None else confidence_float(n)
    # Clamp 0.0-1.0
    conf = max(0.0, min(1.0, conf))
    # Kichik sample da yuqori confidence taqiqlanadi
    if n < 5 and conf > 0.0:
        conf = 0.0
    if n < 10 and conf > 0.55:
        conf = min(conf, 0.49)
    return {
        "value": value,
        "sample_size": n,
        "confidence": round(conf, 3),
        "updated_at": updated_at or _now_iso(),
    }


# ---- Til aniqlash (yengil, AI'siz) ----
_UZ_KEYWORDS = (
    " va ", " bilan ", " uchun ", " bo'lib ", " emas ", " bo'ldi ", " qildi ",
    " juda ", " ham ", " shu ", " bu ", " agar ", " lekin ", " chunki ",
    " o'zbek", " o‘zbek", " g'alla", " yangilik", " bugun", " ertaga",
)
_EN_KEYWORDS = (
    " the ", " and ", " you ", " for ", " with ", " this ", " that ",
    " is ", " are ", " to ", " of ", " in ", " on ",
)
_CYRILLIC_RE = re.compile(r"[а-яА-ЯёЁ]")

def detect_language(text: str) -> str | None:
    """Matndan tilni yengil aniqlash (AI'siz): uz/ru/en."""
    if not text or not isinstance(text, str):
        return None
    if _CYRILLIC_RE.search(text):
        return "ru"
    lowered = f" {text.lower()} "
    # Uzbek specific chars
    if any(ch in lowered for ch in ["oʻ", "gʻ", "o‘", "g‘", "o'", "g'"]):
        # Could still be English with apostrophe, check uz keywords
        if any(kw in lowered for kw in _UZ_KEYWORDS):
            return "uz"
    if any(kw in lowered for kw in _UZ_KEYWORDS):
        return "uz"
    if any(kw in lowered for kw in _EN_KEYWORDS):
        return "en"
    # Default for this bot context — uz
    return "uz"


def detect_language_from_events(events: list[dict]) -> tuple[str, int, Counter]:
    """Eventlardan tilni aniqlash: majority vote. Returns (lang, sample_size, counter)."""
    events = [e for e in (events or []) if isinstance(e, dict)]
    counter: Counter = Counter()
    for e in events:
        lang = e.get("language")
        if lang in ("uz", "ru", "en"):
            counter[lang] += 1
            continue
        txt = e.get("text") or e.get("content") or ""
        if txt:
            dl = detect_language(str(txt))
            if dl:
                counter[dl] += 1
    if not counter:
        return "uz", 0, counter
    most_common = counter.most_common(1)[0][0]
    return most_common, sum(counter.values()), counter


def classify_tone_extended(events: list[dict], avg_emoji_density: float, cta_ratio: float, avg_length: int) -> str:
    """Kengaytirilgan ohang tasnifi (AI'siz, yengil)."""
    d = float(avg_emoji_density or 0.0)
    cr = float(cta_ratio or 0.0)
    l = int(avg_length or 0)
    # Friendly if high emoji
    if d >= 0.012:
        return "friendly"
    if d >= 0.008 and cr < 0.3:
        return "friendly"
    if cr >= 0.6:
        return "promotional"
    if l >= 500:
        return "informative"
    if l <= 120:
        return "casual"
    # Check for formal markers in texts
    formal_markers = ("hurmatli", "iltimos", "rasmiy", "уважаемые", "пожалуйста", "dear", "please")
    for e in events:
        txt = (e.get("text") or e.get("content") or "").lower()
        if any(m in txt for m in formal_markers):
            return "formal"
    return "neutral"


def extract_topics(events: list[dict], top_n: int = 5) -> tuple[list[str], int]:
    """Mavzularni yengil ajratish: topics maydoni yoki matndan kalit so'zlar."""
    events = [e for e in (events or []) if isinstance(e, dict)]
    topic_counter: Counter = Counter()
    sample = 0
    # If events have explicit topics list
    for e in events:
        topics = e.get("topics") or e.get("top_topics") or e.get("topic")
        if isinstance(topics, (list, tuple, set)):
            for t in topics:
                t_clean = str(t).strip().lower()[:64]
                if t_clean and len(t_clean) > 2:
                    topic_counter[t_clean] += 1
            sample += 1
        elif isinstance(topics, str) and topics.strip():
            t_clean = topics.strip().lower()[:64]
            if t_clean:
                topic_counter[t_clean] += 1
                sample += 1

    # If no explicit topics, extract keywords from text
    if not topic_counter:
        stopwords = {
            "va", "bilan", "uchun", "bu", "shu", "ham", "emas", "edi", "bo'lib",
            "the", "and", "for", "with", "this", "that", "you", "are", "is",
            "и", "в", "на", "с", "что", "это", "как", "для", "по",
        }
        for e in events:
            txt = e.get("text") or e.get("content") or ""
            if not txt:
                continue
            # Simple tokenization: split by non-alphanum, keep >3 chars
            tokens = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9oʻgʻo‘g‘']{3,}", str(txt).lower())
            for tok in tokens:
                if tok in stopwords or len(tok) < 3:
                    continue
                # Trim to 32 chars
                topic_counter[tok[:32]] += 1
            sample += 1

    if not topic_counter:
        return [], 0
    top = [t for t, _ in topic_counter.most_common(top_n)]
    return top, sample


def _valid_hour(value: Any) -> int | None:
    try:
        h = int(value)
    except (TypeError, ValueError):
        return None
    return h if 0 <= h <= 23 else None


def _valid_weekday(value: Any) -> int | None:
    try:
        d = int(value)
    except (TypeError, ValueError):
        return None
    return d if 0 <= d <= 6 else None


def compute_best_hours(events: list[dict], top_n: int = 3) -> tuple[list[int], int, dict]:
    """Eng yaxshi soatlar: post_hour bo'yicha top N."""
    counter: Counter = Counter()
    valid = 0
    for e in events:
        h = _valid_hour(e.get("post_hour"))
        if h is not None:
            counter[h] += 1
            valid += 1
    if not counter:
        return [], 0, {}
    top_hours = [h for h, _ in counter.most_common(top_n)]
    return top_hours, valid, dict(counter)


def compute_best_weekdays(events: list[dict], top_n: int = 3) -> tuple[list[int], int, dict]:
    """Eng yaxshi hafta kunlari: post_weekday bo'yicha top N (0=Dushanba)."""
    counter: Counter = Counter()
    valid = 0
    for e in events:
        d = _valid_weekday(e.get("post_weekday"))
        if d is not None:
            counter[d] += 1
            valid += 1
    if not counter:
        return [], 0, {}
    top_days = [d for d, _ in counter.most_common(top_n)]
    return top_days, valid, dict(counter)


def compute_high_performing_formats(events: list[dict], top_n: int = 3) -> tuple[list[str], int, dict]:
    """Yuqori ko'rsatkichli formatlar: media_type / has_media bo'yicha."""
    counter: Counter = Counter()
    for e in events:
        mt = e.get("media_type")
        has_media = e.get("has_media")
        if mt and isinstance(mt, str):
            # Normalize: photo, video, etc.
            fmt = mt.strip().lower()[:32]
            if fmt:
                counter[fmt] += 1
            else:
                counter["text"] += 1
        elif has_media:
            counter["media"] += 1
        else:
            # Check formatting_style if present
            fmt = e.get("formatting_style")
            if fmt:
                counter[str(fmt).lower()[:32]] += 1
            else:
                # Length based
                length = int(e.get("length") or 0)
                if length >= 400:
                    counter["long_form"] += 1
                elif length <= 120:
                    counter["short"] += 1
                else:
                    counter["text"] += 1
    if not counter:
        return [], 0, {}
    top_formats = [f for f, _ in counter.most_common(top_n)]
    return top_formats, len(events), dict(counter)


def compute_channel_dna_extended(events: list[dict], now: str | None = None) -> dict:
    """Kengaytirilgan Channel DNA (FAZA 8,9,22) — PURE, deterministik, AI'siz.

    Har bir metrika: value, sample_size, confidence (0.0-1.0), updated_at.

    Asosiy parametrlar:
      - language, tone, topics, avg_length, emoji_density,
        best_hours, best_weekdays, high_performing_formats.

    Qaytadi::

        {
          "insufficient": False,
          "sample_size": 20,
          "confidence": 0.75,
          "confidence_score": 75,
          "message": None,
          "profile": {
            "language": {"value": "uz", "sample_size": 20, "confidence": 0.75, "updated_at": "..."},
            "tone": {...},
            ...
            # Legacy for backward compat:
            "average_post_length": 350,
            "emoji_level": "medium",
            ...
          },
          "metrics": {... same as profile but structured ...},
          "overall": {"sample_size": 20, "confidence": 0.75, "updated_at": "..."}
        }

    Kam ma'lumotda (<5) insufficient=True, confidence=0.0, profile=None emas,
    balki past confidence bilan metrikalar ham qaytadi (soxta yuqori confidence yo'q).
    """
    events = [e for e in (events or []) if isinstance(e, dict)]
    n = len(events)
    updated_at = now or _now_iso()

    if n < MIN_POSTS_FOR_DNA:
        # Still compute lightweight metrics but with 0.0 confidence
        lang, lang_sample, lang_counter = detect_language_from_events(events)
        # For insufficient, metrics exist but low confidence
        metrics = {
            "language": _wrap_metric(lang, lang_sample or n, confidence=0.0, updated_at=updated_at),
            "tone": _wrap_metric("neutral", n, confidence=0.0, updated_at=updated_at),
            "topics": _wrap_metric([], 0, confidence=0.0, updated_at=updated_at),
            "avg_length": _wrap_metric(0, n, confidence=0.0, updated_at=updated_at),
            "emoji_density": _wrap_metric(0.0, n, confidence=0.0, updated_at=updated_at),
            "best_hours": _wrap_metric([], 0, confidence=0.0, updated_at=updated_at),
            "best_weekdays": _wrap_metric([], 0, confidence=0.0, updated_at=updated_at),
            "high_performing_formats": _wrap_metric([], 0, confidence=0.0, updated_at=updated_at),
        }
        return {
            "insufficient": True,
            "sample_size": n,
            "confidence": 0.0,
            "confidence_score": 0,
            "confidence_level": "low",
            "message": INSUFFICIENT_DATA_MESSAGE,
            "profile": None,
            "metrics": metrics,
            "overall": _wrap_metric(None, n, confidence=0.0, updated_at=updated_at),
        }

    # Sufficient data — compute all
    lengths = [max(0, int(e.get("length") or 0)) for e in events]
    avg_length = int(round(sum(lengths) / n)) if lengths else 0
    densities = [max(0.0, float(e.get("emoji_density") or 0.0)) for e in events]
    avg_density = sum(densities) / n if densities else 0.0
    cta_count = sum(1 for e in events if e.get("cta_detected"))
    cta_ratio = cta_count / n if n else 0.0

    lang, lang_sample, lang_counter = detect_language_from_events(events)
    tone = classify_tone_extended(events, avg_density, cta_ratio, avg_length)
    topics, topics_sample = extract_topics(events, top_n=5)
    best_hours, hours_sample, hours_dist = compute_best_hours(events, top_n=3)
    best_weekdays, weekdays_sample, weekdays_dist = compute_best_weekdays(events, top_n=3)
    high_formats, formats_sample, formats_dist = compute_high_performing_formats(events, top_n=3)

    overall_conf = confidence_float(n)

    # Per-metric confidence based on its own sample size
    metrics = {
        "language": _wrap_metric(lang, lang_sample or n, updated_at=updated_at),
        "tone": _wrap_metric(tone, n, updated_at=updated_at),
        "topics": _wrap_metric(topics, topics_sample or n, updated_at=updated_at),
        "avg_length": _wrap_metric(avg_length, n, updated_at=updated_at),
        "emoji_density": _wrap_metric(round(avg_density, 6), n, updated_at=updated_at),
        "best_hours": _wrap_metric(best_hours, hours_sample, updated_at=updated_at),
        "best_weekdays": _wrap_metric(best_weekdays, weekdays_sample, updated_at=updated_at),
        "high_performing_formats": _wrap_metric(high_formats, formats_sample, updated_at=updated_at),
    }

    # Legacy fields for backward compatibility
    legacy_profile = {
        "average_post_length": avg_length,
        "avg_length": avg_length,
        "emoji_level": classify_emoji_level(avg_density),
        "emoji_density": round(avg_density, 6),
        "cta_style": classify_cta_style(events),
        "formatting_style": classify_formatting_style(events, avg_length),
        "sample_size": n,
        "confidence_score": int(overall_conf * 100),
        "confidence": overall_conf,
    }

    # Extended profile merges legacy + wrapped metrics + raw values for convenience
    profile = {
        **legacy_profile,
        "language": metrics["language"],
        "tone": metrics["tone"],
        "topics": metrics["topics"],
        "avg_length": metrics["avg_length"],
        "emoji_density": metrics["emoji_density"],
        "best_hours": metrics["best_hours"],
        "best_weekdays": metrics["best_weekdays"],
        "high_performing_formats": metrics["high_performing_formats"],
        # Also provide raw values for easy access
        "language_value": lang,
        "tone_value": tone,
        "topics_value": topics,
        "avg_length_value": avg_length,
        "emoji_density_value": round(avg_density, 6),
        "best_hours_value": best_hours,
        "best_weekdays_value": best_weekdays,
        "high_performing_formats_value": high_formats,
        "hours_distribution": hours_dist,
        "weekdays_distribution": weekdays_dist,
        "formats_distribution": formats_dist,
        "language_counter": dict(lang_counter),
    }

    return {
        "insufficient": False,
        "sample_size": n,
        "confidence": overall_conf,
        "confidence_score": int(overall_conf * 100),
        "confidence_level": _confidence_level(n),
        "message": None,
        "profile": profile,
        "metrics": metrics,
        "overall": _wrap_metric(None, n, confidence=overall_conf, updated_at=updated_at),
    }


# Alias for v2
compute_channel_dna_v2 = compute_channel_dna_extended
compute_dna = compute_channel_dna_extended


# ---------------------------------------------------------------------------
# UI / prompt yorliqlari (uz / ru / en) — LEGACY + EXTENDED
# ---------------------------------------------------------------------------
DNA_LABELS = {
    "uz": {
        "emoji_level": {"low": "kam", "medium": "o'rtacha", "high": "ko'p"},
        "cta_style": {
            "always": "har postda CTA",
            "most": "ko'p postlarda CTA",
            "sometimes": "ba'zi postlarda CTA",
            "none": "CTA yo'q",
        },
        "formatting_style": {
            "media_rich": "rasm bilan",
            "long_form": "uzun matn",
            "short": "qisqa matn",
            "balanced": "o'rtacha matn",
        },
        "confidence": {"low": "past", "medium": "o'rtacha", "high": "yuqori"},
    },
    "ru": {
        "emoji_level": {"low": "мало", "medium": "средне", "high": "много"},
        "cta_style": {
            "always": "CTA в каждом посте",
            "most": "CTA в большинстве постов",
            "sometimes": "CTA в некоторых постах",
            "none": "CTA нет",
        },
        "formatting_style": {
            "media_rich": "с фото",
            "long_form": "длинный текст",
            "short": "короткий текст",
            "balanced": "средний текст",
        },
        "confidence": {"low": "низкая", "medium": "средняя", "high": "высокая"},
    },
    "en": {
        "emoji_level": {"low": "low", "medium": "medium", "high": "high"},
        "cta_style": {
            "always": "CTA in every post",
            "most": "CTA in most posts",
            "sometimes": "CTA in some posts",
            "none": "no CTA",
        },
        "formatting_style": {
            "media_rich": "with media",
            "long_form": "long-form text",
            "short": "short text",
            "balanced": "balanced text",
        },
        "confidence": {"low": "low", "medium": "medium", "high": "high"},
    },
}


def dna_labels(lang: str = "uz") -> dict:
    """Tilga mos DNA yorliqlari (noma'lum til → uz)."""
    from locales.translations import normalize_lang
    try:
        code = normalize_lang(lang)
    except Exception:
        code = "uz"
    return DNA_LABELS.get(code) or DNA_LABELS["uz"]


def label_for(kind: str, value: str, lang: str = "uz") -> str:
    """``emoji_level``/``cta_style``/``formatting_style``/``confidence``
    qiymatining tilga mos ko'rinishi (noma'lum qiymat → qisqa qiymat o'zi)."""
    labels = dna_labels(lang)
    table = labels.get(kind) or {}
    return table.get(str(value or ""), str(value or "—"))


# ---------------------------------------------------------------------------
# AI system-prompt bloki (ixcham ko'rinish) — LEGACY + EXTENDED
# ---------------------------------------------------------------------------
_DNA_PROMPT_TEMPLATES = {
    "uz": (
        "KANAL USLUBI (DNA): o'rtacha uzunlik ~{length} belgi; emoji: {emoji}; "
        "CTA: {cta}; format: {fmt}. Yangi postni AYNAN shu uslubda, o'xshash "
        "uzunlikda yoz; emoji zichligi va CTA uslubini saqla."
    ),
    "ru": (
        "СТИЛЬ КАНАЛА (DNA): средняя длина ~{length} символов; эмодзи: {emoji}; "
        "CTA: {cta}; формат: {fmt}. Пиши новый пост в этом стиле, похожей длины; "
        "сохраняй плотность эмодзи и стиль CTA."
    ),
    "en": (
        "CHANNEL STYLE (DNA): avg length ~{length} chars; emoji: {emoji}; "
        "CTA: {cta}; format: {fmt}. Write the new post in this style with a "
        "similar length; keep emoji density and CTA style."
    ),
}

_DNA_PROMPT_TEMPLATES_V2 = {
    "uz": (
        "KANAL DNA (kengaytirilgan): til={lang}, ohang={tone}, o'rtacha uzunlik ~{length} belgi, "
        "emoji zichligi={emoji_density}, mavzular={topics}, eng yaxshi soatlar={hours}, "
        "hafta kunlari={weekdays}, formatlar={formats}. "
        "Yangi postni AYNAN shu DNA asosida yoz."
    ),
    "ru": (
        "ДНК КАНАЛА (расширенная): язык={lang}, тон={tone}, средняя длина ~{length} симв., "
        "плотность эмодзи={emoji_density}, темы={topics}, лучшее время={hours}, "
        "дни недели={weekdays}, форматы={formats}. Пиши новый пост в этом стиле."
    ),
    "en": (
        "CHANNEL DNA (extended): lang={lang}, tone={tone}, avg length ~{length} chars, "
        "emoji density={emoji_density}, topics={topics}, best hours={hours}, "
        "weekdays={weekdays}, formats={formats}. Write new post in this DNA."
    ),
}


def build_dna_system_prompt(profile: dict, lang: str = "uz") -> str:
    """Saqlangan DNA profilidan ixcham system-prompt bloki.

    Profil bo'sh/kam ma'lumotda bo'sh qaytadi (soxta uslub uydirmaslik).
    Kengaytirilgan profilni ham, eski profilni ham qo'llab-quvvatlaydi.
    """
    if not isinstance(profile, dict) or not profile:
        return ""
    try:
        from locales.translations import normalize_lang
        code = normalize_lang(lang)
    except Exception:
        code = "uz"
    if code not in _DNA_PROMPT_TEMPLATES:
        code = "uz"
    sample = profile.get("sample_size")
    # Support wrapped metric
    if isinstance(sample, dict):
        sample = sample.get("value") or sample.get("sample_size")
    if sample is None:
        # Check nested metrics
        overall = profile.get("overall")
        if isinstance(overall, dict):
            sample = overall.get("sample_size")
        else:
            # Try to get from any metric
            for k in ("avg_length", "language"):
                v = profile.get(k)
                if isinstance(v, dict) and "sample_size" in v:
                    sample = v["sample_size"]
                    break
    if sample is None or int(sample) < MIN_POSTS_FOR_DNA:
        return ""
    length = profile.get("average_post_length")
    if length is None:
        # Try wrapped
        al = profile.get("avg_length")
        if isinstance(al, dict):
            length = al.get("value")
        else:
            length = profile.get("avg_length_value")
    if length is None:
        return ""
    labels = DNA_LABELS[code]

    # Legacy path
    if "emoji_level" in profile or "cta_style" in profile:
        return _DNA_PROMPT_TEMPLATES[code].format(
            length=int(length),
            emoji=labels["emoji_level"].get(str(profile.get("emoji_level") or ""), "medium"),
            cta=labels["cta_style"].get(str(profile.get("cta_style") or ""), "sometimes"),
            fmt=labels["formatting_style"].get(str(profile.get("formatting_style") or ""), "balanced"),
        )
    # Extended path — try to build richer prompt if extended fields available
    try:
        lang_val = profile.get("language_value") or (profile.get("language", {}).get("value") if isinstance(profile.get("language"), dict) else "uz")
        tone_val = profile.get("tone_value") or (profile.get("tone", {}).get("value") if isinstance(profile.get("tone"), dict) else "neutral")
        topics_val = profile.get("topics_value") or (profile.get("topics", {}).get("value") if isinstance(profile.get("topics"), dict) else [])
        hours_val = profile.get("best_hours_value") or (profile.get("best_hours", {}).get("value") if isinstance(profile.get("best_hours"), dict) else [])
        weekdays_val = profile.get("best_weekdays_value") or (profile.get("best_weekdays", {}).get("value") if isinstance(profile.get("best_weekdays"), dict) else [])
        formats_val = profile.get("high_performing_formats_value") or (profile.get("high_performing_formats", {}).get("value") if isinstance(profile.get("high_performing_formats"), dict) else [])
        emoji_dens = profile.get("emoji_density_value")
        if emoji_dens is None:
            ed = profile.get("emoji_density")
            if isinstance(ed, dict):
                emoji_dens = ed.get("value")
            else:
                emoji_dens = ed
        if lang_val and tone_val is not None:
            return _DNA_PROMPT_TEMPLATES_V2[code].format(
                lang=lang_val,
                tone=tone_val,
                length=int(length),
                emoji_density=emoji_dens or 0.0,
                topics=", ".join(topics_val[:3]) if topics_val else "—",
                hours=", ".join(str(h) for h in hours_val[:3]) if hours_val else "—",
                weekdays=", ".join(str(d) for d in weekdays_val[:3]) if weekdays_val else "—",
                formats=", ".join(formats_val[:3]) if formats_val else "—",
            )
    except Exception:
        pass
    # Fallback to legacy template
    return _DNA_PROMPT_TEMPLATES[code].format(
        length=int(length),
        emoji=labels["emoji_level"].get(str(profile.get("emoji_level") or ""), "medium"),
        cta=labels["cta_style"].get(str(profile.get("cta_style") or ""), "sometimes"),
        fmt=labels["formatting_style"].get(str(profile.get("formatting_style") or ""), "balanced"),
    )


def build_dna_system_prompt_extended(profile: dict, lang: str = "uz") -> str:
    """Kengaytirilgan DNA dan boy prompt (FAZA 8,9,22)."""
    return build_dna_system_prompt(profile, lang=lang)


# ---------------------------------------------------------------------------
# DB + ownership bilan asinxron xizmatlar — LEGACY + EXTENDED
# ---------------------------------------------------------------------------
def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    """``run_db`` (thread) orqali yoki to'g'ridan-to'g'ri chaqiradi."""
    run_db = getattr(db, "run_db", None)
    if run_db is not None:
        return await run_db(fn, *args, **kwargs)
    return fn(*args, **kwargs)


def is_channel_owner(db: Any, user_id: int, channel_id: str) -> bool:
    """Kanal AYNAN shu foydalanuvchiga tegishlimi (fail-closed).

    Kanal yo'q, DB xato yoki user_id mos kelmasa — ``False``.
    """
    if user_id is None or not channel_id:
        return False
    try:
        owner = db.get_channel_owner_id(channel_id)
    except Exception:
        return False
    if owner is None:
        return False
    try:
        return int(owner) == int(user_id)
    except (TypeError, ValueError):
        return False


async def get_channel_dna(
    channel_id: str | int,
    user_id: int | None = None,
    db_module: Any = None,
) -> dict:
    """Kanal DNA profilini hisoblaydi, saqlaydi va qaytaradi.

    RBAC/IDOR: ``user_id`` berilganda kanal egasi AYNAN shu foydalanuvchi
    bo'lishi shart — aks holda ``FORBIDDEN`` (boshqa birovning kanal DNA
    ma'lumotlarini ko'rish QAT'IYAN MAN etiladi).

    Qaytadi:
      * ``{"ok": False, "error_code": "FORBIDDEN" | ...}`` — himoya/xato;
      * ``{"ok": True, "insufficient": True, "confidence": "low",
         "message": "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)", ...}``
        — kam post (``< 5``);
      * ``{"ok": True, "insufficient": False, "profile": {...},
         "confidence": "low"|"medium"|"high", "confidence_score": N, ...}``
        — to'liq profil.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL",
                "message": "Kanal ID bo'sh"}
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_post_events"):
        return {"ok": False, "error_code": "DB_UNAVAILABLE",
                "message": "Baza mavjud emas"}

    # --- RBAC/IDOR himoyasi (fail-closed) ---
    if user_id is not None:
        try:
            owner = await _db_call(db, db.get_channel_owner_id, ch_id)
        except Exception:
            owner = None
        try:
            owned = owner is not None and int(owner) == int(user_id)
        except (TypeError, ValueError):
            owned = False
        if not owned:
            return {
                "ok": False,
                "error_code": "FORBIDDEN",
                "channel_id": ch_id,
                "message": "Bu kanal sizga tegishli emas — DNA ma'lumotlari "
                           "faqat kanal egasiga ochiladi.",
            }

    events = await _db_call(db, db.get_channel_post_events, ch_id, 500)
    result = compute_channel_dna(events)

    if result["insufficient"]:
        return {
            "ok": True,
            "insufficient": True,
            "channel_id": ch_id,
            "confidence": "low",
            "confidence_score": 0,
            "sample_size": result["sample_size"],
            "message": result["message"],
            "profile": None,
            "saved": False,
        }

    profile = result["profile"]
    saved = False
    try:
        await _db_call(
            db, db.save_channel_intelligence_profile, ch_id,
            avg_post_length=profile["average_post_length"],
            emoji_level=profile["emoji_level"],
            cta_style=profile["cta_style"],
            formatting_style=profile["formatting_style"],
            confidence=profile["confidence_score"],
            sample_size=profile["sample_size"],
        )
        saved = True
    except Exception as e:
        logger.warning("Channel DNA saqlashda xato (%s): %s", ch_id, e)

    return {
        "ok": True,
        "insufficient": False,
        "channel_id": ch_id,
        "confidence": result["confidence"],
        "confidence_score": profile["confidence_score"],
        "sample_size": result["sample_size"],
        "message": None,
        "profile": profile,
        "saved": saved,
    }


async def get_channel_dna_extended(
    channel_id: str | int,
    user_id: int | None = None,
    db_module: Any = None,
) -> dict:
    """Kengaytirilgan Channel DNA (FAZA 8,9,22) — batch agregatsiya.

    RBAC/IDOR himoyasi bilan, AI'siz, faqat DB agregatsiyasi.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL", "message": "Kanal ID bo'sh"}
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_post_events"):
        return {"ok": False, "error_code": "DB_UNAVAILABLE", "message": "Baza mavjud emas"}

    if user_id is not None:
        try:
            owner = await _db_call(db, db.get_channel_owner_id, ch_id)
        except Exception:
            owner = None
        try:
            owned = owner is not None and int(owner) == int(user_id)
        except (TypeError, ValueError):
            owned = False
        if not owned:
            return {
                "ok": False,
                "error_code": "FORBIDDEN",
                "channel_id": ch_id,
                "message": "Bu kanal sizga tegishli emas — DNA ma'lumotlari faqat kanal egasiga ochiladi.",
            }

    events = await _db_call(db, db.get_channel_post_events, ch_id, 500)
    result = compute_channel_dna_extended(events)

    if result["insufficient"]:
        return {
            "ok": True,
            "insufficient": True,
            "channel_id": ch_id,
            "confidence": 0.0,
            "confidence_level": "low",
            "sample_size": result["sample_size"],
            "message": result["message"],
            "profile": None,
            "metrics": result.get("metrics"),
            "overall": result.get("overall"),
            "saved": False,
        }

    profile = result["profile"]
    saved = False
    try:
        # Try new table first
        if hasattr(db, "save_channel_dna_profile"):
            await _db_call(
                db, db.save_channel_dna_profile,
                ch_id,
                profile=profile,
                sample_size=result["sample_size"],
                confidence=result["confidence"],
            )
            saved = True
        # Also save legacy for backward compat
        if hasattr(db, "save_channel_intelligence_profile"):
            await _db_call(
                db, db.save_channel_intelligence_profile, ch_id,
                avg_post_length=profile.get("average_post_length") or profile.get("avg_length_value"),
                emoji_level=profile.get("emoji_level", "medium"),
                cta_style=profile.get("cta_style", "sometimes"),
                formatting_style=profile.get("formatting_style", "balanced"),
                confidence=int(result["confidence"] * 100),
                sample_size=result["sample_size"],
            )
            saved = True
    except Exception as e:
        logger.warning("Channel DNA extended saqlashda xato (%s): %s", ch_id, e)

    return {
        "ok": True,
        "insufficient": False,
        "channel_id": ch_id,
        "confidence": result["confidence"],
        "confidence_score": result["confidence_score"],
        "confidence_level": result.get("confidence_level", "medium"),
        "sample_size": result["sample_size"],
        "message": None,
        "profile": profile,
        "metrics": result.get("metrics"),
        "overall": result.get("overall"),
        "saved": saved,
    }


async def attach_dna_to_context(
    ctx: dict,
    user_id: int | None,
    db_module: Any = None,
) -> dict:
    """AI orkestrator kontekstiga Channel DNA ni ulaydi (ixcham prompt).

    DNA faqat BARCHA shartlar bajarilganda ulanadi:
      * ``ctx`` da ``channel_id`` bor va ``skip_dna`` o'chirilmagan;
      * DB mavjud;
      * ``user_id`` berilgan bo'lsa — kanal AYNAN shu foydalanuvchining
        (IDOR himoyasi);
      * saqlangan profil mavjud va ``sample_size >= 5``.

    Natija: ``ctx["system_prompt"]`` ga ixcham DNA bloki QO'SHILADI (eski
    matn saqlanadi) + ``ctx["channel_dna_attached"] = True``. Fail-soft:
    hech qanday xato kontekstni buzmaydi va generatsiyani to'xtatmaydi.
    """
    try:
        if not isinstance(ctx, dict):
            return ctx
        if ctx.get("skip_dna"):
            return ctx
        ch_id = str(ctx.get("channel_id") or "").strip()
        if not ch_id:
            return ctx
        db = db_module if db_module is not None else _import_database()
        if db is None or not hasattr(db, "get_channel_intelligence_profile"):
            return ctx
        if user_id is not None:
            try:
                owner = await _db_call(db, db.get_channel_owner_id, ch_id)
            except Exception:
                owner = None
            try:
                if owner is None or int(owner) != int(user_id):
                    return ctx
            except (TypeError, ValueError):
                return ctx
        profile = await _db_call(db, db.get_channel_intelligence_profile, ch_id)
        # Fallback to new table
        if (not isinstance(profile, dict) or not profile) and hasattr(db, "get_channel_dna_profile"):
            try:
                dna_profile = await _db_call(db, db.get_channel_dna_profile, ch_id)
                if isinstance(dna_profile, dict):
                    profile = dna_profile.get("profile") or dna_profile
            except Exception:
                pass
        if not isinstance(profile, dict) or not profile:
            return ctx
        sample = profile.get("sample_size")
        if isinstance(sample, dict):
            sample = sample.get("sample_size") or sample.get("value")
        if sample is None:
            # Try wrapped
            al = profile.get("avg_length")
            if isinstance(al, dict):
                sample = al.get("sample_size")
        if sample is None or int(sample) < MIN_POSTS_FOR_DNA:
            return ctx
        block = build_dna_system_prompt(profile, lang=str(ctx.get("lang") or "uz"))
        if not block:
            return ctx
        base = str(ctx.get("system_prompt") or "").strip()
        ctx["system_prompt"] = f"{base}\n\n{block}".strip()
        ctx["channel_dna_attached"] = True
    except Exception as e:  # noqa: BLE001 — fail-soft, generatsiya uzilmaydi
        logger.debug("attach_dna_to_context xatosi: %s", e)
    return ctx
