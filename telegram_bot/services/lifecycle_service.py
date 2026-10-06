"""LifecycleService — PostAssist V2 (9-BOSQICH): Graceful Shutdown holati.

Bot jarayoni ``SIGINT``/``SIGTERM`` olganda (Render deploy, ``Ctrl+C``,
``systemctl stop``) hech qanday ish yarim yo'lda tashlab ketilmasligi kerak:

1. **Yangi ish qabul qilinmaydi** — ``request_shutdown()`` chaqirilgach
   ``is_shutting_down()`` ``True`` qaytaradi; scheduler workerlari navbatdan
   yangi post olmaydi, Telegram polling to'xtatiladi.
2. **Bajarilayotgan ishlar tugatiladi** — har bir faol post yuborish
   ``track(...)`` konteksti bilan ro'yxatga olinadi; ``wait_for_inflight()``
   ular tugashini (yoki ``SHUTDOWN_GRACE_SECONDS`` timeout'ini) kutadi.
   Timeout tugasa ham vazifalar **bekor qilinmaydi** — ular DB'da
   ``processing`` holatida qoladi va keyingi ishga tushishda mavjud
   stale-recovery mexanizmi (10 daqiqa) ularni xavfsiz tiklaydi.
2b. **Navbat (queue) drenaji** — ``in-flight`` hisobidan tashqari,
   komponentlar o'z navbatlarini ``queue_enter()`` / ``track_queue()``
   bilan e'lon qiladi (masalan, delivery engine'ning yuborilayotgan
   xabarlari). ``wait_for_queues()`` ularning bo'shashini kutadi va
   ``main.py`` drenaj hisobotiga qo'shadi (standart byudjet — 15 soniya).
3. **Resurslar toza yopiladi** — ``main.py`` shu servis kutib bo'lgach
   DB pool va Redis/aiohttp ulanishlarini yopadi va ``exit code 0`` bilan
   chiqadi.

Modul **thread-safe** (``threading.Lock``) — chunki DB ishlari
``asyncio.to_thread`` orqali boshqa thread'larda bajariladi va signal
handler event loop ichida ishlaydi. Hech qanday tashqi bog'liqlik yo'q
(``database``/``telegram`` import qilinmaydi) — testlarda va boshqa
servislarda erkin ishlatiladi.

Foydalanish::

    from services import lifecycle_service as lifecycle

    # scheduler worker:
    if lifecycle.is_shutting_down():
        return                        # yangi ish olinmaydi
    with lifecycle.track(f"post:{post_id}"):
        await send(...)               # in-flight sifatida hisoblanadi

    # main.py signal handler:
    lifecycle.request_shutdown("SIGTERM")
    await lifecycle.wait_for_inflight()   # 5–10 soniya kutadi
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


#: Faol (in-flight) vazifalar va navbatlar (delivery queue, scheduler ishlari)
#: tugashini kutish muddati (soniya). PHASE 12 talabi bo'yicha standart
#: **15 soniya** — shu vaqt ichida yuborilayotgan postlar xavfsiz tugaydi.
#: ``SHUTDOWN_GRACE_SECONDS`` env orqali sozlanadi va har doim [5, 30]
#: oralig'iga qisiladi (0 yoki "cheksiz kutish" mumkin emas — konteyner
#: har qanday holatda ham chekli vaqtda yopiladi).
SHUTDOWN_GRACE_MIN = 5.0
SHUTDOWN_GRACE_MAX = 30.0
SHUTDOWN_DRAIN_DEFAULT_SECONDS = 15.0
SHUTDOWN_GRACE_SECONDS = _env_float(
    "SHUTDOWN_GRACE_SECONDS", SHUTDOWN_DRAIN_DEFAULT_SECONDS,
    SHUTDOWN_GRACE_MIN, SHUTDOWN_GRACE_MAX,
)

#: In-flight ro'yxatini qayta tekshirish oralig'i (soniya).
_POLL_INTERVAL = 0.05

_lock = threading.Lock()
_shutdown_requested = False
_shutdown_reason: str | None = None
_shutdown_at: float | None = None
_inflight: dict[int, dict] = {}
_inflight_seq = 0
_completed_total = 0
_queues: dict[str, int] = {}


# ──────────────────────────────────────────────────────────────
# SHUTDOWN BAYROG'I
# ──────────────────────────────────────────────────────────────
def request_shutdown(reason: str = "signal") -> bool:
    """Shutdown'ni so'raydi. Birinchi chaqiruvda ``True``, keyingilarida
    ``False`` qaytaradi (takroriy signal — masalan ikki marta Ctrl+C —
    yopilishni qayta boshlamaydi)."""
    global _shutdown_requested, _shutdown_reason, _shutdown_at
    with _lock:
        if _shutdown_requested:
            return False
        _shutdown_requested = True
        _shutdown_reason = str(reason or "signal")
        _shutdown_at = time.monotonic()
        pending = len(_inflight)
    logger.warning(
        "Graceful shutdown so'raldi (%s): yangi ishlar qabul qilinmaydi, "
        "faol vazifalar: %d", _shutdown_reason, pending,
    )
    return True


def is_shutting_down() -> bool:
    """``True`` — yopilish boshlangan: yangi ish OLINMASLIGI kerak."""
    return _shutdown_requested


def shutdown_reason() -> str | None:
    return _shutdown_reason


def reset_for_tests() -> None:
    """Testlar uchun: bayroq, in-flight va navbat hisoblagichlarini tozalaydi."""
    global _shutdown_requested, _shutdown_reason, _shutdown_at, _completed_total
    with _lock:
        _shutdown_requested = False
        _shutdown_reason = None
        _shutdown_at = None
        _inflight.clear()
        _queues.clear()
        _completed_total = 0


# ──────────────────────────────────────────────────────────────
# IN-FLIGHT VAZIFALAR HISOBI
# ──────────────────────────────────────────────────────────────
def begin_task(label: str = "") -> int:
    """Faol vazifani ro'yxatga oladi va uning tokenini qaytaradi.

    ``track()`` konteksti buni avtomatik qiladi — to'g'ridan-to'g'ri faqat
    kontekst menejeri noqulay bo'lgan joylarda chaqiriladi.
    """
    global _inflight_seq
    with _lock:
        _inflight_seq += 1
        token = _inflight_seq
        _inflight[token] = {
            "label": str(label or ""),
            "started": time.monotonic(),
            "thread": threading.get_ident(),
        }
        return token


def end_task(token: int) -> None:
    """Vazifani ro'yxatdan chiqaradi (idempotent)."""
    global _completed_total
    with _lock:
        if _inflight.pop(token, None) is not None:
            _completed_total += 1


