"""🔁 DUBLIKAT DETEKTOR — kanalning oxirgi postlari bilan solishtirish (PHASE C).

Post kanalga **rejalashtirilishidan yoki chiqarilishidan oldin** yangi matn
kanalning oxirgi postlari (``channel_posts_history``) bilan solishtiriladi.

QAT'IY QOIDALAR:
  * QIMMAT AI MODELLARI CHAQIRILMAYDI — faqat yengil, sof (pure) similarity
    algoritmi: token so'zlari bo'yicha **Jaccard** va **token overlap**
    (containment) ning maksimumi. Hech qanday tarmoq/DB zanjiri hisob-kitobga
    kirmaydi — ``similarity()`` / ``check_duplicate()`` PURE funksiyalar;
  * o'xshashlik **85% dan yuqor** bo'lsa — ogohlantirish::

        ⚠️ O'xshash post topildi. Bu post yaqindagi postingizga juda o'xshaydi.

    va foydalanuvchiga 3 tugma: [🚀 Baribir chiqarish] | [✨ AI bilan
    yangilash] | [❌ Bekor qilish] (tugmalar handler qatlamida);
  * IDOR himoyasi: kanal tarixi FAQAT kanal egasiga tekshiriladi
    (``user_id`` ownership tekshiruvi, fail-closed);
  * fail-soft: DB/baza xatosida detektor hech qachon postni to'sib
    qo'ymaydi va istisno ko'tarmaydi (``checked=False``).

Foydalanish::

    from services.channels.duplicate_detector import check_duplicate

    result = check_duplicate(new_text, recent_texts)   # pure
    # {"checked": True, "duplicate": True, "score": 0.93, ...}

    screen = await screen_post_for_duplicates(channel_id, user_id, new_text)
    # {"ok": True, "checked": True, "duplicate": False, ...}
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

logger = logging.getLogger(__name__)

#: Ogohlantirish chegarasi: o'xshashlik bundan QAT'IY YUQORI bo'lsa — dublikat.
DUPLICATE_THRESHOLD = 0.85

#: Yetarli "semantik og'irlik" uchun minimal token soni — 1-2 so'zli qisqa
#: matnlar (masalan "Buyurtma bering") tasodifiy o'xshash deb flag bo'lmaydi.
MIN_TOKENS_FOR_CHECK = 3

#: Containment (token overlap) faqat KICHIK matn kamida shuncha tokenga ega
#: bo'lganda hisobga olinadi — aks holda kichik matn katta matnning
#: "subset"i bo'lib qolib, soxta 100% chiqardi.
MIN_TOKENS_FOR_CONTAINMENT = 5

#: Bir kanalda solishtiriladigan oxirgi postlar soni (yengil saqlash uchun).
RECENT_POSTS_LIMIT = 10

#: Spec bo'yicha qat'iy ogohlantirish matni (uz).
DUPLICATE_WARNING_MESSAGE = (
    "⚠️ O'xshash post topildi. Bu post yaqindagi postingizga juda o'xshaydi."
)

# So'zlarni ajratish: bo'sh joy/qatorlar bo'yicha (normalizatsiyadan keyin).
_WS_RE = re.compile(r"\s+")
# Token ichida qoldiriladigan belgilar: unicode harflar, raqamlar, _ va -
# (boshqa belgilar — tinish belgisi, emoji, { } — olib tashlanadi).
_STRIP_RE = re.compile(r"[^\w\-']+", re.UNICODE)
# URL'lar butunlay olib tashlanadi — havola takrorlanishi matn o'xshashligini
# soxta oshirib yuboradi (har postda bir xil t.me/... bo'lishi mumkin).
_URL_RE = re.compile(r"https?://\S+|www\.\S+|t\.me/\S+", re.IGNORECASE)


# ---------------------------------------------------------------------------
# PURE hisob-kitob (DB'siz, deterministik, AI'siz)
# ---------------------------------------------------------------------------
def normalize_text(text: Any) -> str:
    """Matnni taqqoslash uchun normalizatsiya qiladi.

    * kichik harfga tushiriladi (casefold — unicode uchun ham);
    * URL'lar butunlay olib tashlanadi;
    * tinish belgilari/emoji/qavslar bo'sh joyga almashtiriladi;
    * bo'shliqlar bittaga siqiladi.
    """
    raw = "" if text is None else str(text)
    raw = raw.casefold()
    raw = _URL_RE.sub(" ", raw)
    raw = _STRIP_RE.sub(" ", raw)
    return _WS_RE.sub(" ", raw).strip()


def tokenize(text: Any) -> set[str]:
    """Normalizatsiyalangan matndagi UNIKAL so'z tokenlari to'plami."""
    return {t for t in normalize_text(text).split(" ") if t}


def jaccard_similarity(a: Any, b: Any) -> float:
    """Ikkala matn token to'plami bo'yicha Jaccard: |A∩B| / |A∪B|.

    Bo'sh to'plamlarda 0.0 qaytaradi (0/0 aniqlanmagan — soxta 1.0 YO'Q).
    """
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return round(len(ta & tb) / len(union), 4)


def containment_ratio(a: Any, b: Any) -> float:
    """Token overlap (containment): |A∩B| / min(|A|, |B|).

    Kichik matn katta matn ichiga to'liq "kirib qolgan" holatlarni ushlaydi
    (masalan, eski postga yangi sarlavha qo'shilgan). KUCHLI QOIDA: kichik
    to'plam ``MIN_TOKENS_FOR_CONTAINMENT`` dan kam tokenli bo'lsa — 0.0
    (1-2 so'zli matnlar soxta 100% bermasin).
    """
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    smaller = min(len(ta), len(tb))
    if smaller < MIN_TOKENS_FOR_CONTAINMENT:
        return 0.0
    return round(len(ta & tb) / smaller, 4)


def similarity(a: Any, b: Any) -> float:
    """Yengil o'xshashlik balli: max(Jaccard, token overlap).

    Ikki metrik ham "token overlap oilasi"ga tegishli — hech qanday AI
    chaqiruvisiz, bir necha millisekundda hisoblanadi.
    """
    ta, tb = tokenize(a), tokenize(b)
    if not ta or not tb:
        return 0.0
    if min(len(ta), len(tb)) < MIN_TOKENS_FOR_CHECK:
        return 0.0
    return max(jaccard_similarity(a, b), containment_ratio(a, b))


def check_duplicate(
    new_text: Any,
    recent_texts: Iterable[Any] | None,
    threshold: float = DUPLICATE_THRESHOLD,
) -> dict:
    """Yangi matn kanalning oxirgi postlari bilan solishtiriladi (PURE).

    Qaytadi::

        {"checked": bool,      # taqqoslash umuman bajarildimi (matn yetarlimi)
         "duplicate": bool,    # threshold dan YUQORI o'xshashlik topildimi
         "score": float,       # eng yuqori o'xshashlik (0.0..1.0)
         "match_index": int|None,   # o'xshash post indeksi (recent_texts'da)
         "matched_text": str,       # o'xshash postning o'zi (preview uchun)
         "threshold": float}

    ``checked=False`` — yangi matn juda qisqa (< 3 token) yoki solishtirish
    uchun hech narsa yo'q: bunda ``duplicate`` HAR DOIM ``False`` (fail-open
    emas — shunchaki taqqoslab bo'lmaydi, postni to'smaydi).
    """
    thr = float(threshold)
    result = {
        "checked": False,
        "duplicate": False,
        "score": 0.0,
        "match_index": None,
        "matched_text": "",
        "threshold": thr,
    }
    if new_text is None:
        return result
    new_norm_tokens = tokenize(new_text)
    if len(new_norm_tokens) < MIN_TOKENS_FOR_CHECK:
        return result
    result["checked"] = True

    best_score = 0.0
    best_index = None
    best_text = ""
    for index, item in enumerate(recent_texts or []):
        if item is None:
            continue
        candidate = str(item)
        score = similarity(new_text, candidate)
        if score > best_score:
            best_score = score
            best_index = index
            best_text = candidate
    result["score"] = round(best_score, 4)
    if best_index is not None and best_score > thr:
        result["duplicate"] = True
        result["match_index"] = best_index
        result["matched_text"] = best_text
    return result


# ---------------------------------------------------------------------------
# DB + ownership bilan asinxron xizmat (fail-soft)
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


async def screen_post_for_duplicates(
    channel_id: str | int,
    user_id: int | None,
    new_text: str,
    db_module: Any = None,
    limit: int = RECENT_POSTS_LIMIT,
) -> dict:
    """Kanalning oxirgi postlari bilan yangi matnni tekshiradi (IDOR + fail-soft).

    * ``user_id`` berilganda kanal AYNAN shu foydalanuvchiga tegishli
      bo'lishi shart — aks holda ``FORBIDDEN`` (boshqa birovning kanal
      tarixini o'qib taqqoslash QAT'IYAN MAN);
    * kanal tarixi ``channel_posts_history`` dan (content ustuni) o'qiladi;
    * har qanday xatoda detektor postni TO'SMAYDI: ``{"ok": True,
      "checked": False, "duplicate": False, ...}`` (fail-soft).

    Qaytadi::

        {"ok": True, "checked": True, "duplicate": True, "score": 0.93,
         "matched_text": "...", "message": "...", "threshold": 0.85}
    """
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return {"ok": False, "error_code": "INVALID_CHANNEL",
                "checked": False, "duplicate": False, "score": 0.0,
                "matched_text": "", "message": "Kanal ID bo'sh"}
    db = db_module if db_module is not None else _import_database()
    if db is None or not hasattr(db, "get_channel_posts_history"):
        return {"ok": True, "checked": False, "duplicate": False,
                "score": 0.0, "matched_text": "", "message": ""}

    try:
        # --- RBAC/IDOR (fail-closed) ---
        if user_id is not None and hasattr(db, "get_channel_owner_id"):
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
                    "ok": False, "error_code": "FORBIDDEN",
                    "checked": False, "duplicate": False, "score": 0.0,
                    "matched_text": "", "channel_id": ch_id,
                    "message": "Bu kanal sizga tegishli emas — dublikat "
                               "tekshiruvi faqat kanal egasiga ochiladi.",
                }

        history = await _db_call(
            db, db.get_channel_posts_history, ch_id, int(limit))
    except Exception as e:  # fail-soft: detektor hech qachon to'suvchi bo'lmaydi
        logger.debug("Dublikat detektori: kanal tarixini o'qib bo'lmadi "
                     "(%s): %s", ch_id, e)
        return {"ok": True, "checked": False, "duplicate": False,
                "score": 0.0, "matched_text": "", "message": ""}

    recent_texts = []
    for row in history or []:
        try:
            content = row.get("content") if isinstance(row, dict) else row[3]
        except (IndexError, TypeError, AttributeError):
            continue
        if content:
            recent_texts.append(str(content))

    result = check_duplicate(new_text, recent_texts)
    result["ok"] = True
    if result["duplicate"]:
        result["message"] = DUPLICATE_WARNING_MESSAGE
    else:
        result["message"] = ""
    return result


__all__ = [
    "DUPLICATE_THRESHOLD",
    "DUPLICATE_WARNING_MESSAGE",
    "MIN_TOKENS_FOR_CHECK",
    "MIN_TOKENS_FOR_CONTAINMENT",
    "RECENT_POSTS_LIMIT",
    "check_duplicate",
    "containment_ratio",
    "jaccard_similarity",
    "normalize_text",
    "screen_post_for_duplicates",
    "similarity",
    "tokenize",
]
