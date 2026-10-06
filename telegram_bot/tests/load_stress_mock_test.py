#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 ⚡ PHASE 11 — LOAD & STRESS TESTLARI (MOCK TELEGRAM SERVER)
=====================================================================

Maqsad: botni **haqiqiy Telegram Bot API'ga birorta ham so'rov yubormasdan**
(mock Telegram server orqali) quyidagi yuklamalarda sinash:

  1. **10 logical users** — har biri to'liq foydalanuvchi yo'lini bosib
     o'tadi (DM /start → menyu → kanalga post → postni tahrirlash), bunda
     delivery engine'ning PRODUCTION rate-limitlari (1 post/s kanal,
     30 xabar/s global) HAQIQIY ishlaydi.
  2. **100 concurrent users** — 100 ta virtual foydalanuvchi bir vaqtda;
     har biri 5 so'rov (jami 500) — stress rejimida (limitlar ko'tarilgan,
     chunki maqsad transport/servis qatlamining throughput'i).
  3. **1000 concurrent requests** — bitta to'lqinda 1000 ta parallel Bot API
     so'rovi (RPS, latency p50/p95/p99, error rate).

O'lchovlar (har bir profil uchun):
  * Throughput — RPS;
  * Latency — p50 / p95 / p99 / max;
  * Error rate — muvaffaqiyatsiz so'rovlar ulushi;
  * DB pool usage — `telegram_bot/tests/load_test.py` (real PostgreSQL,
    pgserver) tomonidan o'lchanadi;
  * Memory leak — RSS o'sishi + asyncio task leak + delivery navbati (queue)
    qoldig'i (graceful shutdown bilan bog'liq).

Shaffoflik qoidasi (47-band): muhit og'ir profilni ko'tara olmasa natija
``[NOT TESTED]`` deb yoziladi — SOXTA PASS berilmaydi.

Ishga tushirish::

    cd telegram_bot && PYTHON=$HOME/venv/bin/python python tests/load_stress_mock_test.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ---- MUHIM: production modullar import qilinishidan OLDIN env sozlash ----
os.environ.setdefault("BOT_TOKEN", "123456:LOAD_STRESS_MOCK_TOKEN")
os.environ.setdefault("ADMIN_ID", "777000")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/loadmock")
os.environ.setdefault("ENVIRONMENT", "test")
# Staging: mock Telegram (haqiqiy API'ga so'rov YO'Q). Bu qiymat `create_safe_bot`
# tomonidan ishlatiladi; testlar o'z serverlarini dinamik portda ko'taradi.
os.environ.setdefault("TELEGRAM_API_BASE_URL", "")

from tests.load_harness import (  # noqa: E402
    LoadProfile, Metrics, call_with_metrics, can_run_profile,
    environment_capabilities, make_mock_bot, rss_mb, start_mock_telegram,
    task_leak_probe,
)

PASSED = 0
FAILED = 0
NOT_TESTED: list[tuple[str, str]] = []
#: Mashina o'qiydigan o'lchovlar (hisobot/test artefaktlari uchun: RPS,
#: p50/p95/p99, xato foizi, RSS o'sishi).
MEASUREMENTS: list[dict] = []


def check(name: str, cond: bool, extra: str = "") -> bool:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {extra}")
    return bool(cond)


def not_tested(name: str, reason: str) -> None:
    NOT_TESTED.append((name, reason))
    print(f"  [NOT TESTED] {name} — {reason}")


def section(title: str) -> None:
    print()
    print("=" * 66)
    print(f" {title}")
    print("=" * 66)


