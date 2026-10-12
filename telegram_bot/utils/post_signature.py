"""🧹 Imzo/havola normalizatsiyasi — HECH QANDAY bog'liqliksiz modul.

Nega alohida fayl?
------------------
``services.post_cleaner`` (tozalash dvigateli) va
``repositories.users_repository`` (bazaga yozish) IKKALASI HAM imzoni bir
xil qoidada tozalashi kerak. Lekin ``repositories`` → ``services`` importi
**sikl** yaratadi (``services/__init__`` → ``config``/``database``). Shu
sababli qoida shu YENGIL modulda yashaydi:

  * faqat stdlib (``re``) — hech qanday ichki import yo'q;
  * ``utils`` — namespace package (``__init__.py`` yo'q), shu sababli
    ``utils.post_signature`` importi hech qanday og'ir modulni tortmaydi.

``services.post_cleaner`` bu nomlarni o'z sirtdan qayta eksport qiladi
(``from services.post_cleaner import normalize_signature`` ham ishlaydi).
"""

from __future__ import annotations

import re

__all__ = [
    "MAX_SIGNATURE_LEN", "MAX_SIGNATURE_LINES", "normalize_signature",
    "signature_is_empty",
]

#: Imzo/havola uzunligi chegarasi (``users.post_signature_text VARCHAR(500)``).
MAX_SIGNATURE_LEN = 500

#: Imzoda ruxsat etilgan eng ko'p qator soni.
MAX_SIGNATURE_LINES = 10

#: Yo'nalish/boshqaruv belgilari (RTL/LRM/RLM, NUL, ESC) — imzoga kiritilmaydi.
#: Bular foydalanuvchi interfeysini "buzish" (bidi override) uchun ishlatiladi.
_BANNED_ORDS = frozenset(range(0x202A, 0x202F)) | {0x200E, 0x200F, 0x00, 0x1B}


def normalize_signature(value) -> str:
    """Imzo/havolani xavfsiz, bir xil ko'rinishga keltiradi (yiqilmaydi).

    * boshqaruv/yo'nalish belgilari (NUL, ESC, RTL/LRM) olib tashlanadi;
    * qatorlar soni ``MAX_SIGNATURE_LINES`` gacha, umumiy uzunlik
      ``MAX_SIGNATURE_LEN`` gacha qisqadi;
    * bo'sh qatorlar va ortiqcha bo'shliqlar o'chadi;
    * HTML teglari YOZUVCHA matn sifatida saqlanadi (keyin escape qilinadi) —
      foydalanuvchi yozgan ``<b>`` teg sifatida emas, matn sifatida chiqadi.
    """
    raw = "" if value is None else str(value)
    kept = []
    for char in raw:
        code = ord(char)
        if char in "\n\r":
            kept.append(char)
            continue
        if code < 32 or code in _BANNED_ORDS:
            continue
        kept.append(char)
    cleaned = "".join(kept).replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\t", " ")
    cleaned = re.sub(r"[ ]{2,}", " ", cleaned)
    lines = [line.strip() for line in cleaned.split("\n")]
    lines = [line for line in lines if line][:MAX_SIGNATURE_LINES]
    return "\n".join(lines).strip()[:MAX_SIGNATURE_LEN].strip()


def signature_is_empty(value) -> bool:
    """Imzo bo'shmi (ya'ni postga hech narsa qo'shilmaydimi)?"""
    return not normalize_signature(value)
