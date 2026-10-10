#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⏱ SPRINT 4 — ONBOARDING TELEMETRIYASI: TTFP + D1/D7 RETENTION (deterministik).

Tekshiriladi:
  (1) 🕒 ``parse_moment`` — ISO (naive/aware, Z) va datetime qiymatlari;
  (2) ⏱ ``ttfp_seconds`` — nol/manfiy/None holatlari (manfiy → 0.0);
  (3) 📈 ``summarize_ttfp`` — o'rtacha, mediana, p90 (nearest-rank), 1h/24h
      ulushlari; bo'sh ro'yxat → ``available=False`` (soxta raqam yo'q);
  (4) 🔁 ``retention_rates`` — D1/D7 formulasi: "qaytdi" = ``last_active_at
      >= created_at + N kun``; kohorta yetilmagan yozuvlar hisobga olinmaydi;
  (5) 🧾 ``build_report`` — ro'yxatdan o'tish/aktivatsiya + d1/d7 ni birlashtiradi
      (dict va tuple qatorlar bilan bir xil natija);
  (6) 🧠 JARAYON XOTIRASI — ``record_start``/``record_first_post`` (birinchi
      yozuv ustuvor), ``in_memory_report`` (waiting/activation_rate), reset;
  (7) 🗄 ``fetch_report`` — TTL kesh, baza xatosida ``[]`` (statistika ekrani
      yiqilmaydi), soxta db-modul bilan deterministik;
  (8) 🖥 ADMIN BLOKI — ``_build_launch_gauges_text`` uchala tilda, bo'sh
      hisobotda «ma'lumot yo'q», ``build_stats_text_with_gauges`` esa eski
      admin statistikasini O'ZGARTIRMAYDI (regressiya qo'riqoni);
  (9) 🪝 HOOKLAR — ``/start`` da ``record_start`` (yangi foydalanuvchi) va
      ``posts_repository.add_post`` da ``record_first_post`` chaqirilishi;
  (10) 🐘 LIVE POSTGRESQL — real ``users``/``scheduled_posts`` ustida
      ``get_retention_cohort`` + TTFP/D1/D7 qiymatlari (pgserver bo'lmasa —
      o'tkazib yuboriladi).
"""
import asyncio
import datetime as dt
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOT = os.path.join(ROOT, "telegram_bot")
if BOT not in sys.path:
    sys.path.insert(0, BOT)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:TTFP_TELEMETRY_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

PASSED = 0
FAILED = 0
LANGS = ("uz", "ru", "en")
NOW = dt.datetime(2026, 10, 8, 12, 0, 0, tzinfo=dt.timezone.utc)


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")
    return bool(condition)


def _iso(days=0, hours=0, minutes=0, seconds=0):
    return (NOW - dt.timedelta(days=days, hours=hours, minutes=minutes,
                               seconds=seconds)).isoformat()


def _row(uid, created_days, post_days=None, last_days=None):
    """Deterministik kohorta qatori (``get_retention_cohort`` shakli)."""
    return {
        "user_id": uid,
        "created_at": _iso(days=created_days),
        "first_post_at": None if post_days is None else _iso(days=post_days),
        "last_active_at": None if last_days is None else _iso(days=last_days),
    }


# ---------------------------------------------------------------------------
# 1-3) Vaqt, TTFP va yig'indi
# ---------------------------------------------------------------------------
def test_moment_and_ttfp():
    print("\n== TEST 1: parse_moment / ttfp_seconds / summarize_ttfp ==")
    from services import onboarding_telemetry as tel

    check("ISO naive qator", tel.parse_moment("2026-10-08T12:00:00") is not None)
    check("ISO 'Z' (UTC)", tel.parse_moment("2026-10-08T12:00:00Z") == NOW,
          tel.parse_moment("2026-10-08T12:00:00Z"))
    check("aware ISO AYNIAN saqlanadi (siljish yo'q)",
          tel.parse_moment("2026-10-08T12:00:00+00:00") == NOW)
    check("bo'sh/None → None",
          tel.parse_moment("") is None and tel.parse_moment(None) is None)
    check("buzilgan qator → None (crash yo'q)",
          tel.parse_moment("kecha ertalab") is None)
    check("datetime qaytarilsa o'zi ishlatiladi",
          tel.parse_moment(NOW) == NOW)
    check("epoch float → datetime", tel.parse_moment(1_700_000_000) is not None)

    check("TTFP: 2 soat = 7200 sekund",
          tel.ttfp_seconds(_iso(hours=2), _iso()) == 7200.0,
          tel.ttfp_seconds(_iso(hours=2), _iso()))
    check("TTFP: darhol (0 sekund)",
          tel.ttfp_seconds(_iso(), _iso()) == 0.0)
    check("TTFP: manfiy → 0.0 (soxta manfiy yo'q)",
          tel.ttfp_seconds(_iso(), _iso(hours=5)) == 0.0)
    check("TTFP: post bo'lmasa → None",
          tel.ttfp_seconds(_iso(days=1), None) is None)
    check("TTFP: register bo'lmasa → None",
          tel.ttfp_seconds(None, _iso()) is None)

    empty = tel.summarize_ttfp([])
    check("bo'sh ro'yxat: available=False va nollar",
          empty["available"] is False and empty["count"] == 0
          and empty["avg_seconds"] == 0.0)
    check("bo'sh ro'yxat: 1h/24h ulushlari 0.0 (bazadan to'qib qo'yilmaydi)",
          empty["within_1h_rate"] == 0.0 and empty["within_24h_rate"] == 0.0)

    # 10, 60, 600, 1800, 7200, 86400, 90000 sekund
    values = [10, 60, 600, 1800, 7200, 86400, 90000]
    summary = tel.summarize_ttfp(values)
    check("count to'g'ri", summary["count"] == 7)
    check("avg = 26581.4 (186070/7)", summary["avg_seconds"] == 26581.4,
          summary["avg_seconds"])
    check("mediana (nearest-rank) = 1800",
          summary["median_seconds"] == 1800.0, summary["median_seconds"])
    check("p90 (nearest-rank, ceil(0.9*7)=7) = 90000",
          summary["p90_seconds"] == 90000.0, summary["p90_seconds"])
    check("min/max", summary["min_seconds"] == 10.0
          and summary["max_seconds"] == 90000.0)
    check("1 soat ichida: 4/7 = 0.5714",
          summary["within_1h_rate"] == 0.5714, summary["within_1h_rate"])
    check("24 soat ichida: 6/7 = 0.8571",
          summary["within_24h_rate"] == 0.8571, summary["within_24h_rate"])
    check("None qiymatlar tashlab yuboriladi",
          tel.summarize_ttfp([None, 100, None])["count"] == 1)


# ---------------------------------------------------------------------------
# 4-5) Retention va hisobot
# ---------------------------------------------------------------------------
def test_retention_and_report():
    print("\n== TEST 2: retention_rates / build_report ==")
    from services import onboarding_telemetry as tel

    rows = [
        # 10 kun oldin ro'yxatdan o'tgan, har kuni faol → D1 ✓, D7 ✓
        _row(1, 10, post_days=10, last_days=0),
        # 10 kun oldin, oxirgi faollik 1 kun oldin → D1 ✓, D7 ✓
        _row(2, 10, last_days=1),
        # 8 kun oldin, faollik 5 kun oldin → D1 ✓, D7 ✗
        _row(3, 8, last_days=5),
        # 3 kun oldin, faollik 0 kun → D1 ✓, D7 kohorta yetilmagan
        _row(4, 3, last_days=0),
        # 6 soat oldin — D1 uchun ham yetilmagan
        _row(5, 0, last_days=0),
    ]
    d1 = tel.retention_rates(rows, now=NOW, day=1)
    check("D1: 4 ta yaroqli (5-kunlik kohorta hali yetilmagan)",
          d1["eligible"] == 4, d1)
    check("D1: 4 ta qaytdi (100%)", d1["returned"] == 4 and d1["rate"] == 1.0, d1)
    check("D1: day maydoni", d1["day"] == 1)

    d7 = tel.retention_rates(rows, now=NOW, day=7)
    check("D7: 3 ta yaroqli (8/10 kunliklar)",
          d7["eligible"] == 3, d7)
    check("D7: 2 tasi qaytdi (0.6667)",
          d7["returned"] == 2 and d7["rate"] == 0.6667, d7)

    check("bo'sh kohorta: eligible=0, rate=0.0 (ma'lumot yo'q)",
          tel.retention_rates([], now=NOW) == {"day": 1, "eligible": 0,
                                               "returned": 0, "rate": 0.0})
    check("buzilgan sana — jim o'tkazib yuboriladi",
          tel.retention_rates([{"created_at": "yo'q"}], now=NOW)["eligible"] == 0)
    check("naive sana ham qabul qilinadi",
          tel.retention_rates([{"created_at": "2026-10-07T12:00:00",
                                "last_active_at": "2026-10-08T11:00:00"}],
                              now=NOW)["eligible"] == 1)

    report = tel.build_report(rows, now=NOW, window_days=30)
    check("hisobot: available=True", report["available"] is True)
    check("hisobot: ro'yxatdan o'tganlar = 5", report["registered"] == 5,
          report["registered"])
    check("hisobot: aktivlashgan = 1 (faqat 1 ta birinchi post)",
          report["activated"] == 1, report["activated"])
    check("hisobot: aktivatsiya ulushi = 0.2",
          report["activation_rate"] == 0.2, report["activation_rate"])
    check("hisobot: TTFP = 0 sekund (bir xil vaqt)",
          report["ttfp"]["available"] is True
          and report["ttfp"]["avg_seconds"] == 0.0, report["ttfp"])
    check("hisobot: d1/d7 joyida",
          report["retention"]["d1"]["eligible"] == 4
          and report["retention"]["d7"]["eligible"] == 3)
    check("hisobot: oyna kuni = 30", report["window_days"] == 30)
    check("hisobot: generated_at ISO", str(report["generated_at"]).startswith("2026-10-08"))

    # tuple qatorlar (repository namunasiga mos) — bir xil natija.
    tuple_rows = [
        (1, _iso(days=10), _iso(days=1), _iso(days=9)),
        (2, _iso(days=4), _iso(days=3), _iso(days=1)),
    ]
    t_report = tel.build_report(tuple_rows, now=NOW)
    check("tuple qatorlar: registered=2, activated=2",
          t_report["registered"] == 2 and t_report["activated"] == 2,
          t_report)
    # (1): created 10 kun → post 9 kun = 1 kun; (2): created 4 kun → post 1 kun = 3 kun.
    check("tuple qatorlar: TTFP o'rtachasi = 2 kun (86400 + 259200)/2",
          t_report["ttfp"]["avg_seconds"] == 172800.0, t_report["ttfp"])
    check("tuple qatorlar: mediana (nearest-rank) = 1 kun",
          t_report["ttfp"]["median_seconds"] == 86400.0)
    check("tuple qatorlar: last_active maydoni (indeks 2) TTFPga aralashmaydi",
          t_report["ttfp"]["count"] == 2)
    check("bo'sh kohorta: available=False, yiqilmaydi",
          tel.build_report([], now=NOW)["available"] is False)


# ---------------------------------------------------------------------------
# 6-7) Jarayon xotirasi va kesh
# ---------------------------------------------------------------------------
def test_memory_and_fetch():
    print("\n== TEST 3: jarayon xotirasi + fetch_report (kesh) ==")
    from services import onboarding_telemetry as tel

    tel.reset()
    tel.reset_cache()
    check("reset: bo'sh hisobot",
          tel.in_memory_report()["started"] == 0
          and tel.in_memory_report()["available"] is False)

    tel.record_start(101, ts=NOW.timestamp())
    tel.record_first_post(101, ts=(NOW + dt.timedelta(minutes=45)).timestamp())
    tel.record_start(102, ts=NOW.timestamp())              # hali post yo'q
    tel.record_start(101, ts=(NOW + dt.timedelta(hours=3)).timestamp())  # birinchi ustuvor
    report = tel.in_memory_report(now=NOW + dt.timedelta(hours=4))
    check("memory: started=2", report["started"] == 2, report)
    check("memory: activated=1, waiting=1",
          report["activated"] == 1 and report["waiting"] == 1, report)
    check("memory: TTFP = 45 daqiqa (qayta yozuv ustuvor emas)",
          report["avg_seconds"] == 2700.0, report["avg_seconds"])
    check("memory: activation_rate = 0.5", report["activation_rate"] == 0.5)
    check("memory: manba = memory", report["source"] == "memory")
    tel.record_first_post(101, ts=(NOW + dt.timedelta(days=5)).timestamp())
    check("memory: birinchi post vaqti o'zgarmaydi",
          tel.in_memory_report()["avg_seconds"] == 2700.0)
    tel.reset()
    check("reset: tozalandi", tel.in_memory_report()["started"] == 0)

    # fetch_cohort / fetch_report — soxta db-modul.
    class _FakeDB:
        def __init__(self, rows=None, fail=False):
            self.rows = rows or []
            self.fail = fail
            self.calls = 0

        def get_retention_cohort(self, days=30):
            self.calls += 1
            if self.fail:
                raise RuntimeError("db uzildi")
            return list(self.rows)

    fake = _FakeDB([_row(1, 10, post_days=10, last_days=0)])
    fetched = tel.fetch_report(fake, 30, now=NOW, ttl=60)
    check("fetch_report: manba = db", fetched["source"] == "db")
    check("fetch_report: registered=1", fetched["registered"] == 1)
    check("fetch_report: 2-chaqiruv keshdan (db faqat 1 marta)",
          tel.fetch_cohort(fake, 30, ttl=60) is not None and fake.calls == 1,
          fake.calls)
    tel.reset_cache()
    tel.fetch_cohort(fake, 30, ttl=60)
    check("reset_cache: yangi so'rov yuboriladi", fake.calls == 2, fake.calls)

    broken = _FakeDB(fail=True)
    check("baza xatosi: fetch_cohort → [] (ekran yiqilmaydi)",
          tel.fetch_cohort(broken, 30, ttl=0) == [])
    check("baza xatosi: fetch_report → available=False, crash yo'q",
          tel.fetch_report(broken, 30, now=NOW, ttl=0)["available"] is False)
    check("db moduli funksiyasiz bo'lsa — []",
          tel.fetch_cohort(SimpleNamespace(), 30, ttl=0) == []
          and tel.fetch_cohort(None, 30) == [])
    tel.reset_cache()

    tel.record_start(103, ts=NOW.timestamp())
    fetched2 = tel.fetch_report(fake, 30, now=NOW + dt.timedelta(hours=1), ttl=0)
    check("fetch_report: jarayon xotirasi ham qo'shiladi (memory bloki)",
          fetched2.get("memory", {}).get("started") == 1, fetched2.get("memory"))
    tel.reset()
    tel.reset_cache()


# ---------------------------------------------------------------------------
# 8) Admin bloki
# ---------------------------------------------------------------------------
def test_admin_gauges_block():
    print("\n== TEST 4: admin statistikasidagi TTFP/D1/D7 bloki ==")
    import handlers.admin as adm
    from services import onboarding_telemetry as tel
    from translations import admin_t

    report = tel.build_report([
        _row(1, 10, post_days=10, last_days=0),
        _row(2, 10, post_days=10, last_days=1),
        _row(3, 8, last_days=5),
    ], now=NOW, window_days=30)
    for lang in LANGS:
        block = adm._build_launch_gauges_text(report, lang)
        check(f"[{lang}] sarlavha (30 kun)", admin_t("lg_title", lang, days=30)[:8] in block)
        check(f"[{lang}] ro'yxatdan o'tganlar qatori",
              admin_t("lg_registered", lang, users=3) in block)
        check(f"[{lang}] aktivatsiya qatori (2/3 → 67%)",
              "67" in block and admin_t("lg_activated", lang, activated=2, percent="67") in block)
        check(f"[{lang}] TTFP qatori bor",
              admin_t("lg_ttfp", lang, avg="x", median="y", day_percent="z")[:10] in block)
        check(f"[{lang}] D1 qatori (100%)",
              admin_t("lg_d1", lang, percent="100", returned=3, eligible=3) in block)
        check(f"[{lang}] D7 qatori (67%)",
              admin_t("lg_d7", lang, percent="67", returned=2, eligible=3) in block)

    empty_block = adm._build_launch_gauges_text({}, "uz")
    check("bo'sh hisobot: «ma'lumot yo'q» (crash yo'q)",
          empty_block == admin_t("lg_no_data", "uz"), empty_block)
    check("None hisobot ham xavfsiz",
          adm._build_launch_gauges_text(None, "uz") == admin_t("lg_no_data", "uz"))

    # format_duration — 3 tilda.
    check("format_duration: 45 sek", adm.format_duration(45, "uz") ==
          admin_t("lg_dur_seconds", "uz", seconds=45))
    check("format_duration: 5 daqiqa", adm.format_duration(300, "uz") ==
          admin_t("lg_dur_minutes", "uz", minutes=5))
    check("format_duration: 2 soat 0 daqiqa", adm.format_duration(7200, "uz") ==
          admin_t("lg_dur_hours", "uz", hours=2, minutes=0))
    check("format_duration: 1 kun 0 soat", adm.format_duration(86400, "uz") ==
          admin_t("lg_dur_days", "uz", days=1, hours=0))
    check("format_duration: manfiy/None → 0 sek",
          adm.format_duration(-5, "uz") == admin_t("lg_dur_seconds", "uz", seconds=0)
          and adm.format_duration(None, "uz") ==
          admin_t("lg_dur_seconds", "uz", seconds=0))

    # REGRESSIYA: eski admin statistikasi matni o'zgarmaydi; gauge qo'shiladi.
    stats = {"users": 100, "channels": 9, "sponsors": 3, "pending": 4,
             "sent": 20, "cancelled": 1, "failed": 2}
    base = adm._build_full_stats_text(stats, "uz")

    class _FakeRunDB:
        def __init__(self, report, fail=False):
            self.report = report
            self.fail = fail

        async def __call__(self, func, *args, **kwargs):
            if self.fail:
                raise RuntimeError("baza uzildi")
            return self.report

    import database as db_mod

    original_run_db = db_mod.run_db
    try:
        db_mod.run_db = _FakeRunDB(report)
        composed = asyncio.run(adm.build_stats_text_with_gauges(stats, "uz"))
        db_mod.run_db = _FakeRunDB(None, fail=True)   # baza xatosi
        fallback = asyncio.run(adm.build_stats_text_with_gauges(stats, "uz"))
    finally:
        db_mod.run_db = original_run_db

    check("regressiya: eski matn AYNAN saqlanadi (prefiks)",
          composed.startswith(base + "\n\n"), composed[:60])
    check("TTFP/D1/D7 bloki matn oxirida qo'shilgan",
          admin_t("lg_title", "uz", days=30) in composed)
    check("baza xatosi: eski matn o'zgarmaydi (blok qo'shilmaydi)",
          fallback == base, fallback[-80:])
    check("gauge matni admin markerlarini buzmaydi",
          all(marker in composed for marker in
              ("Jami foydalanuvchilar", "Homiy kanallar", "Kutilayotgan postlar")))


# ---------------------------------------------------------------------------
# 9) Hooklar
# ---------------------------------------------------------------------------
def test_hooks():
    print("\n== TEST 5: /start va add_post hooklari ==")
    import importlib

    start_mod = importlib.import_module("handlers.start")
    posts_mod = importlib.import_module("repositories.posts_repository")
    import database as db_mod
    from repositories.users_repository import _UserSaveResult
    from services import onboarding_telemetry as tel

    # (a) /start: yangi foydalanuvchi → record_start chaqiriladi.
    tel.reset()
    recorded = []
    original = {
        "run_db": db_mod.run_db, "peek_profile": start_mod.peek_profile,
        "check_user_subscribed": start_mod.check_user_subscribed,
        "get_smart_reply_ad_async": start_mod.get_smart_reply_ad_async,
        "resolve_main_keyboard": start_mod.resolve_main_keyboard,
        "main_menu_intro_suffix": start_mod.main_menu_intro_suffix,
        "run_background_task": start_mod.run_background_task,
    }

    async def _fake_run_db(func, *args, **kwargs):
        if getattr(func, "__name__", "") == "save_user":
            return _UserSaveResult(is_new=True, lang="uz")
        if getattr(func, "__name__", "") == "get_user_language":
            return "uz"
        return {}

    async def _subscribed(bot, user_id):
        return True, []

    async def _no_ad(user_id):
        return ""

    async def _no_markup(*a, **kw):
        return None

    async def _no_suffix(*a, **kw):
        return ""

    def _bg(coro, **kw):
        try:
            coro.close()
        except Exception:
            pass
        return None

    db_mod.run_db = _fake_run_db
    start_mod.peek_profile = lambda uid: None
    start_mod.check_user_subscribed = _subscribed
    start_mod.get_smart_reply_ad_async = _no_ad
    start_mod.resolve_main_keyboard = _no_markup
    start_mod.main_menu_intro_suffix = _no_suffix
    start_mod.run_background_task = _bg

    # Telemetriya modulining ``record_start`` ni ushlaymiz (handler ichida
    # kech import qilinadi — shuning uchun modul atributi almashtiriladi).
    original_telemetry_record = tel.record_start
    tel.record_start = lambda uid, ts=None: recorded.append(uid)
    try:
        msg = SimpleNamespace(sent=[])

        async def _reply(text, reply_markup=None, parse_mode=None, **kw):
            msg.sent.append(text)
            return msg

        msg.reply_text = _reply
        update = SimpleNamespace(
            message=msg, effective_message=msg, callback_query=None,
            effective_user=SimpleNamespace(id=424242, first_name="T",
                                           username="t", full_name="T T"),
        )
        context = SimpleNamespace(args=[], user_data={"lang": "uz"}, chat_data={},
                                  bot=SimpleNamespace(), application=None)
        asyncio.run(start_mod.start(update, context))
    finally:
        tel.record_start = original_telemetry_record
        db_mod.run_db = original["run_db"]
        start_mod.peek_profile = original["peek_profile"]
        start_mod.check_user_subscribed = original["check_user_subscribed"]
        start_mod.get_smart_reply_ad_async = original["get_smart_reply_ad_async"]
        start_mod.resolve_main_keyboard = original["resolve_main_keyboard"]
        start_mod.main_menu_intro_suffix = original["main_menu_intro_suffix"]
        start_mod.run_background_task = original["run_background_task"]
    check("/start (yangi foydalanuvchi) → record_start(424242) chaqirildi",
          recorded == [424242], recorded)
    check("/start → salomlashish yuborildi (oqim uzilmadi)", bool(msg.sent))

    # (b) Birinchi post: ``posts_repository.add_post`` → record_first_post.
    class _Cursor:
        """Soxta kursor: advisory qulf → MAX() → INSERT ... RETURNING id."""

        def __init__(self):
            self.calls = 0

        def execute(self, sql, params=None):
            self.calls += 1

        def fetchone(self):
            return (7,) if self.calls == 2 else (555,)

    class _CursorCtx:
        def __init__(self, cursor):
            self.cursor = cursor

        def __enter__(self):
            return self.cursor

        def __exit__(self, *exc):
            return False

    fake_cursor = _Cursor()
    original_db_cursor = db_mod.db_cursor
    db_mod.db_cursor = lambda *a, **kw: _CursorCtx(fake_cursor)
    recorded_posts = []
    original_record_first = tel.record_first_post
    tel.record_first_post = lambda uid, ts=None: recorded_posts.append(uid)
    try:
        post_id = posts_mod.add_post(
            424242, "-100123", "text", "Test post", None, "2026-10-09 10:00")
    finally:
        tel.record_first_post = original_record_first
    check("add_post: post yaratildi (RETURNING id)", post_id == 555, post_id)
    check("add_post → record_first_post(user_id) chaqirildi (best-effort)",
          recorded_posts == [424242], recorded_posts)
    check("add_post: SQL bajarildi (qulf + MAX + INSERT)", fake_cursor.calls == 3,
          fake_cursor.calls)

    # (c) Telemetriya xatosi post yaratishni BUZMAYDI.
    def _boom(*a, **kw):
        raise RuntimeError("telemetriya buzildi")

    fake_cursor2 = _Cursor()
    db_mod.db_cursor = lambda *a, **kw: _CursorCtx(fake_cursor2)
    tel.record_first_post = _boom
    try:
        result = posts_mod.add_post(
            424242, "-100123", "text", "Test post 2", None, "2026-10-09 11:00")
    finally:
        tel.record_first_post = original_record_first
        db_mod.db_cursor = original_db_cursor
    check("telemetriya xatosi post yaratishni to'xtatmaydi (id=555)",
          result == 555, result)
    check("telemetriya modulida ikkala hook mavjud",
          hasattr(tel, "record_start") and hasattr(tel, "record_first_post")
          and hasattr(tel, "fetch_report"))
    check("start.py manbasida record_start chaqiruvi bor",
          "record_start" in open(
              os.path.join(BOT, "handlers", "start.py"), encoding="utf-8").read())
    check("posts_repository manbasida record_first_post chaqiruvi bor",
          "record_first_post" in open(
              os.path.join(BOT, "repositories", "posts_repository.py"),
              encoding="utf-8").read())


# ---------------------------------------------------------------------------
# 10) LIVE POSTGRESQL
# ---------------------------------------------------------------------------
def test_live_postgres():
    print("\n== TEST 6: Real PostgreSQL (retention kohortasi) ==")
    try:
        import pgserver  # noqa: F401
    except ImportError:
        print("  [SKIP] pgserver yo'q — live DB qismi o'tkazib yuborildi")
        return
    import shutil
    import tempfile

    import database as db
    from services import onboarding_telemetry as tel

    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_ttfp")
    shutil.rmtree(server_dir, ignore_errors=True)
    uri = pgserver.get_server(server_dir).get_uri()
    os.environ["DATABASE_URL"] = uri
    db.DATABASE_URL = uri
    db._reset_pool()
    db.init_db()
    tel.reset()
    tel.reset_cache()

    db.save_user(601, "ttfp_old", full_name="Old")
    db.save_user(602, "ttfp_new", full_name="New")
    # Post uchun kanal SHART (FK: scheduled_posts.channel_id → channels).
    asyncio.run(db.run_db(_create_channel, db, 601, "-100777"))
    # 601: 10 kun oldin ro'yxatdan o'tgan va faol + posti bor.
    asyncio.run(db.run_db(_backdate_user, db, 601, days=10))
    post_id = asyncio.run(db.run_db(
        db.add_post, 601, "-100777", "text", "Birinchi post", None,
        "2026-10-08 09:00"))
    if post_id:
        asyncio.run(db.run_db(_backdate_post, db, post_id, days=10))
    db.save_user(603, "ttfp_fresh", full_name="Fresh")   # bugun, postsiz

    rows = tel.fetch_cohort(db, 30, ttl=0)
    ids = {str(r.get("user_id")) if isinstance(r, dict) else str(r[0]) for r in rows}
    check("live: kohorta o'qildi (≥3 foydalanuvchi)", len(rows) >= 3, len(rows))
    check("live: yangi va eski foydalanuvchilar ichida",
          {"601", "602", "603"} <= ids, sorted(ids))

    report = tel.build_report(rows, now=dt.datetime.now(dt.timezone.utc),
                              window_days=30)
    check("live: ro'yxatdan o'tganlar ≥3", report["registered"] >= 3,
          report["registered"])
    check("live: aktivlashgan ≥1 (posti bor foydalanuvchi)", report["activated"] >= 1,
          report["activated"])
    check("live: D1/D7 bloklari hisoblanadi",
          report["retention"]["d1"]["day"] == 1
          and report["retention"]["d7"]["day"] == 7)
    check("live: TTFP o'lchandi (0 ≤ qiymat)",
          report["ttfp"]["available"] is True
          and report["ttfp"]["avg_seconds"] >= 0, report["ttfp"])

    fetched = tel.fetch_report(db, 30, ttl=0)
    check("live: fetch_report manbasi = db va crash yo'q",
          fetched["source"] == "db" and "retention" in fetched)
    db.close_pool()


def _create_channel(db_module, user_id, channel_id):
    """Live sinov uchun minimal kanal yozuvi (FK talabi)."""
    with db_module.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title) "
            "VALUES (%s, %s, %s) ON CONFLICT (channel_id) DO NOTHING",
            (int(user_id), str(channel_id), "TTFP test kanali"),
        )


def _backdate_user(db_module, user_id, *, days=10):
    """``users.created_at`` ni orqaga suradi (TTFP/retention sinovi uchun)."""
    with db_module.db_cursor() as cur:
        cur.execute(
            "UPDATE users SET created_at = NOW() - (%s || ' days')::interval, "
            "last_active_at = NOW() WHERE user_id = %s",
            (int(days), int(user_id)),
        )


def _backdate_post(db_module, post_id, *, days=10):
    """``scheduled_posts.created_at`` ni orqaga suradi."""
    with db_module.db_cursor() as cur:
        cur.execute(
            "UPDATE scheduled_posts SET created_at = NOW() - (%s || ' days')::interval "
            "WHERE id = %s",
            (int(days), int(post_id)),
        )


def main():
    print("=" * 70)
    print(" ⏱ SPRINT 4 — ONBOARDING TELEMETRIYASI (TTFP + D1/D7)")
    print("=" * 70)
    test_moment_and_ttfp()
    test_retention_and_report()
    test_memory_and_fetch()
    test_admin_gauges_block()
    test_hooks()
    test_live_postgres()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    if FAILED:
        print(" [FAIL] ONBOARDING TELEMETRIYA TESTLARIDA XATOLIK BOR ✘")
        return 1
    print(" SPRINT 4 — ONBOARDING TELEMETRIYA 100% YASHIL ✔")
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
