"""Promo-kod: noto'g'ri urinishlar limiti (kod taxmin qilib topishga qarshi).

Foydalanuvchi bo'yicha oynada (``WINDOW_SECONDS``) ``MAX_FAILS`` ta xato bo'lsa, keyingi urinishlar DB'ga TEGMASDAN
rad etiladi, eng eski xato oynadan chiqquncha. Muvaffaqiyatli faollashtirish hisoblagichni nolga qaytaradi.

Cheklov (ataylab): hisoblagich jarayon xotirasida; bir nechta instance'da har biri o'zini sanaydi, qayta ishga tushirishda
nolga tushadi. Bu qo'shimcha to'siq: asosiy himoya — umumiy rate limiter va kodlarning uzunligi/cheklangan ishlatilishi.
Xotira chegaralangan (``MAX_TRACKED`` foydalanuvchi).
"""
from __future__ import annotations

import time
from collections import deque

MAX_FAILS = 5
WINDOW_SECONDS = 600
MAX_TRACKED = 5000


class PromoAttemptLimiter:
    def __init__(self, max_fails: int = MAX_FAILS, window: int = WINDOW_SECONDS,
                 max_tracked: int = MAX_TRACKED, clock=time.monotonic):
        self.max_fails = max_fails
        self.window = window
        self.max_tracked = max_tracked
        self._clock = clock
        self._fails: dict[int, deque] = {}

    def _prune(self, user_id: int, now: float) -> deque | None:
        q = self._fails.get(user_id)
        if q is None:
            return None
        while q and now - q[0] >= self.window:
            q.popleft()
        if not q:
            del self._fails[user_id]
            return None
        return q

    def retry_after(self, user_id: int) -> int:
        """Necha soniyadan keyin yana urinish mumkin (0 = hozir mumkin)."""
        now = self._clock()
        q = self._prune(user_id, now)
        if q is None or len(q) < self.max_fails:
            return 0
        return max(1, int(self.window - (now - q[0])) + 1)

    def record_failure(self, user_id: int) -> None:
        now = self._clock()
        if user_id not in self._fails and len(self._fails) >= self.max_tracked:
            for uid in list(self._fails):          # avval muddati o'tganlarni tozalaymiz
                self._prune(uid, now)
            while len(self._fails) >= self.max_tracked:   # hamon to'la: eng eskisini chiqaramiz
                self._fails.pop(next(iter(self._fails)))
        q = self._fails.setdefault(user_id, deque())
        q.append(now)
        while len(q) > self.max_fails:
            q.popleft()

    def reset(self, user_id: int) -> None:
        self._fails.pop(user_id, None)


promo_limiter = PromoAttemptLimiter()
