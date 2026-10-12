# -*- coding: utf-8 -*-
"""AI so'rov konteksti: foydalanuvchi, kanal, amal turi va model izi.

Nega kerak
----------
Telegram handler'lari AI'ni chaqirganda ``user_id``/``channel_id`` ko'pincha
funksiya argumentlari orqali uzatilmaydi (eski \"legacy\" zanjir). Shuning
uchun telemetriya va xarajat/byudjet qatlami kontekstni ``contextvars``
orqali oladi:

* :func:`usage_scope` — update darajasida (``main.py``) ``user_id`` ni
  o'rnatadi; AI chaqiruvi shu kontekstni o'qiydi. Kontekst asyncio task
  chegarasidan o'tadi (``asyncio.wait_for`` / ``create_task`` nusxa oladi),
  shuning uchun ichki provayder chaqiruvlari ham uni ko'radi.
* :func:`action_type_for` — vazifa → kanonik amal turi:
  ``post`` | ``vision`` | ``voice`` | ``audit``.
* :class:`ModelNote` — provayder adapteri ishlatgan HAQIQIY model nomini
  qayd etadi (``utils.ai_agent._call_*`` har bir urinishda :func:`note_model`
  chaqiradi). Model aniqlanmasa — bo'sh satr (soxta nom yozilmaydi).
* :func:`prefer_cheap_models` — oddiy matn transformatsiyasi uchun model
  ro'yxatini arzon modellar oldiga suradi (yangi model qo'shilmaydi, faqat
  tartib o'zgaradi).

Bu modul HECH QANDAY tashqi import qilmaydi (sikl yo'q, testda yengil).
"""

from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence

# ---------------------------------------------------------------------------
# Amal turlari (action_type) — STEP 1 telemetriya taksonomiyasi
# ---------------------------------------------------------------------------
ACTION_POST = "post"
ACTION_VISION = "vision"
ACTION_VOICE = "voice"
ACTION_AUDIT = "audit"
ACTION_TYPES: tuple[str, ...] = (ACTION_POST, ACTION_VISION, ACTION_VOICE, ACTION_AUDIT)

_VISION_TASKS = frozenset({
    "vision", "image_post", "image_analysis", "photo_post", "photo_check",
    "image_to_post", "describe_image",
})
_VOICE_TASKS = frozenset({
    "voice_post", "voice", "voice_to_post", "transcribe", "stt", "speech",
})
_AUDIT_TASKS = frozenset({
    "audit", "audit_post", "post_score", "score", "analyze", "post_audit",
    "improve", "improve_post", "channel_analysis", "deep_analysis",
})
_AUDIT_OPERATIONS = frozenset({"post_score"})
_VISION_OPERATIONS = frozenset({"image_post"})
_VOICE_OPERATIONS = frozenset({"voice_post"})


def _norm(value) -> str:
    return re.sub(r"[\s\-]+", "_", str(value or "").strip().lower())


def action_type_for(task=None, operation_type=None) -> str:
    """Vazifa (yoki kvota ``operation_type``) → kanonik amal turi.

    Ustuvorlik: aniq ``task`` nomi → ``operation_type`` → standart ``post``.
    """
    key = _norm(task)
    op = _norm(operation_type)
    if op in ACTION_TYPES and not key:
        # Kanonik amal nomi to'g'ridan-to'g'ri berilgan (fallback yo'li).
        return op
    if key in _VISION_TASKS:
        return ACTION_VISION
    if key in _VOICE_TASKS:
        return ACTION_VOICE
    if key in _AUDIT_TASKS:
        return ACTION_AUDIT
    if op in _VISION_OPERATIONS:
        return ACTION_VISION
    if op in _VOICE_OPERATIONS:
        return ACTION_VOICE
    if op in _AUDIT_OPERATIONS:
        return ACTION_AUDIT
    return ACTION_POST


#: Oddiy matn transformatsiyalari — arzon/tez modelga yo'naltiriladi.
#: (Qisqartirish, qayta yozish, uslub, format, teglar, sarlavha, CTA ...).
#: Post yaratish (generatsiya) va audit/tahlil bu ro'yxatga KIRMAYDI.
CHEAP_TRANSFORM_TASKS = frozenset({
    "rewrite", "restyle", "qayta_yozish", "shorten", "expand", "format",
    "tone", "fix", "hashtags", "cta", "caption", "title", "sarlavha",
    "headline", "extract_time",
})

MODEL_TIER_STANDARD = "standard"
MODEL_TIER_CHEAP = "cheap"


def model_tier_for(task=None) -> str:
    """Vazifa uchun model darajasi (oddiy transformatsiya → ``cheap``)."""
    return MODEL_TIER_CHEAP if _norm(task) in CHEAP_TRANSFORM_TASKS else MODEL_TIER_STANDARD


