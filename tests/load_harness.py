# -*- coding: utf-8 -*-
"""=====================================================================
 ⚡ PHASE 11 — LOAD / STRESS HARNESS (mock Telegram + metrikalar)
=====================================================================

Bu modul yuklama sinovlarining yagona o'lchov qatlami:

  * ``MockTelegramServer`` (``staging.mock_telegram_server``) — HAQIQIY
    Telegram API o'rniga ishlaydigan mock server. Bot butun tarmoq zanjirini
    (PTB → HTTPX → TCP → JSON) haqiqiy holda bosib o'tadi, lekin hech qanday
    so'rov Telegram'ga ketmaydi (spam YO'Q).
  * ``Metrics`` — throughput (RPS), latency (p50/p95/p99/max), error rate.
  * ``rss_mb()`` / ``memory_growth_mb()`` — xotira oqimi (leak) o'lchovi.
  * ``LoadProfile`` — profil tavsifi (10 logical / 100 concurrent /
    1000 concurrent requests) va natijalarni baholash mezonlari.

Barcha o'lchovlar **deterministik bo'lmagan** (real vaqt) kattaliklar, shu
sababli mezonlar ataylab KONSERVATIV (masalan, p99 < 3 s) — maqsad
regressiyani ushlash, raqamni "go'zallashtirish" emas.
"""

from __future__ import annotations

import asyncio
import gc
import os
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

#: Mock server uchun standart token (haqiqiy token EMAS — faqat test).
LOAD_TEST_TOKEN = "123456:LOAD_TEST_MOCK_TOKEN"

#: Latency namunalarining maksimal soni (xotira chegarasi).
MAX_SAMPLES = 100000


# ──────────────────────────────────────────────────────────────
# XOTIRA (memory leak) O'LCHOVLARI
# ──────────────────────────────────────────────────────────────
def rss_mb() -> float:
    """Joriy jarayonning RSS (VmRSS) qiymati, MB. O'lchanmasa -1."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        return -1.0
    return -1.0


def memory_growth_mb(fn: Callable[[], Any]) -> dict:
    """``fn()`` atrofida RSS o'sishini o'lchaydi (leak diagnostikasi).

    Qaytadi: ``{"before_mb", "after_mb", "growth_mb", "ok"}`` — ``ok``
    ``False`` bo'lsa platforma RSS o'qishni qo'llab-quvvatlamaydi.
    """
    gc.collect()
    before = rss_mb()
    fn()
    gc.collect()
    after = rss_mb()
    if before < 0 or after < 0:
        return {"before_mb": before, "after_mb": after, "growth_mb": -1.0, "ok": False}
    return {"before_mb": round(before, 1), "after_mb": round(after, 1),
            "growth_mb": round(after - before, 1), "ok": True}


# ──────────────────────────────────────────────────────────────
# METRIKALAR
# ──────────────────────────────────────────────────────────────
def percentiles(values: Iterable[float]) -> dict:
    """p50/p95/p99/max/avg (bo'sh ro'yxatda — nollar)."""
    samples = sorted(float(v) for v in values)
    if not samples:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "avg": 0.0}
    def _pick(p: float) -> float:
        idx = min(len(samples) - 1, int(round(p / 100.0 * (len(samples) - 1))))
        return round(samples[idx], 2)
    return {"p50": _pick(50), "p95": _pick(95), "p99": _pick(99),
            "max": round(samples[-1], 2), "avg": round(statistics.fmean(samples), 2)}


@dataclass
class Metrics:
    """Yagona o'lchov to'plami: RPS, latency, error rate."""

    name: str = "load"
    started_at: float = field(default_factory=time.perf_counter)
    finished_at: float | None = None
    latencies_ms: list[float] = field(default_factory=list)
    ok: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    labels: dict[str, Any] = field(default_factory=dict)

    # ---- yozib borish -------------------------------------------
    def record_ok(self, latency_ms: float) -> None:
        self.ok += 1
        if len(self.latencies_ms) < MAX_SAMPLES:
            self.latencies_ms.append(float(latency_ms))

    def record_error(self, error: Any, latency_ms: float | None = None) -> None:
        self.failed += 1
        if latency_ms is not None and len(self.latencies_ms) < MAX_SAMPLES:
            self.latencies_ms.append(float(latency_ms))
        if len(self.errors) < 25:
            self.errors.append(type(error).__name__ if isinstance(error, BaseException)
                               else str(error))

    def finish(self) -> "Metrics":
        self.finished_at = time.perf_counter()
        return self

    # ---- natijalar ----------------------------------------------
    @property
    def total(self) -> int:
        return self.ok + self.failed

    @property
    def elapsed(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.perf_counter()
        return max(1e-9, end - self.started_at)

    @property
    def rps(self) -> float:
        return round(self.total / self.elapsed, 1)

    @property
    def error_rate(self) -> float:
        return round((self.failed / self.total) if self.total else 0.0, 5)

    def latency(self) -> dict:
        return percentiles(self.latencies_ms)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "total": self.total,
            "ok": self.ok,
            "failed": self.failed,
            "error_rate": self.error_rate,
            "elapsed_s": round(self.elapsed, 3),
            "rps": self.rps,
            "latency_ms": self.latency(),
            "errors": list(self.errors),
            "labels": dict(self.labels),
        }

    def summary_line(self) -> str:
        lat = self.latency()
        return (f"{self.name}: {self.total} so'rov, {self.rps} RPS, "
                f"xato={self.error_rate * 100:.2f}%, "
                f"p50={lat['p50']}ms p95={lat['p95']}ms p99={lat['p99']}ms")


@dataclass
class LoadProfile:
    """Yuklama profili va qabul mezonlari.

    ``min_rps`` / ``max_p99_ms`` / ``max_error_rate`` — KONSERVATIV chegaralar;
    muhit juda sekin bo'lsa (masalan, 1 vCPU CI runner) test buni ``NOT TESTED``
    deb belgilaydi, soxta PASS yozmaydi.
    """

    name: str
    users: int
    requests_per_user: int
    concurrency: int
    min_rps: float = 20.0
    max_p99_ms: float = 3000.0
    max_error_rate: float = 0.0

    @property
    def expected_requests(self) -> int:
        return max(1, self.users * self.requests_per_user)


# ──────────────────────────────────────────────────────────────
# MOCK TELEGRAM + BOT
# ──────────────────────────────────────────────────────────────
async def start_mock_telegram(port: int = 0):
    """In-process mock Telegram serverni ishga tushiradi (ayni loop ichida)."""
    from staging.mock_telegram_server import MockTelegramServer

    server = MockTelegramServer(host="127.0.0.1", port=port)
    await server.start()
    return server


def build_mock_bot(base_url: str, *, token: str = LOAD_TEST_TOKEN,
                   pool_size: int = 128, read_timeout: float = 30.0):
    """Mock serverga qaraydigan ``SafeHTMLBot`` (haqiqiy sanitizer + HTTPX).

    ``SafeHTMLBot`` — production bot klassi: HTML SSOT sanitizatsiyasi va
    telemetriya ham yuklama ostida HAQIQIY yo'ldan o'tadi.
    """
    from telegram.request import HTTPXRequest
    from utils.telegram_delivery import SafeHTMLBot

    request = HTTPXRequest(
        connection_pool_size=int(pool_size),
        connect_timeout=10,
        read_timeout=float(read_timeout),
        write_timeout=float(read_timeout),
        pool_timeout=float(read_timeout),
    )
    return SafeHTMLBot(token=token, base_url=base_url, request=request,
                       get_updates_request=HTTPXRequest(connection_pool_size=2))


async def make_mock_bot(base_url: str, **kwargs):
    """``build_mock_bot`` + ``initialize()`` — PTB bot to'liq tayyor holatda.

    PTB ``Bot.initialize()`` chaqirilmasa ba'zi ichki xossalar (``bot.bot``)
    ishlamaydi; weakref/limiter qatlamlari esa shunga tayanadi.
    """
    bot = build_mock_bot(base_url, **kwargs)
    await bot.initialize()
    return bot


async def call_with_metrics(metrics: Metrics, coro_factory: Callable[[], Any]) -> Any:
    """Bitta chaqiruvni o'lchaydi (latency + muvaffaqiyat/xato)."""
    started = time.perf_counter()
    try:
        result = await coro_factory()
    except Exception as exc:  # noqa: BLE001 — yuklama ostida har qanday xato hisobga olinadi
        metrics.record_error(exc, (time.perf_counter() - started) * 1000)
        return None
    metrics.record_ok((time.perf_counter() - started) * 1000)
    return result


