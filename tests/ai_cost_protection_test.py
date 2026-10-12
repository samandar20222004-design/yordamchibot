#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🛡 STEP 1 — AI XARAJAT HIMOYASI (telemetriya, konkurentlik, byudjet, marshrutlash).

Qamrov:
  1) Narx: jadvalda yo'q model → ``unpriced`` (``$0`` emas); kesh → ``cached``.
  2) Yagona narx manbai: telemetriya jadvali ``cost_tracker.MODEL_PRICES`` ning hosilasi.
  3) Kesh kaliti: channel_context, prompt, til va model versiyasi kalitga kiradi.
  4) Foydalanuvchi konkurentligi: bir vaqtda faol joblar limiti (fail-fast).
  5) Byudjet: FREE/PRO kunlik/oylik token+USD, bron, refund (idempotent).
  6) Fallback yo'li: telemetriya BIR marta yoziladi (legacy_chain bilan dedupe),
     gate/byudjet rad etsa provayder CHAQIRILMAYDI, xatoda bron qaytariladi.
  7) Arzon model tartibi (faqat ``cheap`` transformatsiyalar) va amal turi (action_type).
  8) /economics: o'rtacha foydalanuvchi xarajati vs PRO narxi, yalpi marja, unpriced eslatma.

Eslatma: barcha testlar OFFLINE (MockProvider/fake provayder). Muhit —
``tests/run_tests.sh`` dagidek (ENVIRONMENT=test).
"""

from __future__ import annotations

import asyncio
import os
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AI_COST_PROTECTION_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BETA_INVITE_ONLY", "false")

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
    """Vaqtinchalik muhit o'zgaruvchilari (byudjet limitlari uchun)."""
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
from services.ai import admission, budget, cost_tracker, fallback  # noqa: E402
from services.ai.concurrency import UserJobGate  # noqa: E402
from services.ai.engine import cache as engine_cache  # noqa: E402
from services.ai.engine import gateway as gw  # noqa: E402
from services.ai.engine import telemetry  # noqa: E402
from services.ai.usage_scope import (  # noqa: E402
    action_type_for,
    current_scope,
    model_tier_for,
    note_model,
    model_note,
    prefer_cheap_models,
    usage_scope,
)


class FakeProvider(fallback.AIProvider):
    """Offline provayder: chaqiruvlarni sanaydi, modelni qayd etadi."""

    name = "FakeP"
    tier = 1
    key_attr = None

    def __init__(self, mode: str = "ok"):
        self.mode = mode
        self.calls = 0

    def is_available(self) -> bool:
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        self.calls += 1
        if self.mode == "fail":
            raise RuntimeError("provider down")
        note_model("fake-model-1")
        return {"post_text": "Kofe haqida qisqa va aniq post matni. " * 3}


def reset_state(fresh_ledger: bool = True):
    """Har test uchun toza telemetriya/ledger/byudjet holati."""
    telemetry.reset_default_recorder()
    if fresh_ledger:
        cost_tracker._ledger = cost_tracker.CostLedger()
    budget.set_tier_resolver(lambda uid: False)  # hammasi FREE
    budget._guard.__init__()                    # bron holatini tozalash
    gate = admission.default_user_gate()
    gate._active.clear()


