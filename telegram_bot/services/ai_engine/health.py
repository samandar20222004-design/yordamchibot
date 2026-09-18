"""Provider Health — Circuit Breaker (AI ENGINE V2, Faza 1).

Audit topilmasi: provayder sog'lig'i ikki joyda nazorat qilinar edi —
``utils/ai_agent.py`` dagi modul-darajadagi ``_BREAKERS`` lug'ati va
hech qanday umumiy holat yo'q edi. Yangi kanonik shlyuz uchun bitta
mazali Circuit Breaker kerak:

* **429 (rate limit), timeout, 5xx va tarmoq xatolarini** ajratib kuzatadi
  (:func:`classify_exception`);
* ketma-ket xatolar soni chegarraga yetganda provayderni VAQTINCHA ochadi
  (cooldown davomida so'rov yuborilmaydi — RPM/tilt himoyasi);
* ``healthy_order`` — sog'lom provayderlar RO'YXAT BOSHINGA chiqadi
  (avto-fallback sog'lom provayderga birinchi bo'lib o'tadi);
* muvaffaqiyatli javob breaker'ni tozalaydi (half-open prob o'z-o'zidan).

MUHIM (yagona manba siyosati — hech narsa noldan yozilmaydi): monitor
holatini eski ``utils/ai_agent._BREAKERS`` lug'atiga ham MIRROR qiladi
(xuddi shu ``{"fails": int, "until": float}`` shaklida). Shu tufayli
legacy zanjir (``services.ai_service.AIFallbackService``) va yangi gateway
BITTA sog'liq holatini ko'radi — provayder gateway tomonidan "ochilsa",
legacy zanjir ham uni cooldown'da o'tkazib yuboradi.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sozlash (ENV — .env.example'da hujjatlangan; chaqiruv paytida o'qiladi).
# ---------------------------------------------------------------------------
#: Ketma-ket nechta xatodan keyin breaker ochiladi (legacy BREAKER_THRESHOLD).
def breaker_threshold() -> int:
    try:
        return max(1, int(os.getenv("AI_BREAKER_THRESHOLD", "3")))
    except (TypeError, ValueError):
        return 3


#: Breaker ochilgan holat necha soniya davom etadi (legacy BREAKER_COOLDOWN).
def breaker_cooldown() -> float:
    try:
        return max(1.0, float(os.getenv("AI_BREAKER_COOLDOWN", "600")))
    except (TypeError, ValueError):
        return 600.0


# ---------------------------------------------------------------------------
# Xato turlari
# ---------------------------------------------------------------------------
FAILURE_RATE_LIMIT = "rate_limit"   # 429 / RPM / quota
FAILURE_TIMEOUT = "timeout"         # connect/read/total timeout
FAILURE_SERVER = "server_error"     # 5xx
FAILURE_NETWORK = "network"         # DNS/connection reset/SSLError ...
FAILURE_OTHER = "other"

_MARKERS = {
    FAILURE_RATE_LIMIT: ("429", "rate limit", "ratelimit", "quota", "too many requests"),
    FAILURE_TIMEOUT: ("timeout", "timed out", "deadline"),
    FAILURE_SERVER: ("500", "502", "503", "504", "internal error", "bad gateway",
                     "service unavailable", "server error"),
    FAILURE_NETWORK: ("network", "connection", "connect", "ssl", "dns", "reset"),
}


def classify_exception(exc: BaseException | str | None) -> str:
    """Istisno/xato matnini kanonik xato turiga aylantiradi (hech qachon yiqilmaydi)."""
    if exc is None:
        return FAILURE_OTHER
    if isinstance(exc, TimeoutError):
        return FAILURE_TIMEOUT
    try:
        import asyncio

        if isinstance(exc, asyncio.TimeoutError):
            return FAILURE_TIMEOUT
    except Exception:  # pragma: no cover — asyncio har doim bor
        pass
    text = str(exc).lower()
    # Tartib muhim: 429 "500" belgisini o'z ichiga olmaydi, lekin timeout
    # matnida boshqa raqamlar bo'lishi mumkin — avval maxsus turlar.
    for kind in (FAILURE_RATE_LIMIT, FAILURE_TIMEOUT, FAILURE_SERVER, FAILURE_NETWORK):
        for marker in _MARKERS[kind]:
            if marker in text:
                return kind
    return FAILURE_OTHER


@dataclass
class BreakerState:
    """Bitta provayderning sog'liq holati."""

    fails: int = 0                       # ketma-ket xatolar (ochiq bo'lmasa)
    open_until: float = 0.0              # ochiq bo'lsa — cooldown tugash vaqti
    last_error: str = ""                 # oxirgi xato (qisqa, log uchun)
    last_error_kind: str = ""            # oxirgi xato turi
    opened_count: int = 0                # necha marta ochilgan (umrbod)
    total_failures: int = 0              # jami xatolar (umrbod)
    total_successes: int = 0             # jami muvaffaqiyatlar (umrbod)
    last_transition: float = field(default_factory=time.time)

    @property
    def open(self) -> bool:
        return bool(self.open_until) and time.time() < self.open_until

    def to_dict(self) -> dict:
        return {
            "fails": self.fails,
            "open": self.open,
            "open_until": self.open_until,
            "last_error": self.last_error,
            "last_error_kind": self.last_error_kind,
            "opened_count": self.opened_count,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
        }


