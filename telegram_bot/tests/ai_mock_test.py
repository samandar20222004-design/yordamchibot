#!/usr/bin/env python3
"""AI mock-server testi — real API'larni taqlid qiluvchi lokal server bilan.

Gemini/Groq/OpenRouter/Pollinations zanjiri to'liq tekshiriladi:
- muvaffaqiyatli javob
- model 404 → keyingi zaxiraga o'tish
- 429 rate-limit → retry
- yaroqsiz JSON → xato qaytadi (crash emas)
- kalitsiz Pollinations zaxirasi

Ishga tushirish:
    cd telegram_bot && python tests/ai_mock_test.py
"""
import os
import sys
import asyncio
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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


# ---- Bo'sh port tanlash ----
_sock = socket.socket()
_sock.bind(("127.0.0.1", 0))
PORT = _sock.getsockname()[1]
_sock.close()

BASE = f"http://127.0.0.1:{PORT}"

# ---- MUHIM: import qilishdan OLDIN env sozlash ----
os.environ["BOT_TOKEN"] = "123:TEST"
os.environ["ADMIN_ID"] = "123"
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/x"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["GROQ_API_KEY"] = "test-groq-key"
os.environ["OPENROUTER_API_KEY"] = "test-or-key"
os.environ["GEMINI_BASE"] = f"{BASE}/gemini"
os.environ["GROQ_ENDPOINT"] = f"{BASE}/groq"
os.environ["OPENROUTER_ENDPOINT"] = f"{BASE}/openrouter"
os.environ["POLLINATIONS_ENDPOINT"] = f"{BASE}/pollinations"

from aiohttp import web
from utils import ai_agent

# ---- Mock server holati ----
S = {
    "gemini_status": 200, "gemini_429_first": False, "gemini_body": {},
    "groq_status": 200, "groq_429_first": False, "groq_body": {},
    "openrouter_status": 200, "openrouter_429_first": False, "openrouter_body": {},
    "pollinations_status": 200, "pollinations_body": {},
    "requests": [],
}

VALID_JSON = '{"post_text": "Mock post matni", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'


async def gemini_handler(request):
    S["requests"].append(("gemini", request.rel_url.path))
    if S.get("gemini_429_first"):
        S["gemini_429_first"] = False
        return web.json_response({"error": {"code": 429}}, status=429, headers={"Retry-After": "1"})
    status = S.get("gemini_status", 200)
    if status != 200:
        return web.json_response({"error": {"message": "model topilmadi"}}, status=status)
    return web.json_response(S["gemini_body"])


def make_openai_handler(key):
    async def handler(request):
        S["requests"].append((key, request.rel_url.path))
        if S.get(f"{key}_429_first"):
            S[f"{key}_429_first"] = False
            return web.json_response({"error": {"code": 429}}, status=429, headers={"Retry-After": "1"})
        status = S.get(f"{key}_status", 200)
        if status != 200:
            return web.json_response({"error": {"message": "xato"}}, status=status)
        body = S.get(f"{key}_body", VALID_JSON)
        return web.json_response({"choices": [{"message": {"content": body}}]})
    return handler


async def main():
    app = web.Application()
    app.router.add_post("/gemini/{model}:generateContent", gemini_handler)
    app.router.add_post("/groq", make_openai_handler("groq"))
    app.router.add_post("/openrouter", make_openai_handler("openrouter"))
    app.router.add_post("/pollinations", make_openai_handler("pollinations"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()

    # ---- Test 1: Gemini muvaffaqiyatli ----
    print("== 1. Gemini muvaffaqiyat ==")
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Gemini javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 2: Gemini 404 → Groq zaxira ----
    print("== 2. Gemini 404 → Groq ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Groq javobi qaytdi (fallback)", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 3: Gemini 429 → retry → muvaffaqiyat ----
    print("== 3. Gemini 429 retry ==")
    S.update({
        "gemini_status": 200,
        "gemini_429_first": True,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    start = asyncio.get_event_loop().time()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    elapsed = asyncio.get_event_loop().time() - start
    check("429'dan keyin Gemini javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])
    check("429 kutish vaqti ≈1s", elapsed >= 0.9 and elapsed < 3, f"{elapsed:.2f}s")

    # ---- Test 4: hammasi xato → aniq xato xabari (crash emas) ----
    print("== 4. Barcha provayderlar xato ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "pollinations_status": 500, "pollinations_body": "xato",
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("error dict qaytdi", "error" in result, str(result)[:100])
    check("xato xabarida kalit bo'yicha yo'l-yo'riq bor",
          "GEMINI_API_KEY" in result.get("error", ""), result.get("error", "")[:80])

    # ---- Test 5: Gemini/Groq/OpenRouter xato, Pollinations kalitsiz ishlaydi ----
    print("== 5. Kalitsiz Pollinations zaxirasi ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "pollinations_status": 200, "pollinations_body": VALID_JSON,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Pollinations javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 6: yaroqsiz JSON (barchasi) → xato, crash emas ----
    print("== 6. Yaroqsiz JSON bilan xato ==")
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": "bu JSON emas"}]}}]},
        "groq_status": 200, "groq_body": "bu ham JSON emas",
        "openrouter_status": 200, "openrouter_body": "bunisi ham",
        "pollinations_status": 200, "pollinations_body": "yo'q",
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("yaroqsiz JSON → error", "error" in result, str(result)[:100])

    # ---- Test 7: markdown blok ichidagi JSON (Gemini ko'pincha shunday qaytaradi) ----
    print("== 7. Markdown blok ichida JSON ==")
    fenced = '```json\n{"post_text": "Blok ichidagi", "scheduled_time": null, "has_explicit_time": false, "target_all": false}\n```'
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": fenced}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("markdown blok tozalanib ishladi", result.get("post_text") == "Blok ichidagi", str(result)[:100])

    await ai_agent.close_ai_session()
    await runner.cleanup()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha AI mock-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    asyncio.run(main())
