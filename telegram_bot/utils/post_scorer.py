"""📊 POST SCORE & IMPROVER — KILLER FEATURE #4 (baholash yadrosi).

Vazifasi
--------
Foydalanuvchi postini **6 mezon** bo'yicha 1–10 ball bilan baholash va
100 ballik umumiy natija hamda 1–2 jumlalik aniq tavsiya qaytarish::

    headline        — sarlavha kuchi (birinchi qator)
    readability     — o'qilishi va abzaslar
    cta             — harakatga chaqiruv aniqligi
    engagement      — qiziqarlilik va savollar
    sales_power     — sotuv / taklif kuchi
    structure       — Telegram formatlash, emojilar, hashtaglar
    overall_score   — mezonlarning 100 ballik ekvivalenti (o'rtacha × 10)
    recommendation  — 1–2 jumlalik qisqa tavsiya

Ishlash tartibi (ikki qavatli himoya)
------------------------------------
1. **AI baholash** — mavjud Gemini Flash → Groq Llama → ... bepul zanjiri
   (``utils.ai_agent.generate_ai_response``, 4-BOSQICH multi-provider
   fallback). Tizim prompti modeldan **faqat JSON** qaytarishni qat'iy talab
   qiladi; ``with_language`` esa tavsiya foydalanuvchi tilida bo'lishini
   kafolatlaydi.
2. **Lokal (deterministik) baholash** — AI butunlay ishlamay qolsa
   (``ai_unavailable``/timeout) ballar ``score_post_locally`` orqali tezkor
   hisoblanadi. Shu tufayli baholash funksiyasi HECH QACHON yiqilmaydi va
   foydalanuvchi kredit/kvota yo'qotmaydi.

Xavfsiz JSON parser
-------------------
``parse_post_score_json`` provayder javobidagi JSON'ni himoyalangan tarzda
o'qiydi: markdown ```json to'siqlari, izohlar, qo'shtirnoq/burchak qoldiqlari,
``8/10`` ko'rinishidagi satr qiymatlar va umuman buzilgan javoblar (regex
zaxira) bilan ham ishlaydi — hech qachon istisno ko'tarmaydi.

Resurs siyosati
---------------
* **Baholash (Score)** — tezkor va arzon operatsiya: kredit YECHILMAYDI,
  kunlik AI kvota sarflanmaydi. Faqat rate-limit (``check_ai_rate_limit``)
  handlerda qo'llanadi.
* **«✨ 95/100 ga yaxshilash»** — bu bosqichda handler 1 ta AI kreditini
  ATOMIK yechadi (``db.use_user_credit`` → ``CreditsService.spend_credits``)
  va xatolikda qaytaradi (refund). ``improve_post_to_95`` AI javoblaridan eng
  sara variantni tanlaydi (lokal ball bo'yicha, qo'shimcha kredit sarflanmaydi).
"""

from __future__ import annotations

import json
import logging
import os
import re

from utils.ai_agent import (
    ensure_magic_hashtags,
    generate_ai_response,
    normalize_ai_lang,
    pick_supported_kwargs,
    sanitize_magic_post_html,
    with_language,
)

logger = logging.getLogger(__name__)

# ============================================================
# KONSTANTALAR
# ============================================================
#: Baholanadigan mezonlar (tartib UI'dagi tartib bilan bir xil).
POST_SCORE_CRITERIA = (
    "headline",
    "readability",
    "cta",
    "engagement",
    "sales_power",
    "structure",
)

SCORE_MIN = 1
SCORE_MAX = 10
OVERALL_MAX = 100
#: «✨ 95/100 ga yaxshilash» tugmasining maqsadli balli.
TARGET_SCORE = 95

#: Baholash uchun minimal matn uzunligi (belgi) — bundan qisqasi mazmunsiz.
POST_SCORE_MIN_CHARS = max(10, int(os.getenv("POST_SCORE_MIN_CHARS", "20")))
#: AI'ga yuboriladigan matnning maksimal uzunligi (Telegram posti chegarasi).
POST_SCORE_MAX_CHARS = max(200, int(os.getenv("POST_SCORE_MAX_CHARS", "3500")))
#: Baholash uchun qat'iy timeout (tezkor operatsiya — 20s).
POST_SCORE_TIMEOUT = max(5.0, float(os.getenv("POST_SCORE_TIMEOUT", "20")))
#: Yaxshilash jarayonida maksimal urinishlar soni (eng sara variant tanlanadi).
IMPROVE_MAX_ATTEMPTS = max(1, min(3, int(os.getenv("POST_SCORE_IMPROVE_ATTEMPTS", "2"))))

