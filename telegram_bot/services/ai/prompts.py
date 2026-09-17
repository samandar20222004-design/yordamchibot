"""🧭 POSTASSIST — AI PROMPT MARKAZI: formatlar, sifat qoidalari, fluff-guard.

3-QADAM (POSTASSIST UI/UX POLISH) — AI generatsiya sifati:

1. MAVZU ANIQLIGI — ``needs_clarification()``: 3 so'zdan qisqa yoki umumiy
   mavzu (``"sport"``, ``"yangiliklar"``, ``"biznes"``, ``"sport haqida
   bo'lsin"``) to'g'ridan-to'g'ri generatsiyaga yuborilmaydi — avval
   ``handlers.ai_post`` wizard'i yo'nalishni aniqlashtiradi.
2. FORMAT AJRATISH — ``detect_post_format()``: axborot so'zlari (yangilik,
   xabar, sport, voqea) HECH QACHON ``"sales"`` ga aylanmaydi — ular doim
   ``"news"`` (📰 Axborot / Yangilik) formatiga tushadi. Tekshiruv tartibi
   qat'iy: INFO → SALES → TIPS → SHORT.
3. SOTUV INTIZOMI — ``should_ask_sales_params()``: sotuv kalit so'zli, lekin
   aniq tafsilotsiz (narx/raqam/sana yo'q) mavzuda AI mahsulotsiz post
   to'qimaydi — avval mahsulot parametrlari so'raladi.
4. FLUFF-GUARD — ``FORBIDDEN_FLUFF_PHRASES``: ``"Kanalga obuna bo'ling"``,
   ``"Bizning kanal eng ishonchli manba"``, ``"Har kuni siz uchun saralab
   olamiz"`` kabi quruq "suv" shablonlar barcha generatsiya promptlarida
   TAQIQLANADI (``scan_text_for_fluff()`` bilan qo'riqlanadi).
5. SIFAT STANDARTI — ``QUALITY_RULES``: kuchli Hook, Telegram HTML
   (``<b>``, ``<i>``), ro'yxatlar (•) va ANIQ mazmun (fakt/raqam/maslahat).

Bu modul FAQAT stdlib'ga tayanadi (telegram/database import YO'Q) — ham
handler'lar, ham testlar uni xavfsiz import qila oladi.
"""

from __future__ import annotations

import re

__all__ = [
    "FORMAT_NEWS",
    "FORMAT_TIPS",
    "FORMAT_SHORT",
    "FORMAT_SALES",
    "FORMAT_GENERAL",
    "POST_FORMATS",
    "INFO_KEYWORDS",
    "SALES_KEYWORDS",
    "TIPS_KEYWORDS",
    "SHORT_KEYWORDS",
    "GENERIC_TOPICS",
    "FILLER_WORDS",
    "EXACT_ONLY_KEYWORDS",
    "FORBIDDEN_FLUFF_PHRASES",
    "QUALITY_RULES",
    "FORMAT_SYSTEMS",
    "FORMAT_TO_MAGIC_STYLE",
    "normalize_topic",
    "count_words",
    "tokenize",
    "meaningful_tokens",
    "needs_clarification",
    "detect_post_format",
    "is_sales_topic",
    "has_concrete_details",
    "should_ask_sales_params",
    "scan_text_for_fluff",
    "prompts_contain_fluff",
    "build_format_system",
    "format_hint_line",
    "map_format_to_magic_style",
]


# ---------------------------------------------------------------------------
# FORMAT IDENTIFIKATORLARI
# ---------------------------------------------------------------------------
FORMAT_NEWS = "news"        # 📰 Yangiliklar / Voqea
FORMAT_TIPS = "tips"        # 💡 Maslahat / Tahlil
FORMAT_SHORT = "short"      # 🔥 Qisqa / Faktlar
FORMAT_SALES = "sales"      # 🛒 Mahsulot / Sotuv
FORMAT_GENERAL = "general"  # aniqlanmagan (wizard talab qiladi)

POST_FORMATS: tuple[str, ...] = (
    FORMAT_NEWS, FORMAT_TIPS, FORMAT_SHORT, FORMAT_SALES,
)


