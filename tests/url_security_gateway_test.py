#!/usr/bin/env python3
"""🛡 URL SECURITY GATEWAY — SSRF HIMOYASI UNIT TESTLARI (PHASE 1).

Markazlashtirilgan ``services/url_security_gateway.py`` shlyuzining qat'iy
SSRF siyosati, DNS-rebinding himoyasi, chegaralar (≤10 MB / 5–7 s) va
yagona xavfsiz xato xabari sinanadi — HECH QANDAY REAL TARMOQ KERAK EMAS
(DNS — stub resolver, transport — fake klient; ``sources_rss_and_recycle``
testidagi ``stub_dns`` usuli).

Ishga tushirish:
    cd telegram_bot && python tests/url_security_gateway_test.py

Qamrov:
  TEST 1  SSRF validatsiyasi: 127.0.0.1 / localhost / metadata IP
          (169.254.169.254) / 10.x / 172.16.x / 192.168.x / IPv6 / o'nlik-
          hex-sakkizlik chetlab o'tish shakllari / xavfli sxemalar / portlar
          → QAT'IY bloklanadi; NORMAL URL (ommaviy IP) → ruxsat.
  TEST 2  DNS REBINDING: bitta yozuv ham ichki bo'lsa — butun host blok.
  TEST 3  Chegaralar: timeout 5–7 s ga clamp, hajm ≤ 10 MB.
  TEST 4  PIN: TCP ulanishi aynan tasdiqlangan IP'ga (host emas!) qotiriladi.
  TEST 5  safe_fetch: muvaffaqiyat / hajm oshishi / content-type / redirect
          bloki / timeout — barchasi fail-soft + XAVFSIZ xabar.
  TEST 6  Xavfsiz xabar: har qanday rad etishda foydalanuvchi FAQAT
          ``SAFE_ERROR_MESSAGE`` ni ko'radi (ichki tafsilot chiqmaydi).
  TEST 7  Integratsiya: ``utils/channel_reader`` (veb-skreyping) gateway
          orqali o'tadi; SSRF havolasi SAFE_ERROR_MESSAGE bilan rad.
  TEST 8  PARITET: gateway va ``url_extractor.validate_public_url`` bir xil
          qarorga keladi (ikkala qatlam drift bo'lishidan qo'riqlanadi) va
          ``url_extractor.fetch_url`` API'si orqaga mos.
"""
import asyncio
import os
import sys
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

# ------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanadi.
# ------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:URL_GATEWAY_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("ADMIN_IDS", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10042")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


from services import url_security_gateway as gw  # noqa: E402

PUBLIC_IP = "93.184.216.34"          # example.com — ommaviy (test stub IP)
PUBLIC_IP_2 = "2606:2800:220:1:248:1893:25c8:1946"  # ommaviy IPv6


def stub_resolver(ips=(PUBLIC_IP,)):
    return lambda host, port=None: list(ips)