#: Tavsiya matnining maksimal uzunligi (UI xavfsizligi).
RECOMMENDATION_MAX_CHARS = 400

_HTML_TAG_RE = re.compile(r"<[^>]{1,200}>")
_WS_RE = re.compile(r"[ \t\u00a0]+")
_EMOJI_RE = re.compile(
    "[" "\U0001F300-\U0001FAFF" "\U00002600-\U000027BF" "\U0001F000-\U0001F2FF"
    "\U00002B00-\U00002BFF" "\u2764\u2b50\u2705\u274c\u2714\u2728" "]"
)
_HASHTAG_RE = re.compile(r"(?<!\w)#\w{2,}", re.UNICODE)
_BULLET_RE = re.compile(r"^\s*(?:[-•*✅✔️🔹▪️]|\d+[.)])\s+", re.MULTILINE)
_LINK_RE = re.compile(r"(https?://|t\.me/|@\w{4,})", re.IGNORECASE)
_NUMBER_VALUE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|so'm|sum|руб|₽|\$|€|usd|uzs)?", re.IGNORECASE)

#: CTA (harakatga chaqiruv) belgilari.
_CTA_MARKERS = {
    "uz": ("buyurtma", "yozing", "yozib", "bog'lan", "boglan", "murojaat",
           "hoziroq", "havola", "pastdagi", "obuna", "ro'yxatdan", "qo'ng'iroq",
           "shoshiling", "olib ket", "manzil"),
    "ru": ("закаж", "напиш", "свяж", "позвон", "подпиш", "перейд", "ссылк",
           "оформ", "успей", "жми", "запис"),
    "en": ("order", "buy", "contact", "dm ", "click", "link", "subscribe",
           "sign up", "get yours", "call ", "book", "grab"),
}

#: Sotuv / taklif kuchi belgilari.
_SALES_MARKERS = {
    "uz": ("chegirma", "aksiya", "narx", "bonus", "bepul", "sovg'a", "kafolat",
           "tejamkor", "foyda", "topshirish", "skidka", " chegirma", "tekin"),
    "ru": ("скидк", "акци", "цен", "бонус", "бесплат", "гаранти", "выгод",
           "доставк", "подарок", "распродаж"),
    "en": ("discount", "sale", "price", "bonus", "free", "guarantee", "offer",
           "delivery", "gift", "limited"),
}

#: Ikkinchi shaxs murojaati (engagement uchun).
_YOU_MARKERS = {
    "uz": ("siz", "sizga", "sizni", "sizning", "sen", "senga"),
    "ru": ("вы ", "вас", "вам", "ваш", "ты ", "тебе"),
    "en": ("you ", "your", "you're", "yours"),
}


# ============================================================
# MATN YORDAMCHILARI
# ============================================================
def strip_html(text) -> str:
    """HTML teglarni olib tashlaydi (tahlil uchun toza matn)."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub(" ", str(text))


def plain_text(text) -> str:
    """Tahlil uchun normalizatsiya qilingan toza matn."""
    clean = strip_html(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_WS_RE.sub(" ", line).strip() for line in clean.split("\n")]
    return "\n".join(lines).strip()


def validate_post_text(text) -> tuple[str, str]:
    """Post matnini tekshiradi va ``(tozalangan_matn, xato_kaliti)`` qaytaradi.

    Xato kalitlari (i18n): ``"empty"`` | ``"too_short"`` | ``"no_content"``;
    matn yaroqli bo'lsa ``("...", "")``.

    Funksiya hech qachon istisno ko'tarmaydi — handler shu sababli
    foydalanuvchiga doim xavfsiz ogohlantirish ko'rsata oladi.
    """
    raw = "" if text is None else str(text)
    clean = plain_text(raw)
    if not clean:
        return "", "empty"
    # Mazmun (harf/raqam) umuman bo'lmasa — faqat tinish belgilari/emojilar.
    letters = re.sub(r"[^\w]", "", clean, flags=re.UNICODE)
    if len(letters) < 3:
        return clean, "no_content"
    if len(clean) < POST_SCORE_MIN_CHARS:
        return clean, "too_short"
    if len(clean) > POST_SCORE_MAX_CHARS:
        return clean[:POST_SCORE_MAX_CHARS], ""
    return clean, ""


# ============================================================
# BALL YORDAMCHILARI
# ============================================================
def clamp_score(value) -> int:
    """Qiymatni 1..10 oralig'iga keltiradi (noma'lum qiymat → 1)."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return SCORE_MIN
    return max(SCORE_MIN, min(SCORE_MAX, number))