# ---------------------------------------------------------------------------
# KALIT SO'ZLAR (o'zaklar — kichik harfda; token BOSHIDAN moslashadi)
# ---------------------------------------------------------------------------
#: Axborot o'zaklari — BIRINCHI navbatda tekshiriladi. Bulardan biri
#: topilsa format doim ``news`` (sotuv kalit so'zlari e'tiborsiz qoldiriladi).
INFO_KEYWORDS: tuple[str, ...] = (
    # uz
    "yangilik", "xabar", "sport", "voqea", "hodisa",
    # ru
    "новость", "новости", "событи", "спорт",
    # en
    "news", "sport", "event",
)

#: Sotuv o'zaklari — IKKINCHI navbatda (INFO topilmasa) tekshiriladi.
SALES_KEYWORDS: tuple[str, ...] = (
    # uz
    "sotil", "sotuv", "sotib", "narx", "aksiya", "chegirma",
    "buyurtma", "arzon",
    # ru
    "скидк", "акци", "прода", "куп", "цен", "заказ",
    # en
    "sale", "discount", "price", "buy", "order", "shop", "promo",
)

#: Maslahat/tahlil o'zaklari — UCHINCHI navbatda.
TIPS_KEYWORDS: tuple[str, ...] = (
    # uz
    "maslahat", "tahlil", "tavsiya", "qo'llanma", "dars",
    # ru
    "совет", "анализ", "рекомендац", "инструкц", "как",
    # en
    "tips", "advice", "guide", "howto", "how",
)

#: Qisqa/fakt o'zaklari — TO'RTINCHI navbatda.
SHORT_KEYWORDS: tuple[str, ...] = (
    # uz
    "qisqa", "fakt", "lo'nda", "londa",
    # ru
    "кратк", "факт", "коротко",
    # en
    "short", "fact", "quick", "brief",
)

#: Juda qisqa (≤3 belgi) o'zaklar — FAQAT butun token mos kelsa hisoblanadi
#: (aks holda "kakao"→"как", "buyer"→"buy" kabi xato moslashuvlar chiqadi).
EXACT_ONLY_KEYWORDS: frozenset[str] = frozenset({"как", "how", "buy", "куп", "цен"})


# ---------------------------------------------------------------------------
# UMUMIY MAVZULAR + TO'LDIRUVCHI SO'ZLAR
# ---------------------------------------------------------------------------
#: Bitta o'zi HECH QACHON aniq mavzu bo'la olmaydigan umumiy so'zlar.
GENERIC_TOPICS: frozenset[str] = frozenset({
    # uz
    "sport", "futbol", "yangilik", "yangiliklar", "xabar", "xabarlar",
    "voqea", "biznes", "business", "ish", "pul", "foyda", "sog'liq",
    "salomatlik", "ta'lim", "oila", "kino", "musiqa", "moda",
    "go'zallik", "sayohat", "ovqat", "retsept", "texnologiya",
    "texnologiyalar", "kripto", "valyuta", "ob-havo",
    # ru
    "спорт", "футбол", "новости", "новость", "бизнес", "работа",
    "деньги", "здоровье", "образование", "семья", "кино", "музыка",
    "мода", "красота", "путешествие", "еда", "рецепт", "технологии",
    "погода",
    # en
    "news", "football", "work", "money", "health", "education",
    "family", "movie", "music", "fashion", "beauty", "travel",
    "food", "recipe", "tech", "technology", "weather",
})

#: Mavzu mazmunini belgilamaydigan to'ldiruvchi so'zlar (aniqlik tahlilida
#: tashlab yuboriladi — "sport haqida bo'lsin" → mazmunli: {sport}).
FILLER_WORDS: frozenset[str] = frozenset({
    "haqida", "bo'lsin", "bo'lsin", "post", "uchun", "kerak", "menga",
    "yozib", "ber", "yoz", "qilib", "tayyorla", "tayyorlab", "qanday",
    "bo'yicha", "buyicha", "haqidа",
    "про", "о", "об", "пост", "поста", "для", "меня", "напиши",
    "сделай", "пожалуйста",
    "about", "write", "me", "please", "make", "post",
})

#: Aniq tafsilot belgilari (sotuv mavzusida mahsulot tafsiloti borligi).
_DETAIL_DIGIT_RX = re.compile(r"\d")
_TOKEN_RX = re.compile(r"[\w']+", re.UNICODE)


