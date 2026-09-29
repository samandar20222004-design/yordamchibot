#!/usr/bin/env python3
"""🔒 PHASE 2 · RATE LIMITING VA REDIS / DISTRIBUTED STATE ARXITEKTURASI.

Muammo (Phase 2 brief'i):
  * Butun rate-limit holati bir instance ichidagi ``dict`` larda edi —
    Render/Docker'da 2+ instance ishlatilganda chegaralar yarim qolardi;
  * Callback throttling barcha tugmalarni bir savatda hisoblaydi
    (``(user_id, "")`` kaliti) — bitta tugma bosilganda boshqalari ham
    1.5 s «muzlab» qolardi;
  * Chegara to'lganda ``_USER_HISTORY.clear()`` — ya'ni bitta foydalanuvchi
    flood'i BOSHQA foydalanuvchilarning holatini ham tozalardi.

Yechim (ushbu test tekshiradi):
  1) `services/cache_backend.py` — yagona ``CacheBackend`` interfeysi
     (``get/set/delete/incr/expire``), Redis backend (ixtiyoriy),
     TTL+LRU In-Memory backend va circuit-breaker'li avtomatik fallback;
  2) `middlewares/rate_limiter.py` — har bir harakat uchun ALOHIDA kalit
     + ALOHIDA TTL: matn, ``(user_id, callback_action)``, AI, URL/RSS fetch;
  3) `.env.example` — ``REDIS_URL`` (ixtiyoriy), ``REDIS_ENABLED`` bayrog'i
     va chegaralarni boshqaruvchi ``RATE_LIMIT_*`` kalitlari.

Ishga tushirish:
    python3 tests/rate_limiter_redis_test.py
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # 3N bosqichi
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import warnings
from pathlib import Path

# ------------------------------------------------------------------
# 0) MUHIT — bot modullari import qilinishidan OLDIN.
# ------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:RATE_LIMITER_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10051")
# 🔴 REDIS_ISHLATISH=0 → barcha testlar «Redis yo'q» (faqat In-Memory)
# rejimida bajariladi; 1 → atayin real/sun'iy Redis ulanishiga urinish.
USE_REDIS = os.environ.get("REDIS_ISHLATISH", "0") == "1"
if not USE_REDIS:
    os.environ.pop("REDIS_URL", None)

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
BOT = ROOT / "telegram_bot"
sys.path.insert(0, str(BOT))

PASSED = 0
FAILURES = 0
LANGS = ("uz", "ru", "en")


def check(name, cond, detail=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name}" + (f" -> {detail}" if detail else ""))
    return bool(cond)


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context faker'lar (telegram API'siz)
# ------------------------------------------------------------------
class FakeQuery:
    """``callback_query`` — ``answer()`` chaqiruvlarini yozib boradi."""

    def __init__(self, data: str):
        self.data = data
        self.answers: list = []

    async def answer(self, text=None, show_alert=False, **kwargs):
        self.answers.append({"text": text, "show_alert": show_alert})


class FakeMessage:
    def __init__(self, text=None, caption=None):
        self.text = text
        self.caption = caption


class FakeUpdate:
    def __init__(self, user_id, text=None, callback=None, caption=None):
        self.effective_user = type("U", (), {"id": user_id})()
        self.effective_message = FakeMessage(text, caption)
        self.message = self.effective_message
        self.callback_query = FakeQuery(callback) if callback else None
        self.update_id = abs(hash((user_id, text, callback))) % 100000


class FakeContext:
    """``get_lang`` uchun minimal kontekst."""

    def __init__(self, lang="uz"):
        self.user_data = {"lang": lang}
        self.bot = None


class FakeRedis:
    """``redis.asyncio`` API'sini taqlid qiluvchi in-memory Redis."""

    def __init__(self, fail: bool = False):
        self.store: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.fail = fail
        self.commands: list[str] = []
        self.closed = False

    def _check(self, name):
        self.commands.append(name)
        if self.fail:
            raise ConnectionError("redis uzildi")

    async def get(self, key):
        self._check("GET")
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self._check("SET")
        self.store[key] = str(value)
        if ex is not None:
            self.expiry[key] = int(ex)
        return True

    async def delete(self, key):
        self._check("DEL")
        self.expiry.pop(key, None)
        return 1 if self.store.pop(key, None) is not None else 0

    async def incrby(self, key, amount):
        self._check("INCR")
        value = int(self.store.get(key, 0)) + int(amount)
        self.store[key] = str(value)
        return value

    async def expire(self, key, seconds):
        self._check("EXPIRE")
        if key not in self.store:
            return False
        self.expiry[key] = int(seconds)
        return True

    async def persist(self, key):
        self._check("PERSIST")
        return 1 if self.expiry.pop(key, None) is not None else 0

    async def ping(self):
        self._check("PING")
        return True

    async def aclose(self):
        self.closed = True


