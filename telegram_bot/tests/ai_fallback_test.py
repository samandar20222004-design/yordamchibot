#!/usr/bin/env python3
"""AI Multi-Provider Fallback test — 4-BOSQICH (services/ai_service.py).

Yagona provayderlar boshqaruvi va avtomatik fallback zanjiri tekshiriladi:
  1. Gemini (Primary)
  2. Groq   (Secondary Fallback — llama-3 / mixtral)
  3. OpenRouter (Tertiary Fallback)
  + kengaytirilgan zaxira (Mistral, Cerebras, SambaNova, Cloudflare, Pollinations)

Tekshiriladigan ssenarilar:
  1) Gemini muvaffaqiyatli ishlaganda to'g'ridan-to'g'ri natija qaytadi
     (boshqa provayderlar umuman chaqirilmaydi).
  2) Gemini 500 xato berganda Groq fallback muvaffaqiyatli ulanadi
     (foydalanuvchiga xatolik ko'rsatilmasdan).
  3) Gemini qat'iy timeout (10s chegarasi) ichida javob bermaganda
     Groq'ga o'tiladi.
  4) Gemini 429 (rate limit) qaytarganda Groq'ga o'tiladi.
  5) Gemini va Groq ishlamay qolganda OpenRouter'ga o'tiladi.
  6) Barcha provayderlar o'chganda: toza xato xabari qaytadi,
     foydalanuvchining kunlik kvotasi yechilmaydi (quota_safe +
     handler balini qaytaradi, sanakchini oshirmaydi).
  7) Barcha provayderlar timeout berganda — xushmuomala timeout xabari.
  8) Zanjir tartibi (AI_PROVIDER_CHAIN env), provayder darajalari va
     orkestrator statusi.

Ishga tushirish:
    cd telegram_bot && python tests/ai_fallback_test.py
"""
import os
import sys
import asyncio
import socket
from pathlib import Path
from types import SimpleNamespace

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
os.environ["ADMIN_ID"] = "1"
os.environ["DATABASE_URL"] = "postgresql://u:p@localhost:5432/x"
os.environ["GEMINI_API_KEY"] = "test-gemini-key"
os.environ["GROQ_API_KEY"] = "test-groq-key"
os.environ["OPENROUTER_API_KEY"] = "test-or-key"
os.environ["MISTRAL_API_KEY"] = "test-mistral-key"
os.environ["CEREBRAS_API_KEY"] = "test-cerebras-key"
os.environ["SAMBANOVA_API_KEY"] = "test-snb-key"
# Cloudflare: account_id BEYOQ — provider o'zi "available emas" deb belgilanadi
os.environ["CLOUDFLARE_API_TOKEN"] = "test-cf-token"
os.environ["CLOUDFLARE_ACCOUNT_ID"] = ""

# Barcha endpointlarni lokal mock serverga yo'naltirish
os.environ["GEMINI_BASE"] = f"{BASE}/gemini"
os.environ["GEMINI_MODELS_ENDPOINT"] = f"{BASE}/gemini/models"
os.environ["GROQ_ENDPOINT"] = f"{BASE}/groq/chat/completions"
os.environ["GROQ_MODELS_ENDPOINT"] = f"{BASE}/groq/models"
os.environ["OPENROUTER_ENDPOINT"] = f"{BASE}/openrouter/chat/completions"
os.environ["OPENROUTER_MODELS_ENDPOINT"] = f"{BASE}/openrouter/models"
os.environ["MISTRAL_ENDPOINT"] = f"{BASE}/mistral/chat/completions"
os.environ["CEREBRAS_ENDPOINT"] = f"{BASE}/cerebras/chat/completions"
os.environ["SAMBANOVA_ENDPOINT"] = f"{BASE}/sambanova/chat/completions"
os.environ["POLLINATIONS_ENDPOINT"] = f"{BASE}/pollinations"
# Discovery tezligi uchun qisqacha
os.environ["AI_MODEL_DISCOVERY"] = "1"

from aiohttp import web  # noqa: E402
from utils import ai_agent  # noqa: E402
from services import ai_service  # noqa: E402

