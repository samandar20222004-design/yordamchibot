"""⏰ SMART BEST TIME GENERATOR (PostAssist V2 — PHASE B, 3-band).

Kanalning kuzatilgan post chiqarish statistikasi (``channel_post_events``)
bo'yicha eng maqbul vaqt oynalarini chiqaradi:

  * hafta kunlari va soatlar kesimidagi taqsimot;
  * foydalanuvchiga tavsiya kartochkasi::

      🔥 Tavsiya etilgan vaqt: 19:00 - 21:00 (O'rtacha 450 belgi, rasm bilan)

QAT'IY QOIDA: yetarli ma'lumot bo'lmaganda (kamida 5 ta post) **soxta
raqamlar uydirmaslik** — ``insufficient`` holati va tushunarli xabar
qaytadi. Barcha hisob funksiyalari PURE (DB'siz) va deterministik.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

#: Aniq tavsiya berish uchun minimal kuzatilgan post soni.
MIN_POSTS_FOR_BEST_TIME = 5

#: Yetarli ma'lumot bo'lmasa qaytariladigan qat'iy xabar (uz).
INSUFFICIENT_DATA_MESSAGE = "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)"

#: Hafta kunlari nomi (0 = Dushanba .. 6 = Yakshanba) — uz / ru / en.
WEEKDAY_NAMES = {
    "uz": ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma",
           "Shanba", "Yakshanba"],
    "ru": ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница",
           "Суббота", "Воскресенье"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
           "Saturday", "Sunday"],
}


def format_hour(hour: int) -> str:
    """Soatni ``HH:00`` formatida (0..23 → ``"19:00"``)."""
    h = int(hour or 0) % 24
    return f"{h:02d}:00"


def hour_window(start_hour: int, span: int = 3) -> str:
    """Peak soatdan boshlanadigan 3 soatlik tavsiya oynasi: ``"19:00 - 21:00"``.

    Oyna 23:00 dan o'tmaydi (24:00 mavjud emas) — masalan 22:00 peak'da
    ``"22:00 - 23:00"``.
    """
    start = int(start_hour or 0) % 24
    end = min(23, start + max(1, int(span or 3)) - 1)
    return f"{format_hour(start)} - {format_hour(end)}"


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


def compute_best_time(events: list[dict]) -> dict:
    """Eventlar ro'yxatidan best-time statistikasini hisoblaydi (PURE).

    Yetarli ma'lumotda qaytadi::

        {"insufficient": False, "sample_size": 24, "peak_hour": 19,
         "top_window": "19:00 - 21:00",
         "top_windows": [("19:00 - 21:00", 8), ("18:00 - 20:00", 6), ...],
         "hour_distribution": {19: 8, 18: 6, ...},
         "weekday_distribution": {0: 4, 2: 3, ...},
         "best_weekdays": ["Dushanba", "Chorshanba", ...],
         "average_length": 450, "media_ratio": 0.58, "message": None}

    Kam ma'lumotda (``< 5`` post YOKI valid soat ma'lumoti yo'q) — soxta
    raqamlar UYDIRMAYDI::

        {"insufficient": True, "sample_size": 3, "peak_hour": None,
         "top_window": None, "top_windows": [], "hour_distribution": {},
         "weekday_distribution": {}, "best_weekdays": [],
         "average_length": None, "media_ratio": 0.0,
         "message": "Yetarli ma'lumot yo'q (kamida 5 ta post kerak)"}
    """
    events = [e for e in (events or []) if isinstance(e, dict)]
    n = len(events)
    if n < MIN_POSTS_FOR_BEST_TIME:
        return {
            "insufficient": True,
            "sample_size": n,
            "peak_hour": None,
            "top_window": None,
            "top_windows": [],
            "hour_distribution": {},
            "weekday_distribution": {},
            "best_weekdays": [],
            "average_length": None,
            "media_ratio": 0.0,
            "message": INSUFFICIENT_DATA_MESSAGE,
        }

    hour_counter: Counter = Counter()
    weekday_counter: Counter = Counter()
    lengths: list[int] = []
    media_count = 0
    for e in events:
        h = _valid_hour(e.get("post_hour"))
        if h is not None:
            hour_counter[h] += 1
        d = _valid_weekday(e.get("post_weekday"))
        if d is not None:
            weekday_counter[d] += 1
        try:
            lengths.append(max(0, int(e.get("length") or 0)))
        except (TypeError, ValueError):
            pass
        if e.get("has_media"):
            media_count += 1

    if not hour_counter:
        # Soat ma'lumoti umuman yo'q — tavsiya berish imkonsiz (soxta
        # raqamlar uydirmaslik qoidasi).
        return {
            "insufficient": True,
            "sample_size": n,
            "peak_hour": None,
            "top_window": None,
            "top_windows": [],
            "hour_distribution": {},
            "weekday_distribution": dict(weekday_counter),
            "best_weekdays": [],
            "average_length": int(round(sum(lengths) / len(lengths))) if lengths else None,
            "media_ratio": round(media_count / n, 4) if n else 0.0,
            "message": INSUFFICIENT_DATA_MESSAGE,
        }

    # Peak soat: eng ko'p post chiqqan soat (durrangda KICHIK soat —
    # deterministik). Top-3: son bo'yicha kamayish, durrangda kichik soat.
    peak_hour = max(sorted(hour_counter), key=lambda h: hour_counter[h])
    ranked = sorted(hour_counter.items(), key=lambda kv: (-kv[1], kv[0]))
    top_windows = [(hour_window(h), c) for h, c in ranked[:3]]
    top_weekdays = sorted(weekday_counter.items(), key=lambda kv: (-kv[1], kv[0]))

    names = WEEKDAY_NAMES["uz"]
    return {
        "insufficient": False,
        "sample_size": n,
        "peak_hour": peak_hour,
        "top_window": hour_window(peak_hour),
        "top_windows": top_windows,
        "hour_distribution": {str(h): c for h, c in hour_counter.items()},
        "weekday_distribution": {str(d): c for d, c in weekday_counter.items()},
        "best_weekdays": [names[d] for d, _ in top_weekdays[:3]],
        "average_length": int(round(sum(lengths) / len(lengths))) if lengths else None,
        "media_ratio": round(media_count / n, 4) if n else 0.0,
        "message": None,
    }


def render_card_lines(result: dict, lang: str = "uz") -> tuple[str, str]:
    """Best-time natijasini UI qatorlari qaytaradi: ``(window_line, extra_lines)``.

    ``window_line`` — asosiy tavsiya kartochka qatori (masalan::

        🔥 Tavsiya etilgan vaqt: 19:00 - 21:00 (O'rtacha 450 belgi, rasm bilan)

    ``extra_lines`` — top soatlar/kunlar tafsilotlari (list[str]).
    Kam ma'lumotda ``(message, [])`` — soxta raqamlar yo'q.
    """
    from locales.translations import normalize_lang

    code = normalize_lang(lang)
    if result.get("insufficient"):
        return str(result.get("message") or INSUFFICIENT_DATA_MESSAGE), []

    avg_len = result.get("average_length")
    media_label = {
        "uz": "rasm bilan" if (result.get("media_ratio") or 0) >= 0.5 else "matn bilan",
        "ru": "с фото" if (result.get("media_ratio") or 0) >= 0.5 else "с текстом",
        "en": "with media" if (result.get("media_ratio") or 0) >= 0.5 else "text-based",
    }.get(code, "rasm bilan")

    if avg_len is not None:
        window_line = {
            "uz": f"🔥 Tavsiya etilgan vaqt: {result['top_window']} "
                  f"(O'rtacha {avg_len} belgi, {media_label})",
            "ru": f"🔥 Рекомендуемое время: {result['top_window']} "
                  f"(в среднем {avg_len} символов, {media_label})",
            "en": f"🔥 Suggested time: {result['top_window']} "
                  f"(avg {avg_len} chars, {media_label})",
        }.get(code, "")
    else:
        window_line = {
            "uz": f"🔥 Tavsiya etilgan vaqt: {result['top_window']}",
            "ru": f"🔥 Рекомендуемое время: {result['top_window']}",
            "en": f"🔥 Suggested time: {result['top_window']}",
        }.get(code, "")

    top_hours = ", ".join(f"{w} ({c})" for w, c in result.get("top_windows", [])[:3])
    top_days = ", ".join(result.get("best_weekdays", [])[:3])
    extra = []
    if top_hours:
        extra.append({
            "uz": f"🕐 Top soatlar: {top_hours}",
            "ru": f"🕐 Топ-часы: {top_hours}",
            "en": f"🕐 Top hours: {top_hours}",
        }.get(code, f"🕐 {top_hours}"))
    if top_days:
        extra.append({
            "uz": f"📅 Eng faol kunlar: {top_days}",
            "ru": f"📅 Самые активные дни: {top_days}",
            "en": f"📅 Most active days: {top_days}",
        }.get(code, f"📅 {top_days}"))
    extra.append({
        "uz": f"📊 Kuzatuv: {result.get('sample_size', 0)} ta post",
        "ru": f"📊 Наблюдено: {result.get('sample_size', 0)} постов",
        "en": f"📊 Observed: {result.get('sample_size', 0)} posts",
    }.get(code, f"📊 {result.get('sample_size', 0)}"))
    return window_line, extra


# ---------------------------------------------------------------------------
# DB + ownership bilan asinxron xizmat
# ---------------------------------------------------------------------------
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


async def get_best_time(
    channel_id: str | int,
    user_id: int | None = None,
    db_module: Any = None,
) -> dict:
    """Kanal uchun eng yaxshi post vaqtini hisoblaydi.

    RBAC/IDOR: ``user_id`` berilganda kanal egasi AYNAN shu foydalanuvchi
    bo'lishi shart — aks holda ``FORBIDDEN``. Yetarli ma'lumot bo'lmasa
    soxta raqamlar uydirmaydi — ``insufficient=True`` + xabar.
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL",
                "message": "Kanal ID bo'sh"}
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_post_events"):
        return {"ok": False, "error_code": "DB_UNAVAILABLE",
                "message": "Baza mavjud emas"}

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
                "message": "Bu kanal sizga tegishli emas — vaqt tahlili faqat "
                           "kanal egasiga ochiladi.",
            }

    events = await _db_call(db, db.get_channel_post_events, ch_id, 500)
    result = compute_best_time(events)
    result["ok"] = True
    result["channel_id"] = ch_id
    return result
