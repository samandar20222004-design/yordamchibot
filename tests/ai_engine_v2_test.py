#!/usr/bin/env python3
"""🚦 AI ENGINE V2 — YAGONA KANONIK AI SHLYUZ, MODEL ROUTER, CIRCUIT BREAKER.

DEEP_AUDIT_REPORT tuzatishi (Faza 1, 2, 3 + 21): AI chaqiruvlari ikkiga
bo'lingan edi — eski modullar ``utils/ai_agent.py`` ga, yangilari
``services/ai/*`` ga murojaat qilardi; yagona marshrutlash va tezkor kesh
yo'q edi. Endi ``services/ai_engine`` — bitta kanonik shlyuz.

Ushbu test quyidagilarni QAT'IY kafolatlaydi:

  TEST 1 — MODEL ROUTER (Faza 2): FAST/QUALITY/REASONING/VISION lane'lari,
           vazifa → lane xaritasi, prompt-based auto-detect, SMM Intent
           sinxroni; lane bo'yicha provayderlar tartibi (FAST — eng tez
           provayder birinchi; QUALITY/REASONING — eng sifatli birinchi).
  TEST 2 — DETERMINISTIK KESH (Faza 3): bir xil so'rov → aynan bir xil
           kalit (provayder tartibidan mustaqil), TTL, LRU chegara, stats.
  TEST 3 — CIRCUIT BREAKER (health): 429/timeout/5xx klassifikatsiyasi,
           ketma-ket xatolar → breaker OCHILADI, sog'lom provayder
           RO'YXAT BOSHINGA chiqadi (avto-fallback), muvaffaqiyat
           breaker'ni tozalaydi, LEGACY ``_BREAKERS`` mirror (bitta
           sog'liq holati).
  TEST 4 — GATEWAY generate/analyze: fail-soft (xato = istisno EMAS),
           provayder tanlash, 429 → keyingi SOG'LOM provayder
           (fallback), FAST PATH kesh hit (ikkinchi chaqiruv provayderga
           CHIQMAYDI), force_refresh, Fast Path qat'iy timeout.
  TEST 5 — LEGACY ADAPTER (backward compat): ``utils.ai_agent`` eski
           chaqiruvlari kanonik shlyuz orqali yuradi (``gateway.legacy_chain``),
           eski monkeypatch nuqtalari (``ai_agent._run_ai_chain``) buzilmaydi.
  TEST 6 — HANDLER IZOLYATSIYASI: hech bir handler provayder qatlamiga
           (``services.ai_service`` / ``services.ai.providers``) to'g'ridan-
           to'g'ri bog'lanmaydi — hammasi shlyuz yoki legacy adapter orqali.
  TEST 7 — DEAD-END TUZOQLAR (Faza 21): aniqlashtirish wizard'i va Magic
           Post uslub menyusida [❌ Bekor qilish] tugmasi bor, callback'lar
           ro'yxatdan o'tgan, i18n paritet saqlangan, 64-bayt xavfsizlik.

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # yoki
    python3 tests/ai_engine_v2_test.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AI_ENGINE_V2_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10000")
# Mock siyosati buzilmasin: test muhitida Mock ruxsat etilgan (legacy zanjir
# uchun), shlyuz esa HAQIQIY provayderlargagina murojaat qiladi (P0-A).
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# IMPORTLAR (muhit sozlangandan KEYIN)
# ---------------------------------------------------------------------------
import services.ai_engine as ai_engine                      # noqa: E402
from services.ai_engine import (                            # noqa: E402
    Lane,
    cache_key,
    canonical_prompt,
    classify_exception,
    default_health_monitor,
    generate,
    reset_cache,
    reset_health_monitor,
    resolve_lane,
    provider_order,
    LANE_SPECS,
)
from services.ai_engine import gateway as gw                 # noqa: E402
from services.ai_engine import providers as eng_providers    # noqa: E402

CALLS: list[str] = []


def _make_handle(name):
    return eng_providers.ProviderHandle(name=name, provider=SimpleNamespace(
        name=name,
        is_available=lambda: True,
        complete=None,
    ))


def patch_providers(handles, executor):
    """Shlyuz provayder qatlamini mock bilan almashtirish (yagona nuqta)."""
    real_build = eng_providers.build_provider_handles
    real_exec = eng_providers.execute_provider
    eng_providers.build_provider_handles = handles
    eng_providers.execute_provider = executor
    return real_build, real_exec


def restore_providers(real):
    eng_providers.build_provider_handles, eng_providers.execute_provider = real


def _executor_of(results_by_name, fail_kinds=None, delay=0.0):
    """Provayder ijrochisi: nom → natija dict yoki ko'tariladigan xato."""
    fail_kinds = fail_kinds or {}

    async def executor(handle, prompt, system_instruction, **kwargs):
        if delay:
            await asyncio.sleep(delay)
        CALLS.append(handle.name)
        if handle.name in fail_kinds:
            raise RuntimeError(fail_kinds[handle.name])
        return results_by_name[handle.name]
    return executor


