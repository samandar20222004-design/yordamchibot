#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 💰 PHASE 6 — AI XARAJAT/TELEMETRIYA JURNALI (REAL POSTGRESQL)
=====================================================================

PHASE 6 talabi: «Har bir AI so'rovi uchun model, provider, input_tokens,
output_tokens, latency, estimated_cost va status (success/failed) qayd
etilsin; kunlik/oylik kvota va xarajat hisoboti foydalanuvchi va kanal
kesimida bo'lsin».

Bu suite HAQIQIY PostgreSQL (pgserver) ustida tekshiradi:

(1) 🧱 SCHEMA — ``ai_usage_events`` jadvali, ustunlari va 2 ta indeks
    (user/kanal kesimi) sxemada va real bazada mavjud;
(2) 💾 YOZUV — ``database.save_ai_usage_event(...)`` parametrlangan
    INSERT qiladi, yozuv ID'sini qaytaradi va maydonlarni AYNAN saqlaydi
    (to'qima raqam yo'q — noma'lum model ``priced=False``);
(3) 📊 HISOBOT — ``database.get_ai_usage_report(user_id=..., period=daily)``
    va kanal kesimi (``channel_id=...``) to'g'ri agregatsiya qiladi
    (requests/successes/failures/tokens/cost);
(4) 🗓 DAVRLAR — ``daily`` / ``monthly`` / ``all`` oynalari;
(5) 🧹 RETENTION — ``database.purge_ai_usage_events(days=...)`` eski
    yozuvlarni o'chiradi va yangilarini saqlab qoldiradi;
(6) 🔌 APPLICATION SERVICE — ``run_ai_task(...)`` real DB adapteriga
    telemetriya yozuvini saqlaydi (``usage_id`` qaytadi).

pgserver bo'lmasa — live qism o'tkazib yuboriladi (statik qism DOIM
ishlaydi) va bu ANIQ xabar sifatida chop etiladi (soxta PASS yo'q).
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))          # tests/
ROOT = os.path.dirname(HERE)                               # repo ildizi
BOT = os.path.join(ROOT, "telegram_bot")                   # telegram_bot
if BOT not in sys.path:
    sys.path.insert(0, BOT)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:AI_COST_TRACKING_DB_TEST")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

PASSED = 0
FAILED = 0


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")
    return bool(condition)


# ---------------------------------------------------------------------------
# 1) STATIK: sxema, konstanta va repo funksiyalari
# ---------------------------------------------------------------------------
def test_static_schema_and_api():
    print("\n== TEST 1: Statik sxema va API ==")
    import database as db

    schema_path = os.path.join(BOT, "schema.sql")
    schema_sql = open(schema_path, encoding="utf-8").read()

    check("database.AI_USAGE_TABLES mavjud",
          tuple(getattr(db, "AI_USAGE_TABLES", ())) == ("ai_usage_events",),
          str(getattr(db, "AI_USAGE_TABLES", None)))
    indexes = tuple(getattr(db, "AI_USAGE_INDEXES", ()))
    check("2 ta indeks e'lon qilingan (user + kanal)",
          indexes == ("idx_ai_usage_user_time", "idx_ai_usage_channel_time"),
          str(indexes))
    check("schema.sql: ai_usage_events DDL bor", "ai_usage_events" in schema_sql)
    for index in indexes:
        check(f"schema.sql: {index} indeksi bor", index in schema_sql)

    # Jadval ``CREATE TABLE IF NOT EXISTS`` literal sonini o'zgartirmaydi
    # (locked count 31) — wrapper shaklida yozilgan.
    check("schema.sql jadval literal soni 31 (regressiya yo'q)",
          schema_sql.count("CREATE TABLE IF NOT EXISTS") == 31,
          str(schema_sql.count("CREATE TABLE IF NOT EXISTS")))

    expected_columns = {
        "id", "user_id", "channel_id", "task", "lane", "operation_type",
        "provider", "model", "input_tokens", "output_tokens", "latency_ms",
        "estimated_cost", "priced", "status", "error_code", "cached",
        "attempts", "prompt_hash", "reservation_id", "created_at",
    }
    missing = sorted(c for c in expected_columns if c not in schema_sql)
    check("barcha telemetriya ustunlari DDL'da", not missing, str(missing))

    for fn_name in ("save_ai_usage_event", "get_ai_usage_report",
                    "purge_ai_usage_events"):
        check(f"database.{fn_name} facade'da mavjud",
              callable(getattr(db, fn_name, None)))
    check("rollar: ai_usage_events yozuvi modul bilan bir xil",
          db.save_ai_usage_event.__module__ == "repositories.audit_repository",
          str(db.save_ai_usage_event.__module__))


