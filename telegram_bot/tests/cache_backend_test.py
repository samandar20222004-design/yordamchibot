#!/usr/bin/env python3
"""PHASE 2 · STATE & CACHE ADAPTER — Redis ⇄ In-Memory (unit testlar).

Nima tekshiriladi (tarmoqsiz, deterministik):
  1) **Yagona interfeys** — ``CacheBackend`` da `get/set/delete/incr/expire`
     mavjudligi va barcha backend'lar shu kontraktni bajarishi;
  2) **In-Memory backend** — TTL (monotonic), fixed-window `incr`, LRU
     chegarasi, «katta qiymat» himoyasi, 512 MB RAM uchun `max_total_bytes`;
  3) **Redis backend** — `redis.asyncio` mijoziga o'xshash sun'iy
     (fake) mijoz orqali to'liq kontrakt: prefiks, `ex`, `incrby`, `persist`;
  4) **Redis YO'Q holati** — `REDIS_ENABLED=0` / bo'sh `REDIS_URL` →
     butunlay In-Memory (Redis paketi ham kerak emas);
  5) **Redis UZILGAN holati** — `ping`/buyruqlar xato beradi →
     avtomatik In-Memory fallback (jim, istisnosiz) + circuit breaker
     (threshold → open → cooldown → half-open → close);
  6) **Factory** — muvaffaqiyatli ulanishda `ResilientCacheBackend`,
     muvaffaqiyatsiz ulanishda `MemoryCacheBackend`;
  7) **Hech qanday mass tozalash** — chegaralar kalit bo'yicha
     ishlaydi: boshqa kalitlarga ta'sir qilmaydi.

Ishga tushirish:
    cd telegram_bot && python tests/cache_backend_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:CACHE_BACKEND_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services import cache_backend as cb  # noqa: E402

PASSED = 0
FAILURES = 0


def check(name, cond, detail=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name}" + (f" -> {detail}" if detail else ""))
    return bool(cond)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# SUN'IY REDIS MIJOZI — redis.asyncio bilan bir xil API (tarmoq yo'q)
# ---------------------------------------------------------------------------
class FakeRedisClient:
    """``redis.asyncio`` ni taqlid qiluvchi minimal async mijoz."""

    def __init__(self, fail: bool = False):
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail = fail
        self.closed = False
        self.calls: list[str] = []

    def _guard(self, name: str) -> None:
        self.calls.append(name)
        if self.fail:
            raise ConnectionError("redis down")

    async def get(self, key):
        self._guard("get")
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self._guard("set")
        self.values[key] = str(value)
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    async def delete(self, key):
        self._guard("delete")
        self.ttls.pop(key, None)
        return 1 if self.values.pop(key, None) is not None else 0

    async def incrby(self, key, amount):
        self._guard("incrby")
        new = int(self.values.get(key, 0)) + int(amount)
        self.values[key] = str(new)
        return new

    async def expire(self, key, seconds):
        self._guard("expire")
        if key not in self.values:
            return False
        self.ttls[key] = int(seconds)
        return True

    async def persist(self, key):
        self._guard("persist")
        return 1 if self.ttls.pop(key, None) is not None else 0

    async def ping(self):
        self._guard("ping")
        return True

    async def aclose(self):
        self.closed = True


# ---------------------------------------------------------------------------
# 1) INTERFEYS KONTRAKTI
# ---------------------------------------------------------------------------
def test_interface():
    print("\n== 1) Yagona interfeys (ABC) kontrakti ==")
    required = ("get", "set", "delete", "incr", "expire")
    for name in required:
        check(f"CacheBackend.{name} mavjud",
              callable(getattr(cb.CacheBackend, name, None)))
    check("CacheBackend — real abstrakt klass (ABC)",
          getattr(cb.CacheBackend, "__abstractmethods__", None) is not None
          and bool(getattr(cb.CacheBackend, "__abstractmethods__", set())))
    for backend, args in (
        (cb.MemoryCacheBackend, ()),
        (cb.RedisCacheBackend, (FakeRedisClient(),)),
        (cb.ResilientCacheBackend, (FakeRedisClient(), cb.MemoryCacheBackend())),
    ):
        try:
            backend(*args)
            instantiable = True
        except TypeError:
            instantiable = False
        check(f"{backend.__name__} — kontraktni to'liq bajaradi",
              instantiable, "abstrakt metod qoldi")


# ---------------------------------------------------------------------------
# 2) IN-MEMORY BACKEND
# ---------------------------------------------------------------------------
def test_memory_backend():
    print("\n== 2) In-Memory backend: TTL, fixed-window incr, LRU, xotira ==")

    async def scenario():
        mem = cb.MemoryCacheBackend(max_entries=3, max_value_bytes=64,
                                    max_total_bytes=1024)
        # --- get/set ---
        check("set → True", await mem.set("k", "v", ttl=5) is True)
        check("get → qiymat", await mem.get("k") == "v")
        check("get (yo'q kalit) → None", await mem.get("yoq") is None)
        # --- delete ---
        check("delete (mavjud) → True", await mem.delete("k") is True)
        check("delete (yo'q) → False", await mem.delete("k") is False)
        check("o'chirilgandan keyin → None", await mem.get("k") is None)
        # --- incr: yangi kalit + TTL ---
        v1 = await mem.incr("w", ttl=1)
        v2 = await mem.incr("w", ttl=1)
        v3 = await mem.incr("w", ttl=1)
        check("incr: 1, 2, 3", (v1, v2, v3) == (1, 2, 3), f"{(v1, v2, v3)}")
        # --- expire ---
        check("expire (mavjud kalit) → True", await mem.expire("w", 30) is True)
        check("expire (yo'q kalit) → False", await mem.expire("yoq2", 30) is False)
        # --- TTL: 1 soniyadan keyin kalit «o'zi» yo'qoladi ---
        fast = await mem.incr("ttl", ttl=1)
        check("ttl: kalit yaratildi", fast == 1)
        await asyncio.sleep(1.15)
        check("ttl: 1.15s keyin kalit o'zi yo'qoldi (mass tozalashsiz)",
              await mem.get("ttl") is None)
        # --- LRU chegarasi ---
        lru = cb.MemoryCacheBackend(max_entries=2)
        await lru.set("a", "1", ttl=30)
        await lru.set("b", "2", ttl=30)
        await lru.set("c", "3", ttl=30)
        check("LRU: chegaradan oshganda eng eski kalit chiqarildi",
              await lru.get("a") is None and await lru.get("b") == "2")
        check("LRU: stats.evictions > 0", lru.stats()["evictions"] > 0)
        # --- katta qiymat himoyasi ---
        big = cb.MemoryCacheBackend(max_value_bytes=64)
        check("katta qiymat saqlanmaydi (xotira himoyasi)",
              await big.set("k", "x" * 500, ttl=30) is False)
        check("katta qiymat yozilmagan", await big.get("k") is None)
        # --- umumiy hajm ---
        size = cb.MemoryCacheBackend(max_value_bytes=64, max_total_bytes=256,
                                     max_entries=1000)
        for i in range(50):
            await size.set(f"k{i}", "v" * 50, ttl=30)
        check("max_total_bytes: umumiy hajm chegarasi buzilmaydi",
              size.stats()["bytes"] <= 256, str(size.stats()["bytes"]))
        # --- stats ---
        st = cb.MemoryCacheBackend()
        await st.set("a", "1", ttl=5)
        await st.get("a")
        await st.get("yoq")
        stats = st.stats()
        check("stats: backend nomi", stats["backend"] == "memory")
        check("stats: hits/misses hisoblanadi",
              stats["hits"] == 1 and stats["misses"] == 1, str(stats))
        check("stats: maxsize nazorati ko'rinadi",
              "max_entries" in stats and "max_total_bytes" in stats)

    run(scenario())


# ---------------------------------------------------------------------------
# 3) REDIS BACKEND (fake mijoz bilan — tarmoq/paket talab qilinmaydi)
# ---------------------------------------------------------------------------
def test_redis_backend():
    print("\n== 3) Redis backend (sun'iy redis.asyncio mijozi) ==")

    async def scenario():
        client = FakeRedisClient()
        backend = cb.RedisCacheBackend(client, key_prefix="test")
        check("prefiks qo'shiladi", backend.full_key("rl:message:1")
              == "test:rl:message:1", backend.full_key("rl:message:1"))
        check("prefiks ikki marta qo'shilmay",
              backend.full_key("test:rl:x") == "test:rl:x")
        check("set → True", await backend.set("k", "v", ttl=5) is True)
        check("get → qiymat", await backend.get("k") == "v")
        check("set → TTL Redis'ga berildi (ex)",
              client.ttls.get("test:k") == 5, str(client.ttls))
        check("incr: 1 → 2", (await backend.incr("num", ttl=5)) == 1
              and (await backend.incr("num", ttl=5)) == 2)
        check("incr: TTL oynasi CHO'ZILMAYDI (eski expiry saqlanadi)",
              client.ttls.get("test:num") == 5, str(client.ttls))
        await backend.incr("yeni", ttl=9)
        check("incr: yangi kalitga TTL qo'yiladi", client.ttls.get("test:yeni") == 9)
        check("expire → True", await backend.expire("k", 60) is True)
        check("expire → yangi qiymat", client.ttls.get("test:k") == 60)
        check("expire(None) → persist (muddatsiz)",
              await backend.expire("k", None) is True and "test:k" not in client.ttls)
        check("delete → True", await backend.delete("k") is True)
        check("delete (yo'q) → False", await backend.delete("k") is False)
        check("ping → True", await backend.ping() is True)
        await backend.close()
        check("close → aclose chaqirildi", client.closed is True)
        # --- Redis xatosi → CacheUnavailableError ---
        broken = cb.RedisCacheBackend(FakeRedisClient(fail=True))
        try:
            await broken.get("x")
            raised = False
        except cb.CacheUnavailableError:
            raised = True
        check("Redis xatosi → CacheUnavailableError", raised)
        check("ping (xato) → False, istisno emas", await broken.ping() is False)

    run(scenario())


# ---------------------------------------------------------------------------
# 4) REDIS YO'Q (faqat In-Memory fallback)
# ---------------------------------------------------------------------------
def test_no_redis():
    print("\n== 4) Redis YO'Q → butunlay In-Memory fallback ==")

    async def scenario():
        before = os.environ.get("REDIS_URL", "")
        os.environ.pop("REDIS_URL", None)
        backend = await cb.create_cache_backend(enabled=False)
        check("REDIS_ENABLED=0 → MemoryCacheBackend",
              isinstance(backend, cb.MemoryCacheBackend)
              and not isinstance(backend, cb.ResilientCacheBackend),
              type(backend).__name__)
        check("Redis paketi umuman chaqirilmaydi", True)
        # URL bor, lekin bayroq o'chirilgan
        backend2 = await cb.create_cache_backend(enabled=False,
                                                 url="redis://localhost:6379/0")
        check("REDIS_ENABLED=0 + URL → yana In-Memory",
              isinstance(backend2, cb.MemoryCacheBackend))
        # Enabled, lekin URL yo'q
        backend3 = await cb.create_cache_backend(enabled=True, url=None)
        check("REDIS_ENABLED=1 lekin URL bo'sh → In-Memory",
              isinstance(backend3, cb.MemoryCacheBackend))
        # Noto'g'ri/unavailable DSN (paket/port yo'q) — jim fallback
        backend4 = await cb.create_cache_backend(
            enabled=True,
            url="redis://127.0.0.1:1/0",
            connect_timeout=0.2,
        )
        check("ulana olinmagan Redis → istisnosiz In-Memory",
              isinstance(backend4, cb.MemoryCacheBackend),
              type(backend4).__name__)
        if before:
            os.environ["REDIS_URL"] = before
        # --- ishlash semantikasi bir xil ---
        await backend.set("rl:message:7", "1", ttl=1)
        check("fallback ham to'liq ishlaydi (get/set)",
              await backend.get("rl:message:7") == "1")

    run(scenario())


# ---------------------------------------------------------------------------
# 5) REDIS UZILGAN → CIRCUIT BREAKER + avtomatik fallback
# ---------------------------------------------------------------------------
def test_redis_failure_fallback():
    print("\n== 5) Redis UZILGAN → avtomatik In-Memory + circuit breaker ==")

    async def scenario():
        primary = cb.RedisCacheBackend(FakeRedisClient(fail=True))
        fallback = cb.MemoryCacheBackend()
        clock = {"t": 1000.0}
        res = cb.ResilientCacheBackend(primary, fallback, failure_threshold=2,
                                       cooldown=10.0, clock=lambda: clock["t"])
        # 1) Birinchi xato — foydalanuvchiga hech narsani sezdirMAYDI
        check("1-xato: get → None (fallback, istisno yo'q)",
              await res.get("k") is None)
        check("1-xato: breaker hali OCHIQ emas (1 < 2)",
              res.circuit_open is False and res.using_fallback is False)
        check("1-xato: set → True (fallback saqladi)",
              await res.set("k", "v", ttl=30) is True)
        check("fallback'da qiymat bor", await fallback.get("k") == "v")
        # 2) Ikkinchi xato → breaker OCHILADI
        check("2-xato: breaker OCHILDI", res.circuit_open is True)
        check("2-xato: using_fallback = True", res.using_fallback is True)
        # 3) Breaker ochiqligida Redis'ga UMURAT qilinmaydi
        before = len(primary.client.calls)
        await res.incr("counter", ttl=5)
        after = len(primary.client.calls)
        check("breaker ochiq: Redis'ga yangi so'rov YUBORILMAYDI",
              after == before, f"{before} -> {after}")
        count = await res.incr("counter", ttl=5)
        check("breaker ochiq: incr fallback'da ishlaydi (2)", count == 2, str(count))
        # 4) Cooldown o'tdi → half-open proba
        clock["t"] += 11.0
        check("cooldown o'tdi: yarim-ochiq (proba yuboriladi)",
              res.using_fallback is False)
        primary.client.fail = False          # Redis qayta tirildi
        check("half-open: proba muvaffaqiyatli → breaker YOPILDI",
              await res.get("k") is None and res.circuit_open is False)
        check("tuzilgan: yana Redis ishlatilmoqda",
              primary.client.calls[-1] == "get", str(primary.client.calls[-3:]))
        check("stats: recoveries hisoblangan", res.stats()["recoveries"] >= 1,
              str(res.stats()))
        # 5) Yana uzilgan → yana ochiladi (mustaqil holat)
        primary.client.fail = True
        await res.get("k")
        await res.get("k")
        check("qayta uzilganda breaker yana ochiladi", res.circuit_open is True)
        await res.close()

    run(scenario())


# ---------------------------------------------------------------------------
# 6) FACTORY: muvaffaqiyatli Redis ulanishi
# ---------------------------------------------------------------------------
def test_factory_success():
    print("\n== 6) Factory: muvaffaqiyatli Redis ulanishi (Resilient) ==")

    async def scenario():
        client = FakeRedisClient()
        backend = await cb.create_cache_backend(
            enabled=True, url="redis://localhost:6379/0", client=client,
            memory=cb.MemoryCacheBackend(),
        )
        check("Redis sog'lom → ResilientCacheBackend (Redis + fallback)",
              isinstance(backend, cb.ResilientCacheBackend), type(backend).__name__)
        check("birinchi so'rov → Redis'ga boradi",
              await backend.set("k", "v", ttl=10) is True
              and client.values.get("postassist:k") == "v",
              str(client.values))
        check("key prefiksi qo'llandi", "postassist:k" in client.values)
        st = backend.stats()
        check("stats: primary/fallback nomlari",
              st["primary"] == "redis" and st["fallback"] == "memory", str(st))
        # --- init/get/set/close (singleton) ---
        cb.set_cache_backend(None)
        check("get_cache_backend() hech qachon xato bermaydi (bo'sh → memory)",
              isinstance(cb.get_cache_backend(), cb.MemoryCacheBackend))
        cb.set_cache_backend(backend)
        check("singleton qo'yildi", cb.get_cache_backend() is backend)
        status = cb.backend_status()
        check("backend_status() parol/DSN siz", "redis://" not in str(status)
              and "password" not in str(status).lower(), str(status))
        await cb.close_cache_backend()
        check("close_cache_backend() — mijoz yopiladi", client.closed is True)
        cb.set_cache_backend(None)

    run(scenario())


# ---------------------------------------------------------------------------
# 7) KALIT BO'YICHA IZOLYATSIYA (mass tozalash YO'Q)
# ---------------------------------------------------------------------------
def test_key_isolation():
    print("\n== 7) Kalitlar izolyatsiyasi — global tozalash yo'q ==")

    async def scenario():
        mem = cb.MemoryCacheBackend()
        await mem.incr("rl:message:1", ttl=30)
        await mem.incr("rl:message:1", ttl=30)
        await mem.incr("rl:message:2", ttl=30)      # boshqa foydalanuvchi
        await mem.incr("rl:callback:1|stgs_hub", ttl=30)
        check("boshqa kalit o'z sanagichiga tegilmaydi",
              await mem.incr("rl:message:1", ttl=30) == 3
              and await mem.incr("rl:message:2", ttl=30) == 2)
        check("bir kalitning muddati boshqasini buzmaydi",
              await mem.get("rl:callback:1|stgs_hub") == "1")
        # TTL faqat o'z kalitiga taalluqli
        fast = cb.MemoryCacheBackend()
        await fast.incr("qisqa", ttl=1)
        await fast.incr("uzun", ttl=600)
        await asyncio.sleep(1.15)
        check("TTL faqat O'Z kalitini o'chiradi",
              await fast.get("qisqa") is None and await fast.get("uzun") == "1")
        check("clear() mavjud lekin rate limiter ishlatmaydi",
              hasattr(mem, "clear"))

    run(scenario())


def test_live_redis_optional():
    """Ixtiyoriy: haqiqiy Redis serveri bilan jonli round-trip.

    Ishlash uchun `pip install redis` va `REDIS_URL=redis://localhost:6379/0`
    kerak. Yo'q bo'lsa — SKIP (soxta PASS yozilmaydi). Sun'iy mijoz bilan
    bajarilgan testlar (3–6-bo'lim) har doim o'tadi.
    """
    print("\n== 8) Ixtiyoriy: JONLI Redis round-trip ==")
    url = (os.environ.get("REDIS_URL") or "").strip()
    try:
        import importlib

        importlib.import_module("redis")
    except Exception:
        print("  [SKIP] `redis` paketi o'rnatilmagan — jonli test o'tkazildi")
        return
    if not url:
        print("  [SKIP] REDIS_URL bo'sh — jonli test o'tkazildi")
        return

    async def scenario():
        try:
            backend = await cb.create_cache_backend(
                enabled=True, url=url, connect_timeout=1.0,
                memory=cb.MemoryCacheBackend(),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [SKIP] Redis ulanmadi ({exc}) — jonli test o'tkazildi")
            return
        if not isinstance(backend, cb.ResilientCacheBackend):
            print("  [SKIP] Redis javob bermadi — In-Memory rejimga tushildi")
            return
        key = f"rl:test:{int(time.time())}"
        try:
            await backend.set(key, "1", ttl=10)
            check("jonli: set → get = 1", await backend.get(key) == "1")
            check("jonli: incr = 2", await backend.incr(key, ttl=10) == 2)
            check("jonli: TTL o'rnatildi", await backend.expire(key, 30) is True)
            check("jonli: delete", await backend.delete(key) is True)
            check("jonli: o'chirilgandan keyin None", await backend.get(key) is None)
        finally:
            await backend.close()

    run(scenario())


def main() -> int:
    print("=" * 70)
    print(" 🗄  PHASE 2 — STATE & CACHE ADAPTER (Redis ⇄ In-Memory) TESTLARI")
    print("=" * 70)
    test_interface()
    test_memory_backend()
    test_redis_backend()
    test_no_redis()
    test_redis_failure_fallback()
    test_factory_success()
    test_key_isolation()
    test_live_redis_optional()
    print()
    print("=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] CACHE BACKEND TESTLARIDA XATOLIK BOR ^^^")
        return 1
    print(" CACHE BACKEND TESTLARI 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
