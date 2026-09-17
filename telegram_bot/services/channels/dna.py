"""🧠 CHANNEL DNA — uslubiy profil (PostAssist V2 — PHASE B, 2-band).

Kanalning kuzatilgan postlari (``channel_post_events``) asosida Channel DNA
profili hisoblanadi:

    average_post_length, emoji_level (kam / o'rtacha / ko'p), cta_style,
    formatting_style, sample_size, confidence_score

Kafolatlari:
  * Natija ``channel_intelligence_profiles`` jadvalida saqlanadi (UPSERT);
  * Postlar soni **5 tadan kam** bo'lsa — profil hisoblanmaydi:
    ``confidence='low'`` va ``"Yetarli ma'lumot yo'q (kamida 5 ta post
    kerak)"`` holati qaytadi (soxta raqamlar uydirmaslik);
  * AI orkestrator post generatsiya qilganda (``context`` da ``channel_id``
    bo'lsa va kanal AYNAN shu foydalanuvchining bo'lsa — IDOR himoyasi) DNA
    ixcham system-prompt bloki sifatida ulanadi;
  * Barcha hisob funksiyalari PURE (DB'siz) — deterministik va testlanadi.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

#: DNA hisoblash uchun minimal post soni.
MIN_POSTS_FOR_DNA = 5

#: Yetarli ma'lumot bo'lmaganda qaytariladigan qat'iy xabar (uz).
INSUFFICIENT_DATA_MESSAGE = "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)"


# ---------------------------------------------------------------------------
# Hisoblash (PURE funksiya — deterministik)
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
# UI / prompt yorliqlari (uz / ru / en)
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
# AI system-prompt bloki (ixcham ko'rinish)
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


def build_dna_system_prompt(profile: dict, lang: str = "uz") -> str:
    """Saqlangan DNA profilidan ixcham system-prompt bloki.

    Profil bo'sh/kam ma'lumotda bo'sh qaytadi (soxta uslub uydirmaslik).
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
    if sample is None or int(sample) < MIN_POSTS_FOR_DNA:
        return ""
    length = profile.get("average_post_length")
    if length is None:
        return ""
    labels = DNA_LABELS[code]
    return _DNA_PROMPT_TEMPLATES[code].format(
        length=int(length),
        emoji=labels["emoji_level"].get(str(profile.get("emoji_level") or ""), "medium"),
        cta=labels["cta_style"].get(str(profile.get("cta_style") or ""), "sometimes"),
        fmt=labels["formatting_style"].get(str(profile.get("formatting_style") or ""), "balanced"),
    )


# ---------------------------------------------------------------------------
# DB + ownership bilan asinxron xizmatlar
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
        if not isinstance(profile, dict) or not profile:
            return ctx
        sample = profile.get("sample_size")
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
