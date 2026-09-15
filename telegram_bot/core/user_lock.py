"""Non-blocking User Lock Manager.

PHASE 4 & 5: Foydalanuvchi darajasidagi qisqa muddatli non-blocking lock mexanizmi (14-band).

Model:
  AI so'rovi paytida foydalanuvchi sessiyasini 10-20 soniya ushlab turadigan
  qo'pol global/session locklar ISHLATILMAYDI.
  To'g'ri model:
    1. Lock olinadi (qisqa, timeout <= 1-2s);
    2. FSM/kontekst snapshot qilinadi;
    3. Lock DARHOL bo'shatiladi;
    4. AI so'rovi fonda (worker/task) mustaqil ishlaydi (foydalanuvchi interfeysi qotmaydi);
    5. Natija tayyor bo'lgach, yana qisqa lock olinadi va holat yangilanadi.
"""

from __future__ import annotations
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")


class UserLockTimeoutError(TimeoutError):
    """Foydalanuvchi lockini belgilangan timeout ichida olib bo'lmadi."""
    pass


class UserLockManager:
    """Foydalanuvchi darajasidagi non-blocking lock boshqaruvchisi."""

    def __init__(self, default_timeout: float = 1.0):
        self._locks: dict[int, asyncio.Lock] = {}
        self._lock_timestamps: dict[int, float] = {}
        self.default_timeout = default_timeout

    def get_lock(self, user_id: int) -> asyncio.Lock:
        """user_id uchun asyncio.Lock obyektini qaytaradi (mavjud bo'lmasa yaratadi)."""
        uid = int(user_id)
        if uid not in self._locks:
            self._locks[uid] = asyncio.Lock()
        return self._locks[uid]

    def is_locked(self, user_id: int) -> bool:
        """Foydalanuvchi locklanganligini tekshiradi."""
        uid = int(user_id)
        lock = self._locks.get(uid)
        return lock.locked() if lock else False

    async def acquire(self, user_id: int, timeout: float | None = None) -> bool:
        """Lockni timeout bilan olishga harakat qiladi (non-blocking tabiati)."""
        uid = int(user_id)
        lock = self.get_lock(uid)
        effective_timeout = self.default_timeout if timeout is None else timeout

        try:
            if effective_timeout <= 0:
                # Instant non-blocking attempt
                if lock.locked():
                    return False
                await lock.acquire()
            else:
                await asyncio.wait_for(lock.acquire(), timeout=effective_timeout)
            self._lock_timestamps[uid] = time.monotonic()
            return True
        except asyncio.TimeoutError:
            logger.debug("UserLock timeout: user=%s (timeout=%.2fs)", uid, effective_timeout)
            return False

    def release(self, user_id: int) -> None:
        """Foydalanuvchi lockini xavfsiz bo'shatadi."""
        uid = int(user_id)
        lock = self._locks.get(uid)
        if lock and lock.locked():
            try:
                lock.release()
            except RuntimeError as e:
                logger.warning("UserLock release xatosi (user=%s): %s", uid, e)
        self._lock_timestamps.pop(uid, None)

    @asynccontextmanager
    async def user_lock(self, user_id: int, timeout: float | None = None):
        """Asinxron kontekst menejeri: lockni oladi va blok tugagach darhol bo'shatadi."""
        uid = int(user_id)
        acquired = await self.acquire(uid, timeout=timeout)
        if not acquired:
            raise UserLockTimeoutError(
                f"Foydalanuvchi {uid} uchun lock band. Qisqa vaqtdan so'ng qayta urinib ko'ring."
            )
        try:
            yield
        finally:
            self.release(uid)

    async def run_with_snapshot(
        self,
        user_id: int,
        snapshot_fn: Callable[[], T],
        async_worker_fn: Callable[[T], Coroutine[Any, Any, R]],
        save_fn: Callable[[R], Any],
        lock_timeout: float = 1.0,
    ) -> R:
        """Snapshot & Non-blocking Worker modeli:

        1. Qisqa lock olinadi -> snapshot_fn() ishga tushadi;
        2. Lock darhol bo'shatiladi;
        3. async_worker_fn(snapshot) mustaqil bajariladi (10-20 soniya kutishda lock ushlab turilmaydi);
        4. Natija kelgach, yana qisqa lock olinadi -> save_fn(result) bajariladi.
        """
        uid = int(user_id)

        # 1-Qadam: Qisqa lock bilan holat snapshot olinadi
        async with self.user_lock(uid, timeout=lock_timeout):
            snapshot_data = snapshot_fn()

        # 2-Qadam: Lock bo'shatilgan holda fonda og'ir AI/worker ishlaydi
        worker_result = await async_worker_fn(snapshot_data)

        # 3-Qadam: Natijani xavfsiz saqlash uchun yana qisqa lock olinadi
        async with self.user_lock(uid, timeout=lock_timeout):
            save_fn(worker_result)

        return worker_result

    def cleanup(self) -> int:
        """Bo'sh turgan locklarni tozalaydi (xotira optimizatsiyasi)."""
        to_delete = [uid for uid, lock in self._locks.items() if not lock.locked()]
        for uid in to_delete:
            self._locks.pop(uid, None)
            self._lock_timestamps.pop(uid, None)
        return len(to_delete)


# Global yagona nusxa
user_lock_manager = UserLockManager()
user_lock = user_lock_manager.user_lock
