#!/usr/bin/env python3
"""Mini App — ishonchli proksi (X-Forwarded-*) va qat'iy auth rate limiter.

Muhit: sof unit; haqiqiy Redis YO'Q (soxta Redis mijozi). Haqiqiy Redis bilan
umumiy sanagich tekshiruvi bu faylda BAJARILMAYDI (alohida SKIP/BLOCKED).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, Counter  # noqa: E402

from multidict import CIMultiDict  # noqa: E402

from miniapp_api.errors import ApiError  # noqa: E402
from miniapp_api.proxy import resolve_client  # noqa: E402
from miniapp_api.ratelimit import StrictLimiter, shared_primary  # noqa: E402
from miniapp_api.settings import load_settings  # noqa: E402
from services.cache_backend import (  # noqa: E402
    CacheUnavailableError,
    MemoryCacheBackend,
    RedisCacheBackend,
    ResilientCacheBackend,
)

T = Counter("MINI APP — PROKSI + QAT'IY RATE LIMITER")
BASE = {"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "production"}


def S(**extra):
    return load_settings({**BASE, **extra})


def H(*pairs):
    h = CIMultiDict()
    for k, v in pairs:
        h.add(k, v)
    return h


def test_proxy():
    print("\n== 1. Forwarded sarlavhalar (soxtalashtirish) ==")
    cidr = S(MINIAPP_TRUSTED_PROXY_CIDRS="10.0.0.0/8", MINIAPP_PROXY_HOPS="1")
    edge = S(MINIAPP_PROXY_ASSERT_EDGE_ONLY="1", MINIAPP_PROXY_HOPS="1")
    none = S()
    spoof = H(("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-Proto", "https"))

    c = resolve_client(("203.0.113.9", 5000), spoof, "http", cidr)
    T.check("ishonchsiz peer: XFF e'tiborsiz (IP=peer)", c.ip == "203.0.113.9" and not c.trusted_proxy)
    T.check("ishonchsiz peer: X-Forwarded-Proto e'tiborsiz (http)", c.scheme == "http")
    c = resolve_client(("10.1.2.3", 5000), H(("X-Forwarded-For", "6.6.6.6, 198.51.100.7"),
                                              ("X-Forwarded-Proto", "https")), "http", cidr)
    T.check("ishonchli peer: o'ngdan 1-chi IP (chapdagi soxta emas)", c.ip == "198.51.100.7")
    T.check("ishonchli peer: https qabul", c.scheme == "https" and c.trusted_proxy)
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "6.6.6.6, 198.51.100.7, 10.9.9.9")),
                       "http", S(MINIAPP_TRUSTED_PROXY_CIDRS="10.0.0.0/8", MINIAPP_PROXY_HOPS="2"))
    T.check("hops=2: o'ngdan 2-chi", c.ip == "198.51.100.7")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "198.51.100.7")), "http",
                       S(MINIAPP_TRUSTED_PROXY_CIDRS="10.0.0.0/8", MINIAPP_PROXY_HOPS="3"))
    T.check("ro'yxat hops'dan qisqa -> peer IP", c.ip == "10.1.2.3")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "not-an-ip")), "http", cidr)
    T.check("yaroqsiz IP -> peer IP", c.ip == "10.1.2.3")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "1.1.1.1"), ("X-Forwarded-For", "2.2.2.2")),
                       "http", cidr)
    T.check("XFF sarlavhasi takrorlansa -> peer IP", c.ip == "10.1.2.3")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-Proto", "javascript")), "http", cidr)
    T.check("noto'g'ri Proto qiymati -> http", c.scheme == "http")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-Proto", "https"), ("X-Forwarded-Proto", "http")),
                       "http", cidr)
    T.check("Proto takrorlansa -> http", c.scheme == "http")
    c = resolve_client(("2001:db8::1", 1), H(("X-Forwarded-For", "6.6.6.6")), "http", cidr)
    T.check("IPv6 peer (CIDR tashqarisi) -> sarlavha e'tiborsiz", c.ip == "2001:db8::1")
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "2001:db8::5")), "http", cidr)
    T.check("IPv6 mijoz IP normallashadi", c.ip == "2001:db8::5")
    c = resolve_client(("198.51.100.1", 1), spoof, "http", none)
    T.check("proksi sozlanmagan: sarlavhalar e'tiborsiz", c.ip == "198.51.100.1" and c.scheme == "http")
    c = resolve_client(("198.51.100.1", 1), H(("X-Forwarded-For", "1.2.3.4"), ("X-Forwarded-Proto", "https")),
                       "http", edge)
    T.check("edge-only: o'ngdan hops-chi", c.ip == "1.2.3.4" and c.scheme == "https")
    c = resolve_client(None, spoof, "http", cidr)
    T.check("peername yo'q -> 'unknown', ishonchsiz", c.ip == "unknown" and not c.trusted_proxy)
    c = resolve_client(("10.1.2.3", 1), H(("X-Forwarded-For", "6.6.6.6, 198.51.100.7")), "https", cidr)
    T.check("transport https, Proto yo'q -> https saqlanadi", c.scheme == "https")


class FakeRedisClient:
    def __init__(self, fail=False):
        self.counts, self.fail, self.calls = {}, fail, 0

    async def eval(self, script, nkeys, key, step, ttl):
        self.calls += 1
        if self.fail:
            raise ConnectionError("redis down")
        self.counts[key] = self.counts.get(key, 0) + int(step)
        return self.counts[key]


def make_resilient(fail=False, clock=None):
    client = FakeRedisClient(fail=fail)
    primary = RedisCacheBackend(client)
    fallback = MemoryCacheBackend()
    kwargs = {"failure_threshold": 2, "cooldown": 30}
    if clock is not None:
        kwargs["clock"] = clock
    return ResilientCacheBackend(primary, fallback, **kwargs), client, fallback


async def hit(limiter, n=1, limit=3, subject="ip1"):
    last = None
    for _ in range(n):
        try:
            await limiter.hit("auth_ip", subject, limit=limit, window=60)
            last = "ok"
        except ApiError as err:
            last = err.code
    return last


def test_limiter():
    print("\n== 2. Qat'iy limiter: umumiy Redis ==")
    backend, client, fallback = make_resilient()
    lim = StrictLimiter(require_shared=True, backend_getter=lambda: backend)
    T.check("sog'lom Redis: 3 ta ruxsat", asyncio.run(hit(lim, 3)) == "ok")
    T.check("4-chi -> rate_limited (429)", asyncio.run(hit(lim, 1)) == "rate_limited")
    T.check("sanagich Redis'da (xotira fallback'da emas)", sum(client.counts.values()) == 4 and not fallback._data)
    T.check("boshqa subyekt mustaqil", asyncio.run(hit(lim, 1, subject="ip2")) == "ok")
    try:
        asyncio.run(lim.hit("auth_ip", "ip1", limit=3, window=60))
    except ApiError as err:
        T.check("429 Retry-After bor", err.status == 429 and err.retry_after == 60)

    print("\n== 3. Redis xatosi / fallback -> 503 (jim ruxsat yo'q) ==")
    backend, client, fallback = make_resilient(fail=True)
    lim = StrictLimiter(require_shared=True, backend_getter=lambda: backend)
    r = asyncio.run(hit(lim, 1))
    T.check("Redis istisnosi -> service_unavailable (503)", r == "service_unavailable")
    # breaker ochiladi (boshqa iste'molchi urinishlari) -> fallback xotira UMUMIY emas
    for _ in range(3):
        asyncio.run(backend.incr("x", ttl=5))
    T.check("breaker ochiq (fallback'ga o'tildi)", backend.circuit_open)
    calls_before = client.calls
    r = asyncio.run(hit(lim, 1))
    T.check("breaker ochiq: require_shared=True -> 503", r == "service_unavailable")
    T.check("xotira hisoblagichi umumiy deb qabul qilinmadi", shared_primary(backend) is None)
    T.check("fallback hisoblagichiga yozilmadi", not any(k.startswith("miniapp") for k in fallback._data))
    T.check("breaker ochiqda Redis'ga ham urilmadi", client.calls == calls_before)

    print("\n== 4. Backend turlari ==")
    mem = MemoryCacheBackend()
    lim = StrictLimiter(require_shared=True, backend_getter=lambda: mem)
    T.check("faqat xotira backend + require_shared -> 503", asyncio.run(hit(lim)) == "service_unavailable")
    lim = StrictLimiter(require_shared=False, backend_getter=lambda: mem)
    T.check("require_shared=False (dev/test): xotira ishlaydi", asyncio.run(hit(lim, 3)) == "ok")
    T.check("require_shared=False: limit baribir ishlaydi", asyncio.run(hit(lim, 1)) == "rate_limited")

    class Boom(MemoryCacheBackend):
        async def incr(self, *a, **k):
            raise RuntimeError("secret-detail")

    lim = StrictLimiter(require_shared=False, backend_getter=lambda: Boom())
    try:
        asyncio.run(lim.hit("auth_ip", "ip", limit=3, window=60))
        T.check("require_shared=False + xato -> 503", False)
    except ApiError as err:
        T.check("require_shared=False + backend xatosi -> 503", err.code == "service_unavailable")
        T.check("503 xabarida ichki matn yo'q", "secret-detail" not in str(err))

    # half-open: cooldown o'tgan, primary sog'lom bo'lsa qayta ishlaydi
    now = [0.0]
    backend, client, _ = make_resilient(fail=True, clock=lambda: now[0])
    for _ in range(3):
        asyncio.run(backend.incr("x", ttl=5))
    T.check("breaker ochildi", backend.circuit_open and backend.using_fallback)
    client.fail = False
    now[0] = 100.0  # cooldown o'tdi
    lim = StrictLimiter(require_shared=True, backend_getter=lambda: backend)
    T.check("cooldown'dan keyin (half-open) primary'ga urinadi", asyncio.run(hit(lim, 1)) == "ok")
    _ = CacheUnavailableError


class PoolLimitedBackend(MemoryCacheBackend):
    """redis-py ConnectionPool'ni taqlid qiladi: bir vaqtda `pool` tadan ortiq chaqiruv -> xato (kutmaydi)."""

    def __init__(self, pool: int):
        super().__init__()
        self.pool, self.inflight, self.peak = pool, 0, 0

    async def incr(self, key, ttl=None, amount=1):
        self.inflight += 1
        self.peak = max(self.peak, self.inflight)
        try:
            if self.inflight > self.pool:
                raise CacheUnavailableError("Too many connections")
            await asyncio.sleep(0.005)
            return await super().incr(key, ttl=ttl, amount=amount)
        finally:
            self.inflight -= 1


