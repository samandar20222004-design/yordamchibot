"""🛡 URL SECURITY GATEWAY — tashqi havolalar uchun YAGONA xavfsiz fetcher.

Muammo: tizimning bir nechta moduli tashqi (foydalanuvchi kiritgan) URL'larga
tarmoq so'rovi yuborardi — 🔗 URL→post va 📡 RSS ``services/sources/`` orqali,
veb-skreyping esa ``utils/channel_reader.py`` orqali alohida (SSRF tekshiruvisiz)
chiqardi. Bu PHASE 1 markazlashtirishi bilan barcha tashqi so'rovlar bitta
shlyuzdan o'tadi::

    from services import url_security_gateway as gateway

    res = gateway.safe_fetch("https://example.com/article")
    res["ok"], res["status"], res["text"], res["error_code"], res["message"]

Qat'iy SSRF siyosati (fail-closed):
  1. **Sxema**: faqat ``http`` / ``https`` (``file:``, ``ftp:``, ``gopher:``,
     ``data:`` … darhol rad etiladi);
  2. **Port**: faqat 80 / 443 (sxema standarti);
  3. **Host IP**: ``localhost`` va barcha ichki/rezerv manzillar —
     ``127.0.0.0/8``, ``10.0.0.0/8``, ``172.16.0.0/12``, ``192.168.0.0/16``,
     ``100.64.0.0/10`` (CGNAT), ``169.254.0.0/16`` (AWS/GCP/Azure/Render
     bulut-metadata — ``169.254.169.254``!) va umuman GLOBAL BO'LMAGAN har
     qanday manzil bloklanadi. O'nlik/o'n oltilik/sakkizlik IP chetlab
     o'tish shakllari (``2130706433``, ``0x7f000001``, ``0177.0.0.1``,
     ``127.1``) kanonik ko'rinishga keltirilib tekshiriladi;
  4. **DNS REBINDING HIMOYASI**: host barcha A/AAAA yozuvlari bo'yicha
     tekshirilgandan so'ng TCP ulanishi AYNAN tasdiqlangan IP'ga pin qilinadi
     (``PinnedUrllibClient``); HTTP proxy'lar o'chirilgan, shuning uchun
     pinlangan hostname emas, tasdiqlangan IP socket'ga uzatiladi;
  5. **Redirect'lar**: avtomatik redirect faqat gateway handler'i orqali
     o'tadi; har bir manzil qayta tekshiriladi va qayta pin qilinadi (ko'pi
     bilan 3 qadam);
  6. **Chegaralar**: javob hajmi ≤ 10 MB (``MAX_RESPONSE_BYTES``), qat'iy
     timeout 5–7 soniya (``MIN/MAX_TIMEOUT_SECONDS`` orasida clamp);
  7. **Xavfsiz xatolik xabari**: foydalanuvchiga ichki tafsilotlar (IP,
     port, DNS sababi) chiqmaydi — barcha rad etishlar yagona
     :data:`SAFE_ERROR_MESSAGE` matni bilan qaytadi; aniq sabob faqat
     server logiga yoziladi.

Orqaga moslik: ``services/sources/url_extractor.py`` o'zining detalli
xato xabarlari va API'sini saqlab qoladi, lekin standart transport endi
shu modulning ``PinnedUrllibClient``'i orqali ishlaydi; ``utils/channel_reader.py``
veb-skreypingi esa to'g'ridan-to'g'ri :func:`safe_fetch` ga o'tdi.

Modul faqat standart kutubxonaga tayanadi va hech qachon istisno
ko'tarmaydi (fail-soft, ``ok=False`` + ``error_code``).
"""

from __future__ import annotations

import contextlib
import http.client
import ipaddress
import logging
import re
import socket
from collections.abc import Callable, Iterable
from typing import Any
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1) CHEGARALAR — qat'iy siyosat (topshiriq: ≤ 10 MB, 5–7 soniya)
# ---------------------------------------------------------------------------
MAX_RESPONSE_BYTES = 10 * 1024 * 1024      # javob hajmi chegarasi (10 MB)
MIN_TIMEOUT_SECONDS = 5.0                  # qat'iy timeout — pastki chegara
MAX_TIMEOUT_SECONDS = 7.0                  # qat'iy timeout — yuqori chegara
FETCH_TIMEOUT_SECONDS = 6.0                # standart timeout (5–7 orasida)
MAX_REDIRECTS = 3                          # redirect zanjiri chegarasi
READ_CHUNK_BYTES = 64 * 1024               # chunk-chunk o'qish (xotira himoyasi)
MAX_URL_LENGTH = 2048