# ---- Javob tanasi (har bir provayderga xos) ----
GEMINI_JSON = '{"post_text": "Gemini post", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'
GROQ_JSON = '{"post_text": "Groq post", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'
OR_JSON = '{"post_text": "OpenRouter post", "scheduled_time": null, "has_explicit_time": false, "target_all": false}'

GEMINI_MODELS_BODY = {
    "models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-lite", "supportedGenerationMethods": ["generateContent"]},
    ],
}
GROQ_MODELS_BODY = {"data": [{"id": "llama-3.3-70b-versatile"}, {"id": "llama3-70b-8192"}]}
OR_MODELS_BODY = {"data": [{"id": "meta-llama/llama-3.3-70b-instruct:free"}]}

# ---- Mock server holati ----
S = {
    "gemini_status": 200, "gemini_sleep": 0,
    "groq_status": 200, "groq_sleep": 0,
    "openrouter_status": 200, "openrouter_sleep": 0,
    "mistral_status": 200, "mistral_sleep": 0,
    "cerebras_status": 200, "cerebras_sleep": 0,
    "sambanova_status": 200, "sambanova_sleep": 0,
    "pollinations_status": 200, "pollinations_sleep": 0,
    "requests": [],  # (provider, path, payload)
}


def reset_state(clear_breakers: bool = True):
    ai_agent._model_cache.clear()
    if clear_breakers:
        ai_agent._BREAKERS.clear()
    S["requests"].clear()
    S.update({
        "gemini_status": 200, "gemini_sleep": 0,
        "groq_status": 200, "groq_sleep": 0,
        "openrouter_status": 200, "openrouter_sleep": 0,
        "mistral_status": 200, "mistral_sleep": 0,
        "cerebras_status": 200, "cerebras_sleep": 0,
        "sambanova_status": 200, "sambanova_sleep": 0,
        "pollinations_status": 200, "pollinations_sleep": 0,
    })


async def gemini_models_handler(request):
    return web.json_response(GEMINI_MODELS_BODY)


async def groq_models_handler(request):
    return web.json_response(GROQ_MODELS_BODY)


async def openrouter_models_handler(request):
    return web.json_response(OR_MODELS_BODY)


async def gemini_handler(request):
    S["requests"].append(("gemini", request.rel_url.path, None))
    try:
        if S["gemini_sleep"]:
            await asyncio.sleep(S["gemini_sleep"])
        if S["gemini_status"] != 200:
            return web.json_response({"error": {"message": "xato"}}, status=S["gemini_status"])
        return web.json_response(
            {"candidates": [{"content": {"parts": [{"text": GEMINI_JSON}]}}]}
        )
    except Exception:
        pass


def make_openai_handler(key, json_body):
    async def handler(request):
        S["requests"].append((key, request.rel_url.path, None))
        try:
            if S[f"{key}_sleep"]:
                await asyncio.sleep(S[f"{key}_sleep"])
            if S[f"{key}_status"] != 200:
                return web.json_response({"error": {"message": "xato"}}, status=S[f"{key}_status"])
            return web.json_response({"choices": [{"message": {"content": json_body}}]})
        except Exception:
            pass
    return handler


def req_count(provider: str) -> int:
    return sum(1 for k, _, _ in S["requests"] if k == provider)


