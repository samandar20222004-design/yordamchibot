#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💲 NOMA'LUM NARXLI AI SO'ROVLARI VA BUDJET (``assumed_usd``).

Muammo: narxi noma'lum (``priced=False``) muvaffaqiyatli so'rov ledger'ga
``cost_usd = 0`` bilan tushardi va USD limitlari (kunlik/oylik) uni umuman
ko'rmasdi — faqat token limiti to'xtatardi.

Tuzatish: bunday so'rovlar uchun FAQAT budjet maqsadida alohida
``assumed_cost_usd`` hisoblanadi (mos yozuv narxi × tokenlar). U
``estimated_cost`` / ``cost_usd`` / ``priced`` ga qo'shilmaydi.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/ai_unpriced_budget_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:UNPRICED_BUDGET_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


import database as db_mod  # noqa: E402
from services.ai import admission, budget, cost_tracker, fallback  # noqa: E402
from services.ai.engine import gateway as gw  # noqa: E402
from services.ai.engine import telemetry  # noqa: E402
from services.ai.usage_scope import note_model, usage_scope  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeProvider(fallback.AIProvider):
    """Offline provayder (model 'fake-model-1' narx jadvalida YO'Q → unpriced)."""

    key_attr = None
    tier = 1

    def __init__(self, name="FakeP", mode="ok"):
        self.name, self.mode, self.calls = name, mode, 0

    def is_available(self):
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        self.calls += 1
        if self.mode == "fail":
            raise RuntimeError("provider down")
        if self.mode == "slow":
            await asyncio.sleep(30)
        note_model("fake-model-1")
        return {"post_text": "Kofe haqida qisqa va aniq post matni. " * 3}


def reset_state():
    telemetry.reset_default_recorder()
    cost_tracker._ledger = cost_tracker.CostLedger()
    budget.set_tier_resolver(lambda uid: False)   # hammasi FREE
    budget._guard.__init__()
    admission.default_user_gate()._active.clear()


def ledger():
    return cost_tracker.default_ledger()


def simulate(provider, model, user_id, n=60):
    """acquire → (soxta provayder) → ledger → release; nechta o'tdi va nega to'xtadi."""
    guard = budget.BudgetGuard()
    allowed, reason = 0, None

    async def go():
        nonlocal allowed, reason
        for _ in range(n):
            d = await guard.acquire(user_id, "free", *budget.estimate_request("p" * 4000, ""))
            if not d.allowed:
                reason = d.reason
                return
            ledger().record(user_id=user_id, provider=provider, model=model,
                            input_tokens=1200, output_tokens=300)
            guard.release(d.ticket)
            allowed += 1
    run(go())
    return allowed, reason


print("\n== 1) Oldingi simulyatsiya: noma'lum narx USD limitiga kiradi ==")
reset_state()
n_priced, r_priced = simulate("Gemini", "gemini-2.5-flash", 9002)
reset_state()
n_unpriced, r_unpriced = simulate("Mystery", "zeta-9000", 9001)
check("narxli model: kunlik USD bilan to'xtaydi", r_priced == "daily_usd", str(r_priced))
check("noma'lum narx: endi ham kunlik USD bilan to'xtaydi (token bilan emas)",
      r_unpriced == "daily_usd", f"{r_unpriced} / allowed={n_unpriced}")
check("noma'lum narx narxli model bilan bir xil sondagi so'rovdan keyin to'xtaydi",
      n_unpriced == n_priced, f"{n_unpriced} != {n_priced}")

print("\n== 2) Haqiqiy $0 narx ≠ noma'lum narx ==")
reset_state()
n_zero, r_zero = simulate("Cerebras", "llama3.1-8b", 9003)   # provayder darajasidagi 0.0 e'lon
d = ledger().user_costs(9003)
check("0.0 narxli model priced hisoblanadi (unpriced emas)",
      d["priced_requests"] == n_zero and d["unpriced_requests"] == 0, str(d))
check("0.0 narxli model: assumed_cost_usd = 0", d["assumed_cost_usd"] == 0.0, str(d))
check("0.0 narxli model USD limitiga tegmaydi (token limiti bilan to'xtaydi)",
      r_zero == "daily_tokens", str(r_zero))
