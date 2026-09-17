"""♻️ CONTENT RECYCLE — eski, yaxshi ko'rsatkichli postlarni YANGILASH (PHASE D, 13-band).

Muammo: kanalda 14+ kun oldin chiqqan, yaxshi natija bergan postlar bor —
ularni **ko'r-ko'rona qayta chiqarish (repost) TAQIQLANADI**. Xizmat esa
AI yordamida:

  * yangi **hook** (diqqatni ushlovchi birinchi qator),
  * yangi **sarlavha**,
  * yangi **CTA** (chaqiriq)

bilan "yangilangan post" yaratadi. Faktlar saqlanadi, so'zma-so'z takrorlash
esa rad etiladi (o'xshashlik chegarasi — ``MAX_REUSE_SIMILARITY``).

Zanjir::

    channel_posts_history (+reaksiyalar)
        → select_recycle_candidates (14+ kun, yaxshi ko'rsatkich)
        → build_recycle_prompt (untrusted eski post + Channel DNA)
        → AI javobi (hook/title/body/cta JSON)
        → compose_first (yangi post) + blind-repost tekshiruvi
        → handler: preview + [📅 Rejalashtirish] / [🚀 Hozir chiqarish]

Kafolatlar:
  * ko'rsatkich ma'lumoti bo'lmasa SOXTA raqamlar uydirilmaydi —
    ``metrics_available=False`` va ochiq izoh qaytadi;
  * AI javobi buzuq bo'lsa — post KO'RSATILMAYDI (yarim-yorti natija yo'q);
  * IDOR: kanal egaligi ``get_channel_owner_id`` bilan tekshiriladi;
  * barcha hisob-kitob funksiyalari PURE (DB'siz) va deterministik.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Iterable

import pytz

from ..ai.smm_common import SMMFeatureService, clip, extract_json, sanitize_html, strip_html
from ..channels.duplicate_detector import (
    containment_ratio,
    jaccard_similarity,
    normalize_text,
    tokenize,
)

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

# ---------------------------------------------------------------------------
# QOIDALAR (speks: 14+ kun, yaxshi ko'rsatkich)
# ---------------------------------------------------------------------------
MIN_AGE_DAYS = 14                 # speks: 14 kundan eski postlar
MIN_POST_CHARS = 60               # juda qisqa postlar recycle qilinmaydi
MIN_VIEWS_ABSOLUTE = 50           # mutlaq ko'rish chegarasi
MIN_VIEWS_RATIO = 0.5             # kanal o'rtachasiga nisbatan ulush
MIN_REACTIONS = 3                 # yoki reaksiyalar soni
DEFAULT_LIMIT = 5
MAX_LIMIT = 10
MAX_REUSE_SIMILARITY = 0.75       # bundan yuqori o'xshashlik == ko'r-ko'rona repost
MAX_GENERATION_ATTEMPTS = 2       # 1 urinish + 1 qayta urinish (qat'iy sikl)
MAX_ORIGINAL_CHARS = 3000

ERR_FORBIDDEN = "FORBIDDEN"
ERR_DB_UNAVAILABLE = "DB_UNAVAILABLE"
ERR_NO_CANDIDATES = "NO_CANDIDATES"
ERR_AI_FAILED = "AI_FAILED"
ERR_BLIND_REPOST = "BLIND_REPOST"
ERR_QUOTA = "QUOTA_DENIED"


# ---------------------------------------------------------------------------
# 1) PURE: NOMZODLARNI TANLASH
# ---------------------------------------------------------------------------
def _as_aware(moment: Any) -> datetime | None:
    """Vaqtni aware datetime'ga keltiradi (naive → Toshkent zonasi)."""
    if moment is None:
        return None
    if isinstance(moment, datetime):
        value = moment
    else:
        text = str(moment).strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return tashkent_tz.localize(value)
    return value


def post_age_days(post: dict, *, now: datetime | None = None) -> float | None:
    """Post yoshi (kunlarda); vaqt o'qilmasa ``None``."""
    moment = now or datetime.now(tashkent_tz)
    if moment.tzinfo is None:
        moment = tashkent_tz.localize(moment)
    published = _as_aware((post or {}).get("post_date")
                          or (post or {}).get("date")
                          or (post or {}).get("created_at"))
    if published is None:
        return None
    return (moment - published).total_seconds() / 86400.0


