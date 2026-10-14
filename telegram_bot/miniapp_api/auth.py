"""Telegram Mini App ``initData`` tekshiruvi (rasmiy bot-token HMAC-SHA-256).

Algoritm (https://core.telegram.org/bots/webapps — "Validating data received
via the Mini App"):

  1. ``initData`` — URL-kodlangan ``key=value&...`` satr;
  2. ``hash`` maydoni ajratib olinadi; QOLGAN BARCHA maydonlar (shu jumladan
     ``signature``, agar kelsa) kalit bo'yicha alifbo tartibida
     ``key=<decoded value>`` ko'rinishida ``\\n`` bilan birlashtiriladi;
  3. ``secret_key = HMAC_SHA256(key=b"WebAppData", msg=BOT_TOKEN)``;
  4. ``hash == hex(HMAC_SHA256(key=secret_key, msg=data_check_string))``.

``signature`` (Ed25519, uchinchi tomon tekshiruvi uchun) bu yerda tekshirilmaydi:
bot-token usulida u oddiy maydon sifatida data-check-string ichida qoladi.

F5 HOLATI (tasdiqlash darajasi): rasmiy hujjat sandbox tarmog'idan o'qib bo'lmadi (siyosat 403) — rasmiy qoida
bu sessiyada TASDIQLANMAGAN. Uchinchi tomon (rasmiy emas) implementatsiyalari bilan o'qib solishtirildi va MOS:
aiogram 3.31.0 (`check_webapp_signature`: faqat `hash` chiqariladi, `signature` qoladi; Ed25519 usulida ikkalasi
chiqariladi va `<bot_id>:WebAppData\\n` prefiksi) va @telegram-apps/init-data-node 2.0.10 (xuddi shunday). Ularning
literal HMAC vektorlari bu kod bilan bir xil natija beradi (tests/miniapp_auth_test.py, 10-bo'lim). Haqiqiy Telegram
klientidan olingan `initData` bilan sinov hali o'tkazilmagan.

Bu modul sof funksiyalardan iborat: tarmoq/DB yo'q, BOT_TOKEN va initData
hech qachon log yoki xato matniga yozilmaydi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from urllib.parse import parse_qsl

from .settings import is_valid_bot_token

_HASH_RE = re.compile(r"\A[0-9a-f]{64}\Z")
_AUTH_DATE_RE = re.compile(r"\A[0-9]{1,12}\Z")
_MAX_FIELDS = 32
_MAX_USER_ID = 2 ** 53
_SCHEME = "tma"


class AuthError(Exception):
    """Autentifikatsiya xatosi. ``code`` — :mod:`errors` katalog kaliti.

    Xabar ATAYLAB bo'sh: foydalanuvchi qiymatlari xatoga tushmasin.
    """

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class VerifiedUser:
    user_id: int
    auth_date: int
    language_code: str | None = None


def parse_authorization(header: str | None) -> str:
    """``Authorization: tma <initData>`` -> xom ``initData`` (yoki AuthError)."""
    if not header or not isinstance(header, str):
        raise AuthError("unauthorized")
    scheme, sep, value = header.partition(" ")
    if not sep or scheme.lower() != _SCHEME or not value or value != value.strip():
        raise AuthError("unauthorized")
    return value


def _json_reject_constant(_name):  # NaN/Infinity -> rad
    raise ValueError("constant")


def _parse_fields(init_data: str, max_bytes: int) -> dict[str, str]:
    if not isinstance(init_data, str) or not init_data:
        raise AuthError("unauthorized")
    if len(init_data.encode("utf-8", "surrogatepass")) > max_bytes:
        raise AuthError("unauthorized")
    if "\x00" in init_data:
        raise AuthError("unauthorized")
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=_MAX_FIELDS, errors="strict")
    except (ValueError, UnicodeError):
        raise AuthError("unauthorized") from None
    fields: dict[str, str] = {}
    for key, value in pairs:
        if not key or value == "" or key in fields:
            raise AuthError("unauthorized")  # bo'sh kalit/qiymat va TAKROR kalit
        fields[key] = value
    return fields


def compute_hash(fields_without_hash: dict[str, str], bot_token: str) -> str:
    data_check_string = "\n".join(
        f"{key}={fields_without_hash[key]}" for key in sorted(fields_without_hash)
    )
    secret_key = hmac.new(b"WebAppData", bot_token.encode("ascii"),
                          hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def validate_init_data(init_data: str, bot_token: str, *, now: float,
                       max_age: int = 3600, future_skew: int = 60,
                       max_bytes: int = 4096) -> VerifiedUser:
    """``initData`` ni tekshiradi va TASDIQLANGAN foydalanuvchini qaytaradi.

    Xatolar: ``AuthError('auth_unavailable')`` — token yo'q/yaroqsiz
    (fail-closed); ``'auth_expired'`` — muddati o'tgan; ``'unauthorized'`` —
    boshqa barcha holatlar.
    """
    if not is_valid_bot_token(bot_token):
        raise AuthError("auth_unavailable")

    fields = _parse_fields(init_data, max_bytes)
    received_hash = fields.pop("hash", None)
    if received_hash is None or not _HASH_RE.match(received_hash):
        raise AuthError("unauthorized")
    auth_date_raw = fields.get("auth_date")
    user_raw = fields.get("user")
    if auth_date_raw is None or user_raw is None:
        raise AuthError("unauthorized")
    if not _AUTH_DATE_RE.match(auth_date_raw):
        raise AuthError("unauthorized")

    expected = compute_hash(fields, bot_token)
    if not hmac.compare_digest(expected.encode("ascii"), received_hash.encode("ascii")):
        raise AuthError("unauthorized")

    # --- imzo to'g'ri: endi MAYDONLAR mazmunini tekshiramiz ---------------
    auth_date = int(auth_date_raw)
    age = now - auth_date
    if age < -future_skew:
        raise AuthError("unauthorized")
    if age > max_age:
        raise AuthError("auth_expired")

    try:
        user = json.loads(user_raw, parse_constant=_json_reject_constant)
    except (ValueError, RecursionError):
        raise AuthError("unauthorized") from None
    if not isinstance(user, dict):
        raise AuthError("unauthorized")
    user_id = user.get("id")
    if (not isinstance(user_id, int) or isinstance(user_id, bool)
            or user_id <= 0 or user_id > _MAX_USER_ID):
        raise AuthError("unauthorized")
    lang = user.get("language_code")
    lang = lang if isinstance(lang, str) and len(lang) <= 12 else None
    return VerifiedUser(user_id=user_id, auth_date=auth_date, language_code=lang)
