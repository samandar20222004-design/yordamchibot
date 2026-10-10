#!/usr/bin/env python3
"""PHASE 6 — AI ARCHITECTURE CONSOLIDATION & COST CONTROL (test to'plami).

Bu test PHASE 6 talablarini QAT'IY tekshiradi:

  TEST 1 — KANONIK AI GATEWAY: ``from services import ai_gateway`` yagona
           interfeys; ``generate(task=..., prompt=..., user_id=...,
           channel_id=..., lane="fast"/"smart"/"premium")`` imzosi;
           eski delegatlar (backward compatibility).
  TEST 2 — ROUTER: task → lane xaritasi (``social_post``/``channel_dna``/
           ``post_score``/``repurpose``) va lane aliaslari (fast/smart/premium).
  TEST 3 — TELEMETRIYA/XARAJAT: har bir so'rov uchun model, provider,
           input/output tokenlar, latency, estimated_cost va status
           (success/failed) hisobga olinadi; user/kanal kesimida kunlik va
           oylik hisobot (xarajatlar).
  TEST 4 — APPLICATION SERVICE: kvota bron → AI → xatoda TO'LIQ refund;
           DB telemetriya yozuvi; kunlik hisobot; quota_status.
  TEST 5 — MOCK SIYOSATI: production'da Mock DEFAULT O'CHIQ (zanjirga ham
           qo'shilmaydi); test/dev ALOHIDA rejimlar; AI_ALLOW_MOCK=1 override.
  TEST 6 — RETRY/FALLBACK/CIRCUIT BREAKER: vaqtinchalik xatoda urinishlar,
           doimiy xatoda darhol keyingi provayder, backoff byudjetga mos.
  TEST 7 — PROMPT GUARD + QAT'IY VALIDATOR: kirishdan ko'rsatmalar
           tozalanadi; ko'rsatma sizib chiqsa javob RAD etiladi; "length >=
           20" kabi sun'iy bypass YO'Q (statik + dinamik tekshiruv).
  TEST 8 — HANDLER IZOLYATSIYASI: handlerlar provayder qatlamiga
           bog'lanmaydi; kanonik sirt ishlatiladi; legacy adapter buzilmagan.

Ishga tushirish:
    cd telegram_bot && python tests/ai_gateway_cost_control_test.py
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import re
import sys
import types
import warnings
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AI_GATEWAY_PHASE6_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")
    return bool(cond)


def run(coro):
    return asyncio.run(coro)


@contextmanager
def env(**values):
    """Vaqtinchalik muhit o'zgaruvchilari (mock siyosati testlari uchun)."""
    old = {k: os.environ.get(k) for k in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)
        yield
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# IMPORTLAR (muhit sozlangandan KEYIN)
# ---------------------------------------------------------------------------
from services import ai_gateway as ag                              # noqa: E402
from services.ai_engine import gateway as gw                       # noqa: E402
from services.ai_engine import providers as eng_providers          # noqa: E402
from services.ai_engine import router as eng_router                # noqa: E402
from services.ai_engine import telemetry                           # noqa: E402
from services.ai_engine.app_service import (                       # noqa: E402
    ai_tasks, run_ai_task,
)
from services.ai_engine.cache import reset_cache                   # noqa: E402
from services.ai_engine.health import (                            # noqa: E402
    default_health_monitor, reset_health_monitor,
)
from services.ai_engine.retry import (                             # noqa: E402
    DEFAULT_RETRY_POLICY, KIND_QUALITY, NO_RETRY_POLICY, RetryPolicy, policy_for,
)
from services.ai_engine.router import Lane, lane_for_task, resolve_lane  # noqa: E402
from services.ai_engine.validator import validate_output           # noqa: E402
import database as db_mod                                          # noqa: E402


CALLS: list[tuple[str, str]] = []
INSTRUCTIONS: list[str] = []


def _handle(name):
    return eng_providers.ProviderHandle(name=name, provider=types.SimpleNamespace(
        name=name, is_available=lambda: True, complete=None,
    ))


def patch_providers(handles, executor):
    """Provayder registri va ijrochisini almashtiradi (test seam)."""
    real = (eng_providers.build_provider_handles, eng_providers.execute_provider)
    eng_providers.build_provider_handles = handles
    eng_providers.execute_provider = executor
    return real


def restore_providers(real):
    eng_providers.build_provider_handles, eng_providers.execute_provider = real


def patch_lane_order(lane, *names):
    """Lane provayder tartibini vaqtincha almashtiradi (qaytarish uchun spec)."""
    spec = eng_router.LANE_SPECS[lane]
    eng_router.LANE_SPECS[lane] = dataclasses.replace(spec, provider_order=tuple(names))
    return spec


def restore_lane_order(lane, spec):
    eng_router.LANE_SPECS[lane] = spec


def executor_of(results, fail_kinds=None, delay=0.0, always_fail=False):
    """Provayder ijrochisi: nom → natija dict yoki ko'tariladigan xato."""
    fail_kinds = fail_kinds or {}

    async def executor(handle, prompt, system_instruction, **kwargs):
        if delay:
            await asyncio.sleep(delay)
        CALLS.append((handle.name, prompt))
        INSTRUCTIONS.append(system_instruction)
        if handle.name in fail_kinds:
            raise RuntimeError(fail_kinds[handle.name])
        if always_fail:
            raise RuntimeError("connection reset by peer")
        return results.get(handle.name, {"post_text": GOOD_TEXT})
    return executor


GOOD_TEXT = (
    "Yangi kofe do'koni bugun ochildi. Birinchi mijozlarga 20% chegirma "
    "beramiz va yangi ta'mni sinab ko'rishni taklif qilamiz. "
    "Buyurtma uchun yozing — manzil va vaqt javobda yuboriladi.\n\n#kofe #chegirma"
)


def good(model=None):
    payload = {"post_text": GOOD_TEXT}
    if model:
        payload["model"] = model
    return payload


def reset_state():
    CALLS.clear()
    INSTRUCTIONS.clear()
    telemetry.reset_default_recorder()
    reset_cache(max_entries=64, ttl=60.0)
    reset_health_monitor()