# ======================================================================
# TEST 1 — SSRF VALIDATSIYASI (127.0.0.1, metadata, normal URL)
# ======================================================================
def test_ssrf_validation():
    print("\n== TEST 1: 🛡 SSRF validatsiyasi — ichki manzillar bloklanadi ==")
    blocked = (
        ("http://127.0.0.1/admin", "private_address"),
        ("http://127.0.0.1:8080/admin", "blocked_port"),
        ("https://127.0.0.1/webhook", "private_address"),
        ("http://localhost/x", "blocked_host"),
        ("http://localhost.localdomain/x", "blocked_host"),
        ("http://169.254.169.254/latest/meta-data/", "private_address"),
        ("http://169.254.169.254/computeMetadata/v1/", "private_address"),
        ("http://metadata.google.internal/", "blocked_host"),
        ("http://10.0.0.5/internal", "private_address"),
        ("http://10.255.255.254/", "private_address"),
        ("http://172.16.5.4/", "private_address"),
        ("http://172.31.255.255/", "private_address"),
        ("http://192.168.1.1/router", "private_address"),
        ("http://192.168.0.254/", "private_address"),
        ("http://100.64.0.1/", "private_address"),          # CGNAT/metadata
        ("http://[::1]/", "private_address"),
        ("http://[fe80::1]/", "private_address"),
        ("http://[fc00::1]/", "private_address"),
        # IP chetlab o'tish shakllari — kanonik ko'rinishga keltiriladi
        ("http://127.1/", "private_address"),
        ("http://2130706433/", "private_address"),          # o'nlik 127.0.0.1
        ("http://0x7f000001/", "private_address"),          # hex 127.0.0.1
        ("http://0177.0.0.1/", "private_address"),          # sakkizlik
        # Sxema / port / host qoidalari
        ("file:///etc/passwd", "blocked_scheme"),
        ("ftp://example.com/x", "blocked_scheme"),
        ("gopher://example.com/x", "blocked_scheme"),
        ("javascript:alert(1)", "blocked_scheme"),
        ("http://example.com:8080/x", "blocked_port"),
        ("http://user:pass@example.com/", "blocked_host"),
        ("http://app.corp/secret", "blocked_host"),
        ("http://wiki.intranet/", "blocked_host"),
    )
    for url, expected_code in blocked:
        res = gw.validate_public_url(url)
        check(f"SSRF blok: {url}",
              res.get("ok") is False
              and res.get("error_code") == expected_code
              and res.get("message") == gw.SAFE_ERROR_MESSAGE,
              f"→ {res.get('error_code')} / {res.get('message')!r}")

    # NORMAL URL — ommaviy manzil ruxsat etiladi (stub DNS).
    res = gw.validate_public_url("https://example.com/article?x=1",
                                 resolver=stub_resolver())
    check("normal URL: ruxsat etiladi", res.get("ok") is True, str(res))
    check("normal URL: host aniqlandi", res.get("host") == "example.com", "")
    check("normal URL: addresses — stub natijasi",
          res.get("addresses") == [PUBLIC_IP], str(res.get("addresses")))
    check("normal URL: port 443 (https standarti)",
          res.get("port") == 443, str(res.get("port")))
    check("normal URL: fragment tozalandi",
          "#" not in res.get("url", ""), res.get("url"))

    res2 = gw.validate_public_url("http://sub.example.com:80/a",
                                  resolver=stub_resolver())
    check("normal URL: http 80 ruxsat", res2.get("ok") is True, str(res2))

    # DNS javob bermasa — fail-closed (dns_failure).
    res3 = gw.validate_public_url("https://no-such-host.example.com",
                                  resolver=lambda h, p=None: [])
    check("DNS javobsiz: fail-closed (dns_failure)",
          res3.get("ok") is False and res3.get("error_code") == "dns_failure",
          str(res3))


# ======================================================================
# TEST 2 — DNS REBINDING (aralash yozuvlar)
# ======================================================================
def test_dns_rebinding_records():
    print("\n== TEST 2: 🔀 DNS rebinding — barcha A/AAAA yozuvlari tekshiriladi ==")
    # Bir yozuv ichki bo'lsa — butun host bloklanadi (rebind:// hujumi).
    res = gw.validate_public_url(
        "https://rebind.example.com",
        resolver=lambda h, p=None: [PUBLIC_IP, "169.254.169.254"])
    check("aralash (public+metadata): BLOK",
          res.get("ok") is False and res.get("error_code") == "private_address",
          str(res.get("error_code")))
    res2 = gw.validate_public_url(
        "https://rebind.example.com",
        resolver=lambda h, p=None: [PUBLIC_IP, "10.0.0.7"])
    check("aralash (public+10.x): BLOK",
          res2.get("ok") is False, str(res2.get("error_code")))
    # Barcha yozuvlar ommaviy — ruxsat.
    res3 = gw.validate_public_url(
        "https://ok.example.com",
        resolver=lambda h, p=None: [PUBLIC_IP, "93.184.216.35"])
    check("barcha yozuvlar ommaviy: ruxsat", res3.get("ok") is True, str(res3))
    # IPv6 ommaviy yozuv ham qabul qilinadi.
    res4 = gw.validate_public_url(
        "https://v6.example.com", resolver=lambda h, p=None: [PUBLIC_IP_2])
    check("ommaviy IPv6 yozuv: ruxsat", res4.get("ok") is True, str(res4))