# ---------------------------------------------------------------------------
# NORMALIZATSIYA / TOKENIZATSIYA
# ---------------------------------------------------------------------------
def normalize_topic(topic) -> str:
    """Mavzuni kichik harfga keltiradi, qo'shtirnoqlarni birxillashtiradi."""
    text = str(topic or "").strip().lower()
    for quote in ("’", "‘", "`", "ʻ", "ʼ", "´"):
        text = text.replace(quote, "'")
    return re.sub(r"\s+", " ", text)


def count_words(topic) -> int:
    """Mavzudagi so'zlar soni (bo'sh joy bo'yicha)."""
    text = str(topic or "").strip()
    return len(text.split()) if text else 0


def tokenize(topic) -> list[str]:
    """Mavzuni kalit so'z qidirish uchun tokenlarga ajratadi."""
    return _TOKEN_RX.findall(normalize_topic(topic))


def meaningful_tokens(topic) -> list[str]:
    """To'ldiruvchi so'zlardan tozalangan mazmunli tokenlar."""
    return [t for t in tokenize(topic) if t not in FILLER_WORDS and len(t) > 1]


def _token_matches(token: str, keywords: tuple[str, ...]) -> bool:
    """Token kalit o'zaklardan biriga mos keladimi (boshidan moslashuv)."""
    for stem in keywords:
        if stem in EXACT_ONLY_KEYWORDS:
            if token == stem:
                return True
        elif token.startswith(stem):
            return True
    return False


def _has_keyword(topic, keywords: tuple[str, ...]) -> bool:
    return any(_token_matches(token, keywords) for token in tokenize(topic))


# ---------------------------------------------------------------------------
# ANIQLIK VA FORMAT ANIQLASH
# ---------------------------------------------------------------------------
def needs_clarification(topic) -> bool:
    """Mavzu aniqlashtirish wizard'ini talab qiladimi?

    * 3 so'zdan qisqa mavzu → HA (darhol generatsiya YO'Q);
    * uzun, lekin mazmuni faqat umumiy so'zlardan iborat mavzu
      (``"sport haqida bo'lsin futbol bo'yicha"``) → HA;
    * aks holda → YO'Q (bevosita oqim davom etadi).
    """
    text = str(topic or "").strip()
    if not text:
        return True
    if count_words(text) < 3:
        return True
    meaningful = meaningful_tokens(text)
    if not meaningful:
        return True
    if len(meaningful) <= 2 and all(t in GENERIC_TOPICS for t in meaningful):
        return True
    return False


def detect_post_format(topic) -> str:
    """Mavzudan post formatini aniqlaydi (``news``/``tips``/``short``/``sales``/``general``).

    Tartib QAT'IY: INFO → SALES → TIPS → SHORT. Ya'ni axborot so'zi
    (``"yangiliklar"``, ``"sport"`` ...) qatnashgan mavzu HECH QACHON
    ``"sales"`` ga aylanmaydi — hatto sotuv so'zi yonma-yon bo'lsa ham.
    """
    if _has_keyword(topic, INFO_KEYWORDS):
        return FORMAT_NEWS
    if _has_keyword(topic, SALES_KEYWORDS):
        return FORMAT_SALES
    if _has_keyword(topic, TIPS_KEYWORDS):
        return FORMAT_TIPS
    if _has_keyword(topic, SHORT_KEYWORDS):
        return FORMAT_SHORT
    return FORMAT_GENERAL


def is_sales_topic(topic) -> bool:
    """Mavzu sotuv oqimiga tegishlimi (``"yangiliklar"`` → har doim False)."""
    return detect_post_format(topic) == FORMAT_SALES


def has_concrete_details(topic) -> bool:
    """Mavzuda aniq tafsilot (raqam/narx/sana yoki batafsil matn) bormi?"""
    text = str(topic or "")
    if _DETAIL_DIGIT_RX.search(text):
        return True
    return count_words(text) >= 6


def should_ask_sales_params(topic) -> bool:
    """Sotuv parametrlari (nom/narx/xususiyat) so'ralishi kerakmi?

    Sotuv kalit so'zi bor, lekin aniq tafsiloti yo'q mavzuda AI
    mahsulotsiz post to'qimasligi uchun — avval parametrlar so'raladi.
    """
    return is_sales_topic(topic) and not has_concrete_details(topic)