# ===========================================================================
# TEST 1 — KANONIK AI GATEWAY INTERFEYSI
# ===========================================================================
def test_canonical_gateway():
    print("\n== TEST 1: Kanonik AI Gateway — yagona interfeys ==")
    reset_state()

    # 1a) Sirt mavjudligi: services.ai_gateway + ai_engine eksportlari.
    from services import ai_engine as eng_pkg
    check("services.ai_gateway.ai_gateway mavjud", hasattr(ag, "ai_gateway"))
    check("ai_gateway — AIGateway nusxasi", isinstance(ag.ai_gateway, ag.AIGateway))
    check("GatewayResult sirtda", ag.GatewayResult is gw.GatewayResult)
    check("run_ai_task sirtda", callable(ag.run_ai_task))
    check("run_ai_task — ai_engine.app_service bilan AYNAN bir xil",
          ag.run_ai_task is run_ai_task)
    check("ai_tasks — yagona Application Service", ag.ai_tasks is ai_tasks)
    check("services.ai_engine.ai_gateway eksport qilingan",
          eng_pkg.ai_gateway is ag.ai_gateway)
    check("services.ai_engine.ai_tasks eksport qilingan",
          eng_pkg.ai_tasks is ag.ai_tasks)
    check("services.ai_engine.run_ai_task eksport qilingan",
          eng_pkg.run_ai_task is run_ai_task)

    # 1b) PHASE 6 imzosi: task/prompt/user_id/channel_id/lane.
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": good("gemini-2.5-flash")}))
    try:
        res = run(ag.ai_gateway.generate(
            prompt="Kofe do'koni uchun ijtimoiy tarmoq posti",
            task="social_post", user_id=101, channel_id=-100200,
            lane="fast", lang="uz", use_cache=False,
        ))
    finally:
        restore_providers(real)

    check("generate(task=..., user_id=..., channel_id=..., lane=...) ishlaydi",
          res.ok and res.text == GOOD_TEXT, str(res)[:160])
    check("natijada task/lane saqlanadi",
          res.task == "social_post" and res.lane is Lane.FAST, str(res.lane))
    check("natijada user_id/channel_id konteksti bor",
          res.user_id == 101 and res.channel_id == -100200)
    check("provider/model qaytadi",
          res.provider == "Gemini" and res.model == "gemini-2.5-flash",
          f"{res.provider}/{res.model}")

    # 1c) Eski delegatlar saqlanadi (backward compatibility).
    reset_state()
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")}, executor_of({"Gemini": good()}))
    try:
        res_old = run(gw.generate("eski uslubdagi chaqiruv", task="simple_post",
                                  use_cache=False))
        res_engine = run(eng_pkg.generate("yana bir chaqiruv", task="simple_post",
                                          use_cache=False))
    finally:
        restore_providers(real)
    check("gateway.generate — eski imzo ishlaydi", res_old.ok, str(res_old)[:120])
    check("services.ai_engine.generate — eski import ishlaydi", res_engine.ok)
    check("GatewayResult eski maydonlari saqlangan",
          all(hasattr(res_old, f) for f in
              ("ok", "text", "provider", "lane", "task", "cached", "elapsed",
               "error", "raw", "provider_chain")), str(res_old))

    # 1d) Lane aliaslari + resolve ustuvorligi.
    check("lane='fast' → FAST", resolve_lane(lane="fast") is Lane.FAST)
    check("lane='smart' → QUALITY", resolve_lane(lane="smart") is Lane.QUALITY)
    check("lane='premium' → REASONING", resolve_lane(lane="premium") is Lane.REASONING)
    check("aniq lane task'dan ustun",
          resolve_lane(task="social_post", lane="premium") is Lane.REASONING)
    check("lane_alias('QUALITY') → QUALITY", ag.lane_alias("QUALITY") is Lane.QUALITY)
    check("lane_alias('tez') → FAST (o'zbekcha alias)", ag.lane_alias("tez") is Lane.FAST)
    check("lane_alias(noma'lum) → None", ag.lane_alias("nomalum_xxx") is None)


# ===========================================================================
# TEST 2 — ROUTER: vazifa → lane xaritasi
# ===========================================================================
def test_task_lane_map():
    print("\n== TEST 2: Router — kanonik vazifa nomlari ==")
    from services.ai_engine.router import TASK_LANES

    expected = {
        "social_post": Lane.FAST,
        "channel_dna": Lane.REASONING,
        "post_score": Lane.QUALITY,
        "repurpose": Lane.QUALITY,
    }
    for task, lane in expected.items():
        check(f"task '{task}' → {lane.value}", lane_for_task(task) is lane)
        check(f"TASK_LANES['{task}'] mavjud", TASK_LANES.get(task) is lane)
    check("noma'lum task uchun xavfsiz standart (QUALITY)",
          resolve_lane(task="mavjud_emas_vazifa") is Lane.QUALITY)
    check("content_plan → REASONING", lane_for_task("content_plan") is Lane.REASONING)
    check("voice_post → FAST", lane_for_task("voice_post") is Lane.FAST)
    check("vision → VISION", lane_for_task("vision") is Lane.VISION)


