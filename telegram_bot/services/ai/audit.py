"""🔍 KENGAYTIRILGAN POST AUDIT & SCORE — 33 va 50-band (PHASE 12).

Postni **6 mezon** bo'yicha tekshiradi va to'liq hisobot chiqaradi::

    1. 🎯 Hook        — birinchi qator o'quvchini to'xtatadimi
    2. 💡 Clarity     — gaplar tushunarli, abzaslar yengilmi
    3. 📦 Value       — aniq foyda: fakt, raqam, amaliy qadam
    4. 🧱 Structure   — Telegram formatlash, punktlar, hashtaglar
    5. 📣 CTA         — harakatga chaqiriq bittami va aniqmi
    6. 💬 Engagement  — izoh/savol/ulashishga tortadimi

Hisobot strukturasi (50-band talabi):

    6 mezon (1-10) → Umumiy Score (88/100 + baho) → Kuchli tomonlar →
    Top 3 yaxshilanish → Yaxshilangan yakuniy namuna post

Ikki qavatli arxitektura (33-band «chuqur audit»)
--------------------------------------------------
* **Ballar — lokal va deterministik.** ``score_post_heuristics`` matnni
  o'lchanadigan ko'rsatkichlar (qator uzunligi, emoji, raqam, punkt,
  hashtag, CTA belgilari, ikkinchi shaxs) orqali baholaydi. Model «100/100»
  deb yozib qo'yishi MUMKIN EMAS — bu manipulyatsiyaga yopiq eshik.
* **Matnlar — AI bilan boyitiladi.** Modelga JSON kontrakti yuboriladi::

      {"verdict": str, "strengths": [str], "improvements": [{"fix": str}],
       "improved_post": str}

  va FAQAT matn maydonlari olinadi (uzunligi cheklangan, XSS'dan
  himoyalangan). JSON buzuq bo'lsa yoki umuman kelmasa — lokal karkas
  bilan hisobot baribir to'liq chiqadi (MockProvider rejimida ham shu).

Kvota: 1 ta AI chaqiruvi uchun 1 atomik bron (Phase 2). Xatoda refund.
Chiqish: ``sanitize_html`` + Telegram 4096 chegarasi bilan chunk'lar.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .smm_common import (
    CHUNK_SAFE_LIMIT,
    QuotaTicket,
    DEFAULT_LANG,
    SMMFeatureService,
    TELEGRAM_TEXT_LIMIT,
    bold,
    clip,
    coerce_int,
    ensure_hashtags,
    escape_literal,
    extract_hashtags,
    extract_json,
    has_dangerous_markup,
    lang_text,
    normalize_lang,
    plain_sentences,
    sanitize_html,
    strip_html,
    text_list,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MEZONLAR
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AuditCriterion:
    """Bitta baholash mezoni (og'irlik + lokal tekshiruv kaliti)."""

    key: str
    emoji: str
    weight: int
    label: dict
    problem: dict
    fix: dict

    def t_label(self, lang: Any) -> str:
        return lang_text(self.label, lang, self.key)

    def t_problem(self, lang: Any) -> str:
        return lang_text(self.problem, lang, "")

    def t_fix(self, lang: Any) -> str:
        return lang_text(self.fix, lang, "")


AUDIT_CRITERIA: tuple[AuditCriterion, ...] = (
    AuditCriterion(
        key="hook", emoji="🎯", weight=20,
        label={"uz": "Hook", "ru": "Хук", "en": "Hook"},
        problem={
            "uz": "Birinchi qator uzun yoki hayajsiz — o'quvchi skrollni to'xtatmaydi.",
            "ru": "Первая строка длинная или без эмоций — читатель не остановится.",
            "en": "The first line is long or flat — the scroll won't stop.",
        },
        fix={
            "uz": "Birinchi qatorni 60-90 belgiga tushiring: raqam yoki munozali savol + bitta emoji, <b>qalin</b> bilan.",
            "ru": "Сократите первую строку до 60-90 символов: цифра или спорный вопрос + один эмодзи, <b>жирным</b>.",
            "en": "Cut the first line to 60-90 characters: a number or a polarising question + one emoji, in <b>bold</b>.",
        },
    ),
    AuditCriterion(
        key="clarity", emoji="💡", weight=15,
        label={"uz": "Clarity", "ru": "Ясность", "en": "Clarity"},
        problem={
            "uz": "Gaplar uzun va abzaslar bitta devor bo'lib qolgan — o'qish qiyin.",
            "ru": "Длинные предложения и один «кирпич» текста — читать тяжело.",
            "en": "Long sentences and one wall of text — hard to read.",
        },
        fix={
            "uz": "Har bir gapni 12-18 so'zga bo'ling, 2-3 qatorli abzaslar qo'ying, ortiqcha atamalarni olib tashlang.",
            "ru": "Разбейте предложения на 12-18 слов, абзацы по 2-3 строки, уберите лишние термины.",
            "en": "Break sentences into 12-18 words, use 2-3 line paragraphs, drop filler terms.",
        },
    ),
    AuditCriterion(
        key="value", emoji="📦", weight=20,
        label={"uz": "Value", "ru": "Польза", "en": "Value"},
        problem={
            "uz": "Umumiy iboralar ko'p, o'quvchi uchun olib qoladigan aniq narsa yo'q.",
            "ru": "Много общих фраз, читателю нечего забрать с собой.",
            "en": "Mostly generic phrasing — the reader takes nothing away.",
        },
        fix={
            "uz": "Kamida bitta aniq raqam, 2-3 ta amaliy punkt va bitta ekspert xulosasini qo'shing.",
            "ru": "Добавьте минимум одну конкретную цифру, 2-3 практических пункта и вывод эксперта.",
            "en": "Add at least one concrete number, two or three practical points and an expert takeaway.",
        },
    ),
    AuditCriterion(
        key="structure", emoji="🧱", weight=15,
        label={"uz": "Structure", "ru": "Структура", "en": "Structure"},
        problem={
            "uz": "Formatlash va hashtaglar yetishmaydi — post monolit ko'rinadi.",
            "ru": "Не хватает форматирования и хэштегов — пост выглядит монолитом.",
            "en": "Little formatting or hashtags — the post looks like a monolith.",
        },
        fix={
            "uz": "<b>qalin</b> sarlavha, ✅ punktlar, bo'sh qatorlar va oxirga 3-5 ta mavzuli hashtag qo'ying.",
            "ru": "Жирный заголовок <b>…</b>, пункты ✅, пустые строки и 3-5 тематических хэштегов в конце.",
            "en": "A <b>bold</b> headline, ✅ bullets, blank lines and 3-5 topical hashtags at the end.",
        },
    ),
    AuditCriterion(
        key="cta", emoji="📣", weight=15,
        label={"uz": "CTA", "ru": "CTA", "en": "CTA"},
        problem={
            "uz": "Yakunda aniq harakat ko'rsatilmagan — o'quvchi nima qilishni bilmaydi.",
            "ru": "В конце нет конкретного действия — читатель не знает, что делать.",
            "en": "No concrete next step — the reader doesn't know what to do.",
        },
        fix={
            "uz": "BITTA qalin CTA qoldiring (masalan «👉 Hoziroq yozing») va bitta cheklov ko'rsating (muddat yoki joylar soni).",
            "ru": "Оставьте ОДИН жирный CTA (например «👉 Напишите сейчас») и одно ограничение (срок или количество мест).",
            "en": "Keep ONE bold CTA (e.g. “👉 Message us now”) plus one limit (deadline or seats).",
        },
    ),
    AuditCriterion(
        key="engagement", emoji="💬", weight=15,
        label={"uz": "Engagement", "ru": "Вовлечение", "en": "Engagement"},
        problem={
            "uz": "Muzokaraga chaqiriq yo'q — izohlar bo'sh qoladi.",
            "ru": "Нет приглашения к обсуждению — комментарии пустые.",
            "en": "Nothing invites a reply — the comments stay empty.",
        },
        fix={
            "uz": "O'quvchiga ikkinchi shaxsda murojaat qiling, oxirga bitta ochiq savol va «ulashing/saqlab oling» qo'shing.",
            "ru": "Обращайтесь к читателю на «вы», добавьте один открытый вопрос и «сохраните/отправьте другу».",
            "en": "Address the reader directly, add one open question and a save/share line.",
        },
    ),
)

AUDIT_CRITERION_KEYS: tuple[str, ...] = tuple(item.key for item in AUDIT_CRITERIA)
#: Bitta mezon bo'yicha ball chegarasi (repo POST_SCORE standarti bilan bir xil).
CRITERION_MIN, CRITERION_MAX = 1, 10
OVERALL_MAX = 100
#: Yaxshilanishlar ro'yxati uzunligi (50-band: «Top 3»).
TOP_IMPROVEMENTS = 3
#: AI xulosa/kuchli tomonlari qabul qilinadigan minimal ball — bundan
#: pasda faqat deterministik (lokal) xulosa ko'rsatiladi.
AI_NARRATIVE_MIN_SCORE = 60
#: Audit uchun minimal matn hajmi.
AUDIT_MIN_CHARS = 20
#: AI'ga yuboriladigan matn chegarasi.
AUDIT_INPUT_LIMIT = 3200

_CTA_WORDS = {
    "uz": ("👉", "buyurtma", "yozing", "yozib", "bog'lan", "murojaat", "hoziroq",
           "havola", "obuna", "ro'yxat", "qo'ng'iroq", "shoshiling", "manzil",
           "yuboring", "o'ting", "tanlang"),
    "ru": ("👉", "закаж", "напиш", "свяж", "позвон", "подпиш", "перейд", "ссылк",
           "оформ", "успей", "жми", "запис", "📞", "🔗"),
    "en": ("👉", "order", "buy", "contact", "message", "click", "link",
           "subscribe", "sign up", "call", "book", "grab", "dm ", "📞", "🔗"),
}
_URGENCY_WORDS = {
    "uz": ("cheklangan", "faqat", "bugun", "muddat", "oxirgi", "hozir", "tezkor", "oyiga"),
    "ru": ("ограничено", "только", "сегодня", "последние", "сейчас", "успей", "до"),
    "en": ("limited", "only", "today", "last", "now", "ends", "until"),
}
_SECOND_PERSON = {
    "uz": ("siz", "sizga", "sizni", "sizning", "sen", "senga", "sizcha"),
    "ru": ("вы ", "вас", "вам", "ваш", "ты ", "тебе", "у вас"),
    "en": ("you ", "your", "you're", "yours", "for you"),
}
_INTERACTION_WORDS = {
    "uz": ("izoh", "fikr", "savol", "so'rov", "poll", " bahashay", "yozing", "saqlab", "ulashing"),
    "ru": ("комментар", "мнени", "опрос", "голос", "сохран", "подели"),
    "en": ("comment", "thought", "poll", "vote", "save ", "share"),
}
_EXPERT_WORDS = {
    "uz": ("xulosa", "yakunda", "natijada", "maslahat", "ekspert", "tavsiya"),
    "ru": ("вывод", "итог", "совет", "эксперт", "рекоменд"),
    "en": ("takeaway", "conclusion", "advice", "expert", "recommend"),
}
_METRIC_RE = re.compile(r"\d+\s*(?:%|so'?m|sum|сум|руб|₽|\$|€|kun|kecha|daqiqa|soat|min|sec|k|million|mld)",
                        re.IGNORECASE)
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
                       "\U0001F300-\U0001F5FF\u2764\u2b50\u2705\u274c\u2714\u2728\U0001F900-\U0001F9FF]")
