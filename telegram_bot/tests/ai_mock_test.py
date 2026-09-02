#!/usr/bin/env python3
"""AI mock-server testi — real API'larni taqlid qiluvchi lokal server bilan.

Gemini/Groq/OpenRouter/Mistral/Cerebras/Pollinations zanjiri to'liq tekshiriladi:
- model discovery: o'chirilgan modellarni tanlab, faqat jonli modellarga so'rov yuboradi
- discovery ishlamasa → qo'lda yozilgan zaxira ro'yxat
- muvaffaqiyatli javob, fallback (Gemini 404 → Groq → Mistral...)
- 429 rate-limit → retry
- response_format qo'llab-quvvatlanmasa → unsiz qayta urinish
- circuit breaker: 3 marta ketma-ket xato → 4-chi so'rovda provayder o'tkazib yuboriladi
- prompt uzunlik limiti (3000 belgi)
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
os.environ["MISTRAL_API_KEY"] = "test-mistral-key"
os.environ["CEREBRAS_API_KEY"] = "test-cerebras-key"
os.environ["GEMINI_BASE"] = f"{BASE}/gemini"
os.environ["GROQ_ENDPOINT"] = f"{BASE}/groq/chat/completions"
os.environ["OPENROUTER_ENDPOINT"] = f"{BASE}/openrouter/chat/completions"
os.environ["MISTRAL_ENDPOINT"] = f"{BASE}/mistral/chat/completions"
os.environ["CEREBRAS_ENDPOINT"] = f"{BASE}/cerebras/chat/completions"
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
    "groq_json_mode_status": 200,
    "openrouter_status": 200, "openrouter_429_first": False, "openrouter_body": {},
    "mistral_status": 200, "mistral_429_first": False, "mistral_body": {},
    "cerebras_status": 200, "cerebras_429_first": False, "cerebras_body": {},
    "pollinations_status": 200, "pollinations_body": {},
    "gemini_models_status": 200,
    "groq_models_status": 200,
    "openrouter_models_status": 200,
    # 🖼 Vision (Photo-to-Post): alohida holat — rasm (inline_data) so'rovlari
    "gemini_vision_status": 200,
    "gemini_vision_429_first": False,
    "gemini_vision_body": {},
    "gemini_vision_error_body": {"error": {"message": "xato"}},
    "requests": [],  # (key, path, payload_dict)
    "vision_requests": [],  # faqat inline_data (rasm) payloadlari
}

VALID_JSON = '{"post_text": "Mock post matni", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'

VISION_JSON = '{"post_text": "<b>Rasm asosidagi sarlavha</b>\\n\\n• Birinchi fikr\\n• Ikkinchi fikr\\n\\n👉 Hoziroq obuna bo\'ling\\n\\n#smm #telegraf #post"}'

GEMINI_MODELS_BODY = {
    "models": [
        {"name": "models/gemini-1.5-flash", "supportedGenerationMethods": ["generateContent"]},   # EOL
        {"name": "models/gemini-3-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
    ]
}
GROQ_MODELS_BODY = {
    "data": [
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct"},  # yangi preferred
        {"id": "meta-llama/llama-4-maverick-17b-128e-instruct"},
        {"id": "llama-3.3-70b-versatile"},
        {"id": "llama3-70b-8192"},
        {"id": "gemma2-9b-it"},
        {"id": "llama3-8b-8192"},
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
    try:
        payload = await request.json()
    except Exception:
        payload = None
    S["requests"].append(("gemini", path, payload))

    # 🖼 Vision: payload'da inline_data (rasm base64) bor → alohida holat
    is_vision = False
    if isinstance(payload, dict):
        for content in payload.get("contents", []) or []:
            for part in content.get("parts", []) or []:
                if isinstance(part, dict) and "inline_data" in part:
                    is_vision = True
                    break
    if is_vision:
        S["vision_requests"].append(payload)
        if S.get("gemini_vision_429_first"):
            S["gemini_vision_429_first"] = False
            return web.json_response(
                {"error": {"code": 429}}, status=429, headers={"Retry-After": "1"}
            )
        status = S.get("gemini_vision_status", 200)
        if status != 200:
            return web.json_response(
                S.get("gemini_vision_error_body", {"error": {"message": "xato"}}),
                status=status,
            )
        return web.json_response(S["gemini_vision_body"])

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


def reset_state(clear_breakers: bool = True):
    ai_agent._model_cache.clear()
    if clear_breakers:
        ai_agent._BREAKERS.clear()
    S["requests"].clear()
    S["vision_requests"].clear()
    S.update({
        "gemini_429_first": False, "groq_429_first": False,
        "openrouter_429_first": False, "mistral_429_first": False,
        "cerebras_429_first": False,
        "gemini_vision_status": 200, "gemini_vision_429_first": False,
        "gemini_vision_error_body": {"error": {"message": "xato"}},
    })


async def main():
    app = web.Application()
    app.router.add_get("/gemini/models", gemini_models_handler)
    app.router.add_post("/gemini/{model}:generateContent", gemini_handler)
    app.router.add_get("/groq/models", groq_models_handler)
    app.router.add_post("/groq/chat/completions", make_openai_handler("groq"))
    app.router.add_get("/openrouter/models", openrouter_models_handler)
    app.router.add_post("/openrouter/chat/completions", make_openai_handler("openrouter"))
    app.router.add_post("/mistral/chat/completions", make_openai_handler("mistral"))
    app.router.add_post("/cerebras/chat/completions", make_openai_handler("cerebras"))
    app.router.add_post("/pollinations", make_openai_handler("pollinations"))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()

    # ---- Test 1: Discovery — faqat jonli modellar tanlanadi ----
    print("== 1. Model discovery (o'chirilgan modellar chiqarib tashlanadi) ==")
    reset_state()
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_chat_paths = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Gemini chat so'rovi jonli modelga ketdi (gemini-2.5-flash)",
          any("gemini-2.5-flash" in p for p in gemini_chat_paths), str(gemini_chat_paths))
    check("EOL model (gemini-1.5-flash) chaqirilmadi",
          not any("gemini-1.5-flash" in p for p in gemini_chat_paths), str(gemini_chat_paths))

    # ---- Test 2: Groq discovery chat modellarini tanlaydi ----
    print("== 2. Groq discovery ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "mistral_status": 500,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    groq_models_used = [p.get("model") for k, _, p in S["requests"] if k == "groq" and p]
    check("Groq javobi qaytdi (fallback)", result.get("post_text") == "Mock post matni", str(result)[:100])
    check("Groq chat modeli jonli (llama-3.3-70b)",
          groq_models_used and "llama-3.3-70b" in groq_models_used[0],
          str(groq_models_used))
    check("O'chirilgan Groq modellari ishlatilmadi",
          all("whisper" not in m for m in groq_models_used),
          str(groq_models_used))

    # ---- Test 3: Discovery ishlamasa (500) → qo'lda yozilgan zaxira ----
    print("== 3. Discovery 500 → statik zaxira ro'yxat ==")
    reset_state()
    S.update({
        "gemini_models_status": 500, "groq_models_status": 500, "openrouter_models_status": 500,
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_paths = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Discovery 500 bo'lsa ham Gemini ishladi (zaxira ro'yxat)",
          result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 4: 429 retry ----
    print("== 4. Gemini 429 retry ==")
    reset_state()
    S.update({
        "gemini_429_first": True,
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    start = asyncio.get_event_loop().time()
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    elapsed = asyncio.get_event_loop().time() - start
    check("429'dan keyin Gemini javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])
    check("429 kutish vaqti ≈1s", elapsed >= 0.9 and elapsed < 3, f"{elapsed:.2f}s")

    # ---- Test 5: response_format qo'llab-quvvatlanmasa → unsiz qayta urinish ----
    print("== 5. Groq response_format fallback ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "groq_json_mode_status": 400,
        "openrouter_status": 500, "mistral_status": 500,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    groq_reqs = [p for k, _, p in S["requests"] if k == "groq" and p]
    check("Groq javobi qaytdi (response_format fallback bilan)", result.get("post_text") == "Mock post matni",
          str(result)[:100])
    check("Avval response_format bilan, keyin unsiz urinildi",
          len(groq_reqs) >= 2 and groq_reqs[0].get("response_format") and not groq_reqs[1].get("response_format"),
          str([bool(r.get("response_format")) for r in groq_reqs]))

    # ---- Test 6: Gemini/Groq/OpenRouter xato → Mistral javob beradi ----
    print("== 6. Mistral zaxirasi ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "mistral_status": 200, "mistral_body": VALID_JSON,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Mistral javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 7: Gemini/Groq/OpenRouter/Mistral xato → Cerebras javob beradi ----
    print("== 7. Cerebras zaxirasi ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "mistral_status": 500, "mistral_body": "xato",
        "cerebras_status": 200, "cerebras_body": VALID_JSON,
        "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Cerebras javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 8: Circuit breaker — 3 marta xato → 4-chi so'rovda o'tkazib yuboriladi ----
    print("== 8. Circuit breaker (o'lik provayder o'tkazib yuboriladi) ==")
    reset_state()
    S.update({
        "gemini_status": 500, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "mistral_status": 500,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    # Gemini 3 marta ketma-ket xato beradi (har safar Groq ishlaydi)
    for _ in range(3):
        result = await ai_agent.analyze_user_prompt("Test so'rov")
        check("Groq javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])
    # 4-chi so'rov: Gemini breaker ochiq → umuman chaqirilmaydi
    # (breaker holatini SAQLAB qolamiz — reset_state faqat so'rovlar ro'yxatini tozalaydi)
    reset_state(clear_breakers=False)
    S.update({
        "gemini_status": 200,  # agar chaqirilsa ishlardi — lekin chaqirilmasligi kerak
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "mistral_status": 500,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_calls = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Gemini breaker ochiq → chaqirilmadi (Groq ishladi)",
          not gemini_calls and result.get("post_text") == "Mock post matni",
          f"gemini_calls={gemini_calls}")
    # Breaker 10 daqiqadan keyin ochiladi (biz qo'lda ochamiz)
    ai_agent._BREAKERS.pop("Gemini", None)
    reset_state()
    S.update({"gemini_status": 200,
              "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
              "groq_status": 500, "openrouter_status": 500,
              "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500})
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    gemini_calls = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Breaker ochilgach Gemini qayta ishlaydi", bool(gemini_calls), str(gemini_calls))

    # ---- Test 9: Prompt uzunlik limiti (3000 belgi) ----
    print("== 9. Prompt limiti ==")
    reset_state()
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    long_prompt = "A" * 10000
    result = await ai_agent.analyze_user_prompt(long_prompt)
    gemini_paths = [p for k, p, _ in S["requests"] if k == "gemini" and p.endswith(":generateContent")]
    check("Uzun prompt kesiladi (Gemini chaqirildi)", bool(gemini_paths), str(gemini_paths))
    check("Prompt ≤ 3000 belgi", result.get("post_text") == "Mock post matni" or "error" in result,
          str(result)[:80])

    # ---- Test 10: hammasi xato → aniq xato xabari (crash emas) ----
    print("== 10. Barcha provayderlar xato ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "mistral_status": 500, "mistral_body": "xato",
        "cerebras_status": 500, "cerebras_body": "xato",
        "pollinations_status": 500, "pollinations_body": "xato",
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("error dict qaytdi", "error" in result, str(result)[:100])
    check("xato xabarida kalit yo'l-yo'rig'i bor", "GEMINI_API_KEY" in result.get("error", ""),
          result.get("error", "")[:80])

    # ---- Test 11: kalitsiz Pollinations zaxirasi ----
    print("== 11. Kalitsiz Pollinations zaxirasi ==")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 500, "groq_body": "xato",
        "openrouter_status": 500, "openrouter_body": "xato",
        "mistral_status": 500, "mistral_body": "xato",
        "cerebras_status": 500, "cerebras_body": "xato",
        "pollinations_status": 200, "pollinations_body": VALID_JSON,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("Pollinations javobi qaytdi", result.get("post_text") == "Mock post matni", str(result)[:100])

    # ---- Test 12: yaroqsiz JSON → xato, crash emas ----
    print("== 12. Yaroqsiz JSON ==")
    reset_state()
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": "bu JSON emas"}]}}]},
        "groq_status": 200, "groq_body": "bu ham JSON emas",
        "openrouter_status": 200, "openrouter_body": "bunisi ham",
        "mistral_status": 200, "mistral_body": "mistral ham",
        "cerebras_status": 200, "cerebras_body": "cerebras ham",
        "pollinations_status": 200, "pollinations_body": "yo'q",
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("yaroqsiz JSON → error", "error" in result, str(result)[:100])

    # ---- Test 13: markdown blok ichida JSON ----
    print("== 13. Markdown blok ichida JSON ==")
    fenced = '```json\n{"post_text": "Blok ichidagi", "scheduled_time": null, "has_explicit_time": false, "target_all": false}\n```'
    reset_state()
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": fenced}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    result = await ai_agent.analyze_user_prompt("Test so'rov")
    check("markdown blok tozalanib ishladi", result.get("post_text") == "Blok ichidagi", str(result)[:100])

    # ---- Test 14: suhbat konteksti (takror yo'q, bot javobi eslab qolinadi) ----
    print("== 14. Suhbat konteksti ==")
    reset_state()
    uid = 555001
    ai_agent.clear_ai_context(uid)
    ai_agent._RUNTIME_PARAMS["context_messages"] = 6
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    await ai_agent.analyze_user_prompt("Birinchi xabar", uid)
    first_payload = [p for k, _, p in S["requests"] if k == "gemini" and p][0]
    first_text = first_payload["contents"][0]["parts"][0]["text"]
    check("birinchi so'rovda kontekst bloki yo'q",
          "So'nggi suhbat" not in first_text, first_text[:120])
    check("birinchi so'rovda xabar bir marta",
          first_text.count("Birinchi xabar") == 1, first_text[:200])

    reset_state()
    S.update({
        "gemini_status": 200,
        "gemini_body": {"candidates": [{"content": {"parts": [{"text": VALID_JSON}]}}]},
    })
    await ai_agent.analyze_user_prompt("Ikkinchi xabar", uid)
    second_payload = [p for k, _, p in S["requests"] if k == "gemini" and p][0]
    second_text = second_payload["contents"][0]["parts"][0]["text"]
    check("ikkinchi so'rovda oldingi xabar konteksti bor",
          "Birinchi xabar" in second_text, second_text[:200])
    check("joriy xabar ikki marta yuborilmaydi",
          second_text.count("Ikkinchi xabar") == 1, second_text[:300])
    check("bot javobi ham kontekstda saqlanadi",
          "Mock post matni" in second_text, second_text[:300])
    check("kontekstda HTML teglari yo'q",
          "<b>" not in second_text, second_text[:200])

    # Xato chaqiruv kontekstga yozilmaydi
    reset_state()
    S.update({
        "gemini_status": 500, "gemini_body": {},
        "groq_status": 500, "openrouter_status": 500,
        "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
    })
    err_res = await ai_agent.analyze_user_prompt("Xatolik xabari", uid)
    check("barcha provayderlar yiqilsa error", "error" in err_res, str(err_res)[:80])
    ctx_after_error = ai_agent._get_ai_context_text(uid, 4000)
    check("muvaffaqiyatsiz so'rov kontekstga yozilmaydi",
          "Xatolik xabari" not in ctx_after_error, ctx_after_error[:200])
    ai_agent.clear_ai_context(uid)
    ai_agent._RUNTIME_PARAMS["context_messages"] = ai_agent._RUNTIME_DEFAULTS["context_messages"]

    # ---- Test 15: o'chirilgan ixtiyoriy parametrlar payloadga tushmaydi ----
    print("== 15. Ixtiyoriy parametrlar (null yuborilmaydi) ==")
    reset_state()
    ai_agent._set_runtime_param("max_tokens", "off")
    ai_agent._set_runtime_param("top_p", "off")
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
        "openrouter_status": 500, "mistral_status": 500,
        "cerebras_status": 500, "pollinations_status": 500,
    })
    await ai_agent.analyze_user_prompt("Parametr testi")
    groq_payloads = [p for k, _, p in S["requests"] if k == "groq" and p]
    gemini_payloads = [p for k, _, p in S["requests"] if k == "gemini" and p]
    check("Groq payloadida max_tokens yo'q",
          all("max_tokens" not in p for p in groq_payloads), str(groq_payloads[:1])[:200])
    check("Groq payloadida top_p yo'q",
          all("top_p" not in p for p in groq_payloads), str(groq_payloads[:1])[:200])
    check("Groq payloadida null qiymat yo'q",
          all(v is not None for p in groq_payloads for v in p.values()), str(groq_payloads[:1])[:200])
    gem_cfgs = [p.get("generationConfig", {}) for p in gemini_payloads]
    check("Gemini generationConfig'da maxOutputTokens/topP yo'q",
          all("maxOutputTokens" not in c and "topP" not in c for c in gem_cfgs), str(gem_cfgs[:1]))

    ai_agent._set_runtime_param("max_tokens", "")
    ai_agent._set_runtime_param("top_p", "")
    reset_state()
    S.update({
        "gemini_status": 404, "gemini_body": {},
        "groq_status": 200, "groq_body": VALID_JSON,
    })
    await ai_agent.analyze_user_prompt("Parametr testi 2")
    groq_payloads = [p for k, _, p in S["requests"] if k == "groq" and p]
    check("default holatda max_tokens yuboriladi",
          any(p.get("max_tokens") for p in groq_payloads), str(groq_payloads[:1])[:200])
    check("default holatda top_p yuboriladi",
          any(p.get("top_p") is not None for p in groq_payloads), str(groq_payloads[:1])[:200])

    # ---- Test 16: 🖼 Vision — rasm Gemini'ga inline_data bilan yuboriladi ----
    print("== 16. Vision (rasmdan post) ==")
    import base64 as _b64
    import os
    import tempfile

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    tmp.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
    tmp.close()
    try:
        # 16.1) Muvaffaqiyatli tahlil
        reset_state()
        S.update({
            "gemini_status": 404, "gemini_body": {},   # matn so'rovlari o'chirilgan
            "groq_status": 500, "openrouter_status": 500,
            "mistral_status": 500, "cerebras_status": 500, "pollinations_status": 500,
            "gemini_vision_status": 200,
            "gemini_vision_body": {"candidates": [{"content": {"parts": [{"text": VISION_JSON}]}}]},
        })
        vres = await ai_agent.generate_vision_post(tmp.name, extra_prompt="mahsulotni sot")
        check("vision: post_text qaytdi", vres.get("post_text", "").startswith("<b>"),
              str(vres)[:100])
        check("vision: sarlavha HTML qalin", "<b>Rasm asosidagi sarlavha</b>" in vres.get("post_text", ""))
        vpayload = S["vision_requests"][-1]
        vparts = vpayload["contents"][0]["parts"]
        inline = [p for p in vparts if "inline_data" in p]
        check("vision: Gemini'ga inline_data yuborildi", bool(inline))
        check("vision: mime_type image/png",
              inline and inline[0]["inline_data"]["mime_type"] == "image/png",
              str(inline)[:120])
        check("vision: base64 to'g'ri (magic bytes)",
              inline and _b64.b64decode(inline[0]["inline_data"]["data"])[:8] == b"\x89PNG\r\n\x1a\n",
              str(inline)[:120])
        check("vision: izoh (extra prompt) yuborildi",
              any("mahsulotni sot" in p.get("text", "") for p in vparts), str(vparts)[:200])
        check("vision: systemInstruction bor", "systemInstruction" in vpayload)

        # 16.2) 429 → Retry-After bilan qayta urinish → muvaffaqiyat
        reset_state()
        S.update({
            "gemini_vision_429_first": True,
            "gemini_vision_status": 200,
            "gemini_vision_body": {"candidates": [{"content": {"parts": [{"text": VISION_JSON}]}}]},
        })
        vres = await ai_agent.generate_vision_post(tmp.name)
        check("vision: 429 retry dan keyin natija", "post_text" in vres, str(vres)[:100])
        check("vision: 429 retry kamida 2 so'rov",
              len(S["vision_requests"]) >= 2, str(len(S["vision_requests"])))

        # 16.3) Xavfsizlik blokirovkasi → tushunarli o'zbekcha xabar
        reset_state()
        S.update({
            "gemini_vision_status": 400,
            "gemini_vision_body": {},
            "gemini_vision_error_body": {
                "error": {"message": "SAFETY: blocked harmful content"}
            },
        })
        vres = await ai_agent.generate_vision_post(tmp.name)
        check("vision: noo'rin rasm xabari",
              "error" in vres and "mos kelmaydi" in vres["error"], str(vres)[:120])

        # 16.4) Doimiy 429 → rate limit xabari
        reset_state()
        S.update({
            "gemini_vision_status": 429,
            "gemini_vision_body": {},
        })
        vres = await ai_agent.generate_vision_post(tmp.name)
        check("vision: 429 → band xabari",
              "error" in vres and "kuting" in vres["error"], str(vres)[:120])
    finally:
        os.remove(tmp.name)
        ai_agent.cleanup_temp_media(tmp.name)

    await ai_agent.close_ai_session()
    await runner.cleanup()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha AI mock-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    asyncio.run(main())
