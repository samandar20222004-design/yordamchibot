"""Privacy-conscious audience question and ``Comment -> Content`` engine.

Raw comments are analysed in memory only.  The optional persistence hook stores
an opaque hash and aggregate counters, never a commenter id, username, phone,
email, URL, or raw comment.  This makes the feature useful for repeated-question
insights without turning the bot into a personal-data archive.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", re.I)
_URL_RE = re.compile(r"(?:https?://|www\.)\S+", re.I)
_PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)")
_HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,64}")
_NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,:/-]\d+)*(?!\w)")
_SPACE_RE = re.compile(r"\s+")

QUESTION_WORDS = {
    "uz": ("qanday", "qachon", "qancha", "nima", "nega", "qayer", "mumkin", "bormi", "qilsam"),
    "ru": ("как", "когда", "сколько", "что", "почему", "где", "можно", "есть"),
    "en": ("how", "when", "how much", "what", "why", "where", "can", "is there"),
}

FAQ_LABELS = {
    "uz": {"access": "Kirish va foydalanish", "price": "Narx va tarif", "delivery": "Yetkazib berish", "support": "Yordam", "general": "Ko'p beriladigan savol"},
    "ru": {"access": "Доступ и использование", "price": "Цена и тариф", "delivery": "Доставка", "support": "Поддержка", "general": "Частый вопрос"},
    "en": {"access": "Access and usage", "price": "Pricing and plans", "delivery": "Delivery", "support": "Support", "general": "Frequently asked question"},
}


@dataclass(frozen=True)
class QuestionSignal:
    question_hash: str
    redacted_text: str
    category: str
    language: str
    is_question: bool

    def as_dict(self) -> dict:
        return {"question_hash": self.question_hash, "question": self.redacted_text,
                "redacted_question": self.redacted_text, "category": self.category,
                "language": self.language, "is_question": self.is_question}


@dataclass(frozen=True)
class AudienceQuestion:
    question_hash: str
    question: str
    category: str
    language: str
    count: int
    faq_candidate: bool

    def as_dict(self) -> dict:
        return {"question_hash": self.question_hash, "question": self.question,
                "redacted_question": self.question, "category": self.category,
                "language": self.language, "count": self.count,
                "occurrences": self.count, "faq_candidate": self.faq_candidate}


def detect_language(text: str, default: str = "uz") -> str:
    raw = str(text or "").lower()
    if any(ch in raw for ch in "ёыэъ") or any(w in raw.split() for w in QUESTION_WORDS["ru"]):
        return "ru"
    if any(w in raw.split() for w in QUESTION_WORDS["en"]):
        return "en"
    return default if default in QUESTION_WORDS else "uz"


def redact_personal_data(text: Any) -> str:
    """Remove common personal identifiers before a question is retained/displayed."""
    value = str(text or "")
    value = _URL_RE.sub(" [link] ", value)
    value = _EMAIL_RE.sub(" [contact] ", value)
    value = _PHONE_RE.sub(" [number] ", value)
    value = _HANDLE_RE.sub(" [user] ", value)
    value = _NUMBER_RE.sub(" [number] ", value)
    value = _SPACE_RE.sub(" ", value).strip()
    # Telegram questions are short; this bound also prevents accidental large
    # payloads being copied into an inline card or AI prompt.
    return value[:500]


# aliases used by integrations
def anonymize_comment(text: Any) -> str:
    return redact_personal_data(text)


def normalize_question(text: Any) -> str:
    value = redact_personal_data(text).casefold()
    # Identifiers are redacted for display, but placeholders must not split an
    # otherwise identical audience question into separate clusters.
    value = re.sub(r"\[(?:contact|user|number|link)\]", " ", value)
    value = re.sub(r"\b(?:email|e-mail|почта|contact)\b", " ", value)
    value = re.sub(r"[^\w\s?'-]", " ", value, flags=re.UNICODE)
    value = _SPACE_RE.sub(" ", value).strip(" ?!.,")
    return value[:500]


def question_fingerprint(text: Any) -> str:
    """Opaque, stable fingerprint; never use a raw comment as a DB key."""
    normalized = normalize_question(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else ""


def classify_question(text: Any, lang: str | None = None) -> str:
    value = str(text or "").casefold()
    if any(token in value for token in ("narx", "qancha", "price", "cost", "сколько", "цена", "тариф")):
        return "price"
    if any(token in value for token in ("yetkaz", "delivery", "достав", "qachon kel", "when will")):
        return "delivery"
    if any(token in value for token in ("yordam", "support", "поддерж", "muammo", "error", "xato", "не работает")):
        return "support"
    if any(token in value for token in ("kirish", "qanday foydalan", "how to", "как пользоваться", "login", "parol")):
        return "access"
    return "general"


def is_question(text: Any, lang: str | None = None) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    language = lang or detect_language(value)
    lower = value.casefold()
    return "?" in value or any(word in lower.split() for word in QUESTION_WORDS.get(language, QUESTION_WORDS["uz"]))


def extract_question_signal(comment: Any, lang: str | None = None) -> QuestionSignal | None:
    """Extract a redacted question from a string or Telegram-like object."""
    if isinstance(comment, dict):
        raw = comment.get("text") or comment.get("comment") or comment.get("body") or comment.get("caption") or ""
    else:
        raw = getattr(comment, "text", None) or getattr(comment, "caption", None) or comment or ""
    redacted = redact_personal_data(raw)
    if not is_question(redacted, lang):
        return None
    language = lang or detect_language(redacted)
    return QuestionSignal(question_fingerprint(redacted), redacted, classify_question(redacted, language), language, True)


def _iter_texts(comments: Iterable[Any]) -> Iterable[Any]:
    for comment in comments or ():
        # Do not inspect or return author fields.  Only the message text is used.
        yield comment


def analyze_repeated_questions(comments: Iterable[Any], *, min_occurrences: int = 2,
                               lang: str | None = None) -> list[dict]:
    """Cluster repeated questions and return only redacted, aggregate records."""
    grouped: dict[str, list[QuestionSignal]] = defaultdict(list)
    for comment in _iter_texts(comments):
        signal = extract_question_signal(comment, lang)
        if signal and signal.question_hash:
            grouped[signal.question_hash].append(signal)
    result: list[AudienceQuestion] = []
    for fingerprint, signals in grouped.items():
        count = len(signals)
        if count < max(1, int(min_occurrences)):
            continue
        first = signals[0]
        result.append(AudienceQuestion(fingerprint, first.redacted_text, first.category,
                                       first.language, count, count >= 2))
    result.sort(key=lambda item: (-item.count, item.category, item.question_hash))
    return [item.as_dict() for item in result]

# Familiar names for callers/tests.
find_repeated_questions = analyze_repeated_questions
extract_repeated_questions = analyze_repeated_questions


def build_faq_draft(repeated_questions: Iterable[dict], *, lang: str = "uz",
                    title: str | None = None) -> dict | None:
    """Build an FAQ/guide draft from aggregate questions, without inventing answers.

    Answers are deliberately framed as editorial prompts.  An editor must fill
    the answer before publishing, so the engine cannot publish an unsafe or
    fabricated promise from a comment alone.
    """
    code = lang if lang in FAQ_LABELS else "uz"
    items = [q for q in (repeated_questions or ()) if isinstance(q, dict) and int(q.get("count", q.get("occurrences", 0)) or 0) >= 2]
    if not items:
        return None
    heading = title or {"uz": "Ko'p so'raladigan savollar", "ru": "Частые вопросы", "en": "Frequently asked questions"}[code]
    lines = [heading]
    for item in items[:10]:
        question = redact_personal_data(item.get("question") or item.get("redacted_question") or "")
        if not question:
            continue
        category = FAQ_LABELS[code].get(str(item.get("category") or "general"), FAQ_LABELS[code]["general"])
        prompt = {
            "uz": "Javobni muharrir to'ldiradi.",
            "ru": "Ответ должен проверить редактор.",
            "en": "An editor should complete this answer.",
        }[code]
        lines.append(f"\n<b>{category}</b>\n❓ {question}\n💡 {prompt}")
    content = "\n".join(lines).strip()
    if len(content) <= len(heading):
        return None
    return {"ok": True, "type": "faq", "title": heading, "content": content,
            "question_count": len(items[:10]), "requires_editor_review": True,
            "source": "repeated_audience_questions"}


def suggest_comment_to_content(repeated_questions: Iterable[dict], *, lang: str = "uz") -> dict:
    draft = build_faq_draft(repeated_questions, lang=lang)
    if not draft:
        return {"suggested": False, "reason": "not_enough_repeated_questions", "draft": None}
    return {"suggested": True, "reason": "repeated_questions", "draft": draft}

comment_to_content = suggest_comment_to_content
generate_faq_draft = build_faq_draft
generate_faq_from_questions = build_faq_draft
generate_faq_post = build_faq_draft


async def analyze_comments(channel_id: str | int, user_id: int, comments: Iterable[Any], *,
                           db_module: Any = None, min_occurrences: int = 2,
                           lang: str = "uz") -> dict:
    """Analyse comments after ownership verification and optionally persist aggregates."""
    db = db_module or _load_database()
    channel = str(channel_id or "").strip()
    if not channel or db is None:
        return {"ok": False, "error": "db_unavailable", "questions": [], "privacy": "raw_comments_not_stored"}
    owner_fn = getattr(db, "get_channel_owner_id", None)
    try:
        owner = await _call(db, owner_fn, channel) if callable(owner_fn) else None
        if owner is None or int(owner) != int(user_id):
            # A team member may have analyst rights; use the role service as a
            # second, explicit authorization path instead of silently opening IDOR.
            from services.channels.team import check_permission
            if not await check_permission(channel, user_id, "view_analytics", db):
                return {"ok": False, "error": "forbidden", "questions": [], "privacy": "raw_comments_not_stored"}
    except Exception:
        return {"ok": False, "error": "forbidden", "questions": [], "privacy": "raw_comments_not_stored"}
    questions = analyze_repeated_questions(comments, min_occurrences=min_occurrences, lang=lang)
    saver = getattr(db, "upsert_audience_question", None)
    if callable(saver):
        for item in questions:
            try:
                await _call(db, saver, channel, item["question_hash"], item["category"], item["count"])
            except Exception:
                logger.debug("Audience aggregate persistence failed", exc_info=True)
    return {"ok": True, "channel_id": channel, "questions": questions,
            "suggestion": suggest_comment_to_content(questions, lang=lang),
            "privacy": "raw_comments_not_stored"}


async def _call(db, fn, *args, **kwargs):
    runner = getattr(db, "run_db", None)
    if callable(runner):
        return await runner(fn, *args, **kwargs)
    value = fn(*args, **kwargs)
    return await value if asyncio.iscoroutine(value) else value


class AudienceQuestionEngine:
    analyze = staticmethod(analyze_repeated_questions)
    build_faq = staticmethod(build_faq_draft)
    comment_to_content = staticmethod(suggest_comment_to_content)

    async def analyze_channel(self, channel_id, user_id, comments, *, db_module=None, lang="uz"):
        return await analyze_comments(channel_id, user_id, comments, db_module=db_module, lang=lang)


class CommentInsightService(AudienceQuestionEngine):
    pass


class CommentAnalysisService(AudienceQuestionEngine):
    pass


__all__ = [
    "AudienceQuestion", "AudienceQuestionEngine", "CommentAnalysisService", "CommentInsightService", "QuestionSignal", "analyze_comments",
    "analyze_repeated_questions", "anonymize_comment", "build_faq_draft",
    "classify_question", "comment_to_content", "detect_language", "extract_question_signal",
    "extract_repeated_questions", "find_repeated_questions", "generate_faq_draft", "generate_faq_from_questions", "generate_faq_post",
    "is_question", "normalize_question", "question_fingerprint", "redact_personal_data",
    "suggest_comment_to_content",
]
