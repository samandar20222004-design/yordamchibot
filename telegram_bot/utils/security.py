"""Literal HTML escaping and URL validation (backward-compatible facade).

Formatting and truncation live in utils.telegram_sanitizer. safe_html here
still escapes ALL tags: dynamic user names must never become HTML markup.
"""

from utils import telegram_sanitizer as _telegram_html
import logging
import unicodedata
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# ============================================================
# 1) HTML XAVFSIZLIK
# ============================================================

#: Telegram HTML uchun maksimal matn uzunligi (xabar) va caption uzunligi.
TELEGRAM_TEXT_LIMIT = _telegram_html.TELEGRAM_TEXT_LIMIT
TELEGRAM_CAPTION_LIMIT = _telegram_html.TELEGRAM_CAPTION_LIMIT


def safe_html(text) -> str:
    """Literal-value proxy; intentionally does not preserve HTML tags."""
    return _telegram_html.escape_html(text)


escape_html = safe_html
html_escape = safe_html


def safe_text(text, max_len: int = None) -> str:
    """Legacy serialized budget without partial entities."""
    return _telegram_html.escape_html_limited(text, max_len)


def safe_limit_html(text, max_len: int = TELEGRAM_CAPTION_LIMIT) -> str:
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