from services import cache_backend as cb  # noqa: E402
from middlewares.rate_limiter import (  # noqa: E402
    RateLimitMiddleware,
    RateLimiter,
    RatePolicy,
    RateDecision,
    default_policies,
    rate_limiter,
)


def make_limiter(backend=None, **policies) -> RateLimiter:
    """Test uchun toza limiter (o'z sanagichi bilan)."""
    return RateLimiter(
        backend=backend or cb.MemoryCacheBackend(),
        policies=default_policies() if not policies else policies,
    )


# ==========================================================================
# TEST 1 — Granular siyosatlar: har bir harakat uchun ALOHIDA TTL
# ==========================================================================
from telegram.ext import ApplicationHandlerStop  # noqa: E402


def test_granular_policies():
    print("\n== TEST 1: Granular siyosatlar (har biri alohida kalit + TTL) ==")
    policies = default_policies()
    for name in ("message", "callback", "ai", "fetch", "fetch_global"):
        check(f"siyosat '{name}' mavjud", name in policies)
    check("message: 1 s da ≤ 2 ta matn",
          policies["message"].limit == 2 and policies["message"].window == 1.0,
          str(policies["message"]))
    check("callback: (user_id, action) kaliti, 1.5 s da 1 ta",
          policies["callback"].limit == 1
          and policies["callback"].window == 1.5, str(policies["callback"]))
    check("ai: 3–5 s oralig'ida bitta qimmatli so'rov",
          3.0 <= policies["ai"].window <= 5.0 and policies["ai"].limit == 1,
          str(policies["ai"]))
    check("fetch: URL/RSS uchun alohida (ko'proq qasddan) chegara",
          policies["fetch"].limit == 5
          and policies["fetch"].window == 60.0, str(policies["fetch"]))
    check("fetch_global: butun bot uchun global fetch chekasi",
          policies["fetch_global"].limit >= policies["fetch"].limit)

    # Kalitlar bir-biridan farqlanadi (global savat yo'q!)
    p = policies
    keys = {
        "message": p["message"].cache_key("42"),
        "callback": p["callback"].cache_key("42|stgs_hub"),
        "ai": p["ai"].cache_key("42"),
        "fetch": p["fetch"].cache_key("42"),
    }
    check("kalitlar prefix bilan ajratilgan (rl:<bucket>:...)",
          all(k.startswith("rl:") for k in keys.values()), str(keys))
    check("kalitlar BIR-BIRIDAN farq qiladi",
          len(set(keys.values())) == len(keys), str(keys))


# ==========================================================================
# TEST 2 — 💬 Matn limiti (oddiy matnli xabarlar)
# ==========================================================================
def test_message_limit():
    print("\n== TEST 2: Matn limiti — 1 soniyada ko'pi bilan 2 ta ==")

    async def scenario():
        limiter = make_limiter()
        d1 = await limiter.allow_message(7)
        d2 = await limiter.allow_message(7)
        d3 = await limiter.allow_message(7)
        check("1-soniyada 1- va 2-xabar o'tadi", bool(d1) and bool(d2))
        check("1-soniyada 3-xabar BLOKLANADI", not bool(d3))
        check("rad qarori bucket='message'", d3.bucket == "message")
        check("rad qarori retry_after > 0", d3.retry_after > 0, str(d3))
        check("boshqa foydalanuvchiga tegilmaydi",
              bool(await limiter.allow_message(8)))
        # Buyruqlar (/) matn limitiga hisoblanmaydi
        check("buyruqlar (/) granullarga kirmaydi",
              limiter.classify(FakeUpdate(7, text="/start")) == [])
        # Klassifikatsiya: oddiy matn → faqat message
        check("oddiy matn → message granulasi",
              limiter.classify(FakeUpdate(7, text="salom"))
              == [("message", "7")])
        # Media/sticker → bu qatlamda tegilmaydi
        empty = FakeUpdate(7, text=None)
        empty.effective_message.text = None
        check("media xabar → granullarga kirmaydi",
              limiter.classify(empty) == [])
        # O'chirilgan limiter — hech narsa bloklamaydi
        limiter.enabled = False
        disabled = [await limiter.allow_message(7) for _ in range(5)]
        check("RATE_LIMIT_ENABLED=0 → hamma narsa ruxsatli",
              all(bool(d) for d in disabled))
        limiter.enabled = True
        # Bool operatori qulay ishlaydi
        check("RateDecision bool() → not: if not decision", not bool(d3))

    run(scenario())