ALLOWED_SCHEMES = ("http", "https")
ALLOWED_PORTS = {None, 80, 443}

#: Bulut metadata manzillari — NOMMA-NOM ro'yxat. Butun ``169.254.0.0/16``
#: va ``100.64.0.0/10`` diapazonlari ham bloklangan (quyida), shuning uchun
#: AWS/GCP/Azure/DigitalOcean/Render'ning link-local metadata endpoint'lari
#: (``169.254.169.254``) va CGNAT ichki metadata'lari ham qamraladi.
CLOUD_METADATA_IPS = frozenset({
    "169.254.169.254",        # AWS EC2 / GCP / Azure / DigitalOcean / Render
    "fd00:ec2::254",          # AWS IPv6 metadata (fc00::/7 qamrab oladi)
})

#: Ichki tarmoq/xizmat nomlari — host nomi bo'yicha ham bloklanadi.
BLOCKED_HOSTNAMES = frozenset({
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata", "metadata.google.internal", "metadata.aws.internal",
    "metadata.azure.internal", "instance-data", "render.metadata.internal",
})
#: Zaxira (reserved) domenlar — SSRF jihatidan hech qachon manba emas.
BLOCKED_HOST_SUFFIXES = (
    ".localhost", ".local", ".internal", ".lan", ".home", ".corp",
    ".intranet", ".invalid", ".test",
)

#: Ichki/xavfli IP tarmoqlari — QAT'IY ro'yxat (``is_global`` bilan birga).
BLOCKED_NETWORKS: tuple = tuple(
    ipaddress.ip_network(item) for item in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8",
        "169.254.0.0/16", "172.16.0.0/12", "192.0.0.0/24", "192.0.2.0/24",
        "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15", "198.51.100.0/24",
        "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4",
        "::/128", "::1/128", "fc00::/7", "fe80::/10", "ff00::/8",
    )
)

USER_AGENT = "PostAssistBot/2.0 (+security-gateway; SSRF-guarded)"

# ---------------------------------------------------------------------------
# 2) XATO KODLARI + YAGONA XAVFSIZ XABAR
# ---------------------------------------------------------------------------
ERR_INVALID_URL = "invalid_url"
ERR_BLOCKED_SCHEME = "blocked_scheme"
ERR_BLOCKED_HOST = "blocked_host"
ERR_BLOCKED_PORT = "blocked_port"
ERR_PRIVATE_ADDRESS = "private_address"
ERR_DNS_FAILURE = "dns_failure"
ERR_NETWORK = "network_error"
ERR_TIMEOUT = "timeout"
ERR_TOO_LARGE = "too_large"
ERR_HTTP_STATUS = "http_status"
ERR_REDIRECT_LIMIT = "redirect_limit"
ERR_CONTENT_TYPE = "content_type"

#: Xavfsizlik (SSRF) rad etish kodlari — bular uchun foydalanuvchi FAQAT
#: umumiy xavfsiz xabarni ko'radi.
SECURITY_ERROR_CODES = frozenset({
    ERR_INVALID_URL, ERR_BLOCKED_SCHEME, ERR_BLOCKED_HOST, ERR_BLOCKED_PORT,
    ERR_PRIVATE_ADDRESS, ERR_DNS_FAILURE, ERR_REDIRECT_LIMIT,
})

#: XAVFSIZ XATOLIK XABARI — ichki tafsilotlar (IP, DNS, port) foydalanuvchiga
#: chiqmaydi; aniq sabab faqat server logiga yoziladi.
SAFE_ERROR_MESSAGE = (
    "⚠️ Ushbu havola xavfsizlik tekshiruvidan o'tmadi yoki unga ulanib bo'lmadi."
)