# ============================================================
# 🔎 0. MOCK TELEGRAM SERVER SANITY (haqiqiy tarmoq zanjiri)
# ============================================================
async def _scenario_sanity() -> None:
    from services.delivery import TelegramDeliveryService
    from services import lifecycle_service as lifecycle

    server = await start_mock_telegram()
    bot = await make_mock_bot(server.base_url)
    delivery = TelegramDeliveryService(global_per_second=0, channel_per_second=0)
    try:
        lifecycle.reset_for_tests()
        # 1) Bot ↔ mock server aloqasi HAQIQIY HTTP orqali.
        msg = await delivery.send_message(
            bot, chat_id=1, text="<b>Salom</b> — mock server sinovi")
        check("mock: sendMessage HTTP orqali ishladi",
              getattr(msg, "message_id", None) is not None, str(msg))

        # 2) Metrikalar endpointi (__stats) mock tomonda ishlaydi.
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(server.stats_url) as resp:
                stats = await resp.json()
        check("mock: /__stats metrikalari o'qiladi",
              stats.get("requests_total", 0) >= 1
              and "sendMessage" in (stats.get("methods") or {}),
              str(stats)[:120])

        # 3) HTML sanitizatsiya (SSOT) mock serverga YETIB BORGAN matnda ham
        #    kuchda: xavfli/uzilgan HTML tozalanadi (SafeHTMLBot qatlami).
        server.state.reset()
        await delivery.send_message(
            bot, chat_id=2,
            text="<script>alert(1)</script><b>Yaxshi<unclosed> post",
            parse_mode="HTML")
        received = server.state.last_texts[-1] if server.state.last_texts else ""
        check("mock: HTML sanitizer ishladi (script yo'q)",
              "<script" not in received.lower(), received[:80])
        check("mock: matn mock serverga yetib bordi", bool(received), repr(received)[:80])

        # 4) 429 in'yeksiyasi → PTB RetryAfter sifatida ko'rinadi.
        await _set_fault(server, {"mode": "429", "retry_after": 1})
        error_name = ""
        try:
            await bot.send_message(chat_id=3, text="429 sinovi")
        except Exception as exc:  # noqa: BLE001
            error_name = type(exc).__name__
        await _set_fault(server, {"mode": "off"})
        check("mock: 429 → RetryAfter (PTB xato sinfi)",
              error_name == "RetryAfter", error_name)

        # 5) Delivery navbati (queue) bo'shab qoldi — leak yo'q.
        check("mock: delivery navbati bo'sh (queue leak yo'q)",
              lifecycle.queue_pending() == {}, str(lifecycle.queue_pending()))
        check("PHASE 12: shutdown drenaj byudjeti ≥ 15 s",
              lifecycle.SHUTDOWN_GRACE_SECONDS >= 15.0,
              str(lifecycle.SHUTDOWN_GRACE_SECONDS))
    finally:
        await bot.shutdown()
        await server.stop()


async def _set_fault(server, payload: dict) -> None:
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{server.port}/__fault", json=payload):
            pass


# ============================================================
# 👤 1. 10 LOGICAL USERS (production rate-limitlari bilan)
# ============================================================
async def _user_journey(delivery, bot, user_no: int, metrics: Metrics,
                        *, chat_offset: int = 0) -> None:
    """Bitta "logical user" ning to'liq yo'li (4 ta haqiqiy so'rov)."""
    dm = 100000 + chat_offset + user_no
    channel = -1000000 - chat_offset - user_no

    async def _send(chat_id, text, **kwargs):
        return await call_with_metrics(
            metrics,
            lambda: delivery.send_message(bot, chat_id=chat_id, text=text, **kwargs))

    await _send(dm, "<b>Salom!</b> PostAssist'ga xush kelibsiz (mock).")
    await _send(dm, "🏠 Asosiy menyu: [✍️ Post yaratish] [📢 Kanallarim]",
                reply_markup={"keyboard": [["✍️ Post yaratish", "📢 Kanallarim"]],
                              "resize_keyboard": True})
    post = await _send(channel, "🚀 <b>Yangi post</b>\n\nFoydali kontent matni.",
                       parse_mode="HTML")
    message_id = getattr(post, "message_id", None) or 1
    await call_with_metrics(
        metrics,
        lambda: delivery.execute(
            bot, "edit_message_text", chat_id=channel, message_id=message_id,
            text="🚀 <b>Yangi post</b> (tahrirlandi)", parse_mode="HTML"))


