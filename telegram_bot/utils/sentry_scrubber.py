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

import json
import re
import threading
from datetime import datetime, timezone

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
    "SecretScrubbingFilter",
    "JsonLogFormatter",
    "install_logging_scrubber",
    "configure_structured_logging",
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

# Telegram bot token: 123456789:AA... (8-10 xona + ':' + 30+ belgi).
# \b ATAYLAB YO'Q: URL ichidagi token (.../bot123456789:AA.../getUpdates)
# oldida harf tursa yoki token '-'/'_' bilan tugasa \b mos kelmaydi va
# token log/Sentry'da ochiq qolar edi; chegara belgilarisiz regex har qanday
# matn ichidagi tokenni (bot<token> shaklini ham) ushlaydi.
_BOT_TOKEN_RE = re.compile(r"\d{8,10}:[A-Za-z0-9_-]{30,64}")

# DB/broker URL'laridagi to'liq credential bo'lagi. Username ham identifikator
# bo'lishi mumkin; production loglarda butun user:password qismi yashiriladi.
_DB_PASSWORD_RE = re.compile(
    r"(?i)\b(postgres(?:ql)?|mysql|redis|rediss|amqp|amqps|"
    r"mongodb(?:\+srv)?)://[^/@\s]+(?::[^/@\s]*)?@"
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
    r"sk-or-v1-[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9_-]{20,}|"
    r"AKIA[0-9A-Z]{16})\b"
)

# Matnli log ichiga tasodifan qo'shilgan .env/JSON/query parametrlari.
# Qiymat vergul, ampersand, whitespace yoki yopuvchi JSON belgigacha kesiladi.
_SECRET_ASSIGNMENT_KEY = (
    r"(?:password|passwd|pwd|secret|token|"
    r"(?:[a-z0-9_-]+[_-])?api[_-]?key|authorization|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|private[_-]?key|"
    r"payment[_-]?(?:details|payload|id|order[_-]?id|receipt[_-]?id|charge[_-]?id)|"
    r"telegram[_-]?payment[_-]?charge[_-]?id|provider[_-]?payment[_-]?charge[_-]?id|"
    r"credit[_-]?card|card[_-]?(?:number|holder|details)|"
    r"pan|cvv2?|cvc|iban|account[_-]?number)"
)
_QUOTED_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<prefix>['\"]?" + _SECRET_ASSIGNMENT_KEY
    + r"['\"]?\s*[:=]\s*)(?P<quote>['\"])(?!\[REDACTED\b)(?P<value>.*?)(?P=quote)"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)(?P<prefix>['\"]?" + _SECRET_ASSIGNMENT_KEY
    + r"['\"]?\s*[:=]\s*)(?!['\"]|\[REDACTED\b)(?P<value>[^\s&;,\"'\]}]+)"
)
_BEARER_RE = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/-]{8,}={0,2}")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
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
    "card", "card_number", "cardnumber", "card_holder", "cardholder",
    "card_details", "credit_card", "payment_details", "payment_payload",
    "payment_id", "payment_order_id", "payment_receipt_id", "charge_id",
    "telegram_payment_charge_id", "provider_payment_charge_id", "receipt_id",
    "receipt_file_id", "invoice_payload", "order_id", "pan", "cvv", "cvv2",
    "cvc", "iban", "account_number", "bank_account", "dsn", "database_url",
    "connection_string", "private_key", "credential", "credentials",
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

    # 2) DB/broker URL credentiallari (username + parol).
    text = _DB_PASSWORD_RE.sub(r"\1://[REDACTED]@", text)

    # 3) Payment PAN raqamlarini assignment'dan OLDIN yutib olamiz — aks
    # holda whitespace bilan guruhlangan karta raqami bo'laklarga ajralardi.
    text = _CARD_GROUPED_RE.sub(REDACTED_CARD, text)
    text = _CARD_PLAIN_RE.sub(REDACTED_CARD, text)

    # 4) Bot tokenni umumiy ``token=...`` assignment'dan OLDIN aniqlaymiz,
    # maxsus BOT_TOKEN markerini saqlash uchun.
    text = _BOT_TOKEN_RE.sub(REDACTED_TOKEN, text)

    # 5) .env/JSON/query-string ko'rinishida yozilib qolgan maxfiy qiymatlar.
    text = _QUOTED_SECRET_ASSIGNMENT_RE.sub(
        lambda match: (match.group("prefix") + match.group("quote")
                       + REDACTED + match.group("quote")), text
    )
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: match.group("prefix") + REDACTED, text
    )
    text = _BEARER_RE.sub(r"\1" + REDACTED, text)
    text = _PRIVATE_KEY_RE.sub(REDACTED, text)

    # 6) Karta raqamlariga ikkinchi himoya o'tishi.
    text = _CARD_GROUPED_RE.sub(REDACTED_CARD, text)
    text = _CARD_PLAIN_RE.sub(REDACTED_CARD, text)

    # 7) Ma'lum API kalit formatlari.
    text = _API_KEY_RE.sub(REDACTED, text)

    return text


