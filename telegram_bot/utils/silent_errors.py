# -*- coding: utf-8 -*-
"""🔇➡️📢 SILENT ERROR ERADICATION — jimgina yutilgan xatolar uchun yagona jurnal nuqtasi.

SPRINT 1 (P0 barqarorlik) talabi
--------------------------------
Loyihada ~470 ta ``except ...: pass`` bloki bor edi. Ular nosozlikni
foydalanuvchidan yashirardi — bu qisman to'g'ri (foydalanuvchi ichki
xatoni ko'rmasligi kerak), lekin xato **butunlay ko'rinmas** bo'lib
qolardi: na logda, na Sentry'da iz qolardi. Natijada:
  * to'lov/scheduler/DB/AI qatlamidagi real nosozliklar sezilmay o'tardi;
  * "ishlayapti" degan taassurot saqlanib, ma'lumot yo'qolardi;
  * incidentni qayta tiklash imkonsiz edi.

Bu modul o'sha bloklar uchun yagona, **structured** jurnal nuqtasini
beradi. ``except ...: pass`` o'rniga endi quyidagi ko'rinishdagi chaqiruv
turadi::

    try:
        ...
    except Exception as _silent_exc:
        log_silent_failure(
            "handlers.channels:refresh_stats", _silent_exc,
            user_id=user_id, channel_id=channel_id,
        )

Xulq-atvor kafolatlari
----------------------
1. **Funksional o'zgarish yo'q** — xato avvalgidek yutiladi (handler
   yiqilmaydi, foydalanuvchi xavfsiz ekran ko'radi). Faqat jurnal qo'shiladi.
2. **Kontekst** — ``user_id``, ``channel_id``, ``chat_id``, ``post_id``,
   ``job_id``, ``payment_id``, ``correlation_id`` kabi maydonlar log
   yozuviga struktur ravishda (``logger.*(..., extra={...})``) qo'shiladi.
   Noma'lum/bo'sh maydonlar tashlab yuboriladi; qiymatlar qisqartiriladi.
3. **Rate-limit / takrorlanish** — bir xil ``(action, xato turi)`` juftligi
   uchun birinchi nosozlik ``WARNING``/``ERROR`` darajasida to'liq kontekst
   bilan yoziladi; keyingi takrorlar ``DEBUG`` darajasiga tushadi
   (log flood bo'lmaydi, lekin hech narsa yo'qolmaydi) va sanog'i oshadi.
4. **Sentry** — ``ERROR`` darajasidagi nosozliklar (to'lov, DB, AI,
   scheduler, delivery) ``sentry_sdk.capture_exception`` orqali yuboriladi.
   SDK o'rnatilmagan yoki DSN yo'q bo'lsa — jim o'tkazib yuboriladi
   (bu modul hech qachon o'zi xato ko'tarmaydi).
5. **Hech qachon raise qilmaydi** — jurnal yozishning o'zi ilovani
   yiqitmasligi kerak (masalan, log handler Exception ko'tarsa).

Foydalanish
-----------
::

    from utils.silent_errors import log_silent_failure

    except ValueError as _silent_exc:
        log_silent_failure("services.payment_service:parse_amount", _silent_exc)

Darajani tanlash (transformator ham shu qoidaga amal qiladi):

  * ``logging.ERROR`` — pul, ma'lumot butunligi va yetkazib berish zanjiri
    (``payments``, ``database``/``repositories``, ``scheduler``,
    ``services/delivery``, ``services/ai*``);
  * ``logging.WARNING`` — foydalanuvchi oqimining qolgan qismi;
  * ``logging.DEBUG`` — ixtiyoriy import/reflection kabi "kutilgan"
    yo'qotishlar (``ImportError``/``AttributeError``).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Mapping

__all__ = [
    "CONTEXT_FIELDS",
    "log_silent_failure",
    "silent_error_stats",
    "reset_silent_error_stats",
]

logger = logging.getLogger("silent_errors")

#: Jurnalga tushadigan (va Sentry'ga "extra" bo'lib ketadigan) kontekst
#: maydonlari. Boshqa kalitlar ham qabul qilinadi, lekin faqat shu
#: ro'yxatdagi nomlar PII xavfi yo'q deb hisoblanadi — boshqalari
#: ``extra`` ichiga baribir qisqartirilgan holda yoziladi.
CONTEXT_FIELDS = (
    "action",
    "user_id",
    "channel_id",
    "chat_id",
    "post_id",
    "job_id",
    "payment_id",
    "order_id",
    "receipt_id",
    "ticket_id",
    "source_id",
    "correlation_id",
    "request_id",
    "update_id",
    "lang",
    "provider",
    "platform",
    "stage",
)

#: Bitta maydon qiymatining maksimal uzunligi (log injection / PII
#: sizib chiqishini cheklash uchun).
_MAX_VALUE_LEN = 120
#: Xato matnining maksimal uzunligi.
_MAX_EXC_LEN = 300
#: Bir xil nosozlik ``WARNING`` darajasida necha marta takrorlanadi.
_FULL_LOG_LIMIT = 3
#: Takrorlanish oynasi (soniya) — shu vaqt ichida sanoq yig'iladi.
_DEDUP_WINDOW_SEC = 300.0
#: Statistika lug'atining maksimal hajmi (uzoq ishlaydigan process uchun).
_MAX_TRACKED_KEYS = 4096

_LOCK = threading.RLock()
_seen: dict[tuple[str, str], dict[str, Any]] = {}


def _shorten(value: Any, limit: int = _MAX_VALUE_LEN) -> str:
    """Qiymatni xavfsiz, qisqa matnga aylantiradi (hech qachon raise qilmaydi)."""
    try:
        text = value if isinstance(value, str) else repr(value)
    except Exception:  # pragma: no cover — repr() buzilgan obyekt
        return "<unrepr-able>"
    text = text.replace("\n", " ").replace("\r", " ").strip()
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _exc_summary(exc: BaseException | None) -> str:
    """``ValueError: msg`` ko'rinishidagi qisqa xato tavsifi."""
    if exc is None:
        return "unknown-error"
    try:
        name = type(exc).__name__
        message = str(exc)
    except Exception:  # pragma: no cover — buzuq __str__
        return "unknown-error"
    if not message:
        return name
    return f"{name}: {_shorten(message, _MAX_EXC_LEN)}"


