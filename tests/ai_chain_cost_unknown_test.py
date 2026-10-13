#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""🔗 PROVIDER ZANJIRI: oldingi noaniq natija oxirgi 429 bilan "nol xarajat" bo'lib ketmasin.

Muammo (audit P1-1/P1-2): umumiy bron ``failure_kind`` (zanjirdagi OXIRGI xato) bo'yicha
bo'shatilardi. 1-provayder timeout (so'rov qabul qilingan bo'lishi mumkin), oxirgisi 429 →
``rate_limit`` → ``release`` (xarajat hisobdan tushib ketardi). Fallback yo'lida
``all_providers_failed`` har doim nol xarajat deb olinardi.

Tuzatish: har bir urinish natijasi ``budget.note_attempt`` bilan qayd etiladi; aniq nol
xarajat DALILI bo'lmasa (timeout, tarmoq uzilishi, tashlab yuborilgan javob...) bron
``mark_unknown`` ga o'tadi. Faqat barcha urinishlar aniq nolxarajatli bo'lsa ``release``.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/ai_chain_cost_unknown_test.py
"""
import asyncio
import base64
import dataclasses
import os
import sys
import types
import warnings
from contextlib import contextmanager
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:CHAIN_COST_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BETA_INVITE_ONLY", "false")
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


from services.ai import admission, budget, cost_tracker, fallback  # noqa: E402
from services.ai.engine import gateway as gw  # noqa: E402
from services.ai.engine import providers as eng_providers  # noqa: E402
from services.ai.engine import router as eng_router  # noqa: E402
from services.ai.engine import telemetry  # noqa: E402
from services.ai.engine.cache import reset_cache  # noqa: E402
from services.ai.usage_scope import note_model, usage_scope  # noqa: E402
from utils import vision_analyzer as va  # noqa: E402


@contextmanager
def env(**values):
    old = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
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
             AI_GLOBAL_DAILY_USD="50")
GOOD_TEXT = "Kofe do'koni uchun qisqa va foydali post matni. " * 3


class Store(budget.GlobalBudgetStore):
    """Faqat chaqiruvlarni yozadi (do'kon semantikasi alohida testlarda)."""

    def __init__(self, slow_settle=False):
        self.calls, self.slow = [], slow_settle
        self.settled = []

    def available(self):
        return True

    async def reserve(self, *a):
        self.calls.append("reserve")
        return {"granted": True, "used": 0}

    async def settle(self, tid, actual, assumed):
        self.calls.append("settle")
        self.settled.append((actual, assumed))
        if self.slow:
            await asyncio.sleep(5)

    async def release(self, *a):
        self.calls.append("release")

    async def mark_unknown(self, *a):
        self.calls.append("mark_unknown")


def fresh(store):
    cost_tracker._ledger = cost_tracker.CostLedger()
    telemetry.reset_default_recorder()
    budget.set_tier_resolver(lambda uid: False)
    budget.set_global_store(store)
    budget._guard.__init__()
    admission.default_user_gate()._active.clear()
    reset_cache()
    from services.ai.engine.health import reset_health_monitor
    reset_health_monitor()
    try:
        fallback._ai_agent()._BREAKERS.clear()
    except Exception:
        pass


# --------------------------------------------------------------------------- gateway
def handle(name):
    return eng_providers.ProviderHandle(name=name, provider=types.SimpleNamespace(
        name=name, is_available=lambda: True, complete=None))


class Boom(Exception):
    pass


def make_exec(script):
    """script: {provider: [harakat, ...]} — har chaqiruvda navbatdagisi: 'timeout' | '429' | '503' |
    'net' | 'quality' | 'ok' | 'hang'."""
    pos = {k: 0 for k in script}

    async def exec_(h, prompt, instruction, *, lang=None, timeout=10.0):
        acts = script[h.name]
        act = acts[min(pos[h.name], len(acts) - 1)]
        pos[h.name] += 1
        if act == "timeout":
            raise asyncio.TimeoutError()
        if act == "429":
            raise RuntimeError("HTTP 429 rate limit")
        if act == "503":
            raise RuntimeError("HTTP 503 service unavailable")
        if act == "net":
            raise RuntimeError("connection reset by peer")
        if act == "quality":
            return {"text": ""}
        if act == "hang":
            await asyncio.sleep(30)
        return {"text": GOOD_TEXT, "model": "gemini-2.5-flash"}
    return exec_


def gateway_run(script, order=("Gemini", "Groq", "OpenRouter"), store=None, **gen_kw):
    store = store or Store()
    fresh(store)
    real = (eng_providers.build_provider_handles, eng_providers.execute_provider)
    spec = eng_router.LANE_SPECS[eng_router.Lane.QUALITY]
    eng_providers.build_provider_handles = lambda: {n: handle(n) for n in script}
    eng_providers.execute_provider = make_exec(script)
    eng_router.LANE_SPECS[eng_router.Lane.QUALITY] = dataclasses.replace(spec, provider_order=tuple(order))
    try:
        with env(**ROOMY):
            res = asyncio.run(gw.ai_gateway.generate(
                prompt="chain " + str(id(script)), task="audit", user_id=5, lane="smart",
                use_cache=False, **gen_kw))
            asyncio.run(asyncio.sleep(0))
    finally:
        eng_providers.build_provider_handles, eng_providers.execute_provider = real
        eng_router.LANE_SPECS[eng_router.Lane.QUALITY] = spec
    return res, store


print("\n== 1) Gateway: timeout → 429 (audit P1-1) ==")
res, st = gateway_run({"Gemini": ["timeout"], "Groq": ["429"]}, order=("Gemini", "Groq"))
check("natija: xato, oxirgi xato turi rate_limit", (not res.ok) and res.failure_kind == "rate_limit", str(res.failure_kind))
check("timeout → 429: bron release QILINMADI, mark_unknown", st.calls == ["reserve", "mark_unknown"], str(st.calls))

print("\n== 2) Gateway: timeout → barcha provayderlar muvaffaqiyatsiz ==")
res, st = gateway_run({"Gemini": ["timeout"], "Groq": ["503"], "OpenRouter": ["429"]})
check("timeout + 503 + 429: noaniq xarajat saqlandi (mark_unknown)", st.calls == ["reserve", "mark_unknown"], str(st.calls))
res, st = gateway_run({"Gemini": ["429"], "Groq": ["quality"], "OpenRouter": ["429"]})
check("sifat bo'yicha tashlangan javob (ishlab chiqarilgan) → noaniq", st.calls == ["reserve", "mark_unknown"], str(st.calls))
res, st = gateway_run({"Gemini": ["net"], "Groq": ["timeout"]}, order=("Gemini", "Groq"))
check("tarmoq uzilishi + timeout → noaniq", st.calls == ["reserve", "mark_unknown"], str(st.calls))

print("\n== 3) Gateway: faqat aniq nol xarajatli xatolar → release ==")
res, st = gateway_run({"Gemini": ["429"], "Groq": ["503"], "OpenRouter": ["429"]})
check("429 + 503 + 429: release (aniq nol)", st.calls == ["reserve", "release"], str(st.calls))
res, st = gateway_run({"Gemini": ["429"]}, order=("Gemini",))
check("yagona 429: release", st.calls == ["reserve", "release"], str(st.calls))
res, st = gateway_run({}, order=())
check("provayder umuman chaqirilmadi: release", st.calls == ["reserve", "release"], str(st.calls))

print("\n== 4) Gateway: muvaffaqiyatli fallback → settlement bir marta ==")
res, st = gateway_run({"Gemini": ["timeout"], "Groq": ["ok"]}, order=("Gemini", "Groq"))
check("timeout → muvaffaqiyat: faqat settle (release/unknown yo'q)", res.ok and st.calls == ["reserve", "settle"], str(st.calls))
check("settle: haqiqiy estimated_cost yozildi (taxmin emas)",
      len(st.settled) == 1 and abs(st.settled[0][0] - res.estimated_cost) < 1e-9 and st.settled[0][1] == 0.0,
      str(st.settled))
res, st = gateway_run({"Gemini": ["ok"]}, order=("Gemini",))
check("oddiy muvaffaqiyat: settle bir marta", st.calls == ["reserve", "settle"] and len(st.settled) == 1)

print("\n== 5) Cancellation va umumiy timeout (mavjud unknown siyosati) ==")
res, st = gateway_run({"Gemini": ["hang"]}, order=("Gemini",), timeout=1.0)
check("umumiy muddat (wait_for) timeout → mark_unknown", (not res.ok) and res.failure_kind == "timeout"
      and st.calls == ["reserve", "mark_unknown"], str(st.calls))


async def cancelled():
    store = Store()
    fresh(store)
    real = (eng_providers.build_provider_handles, eng_providers.execute_provider)
    eng_providers.build_provider_handles = lambda: {"Gemini": handle("Gemini")}
    eng_providers.execute_provider = make_exec({"Gemini": ["hang"]})
    try:
        with env(**ROOMY):
            t = asyncio.create_task(gw.ai_gateway.generate(prompt="cancel", task="audit", user_id=6,
                                                           lane="smart", use_cache=False, timeout=20.0))
            await asyncio.sleep(0.3)
            t.cancel()
            try:
                await t
            except BaseException:
                pass
            await asyncio.sleep(0.1)
    finally:
        eng_providers.build_provider_handles, eng_providers.execute_provider = real
    return store


st = asyncio.run(cancelled())
check("cancellation → mark_unknown (bron hisobda qoladi)", st.calls == ["reserve", "mark_unknown"], str(st.calls))

print("\n== 6) Yakuniy callback takrorlanishi idempotent ==")
store = Store()
fresh(store)


async def twice():
    with env(**ROOMY):
        d = await budget.default_guard().acquire(8, "free", 10, 0.01)
        hint = {"ok": False, "failure_kind": "timeout", "cost_unknown": True, "tracked": True}
        a = await budget.default_guard().finalize(d.ticket, hint)
        b = await budget.default_guard().finalize(d.ticket, hint)
        budget.default_guard().release(d.ticket)
        budget.default_guard().release(d.ticket)
        await asyncio.sleep(0.05)
        return a, b


a, b = asyncio.run(twice())
check("finalize takror: ikkinchisi 'done', do'konga bir marta", (a, b) == ("unknown", "done")
      and store.calls == ["reserve", "mark_unknown"], str((a, b, store.calls)))

print("\n== 7) Fallback (legacy) yo'li ==")


class P(fallback.AIProvider):
    key_attr = None
    tier = 1

    def __init__(self, name, act):
        self.name, self.act = name, act

    def is_available(self):
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        if self.act == "timeout":
            raise asyncio.TimeoutError()
        if self.act == "429":
            raise fallback.AIProviderError(429, "rate limit", self.name)
        if self.act == "503":
            raise fallback.AIProviderError(503, "unavailable", self.name)
        if self.act == "400":
            raise fallback.AIProviderError(400, "bad request", self.name)
        if self.act == "http404text":
            raise RuntimeError("Gemini (m) HTTP 404: model topilmadi")
        if self.act == "boom":
            raise RuntimeError("kutilmagan xato")
        if self.act == "status0":
            raise fallback.AIProviderError(0, "network/timeout", self.name)
        if self.act == "badformat":
            return ["not", "a", "dict"]
        note_model("fake-model")
        return {"post_text": "Kofe haqida qisqa va aniq post matni. " * 3}


def fb_run(*acts):
    store = Store()
    fresh(store)
    svc = fallback.AIFallbackService(providers=[P(f"P{i}", a) for i, a in enumerate(acts)])

    async def go():
        with env(**ROOMY), usage_scope(user_id=9, action_type="post"):
            out = await svc.generate("Kofe haqida post", "tizim", lang="uz")
        await asyncio.sleep(0)
        return out
    out = asyncio.run(go())
    return out, store


out, st = fb_run("timeout", "429")
check("fallback: timeout → 429: release QILINMADI, unknown", st.calls == ["reserve", "mark_unknown"], str(st.calls))
out, st = fb_run("429", "503")
check("fallback: 429 → 503 (aniq nol): release", st.calls == ["reserve", "release"], str(st.calls))
out, st = fb_run("400", "429")
check("fallback: 4xx (so'rov rad etildi) + 429: release", st.calls == ["reserve", "release"], str(st.calls))
out, st = fb_run("http404text", "429")
check("fallback: matndagi 'HTTP 404' (so'rov rad etilgan) + 429: release", st.calls == ["reserve", "release"], str(st.calls))
out, st = fb_run("boom", "429")
check("fallback: tasniflanmagan istisno (nol xarajat isbotlanmagan) + 429: unknown", st.calls == ["reserve", "mark_unknown"], str(st.calls))
out, st = fb_run("status0", "429")
check("fallback: status 0 (tarmoq/timeout, noaniq) + 429: unknown", st.calls == ["reserve", "mark_unknown"], str(st.calls))
out, st = fb_run("badformat", "429")
check("fallback: javob ishlab chiqarilgan (format noto'g'ri) + 429: unknown", st.calls == ["reserve", "mark_unknown"], str(st.calls))
out, st = fb_run("timeout", "ok")
check("fallback: timeout → muvaffaqiyat: settle bir marta", bool(out.get("post_text")) and st.calls == ["reserve", "settle"], str(st.calls))
out, st = fb_run("429", "ok")
check("fallback: 429 → muvaffaqiyat: settle bir marta", st.calls == ["reserve", "settle"] and len(st.settled) == 1)
check("fallback: settle'da narxi noma'lum model → assumed alohida, haqiqiy 0",
      st.settled and st.settled[0][0] == 0.0 and st.settled[0][1] > 0, str(st.settled))

print("\n== 8) Vision model zanjiri ==")
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


class Resp:
    def __init__(self, status, body=None):
        self.status, self._b = status, body or {}

    async def json(self):
        return self._b

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class Client:
    def __init__(self, acts):
        self.acts, self.i = acts, 0

    def post(self, url, json=None, timeout=None):
        act = self.acts[min(self.i, len(self.acts) - 1)]
        self.i += 1
        if act == "timeout":
            raise asyncio.TimeoutError()
        return Resp(int(act))


def vision(*acts):
    store = Store()
    fresh(store)

    async def go():
        with env(**ROOMY):
            return await gw.ai_gateway.vision_analyze(PNG, caption="kofe", lang="uz", user_id=10) \
                if False else await _vision_call(acts)
    return asyncio.run(go()), store


async def _vision_call(acts):
    orig = va.analyze_image
    client = Client(acts)

    async def patched(data, caption="", api_key=None, model=None, timeout=None, session=None, lang="uz", mime_type=None):
        return await orig(data, caption=caption, api_key="test-key", model=model, timeout=timeout,
                          session=client, lang=lang, mime_type=mime_type)
    va.analyze_image = patched
    try:
        res = await gw.ai_gateway.vision_analyze(PNG, caption="kofe", lang="uz", user_id=10)
    finally:
        va.analyze_image = orig
    await asyncio.sleep(0)
    return res


res, st = vision("timeout", "429")
check("vision: 1-model timeout → 2-model 429: release QILINMADI", (not res.ok) and st.calls == ["reserve", "mark_unknown"], str(st.calls))
res, st = vision("429", "503")
check("vision: faqat 429/503 (aniq nol): release", (not res.ok) and st.calls == ["reserve", "release"], str(st.calls))

print("\n== 9) classify_settlement jadvali ==")
cs = budget.classify_settlement
check("cost_unknown=True + oxirgi rate_limit → unknown",
      cs({"ok": False, "failure_kind": "rate_limit", "cost_unknown": True, "tracked": True})[0] == "unknown")
check("zanjir tugagan, noaniq urinish yo'q (kuzatuv bor) → release",
      cs({"ok": False, "failure_kind": "other", "tracked": True, "chain_complete": True})[0] == "release")
check("kuzatuv YO'Q + all_providers_failed → unknown (dalil yo'q)",
      cs({"ok": False, "failure_kind": "all_providers_failed", "tracked": False})[0] == "unknown")
check("zanjir tugamagan (masalan umumiy timeout) + 'other' → unknown",
      cs({"ok": False, "failure_kind": "other", "tracked": True, "chain_complete": False})[0] == "unknown")
check("zanjir tugagan, lekin noaniq urinish bor → unknown",
      cs({"ok": False, "failure_kind": "rate_limit", "tracked": True, "chain_complete": True,
          "cost_unknown": True})[0] == "unknown")
check("timeout (cost_unknown belgisisiz ham) → unknown", cs({"ok": False, "failure_kind": "timeout", "tracked": True})[0] == "unknown")
check("muvaffaqiyat + oldingi noaniq urinish → settle (haqiqiy xarajat saqlanadi)",
      cs({"ok": True, "cost_unknown": True, "estimated_cost": 0.004, "unpriced": False})[:2] == ("settle", 0.004))

print("\n== 10) Kuzatuv holati (holder) bola task'lar bilan umumiy ==")


async def child_visibility():
    budget.reset_settlement_hint()

    async def child():
        budget.note_attempt("X", "timeout")
    await asyncio.create_task(child())
    budget.note_settlement({"status": "failed", "error_code": "rate_limit"})
    return budget.take_settlement_hint()


hint = asyncio.run(child_visibility())
check("bola task ichidagi noaniq urinish ota kontekstda ko'rinadi (py3.11 wait_for ham)",
      hint and hint["cost_unknown"] is True and hint["tracked"] is True, str(hint))

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
