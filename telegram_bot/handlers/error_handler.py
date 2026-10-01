"""Global universal error handler — PostAssist V2 (7-BOSQICH).

Telegram ``telegram.ext`` uchun YAGONA markazlashtirilgan xato ushlagich.
Kafolotlar:

1. **Foydalanuvchiga HECH QACHON Python traceback, SQL xatosi yoki ichki
   xatolik tafsilotlari ko'rsatilmaydi** — faqat foydalanuvchi tilida
   (uz/ru/en) qisqa, xushmuomala xabar yuboriladi.
2. **Xatolikning to'liq tafsiloti** (user_id, chat_id, handler_name,
   exception turi, xabar, traceback) ``logger.error`` orqali STRUCTURED
   (JSON qator) formatida qayd etiladi — Sentry/SIEM uchun ham mos.
3. **Kritik xatolar** (DB down, ulanish uzilishi, timeout) logda
   ``[CRITICAL_HEALTH]`` belgisi bilan AJRATIB ko'rsatiladi va best-effort
   admin audit jurnaliga (``admin_audit_logs``) ham yoziladi — DB turgan
   holdagi kritik xatolar uchun. DB o'zi yiqilganda audit yozuvi tabiiiy
   bajarilmaydi (jim o'tkaziladi) — o'sha holatda ham log + Sentry ishlaydi.
4. **Handler hech qachon o'zi istisno ko'tarmaydi** — eng ichki
   ``try/except`` bilan himoyalangan, aks holda PTB xato halqasiga tushadi.

Statistika: oxirgi 1 soat / 24 soatdagi xatolar soni xotirada (deque,
cheklangan) saqlanadi — ``/health`` hisobotida ko'rsatiladi.

Foydalanish (``main.py``)::

    from handlers.error_handler import register_error_handlers
    register_error_handlers(application)
"""

from __future__ import annotations

import json
import logging
import re
import time
import traceback
from collections import deque
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:  # psycopg2 doim mavjud (requirements), lekin himoyalangan import
    import psycopg2
except ImportError:  # pragma: no cover
    psycopg2 = None

# ──────────────────────────────────────────────────────────────
# KRITIK XATO ANIQLASH
# ──────────────────────────────────────────────────────────────
#: Kritik = botning asosiy infratuzilmasi (DB / tarmoq) ishlamayotgani.
_CRITICAL_EXCEPTION_TYPES: tuple = (TimeoutError, ConnectionError, OSError)

#: Kritik DB istisnolari (psycopg2).
_DB_EXCEPTION_TYPES: tuple = (
    (psycopg2.OperationalError, psycopg2.InterfaceError)
    if psycopg2 is not None else ()
)

#: Xato matni bo'yicha DB/tarmoq muammosi belgilari (kichik harflarda).
_DB_ERROR_MARKERS = (
    "connection refused",
    "connection reset",
    "connection timed out",
    "could not connect",
    "server closed the connection",
    "terminating connection",
    "connection already closed",
    "ssl connection has been closed",
    "no route to host",
    "name or service not known",
    "temporary failure in name resolution",
    "out of memory",
    "too many connections",
    "remaining connection slots",
)

_MARKET_RE = re.compile("|".join(re.escape(m) for m in _DB_ERROR_MARKERS))


def classify_error(error) -> str:
    """Xatoni ``"critical"`` yoki ``"normal"`` deb tasniflaydi.

    Kritik: DB OperationalError/InterfaceError, timeout/connection
    xatolari yoki xato matnida DB ulanish belgilari.
    """
    if error is None:
        return "normal"
    if _DB_EXCEPTION_TYPES and isinstance(error, _DB_EXCEPTION_TYPES):
        return "critical"
    if isinstance(error, _CRITICAL_EXCEPTION_TYPES):
        return "critical"
    try:
        text = str(error).lower()
    except Exception:
        return "normal"
    if text and _MARKET_RE.search(text):
        return "critical"
    return "normal"


# ──────────────────────────────────────────────────────────────
# STRUKTURALI MA'LUMOT AJRATISH
# ──────────────────────────────────────────────────────────────
_SAFE_TEXT_LIMIT = 300