# ===========================================================================
# TEST 1 — NARX: UNPRICED TEG, $0 EMAS
# ===========================================================================
def test_pricing_status():
    print("\n== TEST 1: Narx holati — unpriced ($0 emas), priced, cached ==")
    reset_state()

    priced = telemetry.build_usage_event(
        result=gw.GatewayResult(ok=True, text="salom " * 50, provider="Gemini",
                                model="gemini-2.5-flash", task="social_post"),
        prompt="p" * 400, user_id=1, channel_id=-100, operation_type="magic_post")
    check("ma'lum model → cost_status=priced", priced.cost_status == telemetry.COST_PRICED,
          priced.cost_status)
    check("ma'lum model → xarajat > 0", priced.estimated_cost > 0, str(priced.estimated_cost))

    unknown = telemetry.build_usage_event(
        result=gw.GatewayResult(ok=True, text="javob " * 50, provider="Mystery",
                                model="zeta-9000", task="social_post"),
        prompt="p" * 400, user_id=1, channel_id=-100)
    check("narxsiz model → cost_status=unpriced", unknown.cost_status == telemetry.COST_UNPRICED,
          unknown.cost_status)
    check("narxsiz model → $0 deb ko'rsatilmaydi (unpriced=True)",
          unknown.as_dict().get("unpriced") is True)
    check("narxsiz model → estimated_cost = 0 (soxta raqam yo'q)",
          unknown.estimated_cost == 0.0)

    cached = telemetry.build_usage_event(
        result=gw.GatewayResult(ok=True, text="x", provider="cache", cached=True,
                                model="gemini-2.5-flash"),
        prompt="p", user_id=1)
    check("kesh → cost_status=cached (unpriced emas)",
          cached.cost_status == telemetry.COST_CACHED, cached.cost_status)

    # Ledger: unpriced hisobi 0 emas, alohida sanaladi.
    book = cost_tracker.CostLedger()
    entry = book.record(user_id=7, provider="Mystery", model="zeta-9000",
                        input_tokens=500, output_tokens=500)
    check("ledger: noma'lum model → cost_status=unpriced",
          entry.get("cost_status") == "unpriced", str(entry.get("cost_status")))
    check("ledger: unpriced soni oshdi (memory bo'yicha 0 emas)",
          book.user_costs(7)["unpriced_requests"] == 1)
    check("ledger: unpriced so'rov xarajati 0.0 (to'qilmagan)",
          book.user_costs(7)["cost_usd"] == 0.0)

    kpi = book.record(user_id=7, provider="Gemini", model="gemini-2.5-flash",
                      input_tokens=1000, output_tokens=1000)
    check("ledger: ma'lum model → priced", kpi.get("cost_status") == "priced")
    check("ledger: priced bucket hisobi", book.user_costs(7)["priced_requests"] == 1)


# ===========================================================================
# TEST 2 — YAGONA NARX JADVALI (telemetriya = cost_tracker)
# ===========================================================================
def test_single_price_table():
    print("\n== TEST 2: Yagona narx manbai (ikkinchi jadval yo'q) ==")
    check("PRICE_TABLE kalitlari = MODEL_PRICES kalitlari",
          list(telemetry.PRICE_TABLE.keys()) == list(cost_tracker.MODEL_PRICES.keys()))
    spec = telemetry.price_spec("Gemini", "gemini-2.5-flash")
    ref = cost_tracker.MODEL_PRICES["gemini-2.5-flash"]
    check("gemini-2.5-flash narxi bir xil (nolga tushmaydi)",
          spec.input_per_1k == ref.input_per_1k and spec.output_per_1k == ref.output_per_1k
          and spec.input_per_1k > 0)
    check("uzun moslik: gemini-2.5-flash-lite emas, flash ustun (eng uzun kalit)",
          telemetry.price_spec("Gemini", "gemini-2.5-flash").input_per_1k
          == cost_tracker.price_for("Gemini", "gemini-2.5-flash").input_per_1k)
    check("telemetry va cost_tracker bir xil moslashadi",
          telemetry.is_priced("Groq", "llama-3.1-8b-instant")
          == cost_tracker.is_priced("Groq", "llama-3.1-8b-instant"))


# ===========================================================================
# TEST 3 — KESH KALITI: channel_context + prompt + til + model versiyasi
# ===========================================================================
def test_cache_key_strict():
    print("\n== TEST 3: Kesh kaliti — channel_dna, prompt, til, model versiyasi ==")

    def key(**kw):
        base = dict(prompt="Post yoz", lane="FAST", task="social_post", lang="uz")
        base.update(kw)
        return engine_cache.cache_key(**base)

    check("bir xil kirish → bir xil kalit", key() == key())
    check("boshqa kanal DNA → boshqa kalit",
          key(channel_context="DNA: rasmiy") != key(channel_context="DNA: hazil"))
    check("boshqa prompt → boshqa kalit", key(prompt="Boshqa") != key())
    check("boshqa til → boshqa kalit", key(lang="ru") != key())
    check("boshqa model versiyasi → boshqa kalit",
          key(model_version="ck2|v1|gemini-a") != key(model_version="ck2|v2|gemini-a"))
    check("model_version() sxema versiyasini o'z ichiga oladi",
          engine_cache.CACHE_SCHEMA_VERSION in engine_cache.model_version())
    check("model_version() chaqiruvlar orasida barqaror (lazy import, kalit siljimaydi)",
          engine_cache.model_version() == engine_cache.model_version())
    with env(AI_MODEL_VERSION="2026-10-a"):
        mv1 = engine_cache.model_version()
    with env(AI_MODEL_VERSION="2026-10-b"):
        mv2 = engine_cache.model_version()
    check("AI_MODEL_VERSION o'zgarsa model_version o'zgaradi", mv1 != mv2)
    check("gateway kesh kaliti channel_context va model_version bilan ishlaydi",
          key(channel_context="A", model_version=mv1) != key(channel_context="A", model_version=mv2))