# ---------------------------------------------------------------------------
# FLUFF-GUARD: "suv" shablonlar qora ro'yxati
# ---------------------------------------------------------------------------
#: Generatsiya promptlarida TAQIQLANGAN quruq shablonlar (kichik harfda).
#: ``scan_text_for_fluff()`` ularni har qanday prompt matnidan topadi.
FORBIDDEN_FLUFF_PHRASES: tuple[str, ...] = (
    # uz — obuna qoliplari
    "kanalga obuna bo'ling",
    "kanalimizga obuna bo'ling",
    "obuna bo'ling",
    "obuna bo’ling",
    # uz — "suv" gaplar
    "bizning kanal eng ishonchli manba",
    "eng ishonchli manba",
    "har kuni siz uchun saralab olamiz",
    "siz uchun saralab olamiz",
    "biz siz uchun eng yaxshisini tanlaymiz",
    "eng yaxshisini tanlaymiz",
    "eng yaxshisini tanlaymiz, obuna bo'ling",
    # ru
    "подпишитесь на канал",
    "подписаться на канал",
    # en
    "subscribe to the channel",
)


def scan_text_for_fluff(text) -> list[str]:
    """Matndagi taqiqlangan "suv" shablonlarni qaytaradi (topilmasa [])."""
    normalized = normalize_topic(text)
    # Apostrof variantlarini ham birxillashtiramiz (’ → ' yuqorida).
    normalized = normalized.replace("’", "'").replace("‘", "'")
    found: list[str] = []
    for phrase in FORBIDDEN_FLUFF_PHRASES:
        if phrase in normalized and phrase not in found:
            # Qisqa variant uzunining ichida bo'lsa — faqat uzuni qaytadi.
            if not any(phrase != other and phrase in other
                       for other in FORBIDDEN_FLUFF_PHRASES
                       if other in normalized):
                found.append(phrase)
    return found


def prompts_contain_fluff(prompts: dict) -> dict[str, list[str]]:
    """``{nom: matn}`` promptlar ichidan fluff topilganlarini qaytaradi."""
    result: dict[str, list[str]] = {}
    for name, text in (prompts or {}).items():
        hits = scan_text_for_fluff(text)
        if hits:
            result[str(name)] = hits
    return result


# ---------------------------------------------------------------------------
# SIFAT STANDARTI (barcha formatlar uchun umumiy)
# ---------------------------------------------------------------------------
QUALITY_RULES: dict[str, str] = {
    "uz": (
        "SIFAT STANDARTI (barcha formatlar uchun majburiy):\n"
        "1) Kuchli HOOK — 1-qator: <b>qalin sarlavha</b> + mavzuga mos emoji "
        "(savol, keskin fakt yoki raqam). Undan keyin bo'sh qator.\n"
        "2) Faqat Telegram HTML: <b>qalin</b> va <i>kursiv</i> teglari; "
        "markdown (**, ##, __, ```) QAT'IY TAQIQLANADI.\n"
        "3) Asosiy mazmun • ro'yxatlar yoki raqamlangan punktlar bilan — "
        "kamida 3 ta mustaqil punkt.\n"
        "4) Har bir punkt ANIQ mazmun beradi: fakt, raqam, amaliy maslahat "
        "yoki hayotiy misol. Umumiy gaplar yozilmaydi.\n"
        "5) Quruq 'suv' gaplar va yod bo'lib ketgan umumiy qoliplar "
        "TAQIQLANADI — har bir jumla o'quvchiga real qiymat bersin.\n"
        "6) Yakunda mavzuga xos ANIQ savol yoki muhokama chaqirig'i "
        "(alohida qatorda), eng oxirda 3-5 ta mavzuga mos hashtag."
    ),
    "ru": (
        "СТАНДАРТ КАЧЕСТВА (обязателен для всех форматов):\n"
        "1) Сильный ХУК — 1-я строка: <b>жирный заголовок</b> + уместное эмодзи "
        "(вопрос, резкий факт или цифра). Затем пустая строка.\n"
        "2) Только Telegram HTML: теги <b>жирный</b> и <i>курсив</i>; "
        "markdown (**, ##, __, ```) СТРОГО ЗАПРЕЩЁН.\n"
        "3) Основное содержание — списками • или нумерованными пунктами, "
        "минимум 3 самостоятельных пункта.\n"
        "4) Каждый пункт даёт КОНКРЕТНОЕ содержание: факт, цифру, практический "
        "совет или жизненный пример. Общих фраз нет.\n"
        "5) Пустые «водянистые» фразы и заезженные общие шаблоны ЗАПРЕЩЕНЫ — "
        "каждое предложение несёт реальную пользу.\n"
        "6) В конце — КОНКРЕТНЫЙ вопрос по теме или призыв к обсуждению "
        "(отдельной строкой), самой последней строкой 3-5 тематических хэштегов."
    ),
    "en": (
        "QUALITY STANDARD (mandatory for every format):\n"
        "1) A strong HOOK — line 1: a <b>bold headline</b> + a fitting emoji "
        "(a question, a sharp fact or a number). Then a blank line.\n"
        "2) Telegram HTML only: <b>bold</b> and <i>italic</i> tags; "
        "markdown (**, ##, __, ```) is STRICTLY FORBIDDEN.\n"
        "3) Main body as • bullet lists or numbered points — at least 3 "
        "standalone points.\n"
        "4) Every point delivers CONCRETE substance: a fact, a number, a "
        "practical tip or a real-life example. No generic statements.\n"
        "5) Empty filler phrases and worn-out generic templates are FORBIDDEN — "
        "every sentence must carry real value.\n"
        "6) Close with a CONCRETE topical question or discussion invite "
        "(on its own line), with 3-5 topical hashtags on the very last line."
    ),
}