# ===========================================================================
# TEST 3 — TELEMETRIYA VA XARAJAT HISOBOTI
# ===========================================================================
def test_telemetry_and_cost():
    print("\n== TEST 3: Telemetriya — model/token/latency/xarajat/status ==")
    reset_state()
    recorder = telemetry.default_recorder()

    # 3a) Muvaffaqiyatli so'rov — barcha maydonlar to'ldiriladi.
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": good("gemini-2.5-flash")}))
    try:
        res = run(ag.ai_gateway.generate(
            prompt="Kofe uchun post yoz", task="social_post",
            user_id=7, channel_id=-1001, lane="smart", use_cache=False,
        ))
    finally:
        restore_providers(real)

    usage = res.usage or {}
    check("usage yozuvi mavjud", bool(usage), str(usage)[:120])
    check("model qayd etildi", usage.get("model") == "gemini-2.5-flash",
          str(usage.get("model")))
    check("provider qayd etildi", usage.get("provider") == "Gemini")
    check("input_tokens > 0", int(usage.get("input_tokens") or 0) > 0,
          str(usage.get("input_tokens")))
    check("output_tokens > 0", int(usage.get("output_tokens") or 0) > 0)
    check("latency_ms qayd etildi (int)", isinstance(usage.get("latency_ms"), int))
    check("status == success", usage.get("status") == telemetry.STATUS_SUCCESS)
    check("xarajat hisoblandi (priced)",
          bool(usage.get("priced")) and float(usage.get("estimated_cost") or 0) > 0,
          str(usage.get("estimated_cost")))
    check("res.total_tokens == input+output",
          res.total_tokens == int(usage["input_tokens"]) + int(usage["output_tokens"]))
    check("recorder yozuvni saqladi", recorder.stats()["recorded"] == 1)
    check("yozuvda user/kanal konteksti",
          usage.get("user_id") == 7 and usage.get("channel_id") == -1001)

    # 3b) Narx jadvalida YO'Q provayder/model → priced=False, cost=0 (soxta raqam yo'q).
    spec = patch_lane_order(Lane.FAST, "TestProvX")
    real = patch_providers(lambda: {"TestProvX": _handle("TestProvX")},
                           executor_of({"TestProvX": {"post_text": GOOD_TEXT}}))
    try:
        unknown = run(ag.ai_gateway.generate(
            prompt="noma'lum model", task="social_post", user_id=8,
            channel_id=-1001, lane="fast", use_cache=False,
        ))
    finally:
        restore_providers(real)
        restore_lane_order(Lane.FAST, spec)
    check("noma'lum provayder: ok (javob qabul qilindi)", unknown.ok, str(unknown)[:120])
    check("noma'lum provayder: priced=False va cost=0",
          unknown.priced is False and unknown.estimated_cost == 0.0,
          f"{unknown.priced}/{unknown.estimated_cost}")

    # 3c) XATO ham telemetriyaga tushadi (status=failed).
    before = recorder.stats()["recorded"]
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({}, fail_kinds={"Gemini": "HTTP 429 Too Many Requests"}))
    try:
        failed = run(ag.ai_gateway.generate(
            prompt="xato bo'ladigan so'rov", task="social_post", user_id=7,
            channel_id=-1001, lane="fast", use_cache=False,
        ))
    finally:
        restore_providers(real)
    check("xato: ok=False (fail-soft)", failed.ok is False)
    check("xato: status failed", failed.status == telemetry.STATUS_FAILED)
    check("xato: failure_kind rate_limit", failed.failure_kind == "rate_limit",
          str(failed.failure_kind))
    check("xato ham telemetriyaga yozildi", recorder.stats()["recorded"] == before + 1)
    check("xato yozuvida status failed",
          recorder.last().status == telemetry.STATUS_FAILED)

    # 3d) Kunlik/oylik hisobot — user va kanal kesimida.
    daily_user = telemetry.default_recorder().report(user_id=7, period="daily")
    check("kunlik hisobot: user bo'yicha so'rovlar", daily_user["totals"]["requests"] == 2,
          str(daily_user["totals"]))
    check("kunlik hisobot: 1 success + 1 failed",
          daily_user["totals"]["successes"] == 1 and daily_user["totals"]["failures"] == 1,
          str(daily_user["totals"]))
    check("kunlik hisobot: xarajat yig'indisi > 0",
          daily_user["totals"]["estimated_cost_usd"] > 0)
    check("kunlik hisobot: avg_latency_ms hisoblangan",
          "avg_latency_ms" in daily_user["totals"])
    monthly = telemetry.default_recorder().report(user_id=7, period="monthly")
    check("oylik hisobot ham joriy oynani oladi",
          monthly["totals"]["requests"] == daily_user["totals"]["requests"])
    check("oylik hisobotda kunlik agregatsiya (by_day) bor",
          isinstance(monthly["by_day"], dict) and len(monthly["by_day"]) >= 1)
    channel_report = telemetry.default_recorder().report(channel_id=-1001, period="daily")
    check("kanal kesimida hisobot", channel_report["totals"]["requests"] == 3,
          str(channel_report["totals"]))
    provider_report = daily_user["by_provider"]
    check("by_provider agregatsiyasi (Gemini)", "Gemini" in provider_report,
          str(list(provider_report)))
    check("by_task agregatsiyasi (social_post)", "social_post" in daily_user["by_task"])
    check("by_lane agregatsiyasi (QUALITY)", "QUALITY" in daily_user["by_lane"])
    past = datetime.now(timezone.utc) - timedelta(days=2)
    check("boshqa kunning oynasida yozuv yo'q (deterministik oyna)",
          telemetry.default_recorder().report(
              user_id=7, period="daily", now=past)["events_matched"] == 0)
    all_time = telemetry.default_recorder().report(period="all")
    check("'all' davri butun tarixni oladi", all_time["totals"]["requests"] >= 3)

    # 3e) Kesh hit: xarajat 0 va cache_hits hisoblanadi.
    reset_state()
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": good("gemini-2.5-flash")}))
    try:
        first = run(ag.ai_gateway.generate(prompt="bir xil so'rov", task="social_post",
                                           user_id=5, lane="fast"))
        second = run(ag.ai_gateway.generate(prompt="bir xil so'rov", task="social_post",
                                            user_id=5, lane="fast"))
    finally:
        restore_providers(real)
    check("2-chaqiruv keshdan", first.ok and second.cached and second.provider == "cache",
          f"{second.provider}/{second.cached}")
    check("kesh yozuvi: xarajat 0 va priced=False",
          second.estimated_cost == 0.0 and second.priced is False)
    cached_report = telemetry.default_recorder().report(user_id=5, period="daily")
    check("hisobotda cache_hits qayd etilgan",
          cached_report["totals"]["cache_hits"] == 1, str(cached_report["totals"]))
    check("kesh javobi 'success' statusida", second.status == telemetry.STATUS_SUCCESS)
    check("kesh javobi ham telemetriyaga yozildi",
          telemetry.default_recorder().stats()["recorded"] == 2)

    # 3f) Per-request detallar (events) — diagnostika uchun saqlanadi.
    events = telemetry.default_recorder().events()
    check("events ro'yxati to'ldiriladi", len(events) == 2, str(len(events)))
    check("event: latency_ms int va >= 0",
          all(isinstance(e.latency_ms, int) and e.latency_ms >= 0 for e in events))
    check("event: prompt_hash to'ldirilgan", all(len(e.prompt_hash) == 16 for e in events))
    check("event: to_row() DB ustunlari tartibida (18 ta)",
          all(len(e.to_row()) == 18 for e in events))

    # 3g) Token bahosi va xarajat funksiyalari (yagona manba).
    check("estimate_tokens bo'sh matn → 0", telemetry.estimate_tokens("") == 0)
    check("estimate_tokens matnni hisoblaydi", telemetry.estimate_tokens("a" * 400) == 100)
    spec_price = telemetry.price_spec("Gemini", "gemini-2.5-flash")
    check("price_spec: narx jadvalda", telemetry.is_priced("Gemini", "gemini-2.5-flash"))
    check("estimate_cost formula bo'yicha",
          abs(telemetry.estimate_cost("Gemini", "gemini-2.5-flash", 1000, 1000)
              - (spec_price.input_per_1k + spec_price.output_per_1k)) < 1e-9)