# ==========================================================================
# TEST 3 — 🔘 CALLBACK THROTTLING: bir xil tugma bloklanadi,
#          boshqa tugma ERKIN (topshiriqdagi asosiy talab)
# ==========================================================================
def test_callback_throttling():
    print("\n== TEST 3: Callback throttling — bir xil tugma bloklanadi, "
          "boshqa tugma o'tadi ==")

    async def scenario():
        limiter = make_limiter()

        # 3.1) BIR XIL tugma ketma-ket bosiladi → 2-chisi bloklanadi
        first = await limiter.allow_callback(42, "stgs_hub")
        second = await limiter.allow_callback(42, "stgs_hub")
        third = await limiter.allow_callback(42, "stgs_hub")
        check("bir xil tugma: 1-bosish o'tadi", bool(first))
        check("bir xil tugma: 2-bosish BLOKLANADI (server to'ldirmasligi uchun)",
              not bool(second))
        check("bir xil tugma: 3-bosish ham bloklanadi", not bool(third))
        check("bloklash kaliti (user_id, callback_action)",
              limiter.policies["callback"].cache_key("42|stgs_hub")
              == "rl:callback:42|stgs_hub",
              limiter.policies["callback"].cache_key("42|stgs_hub"))

        # 3.2) BOSHQA tugma — xuddi shu paytda bemalol bosiladi
        other = await limiter.allow_callback(42, "an_detail:123")
        check("BOSHQA tugma bloklanMAYdi (🔘 erkin)", bool(other))
        third_other = await limiter.allow_callback(42, "an_detail:123")
        check("BOSHQA tugma ham o'z oynasi bo'yicha ishlaydi",
              not bool(third_other))
        again = await limiter.allow_callback(42, "stgs_credits")
        check("bir nechta boshqa tugma — hammasi birinchi marta o'tadi",
              bool(await limiter.allow_callback(42, "cab_main"))
              and bool(again))

        # 3.3) Boshqa foydalanuvchi — o'sha tugmani bosishi mumkin
        check("boshqa foydalanuvchiga ta'sir qilmaydi",
              bool(await limiter.allow_callback(43, "stgs_hub")))

        # 3.4) Action farq qilsa — kalit farq qiladi (prefix emas, to'liq data)
        check("bir xil namespace, boshqa action → boshqa kalit",
              bool(await limiter.allow_callback(42, "stgs_hub:uz"))
              and bool(await limiter.allow_callback(42, "stgs_hub:ru")))

        # 3.5) TTL: 1.5 s dan keyin oyna o'zi qayta ochiladi
        short = RateLimiter(
            backend=cb.MemoryCacheBackend(),
            policies={**default_policies(), "callback": RatePolicy(
                "callback", limit=1, window=1.0)},
        )
        await short.allow_callback(50, "btn")
        check("2-bosish bloklanadi", not bool(await short.allow_callback(50, "btn")))
        await asyncio.sleep(1.15)
        check("1.15 s keyin oyna O'ZI qayta ochiladi (TTL, global clear emas)",
              bool(await short.allow_callback(50, "btn")))

        # 3.6) Middleware darajasida: aynan shu talab
        mw = RateLimitMiddleware(make_limiter())
        u1 = FakeUpdate(60, callback="menu:home")
        u2 = FakeUpdate(60, callback="menu:home")
        u3 = FakeUpdate(60, callback="menu:stats")
        r1 = await mw.process_update(u1, FakeContext())
        r2 = await mw.process_update(u2, FakeContext())
        r3 = await mw.process_update(u3, FakeContext())
        check("middleware: bir xil tugma 1-borish → False (o'tdi)", r1 is False)
        check("middleware: bir xil tugma 2-borish → True (bloklandi)", r2 is True)
        check("middleware: BOSHQA tugma → False (o'tdi)", r3 is False)
        check("bloklangan callback'ga javob yuboriladi (tugma qotmaydi)",
              len(u2.callback_query.answers) == 1, str(u2.callback_query.answers))
        check("o'tgan callback'ga javob yuborilMAYdi",
              u1.callback_query.answers == [] and u3.callback_query.answers == [])
        check("javob matni bo'sh emas (uz/ru/en lug'atidan)",
              bool(u2.callback_query.answers[0]["text"]))

    run(scenario())