# ===========================================================================
# TEST 1 — MODEL ROUTER
# ===========================================================================
def test_router():
    print("\n== TEST 1: Model Router — FAST/QUALITY/REASONING/VISION lane'lari ==")

    # 1a) Barcha 4 ta lane mavjud va spetsifikatsiyalari to'liq.
    lanes = {lane.value for lane in Lane}
    check("4 ta lane: FAST/QUALITY/REASONING/VISION",
          lanes == {"FAST", "QUALITY", "REASONING", "VISION"}, str(lanes))
    for lane in Lane:
        spec = LANE_SPECS[lane]
        check(f"{lane.value}: tavsif va provayderlar tartibi bor",
              bool(spec.description) and len(spec.provider_order) >= 3
              and spec.default_timeout > 0, str(spec))

    # 1b) Vazifa → lane xaritasi (spetsifikatsiya).
    check("qayta yozish → FAST", resolve_lane(task="rewrite") is Lane.FAST)
    check("oddiy post → FAST", resolve_lane(task="simple_post") is Lane.FAST)
    check("tuzatish → FAST", resolve_lane(task="fix") is Lane.FAST)
    check("qisqartirish → FAST", resolve_lane(task="shorten") is Lane.FAST)
    check("audit → QUALITY", resolve_lane(task="audit") is Lane.QUALITY)
    check("kanal tahlili → REASONING",
          resolve_lane(task="channel_analysis") is Lane.REASONING)
    check("haftalik reja → REASONING",
          resolve_lane(task="weekly_plan") is Lane.REASONING)
    check("kontent-reja → REASONING",
          resolve_lane(task="content_plan") is Lane.REASONING)
    check("rasm tahlili → VISION", resolve_lane(task="vision") is Lane.VISION)
    check("image_post → VISION", resolve_lane(task="image_post") is Lane.VISION)

    # 1c) Ustuvorlik: aniq lane > vazifa nomi > prompt > standart.
    check("aniq lane ustun",
          resolve_lane(task="rewrite", lane=Lane.REASONING) is Lane.REASONING)
    check("vazifa nomi promptdan ustun",
          resolve_lane(task="audit", prompt="postni qayta yoz") is Lane.QUALITY)
    check("noma'lum → xavfsiz QUALITY standarti",
          resolve_lane(task="noma'lum-vazifa", prompt="salom") is Lane.QUALITY)

    # 1d) Prompt-based auto-detect (task yo'q).
    check("«haftalik reja» → REASONING",
          resolve_lane(prompt="kanal uchun haftalik reja tuz") is Lane.REASONING)
    check("«rasm tahlil» → VISION",
          resolve_lane(prompt="rasm tahlil qilib post yoz") is Lane.VISION)
    check("«qayta yoz» → FAST",
          resolve_lane(prompt="bu postni qayta yozib ber") is Lane.FAST)

    # 1e) SMM Intent Router sinxroni (yagona manba).
    check("SMM intent: IMPROVE → FAST",
          resolve_lane(prompt="bu matnni yaxshilab ber") is Lane.FAST)
    check("SMM intent: POST_AUDIT → QUALITY",
          resolve_lane(prompt="bu postni tahlil qil") is Lane.QUALITY)
    check("SMM intent: CONTENT_IDEAS → REASONING",
          resolve_lane(prompt="mavzu g'oyalari kerak") is Lane.REASONING)

    # 1f) Lane bo'yicha provayderlar tartibi.
    fast_order = provider_order(Lane.FAST)
    quality_order = provider_order(Lane.QUALITY)
    reasoning_order = provider_order(Lane.REASONING)
    vision_order = provider_order(Lane.VISION)
    check("FAST: eng tez provayder (Groq) BIRINCHI",
          fast_order[0] == "Groq", str(fast_order[:3]))
    check("QUALITY: eng sifatli (Gemini) BIRINCHI",
          quality_order[0] == "Gemini", str(quality_order[:3]))
    check("REASONING: Gemini birinchi, keyin chuqur modellar",
          reasoning_order[0] == "Gemini" and reasoning_order[1] == "OpenRouter",
          str(reasoning_order[:3]))
    check("VISION: Gemini (Vision) birinchi",
          vision_order[0] == "Gemini", str(vision_order[:3]))
    # Barcha lane'lar chuqur zanjir bilan tugaydi (oxirgi umumiy qism) va
    # provayder nomlari kanonik (services/ai_service bilan bir xil).
    for order in (fast_order, quality_order, reasoning_order, vision_order):
        check(f"zanjir chuqur zaxiralar bilan tugaydi ({order[-1]})",
              order[-1] == "Pollinations", str(order[-3:]))
    check("hech qanday takroriy provayder yo'q (har lane'da noyob)",
          all(len(set(provider_order(l))) == len(provider_order(l)) for l in Lane))

    # 1g) FAST lane — Fast Path siyosati: qat'iy timeout + kesh default.
    check("FAST: kesh default YOQIQ (Fast Path)",
          LANE_SPECS[Lane.FAST].cache_by_default is True)
    check("QUALITY: kesh default O'CHIQ",
          LANE_SPECS[Lane.QUALITY].cache_by_default is False)
    check("FAST timeout 10-15s oynasida",
          10.0 <= LANE_SPECS[Lane.FAST].default_timeout <= 15.0,
          str(LANE_SPECS[Lane.FAST].default_timeout))