# ===========================================================================
# TEST 4 — APPLICATION SERVICE (kvota + refund + DB telemetriya)
# ===========================================================================
def _fake_real_db():
    """``database`` modulini imitatsiya qiluvchi adapter (``run_db`` real)."""
    fake = types.ModuleType("database")

    async def run_db(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    run_db.__module__ = "database"
    fake.run_db = run_db
    fake.saved_events = []
    fake.report_calls = []

    def save_ai_usage_event(**fields):
        fake.saved_events.append(fields)
        return len(fake.saved_events)

    def get_ai_usage_report(user_id=None, channel_id=None, period="daily"):
        fake.report_calls.append(period)
        return {"period": period, "totals": {"requests": 1, "estimated_cost_usd": 0.5},
                "scope": {"user_id": user_id, "channel_id": channel_id}}

    def check_ai_limit(user_id):
        return (True, 3, 10)

    fake.save_ai_usage_event = save_ai_usage_event
    fake.get_ai_usage_report = get_ai_usage_report
    fake.check_ai_limit = check_ai_limit
    return fake


def test_application_service():
    print("\n== TEST 4: Application Service — kvota, refund, DB telemetriya ==")
    reset_state()
    fake_db = _fake_real_db()

    # 4a) Muvaffaqiyatli tsikl: bron → AI → DB yozuv (refund YO'Q).
    reserve = AsyncMock(return_value={
        "allowed": True, "reason": "ok", "reservation_id": 555,
        "source": "daily_quota", "cost": 1, "legacy": False,
    })
    release = AsyncMock(return_value=True)
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": good("gemini-2.5-flash")}))
    try:
        with patch("services.ai_quota.reserve_ai_quota", reserve), \
                patch("services.ai_quota.release_ai_quota", release):
            outcome = run(run_ai_task(
                db=fake_db, task="social_post", prompt="Kofe uchun post",
                user_id=42, channel_id=-1001, lane="smart", use_cache=False,
            ))
    finally:
        restore_providers(real)

    check("outcome ok", outcome.ok and outcome.text == GOOD_TEXT, str(outcome)[:160])
    check("kvota AYNAN 1 marta bron qilindi", reserve.await_count == 1)
    check("bron argumentlari (db, user, operation_type, cost)",
          reserve.call_args.args[0] is fake_db
          and reserve.call_args.args[1] == 42
          and reserve.call_args.args[2] == "magic_post"
          and reserve.call_args.args[3] == 1, str(reserve.call_args))
    check("muvaffaqiyatda refund YO'Q", release.await_count == 0)
    check("telemetriya DB'ga yozildi",
          len(fake_db.saved_events) == 1, str(len(fake_db.saved_events)))
    saved = fake_db.saved_events[0]
    check("DB yozuvida barcha talab qilingan maydonlar",
          {"model", "provider", "input_tokens", "output_tokens", "latency_ms",
           "estimated_cost", "status"} <= set(saved), str(sorted(saved)))
    check("DB yozuvida status=success", saved["status"] == "success")
    check("DB yozuvida user/kanal konteksti",
          saved["user_id"] == 42 and saved["channel_id"] == -1001)
    check("DB yozuvida reservation bog'langan", saved["reservation_id"] == 555)
    check("usage_id natijaga qaytdi", outcome.usage_id == 1)
    check("outcome as_dict() ko'rsatkichlari",
          outcome.as_dict()["provider"] == "Gemini"
          and outcome.as_dict()["total_tokens"] > 0
          and outcome.as_dict()["lane"] == "QUALITY")

    # 4b) Kvota rad etilganda AI chaqirilmaydi (fail-closed).
    reset_state()
    denied = AsyncMock(return_value={
        "allowed": False, "reason": "insufficient_balance", "reservation_id": None,
        "used": 10, "max_ai": 10, "legacy": False,
    })
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")}, executor_of({"Gemini": good()}))
    try:
        with patch("services.ai_quota.reserve_ai_quota", denied), \
                patch("services.ai_quota.release_ai_quota", AsyncMock(return_value=False)):
            blocked = run(run_ai_task(
                db=fake_db, task="social_post", prompt="post", user_id=43,
                lane="fast", use_cache=False,
            ))
    finally:
        restore_providers(real)
    check("rad etilgan bron: ok=False", blocked.ok is False)
    check("rad etilgan bron: denied_reason", blocked.denied_reason == "insufficient_balance")
    check("rad etilgan bron: provayder CHAQIRILMADI", not CALLS, str(CALLS))
    check("rad etilgan bron: yangi telemetriya YOZILMADI",
          len(fake_db.saved_events) == 1)

    # 4c) AI xatosi → bron TO'LIQ qaytariladi (refund).
    reset_state()
    reserve2 = AsyncMock(return_value={
        "allowed": True, "reason": "ok", "reservation_id": 777,
        "source": "credit", "cost": 1, "legacy": False,
    })
    release2 = AsyncMock(return_value=True)
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({}, fail_kinds={"Gemini": "HTTP 503 unavailable"}))
    try:
        with patch("services.ai_quota.reserve_ai_quota", reserve2), \
                patch("services.ai_quota.release_ai_quota", release2):
            broken = run(run_ai_task(
                db=fake_db, task="social_post", prompt="post", user_id=44,
                lane="fast", use_cache=False,
            ))
    finally:
        restore_providers(real)
    check("AI xatosi: ok=False", broken.ok is False)
    check("AI xatosi: refund AYNAN 1 marta",
          release2.await_count == 1 and release2.call_args.args[1] == 44
          and release2.call_args.args[2] == 777, str(release2.call_args))
    check("AI xatosi: refunded=True", broken.refunded is True)
    check("AI xatosi DB'ga yozildi (status failed)",
          fake_db.saved_events[-1]["status"] == "failed")

    # 4d) Hisobot: DB agregati + in-memory birlashtiriladi.
    report = run(ai_tasks.usage_report(fake_db, user_id=42, period="daily"))
    check("hisobot manbasi database", report["source"] == "database", str(report["source"]))
    check("hisobot DB qismini qaytaradi", report["database"]["totals"]["requests"] == 1)
    check("hisobot memory qismini ham qaytaradi", "totals" in report["memory"])
    check("DB hisoboti period bilan chaqirildi", fake_db.report_calls[-1] == "daily")
    memory_only = run(ai_tasks.usage_report(None, user_id=42, period="daily"))
    check("DB yo'q bo'lsa memory manbasi", memory_only["source"] == "memory")

    # 4e) quota_status — kunlik kvota ko'rsatkichi.
    status = run(ai_tasks.quota_status(fake_db, 42))
    check("quota_status: used/max/remaining",
          status == {"used": 3, "max_ai": 10, "remaining": 7, "available": True}, str(status))

    # 4f) operation_type xaritasi — DB oq ro'yxatiga mos.
    check("operation_type_for('social_post')", ag.operation_type_for("social_post") == "magic_post")
    check("operation_type_for('post_score')", ag.operation_type_for("post_score") == "post_score")
    check("operation_type_for('repurpose')", ag.operation_type_for("repurpose") == "ai_studio")
    check("operation_type_for(noma'lum)", ag.operation_type_for("zzz_yoq") == "other")
    allowed_ops = set(db_mod.AI_OPERATION_TYPES)
    mapped = set(ag.TASK_OPERATION_TYPES.values())
    check("barcha xarita qiymatlari AI_OPERATION_TYPES ichida",
          mapped <= allowed_ops, str(sorted(mapped - allowed_ops)))

    # 4g) reserve_quota=False (bepul operatsiya) — bron umuman chaqirilmaydi.
    reset_state()
    reserve3 = AsyncMock(return_value={"allowed": True, "reservation_id": 1})
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")}, executor_of({"Gemini": good()}))
    try:
        with patch("services.ai_quota.reserve_ai_quota", reserve3):
            free = run(run_ai_task(db=fake_db, task="post_score", prompt="bahola",
                                   user_id=45, lane="smart", reserve_quota=False,
                                   use_cache=False))
    finally:
        restore_providers(real)
    check("reserve_quota=False: bron chaqirilmadi", reserve3.await_count == 0)
    check("reserve_quota=False: javob qaytadi", free.ok is True)


