"""🚀 AI AUTOPILOT — 7 kunlik to'liq post rejasini tuzish (PHASE C, 7-band).

Foydalanuvchi mavzu/yo'nalish kiritadi, xizmat esa kanalning:

  * **Channel DNA** uslub profili (``services.channels.dna``) va
  * **Smart Best Time** tavsiyalari (``services.channels.best_time``)

asosida 7 kunlik (Dushanba–Yakshanba) to'liq post rejasini tuzadi. Har bir
kun uchun: aniq vaqt, mavzu/format, tayyor post matni va CTA.

Kafolatlar:
  * yetarli ma'lumot bo'lmasa soxta raqamlar UYDIRILMAYDI — Best Time
    ``insufficient`` bo'lsa standart soat ishlatiladi va foydalanuvchiga
    ochiq aytiladi;
  * tasdiqlangandan keyin 7 ta post ``database.schedule_week_posts`` orqali
    BITTA ATOMIK tranzaksiyada ``scheduled_posts`` navbatiga yoziladi
    (hammasi yoki hech narsa);
  * FREE foydalanuvchilar uchun navbat limiti (``check_queue_limit``)
    qat'iy tekshiriladi — joy yetmasa hech narsa yozilmaydi;
  * AI javobi ishonchsiz bo'lsa (JSON buzilgan, kunlar yetmagan) — reja
    tuzilmagan deb qaytaradi (yarim-yorti reja YO'Q);
  * IDOR: DNA va best-time oqimlari ``user_id`` ownership tekshiruvi
    bilan chaqiriladi (boshqa foydalanuvchining kanaliga reja tuzilmaydi).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pytz

logger = logging.getLogger(__name__)

#: Rejadagi kunlar soni (Dushanba → Yakshanba).
AUTOPILOT_DAYS = 7

#: Best Time ma'lumoti yetarli bo'lmaganda ishlatiladigan standart soat.
DEFAULT_POST_HOUR = 19

#: Yagona vaqt zonasi (scheduler bilan bir xil).
tashkent_tz = pytz.timezone("Asia/Tashkent")

#: AI javobidagi maydon chegaralari (xavfsizlik/bounded).
MAX_TOPIC_LENGTH = 200
MAX_CONTENT_LENGTH = 3500
MAX_FIELD_LENGTH = 300


# ---------------------------------------------------------------------------
# PURE: vaqtinchalik reja (deterministik, testlanadigan)
# ---------------------------------------------------------------------------
def next_week_start(now: datetime | None = None, hour: int = DEFAULT_POST_HOUR,
                    minute: int = 0) -> datetime:
    """Reja boshlanadigan Dushanba soat ``hour:minute`` (Toshkent).

    Qoida (``handlers.content_plan.week_schedule_times`` bilan bir xil):
    shu haftaning dushanbasi o'tib bo'lsa — KEYINGI hafta dushanbasidan
    boshlanadi, shunda hech bir post o'tmishga tushmaydi.
    """
    reference = now if now is not None else datetime.now(tashkent_tz)
    if reference.tzinfo is None:
        reference = tashkent_tz.localize(reference)
    reference = reference.astimezone(tashkent_tz)

    days_to_monday = (0 - reference.weekday()) % 7
    monday = (reference + timedelta(days=days_to_monday)).date()
    first = tashkent_tz.localize(
        datetime(monday.year, monday.month, monday.day, int(hour) % 24,
                 int(minute) % 60))
    if first <= reference:
        first = first + timedelta(days=7)
    return first


def week_times(count: int = AUTOPILOT_DAYS, hour: int = DEFAULT_POST_HOUR,
               minute: int = 0, now: datetime | None = None) -> list[datetime]:
    """Dushanbadan boshlab ``count`` kun uchun aware datetime ro'yxati."""
    first = next_week_start(now=now, hour=hour, minute=minute)
    return [first + timedelta(days=i) for i in range(max(0, int(count)))]


def resolve_post_hour(best_time_result: dict | None) -> int:
    """Best Time natijasidan post soatini oladi (insufficient → default).

    Soxta raqamlar uydirmaydi: ``insufficient``/buzilgan natijada
    ``DEFAULT_POST_HOUR`` qaytadi (foydalanuvchiga ochiq aytiladi).
    """
    result = best_time_result if isinstance(best_time_result, dict) else {}
    if result.get("insufficient"):
        return DEFAULT_POST_HOUR
    peak = result.get("peak_hour")
    try:
        peak = int(peak)
    except (TypeError, ValueError):
        return DEFAULT_POST_HOUR
    return peak if 0 <= peak <= 23 else DEFAULT_POST_HOUR