def test_middleware_inside_application():
    print("\n== TEST 3b: Middleware haqiqiy PTB Application zanjirida ==")

    def _app_with_middleware(limiter):
        """Real PTB Application + middleware (tarmoqsiz — initialize() yo'q)."""
        from telegram.ext import ApplicationBuilder

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            app = ApplicationBuilder().token("123456:RATE_LIMIT_APP_TEST").build()
        app.add_handler(RateLimitMiddleware(limiter), group=-1)
        return app

    def _query(data, user_id):
        from telegram import CallbackQuery, User

        return CallbackQuery(id="cb-1", from_user=User(id=user_id,
                                                       is_bot=False,
                                                       first_name="T"),
                             chat_instance="ci", data=data)

    def _cb_update(data, user_id=4242):
        from telegram import Update

        return Update(update_id=1, callback_query=_query(data, user_id))

    async def scenario():
        app = _app_with_middleware(make_limiter())
        check("middleware alohida GURUHDA (-1) va birinchi bo'lib ishlaydi",
              -1 in app.handlers
              and list(app.handlers)[0] == -1, str(list(app.handlers)))
        handler = app.handlers[-1][0]
        check("ro'yxatga solingan obyekt — RateLimitMiddleware",
              isinstance(handler, RateLimitMiddleware))

        stopped = []

        async def run_chain(update):
            """PTB process_update mantiqini takror qilamiz (tarmoqsiz)."""
            for group in list(app.handlers):
                for item in list(app.handlers[group]):
                    check_result = item.check_update(update)
                    if check_result is None or check_result is False:
                        continue
                    try:
                        await item.handle_update(update, app, check_result,
                                                 FakeContext())
                    except ApplicationHandlerStop:
                        stopped.append(True)
                    break
                else:
                    continue
                break

        await run_chain(_cb_update("menu:home"))
        check("1-bosish — zanjir to'xtamadi", not stopped)
        await run_chain(_cb_update("menu:home"))
        check("2-bosish — ApplicationHandlerStop bilan ZANJIR TO'XTADI",
              len(stopped) == 1, str(stopped))
        await run_chain(_cb_update("menu:other"))
        check("boshqa tugma — zabr o'tdi (to'xtamadi)", len(stopped) == 1)

    run(scenario())

    run(scenario())


# ==========================================================================
# TEST 4 — 🤖 AI generation limiti (qimmatli so'rovlar)
# ==========================================================================
def test_ai_limit():
    print("\n== TEST 4: AI generation limiti — 3–5 s da bitta so'rov ==")

    async def scenario():
        limiter = make_limiter()
        ok = await limiter.allow_ai(11)
        blocked = await limiter.allow_ai(11)
        check("1-ai so'rovi o'tadi", bool(ok))
        check("2-ai so'rovi darhol BLOKLANADI", not bool(blocked))
        check("boshqa foydalanuvchiga ta'sir qilmaydi",
              bool(await limiter.allow_ai(12)))

        # AI ishga tushiruvchi real callback action'lar → avtomatik granula
        buckets = {b for b, _ in limiter.classify(FakeUpdate(13, callback="studio_ai_post"))}
        check("AI callback (studio_ai_post) → 'ai' granulasi",
              "ai" in buckets, str(buckets))
        buckets_retry = {b for b, _ in limiter.classify(FakeUpdate(13, callback="ai_post_retry"))}
        check("AI callback (ai_post_retry) → 'ai' granulasi", "ai" in buckets_retry)
        buckets_nav = {b for b, _ in limiter.classify(FakeUpdate(13, callback="stgs_hub"))}
        check("oddiy menyu tugmasi AI granulasiga KIRMAGAY",
              "ai" not in buckets_nav, str(buckets_nav))

        # Middleware orqali: ikki xil AI tugmasi — ikkalasi ham granula
        mw = RateLimitMiddleware(make_limiter())
        a1 = await mw.process_update(FakeUpdate(14, callback="studio_ai_post"), FakeContext())
        a2 = await mw.process_update(FakeUpdate(14, callback="studio_ai_photo"), FakeContext())
        check("1-AI amal o'tadi", a1 is False)
        check("2-AI amal (boshqa tugma bo'lsa ham) bloklanadi", a2 is True)

    run(scenario())


