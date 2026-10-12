"""AI Task Concurrency, Bounded Queue & Request Cancellation.

AI Concurrency, User Lock, Bounded Queue va Request Cancellation (13, 14, 15, 16-bandlar).

1. Bounded AI Queue & Rate Limit (13, 16-bandlar):
   - MAX_AI_CONCURRENCY (bir vaqtda ishlaydigan so'rovlar limiti)
   - MAX_AI_QUEUE (kutish navbati sig'imi)
   - Agar navbat to'lib ketgan bo'lsa (QueueFull), fail-closed: foydalanuvchiga muloyim
     xabar qaytariladi: "⏳ AI hozir juda band. Bir necha soniyadan keyin qayta urinib ko'ring."

2. Request Cancellation:
   - Har bir AI generatsiyasiga unikal generation_id beriladi.
   - Foydalanuvchi "❌ Bekor qilish" bosganda orqa fondagi so'rov asyncio.Task.cancel() qilinadi.
   - Kechikib kelgan natija foydalanuvchiga YUBORILMAYDI va kvota refund_ai_request orqali
     to'liq qaytariladi.
"""

from __future__ import annotations
import asyncio
import logging
import os
import uuid
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Konfiguratsiya: muhit o'zgaruvchilari yoki xavfsiz standartlar
MAX_AI_CONCURRENCY = int(os.getenv("MAX_AI_CONCURRENCY", "5"))
MAX_AI_QUEUE = int(os.getenv("MAX_AI_QUEUE", "20"))
AI_QUEUE_TIMEOUT = float(os.getenv("AI_QUEUE_TIMEOUT", "30.0"))


class AIQueueFullError(RuntimeError):
    """AI navbati to'lganida yuzaga keladigan xatolik (fail-closed)."""

    def __init__(self, message: str | None = None, lang: str = "uz"):
        self.lang = lang
        msg = message or get_queue_full_message(lang)
        super().__init__(msg)


class AITaskCancelledError(asyncio.CancelledError):
    """Foydalanuvchi tomonidan bekor qilingan AI vazifasi."""
    pass


class AIQueueTimeoutError(TimeoutError):
    """Navbatda ruxsat kutish vaqti tugadi."""
    pass


def get_queue_full_message(lang: str = "uz") -> str:
    """Tillar bo'yicha navbat to'lganligi haqida muloyim xabar."""
    code = (lang or "uz").lower()
    if code == "ru":
        return "⏳ AI сейчас очень занят. Пожалуйста, повторите попытку через несколько секунд."
    if code == "en":
        return "⏳ AI is currently very busy. Please try again in a few seconds."
    return "⏳ AI hozir juda band. Bir necha soniyadan keyin qayta urinib ko'ring."