def compose_post_text(content: str, cta: str) -> str:
    """Post matni + CTA bitta tayyor matnga birlashtiriladi (PURE).

    CTA bo'sh bo'lsa yoki matn ichida allaqachon bo'lsa — qo'shilmaydi.
    """
    body = str(content or "").strip()
    tail = str(cta or "").strip()
    if not tail:
        return body
    if tail and tail.lower() in body.lower():
        return body
    return f"{body}\n\n{tail}" if body else tail


def _bounded(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def normalize_ai_plan(payload: Any, days: int = AUTOPILOT_DAYS) -> list[dict]:
    """AI JSON javobini QAT'IY normalizatsiya qiladi (PURE).

    Har bir kun: ``{"topic", "format", "content", "cta"}``. Kamida bitta
    kun matnsiz bo'lsa YOKI kunlar soni yetmasa — ``[]`` (yarim-yorti
    reja QAT'IYAN YO'Q).
    """
    if not isinstance(payload, dict):
        return []
    items = (payload.get("days") or payload.get("plan")
             or payload.get("posts") or payload.get("items"))
    if not isinstance(items, list):
        return []
    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            return []
        content = _bounded(item.get("content") or item.get("post")
                           or item.get("text"), MAX_CONTENT_LENGTH)
        if not content:
            return []
        normalized.append({
            "topic": _bounded(item.get("topic") or item.get("theme"),
                              MAX_TOPIC_LENGTH),
            "format": _bounded(item.get("format") or item.get("type"),
                               MAX_FIELD_LENGTH),
            "content": content,
            "cta": _bounded(item.get("cta"), MAX_FIELD_LENGTH),
        })
    if len(normalized) != int(days) or len(normalized) == 0:
        return []
    return normalized


# ---------------------------------------------------------------------------
# AI generatsiya (yagona patch nuqtasi — testlar tarmoqsiz ishlaydi)
# ---------------------------------------------------------------------------
async def generate_autopilot_week(
    topic: str,
    lang: str = "uz",
    dna_block: str = "",
    best_hour: int | None = None,
    days: int = AUTOPILOT_DAYS,
) -> list[dict]:
    """AI orqali ``days`` kunlik to'liq post rejasini oladi (xatoda — [])."""
    try:
        from services.ai_service import run_ai_chain
        from utils.ai_agent import _extract_json
    except Exception:  # pragma: no cover — import xatosi (test muhiti)
        return []

    clean_topic = str(topic or "").strip()[:MAX_TOPIC_LENGTH]
    if not clean_topic:
        return []

    hour_line = ""
    if best_hour is not None:
        hour_line = (
            f"Har bir kun uchun tavsiya etilgan soat: {int(best_hour) % 24}:00 "
            "(kanal statistikasi bo'yicha). Vaqtlarni shu soat atrofida "
            "taklif qilishingiz mumkin.\n"
        )
    system = (
        "Siz tajribali SMM kontent-strategisiz. Faqat JSON qaytaring:\n"
        '{"days": [{"topic": "...", "format": "...", "content": "...", '
        '"cta": "..."}]}\n'
        f"Aynan {int(days)} ta yozuv bo'lsin, boshqa matn qo'shmang. "
        "\"content\" — kanalga chiqadigan TO'LIQ tayyor post matni (sarlavha, "
        "matn, emoji bilan), \"cta\" — qisqa chaqiruv amali."
    )
    prompt = (
        f"Mavzu/yo'nalish: {clean_topic}\n"
        f"{hour_line}"
        "7 kunlik (Dushanba–Yakshanba) SMM post rejasi tuzing. Har bir kun "
        "uchun: topic (qisqa mavzu), format (masalan: e'lon / savol-javob / "
        "case / chegirma / foydali maslahat), content (tayyor post matni) "
        "va cta (chaqiruv amali).\n"
    )
    if dna_block:
        prompt = f"{dna_block}\n\n{prompt}"

    try:
        result = await run_ai_chain(prompt, system, lang)
    except Exception:
        logger.warning("Avtopilot AI generatsiya xatosi", exc_info=True)
        return []
    if not isinstance(result, dict) or result.get("error"):
        return []
    text = result.get("text") or result.get("content") or ""
    if not text:
        return []
    try:
        payload = _extract_json(text)
    except Exception:
        logger.warning("Avtopilot javobini JSON qilib o'qib bo'lmadi")
        return []
    return normalize_ai_plan(payload, days)


async def rewrite_flagged_posts(
    topic: str,
    flagged: list[dict],
    lang: str = "uz",
    dna_block: str = "",
) -> list[dict]:
    """Dublikat deb topilgan postlarni AI bilan YANGILAYDI (boshqacha qiladi).

    ``flagged`` — ``{"index", "content"}`` ro'yxati. Qaytadi: yangilangan
    ``{"index", "content"}`` ro'yxati YOKI xatoda ``[]``.
    """
    if not flagged:
        return []
    try:
        from services.ai_service import run_ai_chain
        from utils.ai_agent import _extract_json
    except Exception:  # pragma: no cover
        return []

    system = (
        "Siz SMM copywriter'siz. Faqat JSON qaytaring:\n"
        '{"posts": [{"index": 0, "content": "..."}]}\n'
        "Har bir postni MAVZU SAQLANIB, lekin tuzilishi, hook va so'zlar "
        "BOSHQAChA qilib qayta yozing."
    )
    listed = "\n".join(
        f"{int(item.get('index', 0))}: {str(item.get('content', ''))[:600]}"
        for item in flagged
    )
    prompt = (
        f"Umumiy mavzu: {str(topic or '')[:MAX_TOPIC_LENGTH]}\n\n"
        f"Quyidagi postlar kanalda yaqinda chiqqan postlarga juda o'xshab "
        f"qoldi. Har birini ANIQ boshqacha qilib qayta yozing (index "
        f"sahlashning):\n\n{listed}\n\n{dna_block or ''}"
    )
    try:
        result = await run_ai_chain(prompt, system, lang)
    except Exception:
        logger.warning("Avtopilot dublikat-rewrite xatosi", exc_info=True)
        return []
    if not isinstance(result, dict) or result.get("error"):
        return []
    text = result.get("text") or result.get("content") or ""
    try:
        payload = _extract_json(text)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    posts = payload.get("posts") or payload.get("days") or []
    rewritten = []
    for item in posts:
        if not isinstance(item, dict):
            continue
        content = _bounded(item.get("content") or item.get("post"),
                           MAX_CONTENT_LENGTH)
        if not content:
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        rewritten.append({"index": index, "content": content})
    return rewritten


# ---------------------------------------------------------------------------
# Rejani yig'ish (AI natijasi + vaqtlar → to'liq kunlar)
# ---------------------------------------------------------------------------
def build_week_plan(
    day_items: list[dict],
    hour: int = DEFAULT_POST_HOUR,
    minute: int = 0,
    now: datetime | None = None,
) -> list[dict]:
    """Normalizatsiyalangan AI kunlariga aniq vaqtlarni ulaydi (PURE).

    Qaytadi — kunlar ro'yxati (Dushanba → Yakshanba)::

        {"index": 0, "weekday": 0, "date": "21.09", "time": "19:00",
         "scheduled_time": <aware datetime>, "topic": "...", "format": "...",
         "content": "...", "cta": "...", "post_text": "tayyor matn + CTA"}
    """
    times = week_times(count=len(day_items), hour=hour, minute=minute, now=now)
    days = []
    for index, (moment, item) in enumerate(zip(times, day_items)):
        item = item or {}
        content = str(item.get("content") or "").strip()
        cta = str(item.get("cta") or "").strip()
        days.append({
            "index": index,
            "weekday": moment.weekday(),
            "date": moment.strftime("%d.%m"),
            "time": moment.strftime("%H:%M"),
            "scheduled_time": moment,
            "topic": str(item.get("topic") or "").strip(),
            "format": str(item.get("format") or "").strip(),
            "content": content,
            "cta": cta,
            "post_text": compose_post_text(content, cta),
        })
    return days


def _import_database():
    try:
        import database as _db
        return _db
    except Exception:  # pragma: no cover
        return None


async def _db_call(db: Any, fn, *args, **kwargs):
    run_db = getattr(db, "run_db", None)
    if run_db is not None:
        return await run_db(fn, *args, **kwargs)
    return fn(*args, **kwargs)


async def create_autopilot_plan(
    user_id: int,
    channel_id: str | int,
    topic: str,
    lang: str = "uz",
    db_module: Any = None,
) -> dict:
    """Kanal DNA + Best Time asosida 7 kunlik reja tuzadi (IDOR himoyasi).

    Qaytadi::

        {"ok": True, "days": [...], "hour": 19,
         "hour_source": "best_time" | "default",
         "best_window": "19:00 - 21:00" | None,
         "dna_attached": bool, "message": None}

    Xato/malumot yetmasa::

        {"ok": False, "error_code": "FORBIDDEN" | "DB_UNAVAILABLE" |
         "AI_FAILED" | "INVALID_TOPIC", "message": "..."}
    """
    from services.channels.best_time import get_best_time
    from services.channels.dna import build_dna_system_prompt, get_channel_dna

    clean_topic = str(topic or "").strip()
    if len(clean_topic) < 3:
        return {"ok": False, "error_code": "INVALID_TOPIC",
                "message": "Mavzu juda qisqa"}
    clean_topic = clean_topic[:MAX_TOPIC_LENGTH]

    db = db_module if db_module is not None else _import_database()

    dna_result = await get_channel_dna(channel_id, user_id, db_module=db)
    if not dna_result.get("ok"):
        return {"ok": False, "error_code": dna_result.get("error_code",
                                                          "DB_UNAVAILABLE"),
                "message": dna_result.get("message", "Kanal topilmadi")}
    best_result = await get_best_time(channel_id, user_id, db_module=db)
    if not best_result.get("ok"):
        return {"ok": False, "error_code": best_result.get("error_code",
                                                           "DB_UNAVAILABLE"),
                "message": best_result.get("message", "Kanal topilmadi")}

    hour = resolve_post_hour(best_result)
    hour_source = "default" if best_result.get("insufficient") else "best_time"
    best_window = best_result.get("top_window")

    dna_block = ""
    dna_attached = False
    profile = dna_result.get("profile")
    if isinstance(profile, dict) and profile:
        block = build_dna_system_prompt(profile, lang=lang)
        if block:
            dna_block = block
            dna_attached = True

    day_items = await generate_autopilot_week(
        clean_topic, lang=lang, dna_block=dna_block, best_hour=hour)
    if not day_items:
        return {"ok": False, "error_code": "AI_FAILED",
                "message": "Reja tuzilmadi"}

    days = build_week_plan(day_items, hour=hour, now=None)
    return {
        "ok": True,
        "days": days,
        "hour": hour,
        "hour_source": hour_source,
        "best_window": best_window,
        "dna_attached": dna_attached,
        "message": None,
    }


# ---------------------------------------------------------------------------
# Navbat limiti + atomik rejalashtirish
# ---------------------------------------------------------------------------
async def check_week_quota(
    user_id: int,
    needed: int = AUTOPILOT_DAYS,
    db_module: Any = None,
) -> dict:
    """FREE/PRO navbat limitini tekshiradi (``check_queue_limit``).

    Qaytadi::

        {"allowed": bool, "current": int, "max": int, "free_slots": int,
         "needed": int}

    ``allowed`` — faqat ``current + needed <= max`` bo'lganda ``True``
    (bitta emak, 7 ta post uchun yetarli joy). DB xatosida fail-closed:
    ruxsat BERILMAYDI (``allowed=False``) — foydalanuvchi xavfsiz
    ogohlantirish oladi.
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "check_queue_limit"):
        return {"allowed": False, "current": 0, "max": 0,
                "free_slots": 0, "needed": int(needed)}
    try:
        can_add, current, max_q = await _db_call(db, db.check_queue_limit,
                                                 int(user_id))
        current = int(current or 0)
        max_q = int(max_q or 0)
        free_slots = max(0, max_q - current)
        return {
            "allowed": bool(can_add) and free_slots >= int(needed),
            "current": current,
            "max": max_q,
            "free_slots": free_slots,
            "needed": int(needed),
        }
    except Exception:
        logger.warning("Avtopilot navbat limitini tekshirishda xato",
                       exc_info=True)
        return {"allowed": False, "current": 0, "max": 0,
                "free_slots": 0, "needed": int(needed)}


async def schedule_autopilot_week(
    user_id: int,
    channel_id: str | int,
    days: list[dict],
    db_module: Any = None,
) -> dict:
    """7 ta postni BITTA ATOMIK tranzaksiyada navbatga qo'yadi.

    ``database.schedule_week_posts`` (Phase 2) ishlatiladi: barcha INSERT'lar
    bitta ``db_cursor(commit=True)`` blokida — birortasi yiqilsa ROLLBACK,
    ya'ni yarim-yorti navbat HECH QACHON qolmaydi (hammasi yoki hech narsa).
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "schedule_week_posts"):
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": "db_unavailable"}
    posts = []
    for day in days or []:
        moment = day.get("scheduled_time")
        text = day.get("post_text")
        if moment is None or not text:
            continue
        posts.append((moment, text))
    if not posts:
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": "empty"}
    try:
        return await _db_call(db, db.schedule_week_posts, int(user_id),
                              str(channel_id), posts)
    except Exception as e:
        logger.exception("Avtopilot: haftalik navbatga qo'yishda xato "
                         "(user=%s)", user_id)
        return {"success": False, "count": 0, "ids": [], "times": [],
                "error": str(e)}


