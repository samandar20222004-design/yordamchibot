#!/usr/bin/env python3
"""Production AI Security P0/P1 tests — fail-closed quota, provider fallback, HTML safety."""
import asyncio
import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123:TEST")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


class FakeQuotaDB:
    def __init__(self, max_ai=5):
        self.max_ai = max_ai
        self.usage = 0
        self.lock = threading.Lock()

    @contextmanager
    def cursor(self, *args, **kwargs):
        yield FakeQuotaCursor(self)


class FakeQuotaCursor:
    def __init__(self, state):
        self.state = state
        self.row = None

    def execute(self, sql, params=None):
        s = " ".join(sql.lower().split())
        if "last_limit_reset" in s:
            self.row = None
            return
        if s.startswith("select plan_type"):
            with self.state.lock:
                self.row = ("free", self.state.usage)
            return
        if s.startswith("update users set ai_requests_today") and "returning ai_requests_today" in s:
            with self.state.lock:
                if self.state.usage < self.state.max_ai:
                    self.state.usage += 1
                    self.row = (self.state.usage,)
                else:
                    self.row = None
            return
        raise AssertionError(f"Unexpected SQL: {sql}")

    def fetchone(self):
        return self.row


def test_2_parallel_free_quota_atomic():
    import database as db
    state = FakeQuotaDB(max_ai=5)
    orig_cursor = db.db_cursor
    db.db_cursor = state.cursor
    db._AI_QUOTA_RESERVATIONS.clear()
    try:
        with ThreadPoolExecutor(max_workers=20) as pool:
            results = list(pool.map(lambda _: db.check_ai_limit(777001), range(20)))
        allowed = [r for r in results if r[0]]
        denied = [r for r in results if not r[0]]
        check("TEST 2: 20 parallel so'rovdan faqat limit miqdori ruxsat oldi", len(allowed) == 5, results)
        check("TEST 2: DB usage limitdan oshmadi", state.usage == 5, state.usage)
        check("TEST 2: qolganlari rad etildi", len(denied) == 15, results)
    finally:
        db.db_cursor = orig_cursor
        db._AI_QUOTA_RESERVATIONS.clear()


def test_3_db_exception_fail_closed():
    import database as db

    @contextmanager
    def broken_cursor(*args, **kwargs):
        raise RuntimeError("pool timeout")
        yield  # pragma: no cover

    orig_cursor = db.db_cursor
    db.db_cursor = broken_cursor
    try:
        allowed, used, max_ai = db.check_ai_limit(777002)
        check("TEST 3: DB exception fail-closed", allowed is False, (allowed, used, max_ai))
    finally:
        db.db_cursor = orig_cursor


def test_4_telegram_html_escaping():
    from utils.helpers import safe_html, telegram_html_payload
    raw = "5 < 10 & price > 100"
    escaped = safe_html(raw)
    payload, parse_mode = telegram_html_payload(raw)
    check("TEST 4: safe_html < & > escape qiladi", escaped == "5 &lt; 10 &amp; price &gt; 100", escaped)
    check("TEST 4: plain text parse_mode=None", payload == raw and parse_mode is None, (payload, parse_mode))
    tagged = "<b>5 < 10 & price > 100</b> <script>x</script>"
    tagged_safe = safe_html(tagged)
    check("TEST 4: ruxsatli tag saqlanib, ichki matn escape qilindi",
          tagged_safe == "<b>5 &lt; 10 &amp; price &gt; 100</b> &lt;script&gt;x&lt;/script&gt;", tagged_safe)


async def test_10_openrouter_free_router():
    from utils import ai_agent
    captured = {}

    async def fake_post(endpoint, headers, payload, http_timeout=None, deadline=None):
        captured.update(payload)
        return {"content": '{"post_text":"OpenRouter OK","scheduled_time":null,"has_explicit_time":false,"target_all":false}'}

    async def fake_discover(api_key):
        return None

    orig_post = ai_agent._post_chat_completion
    orig_discover = ai_agent._discover_openrouter_models
    ai_agent._post_chat_completion = fake_post
    ai_agent._discover_openrouter_models = fake_discover
    try:
        res = await ai_agent._call_openrouter("prompt", "key", "system", {})
        check("TEST 10: OpenRouter dynamic free router ishladi", res.get("post_text") == "OpenRouter OK", res)
        check("TEST 10: model=openrouter/free", captured.get("model") == "openrouter/free", captured)
    finally:
        ai_agent._post_chat_completion = orig_post
        ai_agent._discover_openrouter_models = orig_discover


class StubProvider:
    def __init__(self, name, result=None, exc=None):
        self.name = name
        self.tier = 1
        self.result = result
        self.exc = exc

    def is_available(self):
        return True

    async def complete(self, prompt, system_instruction, params, deadline=None):
        if self.exc:
            raise self.exc
        return dict(self.result)


async def test_11_gemini_to_groq_openrouter_fallback():
    from services.ai_service import AIFallbackService, AIProviderError
    svc = AIFallbackService([
        StubProvider("Gemini", exc=AIProviderError(500, "server error", "Gemini")),
        StubProvider("Groq", result={"post_text": "Groq fallback"}),
        StubProvider("OpenRouter", result={"post_text": "OpenRouter fallback"}),
    ])
    res = await svc.generate("p", "s", lang="uz")
    check("TEST 11: Gemini qulaganda Groq'ga o'tdi", res.get("provider") == "Groq", res)
    check("TEST 11: provider_chain Gemini→Groq", res.get("provider_chain") == ["Gemini", "Groq"], res)


async def test_12_all_providers_graceful():
    from services.ai_service import AIFallbackService, AIProviderError
    svc = AIFallbackService([
        StubProvider("Gemini", exc=AIProviderError(429, "rate limit", "Gemini")),
        StubProvider("Groq", exc=AIProviderError(503, "unavailable", "Groq")),
        StubProvider("OpenRouter", exc=TimeoutError("timeout")),
    ])
    res = await svc.generate("p", "s", lang="uz")
    check("TEST 12: barcha provider yiqilganda graceful", res.get("ai_unavailable") is True, res)
    check("TEST 12: quota_safe=True", res.get("quota_safe") is True, res)
    check("TEST 12: bot crash qilmay, error qaytardi", bool(res.get("error")), res)


def main():
    test_2_parallel_free_quota_atomic()
    test_3_db_exception_fail_closed()
    test_4_telegram_html_escaping()
    asyncio.run(test_10_openrouter_free_router())
    asyncio.run(test_11_gemini_to_groq_openrouter_fallback())
    asyncio.run(test_12_all_providers_graceful())
    print(f"\nProduction AI Security P0/P1: {passed} passed, {failures} failed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
