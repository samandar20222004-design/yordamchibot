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
Natija kodi: 0 — server qoidasi bo'yicha OK; 1 — rad; 2 — foydalanish xatosi.
"""
from __future__ import annotations

import os
import stat
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl

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


def main(argv: list[str]) -> int:
    path = None
    if argv[:1] == ["--file"] and len(argv) == 2:
        path = argv[1]
    elif argv:
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
    return run(data, token)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
