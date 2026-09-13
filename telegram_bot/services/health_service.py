"""HealthService — PostAssist V2 (7-BOSQICH): System Health Check.

Tizimning barcha asosiy komponentlarini bitta so'rovda tekshiradi va
adminlarga chiroyli, tilga mos (uz/ru/en) hisobot qaytaradi:

1. **Database**      — Neon DB ga oddiy ``SELECT 1`` ping + javob vaqti (ms)
                       va ulanishlar pool'i holati (``db.get_db_pool_status``).
2. **Scheduler**     — apscheduler ishlayotgani, faol joblar soni,
                       pending/processing/failed/stale postlar va
                       ``post_deliveries`` dagi ``failed`` / ``dead_letter``
                       soni (``db.get_post_health_counts``).
3. **AI provayderlar** — har bir kalit borligi, circuit-breaker (10 daqiqalik
                       o'tkazib yuborish) holati → OK / DEGRADED / UNCONFIGURED.
4. **Tizim**         — bot uptime, DB pool'dagi faol ulanishlar, asyncio
                       vazifalari va oxirgi 1 soat/24 soatdagi xatolar soni
                       (global error handler statistikasidan).
5. **Umumiy holat**  — ``HEALTHY`` / ``DEGRADED`` / ``UNHEALTHY``.

**Qat'iy qoida:** health tekshiruvi HECH QACHON istisno ko'tarmaydi va botning
asosiy ishini SEKINLASHTIRMAYDI — har bir komponent alohida
``try/except`` ichida, DB so'rovlari ``db.run_db`` (alohida thread) orqali.

**Umumiy holat qoidalari:**

* DB javob bermasa                                  → ``UNHEALTHY``;
* scheduler to'xtagan, dead-letter/failed postlar chegara
  oshsa, stale processing bo'lsa, asosiy (core) AI
  provayderlari hammasi ishlamasa/sozlanmagan bo'lsa → ``DEGRADED``;
* aks holda                                          → ``HEALTHY``.

Chegaralar muhit o'zgaruvchilari bilan sozlanadi:
``HEALTH_DEAD_LETTER_ALERT`` (default 1), ``HEALTH_FAILED_ALERT`` (10),
``HEALTH_PENDING_BACKLOG_ALERT`` (1000).

Foydalanish::

    from services.health_service import get_system_health, format_health_report

    health = await get_system_health()
    if health["status"] == "UNHEALTHY": ...
    text = await format_health_report(lang="uz")
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone

import database as db

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────
# HOLAT KONSTANTALARI
# ──────────────────────────────────────────────────────────────
STATUS_HEALTHY = "HEALTHY"
STATUS_DEGRADED = "DEGRADED"
STATUS_UNHEALTHY = "UNHEALTHY"

# Komponent darajasidagi holatlar
STATUS_OK = "OK"
STATUS_UNCONFIGURED = "UNCONFIGURED"
STATUS_UNKNOWN = "UNKNOWN"
STATUS_RUNNING = "RUNNING"
STATUS_STOPPED = "STOPPED"

#: Asosiy (core) AI provayderlar — 1..3-daraja zanjiri (Gemini → Groq →
#: OpenRouter). Ulardan KAMIDA BITTASI ishlashi botning AI imkoniyatlari
#: uchun yetarli; qolganlari (tier 4) ixtiyoriy zaxira.
CORE_TIERS = (1, 2, 3)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


#: Ogohlantirish chegaralari (env orqali sozlanadi).
DEAD_LETTER_ALERT_THRESHOLD = _env_int("HEALTH_DEAD_LETTER_ALERT", 1)
FAILED_ALERT_THRESHOLD = _env_int("HEALTH_FAILED_ALERT", 10)
PENDING_BACKLOG_ALERT = _env_int("HEALTH_PENDING_BACKLOG_ALERT", 1000)
#: Shuncha va undan ko'p ko'rib chiqilmagan chek → to'lovlar DEGRADED.
PENDING_RECEIPTS_ALERT = _env_int("HEALTH_PENDING_RECEIPTS_ALERT", 50)

#: Stale processing chegara sekundlarda — DB so'rovidagi 10 daqiqa bilan bir xil.
STALE_PROCESSING_THRESHOLD_SEC = 600


# ──────────────────────────────────────────────────────────────
# MODUL HOLATI (uptime / ro'yxatga olish)
# ──────────────────────────────────────────────────────────────
_START_MONOTONIC = time.monotonic()
_START_TIME_UTC = datetime.now(timezone.utc)
_registry_lock = threading.Lock()
_registered_scheduler = None
_registered_application = None


def mark_bot_started() -> None:
    """Bot to'liq ishga tushganda uptime hisobini nolga qaytaradi."""
    global _START_MONOTONIC, _START_TIME_UTC
    _START_MONOTONIC = time.monotonic()
    _START_TIME_UTC = datetime.now(timezone.utc)


