"""Sentry maxfiylik filtri (data scrubber) — PostAssist V2, 10-BOSQICH.

Sentry'ga yuboriladigan HAR QANDAY event ushbu filtrdan o'tadi
(``sentry_sdk.init(before_send=scrub_event)``). Maqsad — sezgir ma'lumotlar
bot token, DB paroli, karta rekvizitlari, API kalitlar, parollar) hech qachon
Sentry loglariga tushmasligi.

Himoya qatlamlari:

1. **Ma'lum qiymatlar ro'yxati** (``register_secret``): config moduli ishga
   tushganda o'zi bilgan barcha sezgir qiymatlarni (``BOT_TOKEN``,
   ``DATABASE_URL`` ichidagi parol, ``CARD_NUMBER``, API kalitlar...) ro'yxatga
   oladi. Event matnida shu qiymatlarning ANIQ mosligi ko'rinsa — o'chiriladi.
2. **Regex aniqlagichlar**: Telegram bot tokeni, ``postgres://user:parol@``
   URL'lari, 13–19 xonali karta raqamlari (bo'shliq/defis bilan ham) va
   "eyewitness" API kalit formatlari matn ichidan avtomatik topiladi.
3. **Kalit bo'yicha filtr**: lug'atlarda ``password``, ``token``, ``secret``,
   ``authorization`` kabi nomli istalgan maydon qiymati o'chiriladi.

Modul faqat standart kutubxonaga bog'liq — ``sentry_sdk`` o'rnatilmagan
bo'lsa ham import qilinadi va unit-testlarda to'g'ridan-to'g'ri tekshiriladi.

Foydalanish::

    from utils.sentry_scrubber import scrub_event, register_secret
    register_secret("123456:AA...", "BOT_TOKEN")
    sentry_sdk.init(dsn=..., before_send=scrub_event, send_default_pii=False)
"""

from __future__ import annotations

import re
import threading

__all__ = [
    "REDACTED",
    "REDACTED_TOKEN",
    "REDACTED_CARD",
    "register_secret",
    "clear_secrets",
    "mask_card_number",
    "scrub_text",
    "scrub_value",
    "scrub_event",
]

#: Noma'lum sezgir qiymat o'rniga qo'yiladigan belgi.
REDACTED = "[REDACTED]"
#: Bot token aniqlanganda qo'yiladigan belgi.
REDACTED_TOKEN = "[REDACTED:BOT_TOKEN]"
#: Karta raqami aniqlanganda qo'yiladigan belgi (oxirgi 4 xona qoladi).
REDACTED_CARD = "[REDACTED:CARD]"

# ──────────────────────────────────────────────────────────────
# REGEX ANIQLAGICHLAR
# ──────────────────────────────────────────────────────────────

# Telegram bot token: 123456789:AA... (8-10 xona + ':' + 30+ belgi)
_BOT_TOKEN_RE = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,64}\b")

# DB ulanish URL'idagi parol: postgresql://user:PAROL@host
_DB_PASSWORD_RE = re.compile(
    r"(?i)\b(postgres(?:ql)?|mysql|redis|amqp|mongodb(?:\+srv)?)://"
    r"([^:/@\s]+):([^@\s]+)@"
)

# Karta raqami: 16 xona, 4 talik guruhda (bo'shliq/defis ixtiyoriy)
_CARD_GROUPED_RE = re.compile(r"\b\d{4}(?:[ -]?\d{4}){2}[ -]?\d{1,4}\b")
# Karta raqami: uzluksiz 13–19 xona
_CARD_PLAIN_RE = re.compile(r"\b\d{13,19}\b")

# Ko'p uchraydigan API kalit formatlari (aniq qiymat ro'yxatidan tashqari
# qo'shimcha himoya): sk-..., AIza..., ghp_..., xoxb-..., key bilan boshlanadi.
_API_KEY_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{30,}|"
    r"ghp_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"gsk_[A-Za-z0-9_-]{20,}|csk-[A-Za-z0-9_-]{20,}|"
    r"sk-or-v1-[A-Za-z0-9]{20,})\b"
)

# ──────────────────────────────────────────────────────────────
# SEZGIR QIYMATLAR RO'YXATI (config moduli to'ldiradi)
# ──────────────────────────────────────────────────────────────

_lock = threading.Lock()
#: {aniq_qiymat: yorliq} — qiymatlar pastga qarab uzunligi bo'yicha saralanadi.
_secrets: dict[str, str] = {}