_BULLET_RE = re.compile(r"^\s*(?:[-•*✅✔🔹▪️\U0001F535\U0001F7E2]|\d+[.)])\s+")
_BOLD_RE = re.compile(r"<b>|<strong>|\*\*[^*\n]{2,}\*\*")
_ITALIC_RE = re.compile(r"<i>|<em>")


# ---------------------------------------------------------------------------
# LOKAL (DETERMINISTIK) HISOBLAGICH
# ---------------------------------------------------------------------------
@dataclass
class AuditMetrics:
    """Tahlil uchun o'lchanadigan ko'rsatkichlar (hisobotda ham ko'rsatiladi)."""

    chars: int = 0
    words: int = 0
    lines: int = 0
    paragraphs: int = 0
    sentences: int = 0
    avg_sentence_words: float = 0.0
    emojis: int = 0
    bullets: int = 0
    hashtags: int = 0
    links: int = 0
    bold_lines: int = 0
    first_line_chars: int = 0
    has_question: bool = False
    has_cta: bool = False
    has_urgency: bool = False
    has_metric: bool = False
    second_person: int = 0
    lang: str = "uz"

    def as_dict(self) -> dict:
        return {
            "chars": self.chars, "words": self.words, "lines": self.lines,
            "paragraphs": self.paragraphs, "sentences": self.sentences,
            "avg_sentence_words": round(self.avg_sentence_words, 1),
            "emojis": self.emojis, "bullets": self.bullets,
            "hashtags": self.hashtags, "links": self.links,
            "bold_lines": self.bold_lines, "first_line_chars": self.first_line_chars,
            "has_question": self.has_question, "has_cta": self.has_cta,
            "has_urgency": self.has_urgency, "has_metric": self.has_metric,
            "second_person": self.second_person, "lang": self.lang,
        }