def engagement_score(views: int, reactions: int = 0,
                     avg_views: float = 0.0) -> float:
    """Yengil ko'rsatkich balli (PURE, deterministik).

    ``views`` kanal o'rtachasiga nisbatan normallashtiriladi + reaksiyalar
    kichik vazn bilan qo'shiladi. Ma'lumot bo'lmasa 0.0 (soxta raqam yo'q).
    """
    try:
        v = max(0, int(views or 0))
    except (TypeError, ValueError):
        v = 0
    try:
        r = max(0, int(reactions or 0))
    except (TypeError, ValueError):
        r = 0
    base = float(avg_views or 0.0)
    ratio = (v / base) if base > 0 else 0.0
    return round(ratio + min(r, 100) * 0.05, 4)


def select_recycle_candidates(
    posts: Iterable[dict],
    *,
    min_age_days: int = MIN_AGE_DAYS,
    min_views_ratio: float = MIN_VIEWS_RATIO,
    limit: int = DEFAULT_LIMIT,
    now: datetime | None = None,
) -> dict:
    """14+ kunlik va yaxshi ko'rsatkichli postlarni tanlaydi (PURE).

    Qaytadi::

        {"candidates": [{"post_id":..., "text":..., "views":..., "age_days":...,
                         "score":..., "quality": "good"|"unknown",
                         "metrics_available": True}],
         "metrics_available": bool, "avg_views": float, "scanned": int}
    """
    moment = now or datetime.now(tashkent_tz)
    if moment.tzinfo is None:
        moment = tashkent_tz.localize(moment)

    prepared: list[dict] = []
    for raw in posts or []:
        post = dict(raw or {})
        text = strip_html(post.get("text") or post.get("content") or "").strip()
        if len(text) < MIN_POST_CHARS:
            continue
        age = post_age_days(post, now=moment)
        if age is None or age < float(min_age_days):
            continue
        try:
            views = max(0, int(post.get("views") or 0))
        except (TypeError, ValueError):
            views = 0
        try:
            reactions = max(0, int(post.get("reactions") or 0))
        except (TypeError, ValueError):
            reactions = 0
        prepared.append({
            "post_id": post.get("id") or post.get("post_id") or post.get("message_id"),
            "message_id": post.get("message_id"),
            "text": text[:MAX_ORIGINAL_CHARS],
            "views": views,
            "reactions": reactions,
            "age_days": round(float(age), 1),
            "post_date": str(post.get("post_date") or post.get("date") or ""),
        })

    views_values = [item["views"] for item in prepared if item["views"] > 0]
    metrics_available = bool(views_values) or any(item["reactions"] > 0
                                                  for item in prepared)
    avg_views = (sum(views_values) / len(views_values)) if views_values else 0.0
    threshold = max(float(MIN_VIEWS_ABSOLUTE), avg_views * float(min_views_ratio))

    candidates: list[dict] = []
    for item in prepared:
        if metrics_available:
            good = (item["views"] >= threshold
                    or item["reactions"] >= MIN_REACTIONS)
            if not good:
                continue
            item["quality"] = "good"
        else:
            # Ko'rsatkich ma'lumoti yo'q: soxta baho BERILMAYDI — nomzod
            # sifatida qoldiriladi, lekin sifat "unknown" deb belgilanadi.
            item["quality"] = "unknown"
        item["score"] = engagement_score(item["views"], item["reactions"],
                                         avg_views)
        item["metrics_available"] = metrics_available
        candidates.append(item)

    candidates.sort(key=lambda row: (-float(row.get("score") or 0.0),
                                     -float(row.get("age_days") or 0.0)))
    return {
        "candidates": candidates[:max(1, min(int(limit), MAX_LIMIT))],
        "metrics_available": metrics_available,
        "avg_views": round(avg_views, 1),
        "scanned": len(prepared),
        "threshold": round(threshold, 1),
    }


# ---------------------------------------------------------------------------
# 2) PURE: YANGILANGAN POST + KO'R-KO'RONA REPOST TEKSHIRUVI
# ---------------------------------------------------------------------------
def reuse_similarity(original: str, generated: str) -> float:
    """Eski va yangi post o'xshashligi (0..1) — eng katta ko'rsatkich.

    ``jaccard`` va ``containment`` dan maksimal olinadi: eski postning
    katta qismi ko'chirilgan bo'lsa — bu ko'r-ko'rona repost belgisi.
    """
    left = normalize_text(strip_html(original))
    right = normalize_text(strip_html(generated))
    if not left or not right:
        return 0.0
    jaccard = jaccard_similarity(left, right)
    containment = containment_ratio(tokenize(left), tokenize(right))
    return round(max(float(jaccard), float(containment)), 4)


