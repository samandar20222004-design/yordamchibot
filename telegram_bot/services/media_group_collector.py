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
  * Har bir yangi element debounce taymerini uyg'otadi va OXIRGI elementdan
    boshlab qayta sanaydi. Bitta bufer uchun faqat bitta worker yaratiladi.
  * Har bir kalitning alohida ``asyncio.Lock``'i bor. Timeout va ``flush`` bir
    paytda ishga tushsa ham faqat bittasi buferni olib, ``on_ready``'ni bir
    marta chaqiradi.
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
DEFAULT_DELAY_SECONDS = 1.5
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
    __slots__ = (
        "items", "ids", "first_at", "last_at", "on_ready", "task",
        "changed", "lock",
    )

    def __init__(self, now: float, on_ready: ReadyCallback, lock: asyncio.Lock):
        self.items: list = []
        self.ids: set = set()
        self.first_at = now
        self.last_at = now
        self.on_ready = on_ready
        self.task: asyncio.Task | None = None
        # ``add`` bu event orqali mavjud bitta worker'ning debounce kutishini
        # qayta boshlaydi; har update uchun yangi finalizer task yaratilmaydi.
        self.changed = asyncio.Event()
        # Timeout/flush/cancel chegarasidagi finalizatsiyani idempotent qiladi.
        self.lock = lock


class MediaGroupCollector:
    """Albom fayllarini yig'adi va jimlikdan keyin bir marta qaytaradi."""

    def __init__(self, *, delay: float = DEFAULT_DELAY_SECONDS,
                 max_wait: float = DEFAULT_MAX_WAIT_SECONDS,
                 max_items: int = TELEGRAM_ALBUM_MAX_ITEMS):
        self.delay = max(0.0, float(delay))
        self.max_wait = max(self.delay, float(max_wait))
        self.max_items = max(1, int(max_items))
        self._buffers: dict[Hashable, _Buffer] = {}
        # Talab bo'yicha har bir media_group kalitiga alohida lock. Lock callback
        # tugaguncha ushlab turiladi, shuning uchun rendering ikki marta ketmaydi.
        self._locks: dict[Hashable, asyncio.Lock] = {}
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

    def task_for(self, key: Hashable) -> asyncio.Task | None:
        """Kalitning yagona worker vazifasi (integratsiya/test cleanup'i uchun)."""
        buf = self._buffers.get(key)
        return buf.task if buf is not None else None

    # -- qo'shish -----------------------------------------------------------
    def add(self, key: Hashable, item: dict, on_ready: ReadyCallback) -> str:
        """Faylni buferga qo'shadi (event loop ichidan chaqiriladi).

        ``item`` — dict; ``message_id`` bo'lsa dublikat aniqlanadi va yakuniy
        ro'yxat shu bo'yicha tartiblanadi (Telegram tartibi).

        Metodda ``await`` yo'q: bitta asyncio event loop ichida append +
        ``last_at`` yangilanishi atomik bajariladi. Finalizer esa shu kalitning
        lock'i ichida vaqtni qayta tekshiradi.
        """
        loop = asyncio.get_running_loop()
        now = loop.time()
        buf = self._buffers.get(key)
        started = buf is None
        if started:
            lock = self._locks.setdefault(key, asyncio.Lock())
            buf = _Buffer(now, on_ready, lock)
            self._buffers[key] = buf
        message_id = item.get("message_id") if isinstance(item, dict) else None
        if message_id is not None and message_id in buf.ids:
            return DUPLICATE
        if len(buf.items) >= self.max_items:
            return FULL
        buf.items.append(item)
        if message_id is not None:
            buf.ids.add(message_id)
        # Muhim: debounce OXIRGI qabul qilingan elementdan qayta boshlanadi.
        buf.last_at = now
        if started:
            # Bitta media_group uchun FAQAT bitta worker.
            buf.task = loop.create_task(self._run(key, buf))
            self._tasks.add(buf.task)
            buf.task.add_done_callback(self._tasks.discard)
            return ADDED_STARTED
        # Mavjud worker'ni uyg'otamiz; yangi preview/finalizer task ochilmaydi.
        buf.changed.set()
        return ADDED

    # -- bekor qilish -------------------------------------------------------
    def cancel(self, key: Hashable) -> bool:
        """Yig'ishni bekor qiladi (``on_ready`` chaqirilmaydi)."""
        buf = self._buffers.pop(key, None)
        if buf is None:
            return False
        if buf.task is not None and not buf.task.done():
            buf.task.cancel()
        self._cleanup_lock(key, buf)
        return True

    async def flush(self, key: Hashable) -> bool:
        """Kutmasdan darhol yakunlaydi (test/o'chirish uchun).

        Worker timeouti bilan bir vaqtda chaqirilsa, per-key lock va bufer
        identity tekshiruvi callback'ni aynan bir marta bajaradi.
        """
        buf = self._buffers.get(key)
        if buf is None:
            return False
        current = asyncio.current_task()
        if buf.task is not None and buf.task is not current and not buf.task.done():
            buf.task.cancel()
        delivered = False
        try:
            async with buf.lock:
                if self._buffers.get(key) is not buf:
                    return False
                self._buffers.pop(key, None)
                await self._deliver(buf)
                delivered = True
        finally:
            self._cleanup_lock(key, buf)
        return delivered

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
                wait = min(
                    buf.last_at + self.delay - now,
                    buf.first_at + self.max_wait - now,
                )
                if wait > 0:
                    try:
                        # Yangi item kelsa darhol uyg'onib, OXIRGI itemdan
                        # yangi to'liq debounce oynasini hisoblaydi.
                        await asyncio.wait_for(buf.changed.wait(), timeout=wait)
                    except asyncio.TimeoutError:
                        pass
                    else:
                        buf.changed.clear()
                        continue

                # Timeout chegarasida update kelishi mumkin. Lock ichida
                # last_at'ni qayta tekshirmasdan pop qilish partial albumga
                # olib kelardi.
                async with buf.lock:
                    if self._buffers.get(key) is not buf:
                        return  # cancel()/flush() allaqachon olib tashlagan
                    now = loop.time()
                    quiet_until = buf.last_at + self.delay
                    hard_deadline = buf.first_at + self.max_wait
                    if now < quiet_until and now < hard_deadline:
                        continue
                    self._buffers.pop(key, None)
                    # Rendering/callback ham shu lock ichida: ayni guruhning
                    # ikkinchi finalizer'i parallel ishlay olmaydi.
                    await self._deliver(buf)
                    return
        except asyncio.CancelledError:
            return
        finally:
            self._cleanup_lock(key, buf)

    def _cleanup_lock(self, key: Hashable, buf: _Buffer) -> None:
        """Kalit qayta ishlatilmayotgan bo'lsa uning lock'ini chiqaradi."""
        # Callback davomida ayni Telegram group ID uchun juda kech update
        # kelsa, yangi buffer aynan shu lock'dan foydalanadi. Bunday holatda
        # eski worker lock mapping'ini o'chirmasligi kerak.
        if self._buffers.get(key) is None \
                and self._locks.get(key) is buf.lock \
                and not buf.lock.locked():
            self._locks.pop(key, None)

    async def _deliver(self, buf: _Buffer) -> None:
        items = sorted(
            list(buf.items),
            key=lambda it: (it.get("message_id") is None, it.get("message_id") or 0)
            if isinstance(it, dict) else (True, 0),
        )
        try:
            await buf.on_ready(items)
        except Exception:  # noqa: BLE001 — bitta albom xatosi boshqalarni buzmasin
            logger.exception("MediaGroupCollector: on_ready xatosi (%d ta fayl)", len(items))
