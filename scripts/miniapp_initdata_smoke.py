#!/usr/bin/env python3
"""Haqiqiy Mini App ``initData`` bilan XAVFSIZ smoke-test (qo'lda ishga tushiriladi).

Foydalanish (TEST bot tokeni bilan; production tokenini ISHLATMANG):

    read -rs MINIAPP_SMOKE_BOT_TOKEN && export MINIAPP_SMOKE_BOT_TOKEN
    # initData ni mini-ilovadan nusxalab, 0600 fayl yoki stdin orqali bering:
    python scripts/miniapp_initdata_smoke.py --file /tmp/initdata.txt   # yoki: ... < fayl
    shred -u /tmp/initdata.txt

Chiqish FAQAT maxfiy bo'lmagan diagnostika: maydon NOMLARI, auth_date yoshi,
hash mosligi (ha/yo'q) va server validatorining xulosasi. Token, initData,
hash va maydon QIYMATLARI hech qachon chop etilmaydi / faylga yozilmaydi.
``signature`` bilan va usiz hisob FAQAT diagnostika sifatida solishtiriladi —
server validatori alternativani QABUL QILMAYDI.
Qo'shimcha: ``--api https://<domen>/api/v1`` — initData bilan ishlayotgan serverning ``GET /me`` ini chaqiradi
(haqiqiy end-to-end tekshiruv; token KERAK EMAS) va faqat HTTP holat + xato KODI / javob kalitlari nomlarini chop etadi.
Natija kodi: 0 — server qoidasi bo'yicha OK; 1 — rad; 2 — foydalanish xatosi.
"""
from __future__ import annotations

import json
import os
import stat
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

_ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(_ROOT))


def _read_init_data(path: str | None) -> str:
    if path:
        p = Path(path)
        mode = p.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SystemExit("Fayl ruxsati 0600 bo'lishi kerak (chmod 600).")
        raw = p.read_text(encoding="utf-8")
    else:
        raw = sys.stdin.read()
    return raw.strip()


def run(init_data: str, token: str, *, now: float | None = None, out=print) -> int:
    from miniapp_api.auth import AuthError, compute_hash, validate_init_data
    from miniapp_api.settings import is_valid_bot_token

    if not is_valid_bot_token(token):
        out("TOKEN: yaroqsiz format (o'zgaruvchi MINIAPP_SMOKE_BOT_TOKEN).")
        return 2
    now = time.time() if now is None else now
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=32, errors="strict")
    except (ValueError, UnicodeError):
        out("PARSE: initData ajratib bo'lmadi.")
        return 1
    fields = dict(pairs)
    out("Maydonlar: " + ", ".join(sorted(fields)))
    received = fields.pop("hash", "")
    try:
        age = int(now - int(fields.get("auth_date", "")))
        out(f"auth_date yoshi: {age} s")
    except ValueError:
        out("auth_date: yo'q yoki raqam emas")
    with_sig = compute_hash(fields, token) == received
    no_sig = False
    if "signature" in fields:
        no_sig = compute_hash({k: v for k, v in fields.items() if k != "signature"}, token) == received
    out(f"[diagnostika] hash mos (signature BILAN, server qoidasi): {with_sig}")
    if "signature" in fields:
        out(f"[diagnostika] hash mos (signature'SIZ, qabul qilinmaydi): {no_sig}")
    try:
        validate_init_data(init_data, token, now=now)
    except AuthError as exc:
        out(f"SERVER VALIDATORI: RAD ({exc.code})")
        return 1
    out("SERVER VALIDATORI: OK")
    return 0


def probe_api(init_data: str, base: str, *, opener=None, out=print) -> int:
    """``GET <base>/me`` — faqat holat va xato KODI/javob kalitlari chop etiladi (qiymatlar hech qachon)."""
    import urllib.error
    import urllib.request

    parts = urlsplit(base)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (parts.scheme == "http" and local):
        out("API: faqat https:// (yoki lokal http://localhost) manzil ruxsat etiladi.")
        return 2
    request = urllib.request.Request(base.rstrip("/") + "/me", headers={
        "Authorization": "tma " + init_data, "Accept": "application/json"}, method="GET")
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=15) as resp:  # nosec B310 — sxema yuqorida tekshirilgan
            status, raw = resp.status, resp.read(65536)
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read(65536)
    except Exception as exc:  # noqa: BLE001 — matnda URL/sarlavha bo'lishi mumkin
        out(f"API: ulanib bo'lmadi ({type(exc).__name__})")
        return 1
    try:
        body = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    if status == 200 and isinstance(body, dict):
        out(f"API /me: HTTP 200, javob kalitlari: {', '.join(sorted(body))}")
        return 0
    code = body.get("error", {}).get("code") if isinstance(body, dict) and isinstance(body.get("error"), dict) else None
    out(f"API /me: HTTP {status}, xato kodi: {code if isinstance(code, str) and len(code) < 40 else '?'}")
    return 1


def main(argv: list[str]) -> int:
    path = None
    api = None
    args = list(argv)
    while args:
        flag = args.pop(0)
        if flag == "--file" and args:
            path = args.pop(0)
        elif flag == "--api" and args:
            api = args.pop(0)
        else:
            print(__doc__)
            return 2
    token = os.environ.get("MINIAPP_SMOKE_BOT_TOKEN", "")
    try:
        data = _read_init_data(path)
    except (OSError, SystemExit) as exc:
        print(str(exc) if isinstance(exc, SystemExit) else "Faylni o'qib bo'lmadi.")
        return 2
    if not data:
        print("initData bo'sh.")
        return 2
    if api:
        return probe_api(data, api) if not token else max(run(data, token), probe_api(data, api))
    return run(data, token)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