async def main():
    app = web.Application()
    app.router.add_get("/gemini/models", gemini_models_handler)
    app.router.add_post("/gemini/{model}:generateContent", gemini_handler)
    app.router.add_get("/groq/models", groq_models_handler)
    app.router.add_post("/groq/chat/completions", make_openai_handler("groq", GROQ_JSON))
    app.router.add_get("/openrouter/models", openrouter_models_handler)
    app.router.add_post("/openrouter/chat/completions", make_openai_handler("openrouter", OR_JSON))
    app.router.add_post("/mistral/chat/completions", make_openai_handler("mistral", GROQ_JSON))
    app.router.add_post("/cerebras/chat/completions", make_openai_handler("cerebras", GROQ_JSON))
    app.router.add_post("/sambanova/chat/completions", make_openai_handler("sambanova", GROQ_JSON))
    app.router.add_post("/pollinations", make_openai_handler("pollinations", GROQ_JSON))

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()

    old_total = ai_service.AI_PROVIDER_TOTAL_TIMEOUT
    old_retries = ai_agent.MAX_429_RETRIES

    try:
        # ------------------------------------------------------------
        print("== 1. Gemini muvaffaqiyatli → to'g'ridan-to'g'ri natija ==")
        reset_state()
        S.update({"groq_status": 500, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        check("Gemini javobi qaytdi", result.get("post_text") == "Gemini post", str(result)[:120])
        check("'provider' maydoni: Gemini", result.get("provider") == "Gemini", str(result)[:120])
        check("provayder zanjiri: [Gemini]", result.get("provider_chain") == ["Gemini"],
              str(result.get("provider_chain")))
        check("xatolik ko'rsatilmadi", "error" not in result, str(result)[:120])
        check("Groq umuman chaqirilmadi", req_count("groq") == 0, str(req_count("groq")))
        check("OpenRouter umuman chaqirilmadi", req_count("openrouter") == 0,
              str(req_count("openrouter")))

        # ------------------------------------------------------------
        print("== 2. Gemini 500 → Groq fallback (xatoliksiz) ==")
        reset_state()
        S.update({"gemini_status": 500, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        check("Groq javobi qaytdi", result.get("post_text") == "Groq post", str(result)[:120])
        check("'provider' maydoni: Groq", result.get("provider") == "Groq", str(result)[:120])
        check("zanjir: Gemini → Groq", result.get("provider_chain") == ["Gemini", "Groq"],
              str(result.get("provider_chain")))
        check("foydalanuvchiga xatolik ko'rsatilmadi", "error" not in result, str(result)[:120])
        check("Groq haqiqatan chaqirildi", req_count("groq") >= 1, str(req_count("groq")))

        # ------------------------------------------------------------
        print("== 3. Gemini qat'iy timeout → Groq fallback ==")
        reset_state()
        ai_service.AI_PROVIDER_TOTAL_TIMEOUT = 1.5  # qat'iy chegara (test uchun qisqa)
        S.update({"gemini_sleep": 4, "gemini_status": 200, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        start = asyncio.get_event_loop().time()
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        elapsed = asyncio.get_event_loop().time() - start
        ai_service.AI_PROVIDER_TOTAL_TIMEOUT = old_total
        check("timeout'dan keyin Groq javobi qaytdi",
              result.get("post_text") == "Groq post" and result.get("provider") == "Groq",
              str(result)[:120])
        check("failover tez bo'ldi (<3.5s, Gemini 4s kutilmadi)", elapsed < 3.5, f"{elapsed:.2f}s")
        check("foydalanuvchiga xatolik ko'rsatilmadi", "error" not in result, str(result)[:120])

        # ------------------------------------------------------------
        print("== 4. Gemini 429 (rate limit) → Groq fallback ==")
        reset_state()
        ai_agent.MAX_429_RETRIES = 0  # doimiy 429 → darhol keyingi provayder
        S.update({"gemini_status": 429, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        ai_agent.MAX_429_RETRIES = old_retries
        check("429'dan keyin Groq javobi qaytdi",
              result.get("post_text") == "Groq post" and result.get("provider") == "Groq",
              str(result)[:120])
        check("foydalanuvchiga xatolik ko'rsatilmadi", "error" not in result, str(result)[:120])

        # ------------------------------------------------------------
        print("== 5. Gemini + Groq ishlamasa → OpenRouter ==")
        reset_state()
        S.update({"gemini_status": 500, "groq_status": 500, "openrouter_status": 200,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        check("OpenRouter javobi qaytdi",
              result.get("post_text") == "OpenRouter post" and result.get("provider") == "OpenRouter",
              str(result)[:120])
        check("zanjir: Gemini → Groq → OpenRouter",
              result.get("provider_chain") == ["Gemini", "Groq", "OpenRouter"],
              str(result.get("provider_chain")))
        check("foydalanuvchiga xatolik ko'rsatilmadi", "error" not in result, str(result)[:120])

        # ------------------------------------------------------------
        print("== 6. Barcha provayderlar o'chdi → toza xato + kvota yechilmaydi ==")
        reset_state()
        S.update({"gemini_status": 404, "groq_status": 500, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        check("error dict qaytdi", "error" in result, str(result)[:120])
        check("post_text YO'Q (muvaffaqiyatsoz soxta javob yo'q)",
              not result.get("post_text"), str(result)[:120])
        check("'ai_unavailable' belgisi bor", result.get("ai_unavailable") is True,
              str(result)[:160])
        check("'quota_safe' belgisi bor (kvota yechilmaydi)", result.get("quota_safe") is True,
              str(result)[:160])
        err = result.get("error", "")
        check("xato xabari toza (Traceback yo'q)", "Traceback" not in err, err[:80])
        check("xato xabari tushunarli", ("AI xizmatlarining hech biri javob bermadi" in err),
              err[:80])

        # analyze_user_prompt ham xato qaytaradi va kontekstni ifloslamaydi
        uid = 777001
        ai_agent.clear_ai_context(uid)
        res2 = await ai_agent.analyze_user_prompt("Kofe post", uid)
        check("analyze_user_prompt: error qaytdi", "error" in res2, str(res2)[:100])
        ctx = ai_agent._get_ai_context_text(uid, 4000)
        check("muvaffaqiyatsiz so'rov kontekstga yozilmadi", "Kofe post" not in ctx, ctx[:120])
        ai_agent.clear_ai_context(uid)

        # ------------------------------------------------------------
        print("== 6b. Handler end-to-end: barcha provayderlar o'chganida kvota yechilmaydi ==")
        reset_state()
        S.update({"gemini_status": 404, "groq_status": 500, "openrouter_status": 500,
                  "mistral_status": 500, "cerebras_status": 500,
                  "sambanova_status": 500, "pollinations_status": 500})

        import database as db_mod
        from handlers import ai_assistant as aih

        QUOTA = {"reserved": 0, "refunded": 0, "incremented": 0}
        orig_run_db = db_mod.run_db

        async def fake_run_db(func, *args, **kwargs):
            name = getattr(func, "__name__", str(func))
            if name == "is_premium":
                return False
            if name == "get_user_credits":
                return 5
            if name == "check_ai_limit":
                return (True, 0, 5)
            if name == "use_user_credit":
                QUOTA["reserved"] += 1
                return True
            if name == "add_user_credit":
                QUOTA["refunded"] += 1
                return True
            if name == "increment_ai_usage":
                QUOTA["incremented"] += 1
                return None
            if name == "get_channel_tone":
                return "friendly"
            if name == "get_channel_posts_history":
                return []
            return None

        class FakeBot:
            username = "postassist_test"

            async def get_me(self):
                return self

            async def send_chat_action(self, *a, **kw):
                return None

        class FakeMsg:
            chat_id = 999
            media_group_id = None
            caption = None
            photo = video = document = audio = animation = voice = sticker = None
            text = "Kofe shopi uchun post yozib ber"

            def __init__(self):
                self.sent = []

            async def reply_text(self, text, **kw):
                self.sent.append(text)
                return None

            async def delete(self):
                return None

        msg = FakeMsg()
        update = SimpleNamespace(
            message=msg,
            effective_user=SimpleNamespace(id=999),
            effective_chat=SimpleNamespace(id=999),
        )
        context = SimpleNamespace(bot=FakeBot(), user_data={})

        db_mod.run_db = fake_run_db
        try:
            state = await aih.ai_input_received(update, context)
        finally:
            db_mod.run_db = orig_run_db

        check("handler yiqilmadi (AI_INPUT holati qaytdi)", state == aih.AI_INPUT, str(state))
        check("ball band qilindi (preflight)", QUOTA["reserved"] == 1, str(QUOTA))
        check("AI xato → ball QAYTARILDI (refund)", QUOTA["refunded"] == 1, str(QUOTA))
        check("kunlik sanakchi OSHIRILMADI (kvota yechilmadi)", QUOTA["incremented"] == 0,
              str(QUOTA))
        check("foydalanuvchiga xushmuomala xabar bor", len(msg.sent) >= 1, str(msg.sent)[:120])
        joined = " ".join(msg.sent)
        check("xabarda texnik traceback yo'q", "Traceback" not in joined, joined[:120])

        # ------------------------------------------------------------
        print("== 7. Barcha provayderlar timeout → xushmuomala timeout xabari ==")
        reset_state()
        ai_service.AI_PROVIDER_TOTAL_TIMEOUT = 0.5
        # Hamma provayder sekin javob beradi (0.5s qat'iy chegara oshadi)
        S.update({"gemini_sleep": 2, "groq_sleep": 2, "openrouter_sleep": 2,
                  "mistral_sleep": 2, "cerebras_sleep": 2,
                  "sambanova_sleep": 2, "pollinations_sleep": 2})
        result = await ai_agent.generate_ai_response("Kofe shopi uchun post yoz")
        ai_service.AI_PROVIDER_TOTAL_TIMEOUT = old_total
        check("error qaytdi", "error" in result, str(result)[:120])
        check("'timeout' belgisi bor", result.get("timeout") is True, str(result)[:160])
        check("'quota_safe' belgisi bor", result.get("quota_safe") is True, str(result)[:160])
        check("timeout xabari xushmuomala",
              "AI xizmati hozir javob bermayapti" in result.get("error", ""),
              result.get("error", "")[:100])

        # ------------------------------------------------------------
        print("== 8. Zanjir sozlamalari, darajalar va status ==")
        reset_state()
        check("yadrowi zanjir: Gemini → Groq → OpenRouter",
              ai_service.CORE_PROVIDER_CHAIN == ("Gemini", "Groq", "OpenRouter"),
              str(ai_service.CORE_PROVIDER_CHAIN))
        check("default zanjir yadrodan boshlanadi",
              ai_service.build_provider_chain()[:3] == ("Gemini", "Groq", "OpenRouter"),
              str(ai_service.build_provider_chain()))
        os.environ["AI_PROVIDER_CHAIN"] = "gemini,groq,openrouter"
        try:
            limited = ai_service.build_provider_chain()
        finally:
            del os.environ["AI_PROVIDER_CHAIN"]
        check("AI_PROVIDER_CHAIN env zanjirni cheklaydi",
              limited == ("Gemini", "Groq", "OpenRouter"), str(limited))
        os.environ["AI_PROVIDER_CHAIN"] = "groq"
        try:
            groq_only = ai_service.build_provider_chain()
        finally:
            del os.environ["AI_PROVIDER_CHAIN"]
        check("aliaslar taniladi (groq)", groq_only == ("Groq",), str(groq_only))

        svc = ai_service.AIFallbackService()
        st = svc.status()
        check("status: zanjir ro'yxati", st["chain"][:3] == ["Gemini", "Groq", "OpenRouter"],
              str(st["chain"]))
        check("status: timeout sozlamasi (3/8/10)",
              st["timeout"] == {"connect": 3, "read": 8, "total": 10}, str(st["timeout"]))
        by_name = {p["name"]: p for p in st["providers"]}
        check("darajalar: Gemini=1, Groq=2, OpenRouter=3",
              by_name["Gemini"]["tier"] == 1 and by_name["Groq"]["tier"] == 2
              and by_name["OpenRouter"]["tier"] == 3, str({k: v["tier"] for k, v in by_name.items()}))
        check("kalit bor → available", by_name["Gemini"]["available"] is True)
        check("Cloudflare (account_id yo'q) → available emas",
              by_name["Cloudflare"]["available"] is False, str(by_name["Cloudflare"]))

    finally:
        ai_service.AI_PROVIDER_TOTAL_TIMEOUT = old_total
        ai_agent.MAX_429_RETRIES = old_retries
        reset_state()
        await ai_agent.close_ai_session()
        await runner.cleanup()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha AI fallback-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    asyncio.run(main())