# ==========================================================================
# TEST 5 — 🔗 URL / RSS fetch limiti (SSRF + DoS himoyasi)
# ==========================================================================
def test_fetch_limit():
    print("\n== TEST 5: URL / RSS fetch limiti (SSRF + DoS) ==")

    async def scenario():
        limiter = make_limiter()
        results = [await limiter.allow_fetch(21) for _ in range(6)]
        check("birinchi 5 ta fetch o'tadi", all(bool(r) for r in results[:5]),
              str([bool(r) for r in results]))
        check("6-tasi BLOKLANADI", not bool(results[5]))
        check("boshqa foydalanuvchiga ta'sir qilmaydi",
              bool(await limiter.allow_fetch(22)))

        # URL li xabar → avtomatik fetch granulasi
        buckets = [b for b, _ in limiter.classify(
            FakeUpdate(23, text="https://example.com/maqola"))]
        check("URL li matn xabari → fetch granulasi", "fetch" in buckets, str(buckets))
        check("URL li xabar → global fetch granulasi ham", "fetch_global" in buckets)
        # RSS «🔄 Hoziroq tekshirish» callback
        rss = [b for b, _ in limiter.classify(FakeUpdate(23, callback="src_chk:12"))]
        check("RSS tekshiruv callback'i → fetch granulasi", "fetch" in rss, str(rss))
        # Oddiy matn → fetch granulasi YO'Q
        plain = [b for b, _ in limiter.classify(FakeUpdate(23, text="salom!"))]
        check("oddiy matn → fetch granulasi YO'Q", "fetch" not in plain, str(plain))
        # Naviqat tugmalari fetch'ni ishga tushirmaydi
        nav = [b for b, _ in limiter.classify(FakeUpdate(23, callback="cab_main"))]
        check("menyu tugmasi fetch granulasini ishga tushirmaydi",
              "fetch" not in nav, str(nav))

    run(scenario())


# ==========================================================================
# TEST 6 — 🔁 Redis YO'Q (faqat In-Memory fallback rejimi)
# ==========================================================================
def test_memory_only_mode():
    print("\n== TEST 6: Redis YO'Q — butunlay In-Memory rejim ==")

    async def scenario():
        saved = os.environ.pop("REDIS_URL", None)
        backend = await cb.create_cache_backend(enabled=False)
        check("REDIS_ENABLED=0 → MemoryCacheBackend",
              isinstance(backend, cb.MemoryCacheBackend), type(backend).__name__)
        limiter = make_limiter(backend)
        m1 = await limiter.allow_message(31)
        m2 = await limiter.allow_message(31)
        m3 = await limiter.allow_message(31)
        check("In-Memory bilan chegaralar ISHLAYDI (xabar: 2 ta o'tadi, 3-si bloklanadi)",
              bool(m1) and bool(m2) and not bool(m3))
        check("In-Memory bilan callback throttling ishlaydi",
              bool(await limiter.allow_callback(31, "a"))
              and not bool(await limiter.allow_callback(31, "a"))
              and bool(await limiter.allow_callback(31, "b")))
        check("Redis paketi bo'lmasa ham bot ishlaydi (muvaffaqiyatli)",
              isinstance(backend, cb.MemoryCacheBackend))
        if saved:
            os.environ["REDIS_URL"] = saved

    run(scenario())


# ==========================================================================
# TEST 7 — 🔗 Redis MAVJUD (multi-instance: sanagichlar UMUMIY)
# ==========================================================================
def test_redis_shared_state():
    print("\n== TEST 7: Redis mavjud — holat instance'lar arasida UMUMIY ==")

    async def scenario():
        client = FakeRedis()
        backend = await cb.create_cache_backend(
            enabled=True, url="redis://localhost:6379/0", client=client,
            memory=cb.MemoryCacheBackend(),
        )
        check("Redis ulandi → Resilient (Redis + In-Memory fallback)",
              isinstance(backend, cb.ResilientCacheBackend), type(backend).__name__)

        # Ikki «instance» — bitta Redis
        instance_a = make_limiter(backend)
        instance_b = make_limiter(backend)
        first = await instance_a.allow_callback(77, "stgs_hub")
        second = await instance_b.allow_callback(77, "stgs_hub")
        check("1-instance: bosish o'tadi", bool(first))
        check("2-INSTANCE: xuddi shu tugma BLOKLANADI (multi-instance himoyasi)",
              not bool(second))
        other = await instance_b.allow_callback(77, "cab_main")
        check("boshqa tugma 2-instance'da ham o'tadi", bool(other))
        check("kalit Redis'da prefiks bilan saqlanadi",
              "postassist:rl:callback:77|stgs_hub" in client.store,
              str(list(client.store)[:3]))
        check("Redis'da TTL belgilangan",
              client.expiry.get("postassist:rl:callback:77|stgs_hub") == 2,
              str(client.expiry))

        # Redis o'chib qolsa — ikkala instance ham ishlashda davom etadi
        client.fail = True
        degraded_a = await instance_a.allow_message(78)
        degraded_b = await instance_b.allow_message(78)
        check("Redis o'lganda 1-instance fail-OPEN (bloklamaydi)",
              bool(degraded_a), str(degraded_a))
        check("Redis o'lganda 2-instance ham ishlaydi", bool(degraded_b))
        check("Redis o'lganda chegaralar In-Memory'da qo'llaniladi",
              not bool(await instance_a.allow_message(78))
              and not bool(await instance_b.allow_message(78)))
        client.fail = False

    run(scenario())


