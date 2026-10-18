"""Telefon raqamidan mamlakatni aniqlash (E.164 mamlakat kodi) — statistika, birja filtri va narx mintaqasi uchun.

Telegram mamlakatni bermaydi; foydalanuvchi O'Z kontaktini ulashganda raqam prefiksi eng ishonchli mezon.
Raqamning o'zi saqlanmaydi — faqat ISO-2 mamlakat kodi. Noma'lum prefiks -> ``UNKNOWN`` («ZZ»).
Taxminlar: +1 -> AQSH (Kanada/Karib dengizi ham shu), +7 -> Rossiya (76/77 -> Qozog'iston).
"""
from __future__ import annotations

UNKNOWN = "ZZ"

# Mamlakat kodi (1-3 raqam) -> ISO-2. Eng uzun mos prefiks tanlanadi.
CALLING_CODES: dict[str, str] = {
    "1": "US", "7": "RU", "20": "EG", "27": "ZA", "30": "GR", "31": "NL", "32": "BE", "33": "FR", "34": "ES", "36": "HU",
    "39": "IT", "40": "RO", "41": "CH", "43": "AT", "44": "GB", "45": "DK", "46": "SE", "47": "NO", "48": "PL", "49": "DE",
    "51": "PE", "52": "MX", "53": "CU", "54": "AR", "55": "BR", "56": "CL", "57": "CO", "58": "VE", "60": "MY", "61": "AU",
    "62": "ID", "63": "PH", "64": "NZ", "65": "SG", "66": "TH", "81": "JP", "82": "KR", "84": "VN", "86": "CN", "90": "TR",
    "91": "IN", "92": "PK", "93": "AF", "94": "LK", "95": "MM", "98": "IR",
    "211": "SS", "212": "MA", "213": "DZ", "216": "TN", "218": "LY", "220": "GM", "221": "SN", "223": "ML", "225": "CI",
    "226": "BF", "227": "NE", "228": "TG", "229": "BJ", "230": "MU", "231": "LR", "232": "SL", "233": "GH", "234": "NG",
    "235": "TD", "237": "CM", "241": "GA", "243": "CD", "244": "AO", "249": "SD", "250": "RW", "251": "ET", "252": "SO",
    "253": "DJ", "254": "KE", "255": "TZ", "256": "UG", "257": "BI", "258": "MZ", "260": "ZM", "261": "MG", "263": "ZW",
    "264": "NA", "265": "MW", "267": "BW", "351": "PT", "352": "LU", "353": "IE", "354": "IS", "355": "AL", "356": "MT",
    "357": "CY", "358": "FI", "359": "BG", "370": "LT", "371": "LV", "372": "EE", "373": "MD", "374": "AM", "375": "BY",
    "376": "AD", "377": "MC", "380": "UA", "381": "RS", "382": "ME", "383": "XK", "385": "HR", "386": "SI", "387": "BA",
    "389": "MK", "420": "CZ", "421": "SK", "423": "LI", "501": "BZ", "502": "GT", "503": "SV", "504": "HN", "505": "NI",
    "506": "CR", "507": "PA", "591": "BO", "592": "GY", "593": "EC", "595": "PY", "598": "UY", "673": "BN", "852": "HK",
    "853": "MO", "855": "KH", "856": "LA", "880": "BD", "886": "TW", "960": "MV", "961": "LB", "962": "JO", "963": "SY",
    "964": "IQ", "965": "KW", "966": "SA", "967": "YE", "968": "OM", "971": "AE", "972": "IL", "973": "BH", "974": "QA",
    "975": "BT", "976": "MN", "977": "NP", "992": "TJ", "993": "TM", "994": "AZ", "995": "GE", "996": "KG", "998": "UZ",
}


def normalize_phone(phone) -> str:
    """Faqat raqamlar (``+998 90 123-45-67`` -> ``998901234567``)."""
    return "".join(ch for ch in str(phone or "") if ch.isdigit())


def country_from_phone(phone) -> str | None:
    """Telefon raqami -> ISO-2 mamlakat; yaroqsiz raqam (8..15 raqam emas, O'zbekiston uchun 12) -> ``None``.

    Noma'lum mamlakat kodi -> ``UNKNOWN`` (raqam yaroqli, lekin jadvalda yo'q).
    """
    digits = normalize_phone(phone)
    if not (8 <= len(digits) <= 15):
        return None
    if digits.startswith("998"):
        return "UZ" if len(digits) == 12 else None
    if digits.startswith(("76", "77")) and len(digits) == 11:
        return "KZ"
    for size in (3, 2, 1):
        iso = CALLING_CODES.get(digits[:size])
        if iso:
            return iso
    return UNKNOWN


def flag(iso: str | None) -> str:
    """ISO-2 -> bayroq emoji (noma'lum/bo'sh -> 🌐)."""
    code = str(iso or "").upper()
    if len(code) != 2 or not code.isalpha() or code == UNKNOWN:
        return "🌐"
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in code)


def label(iso: str | None) -> str:
    """«🇺🇿 UZ» — statistika/ko'rsatish uchun qisqa yorliq."""
    code = str(iso or "").upper()
    return f"{flag(code)} {code}" if code and code != UNKNOWN else "🌐 —"
