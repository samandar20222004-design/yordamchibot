"""RETRY SIYOSATI — PHASE 6 (mustahkamlangan qayta urinish qoidalari).

Audit topilmasi: qayta urinish (retry) logikasi gateway ichida **kod
sifatida** yashiringan edi — ``for attempt in range(2)``:

* 429/timeout/5xx (vaqtinchalik) va "sifatsiz javob" (quality) bir xil
  ko'rilardi va ular orasida **hech qanday kutish (backoff) yo'q** edi —
  ketma-ket ikkita so'rov RPM limitini yana urib, breaker'ni tezroq
  ochardi;
* qayta urinish byudjeti umumiy (fast path) timeout bilan
  bog'lanmagan edi — kichik qolgan vaqtda ham to'liq kutish mumkin edi;
* siyosat test qilinadigan bitta joyda EMAS edi.

Bu modul yagona, deterministik siyosatni beradi:

* :class:`RetryPolicy` — urinishlar soni, jitter'li eksponensial backoff,
  qaysi xato turlari qayta urinishga arziydi;
* faqat **vaqtinchalik** xatolar (rate_limit/timeout/server/network) va
  sifat rad etishlari qayta uriniladi; dasturiy xato (``other``) —
  darhol keyingi provayderga;
* qolgan byudjet (``remaining``) hisobga olinadi — backoff umumiy
  muddatdan oshib ketsa kutish 0 ga tushadi (foydalanuvchi kutmaydi).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, FrozenSet

#: Sifat rad etishlari uchun "koz" turi (xato matni emas — validator belgisi).
KIND_QUALITY = "quality"

#: Vaqtinchalik (qayta urinishga arziydigan) xato turlari — ``health``
#: modulidagi kanonik turlar bilan bir xil satrlar (import sikli yo'q).
RETRYABLE_KINDS: FrozenSet[str] = frozenset({
    "rate_limit", "timeout", "server_error", "network",
})


@dataclass(frozen=True)
class RetryPolicy:
    """Qayta urinish siyosati (deterministik — ``rand`` injeksiya qilinadi)."""

    #: Umumiy urinishlar soni (1 = qayta urinish yo'q).
    max_attempts: int = 2
    #: Kutish bazasi (soniya) — ``base_delay * 2**(attempt-1)``.
    base_delay: float = 0.12
    #: Bitta kutish uchun yuqori chegara (soniya).
    max_delay: float = 0.5
    #: Jitter ulushi (0.0-1.0) — "thundering herd" himoyasi.
    jitter_ratio: float = 0.35
    #: Vaqtinchalik bo'lmagan (dasturiy) xatolar ham qayta urinilsinmi?
    retry_other: bool = False
    #: Sifatsiz javob (validator) uchun qayta urinish (PHASE A bilan bir xil).
    retry_quality: bool = True
    #: Backoff faqat shu vaqtdan ko'p byudjet qolganda qo'llanadi.
    min_remaining_for_backoff: float = 1.0
    #: Qayta uriniladigan turlar.
    retryable_kinds: FrozenSet[str] = field(default_factory=lambda: RETRYABLE_KINDS)

    # ------------------------------------------------------------------ API
    def clip(self) -> "RetryPolicy":
        """Qiymatlarni xavfsiz oynaga keltiradi (manfiy/cheksiz → standart)."""
        return RetryPolicy(
            max_attempts=max(1, min(5, int(self.max_attempts or 1))),
            base_delay=max(0.0, min(5.0, float(self.base_delay or 0.0))),
            max_delay=max(0.0, min(10.0, float(self.max_delay or 0.0))),
            jitter_ratio=max(0.0, min(1.0, float(self.jitter_ratio or 0.0))),
            retry_other=bool(self.retry_other),
            retry_quality=bool(self.retry_quality),
            min_remaining_for_backoff=max(
                0.0, float(self.min_remaining_for_backoff or 0.0)
            ),
            retryable_kinds=frozenset(self.retryable_kinds or RETRYABLE_KINDS),
        )

    def should_retry(self, attempts_done: int, kind: str | None = None) -> bool:
        """``attempts_done`` urinishdan keyin yana urinish kerakmi?"""
        policy = self.clip()
        if int(attempts_done) >= policy.max_attempts:
            return False
        if kind == KIND_QUALITY:
            return policy.retry_quality
        if kind in policy.retryable_kinds:
            return True
        return policy.retry_other

    def delay_for(
        self,
        attempts_done: int,
        *,
        remaining: float | None = None,
        rand: Callable[[], float] | None = None,
    ) -> float:
        """Backoff kutish vaqti (soniya) — byudjetga moslashtirilgan."""
        policy = self.clip()
        wait = min(policy.max_delay, policy.base_delay * (2 ** max(0, int(attempts_done) - 1)))
        if wait <= 0:
            return 0.0
        noise = (rand or random.random)()
        noise = 0.0 if noise is None else max(0.0, min(1.0, float(noise)))
        wait = wait * (1.0 + policy.jitter_ratio * (noise * 2.0 - 1.0))
        wait = max(0.0, min(policy.max_delay, wait))
        if remaining is not None:
            budget = float(remaining) - policy.min_remaining_for_backoff
            if budget <= 0:
                return 0.0
            wait = min(wait, budget)
        return round(wait, 4)


#: Standart siyosat: 1 urinish + 1 retry (PHASE A qoidasi: AYNAN 2 chaqiruv).
DEFAULT_RETRY_POLICY = RetryPolicy()

#: Qayta urinishsiz siyosat (testlar/ops uchun).
NO_RETRY_POLICY = RetryPolicy(max_attempts=1, base_delay=0.0, retry_quality=False)


def policy_for(lane: str | None = None) -> RetryPolicy:
    """Lane bo'yicha siyosat.

    FAST (foydalanuvchi kutishi eng qimmat) — kutishsiz, 2 urinish;
    QUALITY/REASONING/VISION — jitter'li backoff bilan 2 urinish.
    """
    name = str(getattr(lane, "value", lane) or "").upper()
    if name == "FAST":
        return RetryPolicy(base_delay=0.0, max_delay=0.0, jitter_ratio=0.0)
    return DEFAULT_RETRY_POLICY


__all__ = [
    "KIND_QUALITY",
    "RETRYABLE_KINDS",
    "RetryPolicy",
    "DEFAULT_RETRY_POLICY",
    "NO_RETRY_POLICY",
    "policy_for",
]
