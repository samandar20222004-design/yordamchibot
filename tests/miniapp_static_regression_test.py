#!/usr/bin/env python3
"""Mini App — /app/* statik serving, SPA fallback, path traversal va server regressiyasi.

Muhit: aiohttp TestClient, vaqtinchalik `dist` katalogi (tmp). Tarmoq/DB yo'q.
Regressiya: MINIAPP_ENABLED=0 da hech narsa ulanmaydi; /health*, / va
POST /payments/payme javoblari yoqilgan holatda ham o'zgarmaydi.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from miniapp_api import app as appmod  # noqa: E402
from miniapp_api.static import resolve_safe_path  # noqa: E402

T = Counter("MINI APP — STATIC /app/* + SERVER REGRESSIYASI")
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)
INDEX = "<!doctype html><title>MINIAPP-INDEX</title>"
SECRET = "TOP-SECRET-OUTSIDE-DIST"


def run(coro):
    return LOOP.run_until_complete(coro)


async def fetch(app, method, path, **kw):
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        resp = await client.request(method, path, allow_redirects=False, **kw)
        body = await resp.read()
        return resp.status, body, resp.headers
    finally:
        await client.close()


def make_dist(root: Path) -> Path:
    dist = root / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX)
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    (dist / "favicon.svg").write_text("<svg/>")
    (root / "outside.txt").write_text(SECRET)
    try:
        os.symlink(root / "outside.txt", dist / "leak.txt")
        os.symlink(root, dist / "linkdir")
    except OSError:
        pass
    return dist


def mini_app(dist: Path, **extra) -> web.Application:
    app = web.Application()
    env = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
           "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_DIST_DIR": str(dist), **extra}
    assert appmod.register_miniapp_routes(app, env=env)
    return app


def test_static():
    print("\n== 1. /app/* servis ==")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dist = make_dist(root)
        app = mini_app(dist)
        st, body, h = run(fetch(app, "GET", "/app/"))
        T.check("/app/ -> index.html", st == 200 and b"MINIAPP-INDEX" in body)
        T.check("index.html no-cache", h.get("Cache-Control") == "no-cache")
        st, body, h = run(fetch(app, "GET", "/app"))
        T.check("/app -> /app/ ga yo'naltirish", st == 308 and h.get("Location") == "/app/")
        st, body, h = run(fetch(app, "GET", "/app/index.html"))
        T.check("/app/index.html", st == 200 and b"MINIAPP-INDEX" in body)
        st, body, h = run(fetch(app, "GET", "/app/assets/app.js"))
        T.check("asset 200 + JS content-type", st == 200 and "javascript" in h.get("Content-Type", ""))
        T.check("hash'li asset immutable kesh", "immutable" in h.get("Cache-Control", ""))
        st, body, h = run(fetch(app, "GET", "/app/favicon.svg"))
        T.check("boshqa statik fayl", st == 200 and h.get("Cache-Control", "").startswith("public"))
        T.check("X-Content-Type-Options: nosniff", h.get("X-Content-Type-Options") == "nosniff")
        csp = h.get("Content-Security-Policy", "")
        T.check("CSP: frame-ancestors Telegram web", "frame-ancestors https://web.telegram.org" in csp)
        T.check("CSP: script-src 'self' + telegram.org (WebApp SDK)", "script-src 'self' https://telegram.org" in csp)
        T.check("CSP: default-src 'self', object-src 'none'", "default-src 'self'" in csp and "object-src 'none'" in csp)
        directives = {d.strip().split(" ", 1)[0]: d.strip() for d in csp.split(";") if d.strip()}
        T.check("CSP: img-src 'blob:' ruxsat (qoralama rasmi blob: URL)", "blob:" in directives.get("img-src", "").split(), directives.get("img-src", ""))
        T.check("CSP: blob: FAQAT img-src'da (script/connect/default/style/font kengaytirilmagan)",
                [k for k, v in directives.items() if "blob:" in v.split()] == ["img-src"], str(directives))
        T.check("CSP: img-src boshqa manbalari saqlangan ('self' data: https:)",
                all(x in directives.get("img-src", "").split() for x in ("'self'", "data:", "https:")))
        T.check("CSP: connect-src hamon faqat 'self'", directives.get("connect-src") == "connect-src 'self'", directives.get("connect-src", ""))
        T.check("X-Frame-Options QO'YILMAGAN (Telegram WebView bloklanmaydi)", "X-Frame-Options" not in h)
        st, body, h = run(fetch(app, "HEAD", "/app/"))
        T.check("HEAD /app/ 200", st == 200)
        st, body, h = run(fetch(app, "POST", "/app/"))
        T.check("POST /app/ ruxsat etilmaydi", st == 405)

    print("\n== 2. SPA fallback faqat /app/* ichida ==")
    with tempfile.TemporaryDirectory() as tmp:
        dist = make_dist(Path(tmp))
        app = mini_app(dist)
        st, body, _ = run(fetch(app, "GET", "/app/plan/pro"))
        T.check("/app/plan/pro -> index.html (SPA)", st == 200 and b"MINIAPP-INDEX" in body)
        st, body, _ = run(fetch(app, "GET", "/app/missing.js"))
        T.check("yo'q .js -> 404, HTML EMAS", st == 404 and b"MINIAPP-INDEX" not in body)
        st, body, _ = run(fetch(app, "GET", "/app/assets/nope.css"))
        T.check("yo'q .css -> 404", st == 404 and b"MINIAPP-INDEX" not in body)
        for path in ("/", "/health/live", "/health/other", "/payments/other", "/payments", "/other/route"):
            st, body, _ = run(fetch(app, "GET", path))
            T.check(f"{path} index.html QAYTARMAYDI", b"MINIAPP-INDEX" not in body)
        st, body, h = run(fetch(app, "GET", "/api/v1/unknown"))
        T.check("/api/v1/unknown -> JSON 404, HTML emas", st == 404 and b"MINIAPP-INDEX" not in body
                and "json" in h.get("Content-Type", ""))
        st, body, h = run(fetch(app, "GET", "/api/zzz"))
        T.check("/api/zzz -> JSON 404", st == 404 and "json" in h.get("Content-Type", ""))
        st, body, h = run(fetch(app, "GET", "/application"))
        T.check("/application (prefiks o'xshash) -> SPA emas", b"MINIAPP-INDEX" not in body)

    print("\n== 3. Path traversal ==")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dist = make_dist(root)
        app = mini_app(dist)
        attempts = ["/app/%2e%2e/outside.txt", "/app/..%2foutside.txt", "/app/%2e%2e%2foutside.txt",
                    "/app/assets/..%2f..%2foutside.txt", "/app//outside.txt", f"/app/{root}/outside.txt",
                    f"/app//{root}/outside.txt", "/app/%5c..%5coutside.txt", "/app/..%5coutside.txt",
                    "/app/%00", "/app/index.html%00.txt", "/app/%252e%252e/outside.txt",
                    "/app/....//outside.txt", "/app/assets/%2e%2e/%2e%2e/outside.txt",
                    "/app/leak.txt", "/app/linkdir/outside.txt", "/app/linkdir"]
        for path in attempts:
            st, body, _ = run(fetch(app, "GET", path))
            T.check(f"{path[:60]} -> sirt fayl SIZMAYDI", SECRET.encode() not in body)
        T.check("symlink (dist ichidan tashqariga) 404", run(fetch(app, "GET", "/app/leak.txt"))[0] == 404)
        d = str(dist)
        T.check("resolve: '..'", resolve_safe_path(d, "../outside.txt") is None)
        T.check("resolve: absolyut", resolve_safe_path(d, str(root / "outside.txt")) is None)
        T.check("resolve: backslash", resolve_safe_path(d, "..\\outside.txt") is None)
        T.check("resolve: NUL", resolve_safe_path(d, "index.html\x00.png") is None)
        T.check("resolve: symlink tashqariga", resolve_safe_path(d, "leak.txt") is None)
        T.check("resolve: symlink katalog tashqariga", resolve_safe_path(d, "linkdir/outside.txt") is None)
        T.check("resolve: oddiy fayl", resolve_safe_path(d, "assets/app.js") is not None)
        T.check("resolve: katalog fayl emas", resolve_safe_path(d, "assets") is None)

    print("\n== 4. dist yo'q ==")
    with tempfile.TemporaryDirectory() as tmp:
        app = mini_app(Path(tmp) / "no-such-dist")
        st, body, _ = run(fetch(app, "GET", "/app/"))
        T.check("dist yo'q: /app/ 404 (500 emas)", st == 404)
        st, body, _ = run(fetch(app, "GET", "/app/some/route"))
        T.check("dist yo'q: SPA yo'li 404", st == 404)


def test_real_build():
    print("\n== 4b. Haqiqiy `miniapp/dist` build natijasi bilan shartnoma ==")
    import re

    dist = Path(__file__).resolve().parent.parent / "miniapp" / "dist"
    if not (dist / "index.html").is_file():
        T.skip("haqiqiy build bilan /app/* tekshiruvi", "BLOCKED: miniapp/dist qurilmagan (cd miniapp && npm ci && npm run build)")
        return
    app = mini_app(dist)
    st, body, h = run(fetch(app, "GET", "/app/"))
    html = body.decode("utf8")
    T.check("haqiqiy index.html /app/ dan beriladi", st == 200 and "<div id=\"root\">" in html)
    refs = re.findall(r'(?:src|href)="(/app/[^"]+)"', html)
    T.check("index.html /app/ prefiksli lokal resurslarga ega (vite base mos)", len(refs) >= 2, str(refs))
    local = [r for r in re.findall(r'(?:src|href)="([^"]+)"', html) if not r.startswith(("http://", "https://", "//"))]
    T.check("barcha lokal havolalar /app/ ostida", all(r.startswith("/app/") for r in local), str(local))
    kinds = {}
    for ref in refs:
        st, body, h = run(fetch(app, "GET", ref))
        T.check(f"{ref}: 200 va bo'sh emas", st == 200 and len(body) > 100)
        if ref.startswith("/app/assets/"):  # faqat hash'li build assetlari immutable bo'lishi shart
            kinds[ref.rsplit(".", 1)[-1]] = (st, h.get("Content-Type", ""), h.get("Cache-Control", ""))
    T.check("JS to'g'ri content-type bilan", "javascript" in kinds.get("js", (0, ""))[1])
    T.check("CSS to'g'ri content-type bilan", "text/css" in kinds.get("css", (0, ""))[1])
    T.check("hash'li assetlar immutable", all("immutable" in v[2] for v in kinds.values()))
    # Yuklash ekrani logosi: hash'siz statik fayl — rasm sifatida beriladi, immutable EMAS (almashtirilsa yangilansin).
    st, body, h = run(fetch(app, "GET", "/app/logo-192.png"))
    T.check("yuklash ekrani logosi /app/logo-192.png: 200 + image/png", st == 200 and "image/png" in h.get("Content-Type", "") and body[:4] == b"\x89PNG")
    T.check("logo immutable emas (qisqa kesh)", "immutable" not in h.get("Cache-Control", "") and "max-age" in h.get("Cache-Control", ""))
    T.check("index.html yuklash ekrani (splash) logosi bilan", "splash" in html and "/app/logo-192.png" in html)
    T.check("Telegram WebApp SDK <script> bor (CSP script-src bilan mos)", "https://telegram.org/js/telegram-web-app.js" in html)
    st, body, h = run(fetch(app, "GET", "/app/some/deep/link"))
    T.check("SPA chuqur havola index.html beradi", st == 200 and b'id="root"' in body)


def _baseline_snapshot(app):
    async def go():
        out = {}
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            for path in ("/", "/health", "/health/live", "/health/ready"):
                r = await client.get(path)
                try:
                    j = await r.json()
                except Exception:  # noqa: BLE001
                    j = None
                if isinstance(j, dict):
                    j.pop("uptime_seconds", None)
                out[path] = (r.status, j, r.headers.get("Cache-Control"))
            r = await client.get("/payments/payme")
            out["payme GET"] = (r.status, await r.text())
            r = await client.post("/payments/payme", data="{}", headers={"Content-Type": "application/json"})
            out["payme POST noauth"] = (r.status, await r.text())
            r = await client.get("/health/ready", headers={"Authorization": "Bearer x"})
            out["ready bearer"] = r.status
            r = await client.get("/nope")
            out["404"] = r.status
            return out
        finally:
            await client.close()
    return run(go())


def test_regression():
    print("\n== 5. Server regressiyasi: /health*, /, /payments/payme ==")
    from utils.web_server import build_web_app

    keys = ("MINIAPP_ENABLED", "MINIAPP_PROXY_ASSERT_EDGE_ONLY", "MINIAPP_DIST_DIR", "HEALTH_READY_TOKEN")
    saved = {k: os.environ.pop(k, None) for k in keys}
    try:
        app_off = build_web_app()
        routes_off = sorted(r.canonical for r in app_off.router.resources())
        T.check("MINIAPP_ENABLED yo'q: faqat mavjud marshrutlar",
                routes_off == ["/", "/health", "/health/live", "/health/ready", "/payments/payme"], str(routes_off))
        T.check("MINIAPP_ENABLED yo'q: /api va /app ulanmagan",
                not any(r.startswith(("/api", "/app")) for r in routes_off))
        os.environ["MINIAPP_ENABLED"] = "0"
        app_zero = build_web_app()
        T.check("MINIAPP_ENABLED=0: marshrutlar o'zgarmagan",
                sorted(r.canonical for r in app_zero.router.resources()) == routes_off)
        snap_off = _baseline_snapshot(app_off)
        with tempfile.TemporaryDirectory() as tmp:
            dist = make_dist(Path(tmp))
            os.environ.update({"MINIAPP_ENABLED": "1", "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1",
                               "MINIAPP_DIST_DIR": str(dist)})
            app_on = build_web_app()
            routes_on = sorted(r.canonical for r in app_on.router.resources())
            T.check("yoqilgan: /api/v1 va /app ulanadi", "/api/v1" in routes_on and "/app/{tail}" in routes_on)
            T.check("yoqilgan: eski marshrutlar saqlangan", set(routes_off) <= set(routes_on))
            snap_on = _baseline_snapshot(app_on)
        T.check("yoqilgan holatda / , /health* , /payments/payme javoblari AYNAN bir xil",
                snap_off == snap_on, str({k: (snap_off[k], snap_on[k]) for k in snap_off if snap_off[k] != snap_on[k]}))
        T.check("/health/live 200", snap_off["/health/live"][0] == 200 and snap_off["/health/live"][1]["status"] == "live")
        T.check("/health/ready token yo'q -> 404 (fail-closed)", snap_off["/health/ready"][0] == 404)
        T.check("/payments/payme GET -> Payme -32300 (200 JSON-RPC)", snap_off["payme GET"][0] == 200 and "-32300" in snap_off["payme GET"][1])
        T.check("/payments/payme POST auth'siz -> -32504", "-32504" in snap_off["payme POST noauth"][1])
        # xavfsiz bo'lmagan sozlamada ulanmaydi, lekin web-app ishlaydi
        os.environ.pop("MINIAPP_PROXY_ASSERT_EDGE_ONLY")
        app_bad = build_web_app()
        routes_bad = sorted(r.canonical for r in app_bad.router.resources())
        T.check("xavfsiz bo'lmagan sozlama: Mini App ulanmaydi, bot serveri to'liq ishlaydi", routes_bad == routes_off)
        _ = FAKE_TOKEN
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def main() -> int:
    test_static()
    test_real_build()
    test_regression()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