# ===========================================================================
# TEST 4 — FOYDALANUVCHI KONKURENTLIGI (fail-fast)
# ===========================================================================
def test_user_job_gate():
    print("\n== TEST 4: Foydalanuvchi parallel-job limiti ==")
    gate = UserJobGate(max_per_user=2)
    check("1-slot olinadi", gate.try_acquire(1) is True)
    check("2-slot olinadi", gate.try_acquire(1) is True)
    check("3-slot RAD etiladi (limit 2)", gate.try_acquire(1) is False)
    check("boshqa foydalanuvchi — o'z limiti bor", gate.try_acquire(2) is True)
    gate.release(1)
    check("bo'shatilgach yana olinadi", gate.try_acquire(1) is True)
    gate.release(1)
    gate.release(1)
    gate.release(1)  # ortiqcha chaqiruv — manfiy bo'lmaydi
    check("ortiqcha release xavfsiz (active=0)", gate.active(1) == 0)
    check("user_id=None → cheklov yo'q", gate.try_acquire(None) is True)
    check("default limit AI_USER_MAX_CONCURRENT_JOBS (>=1)",
          admission.default_user_gate().max_per_user >= 1)


# ===========================================================================
# TEST 5 — BYUDJET: FREE/PRO, bron, refund
# ===========================================================================
def test_budget_guard():
    print("\n== TEST 5: Kunlik/oylik byudjet — FREE/PRO, bron, refund ==")
    reset_state()
    guard = budget.BudgetGuard()

    with env(AI_BUDGET_FREE_DAILY_USD="0.05", AI_BUDGET_FREE_DAILY_TOKENS="1000000",
             AI_BUDGET_FREE_MONTHLY_USD="10", AI_BUDGET_FREE_MONTHLY_TOKENS="10000000"):
        d1 = run(guard.acquire(5, budget.TIER_FREE, tokens=100, usd=0.01))
        check("birinchi so'rov byudjetga sig'adi", d1.allowed)
        d2 = run(guard.acquire(5, budget.TIER_FREE, tokens=100, usd=0.05))
        check("bronlar yig'indisi limitdan oshsa RAD (daily_usd)",
              (not d2.allowed) and d2.reason == "daily_usd", d2.reason)
        check("rad etilgan so'rov bron qoldirmaydi",
              guard.inflight(5).usd == 0.01)
        check("rad etish sanagichi oshdi", guard.status()["denied"] >= 1)

        check("bron bo'shatiladi (release → True)", guard.release(d1.ticket) is True)
        check("ikkinchi release idempotent (False)", guard.release(d1.ticket) is False)
        d3 = run(guard.acquire(5, budget.TIER_FREE, tokens=100, usd=0.05))
        check("refund'dan keyin byudjet qayta ochiladi", d3.allowed)
        guard.release(d3.ticket)

        # Ledger'dagi haqiqiy sarf ham hisobga olinadi (memory).
        cost_tracker.default_ledger().record(user_id=5, provider="Gemini",
                                             model="gemini-2.5-flash",
                                             input_tokens=900_000, output_tokens=0)
        d4 = run(guard.acquire(5, budget.TIER_FREE, tokens=10, usd=0.01))
        check("haqiqiy sarf (ledger) bilan limit kesiladi",
              (not d4.allowed) and d4.reason in ("daily_usd", "monthly_usd"),
              d4.reason)
        check("rad xabari uz/ru/en tillarda",
              all(budget.budget_message(lang, d4.period) for lang in ("uz", "ru", "en"))
              and budget.budget_message("uz", "daily") != budget.budget_message("en", "daily"))

    reset_state()
    guard = budget.BudgetGuard()
    with env(AI_BUDGET_FREE_DAILY_USD="0.05", AI_BUDGET_PRO_DAILY_USD="5",
             AI_BUDGET_PRO_MONTHLY_USD="5"):
        check("PRO tarif — kengroq limit (FREE rad etgan summa o'tadi)",
              run(guard.acquire(9, budget.TIER_PRO, tokens=10, usd=0.5)).allowed)
        check("noma'lum tarif → FREE (xavfsiz standart)",
              budget.tier_budget("weird").tier == budget.TIER_FREE)
    with env(AI_BUDGET_FREE_DAILY_USD="0", AI_BUDGET_FREE_MONTHLY_USD="0",
             AI_BUDGET_FREE_DAILY_TOKENS="0", AI_BUDGET_FREE_MONTHLY_TOKENS="0"):
        check("limit 0 → cheklov yo'q", budget.tier_budget("free").daily_usd == 0.0
              and run(guard.acquire(11, budget.TIER_FREE, 10, 999.0)).allowed)
    with env(AI_BUDGET_PRO_MONTHLY_USD=None, AI_BUDGET_PRO_MAX_COST_SHARE="0.4"):
        pro_month = budget.tier_budget("pro").monthly_usd
        check("PRO oylik USD = PRO narxi × ulush (>0)", pro_month > 0, str(pro_month))
    est_tokens, est_usd = budget.estimate_request("salom dunyo " * 20, "sys")
    check("taxminiy bron: tokens>0 va usd>0", est_tokens > 0 and est_usd > 0)

    # Tarif aniqlash: is_pro → PRO; resolver xatosi → FREE.
    check("is_pro=True → PRO", run(budget.resolve_tier(3, True)) == budget.TIER_PRO)
    budget.set_tier_resolver(lambda uid: 1 / 0)
    check("tarif aniqlash xatosi → FREE (fail-closed)",
          run(budget.resolve_tier(3, False)) == budget.TIER_FREE)
    budget.set_tier_resolver(lambda uid: True)
    check("resolver PRO qaytarsa → PRO", run(budget.resolve_tier(3, False)) == budget.TIER_PRO)
    budget.set_tier_resolver(None)  # standart (DB yo'q → FREE)
    check("DB yo'q → FREE (standart resolver)",
          run(budget.resolve_tier(3, False)) == budget.TIER_FREE)