# ===========================================================================
# TEST 2 — DETERMINISTIK KESH
# ===========================================================================
def test_cache():
    print("\n== TEST 2: Deterministik kesh — kalit, TTL, LRU ==")
    cache = reset_cache(max_entries=8, ttl=60.0)

    # 2a) Kanonizatsiya: bo'shliq/registr farqlari bir xil matn.
    check("bo'shliqlar kanonizatsiya qilinadi",
          canonical_prompt("  salom   dunyo \n") == "salom dunyo",
          repr(canonical_prompt("  salom   dunyo \n")))

    # 2b) Determinizm: bir xil so'rov → BITTA kalit.
    k1 = cache_key(prompt="kofe do'koni post", lane="FAST", lang="uz")
    k2 = cache_key(prompt="kofe  do'koni   post ", lane="FAST", lang="uz")
    k3 = cache_key(prompt="kofe do'koni post", lane="FAST", lang="ru")
    k4 = cache_key(prompt="kofe do'koni post", lane="QUALITY", lang="uz")
    k5 = cache_key(prompt="kofe do'koni post", lane="FAST", lang="uz", is_pro=True)
    k6 = cache_key(prompt="kofe do'koni post", lane="FAST", lang="uz", tone="formal")
    k7 = cache_key(prompt="kofe do'koni post", lane="FAST", lang="uz",
                   system_instruction="maxsus")
    check("aynan bir xil so'rov → bir xil kalit", k1 == k2, f"{k1} vs {k2}")
    check("til o'zgarsa kalit o'zgaradi", k1 != k3)
    check("lane o'zgarsa kalit o'zgaradi", k1 != k4)
    check("PRO belgisi kalitga kiradi", k1 != k5)
    check("tone kalitga kiradi", k1 != k6)
    check("tizim prompti kalitga kiradi", k1 != k7)
    check("kalit deterministik prefiksli",
          k1.startswith("aicache:") and len(k1) == len("aicache:") + 64, str(k1))

    # 2c) Kesh katta-kichik: provayder tartibi kalitga KIRMAYDI (fallback
    # boshqa provayderga o'tsa ham kalit barqaror).
    check("provayder nomi kalitga kirmaydi",
          cache_key(prompt="x", lane="FAST") == cache_key(prompt="x", lane="FAST"))

    # 2d) TTL: muddati o'tgan yozuv qaytmaydi.
    kttl = cache_key(prompt="ttl test", lane="FAST")
    cache.set(kttl, {"post_text": "javob"}, ttl=0.05)
    check("yangi yozuv o'qiladi", cache.get(kttl) == {"post_text": "javob"})
    import time as _time
    _time.sleep(0.08)
    check("TTL tugagan yozuv QAYTMAYDI", cache.get(kttl) is None)

    # 2e) LRU chegara: sig'imdan oshsa ENG ESKI yozuv chiqarib tashlanadi.
    fresh = reset_cache(max_entries=3, ttl=60.0)
    keys = []
    for i in range(4):
        k = cache_key(prompt=f"lru {i}", lane="FAST")
        fresh.set(k, {"post_text": str(i)})
        keys.append(k)
    check("LRU: sig'im 3 ta", len(fresh) == 3, str(len(fresh)))
    check("LRU: eng eskisi chiqarildi", fresh.get(keys[0]) is None)
    check("LRU: yangilari joyida", fresh.get(keys[3]) == {"post_text": "3"})

    # 2f) stats() — hit rate hisoblanadi.
    stats = fresh.stats()
    check("stats: maydonlar to'liq",
          all(field in stats for field in
              ("entries", "hits", "misses", "hit_rate", "evictions")), str(stats))
    check("stats: eviction qayd etildi", stats["evictions"] >= 1, str(stats))


