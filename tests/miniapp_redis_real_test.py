#!/usr/bin/env python3
"""Mini App — REAL Redis integratsiya testi (umumiy limiter, uzilish -> 503, tiklanish).

Xavfsizlik: faqat LOKAL Redis (127.0.0.1/localhost/::1). Production Redis'ga ULANILMAYDI.
Ikki rejim:
  * `MINIAPP_TEST_REDIS_URL=redis://127.0.0.1:PORT/0` — tayyor lokal sinov serveri (uzilish bosqichlari SKIP:
    serverni test boshqara olmaydi);
  * URL berilmasa va `redis-server` binary + Python `redis` paketi mavjud bo'lsa — test O'ZI vaqtinchalik
    server ishga tushiradi (127.0.0.1, tasodifiy port, persistence YO'Q, tmp katalog) va oxirida o'chiradi.
Python `redis` paketi yoki `redis-server` yo'q bo'lsa — butun fayl SKIP/BLOCKED (CI Python job'ida shunday).
Test faqat o'z kalitlarini (`miniapp:rl:*` + tasodifiy subyekt) ishlatadi va FLUSHALL qilmaydi.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import Counter  # noqa: E402

from miniapp_api.errors import ApiError  # noqa: E402
from miniapp_api.ratelimit import StrictLimiter, shared_primary  # noqa: E402
from services.cache_backend import (  # noqa: E402
    MemoryCacheBackend,
    RedisCacheBackend,
    ResilientCacheBackend,
    build_redis_client,
)

T = Counter("MINI APP — REAL REDIS (umumiy limiter)")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LocalRedis:
    """Vaqtinchalik lokal redis-server (persistence yo'q)."""

    def __init__(self, binary: str):
        self.binary, self.port, self.dir, self.proc = binary, free_port(), tempfile.mkdtemp(prefix="miniapp-redis-"), None

    @property
    def url(self) -> str:
        return f"redis://127.0.0.1:{self.port}/0"

    def start(self) -> None:
        self.proc = subprocess.Popen(
            [self.binary, "--bind", "127.0.0.1", "--port", str(self.port), "--save", "", "--appendonly", "no",
             "--dir", self.dir, "--daemonize", "no", "--protected-mode", "yes"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 8
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.3):
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("redis-server ishga tushmadi")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def cleanup(self) -> None:
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)


def make_backend(url: str, *, cooldown: float = 30.0):
    client = build_redis_client(url, timeout=1.0, max_connections=10)
    return ResilientCacheBackend(RedisCacheBackend(client), MemoryCacheBackend(), failure_threshold=2, cooldown=cooldown), client


async def hit(limiter, subject, limit=3):
    try:
        await limiter.hit("auth_ip", subject, limit=limit, window=30)
        return "ok"
    except ApiError as err:
        return err.code


async def run_shared(url: str, server: LocalRedis | None) -> None:
    print("\n== 1. Umumiy sanagich: ikkita 'instance' bitta Redis'da ==")
    a, ca = make_backend(url)
    b, cb = make_backend(url)
    la = StrictLimiter(require_shared=True, backend_getter=lambda: a)
    lb = StrictLimiter(require_shared=True, backend_getter=lambda: b)
    try:
        T.check("ikkala backend uchun shared_primary = haqiqiy Redis", isinstance(shared_primary(a), RedisCacheBackend)
                and isinstance(shared_primary(b), RedisCacheBackend))
        subj = "t-" + uuid.uuid4().hex
        res = [await hit(la, subj), await hit(lb, subj), await hit(la, subj), await hit(lb, subj)]
        T.check("A,B navbatma-navbat: 3 ta ruxsat, 4-chi (B) rate_limited", res == ["ok", "ok", "ok", "rate_limited"], str(res))
        key = f"postassist:miniapp:rl:auth_ip:{subj}"
        T.check("sanagich Redis'da (4), xotirada emas", int(await ca.get(key)) == 4 and not [k for k in a._fallback._data if "miniapp" in k])
        ttl = await ca.ttl(key)
        T.check("TTL o'rnatilgan (<= oyna)", 0 < ttl <= 30, str(ttl))
        other = "t-" + uuid.uuid4().hex
        T.check("boshqa subyekt mustaqil", await hit(lb, other) == "ok")

        subj2 = "t-" + uuid.uuid4().hex
        results = await asyncio.gather(*[hit(la if i % 2 else lb, subj2, limit=20) for i in range(60)])
        T.check("60 parallel so'rov, 2 instance: aynan 20 ta ruxsat (atomik)", results.count("ok") == 20 and results.count("rate_limited") == 40,
                f"ok={results.count('ok')}")
        await ca.delete(key, f"postassist:miniapp:rl:auth_ip:{subj2}", f"postassist:miniapp:rl:auth_ip:{other}")
    finally:
        await ca.aclose()
        await cb.aclose()

    if server is None:
        T.skip("uzilish va tiklanish bosqichlari", "BLOCKED: tayyor URL berilgan — serverni test boshqara olmaydi")
        return

    print("\n== 2. Redis uzildi -> 503 (xotira fallback umumiy deb qabul qilinmaydi) ==")
    c, cc = make_backend(url, cooldown=1.0)
    lc = StrictLimiter(require_shared=True, backend_getter=lambda: c)
    try:
        subj = "t-" + uuid.uuid4().hex
        T.check("server ishlaganda ruxsat", await hit(lc, subj) == "ok")
        server.stop()
        await asyncio.sleep(0.3)
        started = time.monotonic()
        T.check("server o'chdi: limiter 503 (jim ruxsat YO'Q)", await hit(lc, subj) == "service_unavailable")
        T.check("503 tez qaytdi (< 3 s)", time.monotonic() - started < 3.0)
        for _ in range(3):
            await c.incr("other-consumer", ttl=5)  # boshqa iste'molchilar breaker'ni ochadi (fallback xotira)
        T.check("breaker ochildi, fallback xotiraga o'tildi", c.circuit_open)
        T.check("breaker ochiq: shared_primary None, limiter 503", shared_primary(c) is None and await hit(lc, subj) == "service_unavailable")
        T.check("xotira hisoblagichiga miniapp kaliti yozilmadi", not [k for k in c._fallback._data if "miniapp" in k])

        print("\n== 3. Tiklanish ==")
        server.start()
        await asyncio.sleep(1.2)  # cooldown (1 s) o'tdi
        T.check("server qaytdi + cooldown o'tdi: limiter yana ishlaydi", await hit(lc, "t-" + uuid.uuid4().hex) == "ok")
    finally:
        await cc.aclose()


def main() -> int:
    try:
        import redis  # noqa: F401
    except ImportError:
        T.skip("real Redis testi", "BLOCKED: Python `redis` paketi o'rnatilmagan (requirements.txt'da ixtiyoriy paket)")
        return T.finish()

    url = os.getenv("MINIAPP_TEST_REDIS_URL", "").strip()
    server = None
    if url:
        host = urlparse(url).hostname or ""
        if host not in LOCAL_HOSTS:
            T.skip("real Redis testi", f"SKIP: faqat lokal Redis ruxsat etiladi (host={host!r}); production'ga ulanilmaydi")
            return T.finish()
    else:
        binary = shutil.which("redis-server")
        if not binary:
            T.skip("real Redis testi", "BLOCKED: redis-server binary topilmadi va MINIAPP_TEST_REDIS_URL berilmagan")
            return T.finish()
        server = LocalRedis(binary)
        try:
            server.start()
        except Exception as exc:  # noqa: BLE001
            server.cleanup()
            T.skip("real Redis testi", f"BLOCKED: lokal redis-server ishga tushmadi ({type(exc).__name__})")
            return T.finish()
        url = server.url
    try:
        asyncio.run(run_shared(url, server))
    finally:
        if server:
            server.cleanup()
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