# ---------------------------------------------------------------------------
# 3) SSRF VALIDATSIYASI (PURE + DNS tekshiruvi — barcha A/AAAA yozuvlar)
# ---------------------------------------------------------------------------
def resolve_host(host: str, port: int = 80) -> list[str]:
    """Host nomini IP manzillar ro'yxatiga aylantiradi (``getaddrinfo``).

    DNS xatosida bo'sh ro'yxat qaytadi (istisno ko'tarilmaydi — fail-closed).
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:  # noqa: BLE001 — DNS xatosi fail-closed yo'nalishda
        logger.info("URL gateway: DNS aniqlanmadi (%s)", host)
        return []
    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if sockaddr and sockaddr[0] and sockaddr[0] not in addresses:
            addresses.append(str(sockaddr[0]))
    return addresses


def is_blocked_ip(address: str) -> bool:
    """IP manzil ichki/xavfli (global bo'lmagan, metadata) ekanini bildiradi."""
    try:
        ip = ipaddress.ip_address(str(address).strip())
    except ValueError:
        return True  # o'qib bo'lmadi — fail-closed
    if str(ip) in CLOUD_METADATA_IPS:
        return True
    candidates = [ip]
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        candidates.append(mapped)
    for item in candidates:
        for network in BLOCKED_NETWORKS:
            if item.version != network.version:
                continue
            if item in network:
                return True
        # Qo'shimcha qatlam: global bo'lmagan har qanday manzil (reserved,
        # shared, benchmark, multicast...) ham bloklanadi.
        try:
            if not item.is_global:
                return True
        except Exception:  # noqa: BLE001 — pragma: no cover, eski Python'lar uchun himoya
            if item.is_private or item.is_loopback or item.is_link_local:
                return True
    return False


def _ip_literal(host: str) -> str | None:
    """Host IP literalmi? Bo'lsa — KANONIK ko'rinishini qaytaradi.

    ``inet_aton`` qisqa/o'nlik/o'n oltilik/sakkizlik shakllarni ham qabul
    qiladi (``2130706433`` / ``0x7f000001`` / ``0177.0.0.1`` / ``127.1`` →
    ``127.0.0.1``) — bular SSRF filtrlarining klassik chetlab o'tish yo'li,
    shu sababli kanonik ko'rinishga keltirilib tekshiriladi.
    """
    text = str(host or "").strip().strip("[]")
    if not text:
        return None
    try:
        return str(ipaddress.ip_address(text))
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(text)
    except OSError:
        return None
    return socket.inet_ntoa(packed)


def _normalize_host(host: str) -> str:
    """Host nomini kichik registrga + IDNA (punycode) ko'rinishiga keltiradi."""
    host = str(host or "").strip().strip("[]").lower()
    if not host:
        return ""
    if ":" in host:  # IPv6 literal
        return host
    try:
        return host.encode("idna").decode("ascii")
    except Exception:  # noqa: BLE001 — noto'g'ri domen
        return host


def validate_public_url(url: str, *, resolver: Callable[..., list] | None = None,
                        resolve_dns: bool = True) -> dict:
    """Havolani QAT'IY tekshiradi (SSRF himoyasi — markazlashtirilgan yadro).

    Qaytadi::

        {"ok": True, "url": "https://example.com/a", "host": "example.com",
         "port": 443, "addresses": ["93.184.216.34"], "error_code": None,
         "message": None}
        {"ok": False, "error_code": "private_address",
         "message": "⚠️ Ushbu havola xavfsizlik tekshiruvidan o'tmadi ..."}

    ``resolver`` — test uchun DNS almashtirgich (``(host, port) -> [ip, ...]``).
    ``resolve_dns=False`` bo'lsa faqat sintaktik tekshiruv bajariladi.
    """
    raw = str(url or "").strip()
    if not raw or len(raw) > MAX_URL_LENGTH:
        return {"ok": False, "error_code": ERR_INVALID_URL,
                "message": SAFE_ERROR_MESSAGE, "url": "", "host": "",
                "port": None, "addresses": []}
    try:
        parsed = urlparse.urlsplit(raw)
    except Exception:  # noqa: BLE001
        return {"ok": False, "error_code": ERR_INVALID_URL,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}

    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        return {"ok": False, "error_code": ERR_BLOCKED_SCHEME,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}
    if not parsed.netloc or not parsed.hostname:
        return {"ok": False, "error_code": ERR_INVALID_URL,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}
    if parsed.username or parsed.password:
        # URL ichidagi autentifikatsiya ma'lumotlari — SSRF/log sizishi.
        return {"ok": False, "error_code": ERR_BLOCKED_HOST,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}

    try:
        port = parsed.port
    except ValueError:
        return {"ok": False, "error_code": ERR_BLOCKED_PORT,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}
    if port not in ALLOWED_PORTS:
        return {"ok": False, "error_code": ERR_BLOCKED_PORT,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}
    effective_port = port or (443 if scheme == "https" else 80)

    host = _normalize_host(parsed.hostname or "")
    if not host:
        return {"ok": False, "error_code": ERR_INVALID_URL,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": "",
                "port": None, "addresses": []}
    if host in BLOCKED_HOSTNAMES or host.endswith(BLOCKED_HOST_SUFFIXES):
        return {"ok": False, "error_code": ERR_BLOCKED_HOST,
                "message": SAFE_ERROR_MESSAGE, "url": raw, "host": host,
                "port": effective_port, "addresses": []}

    # IP literal bo'lsa — to'g'ridan-to'g'ri tekshiriladi (DNS so'ralmaydi).
    literal = _ip_literal(host)

    addresses: list[str] = []
    if literal is not None:
        addresses = [literal]
    elif resolve_dns:
        addresses = list((resolver or resolve_host)(host, effective_port) or [])
        if not addresses:
            return {"ok": False, "error_code": ERR_DNS_FAILURE,
                    "message": SAFE_ERROR_MESSAGE, "url": raw, "host": host,
                    "port": effective_port, "addresses": []}

    for address in addresses:
        if is_blocked_ip(address):
            logger.warning("URL gateway: bloklangan manzil (%s → %s)",
                           host, address)
            return {"ok": False, "error_code": ERR_PRIVATE_ADDRESS,
                    "message": SAFE_ERROR_MESSAGE, "url": raw, "host": host,
                    "port": effective_port, "addresses": addresses}

    return {
        "ok": True,
        "url": urlparse.urlunsplit(
            (scheme, parsed.netloc, parsed.path or "/", parsed.query, "")),
        "host": host,
        "port": effective_port,
        "addresses": addresses,
        "error_code": None,
        "message": None,
    }


def safe_url_or_none(url: str, **kwargs) -> str | None:
    """Tekshiruvdan o'tgan havola (aks holda ``None``) — qisqa yordamchi."""
    result = validate_public_url(url, **kwargs)
    return result["url"] if result.get("ok") else None


# ---------------------------------------------------------------------------
# 4) DNS REBINDING HIMOYASI — tasdiqlangan IP'ga «pin» qilingan ulanish
# ---------------------------------------------------------------------------
def _public_pin_or_none(address: Any) -> str | None:
    """Pin uchun faqat kanonik, public IP qabul qiladi (fail-closed)."""
    try:
        text = str(address or "").strip()
        if not text or "%" in text:  # IPv6 zone-id tarmoq interfeysiga bog'liq
            return None
        canonical = str(ipaddress.ip_address(text))
    except (TypeError, ValueError):
        return None
    return None if is_blocked_ip(canonical) else canonical


def _redirect_limit(value: Any) -> int:
    """Redirect sonini 0..MAX_REDIRECTS oralig'ida qat'iy cheklaydi."""
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = MAX_REDIRECTS
    return min(MAX_REDIRECTS, max(0, parsed))


class _GatewayBlockedURLError(urlerror.URLError):
    """Transport validatsiyasi rad etgan URL uchun mashina-o'qiydigan xato."""

    def __init__(self, error_code: str):
        self.error_code = error_code
        super().__init__(f"blocked_by_gateway: {error_code}")


def _pinned_connector(pinned_ip: str) -> Callable[..., socket.socket]:
    """``socket.create_connection`` o'rnini bosuvchi — hostname'ni e'tiborsiz
    qoldirib, faqat kanonik tasdiqlangan public IP'ga ulanadi.

    ``socket.create_connection`` IP literaliga yana ``getaddrinfo`` chaqirishi
    mumkin; bu DNS hostname'ni qayta resolve qilmaydi va TOCTOU'ni ochmaydi.
    """
    pin = _public_pin_or_none(pinned_ip)
    if pin is None:
        raise ValueError("a validated public IP pin is required")

    def _connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                 source_address=None, **kwargs):
        _host, port = address
        if port not in (80, 443):
            raise OSError("URL gateway: blocked destination port")
        return socket.create_connection(
            (pin, port), timeout=timeout, source_address=source_address)

    return _connect


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP ulanishi — TCP faqat ``pinned_ip`` manziliga qotirilgan."""

    def __init__(self, host, port=None, *, pinned_ip=None, **kwargs):
        pin = _public_pin_or_none(pinned_ip)
        if pin is None:
            raise ValueError("a validated public IP pin is required")
        super().__init__(host, port=port, **kwargs)
        self.pinned_ip = pin
        self._create_connection = _pinned_connector(pin)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """TCP public ``pinned_ip`` ga qotiriladi; SNI/sertifikat asl host bilan."""

    def __init__(self, host, port=None, *, pinned_ip=None, **kwargs):
        pin = _public_pin_or_none(pinned_ip)
        if pin is None:
            raise ValueError("a validated public IP pin is required")
        super().__init__(host, port=port, **kwargs)
        self.pinned_ip = pin
        self._create_connection = _pinned_connector(pin)


def _strip_host_override(request) -> None:
    """HTTP Host qiymatini doim URL authority'sidan olishga majbur qiladi."""
    for attr in ("headers", "unredirected_hdrs"):
        headers_obj = getattr(request, attr, None)
        if not isinstance(headers_obj, dict):
            continue
        for key in tuple(headers_obj):
            if str(key).strip().lower() == "host":
                headers_obj.pop(key, None)