async def _scenario_logical_users() -> None:
    from services.delivery import TelegramDeliveryService
    from services import lifecycle_service as lifecycle

    profile = LoadProfile(name="10 logical users", users=10, requests_per_user=4,
                          concurrency=1, min_rps=1.0, max_p99_ms=5000.0)
    caps = environment_capabilities()
    runnable, reason = can_run_profile(profile, caps)
    if not runnable:
        not_tested(profile.name, reason)
        return

    server = await start_mock_telegram()
    bot = await make_mock_bot(server.base_url, pool_size=32)
    # PRODUCTION limitlari ATAYLAB saqlanadi: 30 xabar/s global, 1 post/s kanal.
    delivery = TelegramDeliveryService(global_per_second=30.0, channel_per_second=1.0)
    metrics = Metrics(name=profile.name)
    try:
        lifecycle.reset_for_tests()
        mock_baseline = server.state.requests_total   # bot.initialize() → getMe
        started = time.perf_counter()
        await asyncio.gather(*(
            _user_journey(delivery, bot, i, metrics) for i in range(profile.users)))
        elapsed = time.perf_counter() - started
        metrics.finish()
        metrics.labels.update({"elapsed_wall_s": round(elapsed, 3),
                               "mock_requests": server.state.requests_total})

        metrics.finish()
        print(f"    → {metrics.summary_line()} (devor vaqti {elapsed:.2f}s)")
        MEASUREMENTS.append({**metrics.as_dict(), "wall_seconds": round(elapsed, 3)})
        check("LOAD-10: barcha so'rovlar muvaffaqiyatli",
              metrics.failed == 0 and metrics.total == profile.expected_requests,
              f"ok={metrics.ok} failed={metrics.failed} errors={metrics.errors}")
        check("LOAD-10: error rate 0%", metrics.error_rate == 0.0,
              f"{metrics.error_rate}")
        mock_requests = server.state.requests_total - mock_baseline
        check("LOAD-10: mock serverda 40 so'rov qayd etildi (4 × 10)",
              mock_requests == profile.expected_requests, str(mock_requests))
        check("LOAD-10: production rate-limit hurmat qilindi (30/s)",
              elapsed >= (profile.expected_requests / 30.0) * 0.5,
              f"elapsed={elapsed:.3f}s")
        lat = metrics.latency()
        check("LOAD-10: p95 latency chegarada (< 5s)", lat["p95"] < 5000.0, str(lat))
        check("LOAD-10: delivery navbati drenaj bo'ldi",
              lifecycle.queue_pending() == {}, str(lifecycle.queue_pending()))
    finally:
        await bot.shutdown()
        await server.stop()


