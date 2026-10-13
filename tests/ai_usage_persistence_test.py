#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💾 AI USAGE PERSISTENSIYASI — production yo'li ``ai_usage_events`` ga yozadi.

Muammo: gateway/fallback/legacy yo'llari hodisani faqat xotiraga yozardi;
``save_ai_usage_event`` ni faqat ``AITaskService`` chaqirardi (production'da
chaqiruvchisi yo'q). Restart bilan sarf yo'qolar, DB hisobotlari doim bo'sh edi.

Offline qism soxta DB bilan; jonli qism ``AI_BUDGET_TEST_DATABASE_URL`` berilsa
haqiqiy PostgreSQL bilan (aks holda [SKIP]).

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/ai_usage_persistence_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456789:USAGE_PERSIST_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BETA_INVITE_ONLY", "false")
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
from services.ai.engine import telemetry  # noqa: E402
from services.ai.usage_scope import note_model, usage_scope  # noqa: E402


class FakeProvider(fallback.AIProvider):
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
        note_model("fake-model-1")        # narx jadvalida yo'q → unpriced
        return {"post_text": "Kofe haqida qisqa va aniq post matni. " * 3}


class FakeDb:
    """Soxta DB: save_ai_usage_event chaqiruvlarini yig'adi."""

    _pool = object()

    def __init__(self, fail=False):
        self.rows, self.fail = [], fail

    async def run_db(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def save_ai_usage_event(self, **fields):
        if self.fail:
            raise RuntimeError("db down")
        self.rows.append(fields)
        return len(self.rows)


def reset_state():
    telemetry.reset_default_recorder()
    cost_tracker._ledger = cost_tracker.CostLedger()
    budget.set_tier_resolver(lambda uid: False)
    budget._guard.__init__()
    admission.default_user_gate()._active.clear()


def with_fake_db(fake, coro_factory):
    orig = usage_store._database
    usage_store._database = lambda: fake

    async def main():
        out = await coro_factory()
        await usage_store.drain(2.0)
        return out
    try:
        return asyncio.run(main())
    finally:
        usage_store._database = orig


print("\n== 1) Production yo'li (fallback) hodisani DB'ga yozadi ==")
reset_state()
fake = FakeDb()
svc = fallback.AIFallbackService(providers=[FakeProvider()])


async def ok_flow():
    ok_svc = fallback.AIFallbackService(providers=[FakeProvider()])
    with usage_scope(user_id=71, channel_id=-1001, action_type="post"):
        return await ok_svc.generate("Kofe haqida post", "tizim", lang="uz")


res = with_fake_db(fake, ok_flow)
check("javob keldi", bool(res.get("post_text")))
check("aynan 1 ta qator yozildi", len(fake.rows) == 1, str(fake.rows))
row = fake.rows[0] if fake.rows else {}
check("muvaffaqiyat + narxi noma'lum: status=success, priced=False, cached=False",
      row.get("status") == "success" and row.get("priced") is False and row.get("cached") is False, str(row))
check("narxi noma'lum: estimated_cost = 0 (taxmin YOZILMAYDI)", float(row.get("estimated_cost") or 0) == 0.0)
check("user/kanal/provayder/model yozildi",
      row.get("user_id") == 71 and row.get("channel_id") == -1001
      and row.get("provider") == "FakeP" and row.get("model") == "fake-model-1", str(row))
check("tokenlar yozildi", int(row.get("input_tokens") or 0) > 0 and int(row.get("output_tokens") or 0) > 0)

reset_state()
fake = FakeDb()
svc = fallback.AIFallbackService(providers=[FakeProvider("FailP", "fail")])


async def fail_flow():
    with usage_scope(user_id=72, action_type="post"):
        return await svc.generate("x", "tizim", lang="uz")


with_fake_db(fake, fail_flow)
check("provayder xatosi: 1 ta 'failed' qator, narx 0",
      len(fake.rows) == 1 and fake.rows[0].get("status") == "failed"
      and float(fake.rows[0].get("estimated_cost") or 0) == 0.0, str(fake.rows))

print("\n== 2) Hodisa semantikasi: narxli, cache, timeout ==")
fake = FakeDb()
events = {
    "narxli": gw.GatewayResult(ok=True, text="javob " * 50, provider="Gemini", model="gemini-2.5-flash"),
    "kesh": gw.GatewayResult(ok=True, text="x" * 200, provider="cache", model="gemini-2.5-flash", cached=True),
    "timeout": gw.GatewayResult(ok=False, provider="", failure_kind="timeout"),
}


async def direct():
    for result in events.values():
        ev = telemetry.build_usage_event(result=result, prompt="p" * 400, user_id=73)
        usage_store.persist_usage_event(ev.as_dict())


with_fake_db(fake, direct)
by = {("priced" if r["priced"] else "x", r["status"], r["cached"]): r for r in fake.rows}
check("3 ta hodisa yozildi", len(fake.rows) == 3, str(len(fake.rows)))
check("narxli: priced=True, estimated_cost > 0",
      any(r["priced"] and r["status"] == "success" and float(r["estimated_cost"]) > 0 and not r["cached"]
          for r in fake.rows))
check("kesh: cached=True, estimated_cost = 0, priced=False",
      any(r["cached"] and float(r["estimated_cost"]) == 0.0 and not r["priced"] for r in fake.rows))
check("timeout: status=failed, error_code=timeout",
      any(r["status"] == "failed" and r["error_code"] == "timeout" for r in fake.rows), str(by))

print("\n== 3) Xavfsizlik: xato AI oqimini buzmaydi, o'chirish, sinxron kontekst ==")
reset_state()
fake = FakeDb(fail=True)
res = with_fake_db(fake, ok_flow)
check("DB yozuvi xato berdi: AI javobi baribir qaytdi", bool(res.get("post_text")))
os.environ["AI_USAGE_PERSIST"] = "0"
try:
    fake = FakeDb()
    with_fake_db(fake, ok_flow)
    check("AI_USAGE_PERSIST=0: hech narsa yozilmaydi", fake.rows == [])
finally:
    os.environ.pop("AI_USAGE_PERSIST", None)
orig = usage_store._database
usage_store._database = lambda: FakeDb()
try:
    check("ishlayotgan event loop yo'q: bloklamaydi, False qaytaradi",
          usage_store.persist_usage_event({"user_id": 1, "status": "success"}) is False)
finally:
    usage_store._database = orig
check("DB pool yo'q (offline): False", usage_store.persist_usage_event({"user_id": 1}) is False)

print("\n== 4) Legacy zanjir: bitta yozuv (dedupe) ==")
reset_state()
fake = FakeDb()


async def legacy():
    async def fake_chain(prompt, system_instruction, lang=None):
        note_model("fake-model-1")
        return {"post_text": "Matn " * 20, "provider": "FakeP", "model": "fake-model-1"}

    orig_chain = fallback.run_ai_chain
    fallback.run_ai_chain = fake_chain
    try:
        with usage_scope(user_id=74, action_type="post"):
            return await gw.legacy_chain("Kofe post", "tizim", "uz")
    finally:
        fallback.run_ai_chain = orig_chain


with_fake_db(fake, legacy)
check("legacy_chain: aynan 1 ta qator", len(fake.rows) == 1 and fake.rows[0]["task"] == "legacy_chain",
      str(fake.rows))

print("\n== 5) AITaskService bilan ikki marta yozilmaydi ==")
from services.ai.engine import app_service  # noqa: E402

svc_task = app_service.AITaskService.__new__(app_service.AITaskService)
saved = []


class _Db:
    _pool = object()

    @staticmethod
    async def run_db(fn, **kw):
        saved.append(kw)

    @staticmethod
    def save_ai_usage_event(**kw):
        return 1


svc_task._real_db = lambda db: True
out = asyncio.run(svc_task._save_usage(_Db, {"persisted": True, "user_id": 1}, {}))
check("gateway allaqachon yozgan hodisa AITaskService'da qayta yozilmaydi", out is None and saved == [])

print("\n== 5b) AITaskService yo'lida shlyuz fon yozuvi o'chiriladi (regressiya: usage_id va yo'qolgan yozuv) ==")
seen = {}


class _FakeGateway:
    async def generate(self, prompt, **kw):
        # shlyuz ichidagi `_record` taqlidi: fon yozuvi navbatga qo'yilishi MUMKINmi?
        seen["scheduled"] = usage_store.persist_usage_event({"user_id": 1, "status": "success"})

        async def child():
            seen["child_scheduled"] = usage_store.persist_usage_event({"user_id": 1, "status": "success"})
        await asyncio.create_task(child())
        return gw.GatewayResult(ok=True, text="x" * 80, provider="Gemini", model="gemini-2.5-flash",
                                task="social_post")


async def _task_flow(fake_db):
    svc_t = app_service.AITaskService(gateway=_FakeGateway())
    out = await svc_t.run(db=None, task="social_post", prompt="p", user_id=1,
                          reserve_quota=False, use_cache=False)
    outside = usage_store.persist_usage_event({"user_id": 1, "status": "success"})
    await usage_store.drain(1.0)
    return out, outside


orig_db = usage_store._database
fake_t = FakeDb()
usage_store._database = lambda: fake_t
try:
    outcome, outside_flag = asyncio.run(_task_flow(fake_t))
finally:
    usage_store._database = orig_db
check("AITaskService ichida shlyuz fon yozuvi navbatga qo'yilmaydi", seen.get("scheduled") is False, str(seen))
check("bola task'da ham o'chirilgan (kontekst meros)", seen.get("child_scheduled") is False, str(seen))
check("AITaskService tugagach fon yozuvi qayta yoqiladi", outside_flag is True)
check("AITaskService yo'lida DB'ga ortiqcha yozuv ketmadi (faqat tashqaridagi 1 ta)", len(fake_t.rows) == 1, str(fake_t.rows))

print("\n== 6) Jonli PostgreSQL ==")
live_url = os.environ.get("AI_BUDGET_TEST_DATABASE_URL", "").strip()
if not live_url:
    skipped += 1
    print("  [SKIP] AI_BUDGET_TEST_DATABASE_URL berilmagan — jonli qism o'tkazildi")
else:
    db_mod.DATABASE_URL = live_url
    db_mod._reset_pool()
    db_mod.init_db()
    uid = 910000000 + (os.getpid() % 100000)
    reset_state()
    svc = fallback.AIFallbackService(providers=[FakeProvider()])

    async def live_flow():
        async def one(u):
            with usage_scope(user_id=u, action_type="post"):
                return await svc.generate("Kofe haqida post", "tizim", lang="uz")
        await one(uid)
        ev = telemetry.build_usage_event(
            result=gw.GatewayResult(ok=True, text="x" * 200, provider="cache",
                                    model="gemini-2.5-flash", cached=True),
            prompt="p", user_id=uid)
        usage_store.persist_usage_event(ev.as_dict())
        ev = telemetry.build_usage_event(
            result=gw.GatewayResult(ok=True, text="javob " * 50, provider="Gemini",
                                    model="gemini-2.5-flash"), prompt="p" * 400, user_id=uid)
        usage_store.persist_usage_event(ev.as_dict())
        await usage_store.drain(5.0)

    asyncio.run(live_flow())
    rep = db_mod.get_ai_usage_report(user_id=uid, period="daily")
    t = (rep or {}).get("totals", {})
    check("DB: 3 ta qator (unpriced success, kesh, narxli)", t.get("requests") == 3, str(t))
    check("DB: priced=1, unpriced=1, cache=1",
          t.get("priced_requests") == 1 and t.get("unpriced_requests") == 1 and t.get("cache_hits") == 1, str(t))
    check("DB: unpriced tokenlari alohida hisoblandi",
          int(t.get("unpriced_input_tokens", 0)) > 0 and int(t.get("unpriced_output_tokens", 0)) > 0, str(t))
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM ai_usage_events WHERE user_id = %s", (uid,))
    db_mod.close_pool()

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}  [SKIP]={skipped}")
sys.exit(1 if failures else 0)
