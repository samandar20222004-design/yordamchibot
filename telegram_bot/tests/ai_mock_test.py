#!/usr/bin/env python3
"""AI mock-server testi — real API'larni taqlid qiluvchi lokal server bilan.

Gemini/Groq/OpenRouter/Pollinations zanjiri to'liq tekshiriladi:
- model discovery: o'chirilgan modellarni tanlab, faqat jonli modellarga so'rov yuboradi
- discovery ishlamasa → qo'lda yozilgan zaxira ro'yxat
- muvaffaqiyatli javob, fallback (Gemini 404 → Groq)
- 429 rate-limit → retry
- response_format qo'llab-quvvatlanmasa → unsiz qayta urinish
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
os.environ["GROQ_ENDPOINT"] = f"{BASE}/groq/chat/completions"
os.environ["OPENROUTER_ENDPOINT"] = f"{BASE}/openrouter/chat/completions"
os.environ["POLLINATIONS_ENDPOINT"] = f"{BASE}/pollinations"
# Discovery endpointlari (mock server)
os.environ["GEMINI_MODELS_ENDPOINT"] = f"{BASE}/gemini/models"
os.environ["GROQ_MODELS_ENDPOINT"] = f"{BASE}/groq/models"
os.environ["OPENROUTER_MODELS_ENDPOINT"] = f"{BASE}/openrouter/models"

from aiohttp import web
from utils import ai_agent

# ---- Mock server holati ----
S = {
    "gemini_status": 200, "gemini_429_first": False, "gemini_body": {},
    "groq_status": 200, "groq_429_first": False, "groq_body": {},
    "groq_json_mode_status": 200,   # response_format bilan javob
    "openrouter_status": 200, "openrouter_429_first": False, "openrouter_body": {},
    "pollinations_status": 200, "pollinations_body": {},
    "gemini_models_status": 200,
    "groq_models_status": 200,
    "openrouter_models_status": 200,
    "requests": [],  # (key, path, payload_dict)
}

VALID_JSON = '{"post_text": "Mock post matni", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'

# Discovery javoblari: eski (o'chirilgan) modellar + yangi jonli modellar
GEMINI_MODELS_BODY = {
    "models": [
        {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},   # EOL
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},           # chat emas
    ]
}
GROQ_MODELS_BODY = {
    "data": [
        {"id": "gemma2-9b-it"},                    # decommissioned
        {"id": "llama3-8b-8192"},                  # decommissioned
        {"id": "openai/gpt-oss-120b"},
        {"id": "openai/gpt-oss-20b"},
        {"id": "qwen/qwen3.6-27b"},
        {"id": "whisper-large-v3"},                # chat emas — filtrlanishi kerak
    ]
}
OPENROUTER_MODELS_BODY = {
    "data": [
        {"id": "meta-llama/llama-3.3-70b-instruct:free"},
        {"id": "openai/gpt-4o"},                   # :free emas — filtrlanishi kerak
        {"id": "qwen/qwen-2.5-7b-instruct:free"},
    ]
}


async def gemini_models_handler(request):
    if S.get("gemini_models_status", 200) != 200:
        return web.json_response({"error": "xato"}, status=S["gemini_models_status"])
    return web.json_response(GEMINI_MODELS_BODY)


async def groq_models_handler(request):
    if S.get("groq_models_status", 200) != 200:
        return web.json_response({"error": "xato"}, status=S["groq_models_status"])
    return web.json_response(GROQ_MODELS_BODY)


async def openrouter_models_handler(request):
    if S.get("openrouter_models_status", 200) != 200:
        return web.json_response({"error": "xato"}, status=S["openrouter_models_status"])
    return web.json_response(OPENROUTER_MODELS_BODY)


async def gemini_handler(request):
    path = request.rel_url.path
    S["requests"].append(("gemini", path, None))
    if S.get("gemini_429_first"):
        S["gemini_429_first"] = False
        return web.json_response({"error": {"code": 429}}, status=429, headers={"Retry-After": "1"})
    status = S.get("gemini_status", 200)
    if status != 200:
        return web.json_response({"error": {"message": "model topilmadi"}}, status=status)
    return web.json_response(S["gemini_body"])


def make_openai_handler(key):
    async def handler(request):
        payload = await request.json()
        S["requests"].append((key, request.rel_url.path, payload))
        if S.get(f"{key}_429_first"):
            S[f"{key}_429_first"] = False
            return web.json_response({"error": {"code": 429}}, status=429, headers={"Retry-After": "1"})
        status = S.get(f"{key}_status", 200)
        if status != 200:
            return web.json_response({"error": {"message": "xato"}}, status=status)
        # response_format bilan so'rov maxsus javob olishi mumkin
        if key == "groq" and payload.get("response_format"):
            json_status = S.get("groq_json_mode_status", 200)
            if json_status != 200:
                return web.json_response(
                    {"error": {"message": "Unsupported parameter: 'response_format' is not supported with this model"}},
                    status=json_status,
                )
        body = S.get(f"{key}_body", VALID_JSON)
        return web.json_response({"choices": [{"message": {"content": body}}]})
    return handler


async def main():
    app = web.Application()
    app.router.add_get("/gemini/models", gemini_models_handler)
    app.router.add_post("/gemini/{model}:generateContent", gemini_handler)
    app.router.add_get("/groq/models", groq_models_handler)
    app.router.add_post("/groq/chat/completions", make_openai_handler("groq"))
    app.router.add_get("/openrouter/models", openrouter_models_handler)
    app.router.add_post("/openrouter/chat/completions", make_openai_handler("openrouter"))
    app.router.add_post("/pollinations", make_openai_handler("pollinations"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()

    # ---- Test 1: Discovery — faqat jonli modellar tanlanadi ----
    print("== 1. Model discovery (o'chirilgan modellar chiqarib tashlanadi) ==")
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_chat_paths = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Gemini chat so'rovi jonli modelga ketdi (gemini-3-flash)",
          any("gemini-3-flash" in p for p in gemini_chat_paths), str(gemini_chat_paths))
    check("EOL model (gemini-1.5-flash) chaqirilmadi",
          not any("gemini-1.5-flash" in p for p in gemini_chat_paths), str(gemini_chat_paths))

    # ---- Test 2: Groq discovery chat modellarini tanlaydi ----
    print("== 2. Groq discovery ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    groq_models_used = [p.get("model") for k, _, p in S["requests"] if k == "groq" and p]
    check("Groq javobi qaytdi (fallback)", result.get("post_text") == "Mock post matni", str(result)[:100])
    check("Groq chat modeli jonli (gpt-oss-120b)", groq_models_used and groq_models_used[0] == "openai/gpt-oss-120b",
          str(groq_models_used))
    check("O'chirilgan Groq modellari ishlatilmadi",
          all("gemma2-9b-it" not in m and "llama3-8b-8192" not in m for m in groq_models_used),
          str(groq_models_used))
    check("Whisper (audio) modeli filtrlangan",
          all("whisper" not in m for m in groq_models_used), str(groq_models_used))

    # ---- Test 3: Discovery ishlamasa (500) → qo'lda yozilgan zaxira ----
    print("== 3. Discovery 500 → statik zaxira ro'yxat ==")
    S.update({
        "gemini_models_status": 500, "groq_models_status": 500, "openrouter_models_status": 500,
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    # Discovery keshini tozalaymiz (endi 500 qaytadi)
    ai_agent._model_cache.clear()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_paths = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Discovery 500 bo'lsa ham Gemini ishladi (zaxira ro'yxat)",
          result.get("post_text") == "Mock post matni", str(result)[:100])
    check("Zaxira ro'yxatdagi model ishlatildi (gemini-3-flash)",
          any("gemini-3-flash" in p for p in gemini_paths), str(gemini_paths))

    # ---- Test 4: 429 retry ----
    print("== 4. Gemini 429 retry ==")
    S.update({
        "gemini_429_first": True,
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    ai_agent._model_cache.clear()
    start = asyncio.get_event_loop().time()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    elapsed = asyncio.get_event_loop().time() - start
    check("429'dan keyin Gemini javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])
    check("429 kutish vaqti ≈1s", elapsed >= 0.9 and elapsed < 3, f"{elapsed:.2f}s")

    # ---- Test 5: response_format qo'llab-quvvatlanmasa → unsiz qayta urinish ----
    print("== 5. Groq response_format fallback ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "groq_json_mode_status": 400,
        "openrouter_status": 500, "pollinations_status": 500,
    })
    ai_agent._model_cache.clear()
    S["requests"].clear()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    groq_reqs = [p for k, _, p in S["requests"] if k == "groq" and p]
    check("Groq javobi qaytdi (response_format fallback bilan)", result.get("post_text") == "Mock post matni",
          str(result)[:100])
    check("Avval response_format bilan, keyin unsiz urinildi",
          len(groq_reqs) >= 2 and groq_reqs[0].get("response_format") and not groq_reqs[1].get("response_format"),
          str([bool(r.get("response_format")) for r in groq_reqs]))

    # ---- Test 6: hammasi xato → aniq xato xabari (crash emas) ----
    print("== 6. Barcha provayderlar xato ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "pollinations_status": 500, "pollinations_body": "xato",
    })
    ai_agent._model_cache.clear()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("error dict qaytdi", "error" in result, str(result)[:100])
    check("xato xabarida kalit bo'yicha yo'l-yo'riq bor",
          "GEMINI_API_KEY" in result.get("error", ""), result.get("error", "")[:80])

    # ---- Test 7: kalitsiz Pollinations zaxirasi ----
    print("== 7. Kalitsiz Pollinations zaxirasi ==")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "pollinations_status": 200, "pollinations_body": VALID_JSON,
    })
    ai_agent._model_cache.clear()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Pollinations javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 8: yaroqsiz JSON → xato, crash emas ----
    print("== 8. Yaroqsiz JSON ==")
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": "bu JSON emas"}]}}]},
        "groq_status": 200, "groq_body": "bu ham JSON emas",
        "openrouter_status": 200, "openrouter_body": "bunisi ham",
        "pollinations_status": 200, "pollinations_body": "yo'q",
    })
    ai_agent._model_cache.clear()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("yaroqsiz JSON → error", "error" in result, str(result)[:100])

    # ---- Test 9: markdown blok ichida JSON ----
    print("== 9. Markdown blok ichida JSON ==")
    fenced = '```json\n{"post_text": "Blok ichidagi", "scheduled_time": null, "has_explicit_time": false, "target_all": false}\n```'
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": fenced}]}}]},
        "groq_status": 500, "openrouter_status": 500, "pollinations_status": 500,
    })
    ai_agent._model_cache.clear()
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