def _contains_any(haystack: str, needles) -> bool:
    return any(needle in haystack for needle in needles)


def measure_post(text: Any, lang: str = "uz") -> AuditMetrics:
    """Postni o'lchanadigan qismlarga ajratadi (xavfsiz, istisnosiz)."""
    code = normalize_lang(lang)
    raw = str(text or "")
    plain = strip_html(raw)
    if not plain:
        return AuditMetrics(lang=code)
    lines = [line.strip() for line in re.split(r"\n+", plain) if line.strip()]
    paragraphs = [chunk for chunk in re.split(r"\n\s*\n", raw) if chunk.strip()]
    sentences = plain_sentences(raw, min_len=1, max_items=40) or [plain]
    words = re.findall(r"[\w']+", plain)
    first_line = lines[0] if lines else ""
    lower = plain.lower()
    return AuditMetrics(
        chars=len(plain),
        words=len(words),
        lines=len(lines),
        paragraphs=len(paragraphs),
        sentences=len(sentences),
        avg_sentence_words=(len(words) / max(1, len(sentences))),
        emojis=len(_EMOJI_RE.findall(plain)),
        bullets=sum(1 for line in lines if _BULLET_RE.match(line)),
        hashtags=len(extract_hashtags(raw)),
        links=len(re.findall(r"https?://|t\.me/|@[\w_]{4,}", raw, re.IGNORECASE)),
        bold_lines=len(_BOLD_RE.findall(raw)),
        first_line_chars=len(first_line),
        has_question="?" in plain,
        has_cta=_contains_any(lower, _CTA_WORDS.get(code, _CTA_WORDS["uz"])),
        has_urgency=_contains_any(lower, _URGENCY_WORDS.get(code, _URGENCY_WORDS["uz"])),
        has_metric=bool(_METRIC_RE.search(plain)) or bool(re.search(r"\b\d{2,}\b", plain)),
        second_person=sum(lower.count(word) for word in _SECOND_PERSON.get(code, ())),
        lang=code,
    )


def audit_topic(text: Any) -> str:
    """Audit so'rovida «mavzu» sifatida yuboriladigan tozalangan sarlavha."""
    return clip(re.sub(r"\s*[:?!.]+\s*$", "", re.sub(r"^[^\w]+", "", _first_line(text))), 70)


def _first_line(text: str) -> str:
    """Matndagi birinchi mazmuniy qator (audit sarlavhasi uchun)."""
    for line in re.split(r"\n+\s*\n+|\n+", str(text or "")):
        stripped = line.strip()
        if len(stripped) >= 6:
            return re.sub(r"\s+", " ", stripped)
    return str(text or "").strip()


def _clamp(value: int, lo: int = CRITERION_MIN, hi: int = CRITERION_MAX) -> int:
    return max(lo, min(hi, int(value)))