# ===========================================================================
# TEST 5 — MOCK SIYOSATI (production'da DEFAULT O'CHIQ)
# ===========================================================================
def test_mock_policy():
    print("\n== TEST 5: Mock siyosati — production'da O'CHIQ ==")

    with env(ENVIRONMENT="production", AI_ALLOW_MOCK="0"):
        check("production: mock_mode() == off", ag.mock_mode() == ag.MOCK_MODE_OFF,
              ag.mock_mode())
        check("production: mock ruxsat etilmagan", ag.mock_provider_allowed() is False)
        check("production: provider_allowed('Mock') is False",
              ag.provider_allowed("Mock") is False)
        check("production: 'MockProvider' ham bloklangan",
              ag.provider_allowed("MockProvider") is False)
        check("production: haqiqiy provayder ruxsat etilgan",
              ag.provider_allowed("Gemini") is True)
        check("production: 'cache' ruxsat etilgan (Mock emas)",
              ag.provider_allowed("cache") is True)
        from services.ai.providers import mock_is_allowed
        check("services.ai.providers.mock_is_allowed() bilan sinxron (False)",
              bool(mock_is_allowed()) is False)

        # Zanjirda Mock bo'lsa ham — production'da CHETLAB O'TILADI.
        reset_state()
        spec = patch_lane_order(Lane.FAST, "Mock", "Gemini")
        real = patch_providers(lambda: {"Mock": _handle("Mock"), "Gemini": _handle("Gemini")},
                               executor_of({"Mock": good(), "Gemini": good("gemini-2.5-flash")}))
        try:
            res = run(ag.ai_gateway.generate(prompt="post", task="social_post",
                                             lane="fast", use_cache=False))
        finally:
            restore_providers(real)
            restore_lane_order(Lane.FAST, spec)
        check("production: Mock chaqirilmadi (fail-closed)",
              "Mock" not in [n for n, _ in CALLS], str(CALLS))
        check("production: haqiqiy provayder ishlatildi",
              res.ok and res.provider == "Gemini", str(res)[:120])
        check("production: Mock zanjirga umuman kirmaydi (faqat real)",
              res.provider_chain == ["Gemini"], str(res.provider_chain))

    with env(ENVIRONMENT="test", AI_ALLOW_MOCK="0"):
        check("test: mock_mode() == test", ag.mock_mode() == ag.MOCK_MODE_TEST)
        check("test: mock ruxsat etilgan", ag.mock_provider_allowed() is True)
        reset_state()
        spec = patch_lane_order(Lane.FAST, "Mock")
        real = patch_providers(lambda: {"Mock": _handle("Mock")},
                               executor_of({"Mock": {"post_text": GOOD_TEXT}}))
        try:
            ok_mock = run(ag.ai_gateway.generate(prompt="post", task="social_post",
                                                 lane="fast", use_cache=False))
        finally:
            restore_providers(real)
            restore_lane_order(Lane.FAST, spec)
        check("test: Mock ishlatiladi (alohida test rejimi)",
              ok_mock.ok and ok_mock.provider == "Mock", str(ok_mock)[:120])
    with env(ENVIRONMENT="development", AI_ALLOW_MOCK="0"):
        check("development: mock_mode() == development",
              ag.mock_mode() == ag.MOCK_MODE_DEVELOPMENT)
        check("dev: mock ruxsat etilgan", ag.mock_provider_allowed() is True)
    with env(ENVIRONMENT="production", AI_ALLOW_MOCK="1"):
        check("AI_ALLOW_MOCK=1: forced rejim (ochiq override)",
              ag.mock_mode() == ag.MOCK_MODE_FORCED)
        check("AI_ALLOW_MOCK=1: mock ruxsat etilgan", ag.mock_provider_allowed() is True)
    with env(ENVIRONMENT=None, AI_ALLOW_MOCK=None):
        check("ENVIRONMENT yo'q: fail-closed production + off",
              ag.environment() == "production" and ag.mock_mode() == ag.MOCK_MODE_OFF)
    with env(ENVIRONMENT="prod", AI_ALLOW_MOCK="0"):
        check("'prod' ham production kabi fail-closed (off)",
              ag.mock_mode() == ag.MOCK_MODE_OFF)