#: Lug'at kalitlari bo'yicha filtr (kichik harfda solishtiriladi).
SENSITIVE_KEYS = frozenset({
    "password", "passwd", "pwd", "secret", "token", "bot_token",
    "api_key", "apikey", "api-key", "access_token", "refresh_token",
    "authorization", "auth", "cookie", "cookies", "session",
    "card_number", "cardnumber", "card_holder", "pan", "cvv", "cvc",
    "dsn", "database_url", "private_key", "credential", "credentials",
    "x-api-key", "set-cookie",
})

#: Ro'yxatga olinadigan qiymatning minimal uzunligi (juda qisqa qiymatlar
#: oddiy matnlarni noto'g'ri o'chirib yuborishi mumkin).
_MIN_SECRET_LEN = 8


def register_secret(value, label: str = "SECRET") -> bool:
    """Sezgir qiymatni ro'yxatga oladi (aniq mosliklar o'chiriladi).

    Bo'sh, ``None`` yoki juda qisqa qiymatlar e'tiborga olinmaydi.
    Qaytadi: ``True`` — ro'yxatga olindi.
    """
    if value is None:
        return False
    text = str(value).strip()
    if len(text) < _MIN_SECRET_LEN:
        return False
    with _lock:
        _secrets[text] = str(label or "SECRET")
    return True


def clear_secrets() -> None:
    """Testlar uchun: ro'yxatni tozalaydi."""
    with _lock:
        _secrets.clear()


def _known_secrets() -> list[tuple[str, str]]:
    with _lock:
        items = list(_secrets.items())
    # Uzun qiymatlar birinchi almashtiriladi (ichma-ich qiymatlar uchun).
    items.sort(key=lambda kv: len(kv[0]), reverse=True)
    return items


# ──────────────────────────────────────────────────────────────
# MATN TOZALASH
# ──────────────────────────────────────────────────────────────

def mask_card_number(value) -> str:
    """Karta raqamini niqoblaydi: faqat oxirgi 4 xona saqlanadi.

    Masalan: ``8600060950825589`` → ``**** **** **** 5589``.
    Karta bo'lmasa — qiymat o'zgarishsiz qaytadi.
    """
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if not (13 <= len(digits) <= 19):
        return text
    return "**** **** **** " + digits[-4:]


def scrub_text(text: str) -> str:
    """Matn ichidagi barcha sezgir ma'lumotlarni o'chiradi."""
    if not text or not isinstance(text, str):
        return text

    # 1) Ro'yxatdagi aniq qiymatlar.
    for secret, label in _known_secrets():
        if secret and secret in text:
            text = text.replace(secret, f"{REDACTED}:{label}")

    # 2) DB URL parollari.
    text = _DB_PASSWORD_RE.sub(r"\1://\2:" + REDACTED + "@", text)

    # 3) Bot tokenlari.
    text = _BOT_TOKEN_RE.sub(REDACTED_TOKEN, text)

    # 4) Karta raqamlari (guruhlangan va uzluksiz).
    text = _CARD_GROUPED_RE.sub(REDACTED_CARD, text)
    text = _CARD_PLAIN_RE.sub(REDACTED_CARD, text)

    # 5) Ma'lum API kalit formatlari.
    text = _API_KEY_RE.sub(REDACTED, text)

    return text


# ──────────────────────────────────────────────────────────────
# TARKIBIY QIYMATLARNI TOZALASH (dict / list / str)
# ──────────────────────────────────────────────────────────────

_MAX_DEPTH = 12


def _is_sensitive_key(key) -> bool:
    try:
        return str(key).lower().strip() in SENSITIVE_KEYS
    except Exception:
        return False


def scrub_value(value, _depth: int = 0):
    """Ixtiyoriy Python qiymatini chuqurlik bo'yicha tozalaydi."""
    if _depth > _MAX_DEPTH:
        return REDACTED

    if isinstance(value, str):
        return scrub_text(value)

    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                clean[key] = REDACTED
            else:
                clean[key] = scrub_value(item, _depth + 1)
        return clean

    if isinstance(value, (list, tuple)):
        cleaned = [scrub_value(item, _depth + 1) for item in value]
        return cleaned if isinstance(value, list) else tuple(cleaned)

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    # Boshqa obyektlar — repr orqali matn qilib tozalanadi.
    try:
        return scrub_text(repr(value))
    except Exception:
        return REDACTED


# ──────────────────────────────────────────────────────────────
# SENTRY EVENT FILTRI (before_send)
# ──────────────────────────────────────────────────────────────