# ==========================================================================
# TEST 8 — 🛡 Circuit breaker: Redis uzilib qolsa bot qulamaydi
# ==========================================================================
def test_circuit_breaker_graceful():
    print("\n== TEST 8: Graceful degradation — circuit breaker ==")

    async def scenario():
        clock = {"t": 100.0}
        primary = cb.RedisCacheBackend(FakeRedis(fail=True))
        fallback = cb.MemoryCacheBackend()
        resilient = cb.ResilientCacheBackend(
            primary, fallback, failure_threshold=2, cooldown=5.0,
            clock=lambda: clock["t"],
        )
        limiter = make_limiter(resilient)

        d1 = await limiter.allow_callback(90, "btn")
        check("1-xato: foydalanuvchiga hech narsani sezdirilmaydi", bool(d1))
        d2 = await limiter.allow_callback(90, "btn")
        check("2-xato: breaker OCHILDI (Redis'ga urinish to'xtaydi)",
              resilient.circuit_open is True)
        check("breaker ochiqligida ham chegaralar ishlaydi", not bool(d2))
        d3 = await limiter.allow_callback(90, "other")
        check("breaker ochiq: boshqa tugma o'sha oynada erkin", bool(d3))

        before = len(primary.client.commands)
        await limiter.allow_callback(90, "btn")
        check("breaker ochiq: Redis'ga yangi so'rov YUBORILMAYDI",
              len(primary.client.commands) == before)

        # Cooldown → half-open → tiklanish
        clock["t"] += 6.0
        primary.client.fail = False
        check("cooldown'dan keyin proba muvaffaqiyatli → breaker yopildi",
              bool(await limiter.allow_callback(90, "btn"))
              and resilient.circuit_open is False)
        check("tuzilgach: yana Redis ishlatilmoqda",
              primary.client.commands[-1] in {"INCR", "EXPIRE"},
              primary.client.commands[-1])
        await resilient.close()

    run(scenario())


# ==========================================================================
# TEST 9 — 🧹 Global tozalash YO'Q (bir foydalanuvchi boshqasini
#          buzmaydi) + middleware xavfsizligi
# ==========================================================================
def test_no_global_clear():
    print("\n== TEST 9: Global tozalash yo'q + middleware xavfsizligi ==")

    async def scenario():
        backend = cb.MemoryCacheBackend(max_entries=500)
        limiter = make_limiter(backend)
        # 1-foydalanuvchi chegarani to'ldiradi
        for _ in range(3):
            await limiter.allow_message(100)
        check("1-foydalanuvchi bloklandi", not bool(await limiter.allow_message(100)))
        # 2-foydalanuvchining holati BUZILMAYDI
        check("2-foydalanuvchining o'z sanagichi saqlanadi",
              bool(await limiter.allow_message(101))
              and bool(await limiter.allow_message(101)))
        # eski kalitlar o'z TTL'i bilan (clear() chaqirilmadi)
        check("backend'da har bir kalit o'z holatida saqlangan (clear() YO'Q)",
              backend.stats()["entries"] == 2, str(backend.stats()["entries"]))

        # Middleware: backend nosoz bo'lsa — fail-OPEN (foydalanuvchi bloklanmaydi)
        class BrokenBackend:
            async def get(self, key):
                raise RuntimeError("backend o'lgan")

            async def set(self, key, value, ttl=None):
                raise RuntimeError("backend o'lgan")

            async def delete(self, key):
                raise RuntimeError("backend o'lgan")

            async def incr(self, key, ttl=None, amount=1):
                raise RuntimeError("backend o'lgan")

            async def expire(self, key, ttl):
                raise RuntimeError("backend o'lgan")

        broken_limiter = make_limiter(BrokenBackend())
        mw = RateLimitMiddleware(broken_limiter)
        ok = await mw.process_update(FakeUpdate(102, callback="btn"), FakeContext())
        ok2 = await mw.process_update(FakeUpdate(102, text="salom"), FakeContext())
        check("backend nosoz: middleware fail-OPEN (callback)", ok is False)
        check("backend nosoz: middleware fail-OPEN (matn)", ok2 is False)
        check("backend nosoz: RateDecision allowed=True",
              bool(await broken_limiter.allow_message(102)))

        # Aniq noma'lum bucket — deyarli cheklanmagan (moslashuvchan)
        loose = RateLimiter(backend=cb.MemoryCacheBackend(),
                            policies={"message": RatePolicy("message", 2, 1.0)})
        d = await loose.hit("noma_lum_bucket", "1")
        check("noma'lum bucket → xavfsiz default (bloklamaydi)", bool(d))

    run(scenario())