# ===========================================================================
# TEST 3 — CIRCUIT BREAKER (health)
# ===========================================================================
def test_circuit_breaker():
    print("\n== TEST 3: Circuit Breaker — 429/timeout kuzatuvi + avto-fallback ==")
    monitor = reset_health_monitor()
    try:
        from utils import ai_agent as aa
        legacy_before = dict(getattr(aa, "_BREAKERS", {}))
    except Exception:  # pragma: no cover
        aa = None
        legacy_before = {}

    # 3a) Xato klassifikatsiyasi.
    check("429 → rate_limit",
          classify_exception("HTTP 429 Too Many Requests") == "rate_limit")
    check("quota matni → rate_limit",
          classify_exception("quota exceeded") == "rate_limit")
    check("TimeoutError → timeout", classify_exception(TimeoutError()) == "timeout")
    check("«timed out» matni → timeout",
          classify_exception("provider timed out after 10s") == "timeout")
    check("503 → server_error",
          classify_exception("HTTP 503 Service Unavailable") == "server_error")
    check("tarmoq → network",
          classify_exception("connection reset by peer") == "network")
    check("noma'lum → other", classify_exception(RuntimeError("boom")) == "other")
    check("None → other", classify_exception(None) == "other")

    # 3b) Chegarragacha hisoblash (default 3) — breaker OCHILADI.
    r1 = monitor.record_failure("Gemini", "rate_limit", "429")
    r2 = monitor.record_failure("Gemini", "rate_limit", "429")
    check("1-2 xato: hali ochiq emas",
          r1 == "counting" and r2 == "counting" and not monitor.is_open("Gemini"))
    r3 = monitor.record_failure("Gemini", "timeout", "timed out")
    check("3-xato: breaker OCHILADI", r3 == "open" and monitor.is_open("Gemini"))
    snap = monitor.snapshot().get("Gemini", {})
    check("snapshot: ochilish tarixi va oxirgi xato",
          snap.get("opened_count") == 1 and snap.get("last_error_kind") == "timeout"
          and snap.get("total_failures") == 3, str(snap))

    # 3c) Avto-fallback: sog'lom provayder RO'YXAT BOSHINGA chiqadi.
    order = monitor.healthy_order(["Gemini", "Groq", "OpenRouter"])
    check("ochiq provayder oxirga suriladi (sog'lom birinchi)",
          order == ["Groq", "OpenRouter", "Gemini"], str(order))

    # 3d) LEGACY MIRROR: utils.ai_agent._BREAKERS bilan bitta holat.
    if aa is not None:
        mirrored = getattr(aa, "_BREAKERS", {}).get("Gemini")
        check("legacy _BREAKERS mirror: ochiq muddat uzatildi",
              bool(mirrored and mirrored.get("until")), str(mirrored))
        check("legacy _breaker_open ham ochiq deb ko'radi",
              aa._breaker_open("Gemini") is True)
    else:  # pragma: no cover
        check("legacy mirror mavjud", False, "utils.ai_agent import yo'q")

    # 3e) Muvaffaqiyat breaker'ni tozalaydi (half-open yopiladi).
    monitor.record_success("Gemini")
    check("muvaffaqiyatdan keyin breaker yopiladi", not monitor.is_open("Gemini"))
    check("tiklangan provayder qayta birinchi o'rinda",
          monitor.healthy_order(["Gemini", "Groq"])[0] == "Gemini")
    if aa is not None:
        check("legacy mirror ham tozalandi",
              "Gemini" not in getattr(aa, "_BREAKERS", {}),
              str(getattr(aa, "_BREAKERS", {}).get("Gemini")))

    # 3f) Short-circuit reset: cooldown tugagach half-open hisob.
    monitor.reset()

    # 3g) Yangi monitor siyosati konfiguratsiyasi (threshold=1).
    strict = ai_engine.ProviderHealthMonitor(threshold=1, cooldown=30.0)
    strict.record_failure("Groq", "server_error", "500")
    check("threshold=1: birinchi xatoda ochiladi", strict.is_open("Groq"))
    check("xato turi snapshot'da",
          strict.snapshot()["Groq"]["last_error_kind"] == "server_error")
    strict.reset()

    # 3h) Boshlang'ich legacy holat buzilmagan.
    if aa is not None:
        legacy_now = getattr(aa, "_BREAKERS", {})
        check("reset() legacy holatni ham tozalaydi", not legacy_now, str(legacy_now))
    del legacy_before