def _safe_id(value) -> int | None:
    try:
        if isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_user_info(update) -> dict:
    """Update'dan user/chat ID (xavfsiz — hech narsa bo'lmasa bo'sh)."""
    info = {"user_id": None, "chat_id": None, "update_type": "unknown"}
    if update is None:
        return info
    try:
        user = getattr(update, "effective_user", None)
        if user is None:
            query = getattr(update, "callback_query", None)
            user = getattr(query, "from_user", None) if query else None
        info["user_id"] = _safe_id(getattr(user, "id", None))

        chat = getattr(update, "effective_chat", None)
        info["chat_id"] = _safe_id(getattr(chat, "id", None))

        if getattr(update, "callback_query", None) is not None:
            info["update_type"] = "callback_query"
        elif (getattr(update, "message", None) is not None
              or getattr(update, "effective_message", None) is not None):
            info["update_type"] = "message"
        elif getattr(update, "edited_message", None) is not None:
            info["update_type"] = "edited_message"
        elif getattr(update, "channel_post", None) is not None:
            info["update_type"] = "channel_post"
        elif getattr(update, "pre_checkout_query", None) is not None:
            info["update_type"] = "pre_checkout_query"
    except Exception:
        pass
    return info


def _extract_handler_name(context) -> str:
    """Xato traceback'idan bot handler'ining nomini aniqlaydi.

    Telegram/PTB doiralari tashlab ketilib, birinchi LOYIHA moduli
    (handlers/services/database/scheduler/utils) kadri topiladi.
    Topilmasa — ``"unknown"``.
    """
    error = getattr(context, "error", None)
    if error is None or not getattr(error, "__traceback__", None):
        return "unknown"
    project_roots = ("handlers.", "services.", "database", "scheduler", "utils.", "main")
    try:
        for frame, lineno in traceback.walk_tb(error.__traceback__):
            module = frame.f_globals.get("__name__", "")
            if any(module == root.rstrip(".") or module.startswith(root)
                   for root in project_roots):
                func = frame.f_code.co_name
                short = module.split(".")[-1] if module else module
                return f"{short}.{func}"
    except Exception:
        pass
    return "unknown"


def _extract_error_summary(error) -> dict:
    """Istisno turi va xavfsiz qisqa xabari (log uchun)."""
    if error is None:
        return {"type": "None", "message": ""}
    etype = type(error).__name__
    try:
        message = str(error)[:_SAFE_TEXT_LIMIT]
    except Exception:
        message = "<unprintable>"
    return {"type": etype, "message": message}


# ──────────────────────────────────────────────────────────────
# XATOLAR STATISTIKASI (/health uchun)
# ──────────────────────────────────────────────────────────────
_MAX_RECENT_ERRORS = 1000
_recent_errors: deque = deque(maxlen=_MAX_RECENT_ERRORS)
_total_errors = 0


def _record_error_stats(error, critical: bool, user_id) -> None:
    global _total_errors
    _total_errors += 1
    _recent_errors.append({
        "t": time.time(),
        "critical": bool(critical),
        "type": type(error).__name__ if error is not None else "None",
        "user_id": user_id,
    })


def _count_since(seconds: float) -> int:
    cutoff = time.time() - seconds
    return sum(1 for e in _recent_errors if e["t"] >= cutoff)


def get_error_stats() -> dict:
    """Xatolar statistikasi: jami, oxirgi 1 soat va 24 soat."""
    if not _recent_errors:
        return {"total": _total_errors, "last_hour": 0, "last_24h": 0,
                "critical_last_24h": 0}
    return {
        "total": _total_errors,
        "last_hour": _count_since(3600),
        "last_24h": _count_since(86400),
        "critical_last_24h": sum(1 for e in _recent_errors
                                 if e["t"] >= time.time() - 86400 and e["critical"]),
    }


def _reset_error_stats() -> None:
    """Faqat testlar uchun: statistikani tozalaydi."""
    global _total_errors
    _recent_errors.clear()
    _total_errors = 0


# ──────────────────────────────────────────────────────────────
# KRITIK XATO — AUDIT (best-effort)
# ──────────────────────────────────────────────────────────────
async def _audit_critical_error(user_id, summary: dict, handler_name: str) -> None:
    """Kritik xatoni admin audit jurnaliga yozadi (best-effort).

    ``admin_id`` talab qilinadi (audit sxemasi) — xatoni ko'rgan foydalanuvchi
    ID'si ishlatiladi. DB o'zi yiqilgan bo'lsa yozuv baribir bajarilmaydi —
    bunda [CRITICAL_HEALTH] log qatori + Sentry (sozlangan bo'lsa) ishlaydi.
    """
    if user_id is None:
        return
    try:
        from services.audit_service import AuditService
        await AuditService.log_action_async(
            user_id,
            "system_critical_error",
            target_type="system_health",
            target_id=handler_name[:64],
            new_value={
                "error_type": summary.get("type", "")[:64],
                "error_message": (summary.get("message") or "")[:500],
            },
        )
    except Exception as e:
        logger.error("[CRITICAL_HEALTH] audit yozuvi bajarilmadi: %s", e)


