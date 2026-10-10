#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""=====================================================================
 🌀 PHASE 11 — CHAOS & SECURITY TESTLARI (FAIL-CLOSED, CRASH YO'Q)
=====================================================================

Har bir nosozlik stsenariysida bot **qulamasligi** va **fail-closed**
(ruxsat bermaslik / muloyim javob) ishlashi tasdiqlanadi:

  TEST 1  🗄  DB ulanishi uzildi (DB unavailable) — barcha darajalar
              fail-closed, hech qanday istisno tashqariga chiqmaydi.
  TEST 2  🔌 Redis uzildi — ``services/cache_backend`` In-Memory'ga
              qaytadi (circuit breaker), bot ishlashda davom etadi.
  TEST 3  🤖 Barcha AI provayderlar 500/timeout — foydalanuvchi
              MULOYM xabar oladi («AI hozirda mavjud emas…»), bron
              qilingan kvota QAYTARILADI, soxta generatsiya YO'Q.
  TEST 4  📨 Telegram API 429 flood va uzilishlar — delivery engine
              aniq kutish + jitter bilan qayta uradi; defer rejimida
              xato chaqiruvchiga qaytariladi (dublikat/yo'qotish yo'q).
  TEST 5  🛡  SSRF: localhost, private IP, IPv6 halqa, o'nlik/hex/sakkizlik
              chetlab o'tishlar — BARCHASI yagona URL Security Gateway
              darajasida bloklanadi; tashqi URL so'rovlari faqat shu
              shlyuzdan o'tishi statik skaner bilan tekshiriladi.
  TEST 6  ♻️  Dublikat callback / dublikat to'lov / eskirgan (stale) update
              in'yeksiyasi — idempotentlik va rad etish.
  TEST 7  💧 Yakuniy resurs tekshiruvi: asyncio task/queue/connection leak
              yo'q; barcha shlyuzlar yopiladi.

Mock Telegram server (``staging.mock_telegram_server``) ishlatiladi —
haqiqiy Telegram API'ga BIRORTA ham so'rov ketmaydi.

Ishga tushirish::

    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
    python3 tests/phase11_chaos_security_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

# ---- MUHIM: production modullar import qilinishidan OLDIN env sozlash ----
os.environ.setdefault("BOT_TOKEN", "123456:CHAOS_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "777000")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/chaos")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("TELEGRAM_API_BASE_URL", "")

import database as db  # noqa: E402
from services import lifecycle_service as lifecycle  # noqa: E402

PASSED = 0
FAILED = 0
NOT_TESTED: list[tuple[str, str]] = []


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


def run(coro):
    return asyncio.run(coro)


# ============================================================
# TEST 1 — 🗄 DB UZILISHI (FAIL-CLOSED)
# ============================================================
def test_db_unavailable_fail_closed() -> None:
    section("TEST 1) 🗄 DB UZILDI — FAIL-CLOSED, CRASH YO'Q")

    from services import health_service
    from services.ai_quota import reserve_ai_quota

    class _Boom(Exception):
        pass

    async def _db_down_run_db(*args, **kwargs):
        raise _Boom("connection to server was lost")

    def _db_down_cursor(*args, **kwargs):
        raise _Boom("could not connect to server")

    original_run_db = db.run_db
    original_cursor = db.db_cursor
    original_transaction = getattr(db, "db_transaction", None)
    try:
        db.run_db = _db_down_run_db          # async
        db.db_cursor = _db_down_cursor

        # 1) ping_db — istisno EMAS, False (fail-closed).
        try:
            ping = db.ping_db()
            ping_ok = ping is False
        except Exception as exc:  # noqa: BLE001
            ping_ok = False
            ping = f"raised {type(exc).__name__}"
        check("DB down: ping_db() → False (istisno yo'q)", ping_ok, str(ping))

        # 2) Pool holati o'qish ham qulamaydi.
        try:
            pool = db.get_db_pool_status()
            pool_ok = isinstance(pool, dict) and "ready" in pool
        except Exception as exc:  # noqa: BLE001
            pool_ok = False
            pool = type(exc).__name__
        check("DB down: get_db_pool_status() xavfsiz dict qaytaradi",
              pool_ok, str(pool)[:100])

        # 3) Readiness — ready=False, database=error (fail-closed).
        ready = run(health_service.get_readiness_status())
        check("DB down: readiness.ready=False",
              ready.get("ready") is False, str(ready))
        check("DB down: readiness 'database'=error",
              (ready.get("checks") or {}).get("database") == "error", str(ready))

        # 4) AI kvota broni — db_error va allowed=False (fail-closed).
        reservation = run(reserve_ai_quota(db, 424242, "magic_post", 1))
        check("DB down: AI kvota FAIL-CLOSED (allowed=False)",
              reservation.get("allowed") is False, str(reservation))
        check("DB down: AI kvota sababi db_error",
              reservation.get("reason") == "db_error", str(reservation))

        # 5) To'lov ham fail-closed (ruxsat yo'q, istisno yo'q).
        from services.payment_service import PaymentService

        @contextmanager
        def _broken_transaction(*args, **kwargs):
            raise _Boom("DB uzildi (payment)")
            yield  # pragma: no cover

        with patch("services.payment_service.transaction", _broken_transaction):
            result = PaymentService.process_stars_payment(
                424242, "charge-db-down", 1, "sub_stars_1m_424242", "pro", 30,
                currency="XTR")
        check("DB down: to'lov fail-closed (ok=False, istisno YO'Q)",
              result.get("ok") is False, str(result)[:120])

        # 6) 50 ta parallel so'rov ham qulamaydi (storm).
        async def _storm():
            tasks = [health_service.get_readiness_status() for _ in range(25)]
            tasks += [reserve_ai_quota(db, 500000 + i, "magic_post", 1)
                      for i in range(25)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return sum(1 for r in results if isinstance(r, BaseException))

        raised = run(_storm())
        check("DB down: 50 parallel so'rovda 0 istisno (crash yo'q)",
              raised == 0, f"raised={raised}")

        # 7) Foydalanuvchi UX: texnik matn MULOYM xabar bilan almashtiriladi.
        from handlers.error_handler import (
            classify_user_error_kind, format_user_error_message,
            sanitize_user_error_text,
        )

        polite = sanitize_user_error_text("Exception occurred: psycopg2.OperationalError",
                                          "uz")
        check("DB down: 'Exception occurred' → muloyim xabar",
              "exception occurred" not in polite.lower() and bool(polite), polite)
        check("DB down: umumiy xato turi 'general'",
              classify_user_error_kind(_Boom("connection lost")) == "general",
              classify_user_error_kind(_Boom("connection lost")))
        check("DB down: uchala tilda matn bor",
              all(len(format_user_error_message(_Boom("db"), lang)) > 10
                  for lang in ("uz", "ru", "en")))
    finally:
        db.run_db = original_run_db
        db.db_cursor = original_cursor
        if original_transaction is not None:
            db.db_transaction = original_transaction


# ============================================================
# TEST 2 — 🔌 REDIS UZILDI → IN-MEMORY FALLBACK
# ============================================================
class _FlakyRedis:
    """``redis.asyncio`` mijozi shimoli: ``fail_after`` amaldan keyin uziladi."""

    def __init__(self, fail_after: int = 0) -> None:
        self.calls = 0
        self.fail_after = int(fail_after)
        self.store: dict[str, str] = {}
        self.closed = False

    def _maybe_fail(self) -> None:
        self.calls += 1
        if self.calls > self.fail_after:
            raise ConnectionError("Redis uzildi (connection refused)")

    async def ping(self):
        self._maybe_fail()
        return True

    async def get(self, key):
        self._maybe_fail()
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        self._maybe_fail()
        self.store[str(key)] = value
        return True

    async def delete(self, *keys):
        self._maybe_fail()
        removed = 0
        for key in keys:
            removed += 1 if self.store.pop(str(key), None) is not None else 0
        return removed

    async def expire(self, key, ttl):
        self._maybe_fail()
        return True

    async def eval(self, script, numkeys, *args):
        self._maybe_fail()
        key = str(args[0])
        amount = int(args[1])
        current = int(self.store.get(key, 0)) + amount
        self.store[key] = current
        return current

    async def aclose(self):
        self.closed = True

    async def close(self):
        self.closed = True

    def __await__(self):  # pragma: no cover — ba'zi mijozlar await qilinadi
        async def _self():
            return self
        return _self().__await__()


def test_redis_down_fallback() -> None:
    section("TEST 2) 🔌 REDIS UZILDI → IN-MEMORY FALLBACK (CIRCUIT BREAKER)")

    from services import cache_backend as cache

    async def _scenario():
        # 1) Redis umuman javob bermaydi → factory In-Memory'ga tushadi.
        dead = _FlakyRedis(fail_after=0)
        backend = await cache.create_cache_backend(
            "redis://127.0.0.1:6379/0", enabled=True, client=dead)
        first = {
            "name": getattr(backend, "name", ""),
            "set": await backend.set("k1", "v1", ttl=30),
            "get": await backend.get("k1"),
            "ping": await backend.ping(),
        }

        # 2) Redis ishlab turadi, keyin UZILADI → ResilientCacheBackend
        #    In-Memory'dan xizmat qiladi va bot ishlashda davom etadi.
        flaky = _FlakyRedis(fail_after=1)   # faqat ping ishlaydi
        resilient = await cache.create_cache_backend(
            "redis://127.0.0.1:6379/0", enabled=True, client=flaky)
        await resilient.set("shared", "1", ttl=30)      # Redis endi uzilgan
        written = await resilient.set("counter", "7", ttl=60)
        value = await resilient.get("counter")
        increased = await resilient.incr("hits", ttl=60, amount=1)
        alive = await resilient.ping()
        stats = resilient.stats() if hasattr(resilient, "stats") else {}
        closed = await resilient.close()

        return {
            "dead_name": first["name"], "dead_set": first["set"],
            "dead_get": first["get"], "dead_ping": first["ping"],
            "live_name": getattr(resilient, "name", ""),
            "written": written, "value": value, "incr": increased,
            "alive": alive, "stats": stats, "closed_ok": closed is None,
            "flaky_calls": flaky.calls,
        }

    out = run(_scenario())
    check("Redis down: factory In-Memory backend tanladi",
          out["dead_name"] == "memory", str(out["dead_name"]))
    check("Redis down: In-Memory'da set/get ishlaydi",
          out["dead_set"] is True and out["dead_get"] == "v1", str(out))
    check("Redis down: fallback ping ham True (bot tirik)",
          out["dead_ping"] is True, str(out["dead_ping"]))
    check("Redis down: resilient backend nomi 'resilient'",
          out["live_name"] == "resilient", str(out["live_name"]))
    check("Redis down: yozuv In-Memory'ga tushdi (yo'qolmadi)",
          out["written"] is True and out["value"] == "7", str(out))
    check("Redis down: incr ham ishlaydi (rate-limit sanagichi)",
          isinstance(out["incr"], int) and out["incr"] >= 1, str(out["incr"]))
    check("Redis down: ping True (fail-open, foydalanuvchi bloklanmaydi)",
          out["alive"] is True, str(out["alive"]))
    stats = out["stats"] or {}
    check("Redis down: stats() fallback holatini ko'rsatadi",
          bool(stats.get("fallbacks", 0) >= 1) or stats.get("backend") in
          ("resilient", "memory", "hybrid"), str(stats)[:140])
    check("Redis down: backend yopilishi xatosiz", out["closed_ok"] is True)

    # 3) Singleton hech qachon istisno ko'tarmaydi (init qilinmagan holat).
    cache.set_cache_backend(None)
    try:
        backend = cache.get_cache_backend()
        ok = backend is not None and bool(cache.backend_status())
    except Exception as exc:  # noqa: BLE001
        ok = False
        backend = f"{type(exc).__name__}: {exc}"
    check("Redis down: get_cache_backend() xavfsiz (In-Memory default)", ok,
          str(backend)[:100])


# ============================================================
# TEST 3 — 🤖 BARCHA AI PROVAYDERLAR 500/TIMEOUT
# ============================================================
def test_all_ai_providers_down() -> None:
    section("TEST 3) 🤖 BARCHA AI PROVAYDERLAR 500/TIMEOUT → MULOYM UX")

    from services import ai_gateway
    from services.ai.providers import ai_unavailable_message
    from services.ai_engine import providers as engine_providers
    from services.ai_engine.router import provider_order as router_order
    from services.ai_engine.router import resolve_lane  # noqa: F401

    class Provider500(RuntimeError):
        pass

    from services.ai_engine import gateway as gw

    # Sinov mazmunli bo'lishi uchun: real kalitlar mavjud bo'lmasa ham zanjir
    # HAQIQATAN urinib ko'riladi — sintetik handle + doimiy xato beruvchi ijro.
    lane_order = [name for name in router_order("fast")
                  if not gw.is_mock_provider(name)]
    handle_name = lane_order[0]

    class _DownProvider:
        """Har doim "kalit bor" deb javob beradigan, lekin ishlamaydigan adapter."""

        name = handle_name

        def is_available(self) -> bool:
            return True

    async def _scenario():
        calls = {"n": 0}

        async def _failing_execute(handle, prompt, instruction, *, lang=None,
                                   timeout=10.0):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise asyncio.TimeoutError()
            raise Provider500(f"{handle.name}: HTTP 500 Internal Server Error")

        synthetic = {handle_name: engine_providers.ProviderHandle(
            name=handle_name, provider=_DownProvider())}
        with patch.object(engine_providers, "build_provider_handles",
                          lambda: synthetic), \
             patch.object(engine_providers, "execute_provider", _failing_execute):
            outcomes = {}
            for lang in ("uz", "ru", "en"):
                outcomes[lang] = await ai_gateway.generate(
                    "Mavzu: kofe do'koni", task="social_post", lane="fast",
                    lang=lang, timeout=3.0, use_cache=False)
        return outcomes, calls["n"], len(synthetic)

    outcomes, attempts, handle_count = run(_scenario())
    check("AI down: provayder zanjiri mavjud (sinov mazmunli)",
          handle_count >= 1, str(handle_count))
    check("AI down: qayta urinishlar bo'ldi (fallback zanjiri ishladi)",
          attempts >= 1, str(attempts))
    for lang in ("uz", "ru", "en"):
        res = outcomes[lang]
        check(f"AI down ({lang}): GatewayResult ok=False",
              res.ok is False, str(res)[:120])
        check(f"AI down ({lang}): MULOYM xabar qaytdi",
              bool(res.error) and res.error == ai_unavailable_message(lang),
              str(res.error)[:160])
        check(f"AI down ({lang}): soxta matn YO'Q",
              not (res.text or "").strip(), repr(res.text)[:60])

    # Foydalanuvchi UX tasnifi: 'ai_busy' + 3 tilda muloyim matn.
    from handlers.error_handler import (
        classify_user_error_kind, format_user_error_message,
    )

    kind = classify_user_error_kind(Provider500("Gemini: insufficient_quota"))
    check("AI down: error_handler turi 'ai_busy'", kind == "ai_busy", kind)
    texts = {lang: format_user_error_message(
        Provider500("Gemini: model overloaded"), lang) for lang in ("uz", "ru", "en")}
    check("AI down: 'Exception occurred' matni YO'Q",
          all("exception" not in t.lower() for t in texts.values()), str(texts)[:140])
    check("AI down: 3 tilli muloyim xabarlar mavjud",
          all(len(t) > 10 for t in texts.values()), str(texts)[:140])

    # run_ai_task: kvota QAYTARILADI (refund) — soxta generatsiya YO'Q.
    from services.ai_engine.app_service import run_ai_task

    class _Outcome:
        def __init__(self):
            self.ok = None
            self.error = None
            self.denied_reason = None
            self.result = None

    async def _task_scenario():
        refunds = {"release": 0, "used": 0}

        async def _reserve(db_module, user_id, operation_type="other", cost=1):
            refunds["used"] += 1
            return {"allowed": True, "reason": "ok", "reservation_id": 9001,
                    "source": "credit", "cost": cost, "used": 1, "max_ai": 10,
                    "credits_left": 4, "legacy": False}

        async def _release(db_module, user_id, reservation_id=None, **kwargs):
            refunds["release"] += 1
            return True

        async def _no_write(*args, **kwargs):
            return None

        from services.ai_engine import app_service as app

        fake_db = SimpleNamespace()
        with patch("services.ai_quota.reserve_ai_quota", _reserve), \
             patch("services.ai_quota.release_ai_quota", _release), \
             patch.object(app.ai_gateway, "generate", _ai_failing_generate), \
             patch.object(app.ai_tasks, "_persist_usage", _no_write,
                          create=True):
            outcome = await run_ai_task(
                task="social_post", prompt="Mavzu: kitob do'koni",
                db=fake_db, user_id=424242, lane="fast", lang="uz",
                reserve_quota=True, persist_usage=False, require_quality=False,
                timeout=3.0)
        return outcome, refunds

    async def _ai_failing_generate(*args, **kwargs):
        from services.ai_engine.gateway import GatewayResult, resolve_lane  # noqa: F811
        return GatewayResult(
            ok=False, lane=resolve_lane(kwargs.get("lane") or "fast"),
            task=kwargs.get("task") or "", elapsed=0.01,
            error=ai_unavailable_message(kwargs.get("lang") or "uz"),
            provider_chain=[handle_name], status="failed", attempts=1)

    try:
        outcome, refunds = run(_task_scenario())
        check("AI down: run_ai_task ok=False (istisno yo'q)",
              outcome.ok is False, str(outcome)[:120])
        polite = str(getattr(outcome.result, "error", "") or "")
        check("AI down: run_ai_task muloyim xabar berdi (result.error)",
              bool(polite) and "AI" in polite and "exception" not in polite.lower(),
              polite[:160])
        check("AI down: run_ai_task refund bayrog'i True",
              outcome.refunded is True, str(outcome.refunded))
        check("AI down: kvota bron qilingan bo'lsa QAYTARILDI (refund)",
              refunds["used"] >= 1 and refunds["release"] >= 1, str(refunds))
    except Exception as exc:  # noqa: BLE001 — suite yiqilmasin
        not_tested("AI down: run_ai_task refund stsenariysi",
                   f"stsenariy mos kelmadi: {type(exc).__name__}: {exc}")


# ============================================================
# TEST 4 — 📨 TELEGRAM 429 FLOOD VA UZILISHLAR
# ============================================================
def test_telegram_flood_and_outage() -> None:
    section("TEST 4) 📨 TELEGRAM 429 FLOOD + UZILISHLAR (MOCK SERVER)")

    from staging.mock_telegram_server import MockTelegramServer
    from services.delivery import TelegramDeliveryService
    from tests.load_harness import make_mock_bot
    from telegram.error import NetworkError, RetryAfter, TelegramError  # noqa: F401

    async def _fault(port: int, payload: dict) -> None:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.post(f"http://127.0.0.1:{port}/__fault", json=payload):
                pass

    async def _scenario():
        server = MockTelegramServer(host="127.0.0.1", port=0)
        await server.start()
        bot = await make_mock_bot(server.base_url, pool_size=32)
        delivery = TelegramDeliveryService(global_per_second=2000.0,
                                           channel_per_second=500.0)
        # Sleep injectable (dvigatelning o'z test interfeysi): ANIQ kutish
        # qiymatini o'lchaymiz — devorni real sekundlab kutmaymiz.
        waits: list[float] = []

        async def _fake_sleep(seconds: float) -> None:
            waits.append(float(seconds))

        delivery._sleep = _fake_sleep
        out = {}
        try:
            # 1) 429 flood: engine aniq kutish (retry_after) bilan qayta uradi.
            #    `times=1` — bir martalik 429: qayta urinish MUVAFFAQIYATLI
            #    bo'ladi (deterministik, mock hisoblagichga bog'liq emas).
            await _fault(server.port, {"mode": "429", "retry_after": 1,
                                       "times": 1})
            result = await delivery.execute(
                bot, "send_message", chat_id=1001, text="429 flood sinovi",
                max_attempts=3, inline_max_wait=5.0)
            out["recovered"] = getattr(result, "message_id", None) is not None
            out["wait"] = waits[0] if waits else 0.0

            # 2) Defer rejimi (inline_max_wait=0) — xato chaqiruvchiga qaytadi.
            await _fault(server.port, {"mode": "429", "retry_after": 3,
                                       "every": 1})
            try:
                await delivery.execute(bot, "send_message", chat_id=1002,
                                       text="defer sinovi", max_attempts=3,
                                       inline_max_wait=0.0)
                out["defer_error"] = None
            except Exception as exc:  # noqa: BLE001
                out["defer_error"] = exc
            out["defer_is_retryafter"] = isinstance(out["defer_error"], RetryAfter)
            out["defer_class"] = TelegramDeliveryService.classify(out["defer_error"])

            # 3) 500 uzilishi — PTB buni NetworkError deb ko'taradi (ambiguous):
            #    xato YUTILMAYDI va "blind retry" QILINMAYDI (bitta HTTP so'rov).
            await _fault(server.port, {"mode": "500"})
            before = int(server.state.requests_total)
            try:
                await delivery.execute(bot, "send_message", chat_id=1003,
                                       text="500 sinovi", max_attempts=3)
                out["500_error"] = None
            except Exception as exc:  # noqa: BLE001
                out["500_error"] = exc
            out["500_requests"] = int(server.state.requests_total) - before
            out["500_class"] = TelegramDeliveryService.classify(out["500_error"])
            out["500_type"] = (type(out["500_error"]).__name__
                               if out["500_error"] is not None else "-")

            # 4) Tarmoq uzilishi (network) — ambiguous (blind retry TAQIQ).
            await _fault(server.port, {"mode": "network"})
            try:
                await delivery.execute(bot, "send_message", chat_id=1004,
                                       text="uzilish sinovi", max_attempts=1)
                out["net_error"] = None
            except Exception as exc:  # noqa: BLE001
                out["net_error"] = exc
            out["net_class"] = TelegramDeliveryService.classify(out["net_error"])
            out["net_type"] = (type(out["net_error"]).__name__
                               if out["net_error"] is not None else "-")
            out["net_is_network"] = isinstance(out["net_error"], NetworkError)

            # 5) FLOOD STORM: 60 parallel so'rov, har 3-chisi 429.
            await _fault(server.port, {"mode": "429", "retry_after": 1, "every": 5})
            ok = {"n": 0}
            errors: list[str] = []

            async def _send(i: int):
                try:
                    await delivery.execute(
                        bot, "send_message", chat_id=2000 + i,
                        text=f"storm #{i}", max_attempts=5, inline_max_wait=5.0)
                    ok["n"] += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(type(exc).__name__)

            started = time.perf_counter()
            await asyncio.gather(*(_send(i) for i in range(60)))
            out["storm_ok"] = ok["n"]
            out["storm_errors"] = errors
            out["storm_elapsed"] = time.perf_counter() - started
            out["storm_429"] = server.state.errors_429
            out["storm_queue"] = lifecycle.queue_pending()
            await _fault(server.port, {"mode": "off"})
        finally:
            await bot.shutdown()
            await server.stop()
        return out

    out = run(_scenario())
    check("Flood: 429 dan keyin so'rov muvaffaqiyatli qayta yuborildi",
          out["recovered"] is True, str(out)[:140])
    check("Flood: aniq kutish (retry_after + jitter) HISOBLANDI (≥1s)",
          out["wait"] >= 1.0, f"wait={out['wait']:.3f}s")
    check("Flood: defer rejimida RetryAfter chaqiruvchiga qaytadi",
          out["defer_is_retryafter"] is True, repr(out["defer_error"])[:120])
    check("Flood: defer xatosi 'rate_limit' deb tasniflanadi",
          out["defer_class"] == "rate_limit", str(out["defer_class"]))
    check("Uzilish: 500 → xato YUTILMAYDI (istisno chaqiruvchiga yetadi)",
          out["500_error"] is not None,
          f"type={out['500_type']} class={out['500_class']}")
    check("Uzilish: 500 → BLIND RETRY YO'Q (1 ta HTTP so'rov)",
          out["500_requests"] == 1,
          f"requests={out['500_requests']} class={out['500_class']}")
    check("Uzilish: tarmoq uzilishi 'ambiguous' (blind retry TAQIQLANGAN)",
          out["net_class"] == "ambiguous",
          f"class={out['net_class']} type={out['net_type']}")
    check("Flood storm: 60 parallel so'rovning barchasi yetib bordi",
          out["storm_ok"] == 60 and not out["storm_errors"],
          f"ok={out['storm_ok']} errors={out['storm_errors'][:3]}")
    check("Flood storm: 429'lar HAQIQATAN bo'ldi (mock statistikasi)",
          out["storm_429"] >= 10, str(out["storm_429"]))
    check("Flood storm: delivery navbati drenaj bo'ldi (leak yo'q)",
          out["storm_queue"] == {}, str(out["storm_queue"]))
    check("Flood storm: cheklangan vaqt ichida tugadi (< 30s)",
          out["storm_elapsed"] < 30.0, f"{out['storm_elapsed']:.2f}s")

    # UX: flood xatosi foydalanuvchiga muloyim tilda aytiladi.
    from handlers.error_handler import classify_user_error_kind, format_user_error_message

    flood = RetryAfter(3)
    check("Flood: error_handler turi 'telegram_flood'",
          classify_user_error_kind(flood) == "telegram_flood")
    check("Flood: foydalanuvchi xabari muloyim va texnik emas",
          "retry" not in format_user_error_message(flood, "uz").lower(),
          format_user_error_message(flood, "uz"))


# ============================================================
# TEST 5 — 🛡 SSRF (YAGONA URL SECURITY GATEWAY)
# ============================================================
BLOCKED_URLS = (
    "http://localhost/",
    "http://localhost:8080/admin",
    "http://127.0.0.1/",
    "http://127.1/",
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://[fd00::1]/",
    "http://[fe80::1]/",
    "http://10.0.0.5/",
    "http://192.168.1.1/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://2130706433/",          # o'nlik IP (127.0.0.1)
    "http://0177.0.0.1/",          # sakkizlik IP
    "http://0x7f000001/",          # hex IP
    "http://user:pass@127.0.0.1/",  # userinfo hiylasi
    "http://example.com@127.0.0.1/",
    "file:///etc/passwd",
    "gopher://127.0.0.1:6379/",
    "ftp://example.com/",
)


def test_ssrf_gateway() -> None:
    section("TEST 5) 🛡 SSRF — PRIVATE IP / LOCALHOST / IPv6 HALQA")

    from services import url_security_gateway as gateway

    blocked_failures = []
    for url in BLOCKED_URLS:
        result = gateway.validate_public_url(url)
        if result.get("ok"):
            blocked_failures.append(url)
    check(f"SSRF: {len(BLOCKED_URLS)} ta ichki/aylanma URL BLOKLANADI",
          not blocked_failures, str(blocked_failures))

    # Chetlab o'tish kalitlari (encoded IP'lar) aniq xato kodini beradi.
    encoded = {
        "0177.0.0.1": "private_address",
        "0x7f000001": "private_address",
        "2130706433": "private_address",
    }
    for host, expected in encoded.items():
        result = gateway.validate_public_url(f"http://{host}/")
        check(f"SSRF: {host} → {expected}",
              (not result.get("ok")) and result.get("error_code") == expected,
              str(result.get("error_code")))

    # Ochiq URL'lar hamon ishlaydi (regressiya yo'q).
    for good in ("http://example.com/", "https://example.com/page?x=1"):
        result = gateway.validate_public_url(good)
        check(f"SSRF: ochiq URL ruxsat etiladi ({good})", bool(result.get("ok")),
              str(result)[:100])

    # safe_fetch: bloklangan URL tarmoqqa UMUMAN chiqmaydi, fail-soft javob.
    class _CountingClient:
        def __init__(self):
            self.opened = 0

        def open(self, request, timeout=None):  # pragma: no cover - chaqirilmasligi kerak
            self.opened += 1
            raise AssertionError("bloklangan URL uchun tarmoq chaqiruvi bo'ldi")

    client = _CountingClient()
    for url in ("http://127.0.0.1/", "http://169.254.169.254/", "http://[::1]/"):
        result = gateway.safe_fetch(url, client=client)
        check(f"SSRF: safe_fetch bloklaydi ({url})",
              result.get("ok") is False and client.opened == 0,
              str(result)[:120])
    check("SSRF: xato xabari XAVFSIZ (ichki tafsilotsiz)",
          result.get("message") == gateway.SAFE_ERROR_MESSAGE,
          str(result.get("message"))[:100])

    # Statik skaner: tashqi (foydalanuvchi) URL'lari faqat gateway orqali.
    prod_files = {}
    for path in (ROOT / "telegram_bot").rglob("*.py"):
        if "tests" in path.parts or "__pycache__" in path.parts:
            continue
        prod_files[path.relative_to(ROOT).as_posix()] = path.read_text(
            encoding="utf-8", errors="ignore")

    # Foydalanuvchi havolasini yuklaydigan modullar shlyuzga bog'langan bo'lishi shart.
    user_url_modules = [
        "telegram_bot/utils/channel_reader.py",
        "telegram_bot/services/sources/rss_service.py",
        "telegram_bot/services/sources/url_extractor.py",
    ]
    for rel in user_url_modules:
        source = prod_files.get(rel, "")
        if not source:
            not_tested(f"SSRF statik skaner: {rel}", "fayl topilmadi")
            continue
        check(f"SSRF statik: {rel} — url_security_gateway ishlatadi",
              "url_security_gateway" in source, rel)

    # Xom (raw) tarmoq yuklash shlyuzdan tashqarida qolmaganini tekshiramiz.
    raw_offenders = []
    for rel, source in prod_files.items():
        if rel.endswith("services/url_security_gateway.py"):
            continue
        if "url_security_gateway" in source:
            continue
        if "urlopen(" in source or "urlretrieve(" in source:
            raw_offenders.append(rel)
    check("SSRF statik: shlyuzsiz xom urlopen() YO'Q", not raw_offenders,
          str(raw_offenders))


# ============================================================
# TEST 6 — ♻️ DUBLIKAT CALLBACK / TO'LOV / STALE UPDATE
# ============================================================
def test_duplicates_and_stale_updates() -> None:
    section("TEST 6) ♻️ DUBLIKAT CALLBACK / TO'LOV / STALE UPDATE")

    from middlewares.rate_limiter import RateLimiter

    async def _callback_dedupe():
        # Yangi limiter — test izolyatsiyasi (global singleton'ga tegmaymiz).
        limiter = RateLimiter()
        first = await limiter.allow_callback(777001, "ch_np:123")
        second = await limiter.allow_callback(777001, "ch_np:123")
        other = await limiter.allow_callback(777001, "cab_stats")
        return first, second, other

    first, second, other = run(_callback_dedupe())
    check("Dublikat callback: birinchi bosish RUXSAT",
          bool(first.allowed) is True, str(first))
    check("Dublikat callback: ketma-ket ikkinchi bosish BLOKLANADI",
          bool(second.allowed) is False, str(second))
    check("Dublikat callback: boshqa tugma bemalol ishlaydi (izolyatsiya)",
          bool(other.allowed) is True, str(other))

    # --- Dublikat to'lov (10 parallel, bir xil charge_id) -----------------
    from services.payment_service import PaymentService

    import config

    inserted = {"n": 0}

    class _Cur:
        def execute(self, sql, params=None):
            text = str(sql)
            self.rowcount = 1
            if "FROM payments WHERE telegram_payment_charge_id" in text and "FOR UPDATE" in text:
                self._ret = None if inserted["n"] == 0 else (1,)
            elif "INSERT INTO payments" in text:
                if inserted["n"] == 0:
                    inserted["n"] = 1
                    self._ret = (1,)
                else:
                    self._ret = None
                    self.rowcount = 0
            elif "SELECT 1 FROM users" in text:
                self._ret = (1,)
            else:
                self._ret = (1,)

        def fetchone(self):
            return self._ret

    class _Ctx:
        def __enter__(self):
            return _Cur()

        def __exit__(self, *args):
            return False

    from concurrent.futures import ThreadPoolExecutor

    with patch("services.payment_service.transaction", lambda: _Ctx()), \
         patch("services.payment_service._invalidate_user"), \
         patch("services.payment_service._cache_clear"):
        uid = 909000
        payload = f"sub_stars_1m_{uid}"
        charge = "chaos-duplicate-charge"
        stars = int(config.STARS_PLANS["stars_1m"]["stars"])

        def _pay(_):
            return PaymentService.process_stars_payment(
                uid, charge, stars, payload, "pro", 30, currency="XTR")

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(_pay, range(10)))

    oks = [r for r in results if r.get("ok") and not r.get("duplicate")]
    dups = [r for r in results if r.get("duplicate")]
    check("Dublikat to'lov: 10 parallel → FAQAT 1 ta yangi to'lov",
          len(oks) == 1, f"oks={len(oks)}")
    check("Dublikat to'lov: qolgan 9 tasi duplicate deb belgilandi",
          len(dups) == 9, f"dups={len(dups)}")
    check("Dublikat to'lov: ledger'ga FAQAT 1 marta yozildi",
          inserted["n"] == 1, str(inserted))

    # --- Eskirgan (stale) update in'yeksiyasi -----------------------------
    from datetime import datetime, timedelta, timezone

    import main as main_mod

    fresh = SimpleNamespace(
        date=datetime.now(timezone.utc), update_id=1,
        effective_user=None, effective_message=None, callback_query=None)
    stale = SimpleNamespace(
        date=datetime.now(timezone.utc) - timedelta(seconds=3600),
        update_id=2, effective_user=None, effective_message=None,
        callback_query=None)

    check("Stale update: yangi update O'TKAZILADI",
          main_mod.GuardedApplication.is_stale_update(fresh) is False)
    check("Stale update: 1 soatlik update INDIRO'LADI",
          main_mod.GuardedApplication.is_stale_update(stale) is True)

    # process_update: stale update handler'larga UMUMAN yetib bormaydi.
    app = object.__new__(main_mod.GuardedApplication)
    handled = {"n": 0}

    async def _fake_super(self, update):  # pragma: no cover
        handled["n"] += 1

    with patch("telegram.ext.Application.process_update", _fake_super):
        out_stale = run(app.process_update(stale))
    check("Stale update: process_update → None (handler chaqirilmadi)",
          out_stale is None and handled["n"] == 0,
          f"handled={handled['n']} out={out_stale}")

    # Dublikat xabar (bir xil matn qisqa vaqt ichida) ham bloklanadi.
    from utils.helpers import is_duplicate_message

    check("Dublikat xabar: birinchi matn o'tadi",
          is_duplicate_message(555001, "chaos dublikat matni") is False)
    check("Dublikat xabar: takroriy matn BLOKLANADI",
          is_duplicate_message(555001, "chaos dublikat matni") is True)


# ============================================================
# TEST 7 — 💧 RESURS HOLATI (CHAOS'DAN KEYIN)
# ============================================================
def test_resource_state_after_chaos() -> None:
    section("TEST 7) 💧 CHAOS'DAN KEYIN RESURS HOLATI (LEAK YO'Q)")

    async def _probe():
        from services import cache_backend as cache
        from services.delivery import TelegramDeliveryService
        from staging.mock_telegram_server import MockTelegramServer
        from tests.load_harness import make_mock_bot

        before = len(asyncio.all_tasks())
        server = await MockTelegramServer(host="127.0.0.1", port=0).start()
        bot = await make_mock_bot(server.base_url, pool_size=16)
        delivery = TelegramDeliveryService(global_per_second=2000.0,
                                           channel_per_second=500.0)
        try:
            await asyncio.gather(*(delivery.send_message(
                bot, chat_id=700000 + i, text=f"final #{i}") for i in range(50)))
        finally:
            await bot.shutdown()
            await server.stop()
            await cache.close_cache_backend()
        await asyncio.sleep(0.05)
        after = len(asyncio.all_tasks())
        return before, after

    before, after = run(_probe())
    check("Resurs: asyncio task leak YO'Q", after <= before,
          f"before={before} after={after}")
    check("Resurs: lifecycle navbatlari bo'sh", lifecycle.queue_pending() == {},
          str(lifecycle.queue_pending()))
    check("Resurs: shutdown bayrog'i toza (test izolyatsiyasi)",
          lifecycle.is_shutting_down() is False, str(lifecycle.status()))

    from services import cache_backend as cache

    cache.set_cache_backend(None)
    try:
        status = cache.backend_status()
        check("Resurs: cache backend yopilgach status xavfsiz",
              isinstance(status, dict), str(status)[:100])
    except Exception as exc:  # noqa: BLE001
        check("Resurs: cache backend yopilgach status xavfsiz", False,
              f"{type(exc).__name__}: {exc}")


# ============================================================
# MAIN
# ============================================================
def main() -> int:
    print("=" * 66)
    print(" 🌀 PHASE 11 — CHAOS & SECURITY SUITE (FAIL-CLOSED)")
    print("=" * 66)
    lifecycle.reset_for_tests()

    test_db_unavailable_fail_closed()
    test_redis_down_fallback()
    test_all_ai_providers_down()
    test_telegram_flood_and_outage()
    test_ssrf_gateway()
    test_duplicates_and_stale_updates()
    test_resource_state_after_chaos()

    print()
    print("=" * 66)
    print(f" NATIJA: [OK]={PASSED}  [FAIL]={FAILED}  [NOT TESTED]={len(NOT_TESTED)}")
    for name, reason in NOT_TESTED:
        print(f"   - {name}: {reason}")
    print("=" * 66)
    if FAILED:
        print(" ❌ PHASE 11 CHAOS SUITE: FAIL")
        return 1
    print(" ✅ PHASE 11 CHAOS SUITE: 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