def _require_request_pin(req) -> str:
    pin = _public_pin_or_none(getattr(req, "pinned_ip", None))
    if pin is None:
        raise _GatewayBlockedURLError(ERR_PRIVATE_ADDRESS)
    # Keep the canonical value attached for the connection constructor.
    req.pinned_ip = pin
    _strip_host_override(req)
    return pin


class PinnedHTTPHandler(urlrequest.HTTPHandler):
    """HTTP'ni pin qilmasdan (DNS fallback bilan) yuborishga YO'L QO'YMAYDI."""

    def http_open(self, req):
        return self.do_open(_PinnedHTTPConnection, req,
                            pinned_ip=_require_request_pin(req))


class PinnedHTTPSHandler(urlrequest.HTTPSHandler):
    """HTTPS'ni pin qilmasdan yubormaydi; TLS hostname/SNI asl holda qoladi."""

    def https_open(self, req):
        return self.do_open(_PinnedHTTPSConnection, req,
                            context=self._context,
                            check_hostname=self._check_hostname,
                            pinned_ip=_require_request_pin(req))


class ValidatingRedirectHandler(urlrequest.HTTPRedirectHandler):
    """Har bir redirect nishoni qayta tekshiriladi va qayta IP-pin qilinadi."""

    def __init__(self, resolver=None, max_redirects: int = MAX_REDIRECTS):
        super().__init__()
        self.resolver = resolver
        self.max_redirections = _redirect_limit(max_redirects)

    def redirect_request(self, req, fp, code, msg, headers, newurl, *args):
        check = validate_public_url(newurl, resolver=self.resolver)
        if not check.get("ok"):
            logger.warning(
                "URL gateway: redirect bloklandi (%s → %s): %s",
                getattr(req, "full_url", "?"), newurl, check.get("error_code"))
            raise urlerror.HTTPError(
                newurl, code,
                f"blocked redirect: {check.get('error_code')}", headers, fp)
        addresses = check.get("addresses") or []
        pin = _public_pin_or_none(addresses[0]) if addresses else None
        if pin is None:
            # No unpinned follow-up is ever permitted, even if a future URL
            # validator accidentally returns ok=True without a DNS answer.
            raise urlerror.HTTPError(
                newurl, code, "blocked redirect: missing safe IP pin", headers, fp)
        newreq = super().redirect_request(req, fp, code, msg, headers,
                                          check["url"], *args)
        if newreq is not None:
            newreq.pinned_ip = pin
            _strip_host_override(newreq)
        return newreq


