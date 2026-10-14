#!/usr/bin/env python3
"""Mini App — AI generatsiya (kvota bron/qaytarish), yozuv validatsiyasi va marshrut limitlari (DB'siz).

Haqiqiy kod: `PostWriter.ai_generate`, `read_json_object`, validatorlar, aiohttp marshrutlari, auth,
xato katalogi. Mock: servis (ruxsat/egalik), AI adapter (bron/generatsiya/qaytarish), limiter.
Kvota ATOMIKLIGI DB qatlamida (`atomic_quota_test.py`, real PG: `credits_bonus_concurrency_test.py`);
bu yerda Mini App faqat o'sha bron/qaytarish API'sini TO'G'RI ishlatishi tekshiriladi.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from miniapp_testkit import FAKE_TOKEN, NOW, Counter, make_init_data  # noqa: E402

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from miniapp_api import app as appmod  # noqa: E402
from miniapp_api.errors import ApiError  # noqa: E402
from miniapp_api.settings import load_settings  # noqa: E402
from miniapp_api.writes import PostWriter  # noqa: E402

T = Counter("MINI APP — AI + yozuv validatsiyasi (DB'siz)")
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)
SECRET_INPUT = "MAXFIY-FOYDALANUVCHI-MATNI-777"


def run(coro):
    return LOOP.run_until_complete(coro)


class FakeService:
    def __init__(self, is_admin=False):
        self.is_admin = is_admin

    async def authorize(self, user_id):
        return {"is_admin": self.is_admin, "language": "uz"}

    async def owns_channel(self, user_id, channel_id):
        return False

    async def post(self, user_id, post_id):
        raise ApiError("not_found")


class FakeAI:
    def __init__(self, *, allow=True, reason="insufficient", pro=False, result=None, exc=None,
                 delay=0.0, credits=None):
        self.allow, self.reason, self.pro, self.result, self.exc = allow, reason, pro, result, exc
        self.delay, self.credits = delay, credits
        self.reserved, self.released, self.generated = [], [], []
        self._next = 1

    async def is_pro(self, user_id):
        return self.pro

    async def reserve(self, user_id):
        if self.credits is not None:
            if self.credits <= 0:
                return {"allowed": False, "reason": "insufficient"}
            self.credits -= 1
        elif not self.allow:
            return {"allowed": False, "reason": self.reason}
        rid = self._next
        self._next += 1
        self.reserved.append((user_id, rid))
        return {"allowed": True, "reservation_id": rid}

    def is_balance_reason(self, reason):
        return reason == "insufficient"

    async def release(self, user_id, reservation_id):
        self.released.append((user_id, reservation_id))

    async def generate(self, text, style, lang, is_pro):
        self.generated.append((text, style, lang, is_pro))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result if self.result is not None else {"post_text": "AI natija", "style": style}


def settings_for(**over):
    base = load_settings({"MINIAPP_ENABLED": "1", "BOT_TOKEN": FAKE_TOKEN, "ENVIRONMENT": "test",
                          "MINIAPP_PROXY_ASSERT_EDGE_ONLY": "1", "MINIAPP_REQUIRE_HTTPS": "0"})
    return dataclasses.replace(base, **over) if over else base


def writer(ai, *, admin=False, **over):
    return PostWriter(FakeService(admin), settings_for(**over), ai=ai)


def gen(w, text="g'oya", style="casual", user=7):
    return w.ai_generate(user, {"text": text, "style": style})


def code_of(coro):
    try:
        run(coro)
    except ApiError as exc:
        return exc.code
    return "OK"


def main() -> int:
    print("\n== 1. Muvaffaqiyat ==")
    ai = FakeAI()
    out = run(gen(writer(ai)))
    T.check("natija matni + uslub qaytadi", out == {"text": "AI natija", "style": "casual"})
    T.check("bepul foydalanuvchi: AYNAN 1 bron, qaytarish yo'q", len(ai.reserved) == 1 and ai.released == [])
    T.check("til profilga ko'ra (uz), is_pro=False uzatildi", ai.generated[0][2:] == ("uz", False))

    print("\n== 2. Xato va bron qaytarish ==")
    for label, ai in (("provayder xatosi (error)", FakeAI(result={"error": "boom " + SECRET_INPUT})),
                      ("bo'sh javob", FakeAI(result={"post_text": "  "})),
                      ("istisno", FakeAI(exc=RuntimeError(SECRET_INPUT)))):
        logs = logging.getLogger("miniapp_api.writes")
        records = []

        class H(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        h = H()
        logs.addHandler(h)
        try:
            code = code_of(gen(writer(ai), text=SECRET_INPUT))
        finally:
            logs.removeHandler(h)
        T.check(f"{label}: 503 ai_unavailable (soxta matn YO'Q)", code == "ai_unavailable")
        T.check(f"{label}: bron AYNAN 1 marta qaytarildi", ai.released == ai.reserved and len(ai.released) == 1)
        T.check(f"{label}: logda foydalanuvchi matni/istisno matni yo'q", not any(SECRET_INPUT in r for r in records))

    print("\n== 3. Limit va rad ==")
    ai = FakeAI(allow=False)
    T.check("kvota/kredit tugagan -> 403 ai_limit_reached", code_of(gen(writer(ai))) == "ai_limit_reached")
    T.check("rad etilganda generatsiya chaqirilmadi", ai.generated == [] and ai.released == [])
    ai = FakeAI(allow=False, reason="db_error")
    T.check("DB xatosi (fail-closed) -> 503 service_unavailable", code_of(gen(writer(ai))) == "service_unavailable" and ai.generated == [])
    ai = FakeAI(pro=True)
    run(gen(writer(ai)))
    T.check("PRO: bron QILINMAYDI (bot bilan bir xil), generatsiya bor", ai.reserved == [] and ai.generated[0][3] is True)
    ai = FakeAI()
    run(gen(writer(ai, admin=True)))
    T.check("admin: bron QILINMAYDI", ai.reserved == [] and len(ai.generated) == 1)

    print("\n== 4. Parallel so'rovlar ==")
    ai = FakeAI(credits=2, delay=0.05)
    w = writer(ai)

    async def burst():
        return await asyncio.gather(*[gen(w) for _ in range(6)], return_exceptions=True)

    res = run(burst())
    ok = [r for r in res if isinstance(r, dict)]
    denied = [r for r in res if isinstance(r, ApiError) and r.code == "ai_limit_reached"]
    T.check("2 kredit, 6 parallel so'rov: AYNAN 2 ta muvaffaqiyat, 4 ta rad", len(ok) == 2 and len(denied) == 4, str(res))
    T.check("faqat bron qilinganlar generatsiya qilindi (2)", len(ai.generated) == 2 and ai.released == [])

    print("\n== 5. Bekor qilinish / timeout ==")
    ai = FakeAI(delay=5.0)

    async def timed():
        return await asyncio.wait_for(gen(writer(ai)), 0.2)

    try:
        run(timed())
    except asyncio.TimeoutError:
        pass
    T.check("timeout/bekor: bron QAYTARILDI (osilib qolmaydi)", ai.released == ai.reserved and len(ai.released) == 1)

    print("\n== 6. Kirish validatsiyasi ==")
    ai = FakeAI()
    w = writer(ai)
    for label, body in (("bo'sh matn", {"text": ""}), ("matn yo'q", {}), ("3501 belgi", {"text": "a" * 3501}),
                        ("noma'lum uslub", {"text": "x", "style": "evil"}), ("matn turi", {"text": 5}),
                        ("qo'shimcha maydon", {"text": "x", "user_id": 1}), ("uslub turi", {"text": "x", "style": ["casual"]})):
        T.check(f"{label} -> invalid_input, bron/generatsiya yo'q", code_of(w.ai_generate(7, body)) == "invalid_input"
                and ai.reserved == [] and ai.generated == [])

    print("\n== 7. HTTP marshruti ==")
    limiter_calls = []

    class RecLimiter:
        async def hit(self, bucket, subject, *, limit, window):
            limiter_calls.append((bucket, subject, limit))

    async def http(method, path, headers=None, **kw):
        ai2 = FakeAI()
        settings = settings_for()
        service = FakeService()
        api = appmod.build_api_app(settings, limiter=RecLimiter(), clock=lambda: NOW, service=service,
                                   writer=PostWriter(service, settings, ai=ai2))
        app = web.Application()
        app.add_subapp(appmod.API_PREFIX, api)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            resp = await client.request(method, path, headers=headers, **kw)
            try:
                body = await resp.json()
            except Exception:  # noqa: BLE001
                body = None
            return resp.status, body, ai2
        finally:
            await client.close()

    auth = {"Authorization": "tma " + make_init_data(7)}
    st, body, ai2 = run(http("POST", "/api/v1/ai/generate", auth, json={"text": "g'oya", "style": "sales"}))
    T.check("POST /ai/generate -> 200 {text, style}", st == 200 and body == {"text": "AI natija", "style": "sales"}, f"{st} {body}")
    buckets = [b for b, _, _ in limiter_calls]
    T.check("limiterlar tartibi: auth_ip, user, write, ai", buckets[-4:] == ["auth_ip", "user", "write", "ai"], str(buckets))
    T.check("limiter subyekti tasdiqlangan user_id (7)", [s for b, s, _ in limiter_calls if b in ("user", "write", "ai")] == ["7", "7", "7"])
    st, body, _ = run(http("POST", "/api/v1/ai/generate", None, json={"text": "x"}))
    T.check("auth'siz -> 401", st == 401 and body["error"]["code"] == "unauthorized")
    st, body, _ = run(http("POST", "/api/v1/ai/generate", auth, data="text=x"))
    T.check("JSON emas -> 415", st == 415)
    st, body, _ = run(http("GET", "/api/v1/ai/generate", auth))
    T.check("GET /ai/generate -> 405", st == 405 and body["error"]["code"] == "method_not_allowed")
    st, body, _ = run(http("POST", "/api/v1/ai/generate", auth, json={"text": "x", "user_id": 99}))
    T.check("body'dagi user_id qabul qilinmaydi -> 422", st == 422 and body["error"]["code"] == "invalid_input")
    st, body, _ = run(http("DELETE", "/api/v1/posts/5/../../me", auth))
    T.check("path traversal shaklidagi yo'l -> 404/405 (JSON)", st in (404, 405) and body and "error" in body)
    return T.finish()


if __name__ == "__main__":
    sys.exit(main())