# ──────────────────────────────────────────────────────────────
# PHASE 9 — ERROR UX VA USER COMMUNICATION (ANIQ VA MULOYIM XABARLAR)
# ──────────────────────────────────────────────────────────────
_RAW_TECHNICAL_MARKERS = (
    "exception occurred",
    "traceback (most recent call last)",
    "unhandled exception",
    "psycopg2.",
    "operationalerror",
    "interfaceerror",
    "syntaxerror:",
    "keyerror:",
    "attributeerror:",
    "typeerror:",
    "valueerror:",
)

_AI_ERROR_MARKERS = (
    "openai",
    "gemini",
    "groq",
    "anthropic",
    "ai_service",
    "ai_chain",
    "ai busy",
    "ai_busy",
    "model overloaded",
    "rate_limit_exceeded",
    "insufficient_quota",
)

_FLOOD_ERROR_MARKERS = (
    "retryafter",
    "retry after",
    "flood control",
    "too many requests: retry after",
    "telegram_flood",
    "flood limit",
)

_URL_ERROR_MARKERS = (
    "urlsecurity",
    "safefetch",
    "url_security_gateway",
    "url_extractor",
    "ssrf",
    "invalid_url",
    "blocked_host",
    "blocked_scheme",
    "private_address",
    "url_error",
)


def classify_user_error_kind(error) -> str:
    """Foydalanuvchi UX uchun xato turini aniqlaydi (PHASE 9):

    - ``"ai_busy"``        → AI band / javob bermadi
    - ``"telegram_flood"`` → Telegram flood / RetryAfter
    - ``"url_error"``      → Havolani xavfsiz yuklab bo'lmadi
    - ``"general"``        → Boshqa xatolar (muloyim umumiy xabar)
    """
    if error is None:
        return "general"
    etype = type(error).__name__.lower()
    emod = (getattr(type(error), "__module__", "") or "").lower()
    try:
        emsg = str(error).lower()
    except Exception:
        emsg = ""
    combined = f"{etype} {emod} {emsg}"

    if etype == "retryafter" or any(m in combined for m in _FLOOD_ERROR_MARKERS):
        return "telegram_flood"
    if any(m in combined for m in _URL_ERROR_MARKERS):
        return "url_error"
    if any(m in combined for m in _AI_ERROR_MARKERS):
        return "ai_busy"
    return "general"


def format_user_error_message(error, lang: str | None = "uz") -> str:
    """Har bir xato uchun aniq, muloyim va harakatga yo'naltirilgan xabar (PHASE 9).

    Hech qachon texnik ``Exception occurred`` yoki stacktrace qaytarmaydi:
      - AI band bo'lsa: "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring."
      - Telegram flood bo'lsa: "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi."
      - URL xato bo'lsa: "Bu havolani xavfsiz yuklab bo‘lmadi."
    """
    kind = classify_user_error_kind(error)
    key_map = {
        "ai_busy": "err_ux_ai_busy",
        "telegram_flood": "err_ux_telegram_flood",
        "url_error": "err_ux_url_failed",
    }
    i18n_key = key_map.get(kind, "sys_unexpected_error")
    try:
        from locales.translations import get_text
        return get_text(i18n_key, lang or "uz")
    except Exception:
        if kind == "ai_busy":
            return "AI hozir band. 20 soniyadan keyin qayta urinib ko‘ring."
        if kind == "telegram_flood":
            return "Telegram tezlik limitini berdi. Xabaringiz navbatga qo‘yildi."
        if kind == "url_error":
            return "Bu havolani xavfsiz yuklab bo‘lmadi."
        return "⚠️ Xatolik yuz berdi. Iltimos, birozdan so'ng qayta urinib ko'ring."


def sanitize_user_error_text(text: str, lang: str | None = "uz") -> str:
    """Texnik 'Exception occurred' yoki traceback matnini muloyim xabar bilan almashtiradi."""
    raw = str(text or "").strip()
    lowered = raw.lower()
    if not raw or any(marker in lowered for marker in _RAW_TECHNICAL_MARKERS):
        return format_user_error_message(None, lang=lang)
    return raw


