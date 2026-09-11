"""HTML/URL xavfsizlik yordamchilari — PostAssist V2 (6-bosqich).

Bu modul FAQAT standart kutubxonaga tayanadi (telegram/DB import qilinmaydi),
shuning uchun uni istalgan qavat — handler, servis yoki test — xavfsiz
import qilishi mumkin.

Ikki asosiy vazifa
------------------
1. **``safe_html(text)``** — foydalanuvchi ismi, AI qoldig'i, kanal nomi kabi
   *dinamik* matnlarni ``html.escape`` qiladi. Natija Telegram HTML
   (``parse_mode="HTML"``) uchun 100% xavfsiz: noto'g'ri/yaroqsiz teg
   tufayli yuzaga keladigan ``BadRequest: can't parse entities`` xatolari
   oldini oladi.

   .. note::
      ``utils.helpers.safe_html()`` boshqa vazifani bajaradi — u AI
      javobidagi *ruxsat etilgan* Telegram teglarini saqlab qoladi
      (sanitizer). Bu yerdagi ``safe_html()`` esa hech narsani saqlamaydi:
      har bir ``<``, ``>``, ``&``, ``"`` belgisi escape qilinadi. Dinamik
      qiymatlar uchun aynan shu funksiya ishlatilishi kerak.

2. **``validate_button_url(url)``** — inline tugma havolasi uchun qat'iy oq
   ro'yxat: faqat ``http://``, ``https://`` va ``tg://``. ``javascript:``,
   ``data:``, ``vbscript:``, ``file:`` kabi barcha boshqa protokollar, ichida
   bo'sh joy/control belgi bor yoki domeni yo'q havolalar rad etiladi.

Foydalanish::

    from utils.security import safe_html, validate_button_url

    text = f"👤 <b>{safe_html(user.full_name)}</b>"
    if validate_button_url(url):
        InlineKeyboardButton("🌐 Sayt", url=url)
"""

import html
import logging
import unicodedata
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# ============================================================
# 1) HTML XAVFSIZLIK
# ============================================================

#: Telegram HTML uchun maksimal matn uzunligi (xabar) va caption uzunligi.
TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_CAPTION_LIMIT = 1024