@contextmanager
def track(label: str = ""):
    """``with lifecycle.track("post:42"): ...`` — blok davomida vazifa
    in-flight hisoblanadi; istisno bo'lsa ham ro'yxatdan chiqariladi."""
    token = begin_task(label)
    try:
        yield token
    finally:
        end_task(token)


def inflight_count() -> int:
    with _lock:
        return len(_inflight)


def inflight_labels() -> list[str]:
    with _lock:
        return [item["label"] for item in _inflight.values()]


def completed_count() -> int:
    """Ro'yxatdan muvaffaqiyatli chiqarilgan vazifalar soni (diagnostika)."""
    return _completed_total


# ──────────────────────────────────────────────────────────────
# NAVBATLAR (QUEUE) — delivery engine, scheduler ishlari
# ──────────────────────────────────────────────────────────────
def queue_enter(name: str = "delivery", count: int = 1) -> int:
    """Navbatdagi birlik ishga tushdi (masalan, yuborilayotgan xabar).

    Hisoblagich ``int`` — komponent o'z navbatini ``queue_leave()`` bilan
    kamaytiradi. Qiymat **hech qachon manfiy bo'lmaydi** (dasturchi xatosi
    drenajni "abadiy band" qilib qo'ymasin).
    """
    key = str(name or "default")
    with _lock:
        _queues[key] = _queues.get(key, 0) + max(1, int(count or 1))
        return _queues[key]