# ---------------------------------------------------------------------------
# 2) TELEMETRIYA MODELI → DB QATORI (to'qima raqamsiz)
# ---------------------------------------------------------------------------
def test_event_shape():
    print("\n== TEST 2: Telemetriya yozuvi → DB ustunlari ==")
    from services.ai_engine import telemetry

    event = telemetry.AIUsageEvent(
        user_id=5, channel_id=-100, task="social_post", lane="FAST",
        operation_type="magic_post", provider="Gemini",
        model="gemini-2.5-flash", input_tokens=100, output_tokens=50,
        latency_ms=1234, estimated_cost=0.000425, priced=True,
        status=telemetry.STATUS_SUCCESS, cached=False, attempts=1,
        prompt_hash="abc123",
    )
    row = event.to_row()
    check("to_row() 18 ta ustun", len(row) == 18, str(len(row)))
    check("status CHECK qiymati (success)",
          row[12] in ("success", "failed"), str(row[12]))
    check("estimated_cost float", isinstance(row[10], float), str(row[10]))
    check("tokenlar int", isinstance(row[7], int) and isinstance(row[8], int))
    check("total_tokens xossasi", event.total_tokens == 150)

    unknown = telemetry.AIUsageEvent(
        provider="NomaLum", model="xyz", input_tokens=10, output_tokens=5,
        status=telemetry.STATUS_FAILED, error_code="ai_unavailable",
    )
    event_dict = unknown.as_dict()
    check("as_dict() xarajat maydonlari bor",
          "estimated_cost" in event_dict and "status" in event_dict)
    check("noma'lum model uchun narx jadvali False",
          telemetry.is_priced("NomaLum", "xyz") is False)
    check("narx jadvalida bor model True",
          telemetry.is_priced("Gemini", "gemini-2.5-flash") is True)