def register_scheduler(scheduler) -> None:
    """``main()`` ichida AsyncIOScheduler instansiyasini ro'yxatga oladi."""
    global _registered_scheduler
    with _registry_lock:
        _registered_scheduler = scheduler


def register_application(application) -> None:
    """PTB ``Application`` instansiyasini ro'yxatga oladi (diagnostika uchun)."""
    global _registered_application
    with _registry_lock:
        _registered_application = application


def get_registered_scheduler():
    with _registry_lock:
        return _registered_scheduler


def get_uptime_seconds() -> float:
    """Bot ishga tushganidan beri o'tgan vaqt (sekund)."""
    return max(0.0, time.monotonic() - _START_MONOTONIC)


def get_started_at_iso() -> str:
    """Ishga tushirish vaqti (UTC, ISO-8601)."""
    return _START_TIME_UTC.isoformat(timespec="seconds")


def format_uptime(seconds: float = None) -> str:
    """Uptime'ni ixcham, tilga bog'liq bo'lmagan ko'rinishda formatlaydi.

    ``"2 kun"`` o'rniga ``"2d 3h 15m"`` — uchta til uchun ham bir xil,
    tarjima kalitlarini kengaytirmasdan o'qilishi oson.
    Qoidalar: kun bor bo'lsa sekund ko'rsatilmaydi, soat bor bo'lsa ham
    yo'q; eng kichik daraja (daqiqasiz) sekundni ko'rsatadi.
    """
    if seconds is None:
        seconds = get_uptime_seconds()
    total = int(max(0, seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s" if secs else f"{minutes}m"
    return f"{secs}s"


# ──────────────────────────────────────────────────────────────
# 1) DATABASE
# ──────────────────────────────────────────────────────────────
async def _check_database() -> dict:
    """Neon DB holati: SELECT 1 ping, latency va pool holati."""
    result = {
        "component": "database",
        "status": STATUS_UNKNOWN,
        "latency_ms": None,
        "error": None,
        "pool": {},
    }
    try:
        ping = await db.run_db(db.ping_db_with_latency)
        result["ok"] = bool(ping.get("ok"))
        result["latency_ms"] = ping.get("latency_ms")
        result["error"] = ping.get("error")
        result["status"] = STATUS_OK if ping.get("ok") else STATUS_UNHEALTHY
    except Exception as e:  # run_db ham yiqilsa — UNHEALTHY, crash yo'q
        logger.warning("health: DB tekshiruvida xato: %s", e)
        result["ok"] = False
        result["status"] = STATUS_UNHEALTHY
        result["error"] = f"{type(e).__name__}: {e}"[:200]

    # Pool holati — sync, lekin arzon (lug'at o'qish). Thread'da: xavfsizlik uchun.
    try:
        result["pool"] = await db.run_db(db.get_db_pool_status)
    except Exception as e:
        logger.debug("health: pool holati o'qilmadi: %s", e)
        result["pool"] = {}
    return result


# ──────────────────────────────────────────────────────────────
# 2) SCHEDULER
# ──────────────────────────────────────────────────────────────
async def _check_scheduler(post_counts: dict) -> dict:
    """apscheduler holati + pending/failed/dead_letter postlar soni."""
    result = {
        "component": "scheduler",
        "status": STATUS_UNKNOWN,
        "running": None,
        "jobs": None,
        "pending": post_counts.get("pending", 0),
        "processing": post_counts.get("processing", 0),
        "failed": post_counts.get("failed", 0),
        "stale_processing": post_counts.get("stale_processing", 0),
        "delivery_failed": post_counts.get("delivery_failed", 0),
        "dead_letter": post_counts.get("dead_letter", 0),
        # 11-bosqich: UNKNOWN_DELIVERY (albom timeout — qo'lda tekshiruv kerak)
        "unknown_posts": post_counts.get("unknown_posts", 0),
        "unknown_delivery": post_counts.get("unknown_delivery", 0),
        "error": post_counts.get("error"),
    }

    scheduler = get_registered_scheduler()
    if scheduler is None:
        # Ro'yxatga olinmagan (masalan, test muhiti) — UNKNOWN, DEGRADED emas.
        result["status"] = STATUS_UNKNOWN
        return result

    try:
        running = bool(scheduler.running)
    except Exception:
        running = False
    result["running"] = running
    try:
        result["jobs"] = len(scheduler.get_jobs())
    except Exception:
        result["jobs"] = None

    result["status"] = STATUS_RUNNING if running else STATUS_STOPPED
    return result


# ──────────────────────────────────────────────────────────────
# 2b) TO'LOVLAR (11-bosqich)
# ──────────────────────────────────────────────────────────────
STATUS_DISABLED = "DISABLED"


def _payments_configured() -> dict:
    """Stars/karta to'lovlari sozlanganmi (config'dan, maxfiy ma'lumotsiz)."""
    info = {"card_enabled": False, "stars_enabled": True}
    try:
        from config import CARD_NUMBER  # lazy — testlarda config almashtirilishi mumkin
        info["card_enabled"] = bool((CARD_NUMBER or "").strip())
    except Exception:
        pass
    return info


async def _check_payments() -> dict:
    """To'lov holati: kutayotgan cheklar, 24 soatlik tasdiqlar/Stars soni."""
    result = {
        "component": "payments",
        "status": STATUS_UNKNOWN,
        "pending_receipts": 0,
        "approved_24h": 0,
        "stars_24h": 0,
        "card_enabled": False,
        "stars_enabled": True,
        "error": None,
    }
    result.update(_payments_configured())
    try:
        getter = getattr(db, "get_payments_health_counts", None)
        counts = await db.run_db(getter) if getter is not None else {}
        counts = counts or {}
        result["pending_receipts"] = int(counts.get("pending_receipts") or 0)
        result["approved_24h"] = int(counts.get("approved_24h") or 0)
        result["stars_24h"] = int(counts.get("stars_24h") or 0)
        result["error"] = counts.get("error")
    except Exception as e:
        logger.warning("health: to'lov tekshiruvida xato: %s", e)
        result["error"] = f"{type(e).__name__}: {e}"[:200]
    if result["error"]:
        # DB uzilishi allaqachon "database" komponentida aks etadi —
        # bu yerda faqat UNKNOWN (ikki marta jarima yo'q).
        result["status"] = STATUS_UNKNOWN
    elif not result["card_enabled"] and not result["stars_enabled"]:
        result["status"] = STATUS_DISABLED
    elif result["pending_receipts"] >= PENDING_RECEIPTS_ALERT:
        result["status"] = STATUS_DEGRADED
    else:
        result["status"] = STATUS_OK
    return result


# ──────────────────────────────────────────────────────────────
# 3) AI PROVAYDERLAR
# ──────────────────────────────────────────────────────────────
def _ai_breaker_fail_count(aa, name: str) -> int:
    """Provayderning ketma-ket xatolari soni (circuit-breaker hisoblagichi)."""
    try:
        entry = (getattr(aa, "_BREAKERS", None) or {}).get(name) or {}
        return int(entry.get("fails") or 0)
    except Exception:
        return 0


def _check_ai_providers() -> dict:
    """Har bir AI provayder: kalit bormi + circuit-breaker holati.

    Har bir provayder: ``OK`` (kalit bor, breaker yopiq) /
    ``DEGRADED`` (breaker ochiq — 3 marta ketma-ket xato) /
    ``UNCONFIGURED`` (kalit yo'q).
    """
    result = {
        "component": "ai_providers",
        "status": STATUS_UNKNOWN,
        "providers": [],
        "core_ok": 0,
        "core_total": 0,
        "breakers_open": 0,
        "consecutive_errors": 0,
    }
    try:
        from services.ai_service import build_default_providers  # lazy import
        from utils import ai_agent as aa

        providers = []
        core_ok = 0
        core_total = 0
        open_count = 0
        total_fails = 0
        any_key_configured = False
        for provider in build_default_providers():
            try:
                available = bool(provider.is_available())
            except Exception:
                available = False
            try:
                breaker = bool(aa._breaker_open(provider.name))
            except Exception:
                breaker = False

            if not available:
                status = STATUS_UNCONFIGURED
            elif breaker:
                status = STATUS_DEGRADED
            else:
                status = STATUS_OK

            if provider.tier in CORE_TIERS:
                core_total += 1
                if status == STATUS_OK:
                    core_ok += 1
            # Pollinations kalitsiz (har doim mavjud) — "sozlangan" hisobga
            # kirmaydi: hech bo'lmasa Bitta haqiqiy API kalit bo'lmasa
            # holat UNCONFIGURED bo'ladi.
            if available and getattr(provider, "key_attr", None):
                any_key_configured = True

            fails = _ai_breaker_fail_count(aa, provider.name)
            if breaker:
                open_count += 1
            total_fails += fails
            providers.append({
                "name": provider.name,
                "tier": provider.tier,
                "status": status,
                "breaker_open": breaker,
                "configured": available,
                "consecutive_errors": fails,
            })

        result["providers"] = providers
        result["breakers_open"] = open_count
        result["consecutive_errors"] = total_fails
        result["core_ok"] = core_ok
        result["core_total"] = core_total

        if not any_key_configured and core_ok == 0:
            # Hech qanday API kalit sozlanmagan.
            result["status"] = STATUS_UNCONFIGURED
        elif core_ok == 0:
            result["status"] = STATUS_DEGRADED
        else:
            result["status"] = STATUS_OK
    except Exception as e:
        logger.warning("health: AI provayderlar tekshiruvida xato: %s", e)
        result["status"] = STATUS_UNKNOWN
        result["error"] = f"{type(e).__name__}: {e}"[:200]
    return result


# ──────────────────────────────────────────────────────────────
# 4) TIZIM RESURSLARI
# ──────────────────────────────────────────────────────────────
def _error_stats_safe() -> dict:
    """Global error handler statistikasi (mavjud bo'lmasa — bo'sh)."""
    try:
        from handlers.error_handler import get_error_stats  # lazy import
        return get_error_stats()
    except Exception:
        return {"total": None, "last_hour": None, "last_24h": None}


def _check_system() -> dict:
    """Uptime, faol ulanishlar, asyncio vazifalari va xatolar statistikasi."""
    system = {
        "component": "system",
        "uptime_seconds": round(get_uptime_seconds(), 1),
        "uptime_human": format_uptime(),
        "started_at": get_started_at_iso(),
        "pid": os.getpid(),
        "asyncio_tasks": None,
        "errors_last_hour": None,
        "errors_last_24h": None,
    }
    try:
        system["asyncio_tasks"] = len(asyncio.all_tasks())
    except Exception:
        pass
    stats = _error_stats_safe()
    system["errors_last_hour"] = stats.get("last_hour")
    system["errors_last_24h"] = stats.get("last_24h")
    return system


# ──────────────────────────────────────────────────────────────
# 5) UMUMIY HOLAT
# ──────────────────────────────────────────────────────────────
def _compute_overall_status(database: dict, scheduler: dict,
                            ai: dict, payments: dict = None) -> str:
    """Komponentlardan umumiy HEALTHY / DEGRADED / UNHEALTHY ni hisoblaydi."""
    # 1) DB yiqilgan bo'lsa — bot umuman ishlamaydi → UNHEALTHY.
    if database.get("status") != STATUS_OK:
        return STATUS_UNHEALTHY

    # 2) DEGRADED sabablari:
    reasons = []

    if scheduler.get("status") == STATUS_STOPPED:
        reasons.append("scheduler_stopped")

    if scheduler.get("dead_letter", 0) >= DEAD_LETTER_ALERT_THRESHOLD:
        reasons.append("dead_letter")
    if scheduler.get("failed", 0) >= FAILED_ALERT_THRESHOLD:
        reasons.append("failed_posts")
    if scheduler.get("pending", 0) >= PENDING_BACKLOG_ALERT:
        reasons.append("pending_backlog")
    if scheduler.get("stale_processing", 0) > 0:
        reasons.append("stale_processing")

    if (scheduler.get("unknown_posts") or 0) > 0 or (scheduler.get("unknown_delivery") or 0) > 0:
        reasons.append("unknown_delivery")

    if ai.get("status") == STATUS_DEGRADED:
        reasons.append("ai_core_degraded")

    if payments and payments.get("status") in (STATUS_DEGRADED, STATUS_UNHEALTHY):
        reasons.append("payments")

    return STATUS_DEGRADED if reasons else STATUS_HEALTHY


async def get_system_health() -> dict:
    """Barcha komponentlarni tekshirib, yagona health hisobotini qaytaradi.

    Returns::

        {
          "status": "HEALTHY" | "DEGRADED" | "UNHEALTHY",
          "checked_at": "2026-09-11T14:05:00+00:00",
          "uptime_seconds": 12345.6,
          "database":   {"status", "ok", "latency_ms", "error", "pool"},
          "scheduler":  {"status", "running", "jobs", "pending", ...},
          "ai_providers": {"status", "providers": [...], "core_ok", ...},
          "system":     {"uptime_human", "asyncio_tasks", ...},
        }
    """
    database_info = await _check_database()
    post_counts = await db.run_db(db.get_post_health_counts)
    scheduler_info = await _check_scheduler(post_counts or {})
    ai_info = _check_ai_providers()
    try:
        payments_info = await _check_payments()
    except Exception as e:  # hech qachon health'ni yiqitmasin
        logger.warning("health: payments tekshiruvi yiqildi: %s", e)
        payments_info = {"component": "payments", "status": STATUS_UNKNOWN,
                         "error": f"{type(e).__name__}: {e}"[:200]}
    system_info = _check_system()

    overall = _compute_overall_status(database_info, scheduler_info, ai_info, payments_info)

    return {
        "status": overall,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": system_info["uptime_seconds"],
        "database": database_info,
        "scheduler": scheduler_info,
        "ai_providers": ai_info,
        "payments": payments_info,
        "system": system_info,
    }


# ──────────────────────────────────────────────────────────────
# 6) ADMINLAR UCHUN FORMATLANGAN HISOBOT
# ──────────────────────────────────────────────────────────────
def _status_emoji(status: str) -> str:
    return {
        STATUS_OK: "✅",
        STATUS_HEALTHY: "✅",
        STATUS_RUNNING: "✅",
        STATUS_DEGRADED: "⚠️",
        STATUS_STOPPED: "🛑",
        STATUS_UNCONFIGURED: "⚪️",
        STATUS_UNHEALTHY: "❌",
        STATUS_UNKNOWN: "❔",
        STATUS_DISABLED: "⚪️",
    }.get(status, "❔")


def _fmt_num(value) -> str:
    """Sonni yoki '—' (ma'lum emas) ni qaytaradi."""
    if value is None:
        return "—"
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


async def format_health_report(lang: str = "uz", health: dict = None) -> str:
    """Admin uchun formatlangan chiroyli HTML health hisoboti.

    Args:
        lang: hisobot tili (``uz`` / ``ru`` / ``en``).
        health: tayyor ``get_system_health()`` natijasi (None bo'lsa — o'zi tekshiradi).

    Barcha dinamik qiymatlar ``html.escape`` orqali o'tkaziladi — Telegram
    HTML parse xatosi yoki injeksiya mumkin emas.
    """
    import html as _html

    from locales.translations import get_text, normalize_lang

    lang = normalize_lang(lang)
    if health is None:
        health = await get_system_health()

    db_info = health.get("database") or {}
    sched = health.get("scheduler") or {}
    ai = health.get("ai_providers") or {}
    system = health.get("system") or {}
    pool = db_info.get("pool") or {}

    overall = health.get("status") or STATUS_UNKNOWN

    lines = [
        get_text("health_title", lang),
        "",
        f"{get_text('health_overall', lang)} "
        f"{_status_emoji(overall)} <b>{_html.escape(overall)}</b>",
        get_text("health_checked_at", lang).format(
            time=_html.escape(str(health.get("checked_at", "—")))
        ),
        get_text("health_uptime", lang).format(
            uptime=_html.escape(str(system.get("uptime_human", "—")))
        ),
        "",
    ]

    # ── Database ──
    db_status = db_info.get("status") or STATUS_UNKNOWN
    lines.append(
        get_text("health_db_title", lang).format(
            status=f"{_status_emoji(db_status)} {_html.escape(db_status)}"
        )
    )
    if db_status == STATUS_OK:
        lines.append(get_text("health_db_latency", lang).format(
            latency=_fmt_num(db_info.get("latency_ms"))
        ))
    elif db_info.get("error"):
        lines.append(get_text("health_db_error", lang).format(
            error=_html.escape(str(db_info.get("error")))[:160]
        ))
    if pool:
        lines.append(get_text("health_db_pool", lang).format(
            used=_fmt_num(pool.get("used")),
            max=_fmt_num(pool.get("max")),
            available=_fmt_num(pool.get("available")),
        ))
    lines.append("")

    # ── Scheduler ──
    sched_status = sched.get("status") or STATUS_UNKNOWN
    lines.append(
        get_text("health_scheduler_title", lang).format(
            status=f"{_status_emoji(sched_status)} {_html.escape(sched_status)}"
        )
    )
    if sched_status == STATUS_RUNNING:
        lines.append(get_text("health_sched_jobs", lang).format(
            count=_fmt_num(sched.get("jobs"))
        ))
    lines.append(get_text("health_posts_pending", lang).format(
        count=_fmt_num(sched.get("pending"))
    ))
    lines.append(get_text("health_posts_processing", lang).format(
        count=_fmt_num(sched.get("processing"))
    ))
    lines.append(get_text("health_posts_failed", lang).format(
        count=_fmt_num(sched.get("failed"))
    ))
    lines.append(get_text("health_posts_dead", lang).format(
        count=_fmt_num(sched.get("dead_letter"))
    ))
    if sched.get("stale_processing"):
        lines.append(get_text("health_posts_stale", lang).format(
            count=_fmt_num(sched.get("stale_processing"))
        ))
    unknown_total = max(int(sched.get("unknown_posts") or 0),
                        int(sched.get("unknown_delivery") or 0))
    lines.append(get_text("health_posts_unknown", lang).format(
        count=_fmt_num(unknown_total)
    ))
    lines.append("")

    # ── AI provayderlar ──
    ai_status = ai.get("status") or STATUS_UNKNOWN
    lines.append(
        get_text("health_ai_title", lang).format(
            status=f"{_status_emoji(ai_status)} {_html.escape(ai_status)}"
        )
    )
    for provider in ai.get("providers") or []:
        p_status = provider.get("status") or STATUS_UNKNOWN
        lines.append(get_text("health_ai_provider", lang).format(
            name=_html.escape(str(provider.get("name", "?"))),
            status=f"{_status_emoji(p_status)} {_html.escape(p_status)}",
        ))
    lines.append(get_text("health_ai_errors", lang).format(
        open=_fmt_num(ai.get("breakers_open")),
        errors=_fmt_num(ai.get("consecutive_errors")),
    ))
    lines.append("")

    # ── To'lovlar ──
    pay = health.get("payments") or {}
    pay_status = pay.get("status") or STATUS_UNKNOWN
    lines.append(get_text("health_payments_title", lang).format(
        status=f"{_status_emoji(pay_status)} {_html.escape(pay_status)}"
    ))
    lines.append(get_text("health_payments_pending", lang).format(
        count=_fmt_num(pay.get("pending_receipts"))
    ))
    lines.append(get_text("health_payments_24h", lang).format(
        approved=_fmt_num(pay.get("approved_24h")),
        stars=_fmt_num(pay.get("stars_24h")),
    ))
    if pay.get("error"):
        lines.append(get_text("health_db_error", lang).format(
            error=_html.escape(str(pay.get("error")))[:160]
        ))
    lines.append("")

    # ── Tizim ──
    lines.append(get_text("health_system_title", lang))
    err_hour = system.get("errors_last_hour")
    err_day = system.get("errors_last_24h")
    lines.append(get_text("health_errors", lang).format(
        hour=_fmt_num(err_hour),
        day=_fmt_num(err_day),
    ))
    tasks = system.get("asyncio_tasks")
    if tasks is not None:
        lines.append(get_text("health_tasks", lang).format(count=_fmt_num(tasks)))

    return "\n".join(lines)