def overall_from_scores(scores: dict) -> int:
    """6 mezon o'rtachasining 100 ballik ekvivalenti (1..100)."""
    values = [clamp_score(scores.get(name)) for name in POST_SCORE_CRITERIA]
    if not values:
        return 0
    average = sum(values) / len(values)
    return max(1, min(OVERALL_MAX, int(round(average * 10))))


def score_bar(value, width: int = 10) -> str:
    """1–10 ballni vizual shkalaga aylantiradi: ``▰▰▰▰▰▰▱▱▱▱``."""
    filled = clamp_score(value)
    filled = max(0, min(width, filled))
    return "▰" * filled + "▱" * (width - filled)


def weakest_criterion(scores: dict) -> str:
    """Eng past ballli mezon (tavsiya shu mezonga qaratiladi)."""
    best_name, best_value = POST_SCORE_CRITERIA[0], SCORE_MAX + 1
    for name in POST_SCORE_CRITERIA:
        value = clamp_score((scores or {}).get(name))
        if value < best_value:
            best_name, best_value = name, value
    return best_name


# ============================================================
# AI PROMPTLARI (BARQAROR JSON KONTRAKTI)
# ============================================================
_POST_SCORE_SYSTEM = """Siz PostAssist — Telegram kanallari uchun professional SMM auditorisiz.
Vazifangiz: foydalanuvchi postini 6 mezon bo'yicha 1 dan 10 gacha ball bilan
xolis baholash va 1-2 jumlalik aniq tavsiya berish.

MEZONLAR (har biri 1-10 butun son):
- headline — sarlavha kuchi: birinchi qator diqqatni jalb qiladimi, qisqami;
- readability — o'qilishi: abzaslar, jumla uzunligi, tushunarlilik;
- cta — harakatga chaqiruv aniqligi: oxirida aniq qadam bormi;
- engagement — qiziqarlilik: savollar, hissiyot, o'quvchi bilan muloqot;
- sales_power — sotuv/taklif kuchi: foyda, narx, chegirma, kafolat aniqmi;
- structure — Telegram formatlash: qalin sarlavha, emojilar, punktlar, 3-5 hashtag.

BAHOLASH QOIDALARI:
- 10 ball — juda kuchli, professional daraja; 1 ball — umuman yo'q/bo'sh;
- ballarni sun'iy oshirmang: mezon bajarilmagan bo'lsa past ball qo'ying;
- 5-6 ball — o'rtacha, 7-8 — yaxshi, 9-10 — ajoyib;
- overall_score — 6 mezon o'rtachasining 100 ballik ekvivalenti
  (masalan o'rtacha 7.5 → 75);
- recommendation — foydalanuvchi tilida 1-2 jumla: ANIQ nima o'zgartirish
  kerakligini yozing (umumiy gap emas).

FORMAT (qat'iy): javob FAQAT JSON obyekt bo'lsin, boshqa matn/markdown/izoh
YO'Q:
{"headline": 8, "readability": 7, "cta": 6, "engagement": 7, "sales_power": 6, "structure": 8, "overall_score": 70, "recommendation": "1-2 jumlalik tavsiya"}"""