# ============================================================
# 👥 2. 100 CONCURRENT USERS (stress rejimi)
# ============================================================
async def _scenario_concurrent_users() -> None:
    from services.delivery import TelegramDeliveryService
    from services import lifecycle_service as lifecycle

    # Har bir foydalanuvchi 5 so'rov: 500 so'rov / 100 parallel user.
    profile = LoadProfile(name="100 concurrent users", users=100, requests_per_user=5,
                          concurrency=50, min_rps=30.0, max_p99_ms=5000.0)
    caps = environment_capabilities()
    runnable, reason = can_run_profile(profile, caps)
    if not runnable:
        not_tested(profile.name, reason)
        return

    server = await start_mock_telegram()
    bot = await make_mock_bot(server.base_url, pool_size=64)
    # STRESS REJIMI: rate-limitlar ko'tarilgan (maqsad — transport/servis
    # throughput'i, limiter siyosati emas; limiter alohida suite'da qulflangan).
    delivery = TelegramDeliveryService(global_per_second=2000.0, channel_per_second=500.0)
    metrics = Metrics(name=profile.name)
    mock_baseline = server.state.requests_total

    async def _one_user(user_no: int):
        dm = 200000 + user_no
        for step in range(profile.requests_per_user):
            await call_with_metrics(
                metrics,
                lambda step=step: delivery.send_message(
                    bot, chat_id=dm,
                    text=f"<b>User {user_no}</b> — qadam {step + 1}/5",
                    parse_mode="HTML"))

    try:
        lifecycle.reset_for_tests()
        tasks = [asyncio.create_task(_one_user(i)) for i in range(profile.users)]
        await asyncio.wait(tasks, timeout=90)
        metrics.finish()
        pending_tasks = sum(1 for t in tasks if not t.done())
        check("LOAD-100: barcha virtual foydalanuvchilar tugadi",
              pending_tasks == 0, f"pending={pending_tasks}")

        print(f"    → {metrics.summary_line()}")
        MEASUREMENTS.append(metrics.as_dict())
        check("LOAD-100: 500 so'rov muvaffaqiyatli",
              metrics.total == profile.expected_requests and metrics.failed == 0,
              f"ok={metrics.ok} failed={metrics.failed} errors={metrics.errors}")
        check("LOAD-100: error rate 0%", metrics.error_rate == 0.0,
              f"{metrics.error_rate}")
        lat = metrics.latency()
        check("LOAD-100: p99 latency < 5s", lat["p99"] < profile.max_p99_ms, str(lat))
        check("LOAD-100: throughput ≥ 30 RPS", metrics.rps >= profile.min_rps,
              f"{metrics.rps} RPS")
        mock_requests = server.state.requests_total - mock_baseline
        check("LOAD-100: mock server barcha so'rovlarni qabul qildi",
              mock_requests == profile.expected_requests, str(mock_requests))
        check("LOAD-100: delivery navbati bo'sh (queue leak yo'q)",
              lifecycle.queue_pending() == {}, str(lifecycle.queue_pending()))

        # asyncio task leak: qo'shimcha yuklamadan keyin ham 0 qoldiq.
        leak = await task_leak_probe(lambda: asyncio.gather(*(
            delivery.send_message(bot, chat_id=300000 + i, text="leak probe")
            for i in range(20))))

        check("LOAD-100: asyncio task leak yo'q", leak <= 0, f"leak={leak}")
    finally:
        await bot.shutdown()
        await server.stop()