class AIConcurrencyManager:
    """Yagona AI Concurrency, Bounded Queue va Task Cancellation menejeri."""

    def __init__(
        self,
        max_concurrency: int = MAX_AI_CONCURRENCY,
        max_queue: int = MAX_AI_QUEUE,
        queue_timeout: float = AI_QUEUE_TIMEOUT,
    ):
        self.max_concurrency = max(1, max_concurrency)
        self.max_queue = max(1, max_queue)
        self.queue_timeout = queue_timeout

        self._semaphore = asyncio.Semaphore(self.max_concurrency)
        self._active_slots = 0
        self._waiting_count = 0

        # user_id -> {generation_id: asyncio.Task}
        self._user_tasks: dict[int, dict[str, asyncio.Task]] = {}
        # generation_id -> (user_id, reservation_id, db_module)
        self._task_metadata: dict[str, tuple[int, int | None, Any]] = {}
        # Bekor qilingan generatsiyalar to'plami (kechikkan natijalarni filtrlash uchun)
        self._cancelled_generations: set[str] = set()
        # Qaytarilgan kvotalar to'plami (idempotent refund)
        self._refunded_reservations: set[int] = set()

    @staticmethod
    def generate_id(user_id: int) -> str:
        """Har bir generatsiyaga unikal generation_id yaratadi."""
        return f"gen_{user_id}_{uuid.uuid4().hex[:10]}"

    @property
    def waiting_count(self) -> int:
        """Hozir navbatda turgan so'rovlar soni."""
        return self._waiting_count

    @property
    def active_count(self) -> int:
        """Hozir ishlayotgan parallel so'rovlar soni."""
        return self._active_slots

    def get_status(self) -> dict[str, Any]:
        """Tizim monitoringi uchun holat hisoboti."""
        return {
            "active_slots": self._active_slots,
            "max_concurrency": self.max_concurrency,
            "waiting_queue": self._waiting_count,
            "max_queue": self.max_queue,
            "tracked_users": len(self._user_tasks),
        }

    def register_task(
        self,
        user_id: int,
        generation_id: str,
        task: asyncio.Task,
        reservation_id: int | None = None,
        db_module: Any = None,
    ) -> None:
        """AI taskni ro'yxatga oladi."""
        uid = int(user_id)
        if uid not in self._user_tasks:
            self._user_tasks[uid] = {}
        self._user_tasks[uid][generation_id] = task
        self._task_metadata[generation_id] = (uid, reservation_id, db_module)

    def unregister_task(self, user_id: int, generation_id: str) -> None:
        """AI taskni ro'yxatdan chiqaradi."""
        uid = int(user_id)
        if uid in self._user_tasks:
            self._user_tasks[uid].pop(generation_id, None)
            if not self._user_tasks[uid]:
                self._user_tasks.pop(uid, None)
        self._task_metadata.pop(generation_id, None)
        self._cancelled_generations.discard(generation_id)

    def is_cancelled(self, generation_id: str) -> bool:
        """Generatsiya bekor qilinganligini tekshiradi."""
        return generation_id in self._cancelled_generations

    async def _handle_refund(self, user_id: int, reservation_id: int | None, db_module: Any) -> bool:
        """Bekor qilingan yoki xato bergan generatsiya uchun kvotani qaytarish (fail-closed, idempotent)."""
        if not reservation_id or not user_id:
            return False
        if reservation_id in self._refunded_reservations:
            return True
        self._refunded_reservations.add(reservation_id)
        try:
            db = db_module
            if db is None:
                import database as db
            from services.ai_quota import release_ai_quota
            res = await release_ai_quota(db, user_id, reservation_id)
            logger.info("Task bekor qilingani sababli kvota qaytarildi: user=%s, res_id=%s, result=%s",
                        user_id, reservation_id, res)
            return True
        except Exception as e:
            logger.error("Bekor qilingan task kvotasini qaytarishda xatolik: %s", e)
            return False

    async def cancel_user_requests(self, user_id: int, reason: str = "user_cancelled") -> int:
        """Foydalanuvchining barcha faol AI tasklarini bekor qiladi va kvotasini qaytaradi."""
        uid = int(user_id)
        tasks_map = self._user_tasks.get(uid, {})
        if not tasks_map:
            return 0

        cancelled_count = 0
        to_cancel = list(tasks_map.items())

        for gen_id, task in to_cancel:
            self._cancelled_generations.add(gen_id)
            meta = self._task_metadata.get(gen_id)
            if meta:
                _, res_id, db_mod = meta
                if res_id:
                    # Kvotani darhol qaytarish
                    await self._handle_refund(uid, res_id, db_mod)

            if not task.done():
                logger.info("AI so'rovi bekor qilinmoqda: user=%s, gen_id=%s, sabab=%s", uid, gen_id, reason)
                task.cancel()
                cancelled_count += 1

        return cancelled_count

    async def run_with_queue(
        self,
        user_id: int,
        coro_fn: Callable[[], Coroutine[Any, Any, T]],
        generation_id: str | None = None,
        reservation_id: int | None = None,
        db_module: Any = None,
        lang: str = "uz",
    ) -> T:
        """Vazifani Bounded Queue va Concurrency Semaphore orqali xavfsiz boshqaradi."""
        uid = int(user_id)
        gen_id = generation_id or self.generate_id(uid)

        # 1. Bounded Queue tekshiruvi (agar navbat to'lgan bo'lsa darhol fail-closed rad etish)
        if self._waiting_count >= self.max_queue:
            logger.warning("AI Queue to'ldi: waiting=%s >= max=%s (user=%s)",
                           self._waiting_count, self.max_queue, uid)
            raise AIQueueFullError(lang=lang)

        self._waiting_count += 1
        current_task = asyncio.current_task()
        if current_task:
            self.register_task(uid, gen_id, current_task, reservation_id, db_module)

        try:
            # 2. Semafor uchun navbatda kutish
            try:
                await asyncio.wait_for(self._semaphore.acquire(), timeout=self.queue_timeout)
            except asyncio.TimeoutError:
                logger.warning("AI Queue kutish vaqti tugadi (user=%s, gen_id=%s)", uid, gen_id)
                await self._handle_refund(uid, reservation_id, db_module)
                raise AIQueueTimeoutError("Navbatda kutish vaqti tugadi.")
        finally:
            self._waiting_count -= 1

        self._active_slots += 1
        try:
            # Agar kutish davomida foydalanuvchi bekor qilishni bosgan bo'lsa
            if gen_id in self._cancelled_generations:
                logger.info("Kutish vaqtida bekor qilingan task bajarilmadi (gen_id=%s)", gen_id)
                await self._handle_refund(uid, reservation_id, db_module)
                raise AITaskCancelledError("So'rov bekor qilindi.")

            # 3. AI vazifasini bajarish
            result = await coro_fn()

            # 4. Agar javob kechikib kelgan bo'lsa va task bekor qilingan bo'lsa
            if gen_id in self._cancelled_generations:
                logger.info("Kechikkan natija rad etildi va kvota qaytarildi (gen_id=%s)", gen_id)
                await self._handle_refund(uid, reservation_id, db_module)
                raise AITaskCancelledError("So'rov bekor qilindi.")

            return result

        except asyncio.CancelledError:
            logger.info("AI Task bekor qilindi (user=%s, gen_id=%s)", uid, gen_id)
            self._cancelled_generations.add(gen_id)
            await self._handle_refund(uid, reservation_id, db_module)
            raise AITaskCancelledError("So'rov bekor qilindi.")

        finally:
            self._active_slots -= 1
            self._semaphore.release()
            self.unregister_task(uid, gen_id)