def score_criterion(key: str, metrics: AuditMetrics) -> int:
    """Bitta mezon bo'yicha 1-10 ball (to'liq deterministik qoidalar)."""
    m = metrics
    if key == "hook":
        score = 3
        if 0 < m.first_line_chars <= 90:
            score += 2
        elif m.first_line_chars <= 130:
            score += 1
        if m.bold_lines:
            score += 1
        if m.emojis:
            score += 1
        if m.has_question or m.has_metric:
            score += 2
        if 2 <= m.lines <= 30:
            score += 1
        return _clamp(score)

    if key == "clarity":
        score = 3
        if 6 <= m.avg_sentence_words <= 22:
            score += 2
        elif m.avg_sentence_words <= 30:
            score += 1
        if 40 <= m.words <= 320:
            score += 2
        elif m.words > 320:
            score -= 1
        if m.paragraphs >= 2:
            score += 2
        if m.sentences <= 14:
            score += 1
        return _clamp(score)

    if key == "value":
        score = 2
        if m.has_metric:
            score += 2
        if m.bullets >= 2:
            score += 2
        elif m.bullets:
            score += 1
        if m.words >= 60:
            score += 2
        if m.sentences >= 3:
            score += 1
        return _clamp(score)

    if key == "structure":
        score = 1
        if m.bold_lines:
            score += 2
        if m.paragraphs >= 3:
            score += 2
        elif m.paragraphs == 2:
            score += 1
        if 3 <= m.hashtags <= 6:
            score += 3
        elif m.hashtags:
            score += 1
        if 2 <= m.emojis <= 12:
            score += 1
        if 300 <= m.chars <= 1600:
            score += 1
        return _clamp(score)

    if key == "cta":
        score = 2
        if m.has_cta:
            score += 3
        if m.links:
            score += 1
        if m.has_urgency:
            score += 2
        if m.bold_lines >= 2:
            score += 1
        return _clamp(score)

    if key == "engagement":
        score = 2
        if m.second_person >= 1:
            score += 2
        if m.has_question:
            score += 2
        if m.emojis >= 2:
            score += 1
        return _clamp(score)

    return _clamp(CRITERION_MIN)


#: ``value``/``engagement`` uchun qo'shimcha matnga bog'liq bonuslar
#: (metrikalar saqlanmasligi uchun alohida funksiya — pastda chaqiriladi).
def _text_bonus(key: str, plain_lower: str, code: str) -> int:
    if key == "value":
        bonus = 0
        if _contains_any(plain_lower, _EXPERT_WORDS.get(code, _EXPERT_WORDS["uz"])):
            bonus += 1
        if _contains_any(plain_lower, ("misol", "keysi", "case", "истори", "пример", "example", "case study")):
            bonus += 1
        return bonus
    if key == "engagement":
        bonus = 0
        if _contains_any(plain_lower, _INTERACTION_WORDS.get(code, _INTERACTION_WORDS["uz"])):
            bonus += 2
        if _contains_any(plain_lower, ("🔁", "ulash", "saqla", "сохран", "подели", "share", "save")):
            bonus += 1
        return bonus
    return 0


def score_post_heuristics(text: Any, lang: str = "uz") -> tuple[dict, AuditMetrics]:
    """6 mezon bo'yicha lokal ballar + o'lchovlar (AI'siz, reproducible)."""
    code = normalize_lang(lang)
    metrics = measure_post(text, code)
    plain_lower = strip_html(text).lower()
    scores: dict[str, int] = {}
    for criterion in AUDIT_CRITERIA:
        value = score_criterion(criterion.key, metrics) + _text_bonus(criterion.key, plain_lower, code)
        scores[criterion.key] = _clamp(value)
    return scores, metrics


def overall_from_criteria(scores: dict[str, int]) -> int:
    """Og'irlikka ko'ra umumiy 0-100 ball (har bir mezon weight/10 ga teng)."""
    total = 0.0
    for criterion in AUDIT_CRITERIA:
        value = coerce_int(scores.get(criterion.key), CRITERION_MIN, CRITERION_MIN, CRITERION_MAX)
        total += value * (criterion.weight / CRITERION_MAX)
    return max(0, min(OVERALL_MAX, int(round(total))))


def grade_for(score: int) -> str:
    score = max(0, min(OVERALL_MAX, int(score or 0)))
    if score >= 95:
        return "A+"
    if score >= 88:
        return "A"
    if score >= 78:
        return "B+"
    if score >= 68:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "E"


def score_bar(value: int, width: int = 10) -> str:
    filled = max(0, min(width, int(value)))
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------------------
# NATIJA MODELLARI
# ---------------------------------------------------------------------------
@dataclass
class CriterionScore:
    """Bitta mezon natijasi (ball + og'irlik + izoh)."""

    key: str
    label: str
    emoji: str
    score: int
    weight: int
    points: int
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "emoji": self.emoji,
            "score": self.score, "max": CRITERION_MAX, "weight": self.weight,
            "points": self.points, "note": self.note,
            "bar": score_bar(self.score),
        }

    def render(self) -> str:
        header = (f"{self.emoji} {self.label}: {self.score}/{CRITERION_MAX} "
                  f"\u2192 {self.points}/{self.weight}")
        return f"{escape_literal(header)} {score_bar(self.score)}"


@dataclass
class ImprovementTip:
    """Bitta yaxshilanish taklifi (Top 3 ro'yxati elementi)."""

    rank: int
    criterion: str
    label: str
    problem: str
    fix: str
    gain: int
    score: int = CRITERION_MAX
    source: str = "local"

    def as_dict(self) -> dict:
        return {
            "rank": self.rank, "criterion": self.criterion, "label": self.label,
            "problem": self.problem, "fix": self.fix, "gain": self.gain,
            "score": self.score,
            "source": self.source,
        }

    def render(self) -> str:
        line = f"<b>{self.rank}) {escape_literal(self.label)}</b>"
        # Ball yuqori bo'lsa «muammo» deb yozilmaydi — bu kuchaytirish bo'limi.
        if self.score < 8 and self.problem:
            line += f" — {escape_literal(self.problem)}"
        if self.fix:
            line += f"\n🛠 {escape_literal(self.fix)}"
        if self.gain > 0:
            line += f"\n📈 kutilayotgan o'sish: +{self.gain} ball"
        return line


