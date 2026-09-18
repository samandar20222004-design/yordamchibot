"""Literal HTML escaping and URL validation (backward-compatible facade).

Formatting and truncation live in utils.telegram_sanitizer. safe_html here
still escapes ALL tags: dynamic user names must never become HTML markup.
"""

from utils import telegram_sanitizer as _telegram_html
import ipaddress
import logging
import socket
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

# ============================================================
# 2b) SSRF HIMOYASI — ICHKI TARMOQ MANZILLARI (FAZA 23)
# ============================================================
# Havolali tugmalar va manbalar ICHKI TARMOQ manzillariga ishora
# qilmasligi shart: localhost, 127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12,
# 192.168.0.0/16, 169.254.0.0/16 (bulut metadata!) va umuman global
# bo'lmagan har qanday IP mutlaqo bloklanadi. ``services.sources.
# url_extractor`` moduli bilan bitta siyosat (SSOT): bu yerda o'sha
# ro'yxatning tugma kontekstiga mos yengil (DNS'siz, sintaktik) nusxasi.

#: Ichki tarmoq/xizmat nomlari — host nomi bo'yicha ham bloklanadi.
BLOCKED_BUTTON_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "instance-data",
    "metadata.aws.internal",
})

#: Zaxira/ichki domen sofikslari (SSRF klassik yo'llari).
BLOCKED_BUTTON_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".lan", ".home", ".corp",
    ".intranet", ".invalid",
)

#: Bloklangan IP tarmoqlari — RFC 1918 + loopback + link-local + metadata.
BLOCKED_BUTTON_NETWORKS: tuple = tuple(
    ipaddress.ip_network(item) for item in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
        "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
)


def _canonical_ip_literal(host: str):
    """Host IP literal bo'lsa — KANONIK ``ipaddress`` obyektini qaytaradi.

    Brauzer/``inet_aton`` klassik chetlab o'tish shakllari ham taniladi::

        2130706433      → 127.0.0.1      (o'nlik)
        0x7f000001      → 127.0.0.1      (o'n oltilik)
        0177.0.0.1      → 127.0.0.1      (sakkizlik)
        127.1           → 127.0.0.1      (qisqa)

    Oddiy doman nomlari uchun ``None`` qaytadi.
    """
    text = str(host or "").strip().strip("[]")
    if not text:
        return None
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(text)
    except OSError:
        return None
    try:
        return ipaddress.ip_address(socket.inet_ntoa(packed))
    except ValueError:  # pragma: no cover — himoya qatlami
        return None


def is_blocked_private_ip(address) -> bool:
    """IP manzil ichki/xavfli (global bo'lmagan) ekanini bildiradi.

    O'qib bo'lmagan qiymat uchun ``True`` qaytadi (fail-closed).
    """
    if isinstance(address, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
        ip = address
    else:
        try:
            ip = ipaddress.ip_address(str(address).strip())
        except ValueError:
            return True  # fail-closed
    candidates = [ip]
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    for item in candidates:
        for network in BLOCKED_BUTTON_NETWORKS:
            if item.version == network.version and item in network:
                return True
        # Qo'shimcha qatlam: global bo'lmagan har qanday manzil bloklanadi.
        try:
            if not item.is_global:
                return True
        except Exception:  # pragma: no cover — eski Python himoyasi
            if item.is_private or item.is_loopback or item.is_link_local:
                return True
    return False


def is_blocked_private_host(host: str) -> bool:
    """Host nomi yoki IP literali ichki tarmoqqa tegishlimi? (SSRF)

    Faqat SINTAKTIK tekshiruv (DNS so'rovi yuborilmaydi) — bu tugma
    konteksti uchun yetarli, chunki tugma havolasi foydalanuvchi
    qurilmasida ochiladi; server tomonidan yuklanadigan manbalar uchun
    DNS-darabali to'liq guard ``validate_public_url`` da.
    """
    normalized = str(host or "").strip().strip("[]").lower()
    if not normalized:
        return False
    if (normalized in BLOCKED_BUTTON_HOSTNAMES
            or normalized.endswith(BLOCKED_BUTTON_HOST_SUFFIXES)):
        return True
    literal = _canonical_ip_literal(normalized)
    if literal is not None and is_blocked_private_ip(literal):
        return True
    return False


def url_rejection_reason(url) -> str:
    """Havolani tekshiradi va rad etish sababini qaytaradi.

    Returns:
        str: ``""`` — havola xavfsiz; aks holda qisqa sabab kodi:
        ``empty`` | ``too_long`` | ``bad_chars`` | ``malformed`` |
        ``bad_scheme`` | ``bad_host`` | ``credentials`` | ``bad_port`` |
        ``private_address`` (FAZA 23 — SSRF: localhost, 127.x, 10.x,
        172.16-31.x, 192.168.x, 169.254.x metadata va boshqa ichki
        tarmoq manzillari).
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

    if scheme in ("http", "https"):
        # FAZA 23 (SSRF): ichki tarmoq manzillari — localhost, 127.0.0.1,
        # 10.*, 172.16-31.*, 192.168.*, 169.254.* (bulut metadata) va
        # ichki domen nomlari havolali tugma/manbada QAT'IY bloklanadi.
        # Bu tekshiruv nuqta-syshildidan OLDIN turadi: ``2130706433``,
        # ``127.1``, ``0x7f000001``, ``[::1]`` kabi chetlab o'tish
        # shakllari ham aynan ``private_address`` sifatida rad etiladi.
        if is_blocked_private_host(host):
            return "private_address"
        if "." not in host:
            # Domen bo'lishi shart: "https://" yoki "https://intranet" rad etiladi.
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