# ==========================================================================
# TEST 10 — ⚙️ Konfiguratsiya va .env.example (paritet)
# ==========================================================================
def test_config_and_env_docs():
    print("\n== TEST 10: Konfiguratsiya + .env.example pariteti ==")
    import config

    check("config.REDIS_URL mavjud (ixtiyoriy, default bo'sh)",
          hasattr(config, "REDIS_URL"))
    check("config.REDIS_ENABLED mavjud (bayroq)",
          hasattr(config, "REDIS_ENABLED"))
    check("REDIS_ENABLED standart qiymati '0' yoki '1'",
          str(config.REDIS_ENABLED) in {"0", "1"}, str(config.REDIS_ENABLED))
    for name in ("REDIS_KEY_PREFIX", "REDIS_SOCKET_TIMEOUT", "REDIS_MAX_CONNECTIONS",
                 "REDIS_CIRCUIT_FAILURES", "REDIS_CIRCUIT_COOLDOWN",
                 "MEM_CACHE_MAX_ENTRIES", "MEM_CACHE_MAX_VALUE_BYTES",
                 "MEM_CACHE_MAX_TOTAL_BYTES", "RATE_LIMIT_ENABLED",
                 "RATE_LIMIT_MESSAGE_MAX", "RATE_LIMIT_MESSAGE_WINDOW",
                 "RATE_LIMIT_CALLBACK_MAX", "RATE_LIMIT_CALLBACK_WINDOW",
                 "RATE_LIMIT_AI_MAX", "RATE_LIMIT_AI_WINDOW",
                 "RATE_LIMIT_FETCH_MAX", "RATE_LIMIT_FETCH_WINDOW",
                 "RATE_LIMIT_FETCH_GLOBAL_MAX"):
        check(f"config.{name} mavjud", hasattr(config, name))
    check("RATE_LIMIT_ENABLED standart True (fail-safe yo'q)",
          config.RATE_LIMIT_ENABLED is True)
    check("In-Memory chegaralari 512 MB RAM uchun xavfsiz",
          config.MEM_CACHE_MAX_TOTAL_BYTES <= 128 * 1024 * 1024
          and config.MEM_CACHE_MAX_ENTRIES <= 200000,
          str(config.MEM_CACHE_MAX_TOTAL_BYTES))

    # .env.example — ikkala nusxa ham, bir xil qiymat bilan
    env_files = (ROOT / ".env.example", BOT / ".env.example")
    parsed = []
    for path in env_files:
        text = path.read_text(encoding="utf-8")
        kv = dict(re.findall(r"(?m)^([A-Z0-9_]+)=(.*)$", text))
        parsed.append(kv)
        for key in ("REDIS_URL", "REDIS_ENABLED", "RATE_LIMIT_MESSAGE_MAX",
                    "RATE_LIMIT_CALLBACK_WINDOW", "RATE_LIMIT_AI_WINDOW",
                    "RATE_LIMIT_FETCH_MAX"):
            check(f"{path.name}: {key} hujjatlangan", key in kv)
        check(f"{path.name}: REDIS_URL qiymati BO'SH (ixtiyoriy)",
              kv.get("REDIS_URL", "") == "")
        check(f"{path.name}: REDIS_ENABLED avtomatik (bo'sh)",
              kv.get("REDIS_ENABLED", "x") == "")
    check("ikki .env.example PARITYETI saqlangan (bir xil qiymatlar)",
          parsed[0] == parsed[1],
          str([k for k in parsed[0] if parsed[0][k] != parsed[1].get(k)][:5]))
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    check("REDIS_URL namunasi hujjatlangan (redis://localhost:6379/0)",
          "redis://localhost:6379/0" in text)
    check("fallback (circuit breaker) izohlangan",
          "fallback" in text.lower() and "circuit" in text.lower())