class ProviderHealthMonitor:
    """Yagona Circuit Breaker / provayder sog'lig'i monitori.

    Parametrlar legacy ``ai_agent.BREAKER_THRESHOLD/BREAKER_COOLDOWN``
    standartlari bilan bir xil (3 xato → 600s cooldown) — ikki tizim
    bir xil siyosatda yashaydi.
    """

    def __init__(self, threshold: int | None = None, cooldown: float | None = None):
        self.threshold = int(threshold or breaker_threshold())
        self.cooldown = float(cooldown or breaker_cooldown())
        self._states: dict[str, BreakerState] = {}

    # ------------------------------------------------------------- o'qish
    def state(self, name: str) -> BreakerState:
        return self._states.setdefault(name, BreakerState())

    def is_open(self, name: str) -> bool:
        """Provayder cooldown'dami (so'rov yuborilmasligi kerakmi)?"""
        return self.state(name).open

    def healthy_order(self, names: Iterable[str]) -> list[str]:
        """Sog'lom provayderlar BOSHIDA bo'lgan tartib (avto-fallback).

        Ochiq breaker'li provayderlar ro'yxat OXIRIGA suriladi (agar barcha
        ochiq bo'lsa — eng kam xatolisi birinchi sinovga chiqadi, ya'ni
        to'liq bloklanish yo'q).
        """
        healthy: list[str] = []
        degraded: list[str] = []
        for name in names:
            (healthy if not self.is_open(name) else degraded).append(name)
        return healthy + degraded

    def snapshot(self) -> dict[str, dict]:
        """Barcha provayderlar holati (admin diagnostikasi/testlar uchun)."""
        return {name: st.to_dict() for name, st in self._states.items()}

    # ------------------------------------------------------------ yozish
    def record_success(self, name: str) -> None:
        """Muvaffaqiyat — breaker tozalanadi (half-open yopiladi)."""
        st = self._states.get(name)
        if st is None:
            st = BreakerState()
            self._states[name] = st
        st.total_successes += 1
        if st.fails or st.open_until:
            st.fails = 0
            st.open_until = 0.0
            st.last_transition = time.time()
            logger.debug("Circuit breaker: %s tiklandi", name)
        self._mirror_legacy(name)

    def record_failure(self, name: str, kind: str = FAILURE_OTHER, detail: str = "") -> str:
        """Xato qayd etiladi; chegarraga yetsa breaker OCHILADI.

        Returns: ``"open"`` (breaker endi ochildi) | ``"counting"`` | ``"cooldown_reset"``.
        """
        now = time.time()
        st = self.state(name)
        if st.open_until and now > st.open_until:
            # Cooldown tugagan — half-open: yangi hisobdan boshlaymiz.
            st.fails = 0
            st.open_until = 0.0
        st.total_failures += 1
        st.fails += 1
        st.last_error = str(detail or kind)[:200]
        st.last_error_kind = kind or FAILURE_OTHER
        st.last_transition = now
        outcome = "counting"
        if st.fails >= self.threshold:
            st.open_until = now + self.cooldown
            st.opened_count += 1
            st.fails = 0
            outcome = "open"
            logger.warning(
                "Circuit breaker: %s %ss ga o'tkazib yuboriladi (%s marta ketma-ket "
                "xato, oxirgi: %s)", name, int(self.cooldown), self.threshold,
                st.last_error)
        self._mirror_legacy(name)
        return outcome

    def reset(self, name: str | None = None) -> None:
        """Holatni tozalaydi (testlar/admin) — legacy mirror ham tozalanadi."""
        if name is None:
            names = list(self._states)
            self._states.clear()
            for cleared in names:
                self._mirror_legacy(cleared)
        else:
            self._states.pop(name, None)
            self._mirror_legacy(name)

    # -------------------------------------------------- legacy mirror
    def _mirror_legacy(self, name: str | None) -> None:
        """Holatni ``utils.ai_agent._BREAKERS`` ga aks qiladi (yagona manba).

        Legacy shakl: ``{"fails": int, "until": float}`` —
        ``ai_agent._breaker_open/fail/success`` aynan shu bilan ishlaydi.
        Import xatosi (masalan, izolyatsiyalangan test muhiti) jim
        o'tkazib yuboriladi — mirror ixtiyoriy optimizatsiya.
        """
        if not name:
            return
        try:
            from utils import ai_agent as _aa

            legacy = getattr(_aa, "_BREAKERS", None)
            if legacy is None:
                return
            st = self._states.get(name)
            if st is None or (not st.fails and not st.open_until):
                legacy.pop(name, None)
            else:
                legacy[name] = {"fails": int(st.fails), "until": float(st.open_until)}
        except Exception:  # pragma: no cover — mirror majburiy emas
            pass


# ---------------------------------------------------------------------------
# Yagona singleton (gateway ishlatadi; testlar reset qilishi mumkin).
# ---------------------------------------------------------------------------
_default_monitor: ProviderHealthMonitor | None = None


def default_health_monitor() -> ProviderHealthMonitor:
    """Global monitor (birinchi chaqiruvda quriladi)."""
    global _default_monitor
    if _default_monitor is None:
        _default_monitor = ProviderHealthMonitor()
    return _default_monitor


def reset_health_monitor() -> ProviderHealthMonitor:
    """Testlar uchun: monitorni qayta quradi va yangisini qaytaradi."""
    global _default_monitor
    _default_monitor = ProviderHealthMonitor()
    return _default_monitor


__all__ = [
    "BreakerState",
    "ProviderHealthMonitor",
    "classify_exception",
    "default_health_monitor",
    "reset_health_monitor",
    "breaker_threshold",
    "breaker_cooldown",
    "FAILURE_RATE_LIMIT",
    "FAILURE_TIMEOUT",
    "FAILURE_SERVER",
    "FAILURE_NETWORK",
    "FAILURE_OTHER",
]