# ──────────────────────────────────────────────────────────────
# TARKIBIY QIYMATLARNI TOZALASH (dict / list / str)
# ──────────────────────────────────────────────────────────────

_MAX_DEPTH = 12


def _is_sensitive_key(key) -> bool:
    """Dictionary/log field nomidagi secretlarni aniq va kompozit ko'rinishda topadi."""
    try:
        raw = str(key).lower().strip()
        normalized = re.sub(r"[^a-z0-9]+", "_", raw).strip("_")
        if raw in SENSITIVE_KEYS or normalized in SENSITIVE_KEYS:
            return True
        # ``openai_api_key``, ``gemini_access_token`` va shunga o'xshash
        # vendor-prefiksli maydonlar ham kalit bo'yicha tozalanadi.
        return any(marker in normalized for marker in (
            "password", "passwd", "secret", "token", "api_key",
            "authorization", "private_key", "credential", "card_number",
            "card_holder", "payment_details", "payment_payload", "payment_id",
            "charge_id", "receipt_id", "invoice_payload", "order_id",
            "account_number", "bank_account",
        )) or normalized in {"pan", "cvv", "cvv2", "cvc", "iban", "card"}
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

_STANDARD_LOG_RECORD_FIELDS = frozenset(
    set(_logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
    | {"message", "asctime"}
)


class SecretScrubbingFilter(_logging.Filter):
    """LogRecord xabari, argumentlari, konteksti va istisno matnini tozalaydi."""

    def filter(self, record: _logging.LogRecord) -> bool:  # noqa: A003
        try:
            # First scrub arguments by structure, then render the message and
            # scrub the final text. Scrubbing ``token=%s`` in the template
            # before %-formatting would consume a placeholder and trigger a
            # logging formatting error (and could silently drop the event).
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: scrub_value(v) for k, v in record.args.items()}
                elif isinstance(record.args, tuple):
                    record.args = tuple(_scrub_arg(a) for a in record.args)
            try:
                rendered_message = record.getMessage()
            except Exception:
                rendered_message = str(record.msg)
            record.msg = scrub_text(str(rendered_message))
            record.args = ()
            if record.exc_info and record.exc_info[1] is not None:
                exc = record.exc_info[1]
                try:
                    exc.args = tuple(_scrub_arg(a) for a in exc.args)
                except Exception:
                    pass
            if getattr(record, "exc_text", None):
                record.exc_text = scrub_text(record.exc_text)

            # logger.info(..., extra={...}) orqali uzatilgan barcha maydonlar
            # ham JSON formatterga yetib borishdan oldin tozalanadi.
            for key, value in tuple(record.__dict__.items()):
                if key in _STANDARD_LOG_RECORD_FIELDS or key.startswith("_"):
                    continue
                record.__dict__[key] = (
                    REDACTED if _is_sensitive_key(key) else scrub_value(value)
                )
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


def _iter_loggers(logger_obj=None):
    if logger_obj is not None:
        yield logger_obj
        return
    yield _logging.getLogger()
    for candidate in _logging.Logger.manager.loggerDict.values():
        if isinstance(candidate, _logging.Logger):
            yield candidate