def is_blind_repost(original: str, generated: str,
                    threshold: float = MAX_REUSE_SIMILARITY) -> dict:
    """Yangi post eski postning ko'r-ko'rona nusxasimi?"""
    score = reuse_similarity(original, generated)
    return {"blind": score >= float(threshold), "score": score,
            "threshold": float(threshold)}


def compose_refreshed(hook: str, title: str, body: str, cta: str) -> str:
    """AI qismlaridan tayyor post matnini yig'adi (PURE)."""
    parts: list[str] = []
    hook_line = strip_html(hook).strip()
    title_line = strip_html(title).strip()
    body_text = strip_html(body).strip()
    cta_line = strip_html(cta).strip()
    if hook_line:
        parts.append(hook_line)
    if title_line and normalize_text(title_line) not in normalize_text(hook_line):
        parts.append(f"<b>{title_line}</b>")
    if body_text:
        parts.append(body_text)
    if cta_line:
        parts.append(cta_line)
    return "\n\n".join(parts).strip()


def parse_recycled_payload(payload: Any) -> dict:
    """AI JSON javobini (hook/title/body/cta) o'qiydi (PURE, fail-soft)."""
    data = extract_json(payload) if not isinstance(payload, dict) else dict(payload)
    if not isinstance(data, dict):
        return {"ok": False, "hook": "", "title": "", "body": "", "cta": ""}
    recycled = data.get("refreshed") if isinstance(data.get("refreshed"), dict) else data
    hook = str(recycled.get("hook") or "").strip()
    title = str(recycled.get("title") or "").strip()
    body = str(recycled.get("body") or recycled.get("text") or "").strip()
    cta = str(recycled.get("cta") or "").strip()
    text = compose_refreshed(hook, title, body, cta)
    return {"ok": bool(len(strip_html(text)) >= 40), "hook": hook,
            "title": title, "body": body, "cta": cta, "text": text}


RECYCLE_SYSTEM_PROMPT = {
    "uz": (
        "Siz kontent muharririsiz. Sizga kanalning ESKI (14+ kun oldin "
        "chiqqan) posti beriladi. Uni YANGILANG: yangi hook, yangi sarlavha "
        "va yangi CTA yozing. QAT'IY QOIDALAR: (1) ko'r-ko'rona repost "
        "taqiqlanadi — jumlalarni so'zma-so'z ko'chirmang, tuzilishni "
        "o'zgartiring; (2) faqat eski postdagi faktlarga tayaning, yangi "
        "fakt/raqam/narx o'ylab topmang; (3) til va ohang kanal uslubiga mos "
        "bo'lsin. Javobni FAQAT JSON ko'rinishida qaytaring:\n"
        '{"refreshed": {"hook": "...", "title": "...", "body": "...", '
        '"cta": "..."}}'
    ),
    "ru": (
        "Вы контент-редактор. Вам даётся СТАРЫЙ пост канала (14+ дней назад). "
        "ОБНОВИТЕ его: новый хук, новый заголовок и новый CTA. СТРОГИЕ "
        "ПРАВИЛА: (1) слепой репост запрещён — не копируйте фразы дословно, "
        "измените структуру; (2) опирайтесь только на факты старого поста, "
        "не выдумывайте факты/цифры/цены; (3) стиль должен соответствовать "
        "каналу. Ответ верните ТОЛЬКО в JSON:\n"
        '{"refreshed": {"hook": "...", "title": "...", "body": "...", '
        '"cta": "..."}}'
    ),
    "en": (
        "You are a content editor. You are given an OLD channel post (14+ days "
        "ago). REFRESH it: a new hook, a new title and a new CTA. STRICT "
        "RULES: (1) blind reposting is forbidden — do not copy sentences "
        "verbatim, change the structure; (2) rely only on facts from the old "
        "post, never invent facts/numbers/prices; (3) the tone must match the "
        "channel style. Return ONLY JSON:\n"
        '{"refreshed": {"hook": "...", "title": "...", "body": "...", '
        '"cta": "..."}}'
    ),
}