# ===========================================================================
# TEST 6 — FALLBACK YO'LI: telemetriya, gate/byudjet, refund, dedupe
# ===========================================================================
def test_fallback_telemetry_and_gates():
    print("\n== TEST 6: Fallback — telemetriya, gate, byudjet, refund ==")
    reset_state()
    provider = FakeProvider("ok")
    svc = fallback.AIFallbackService(providers=[provider])

    with usage_scope(user_id=42, channel_id=-1001, action_type="post"):
        res = run(svc.generate("Kofe haqida post", "tizim", lang="uz"))
    check("muvaffaqiyatli javob (post_text)", bool(res.get("post_text")), str(res)[:120])
    check("provayder bir marta chaqirildi", provider.calls == 1)
    check("real model qayd etildi (fake-model-1)", res.get("model") == "fake-model-1",
          str(res.get("model")))
    user_events = [e for e in telemetry.default_recorder().events() if e.user_id == 42]
    check("telemetriya: aynan 1 ta yozuv", len(user_events) == 1, str(len(user_events)))
    if user_events:
        ev = user_events[0]
        check("yozuvda user_id/channel_id bor", ev.user_id == 42 and ev.channel_id == -1001)
        check("yozuvda provider/model bor", ev.provider == "FakeP" and ev.model == "fake-model-1")
        check("yozuvda action_type=post", ev.action_type == "post", ev.action_type)
        check("yozuvda token hajmi > 0", ev.input_tokens > 0 and ev.output_tokens > 0)
    check("xarajat ledger'ida ham 1 ta so'rov",
          cost_tracker.default_ledger().user_costs(42)["requests"] == 1)
    check("bron/slot bo'shatildi (byudjet inflight=0)",
          budget.default_guard().inflight(42).tokens == 0)
    check("bron/slot bo'shatildi (gate active=0)",
          admission.default_user_gate().active(42) == 0)

    # Xato → telemetriya 'failed', bron qaytariladi.
    reset_state()
    failing = FakeProvider("fail")
    svc = fallback.AIFallbackService(providers=[failing])
    with usage_scope(user_id=43, action_type="audit"):
        res = run(svc.generate("x", "tizim", lang="uz"))
    check("xato: javob dict, post_text yo'q", not res.get("post_text"))
    fails = [e for e in telemetry.default_recorder().events() if e.user_id == 43]
    check("xatoda ham aynan 1 ta telemetriya yozuvi", len(fails) == 1, str(len(fails)))
    check("xato yozuvi status=failed",
          bool(fails) and fails[0].status == telemetry.STATUS_FAILED)
    check("xatoda bron qaytarildi (inflight=0)", budget.default_guard().inflight(43).tokens == 0)
    check("xatoda gate bo'shatildi", admission.default_user_gate().active(43) == 0)

    # Gate to'lgan → provayder CHAQIRILMAYDI, rad telemetriyaga yoziladi.
    reset_state()
    provider = FakeProvider("ok")
    svc = fallback.AIFallbackService(providers=[provider])
    gate = admission.default_user_gate()
    for _ in range(gate.max_per_user):
        gate.try_acquire(44)
    with usage_scope(user_id=44):
        res = run(svc.generate("x", "tizim", lang="uz"))
    check("gate to'lgan: provayder chaqirilmadi", provider.calls == 0)
    check("gate to'lgan: xato matni qaytdi", bool(res.get("error")))
    rej = [e for e in telemetry.default_recorder().events() if e.user_id == 44]
    check("gate rad etishi telemetriyaga yozildi (user_busy)",
          len(rej) == 1 and rej[0].error_code == "user_busy",
          str([(e.error_code) for e in rej]))
    for _ in range(gate.max_per_user):
        gate.release(44)

    # Byudjet tugagan → provayder chaqirilmaydi.
    reset_state()
    provider = FakeProvider("ok")
    svc = fallback.AIFallbackService(providers=[provider])
    with env(AI_BUDGET_FREE_DAILY_USD="0.0000001"):
        with usage_scope(user_id=45):
            res = run(svc.generate("x", "tizim", lang="uz"))
    check("byudjet tugagan: provayder chaqirilmadi", provider.calls == 0)
    check("byudjet tugagan: xabar (uz)", "byudjet" in str(res.get("error", "")).lower())

    # Scope yo'q (kontekstsiz) → gate/byudjet yo'q, lekin ishlaydi.
    reset_state()
    provider = FakeProvider("ok")
    svc = fallback.AIFallbackService(providers=[provider])
    res = run(svc.generate("x", "tizim", lang="uz"))
    check("kontekstsiz chaqiruv ishlaydi (gate qo'llanmaydi)", bool(res.get("post_text")))
    check("scope tugagach tiklandi", current_scope() is None)