def _exc_type_name(exc: BaseException | None) -> str:
    try:
        return type(exc).__name__ if exc is not None else "UnknownError"
    except Exception:  # pragma: no cover
        return "UnknownError"


def _clean_context(context: Mapping[str, Any]) -> dict[str, str]:
    """Faqat mazmunli (None bo'lmagan, bo'sh bo'lmagan) maydonlarni qoldiradi."""
    cleaned: dict[str, str] = {}
    for key, value in context.items():
        if value is None or value == "":
            continue
        try:
            if isinstance(value, bool):
                cleaned[key] = "1" if value else "0"
            elif isinstance(value, (int, float)):
                cleaned[key] = str(value)
            else:
                text = str(value).strip()
                if not text:
                    continue
                cleaned[key] = _shorten(text)
        except Exception:  # pragma: no cover — buzuq __str__
            continue
    return cleaned


def _register(action: str, exc: BaseException | None) -> tuple[int, int, dict[str, Any]]:
    """Takrorlanishni qayd etadi.

    Qaytaradi: ``(occurrences, repeats_in_window, key_state)``.
    """
    key = (action, _exc_type_name(exc))
    now = time.monotonic()
    with _LOCK:
        state = _seen.get(key)
        if state is None or (now - state["last"]) > _DEDUP_WINDOW_SEC:
            state = {"count": 0, "total": 0, "first": now, "last": now}
            if len(_seen) >= _MAX_TRACKED_KEYS:
                # Eng eski yozuvni bo'shatamiz — xotira chegarasi.
                oldest = min(_seen, key=lambda item: _seen[item]["last"])
                _seen.pop(oldest, None)
            _seen[key] = state
        state["count"] += 1
        state["total"] += 1
        state["last"] = now
        return state["count"], state["total"], dict(state)