reset_state()
simulate("Mystery", "zeta-9000", 9004, n=3)
d = ledger().user_costs(9004)
check("noma'lum narx: unpriced hisoblagichi, priced emas",
      d["unpriced_requests"] == 3 and d["priced_requests"] == 0, str(d))
check("noma'lum narx: assumed_cost_usd > 0", d["assumed_cost_usd"] > 0, str(d))

print("\n== 3) estimated_cost / cost_usd / priced sun'iy oshmaydi ==")
check("noma'lum narx: cost_usd (haqiqiy) = 0.0 — taxmin unga qo'shilmagan",
      d["cost_usd"] == 0.0 and d["cost_uzs"] == 0.0, str(d))
check("jarayon yig'indisi (totals): cost_usd = 0.0, assumed alohida",
      ledger().totals()["cost_usd"] == 0.0 and ledger().totals()["assumed_cost_usd"] > 0)
check("oylik hisobot ham ajratilgan",
      ledger().user_costs(9004, period="monthly")["cost_usd"] == 0.0
      and ledger().user_costs(9004, period="monthly")["assumed_cost_usd"] > 0)
reset_state()
provider = FakeProvider()
svc = fallback.AIFallbackService(providers=[provider])
with usage_scope(user_id=77, action_type="post"):
    res = run(svc.generate("Kofe haqida post", "tizim", lang="uz"))
ev = [e for e in telemetry.default_recorder().events() if e.user_id == 77]
check("fallback: javob keldi", bool(res.get("post_text")))
check("hodisa: estimated_cost = 0.0, priced=False, cost_status=unpriced",
      len(ev) == 1 and ev[0].estimated_cost == 0.0 and ev[0].priced is False
      and ev[0].cost_status == telemetry.COST_UNPRICED, str(ev))
check("hodisa lug'atida 'assumed' narx maydoni YO'Q (telemetriya tozaligi)",
      "assumed_cost_usd" not in ev[0].as_dict())
day = ledger().user_costs(77)
check("ledger: bu so'rov uchun taxmin alohida yozildi, cost_usd = 0",
      day["assumed_cost_usd"] > 0 and day["cost_usd"] == 0.0, str(day))
expected = cost_tracker.assumed_cost_usd(ev[0].input_tokens, ev[0].output_tokens)
check("taxmin = mos yozuv narxi × hodisadagi tokenlar",
      abs(day["assumed_cost_usd"] - expected) < 1e-9, f"{day['assumed_cost_usd']} vs {expected}")

print("\n== 4) Cache, xato, timeout, rad, fallback ==")
reset_state()
for label, result, kw in (
        ("xato", gw.GatewayResult(ok=False, provider="Mystery", model="zeta-9000",
                                  failure_kind="server_error"), {}),
        ("timeout", gw.GatewayResult(ok=False, provider="Mystery", model="zeta-9000",
                                     failure_kind="timeout"), {}),
        ("kesh", gw.GatewayResult(ok=True, text="x" * 200, provider="cache",
                                  model="zeta-9000", cached=True), {"cached": True}),
):
    e = telemetry.build_usage_event(result=result, prompt="p" * 400, user_id=55,
                                    channel_id=-100, **kw)
    cost_tracker.record_usage_event(e.as_dict())
    d = ledger().user_costs(55)
    check(f"{label}: taxminiy sarf qo'shilmadi", d["assumed_cost_usd"] == 0.0, str(d))
check("xato/timeout/kesh unpriced deb sanalmadi", ledger().user_costs(55)["unpriced_requests"] == 0)

reset_state()
failing, ok_provider = FakeProvider("FailP", "fail"), FakeProvider("FakeP", "ok")
svc = fallback.AIFallbackService(providers=[failing, ok_provider])
with usage_scope(user_id=56, action_type="post"):
    res = run(svc.generate("Kofe haqida post", "tizim", lang="uz"))
d = ledger().user_costs(56)
single = cost_tracker.assumed_cost_usd(
    *[(e.input_tokens, e.output_tokens) for e in telemetry.default_recorder().events()
      if e.user_id == 56][0])
check("fallback: muvaffaqiyatsiz urinish hisoblanmaydi, faqat yakuniy natija (hujjatlashtirilgan cheklov)",
      failing.calls >= 1 and d["requests"] == 1 and abs(d["assumed_cost_usd"] - single) < 1e-9, str(d))