# ---------------------------------------------------------------------------
# Kontekst (usage scope)
# ---------------------------------------------------------------------------
@dataclass
class UsageScope:
    """Joriy AI so'rovi kontekstining o'zgarmas-bo'lmagan yig'indisi."""

    user_id: int | None = None
    channel_id: int | None = None
    action_type: str | None = None
    #: Model darajasi (``cheap`` — oddiy transformatsiya); ``None`` — standart.
    model_tier: str | None = None
    #: ``True`` — ichki (takroriy) chaqiruv: telemetriya bu yerda yozilmaydi.
    suppress_recording: bool = False


_SCOPE: contextvars.ContextVar[UsageScope | None] = contextvars.ContextVar(
    "ai_usage_scope", default=None)
_MODEL_NOTE: contextvars.ContextVar["ModelNote | None"] = contextvars.ContextVar(
    "ai_model_note", default=None)


def current_scope() -> UsageScope | None:
    """Joriy kontekst (yo'q bo'lsa ``None``)."""
    return _SCOPE.get()


@contextmanager
def usage_scope(*, user_id: int | None = None, channel_id: int | None = None,
                action_type: str | None = None, model_tier: str | None = None,
                suppress_recording: bool | None = None) -> Iterator[UsageScope]:
    """Kontekstni o'rnatadi; chiqishda avvalgi holatni tiklaydi.

    Ichki scope berilgan maydonlarni meros qilib oladi (faqat berilganlari
    o'zgaradi), shuning uchun ichki chaqiruv tashqi ``user_id`` ni yo'qotmaydi.
    """
    parent = _SCOPE.get()
    scope = UsageScope(
        user_id=user_id if user_id is not None else (parent.user_id if parent else None),
        channel_id=channel_id if channel_id is not None else (parent.channel_id if parent else None),
        action_type=action_type or (parent.action_type if parent else None),
        model_tier=model_tier or (parent.model_tier if parent else None),
        suppress_recording=(bool(suppress_recording) if suppress_recording is not None
                            else (parent.suppress_recording if parent else False)),
    )
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


# ---------------------------------------------------------------------------
# Haqiqiy model izi
# ---------------------------------------------------------------------------
class ModelNote:
    """Bitta provayder urinishi ishlatgan model nomi (mutable holder)."""

    __slots__ = ("model",)

    def __init__(self, model: str = "") -> None:
        self.model = str(model or "")


@contextmanager
def model_note() -> Iterator[ModelNote]:
    """Yangi model-izi holderini o'rnatadi (provayder urinishi uchun)."""
    holder = ModelNote()
    token = _MODEL_NOTE.set(holder)
    try:
        yield holder
    finally:
        _MODEL_NOTE.reset(token)


def note_model(model) -> None:
    """Provayder adapteri ishlatayotgan modelni qayd etadi (yo'q bo'lsa — jim)."""
    holder = _MODEL_NOTE.get()
    if holder is not None and model:
        holder.model = str(model)


# ---------------------------------------------------------------------------
# Arzon model tartibi
# ---------------------------------------------------------------------------
#: Arzon/tez model belgilari — faqat ALOHIDA token sifatida (``gemini`` ichidagi
#: ``mini`` kabi qismiy mosliklar e'tiborga olinmaydi).
_CHEAP_MARKERS = re.compile(
    r"(?<![a-z])(?:8b|7b|mini|lite|instant|small|nemo|haiku|fast|flash(?!-?pro))(?![a-z])",
    re.IGNORECASE,
)


def prefer_cheap_models(models: Sequence[str], tier: str | None = None) -> list[str]:
    """``cheap`` darajada arzon (kichik/tez) modellarni oldinga suradi.

    Tartib barqaror: arzonlar o'z ichida, qolganlari o'z ichida avvalgi
    tartibini saqlaydi. ``tier`` standart bo'lsa ro'yxat o'zgarmaydi.
    Joriy kontekst tiri ham hisobga olinadi (``tier`` berilmasa).
    """
    items = [str(m) for m in (models or []) if m]
    effective = tier
    if effective is None:
        scope = _SCOPE.get()
        effective = scope.model_tier if scope else None
    if effective != MODEL_TIER_CHEAP:
        return items
    cheap = [m for m in items if _CHEAP_MARKERS.search(m)]
    rest = [m for m in items if m not in cheap]
    return cheap + rest


__all__ = [
    "ACTION_AUDIT",
    "ACTION_POST",
    "ACTION_TYPES",
    "ACTION_VISION",
    "ACTION_VOICE",
    "CHEAP_TRANSFORM_TASKS",
    "MODEL_TIER_CHEAP",
    "MODEL_TIER_STANDARD",
    "ModelNote",
    "UsageScope",
    "action_type_for",
    "current_scope",
    "model_note",
    "model_tier_for",
    "note_model",
    "prefer_cheap_models",
    "usage_scope",
]