# ---------------------------------------------------------------------------
# RESULT
# ---------------------------------------------------------------------------
@dataclass
class PostAuditResult:
    """Deep audit hisoboti."""

    success: bool = False
    criteria: dict = field(default_factory=dict)
    overall_score: int = 0
    grade: str = "E"
    verdict: str = ""
    strengths: list = field(default_factory=list)
    improvements: list = field(default_factory=list)
    improved_post: str = ""
    metrics: dict = field(default_factory=dict)
    report: str = ""
    chunks: list = field(default_factory=list)
    lang: str = DEFAULT_LANG
    provider_used: str = "none"
    ai_merged: bool = False
    cost: int = 0
    reservation_id: Any = None
    quota: dict = field(default_factory=dict)
    paid: bool = False
    refund_issued: bool = False
    error: str | None = None
    error_code: str | None = None

    @property
    def scores(self) -> dict:
        return {key: item.score for key, item in self.criteria.items()}

    def as_dict(self) -> dict:
        return {
            "success": self.success,
            "score": self.overall_score,
            "score_label": f"{self.overall_score}/{OVERALL_MAX}",
            "grade": self.grade,
            "verdict": self.verdict,
            "criteria": {key: item.as_dict() for key, item in self.criteria.items()},
            "strengths": list(self.strengths),
            "improvements": [item.as_dict() for item in self.improvements],
            "improved_post": self.improved_post,
            "metrics": dict(self.metrics),
            "lang": self.lang,
            "provider_used": self.provider_used,
            "ai_merged": self.ai_merged,
            "cost": self.cost,
            "reservation_id": self.reservation_id,
            "quota": dict(self.quota),
            "paid": self.paid,
            "refund_issued": self.refund_issued,
            "error": self.error,
            "error_code": self.error_code,
            "report": self.report,
            "chunks": list(self.chunks),
        }


# ---------------------------------------------------------------------------
# XIZMAT
# ---------------------------------------------------------------------------
_VERDICTS = {
    "uz": {
        "excellent": "Ajoyib post — shu holicha ham chiqarish mumkin.",
        "good": "Yaxshi asos — Top 3 tuzatishni qo'shsangiz kuchayadi.",
        "average": "O'rtacha: mazmun bor, lekin struktura va chaqiriq sust.",
        "weak": "Qayta ishlash kerak: hook, foyda va CTA birga zaif.",
    },
    "ru": {
        "excellent": "Отличный пост — можно публиковать как есть.",
        "good": "Хорошая база — Топ-3 правки сделают его сильнее.",
        "average": "Средне: смысл есть, но структура и призыв слабые.",
        "weak": "Нужна переработка: хук, польза и CTA слабы.",
    },
    "en": {
        "excellent": "Excellent post — publish it as is.",
        "good": "Solid base — the Top 3 fixes will make it stronger.",
        "average": "Average: the idea is there, structure and CTA are weak.",
        "weak": "Needs a rewrite: hook, value and CTA are all weak.",
    },
}