reset_state()
rej_provider = FakeProvider()
svc = fallback.AIFallbackService(providers=[rej_provider])
old = os.environ.get("AI_BUDGET_FREE_DAILY_USD")
os.environ["AI_BUDGET_FREE_DAILY_USD"] = "0.0000001"
try:
    with usage_scope(user_id=57):
        run(svc.generate("x", "tizim", lang="uz"))
finally:
    if old is None:
        os.environ.pop("AI_BUDGET_FREE_DAILY_USD", None)
    else:
        os.environ["AI_BUDGET_FREE_DAILY_USD"] = old
check("rad etilgan so'rov: provayder chaqirilmadi, taxmin qo'shilmadi",
      rej_provider.calls == 0 and ledger().user_costs(57)["assumed_cost_usd"] == 0.0)

print("\n== 5) Parallel rezervatsiyalar limitni oshirmaydi ==")
reset_state()
guard = budget.BudgetGuard()
ledger().record(user_id=88, provider="Mystery", model="zeta-9000",
                input_tokens=12000, output_tokens=3000)    # taxmin: ≈0.0111 USD committed
est_tokens, est_usd = budget.estimate_request("p" * 400, "")
cap = budget.tier_budget("free").daily_usd
committed = ledger().user_costs(88)["assumed_cost_usd"]


async def burst():
    return await asyncio.gather(*[guard.acquire(88, "free", est_tokens, est_usd) for _ in range(40)])


decisions = run(burst())
granted = [d for d in decisions if d.allowed]
check("parallel 40 so'rov: ba'zilari o'tdi, ba'zilari rad etildi", 0 < len(granted) < 40, str(len(granted)))
check("parallel: committed(taxmin) + bronlar kunlik USD limitidan oshmadi",
      committed + len(granted) * est_usd <= cap + 1e-9,
      f"{committed + len(granted) * est_usd} > {cap}")
check("parallel: rad sababi daily_usd",
      {d.reason for d in decisions if not d.allowed} == {"daily_usd"})
for d in granted:
    guard.release(d.ticket)
check("bronlar bo'shatildi", guard.inflight(88).usd == 0.0)

print("\n== 6) DB hisobot: taxmin tokenlardan olinadi, haqiqiy sarfga qo'shilmaydi ==")
src = (ROOT / "repositories" / "audit_repository.py").read_text(encoding="utf-8")
check("SQL: noma'lum narxli tokenlar alohida ustunlarda",
      "unpriced_input_tokens" in src and "unpriced_output_tokens" in src
      and "FILTER (WHERE status = 'success' AND NOT priced AND NOT cached)" in src)
check("DB estimated_cost_usd taxmin bilan aralashtirilmagan (SQL SUM(estimated_cost) o'zgarmagan)",
      "COALESCE(SUM(estimated_cost), 0)" in src)

fake_totals = {"total_tokens": 4500, "estimated_cost_usd": 0.0,
               "unpriced_input_tokens": 3600, "unpriced_output_tokens": 900}
orig_ready, orig_report = budget._db_ready, db_mod.get_ai_usage_report
budget._db_ready = lambda: True
db_mod.get_ai_usage_report = lambda **kw: {"totals": dict(fake_totals)}
try:
    usage = budget._db_usage(5, "daily")
    fake_totals.pop("unpriced_input_tokens")
    fake_totals.pop("unpriced_output_tokens")
    legacy = budget._db_usage(5, "daily")
finally:
    budget._db_ready, db_mod.get_ai_usage_report = orig_ready, orig_report
check("DB: taxmin mos yozuv narxi × unpriced tokenlar",
      abs(usage.assumed_usd - cost_tracker.assumed_cost_usd(3600, 900)) < 1e-9 and usage.usd == 0.0,
      str(usage))
check("DB: eski javob (yangi maydonlarsiz) buzilmaydi: assumed = 0",
      legacy.assumed_usd == 0.0 and legacy.tokens == 4500, str(legacy))
both = budget.Usage(100, 0.0, 0.004).max_with(budget.Usage(80, 0.0, 0.006))
check("xotira va DB max() bilan birlashadi (ikki marta sanalmaydi)",
      both.assumed_usd == 0.006 and both.tokens == 100, str(both))

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