def safe_html(text) -> str:
    """Dinamik matnni Telegram HTML uchun xavfsiz (escape qilingan) holga keltiradi.

    ``<b>``, ``<script>``, ``&``, ``"`` kabi barcha maxsus belgilar
    ``&lt;b&gt;``, ``&amp;`` ko'rinishiga o'giriladi — natijada foydalanuvchi
    yoki AI yozgan matn Telegramning HTML parser'ini hech qachon buza olmaydi.

    Args:
        text: Har qanday qiymat (``None`` → bo'sh satr, sonlar ``str()``).

    Returns:
        str: Escape qilingan matn.

    Misol::

        >>> safe_html('<b>hi</b> & <script>')
        '&lt;b&gt;hi&lt;/b&gt; &amp; &lt;script&gt;'
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return ""
    # quote=True — qo'shtirnoqlar ham escape qilinadi (href/atribut xavfsizligi).
    return html.escape(text, quote=True)


#: Eski nom bilan moslik uchun (``html_escape`` bilan bir xil xatti-harakat).
escape_html = safe_html


def safe_text(text, max_len: int = None) -> str:
    """``safe_html`` + ixtiyoriy qisqartirish (Telegram limitidan oshmasligi uchun).

    Qisqartirish HTML escape'dan KEYIN bajariladi, shuning uchun kesilgan
    matnda yarim teg qolmaydi (escape tufayli teg umuman yo'q).
    """
    result = safe_html(text)
    if max_len is not None and max_len >= 0 and len(result) > max_len:
        result = result[:max_len]
    return result


def safe_limit_html(text, max_len: int = TELEGRAM_CAPTION_LIMIT) -> str:
    """Caption (1024) yoki xabar (4096) limitiga mos xavfsiz matn."""
    return safe_text(text, max_len=max_len)


def normalize_username(username, with_at: bool = False) -> str:
    """Username'ni xavfsiz ko'rinishga keltiradi (``@`` belgisisiz, escape qilingan).

    Bo'sh/noto'g'ri qiymatda bo'sh satr qaytadi — chaqiruvchi shunga qarab
    ixtiyoriy qatorni tashlab ketishi mumkin.
    """
    value = (str(username or "")).strip().lstrip("@")
    if not value:
        return ""
    # Username faqat [A-Za-z0-9_] bo'ladi; qolgan belgilar xavfsiz olib tashlanadi.
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch == "_")
    if not cleaned:
        return ""
    return ("@" if with_at else "") + safe_html(cleaned)


def strip_control_chars(text, replace_with: str = "") -> str:
    """Ko'rinmas control belgilarni olib tashlaydi (log/DB injection himoyasi)."""
    if text is None:
        return ""
    cleaned = "".join(
        replace_with if unicodedata.category(ch) in ("Cc", "Cf") and ch not in "\n\t"
        else ch
        for ch in str(text)
    )
    return cleaned


# ============================================================
# 2) URL XAVFSIZLIGI
# ============================================================

#: Inline tugma uchun ruxsat etilgan protokollar (oq ro'yxat).
ALLOWED_URL_SCHEMES = ("http", "https", "tg")

#: Xavfli/tanilmagan protokollar — testlar va xato xabarlari uchun.
DANGEROUS_URL_SCHEMES = (
    "javascript", "data", "vbscript", "file", "blob", "about",
    "chrome", "jar", "view-source",
)

#: Havolada umuman bo'lmasligi kerak belgilar.
_FORBIDDEN_URL_CHARS = frozenset('<>"\'`\\')

#: Telegram inline tugma havolasi uchun maksimal uzunlik.
MAX_URL_LENGTH = 2048


def url_rejection_reason(url) -> str:
    """Havolani tekshiradi va rad etish sababini qaytaradi.

    Returns:
        str: ``""`` — havola xavfsiz; aks holda qisqa sabab kodi:
        ``empty`` | ``too_long`` | ``bad_chars`` | ``malformed`` |
        ``bad_scheme`` | ``bad_host`` | ``credentials`` | ``bad_port``.
    """
    if url is None:
        return "empty"
    value = str(url).strip()
    if not value:
        return "empty"
    if len(value) > MAX_URL_LENGTH:
        return "too_long"
    # Bo'sh joy, yangi qator, tab va control belgilar — Telegram ham rad etadi.
    if any(ch.isspace() for ch in value) or any(ord(ch) < 32 for ch in value):
        return "bad_chars"
    if any(ch in _FORBIDDEN_URL_CHARS for ch in value):
        return "bad_chars"

    try:
        parts = urlsplit(value)
    except ValueError:
        return "malformed"

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_URL_SCHEMES:
        # javascript:, data:, file:, t.me/... (protokolsiz) va h.k.
        return "bad_scheme"

    netloc = parts.netloc
    if not netloc:
        return "bad_host"
    # ``https://user:pass@host`` — Telegram bunday havolani rad etadi va
    # fishing uchun ishlatilishi mumkin.
    if "@" in netloc:
        return "credentials"

    try:
        host = (parts.hostname or "").strip()
        port = parts.port
    except ValueError:
        # "https://example.com:abc/" kabi noto'g'ri port.
        return "bad_port"
    if not host:
        return "bad_host"
    if port is not None and not (0 < port < 65536):
        return "bad_port"

    if scheme in ("http", "https") and "." not in host:
        # Domen bo'lishi shart: "https://" yoki "https://localhost" rad etiladi.
        return "bad_host"
    return ""


def validate_button_url(url) -> bool:
    """Inline tugma havolasi xavfsizmi?

    Faqat ``http://``, ``https://`` va ``tg://`` protokollari ruxsat etiladi.
    ``javascript:``, ``data:`` yoki boshqa istalgan xavfli protokol rad etiladi.

    Returns:
        bool: ``True`` — havolani tugmaga qo'yish mumkin.
    """
    return url_rejection_reason(url) == ""


#: Ba'zi chaqiruvchilar "mutlaqo xavfsiz" ma'nosida shu nomni ishlatadi.
is_safe_button_url = validate_button_url


def sanitize_button_url(url) -> str:
    """Havolani qaytaradi (xavfsiz bo'lsa) yoki bo'sh satr."""
    return str(url).strip() if validate_button_url(url) else ""


#: Tashqi (AI/reklama) matnlarida uchraydigan havolalar uchun xuddi shu oq ro'yxat.
validate_link = validate_button_url
