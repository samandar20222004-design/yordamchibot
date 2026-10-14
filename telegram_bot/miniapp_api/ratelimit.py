"""Mini App uchun QAT'IY rate limiter (auth himoyasi).

Mavjud ``RateLimiter.hit()`` backend xatosida FAIL-OPEN ishlaydi va
``ResilientCacheBackend`` Redis uzilganda jimgina PROCESS-LOKAL xotira
hisoblagichiga o'tadi. Auth uchun bu qabul qilinmaydi, shuning uchun bu yerda:

  * hisoblagich xatosi -> :class:`ApiError` ``service_unavailable`` (503);
  * ``require_shared=True`` bo'lsa FAQAT sog'lom Redis primary'si ishlatiladi
    (``ResilientCacheBackend.primary``); breaker ochiq / fallback / Redis yo'q ->
    503. Xotira fallback'i hech qachon "umumiy" deb hisoblanmaydi;
  * ``require_shared=False`` (faqat development/test) -> joriy backend (xotira
    bo'lishi mumkin) ishlatiladi, lekin istisno baribir 503.

Hisoblagich: qat'iy "fixed window" (``incr`` + TTL), atomik (Redis Lua).
"""
from __future__ import annotations

import asyncio
import logging
import math

from .errors import ApiError

logger = logging.getLogger(__name__)

KEY_PREFIX = "miniapp:rl"


def shared_primary(backend):
    """Sog'lom UMUMIY (Redis) backend yoki ``None``.

    Faqat haqiqiy holatga tayanadi: backend ``ResilientCacheBackend`` bo'lib,
    primary ``RedisCacheBackend`` va fallback rejimida EMAS (breaker cooldown
    ichida bo'lsa ``using_fallback`` rost -> ``None``). Cooldown o'tgach
    (half-open) primary'ga urinish mumkin: sanagich BARIBIR Redis'ning o'zida
    hisoblanadi (xotirada emas), muvaffaqiyatsiz bo'lsa 503.
    """
    try:
        from services.cache_backend import RedisCacheBackend, ResilientCacheBackend
    except Exception:  # noqa: BLE001
        return None
    if isinstance(backend, RedisCacheBackend):
        return backend
    if isinstance(backend, ResilientCacheBackend):
        primary = backend.primary
        if isinstance(primary, RedisCacheBackend) and not backend.using_fallback:
            return primary
    return None


class StrictLimiter:
    """``max_concurrency`` — bir vaqtda Redis'ga yuboriladigan sanagich chaqiruvlari soni.

    Redis mijozining ulanish pool'i cheklangan (sukut 10, botning o'z limiteri bilan UMUMIY) va to'lganda
    kutmaydi, balki xato beradi — burst (masalan Mini App'ga ommaviy kirish) paytida bu keraksiz 503'larga
    olib keladi. Chaqiruvlar juda qisqa (bitta atomik INCR), shuning uchun ortiqcha so'rovlar bu yerda
    navbatda KUTADI (HTTP timeout chegarasida) va pool'dan kichik son bilan ishlaydi.
    """

    def __init__(self, *, require_shared: bool, backend_getter=None, max_concurrency: int = 4) -> None:
        self._require_shared = bool(require_shared)
        self._get_backend = backend_getter or self._default_backend
        self._gate = asyncio.Semaphore(max(1, int(max_concurrency)))

    @staticmethod
    def _default_backend():
        from services.cache_backend import get_cache_backend

        return get_cache_backend()

    def _counter_backend(self):
        backend = self._get_backend()
        if self._require_shared:
            shared = shared_primary(backend)
            if shared is None:
                raise ApiError("service_unavailable", retry_after=30)
            return shared
        return backend

    async def hit(self, bucket: str, subject: str, *, limit: int, window: float) -> None:
        """Sanagichni oshiradi; chegara oshsa 429, xatoda 503 (hech qachon jim emas)."""
        window_s = max(1, int(math.ceil(window)))
        backend = self._counter_backend()
        key = f"{KEY_PREFIX}:{bucket}:{subject}"
        try:
            async with self._gate:
                count = int(await backend.incr(key, ttl=window_s))
        except Exception as exc:  # noqa: BLE001 — fail-closed
            logger.warning("miniapp rate limiter: sanagich xatosi (%s)", type(exc).__name__)
            raise ApiError("service_unavailable", retry_after=30) from None
        if count > limit:
            raise ApiError("rate_limited", retry_after=window_s)