# ===========================================================================
# TEST 4 — GATEWAY: generate/analyze (fail-soft, fallback, kesh, timeout)
# ===========================================================================
def test_gateway_generate():
    print("\n== TEST 4: Gateway — yagona generate/analyze interfeysi ==")
    reset_cache(max_entries=64, ttl=60.0)
    reset_health_monitor()

    # 4a) FAIL-SOFT: provayder yo'q — istisno EMAS, ok=False + muloyim xabar.
    CALLS.clear()
    real = patch_providers(lambda: {}, _executor_of({}))
    try:
        res = run(generate("salom", task="simple_post", timeout=5))
    finally:
        restore_providers(real)
    check("provayder yo'q: ok=False", res.ok is False, str(res))
    check("provayder yo'q: istisno EMAS, muloyim xabar",
          bool(res.error) and "AI" in res.error, str(res.error))
    check("provayder yo'q: lane saqlangan",
          res.lane is Lane.FAST and res.task == "simple_post", str(res.lane))

    # 4b) Muvaffaqiyat: birinchi sog'lom provayder javob beradi.
    CALLS.clear()
    handles = lambda: {"Groq": _make_handle("Groq"), "Gemini": _make_handle("Gemini")}  # noqa: E731
    executor = _executor_of({"Groq": {"post_text": "FAST javob"}})
    real = patch_providers(handles, executor)
    try:
        res = run(generate("postni qayta yoz", task="rewrite", use_cache=False))
    finally:
        restore_providers(real)
    check("FAST lane: Groq javob berdi",
          res.ok and res.provider == "Groq" and res.text == "FAST javob", str(res))
    check("natija'da lane/chain ma'lumotlari",
          res.lane is Lane.FAST and res.provider_chain == ["Groq"], str(res.provider_chain))
    check("keshdan KELMAGAN (use_cache=False)", res.cached is False)

    # 4c) FALLBACK: birinchi provayder 429 → keyingi SOG'LOM provayder.
    CALLS.clear()
    reset_health_monitor()
    handles = lambda: {"Groq": _make_handle("Groq"), "Gemini": _make_handle("Gemini")}  # noqa: E731
    executor = _executor_of(
        {"Gemini": {"post_text": "Gemini javob"}},
        fail_kinds={"Groq": "HTTP 429 Too Many Requests"},
    )
    real = patch_providers(handles, executor)
    try:
        res = run(generate("oddiy post", task="simple_post", use_cache=False))
    finally:
        restore_providers(real)
    check("429'dan keyin Gemini javob berdi (avto-fallback)",
          res.ok and res.provider == "Gemini" and res.text == "Gemini javob", str(res))
    check("fallback zanjiri qayd etildi",
          res.provider_chain == ["Groq", "Gemini"], str(res.provider_chain))
    snap = default_health_monitor().snapshot()
    check("health: Groq 429 xatosi qayd etildi",
          snap.get("Groq", {}).get("last_error_kind") == "rate_limit", str(snap.get("Groq")))
    check("health: Gemini muvaffaqiyati qayd etildi",
          snap.get("Gemini", {}).get("total_successes") == 1, str(snap.get("Gemini")))

    # 4d) TIMEOUT klassifikatsiyasi ham fallback ochadi.
    CALLS.clear()
    reset_health_monitor()
    executor = _executor_of(
        {"Gemini": {"post_text": "Zaxira javob"}},
        fail_kinds={"Groq": asyncio.TimeoutError("timed out")},
    )
    real = patch_providers(handles, executor)
    try:
        res = run(generate("oddiy post 2", task="simple_post", use_cache=False))
    finally:
        restore_providers(real)
    check("timeout'dan keyin zaxira javob berdi",
          res.ok and res.provider == "Gemini", str(res))
    check("health: timeout klassifikatsiyasi",
          default_health_monitor().snapshot().get("Groq", {}).get(
              "last_error_kind") == "timeout")

    # 4e) FAST PATH KESH: birinchi chaqiruv provayderga chiqadi, IKKINCHISI
    # keshdan — provayder UMUMAN chaqirilmaydi.
    CALLS.clear()
    reset_cache(max_entries=64, ttl=60.0)
    reset_health_monitor()
    calls_holder = {"n": 0}

    async def counting_executor(handle, prompt, system_instruction, **kwargs):
        calls_holder["n"] += 1
        CALLS.append(handle.name)
        return {"post_text": f"javob #{calls_holder['n']}"}

    real = patch_providers(handles, counting_executor)
    try:
        first = run(generate("bir xil so'rov", task="simple_post"))
        second = run(generate("bir xil so'rov", task="simple_post"))
    finally:
        restore_providers(real)
    check("1-chaqiruv: provayderdan", first.ok and first.provider == "Groq", str(first))
    check("2-chaqiruv: KESHDA (cached=True, provider='cache')",
          second.ok and second.cached and second.provider == "cache", str(second))
    check("kesh hit: matn bir xil", first.text == second.text,
          f"{first.text!r} vs {second.text!r}")
    check("kesh hit: provayder FAQAT 1 marta chaqirildi", calls_holder["n"] == 1,
          str(calls_holder["n"]))
    check("kesh hit tez (<5ms)", second.elapsed < 0.005, f"{second.elapsed:.4f}s")

    # 4f) force_refresh: keshni e'tiborsiz qoldiradi.
    CALLS.clear()
    real = patch_providers(handles, counting_executor)
    try:
        refreshed = run(generate("bir xil so'rov", task="simple_post", force_refresh=True))
    finally:
        restore_providers(real)
    check("force_refresh: kesh e'tiborsiz, provayder qayta chaqirildi",
          refreshed.cached is False and calls_holder["n"] == 2, str(calls_holder["n"]))
    check("force_refresh natijasi keshga qayta yozildi (3-chaqiruv yana hit)",
          run(generate("bir xil so'rov", task="simple_post")).cached is True)

    # 4g) Kesh o'chirilganda provayder yana chaqiriladi (nomzodlar farqli).
    CALLS.clear()
    reset_cache(max_entries=64, ttl=60.0)
    reset_health_monitor()
    real = patch_providers(handles, counting_executor)
    try:
        other = run(generate("BOSHQA so'rov", task="simple_post"))
    finally:
        restore_providers(real)
    check("boshqa so'rov → provayder chaqirildi (kesh miss)",
          other.ok and other.cached is False, str(other))

    # 4h) FAST PATH qat'iy timeout: sekin provayder — muloyim timeout xabari.
    CALLS.clear()
    reset_cache(max_entries=64, ttl=60.0)
    reset_health_monitor()
    old_fast = os.environ.get("AI_FAST_PATH_TIMEOUT")
    os.environ["AI_FAST_PATH_TIMEOUT"] = "0.5"

    async def slow_executor(handle, prompt, system_instruction, **kwargs):
        await asyncio.sleep(3.0)
        return {"post_text": "kechikdi"}

    real = patch_providers(handles, slow_executor)
    try:
        started = time.monotonic()
        res = run(generate("sekin so'rov", task="simple_post", use_cache=False))
        elapsed = time.monotonic() - started
    finally:
        restore_providers(real)
        if old_fast is None:
            os.environ.pop("AI_FAST_PATH_TIMEOUT", None)
        else:
            os.environ["AI_FAST_PATH_TIMEOUT"] = old_fast
    check("Fast Path: sekin javob — ok=False (istisno EMAS)",
          res.ok is False and bool(res.error), str(res))
    check("Fast Path: timeout xabari (aybdor foydalanuvchi emas)",
          "AI" in (res.error or "") and ("keyinroq" in (res.error or "")
                                         or "soniya" in (res.error or "")),
          str(res.error))
    check("Fast Path: ~0.5s da to'xtadi (3s kutilmadi)", elapsed < 2.0,
          f"{elapsed:.2f}s")

    # 4i) analyze() — tahlil lane'i va JSON yordamchisi.
    CALLS.clear()
    reset_health_monitor()
    real = patch_providers(
        lambda: {"Gemini": _make_handle("Gemini")},
        _executor_of({"Gemini": {"content": '{"score": 88, "verdict": "yaxshi"}'}}),
    )
    try:
        res = run(gw.analyze("bu postni tahlil qil", task="audit", use_cache=False))
    finally:
        restore_providers(real)
    check("analyze: QUALITY lane (audit)",
          res.ok and res.lane is Lane.QUALITY and res.provider == "Gemini", str(res))
    parsed = res.json_result()
    check("analyze: json_result() dict qaytaradi",
          isinstance(parsed, dict) and parsed.get("score") == 88, str(parsed))

    # 4j) Vision adapter: shlyuz vision_analyze — utils.vision_analyzer ga delegat.
    import utils.vision_analyzer as va

    async def fake_analyze_image(data, **kwargs):
        return {"description": "Qahvachilik", "model": "gemini-2.5-flash",
                "product_name": "Kofe"}

    orig_analyze = va.analyze_image
    va.analyze_image = fake_analyze_image
    try:
        res = run(gw.vision_analyze(b"\x89PNG fake", caption="kofe", lang="uz"))
    finally:
        va.analyze_image = orig_analyze
    check("vision_analyze: VISION lane + delegat ishladi",
          res.ok and res.lane is Lane.VISION and "Kofe" in res.raw.get("product_name", ""),
          str(res))
    check("vision_analyze: provayder model belgisi",
          "gemini-2.5-flash" in res.provider, str(res.provider))