_POST_IMPROVE_SYSTEM = """Siz PostAssist — Telegram kanallari uchun professional SMM
kopirayter va muharrirsiz. Vazifangiz: foydalanuvchi postini 95/100 dan past
bo'lmagan darajaga ko'tarish (sifatni sakrab oshirish, faktlarni buzmaslik).

QAT'IY QOIDALAR:
- postning BARCHA faktlarini saqlang (nom, narx, sana, manzil, havola) —
  hech narsani o'zgartirmang va o'zingizdan qo'shmang;
- birinchi qatorda 60 belgidan oshmaydigan kuchli sarlavha (<b>...</b>);
- matnni 2-4 qisqa abzasga bo'ling; ro'yxat kerak bo'lsa "•" yoki "✅" bilan;
- 2-4 ta mos emoji ishlating (ko'p emas), oxirida aniq CTA;
- oxirgi qatorda 3-5 hashtag (bo'sh joy bilan ajratilgan);
- faqat Telegram uchun xavfsiz HTML: <b> va <i> teglari (boshqa teg YO'Q;
  <script>, <a>, <div> va h.k. taqiqlanadi);
- matn uzunligi 400-1200 belgi oralig'ida bo'lsin.

MAQSAD: sarlavha, o'qilishi, CTA, qiziqarlilik, sotuv kuchi va struktura
mezonlarining barchasi 9-10 ball bo'lishi kerak.

FORMAT (qat'iylik): javob FAQAT JSON:
{"post_text": "tayyor yaxshilangan post", "changes": ["nima o'zgardi (qisqa)"]}"""


def build_post_score_system_prompt() -> str:
    """Baholash uchun tizim prompti (JSON kontrakti bilan)."""
    return _POST_SCORE_SYSTEM


def build_post_score_prompt(text: str, lang: str = "uz") -> str:
    """Baholanayotgan postni o'rab beruvchi user prompti."""
    code = normalize_ai_lang(lang)
    body = str(text or "").strip()[:POST_SCORE_MAX_CHARS]
    return (
        f"Baholanishi kerak bo'lgan post (til: {code}):\n"
        "--- POST START ---\n"
        f"{body}\n"
        "--- POST END ---\n"
        "Javobni FAQAT yuqoridagi JSON formatida qaytaring."
    )


def build_improve_system_prompt() -> str:
    """«95/100 ga yaxshilash» uchun tizim prompti."""
    return _POST_IMPROVE_SYSTEM


def build_improve_prompt(text: str, scores: dict = None, lang: str = "uz") -> str:
    """Yaxshilash uchun user prompti (kuchsiz mezonlar ko'rsatiladi)."""
    code = normalize_ai_lang(lang)
    body = str(text or "").strip()[:POST_SCORE_MAX_CHARS]
    weak = weakest_criterion(scores or {}) if scores else "structure"
    return (
        "Quyidagi postni 95/100 dan past bo'lmagan sifatga yetkazing.\n"
        f"Til: {code}. Eng ko'p e'tibor bering: {weak}.\n"
        "--- POST START ---\n"
        f"{body}\n"
        "--- POST END ---\n"
        'Javobni FAQAT {"post_text": "..."} JSON formatida qaytaring.'
    )


# ============================================================
# XAVFSIZ JSON PARSER
# ============================================================
def _repair_json(raw: str) -> str:
    """Keng tarqalgan model xatolarini tuzatadi (oxirgi urinish)."""
    fixed = raw.replace("'", '"').replace("\n", " ")
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)          # trailing comma
    fixed = re.sub(r"\bTrue\b", "true", fixed)
    fixed = re.sub(r"\bFalse\b", "false", fixed)
    fixed = re.sub(r"\bNone\b", "null", fixed)
    return fixed


def _json_slice(raw: str) -> str:
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return raw[start:end + 1]


def _regex_fallback(raw: str) -> dict:
    """JSON butunlay buzilganda maydonlarni regex bilan yig'adi."""
    data: dict = {}
    for name in POST_SCORE_CRITERIA + ("overall_score",):
        match = re.search(
            rf'["\']?{name}["\']?\s*[:=]\s*["\']?\s*(\d{{1,3}})', raw, re.IGNORECASE
        )
        if match:
            try:
                data[name] = int(match.group(1))
            except (TypeError, ValueError):
                continue
    match = re.search(
        r'["\']?recommendation["\']?\s*[:=]\s*["\'](.{1,600}?)["\']\s*[,}]',
        raw, re.IGNORECASE | re.DOTALL,
    )
    if match:
        data["recommendation"] = match.group(1).strip()
    return data


def _flatten_payload(data) -> dict:
    """Ichki konteynerlarni ochadi (``scores``/``result``/``audit``)."""
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), {})
    if not isinstance(data, dict):
        return {}
    merged = dict(data)
    for container in ("scores", "result", "audit", "data", "analysis"):
        inner = data.get(container)
        if isinstance(inner, dict):
            for key, value in inner.items():
                merged.setdefault(key, value)
        elif isinstance(inner, list):
            inner = next((item for item in inner if isinstance(item, dict)), None)
            if isinstance(inner, dict):
                for key, value in inner.items():
                    merged.setdefault(key, value)
    return merged