# ---------------------------------------------------------------------------
# FORMAT TIZIM PROMPTLARI (fluff'siz, mazmunli)
# ---------------------------------------------------------------------------
FORMAT_SYSTEMS: dict[str, dict[str, str]] = {
    FORMAT_NEWS: {
        "uz": (
            "FORMAT: 📰 YANGILIK / VOQEA (axborot uslubi).\n"
            "- 1-qator: eng muhim fakt yoki voqea — <b>qalin sarlavha</b>.\n"
            "- Keyin: nima bo'lgani (kim, qayerda, qachon) — qisqa va aniq.\n"
            "- So'ng: kontekst — nima uchun bu muhim, o'quvchiga qanday aloqasi bor.\n"
            "- Tasdiqlanmagan raqam/fakt O'YLAB TOPILMAYDI — noma'lum joyga "
            "[manba]/[sana] belgisi qo'yiladi.\n"
            "- Sotuv ohangi va bosim QAT'IY TAQIQLANADI — bu axborot posti."
        ),
        "ru": (
            "ФОРМАТ: 📰 НОВОСТЬ / СОБЫТИЕ (информационный стиль).\n"
            "- 1-я строка: главный факт или событие — <b>жирный заголовок</b>.\n"
            "- Далее: что произошло (кто, где, когда) — коротко и точно.\n"
            "- Затем: контекст — почему это важно и как касается читателя.\n"
            "- Неподтверждённые цифры/факты НЕ ВЫДУМЫВАЮТСЯ — вместо них "
            "метка [источник]/[дата].\n"
            "- Продающий тон и давление СТРОГО ЗАПРЕЩЕНЫ — это новостной пост."
        ),
        "en": (
            "FORMAT: 📰 NEWS / EVENT (informational style).\n"
            "- Line 1: the key fact or event — a <b>bold headline</b>.\n"
            "- Next: what happened (who, where, when) — short and precise.\n"
            "- Then: context — why it matters and how it affects the reader.\n"
            "- Never invent unconfirmed numbers/facts — use a [source]/[date] "
            "marker instead.\n"
            "- Sales tone and pressure are STRICTLY FORBIDDEN — this is a news post."
        ),
    },
    FORMAT_TIPS: {
        "uz": (
            "FORMAT: 💡 MASLAHAT / TAHLIL (ekspert uslubi).\n"
            "- Kirish: muammo 1-2 jumlada — o'quvchi o'zini tanisin.\n"
            "- 3-5 ta AMALIY punkt (• yoki raqamlangan): har biri aniq qadam, "
            "fakt yoki misol bilan.\n"
            "- Yakun: 🧠 Ekspert xulosasi — bitta vaznli, ishonchli gap.\n"
            "- Mavzu chuqur ochiladi: 'nimaga' va 'qanday' savollariga javob bor."
        ),
        "ru": (
            "ФОРМАТ: 💡 СОВЕТ / АНАЛИЗ (экспертный стиль).\n"
            "- Вступление: проблема в 1-2 предложениях — читатель узнаёт себя.\n"
            "- 3-5 ПРАКТИЧЕСКИХ пунктов (• или нумерованных): каждый с конкретным "
            "шагом, фактом или примером.\n"
            "- Финал: 🧠 вывод эксперта — одна весомая уверенная фраза.\n"
            "- Тема раскрыта глубоко: есть ответы на «почему» и «как»."
        ),
        "en": (
            "FORMAT: 💡 TIPS / ANALYSIS (expert style).\n"
            "- Lead: the problem in 1-2 sentences — the reader recognises it.\n"
            "- 3-5 PRACTICAL points (• or numbered): each with a concrete step, "
            "fact or example.\n"
            "- Close: 🧠 an expert takeaway — one weighty, confident line.\n"
            "- The topic is covered in depth: the “why” and the “how” are answered."
        ),
    },
    FORMAT_SHORT: {
        "uz": (
            "FORMAT: 🔥 QISQA / FAKTLAR (tez o'qiladigan uslub).\n"
            "- Jami 4-7 qisqa qator: ortiqcha kirishsiz, darhol mohiyatga.\n"
            "- 2-4 ta keskin fakt yoki raqam — har biri alohida qatorda.\n"
            "- Bitta yakuniy savol — muhokama uchun ilgak.\n"
            "- Qisqa bo'lgani uchun har bir so'z yuk ko'taradi: 'suv' YO'Q."
        ),
        "ru": (
            "ФОРМАТ: 🔥 КОРОТКО / ФАКТЫ (быстро читаемый стиль).\n"
            "- Всего 4-7 коротких строк: без лишних вступлений, сразу к сути.\n"
            "- 2-4 резких факта или цифры — каждый с новой строки.\n"
            "- Один финальный вопрос — крючок для обсуждения.\n"
            "- Пост короткий, поэтому каждое слово весомо: «воды» НЕТ."
        ),
        "en": (
            "FORMAT: 🔥 SHORT / FACTS (quick-read style).\n"
            "- 4-7 short lines total: no lengthy intro, straight to the point.\n"
            "- 2-4 sharp facts or numbers — each on its own line.\n"
            "- One closing question — a hook for discussion.\n"
            "- Short means every word carries weight: NO filler."
        ),
    },
    FORMAT_SALES: {
        "uz": (
            "FORMAT: 🛒 MAHSULOT / SOTUV (taklif uslubi).\n"
            "- Faqat materialdagi ANIQ ma'lumot bilan yoziladi: mahsulot nomi, "
            "narxi va xususiyati foydalanuvchi bergan matndan olinadi.\n"
            "- Narx/nom/xususiyat materialda bo'lmasa — ular O'YLAB TOPILMAYDI, "
            "[mahsulot] / [narx] / [xususiyat] belgisi qo'yiladi.\n"
            "- Tuzilma: muammo → yechim (mahsulot) → 3 ta FOYDA (✅) → ANIQ "
            "taklif alohida <b>qalin</b> qatorda → bitta sotuv chaqirig'i.\n"
            "- Mahsulotsiz, mavhum va'dali sotuv posti yozish TAQIQLANADI."
        ),
        "ru": (
            "ФОРМАТ: 🛒 ТОВАР / ПРОДАЖА (стиль предложения).\n"
            "- Пишется ТОЛЬКО по КОНКРЕТНЫМ данным из материала: название товара, "
            "цена и особенность берутся из текста пользователя.\n"
            "- Если цены/названия/особенности в материале нет — они НЕ ВЫДУМЫВАЮТСЯ, "
            "ставится метка [товар] / [цена] / [особенность].\n"
            "- Структура: проблема → решение (товар) → 3 ВЫГОДЫ (✅) → КОНКРЕТНОЕ "
            "предложение отдельной <b>жирной</b> строкой → один продающий призыв.\n"
            "- Продающий пост без товара и с туманными обещаниями ЗАПРЕЩЁН."
        ),
        "en": (
            "FORMAT: 🛒 PRODUCT / SALES (offer style).\n"
            "- Written ONLY from CONCRETE material: the product name, price and "
            "key feature come from the user's text.\n"
            "- If the price/name/feature is missing — NEVER invent it, use a "
            "[product] / [price] / [feature] marker instead.\n"
            "- Structure: problem → solution (product) → 3 BENEFITS (✅) → a "
            "CONCRETE offer on its own <b>bold</b> line → one sales call to action.\n"
            "- A product-less sales post with vague promises is FORBIDDEN."
        ),
    },
}