# ---------------------------------------------------------------------------
# HAR FOYDALANUVCHI UCHUN FAOL AI JOBLAR LIMITI
# ---------------------------------------------------------------------------
#: Bir foydalanuvchining bir vaqtdagi faol LLM generatsiyalari (standart 2).
#: Global semafor (``MAX_AI_CONCURRENCY``) bitta foydalanuvchini boshqalardan
#: ajratmaydi — bitta foydalanuvchi navbatni egallab qo'ymasin deb shu limit.
AI_USER_MAX_CONCURRENT_JOBS = max(1, int(os.getenv("AI_USER_MAX_CONCURRENT_JOBS", "2")))


class UserJobGate:
    """Foydalanuvchi kesimida faol AI joblar soni (fail-fast, navbatsiz).

    Limitga yetgan foydalanuvchining yangi so'rovi DARHOL rad etiladi (kutib
    turmaydi): chaqiruvchi ``try_acquire`` → ``False`` olganda AI chaqirmaydi
    va kvota refund qilinadi. ``release`` har doim ``finally`` da chaqiriladi.
    Thread-safe (blok qisqa, faqat dict yangilanadi).
    """

    def __init__(self, max_per_user: int | None = None) -> None:
        import threading

        self.max_per_user = max(1, int(max_per_user or AI_USER_MAX_CONCURRENT_JOBS))
        self._lock = threading.Lock()
        self._active: dict[int, int] = {}
        self.rejected = 0

    def active(self, user_id) -> int:
        """Foydalanuvchining hozirgi faol joblar soni."""
        if user_id is None:
            return 0
        with self._lock:
            return self._active.get(int(user_id), 0)

    def try_acquire(self, user_id) -> bool:
        """Slot olishga urinadi; limit to'lgan bo'lsa ``False``."""
        if user_id is None:
            return True
        uid = int(user_id)
        with self._lock:
            current = self._active.get(uid, 0)
            if current >= self.max_per_user:
                self.rejected += 1
                return False
            self._active[uid] = current + 1
            return True

    def release(self, user_id) -> None:
        """Slotni bo'shatadi (ortiqcha chaqiruv xavfsiz — manfiy bo'lmaydi)."""
        if user_id is None:
            return
        uid = int(user_id)
        with self._lock:
            current = self._active.get(uid, 0)
            if current <= 1:
                self._active.pop(uid, None)
            else:
                self._active[uid] = current - 1

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "max_per_user": self.max_per_user,
                "tracked_users": len(self._active),
                "active_jobs": sum(self._active.values()),
                "rejected": self.rejected,
            }


_user_job_gate = UserJobGate()


def default_user_gate() -> UserJobGate:
    """Jarayon bo'yicha yagona foydalanuvchi-job gate'i."""
    return _user_job_gate


def user_busy_message(lang: str = "uz") -> str:
    """Foydalanuvchi limiti to'lganda — mavjud «AI band» matni (yangi matn yo'q)."""
    return get_queue_full_message(lang)


# Global yagona Concurrency menejeri
ai_concurrency_manager = AIConcurrencyManager()