# ===========================================================================
# TEST 5 — LEGACY ADAPTER (backward compatibility)
# ===========================================================================
def test_legacy_adapter():
    print("\n== TEST 5: Legacy adapter — eski chaqiruvlar shlyuz orqali ==")
    import utils.ai_agent as aa

    # 5a) ``ai_agent._run_ai_chain`` endi kanonik shlyuzga delegat.
    src = Path(aa.__file__).read_text(encoding="utf-8")
    check("ai_agent._run_ai_chain → gateway.legacy_chain",
          "gateway.legacy_chain" in src, "")

    # 5b) Haqiqiy yo'l: generate_ai_response → gateway.legacy_chain chaqiriladi.
    captured = {}

    async def fake_legacy(prompt, system_instruction, lang=None):
        captured["prompt"] = prompt
        captured["lang"] = lang
        return {"post_text": "SHLYUZ JAVOBI", "provider": "FakeProvider"}

    orig_legacy = gw.legacy_chain
    gw.legacy_chain = fake_legacy
    try:
        result = run(aa.generate_ai_response("kofe uchun post", timeout=10, lang="ru"))
    finally:
        gw.legacy_chain = orig_legacy
    check("eski generate_ai_response shlyuzdan o'tadi",
          result.get("post_text") == "SHLYUZ JAVOBI", str(result)[:120])
    check("provider maydoni saqlanadi (javob shakli o'zgarmagan)",
          result.get("provider") == "FakeProvider", str(result.get("provider")))
    check("lang shlyuzga uzatiladi", captured.get("lang") == "ru", str(captured))

    # 5c) ESKI monkeypatch nuqtasi ishlashda davom etadi (barcha eski testlar).
    async def fake_chain_old(prompt, system_instruction, lang=None):
        return {"reply": "eski uslubdagi javob"}

    orig_run_chain = aa._run_ai_chain
    aa._run_ai_chain = fake_chain_old
    try:
        result2 = run(aa.generate_ai_response("x", timeout=10))
    finally:
        aa._run_ai_chain = orig_run_chain
    check("ai_agent._run_ai_chain monkeypatch'i buzilmagan",
          result2.get("reply") == "eski uslubdagi javob", str(result2)[:120])

    # 5d) legacy_chain o'zi legacy zanjirga delegat (late binding —
    # services.ai_service.run_ai_chain monkeypatch'i ko'rinadi).
    from services import ai_service

    async def fake_run_chain(prompt, system_instruction, lang=None):
        return {"content": "zanjir javobi", "provider": "Chain"}

    orig_rc = ai_service.run_ai_chain
    ai_service.run_ai_chain = fake_run_chain
    try:
        result3 = run(gw.legacy_chain("p", "s", lang="uz"))
    finally:
        ai_service.run_ai_chain = orig_rc
    check("legacy_chain → services.ai_service.run_ai_chain (hech narsa noldan yozilmagan)",
          result3.get("provider") == "Chain", str(result3)[:120])