def queue_leave(name: str = "delivery", count: int = 1) -> int:
    """Navbatdagi birlik ish tugadi (idempotent, manfiyga tushmaydi)."""
    key = str(name or "default")
    with _lock:
        remaining = max(0, _queues.get(key, 0) - max(1, int(count or 1)))
        if remaining:
            _queues[key] = remaining
        else:
            _queues.pop(key, None)
        return remaining


@contextmanager
def track_queue(name: str = "delivery"):
    """``with lifecycle.track_queue("delivery"): await send(...)`` — blok
    davomida navbat band hisoblanadi; istisno bo'lsa ham bo'shatiladi."""
    queue_enter(name)
    try:
        yield
    finally:
        queue_leave(name)


def queue_pending() -> dict:
    """Navbatlar bo'yicha band birliklar soni (bo'sh bo'lganlar kirmaydi)."""
    with _lock:
        return {key: value for key, value in _queues.items() if value > 0}


def queue_pending_total() -> int:
    with _lock:
        return sum(_queues.values())


# ──────────────────────────────────────────────────────────────
# KUTISH
# ──────────────────────────────────────────────────────────────
async def wait_for_inflight(timeout: float | None = None) -> dict:
    """Faol vazifalar tugashini kutadi (maks. ``timeout`` soniya).

    Vazifalar **bekor qilinmaydi** — faqat kutiladi. Natija::

        {"drained": bool,          # True — hammasi tugadi
         "remaining": int,         # timeout'da hali faol bo'lganlar
         "labels": [...],          # ularning yorliqlari
         "waited": float,          # kutilgan soniya
         "timeout": float}
    """
    if timeout is None:
        timeout = SHUTDOWN_GRACE_SECONDS
    timeout = max(0.0, float(timeout))
    started = time.monotonic()
    deadline = started + timeout
    while True:
        remaining = inflight_count()
        now = time.monotonic()
        if remaining == 0 or now >= deadline:
            break
        # Log: uzoq kutilsa har ~1 soniyada eslatma.
        await asyncio.sleep(min(_POLL_INTERVAL, max(0.0, deadline - now)))
    remaining = inflight_count()
    waited = time.monotonic() - started
    result = {
        "drained": remaining == 0,
        "remaining": remaining,
        "labels": inflight_labels(),
        "waited": round(waited, 3),
        "timeout": timeout,
    }
    if result["drained"]:
        logger.info("Graceful shutdown: barcha faol vazifalar %.2fs ichida tugadi.", waited)
    else:
        logger.warning(
            "Graceful shutdown: %d ta vazifa %.1fs timeout ichida tugamadi (%s) — "
            "ular bekor qilinmaydi; DB'dagi 'processing' holati keyingi ishga "
            "tushishda stale-recovery orqali tiklanadi.",
            remaining, timeout, ", ".join(result["labels"][:10]),
        )
    return result


def wait_for_inflight_sync(timeout: float | None = None) -> dict:
    """``wait_for_inflight`` ning sinxron varianti (event loop'siz kontekst)."""
    if timeout is None:
        timeout = SHUTDOWN_GRACE_SECONDS
    timeout = max(0.0, float(timeout))
    started = time.monotonic()
    deadline = started + timeout
    while inflight_count() and time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
    remaining = inflight_count()
    return {
        "drained": remaining == 0,
        "remaining": remaining,
        "labels": inflight_labels(),
        "waited": round(time.monotonic() - started, 3),
        "timeout": timeout,
    }