# ======================================================================
# TEST 3 — CHEGARALAR (timeout 5–7 s, hajm ≤ 10 MB)
# ======================================================================
def test_limits():
    print("\n== TEST 3: 📏 Chegaralar — qat'iy timeout va hajm limiti ==")
    check("clamp_timeout(0.5) → 5.0 (pastki chegara)",
          gw.clamp_timeout(0.5) == 5.0, str(gw.clamp_timeout(0.5)))
    check("clamp_timeout(30) → 7.0 (yuqori chegara)",
          gw.clamp_timeout(30) == 7.0, str(gw.clamp_timeout(30)))
    check("clamp_timeout(6) → 6.0 (oraliqda)",
          gw.clamp_timeout(6) == 6.0, str(gw.clamp_timeout(6)))
    check("clamp_timeout(None/xato) → standart 6.0",
          gw.clamp_timeout(None) == 6.0 and gw.clamp_timeout("abc") == 6.0, "")
    check("DEFAULT_TIMEOUT 5–7 oralig'ida",
          5.0 <= gw.FETCH_TIMEOUT_SECONDS <= 7.0,
          str(gw.FETCH_TIMEOUT_SECONDS))

    check("clamp_max_bytes(50 MB) → 10 MB (qat'iy shifft)",
          gw.clamp_max_bytes(50 * 1024 * 1024) == gw.MAX_RESPONSE_BYTES,
          str(gw.clamp_max_bytes(50 * 1024 * 1024)))
    check("clamp_max_bytes(100) → 100 (torroq chegara saqlanadi)",
          gw.clamp_max_bytes(100) == 100, "")
    check("MAX_RESPONSE_BYTES ≤ 10 MB",
          gw.MAX_RESPONSE_BYTES <= 10 * 1024 * 1024,
          str(gw.MAX_RESPONSE_BYTES))


# ======================================================================
# TEST 4 — DNS PIN (ulanish aynan tasdiqlangan IP'ga)
# ======================================================================
def test_dns_pinning():
    print("\n== TEST 4: 📌 DNS pin — TCP aynan tasdiqlangan IP'ga ulanadi ==")
    # a) connector HOSTNI IGNORAB, pin qilingan IP'ga ulanadi.
    conn = gw._PinnedHTTPConnection("evil.example.com", pinned_ip=PUBLIC_IP)
    with patch("socket.create_connection") as mock_cc:
        mock_cc.return_value = "SOCK"
        sock = conn._create_connection(("evil.example.com", 80), 6.0, None)
        dialed = mock_cc.call_args[0][0]
        check("pin: ulanish manzili — PIN IP (host emas)",
              dialed == (PUBLIC_IP, 80), str(dialed))
        check("pin: timeout uzatildi",
              mock_cc.call_args[1].get("timeout") == 6.0, "")
        check("pin: natija qaytdi", sock == "SOCK", "")

    # b) PinnedUrllibClient: validatsiya → pin → opener.
    client = gw.PinnedUrllibClient(resolver=stub_resolver())
    captured = {}

    def fake_opener_open(request, timeout=None):
        captured["pinned_ip"] = getattr(request, "pinned_ip", None)
        captured["timeout"] = timeout
        return "RESPONSE"

    client._opener.open = fake_opener_open
    req = gw.build_safe_request("https://example.com/x")
    result = client.open(req, timeout=6.5)
    check("client: pin o'rnatildi (stub IP)",
          captured.get("pinned_ip") == PUBLIC_IP, str(captured))
    check("client: timeout uzatildi", captured.get("timeout") == 6.5, "")
    check("client: opener natijasi qaytdi", result == "RESPONSE", "")

    # c) Oldindan pin qo'yilgan so'rov — qayta validatsiya QILINMAYDI.
    req2 = gw.build_safe_request("https://example.com/y")
    req2.pinned_ip = "1.2.3.4"
    captured.clear()
    client.open(req2, timeout=6)
    check("client: oldindan pin qilingan so'rov o'zgarmaydi",
          captured.get("pinned_ip") == "1.2.3.4", str(captured))

    # d) Bloklangan havola — tarmoqqa chiqilmaydi (URLError).
    import urllib.error as urlerror
    blocked_client = gw.PinnedUrllibClient(resolver=stub_resolver())
    try:
        blocked_client.open(gw.build_safe_request("http://127.0.0.1/secret"))
        check("client: bloklangan havola URLError ko'taradi", False,
              "istisno otilmadi")
    except urlerror.URLError as exc:
        check("client: bloklangan havola URLError ko'taradi",
              "blocked_by_gateway" in str(exc), str(exc))

    # e) Redirect handler: har bir nishon qayta tekshiriladi va qayta pin.
    handler = gw.ValidatingRedirectHandler(resolver=stub_resolver())
    from urllib import request as urlrequest
    base_req = urlrequest.Request("https://example.com/a")
    base_req.pinned_ip = PUBLIC_IP
    try:
        handler.redirect_request(
            base_req, None, 302, "Found",
            {"Location": "http://169.254.169.254/latest/"}, "http://127.0.0.1/x")
        check("redirect: metadata nishon BLOKLANADI", False, "o'tib ketdi")
    except urlerror.HTTPError as exc:
        check("redirect: metadata nishon BLOKLANADI",
              "blocked redirect" in str(exc), str(exc))
    newreq = handler.redirect_request(
        base_req, None, 302, "Found",
        {"Location": "https://ok.example.com/b"}, "https://ok.example.com/b")
    check("redirect: ommaviy nishon ruxsat + QAYTA PIN",
          newreq is not None and getattr(newreq, "pinned_ip", None) == PUBLIC_IP,
          str(getattr(newreq, "pinned_ip", None)))


