"""FAZA 25 — Telegram update handlerlari uchun asinxron xavfsizlik chegaralari.

Maqsad: og'ir AI yoki tahlil chaqiruvlari Telegram update qabul zanjirini
(intake) hech qachon cheksiz bloklamasligi:

1. :func:`await_with_timeout` — istalgan awaitable'ga QAT'IY muddat qo'yadi
   (``asyncio.wait_for``). Muddat oshsa awaitable BEKOR qilinadi va
   ``asyncio.TimeoutError`` ko'tariladi — chaqiruvchi foydalanuvchiga
   xushmuomala javob qaytarishi uchun qat'iy nuqta.
2. :func:`run_background_task` — fon (fire-and-forget) vazifalarini
   ro'yxatga oluvchi yordamchi. Vazifa o'z muddati bilan o'raladi
   (leak bo'lmaydi), tugagach natija/xato LOGGA yoziladi (unutildigan
   "failed silently" task bo'lmaydi) va ro'yxatdan tozalanadi.

So'zlash (config.py): ``UPDATE_HANDLER_TIMEOUT_SECONDS`` (standart 110s —
update handler watchdog) va ``BACKGROUND_TASK_TIMEOUT_SECONDS`` (standart
300s — fon vazifalari uchun umumiy chegara).
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_HANDLER_TIMEOUT = 110.0
DEFAULT_BACKGROUND_TIMEOUT = 300.0

#: Faol fon vazifalarining ro'yxati (leak diagnostikasi uchun).
_background_tasks: set[asyncio.Task] = set()


def get_handler_timeout() -> float:
    """Update handler watchdog muddati (config'dan, sekundlarda)."""
    try:
        from config import UPDATE_HANDLER_TIMEOUT_SECONDS
        value = float(UPDATE_HANDLER_TIMEOUT_SECONDS)
    except Exception:  # pragma: no cover — config import muammosi
        value = DEFAULT_HANDLER_TIMEOUT
    return value if value > 0 else DEFAULT_HANDLER_TIMEOUT


def background_task_count() -> int:
    """Hozir kuzatilayotgan (tugallanmagan) fon vazifalari soni."""
    return sum(1 for task in _background_tasks if not task.done())


async def await_with_timeout(awaitable, timeout: float | None = None,
                             *, label: str = "handler"):
    """``awaitable`` ni QAT'IY muddat bilan bajaradi.

    ``timeout`` (soniya) oshganda — ichki korutin bekor qilinadi
    (``CancelledError``) va ``asyncio.TimeoutError`` ko'tariladi.
    ``timeout=None`` bo'lsa konfiguratsiyadagi handler chegarasi olinadi.

    Qaytadi: awaitable natijasi. Istisnolar: ``asyncio.TimeoutError`` —
    muddat oshdi; awaitable o'z istisnosini qayta ko'taradi.
    """
    limit = timeout if timeout is not None else get_handler_timeout()
    started = time.monotonic()
    try:
        return await asyncio.wait_for(awaitable, timeout=limit)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - started
        # Log xabari scrubber (utils.sentry_scrubber) orqali o'tadi —
        # maxfiy kalitlar tushmaydi. Foydalanuvchi matni bu yerda
        # ko'rsatilmaydi — faqat texnik yorliq.
        logger.error(
            "FAZA25 timeout: %s %.1fs chegarasidan oshdi (kutildi: %.1fs) — "
            "vazifa bekor qilindi", label, limit, elapsed)
        raise


def run_background_task(coro, *, name: str | None = None,
                        timeout: float | None = None,
                        on_error=None) -> asyncio.Task:
    """Fon vazifasini (fire-and-forget) xavfsiz ishga tushiradi.

    Kafolatlar:
      * asosiy qabul zanjiri (update intake) BLOKLANMAYDI — vazifa alohida
        ``asyncio.Task`` sifatida yuradi;
      * vazifa ``timeout`` (standart: ``BACKGROUND_TASK_TIMEOUT_SECONDS``)
        dan oshsa BEKOR qilinadi — cheksiz osilib qolgan task hosil
        bo'lmaydi (task leak himoyasi);
      * yakuniy xato istisno sifatida "yutilmaydi" — logga yoziladi
        (scrubber orqali) va ``on_error`` callback'iga uzatiladi;
      * tugagan task ro'yxatdan darhol o'chiriladi (xotira toza).

    Qaytadi: yaratilgan ``asyncio.Task``.
    """
    limit = timeout
    if limit is None:
        try:
            from config import BACKGROUND_TASK_TIMEOUT_SECONDS
            limit = float(BACKGROUND_TASK_TIMEOUT_SECONDS)
        except Exception:  # pragma: no cover
            limit = DEFAULT_BACKGROUND_TIMEOUT
    if not limit or limit <= 0:
        limit = DEFAULT_BACKGROUND_TIMEOUT

    task = asyncio.ensure_future(
        await_with_timeout(coro, limit, label=name or "background-task"))
    if name:
        try:
            task.set_name(name)
        except Exception:  # pragma: no cover — eski Python
            pass
    _background_tasks.add(task)

    def _on_done(done_task: asyncio.Task) -> None:
        _background_tasks.discard(done_task)
        try:
            if done_task.cancelled():
                logger.warning("Fon vazifasi bekor qilindi: %s",
                               name or done_task.get_name())
                return
            exc = done_task.exception()
        except Exception:  # pragma: no cover — himoya qatlami
            exc = None
        if exc is not None:
            logger.error("Fon vazifasida xatolik (%s): %s",
                         name or done_task.get_name(), exc)
        if on_error is not None and exc is not None:
            try:
                on_error(exc)
            except Exception:  # pragma: no cover — callback xatosi yashirin
                pass

    task.add_done_callback(_on_done)
    return task


__all__ = [
    "DEFAULT_HANDLER_TIMEOUT",
    "DEFAULT_BACKGROUND_TIMEOUT",
    "await_with_timeout",
    "run_background_task",
    "get_handler_timeout",
    "background_task_count",
]