async def wait_for_queues(timeout: float | None = None) -> dict:
    """Band navbatlar (delivery queue va h.k.) bo'shashini kutadi.

    Navbatdagi ishlar **bekor qilinmaydi** — faqat kutiladi: yuborilayotgan
    post Telegramga yetib borishi yoki o'z xatosi bilan tugashi kerak.
    Natija::

        {"drained": bool,
         "remaining": int,          # timeout'da hali band birliklar
         "queues": {...},           # navbatlar kesimida qoldiq
         "waited": float,
         "timeout": float}
    """
    if timeout is None:
        timeout = SHUTDOWN_GRACE_SECONDS
    timeout = max(0.0, float(timeout))
    started = time.monotonic()
    deadline = started + timeout
    while queue_pending_total() and time.monotonic() < deadline:
        await asyncio.sleep(min(_POLL_INTERVAL, max(0.0, deadline - time.monotonic())))
    pending = queue_pending()
    result = {
        "drained": not pending,
        "remaining": sum(pending.values()),
        "queues": pending,
        "waited": round(time.monotonic() - started, 3),
        "timeout": timeout,
    }
    if result["drained"]:
        logger.info("Graceful shutdown: navbatlar %.2fs ichida bo'shadi.", result["waited"])
    else:
        logger.warning(
            "Graceful shutdown: navbatlarda %d birlik %.1fs timeout ichida "
            "tugamadi (%s) — ular bekor qilinmaydi; DB'dagi 'processing' "
            "holati keyingi ishga tushishda stale-recovery orqali tiklanadi.",
            result["remaining"], timeout, pending,
        )
    return result


def wait_for_queues_sync(timeout: float | None = None) -> dict:
    """``wait_for_queues`` ning sinxron varianti."""
    if timeout is None:
        timeout = SHUTDOWN_GRACE_SECONDS
    timeout = max(0.0, float(timeout))
    started = time.monotonic()
    deadline = started + timeout
    while queue_pending_total() and time.monotonic() < deadline:
        time.sleep(_POLL_INTERVAL)
    pending = queue_pending()
    return {
        "drained": not pending,
        "remaining": sum(pending.values()),
        "queues": pending,
        "waited": round(time.monotonic() - started, 3),
        "timeout": timeout,
    }


async def wait_for_drain(timeout: float | None = None) -> dict:
    """Yagona drenaj: faol vazifalar **va** navbatlar (delivery/scheduler).

    Byudjet (``timeout``, standart ``SHUTDOWN_GRACE_SECONDS`` = 15 s) ikkala
    fazaga bo'linadi: avval in-flight vazifalar, qolgan vaqtda navbatlar.
    Qaytadi: ikkala fazaning hisobotlari + ``drained`` yakuniy bayrog'i.
    """
    if timeout is None:
        timeout = SHUTDOWN_GRACE_SECONDS
    timeout = max(0.0, float(timeout))
    started = time.monotonic()
    inflight_report = await wait_for_inflight(timeout)
    remaining_budget = max(0.0, timeout - (time.monotonic() - started))
    queues_report = await wait_for_queues(remaining_budget)
    return {
        "drained": bool(inflight_report.get("drained")) and bool(queues_report.get("drained")),
        "inflight": inflight_report,
        "queues": queues_report,
        "waited": round(time.monotonic() - started, 3),
        "timeout": timeout,
    }


def status() -> dict:
    """Health/diagnostika uchun qisqa holat."""
    with _lock:
        queues = {key: value for key, value in _queues.items() if value > 0}
        return {
            "shutting_down": _shutdown_requested,
            "reason": _shutdown_reason,
            "inflight": len(_inflight),
            "queues": queues,
            "queued_total": sum(queues.values()),
            "completed": _completed_total,
            "grace_seconds": SHUTDOWN_GRACE_SECONDS,
            "drain_default_seconds": SHUTDOWN_DRAIN_DEFAULT_SECONDS,
        }