def install_logging_scrubber(logger_obj: _logging.Logger = None) -> _logging.Filter:
    """Maxfiylik filtrini root/child loggerlar va mavjud handlerlarga o'rnatadi.

    Handler darajasidagi filter muhim: log record'lar child loggerdan root'ga
    propagate qilganda root loggerning filteri qayta ishlamasligi mumkin.
    """
    for target in _iter_loggers(logger_obj):
        if _LOG_FILTER not in target.filters:
            target.addFilter(_LOG_FILTER)
        for handler in list(target.handlers):
            if _LOG_FILTER not in handler.filters:
                handler.addFilter(_LOG_FILTER)
    return _LOG_FILTER


class JsonLogFormatter(_logging.Formatter):
    """Har bir LogRecord uchun maxfiylikdan o'tgan, bir qatorli JSON yozuv."""

    def format(self, record: _logging.LogRecord) -> str:
        now = datetime.fromtimestamp(record.created, tz=timezone.utc)
        timestamp = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        try:
            message = record.getMessage()
        except Exception:
            message = "[log message unavailable]"
        message = scrub_text(str(message))

        embedded = None
        marker = "[BOT_ERROR] "
        if message.startswith(marker):
            try:
                candidate = json.loads(message[len(marker):])
                if isinstance(candidate, dict):
                    embedded = candidate
            except Exception:
                embedded = None

        raw_event = getattr(record, "event", None)
        if raw_event is None and embedded:
            raw_event = embedded.get("event")
        event = raw_event if isinstance(raw_event, str) else message
        event = scrub_text(str(event))

        user_id = getattr(record, "user_id", None)
        channel_id = getattr(record, "channel_id", None)
        latency_ms = getattr(record, "latency_ms", None)
        error_code = getattr(record, "error_code", None)
        if embedded:
            user_id = user_id if user_id is not None else embedded.get("user_id")
            channel_id = channel_id if channel_id is not None else embedded.get("channel_id")
            latency_ms = latency_ms if latency_ms is not None else embedded.get("latency_ms")
            error_code = error_code or embedded.get("error_code") or embedded.get("exception_type")
        if error_code is None and record.exc_info and record.exc_info[1] is not None:
            error_code = type(record.exc_info[1]).__name__

        payload = {
            "timestamp": timestamp,
            "level": record.levelname,
            "event": event,
            "user_id": scrub_value(user_id),
            "channel_id": scrub_value(channel_id),
            "latency_ms": scrub_value(latency_ms),
            "error_code": scrub_value(error_code),
            "logger": record.name,
        }

        context = {}
        reserved = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "asctime", "user_id", "channel_id", "latency_ms", "error_code",
            "event",
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_LOG_RECORD_FIELDS and key not in reserved and not key.startswith("_"):
                context[key] = REDACTED if _is_sensitive_key(key) else scrub_value(value)
        if embedded:
            context["error"] = scrub_value(embedded)
        if context:
            payload["context"] = context
        if record.exc_info:
            try:
                payload["stack_trace"] = scrub_text(self.formatException(record.exc_info))
            except Exception:
                payload["stack_trace"] = "[REDACTED]"
        elif record.stack_info:
            payload["stack_trace"] = scrub_text(self.formatStack(record.stack_info))

        try:
            return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception:
            return json.dumps({
                "timestamp": timestamp, "level": "ERROR", "event": "log_format_error",
                "user_id": None, "channel_id": None, "latency_ms": None,
                "error_code": "LOG_FORMAT_ERROR",
            }, separators=(",", ":"))


def configure_structured_logging(level: int = _logging.INFO,
                                 logger_obj: _logging.Logger = None):
    """Markaziy stdout loggerini JSON Lines + secrets scrubber bilan sozlaydi."""
    target = logger_obj or _logging.getLogger()
    if not target.handlers:
        target.addHandler(_logging.StreamHandler())
    target.setLevel(level)
    install_logging_scrubber(target if logger_obj is not None else None)
    for owner in _iter_loggers(target if logger_obj is not None else None):
        for handler in list(owner.handlers):
            handler.setFormatter(JsonLogFormatter())
            if _LOG_FILTER not in handler.filters:
                handler.addFilter(_LOG_FILTER)
    return target


def scrub_log_line(text: str) -> str:
    """Tayyor log satrini tozalash (tashqi log yozuvchilar uchun)."""
    return scrub_text(text)