class PostAuditService(SMMFeatureService):
    """Postni chuqur audit qilish va 6 mezonli hisobot (33/50-band)."""

    feature = "audit"
    quota_operation = "post_score:audit"
    quota_cost = 1

    # -- public API --------------------------------------------------------
    async def audit_post(
        self,
        user_id: int | None,
        post_text: str,
        lang: str = DEFAULT_LANG,
        *,
        db_module: Any = None,
        use_ai: bool = True,
        improve: bool = True,
        orchestrator: Any = None,
    ) -> PostAuditResult:
        """Post uchun to'liq hisobot qaytaradi (hech qachon istisno bermaydi).

        Tarif siyosati ``utils/post_scorer`` konventsiyasi bilan bir xil:
        baholash (6 mezon + score + tavsiyalar) — BEPUL; «✨ yaxshilangan
        yakuniy namuna» — AI ishida 1 atomik kredit. AI yiqilsa bron
        qaytariladi (``refund_issued=True``, ``cost=0``).
        """
        code = normalize_lang(lang)
        raw = str(post_text or "").strip()
        if len(strip_html(raw)) < AUDIT_MIN_CHARS:
            return PostAuditResult(success=False, lang=code,
                                   error="text_too_short", error_code="INVALID_INPUT")

        if orchestrator is not None:
            self._injected_orchestrator = orchestrator

        # Bepul bosqich: AI yaxshilash so'ralmasa (improve=False yoki
        # use_ai=False) bron UMUMIY qilinmaydi — xuddi post_score'dagi kabi.
        paid_step = bool(improve and use_ai)
        ticket = (await self.acquire_quota(db_module, user_id) if paid_step
                  else QuotaTicket(allowed=True, skipped=True, reason="free_audit"))
        if not ticket.allowed:
            return PostAuditResult(
                success=False, lang=code,
                error=ticket.reason or "quota_denied",
                error_code="QUOTA_EXCEEDED" if not ticket.reason or ticket.reason in {
                    "insufficient_balance", "user_not_found",
                } else "QUOTA_UNAVAILABLE",
                quota=ticket.as_dict(),
            )

        try:
            scores, metrics = score_post_heuristics(raw, code)
            criteria = self._criteria_view(scores, code)
            overall = overall_from_criteria(scores)
            strengths = self._local_strengths(criteria, code)
            improvements = self._local_improvements(criteria, code)
            improved_post = self._local_improved_post(raw, criteria, code)
            verdict = self._local_verdict(overall, code)
            provider_used = "local"
            ai_merged = False
            refund_issued = False

            # 33-band: AI chuqurlashtirilgan qismi (matnlar — ballar emas).
            if use_ai:
                outcome = await self.ask(
                    self.build_audit_prompt(raw, code, scores),
                    user_id=user_id, lang=code,
                    context={"smm_mode": "AUDIT",
                             "smm_topic": audit_topic(strip_html(raw))},
                )
                ai_failed = not outcome.ok
                if outcome.error_code == "CANCELLED":
                    await self.release_quota(ticket)
                    return PostAuditResult(
                        success=False, lang=code, error=outcome.error or "cancelled",
                        error_code="CANCELLED", cost=ticket.cost,
                        reservation_id=ticket.reservation_id, quota=ticket.as_dict(),
                    )
                if outcome.provider and outcome.provider != "none":
                    provider_used = outcome.provider
                payload = extract_json(outcome.text or outcome.raw) if outcome.ok else None
                if isinstance(payload, dict):
                    # 🛡 AI matnlari deterministik dalilga ZID kelmasligi kerak:
                    # past ballli postda «hammasi zo'r» degan xulosa yozib
                    # bo'lsa ham qabul qilinmaydi. improved_post esa doim
                    # qabul qilinadi — u da'vo emas, taklif.
                    if overall >= AI_NARRATIVE_MIN_SCORE:
                        ai_verdict = clip(strip_html(payload.get("verdict", "")), 240)
                        if len(ai_verdict) >= 12:
                            verdict = ai_verdict
                        ai_strengths = text_list(payload.get("strengths"), 240, 4)
                        if ai_strengths:
                            strengths = ai_strengths
                    improvements = self._merge_improvements(
                        improvements, payload.get("improvements"))
                    ai_post = (self._clean_ai_post(payload.get("improved_post"))
                               if paid_step else "")
                    if ai_post:
                        improved_post = ai_post
                    ai_merged = True

                # 💳 Pulli qism (yaxshilangan namuna) AI'da chiqmadi → bron qaytariladi.
                if paid_step and ai_failed and outcome.error_code != "CANCELLED":
                    refund_issued = await self.release_quota(ticket)
                    if refund_issued:
                        ticket.cost = 0

            report, chunks = self._render(criteria, overall, verdict, strengths,
                                          improvements, improved_post, code)
            result = PostAuditResult(
                success=True,
                criteria=criteria,
                overall_score=overall,
                grade=grade_for(overall),
                verdict=verdict,
                strengths=strengths,
                improvements=improvements,
                improved_post=improved_post,
                metrics=metrics.as_dict(),
                report=report,
                chunks=chunks,
                lang=code,
                provider_used=provider_used,
                ai_merged=ai_merged,
                cost=ticket.cost,
                reservation_id=ticket.reservation_id,
                quota=ticket.as_dict(),
                paid=paid_step and not refund_issued,
                refund_issued=refund_issued,
            )
            self._log("audit tayyor (user=%s, score=%s/%s, lang=%s)",
                      user_id, overall, OVERALL_MAX, code)
            return result
        except Exception as exc:  # noqa: BLE001 — xizmat yiqilmasligi kerak
            logger.exception("audit xatosi: %s", exc)
            await self.release_quota(ticket)
            return PostAuditResult(success=False, lang=code, error=str(exc),
                                   error_code="AUDIT_FAILED",
                                   cost=ticket.cost,
                                   reservation_id=ticket.reservation_id,
                                   quota=ticket.as_dict())

    # -- prompt ------------------------------------------------------------
    @staticmethod
    def build_audit_prompt(post_text: str, lang: str = "uz",
                           scores: dict | None = None) -> str:
        """Modelga yuboriladigan audit topshirig'i (JSON kontrakt bilan)."""
        code = normalize_lang(lang)
        safe = escape_literal(clip(strip_html(post_text), AUDIT_INPUT_LIMIT))
        lead = {
            "uz": "Ushbu postni professional SMM auditor sifatida tahlil qiling va baholang.",
            "ru": "Проанализируй и оцени этот пост как профессиональный SMM-аудитор.",
            "en": "Audit and rate this post as a senior SMM auditor.",
        }[code]
        return "\n".join([
            "[SMM TASK: post_audit — audit this post]",
            lead,
            "",
            safe,
            "",
            "Javobni FAQAT bitta JSON obyektida qaytaring (izohsiz):",
            '{"verdict": "1-2 jumlalik xulosa", "strengths": ["kuchli tomon"], '
            '"improvements": [{"criterion": "hook", "fix": "aniq tuzatish"}], '
            '"improved_post": "<b>yaxshilangan post</b>"}',
            "Mezon kalitlari: hook | clarity | value | structure | cta | engagement.",
            "Talab: improvements ro'yxati 3 tagacha, improved_post Telegram HTML "
            "(<b>, <i>) va 3-5 hashtag bilan; markdown ishlatmang.",
        ])

    # -- ichki quruvchilar -------------------------------------------------
    @staticmethod
    def _criteria_view(scores: dict, lang: str) -> dict:
        code = normalize_lang(lang)
        view: dict[str, CriterionScore] = {}
        for criterion in AUDIT_CRITERIA:
            value = coerce_int(scores.get(criterion.key), CRITERION_MIN,
                              CRITERION_MIN, CRITERION_MAX)
            points = int(round(value * (criterion.weight / CRITERION_MAX)))
            view[criterion.key] = CriterionScore(
                key=criterion.key, label=criterion.t_label(code),
                emoji=criterion.emoji, score=value, weight=criterion.weight,
                points=points,
                note=clip(criterion.t_problem(code) if value < 8 else
                         lang_text({"uz": "Me'yor darajasida", "ru": "В норме",
                                    "en": "Within standards"}, code), 240),
            )
        return view

    @staticmethod
    def _local_strengths(criteria: dict, lang: str) -> list[str]:
        code = normalize_lang(lang)
        templates = {
            "hook": {"uz": "Birinchi qator e'tibor tortadi — skrollni to'xtatadi",
                     "ru": "Первая строка цепляет взгляд — скролл останавливается",
                     "en": "The opening line stops the scroll"},
            "clarity": {"uz": "Gaplar qisqa va abzaslar yengil — o'qish oson",
                        "ru": "Короткие фразы и лёгкие абзацы — читается легко",
                        "en": "Short sentences and light paragraphs read easily"},
            "value": {"uz": "Aniq foyda bor: raqam/punkt bilan asoslangan",
                      "ru": "Есть конкретная польза: цифры и пункты",
                      "en": "Concrete value is present: numbers and points"},
            "structure": {"uz": "Telegram formatlash va hashtaglar tartibli ishlatilgan",
                          "ru": "Форматирование Telegram и хэштеги использованы аккуратно",
                          "en": "Telegram formatting and hashtags are used properly"},
            "cta": {"uz": "Harakatga chaqiriq aniq va bitta",
                    "ru": "Призыв к действию чёткий и один",
                    "en": "The call to action is clear and single"},
            "engagement": {"uz": "O'quvchi bilan muloqotga ochiq eshik bor",
                           "ru": "Есть открытая дверь для диалога с читателем",
                           "en": "There is an open door for reader dialogue"},
        }
        found = []
        for key, item in criteria.items():
            if item.score >= 8:
                found.append(clip(lang_text(templates.get(key, {}), code), 200))
        if not found:
            fallback = {
                "uz": "Mavzu dolzarb va tanlov aniq — asos to'g'ri qo'yilgan",
                "ru": "Тема актуальна, выбор понятен — фундамент верный",
                "en": "The topic is relevant and the angle is clear — the base is right",
            }
            found.append(lang_text(fallback, code))
        return found[:4]

    @staticmethod
    def _local_improvements(criteria: dict, lang: str) -> list:
        """Eng «qimmat» 3 mezon bo'yicha takliflar (ball/og'irlik arifmetikasi)."""
        code = normalize_lang(lang)
        ranked = sorted(
            criteria.values(),
            key=lambda item: (item.points - item.weight, -item.weight, item.key),
        )
        tips = []
        for rank, item in enumerate(ranked[:TOP_IMPROVEMENTS], start=1):
            criterion = next(cur for cur in AUDIT_CRITERIA if cur.key == item.key)
            tips.append(ImprovementTip(
                rank=rank,
                score=item.score,
                criterion=criterion.key,
                label=criterion.t_label(code),
                problem=clip(criterion.t_problem(code), 240),
                fix=clip(criterion.t_fix(code), 300),
                gain=max(0, criterion.weight - item.points),
            ))
        return tips

    @staticmethod
    def _merge_improvements(tips: list, raw_items: Any) -> list:
        """AI tuzatishlarini MEZON BO'YICHA birlashtiradi.

        Model ``{"criterion": "hook", "fix": "..."``} ko'rinishida yuborsa,
        tuzatish o'sha mezon tipiga qo'yiladi; mezon tanilmasa yoki u Top 3
        ichida bo'lmasa — AI matni e'tiborsiz qoldiriladi (lokal maslahat
        saqlanadi). Shu sababli hisobot hech qachon «mavzudan chiqib» ketmaydi.
        """
        items = raw_items if isinstance(raw_items, list) else []
        by_criterion: dict[str, str] = {}
        generic: list[str] = []
        for item in items:
            if isinstance(item, dict):
                fix = clip(strip_html(item.get("fix") or item.get("text") or ""), 300)
                key = str(item.get("criterion") or item.get("key") or "").strip().lower()
                if key in AUDIT_CRITERION_KEYS and len(fix) >= 12:
                    by_criterion.setdefault(key, fix)
                elif len(fix) >= 12:
                    generic.append(fix)
            else:
                text = clip(strip_html(item), 300)
                if len(text) >= 12:
                    generic.append(text)
        for tip in tips:
            if tip.criterion in by_criterion:
                tip.fix = by_criterion[tip.criterion]
                tip.source = "ai"
            elif generic:
                tip.fix = generic.pop(0)
                tip.source = "ai"
        return tips

    @staticmethod
    def _clean_ai_post(value: Any) -> str:
        """Modelning «yaxshilangan posti» — faqat ruxsat etilgan HTML, chegarali.

        Xavfli teg (script/iframe/...) uchsa sanitizer uni escape qiladi;
        shunga qaramay matn juda qisqa bo'lsa — model javobi rad etiladi va
        lokal qurilgan variant ishlatiladi.
        """
        if not value:
            return ""
        text = str(value).strip()
        if has_dangerous_markup(text):
            text = strip_html(text)
        text = sanitize_html(text, TELEGRAM_TEXT_LIMIT)
        if len(strip_html(text)) < 40:
            return ""
        return text

    # -- lokal «yaxshilangan» post -----------------------------------------
    @staticmethod
    def _local_improved_post(post_text: str, criteria: dict, lang: str) -> str:
        """AI ishlamasa ham foydalanuvchi qo'lida tayyor variant bo'lsin."""
        code = normalize_lang(lang)
        plain = strip_html(post_text)
        sentences = plain_sentences(plain, min_len=14, max_items=6)
        headline = clip(re.sub(r"^[^\w]+", "", sentences[0] if sentences else plain), 96) or "Yangi post"
        hook_labels = {
            "uz": "🔥 {hook} — 3 daqiqada tushunadigan asosiy fikr",
            "ru": "🔥 {hook} — главная мысль, понятная за 3 минуты",
            "en": "🔥 {hook} — the core idea you get in three minutes",
        }[code]
        blocks = [bold(escape_literal(clip(hook_labels.format(hook=headline), TELEGRAM_TEXT_LIMIT)))]
        body = sentences[1:4] or sentences[:2]
        if body:
            blocks.append("\n".join(f"• {escape_literal(clip(item, 180))}" for item in body))
        weak = [key for key, item in criteria.items() if item.score < 8]
        if "value" in weak or not body:
            value_line = {
                "uz": "✅ Natija: [ko'rsatkich] bo'yicha haftada +[foiz] — bitta metrikaga e'tibor qarating.",
                "ru": "✅ Итог: +[процент] в неделю по метрике [показатель] — сфокусируйтесь на одном.",
                "en": "✅ Result: +[percent] a week on [metric] — focus on a single number.",
            }[code]
            blocks.append(escape_literal(value_line))
        if "cta" in weak:
            cta = {
                "uz": "👉 <b>Hoziroq yozing</b> — [muddat] gacha, joylar soni cheklangan.",
                "ru": "👉 <b>Напишите сейчас</b> — до [дата], количество мест ограничено.",
                "en": "👉 <b>Message now</b> — until [date], limited seats.",
            }[code]
            blocks.append(cta)
        if "engagement" in weak:
            ask = {
                "uz": "💬 Sizda qanday? Izohda yozing — eng faol javoblarni keyingi postga olamiz.",
                "ru": "💬 А как у вас? Напишите в комментариях — лучший ответ попадёт в следующий пост.",
                "en": "💬 How about you? Drop it in the comments — best answer gets featured.",
            }[code]
            blocks.append(escape_literal(ask))
        text = "\n\n".join(blocks)
        return ensure_hashtags(text, {
            "uz": ("#tahlil", "#yaxshilangan", "#smm"),
            "ru": ("#разбор", "#улучшено", "#smm"),
            "en": ("#audit", "#improved", "#smm"),
        }[code], 3, 5)

    @staticmethod
    def _local_verdict(score: int, lang: str) -> str:
        code = normalize_lang(lang)
        table = _VERDICTS[code]
        if score >= 88:
            return table["excellent"]
        if score >= 68:
            return table["good"]
        if score >= 45:
            return table["average"]
        return table["weak"]

    # -- hisobot render -----------------------------------------------------
    def _render(self, criteria: dict, overall: int, verdict: str,
                strengths: list, improvements: list, improved_post: str,
                lang: str) -> tuple[str, list[str]]:
        code = normalize_lang(lang)
        titles = {
            "uz": {"report": "Post audit", "criteria": "Mezonlar",
                   "strengths": "Kuchli tomonlar", "improvements": "Top 3 yaxshilanish",
                   "improved": "Yaxshilangan yakuniy namuna"},
            "ru": {"report": "Аудит поста", "criteria": "Критерии",
                   "strengths": "Сильные стороны", "improvements": "Топ-3 улучшения",
                   "improved": "Итоговый улучшенный вариант"},
            "en": {"report": "Post audit", "criteria": "Criteria",
                   "strengths": "Strengths", "improvements": "Top 3 improvements",
                   "improved": "Improved final sample"},
        }[code]
        header = bold(f"📊 {titles['report']} — {overall}/{OVERALL_MAX} · {grade_for(overall)}")
        blocks = [header]
        if verdict:
            blocks.append(f"<i>{escape_literal(verdict)}</i>")
        criteria_lines = "\n".join(item.render() for item in criteria.values())
        blocks.append(f"{bold('🧾 ' + escape_literal(titles['criteria']))}\n{criteria_lines}")
        blocks.append(bold(f"✅ {titles['strengths']}") + "\n" +
                      "\n".join(f"• {escape_literal(clip(item, 240))}" for item in strengths))
        blocks.append(bold(f"🛠 {titles['improvements']}") + "\n" +
                      "\n\n".join(tip.render() for tip in improvements))
        if improved_post:
            blocks.append(bold(f"✨ {titles['improved']}") + "\n\n" + improved_post)
        report = sanitize_html("\n\n".join(blocks), TELEGRAM_TEXT_LIMIT)
        chunks = self.render([f"📊 {bold(titles['report'])} ({overall}/{OVERALL_MAX})\n\n{block}"
                              if index == 0 else block
                              for index, block in enumerate(blocks)],
                             limit=CHUNK_SAFE_LIMIT)
        return report, chunks


default_audit = PostAuditService()


async def audit_post(user_id: int | None, post_text: str, lang: str = "uz",
                     **kwargs: Any) -> PostAuditResult:
    """Yordamchi funksiya: ``PostAuditService().audit_post(...)``."""
    return await PostAuditService().audit_post(user_id, post_text, lang, **kwargs)


__all__ = [
    "AUDIT_CRITERIA",
    "AUDIT_CRITERION_KEYS",
    "AuditCriterion",
    "CriterionScore",
    "ImprovementTip",
    "PostAuditResult",
    "PostAuditService",
    "audit_topic",
    "measure_post",
    "score_post_heuristics",
    "score_criterion",
    "overall_from_criteria",
    "grade_for",
    "score_bar",
    "audit_post",
    "default_audit",
]