# ===========================================================================
# TEST 7 — LEGACY_CHAIN DEDUPE: bitta yozuv, bitta hisob
# ===========================================================================
def test_legacy_dedupe():
    print("\n== TEST 7: Legacy zanjir — ikki marta hisoblanmaydi ==")
    from services.ai import fallback as _public  # noqa: F401 — import sanity
    from services.ai import fallback as ai_fb

    reset_state()
    provider = FakeProvider("ok")
    svc = fallback.AIFallbackService(providers=[provider])

    async def fake_chain(prompt, system_instruction, lang=None):
        # Legacy zanjir ichida nested generate — telemetriya/gate qayta ishlamaydi.
        return await svc.generate(prompt, system_instruction, lang=lang)

    real = ai_fb.run_ai_chain
    ai_fb.run_ai_chain = fake_chain
    try:
        with usage_scope(user_id=50, channel_id=-7, action_type="vision"):
            res = run(gw.legacy_chain("p", "s", lang="uz"))
    finally:
        ai_fb.run_ai_chain = real
    check("legacy natija to'liq (post_text)", bool(res.get("post_text")))
    events = [e for e in telemetry.default_recorder().events() if e.user_id == 50]
    check("legacy: aynan 1 ta telemetriya yozuvi (dedupe)", len(events) == 1, str(len(events)))
    check("legacy yozuvi task=legacy_chain", bool(events) and events[0].task == "legacy_chain")
    check("legacy yozuvi user/channel scope'dan",
          bool(events) and events[0].channel_id == -7)
    check("legacy yozuvi action_type=vision", bool(events) and events[0].action_type == "vision")
    check("ledger: legacy so'rov bir marta", cost_tracker.default_ledger().user_costs(50)["requests"] == 1)
    check("provayder bir marta chaqirildi (qayta urinish yo'q)", provider.calls == 1)