#: Mavzu generatsiyaga uzatilayotganda materialga qo'shiladigan ixcham
#: format ko'rsatmasi (tanlangan yo'nalish AI'ga yo'qolmasligi uchun).
_FORMAT_HINTS: dict[str, dict[str, str]] = {
    FORMAT_NEWS: {
        "uz": "[Format: 📰 Yangilik — eng muhim fakt birinchi qatorda, keyin kontekst.]",
        "ru": "[Формат: 📰 Новость — главный факт в первой строке, затем контекст.]",
        "en": "[Format: 📰 News — the key fact first, then context.]",
    },
    FORMAT_TIPS: {
        "uz": "[Format: 💡 Maslahat — muammo, 3-5 amaliy qadam va ekspert xulosasi.]",
        "ru": "[Формат: 💡 Совет — проблема, 3-5 практических шагов и вывод эксперта.]",
        "en": "[Format: 💡 Tips — problem, 3-5 practical steps, expert takeaway.]",
    },
    FORMAT_SHORT: {
        "uz": "[Format: 🔥 Qisqa faktlar — 4-7 qator, keskin faktlar, bitta savol.]",
        "ru": "[Формат: 🔥 Короткие факты — 4-7 строк, резкие факты, один вопрос.]",
        "en": "[Format: 🔥 Short facts — 4-7 lines, sharp facts, one question.]",
    },
    FORMAT_SALES: {
        "uz": "[Format: 🛒 Sotuv — faqat materialdagi aniq nom/narx/xususiyat bilan.]",
        "ru": "[Формат: 🛒 Продажа — только по точным данным материала.]",
        "en": "[Format: 🛒 Sales — only from the concrete facts in the material.]",
    },
}

