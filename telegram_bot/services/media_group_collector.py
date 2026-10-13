"""🖼 Media group (albom) yig'uvchi — ``media_group_id`` bo'yicha debounce bufer.

Telegram albomning har bir faylini ALOHIDA update sifatida yuboradi (odatda
0.1–0.5 soniya ichida). Handler har bir updatega alohida javob bersa, bitta
albom bir nechta mustaqil postga bo'linib ketadi. Bu kollektor fayllarni
``(foydalanuvchi, media_group_id)`` kaliti bo'yicha yig'adi va OXIRGI fayldan
``delay`` soniya jimlik o'tgach BITTA ro'yxat sifatida ``on_ready`` ga beradi.

Muhim:
  * ``GuardedApplication`` har bir foydalanuvchi updatelarini ketma-ket
    ishlaydi, shu sababli handler ICHIDA ``sleep`` qilib bo'lmaydi — albomning
    qolgan qismlari navbatda kutib, har biri alohida post bo'lib ketadi.
    Kollektor kutishni ALOHIDA fon vazifasida bajaradi, handler esa darhol
    qaytadi.
  * Dublikat update (bir xil ``message_id``) bir marta hisoblanadi.
  * ``max_wait`` — sekin tarmoqda ham yig'ish cheksiz cho'zilmaydi.
  * ``on_ready`` xatosi logga yoziladi va boshqa albomlarga ta'sir qilmaydi.

Modul faqat stdlib + asyncio ishlatadi (telegram bog'liqligi yo'q).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Hashable

logger = logging.getLogger(__name__)

__all__ = [
    "MediaGroupCollector",
    "DEFAULT_DELAY_SECONDS",
    "DEFAULT_MAX_WAIT_SECONDS",
    "TELEGRAM_ALBUM_MAX_ITEMS",
    "ADDED_STARTED",
    "ADDED",
    "DUPLICATE",
    "FULL",
]

#: Oxirgi fayldan keyingi jimlik oynasi (debounce).
DEFAULT_DELAY_SECONDS = 1.0
#: Birinchi fayldan boshlab umumiy kutish chegarasi.
DEFAULT_MAX_WAIT_SECONDS = 10.0
#: Telegram albom chegarasi.
TELEGRAM_ALBUM_MAX_ITEMS = 10

#: ``add`` natijalari.
ADDED_STARTED = "started"   # yangi bufer ochildi (shu albomning birinchi fayli)
ADDED = "added"             # mavjud buferga qo'shildi
DUPLICATE = "duplicate"     # shu ``message_id`` allaqachon bor
FULL = "full"               # bufer to'lgan (fayl qo'shilmadi)

ReadyCallback = Callable[[list], Awaitable[Any]]


class _Buffer:
    __slots__ = ("items", "ids", "first_at", "last_at", "on_ready", "task")

    def __init__(self, now: float, on_ready: ReadyCallback):
        self.items: list = []
        self.ids: set = set()
        self.first_at = now
        self.last_at = now
        self.on_ready = on_ready
        self.task: asyncio.Task | None = None


class MediaGroupCollector:
    """Albom fayllarini yig'adi va jimlikdan keyin bir marta qaytaradi."""

    def __init__(self, *, delay: float = DEFAULT_DELAY_SECONDS,
                 max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
                 max_items: int = TELEGRAM_ALBUM_MAX_ITEMS):
        self.delay = max(0.0, float(delay))
        self.max_wait = max(self.delay, float(max_wait))
        self.max_items = max(1, int(max_items))
        self._buffers: dict[Hashable, _Buffer] = {}
        # Fon vazifalarga kuchli havola — GC ularni yig'ib yubormasligi uchun.
        self._tasks: set[asyncio.Task] = set()

    # -- holat --------------------------------------------------------------
    def pending(self, key: Hashable | None = None) -> int:
        """Yig'ilayotgan fayllar soni (``key`` bo'lmasa — barcha albomlar)."""
        if key is not None:
            buf = self._buffers.get(key)
            return len(buf.items) if buf else 0
        return sum(len(b.items) for b in self._buffers.values())

    def is_collecting(self, key: Hashable) -> bool:
        return key in self._buffers

    # -- qo'shish -----------------------------------------------------------
    def add(self, key: Hashable, item: dict, on_ready: ReadyCallback) -> str:
        """Faylni buferga qo'shadi (event loop ichidan chaqiriladi).

        ``item`` — dict; ``message_id`` bo'lsa dublikat aniqlanadi va yakuniy
        ro'yxat shu bo'yicha tartiblanadi (Telegram tartibi).
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        buf = self._buffers.get(key)
        started = buf is None
        if started:
            buf = _Buffer(now, on_ready)
            self._buffers[key] = buf
        message_id = item.get("message_id") if isinstance(item, dict) else None
        if message_id is not None and message_id in buf.ids:
            return DUPLICATE
        if len(buf.items) >= self.max_items:
            return FULL
        buf.items.append(item)
        if message_id is not None:
            buf.ids.add(message_id)
        buf.last_at = now
        if started:
            buf.task = loop.create_task(self._run(key, buf))
            self._tasks.add(buf.task)
            buf.task.add_done_callback(self._tasks.discard)
            return ADDED_STARTED
        return ADDED

    # -- bekor qilish -------------------------------------------------------
    def cancel(self, key: Hashable) -> bool:
        """Yig'ishni bekor qiladi (``on_ready`` chaqirilmaydi)."""
        buf = self._buffers.pop(key, None)
        if buf is None:
            return False
        if buf.task is not None and not buf.task.done():
            buf.task.cancel()
        return True

    async def flush(self, key: Hashable) -> bool:
        """Kutmasdan darhol yakunlaydi (test/o'chirish uchun)."""
        buf = self._buffers.pop(key, None)
        if buf is None:
            return False
        if buf.task is not None and not buf.task.done():
            buf.task.cancel()
        await self._deliver(buf)
        return True

    async def wait_idle(self) -> None:
        """Barcha fon vazifalar tugashini kutadi (testlar uchun)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    # -- ichki --------------------------------------------------------------
    async def _run(self, key: Hashable, buf: _Buffer) -> None:
        loop = asyncio.get_running_loop()
        try:
            while True:
                now = loop.time()
                wait = min(buf.last_at + self.delay - now,
                           buf.first_at + self.max_wait - now)
                if wait <= 0:
                    break
                await asyncio.sleep(wait)
        except asyncio.CancelledError:
            return
        if self._buffers.get(key) is not buf:
            return  # cancel()/flush() allaqachon olib tashlagan
        self._buffers.pop(key, None)
        await self._deliver(buf)

    async def _deliver(self, buf: _Buffer) -> None:
        items = sorted(
            buf.items,
            key=lambda it: (it.get("message_id") is None, it.get("message_id") or 0)
            if isinstance(it, dict) else (True, 0),
        )
        try:
            await buf.on_ready(items)
        except Exception:  # noqa: BLE001 — bitta albom xatosi boshqalarni buzmasin
            logger.exception("MediaGroupCollector: on_ready xatosi (%d ta fayl)", len(items))
