"""PHASE 2 · State & Cache Adapter — Redis ⇄ In-Memory (ixtiyoriy ulanish).

Muammo (multi-instance arxitekturasi):
  * Rate limitlar, "menu bosildi" holatlari va boshqa nozik holatlar bir
    instance ichidagi ``dict`` larda saqlanardi (``utils/helpers.py``) —
    Render/Docker'da ikkita instance ishlatilganda bir foydalanuvchining
    harakati BIRLIKKA tegib kelmasdi (ko'p instance = ko'p eshik);
  * Butun ``_USER_HISTORY.clear()`` kabi "global tozalash" barcha
    foydalanuvchilarning holatini bir vaqtda yo'q qilardi — bitta
    flood-tozalash boshqa odamlar chegarasini buzardi.

Yechim — bu modul:
  1. **Yagona interfeys** (:class:`CacheBackend`): ``get`` / ``set`` /
     ``delete`` / ``incr`` / ``expire`` — barcha qiymatlar STRING
     (``int`` hisoblagich ham string ko'rinishida saqlanadi, Redis bilan
     bir xil), TTL soniyada;
  2. **Redis backend** (:class:`RedisCacheBackend`) — ``REDIS_ENABLED`` +
     ``REDIS_URL`` bo'lsa va ulanish muvaffaqiyatli bo'lsa, holat
     butun instance'lar arasida UMUMIY bo'ladi (multi-instance uchun);
  3. **In-Memory backend** (:class:`MemoryCacheBackend`) — Redis yo'q/
     o'chirilgan bo'lsa yoki **uzilib qolsa** avtomatik ishlatiladi.
     Thread-xavfsiz, TTL + LRU + ``max_entries``/``max_value_bytes``/
     ``max_total_bytes`` chegaralari bilan (Render 512 MB RAM himoyasi);
  4. **Circuit Breaker / graceful degradation**
     (:class:`ResilientCacheBackend`) — Redis xatosi yoki timeout'ida
     bot QULAMASDAN avtomatik In-Memory fallback rejimiga o'tadi;
     ``failure_threshold`` ta ketma-ket xatodan keyin breaker OCHILADI
     (Redisga urinish to'xtaydi) va ``cooldown`` sekunddan keyin
     yarim-ochiq (half-open) holatda bitta «probes» bilan tiklanadi.

Redis paketi (``redis``) **ixtiyoriy** — o'rnatilmagan bo'lsa yoki
``REDIS_URL`` bo'sh bo'lsa tizim butunlay In-Memory rejimda ishlaydi
(degraded emas, shunchaki state instance ichida qoladi).

Foydalanish::

    from services import cache_backend as cb

    backend = await cb.init_cache_backend()      # main.py da bir marta
    await backend.set("rl:message:42", "1", ttl=1.0)
    await backend.incr("rl:message:42", ttl=1.0)  # -> 2

Hech qanday metod hech qachon istisno ko'tarmaydi (Redis nosozligi
ham ``ResilientCacheBackend`` ichida yumshatiladi) — bu qatlam bot
ishining uzluksizligini kafolatlaydi.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import logging
import threading
import time
from collections import OrderedDict
from typing import Any

logger = logging.getLogger(__name__)

#: Barcha kalitlar ostidagi umumiy prefiks (Redis'ning boshqa ilovalar
#: bilan to'qnashmasligi uchun).
DEFAULT_KEY_PREFIX = "postassist"

#: TTL cheklari: ``None``/0 = muddatsiz, juda kichik = 1s, juda katta = 1 hafta.
MIN_TTL_SECONDS = 1
MAX_TTL_SECONDS = 7 * 24 * 3600

#: Xotira himoyasi (Render free-tier = 512 MB).
DEFAULT_MAX_ENTRIES = 20000
DEFAULT_MAX_VALUE_BYTES = 64 * 1024
DEFAULT_MAX_TOTAL_BYTES = 32 * 1024 * 1024

#: Circuit breaker standartlari.
DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 30.0

#: Redis ulanish tekshiruvining maksimal vaqti (soniya) — bot startini
#: sekinlashtirmaslik uchun qisqa.
DEFAULT_CONNECT_TIMEOUT = 2.0


class CacheUnavailableError(RuntimeError):
    """Backend vaqtincha ishlamayapti (Redis uzildi / paket yo'q / timeout)."""


def _coerce_ttl(ttl: Any) -> int | None:
    """TTL ni Redis-compatible butun soniyaga aylantiradi.

    ``None`` yoki ``<= 0`` → ``None`` (muddatsiz). ``0.4`` → ``1``
    (keshni darhol o'chirib yubormaslik uchun pastga yaxlitlanmaydi).
    """
    if ttl is None:
        return None
    try:
        value = float(ttl)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return int(min(MAX_TTL_SECONDS, max(MIN_TTL_SECONDS, round(value))))


def _to_str(value: Any) -> str:
    """Qiymatni STRING ko'rinishiga keltiradi (Redis bilan bir xil)."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, str):
        return value
    return str(value)


def _from_str(raw: Any) -> str | None:
    """Redis/byte javobini ``str | None`` ga aylantiradi."""
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", "replace")
    if isinstance(raw, str):
        return raw
    return str(raw)


# ===========================================================================
# 1) YAGONA INTERFEYS
# ===========================================================================
class CacheBackend(abc.ABC):
    """Redis va In-Memory uchun umumiy interfeys (Abstract Base Class).

    Kontrakt:
      * barcha metodlar ``async`` (event loop'dan chaqiriladi);
      * qiymatlar ``str`` (``None`` = kalit yo'q);
      * ``ttl`` — soniya; ``None``/``<=0`` = muddatsiz;
      * hech qanday metoda **mass tozalash** yo'q — har bir kalit
        o'z TTL'i bilan «o'zi» yo'qoladi (boshqa foydalanuvchilarning
        holati buzg'unmaydi).
    """

    name: str = "abstract"

    # --- majburiy abstrakt metodlar ------------------------------------
    @abc.abstractmethod
    async def get(self, key: str) -> str | None:
        """Kalit qiymatini qaytaradi (yo'q/eskirgan bo'lsa ``None``)."""

    @abc.abstractmethod
    async def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        """Qiymatni (ixtiyoriy TTL bilan) yozadi. ``True`` — muvaffaqiyat."""

    @abc.abstractmethod
    async def delete(self, key: str) -> bool:
        """Kalitni o'chiradi. ``True`` — kalit mavjud edi va o'chirildi."""

    @abc.abstractmethod
    async def incr(self, key: str, ttl: float | None = None, amount: int = 1) -> int:
        """Hisoblagichni oshiradi va YANGI qiymatni qaytaradi.

        Semantika (Redis ``INCR`` bilan bir xil):
          * kalit YO'Q bo'lsa — yaratiladi va ``ttl`` berilgan bo'lsa
            o'sha oynadan boshlab muddati qo'yiladi (fixed window);
          * kalit BO'LSA — qiymat oshiriladi, **mavjud TTL saqlanadi**
            (oynа oxirigacha cho'zilmaydi).
        """

    @abc.abstractmethod
    async def expire(self, key: str, ttl: float | None) -> bool:
        """Kalitga yangi muddat o'rnatadi. ``False`` — kalit yo'q."""

    # --- ixtiyoriy qulaylik metodlari ----------------------------------
    async def ping(self) -> bool:
        """Backend javob bermoqda (health/diagnostika)."""
        return True

    async def close(self) -> None:
        """Resurslarni yopadi (Redis connection pool)."""
        return None

    def stats(self) -> dict:
        """Diagnostika uchun (parol/DSN **yo'q**)."""
        return {"backend": self.name}


# ===========================================================================
# 2) IN-MEMORY BACKEND — TTL + LRU + xotira chegaralari
# ===========================================================================
class MemoryCacheBackend(CacheBackend):
    """Thread-xavfsiz, TTL qo'llab-quvvatlaydigan LRU xotira keshi.

    * **TTL** — ``time.monotonic()`` asosida (tizim soati o'zgarsa
      kesh buzilmaydi);
    * **LRU** — ``OrderedDict``; chegaradan oshsa eng eski yozuv
      chiqariladi (``max_entries``);
    * **Xotira chegaralari** — bitta qiymat (``max_value_bytes``) va
      umumiy hajm (``max_total_bytes``) bo'yicha ham himoya: Render'ning
      512 MB limitida bot OOM bo'lmaydi;
    * **Thread-xavfsiz** — ``threading.RLock`` (event loop + scheduler
      thread'idan bir vaqtda chaqirilishi mumkin).

    DIQQAT: ``clear()`` faqat test/operatsiya uchun. Rate limiter
    uni **hech qachon** ishlatmaydi — chegaralar faqat ``incr`` +
    ``expire`` bilan, kalit bo'yicha ishlaydi.
    """

    name = "memory"

    def __init__(
        self,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES,
        max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
    ) -> None:
        self._lock = threading.RLock()
        self._data: "OrderedDict[str, tuple[str, float | None]]" = OrderedDict()
        self._max_entries = max(1, int(max_entries))
        self._max_value_bytes = max(64, int(max_value_bytes))
        self._max_total_bytes = max(self._max_value_bytes, int(max_total_bytes))
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

    # --- ichki yordamchilar (lock olib ishlaydi) -----------------------
    def _expired(self, expires_at: float | None, now: float) -> bool:
        return expires_at is not None and expires_at <= now

    def _drop(self, key: str) -> None:
        item = self._data.pop(key, None)
        if item is not None:
            self._bytes -= len(item[0].encode("utf-8", "ignore")) + len(key)

    def _evict_if_needed(self) -> None:
        """Chegaralardan oshsa eng eski (LRU) yozuvlarni chiqaradi."""
        while len(self._data) > self._max_entries or self._bytes > self._max_total_bytes:
            oldest = next(iter(self._data), None)
            if oldest is None:
                break
            self._drop(oldest)
            self._evictions += 1

    def _store(self, key: str, value: str, expires_at: float | None) -> None:
        self._drop(key)
        self._data[key] = (value, expires_at)
        self._bytes += len(value.encode("utf-8", "ignore")) + len(key)
        self._data.move_to_end(key)
        self._evict_if_needed()

    def _expiry_for(self, ttl: float | None, now: float) -> float | None:
        seconds = _coerce_ttl(ttl)
        return None if seconds is None else now + seconds

    # --- CacheBackend kontrakti ----------------------------------------
    async def get(self, key: str) -> str | None:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._misses += 1
                return None
            value, expires_at = item
            if self._expired(expires_at, now):
                self._drop(key)
                self._expirations += 1
                self._misses += 1
                return None
            self._data.move_to_end(key)
            self._hits += 1
            return value

    async def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        text = _to_str(value)
        if len(text.encode("utf-8", "ignore")) > self._max_value_bytes:
            # Xotira himoyasi: juda katta qiymatni saqlamaymiz.
            logger.warning("cache: qiymat limitdan katta, saqlanmadi (key=%s)", key[:64])
            return False
        now = time.monotonic()
        with self._lock:
            self._store(str(key), text, self._expiry_for(ttl, now))
        return True

    async def delete(self, key: str) -> bool:
        with self._lock:
            existed = str(key) in self._data
            self._drop(str(key))
        return existed

    async def incr(self, key: str, ttl: float | None = None, amount: int = 1) -> int:
        key = str(key)
        try:
            step = int(amount)
        except (TypeError, ValueError):
            step = 1
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            current, expires_at = 0, None
            if item is not None:
                raw_value, stored_expiry = item
                if self._expired(stored_expiry, now):
                    self._drop(key)
                    self._expirations += 1
                else:
                    try:
                        current = int(raw_value)
                    except (TypeError, ValueError):
                        current = 0
                    expires_at = stored_expiry
                    self._data.move_to_end(key)
            new_value = current + step
            # Fixed window: TTL faqat kalit YANGI yaratilganda qo'yiladi.
            if expires_at is None:
                expires_at = self._expiry_for(ttl, now)
            self._store(key, str(new_value), expires_at)
        return new_value

    async def expire(self, key: str, ttl: float | None) -> bool:
        key = str(key)
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return False
            value, _ = item
            expires_at = self._expiry_for(ttl, now)
            if expires_at is None:
                # ``None`` = muddatsiz qilish.
                self._store(key, value, None)
            else:
                self._store(key, value, expires_at)
        return True

    # --- diagnostika / test --------------------------------------------
    async def ping(self) -> bool:
        return True

    def clear(self) -> None:
        """BARCHA kalitlarni tozalaydi — faqat test/operatsiya uchun.

        Rate limiter va boshqa ishlab chiqarish kodida
        **CHAQIRILMAYDI**: chegaralar «global tozalash» bilan emas,
        har bir kalitning o'z TTL'i bilan boshqariladi.
        """
        with self._lock:
            self._data.clear()
            self._bytes = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                "backend": self.name,
                "entries": len(self._data),
                "max_entries": self._max_entries,
                "bytes": self._bytes,
                "max_total_bytes": self._max_total_bytes,
                "max_value_bytes": self._max_value_bytes,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "expirations": self._expirations,
            }


# ===========================================================================
# 3) REDIS BACKEND — redis.asyncio (paket ixtiyoriy)
# ===========================================================================
class RedisCacheBackend(CacheBackend):
    """``redis.asyncio`` mijozini yagona interfeysga moslaydi.

    * ``redis`` paketi o'rnatilmagan bo'lsa — bu klass hech qachon
      yaratilmaydi, factory avvaldan In-Memory rejimga o'tadi;
    * har bir istisno ``CacheUnavailableError`` ga aylantiriladi —
      :class:`ResilientCacheBackend` shuni ushlab, In-Memory'ga qaytadi;
    * ``setex``/``expire``/``incrby`` — Redis'ning o'z atomar
      buyruqlari (fixed window oyna ``incr`` + birinchi marta ``expire``).
    """

    name = "redis"

    def __init__(
        self,
        client: Any,
        key_prefix: str = DEFAULT_KEY_PREFIX,
        timeout: float = DEFAULT_CONNECT_TIMEOUT,
    ) -> None:
        self._client = client
        self._prefix = (str(key_prefix or DEFAULT_KEY_PREFIX).strip()
                        or DEFAULT_KEY_PREFIX)
        self._timeout = float(timeout or DEFAULT_CONNECT_TIMEOUT)

    # --- yordamchilar --------------------------------------------------
    @property
    def client(self) -> Any:
        return self._client

    def full_key(self, key: str) -> str:
        text = str(key)
        if text.startswith(f"{self._prefix}:"):
            return text
        return f"{self._prefix}:{text}"

    def _expiry_for(self, ttl: float | None) -> float | None:
        return _coerce_ttl(ttl)

    # --- CacheBackend kontrakti ----------------------------------------
    async def get(self, key: str) -> str | None:
        try:
            raw = await self._client.get(self.full_key(key))
        except Exception as exc:  # noqa: BLE001 — har qanday Redis xatosi
            raise CacheUnavailableError(f"redis.get: {exc}") from exc
        return _from_str(raw)

    async def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        ex = self._expiry_for(ttl)
        try:
            if ex is None:
                await self._client.set(self.full_key(key), _to_str(value))
            else:
                await self._client.set(self.full_key(key), _to_str(value), ex=ex)
        except Exception as exc:  # noqa: BLE001
            raise CacheUnavailableError(f"redis.set: {exc}") from exc
        return True

    async def delete(self, key: str) -> bool:
        try:
            removed = await self._client.delete(self.full_key(key))
        except Exception as exc:  # noqa: BLE001
            raise CacheUnavailableError(f"redis.delete: {exc}") from exc
        return bool(removed)

    async def incr(self, key: str, ttl: float | None = None, amount: int = 1) -> int:
        full = self.full_key(key)
        try:
            try:
                step = int(amount)
            except (TypeError, ValueError):
                step = 1
            value = int(await self._client.incrby(full, step))
            # Fixed window: TTL faqat kalit birinchi marta yaratilganda.
            if value == step:
                ex = self._expiry_for(ttl)
                if ex is not None:
                    await self._client.expire(full, ex)
        except Exception as exc:  # noqa: BLE001
            raise CacheUnavailableError(f"redis.incr: {exc}") from exc
        return int(value)

    async def expire(self, key: str, ttl: float | None) -> bool:
        full = self.full_key(key)
        ex = self._expiry_for(ttl)
        try:
            if ex is None:
                removed = await self._client.persist(full)
                return bool(removed)
            return bool(await self._client.expire(full, ex))
        except Exception as exc:  # noqa: BLE001
            raise CacheUnavailableError(f"redis.expire: {exc}") from exc

    async def ping(self) -> bool:
        try:
            await self._client.ping()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def close(self) -> None:
        for attr in ("aclose", "close"):
            closer = getattr(self._client, attr, None)
            if closer is None:
                continue
            try:
                result = closer()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:  # noqa: BLE001 — yopish xatosi botni to'xtatmasin
                pass
            return


def build_redis_client(
    url: str,
    *,
    timeout: float = DEFAULT_CONNECT_TIMEOUT,
    max_connections: int = 10,
) -> Any:
    """``redis.asyncio`` mijozini yaratadi.

    ``ImportError`` / ``redis`` paketi yo'q bo'lsa —
    ``CacheUnavailableError`` (factory uni ushlab, In-Memory'ga o'tadi).
    """
    try:
        from redis import asyncio as redis_asyncio  # type: ignore
    except Exception as exc:  # noqa: BLE001 — ImportError ham shu yerda
        raise CacheUnavailableError(
            f"redis paketi o'rnatilmagan yoki mos emas: {exc}"
        ) from exc

    try:
        return redis_asyncio.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=float(timeout),
            socket_connect_timeout=float(timeout),
            max_connections=max(1, int(max_connections)),
            health_check_interval=30,
        )
    except Exception as exc:  # noqa: BLE001
        raise CacheUnavailableError(f"redis.from_url: {exc}") from exc


# ===========================================================================
# 4) RESILIENT BACKEND — Circuit Breaker + In-Memory fallback
# ===========================================================================
class ResilientCacheBackend(CacheBackend):
    """Redis (primary) + In-Memory (fallback) + circuit breaker.

    Xatti-harakat:
      * Redis sog'lom bo'lsa — barcha amallar Redis'da (multi-instance
        uchun umumiy state);
      * Redis **bir marta** xato berdi — joriy so'rov darhol In-Memory
        dan xizmat qiladi (foydalanuvchi hech narsani sezmaydi);
      * ``failure_threshold`` ta ketma-ket xatodan keyin breaker
        **OCHILADI**: Redis'ga urinish to'xtaydi, faqat In-Memory ishlaydi
        (Redis o'lgan bo'lsa har bir so'rov uchun timeout yo'q);
      * ``cooldown`` sekund o'tgach **half-open**: bitta proba
        yuboriladi — muvaffaqiyatli bo'lsa breaker yopiladi, yana
        xato bo'lsa cooldown davom etadi.

    Circuit breaker HOLATI hech qachon istisno ko'tarmaydi — bot
    qulamasdan «degraded» rejimda ishlashda davom etadi.
    """

    name = "resilient"

    def __init__(
        self,
        primary: CacheBackend,
        fallback: CacheBackend,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown: float = DEFAULT_COOLDOWN_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._threshold = max(1, int(failure_threshold))
        self._cooldown = max(1.0, float(cooldown))
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._fallbacks = 0
        self._recoveries = 0

    # --- breaker holati -------------------------------------------------
    @property
    def using_fallback(self) -> bool:
        """Hozir In-Memory rejimda ekanini bildiradi (teshiruv/log uchun).

        Breaker yopiq yoki cooldown o'tib yarim-ochiq holatda bo'lsa —
        ``False`` (keyingi so'rov primary'ga urinadi).
        """
        if self._opened_at is None:
            return False
        if (self._clock() - self._opened_at) >= self._cooldown:
            return False  # half-open: proba yuboriladi
        return True

    @property
    def circuit_open(self) -> bool:
        return self._opened_at is not None

    def _note_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            if self._opened_at is None:
                logger.warning(
                    "cache: circuit breaker OCHILDI (%s ta ketma-ket xato) — "
                    "In-Memory fallback rejimiga o'tildi.",
                    self._failures,
                )
            self._opened_at = self._clock()

    def _note_success(self) -> None:
        if self._opened_at is not None:
            logger.info("cache: circuit breaker yopildi — Redis qayta faol.")
            self._recoveries += 1
        self._failures = 0
        self._opened_at = None

    # --- bajaruvchi ------------------------------------------------------
    async def _run(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Primary'ga urinish; muvaffaqiyatsiz bo'lsa — fallback."""
        if self.using_fallback:
            self._fallbacks += 1
            return await getattr(self._fallback, method)(*args, **kwargs)
        try:
            result = await getattr(self._primary, method)(*args, **kwargs)
        except CacheUnavailableError as exc:
            self._note_failure()
            self._fallbacks += 1
            logger.warning(
                "cache: %s.%s muvaffaqiyatsiz (%s) — In-Memory fallback.",
                self._primary.name, method, exc,
            )
            return await getattr(self._fallback, method)(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — noma'lum backend xatosi
            self._note_failure()
            self._fallbacks += 1
            logger.warning(
                "cache: %s.%s kutilmagan xato (%s) — In-Memory fallback.",
                self._primary.name, method, exc,
            )
            return await getattr(self._fallback, method)(*args, **kwargs)
        self._note_success()
        return result

    # --- CacheBackend kontrakti ----------------------------------------
    async def get(self, key: str) -> str | None:
        return await self._run("get", key)

    async def set(self, key: str, value: Any, ttl: float | None = None) -> bool:
        return await self._run("set", key, value, ttl)

    async def delete(self, key: str) -> bool:
        return await self._run("delete", key)

    async def incr(self, key: str, ttl: float | None = None, amount: int = 1) -> int:
        return await self._run("incr", key, ttl, amount)

    async def expire(self, key: str, ttl: float | None) -> bool:
        return await self._run("expire", key, ttl)

    async def ping(self) -> bool:
        if self.using_fallback:
            return await self._fallback.ping()
        try:
            ok = await self._primary.ping()
        except Exception:  # noqa: BLE001
            self._note_failure()
            return await self._fallback.ping()
        if ok:
            self._note_success()
            return True
        return await self._fallback.ping()

    async def close(self) -> None:
        for backend in (self._primary, self._fallback):
            with contextlib.suppress(Exception):
                await backend.close()

    def stats(self) -> dict:
        return {
            "backend": self.name,
            "primary": self._primary.name,
            "fallback": self._fallback.name,
            "failures": self._failures,
            "failure_threshold": self._threshold,
            "circuit_open": self.circuit_open,
            "using_fallback": self.using_fallback,
            "fallback_hits": self._fallbacks,
            "recoveries": self._recoveries,
        }


# ===========================================================================
# 5) FACTORY — REDIS (ixtiyoriy) → IN-MEMORY (fallback)
# ===========================================================================
class CacheSettings:
    """``config`` dan o'qilgan sozlamalar (import xatosidan qat'i nazar)."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.url: str | None = None
        self.key_prefix: str = DEFAULT_KEY_PREFIX
        self.timeout: float = DEFAULT_CONNECT_TIMEOUT
        self.max_connections: int = 10
        self.failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
        self.cooldown: float = DEFAULT_COOLDOWN_SECONDS
        self.max_entries: int = DEFAULT_MAX_ENTRIES
        self.max_value_bytes: int = DEFAULT_MAX_VALUE_BYTES
        self.max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES

        try:
            from config import (
                MEM_CACHE_MAX_ENTRIES,
                MEM_CACHE_MAX_TOTAL_BYTES,
                MEM_CACHE_MAX_VALUE_BYTES,
                REDIS_CIRCUIT_COOLDOWN,
                REDIS_CIRCUIT_FAILURES,
                REDIS_ENABLED,
                REDIS_KEY_PREFIX,
                REDIS_MAX_CONNECTIONS,
                REDIS_SOCKET_TIMEOUT,
                REDIS_URL,
            )
        except Exception:  # noqa: BLE001 — config import muvaffaqiyatsiz
            return

        self.enabled = str(REDIS_ENABLED or "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        self.url = (REDIS_URL or None)
        self.key_prefix = REDIS_KEY_PREFIX or DEFAULT_KEY_PREFIX
        self.timeout = float(REDIS_SOCKET_TIMEOUT or DEFAULT_CONNECT_TIMEOUT)
        self.max_connections = int(REDIS_MAX_CONNECTIONS or 10)
        self.failure_threshold = int(
            REDIS_CIRCUIT_FAILURES or DEFAULT_FAILURE_THRESHOLD
        )
        self.cooldown = float(REDIS_CIRCUIT_COOLDOWN or DEFAULT_COOLDOWN_SECONDS)
        self.max_entries = int(MEM_CACHE_MAX_ENTRIES or DEFAULT_MAX_ENTRIES)
        self.max_value_bytes = int(
            MEM_CACHE_MAX_VALUE_BYTES or DEFAULT_MAX_VALUE_BYTES
        )
        self.max_total_bytes = int(MEM_CACHE_MAX_TOTAL_BYTES or DEFAULT_MAX_TOTAL_BYTES)


def make_memory_backend(
    max_entries: int | None = None,
    max_value_bytes: int | None = None,
    max_total_bytes: int | None = None,
) -> MemoryCacheBackend:
    """Sozlamalarga mos In-Memory backend yaratadi."""
    cfg = CacheSettings()
    return MemoryCacheBackend(
        max_entries=int(max_entries or cfg.max_entries),
        max_value_bytes=int(max_value_bytes or cfg.max_value_bytes),
        max_total_bytes=int(max_total_bytes or cfg.max_total_bytes),
    )


async def create_cache_backend(
    url: str | None = None,
    enabled: bool | None = None,
    *,
    client: Any = None,
    memory: CacheBackend | None = None,
    connect_timeout: float | None = None,
) -> CacheBackend:
    """REDIS_ENABLED/REDIS_URL ga qarab backend yaratadi.

    * ``REDIS_ENABLED`` o'chirgan yoki ``REDIS_URL`` yo'q bo'lsa →
      **faqat In-Memory**;
    * ``redis`` paketi yo'q / ulanish uzilgan / ``PING`` muvaffaqiyatsiz
      bo'lsa → **jim** In-Memory ga qaytadi (bot qulamaydi);
    * muvaffaqiyatli ulanish → :class:`ResilientCacheBackend`
      (Redis + In-Memory fallback + circuit breaker).

    ``client`` berilsa (test/fake Redis) — ulanish o'rnatilmaydi.
    """
    cfg = CacheSettings()
    if enabled is None:
        enabled = cfg.enabled
    if url is None:
        url = cfg.url
    prefix = cfg.key_prefix
    timeout = float(connect_timeout or cfg.timeout)
    max_conn = cfg.max_connections
    failures = cfg.failure_threshold
    cooldown = cfg.cooldown

    fallback = memory or make_memory_backend()
    if not enabled or not url:
        if enabled and not url:
            logger.info("cache: REDIS_ENABLED=1 lekin REDIS_URL bo'sh — In-Memory.")
        else:
            logger.info("cache: Redis o'chirilgan — In-Memory rejim (holat instance ichida).")
        return fallback

    redis_client = client
    if redis_client is None:
        try:
            redis_client = build_redis_client(
                url, timeout=timeout, max_connections=max_conn
            )
        except CacheUnavailableError as exc:
            logger.warning("cache: Redis ulanishi yo'q (%s) — In-Memory fallback.", exc)
            return fallback

    backend = RedisCacheBackend(redis_client, key_prefix=prefix, timeout=timeout)
    try:
        alive = await asyncio.wait_for(backend.ping(), timeout=timeout)
    except Exception as exc:  # noqa: BLE001 — timeout/noto'g'ri DSN
        logger.warning("cache: Redis PING muvaffaqiyatsiz (%s) — In-Memory fallback.", exc)
        with contextlib.suppress(Exception):
            await backend.close()
        return fallback

    if not alive:
        logger.warning("cache: Redis javob bermadi — In-Memory fallback.")
        with contextlib.suppress(Exception):
            await backend.close()
        return fallback

    logger.info("cache: Redis faol (prefix=%s) — state instance'lar arasida umumiy.", prefix)
    return ResilientCacheBackend(
        backend,
        fallback,
        failure_threshold=failures,
        cooldown=cooldown,
    )


# ===========================================================================
# 6) MODUL DARAJASIDAGI YAGONA (SINGLETON)
# ===========================================================================
_backend: CacheBackend | None = None


def get_cache_backend() -> CacheBackend:
    """Hozirgi backendni qaytaradi (init qilinmagan bo'lsa — In-Memory).

    **Hech qachon istisno ko'tarmaydi**: bot startidan oldin ham,
    testlarda ham xavfsiz.
    """
    global _backend
    if _backend is None:
        _backend = make_memory_backend()
    return _backend


def set_cache_backend(backend: CacheBackend | None) -> None:
    """Backendni almashtiradi (testlar / main.py init)."""
    global _backend
    _backend = backend


async def init_cache_backend(**kwargs: Any) -> CacheBackend:
    """``REDIS_*`` sozlamalaridan backend yaratib, singleton'ga o'rnatadi."""
    backend = await create_cache_backend(**kwargs)
    set_cache_backend(backend)
    return backend


async def close_cache_backend() -> None:
    """Backendni yopadi (graceful shutdown)."""
    global _backend
    backend, _backend = _backend, None
    if backend is None:
        return
    with contextlib.suppress(Exception):
        await backend.close()


def backend_status() -> dict:
    """Diagnostika (parol/DSN siz) — admin monitoring uchun."""
    backend = get_cache_backend()
    try:
        stats = backend.stats()
    except Exception:  # noqa: BLE001
        stats = {"backend": getattr(backend, "name", "unknown")}
    stats = dict(stats)
    stats.setdefault("backend", getattr(backend, "name", "unknown"))
    return stats