def _capture_to_sentry(exc: BaseException | None, extra: dict[str, Any]) -> None:
    """Sentry'ga yuborish — SDK/DSN bo'lmasa jimgina o'tkazib yuboriladi."""
    if exc is None:
        return
    try:
        import sentry_sdk  # lokal import: ixtiyoriy qaramlik

        sentry_sdk.capture_exception(exc)
        return
    except Exception as sentry_exc:  # noqa: BLE001 — monitoring hech qachon oqimni buzmaydi
        # MUHIM: bu yer ``pass`` emas — muammo DEBUG darajasida ko'rinadi.
        logger.debug(
            "Sentry capture o'tkazib yuborildi: %s (action=%s)",
            _exc_summary(sentry_exc), extra.get("action", "?"),
        )


def log_silent_failure(
    action: str,
    exc: BaseException | None = None,
    *,
    level: int = logging.WARNING,
    expected: bool = False,
    capture: bool | None = None,
    **context: Any,
) -> None:
    """Yutilgan xatoni structured jurnalga yozadi.

    Parametrlar:
        action:  amal nomi (``"handlers.channels:refresh_stats"`` ko'rinishida).
        exc:     tutilgan xato obyekti (``except ... as _silent_exc``).
        level:   ``logging.WARNING`` (standart) yoki ``logging.ERROR``.
        expected: ``True`` bo'lsa daraja ``DEBUG`` ga tushiriladi — masalan,
                 ixtiyoriy import yoki "hali ma'lumot yo'q" holatlari.
        capture: Sentry'ga yuborishni majburan yoqish/o'chirish.
        **context: ``user_id``, ``channel_id``, ``correlation_id`` kabi
                 kontekst maydonlari (qisqartirilib, ``extra`` ga qo'shiladi).

    Qaytaradi: ``None``. **Hech qachon raise qilmaydi.**
    """
    try:
        name = action or "unknown"
        if expected:
            level = logging.DEBUG

        occurrences, total, state = _register(name, exc)

        extra = _clean_context(context)
        extra["action"] = name
        if exc is not None:
            extra["error_type"] = _exc_type_name(exc)
        if occurrences > 1:
            extra["repeat_count"] = occurrences
            extra["total_count"] = total

        summary = _exc_summary(exc)
        message = "[silent-error] %s → %s" % (name, summary)

        if occurrences > _FULL_LOG_LIMIT:
            # Log flood'dan himoya: birinchi bir nechtasi to'liq yozildi,
            # qolganlari DEBUG darajasida (sanoq bilan) davom etadi.
            logger.debug(
                "%s (takror #%d)", message, occurrences,
                exc_info=False, extra=extra, stacklevel=2,
            )
            return

        logger.log(
            level,
            "%s", message,
            exc_info=(level >= logging.ERROR) or occurrences == 1,
            extra=extra,
            stacklevel=2,
        )

        should_capture = capture
        if should_capture is None:
            should_capture = level >= logging.ERROR
        if should_capture and occurrences <= _FULL_LOG_LIMIT:
            _capture_to_sentry(exc, extra)
    except Exception as logging_exc:  # noqa: BLE001 — jurnal yozish ilovani yiqitmasligi shart
        # Fallback: hech bo'lmasa standart logger orqali iz qoldiramiz.
        try:
            logging.getLogger(__name__).debug(
                "log_silent_failure o'zi xato berdi: %r", logging_exc,
            )
        except Exception:  # pragma: no cover — logging butunlay buzuq
            return


def silent_error_stats() -> dict[str, int]:
    """Joriy processdagi yutilgan xatolar statistikasi (testlar/monitoring uchun).

    Kalit — ``"action|XatoTuri"``, qiymat — umumiy takrorlanish soni.
    """
    with _LOCK:
        return {f"{action}|{exc_type}": int(state["total"])
                for (action, exc_type), state in _seen.items()}


def reset_silent_error_stats() -> None:
    """Statistikani tozalaydi (testlar orasida izolyatsiya uchun)."""
    with _LOCK:
        _seen.clear()