#: Wizard formati → Magic Post uslubi (standart taklif).
#: Muhim: axborot formatlari (news/tips/short) HECH QACHON sotuv
#: uslublariga (``sales``/``ads``) tushmaydi.
FORMAT_TO_MAGIC_STYLE: dict[str, str] = {
    FORMAT_NEWS: "informative",
    FORMAT_TIPS: "informative",
    FORMAT_SHORT: "casual",
    FORMAT_SALES: "sales",
    FORMAT_GENERAL: "casual",
}


def _normalize_lang(lang) -> str:
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in ("uz", "ru", "en") else "uz"


def build_format_system(format_key, lang="uz") -> str:
    """Format va til bo'yicha to'liq tizim prompti (sifat + format)."""
    key = str(format_key or "").strip().lower()
    if key not in FORMAT_SYSTEMS:
        key = FORMAT_NEWS
    code = _normalize_lang(lang)
    format_block = FORMAT_SYSTEMS[key][code]
    return f"{format_block}\n\n{QUALITY_RULES[code]}"


def format_hint_line(format_key, lang="uz") -> str:
    """Materialga qo'shiladigan ixcham format ko'rsatmasi."""
    key = str(format_key or "").strip().lower()
    table = _FORMAT_HINTS.get(key) or {}
    return table.get(_normalize_lang(lang), "")


def map_format_to_magic_style(format_key, default: str = "casual") -> str:
    """Wizard formati → Magic Post uslubi (noma'lum → ``default``)."""
    key = str(format_key or "").strip().lower()
    style = FORMAT_TO_MAGIC_STYLE.get(key, default)
    if style not in ("sales", "premium", "casual", "ads", "informative"):
        return default if default in (
            "sales", "premium", "casual", "ads", "informative") else "casual"
    return style