class PinnedUrllibClient:
    """DNS-rebinding'ga qarshi standart transport (urllib asosida).

    ``open()`` chaqiruvida havola DARHOL gateway validatsiyasidan o'tadi:
    barcha A/AAAA yozuvlari tekshiriladi va TCP ulanishi ANIQ tasdiqlangan
    IP'ga «pin» qilinadi — validator bilan ulanish orasida DNS javobini
    almashtirish (DNS rebinding) endi samarasiz. Redirect'lar ham xuddi shu
    qoida bilan qayta tekshirilib qayta pin qilinadi.
    """

    def __init__(self, resolver: Callable[..., list] | None = None,
                 max_redirects: int = MAX_REDIRECTS):
        self.resolver = resolver
        self._redirect = ValidatingRedirectHandler(resolver, max_redirects)
        self._http = PinnedHTTPHandler()
        self._https = PinnedHTTPSHandler()
        # Never let urllib honor HTTP_PROXY/HTTPS_PROXY: a proxy would resolve
        # the hostname on a different machine and bypass this socket pin.
        self._proxy = urlrequest.ProxyHandler({})
        self._opener = urlrequest.build_opener(
            self._proxy, self._http, self._https, self._redirect)

    def open(self, request, timeout: float = FETCH_TIMEOUT_SECONDS):
        if isinstance(request, str):
            request = build_safe_request(request)
        url = str(getattr(request, "full_url", "") or "")
        # A Request is mutable and callers can set arbitrary attributes. Never
        # trust a caller-provided ``pinned_ip``; resolve and validate the URL
        # here, immediately before handing it to the socket transport.
        with contextlib.suppress(AttributeError):
            delattr(request, "pinned_ip")
        check = validate_public_url(url, resolver=self.resolver)
        if not check.get("ok"):
            error_code = check.get("error_code") or ERR_INVALID_URL
            logger.warning("URL gateway: havola bloklandi (%s): %s",
                           check.get("host") or url, error_code)
            raise _GatewayBlockedURLError(error_code)
        addresses = check.get("addresses") or []
        pin = _public_pin_or_none(addresses[0]) if addresses else None
        if pin is None:
            logger.warning("URL gateway: xavfsiz IP pini topilmadi (%s)",
                           check.get("host") or url)
            raise _GatewayBlockedURLError(ERR_DNS_FAILURE)
        request.pinned_ip = pin
        _strip_host_override(request)
        return self._opener.open(request, timeout=timeout)