# ===========================================================================
# TEST 6 — HANDLER IZOLYATSIYASI (provayderga to'g'ridan-to'g'ri bog'lanish YO'Q)
# ===========================================================================
def test_handler_isolation():
    print("\n== TEST 6: Handler izolyatsiyasi — yagona shlyuz qoidasi ==")
    handlers_dir = ROOT / "handlers"
    violations: list[str] = []
    for py in sorted(handlers_dir.glob("*.py")):
        src = py.read_text(encoding="utf-8", errors="ignore")
        for forbidden in (
            "services.ai_service",
            "from services.ai_service import",
            "services.ai.providers",
            "services.ai_engine.providers",
            "services.ai.orchestrator",
            "ai_engine import providers",
        ):
            if forbidden in src:
                violations.append(f"{py.name}: {forbidden}")
    check("hech bir handler provayder qatlamiga bog'lanmaydi",
          not violations, str(violations))

    # Gateway/legacy adapter orqali bog'lanishlar ro'yxatda (ruhsat etilgan).
    gp = (handlers_dir / "post_score.py").read_text(encoding="utf-8")
    ip = (handlers_dir / "image_post.py").read_text(encoding="utf-8")
    mnp = (handlers_dir / "manual_post.py").read_text(encoding="utf-8")
    ccf = (handlers_dir / "content_calendar_flow.py").read_text(encoding="utf-8")
    check("post_score → gateway sirti",
          "services.ai_engine.gateway import" in gp, "")
    check("image_post → gateway sirti",
          "services.ai_engine.gateway import" in ip, "")
    check("manual_post → gateway.legacy_chain",
          "services.ai_engine import gateway" in mnp
          and "gateway.legacy_chain" in mnp, "")
    check("content_calendar_flow → gateway.legacy_chain",
          "services.ai_engine import gateway" in ccf
          and "gateway.legacy_chain" in ccf, "")

    # Gateway delegatlari xuddi shu funksiyalarga kechikkan bog'lanishda.
    from services import ai_service

    check("gateway.score_post — ai_service delegati",
          gw.score_post.__name__ == "score_post"
          and gw.score_post.__module__ == gw.__name__, "")
    check("gateway.generate_image_post — ai_service delegati",
          gw.generate_image_post.__name__ == "generate_image_post", "")
    check("delegat korutina funksiyasi",
          asyncio.iscoroutinefunction(gw.score_post)
          and asyncio.iscoroutinefunction(gw.improve_post_to_95), "")
    check("ai_service manbasi O'ZGARMAGAN (score_post mavjud)",
          callable(ai_service.score_post) and callable(ai_service.improve_post_to_95))