# ===========================================================================
# TEST 8 — ARZON MODEL MARSHRUTI + AMAL TURI
# ===========================================================================
def test_cheap_routing_and_action_type():
    print("\n== TEST 8: Arzon model (faqat transformatsiya) + action_type ==")
    check("rewrite → cheap", model_tier_for("rewrite") == "cheap")
    check("shorten → cheap", model_tier_for("shorten") == "cheap")
    check("social_post (post yaratish) → standard", model_tier_for("social_post") == "standard")
    check("audit → standard (sifat saqlanadi)", model_tier_for("audit") == "standard")

    models = ["gemini-2.5-pro", "llama-3.3-70b", "llama-3.1-8b-instant", "mistral-large"]
    with usage_scope(model_tier="cheap"):
        ordered = prefer_cheap_models(models)
    check("cheap: arzon (8b/instant) oldinga suriladi", ordered[0] == "llama-3.1-8b-instant",
          str(ordered))
    check("cheap: ro'yxat o'zgarmaydi (faqat tartib)", sorted(ordered) == sorted(models))
    with usage_scope(model_tier="standard"):
        check("standard: tartib o'zgarmaydi", prefer_cheap_models(models) == models)
    check("kontekstsiz: tartib o'zgarmaydi", prefer_cheap_models(models) == models)

    check("action: image_post → vision", action_type_for("image_post") == "vision")
    check("action: voice_post → voice", action_type_for("voice_post") == "voice")
    check("action: post_score → audit", action_type_for("post_score") == "audit")
    check("action: social_post → post", action_type_for("social_post") == "post")
    check("action: kanonik 'vision' (operation_type) → vision",
          action_type_for("", "vision") == "vision")
    check("action: noma'lum → post (standart)", action_type_for("zzz", "") == "post")

    # model_note: provayder urinishi ichida qayd etiladi, tashqarida — yo'q.
    with model_note() as note:
        note_model("m-1")
    check("model_note: qayd etildi", note.model == "m-1")
    note_model("m-2")  # holder yo'q — jim
    check("model_note: tashqarida xato yo'q", True)


# ===========================================================================
# TEST 9 — /economics: o'rtacha foydalanuvchi vs PRO narxi, yalpi marja
# ===========================================================================
def test_economics_margin():
    print("\n== TEST 9: /economics — o'rtacha xarajat, PRO narxi, yalpi marja ==")
    from handlers.economics import build_economics_text

    book = cost_tracker.CostLedger()
    book.record(user_id=1, provider="Gemini", model="gemini-2.5-flash",
                input_tokens=200_000, output_tokens=100_000)
    book.record(user_id=2, provider="Mystery", model="zeta-9000",
                input_tokens=1000, output_tokens=1000)
    summary = cost_tracker.economics_summary(
        period="monthly", db_module=None, ledger=book, active_users=2,
        pro_price_uzs=19000, rate=12600)
    check("PRO narxi 19 000 so'm", summary["pro_price_uzs"] == 19000)
    check("o'rtacha foydalanuvchi xarajati = jami / faol",
          abs(summary["avg_cost_usd"] - summary["total_cost_usd"] / 2) < 1e-6)
    check("yalpi marja = (PRO - o'rtacha) / PRO",
          abs(summary["margin_rate"] - (19000 - summary["avg_cost_uzs"]) / 19000) < 1e-3,
          str(summary["margin_rate"]))
    check("unpriced so'rov sanaldi ($0 emas)", summary["unpriced_requests"] == 1)
    text = build_economics_text(summary, lang="en")
    check("matnda yalpi marja (EN) ko'rsatildi", "Gross margin" in text)
    check("matnda PRO narxi ko'rsatildi", "19 000" in text)
    check("matnda unpriced eslatma bor", "missing from the price table" in text)
    text_uz = build_economics_text(summary, lang="uz")
    check("uz matnda 'Yalpi marja' bor", "Yalpi marja" in text_uz)

    # Narxsiz model yo'q bo'lsa — eslatma chiqmaydi.
    clean = cost_tracker.economics_summary(
        period="monthly", db_module=None, ledger=cost_tracker.CostLedger(),
        active_users=1, pro_price_uzs=19000, rate=12600)
    check("unpriced yo'q → eslatma yo'q",
          "missing from the price table" not in build_economics_text(clean, lang="en"))


