"""Mini App testlari uchun umumiy yordamchilar (test emas).

``sign_init_data`` Telegram hujjatidagi algoritmni ``miniapp_api.auth`` dan
MUSTAQIL qayta yozadi (o'zaro tasdiqlash aylanasi bo'lmasligi uchun).
Tokenlar faqat soxta test qiymatlari.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, urlencode

os.environ.setdefault("BOT_TOKEN", "123456789:TESTtokenABCDEFGHIJKLMNOPQRSTUV")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

REPO = Path(__file__).resolve().parent.parent
BOT_ROOT = REPO / "telegram_bot"
if str(BOT_ROOT) not in sys.path:
    sys.path.insert(0, str(BOT_ROOT))

FAKE_TOKEN = "123456789:TESTtokenABCDEFGHIJKLMNOPQRSTUV"
NOW = 1_760_000_000


class Counter:
    def __init__(self, title: str):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        print("=" * 70)
        print(f" {title}")
        print("=" * 70)

    def check(self, label: str, condition, detail: str = "") -> None:
        if condition:
            self.passed += 1
            print(f"  [OK] {label}")
        else:
            self.failed += 1
            print(f"  [XATO] {label}" + (f" — {detail}" if detail else ""))

    def skip(self, label: str, reason: str) -> None:
        self.skipped += 1
        print(f"  [SKIP] {label} — {reason}")

    def finish(self) -> int:
        print("\n" + "=" * 70)
        print(f" JAMI: o'tdi={self.passed}, xato={self.failed}, skip={self.skipped}")
        print("=" * 70)
        return 0 if self.failed == 0 else 1


def sign_fields(fields: dict, token: str = FAKE_TOKEN) -> str:
    """Hujjat algoritmi: hash'dan boshqa BARCHA maydonlar (signature ham) saralanadi."""
    dcs = "\n".join(f"{k}={fields[k]}" for k in sorted(fields) if k != "hash")
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    return hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()


def make_init_data(user_id: int = 4242, *, auth_date: int = NOW, token: str = FAKE_TOKEN,
                   extra: dict | None = None, user_obj=None, drop=(), lang="uz") -> str:
    user = user_obj if user_obj is not None else {
        "id": user_id, "first_name": "Test", "language_code": lang}
    fields = {"auth_date": str(auth_date), "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
              "user": user if isinstance(user, str) else json.dumps(user, separators=(",", ":"))}
    fields.update(extra or {})
    for key in drop:
        fields.pop(key, None)
    fields["hash"] = sign_fields(fields, token)
    return urlencode(fields, quote_via=quote)