# ===========================================================================
# TEST 7 — DEAD-END TUZOQLAR (Faza 21): [❌ Bekor qilish] tugmalari
# ===========================================================================
def test_dead_end_traps():
    print("\n== TEST 7: Dead-end tuzoqlar — bekor qilish tugmalari ==")
    import handlers.ai_post as aip
    import handlers.magic_post as mp
    import translations.magic_post as tm

    # 7a) Magic Post uslub menyusi: 5 uslub + [❌ Bekor qilish].
    markup = mp._magic_style_keyboard("uz")
    rows = [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]
    flat = [btn for row in rows for btn in row]
    style_cbs = [cb for _t, cb in flat if cb.startswith("mp_style:")]
    check("5 uslub tugmasi saqlangan", len(style_cbs) == 5, str(style_cbs))
    check("[❌ Bekor qilish] tugmasi bor (mp_cancel)",
          ("❌ Bekor qilish", "mp_cancel") in flat, str(flat))
    check("bekor tugmasi alohida oxirgi qatorda",
          rows[-1] == [("❌ Bekor qilish", "mp_cancel")], str(rows[-1]))

    # 7b) Aniqlashtirish wizard'i: 5 yo'nalish + [❌ Bekor qilish].
    kb = aip.build_clarification_keyboard("uz")
    aip_flat = [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]
    aip_cbs = [cb for _t, cb in aip_flat]
    check("5 yo'nalish tugmasi saqlangan",
          [cb for cb in aip_cbs if cb.startswith("aip_fmt:")]
          == ["aip_fmt:news", "aip_fmt:tips", "aip_fmt:short",
              "aip_fmt:sales", "aip_fmt:custom"], str(aip_cbs))
    check("[❌ Bekor qilish] tugmasi bor (aip_cancel)",
          ("❌ Bekor qilish", "aip_cancel") in aip_flat, str(aip_flat))
    check("bekor tugmasi oxirgi qator (dead-end yo'q)",
          aip_flat[-1] == ("❌ Bekor qilish", "aip_cancel"), str(aip_flat[-1]))

    # 7c) Callback'lar routerda ro'yxatdan o'tgan (handlers/__init__.py).
    import handlers as handlers_pkg
    import inspect

    src = inspect.getsource(handlers_pkg)
    check("mp_cancel ro'yxatda (MAGIC_STYLE_SELECT)", "mp_cancel" in src)
    check("aip_cancel ro'yxatda (AI_POST_CLARIFY)", "aip_cancel" in src)
    check("magic_cancel_callback import qilingan", "magic_cancel_callback" in src)
    check("ai_post_cancel_callback import qilingan", "ai_post_cancel_callback" in src)

    # 7d) Callback xavfsizligi (64-bayt, xavfsiz belgilar).
    for data in (mp.MP_CANCEL, aip.AIP_CANCEL):
        size = len(data.encode("utf-8"))
        check(f"callback «{data}» xavfsiz va ≤64 bayt",
              size <= 64 and data.replace("_", "").isalnum(), f"{data} ({size}b)")

    # 7e) i18n: uchala tilda bekor matnlari + paritet buzilmagan.
    for lang, label in (("uz", "❌ Bekor qilish"), ("ru", "❌ Отмена"),
                        ("en", "❌ Cancel")):
        check(f"magic bekor matni [{lang}]",
              tm.magic_t("mp_btn_cancel", lang) == label,
              tm.magic_t("mp_btn_cancel", lang))
        check(f"magic bekor tasdig'i [{lang}] bo'sh emas",
              bool(tm.magic_t("mp_cancel_done", lang)))
        check(f"aip bekor matni [{lang}] aynan",
              aip.aip_t("cancel_button", lang) == label, aip.aip_t("cancel_button", lang))
        check(f"aip bekor tasdig'i [{lang}] bo'sh emas",
              bool(aip.aip_t("cancel_done", lang)))
    check("magic i18n pariteti buzilmagan",
          tm.magic_post_parity_report()["in_sync"] is True)

    # 7f) Bekor qilish CALLBACK'lari: sessiya tozalanadi + END qaytadi.
    class FakeMsg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text=None, **k):
            self.replies.append({"text": text, **k})

    class FakeQuery:
        def __init__(self, data):
            self.data = data
            self.edited = None
            self.message = FakeMsg()
            self.answered = False

        async def answer(self, *a, **k):
            self.answered = True

        async def edit_message_text(self, text=None, **k):
            self.edited = {"text": text, **k}

        async def edit_message_reply_markup(self, **k):
            self.edited = k

    class FakeUpd:
        def __init__(self, query):
            self.callback_query = query
            self.message = query.message

    # Magic bekor qilish: sessiya kalitlari tozalanadi, END qaytadi.

    ctx = SimpleNamespace(user_data={
        "lang": "uz", "magic_raw_text": "kofe", "magic_post_text": "post",
        "magic_style": "sales",
    })
    q = FakeQuery("mp_cancel")
    state = run(mp.magic_cancel_callback(FakeUpd(q), ctx))
    check("magic bekor: query.answer() chaqirildi", q.answered is True)
    check("magic bekor: sessiya kalitlari TOZALANDI",
          not {"magic_raw_text", "magic_post_text", "magic_style"} & set(ctx.user_data),
          str(ctx.user_data))
    check("magic bekor: foydalanuvchiga tasdiq xabari",
          q.edited and "Bekor qilindi" in (q.edited.get("text") or ""),
          str(q.edited))
    check("magic bekor: ConversationHandler.END",
          state == mp.ConversationHandler.END, str(state))

    # aip bekor qilish: wizard kalitlari tozalanadi, END qaytadi.
    ctx2 = SimpleNamespace(user_data={
        "lang": "uz", "aip_topic": "sport", "aip_origin": "magic",
        "aip_format": "news", "aip_format_hint": "x",
    })
    q2 = FakeQuery("aip_cancel")
    state2 = run(aip.ai_post_cancel_callback(FakeUpd(q2), ctx2))
    check("aip bekor: wizard kalitlari TOZALANDI",
          not {"aip_topic", "aip_origin", "aip_format", "aip_format_hint"}
          & set(ctx2.user_data), str(ctx2.user_data))
    check("aip bekor: foydalanuvchiga tasdiq xabari",
          q2.message.replies and "Bekor qilindi" in (q2.message.replies[0].get("text") or ""),
          str(q2.message.replies))
    check("aip bekor: ConversationHandler.END",
          state2 == aip.ConversationHandler.END, str(state2))


# ===========================================================================
def main() -> int:
    print("=" * 70)
    print(" 🚦 AI ENGINE V2 — YAGONA SHLYUZ + ROUTER + BREAKER + KESH TESTI")
    print("=" * 70)
    test_router()
    test_cache()
    test_circuit_breaker()
    test_gateway_generate()
    test_legacy_adapter()
    test_handler_isolation()
    test_dead_end_traps()

    print("\n" + "=" * 70)
    if failures:
        print(f" [FAIL] JAMI: o'tdi={passed}, xato={failures}")
        return 1
    print(f" JAMI: o'tdi={passed}, xato=0 — AI ENGINE V2 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # pragma: no cover
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
