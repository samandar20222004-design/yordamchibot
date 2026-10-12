"""📚 CONTENT LEARNING & GAP DETECTION.

Kanalning REAL postlari (``channel_posts_history``) asosida **kontent
o'rganish** tahlili: qanday post formatlari (Q&A, tutorial/qo'llanma,
ijtimoiy isbot, yangilik, maslahat, so'rovnoma, taklif, hikoya) kuzatilgan
va qaysilari YETISHMAYAPTI — shu bo'shliqlar (gaps) asosida AI Studio va
Post auditi ekranlarida **lokalizatsiya qilingan tavsiyalar** (uz/ru/en)
ko'rsatiladi.

Qat'iy kafolatlar (NO FABRICATION):
  * Tahlil FAQAT real post matnlari bo'yicha (AI'siz, deterministik
    kalit-so'z tasnifi) — hech qanday soxta metrika/foiz UYDIRILMAYDI;
  * Postlar soni ``MIN_POSTS_FOR_LEARNING`` (5) dan kam bo'lsa —
    ``insufficient=True`` va HALOL xabar ("kamida 5 ta post kerak, hozir
    N ta") qaytadi; tavsiyalar ro'yxati BO'SH;
  * Kanal ulanmagan bo'lsa — ``reason="no_channels"`` (haqiqiy sabab);
  * IDOR: ``get_content_learning_for_user`` FAQAT ``user_id`` ning O'Z
    kanallarini tahlil qiladi (``db.get_user_channels`` — begona kanal
    ma'lumotlari hech qachon so'ralmaydi);
  * Fail-soft: DB xatosi istisno ko'tarmaydi — ``ok=False`` hisobot qaytadi.

Barcha hisob funksiyalari PURE (DB'siz) — deterministik va testlanadi.
Matnlar ``translations.content_learning`` orqali uchala tilda (uz/ru/en).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)

#: Tahlil uchun minimal post soni (kam bo'lsa — soxta tavsiya yo'q).
MIN_POSTS_FOR_LEARNING = 5

#: Kanonik kontent formatlari (kodlar — o'zgarmas, i18n yorliqlari
#: ``translations.content_learning`` da: ``cl_format_<kod>``).
CONTENT_FORMATS: tuple[str, ...] = (
    "qa",            # ❓ Savol-javob (Q&A)
    "tutorial",      # 🎓 Qo'llanma / tutorial
    "social_proof",  # ⭐ Ijtimoiy isbot (mijoz fikrlari, keyslar)
    "news",          # 📰 Yangilik
    "tips",          # 💡 Maslahat / foydali ro'yxat
    "poll",          # 📊 So'rovnoma / faollik
    "offer",         # 🛒 Taklif / sotuv
    "story",         # 📖 Shaxsiy hikoya
)

#: Tavsiya ustuvorligi — STEP 3 talabidagi formatlar (Q&A, tutorial,
#: social proof) BIRINCHI navbatda, qolganlari keyin.
PRIORITY_FORMATS: tuple[str, ...] = ("qa", "tutorial", "social_proof")

#: Bir hisobotda ko'rsatiladigan maksimal tavsiyalar soni.
MAX_RECOMMENDATIONS = 4

#: Format kalit-so'zlari (uz/ru/en o'zaklari — kichik harfda). Tasnif
#: AI'siz, deterministik: matn pastga tushiriladi va o'zaklar qidiriladi.
FORMAT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "qa": (
        # uz
        "savol", "javob", "faq",
        # ru
        "вопрос", "ответ", "отвечаем",
        # en
        "question", "answer", "q&a", "ask me",
    ),
    "tutorial": (
        # uz
        "qo'llanma", "qo‘llanma", "dars", "bosqichma-bosqich", "bosqichma bosqich",
        "1-qadam", "2-qadam", "o'rgat", "o‘rgat", "instruksiya", "qanday qilib",
        # ru
        "инструкци", "урок", "руководство", "пошагов", "шаг 1", "как сделать",
        "обучен",
        # en
        "tutorial", "how to", "step-by-step", "step by step", "step 1",
        "guide", "learn how",
    ),
    "social_proof": (
        # uz
        "mijoz", "otziv", "sharh", "fikr-mulohaza", "izohlar", "muvaffaqiyat",
        "natijalarimiz", "rahmat",
        # ru
        "отзыв", "клиент", "кейс", "результат", "благодар", "история успеха",
        # en
        "testimonial", "review", "client", "case study", "feedback",
        "success story", "thank you",
    ),
    "news": (
        # uz
        "yangilik", "xabar", "e'lon", "voqea",
        # ru
        "новост", "событ", "анонс",
        # en
        "news", "announce", "breaking", "released",
    ),
    "tips": (
        # uz
        "maslahat", "tavsiya", "foydali", "hayotiy",
        # ru
        "совет", "полезн", "рекоменд",
        # en
        "tips", "advice", "useful", "best practices",
    ),
    "poll": (
        # uz
        "so'rovnoma", "so‘rovnoma", "anketa", "ovoz bering", "izohda yozing",
        # ru
        "опрос", "голосов", "напишите в комментар",
        # en
        "poll", "vote", "comment below",
    ),
    "offer": (
        # uz
        "chegirma", "aksiya", "narx", "buyurtma", "sotuv", "taklif",
        # ru
        "скидк", "акци", "цен", "заказ", "прода",
        # en
        "discount", "sale", "price", "order", "offer", "buy now",
    ),
    "story": (
        # uz
        "hikoya", "boshimdan", "tajriba", "hayotiy misol",
        # ru
        "история", "случай", "из жизни", "опыт",
        # en
        "story", "my experience", "once i",
    ),
}


# ---------------------------------------------------------------------------
# PURE yordamchilar
# ---------------------------------------------------------------------------
def extract_post_text(row: Any) -> str:
    """Post yozuvidan matnni oladi (dict / tuple / str — fail-soft)."""
    if isinstance(row, str):
        return row.strip()
    if isinstance(row, dict):
        text = row.get("text") or row.get("content") or ""
        return str(text or "").strip()
    if isinstance(row, (list, tuple)):
        # channel_posts_history xom qatori: (id, channel_id, message_id,
        # content, views, post_date, ...) — matn 3-indeksda.
        for index in (3, 2, 1):
            if len(row) > index and isinstance(row[index], str) and row[index].strip():
                return row[index].strip()
    return ""


def classify_post_formats(text: str) -> set:
    """Bitta post matnidan kuzatilgan formatlar to'plami (AI'siz, PURE).

    Juda qisqa matnlar (``< 20`` belgi) tasniflanmaydi — tasodifiy
    moslashuvlar oldini oladi.
    """
    raw = str(text or "").strip().lower()
    if len(raw) < 20:
        return set()
    found = set()
    for fmt in CONTENT_FORMATS:
        for keyword in FORMAT_KEYWORDS.get(fmt, ()):  # noqa: SIM118
            if keyword in raw:
                found.add(fmt)
                break
    return found


def analyze_content_coverage(posts: Any, min_posts: int = MIN_POSTS_FOR_LEARNING) -> dict:
    """Postlar ro'yxatidan kontent qamrovi hisobotini hisoblaydi (PURE).

    Qaytadi::

        {
          "insufficient": False, "sample_size": 12, "min_posts": 5,
          "observed": {"news": 8, "tips": 3},       # REAL sonlar
          "missing": ["qa", "tutorial", ...],        # kuzatilmagan formatlar
          "recommendations": ["qa", "tutorial", "social_proof", "poll"],
          "formats_total": 8, "formats_observed": 2,
        }

    Kam ma'lumotda (``< min_posts``) ``insufficient=True`` va tavsiyalar
    BO'SH — soxta metrika UYDIRILMAYDI::

        {"insufficient": True, "sample_size": 3, "min_posts": 5,
         "observed": {}, "missing": [], "recommendations": [], ...}
    """
    minimum = max(1, int(min_posts or MIN_POSTS_FOR_LEARNING))
    texts = [extract_post_text(row) for row in (posts or ())]
    texts = [t for t in texts if len(t) >= 20]
    n = len(texts)

    if n < minimum:
        return {
            "insufficient": True,
            "sample_size": n,
            "min_posts": minimum,
            "observed": {},
            "missing": [],
            "recommendations": [],
            "formats_total": len(CONTENT_FORMATS),
            "formats_observed": 0,
        }

    observed: Counter = Counter()
    for text in texts:
        for fmt in classify_post_formats(text):
            observed[fmt] += 1

    missing_priority = [f for f in PRIORITY_FORMATS if f not in observed]
    missing_other = [
        f for f in CONTENT_FORMATS
        if f not in observed and f not in PRIORITY_FORMATS
    ]
    missing = missing_priority + missing_other
    return {
        "insufficient": False,
        "sample_size": n,
        "min_posts": minimum,
        "observed": dict(observed),
        "missing": missing,
        "recommendations": missing[:MAX_RECOMMENDATIONS],
        "formats_total": len(CONTENT_FORMATS),
        "formats_observed": len(observed),
    }


def render_content_learning_text(report: Any, lang: str = "uz") -> str:
    """Hisobotdan Telegram HTML blokini chizadi (uz/ru/en — to'liq lokal).

    NO FABRICATION: ko'rsatiladigan HAR BIR son hisobotdagi real qiymat
    (``sample_size``, ``channels_analyzed``, kuzatilgan format sonlari).
    Ma'lumot yetishmasa — halol "yetarli ma'lumot yo'q" xabari chiqadi.
    """
    from translations.content_learning import content_learning_t as _t

    data = report if isinstance(report, dict) else {}
    lines = [_t("cl_title", lang)]

    if data.get("reason") == "no_channels":
        lines.append(_t("cl_no_channels", lang))
        return "\n".join(lines)

    n = int(data.get("sample_size") or 0)
    minimum = int(data.get("min_posts") or MIN_POSTS_FOR_LEARNING)
    if data.get("insufficient") or n <= 0:
        lines.append(_t("cl_insufficient", lang, n=n, min=minimum))
        return "\n".join(lines)

    channels = int(data.get("channels_analyzed") or 0)
    lines.append(_t("cl_analyzed", lang, n=n, channels=channels))

    observed = data.get("observed") or {}
    lines.append(_t("cl_observed_header", lang))
    if observed:
        for fmt in CONTENT_FORMATS:
            count = int(observed.get(fmt) or 0)
            if count > 0:
                lines.append(_t(
                    "cl_observed_item", lang,
                    label=_t(f"cl_format_{fmt}", lang), count=count))
    else:
        lines.append(_t("cl_observed_none", lang))

    recommendations = [
        r for r in (data.get("recommendations") or []) if r in CONTENT_FORMATS
    ]
    if recommendations:
        lines.append(_t("cl_missing_header", lang))
        for fmt in recommendations:
            lines.append(f"• {_t(f'cl_reco_{fmt}', lang)}")
    else:
        lines.append(_t("cl_all_covered", lang))

    lines.append(_t("cl_footer", lang))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# DB + ownership bilan asinxron xizmat (IDOR-safe, fail-soft)
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


def _channel_id_of(row: Any) -> str | None:
    if isinstance(row, dict):
        value = row.get("channel_id") or row.get("id")
    elif isinstance(row, (list, tuple)) and row:
        value = row[0]
    else:
        value = row if isinstance(row, (str, int)) else None
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def get_content_learning_for_user(
    user_id: int | None,
    lang: str = "uz",
    db_module: Any = None,
    per_channel_limit: int = 25,
    max_channels: int = 5,
) -> dict:
    """Foydalanuvchining O'Z kanallari bo'yicha kontent o'rganish hisoboti.

    IDOR himoyasi: kanallar ``db.get_user_channels(user_id)`` orqali
    olinadi — faqat shu foydalanuvchining kanallari. Post matnlari
    ``db.get_channel_posts_history`` dan (fail-soft).

    Hech qachon istisno ko'tarmaydi: xato holatida
    ``{"ok": False, "insufficient": True, "sample_size": 0, ...}`` qaytadi
    (soxta tavsiyalar UYDIRILMAYDI).
    """
    base_insufficient = {
        "ok": False,
        "insufficient": True,
        "sample_size": 0,
        "min_posts": MIN_POSTS_FOR_LEARNING,
        "observed": {},
        "missing": [],
        "recommendations": [],
        "formats_total": len(CONTENT_FORMATS),
        "formats_observed": 0,
        "channels_analyzed": 0,
    }
    try:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return {**base_insufficient, "reason": "no_user"}
        if uid <= 0:
            return {**base_insufficient, "reason": "no_user"}

        db = db_module if db_module is not None else _import_database()
        if db is None or not hasattr(db, "get_user_channels"):
            return {**base_insufficient, "reason": "db_unavailable"}

        channels = await _db_call(db, db.get_user_channels, uid)
        channel_ids: list[str] = []
        for row in (channels or [])[: max(1, int(max_channels))]:
            ch_id = _channel_id_of(row)
            if ch_id and ch_id not in channel_ids:
                channel_ids.append(ch_id)
        if not channel_ids:
            return {**base_insufficient, "ok": True, "reason": "no_channels"}

        posts: list[Any] = []
        if hasattr(db, "get_channel_posts_history"):
            limit = max(1, min(int(per_channel_limit), 50))
            for ch_id in channel_ids:
                try:
                    rows = await _db_call(
                        db, db.get_channel_posts_history, ch_id, limit)
                    if isinstance(rows, (list, tuple)):
                        posts.extend(rows)
                except Exception:
                    logger.debug(
                        "content learning: post tarixi olinmadi (%s)", ch_id,
                        exc_info=True)

        report = analyze_content_coverage(posts)
        report["ok"] = True
        report["channels_analyzed"] = len(channel_ids)
        return report
    except Exception as e:  # noqa: BLE001 — fail-soft, ekran uzilmaydi
        logger.debug("get_content_learning_for_user xatosi: %s", e)
        return {**base_insufficient, "reason": "error"}
