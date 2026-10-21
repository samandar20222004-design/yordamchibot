"""Reklama birjasi: kanal qaysi hududga (davlatga) mos yoki global ekanini aniqlash.

Egasi faqat DAVLATni tanlaydi (yoki «🌍 Global»). Bot kanal nomi/tavsifi/e'lon matnining TILINI aniqlab, tanlangan davlatga
mosligini tekshiradi va mos kelmasa tavsiya beradi. Aniqlash faqat ishonchli bo'lganda ishlaydi: noaniq matn (qisqa, bir nechta
til, noma'lum lotin tili) — ogohlantirish YO'Q (chet ellik foydalanuvchilar bexuda to'sib qo'yilmaydi).
Saqlanadigan qiymat: ISO-2 (``UZ``, ``RU``...) yoki ``ZZ`` = global (``ad_market_listings.country``).
"""
from __future__ import annotations

import re

from services.country import CALLING_CODES

GLOBAL = "ZZ"

#: Tanlash ro'yxatida birinchi ko'rsatiladigan davlatlar (bot tugmalari va Mini App ro'yxati boshi).
POPULAR = ("UZ", "RU", "KZ", "KG", "TJ", "TM", "TR", "AZ", "UA", "BY", "GE", "AM",
           "US", "GB", "DE", "FR", "IT", "ES", "AE", "SA", "EG", "IN", "PK", "CN")

#: Davlat -> shu davlat kanali uchun tabiiy tillar. Ro'yxatda yo'q davlat — til tekshiruvi o'tkazilmaydi.
_ARAB = ("SA", "AE", "EG", "IQ", "JO", "KW", "QA", "OM", "BH", "YE", "SY", "LB", "LY", "DZ", "MA", "TN", "SD")
_ENGLISH = ("US", "GB", "CA", "AU", "NZ", "IE", "IN", "PK", "NG", "SG", "ZA", "PH", "KE", "GH")
COUNTRY_LANGS: dict[str, frozenset] = {
    "UZ": frozenset({"uz", "ru"}), "RU": frozenset({"ru"}), "KZ": frozenset({"ru", "kk"}), "KG": frozenset({"ru"}),
    "TJ": frozenset({"ru"}), "TM": frozenset({"ru"}), "UA": frozenset({"uk", "ru"}), "BY": frozenset({"ru"}),
    "AZ": frozenset({"ru"}), "AM": frozenset({"ru"}), "GE": frozenset({"ru"}), "MD": frozenset({"ru"}),
    "TR": frozenset({"tr"}),
    **{c: frozenset({"ar"}) for c in _ARAB},
    **{c: frozenset({"en"}) for c in _ENGLISH},
}
#: Til -> tavsiya etiladigan davlat (global bo'lsa ``GLOBAL``).
LANG_TO_REGION = {"uz": "UZ", "ru": "RU", "kk": "KZ", "uk": "UA", "tr": "TR", "ar": "SA", "en": GLOBAL}

_NOISE = re.compile(r"https?://\S+|t\.me/\S+|@\w+|#\w+|\d+")
_UZ_WORDS = frozenset("va bilan uchun bu bir kanal yangiliklar eng har kun ham haqida siz biz endi lekin yoki bo'ladi qiling "
                      "uzbekiston toshkent ozbekiston o'zbekiston bugun xabarlar kanalimiz".split())
_TR_WORDS = frozenset("ve bir için bu ile çok daha ama gibi olarak haber haberler türkiye kanal".split())
_EN_WORDS = frozenset("the and of to in for is on with you your our news daily channel best free new".split())
_WORD = re.compile(r"[a-zçğıöşüʻʼ'`‘’]+", re.IGNORECASE)


def _letters(text: str) -> list[str]:
    return [ch for ch in _NOISE.sub(" ", text or "") if ch.isalpha()]


def detect_language(*texts: str | None) -> str | None:
    """Matn(lar) tili: ``uz|ru|kk|uk|tr|ar|en`` yoki ``None`` (qisqa/noaniq/noma'lum til)."""
    text = " ".join(t for t in texts if t)
    letters = _letters(text)
    if len(letters) < 10:
        return None
    n = len(letters)
    cyr = sum(1 for ch in letters if "Ѐ" <= ch <= "ӿ")
    arab = sum(1 for ch in letters if "؀" <= ch <= "ۿ")
    lat = sum(1 for ch in letters if ch.isascii() or "À" <= ch <= "ɏ")
    if arab / n > 0.6:
        return "ar"
    if cyr / n > 0.6:
        low = "".join(letters).lower()
        if sum(low.count(c) for c in "ўқғҳ") >= 2:
            return "uz"
        if sum(low.count(c) for c in "іїєґ") >= 2:
            return "uk"
        if sum(low.count(c) for c in "ңғүұқәө") >= 2:
            return "kk"
        return "ru"
    if lat / n > 0.6:
        words = [w.lower().replace("ʻ", "'").replace("ʼ", "'").replace("‘", "'").replace("’", "'").replace("`", "'")
                 for w in _WORD.findall(text)]
        uz = sum(1 for w in words if w in _UZ_WORDS) + sum(1 for w in words if re.search(r"[og]'", w))
        tr = sum(1 for w in words if w in _TR_WORDS) + sum(1 for ch in text if ch in "ğıİşŞĞ")
        en = sum(1 for w in words if w in _EN_WORDS)
        best = max(uz, tr, en)
        if best < 2 or [uz, tr, en].count(best) > 1:
            return None
        return "uz" if best == uz else "tr" if best == tr else "en"
    return None


def valid_region(code) -> bool:
    c = str(code or "").upper()
    return c == GLOBAL or c in set(CALLING_CODES.values()) | {"KZ"}


def all_regions() -> list[str]:
    """Davlatlar ro'yxati: mashhurlari boshida, qolganlari alifbo tartibida (global bu ro'yxatda YO'Q)."""
    rest = sorted((set(CALLING_CODES.values()) | {"KZ"}) - set(POPULAR) - {GLOBAL})
    return [*POPULAR, *rest]


def suggest_region(language: str | None) -> str | None:
    return LANG_TO_REGION.get(language or "")


def assess(region: str | None, *texts: str | None) -> dict:
    """Tanlangan hudud kanal matniga mosmi.

    ``{"language", "fits", "suggested", "recommended"}``: ``fits`` — ``True``/``False``/``None`` (noaniq: ogohlantirish yo'q);
    ``suggested`` — ``fits`` False bo'lganda mos hudud; ``recommended`` — eng yaxshi boshlang'ich tanlov (mos bo'lsa tanlangan).
    """
    chosen = str(region or "").upper() or None
    lang = detect_language(*texts)
    if chosen == GLOBAL or lang is None or chosen is None:
        return {"language": lang, "fits": None if lang is None else True, "suggested": None, "recommended": chosen or suggest_region(lang)}
    allowed = COUNTRY_LANGS.get(chosen)
    if allowed is None or lang in allowed:
        return {"language": lang, "fits": True if allowed is not None else None, "suggested": None, "recommended": chosen}
    suggested = suggest_region(lang)
    return {"language": lang, "fits": False, "suggested": suggested, "recommended": suggested or chosen}

