#!/usr/bin/env python3
"""PostAssist V2 — 7-BOSQICH: System Health Check, Universal Error Boundary
va Production Monitoring testlari.

Nima tekshiriladi
-----------------
1. **HealthService** — ``get_system_health()`` barcha komponentlarni
   to'g'ri tekshiradi:
   * DB OK (ping + latency) va scheduler ishlayotganda → ``HEALTHY``;
   * DB uzilsa (ping False yoki istisno) → ``UNHEALTHY``;
   * scheduler to'xtasa / dead-letter yoki failed postlar chegara
     oshsa / stale processing bo'lsa → ``DEGRADED``;
   * AI provayderlar: kalit bor → ``OK``, breaker ochiq → ``DEGRADED``,
     kalit yo'q → ``UNCONFIGURED``;
   * health hisoboti HECH QACHON istisno ko'tarmaydi.
2. **format_health_report(lang)** — uz/ru/en uchun formatlangan,
   HTML-xavfsiz (dinamik qiymatlar escape qilingan) chiroyli hisobot.
3. **Global universal error handler**:
   * foydalanuvchiga HECH QACHON traceback / SQL / ichki xatolik
     ko'rsatilmaydi — faqat tilga mos (uz/ru/en) xushmuomala xabar;
   * strukturalli (JSON) log: user_id, handler_name, exception turi;
   * kritik (DB down) xatolar logda [CRITICAL_HEALTH] bilan ajratiladi;
   * handler o'zi hech qachon yiqilmaydi (update=None, reply xatosi);
   * xatolar statistikasi (/health uchun) to'g'ri hisoblanadi.
4. **RBAC** — oddiy foydalanuvchi (va SUPER_ADMIN) ``/health`` ni
   ishlata OLMAIDI (``system_settings`` faqat OWNER'da); handler ichiga
   kirish sodir bo'lmaydi.

Ishga tushirish
---------------
::

    cd telegram_bot && python3 tests/health_monitoring_test.py
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("ADMIN_IDS", "123456789,555000111")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

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


OWNER_ID = 123456789        # ADMIN_ID → OWNER (legacy)
SUPER_ADMIN_ID = 555000111  # ADMIN_IDS → SUPER_ADMIN (system_settings YO'Q)
PLAIN_USER_ID = 987654321   # oddiy foydalanuvchi


# ============================================================
# 1. HEALTH SERVICE — KOMPONENTLAR VA UMUMIY HOLAT
# ============================================================
def test_health_components():
    print("== HealthService: komponentlar va umumiy holat ==")
    from services import health_service
    import database as db
    from utils import ai_agent as aa

    # --- DB OK, scheduler ishlayapti, AI kalit bor → HEALTHY ---
    orig_ping = db.ping_db_with_latency
    orig_counts = db.get_post_health_counts
    orig_pool = db.get_db_pool_status
    orig_gemini = aa.GEMINI_API_KEY
    try:
        db.ping_db_with_latency = lambda: {"ok": True, "latency_ms": 4.2, "error": None}
        db.get_post_health_counts = lambda: {
            "pending": 2, "processing": 1, "failed": 0, "stale_processing": 0,
            "delivery_failed": 0, "dead_letter": 0,
        }
        db.get_db_pool_status = lambda: {"ready": True, "used": 1, "available": 7, "max": 8}
        aa.GEMINI_API_KEY = "test-key"  # core provayder sozlangan

        from apscheduler.schedulers.background import BackgroundScheduler
        sched = BackgroundScheduler()
        sched.start()
        sched.add_job(lambda: None, "interval", seconds=60, id="h_job")
        health_service.register_scheduler(sched)
        health_service.register_application(object())
        health_service.mark_bot_started()

        health = asyncio.run(health_service.get_system_health())

        check("health: umumiy status mavjud",
              health.get("status") in ("HEALTHY", "DEGRADED", "UNHEALTHY"),
              str(health.get("status")))
        check("health: DB OK → HEALTHY",
              health["database"]["status"] == "OK" and health["database"]["ok"] is True)
        check("health: DB latency ms qaytadi",
              isinstance(health["database"]["latency_ms"], (int, float)),
              str(health["database"]["latency_ms"]))
        check("health: scheduler RUNNING",
              health["scheduler"]["status"] == "RUNNING" and health["scheduler"]["running"] is True)
        check("health: scheduler joblar soni",
              health["scheduler"]["jobs"] == 1)
        check("health: pending postlar soni",
              health["scheduler"]["pending"] == 2)
        check("health: AI provayderlar ro'yxati bo'sh emas",
              len(health["ai_providers"]["providers"]) > 0)
        gemini = next((p for p in health["ai_providers"]["providers"]
                       if p["name"] == "Gemini"), None)
        check("health: Gemini (kalit bor) → OK",
              gemini is not None and gemini["status"] == "OK", str(gemini))
        check("health: uptime > 0",
              health["system"]["uptime_seconds"] >= 0)
        check("health: checked_at ISO formatda",
              "T" in str(health.get("checked_at", "")))

        # DB OK + scheduler RUNNING + core AI OK → to'liq HEALTHY
        check("health: hammasi joyida → HEALTHY",
              health["status"] == "HEALTHY", str(health["status"]))

        # --- DB uzilsa → UNHEALTHY ---
        db.ping_db_with_latency = lambda: {"ok": False, "latency_ms": None,
                                           "error": "OperationalError: connection refused"}
        health2 = asyncio.run(health_service.get_system_health())
        check("health: DB uzilsa → UNHEALTHY",
              health2["status"] == "UNHEALTHY", str(health2["status"]))
        check("health: DB komponenti UNHEALTHY",
              health2["database"]["status"] == "UNHEALTHY")
        check("health: DB xato matni log uchun saqlanadi",
              "connection refused" in str(health2["database"].get("error") or ""))

        # --- DB istisno tashlasa ham health yiqilmaydi ---
        def _boom():
            raise RuntimeError("connection refused during ping")
        db.ping_db_with_latency = _boom
        health3 = asyncio.run(health_service.get_system_health())
        check("health: DB istisnoda → UNHEALTHY (crash yo'q)",
              health3["status"] == "UNHEALTHY")
        check("health: DB istisno xato matnida",
              health3["database"].get("error") is not None)
    finally:
        db.ping_db_with_latency = orig_ping
        db.get_post_health_counts = orig_counts
        db.get_db_pool_status = orig_pool
        aa.GEMINI_API_KEY = orig_gemini
        health_service.register_scheduler(None)


def test_health_degraded_reasons():
    print("== HealthService: DEGRADED sabablari ==")
    from services import health_service
    import database as db

    orig_ping = db.ping_db_with_latency
    orig_counts = db.get_post_health_counts
    orig_pool = db.get_db_pool_status
    try:
        db.ping_db_with_latency = lambda: {"ok": True, "latency_ms": 3.0, "error": None}
        db.get_db_pool_status = lambda: {}

        # --- dead_letter chegara oshsa → DEGRADED ---
        db.get_post_health_counts = lambda: {
            "pending": 0, "processing": 0, "failed": 0, "stale_processing": 0,
            "delivery_failed": 0, "dead_letter": 5,
        }
        health = asyncio.run(health_service.get_system_health())
        check("health: dead_letter ≥ chegara → DEGRADED",
              health["status"] == "DEGRADED", str(health["status"]))
        check("health: dead_letter soni hisobotda",
              health["scheduler"]["dead_letter"] == 5)

        # --- failed postlar chegara oshsa → DEGRADED ---
        db.get_post_health_counts = lambda: {
            "pending": 0, "processing": 0, "failed": 50, "stale_processing": 0,
            "delivery_failed": 0, "dead_letter": 0,
        }
        health = asyncio.run(health_service.get_system_health())
        check("health: failed ≥ chegara → DEGRADED",
              health["status"] == "DEGRADED")

        # --- stale processing → DEGRADED ---
        db.get_post_health_counts = lambda: {
            "pending": 0, "processing": 3, "failed": 0, "stale_processing": 2,
            "delivery_failed": 0, "dead_letter": 0,
        }
        health = asyncio.run(health_service.get_system_health())
        check("health: stale processing → DEGRADED",
              health["status"] == "DEGRADED")
        check("health: stale_processing soni",
              health["scheduler"]["stale_processing"] == 2)

        # --- scheduler ro'yxatga olingan, lekin TO'XTAGAN → DEGRADED ---
        db.get_post_health_counts = lambda: {
            "pending": 0, "processing": 0, "failed": 0, "stale_processing": 0,
            "delivery_failed": 0, "dead_letter": 0,
        }
        from apscheduler.schedulers.background import BackgroundScheduler
        stopped = BackgroundScheduler()  # start() chaqirilmagan
        health_service.register_scheduler(stopped)
        health = asyncio.run(health_service.get_system_health())
        check("health: scheduler to'xtagan → STOPPED",
              health["scheduler"]["status"] == "STOPPED")
        check("health: scheduler to'xtagan → DEGRADED",
              health["status"] == "DEGRADED", str(health["status"]))
    finally:
        db.ping_db_with_latency = orig_ping
        db.get_post_health_counts = orig_counts
        db.get_db_pool_status = orig_pool
        health_service.register_scheduler(None)


def test_health_ai_providers():
    print("== HealthService: AI provayderlar holati ==")
    from services import health_service
    from utils import ai_agent as aa

    orig_gemini = aa.GEMINI_API_KEY
    orig_groq = aa.GROQ_API_KEY
    orig_openrouter = aa.OPENROUTER_API_KEY
    try:
        # Kalit YO'Q → UNCONFIGURED
        aa.GEMINI_API_KEY = ""
        aa.GROQ_API_KEY = ""
        aa.OPENROUTER_API_KEY = ""
        aa._BREAKERS.clear()
        info = health_service._check_ai_providers()
        check("ai: kalit yo'q → UNCONFIGURED",
              info["status"] == "UNCONFIGURED", str(info["status"]))
        gemini = next(p for p in info["providers"] if p["name"] == "Gemini")
        check("ai: Gemini UNCONFIGURED belgilangan",
              gemini["status"] == "UNCONFIGURED" and gemini["configured"] is False)

        # Kalit BOR, breaker YO'Q → OK
        aa.GEMINI_API_KEY = "k1"
        aa.GROQ_API_KEY = "k2"
        aa.OPENROUTER_API_KEY = "k3"
        info = health_service._check_ai_providers()
        check("ai: kalitlar bor → OK",
              info["status"] == "OK", str(info["status"]))
        check("ai: core zanjir to'liq (3 ta)",
              info["core_total"] == 3 and info["core_ok"] == 3)

        # Breaker OCHIQ (3 xato) → DEGRADED
        aa._BREAKERS["Gemini"] = {"fails": 3, "until": aa._time.time() + 600}
        info = health_service._check_ai_providers()
        gemini = next(p for p in info["providers"] if p["name"] == "Gemini")
        check("ai: breaker ochiq → Gemini DEGRADED",
              gemini["status"] == "DEGRADED" and gemini["breaker_open"] is True)

        # Bitta core qoldi (Groq ham, OpenRouter ham breaker) → DEGRADED
        aa._BREAKERS["Groq"] = {"fails": 3, "until": aa._time.time() + 600}
        aa._BREAKERS["OpenRouter"] = {"fails": 3, "until": aa._time.time() + 600}
        info = health_service._check_ai_providers()
        check("ai: barcha core breaker ochiq → DEGRADED",
              info["status"] == "DEGRADED", str(info["status"]))
    finally:
        aa.GEMINI_API_KEY = orig_gemini
        aa.GROQ_API_KEY = orig_groq
        aa.OPENROUTER_API_KEY = orig_openrouter
        aa._BREAKERS.clear()


def test_uptime_helpers():
    print("== HealthService: uptime yordamchilari ==")
    from services import health_service

    check("uptime: format_uptime(0) → '0s'",
          health_service.format_uptime(0) == "0s",
          health_service.format_uptime(0))
    check("uptime: format_uptime(90) → '1m 30s'",
          health_service.format_uptime(90) == "1m 30s",
          health_service.format_uptime(90))
    check("uptime: format_uptime(90061) → '1d 1h 1m'",
          health_service.format_uptime(90061) == "1d 1h 1m",
          health_service.format_uptime(90061))
    check("uptime: get_uptime_seconds ≥ 0",
          health_service.get_uptime_seconds() >= 0)
    check("uptime: get_started_at_iso ISO",
          "T" in health_service.get_started_at_iso())
    # mark_bot_started nolga qaytaradi
    health_service.mark_bot_started()
    check("uptime: mark_bot_started nol qo'yadi",
          health_service.get_uptime_seconds() < 5)


# ============================================================
# 2. FORMATLANGAN HISOBOT (admin uchun)
# ============================================================
def test_format_health_report():
    print("== format_health_report: uz/ru/en va HTML xavfsizlik ==")
    from services import health_service

    health = {
        "status": "DEGRADED",
        "checked_at": "2026-09-11T14:05:00+00:00",
        "uptime_seconds": 90061.0,
        "database": {"status": "OK", "ok": True, "latency_ms": 12.34, "error": None,
                     "pool": {"ready": True, "used": 2, "available": 6, "max": 8}},
        "scheduler": {"status": "RUNNING", "running": True, "jobs": 3,
                      "pending": 7, "processing": 1, "failed": 2,
                      "stale_processing": 0, "delivery_failed": 1, "dead_letter": 4,
                      "error": None},
        "ai_providers": {"status": "OK", "core_ok": 2, "core_total": 3, "providers": [
            {"name": "Gemini", "tier": 1, "status": "OK", "breaker_open": False, "configured": True},
            {"name": "Groq", "tier": 2, "status": "DEGRADED", "breaker_open": True, "configured": True},
            {"name": "Pollinations", "tier": 4, "status": "OK", "breaker_open": False, "configured": True},
        ]},
        "system": {"uptime_human": "1d 1h 1m", "asyncio_tasks": 9,
                   "errors_last_hour": 3, "errors_last_24h": 11},
    }

    titles = {}
    for lang in ("uz", "ru", "en"):
        text = asyncio.run(health_service.format_health_report(lang=lang, health=health))
        titles[lang] = text
        check(f"report[{lang}]: sarlavha kalit nomi emas (tarjima bor)",
              "health_title" not in text)
        check(f"report[{lang}]: umumiy holat DEGRADED ko'rinadi",
              "DEGRADED" in text)
        check(f"report[{lang}]: HTML tuzilishi (<b>)",
              "<b>" in text)
        check(f"report[{lang}]: provayder nomlari bor",
              "Gemini" in text and "Groq" in text)
        check(f"report[{lang}]: sonlar formatlangan",
              "12" in text and "4" in text)

    check("report: uz sarlavhasi o'zbekcha",
          "TIZIM HOLATI" in titles["uz"])
    check("report: ru sarlavhasi ruscha",
          "СОСТОЯНИЕ СИСТЕМЫ" in titles["ru"])
    check("report: en sarlavhasi inglizcha",
          "SYSTEM HEALTH" in titles["en"])
    check("report: tillar bir-biridan farq qiladi",
          len({titles["uz"], titles["ru"], titles["en"]}) == 3)

    # HTML injeksiya himoyasi: xato matnidagi <script> ESCAPE bo'lishi shart
    evil = health.copy()
    evil["database"] = dict(health["database"], status="UNHEALTHY", ok=False,
                            error='OperationalError: <script>alert("x")</script>')
    evil["status"] = "UNHEALTHY"
    text = asyncio.run(health_service.format_health_report(lang="uz", health=evil))
    check("report: <script> escape qilingan (raw yo'q)",
          "<script>" not in text and "&lt;script&gt;" in text)
    check("report: UNHEALTHY ko'rinadi", "UNHEALTHY" in text)

    # health=None → o'zi tekshiradi (DB mock bilan, crash yo'q)
    import database as db
    orig_ping = db.ping_db_with_latency
    orig_counts = db.get_post_health_counts
    orig_pool = db.get_db_pool_status
    try:
        db.ping_db_with_latency = lambda: {"ok": True, "latency_ms": 1.0, "error": None}
        db.get_post_health_counts = lambda: {"pending": 0, "processing": 0, "failed": 0,
                                             "stale_processing": 0, "delivery_failed": 0,
                                             "dead_letter": 0}
        db.get_db_pool_status = lambda: {"ready": False}
        health_service.register_scheduler(None)  # scheduler ro'yxatga olinmagan
        text = asyncio.run(health_service.format_health_report(lang="ru"))
        check("report: health=None → avtomatik tekshiruv ishlaydi",
              "СОСТОЯНИЕ" in text and "—" in text)
    finally:
        db.ping_db_with_latency = orig_ping
        db.get_post_health_counts = orig_counts
        db.get_db_pool_status = orig_pool


# ============================================================
# 3. DB YORDAMCHILARI (database.py — QO'SHIMCHA, BUZMAYDIGAN)
# ============================================================
def test_db_health_helpers():
    print("== database: ping_db_with_latency va get_post_health_counts ==")
    import database as db
    from contextlib import contextmanager

    # --- ping_db_with_latency: muvaffaqiyat ---
    class _FakeCursor:
        def execute(self, query, params=None):
            assert "SELECT 1" in query
        def fetchone(self):
            return (1,)
    @contextmanager
    def _fake_cursor(*a, **kw):
        yield _FakeCursor()

    orig = db.db_cursor
    try:
        db.db_cursor = _fake_cursor
        result = db.ping_db_with_latency()
        check("db ping: ok=True", result["ok"] is True)
        check("db ping: latency ms raqam",
              isinstance(result["latency_ms"], (int, float)))
        check("db ping: error yo'q", result["error"] is None)

        # --- ping_db_with_latency: xato ---
        @contextmanager
        def _bad_cursor(*a, **kw):
            raise RuntimeError("connection refused")
        db.db_cursor = _bad_cursor
        result = db.ping_db_with_latency()
        check("db ping: xatoda ok=False", result["ok"] is False)
        check("db ping: xato matni saqlanadi",
              "connection refused" in (result["error"] or ""))
        check("db ping: xatoda latency None", result["latency_ms"] is None)

        # --- get_post_health_counts: so'rovlar va mapping ---
        class _CountsCursor:
            def __init__(self):
                self.queries = []
            def execute(self, query, params=None):
                self.queries.append(query)
            def fetchone(self):
                if "scheduled_posts" in self.queries[-1]:
                    return (3, 1, 2, 1)   # pending, processing, failed, stale
                return (7, 4)             # delivery_failed, dead_letter
        cc = _CountsCursor()

        @contextmanager
        def _counts_cursor(*a, **kw):
            yield cc

        db.db_cursor = _counts_cursor
        counts = db.get_post_health_counts()
        check("db counts: pending", counts["pending"] == 3, str(counts))
        check("db counts: processing", counts["processing"] == 1)
        check("db counts: failed", counts["failed"] == 2)
        check("db counts: stale_processing", counts["stale_processing"] == 1)
        check("db counts: delivery_failed", counts["delivery_failed"] == 7)
        check("db counts: dead_letter", counts["dead_letter"] == 4)
        check("db counts: ikkala jadval so'ralgan",
              any("scheduled_posts" in q for q in cc.queries) and
              any("post_deliveries" in q for q in cc.queries))
        check("db counts: stale chegara SQL'da (10 daqiqa)",
              "10 minutes" in cc.queries[0])

        # --- get_post_health_counts: xatoda crash YO'Q ---
        db.db_cursor = _bad_cursor
        counts = db.get_post_health_counts()
        check("db counts: xatoda ham dict qaytadi", isinstance(counts, dict))
        check("db counts: xatoda error kaliti", "error" in counts)
        check("db counts: xatoda ham asosiy kalitlar nol bilan",
              counts.get("dead_letter") == 0)
    finally:
        db.db_cursor = orig


# ============================================================
# 4. GLOBAL UNIVERSAL ERROR HANDLER
# ============================================================
class _FakeMsg:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return True


class _FakeQuery:
    def __init__(self):
        self.answers = []
    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


class _FakeUpdMsg:
    def __init__(self, msg, user_id=None):
        self.effective_message = msg
        self.effective_user = type("U", (), {"id": user_id})() if user_id else None


class _FakeUpdQuery:
    def __init__(self, query, user_id=None):
        self.callback_query = query
        self.effective_message = None
        self.effective_user = type("U", (), {"id": user_id})() if user_id else None


class _FakeCtx:
    def __init__(self, error, lang=None):
        self.error = error
        self.user_data = {"lang": lang} if lang else {}


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []
    def emit(self, record):
        self.records.append(record)


def test_error_handler_friendly_messages():
    print("== Error handler: foydalanuvchiga xushmuomala xabar (traceback'SIZ) ==")
    from handlers.error_handler import (
        global_error_handler, _reset_error_stats,
    )

    _reset_error_stats()

    async def _run():
        msg = _FakeMsg()
        upd = _FakeUpdMsg(msg, user_id=42)
        ctx = _FakeCtx(ValueError("boom"), lang="uz")
        await global_error_handler(upd, ctx)
        return msg

    msg = asyncio.run(_run())
    check("eh: foydalanuvchiga FAQAT 1 ta xushmuomala xabar",
          len(msg.replies) == 1, str(msg.replies))
    reply = msg.replies[0] if msg.replies else ""
    check("eh: uz xabari xushmuomala", "xatolik" in reply.lower(), reply)
    check("eh: traceback so'zi YO'Q", "Traceback" not in reply and "traceback" not in reply)
    check("eh: istisno matni YO'Q", "boom" not in reply)
    check("eh: Python turi YO'Q", "ValueError" not in reply)

    # RU va EN
    async def _run_lang(lang):
        msg = _FakeMsg()
        await global_error_handler(_FakeUpdMsg(msg, 42), _FakeCtx(RuntimeError("x"), lang=lang))
        return msg.replies[0] if msg.replies else ""

    ru = asyncio.run(_run_lang("ru"))
    check("eh: RU xabar", "непредвиденная ошибка" in ru, ru)
    en = asyncio.run(_run_lang("en"))
    check("eh: EN xabar (EN overlay)", "error" in en.lower(), en)
    check("eh: EN xabar RU/uz emas", "непредвиденная" not in en and "Kutilmagan" not in en)

    # Kritik DB xatosida ham foydalanuvchiga faqat xushmuomala xabar
    import psycopg2
    async def _run_db_error():
        msg = _FakeMsg()
        await global_error_handler(
            _FakeUpdMsg(msg, 42),
            _FakeCtx(psycopg2.OperationalError(
                'connection to server failed: FATAL: password authentication failed'), lang="ru"),
        )
        return msg.replies[0] if msg.replies else ""

    reply = asyncio.run(_run_db_error())
    check("eh: DB xatosida ham SQL tafsiloti YO'Q",
          "password" not in reply and "FATAL" not in reply and "server" not in reply, reply)
    check("eh: DB xatosida ham xushmuomala", "непредвиденная ошибка" in reply)


def test_error_handler_never_crashes():
    print("== Error handler: hech qachon yiqilmaydi ==")
    from handlers.error_handler import global_error_handler, _reset_error_stats

    _reset_error_stats()

    # 1) update=None
    async def _none_update():
        await global_error_handler(None, _FakeCtx(RuntimeError("no update")))
    try:
        asyncio.run(_none_update())
        check("eh: update=None → crash yo'q", True)
    except Exception as e:
        check("eh: update=None → crash yo'q", False, str(e))

    # 2) error=None
    async def _none_error():
        msg = _FakeMsg()
        await global_error_handler(_FakeUpdMsg(msg, 1), _FakeCtx(None, lang="uz"))
        return msg
    try:
        asyncio.run(_none_error())
        check("eh: error=None → crash yo'q", True)
    except Exception as e:
        check("eh: error=None → crash yo'q", False, str(e))

    # 3) reply_text o'zi yiqilsa (chat o'chirilgan, BotBlocked...)
    class _BrokenMsg:
        async def reply_text(self, text, **kwargs):
            raise RuntimeError("Bot was blocked by the user")
    async def _broken_reply():
        await global_error_handler(
            _FakeUpdMsg(_BrokenMsg(), 2), _FakeCtx(ValueError("x"), lang="uz"))
    try:
        asyncio.run(_broken_reply())
        check("eh: reply xatosi yutiladi", True)
    except Exception as e:
        check("eh: reply xatosi yutiladi", False, str(e))

    # 4) faqat callback_query (message yo'q) → toast javob
    async def _query_only():
        q = _FakeQuery()
        await global_error_handler(_FakeUpdQuery(q, 3), _FakeCtx(ValueError("x"), lang="ru"))
        return q
    q = asyncio.run(_query_only())
    check("eh: callback faqat toast bilan javoblanadi",
          len(q.answers) == 1, str(q.answers))
    # 🌐 Toast endi foydalanuvchi tilida: _FakeCtx(lang="ru") → ruscha
    # qisqa xato matni ("⚠️ Произошла ошибка"), traceback yo'q.
    from locales.translations import get_text as _gt
    check("eh: toast matni xavfsiz (tilga mos, traceback'siz)",
          q.answers and q.answers[0][0] == _gt("sys_error_short", "ru"),
          str(q.answers))


def test_error_handler_structured_log_and_critical():
    print("== Error handler: strukturalli log + kritik xatolar ==")
    from handlers.error_handler import (
        global_error_handler, get_error_stats, _reset_error_stats,
    )

    _reset_error_stats()
    root = logging.getLogger()
    capture = _LogCapture()
    root.addHandler(capture)
    try:
        # handler_name aniqlash: xato handlers moduli ICHIDA ko'tariladi
        from handlers import error_handler as eh_mod

        try:
            # _count_since(str) — TypeError handlers/error_handler.py ICHIDA
            eh_mod._count_since("not-a-number")
        except TypeError as e:
            inner_err = e

        async def _run():
            msg = _FakeMsg()
            await global_error_handler(_FakeUpdMsg(msg, 777), _FakeCtx(inner_err, lang="uz"))
        asyncio.run(_run())

        bot_errors = [r for r in capture.records if "[BOT_ERROR]" in r.getMessage()]
        check("log: [BOT_ERROR] yozuvi bor", len(bot_errors) >= 1)
        payload = None
        for r in bot_errors:
            try:
                payload = json.loads(r.getMessage().replace("[BOT_ERROR] ", "", 1))
                break
            except Exception:
                continue
        check("log: strukturalli JSON parse bo'ladi", payload is not None)
        if payload:
            check("log: user_id saqlangan", payload.get("user_id") == 777, str(payload))
            check("log: handler_name saqlangan",
                  "error_handler" in str(payload.get("handler_name", "")),
                  str(payload.get("handler_name")))
            check("log: exception turi saqlangan",
                  payload.get("exception_type") == "TypeError")
            check("log: update turi saqlangan",
                  payload.get("update_type") == "message")
            check("log: traceback log RECORD'da (foydalanuvchiga emas)",
                  bot_errors[0].exc_info is not None)

        # Kritik DB xato → [CRITICAL_HEALTH] + stats critical
        import psycopg2
        critical_records_before = sum(
            1 for r in capture.records if "[CRITICAL_HEALTH]" in r.getMessage())
        async def _run_critical():
            await global_error_handler(
                _FakeUpdMsg(_FakeMsg(), 888),
                _FakeCtx(psycopg2.OperationalError("server closed the connection"), lang="uz"),
            )
        asyncio.run(_run_critical())
        critical_records_after = sum(
            1 for r in capture.records if "[CRITICAL_HEALTH]" in r.getMessage())
        check("log: kritik xato [CRITICAL_HEALTH] bilan ajratilgan",
              critical_records_after > critical_records_before)

        stats = get_error_stats()
        check("stats: total hisoblangan", stats["total"] >= 2, str(stats))
        check("stats: critical sanalgan", stats.get("critical_last_24h", 0) >= 1, str(stats))
        check("stats: last_hour/last_24h mavjud",
              "last_hour" in stats and "last_24h" in stats)
    finally:
        root.removeHandler(capture)


def test_classify_error():
    print("== Error handler: kritik xatolarni tasniflash ==")
    from handlers.error_handler import classify_error
    import psycopg2

    check("classify: OperationalError → critical",
          classify_error(psycopg2.OperationalError("connection refused")) == "critical")
    check("classify: InterfaceError → critical",
          classify_error(psycopg2.InterfaceError("connection already closed")) == "critical")
    check("classify: TimeoutError → critical",
          classify_error(TimeoutError()) == "critical")
    check("classify: ConnectionError → critical",
          classify_error(ConnectionError("reset by peer")) == "critical")
    check("classify: 'could not connect' matni → critical",
          classify_error(RuntimeError("could not connect to server")) == "critical")
    check("classify: ValueError → normal",
          classify_error(ValueError("boom")) == "normal")
    check("classify: BadRequest (Telegram) → normal",
          classify_error(RuntimeError("Message is not modified")) == "normal")
    check("classify: None → normal", classify_error(None) == "normal")


def test_error_handler_registration():
    print("== Error handler: PTB ga ulanish va orqaga moslik ==")
    from handlers.error_handler import (
        global_error_handler, register_error_handlers, error_handler,
    )

    registered = []
    class _FakeApp:
        def add_error_handler(self, handler):
            registered.append(handler)

    app = _FakeApp()
    register_error_handlers(app)
    check("register: add_error_handler chaqirildi", len(registered) == 1)
    check("register: global_error_handler ulangan",
          registered and registered[0] is global_error_handler)

    # Orqaga moslik: main.error_handler hali ham chaqiriladigan alias
    import main as main_mod
    check("orqaga mos: main.error_handler mavjud",
          callable(getattr(main_mod, "error_handler", None)))
    check("orqaga mos: main.error_handler == global handler",
          main_mod.error_handler is global_error_handler)
    check("orqaga mos: handlers.error_handler.error_handler alias",
          error_handler is global_error_handler)

    # /health buyrug'i ro'yxatdan o'tgan (source darajasida)
    import handlers as handlers_pkg
    src = open(handlers_pkg.__file__, encoding="utf-8").read()
    check("register: CommandHandler('health') ro'yxatdan o'tgan",
          'CommandHandler("health"' in src)


# ============================================================
# 5. /health — RBAC (faqat system_settings ruxsati)
# ============================================================
def test_health_rbac():
    print("== /health: RBAC — oddiy foydalanuvchi va SUPER_ADMIN rad etiladi ==")
    from services import rbac_service
    from services.rbac_service import Role
    import handlers.health as health_mod
    from services import health_service

    # Keshni tozalash va qat'iy nazorat: DB'ga hech qanday murojaat bo'lmasin
    rbac_service.invalidate_role_cache()
    orig_read = rbac_service._read_stored_role
    rbac_service._read_stored_role = lambda uid: None  # DB YO'Q deb hisoblaymiz
    rbac_service._cache_set(PLAIN_USER_ID, Role.USER)
    rbac_service._cache_set(SUPER_ADMIN_ID, Role.SUPER_ADMIN)
    rbac_service._cache_set(OWNER_ID, Role.OWNER)

    called = {"report": 0}
    orig_report = health_service.format_health_report

    async def _fake_report(lang="uz", health=None):
        called["report"] += 1
        return "🩺 FAKE REPORT"

    health_service.format_health_report = _fake_report
    try:
        # --- Oddiy foydalanuvchi: rad javobi, handler ICHIGA KIRMAYDI ---
        async def _plain():
            msg = _FakeMsg()
            upd = _FakeUpdMsg(msg, user_id=PLAIN_USER_ID)
            ctx = _FakeCtx(None, lang="uz")
            await health_mod.health_command(upd, ctx)
            return msg
        msg = asyncio.run(_plain())
        check("rbac: oddiy foydalanuvchiga rad javobi bor",
              len(msg.replies) == 1 and "ruxsat" in msg.replies[0].lower(),
              str(msg.replies))
        check("rbac: oddiy foydalanuvchi uchun health hisobot YO'Q",
              called["report"] == 0)
        check("rbac: hisobot matni oddiy foydalanuvchiga yuborilmadi",
              not msg.replies or "FAKE REPORT" not in msg.replies[0])

        # --- SUPER_ADMIN: system_settings YO'Q → rad etiladi (matritsa bo'yicha) ---
        async def _superadmin():
            msg = _FakeMsg()
            upd = _FakeUpdMsg(msg, user_id=SUPER_ADMIN_ID)
            ctx = _FakeCtx(None, lang="ru")
            await health_mod.health_command(upd, ctx)
            return msg
        msg = asyncio.run(_superadmin())
        check("rbac: SUPER_ADMIN system_settings uchun rad etiladi",
              len(msg.replies) == 1 and "ruxsat" in msg.replies[0].lower(),
              str(msg.replies))
        check("rbac: SUPER_ADMIN uchun ham hisobot yo'q", called["report"] == 0)

        # --- OWNER: ruxsat bor → hisobot yuboriladi ---
        async def _owner():
            msg = _FakeMsg()
            upd = _FakeUpdMsg(msg, user_id=OWNER_ID)
            ctx = _FakeCtx(None, lang="uz")
            await health_mod.health_command(upd, ctx)
            return msg
        msg = asyncio.run(_owner())
        check("rbac: OWNER /health oladi (hisobot chaqirildi)",
              called["report"] == 1)
        check("rbac: OWNER hisobot matni yuborildi",
              msg.replies and "FAKE REPORT" in msg.replies[0], str(msg.replies))

        # --- hisobot yaratish o'zi yiqilsa — foydalanuvchi xavfsiz javob oladi ---
        async def _boom_report(lang="uz", health=None):
            raise RuntimeError("secret internal failure details")
        health_service.format_health_report = _boom_report
        async def _owner_boom():
            msg = _FakeMsg()
            upd = _FakeUpdMsg(msg, user_id=OWNER_ID)
            ctx = _FakeCtx(None, lang="uz")
            await health_mod.health_command(upd, ctx)
            return msg
        msg = asyncio.run(_owner_boom())
        check("rbac: hisobot xatosida foydalanuvchiga xavfsiz javob",
              msg.replies and "secret internal failure" not in msg.replies[0],
              str(msg.replies))
    finally:
        health_service.format_health_report = orig_report
        rbac_service._read_stored_role = orig_read
        rbac_service.invalidate_role_cache()


def test_health_rbac_permission_matrix():
    print("== /health: system_settings faqat OWNER'da (RBAC matritsasi) ==")
    from services.rbac_service import (
        has_permission, PERM_SYSTEM_SETTINGS, permissions_for, Role,
    )

    check("rbac: OWNER → system_settings bor",
          has_permission(OWNER_ID, PERM_SYSTEM_SETTINGS) is True)
    check("rbac: SUPER_ADMIN → system_settings YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.SUPER_ADMIN))
    check("rbac: ADMIN → system_settings YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.ADMIN))
    check("rbac: MODERATOR → system_settings YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.MODERATOR))
    check("rbac: FINANCE → system_settings YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.FINANCE))
    check("rbac: USER → system_settings YO'Q",
          PERM_SYSTEM_SETTINGS not in permissions_for(Role.USER))


# ============================================================
# 6. INTEGRATSIYA — main.py va handlers registratsiyasi
# ============================================================
def test_main_integration():
    print("== Integratsiya: main.py health registratsiyasi ==")
    import main as main_mod
    src = open(main_mod.__file__, encoding="utf-8").read()

    check("main: health_service import qilingan",
          "from services import health_service" in src)
    check("main: register_scheduler chaqirilgan",
          "health_service.register_scheduler(scheduler)" in src)
    check("main: register_application chaqirilgan",
          "health_service.register_application(application)" in src)
    check("main: mark_bot_started chaqirilgan",
          "health_service.mark_bot_started()" in src)
    check("main: register_error_handlers ulangan",
          "register_error_handlers(application)" in src)
    check("main: eski inline error mantiq olib tashlangan (alias delegatsiya)",
          "error_handler = global_error_handler" in src)


# ============================================================
# 7. TARJIMALAR PARITETI (uz ↔ ru ↔ en)
# ============================================================
def test_translations_parity():
    print("== Tarjimalar: health_* kalitlari pariteti ==")
    from locales.translations import (
        TRANSLATIONS, get_text, translation_parity_report,
    )

    health_keys = sorted(k for k in TRANSLATIONS["uz"] if k.startswith("health_"))
    check("tarjima: health_* kalitlari mavjud (19 ta)",
          len(health_keys) >= 19, str(len(health_keys)))

    for lang in ("ru", "en"):
        missing = [k for k in health_keys if k not in TRANSLATIONS[lang]]
        check(f"tarjima: {lang.upper()} blokida hammasi bor",
              not missing, str(missing[:5]))

    report = translation_parity_report()
    check("tarjima: umumiy UZ↔RU paritet buzilmagan",
          report["in_sync"] is True, str(report)[:120])

    for key in health_keys:
        for lang in ("uz", "ru", "en"):
            val = get_text(key, lang)
            if val != key:
                continue
            check(f"tarjima: {key}/{lang} kalit nomi qaytmaydi", False, val)
            break

    # format plaseholderlari ishlaydi (KeyError/crash yo'q)
    sample = get_text("health_db_latency", "uz").format(latency="12.3")
    check("tarjima: format placeholder ishlaydi", "12.3" in sample, sample)
    sample_ru = get_text("health_errors", "ru").format(hour="1", day="2")
    check("tarjima: ru format placeholder ishlaydi", "1" in sample_ru and "2" in sample_ru)


# ============================================================
# ASOSIY
# ============================================================
def main():
    print("=" * 60)
    print("POSTASSIST V2 — 7-BOSQICH: HEALTH & MONITORING TESTLARI")
    print("=" * 60)
    test_health_components()
    test_health_degraded_reasons()
    test_health_ai_providers()
    test_uptime_helpers()
    test_format_health_report()
    test_db_health_helpers()
    test_error_handler_friendly_messages()
    test_error_handler_never_crashes()
    test_error_handler_structured_log_and_critical()
    test_classify_error()
    test_error_handler_registration()
    test_health_rbac()
    test_health_rbac_permission_matrix()
    test_main_integration()
    test_translations_parity()

    print("-" * 60)
    print(f"Jami: {passed + failures}, muvaffaqiyatli: {passed}, xato: {failures}")
    if failures:
        print("❌ BA'ZI TESTLAR YIQILDI")
        sys.exit(1)
    print("✅ BARCHA HEALTH & MONITORING TESTLAR YASHIL")


if __name__ == "__main__":
    main()