# ===========================================================================
# TEST 6 — RETRY / FALLBACK / CIRCUIT BREAKER
# ===========================================================================
def test_retry_policy():
    print("\n== TEST 6: Retry siyosati, fallback va backoff ==")

    # 6a) Siyosat birliklari.
    policy = DEFAULT_RETRY_POLICY.clip()
    check("standart: 2 urinish (1 + 1 retry)", policy.max_attempts == 2)
    check("rate_limit qayta uriniladi", policy.should_retry(1, "rate_limit") is True)
    check("timeout qayta uriniladi", policy.should_retry(1, "timeout") is True)
    check("server/network qayta uriniladi",
          policy.should_retry(1, "server_error") and policy.should_retry(1, "network"))
    check("dasturiy xato ('other') qayta urinilMAYDI",
          policy.should_retry(1, "other") is False)
    check("2 urinishdan keyin to'xtaydi", policy.should_retry(2, "rate_limit") is False)
    check("quality rad etish 1 marta qayta uriniladi",
          policy.should_retry(1, KIND_QUALITY) is True)
    check("NO_RETRY_POLICY: urinish yo'q",
          NO_RETRY_POLICY.should_retry(1, "rate_limit") is False)
    check("FAST lane: backoff 0 (foydalanuvchi kutmaydi)",
          policy_for("fast").base_delay == 0.0 and policy_for("fast").max_delay == 0.0)
    check("QUALITY lane: backoff > 0", policy_for("smart").base_delay > 0)
    check("backoff byudjet tugasa 0", policy.delay_for(1, remaining=0.5) == 0.0)
    check("backoff jitter chegarasida",
          0.0 <= policy.delay_for(1, remaining=10.0, rand=lambda: 1.0) <= policy.max_delay)
    check("clip() noto'g'ri qiymatlarni tuzatadi",
          RetryPolicy(max_attempts=0, base_delay=-5).clip().max_attempts >= 1)

    # 6b) 429 → urinishlar → keyingi provayder (fallback).
    reset_state()
    real = patch_providers(
        lambda: {"Groq": _handle("Groq"), "Gemini": _handle("Gemini")},
        executor_of({"Gemini": good()}, fail_kinds={"Groq": "HTTP 429 Too Many Requests"}),
    )
    try:
        res = run(ag.ai_gateway.generate(prompt="post", task="social_post",
                                         lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    groq_calls = [n for n, _ in CALLS if n == "Groq"]
    check("429: Groq 2 marta urinildi (1 + 1 retry)", len(groq_calls) == 2, str(CALLS))
    check("429: keyin Gemini fallback", res.ok and res.provider == "Gemini")
    check("429: provider_chain qayd etildi", res.provider_chain == ["Groq", "Gemini"],
          str(res.provider_chain))
    check("429: umumiy urinishlar soni 3", res.attempts == 3, str(res.attempts))

    # 6c) Doimiy (dasturiy) xato → AYNAN 1 urinish, darhol keyingi provayder.
    reset_state()
    real = patch_providers(
        lambda: {"Groq": _handle("Groq"), "Gemini": _handle("Gemini")},
        executor_of({"Gemini": good()}, fail_kinds={"Groq": "ValueError: bad payload"}),
    )
    try:
        res2 = run(ag.ai_gateway.generate(prompt="post", task="social_post",
                                          lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    check("doimiy xato: 1 urinish",
          len([n for n, _ in CALLS if n == "Groq"]) == 1, str(CALLS))
    check("doimiy xato: keyingi provayder ishladi", res2.ok and res2.provider == "Gemini")

    # 6d) Qat'iy sifat validatori: yupqa javob retry qilinadi, keyin RAD etiladi.
    reset_state()
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": {"post_text": "Yupqa javob"}}))
    try:
        strict = run(ag.ai_gateway.generate(
            prompt="post", task="social_post", lane="smart",
            require_quality=True, use_cache=False,
        ))
    finally:
        restore_providers(real)
    check("yupqa javob: retry qilindi (2 urinish)", len(CALLS) == 2, str(CALLS))
    check("yupqa javob: RAD etildi (bypass yo'q)", strict.ok is False)
    check("retry ko'rsatmasi 2-urinishda biriktirildi",
          gw.RETRY_INSTRUCTION not in INSTRUCTIONS[0]
          and gw.RETRY_INSTRUCTION in INSTRUCTIONS[1], str(INSTRUCTIONS)[:200])

    # 6e) Sifat rad etilsa ham keyingi provayder yaroqli javob bersa — o'tadi.
    reset_state()
    real = patch_providers(
        lambda: {"Groq": _handle("Groq"), "Gemini": _handle("Gemini")},
        executor_of({"Groq": {"post_text": "Yupqa"}, "Gemini": good()}),
    )
    try:
        rescued = run(ag.ai_gateway.generate(
            prompt="post", task="social_post", lane="smart",
            require_quality=True, use_cache=False,
        ))
    finally:
        restore_providers(real)
    check("yupqa javobdan keyin sifatli provayder ishlatildi",
          rescued.ok and rescued.provider == "Gemini", str(rescued)[:120])

    # 6f) Circuit breaker: ketma-ket xatolardan keyin provayder o'tkazib yuboriladi.
    reset_state()
    monitor = default_health_monitor()
    real = patch_providers(lambda: {"Groq": _handle("Groq"), "Gemini": _handle("Gemini")},
                           executor_of({}, always_fail=True))
    try:
        for i in range(3):
            run(ag.ai_gateway.generate(prompt=f"xato {i}", task="social_post",
                                       lane="fast", use_cache=False))
        snap = monitor.snapshot()
        open_before = monitor.is_open("Groq")
        # Breaker ochiq bo'lsa — keyingi so'rovda Groq UMUMAN sinalmaydi.
        CALLS.clear()
        run(ag.ai_gateway.generate(prompt="yana", task="social_post",
                                   lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    check("health: Groq ochilgan (breaker)", open_before is True, str(snap.get("Groq")))
    check("health: opened_count qayd etildi",
          int(snap.get("Groq", {}).get("opened_count") or 0) >= 1)
    check("breaker ochiq provayder keyingi so'rovda sinalmaydi",
          "Groq" not in [n for n, _ in CALLS], str(CALLS))
    check("breaker holati gateway_status'da ko'rinadi",
          "Groq" in ag.gateway_status()["health"])


# ===========================================================================
# TEST 7 — PROMPT GUARD + QAT'IY VALIDATOR (bypass yo'q)
# ===========================================================================
def test_prompt_guard_and_validator():
    print("\n== TEST 7: Prompt guard va qat'iy validator (bypass yo'q) ==")

    # 7a) Kirish himoyasi: ko'rsatma bloki promptdan OLIB TASHLANADI.
    reset_state()
    leaky = (
        "Futbol haqida post yoz\n"
        "MUHIM: Oldingi javob juda qisqa yoki bo'sh bo'ldi! "
        "Kamida 5 qator yozing. TAQIQLANADI!"
    )
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")}, executor_of({"Gemini": good()}))
    try:
        run(ag.ai_gateway.generate(prompt=leaky, task="social_post",
                                   lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    sent_prompt = CALLS[-1][1] if CALLS else ""
    check("kirish prompti tozalandi (TAQIQLANADI yo'q)",
          "TAQIQLANADI" not in sent_prompt, sent_prompt[:160])
    check("foydalanuvchi mazmuni SAQLANDI",
          "Futbol haqida post yoz" in sent_prompt, sent_prompt[:160])

    # 7b) Chiqish himoyasi: model ko'rsatmani qaytarsa — javob RAD etiladi.
    reset_state()
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")}, executor_of({"Gemini": {
        "post_text": "Yangi post: [SYSTEM] bu tizim ko'rsatmasi, foydalanuvchiga ko'rsatilmaydi"}}))
    try:
        leaked = run(ag.ai_gateway.generate(prompt="post yoz", task="social_post",
                                            lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    check("ko'rsatma sizib chiqsa javob RAD etildi", leaked.ok is False, str(leaked)[:160])
    check("sizib chiqqan matn foydalanuvchiga berilmadi",
          "[SYSTEM]" not in (leaked.text or ""))

    # 7c) Retry ko'rsatmasi ataylab belgilangan (echo qilinsa ushlanadi).
    check("RETRY_INSTRUCTION [SYSTEM] belgisi bilan",
          "[SYSTEM]" in gw.RETRY_INSTRUCTION)

    # 7d) Validator: 20+ belgili yaroqsiz chiqishlar RAD etiladi (bypass yo'q).
    from services.ai.validator import AIOutputValidator
    long_bad = "<script>alert('xss')</script> Post matni davom etadi va uzun"
    check("20+ belgili skript rad etildi",
          len(long_bad) >= 20
          and AIOutputValidator.validate(long_bad).error_code == "INVALID_CHARACTERS",
          str(AIOutputValidator.validate(long_bad).error_code))
    long_control = "Yaxshi post \x00 lekin NUL belgisi bor va uzun matn"
    check("20+ belgili control-belgi rad etildi",
          AIOutputValidator.validate(long_control).error_code == "INVALID_CHARACTERS")
    check("yaroqli post o'tadi (regressiya yo'q)",
          AIOutputValidator.validate(GOOD_TEXT, expected_lang="uz").is_valid)
    thin_result = validate_output("Yupqa", lang="uz")
    check("ai_engine validator: yupqa matn THIN_OUTPUT",
          thin_result.is_valid is False and thin_result.error_code == "THIN_OUTPUT",
          str(thin_result.error_code))
    check("ai_engine validator: yaroqli matn o'tadi",
          validate_output(GOOD_TEXT, lang="uz").is_valid is True)
    long_thin = "ha ha ha ha ha ha ha ha ha ha ha ha ha ha ha ha"
    check("uzun (20+) LEKIN mazmunsiz matn rad etiladi (uzunlik bypass emas)",
          len(long_thin) >= 20
          and validate_output(long_thin, lang="uz").is_valid is False,
          str(validate_output(long_thin, lang="uz").error_code))
    russian = "Это очень длинный русский текст который должен быть отклонён"
    check("uzun (20+) begona tilli matn rad etiladi (til bypass emas)",
          len(russian) >= 20
          and validate_output(russian, lang="uz").is_valid is False,
          str(validate_output(russian, lang="uz").error_code))
    check("begona til sababi LANGUAGE_MISMATCH",
          validate_output(russian, lang="uz").error_code == "LANGUAGE_MISMATCH")
    from services.ai_engine.schemas import PostResult, parse_result
    schema_result = validate_output('{"hook": "s"}', lang="uz", schema=PostResult)
    check("sxema buzilganda INVALID_SCHEMA (qat'iy)",
          schema_result.is_valid is False
          and schema_result.error_code == "INVALID_SCHEMA", str(schema_result))
    strict_failed = False
    try:
        parse_result('{"hook": "s"}', PostResult, strict=True)
    except ValueError:
        strict_failed = True
    check("qat'iy parse buzilgan sxemani rad etadi", strict_failed)

    # 7e) Statik tekshiruv: sun'iy "length >= 20" bypass YO'Q.
    def strip_comments_and_docstrings(source: str) -> str:
        text = re.sub(r'"""(?:.|\n)*?"""', "", source)
        text = re.sub(r"'''(?:.|\n)*?'''", "", text)
        return re.sub(r"#[^\n]*", "", text)

    # AI STEK DE-BLOAT: kanonik AI shlyuz kodi `services/ai/engine/` ga
    # ko'chirildi (`services/ai_engine/` — nol-logikali muvofiqlik shimi).
    # Skanerlanadigan FAYL YO'LLARI yangilandi; tekshiruv mezonlari
    # (bypass shakli va uzunlik qabul mezoni yo'qligi) O'ZGARMAGAN.
    ai_sources = {}
    for rel in (
        "services/ai/validator.py",
        "services/ai/engine/validator.py",
        "services/ai/engine/gateway.py",
        "services/ai/engine/providers.py",
        "services/ai/prompt_guard.py",
        "services/ai/engine/app_service.py",
    ):
        ai_sources[rel] = strip_comments_and_docstrings(
            (ROOT / rel).read_text(encoding="utf-8"))
    for rel, source in ai_sources.items():
        check(f"{rel}: 'is_valid or len(...)' bypass shakli yo'q",
              "is_valid or len(" not in source)
    for rel in ("services/ai/validator.py", "services/ai/engine/validator.py"):
        check(f"{rel}: uzunlik (>=20) qabul mezoni yo'q",
              not re.search(r"len\([^)]*\)\s*>=\s*20", ai_sources[rel]))

    # 7f) Shlyuz hech qachon bo'sh matnni ok=True qilib qaytarmaydi.
    reset_state()
    real = patch_providers(lambda: {"Gemini": _handle("Gemini")},
                           executor_of({"Gemini": {"post_text": "   "}}))
    try:
        empty = run(ag.ai_gateway.generate(prompt="post", task="social_post",
                                           lane="fast", use_cache=False))
    finally:
        restore_providers(real)
    check("bo'sh javob ok=True BO'LMAYDI (fail-soft)", empty.ok is False, str(empty)[:120])


# ===========================================================================
# TEST 8 — HANDLER IZOLYATSIYASI VA BACKWARD COMPATIBILITY
# ===========================================================================
def test_handler_isolation_and_compat():
    print("\n== TEST 8: Handler izolyatsiyasi va backward compatibility ==")
    handlers_dir = ROOT / "handlers"
    forbidden = (
        "services.ai_service", "from services.ai_service import",
        "services.ai.providers", "services.ai_engine.providers",
        "services.ai.orchestrator", "ai_engine import providers",
    )
    violations = []
    canonical_users = []
    for py in sorted(handlers_dir.glob("*.py")):
        src = py.read_text(encoding="utf-8", errors="ignore")
        for needle in forbidden:
            if needle in src:
                violations.append(f"{py.name}: {needle}")
        if "services.ai_engine" in src or "services.ai_gateway" in src \
                or "services.ai_quota" in src:
            canonical_users.append(py.name)
    check("hech bir handler provayder qatlamiga bog'lanmaydi", not violations,
          str(violations))
    check("handlerlar kanonik sirt(lar)dan foydalanadi",
          len(canonical_users) >= 4, str(canonical_users))
    check("content_calendar_flow: kanonik ai_gateway + legacy zaxira",
          (ROOT / "handlers" / "content_calendar_flow.py").read_text(
              encoding="utf-8").count("ai_gateway.generate") >= 1)

    # 8b) Legacy adapter o'zgarmagan (services.ai_service.run_ai_chain delegati).
    reset_state()
    from services import ai_service

    async def fake_run_chain(prompt, system_instruction, lang=None):
        return {"content": "legacy javob", "provider": "LegacyChain"}

    real_chain = ai_service.run_ai_chain
    ai_service.run_ai_chain = fake_run_chain
    try:
        result = run(gw.legacy_chain("p", "s", lang="uz"))
    finally:
        ai_service.run_ai_chain = real_chain
    check("legacy_chain → services.ai_service.run_ai_chain",
          result.get("provider") == "LegacyChain")
    check("legacy_chain natijasi o'zgarmagan (dict shakl)",
          result.get("content") == "legacy javob")
    legacy_events = [e for e in telemetry.default_recorder().events()
                     if e.task == "legacy_chain"]
    check("legacy yo'l ham telemetriyaga yozildi", len(legacy_events) == 1,
          str(len(legacy_events)))
    check("legacy yozuvida provider qayd etildi",
          bool(legacy_events) and legacy_events[0].provider == "LegacyChain")

    # 8c) Gateway diagnostikasi (admin/health) yangi bo'limlarni beradi.
    status = ag.gateway_status()
    check("gateway_status: mock bo'limi", "mock" in status and "mode" in status["mock"])
    check("gateway_status: usage hisobi", "recorded" in status["usage"])
    check("gateway_status: lane'lar saqlangan",
          set(status["lanes"]) == {"FAST", "QUALITY", "REASONING", "VISION"})

    # 8d) ai_engine paketidan yangi API'lar eksport qilinadi.
    from services import ai_engine
    for name in ("ai_gateway", "AIGateway", "ai_tasks", "run_ai_task",
                 "estimate_tokens", "estimate_cost", "ai_usage_report",
                 "RetryPolicy", "AIUsageEvent", "UsageRecorder", "mock_mode"):
        check(f"ai_engine.{name} eksport qilinadi", hasattr(ai_engine, name))

    # 8e) Facade — AYNAN bir xil obyektlar (dublikat logika yo'q).
    check("facade.run_ai_task — ai_engine.app_service bilan bir xil",
          ag.run_ai_task is run_ai_task)
    check("facade.ai_gateway — gateway.ai_gateway bilan bir xil",
          ag.ai_gateway is gw.ai_gateway)
    check("facade.ai_tasks — yagona servis", ag.ai_tasks is ai_tasks)


# ===========================================================================
# RUNNER
# ===========================================================================
def main() -> int:
    print("=" * 70)
    print(" 💰 PHASE 6 — AI ARCHITECTURE CONSOLIDATION & COST CONTROL")
    print("=" * 70)
    test_canonical_gateway()
    test_task_lane_map()
    test_telemetry_and_cost()
    test_application_service()
    test_mock_policy()
    test_retry_policy()
    test_prompt_guard_and_validator()
    test_handler_isolation_and_compat()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] PHASE 6 TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE 6 — AI GATEWAY & COST CONTROL 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