# ==========================================================================
# TEST 11 — 🔌 main.py integratsiyasi (middleware ro'yxatga olinishi)
# ==========================================================================
def test_main_integration():
    print("\n== TEST 11: main.py integratsiyasi ==")
    src = (BOT / "main.py").read_text(encoding="utf-8")
    check("main.py: RateLimitMiddleware import qilinadi",
          "from middlewares.rate_limiter import RateLimitMiddleware" in src)
    check("main.py: middleware barcha handler'lardan OLDIN ro'yxatga olinadi",
          re.search(r"add_handler\(RateLimitMiddleware\(\),\s*group=-1\)", src)
          is not None)
    check("main.py: cache backend startda ishga tushiriladi",
          "init_cache_backend()" in src)
    check("main.py: cache backend graceful shutdown'da yopiladi",
          "close_cache_backend()" in src)
    check("main.py: eski global callback-debounce o'rniga granular qatlam",
          "is_callback_throttled" not in src)
    # Middleware o'zi PTB v21 middleware kontraktiga mos (BaseHandler)
    from telegram.ext import BaseHandler
    check("RateLimitMiddleware — PTB BaseHandler (add_handler talabi)",
          issubclass(RateLimitMiddleware, BaseHandler))
    check("check_update har bir update'ni ko'radi",
          RateLimitMiddleware(make_limiter()).check_update(FakeUpdate(1, text="x")) is True)
    check("block=True — qaror keyingi handler'lardan oldin qabul qilinadi",
          RateLimitMiddleware(make_limiter()).block is True)
    check("RateDecision — bool kontekstida ishlaydi (if not decision)",
          RateDecision(True, "message", 2, 1.0).allowed is True
          and not RateDecision(False, "message", 2, 1.0).allowed
          and bool(RateDecision(True, "message", 2, 1.0)) is True)
    check("process_update async qaytaruvchi (True = bloklandi)",
          asyncio.iscoroutinefunction(RateLimitMiddleware.process_update))
    # Bloklangan update butun zanjirni to'xtatadi
    try:
        await_or_fail = RateLimitMiddleware(make_limiter()).handle_update
        check("handle_update mavjud (PTB uni shu yerda chaqiradi)",
              asyncio.iscoroutinefunction(await_or_fail))
    except AttributeError as exc:  # pragma: no cover
        check("handle_update mavjud", False, str(exc))
    # middlewares paketi eksport qiladi
    import middlewares
    check("middlewares.__all__ eksportlari to'liq",
          {"RateLimitMiddleware", "RateLimiter", "RateDecision", "rate_limiter"}
          <= set(middlewares.__all__), str(middlewares.__all__))
    check("global rate_limiter nusxasi mavjud",
          isinstance(middlewares.rate_limiter, RateLimiter))


# ==========================================================================
# TEST 12 — 🔗 Rate limiter ⇄ cache backend integratsiyasi
# ==========================================================================
def test_limiter_backend_integration():
    print("\n== TEST 12: Limiter ⇄ backend integratsiyasi ==")

    async def scenario():
        # 1) Global singleton (main.py dagide) — default In-Memory
        cb.set_cache_backend(None)
        singleton = rate_limiter
        check("backend hali init qilinmagan bo'lsa — In-Memory",
              isinstance(singleton.backend, cb.MemoryCacheBackend),
              type(singleton.backend).__name__)
        # 2) Redis bilan
        client = FakeRedis()
        await cb.init_cache_backend(enabled=True, url="redis://localhost:6379/0",
                                    client=client)
        try:
            check("init_cache_backend() → Redis ulandi",
                  isinstance(cb.get_cache_backend(), cb.ResilientCacheBackend),
                  type(cb.get_cache_backend()).name)
            check("singleton backend Redis'ga ulandi",
                  singleton.backend is cb.get_cache_backend())
            singleton.set_backend(None)
            await singleton.allow_callback(4242, "menu:home")
            check("limiter hisoblagichi Redis'ga yozildi",
                  any(k.startswith("postassist:rl:") for k in client.store),
                  str(list(client.store)[:3]))
            check("kalit prefiksi va action bilan",
                  "postassist:rl:callback:4242|menu:home" in client.store,
                  str(list(client.store)[:5]))
        finally:
            await cb.close_cache_backend()
        # 3) close → In-Memory ga qaytadi (xavfsiz fallback)
        check("close qilingachadan keyin yana xavfsiz (In-Memory)",
              isinstance(cb.get_cache_backend(), cb.MemoryCacheBackend))
        # 4) backend_status() — sirlar yo'q
        status = cb.backend_status()
        check("backend_status() — DSN/parol yo'q",
              "redis://" not in str(status), str(status))

    run(scenario())


def main() -> int:
    print("=" * 70)
    print(" 🔒 PHASE 2 — RATE LIMITING + REDIS / DISTRIBUTED STATE")
    print("=" * 70)
    test_granular_policies()
    test_message_limit()
    test_callback_throttling()
    test_middleware_inside_application()
    test_ai_limit()
    test_fetch_limit()
    test_memory_only_mode()
    test_redis_shared_state()
    test_circuit_breaker_graceful()
    test_no_global_clear()
    test_config_and_env_docs()
    test_main_integration()
    test_limiter_backend_integration()
    print()
    print("=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] PHASE 2 RATE LIMITING / REDIS TESTLARIDA XATOLIK BOR ^^^")
        return 1
    print(" PHASE 2 — RATE LIMITING va REDIS/DISTRIBUTED STATE 100% YASHIL ✔")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