# ======================================================================
# TEST 5 — safe_fetch (fake transport bilan, tarmoqsiz)
# ======================================================================
class FakeResponse:
    """Urllib javosini imitatsiya qiladi (status/headers/read/close)."""

    def __init__(self, status=200, body=b"<html>ok</html>",
                 content_type="text/html; charset=utf-8", url=""):
        self.status = status
        self.code = status
        self.url = url or "https://example.com/x"
        self._body = body
        self.closed = False
        self.headers = SimpleNamespace(
            get=lambda name, default=None: {
                "Content-Type": content_type,
                "Content-Length": str(len(body)),
            }.get(name, default))

    def read(self, size=-1):
        if self.closed or not self._body:
            return b""
        chunk = self._body[:max(1, size)] if size and size > 0 else self._body
        self._body = self._body[len(chunk):]
        return chunk

    def close(self):
        self.closed = True


class FakeClient:
    """``.open(request, timeout)`` interfeysli soxta transport."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append((str(getattr(request, "full_url", "")), timeout,
                           getattr(request, "pinned_ip", None)))
        if self.error is not None:
            raise self.error
        return self.response


def test_safe_fetch():
    print("\n== TEST 5: 🔄 safe_fetch — fail-soft yuklash (fake transport) ==")
    resolver = stub_resolver()

    # a) Muvaffaqiyatli yuklash.
    client = FakeClient(FakeResponse(200, b"<html>Salom</html>",
                                     "text/html; charset=utf-8"))
    res = gw.safe_fetch("https://example.com/x", resolver=resolver,
                        client=client)
    check("fetch: ok=True", res.get("ok") is True, str(res))
    check("fetch: status 200", res.get("status") == 200, "")
    check("fetch: matn dekodlandi",
          res.get("text") == "<html>Salom</html>", repr(res.get("text")))
    check("fetch: bytes sanaldi", res.get("bytes") == 18, str(res.get("bytes")))
    check("fetch: content_type tozalandi",
          res.get("content_type") == "text/html", res.get("content_type"))
    check("fetch: host + final_url",
          res.get("host") == "example.com" and res.get("final_url"), str(res))
    check("fetch: pin transportga yetdi",
          client.calls and client.calls[0][2] == PUBLIC_IP, str(client.calls))
    check("fetch: timeout qat'iy oralig'ga clamp qilindi",
          client.calls and 5.0 <= client.calls[0][1] <= 7.0, str(client.calls))

    # b) Hajm oshishi — Content-Length oldindan tekshiriladi.
    big = FakeResponse(200, b"x" * 100, "text/html")
    big.headers = SimpleNamespace(
        get=lambda name, default=None: {
            "Content-Type": "text/html",
            "Content-Length": "999999999",
        }.get(name, default))
    client2 = FakeClient(big)
    res2 = gw.safe_fetch("https://example.com/big", resolver=resolver,
                         client=client2, max_bytes=50)
    check("fetch: Content-Length > limit → too_large",
          res2.get("ok") is False and res2.get("error_code") == "too_large",
          str(res2.get("error_code")))

    # c) Hajm oshishi — chunk o'qishda aniqlanadi.
    class ChunkyClient(FakeClient):
        def open(self, request, timeout=None):
            self.calls.append((str(getattr(request, "full_url", "")),
                               timeout, getattr(request, "pinned_ip", None)))
            # Content-Length bermaymiz — faqat chunk chegarasi ishlashi kerak
            resp = FakeResponse(200, b"a" * (5 * 1024 * 1024), "text/plain")
            resp.headers = SimpleNamespace(
                get=lambda name, default=None: {"Content-Type": "text/plain"}
                .get(name, default))
            return resp

    res3 = gw.safe_fetch("https://example.com/huge", resolver=resolver,
                         client=ChunkyClient(), max_bytes=1000)
    check("fetch: chunk chegarasi → too_large",
          res3.get("ok") is False and res3.get("error_code") == "too_large",
          str(res3.get("error_code")))

    # d) Content-type filtri.
    client4 = FakeClient(FakeResponse(200, b"BIN", "application/octet-stream"))
    res4 = gw.safe_fetch("https://example.com/file.bin", resolver=resolver,
                         client=client4,
                         allowed_content_types=("text/html", "text/plain"))
    check("fetch: ruxsat etilmagan content-type → rad",
          res4.get("ok") is False and res4.get("error_code") == "content_type",
          str(res4.get("error_code")))
    res4b = gw.safe_fetch("https://example.com/file.bin", resolver=resolver,
                          client=FakeClient(FakeResponse(
                              200, b"BIN", "application/octet-stream")))
    check("fetch: allowed_content_types=None → filtrlanmaydi",
          res4b.get("ok") is True, str(res4b.get("error_code")))

    # e) Bloklangan redirect — HTTPError transportdan.
    import urllib.error as urlerror
    err = urlerror.HTTPError("https://example.com/r", 302,
                             "blocked redirect: private_address", None, None)
    client5 = FakeClient(error=err)
    res5 = gw.safe_fetch("https://example.com/r", resolver=resolver,
                         client=client5)
    check("fetch: bloklangan redirect → redirect_limit + xavfsiz xabar",
          res5.get("ok") is False
          and res5.get("error_code") == "redirect_limit"
          and res5.get("message") == gw.SAFE_ERROR_MESSAGE,
          str(res5.get("error_code")))

    # f) Timeout — URLError(reason=timeout) to'g'ri tasniflanadi.
    err6 = urlerror.URLError(socket.timeout("timed out"))
    res6 = gw.safe_fetch("https://slow.example.com/", resolver=resolver,
                         client=FakeClient(error=err6))
    check("fetch: timeout → error_code=timeout",
          res6.get("ok") is False and res6.get("error_code") == "timeout",
          str(res6.get("error_code")))

    # g) Tarmoq xatosi.
    res7 = gw.safe_fetch("https://down.example.com/", resolver=resolver,
                         client=FakeClient(error=OSError("refused")))
    check("fetch: tarmoq xatosi → network_error (istisno EMAS)",
          res7.get("ok") is False and res7.get("error_code") == "network_error",
          str(res7.get("error_code")))

    # h) SSRF havolasi — transportga UMUMAN borilmaydi.
    class Boom:
        def open(self, *a, **k):
            raise AssertionError("tarmoqqa chiqmasligi kerak edi!")

    for bad in ("http://127.0.0.1/x", "http://169.254.169.254/meta-data",
                "file:///etc/passwd", "http://localhost/a"):
        res8 = gw.safe_fetch(bad, client=Boom())
        check(f"fetch: {bad} — tarmoqqa chiqilmaydi",
              res8.get("ok") is False
              and res8.get("message") == gw.SAFE_ERROR_MESSAGE,
              str(res8.get("error_code")))


# ======================================================================
# TEST 6 — XAVFSIZ XATO XABARI (SPESIFIKATSIYA MATNI)
# ======================================================================
def test_safe_message():
    print("\n== TEST 6: 🔒 Yagona xavfsiz xato xabari ==")
    expected = ("⚠️ Ushbu havola xavfsizlik tekshiruvidan o'tmadi "
                "yoki unga ulanib bo'lmadi.")
    check("SAFE_ERROR_MESSAGE — spetsifikatsiya matni aynan",
          gw.SAFE_ERROR_MESSAGE == expected, gw.SAFE_ERROR_MESSAGE)
    for bad in ("http://127.0.0.1/", "http://10.0.0.1/", "ftp://x/"):
        res = gw.validate_public_url(bad)
        check(f"validate: {bad} → xabar LEAK Yo'Q (IP/sabab yashirilgan)",
              res.get("message") == expected
              and "127" not in res.get("message", "")
              and "10.0" not in res.get("message", ""), "")
    check("SECURITY_ERROR_CODES — asosiy SSRF kodlari qamrab olingan",
          {"private_address", "blocked_host", "blocked_scheme",
           "blocked_port", "dns_failure"} <= set(gw.SECURITY_ERROR_CODES),
          str(gw.SECURITY_ERROR_CODES))


# ======================================================================
# TEST 7 — INTEGRATSIYA: channel_reader (veb-skreyping) gateway'da
# ======================================================================
def test_channel_reader_gateway():
    print("\n== TEST 7: 🌐 Veb-skreyping (channel_reader) — gateway orqali ==")
    import utils.channel_reader as cr

    # a) _fetch_html — gateway.safe_fetch chaqiradi va (status, text, ctype)
    #    qaytaradi; hajm/timeout/header argumentlari uzatiladi.
    calls = {}

    def fake_safe_fetch(url, **kwargs):
        calls["url"] = url
        calls["kwargs"] = kwargs
        return {"ok": True, "error_code": None, "message": None,
                "status": 200, "text": "<html>t.me</html>",
                "content_type": "text/html; charset=utf-8"}

    with patch.object(gw, "safe_fetch", fake_safe_fetch):
        status, html, ctype = asyncio.run(cr._fetch_html("https://t.me/s/kanal"))
    check("_fetch_html: status/text/ctype qaytdi",
          status == 200 and html == "<html>t.me</html>"
          and "text/html" in ctype, f"{status}/{ctype}")
    check("_fetch_html: timeout 5–7 s oralig'ida uzatildi",
          5.0 <= calls["kwargs"].get("timeout", 0) <= 7.0,
          str(calls["kwargs"].get("timeout")))
    check("_fetch_html: hajm chegarasi (2 MB) uzatildi",
          calls["kwargs"].get("max_bytes") == 2_000_000,
          str(calls["kwargs"].get("max_bytes")))
    check("_fetch_html: brauzer header'lari uzatildi",
          "User-Agent" in (calls["kwargs"].get("headers") or {}), "")

    # b) Gateway rad etishi — GatewayBlockedError (xavfsizlik kodlari).
    def fake_safe_fetch_blocked(url, **kwargs):
        return {"ok": False, "error_code": "private_address",
                "message": gw.SAFE_ERROR_MESSAGE}

    with patch.object(gw, "safe_fetch", fake_safe_fetch_blocked):
        try:
            asyncio.run(cr._fetch_html("http://192.168.1.1/router"))
            check("_fetch_html: SSRF → GatewayBlockedError", False,
                  "istisno otilmadi")
        except cr.GatewayBlockedError as exc:
            check("_fetch_html: SSRF → GatewayBlockedError",
                  exc.error_code == "private_address"
                  and exc.message == gw.SAFE_ERROR_MESSAGE, str(exc))

    # c) Gateway tarmoq xatosi — oddiy OSError (boshqa xabarlar saqlanadi).
    def fake_safe_fetch_net(url, **kwargs):
        return {"ok": False, "error_code": "timeout", "message": None}

    with patch.object(gw, "safe_fetch", fake_safe_fetch_net):
        try:
            asyncio.run(cr._fetch_html("https://slow.example.com/"))
            check("_fetch_html: timeout → OSError (GatewayBlocked EMAS)",
                  False, "istisno otilmadi")
        except cr.GatewayBlockedError:
            check("_fetch_html: timeout → OSError (GatewayBlocked EMAS)",
                  False, "noto'g'ri istisno turi")
        except OSError:
            check("_fetch_html: timeout → OSError (GatewayBlocked EMAS)",
                  True, "")

    # d) read_webpage_for_ai: SSRF havolasi → XAVFSIZ umumiy xabar.
    #    (IP literal — DNS kerak emas, deterministik.)
    page = asyncio.run(
        cr.read_webpage_for_ai("http://169.254.169.254/latest/meta-data/"))
    check("read_webpage_for_ai: metadata IP → SAFE_ERROR_MESSAGE",
          page.get("error") == gw.SAFE_ERROR_MESSAGE, str(page))
    page2 = asyncio.run(cr.read_webpage_for_ai("http://127.0.0.1:8080/admin"))
    check("read_webpage_for_ai: 127.0.0.1 → SAFE_ERROR_MESSAGE",
          page2.get("error") == gw.SAFE_ERROR_MESSAGE, str(page2))


# ======================================================================
# TEST 8 — PARITET + ORQAGA MOSLIK (url_extractor)
# ======================================================================
def test_parity_with_extractor():
    print("\n== TEST 8: 🤝 Paritet — gateway ↔ url_extractor (drift qo'riqoni) ==")
    from services.sources import url_extractor as ux

    resolver = stub_resolver()
    matrix = (
        # (url, kutilgan ok)
        ("http://127.0.0.1/", False),
        ("http://localhost/x", False),
        ("http://169.254.169.254/latest/meta-data", False),
        ("http://10.0.0.5/internal", False),
        ("http://172.16.5.4/", False),
        ("http://192.168.1.1/router", False),
        ("http://[::1]/", False),
        ("http://metadata.google.internal/", False),
        ("http://2130706433/", False),
        ("file:///etc/passwd", False),
        ("http://example.com:8080/x", False),
        ("https://example.com/article", True),
        ("http://sub.example.com:80/a", True),
    )
    agree = True
    detail = []
    for url, expect_ok in matrix:
        g = gw.validate_public_url(url, resolver=resolver)
        u = ux.validate_public_url(url, resolver=resolver)
        if bool(g.get("ok")) != bool(u.get("ok")) or bool(g.get("ok")) != expect_ok:
            agree = False
            detail.append((url, g.get("ok"), g.get("error_code"),
                           u.get("ok"), u.get("error_code")))
    check("gateway va url_extractor bir xil qarorda (13 holat)",
          agree, str(detail))

    # Orqaga moslik: url_extractor.fetch_url — client in'yeksiyasi va natija
    # shakli o'zgarmagan (kanal: fake transport).
    fake = FakeClient(FakeResponse(200, b"<html>maqola</html>",
                                   "text/html; charset=utf-8"))
    res = ux.fetch_url("https://example.com/article", client=fake,
                       resolver=resolver)
    check("url_extractor.fetch_url: ok=True (eski API saqlangan)",
          res.get("ok") is True and res.get("status") == 200, str(res))
    check("url_extractor.fetch_url: text/bytes/final_url shakli",
          res.get("text") == "<html>maqola</html>"
          and res.get("bytes") == 19 and "final_url" in res, str(res))
    res2 = ux.fetch_url("http://127.0.0.1/secret", client=FakeClient())
    check("url_extractor.fetch_url: SSRF rad (o'z xabarlari bilan)",
          res2.get("ok") is False
          and res2.get("error_code") == "private_address"
          and res2.get("message") == ux.user_message("private_address"),
          str(res2.get("error_code")))


# ======================================================================
def main():
    print("=" * 70)
    print(" 🛡 URL SECURITY GATEWAY — SSRF HIMOYASI UNIT TESTLARI (PHASE 1)")
    print("=" * 70)
    test_ssrf_validation()
    test_dns_rebinding_records()
    test_limits()
    test_dns_pinning()
    test_safe_fetch()
    test_safe_message()
    test_channel_reader_gateway()
    test_parity_with_extractor()
    print()
    if failures:
        print(f"❌ {failures} ta tekshiruv YIQILDI (jami {passed + failures})")
        sys.exit(1)
    print(f"✅ BARCHA GATEWAY TESTLARI O'TDI ({passed} tekshiruv)")


if __name__ == "__main__":
    main()