# ===========================================================================
# TEST 9b — VISION (gateway): gate/byudjet vision chaqiruvini ham boshqaradi
# ===========================================================================
def test_vision_gate():
    print("\n== TEST 9b: Vision (gateway) — gate va byudjet ==")
    reset_state()
    from utils import vision_analyzer as va

    calls = {"n": 0}

    async def fake_analyze(*args, **kwargs):
        calls["n"] += 1
        return {"description": "mahsulot", "model": "gemini-vision-x"}

    real = va.analyze_image
    va.analyze_image = fake_analyze
    gate = admission.default_user_gate()
    try:
        for _ in range(gate.max_per_user):
            gate.try_acquire(61)
        blocked = run(gw.ai_gateway.vision_analyze(b"x", caption="c", user_id=61))
        check("vision: gate to'lgan → provayder chaqirilmadi", calls["n"] == 0)
        check("vision: rad etildi (ok=False, user_busy)",
              (not blocked.ok) and blocked.failure_kind == "user_busy", str(blocked.failure_kind))
        for _ in range(gate.max_per_user):
            gate.release(61)

        allowed = run(gw.ai_gateway.vision_analyze(b"x", caption="c", user_id=61))
        check("vision: limit ichida → chaqirildi va ok", calls["n"] == 1 and allowed.ok)
        check("vision: model telemetriyada", allowed.model == "gemini-vision-x", allowed.model)
        check("vision: slot bo'shatildi", gate.active(61) == 0)
        check("vision: byudjet bron bo'shatildi", budget.default_guard().inflight(61).tokens == 0)
    finally:
        va.analyze_image = real


# ===========================================================================
# TEST 10 — DB HISOBOT: cache hit unpriced hisoblanmaydi, by_action bor
# ===========================================================================
def test_db_report_sql():
    print("\n== TEST 10: DB hisobot SQL — cache unpriced emas, by_action ==")
    src = (ROOT / "repositories" / "audit_repository.py").read_text(encoding="utf-8")
    check("unpriced: keshlanganlar sanalmaydi (NOT priced AND NOT cached)",
          "AND NOT priced AND NOT cached" in src)
    check("eski (NOT priced OR cached) predikati olib tashlangan",
          "(NOT priced OR cached)" not in src)
    check("by_action guruhlash (post/vision/voice/audit) bor",
          "by_action" in src and "'vision'" in src and "'audit'" in src and "'voice'" in src)


# ===========================================================================
# TEST 11 — KONTEKST: gateway usage_scope va main.py ulanishi
# ===========================================================================
def test_scope_wiring():
    print("\n== TEST 11: Kontekst ulanishi (main.py, gateway, fallback) ==")
    main_src = (ROOT / "main.py").read_text(encoding="utf-8")
    check("main.py: update darajasida usage_scope(user_id=...)",
          "with usage_scope(user_id=scope_uid)" in main_src)
    gw_src = (ROOT / "services" / "ai" / "engine" / "gateway.py").read_text(encoding="utf-8")
    check("gateway: byudjet + gate ulangan", "default_guard().acquire" in gw_src
          and "default_user_gate()" in gw_src)
    check("gateway: cache kaliti channel_context + model_version bilan",
          "channel_context=channel_context, model_version=model_version()" in gw_src)
    app_src = (ROOT / "services" / "ai" / "engine" / "app_service.py").read_text(encoding="utf-8")
    check("app_service: ledger faqat qurilgan yozuvga (ikki marta yo'q)",
          app_src.count("record_usage_event(") == 1)


def main() -> int:
    print("=" * 70)
    print(" STEP 1 — AI XARAJAT HIMOYASI (telemetriya, konkurentlik, byudjet)")
    print("=" * 70)
    tests = [
        test_pricing_status,
        test_single_price_table,
        test_cache_key_strict,
        test_user_job_gate,
        test_budget_guard,
        test_fallback_telemetry_and_gates,
        test_legacy_dedupe,
        test_cheap_routing_and_action_type,
        test_economics_margin,
        test_vision_gate,
        test_db_report_sql,
        test_scope_wiring,
    ]
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            global failures
            failures += 1
            import traceback

            print(f"  [FAIL] {test.__name__} istisno: {exc}")
            traceback.print_exc()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] STEP 1 TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" STEP 1 — AI XARAJAT HIMOYASI 100% YASHIL ✔")
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