def build_safe_request(url: str,
                       extra_headers: dict | None = None) -> urlrequest.Request:
    """Standart xavfsiz so'rov (User-Agent + Accept) — test uchun ham qulay."""
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": ("text/html,application/xhtml+xml,text/plain;q=0.9,"
                   "*/*;q=0.1"),
        "Accept-Language": "uz,ru;q=0.8,en;q=0.6",
    }
    for key, value in (extra_headers or {}).items():
        if key and value is not None and str(key).strip().lower() != "host":
            headers[str(key)] = str(value)
    return urlrequest.Request(url, headers=headers)


def clamp_timeout(timeout: Any) -> float:
    """Timeout'ni qat'iy 5–7 soniya oralig'iga keltiradi."""
    try:
        value = float(timeout)
    except (TypeError, ValueError):
        return FETCH_TIMEOUT_SECONDS
    if value <= 0:
        return FETCH_TIMEOUT_SECONDS
    return min(MAX_TIMEOUT_SECONDS, max(MIN_TIMEOUT_SECONDS, value))


def clamp_max_bytes(max_bytes: Any) -> int:
    """Hajm chegarasini 1 bayt..10MB oralig'iga keltiradi."""
    try:
        value = int(max_bytes)
    except (TypeError, ValueError):
        return MAX_RESPONSE_BYTES
    if value <= 0:
        return MAX_RESPONSE_BYTES
    return min(value, MAX_RESPONSE_BYTES)