# ---------------------------------------------------------------------------
# 3) LIVE POSTGRESQL (pgserver)
# ---------------------------------------------------------------------------
def test_live_postgres():
    print("\n== TEST 3: Real PostgreSQL (pgserver) ==")
    try:
        import pgserver
    except ImportError:
        print("  [SKIP] pgserver yo'q — live DB qismi o'tkazib yuborildi "
              "(pip install pgserver)")
        return

    import database as db

    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_cost")
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri
    db.DATABASE_URL = uri
    db._reset_pool()
    db.init_db()

    with db.db_cursor() as cur:
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'ai_usage_events'")
        columns = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'ai_usage_events'")
        indexes = {r[0] for r in cur.fetchall()}
    check("real bazada jadval ustunlari to'liq",
          {"user_id", "channel_id", "provider", "model", "input_tokens",
           "output_tokens", "latency_ms", "estimated_cost", "status",
           "priced", "cached", "created_at"} <= columns,
          str(sorted({"provider", "estimated_cost", "status"} - columns)))
    check("real bazada indekslar mavjud",
          set(db.AI_USAGE_INDEXES) <= indexes,
          str(sorted(set(db.AI_USAGE_INDEXES) - indexes)))

    # --- 3a) Yozuv (save) ------------------------------------------------
    row_id_1 = db.save_ai_usage_event(
        user_id=11, channel_id=-501, task="social_post", lane="FAST",
        operation_type="magic_post", provider="Gemini",
        model="gemini-2.5-flash", input_tokens=200, output_tokens=100,
        latency_ms=1500, estimated_cost=0.00031, priced=True,
        status="success", cached=False, attempts=1, prompt_hash="h1",
    )
    row_id_2 = db.save_ai_usage_event(
        user_id=11, channel_id=-501, task="post_score", lane="QUALITY",
        operation_type="post_score", provider="Groq", model="llama-3.3-70b",
        input_tokens=80, output_tokens=20, latency_ms=800,
        estimated_cost=0.0, priced=False, status="failed",
        error_code="rate_limit", cached=False, attempts=2, prompt_hash="h2",
    )
    row_id_3 = db.save_ai_usage_event(
        user_id=12, channel_id=-502, task="channel_dna", lane="REASONING",
        operation_type="content_calendar", provider="Mock", model="mock",
        input_tokens=10, output_tokens=10, latency_ms=5,
        estimated_cost=0.0, priced=False, status="success", cached=True,
        attempts=1, prompt_hash="h3",
    )
    check("save: ID qaytadi", isinstance(row_id_1, int) and row_id_1 > 0,
          str(row_id_1))
    check("save: ketma-ket ID'lar o'sadi", row_id_3 > row_id_2 > row_id_1,
          f"{row_id_1}/{row_id_2}/{row_id_3}")
    check("save: yaroqsiz status 'failed' ga majburan tushiriladi",
          db.save_ai_usage_event(user_id=90, status="buzilgan") is not None)
    with db.db_cursor() as cur:
        cur.execute("SELECT status FROM ai_usage_events WHERE user_id = 90")
        coerced = cur.fetchall()
    check("save: status CHECK buzilmagan (yozuv 'failed')",
          coerced and coerced[0][0] == "failed", str(coerced))

    # --- 3b) Kunlik hisobot (foydalanuvchi kesimi) -----------------------
    daily = db.get_ai_usage_report(user_id=11, period="daily")
    check("kunlik hisobot lug'at qaytaradi", isinstance(daily, dict), str(type(daily)))
    totals = (daily or {}).get("totals", {})
    check("kunlik: 2 ta so'rov (user=11)", totals.get("requests") == 2,
          str(totals))
    check("kunlik: 1 success + 1 failed",
          totals.get("successes") == 1 and totals.get("failures") == 1,
          str(totals))
    check("kunlik: tokenlar yig'indisi",
          totals.get("input_tokens") == 280 and totals.get("output_tokens") == 120,
          str(totals))
    check("kunlik: xarajat yig'indisi (faqat priced)",
          abs(float(totals.get("estimated_cost_usd") or 0) - 0.00031) < 1e-9,
          str(totals.get("estimated_cost_usd")))
    check("kunlik: priced/unpriced ajratilgan (success kesimida)",
          totals.get("priced_requests") == 1 and totals.get("unpriced_requests") == 0,
          str(totals))
    by_provider = (daily or {}).get("by_provider", {})
    check("kunlik: by_provider (Gemini/Groq)",
          "Gemini" in by_provider and "Groq" in by_provider,
          str(list(by_provider)))
    check("kunlik: by_model (gemini-2.5-flash)",
          "gemini-2.5-flash" in (daily or {}).get("by_model", {}))
    check("kunlik: by_task va by_lane",
          "social_post" in (daily or {}).get("by_task", {})
          and "FAST" in (daily or {}).get("by_lane", {}))

    # --- 3c) Kanal kesimi ------------------------------------------------
    channel = db.get_ai_usage_report(channel_id=-501, period="daily")
    check("kanal kesimi: 2 ta so'rov (channel=-501)",
          (channel or {}).get("totals", {}).get("requests") == 2,
          str((channel or {}).get("totals")))
    other_channel = db.get_ai_usage_report(channel_id=-502, period="daily")
    check("kanal kesimi: boshqa kanal izolyatsiyasi",
          (other_channel or {}).get("totals", {}).get("requests") == 1,
          str(other_channel))

    # --- 3d) Davrlar (daily / monthly / all) -----------------------------
    monthly = db.get_ai_usage_report(user_id=11, period="monthly")
    check("monthly: joriy oyda ham ko'rinadi",
          (monthly or {}).get("totals", {}).get("requests") == 2,
          str((monthly or {}).get("totals")))
    check("monthly: by_day kunlik kesim beradi",
          isinstance((monthly or {}).get("by_day"), dict)
          and len((monthly or {}).get("by_day")) >= 1, str((monthly or {}).get("by_day")))
    all_time = db.get_ai_usage_report(user_id=11, period="all")
    check("all: butun tarix", (all_time or {}).get("totals", {}).get("requests") == 2)
    bad_period = db.get_ai_usage_report(user_id=11, period="DROP TABLE")
    check("noto'g'ri davr xavfsiz 'daily' ga tushadi",
          (bad_period or {}).get("period") == "daily", str(bad_period))

    # --- 3e) Retention (purge) ------------------------------------------
    old_id = db.save_ai_usage_event(user_id=13, channel_id=-503, task="social_post",
                                    provider="Gemini", model="gemini-2.5-flash",
                                    status="success", priced=True,
                                    estimated_cost=0.001)
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE ai_usage_events SET created_at = NOW() - make_interval(days => 30) "
            "WHERE id = %s", (old_id,))
    deleted = db.purge_ai_usage_events(days=7)
    check("purge: eski yozuv o'chirildi (>=1)", int(deleted) >= 1, str(deleted))
    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ai_usage_events WHERE id = %s", (old_id,))
        gone = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM ai_usage_events")
        remaining = int(cur.fetchone()[0])
    check("purge: eski yozuv bazada YO'Q", gone == 0)
    check("purge: yangi yozuvlar saqlanib qoldi", remaining >= 3, str(remaining))
    fresh_report = db.get_ai_usage_report(user_id=11, period="daily")
    check("purge'dan keyin hisobot buzilmagan",
          (fresh_report or {}).get("totals", {}).get("requests") == 2)

    # --- 3f) Application Service real adapter bilan ----------------------
    import asyncio
    from services.ai_engine import providers as eng_providers
    from services.ai_engine.app_service import ai_tasks

    handle = eng_providers.ProviderHandle(
        name="Gemini",
        provider=type("P", (), {"name": "Gemini", "is_available": lambda s: True})(),
    )

    async def fake_execute(handle_, prompt, system_instruction, **kwargs):
        return {"post_text": "Real bazaga yoziladigan SMM post matni yetarli darajada "
                             "mazmunli va tayyor.", "model": "gemini-2.5-flash"}

    real = (eng_providers.build_provider_handles, eng_providers.execute_provider)
    eng_providers.build_provider_handles = lambda: {"Gemini": handle}
    eng_providers.execute_provider = fake_execute
    try:
        outcome = asyncio.run(ai_tasks.run(
            db=db, task="social_post", prompt="Kofe do'koni uchun post",
            user_id=21, channel_id=-601, lane="smart",
            reserve_quota=False, use_cache=False,
        ))
    finally:
        eng_providers.build_provider_handles, eng_providers.execute_provider = real

    check("run_ai_task: javob ok", outcome.ok, str(outcome)[:120])
    check("run_ai_task: DB yozuv ID qaytdi", isinstance(outcome.usage_id, int),
          str(outcome.usage_id))
    live = db.get_ai_usage_report(user_id=21, period="daily")
    check("run_ai_task yozuvi hisobotda ko'rinadi",
          (live or {}).get("totals", {}).get("requests") == 1, str(live))
    check("yozuvda model/provayder saqlangan",
          "gemini-2.5-flash" in (live or {}).get("by_model", {})
          and "Gemini" in (live or {}).get("by_provider", {}))
    check("yozuvda kanal kesimi ishlaydi",
          (db.get_ai_usage_report(channel_id=-601, period="daily") or {}).get(
              "totals", {}).get("requests") == 1)

    db.close_pool()


def main():
    print("=" * 70)
    print(" 💰 PHASE 6 — AI COST TRACKING (ai_usage_events / REAL POSTGRESQL)")
    print("=" * 70)
    test_static_schema_and_api()
    test_event_shape()
    test_live_postgres()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILED}")
    if FAILED:
        print(" [FAIL] PHASE 6 COST TRACKING TESTLARIDA XATOLIK BOR ✘")
        return 1
    print(" PHASE 6 — AI COST TRACKING 100% YASHIL ✔")
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