# ============================================================
# 🌊 3. 1000 CONCURRENT REQUESTS (throughput sinovi)
# ============================================================
async def _scenario_1000_requests() -> None:
    from services import lifecycle_service as lifecycle

    profile = LoadProfile(name="1000 concurrent requests", users=1000,
                          requests_per_user=1, concurrency=1000,
                          min_rps=100.0, max_p99_ms=5000.0)
    caps = environment_capabilities()
    runnable, reason = can_run_profile(profile, caps)
    if not runnable:
        not_tested(profile.name, reason)
        return

    server = await start_mock_telegram()
    bot = await make_mock_bot(server.base_url, pool_size=256)
    metrics = Metrics(name=profile.name)
    mock_baseline = server.state.requests_total
    rss_before = rss_mb()
    try:
        lifecycle.reset_for_tests()
        # Bitta to'lqin: 1000 ta so'rov BIR VAQTDA yuboriladi.
        wave = [
            call_with_metrics(
                metrics,
                lambda i=i: bot.send_message(
                    chat_id=400000 + i,
                    text=f"to'lqin #{i} — <b>HTML</b> chegara sinovi",
                    parse_mode="HTML"))
            for i in range(1000)
        ]
        await asyncio.gather(*wave)
        metrics.finish()

        print(f"    → {metrics.summary_line()}")
        MEASUREMENTS.append(metrics.as_dict())
        check("LOAD-1000: barcha 1000 so'rov muvaffaqiyatli",
              metrics.total == 1000 and metrics.failed == 0,
              f"ok={metrics.ok} failed={metrics.failed} errors={metrics.errors}")
        check("LOAD-1000: error rate 0%", metrics.error_rate == 0.0,
              f"{metrics.error_rate}")
        mock_requests = server.state.requests_total - mock_baseline
        check("LOAD-1000: mock server 1000 so'rovni qabul qildi",
              mock_requests == 1000, str(mock_requests))
        lat = metrics.latency()
        check("LOAD-1000: p99 latency < 5s", lat["p99"] < profile.max_p99_ms, str(lat))
        check("LOAD-1000: throughput ≥ 100 RPS", metrics.rps >= profile.min_rps,
              f"{metrics.rps} RPS")

        rss_after = rss_mb()
        if rss_before > 0 and rss_after > 0:
            growth = rss_after - rss_before
            check("LOAD-1000: xotira o'sishi chegarada (< 200 MB)",
                  growth < 200.0, f"growth={growth:.1f} MB")
        else:
            not_tested("LOAD-1000: RSS o'sishi", "RSS o'qib bo'lmadi (no-Linux?)")
        check("LOAD-1000: barcha lifecycle navbatlari bo'sh",
              lifecycle.queue_pending() == {}, str(lifecycle.queue_pending()))
    finally:
        await bot.shutdown()
        await server.stop()


# ============================================================
# 💧 4. MEMORY LEAK — KO'P TAKRORIY TO'LQINLAR
# ============================================================
async def _scenario_memory_leak() -> None:
    from services import lifecycle_service as lifecycle

    server = await start_mock_telegram()
    bot = await make_mock_bot(server.base_url, pool_size=64)

    async def _burst() -> None:
        await asyncio.gather(*(
            bot.send_message(chat_id=500000 + i, text=f"burst #{i}")
            for i in range(200)))

    try:
        lifecycle.reset_for_tests()
        await _burst()          # isinish (bir martalik allokatsiyalar)
        gc_before = rss_mb()
        for _ in range(4):
            await _burst()
        gc_after = rss_mb()
        if gc_before > 0 and gc_after > 0:
            growth = gc_after - gc_before
            per_burst = growth / 4.0
            check("LEAK: 4 × 200 so'rovdan keyin RSS o'sishi < 40 MB",
                  growth < 40.0, f"growth={growth:.1f} MB")
            check("LEAK: o'rtacha o'sish < 10 MB/to'lqin",
                  per_burst < 10.0, f"per_burst={per_burst:.2f} MB")
            MEASUREMENTS.append({
                "name": "memory leak (4 × 200 so'rov)",
                "requests": 800, "rss_growth_mb": round(growth, 2),
                "per_burst_mb": round(per_burst, 2),
            })
        else:
            not_tested("LEAK: RSS o'sishi", "RSS o'qib bo'lmadi")
        check("LEAK: lifecycle navbatlari bo'sh", lifecycle.queue_pending() == {},
              str(lifecycle.queue_pending()))
    finally:
        await bot.shutdown()
        await server.stop()


