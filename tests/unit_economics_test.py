#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""💰 SPRINT 4 — UNIT ECONOMICS TESTI (deterministik).

Tekshiriladi:
  (1) 🧾 NARX JADVALI — ``services/ai/cost_tracker.py`` Gemini / OpenAI /
      Groq oilalari uchun ``$ / 1K token`` narxini biladi; jadvalda yo'q
      model uchun xarajat ``0.0`` va ``priced=False`` (soxta raqam YO'Q);
  (2) 🧮 MATEMATIKA — kirish/chiqish tokenlari bo'yicha xarajat AYNAN
      kutilgan qiymatga teng (deterministik, yaxlitlash 6 xona);
  (3) 💱 VALYUTA — USD ⇄ UZS kursi (env ``USD_UZS_RATE``) to'g'ri qo'llanadi;
  (4) 👤 USER_LEDGER — har bir foydalanuvchi uchun KUNLIK va OYLIK sarf
      (USD + UZS), cheklangan xotira (LRU) va reset;
  (5) 📊 USER_AI_COSTS — baza bo'lmasa jarayon xotirasi, baza bo'lsa
      ``ai_usage_events`` agregati (soxta db-modul bilan deterministik);
  (6) 📈 ECONOMICS_SUMMARY — o'rtacha bitta faol foydalanuvchi sarfi, PRO
      tarif (19 000 so'm) marjasi, rentabellik xulosasi va zararsizlik;
  (7) 🖥 /economics — uchala tilda matn chiziladi, faqat admin, real PTB
      Application'da ro'yxatdan o'tgan;
  (8) 🐘 LIVE POSTGRESQL (pgserver) — real ``ai_usage_events`` yozuvlaridan
      ``user_ai_costs`` va ``economics_summary`` (pgserver bo'lmasa —
      o'tkazib yuboriladi, soxta PASS berilmaydi).
"""
import asyncio
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BOT = os.path.join(ROOT, "telegram_bot")
if BOT not in sys.path:
    sys.path.insert(0, BOT)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:UNIT_ECONOMICS_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

PASSED = 0
FAILED = 0
LANGS = ("uz", "ru", "en")
ADMIN_ID = 123456789
USER_ID = 501501


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")
    return bool(condition)


def _close(a, b, eps=1e-9):
    return abs(float(a) - float(b)) <= eps


# ---------------------------------------------------------------------------
# 1-3) Narx jadvali, matematika va valyuta
# ---------------------------------------------------------------------------
def test_pricing_math():
    print("\n== TEST 1: Narx jadvali va xarajat matematikasi ==")
    from services.ai import cost_tracker as ct

    # Gemini / OpenAI / Groq — uchala oila jadvalda BOR.
    check("Gemini model narxi bor", ct.is_priced("Gemini", "gemini-2.5-flash"))
    check("OpenAI model narxi bor", ct.is_priced("OpenAI", "gpt-4o-mini"))
    check("OpenAI (OpenRouter orqali) taniladi",
          ct.is_priced("OpenRouter", "openai/gpt-4o"))
    check("Groq model narxi bor", ct.is_priced("Groq", "llama-3.3-70b-versatile"))
    check("Bepul provayder narxda bor (0.0)",
          ct.is_priced("Cloudflare", "workers-ai-8b")
          and ct.cost_usd("Cloudflare", "workers-ai-8b", 1000, 1000) == 0.0)
    check("Kesh/mock javob — xarajat YO'Q",
          ct.is_priced("cache", "cache") and ct.cost_usd("cache", "cached", 10_000, 10_000) == 0.0)
    check("Noma'lum model — narx YO'Q (priced=False)",
          ct.is_priced("NomaLum", "super-model-9") is False)
    check("Noma'lum model xarajati 0.0 (soxta raqam yo'q)",
          ct.cost_usd("NomaLum", "super-model-9", 1_000_000, 1_000_000) == 0.0)

    # Aynan kutilgan qiymatlar (list narxlar bo'yicha).
    check("gemini-2.5-flash: 1K+1K = $0.0028",
          _close(ct.cost_usd("Gemini", "gemini-2.5-flash", 1000, 1000), 0.0028),
          ct.cost_usd("Gemini", "gemini-2.5-flash", 1000, 1000))
    check("gpt-4o-mini: 2K kirish + 1K chiqish = $0.0009",
          _close(ct.cost_usd("OpenAI", "gpt-4o-mini", 2000, 1000), 0.0009),
          ct.cost_usd("OpenAI", "gpt-4o-mini", 2000, 1000))
    check("gpt-4o: 1K kirish = $0.0025",
          _close(ct.cost_usd("OpenAI", "gpt-4o", 1000, 0), 0.0025))
    check("llama-3.3-70b: 1K kirish = $0.00059",
          _close(ct.cost_usd("Groq", "llama-3.3-70b", 1000, 0), 0.00059))
    check("manfiy tokenlar 0 ga qisiladi (xarajat 0)",
          ct.cost_usd("Gemini", "gemini-2.5-flash", -50, -50) == 0.0)
    check("uzun kalit ustun (flash ≠ gemini default)",
          _close(ct.cost_usd("Gemini", "gemini-2.5-flash", 0, 1000), 0.0025)
          and _close(ct.cost_usd("Gemini", "gemini-2.5-pro", 0, 1000), 0.01))
    check("model nomi registrga bog'liq emas (GEMINI-2.5-FLASH)",
          _close(ct.cost_usd("gemini", "GEMINI-2.5-FLASH", 1000, 0), 0.0003))

    # Valyuta: kurs berilgan bo'lsa — aynan shu kurs ishlatiladi.
    check("USD → UZS (kurs 12600): $1.5 = 18 900 so'm",
          _close(ct.usd_to_uzs(1.5, 12600), 18900.0))
    check("UZS → USD: 19 000 so'm ≈ $1.507937",
          _close(ct.uzs_to_usd(19000, 12600), 1.507937, 1e-6))
    check("kurs default > 0", float(ct.usd_uzs_rate()) > 0)
    check("narxlar 6 xonaga yaxlitlanadi",
          ct.cost_usd("OpenAI", "gpt-4o", 7, 3) == round(7 / 1000 * 0.0025 + 3 / 1000 * 0.01, 6))


# ---------------------------------------------------------------------------
# 4-5) Foydalanuvchi ledger'i va user_ai_costs
# ---------------------------------------------------------------------------
class _FakeDBReport:
    """``get_ai_usage_report`` / ``get_observability_metrics`` taqlidi."""

    def __init__(self, cost_usd=0.0, requests=0, tokens=0, unpriced=0):
        self.cost_usd = cost_usd
        self.requests = requests
        self.tokens = tokens
        self.unpriced = unpriced
        self.calls = []

    def get_ai_usage_report(self, user_id=None, channel_id=None, period="daily"):
        self.calls.append(period)
        return {
            "period": period,
            "totals": {
                "requests": self.requests,
                "input_tokens": self.tokens // 2,
                "output_tokens": self.tokens - self.tokens // 2,
                "total_tokens": self.tokens,
                "estimated_cost_usd": self.cost_usd,
                "priced_requests": max(0, self.requests - self.unpriced),
                "unpriced_requests": self.unpriced,
            },
        }

    def get_observability_metrics(self):
        return {"available": True, "active_users_daily": 10,
                "active_users_monthly": 40}


def test_ledger_and_user_costs():
    print("\n== TEST 2: Foydalanuvchi ledger'i va user_ai_costs ==")
    from services.ai import cost_tracker as ct

    ledger = ct.CostLedger(max_users=3)
    ledger.record(user_id=1, provider="Gemini", model="gemini-2.5-flash",
                  input_tokens=1000, output_tokens=1000)
    ledger.record(user_id=1, provider="OpenAI", model="gpt-4o-mini",
                  input_tokens=2000, output_tokens=1000)
    ledger.record(user_id=2, provider="Groq", model="llama-3.3-70b",
                  input_tokens=1000, output_tokens=0, status="failed")
    check("ledger: 2 ta foydalanuvchi kuzatiladi", ledger.users_tracked() == 2,
          ledger.users_tracked())

    day = ledger.user_costs(1, period="daily", rate=12600)
    check("kunlik: 2 so'rov", day["requests"] == 2, day)
    check("kunlik: tokenlar yig'indisi 5000",
          day["total_tokens"] == 5000, day["total_tokens"])
    check("kunlik: xarajat $0.0037 (0.0028 + 0.0009)",
          _close(day["cost_usd"], 0.0037), day["cost_usd"])
    check("kunlik: UZS ga o'girilgan (0.0037 × 12600 = 46.62)",
          _close(day["cost_uzs"], 46.62, 0.01), day["cost_uzs"])
    check("kunlik manba = memory (baza yo'q)", day["source"] == "memory")

    month = ledger.user_costs(1, period="monthly", rate=12600)
    check("oylik: bugungi yozuvlar ham kiradi", month["requests"] == 2)
    check("boshqa foydalanuvchi izolyatsiyasi: user=2 $0.00059",
          _close(ledger.user_costs(2, period="daily")["cost_usd"], 0.00059))
    check("yangi foydalanuvchi — nollar",
          ledger.user_costs(999)["requests"] == 0)

    totals = ledger.totals(period="daily", rate=12600)
    check("jami kunlik: 3 so'rov", totals["requests"] == 3, totals)
    check("top_users: eng katta sarf — user 1",
          ledger.top_users(period="daily")[0]["user_id"] == 1)

    # LRU chegara (max_users=3): 4-chi foydalanuvchi birinchisini siqib chiqaradi.
    ledger.record(user_id=3, provider="Groq", model="llama-3.1-8b", input_tokens=10)
    ledger.record(user_id=4, provider="Groq", model="llama-3.1-8b", input_tokens=10)
    check("ledger xotirasi cheklangan (LRU ≤ max_users)",
          ledger.users_tracked() <= 3, ledger.users_tracked())

    # ── user_ai_costs: baza YO'Q → jarayon xotirasi
    ledger2 = ct.CostLedger()
    ledger2.record(user_id=USER_ID, provider="Gemini", model="gemini-2.5-flash",
                   input_tokens=1000, output_tokens=1000)
    costs = ct.user_ai_costs(USER_ID, ledger=ledger2, rate=12600)
    check("user_ai_costs: kunlik/oylik/umumiy kalitlari bor",
          set(costs) >= {"user_id", "daily", "monthly", "all", "source"})
    check("user_ai_costs: manba = memory", costs["source"] == "memory")
    check("user_ai_costs: kunlik $0.0028 ≈ 35.28 so'm",
          _close(costs["daily"]["cost_usd"], 0.0028)
          and _close(costs["daily"]["cost_uzs"], 35.28, 0.01), costs["daily"])

    # ── user_ai_costs: baza BOR → ai_usage_events agregati
    fake = _FakeDBReport(cost_usd=0.0123, requests=7, tokens=4200, unpriced=2)
    db_costs = ct.user_ai_costs(USER_ID, db_module=fake, ledger=ledger2, rate=12600)
    check("user_ai_costs: manba = db (agregat ishlatildi)",
          db_costs["source"] == "db", db_costs["source"])
    check("user_ai_costs(db): xarajat agregatdan olinadi",
          _close(db_costs["daily"]["cost_usd"], 0.0123), db_costs["daily"])
    check("user_ai_costs(db): UZS ga o'girilgan",
          _close(db_costs["daily"]["cost_uzs"], 0.0123 * 12600, 0.01))
    check("user_ai_costs(db): narxsiz so'rovlar ko'rinadi",
          db_costs["daily"]["unpriced_requests"] == 2)

    # ── Telemetriya yozuvi (ai_usage_events shakli) ledger'ga tushadi
    ledger3 = ct.CostLedger()
    ok = ct.record_usage_event({
        "user_id": 5, "provider": "OpenAI", "model": "gpt-4o",
        "input_tokens": 1000, "output_tokens": 1000,
        "estimated_cost": 0.0125, "status": "success", "cached": False,
    }, ledger=ledger3)
    check("record_usage_event: yozuv qabul qilindi", ok is True)
    check("record_usage_event: xarajat yozildi",
          _close(ledger3.user_costs(5)["cost_usd"], 0.0125))
    check("record_usage_event: user_id yo'q — jim o'tadi (xato yo'q)",
          ct.record_usage_event({"provider": "Mock", "model": "mock"},
                                ledger=ledger3) is True)


# ---------------------------------------------------------------------------
# 6) economics_summary — PRO tarif rentabelligi
# ---------------------------------------------------------------------------
def _summary_for_avg_uzs(avg_uzs, *, users=1, rate=12600, pro=19000):
    """Bitta foydalanuvchi uchun aynan ``avg_uzs`` sarf yasaydi."""
    from services.ai import cost_tracker as ct

    ledger = ct.CostLedger()
    if avg_uzs > 0:
        ledger.record(user_id=1, provider="Mock", model="mock",
                      cost=avg_uzs / rate, input_tokens=0, output_tokens=0)
    return ct.economics_summary(period="monthly", ledger=ledger, active_users=users,
                                pro_price_uzs=pro, rate=rate)


def test_economics_summary():
    print("\n== TEST 3: economics_summary — PRO tarif rentabelligi ==")
    from services.ai import cost_tracker as ct

    healthy = _summary_for_avg_uzs(1000.0)   # 5.3% — sog'lom
    check("rentabellik: arzon sarf → 'healthy'",
          healthy["verdict"] == ct.VERDICT_HEALTHY, healthy["verdict"])
    check("marja: 19 000 − 1 000 = 18 000 so'm",
          _close(healthy["margin_uzs"], 18000.0), healthy["margin_uzs"])
    check("marja foizi ≈ 94.7%",
          _close(healthy["margin_rate"], 0.9474, 1e-3), healthy["margin_rate"])

    watch = _summary_for_avg_uzs(9000.0)     # 47.4% — kuzatuv
    check("rentabellik: 9 000 so'm → 'watch'",
          watch["verdict"] == ct.VERDICT_WATCH, watch["verdict"])

    thin = _summary_for_avg_uzs(15000.0)     # 78.9% — yupqa
    check("rentabellik: 15 000 so'm → 'thin'",
          thin["verdict"] == ct.VERDICT_THIN, thin["verdict"])

    loss = _summary_for_avg_uzs(25000.0)     # 131% — zarar
    check("rentabellik: 25 000 so'm → 'loss'",
          loss["verdict"] == ct.VERDICT_LOSS, loss["verdict"])
    check("zararda marja manfiy", loss["margin_uzs"] < 0, loss["margin_uzs"])

    # Bitta to'lov necha foydalanuvchini qoplaydi: 19000 / 1000 = 19.
    check("zararsizlik: bitta to'lov 19 ta foydalanuvchini qoplaydi",
          healthy["users_per_payment"] == 19, healthy["users_per_payment"])

    # Faol foydalanuvchi 0 bo'lsa — nolga bo'lish YO'Q.
    empty = ct.economics_summary(period="monthly", active_users=0, rate=12600)
    check("faol foydalanuvchi 0 — xavfsiz (avg=0, crash yo'q)",
          empty["avg_cost_uzs"] == 0.0 and empty["active_users"] == 0)
    check("PRO narxi config'dan (19 000 so'm)",
          empty["pro_price_uzs"] == 19000, empty["pro_price_uzs"])
    check("PRO narxi USD da ham ko'rsatiladi",
          _close(empty["pro_price_usd"], 1.507937, 1e-4), empty["pro_price_usd"])

    # Aktiv foydalanuvchilar bazadan olinadi (observability metrikasi).
    fake = _FakeDBReport(cost_usd=0.40, requests=40, tokens=10000)
    db_summary = ct.economics_summary(period="monthly", db_module=fake, rate=12600)
    check("baza: jami xarajat $0.40", _close(db_summary["total_cost_usd"], 0.40))
    check("baza: faol foydalanuvchilar = 40 (oylik metrika)",
          db_summary["active_users"] == 40, db_summary["active_users"])
    check("baza: o'rtacha sarf $0.01 = 126 so'm",
          _close(db_summary["avg_cost_uzs"], 126.0, 0.01), db_summary["avg_cost_uzs"])
    check("baza: manba = db", db_summary["source"] == "db")
    check("baza: kunlik davr ham ishlaydi",
          ct.economics_summary(period="daily", db_module=fake)["active_users"] == 10)


# ---------------------------------------------------------------------------
# 7) /economics handler + matn (3 til)
# ---------------------------------------------------------------------------
def test_economics_command_and_text():
    print("\n== TEST 4: /economics buyrug'i va matni ==")
    from types import SimpleNamespace

    import database as db_mod  # noqa: E402
    from services.ai import cost_tracker as ct
    from translations import admin_t
    import handlers.economics as eco

    from telegram.ext import CommandHandler  # noqa: E402
    import handlers  # noqa: E402,F401 — reyestrni yuklaydi

    # (a) matn uchala tilda chiziladi va kalit raqamlarni ko'rsatadi.
    for lang in LANGS:
        text = eco.build_economics_text({
            "period": "monthly", "requests": 12, "total_tokens": 3456,
            "total_cost_usd": 0.0123, "total_cost_uzs": 154.98,
            "avg_cost_usd": 0.0012, "avg_cost_uzs": 15.12, "active_users": 10,
            "pro_price_uzs": 19000, "pro_price_usd": 1.507937,
            "margin_uzs": 18984.88, "margin_rate": 0.9992, "cost_share": 0.0008,
            "verdict": ct.VERDICT_HEALTHY, "users_per_payment": 1256,
            "unpriced_requests": 1, "source": "db", "rate_usd_uzs": 12600,
        }, lang=lang, top_users=[{"user_id": 42, "cost_uzs": 12.6, "requests": 3}])
        check(f"[{lang}] sarlavha chizildi",
              admin_t("eco_title", lang) in text, text[:80])
        check(f"[{lang}] PRO narxi (19 000) ko'rinadi", "19 000" in text)
        check(f"[{lang}] o'rtacha sarf qatori bor",
              admin_t("eco_line_avg", lang, usd="x", uzs="y", users=10)[:12] in text)
        check(f"[{lang}] narxsiz so'rovlar ogohlantirishi bor",
              admin_t("eco_note_unpriced", lang, count=1) in text)
        check(f"[{lang}] manba/kurs qatori bor",
              "12600" in text.replace(" ", ""))
        check(f"[{lang}] top spender qatori bor", "42" in text)

    # (b) real PTB Application'da /economics ro'yxatdan o'tgan.
    from telegram.ext import ApplicationBuilder

    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()
    handlers.register_all_handlers(app)
    names = set()
    for h in app.handlers.get(0, []):
        if isinstance(h, CommandHandler):
            names.update(h.commands)
    check("/economics ro'yxatdan o'tgan (haqiqiy Application)", "economics" in names,
          sorted(names))
    check("/beta ham ro'yxatdan o'tgan", "beta" in names, sorted(names))

    # (c) faqat admin: oddiy foydalanuvchiga javob YO'Q.
    class _Msg:
        def __init__(self):
            self.sent = []

        async def reply_text(self, text, **kw):
            self.sent.append(text)

    def _update(user_id):
        msg = _Msg()
        return SimpleNamespace(message=msg, effective_message=msg,
                               effective_user=SimpleNamespace(id=user_id,
                                                              first_name="T")), msg

    ctx = SimpleNamespace(args=[], user_data={"lang": "uz"}, bot=SimpleNamespace(),
                          chat_data={})

    upd_user, msg_user = _update(USER_ID)
    asyncio.run(eco.economics_command(upd_user, ctx))
    check("oddiy foydalanuvchi /economics — javob yo'q", not msg_user.sent)

    # (d) admin uchun hisobot (baza mock'i bilan deterministik).
    original_run_db = db_mod.run_db

    async def _fake_run_db(func, *args, **kwargs):
        return ct.economics_summary(period="monthly", active_users=5, rate=12600,
                                    pro_price_uzs=19000)

    db_mod.run_db = _fake_run_db
    try:
        upd_admin, msg_admin = _update(ADMIN_ID)
        asyncio.run(eco.economics_command(upd_admin, ctx))
    finally:
        db_mod.run_db = original_run_db
    check("admin /economics — javob yuborildi", bool(msg_admin.sent))
    admin_text = msg_admin.sent[-1] if msg_admin.sent else ""
    check("admin matnida PRO narxi bor", "19 000" in admin_text, admin_text[:100])
    check("admin matnida xulosa (verdict) bor",
          admin_t("eco_verdict_healthy", "uz") in admin_text)

    # (e) daily rejimi argumenti.
    original_run_db = db_mod.run_db
    captured = {}

    async def _fake_run_db2(func, *args, **kwargs):
        captured.update(kwargs)
        return ct.economics_summary(period="daily", active_users=5, rate=12600)

    db_mod.run_db = _fake_run_db2
    try:
        upd_admin, msg_admin = _update(ADMIN_ID)
        asyncio.run(eco.economics_command(upd_admin,
                                          SimpleNamespace(args=["daily"],
                                                          user_data={"lang": "uz"},
                                                          bot=SimpleNamespace(),
                                                          chat_data={})))
    finally:
        db_mod.run_db = original_run_db
    check("/economics daily — davr uzatiladi",
          captured.get("period") == "daily", captured)


# ---------------------------------------------------------------------------
# 8) LIVE POSTGRESQL
# ---------------------------------------------------------------------------
def test_live_postgres():
    print("\n== TEST 5: Real PostgreSQL (pgserver) ==")
    try:
        import pgserver
    except ImportError:
        print("  [SKIP] pgserver yo'q — live DB qismi o'tkazib yuborildi "
              "(pip install pgserver)")
        return

    import database as db
    from services.ai import cost_tracker as ct

    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_econ")
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri
    db.DATABASE_URL = uri
    db._reset_pool()
    db.init_db()

    db.save_ai_usage_event(
        user_id=77, channel_id=-700, task="social_post", provider="Gemini",
        model="gemini-2.5-flash", input_tokens=1000, output_tokens=1000,
        latency_ms=900, estimated_cost=0.0028, priced=True, status="success",
    )
    db.save_ai_usage_event(
        user_id=77, channel_id=-700, task="post_score", provider="NomaLum",
        model="xyz-unknown", input_tokens=100, output_tokens=100,
        estimated_cost=0.0, priced=False, status="success",
    )
    db.save_ai_usage_event(
        user_id=88, channel_id=-701, task="social_post", provider="OpenAI",
        model="gpt-4o-mini", input_tokens=2000, output_tokens=1000,
        latency_ms=500, estimated_cost=0.0009, priced=True, status="success",
    )
    # Faol foydalanuvchilar metrikasi ``users.last_active_at`` dan o'qiladi.
    db.save_user(77, "econ_user_77", full_name="Econ 77")
    db.save_user(88, "econ_user_88", full_name="Econ 88")
    db.touch_user_activity([77, 88])

    costs = ct.user_ai_costs(77, db_module=db, rate=12600)
    check("live: user_ai_costs manbasi — db", costs["source"] == "db", costs)
    check("live: kunlik xarajat AYNAN yozuvdan ($0.0028)",
          _close(costs["daily"]["cost_usd"], 0.0028), costs["daily"])
    check("live: kunlik sarf so'mda (35.28)",
          _close(costs["daily"]["cost_uzs"], 35.28, 0.01), costs["daily"])
    check("live: 2 ta so'rov (bittasi narxsiz)",
          costs["daily"]["requests"] == 2
          and costs["daily"]["unpriced_requests"] == 1, costs["daily"])
    check("live: boshqa foydalanuvchi aralashmaydi ($0.0009)",
          _close(ct.user_ai_costs(88, db_module=db)["daily"]["cost_usd"], 0.0009))

    summary = ct.economics_summary(period="monthly", db_module=db, rate=12600)
    check("live: jami xarajat $0.0037",
          _close(summary["total_cost_usd"], 0.0037), summary["total_cost_usd"])
    check("live: jami 3 ta so'rov", summary["requests"] == 3, summary["requests"])
    check("live: faol foydalanuvchilar bazadan (≥2)",
          summary["active_users"] >= 2, summary["active_users"])
    check("live: avg ≤ jami (matematik izchillik)",
          summary["avg_cost_uzs"] <= summary["total_cost_uzs"] + 1e-6)

    # Price jadvalidagi model narxi DB yozuvi bilan mos keladi.
    check("live: gemini-2.5-flash narxi ledger hisobi bilan mos",
          _close(ct.cost_usd("Gemini", "gemini-2.5-flash", 1000, 1000), 0.0028))

    db.close_pool()


def main():
    print("=" * 70)
    print(" 💰 SPRINT 4 — UNIT ECONOMICS (AI XARAJAT / PRO RENTABELLIK)")
    print("=" * 70)
    test_pricing_math()
    test_ledger_and_user_costs()
    test_economics_summary()
    test_economics_command_and_text()
    test_live_postgres()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    if FAILED:
        print(" [FAIL] UNIT ECONOMICS TESTLARIDA XATOLIK BOR ✘")
        return 1
    print(" SPRINT 4 — UNIT ECONOMICS 100% YASHIL ✔")
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