#: Event ichidan tozalanadigan asosiy bo'limlar.
_EVENT_SECTIONS = (
    "message", "logentry", "transaction", "environment", "release",
    "server_name", "fingerprint",
)


def scrub_event(event, hint=None):
    """``sentry_sdk`` ``before_send`` callback'i.

    Event'dagi barcha matn/ma'lumotlarni tozalaydi. Hech qachon istisno
    ko'tarmaydi — filtrning o'zi xato bersa event o'chiriladi (xavfsiz tomon).
    Qaytadi: tozalangan event (yoki istisnoda ``None`` — yuborilmaydi).
    """
    try:
        if not isinstance(event, dict):
            return event

        # Oddiy maydonlar.
        for section in _EVENT_SECTIONS:
            if section in event:
                event[section] = scrub_value(event[section])

        # HTTP so'rov ma'lumotlari (header/cookie/data).
        request = event.get("request")
        if isinstance(request, dict):
            event["request"] = scrub_value(request)

        # Foydalanuvchi ma'lumotlari (PII minimalizatsiyasi).
        user = event.get("user")
        if isinstance(user, dict):
            event["user"] = {
                "id": user.get("id"),
            }

        # Istisno frame'lari (lokal o'zgaruvchilar).
        exception = event.get("exception")
        if isinstance(exception, dict):
            for value in exception.get("values") or ():
                if not isinstance(value, dict):
                    continue
                value["value"] = scrub_value(value.get("value"))
                stacktrace = value.get("stacktrace") or {}
                for frame in stacktrace.get("frames") or ():
                    if isinstance(frame, dict) and "vars" in frame:
                        frame["vars"] = scrub_value(frame.get("vars"))

        # Breadcrumbs, extra, contexts, tags.
        for key in ("breadcrumbs", "extra", "contexts", "tags", "modules"):
            if key in event:
                event[key] = scrub_value(event[key])

        return event
    except Exception:
        # Xavfsiz tomon: filtr ishlamasa event umuman yuborilmaydi.
        return None


# ──────────────────────────────────────────────────────────────
# STDLIB LOGGING FILTRI (11-bosqich, P0 — qat'iy log scrubbing)
# ──────────────────────────────────────────────────────────────
#
# Sentry'dan tashqari ODDIY loglar (stdout/fayl) ham tozalanadi: bot token,
# DB paroli (URL ichida), to'liq karta raqamlari va API kalitlar
# ``[REDACTED...]`` bilan almashtiriladi. Filtr root logger'ning barcha
# handler'lariga va root'ning o'ziga o'rnatiladi — keyin qo'shilgan
# handler'lar uchun ``install_logging_scrubber()`` qayta chaqirilishi mumkin
# (idempotent).

import logging as _logging


class SecretScrubbingFilter(_logging.Filter):
    """LogRecord xabari, argumentlari va istisno matnini tozalaydi."""

    def filter(self, record: _logging.LogRecord) -> bool:  # noqa: A003
        try:
            if isinstance(record.msg, str):
                record.msg = scrub_text(record.msg)
            elif record.msg is not None and not isinstance(record.msg, (int, float)):
                record.msg = scrub_text(str(record.msg))
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: scrub_value(v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_scrub_arg(a) for a in record.args)
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                try:
                    new_args = tuple(_scrub_arg(a) for a in exc.args)
                    if new_args != exc.args:
                        exc.args = new_args
                except Exception:
                    pass
            if getattr(record, "exc_text", None):
                record.exc_text = scrub_text(record.exc_text)
        except Exception:
            # Filtr HECH QACHON logni yiqitmasin.
            pass
        return True


def _scrub_arg(value):
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, (dict, list, tuple)):
        return scrub_value(value)
    if isinstance(value, BaseException):
        try:
            value.args = tuple(_scrub_arg(a) for a in value.args)
        except Exception:
            pass
        return value
    return value


_LOG_FILTER = SecretScrubbingFilter("secret_scrubber")


def install_logging_scrubber(logger_obj: _logging.Logger = None) -> _logging.Filter:
    """Filtrni root (yoki berilgan) logger va uning handler'lariga o'rnatadi."""
    target = logger_obj or _logging.getLogger()
    if _LOG_FILTER not in target.filters:
        target.addFilter(_LOG_FILTER)
    for handler in list(target.handlers):
        if _LOG_FILTER not in handler.filters:
            handler.addFilter(_LOG_FILTER)
    return _LOG_FILTER


def scrub_log_line(text: str) -> str:
    """Tayyor log satrini tozalash (tashqi log yozuvchilar uchun)."""
    return scrub_text(text)