def parse_post_score_json(raw) -> dict:
    """AI javobidan ball JSON'ini XAVFSIZ ajratadi (hech qachon istisno bermaydi).

    Qo'llab-quvvatlanadi:
      * tayyor dict/list (provayder JSON'ni o'zi parse qilgan bo'lsa);
      * ```json to'siqlari va JSON atrofidagi izohlar;
      * ``"8/10"``, ``"8 ball"``, ``"75%"`` kabi satr qiymatlar;
      * buzilgan JSON (regex zaxira).

    Returns:
        dict — topilgan maydonlar (bo'sh dict ham mumkin).
    """
    if raw is None:
        return {}
    if isinstance(raw, (dict, list)):
        return _flatten_payload(raw)
    text = str(raw).strip()
    if not text:
        return {}

    # Markdown to'siqlarini olib tashlaymiz.
    text = re.sub(r"```[a-zA-Z]*", "", text).strip()
    candidate = _json_slice(text)

    for attempt in (candidate, _repair_json(candidate) if candidate else ""):
        if not attempt:
            continue
        try:
            parsed = json.loads(attempt, parse_constant=lambda _v: 0)
        except Exception:
            continue
        data = _flatten_payload(parsed)
        if data:
            return data

    # Zaxira: maydonlarni regex bilan yig'amiz.
    fallback = _regex_fallback(text)
    if fallback:
        logger.info("Post Score JSON buzilgan — regex zaxira ishlatildi")
    return fallback


