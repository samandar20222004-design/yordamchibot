"""Mini App uchun FAQAT-O'QISH DB ijrochisi.

Muhim cheklovlar (kod izohi va hujjat bilan mos):

  * ``db.run_db`` ``asyncio.to_thread`` ishlatadi: HTTP javob timeout'i (yoki
    mijoz uzilishi) kutishni BEKOR QILADI, lekin thread va unda ketayotgan SQL
    so'rovi o'zi to'xtamaydi — ulanish so'rov tugaguncha band qoladi.
    Haqiqiy to'xtatish faqat server tomonida: ``SET LOCAL statement_timeout``;
  * ``SET LOCAL`` autocommit rejimida ta'sirsiz. Shu sababli ``db_transaction(
    commit=False, readonly=True)`` ishlatiladi (u ``fast_read``ni o'chiradi, aniq
    ``BEGIN`` + ``SET LOCAL TRANSACTION READ ONLY`` beradi). ``SET LOCAL``
    tranzaksiya tugashi bilan (ROLLBACK) yo'qoladi va pool'ga qaytayotgan
    ulanishga O'TMAYDI. Mavjud bot so'rovlariga global timeout O'RNATILMAYDI;
  * parallel so'rovlar soni ``asyncio.Semaphore`` bilan cheklanadi va u THREAD tugaganda
    bo'shatiladi (kutish bekor qilinganda emas) — shu tariqa pool resurslari haqiqatan
    himoyalanadi. Burst (masalan ommaviy kirish) paytida ortiqcha so'rovlar darhol 503
    olmaydi: ular cheklangan navbatda (``queue_wait_seconds``, ``max_queue``) kutadi, navbat
    to'lsa yoki kutish tugasa — tez 503. Real PostgreSQL bilan o'lchangan: 20 parallel so'rovda
    navbatsiz faqat 4 tasi o'tgan, 16 tasi 503 bergan;
  * xato HECH QACHON bo'sh natijaga aylantirilmaydi: istisno -> 503.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from .errors import ApiError

logger = logging.getLogger(__name__)


def _default_tx_factory():
    import database as db  # kech import: testlarda almashtiriladi

    return db.db_transaction(commit=False, readonly=True)


class ReadOnlyRunner:
    def __init__(self, *, statement_timeout_ms: int, max_inflight: int,
                 tx_factory=None, queue_wait_seconds: float = 2.0, max_queue: int = 64) -> None:
        self._timeout_ms = int(statement_timeout_ms)
        self._gate = asyncio.Semaphore(max(1, int(max_inflight)))
        self._queue_wait = max(0.0, float(queue_wait_seconds))
        self._max_queue = max(0, int(max_queue))
        self._waiting = 0
        self._tx_factory = tx_factory or _default_tx_factory
        self._inflight = 0
        self._lock = threading.Lock()

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight

    @property
    def waiting(self) -> int:
        return self._waiting

    def _work(self, fn, loop):
        try:
            with self._lock:
                self._inflight += 1
            with self._tx_factory() as cur:
                # int() — SQL in'ektsiyasiz; faqat shu tranzaksiya uchun.
                cur.execute(f"SET LOCAL statement_timeout = {int(self._timeout_ms)}")
                cur.execute(f"SET LOCAL lock_timeout = {int(self._timeout_ms)}")
                return fn(cur)
        finally:
            with self._lock:
                self._inflight -= 1
            try:
                loop.call_soon_threadsafe(self._gate.release)  # slot THREAD tugaganda bo'shaydi
            except RuntimeError:
                pass  # event loop yopilgan (o'chirilish paytida)

    async def _admit(self) -> bool:
        """Slot oladi: bo'sh bo'lsa darhol, aks holda cheklangan navbatda kutadi."""
        if not self._gate.locked():
            await self._gate.acquire()
            return True
        if self._waiting >= self._max_queue or self._queue_wait <= 0:
            return False
        self._waiting += 1
        try:
            await asyncio.wait_for(self._gate.acquire(), self._queue_wait)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._waiting -= 1

    async def run(self, fn):
        """``fn(cur)`` ni read-only tranzaksiyada thread'da bajaradi."""
        if not await self._admit():
            raise ApiError("service_unavailable", retry_after=2)
        loop = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(None, self._work, fn, loop)
        except BaseException:
            self._gate.release()  # thread boshlanmadi
            raise
        try:
            return await future
        except ApiError:
            raise
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — DB xatosi bo'sh ma'lumotga AYLANMAYDI
            # Faqat sinf nomi: istisno matni SQL/qiymat saqlashi mumkin.
            logger.warning("miniapp db: so'rov xatosi (%s)", type(exc).__name__)
            raise ApiError("service_unavailable", retry_after=5) from None