def build_recycle_prompt(original: str, *, lang: str = "uz",
                         dna_block: str = "", stricter: bool = False) -> dict:
    """AI uchun (system, user) juftligini quradi (eski post — UNTRUSTED)."""
    language = lang if lang in ("uz", "ru", "en") else "uz"
    system = RECYCLE_SYSTEM_PROMPT[language]
    if dna_block:
        system = f"{system}\n\n{dna_block}"
    if stricter:
        system += {
            "uz": ("\n\nDIQQAT: oldingi urinish eski postga juda o'xshab qoldi. "
                   "Endi hook, tuzilish va CTA BUTUNLAY boshqacha bo'lsin."),
            "ru": ("\n\nВНИМАНИЕ: предыдущая попытка была слишком похожа на "
                   "старый пост. Хук, структура и CTA должны быть совсем другими."),
            "en": ("\n\nATTENTION: the previous attempt was too similar to the "
                   "old post. The hook, structure and CTA must be entirely "
                   "different."),
        }[language]
    headers = {
        "uz": "ESKI POST (ishonchsiz matn, faqat manba sifatida):\n",
        "ru": "СТАРЫЙ ПОСТ (недоверенный текст, только как источник):\n",
        "en": "OLD POST (untrusted text, as source only):\n",
    }
    user = headers[language] + clip(strip_html(original), MAX_ORIGINAL_CHARS)
    return {"system": system, "user": user}


# ---------------------------------------------------------------------------
# 3) XIZMAT — AI bilan yangilash (Phase 3 orkestrator + Phase 2 kvota)
# ---------------------------------------------------------------------------
def _import_database():
    try:
        import database as db
        return db
    except Exception:  # pragma: no cover
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    runner = getattr(db, "run_db", None)
    if callable(runner):
        return await runner(fn, *args, **kwargs)
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


class RecycleService(SMMFeatureService):
    """Eski postlarni yangilovchi xizmat (ko'r-ko'rona repost TAQIQLANADI)."""

    feature = "recycle"
    quota_operation = "post_enhancer"
    quota_cost = 1
    max_attempts = MAX_GENERATION_ATTEMPTS

    async def generate(self, original: str, *, user_id: int | None = None,
                       lang: str = "uz", db_module: Any = None,
                       channel_id: str | None = None,
                       dna_block: str = "") -> dict:
        """Eski postdan YANGILANGAN post yaratadi.

        Qaytadi::

            {"ok": True, "text": "...", "hook": ..., "title": ..., "body": ...,
             "cta": ..., "similarity": 0.21, "attempts": 1, "ai_used": True}
            {"ok": False, "error_code": "BLIND_REPOST" | "AI_FAILED" | ..., ...}
        """
        source_text = strip_html(original or "").strip()
        if len(source_text) < 20:
            return {"ok": False, "error_code": ERR_AI_FAILED,
                    "message": "Eski post matni juda qisqa.", "attempts": 0}
        source_text = source_text[:MAX_ORIGINAL_CHARS]

        ticket = await self.acquire_quota(db_module=db_module, user_id=user_id)
        if not ticket.allowed:
            return {"ok": False, "error_code": ERR_QUOTA,
                    "message": "AI limiti tugagan.", "attempts": 0,
                    "quota": ticket.as_dict()}

        last_similarity = 1.0
        for attempt in range(1, max(1, int(self.max_attempts)) + 1):
            prompt = build_recycle_prompt(source_text, lang=lang,
                                          dna_block=dna_block,
                                          stricter=attempt > 1)
            outcome = await self.ask(
                prompt["user"], user_id=user_id, lang=lang,
                context={"feature": self.feature, "system_prompt": prompt["system"],
                         "untrusted_source": True, "channel_id": channel_id,
                         "smm_mode": "RECYCLE",
                         "smm_topic": clip(source_text, 120)},
            )
            if not outcome.ok:
                break
            parsed = parse_recycled_payload(outcome.text)
            if not parsed.get("ok"):
                continue
            check = is_blind_repost(source_text, parsed["text"])
            last_similarity = check["score"]
            if check["blind"]:
                self._log("recycle: %d-urinish juda o'xshash (%.2f) — qayta",
                          attempt, check["score"])
                continue
            return {
                "ok": True,
                "error_code": None,
                "text": sanitize_html(parsed["text"], 3600),
                "hook": clip(parsed["hook"], 300),
                "title": clip(parsed["title"], 300),
                "body": clip(parsed["body"], 3000),
                "cta": clip(parsed["cta"], 300),
                "similarity": check["score"],
                "threshold": check["threshold"],
                "attempts": attempt,
                "ai_used": True,
                "provider": outcome.provider,
                "quota": ticket.as_dict(),
            }

        await self.release_quota(ticket)
        blind = last_similarity >= MAX_REUSE_SIMILARITY
        return {
            "ok": False,
            "error_code": ERR_BLIND_REPOST if blind else ERR_AI_FAILED,
            "message": ("Eski post matni juda o'xshab qoldi — repost "
                        "taqiqlanadi." if blind else
                        "AI yangilangan postni bera olmadi."),
            "similarity": last_similarity,
            "attempts": max(1, int(self.max_attempts)),
            "quota": ticket.as_dict(),
        }