def _value_to_score(value, default: int) -> int:
    """Har xil ko'rinishdagi ball qiymatini 1..10 ga keltiradi."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        number = float(value)
        # 0..100 oralig'idagi qiymat kelganda 10 ballikka keltiramiz.
        if number > SCORE_MAX:
            number = number / 10.0
        return clamp_score(number)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return default
    number = float(match.group(0).replace(",", "."))
    if number > SCORE_MAX and number <= OVERALL_MAX:
        number = number / 10.0
    if number <= 0:
        return default
    return clamp_score(number)


def _clean_recommendation(value) -> str:
    """Tavsiya matnini xavfsiz tozalaydi (HTML'siz, uzunlik cheklangan)."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if item)
    clean = strip_html(str(value))
    clean = re.sub(r"\s+", " ", clean).strip().strip('"').strip("'")
    if len(clean) > RECOMMENDATION_MAX_CHARS:
        clean = clean[:RECOMMENDATION_MAX_CHARS - 1].rstrip() + "…"
    return clean


def normalize_post_score(raw, text: str = "", lang: str = "uz",
                         provider: str = "", source: str = "ai") -> dict:
    """Xom AI javobini yagona ball sxemasiga keltiradi.

    Returns:
        {
          "scores": {"headline": 8, ...},   # 6 mezon, 1..10
          "overall": 70,                    # 100 ballik ekvivalent
          "recommendation": "...",          # AI tavsiyasi (bo'sh bo'lishi mumkin)
          "weakest": "cta",                 # eng past mezon (lokal tavsiya uchun)
          "fallback": False,                # lokal baholash ishlatilganmi
          "provider": "Gemini",
          "source": "ai" | "local",
          "lang": "uz",
        }

    ``raw`` da hech qanday mezon topilmasa — ``None`` qaytadi (chaqiruvchi
    lokal baholashga o'tadi).
    """
    data = parse_post_score_json(raw)
    if not data:
        return None

    scores: dict = {}
    for name in POST_SCORE_CRITERIA:
        value = data.get(name)
        if value is None:
            # Muqobil nomlar (model ba'zan boshqacha yozadi).
            for alt in (f"{name}_score", f"score_{name}"):
                if data.get(alt) is not None:
                    value = data.get(alt)
                    break
        scores[name] = _value_to_score(value, default=None) if value is not None else None

    present = [name for name in POST_SCORE_CRITERIA if scores.get(name) is not None]
    overall_raw = data.get("overall_score", data.get("overall"))
    if not present and overall_raw is None:
        return None

    # Yetishmayotgan mezonlar lokal tahlil bilan to'ldiriladi (xolis zaxira).
    local = score_post_locally(text).get("scores", {}) if text else {}
    for name in POST_SCORE_CRITERIA:
        if scores.get(name) is None:
            scores[name] = clamp_score(local.get(name, 5))

    overall = overall_from_scores(scores)
    recommendation = _clean_recommendation(
        data.get("recommendation") or data.get("advice") or data.get("comment")
    )
    return {
        "scores": scores,
        "overall": overall,
        "recommendation": recommendation,
        "weakest": weakest_criterion(scores),
        "fallback": False,
        "provider": provider or "AI",
        "source": source,
        "lang": normalize_ai_lang(lang),
    }


# ============================================================
# LOKAL (DETERMINISTIK) BAHOLASH — AI ishlamay qolganda
# ============================================================
def _contains_any(lowered: str, markers) -> bool:
    return any(marker in lowered for marker in markers)


def score_post_locally(text: str, lang: str = "uz") -> dict:
    """Tezkor deterministik baholash (AI'siz, tarmoqsiz, kreditsiz).

    Har bir mezon 1..10 ball oladi, umumiy ball — o'rtacha × 10. Baholash
    qoidalari shaffof va takrorlanuvchan: bir xil matn har doim bir xil ball
    oladi (testlar uchun deterministik).
    """
    code = normalize_ai_lang(lang)
    clean = plain_text(text)
    lowered = clean.lower()
    lines = [line for line in clean.split("\n") if line.strip()]
    first_line = lines[0] if lines else ""
    length = len(clean)
    emojis = _EMOJI_RE.findall(clean)
    hashtags = _HASHTAG_RE.findall(clean)
    paragraphs = [block for block in re.split(r"\n\s*\n", clean) if block.strip()]
    sentences = [s for s in re.split(r"[.!?…]+", clean) if s.strip()]
    words = re.findall(r"\w+", clean, flags=re.UNICODE)
    avg_sentence_words = (len(words) / len(sentences)) if sentences else len(words)

    # --- headline ---
    headline = 4
    if len(lines) > 1 or len(first_line) <= 80:
        headline = 5
    if len(first_line) <= 60 and first_line:
        headline += 2
    if _EMOJI_RE.search(first_line) or first_line.isupper():
        headline += 1
    if first_line.endswith(("!", ":", "?")):
        headline += 1
    if len(first_line) > 110:
        headline = 3
    if len(lines) == 1 and len(clean) > 200:
        headline = min(headline, 4)
    if len(lines) == 1 and length < 100:
        # Bir qatorli juda qisqa matnda alohida sarlavha tuzilmasi yo'q.
        headline = min(headline, 5)

    # --- readability ---
    readability = 5
    if len(paragraphs) >= 2:
        readability += 2
    if len(lines) >= 4:
        readability += 1
    if avg_sentence_words <= 16:
        readability += 1
    if length < 80:
        readability -= 2
    if length > 1400:
        readability -= 2
    if max((len(block) for block in paragraphs), default=0) > 700:
        readability -= 1

    # --- cta ---
    cta = 3
    cta_markers = _CTA_MARKERS.get(code) or _CTA_MARKERS["en"]
    if _contains_any(lowered, cta_markers):
        cta += 4
    if any(emoji in clean for emoji in ("👉", "🛒", "📩", "📲", "✅", "🔗")):
        cta += 1
    if _LINK_RE.search(clean):
        cta += 1
    if "!" in clean[-160:]:
        cta += 1

    # --- engagement ---
    engagement = 4
    if "?" in clean:
        engagement += 2
    you_markers = _YOU_MARKERS.get(code) or _YOU_MARKERS["en"]
    if _contains_any(lowered, you_markers):
        engagement += 1
    engagement += min(3, len(emojis) // 2)
    if length < 100:
        engagement -= 1

    # --- sales_power ---
    sales = 4
    sales_markers = _SALES_MARKERS.get(code) or _SALES_MARKERS["en"]
    if _contains_any(lowered, sales_markers):
        sales += 3
    if re.search(r"\d+\s*%", clean) or _NUMBER_VALUE_RE.search(clean):
        sales += 1
    if _contains_any(lowered, ("kafolat", "гаранти", "guarantee", "bepul", "бесплат", "free")):
        sales += 1
    if length < 100:
        sales -= 1

    # --- structure ---
    structure = 4
    if len(hashtags) >= 3:
        structure += 2
    elif hashtags:
        structure += 1
    if len(emojis) >= 3:
        structure += 1
    if _BULLET_RE.search(clean):
        structure += 1
    if 200 <= length <= 1200:
        structure += 1
    if length > 2000:
        structure -= 1
    if len(paragraphs) == 1 and length > 600:
        structure -= 1

    scores = {
        "headline": clamp_score(headline),
        "readability": clamp_score(readability),
        "cta": clamp_score(cta),
        "engagement": clamp_score(engagement),
        "sales_power": clamp_score(sales),
        "structure": clamp_score(structure),
    }
    return {
        "scores": scores,
        "overall": overall_from_scores(scores),
        "recommendation": "",
        "weakest": weakest_criterion(scores),
        "fallback": True,
        "provider": "local",
        "source": "local",
        "lang": code,
    }


# ============================================================
# AI CHAQIRUV (BEPUL, KREDITSIZ)
# ============================================================
async def _call_ai(prompt: str, system_instruction: str, lang: str,
                   timeout=None, is_pro: bool = False) -> dict:
    """``generate_ai_response`` ni mos imzo bilan chaqiradi (mock-safe)."""
    kwargs = pick_supported_kwargs(
        generate_ai_response,
        prompt=prompt,
        system_instruction=system_instruction,
        timeout=timeout,
        is_pro=is_pro,
        lang=lang,
    )
    return await generate_ai_response(**kwargs)


async def score_post(text: str, lang: str = "uz", timeout: float = None,
                     use_ai: bool = True) -> dict:
    """Postni 6 mezon bo'yicha baholaydi (BEPUL — kredit yechilmaydi).

    Args:
        text: post matni (HTML teglari tahlildan oldin olib tashlanadi);
        lang: foydalanuvchi tili ('uz' | 'ru' | 'en') — tavsiya shu tilda;
        timeout: qat'iy vaqt chegarasi (None → 20s);
        use_ai: ``False`` bo'lsa faqat lokal deterministik baholash ishlatiladi.

    Returns:
        ``normalize_post_score`` sxemasi; yaroqsiz matnda ``{"error": ...}``:

            {"error": "empty" | "too_short" | "no_content" | "score_failed"}
    """
    code = normalize_ai_lang(lang)
    clean, error = validate_post_text(text)
    if error:
        return {"error": error, "lang": code}

    if use_ai:
        system = with_language(build_post_score_system_prompt(), code)
        prompt = build_post_score_prompt(clean, code)
        try:
            result = await _call_ai(
                prompt, system, code,
                timeout=timeout if timeout is not None else POST_SCORE_TIMEOUT,
            )
        except Exception as e:  # noqa: BLE001 — baholash hech qachon yiqilmaydi
            logger.warning("Post Score AI chaqiruv xatosi: %s", e)
            result = {"error": "exception"}

        # Provayder ba'zan JSON'ni o'zi parse qiladi (dict), ba'zan xom matn
        # qaytaradi (str) — ikkalasi ham xavfsiz parser orqali o'qiladi.
        provider = ""
        raw_payload = None
        if isinstance(result, dict):
            if not result.get("error"):
                provider = str(result.get("provider") or "AI")
                raw_payload = result
        elif isinstance(result, (str, list)):
            raw_payload = result

        if raw_payload is not None:
            payload = normalize_post_score(
                raw_payload, text=clean, lang=code,
                provider=provider or "AI", source="ai",
            )
            if payload:
                return payload
            logger.info("Post Score: AI javobida mezonlar topilmadi — lokal baholash")
        elif isinstance(result, dict) and result.get("error"):
            logger.info(
                "Post Score: AI mavjud emas (%s) — lokal baholashga o'tildi",
                result.get("error"),
            )
        else:
            logger.info("Post Score: AI javobi kutilmagan formatda — lokal baholash")

    # --- Zaxira: lokal baholash (kreditsiz, tarmoqsiz, deterministik) ---
    return score_post_locally(clean, code)


# ============================================================
# «✨ 95/100 GA YAXSHILASH»
# ============================================================
def _extract_improved_text(result) -> str:
    """AI javobidan yaxshilangan postni ajratadi (zaxira kalitlar bilan)."""
    if not isinstance(result, dict):
        return ""
    for key in ("post_text", "improved_post", "text", "reply", "content"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def improve_post_to_95(text: str, lang: str = "uz", is_pro: bool = False,
                             timeout: float = None, attempts: int = None) -> dict:
    """Postni 95+ ballik eng sara variantga qayta ishlaydi.

    Kreditni chaqiruvchi HANDLER yechadi (bu funksiya resurs siyosatiga
    aralashmaydi). Funksiya bir necha urinishdan eng yuqori lokal ballga ega
    variantni tanlaydi — qo'shimcha kredit sarflanmaydi.

    Returns:
        {"post_text": "...", "score": {...}, "attempts": 2,
         "target_met": True, "lang": "uz"} — muvaffaqiyatda;
        {"error": "<lokalizatsiya qilingan xabar>"} — AI ishlamaganda.
    """
    from utils.ai_agent import localize_ai_error

    code = normalize_ai_lang(lang)
    clean, error = validate_post_text(text)
    if error:
        return {"error": localize_ai_error(
            "⚠️ Yaxshilash uchun post matni topilmadi.", code
        )}

    tries = attempts if isinstance(attempts, int) and attempts > 0 else IMPROVE_MAX_ATTEMPTS
    tries = max(1, min(3, tries))

    baseline = score_post_locally(clean, code)
    system = with_language(build_improve_system_prompt(), code)

    best_text, best_score, best_meta = "", None, {}
    last_error = ""
    for attempt in range(1, tries + 1):
        prompt = build_improve_prompt(clean, baseline.get("scores"), code)
        if attempt > 1:
            prompt += (
                "\nOldingi variant yetarli emas — yanada kuchliroq sarlavha, "
                "aniqroq CTA va yaxshiroq struktura bilan qayta yozing."
            )
        try:
            result = await _call_ai(
                prompt, system, code,
                timeout=timeout if timeout is not None else POST_SCORE_TIMEOUT,
                is_pro=is_pro,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("Post Score improve xatosi (%s/urinish): %s", attempt, e)
            result = {"error": "exception"}

        if isinstance(result, dict) and result.get("error"):
            last_error = str(result.get("error"))
            continue

        # Provayder JSON'ni o'zi parse qilgan (dict) yoki xom matn (str)
        # qaytargan bo'lishi mumkin — ikkalasi ham qo'llab-quvvatlanadi.
        payload = result if isinstance(result, dict) else parse_post_score_json(result)
        candidate = _extract_improved_text(payload or {})
        if not candidate and isinstance(result, str) and result.strip():
            # Model JSON o'rashsiz to'g'ridan-to'g'ri post matnini qaytardi.
            candidate = result.strip()
        if not candidate:
            last_error = "empty_result"
            continue

        # Xavfsiz HTML + 3-5 hashtag kafolati (Magic Post bilan bir xil qoidalar).
        candidate = sanitize_magic_post_html(
            ensure_magic_hashtags(candidate, "casual", code)
        ).strip()
        if not candidate:
            last_error = "empty_after_sanitize"
            continue

        candidate_score = score_post_locally(candidate, code)
        if best_score is None or candidate_score["overall"] > best_score["overall"]:
            best_text, best_score = candidate, candidate_score
            best_meta = {
                "provider": (result or {}).get("provider") if isinstance(result, dict) else None,
                "provider_chain": (
                    (result or {}).get("provider_chain") if isinstance(result, dict) else None
                ),
            }
        if best_score["overall"] >= TARGET_SCORE:
            break

    if not best_text or best_score is None:
        logger.info("Post Score: yaxshilash bajarilmadi (%s)", last_error)
        return {"error": localize_ai_error(
            "⚠️ AI hozircha javob bermadi — 1 kredit qaytarildi. "
            "Birozdan so'ng qayta urinib ko'ring.", code
        )}

    payload = dict(best_score)
    payload["lang"] = code
    payload["source"] = "ai"
    payload["provider"] = best_meta.get("provider") or payload.get("provider")
    return {
        "post_text": best_text,
        "score": payload,
        "attempts": attempt,
        "target_met": payload["overall"] >= TARGET_SCORE,
        "provider": payload.get("provider"),
        "provider_chain": best_meta.get("provider_chain"),
        "lang": code,
    }