# ============================================================
# 🛑 5. GRACEFUL SHUTDOWN — YUKLAMA OSTIDA DRENAJ (PHASE 12 bilan bog'liq)
# ============================================================
async def _scenario_shutdown_drain() -> None:
    from services import lifecycle_service as lifecycle
    from services.delivery import TelegramDeliveryService

    server = await start_mock_telegram()
    # Kechikishli javob: drenaj HAQIQATAN kutayotganini ko'rsatadi.
    await _set_fault(server, {"mode": "off", "latency_ms": 100})
    bot = await make_mock_bot(server.base_url, pool_size=64)
    delivery = TelegramDeliveryService(global_per_second=2000.0, channel_per_second=500.0)
    metrics = Metrics(name="shutdown drain")
    try:
        lifecycle.reset_for_tests()
        jobs = [
            call_with_metrics(metrics, lambda i=i: delivery.send_message(
                bot, chat_id=600000 + i, text=f"drenaj #{i}"))
            for i in range(300)
        ]
        tasks = [asyncio.create_task(job) for job in jobs]
        await asyncio.sleep(0.2)    # so'rovlar uchib ketdi, hali tugamagan

        in_flight = lifecycle.queue_pending_total()
        lifecycle.request_shutdown("SIGTERM")
        check("DRAIN: shutdown paytida navbatda birliklar bor", in_flight > 0,
              f"pending={in_flight}")
        drained = await lifecycle.wait_for_drain(15.0)
        await asyncio.gather(*tasks, return_exceptions=True)
        metrics.finish()

        print(f"    → {metrics.summary_line()}")
        MEASUREMENTS.append(metrics.as_dict())
        check("DRAIN: 15 s byudjetda to'liq drenaj", drained["drained"] is True,
              str(drained)[:200])
        check("DRAIN: navbatdagi barcha 300 so'rov BEKOR QILINMADI (yetib bordi)",
              metrics.ok == 300 and metrics.failed == 0,
              f"ok={metrics.ok} failed={metrics.failed}")
        check("DRAIN: navbat bo'sh", lifecycle.queue_pending() == {},
              str(lifecycle.queue_pending()))
        check("DRAIN: qayta signal yopilishni boshlamaydi",
              lifecycle.request_shutdown("SIGTERM") is False)
        status = lifecycle.status()
        check("DRAIN: status() shutdown holatini ko'rsatadi",
              status["shutting_down"] is True and status["queued_total"] == 0,
              str(status))
    finally:
        lifecycle.reset_for_tests()
        await bot.shutdown()
        await server.stop()


# ============================================================
# MAIN
# ============================================================
def main() -> int:
    print("=" * 66)
    print(" ⚡ PHASE 11 — LOAD & STRESS (MOCK TELEGRAM SERVER)")
    print("=" * 66)
    caps = environment_capabilities()
    print(f" Muhit: CPU={caps['cpus']} · bo'sh RAM={caps['mem_available_mb']} MB · "
          f"fd limit={caps['fd_limit']}")
    print(" Telegram API: MOCK server (haqiqiy API'ga so'rov YO'Q)")

    section("0) MOCK TELEGRAM SERVER — HAQIQIY TARMOQ ZANJIRI")
    asyncio.run(_scenario_sanity())

    section("1) 👤 10 LOGICAL USERS (production rate-limitlari)")
    asyncio.run(_scenario_logical_users())

    section("2) 👥 100 CONCURRENT USERS (500 so'rov)")
    asyncio.run(_scenario_concurrent_users())

    section("3) 🌊 1000 CONCURRENT REQUESTS")
    asyncio.run(_scenario_1000_requests())

    section("4) 💧 MEMORY LEAK (4 to'lqin × 200 so'rov)")
    asyncio.run(_scenario_memory_leak())

    section("5) 🛑 GRACEFUL SHUTDOWN — DRENAJ YUKLAMA OSTIDA")
    asyncio.run(_scenario_shutdown_drain())

    print()
    print("=" * 66)
    if MEASUREMENTS:
        print(" O'LCHOVLAR (JSON — hisobot artefakti uchun):")
        print("MEASUREMENTS_JSON=" + json.dumps(MEASUREMENTS, ensure_ascii=False))
    print(f" NATIJA: [OK]={PASSED}  [FAIL]={FAILED}  [NOT TESTED]={len(NOT_TESTED)}")
    for name, reason in NOT_TESTED:
        print(f"   - {name}: {reason}")
    print("=" * 66)
    if FAILED:
        print(" ❌ PHASE 11 LOAD SUITE: FAIL")
        return 1
    print(" ✅ PHASE 11 LOAD SUITE: 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