# ──────────────────────────────────────────────────────────────
# FOYDALANUVCHIGA XUSHMUOMALA XABAR (traceback'SIZ)
# ──────────────────────────────────────────────────────────────
async def _notify_user(update, context) -> None:
    """Foydalanuvchi tilida (uz/ru/en) qisqa xushmuomala xabar (best-effort)."""
    message = getattr(update, "effective_message", None) if update is not None else None
    query = getattr(update, "callback_query", None) if update is not None else None
    if message is None and query is None:
        return

    lang = None
    try:
        from locales.translations import get_lang
        lang = get_lang(context)
    except Exception:
        lang = None

    # Keshda til yo'q bo'lsa — DB'dan o'qishga urinamiz (DB yiqilgan bo'lsa jim).
    if not lang:
        try:
            from handlers.start import ensure_user_lang
            user = getattr(update, "effective_user", None)
            uid = _safe_id(getattr(user, "id", None))
            if uid:
                lang = await ensure_user_lang(context, uid)
        except Exception:
            lang = None

    error = getattr(context, "error", None) if context is not None else None
    text = sanitize_user_error_text(format_user_error_message(error, lang), lang=lang)

    if message is not None:
        try:
            await message.reply_text(text, parse_mode="HTML")
            return
        except Exception as e:
            # Masalan, chat o'chirilgan/BotBlocked — bu yerda hech narsa
            # qilinmaydi; asosiy vazifa (log) allaqachon bajarilgan.
            logger.debug("error_handler: foydalanuvchiga javob yuborilmadi: %s", e)
    if query is not None:
        # 🌐 Qisqa xato toast'i ham foydalanuvchi tilida (uz/ru/en).
        kind = classify_user_error_kind(error)
        if kind in ("ai_busy", "telegram_flood", "url_error"):
            short = text[:200]
        else:
            try:
                from locales.translations import get_text as _get_text
                short = _get_text("sys_error_short", lang)
            except Exception:
                short = "⚠️ Xatolik yuz berdi"
        try:
            await query.answer(short, show_alert=False)
        except TypeError:
            try:
                await query.answer(short)
            except Exception:
                pass
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────
# GLOBAL HANDLER
# ──────────────────────────────────────────────────────────────
async def global_error_handler(update, context) -> None:
    """PTB global xato ushlagichi — HECH QACHON istisno ko'tarmaydi.

    Tartib:
      1. update/error ma'lumotlarini xavfsiz ajratadi;
      2. to'liq tafsilotni STRUKTURALI (JSON) log qatorida yozadi
         (``exc_info`` bilan — to'liq traceback log faylida saqlanadi,
         lekin FOYDALANUVCHIGA hech qachon yuborilmaydi);
      3. kritik bo'lsa — ``[CRITICAL_HEALTH]`` bilan ajratadi va auditga
         yozadi (best-effort);
      4. foydalanuvchiga tilga mos xushmuomala xabar yuboradi.
    """
    try:
        error = getattr(context, "error", None)
        user_info = _extract_user_info(update)
        handler_name = _extract_handler_name(context)
        summary = _extract_error_summary(error)
        critical = classify_error(error) == "critical"

        # 1+2) Strukturalli log — har doim.
        structured = {
            "event": "bot_error",
            "severity": "critical" if critical else "error",
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "user_id": user_info.get("user_id"),
            "chat_id": user_info.get("chat_id"),
            "update_type": user_info.get("update_type"),
            "handler_name": handler_name,
            "exception_type": summary["type"],
            "exception_message": summary["message"],
        }
        logger.error(
            "[BOT_ERROR] %s",
            json.dumps(structured, ensure_ascii=False),
            exc_info=error,
        )

        _record_error_stats(error, critical, user_info.get("user_id"))

        # 3) Kritik xato — alohida ajratib ko'rsatiladi + audit.
        if critical:
            logger.critical(
                "[CRITICAL_HEALTH] Kritik tizim xatosi: %s | user=%s | handler=%s",
                summary["type"], user_info.get("user_id"), handler_name,
                exc_info=error,
            )
            await _audit_critical_error(
                user_info.get("user_id"), summary, handler_name
            )

        # 4) Foydalanuvchiga xavfsiz xushmuomala xabar (hech qanday
        #    traceback/SQL tafsiloti YO'Q).
        await _notify_user(update, context)
    except Exception:
        # Eng oxirgi himoya: error handler o'zi yiqilib botni to'xtatmasin.
        try:
            logger.exception("error_handler ichida kutilmagan xato")
        except Exception:
            pass


#: Qisqa alias (eski ``main.error_handler`` mos kelishi uchun).
error_handler = global_error_handler


def register_error_handlers(application) -> None:
    """``application.add_error_handler(global_error_handler)`` ni bajardi."""
    application.add_error_handler(global_error_handler)