def test_concurrency_gate():
    print("\n== 5. Burst: Redis pool'idan ortiq parallel so'rov (concurrency gate) ==")

    async def burst(limiter, n=60, limit=20):
        res = await asyncio.gather(*[hit(limiter, subject="burst", limit=limit) for _ in range(n)])
        return {k: res.count(k) for k in set(res)}

    be = PoolLimitedBackend(pool=10)
    gated = StrictLimiter(require_shared=False, backend_getter=lambda: be, max_concurrency=4)
    out = asyncio.run(burst(gated))
    T.check("gate=4, pool=10: 60 parallel so'rovda 503 YO'Q, aynan 20 ruxsat / 40 rate_limited",
            out == {"ok": 20, "rate_limited": 40}, str(out))
    T.check("Redis'ga bir vaqtda chaqiruvlar gate'dan oshmadi", be.peak <= 4, f"peak={be.peak}")

    be2 = PoolLimitedBackend(pool=10)
    ungated = StrictLimiter(require_shared=False, backend_getter=lambda: be2, max_concurrency=1000)
    out2 = asyncio.run(burst(ungated))
    T.check("gate'siz (nazorat): pool to'lganda 503 chiqadi (muammo haqiqiy ekanini tasdiqlaydi)",
            out2.get("service_unavailable", 0) > 0, str(out2))

    class Hang(MemoryCacheBackend):
        async def incr(self, key, ttl=None, amount=1):
            raise RuntimeError("xato")

    lim = StrictLimiter(require_shared=False, backend_getter=lambda: Hang(), max_concurrency=2)
    res = asyncio.run(burst(lim, n=5, limit=3))
    T.check("backend xatosida gate fail-closed (503) va semafor bo'shaydi (osilib qolmaydi)",
            res == {"service_unavailable": 5}, str(res))
    T.check("max_concurrency <= 0 xavfsiz (kamida 1)", asyncio.run(hit(StrictLimiter(
        require_shared=False, backend_getter=lambda: MemoryCacheBackend(), max_concurrency=0), subject="z")) == "ok")


def main() -> int:
    test_proxy()
    test_limiter()
    test_concurrency_gate()
    T.skip("haqiqiy Redis bilan umumiy sanagich (2 instance)", "BLOCKED: Redis serveri/paketi mavjud emas")
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