# ---------------------------------------------------------------------------
# Dublikat tekshiruvi (rejalashtirishdan OLDIN)
# ---------------------------------------------------------------------------
def flag_duplicate_days(
    days: list[dict],
    recent_texts: list[str],
    threshold: float | None = None,
) -> dict:
    """Rejadagi kunlarni kanalning oxirgi postlari bilan solishtiradi (PURE).

    Qaytadi::

        {"flagged": [0, 3],            # dublikat kun indekslari
         "scores": {0: 0.93, 3: 0.88}, # indeks → o'xshashlik
         "best_preview": "..."}        # eng o'xshash post parchasi
    """
    from services.channels.duplicate_detector import (
        DUPLICATE_THRESHOLD, check_duplicate,
    )

    thr = float(threshold) if threshold is not None else DUPLICATE_THRESHOLD
    flagged: list[int] = []
    scores: dict[int, float] = {}
    best_preview = ""
    best_score = 0.0
    for day in days or []:
        index = int(day.get("index", 0))
        result = check_duplicate(day.get("post_text"), recent_texts,
                                 threshold=thr)
        if result.get("duplicate"):
            flagged.append(index)
            scores[index] = float(result.get("score") or 0.0)
            if float(result.get("score") or 0.0) > best_score:
                best_score = float(result.get("score") or 0.0)
                best_preview = str(result.get("matched_text") or "")
    return {"flagged": flagged, "scores": scores, "best_preview": best_preview}