# ---------------------------------------------------------------------------
# 5) YAGONA XAVFSIZ FETCHER — safe_fetch
# ---------------------------------------------------------------------------
def _decode_body(raw: bytes, charset: str | None) -> str:
    """Javobni matnga aylantiradi (charset yoki xavfsiz fallback)."""
    if not raw:
        return ""
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except (LookupError, TypeError, ValueError):
            pass
    for candidate in ("utf-8", "cp1251", "latin-1"):
        try:
            return raw.decode(candidate, errors="replace")
        except (LookupError, TypeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def _charset_from_content_type(content_type: str) -> str | None:
    match = re.search(r"charset\s*=\s*[\"']?([\w\-]+)", content_type or "",
                      re.IGNORECASE)
    return match.group(1) if match else None


def safe_fetch(
    url: str,
    *,
    timeout: float = FETCH_TIMEOUT_SECONDS,
    max_bytes: int = MAX_RESPONSE_BYTES,
    allowed_content_types: Iterable[str] | None = None,
    resolver: Callable[..., list] | None = None,
    client: Any = None,
    headers: dict | None = None,
    max_redirects: int = MAX_REDIRECTS,
) -> dict:
    """Tashqi havolani SSRF/DNS-rebinding himoyasi bilan yuklaydi.

    Qat'iy chegaralar: timeout 5–7 s (``clamp_timeout``), hajm ≤ 10 MB
    (``clamp_max_bytes``), redirect ≤ 3 (har biri qayta tekshiriladi).

    Qaytadi::

        {"ok": True, "url": ..., "final_url": ..., "host": ...,
         "pinned_ip": "93.184.216.34", "status": 200,
         "content_type": "text/html", "text": "<html>...", "bytes": 1234,
         "error_code": None, "message": None}

    Har qanday xatoda ``ok=False`` + ``error_code`` + XAVFSIZ ``message``
    (:data:`SAFE_ERROR_MESSAGE`) — istisno KO'TARILMAYDI (fail-soft), ichki
    tafsilotlar faqat logga yoziladi. ``client`` — test uchun almashtiriladigan
    transport (``.open(request, timeout=...)``).
    """
    raw_url = str(url or "").strip()
    check = validate_public_url(raw_url, resolver=resolver)
    if not check.get("ok"):
        logger.warning("URL gateway: havola rad etildi (%s): %s",
                       check.get("host") or raw_url, check.get("error_code"))
        return {"ok": False, "error_code": check.get("error_code")
                or ERR_INVALID_URL, "message": SAFE_ERROR_MESSAGE,
                "url": raw_url, "final_url": "", "host": check.get("host"),
                "pinned_ip": None, "status": None, "content_type": "",
                "text": "", "bytes": 0}

    strict_timeout = clamp_timeout(timeout)
    size_cap = clamp_max_bytes(max_bytes)

    request = build_safe_request(check["url"], headers)
    pinned_ip = (check.get("addresses") or [None])[0]
    if pinned_ip:
        request.pinned_ip = pinned_ip

    http = client if client is not None else PinnedUrllibClient(
        resolver=resolver, max_redirects=_redirect_limit(max_redirects))
    try:
        response = http.open(request, timeout=strict_timeout)
        # The built-in transport revalidates immediately before connect and
        # replaces the preflight pin. Preserve that exact pin in the result.
        if client is None:
            pinned_ip = _public_pin_or_none(
                getattr(request, "pinned_ip", None)) or pinned_ip
    except urlerror.HTTPError as exc:
        code = getattr(exc, "code", None)
        reason = str(getattr(exc, "reason", "") or "")
        blocked = code in (301, 302, 303, 307, 308) or "blocked redirect" in reason
        error_code = ERR_REDIRECT_LIMIT if blocked else ERR_HTTP_STATUS
        logger.info("URL gateway: HTTP xato (%s): %s %s",
                    check["url"], code, reason[:120])
        return {"ok": False, "error_code": error_code,
                "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                "final_url": "", "host": check.get("host"),
                "pinned_ip": pinned_ip, "status": code, "content_type": "",
                "text": "", "bytes": 0}
    except urlerror.URLError as exc:
        reason = getattr(exc, "reason", None)
        gateway_error = getattr(exc, "error_code", None)
        if gateway_error in SECURITY_ERROR_CODES:
            logger.warning("URL gateway: transport qayta tekshiruvi rad etdi (%s)",
                           gateway_error)
            return {"ok": False, "error_code": gateway_error,
                    "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                    "final_url": "", "host": check.get("host"),
                    "pinned_ip": None, "status": None, "content_type": "",
                    "text": "", "bytes": 0}
        if isinstance(reason, TimeoutError) or isinstance(exc, TimeoutError):
            logger.info("URL gateway: timeout (%s)", check["url"])
            return {"ok": False, "error_code": ERR_TIMEOUT,
                    "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                    "final_url": "", "host": check.get("host"),
                    "pinned_ip": pinned_ip, "status": None,
                    "content_type": "", "text": "", "bytes": 0}
        logger.info("URL gateway: tarmoq xatosi (%s): %s", check["url"],
                    reason if reason is not None else exc)
        return {"ok": False, "error_code": ERR_NETWORK,
                "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                "final_url": "", "host": check.get("host"),
                "pinned_ip": pinned_ip, "status": None, "content_type": "",
                "text": "", "bytes": 0}
    except TimeoutError:
        logger.info("URL gateway: timeout (%s)", check["url"])
        return {"ok": False, "error_code": ERR_TIMEOUT,
                "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                "final_url": "", "host": check.get("host"),
                "pinned_ip": pinned_ip, "status": None, "content_type": "",
                "text": "", "bytes": 0}
    except Exception as exc:  # noqa: BLE001 — tarmoq xatolari fail-soft
        logger.info("URL gateway: kutilmagan xato (%s): %s", check["url"], exc)
        return {"ok": False, "error_code": ERR_NETWORK,
                "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                "final_url": "", "host": check.get("host"),
                "pinned_ip": pinned_ip, "status": None, "content_type": "",
                "text": "", "bytes": 0}

    raw = b""
    status = None
    content_type = ""
    try:
        status = int(getattr(response, "status", None)
                     or getattr(response, "code", 200) or 200)
        headers_obj = getattr(response, "headers", None)
        if headers_obj is not None:
            try:
                content_type = str(headers_obj.get("Content-Type", "") or "")
            except Exception:  # noqa: BLE001 — pragma: no cover, g'alati header obyekti
                content_type = ""
        declared = 0
        if headers_obj is not None:
            try:
                declared = int(headers_obj.get("Content-Length") or 0)
            except Exception:  # noqa: BLE001
                declared = 0
        if declared and declared > size_cap:
            return {"ok": False, "error_code": ERR_TOO_LARGE,
                    "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                    "final_url": str(getattr(response, "url", None)
                                     or check["url"]), "host": check.get("host"),
                    "pinned_ip": pinned_ip, "status": status,
                    "content_type": content_type, "text": "", "bytes": 0}

        while True:
            try:
                chunk = response.read(READ_CHUNK_BYTES)
            except TimeoutError:
                return {"ok": False, "error_code": ERR_TIMEOUT,
                        "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                        "final_url": str(getattr(response, "url", None)
                                         or check["url"]),
                        "host": check.get("host"), "pinned_ip": pinned_ip,
                        "status": status, "content_type": content_type,
                        "text": "", "bytes": len(raw)}
            except Exception as exc:  # noqa: BLE001
                logger.info("URL gateway: o'qish xatosi (%s): %s",
                            check["url"], exc)
                return {"ok": False, "error_code": ERR_NETWORK,
                        "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                        "final_url": str(getattr(response, "url", None)
                                         or check["url"]),
                        "host": check.get("host"), "pinned_ip": pinned_ip,
                        "status": status, "content_type": content_type,
                        "text": "", "bytes": len(raw)}
            if not chunk:
                break
            raw += chunk
            if len(raw) > size_cap:
                return {"ok": False, "error_code": ERR_TOO_LARGE,
                        "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                        "final_url": str(getattr(response, "url", None)
                                         or check["url"]),
                        "host": check.get("host"), "pinned_ip": pinned_ip,
                        "status": status, "content_type": content_type,
                        "text": "", "bytes": len(raw)}
    finally:
        with contextlib.suppress(Exception):  # pragma: no cover
            response.close()

    base_type = (content_type.split(";", 1)[0] or "").strip().lower()
    if allowed_content_types is not None:
        allowed = tuple(allowed_content_types)
        if base_type and base_type not in allowed:
            return {"ok": False, "error_code": ERR_CONTENT_TYPE,
                    "message": SAFE_ERROR_MESSAGE, "url": check["url"],
                    "final_url": str(getattr(response, "url", None)
                                     or check["url"]), "host": check.get("host"),
                    "pinned_ip": pinned_ip, "status": status,
                    "content_type": base_type, "text": "", "bytes": len(raw)}

    return {
        "ok": True,
        "error_code": None,
        "message": None,
        "url": check["url"],
        "final_url": str(getattr(response, "url", None) or check["url"]),
        "host": check.get("host"),
        "pinned_ip": pinned_ip,
        "status": status,
        "content_type": base_type or "text/html",
        "text": _decode_body(raw, _charset_from_content_type(content_type)),
        "bytes": len(raw),
    }


