"""``/app/*`` statik fayllar va SPA fallback (faqat shu prefiks doirasida).

Himoya: yo'l ``realpath`` bilan hal qilinadi va ``dist`` ildizidan tashqariga
chiqsa (``..``, URL-kodlash, absolyut yo'l, backslash, NUL, symlink) rad etiladi.
SPA fallback faqat kengaytmasiz yo'llar uchun (yo'q ``.js``/``.css`` -> 404, HTML emas).
"""
from __future__ import annotations

import os

from aiohttp import web

APP_PREFIX = "/app"

# Telegram Mini App uchun: frame-ancestors Telegram web klientlariga ruxsat,
# X-Frame-Options QO'YILMAYDI (u WebView/iframe'ni tasodifan bloklardi).
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://telegram.org; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'none'; object-src 'none'; form-action 'none'; "
    "frame-ancestors https://web.telegram.org https://*.telegram.org https://telegram.org"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def resolve_safe_path(dist_dir: str, tail: str) -> str | None:
    """``dist`` ichidagi mavjud fayl yo'li yoki ``None`` (xavfli/yo'q)."""
    if "\x00" in tail or "\\" in tail or tail.startswith("/"):
        return None
    if any(part == ".." for part in tail.split("/")):
        return None
    root = os.path.realpath(dist_dir)
    candidate = os.path.realpath(os.path.join(root, tail))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
    except ValueError:
        return None
    return candidate if os.path.isfile(candidate) else None


def _not_found() -> web.Response:
    return web.Response(status=404, text="Not found", headers={
        **SECURITY_HEADERS, "Cache-Control": "no-store"})


def make_static_handlers(dist_dir: str):
    async def redirect_root(request: web.Request):
        raise web.HTTPPermanentRedirect(APP_PREFIX + "/")

    async def serve(request: web.Request):
        tail = request.match_info.get("tail", "")
        index = resolve_safe_path(dist_dir, "index.html")
        if tail in ("", "index.html"):
            target, is_index = index, True
        else:
            target = resolve_safe_path(dist_dir, tail)
            is_index = False
            if target is None:
                last = tail.rsplit("/", 1)[-1]
                if "." in last or "\x00" in tail or "\\" in tail:
                    return _not_found()  # yo'q asset: HTML qaytarilmaydi
                target, is_index = index, True  # SPA marshruti
        if target is None:
            return _not_found()
        resp = web.FileResponse(target)
        resp.headers.update(SECURITY_HEADERS)
        if is_index:
            resp.headers["Cache-Control"] = "no-cache"
        elif tail.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp

    return redirect_root, serve


def register_static_routes(app: web.Application, dist_dir: str) -> None:
    redirect_root, serve = make_static_handlers(dist_dir)
    app.router.add_get(APP_PREFIX, redirect_root)
    app.router.add_get(APP_PREFIX + "/{tail:.*}", serve)