async def run_concurrent(jobs: list[Callable[[], Any]], *, max_inflight: int | None = None):
    """``jobs`` ni parallel ishlatadi (ixtiyoriy: bir vaqtda maksimal N ta)."""
    if not max_inflight or max_inflight >= len(jobs):
        return await asyncio.gather(*(job() for job in jobs))
    semaphore = asyncio.Semaphore(int(max_inflight))

    async def _guarded(job):
        async with semaphore:
            return await job()

    return await asyncio.gather(*(_guarded(job) for job in jobs))


# ──────────────────────────────────────────────────────────────
# ASYNCIO LEAK TEKSHIRUVI
# ──────────────────────────────────────────────────────────────
async def task_leak_probe(coro_factory: Callable[[], Any], *, settle: float = 0.05) -> int:
    """Yuklamadan keyin qolgan asyncio task'lar soni (leak bo'lsa > 0).

    O'lchov AYNI event loop ichida: yuklama tugagach done-callback'lar
    ishlashi uchun qisqa kutish beriladi.
    """
    before = len(asyncio.all_tasks())
    await coro_factory()
    await asyncio.sleep(settle)
    return len(asyncio.all_tasks()) - before


# ──────────────────────────────────────────────────────────────
# MUHIT IMKONIYATI (NOT TESTED shaffofligi)
# ──────────────────────────────────────────────────────────────
def environment_capabilities() -> dict:
    """CPU / bo'sh xotira / fayl deskriptorlari — og'ir profil uchun shart."""
    cpu = os.cpu_count() or 1
    memory_mb = -1.0
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    memory_mb = int(line.split()[1]) / 1024.0
                    break
    except Exception:
        memory_mb = -1.0
    try:
        import resource
        nofile = resource.getrlimit(resource.RLIMIT_NOFILE)
        fd_limit = int(nofile[0]) if isinstance(nofile, tuple) else int(nofile)
    except Exception:
        fd_limit = -1
    return {"cpus": cpu, "mem_available_mb": round(memory_mb, 1), "fd_limit": fd_limit}


def can_run_profile(profile: LoadProfile, caps: dict | None = None) -> tuple[bool, str]:
    """Profil muhitga sig'adimi (sig'masa — aniq sabab bilan NOT TESTED)."""
    caps = caps or environment_capabilities()
    memory = caps.get("mem_available_mb", -1)
    if memory >= 0 and memory < 256:
        return False, f"bo'sh xotira juda kam ({memory} MB < 256 MB)"
    fd_limit = caps.get("fd_limit", -1)
    needed = min(profile.concurrency, 512) + 128
    if fd_limit and fd_limit >= 0 and fd_limit < needed:
        return False, f"fayl deskriptorlari chegarasi past ({fd_limit} < {needed})"
    return True, ""