__all__ = [
    "ALLOWED_PORTS",
    "ALLOWED_SCHEMES",
    "BLOCKED_HOSTNAMES",
    "BLOCKED_HOST_SUFFIXES",
    "BLOCKED_NETWORKS",
    "CLOUD_METADATA_IPS",
    "ERR_BLOCKED_HOST",
    "ERR_BLOCKED_PORT",
    "ERR_BLOCKED_SCHEME",
    "ERR_CONTENT_TYPE",
    "ERR_DNS_FAILURE",
    "ERR_HTTP_STATUS",
    "ERR_INVALID_URL",
    "ERR_NETWORK",
    "ERR_PRIVATE_ADDRESS",
    "ERR_REDIRECT_LIMIT",
    "ERR_TIMEOUT",
    "ERR_TOO_LARGE",
    "FETCH_TIMEOUT_SECONDS",
    "MAX_REDIRECTS",
    "MAX_RESPONSE_BYTES",
    "MAX_TIMEOUT_SECONDS",
    "MAX_URL_LENGTH",
    "MIN_TIMEOUT_SECONDS",
    "SAFE_ERROR_MESSAGE",
    "SECURITY_ERROR_CODES",
    "USER_AGENT",
    "PinnedHTTPHandler",
    "PinnedHTTPSHandler",
    "PinnedUrllibClient",
    "ValidatingRedirectHandler",
    "build_safe_request",
    "clamp_max_bytes",
    "clamp_timeout",
    "is_blocked_ip",
    "resolve_host",
    "safe_fetch",
    "safe_url_or_none",
    "validate_public_url",
]
