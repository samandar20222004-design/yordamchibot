#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🌐 UMUMIY KUNLIK AI BYUDJETI (AI_GLOBAL_DAILY_USD) — BudgetGuard + atomik do'kon.

Ikki rejim: soxta xotira do'koni (har doim) va haqiqiy PostgreSQL (``AI_BUDGET_TEST_DATABASE_URL``
berilsa; aks holda jonli qism [SKIP], o'tgan deb sanalmaydi).

Qamrov: parallel bron (bir process va ikki "instance"), chegara yoqilgan/o'chirilgan,
DB xatosi/timeout (fail-closed), cache hit, unpriced muvaffaqiyat (assumed), provayder xatosi,
timeout (noma'lum sarf), fallback, restart, TTL va kechikkan yakunlash, idempotent release.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/ai_global_budget_test.py
"""
import asyncio
import os
import sys
import threading
import types
import warnings
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:GLOBAL_BUDGET_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = failures = skipped = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


import database as db_mod  # noqa: E402
from services.ai import admission, budget, cost_tracker, fallback, usage_store  # noqa: E402
from services.ai.engine import gateway as gw  # noqa: E402
from services.ai.engine import providers as eng_providers  # noqa: E402
from services.ai.engine import telemetry  # noqa: E402
from services.ai.engine.cache import reset_cache  # noqa: E402
from services.ai.usage_scope import note_model, usage_scope  # noqa: E402


@contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = str(v)
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


ROOMY = dict(AI_BUDGET_FREE_DAILY_USD="100", AI_BUDGET_FREE_DAILY_TOKENS="0",
             AI_BUDGET_FREE_MONTHLY_USD="0", AI_BUDGET_FREE_MONTHLY_TOKENS="0",
             AI_BUDGET_PRO_DAILY_USD="100", AI_BUDGET_PRO_DAILY_TOKENS="0",
             AI_BUDGET_PRO_MONTHLY_USD="0", AI_BUDGET_PRO_MONTHLY_TOKENS="0")


def run(coro):
    return asyncio.run(coro)


class FakeStore:
    """DB semantikasini xotirada taqlid qiladi (atomiklik: threading.Lock)."""

    def __init__(self, fail=None, base=0.0):
        self.fail = fail                   # None | Exception | "timeout"
        self.lock = threading.Lock()
        self.t = {}                        # ticket -> dict(est, state)
        self.spent = self.assumed = self.unknown = 0.0
        self.base = base
        self.calls = {"reserve": 0, "settle": 0, "release": 0, "mark_unknown": 0}

    def available(self):
        return True

    def _maybe_fail(self):
        if self.fail == "timeout":
            raise asyncio.TimeoutError()
        if self.fail is not None:
            raise self.fail

    def open_usd(self):
        return sum(v["est"] for v in self.t.values() if v["state"] == "reserved")

    def used(self):
        return self.base + self.spent + self.assumed + self.unknown + self.open_usd()

    async def reserve(self, tid, uid, est, cap, ttl):
        self.calls["reserve"] += 1
        self._maybe_fail()
        with self.lock:
            if tid in self.t:
                return {"granted": self.t[tid]["state"] == "reserved", "reason": "ok", "used": 0}
            if round(self.used() + est, 6) > round(cap, 6):
                return {"granted": False, "reason": "global_daily_usd", "used": self.used()}
            self.t[tid] = {"est": est, "state": "reserved"}
            return {"granted": True, "reason": "ok", "used": self.used()}

    async def settle(self, tid, actual, assumed):
        self.calls["settle"] += 1
        self._maybe_fail()
        with self.lock:
            e = self.t.get(tid)
            if not e or e["state"] not in ("reserved", "expired"):
                return "noop"
            if e["state"] == "expired":
                self.unknown -= e["est"]
            e["state"] = "settled"
            self.spent += actual
            self.assumed += assumed
            return "settled"

    async def release(self, tid):
        self.calls["release"] += 1
        self._maybe_fail()
        with self.lock:
            e = self.t.get(tid)
            if e is None:
                self.t[tid] = {"est": 0.0, "state": "released"}
                return "tombstone"
            if e["state"] == "reserved":
                e["state"] = "released"
                return "released"
            if e["state"] == "expired":
                self.unknown -= e["est"]
                e["state"] = "released"
                return "released"
            return "noop"

    async def mark_unknown(self, tid):
        self.calls["mark_unknown"] += 1
        self._maybe_fail()
        with self.lock:
            e = self.t.get(tid)
            if not e or e["state"] not in ("reserved", "expired"):
                return "noop"
            if e["state"] == "reserved":
                self.unknown += e["est"]
            e["state"] = "unknown"
            return "unknown"

    def expire(self, tid):
        with self.lock:
            e = self.t[tid]
            if e["state"] == "reserved":
                e["state"] = "expired"
                self.unknown += e["est"]

    def snapshot(self):
        return {"spent": round(self.spent, 6), "assumed": round(self.assumed, 6),
                "unknown": round(self.unknown, 6), "open": round(self.open_usd(), 6)}


class LiveStore(budget.GlobalBudgetStore):
    """Haqiqiy DB; ``snapshot`` kunlik hisobdan DELTA beradi."""

    def __init__(self):
        self.t0 = db_mod.get_ai_budget_status()

    def snapshot(self):
        now = db_mod.get_ai_budget_status()
        return {"spent": round(now["spent_usd"] - self.t0["spent_usd"], 6),
                "assumed": round(now["assumed_usd"] - self.t0["assumed_usd"], 6),
                "unknown": round(now["unknown_usd"] - self.t0["unknown_usd"], 6),
                "open": round(now["open_usd"] - self.t0["open_usd"], 6)}

    def used_delta(self):
        return round(db_mod.get_ai_budget_status()["used_usd"] - self.t0["used_usd"], 6)


def fresh_guard(tier_pro_users=()):
    cost_tracker._ledger = cost_tracker.CostLedger()
    telemetry.reset_default_recorder()
    budget.set_tier_resolver(lambda uid: uid in tier_pro_users)
    guard = budget.BudgetGuard()
    budget._guard = guard
    admission.default_user_gate()._active.clear()
    return guard


def mk_cap(store, room):
    """Hozirgi 'used' ustiga ``room`` USD joy qoldiradigan chegara."""
    cur = store.used() if isinstance(store, FakeStore) else store.used_delta()
    base = store.base if isinstance(store, FakeStore) else db_mod.get_ai_budget_status()["used_usd"] - cur
    return round(base + cur + room, 6)


def scenarios(label, make_store):
    print(f"\n######## {label} ########")
    EST = 0.01

    # ---- 1) Chegara o'chirilgan (0): do'konga umuman tegilmaydi ----
    store = make_store()
    budget.set_global_store(store)
    guard = fresh_guard()
    with env(AI_GLOBAL_DAILY_USD=None, **ROOMY):
        d = run(guard.acquire(1, "free", 10, EST))
        check(f"[{label}] AI_GLOBAL_DAILY_USD=0: bron ruxsat, global bron olinmaydi",
              d.allowed and d.ticket.global_reserved is False)
        if isinstance(store, FakeStore):
            check(f"[{label}] o'chirilgan: do'kon chaqirilmadi", sum(store.calls.values()) == 0, str(store.calls))
        guard.release(d.ticket)
    with env(AI_GLOBAL_DAILY_USD="abc", **ROOMY):
        check(f"[{label}] noto'g'ri qiymat → cheklov yo'q", budget.global_daily_usd_cap() == 0.0)

    # ---- 2) Parallel bron (bir process): FREE+PRO aralash, aniq 10 ta ----
    store = make_store()
    budget.set_global_store(store)
    guard = fresh_guard(tier_pro_users={i for i in range(1, 100, 2)})
    with env(AI_GLOBAL_DAILY_USD="1", **ROOMY):
        cap = mk_cap(store, 10 * EST)

        async def burst():
            return await asyncio.gather(*[
                guard.acquire(i + 1, "pro" if (i + 1) % 2 else "free", 10, EST) for i in range(40)])
        os.environ["AI_GLOBAL_DAILY_USD"] = str(cap)
        decs = run(burst())
        ok = [d for d in decs if d.allowed]
        check(f"[{label}] 40 parallel so'rov (FREE+PRO), joy 10 ta → aynan 10 ta o'tdi",
              len(ok) == 10, f"{len(ok)}")
        check(f"[{label}] rad sababi global_daily_usd va period=global",
              {d.reason for d in decs if not d.allowed} == {"global_daily_usd"}
              and all(d.period == budget.PERIOD_GLOBAL for d in decs if not d.allowed))
        check(f"[{label}] o'tganlar global bron oldi", all(d.ticket.global_reserved for d in ok))
        check(f"[{label}] rad etilgan so'rovlarda foydalanuvchi broni qolmadi",
              guard.status()["open_tickets"] == 10 and guard.status()["global_denied"] == 30,
              str(guard.status()))

        # chegaraga yetgach: yangi rad, lekin oldindan bron qilinganlar yakunlanadi
        extra = run(guard.acquire(999, "pro", 10, EST))
        check(f"[{label}] chegaraga yetganda PRO ham rad etiladi", not extra.allowed and extra.reason == "global_daily_usd")
        hint = {"ok": True, "cached": False, "unpriced": False, "estimated_cost": 0.004,
                "input_tokens": 100, "output_tokens": 100, "attempts": 1, "failure_kind": ""}
        res = run(guard.finalize(ok[0].ticket, hint))
        check(f"[{label}] oldindan bron qilingan so'rov yakunlanadi (settle)", res == "settled", res)
        check(f"[{label}] yakunlash idempotent (ikkinchi marta 'done')",
              run(guard.finalize(ok[0].ticket, hint)) == "done")
        snap = store.snapshot()
        check(f"[{label}] haqiqiy sarf yozildi, bron (0.01) o'rniga",
              abs(snap["spent"] - 0.004) < 1e-6 and abs(snap["open"] - 9 * EST) < 1e-6, str(snap))
        again = run(guard.acquire(1000, "free", 10, 0.005))
        check(f"[{label}] yakunlash joy ochdi: kichik so'rov o'tadi", again.allowed, again.reason)
        for d in ok[1:] + ([again] if again.allowed else []):
            guard.release(d.ticket)
        run(asyncio.sleep(0))

    # ---- 3) Ikki "instance" (ikki BudgetGuard) bitta do'kon ----
    store = make_store()
    budget.set_global_store(store)
    g1, g2 = budget.BudgetGuard(), budget.BudgetGuard()
    cost_tracker._ledger = cost_tracker.CostLedger()
    budget.set_tier_resolver(lambda uid: False)
    with env(AI_GLOBAL_DAILY_USD="1", **ROOMY):
        cap = mk_cap(store, 10 * EST)
        os.environ["AI_GLOBAL_DAILY_USD"] = str(cap)

        async def two_instances():
            jobs = [g1.acquire(i, "free", 10, EST) for i in range(1, 21)]
            jobs += [g2.acquire(i, "free", 10, EST) for i in range(101, 121)]
            return await asyncio.gather(*jobs)
        decs = run(two_instances())
        check(f"[{label}] ikki instance: umumiy bron aynan 10 ta (xotira umumiy emas, DB umumiy)",
              sum(1 for d in decs if d.allowed) == 10, str(sum(1 for d in decs if d.allowed)))
        for d in decs:
            if d.allowed:
                (g1 if d.ticket.user_id < 100 else g2).release(d.ticket)
        run(asyncio.sleep(0))

    # ---- 4) DB xatosi / timeout: fail-closed ----
    for kind, fail in (("xato", RuntimeError("db down")), ("timeout", "timeout")):
        store = FakeStore(fail=fail)
        budget.set_global_store(store)
        guard = fresh_guard()
        with env(AI_GLOBAL_DAILY_USD="1", **ROOMY):
            d = run(guard.acquire(7, "pro", 10, EST))
            check(f"[{label}] DB {kind}: pullik so'rov rad etildi (fail-closed)",
                  (not d.allowed) and d.reason == "global_unavailable" and d.period == budget.PERIOD_GLOBAL, d.reason)
            check(f"[{label}] DB {kind}: foydalanuvchi broni qaytarildi",
                  guard.status()["open_tickets"] == 0 and guard.inflight(7).tokens == 0)
            check(f"[{label}] DB {kind}: global_unavailable hisoblandi", guard.status()["global_unavailable"] == 1)
            check(f"[{label}] DB {kind}: qabr belgisi uchun release urinildi", store.calls["release"] == 1)
        with env(AI_GLOBAL_DAILY_USD=None, **ROOMY):
            ok = run(guard.acquire(7, "pro", 10, EST))
            check(f"[{label}] DB {kind} + chegara o'chirilgan: AI bloklanmaydi", ok.allowed)
            guard.release(ok.ticket)
    msgs = {lang: budget.budget_message(lang, budget.PERIOD_GLOBAL) for lang in ("uz", "ru", "en")}
    check(f"[{label}] umumiy limit xabari uz/ru/en", len(set(msgs.values())) == 3 and all("PRO" not in m for m in msgs.values()))


def lifecycle_scenarios(label, make_store):
    print(f"\n######## {label}: yakunlash holatlari (gateway/fallback oqimi) ########")
    EST_CAP = "50"

    class FakeP(fallback.AIProvider):
        key_attr = None
        tier = 1

        def __init__(self, name="FakeP", mode="ok"):
            self.name, self.mode, self.calls = name, mode, 0

        def is_available(self):
            return True

        async def complete(self, prompt, system_instruction, params, deadline=None):
            self.calls += 1
            if self.mode == "fail":
                # Provayder HTTP xatosi (so'rov rad etilgan, javob yo'q) — aniq nol xarajat.
                # (Tasniflanmagan umumiy istisno endi NOMA'LUM: tests/ai_chain_cost_unknown_test.py.)
                raise fallback.AIProviderError(503, "provider down", self.name)
            note_model("fake-model-1")        # narxi noma'lum
            return {"post_text": "Kofe haqida qisqa va aniq post matni. " * 3}

    def flow(providers, uid):
        svc = fallback.AIFallbackService(providers=providers)

        async def go():
            with usage_scope(user_id=uid, action_type="post"):
                out = await svc.generate("Kofe haqida post", "tizim", lang="uz")
            await asyncio.sleep(0)
            await usage_store.drain(1.0)
            return out
        return run(go())

    # a) unpriced muvaffaqiyat → settle: haqiqiy 0, assumed > 0 (alohida)
    store = make_store()
    budget.set_global_store(store)
    fresh_guard()
    with env(AI_GLOBAL_DAILY_USD=EST_CAP, **ROOMY):
        flow([FakeP()], 11)
        snap = store.snapshot()
        check(f"[{label}] unpriced success: spent=0 (soxta narx yo'q), assumed>0 alohida, bron yopildi",
              snap["spent"] == 0.0 and snap["assumed"] > 0 and snap["open"] == 0.0, str(snap))
        ev = [e for e in telemetry.default_recorder().events() if e.user_id == 11][0]
        check(f"[{label}] assumed = mos yozuv narxi × hodisa tokenlari",
              abs(snap["assumed"] - cost_tracker.assumed_cost_usd(ev.input_tokens, ev.output_tokens)) < 1e-6)

        # b) provayder xatosi (barcha provayderlar) → bron QAYTARILADI, hisob o'zgarmaydi
        before = store.snapshot()
        flow([FakeP("FailP", "fail")], 12)
        after = store.snapshot()
        check(f"[{label}] provayder xatosi: bron qaytarildi, sarf/noma'lum o'zgarmadi",
              after["open"] == before["open"] and after["spent"] == before["spent"]
              and after["unknown"] == before["unknown"] and after["assumed"] == before["assumed"], str((before, after)))

        # c) fallback: birinchi provayder xato, ikkinchisi muvaffaqiyat → bitta yakuniy hisob
        before = store.snapshot()
        flow([FakeP("FailP", "fail"), FakeP("FakeP", "ok")], 13)
        after = store.snapshot()
        check(f"[{label}] fallback: faqat yakuniy muvaffaqiyat hisoblandi (bitta assumed)",
              after["assumed"] > before["assumed"] and after["open"] == before["open"], str((before, after)))

    # d) gateway timeout → NOMA'LUM sarf (bron hisobda qoladi, qaytarilmaydi)
    store = make_store()
    budget.set_global_store(store)
    fresh_guard()
    reset_cache()

    async def slow_exec(handle, prompt, instruction, *, lang=None, timeout=10.0):
        await asyncio.sleep(30)

    real = (eng_providers.build_provider_handles, eng_providers.execute_provider)
    eng_providers.build_provider_handles = lambda: {"Gemini": eng_providers.ProviderHandle(
        name="Gemini", provider=types.SimpleNamespace(name="Gemini", is_available=lambda: True, complete=None))}
    eng_providers.execute_provider = slow_exec
    try:
        with env(AI_GLOBAL_DAILY_USD=EST_CAP, **ROOMY):
            res = run(gw.ai_gateway.generate(prompt="timeout test", task="social_post", user_id=14,
                                             lane="fast", use_cache=False, timeout=1.0))
            snap = store.snapshot()
            check(f"[{label}] timeout: natija xato (failure_kind=timeout)",
                  (not res.ok) and res.failure_kind == "timeout", str(res.failure_kind))
            check(f"[{label}] timeout: bron QAYTARILMADI — noma'lum sarf sifatida hisobda qoldi",
                  snap["unknown"] > 0 and snap["open"] == 0.0 and snap["spent"] == 0.0, str(snap))
    finally:
        eng_providers.build_provider_handles, eng_providers.execute_provider = real

    # e) cache hit → global bron olinmaydi (cap yoqilgan, do'kon ishlamasa ham)
    reset_cache()

    async def good_exec(handle, prompt, instruction, *, lang=None, timeout=10.0):
        return {"text": "Kofe do'koni uchun qisqa va foydali post matni. " * 3, "model": "gemini-2.5-flash"}

    eng_providers.build_provider_handles = lambda: {"Gemini": eng_providers.ProviderHandle(
        name="Gemini", provider=types.SimpleNamespace(name="Gemini", is_available=lambda: True, complete=None))}
    eng_providers.execute_provider = good_exec
    store = make_store()
    budget.set_global_store(store)
    fresh_guard()
    try:
        with env(AI_GLOBAL_DAILY_USD=EST_CAP, **ROOMY):
            first = run(gw.ai_gateway.generate(prompt="bir xil so'rov", task="social_post", user_id=15, lane="fast"))
            calls_after_first = dict(store.calls) if isinstance(store, FakeStore) else None
            if isinstance(store, FakeStore):
                store.fail = RuntimeError("db down")      # DB yo'q bo'lsa ham kesh javobi beriladi
            second = run(gw.ai_gateway.generate(prompt="bir xil so'rov", task="social_post", user_id=15, lane="fast"))
            check(f"[{label}] kesh hiti global bron talab qilmaydi (DB xatosida ham bloklanmaydi)",
                  first.ok and second.cached and second.ok, f"{second.provider}/{second.error}")
            if isinstance(store, FakeStore):
                check(f"[{label}] kesh hiti do'konga murojaat qilmadi",
                      store.calls["reserve"] == calls_after_first["reserve"], str(store.calls))
    finally:
        eng_providers.build_provider_handles, eng_providers.execute_provider = real


def ttl_scenarios_fake():
    print("\n######## FAKE: TTL eskirishi, kechikkan yakunlash, release idempotentligi ########")
    store = FakeStore()
    budget.set_global_store(store)
    guard = fresh_guard()
    with env(AI_GLOBAL_DAILY_USD="1", **ROOMY):
        d = run(guard.acquire(21, "free", 10, 0.05))
        store.expire(d.ticket.ticket_id)
        check("eskirgan bron hisobdan TUSHMADI (unknown sifatida qoldi)",
              abs(store.snapshot()["unknown"] - 0.05) < 1e-9 and store.snapshot()["open"] == 0.0)
        hint = {"ok": True, "cached": False, "unpriced": False, "estimated_cost": 0.01,
                "input_tokens": 1, "output_tokens": 1, "attempts": 1, "failure_kind": ""}
        run(guard.finalize(d.ticket, hint))
        s = store.snapshot()
        check("kechikkan yakunlash: noma'lum bron haqiqiy sarfga almashtirildi",
              s["unknown"] == 0.0 and abs(s["spent"] - 0.01) < 1e-9, str(s))
        guard.release(d.ticket)
        guard.release(d.ticket)
        check("takroriy release foydalanuvchi bronini ikki marta qaytarmaydi", guard.inflight(21).tokens == 0)
    # release safety-net: finalize chaqirilmasdan release → fonda 'unknown'
    store = FakeStore()
    budget.set_global_store(store)
    guard = fresh_guard()
    with env(AI_GLOBAL_DAILY_USD="1", **ROOMY):
        async def forgot():
            d = await guard.acquire(22, "free", 10, 0.02)
            guard.release(d.ticket)            # finalize chaqirilmagan (kutilmagan chiqish)
            await asyncio.sleep(0.05)
            return d
        d = run(forgot())
        check("finalize'siz release: bron fonda 'noma'lum' deb yakunlandi (hisobda qoldi)",
              store.calls["mark_unknown"] == 1 and abs(store.snapshot()["unknown"] - 0.02) < 1e-9, str(store.calls))
    # classify_settlement jadvali
    cs = budget.classify_settlement
    check("classify: ma'lumot yo'q → unknown", cs(None)[0] == "unknown")
    check("classify: timeout → unknown", cs({"ok": False, "failure_kind": "timeout"})[0] == "unknown")
    check("classify: boshqa/noma'lum xato → unknown", cs({"ok": False, "failure_kind": "other"})[0] == "unknown")
    check("classify: 429/5xx/tarmoq → release",
          all(cs({"ok": False, "failure_kind": k})[0] == "release" for k in ("rate_limit", "server_error", "network")))
    check("classify: unpriced success → settle, assumed > 0, actual = 0",
          (lambda r: r[0] == "settle" and r[1] == 0.0 and r[2] > 0)(
              cs({"ok": True, "unpriced": True, "estimated_cost": 0.0, "input_tokens": 500, "output_tokens": 500})))
    check("classify: narxli success → settle, assumed = 0",
          (lambda r: r[0] == "settle" and r[1] == 0.004 and r[2] == 0.0)(
              cs({"ok": True, "unpriced": False, "estimated_cost": 0.004})))


scenarios("FAKE", FakeStore)
lifecycle_scenarios("FAKE", FakeStore)
ttl_scenarios_fake()

live_url = os.environ.get("AI_BUDGET_TEST_DATABASE_URL", "").strip()
if not live_url:
    skipped += 1
    print("\n  [SKIP] AI_BUDGET_TEST_DATABASE_URL berilmagan — jonli PostgreSQL qismi o'tkazildi")
else:
    db_mod.DATABASE_URL = live_url
    db_mod._reset_pool()
    db_mod.init_db()
    # DIQQAT: AI_BUDGET_TEST_DATABASE_URL FAQAT sinov bazasiga ishora qilishi kerak —
    # bugungi byudjet jadvallari tozalanadi (oldingi sinovlar qoldiqlari delta'ni buzmasin).
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM ai_budget_reservations")
        cur.execute("DELETE FROM ai_budget_days")
    scenarios("LIVE-PG", LiveStore)

    # LiveStore snapshot'i 'open' yo'qligi uchun lifecycle faqat unpriced/xato/timeout/kesh'ni tekshiradi
    def make_live():
        return LiveStore()
    lifecycle_scenarios("LIVE-PG", make_live)

    print("\n######## LIVE-PG: restart, DB timeout kompensatsiyasi, DB uzilishi ########")
    store = LiveStore()
    budget.set_global_store(store)
    guard = fresh_guard()
    with env(AI_GLOBAL_DAILY_USD="1000", **ROOMY):
        d = run(guard.acquire(31, "free", 10, 0.02))
        before = store.used_delta()
        db_mod.close_pool()
        db_mod._reset_pool()           # restart: yangi pool, xotira yo'q
        guard2 = budget.BudgetGuard()
        budget._guard = guard2
        check("restartdan keyin hisob DB'dan tiklandi (bron saqlanib qoldi)", abs(store.used_delta() - before) < 1e-9)
        check("restart: eski jarayon bronini yangi guard yakunlay olmaydi ('done'), bron DB'da qoladi",
              run(guard2.finalize(d.ticket)) == "done" and abs(store.snapshot()["open"] - 0.02) < 1e-9,
              str(store.snapshot()))
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("UPDATE ai_budget_reservations SET expires_at = NOW() - interval '1 second' "
                        "WHERE ticket_id = %s", (d.ticket.ticket_id,))
        run(guard2.acquire(34, "free", 10, 0.001))        # keyingi bron eskirganlarni supuradi
        snap = store.snapshot()
        check("TTL dan keyin yakunlanmagan bron hisobdan TUSHMADI: open → unknown",
              abs(snap["unknown"] - 0.02) < 1e-9 and abs(snap["open"] - 0.001) < 1e-9, str(snap))

    # timeout kompensatsiyasi: reserve fonda sekin, wait_for timeout, qabr belgisi — bron sizib qolmaydi
    store = LiveStore()
    budget.set_global_store(store)
    guard = fresh_guard()
    real_reserve = db_mod.reserve_ai_budget
    import time as _time

    def slow_reserve(*a, **k):
        _time.sleep(0.6)
        return real_reserve(*a, **k)

    db_mod.reserve_ai_budget = slow_reserve
    old_to = budget.GLOBAL_DB_TIMEOUT
    budget.GLOBAL_DB_TIMEOUT = 0.15
    try:
        with env(AI_GLOBAL_DAILY_USD="1000", **ROOMY):
            d = run(guard.acquire(32, "free", 10, 0.03))
            _time.sleep(1.2)           # fon tranzaksiyasi tugashini kutamiz
    finally:
        db_mod.reserve_ai_budget = real_reserve
        budget.GLOBAL_DB_TIMEOUT = old_to
    check("DB timeout: so'rov rad etildi (global_unavailable)", (not d.allowed) and d.reason == "global_unavailable", d.reason)
    check("DB timeout: kech yetib kelgan bron SIZIB QOLMADI (qabr belgisi)", abs(store.snapshot()["open"]) < 1e-9,
          str(store.snapshot()))

    # DB uzilishi (pool yo'q) → fail-closed
    store = budget.GlobalBudgetStore()
    budget.set_global_store(store)
    guard = fresh_guard()
    saved_pool = db_mod._pool
    db_mod._pool = None
    try:
        with env(AI_GLOBAL_DAILY_USD="1000", **ROOMY):
            d = run(guard.acquire(33, "pro", 10, 0.01))
    finally:
        db_mod._pool = saved_pool
    check("DB pool yo'q: yangi pullik so'rov rad etildi", (not d.allowed) and d.reason == "global_unavailable")
    db_mod.close_pool()

budget.set_global_store(None)
print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}  [SKIP]={skipped}")
sys.exit(1 if failures else 0)