# ---------------------------------------------------------------------------
# 4) DB OQIMI — nomzodlarni yuklash + navbatga yozish
# ---------------------------------------------------------------------------
async def load_recycle_candidates(channel_id: str | int, user_id: int, *,
                                  db_module: Any = None, now: datetime | None = None,
                                  min_age_days: int = MIN_AGE_DAYS,
                                  limit: int = DEFAULT_LIMIT) -> dict:
    """Kanal uchun recycle nomzodlarini yuklaydi (IDOR himoyasi bilan)."""
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_recycle_candidates"):
        return {"ok": False, "error_code": ERR_DB_UNAVAILABLE,
                "message": "Baza mavjud emas.", "candidates": []}
    try:
        owner = await _db_call(db, db.get_channel_owner_id, str(channel_id))
    except Exception:  # noqa: BLE001 — fail-closed
        return {"ok": False, "error_code": ERR_DB_UNAVAILABLE,
                "message": "Kanal egaligi tekshirilmadi.", "candidates": []}
    try:
        if owner is None or int(owner) != int(user_id):
            return {"ok": False, "error_code": ERR_FORBIDDEN,
                    "message": "Kanal topilmadi.", "candidates": []}
    except (TypeError, ValueError):
        return {"ok": False, "error_code": ERR_FORBIDDEN,
                "message": "Kanal topilmadi.", "candidates": []}

    try:
        rows = await _db_call(db, db.get_recycle_candidates, str(channel_id),
                              int(min_age_days), int(MAX_LIMIT) * 3)
    except Exception:  # noqa: BLE001
        logger.exception("Recycle: nomzodlarni o'qishda xato")
        return {"ok": False, "error_code": ERR_DB_UNAVAILABLE,
                "message": "Postlar tarixi o'qilmadi.", "candidates": []}

    result = select_recycle_candidates(rows or [], min_age_days=min_age_days,
                                       limit=limit, now=now)
    if not result["candidates"]:
        return {"ok": False, "error_code": ERR_NO_CANDIDATES,
                "message": ("14+ kun oldin chiqqan, yaxshi ko'rsatkichli post "
                            "topilmadi."),
                "candidates": [], "metrics_available": result["metrics_available"]}
    return {"ok": True, "error_code": None, "message": None,
            "candidates": result["candidates"],
            "metrics_available": result["metrics_available"],
            "avg_views": result["avg_views"]}


async def schedule_recycled_post(db_module: Any, user_id: int,
                                 channel_id: str | int, text: str,
                                 scheduled_time: datetime) -> int:
    """Yangilangan postni navbatga yozadi (``add_post`` — yagona yozish nuqtasi)."""
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "add_post"):
        return 0
    content = strip_html(text or "").strip()
    if not content:
        return 0
    try:
        post_id = await _db_call(db, db.add_post, user_id=int(user_id),
                                 channel_id=str(channel_id), post_type="text",
                                 content=text, file_id=None,
                                 scheduled_time=scheduled_time)
    except Exception:  # noqa: BLE001
        logger.exception("Recycle: navbatga yozishda xato")
        return 0
    return int(post_id or 0)


__all__ = [
    "MIN_AGE_DAYS", "MIN_POST_CHARS", "MIN_VIEWS_ABSOLUTE", "MIN_VIEWS_RATIO",
    "MIN_REACTIONS", "DEFAULT_LIMIT", "MAX_LIMIT", "MAX_REUSE_SIMILARITY",
    "MAX_GENERATION_ATTEMPTS", "ERR_FORBIDDEN", "ERR_DB_UNAVAILABLE",
    "ERR_NO_CANDIDATES", "ERR_AI_FAILED", "ERR_BLIND_REPOST", "ERR_QUOTA",
    "post_age_days", "engagement_score", "select_recycle_candidates",
    "reuse_similarity", "is_blind_repost", "compose_refreshed",
    "parse_recycled_payload", "RECYCLE_SYSTEM_PROMPT", "build_recycle_prompt",
    "RecycleService", "load_recycle_candidates", "schedule_recycled_post",
]