async def load_recent_channel_texts(
    channel_id: str | int,
    user_id: int,
    limit: int = 10,
    db_module: Any = None,
) -> list[str] | None:
    """Kanalning oxirgi post matnlarini oladi (IDOR + fail-soft).

    Kanal egasi bo'lmasa YOKI DB o'qilmasa — ``None`` (detektor to'suvchi
    bo'lmaydi, tekshiruv o'tkazib yuboriladi).
    """
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_posts_history"):
        return None
    try:
        if hasattr(db, "get_channel_owner_id"):
            owner = await _db_call(db, db.get_channel_owner_id,
                                   str(channel_id))
            try:
                owned = owner is not None and int(owner) == int(user_id)
            except (TypeError, ValueError):
                owned = False
            if not owned:
                return None
        history = await _db_call(db, db.get_channel_posts_history,
                                 str(channel_id), int(limit))
    except Exception:
        logger.debug("Avtopilot: kanal tarixini o'qib bo'lmadi (%s)",
                     channel_id, exc_info=True)
        return None
    texts = []
    for row in history or []:
        try:
            content = row.get("content") if isinstance(row, dict) else row[3]
        except (IndexError, TypeError, AttributeError):
            continue
        if content:
            texts.append(str(content))
    return texts


__all__ = [
    "AUTOPILOT_DAYS",
    "DEFAULT_POST_HOUR",
    "build_week_plan",
    "check_week_quota",
    "compose_post_text",
    "create_autopilot_plan",
    "flag_duplicate_days",
    "generate_autopilot_week",
    "load_recent_channel_texts",
    "next_week_start",
    "normalize_ai_plan",
    "resolve_post_hour",
    "rewrite_flagged_posts",
    "schedule_autopilot_week",
    "week_times",
]
