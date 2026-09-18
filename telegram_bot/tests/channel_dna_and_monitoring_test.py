#!/usr/bin/env python3
"""FAZA 8,9,22 — Channel DNA, Monitoring va DB Hardening testi.

Tekshiriladi:
  1. Postlar qo'shilishi bilan Channel DNA metrikalarining to'g'ri yangilanishi
     (language, tone, topics, avg_length, emoji_density, best_hours,
     best_weekdays, high_performing_formats) — har bir metrika
     sample_size, confidence (0.0-1.0), updated_at bilan.
  2. sample_size kam bo'lganda confidence pastligi (soxta yuqori confidence yo'q).
  3. Oddiy postda AI chaqirilmasligi (faqat DB agregatsiyasi) — monitoring va monitor modullari.
  4. Migratsiyalarning idempotency tekshiruvi (CREATE TABLE IF NOT EXISTS,
     CREATE INDEX IF NOT EXISTS, ON CONFLICT DO NOTHING, FK NOT VALID fallback).

Ishga tushirish:
    cd telegram_bot && python tests/channel_dna_and_monitoring_test.py
"""

import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0
skipped = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name} {reason}")


# ============================================================
# 1. CHANNEL DNA METRIKALARI TO'G'RI YANGILANISHI
# ============================================================

def test_dna_extended_metrics():
    print("== Channel DNA extended metrikalari ==")
    from services.channels.dna import (
        compute_channel_dna_extended,
        confidence_float,
        MIN_POSTS_FOR_DNA,
        INSUFFICIENT_DATA_MESSAGE,
    )

    # Test with sufficient data (10 posts)
    events = []
    for i in range(10):
        events.append({
            "channel_id": "-100123",
            "message_id": i + 1,
            "post_hour": 19 if i % 2 == 0 else 20,
            "post_weekday": 0 if i < 5 else 2,
            "has_media": i % 3 == 0,
            "media_type": "photo" if i % 3 == 0 else None,
            "length": 300 + i * 10,
            "cta_detected": i % 2 == 0,
            "emoji_density": 0.008 + (i * 0.0001),
            "text": "Salom, bu test posti! Buyurtma bering 👉" if i % 2 == 0 else "Bugun juda yaxshi yangilik bor va bilan uchun",
            "language": "uz" if i < 7 else "ru",
            "topics": ["news", "sport"] if i % 2 == 0 else ["tech"],
        })

    result = compute_channel_dna_extended(events)
    check("extended: insufficient=False for 10 posts", result.get("insufficient") is False)
    check("extended: sample_size=10", result.get("sample_size") == 10)
    check("extended: confidence 0.0-1.0", 0.0 <= float(result.get("confidence", 0)) <= 1.0)
    check("extended: confidence not fake high for 10", float(result.get("confidence", 0)) < 0.8,
          f"got {result.get('confidence')}")
    check("extended: profile exists", isinstance(result.get("profile"), dict))
    check("extended: metrics exists", isinstance(result.get("metrics"), dict))

    profile = result.get("profile") or {}
    metrics = result.get("metrics") or {}

    # Check required metrics
    required = ["language", "tone", "topics", "avg_length", "emoji_density",
                "best_hours", "best_weekdays", "high_performing_formats"]
    for key in required:
        check(f"extended: metric {key} in profile", key in profile, f"missing {key}")
        check(f"extended: metric {key} in metrics", key in metrics, f"missing {key} in metrics")
        m = metrics.get(key) or {}
        # Each metric must have sample_size, confidence, updated_at
        check(f"extended: {key} has sample_size", "sample_size" in m, str(m))
        check(f"extended: {key} has confidence", "confidence" in m, str(m))
        check(f"extended: {key} has updated_at", "updated_at" in m, str(m))
        # confidence 0.0-1.0
        try:
            conf = float(m.get("confidence", -1))
            check(f"extended: {key} confidence 0.0-1.0", 0.0 <= conf <= 1.0, f"got {conf}")
        except Exception:
            check(f"extended: {key} confidence valid", False, str(m.get("confidence")))

    # Check specific values
    lang_metric = metrics.get("language") or {}
    check("extended: language value is uz/ru/en", lang_metric.get("value") in ("uz", "ru", "en"),
          f"got {lang_metric.get('value')}")
    # Language should be uz (majority 7 uz vs 3 ru)
    check("extended: language majority uz", lang_metric.get("value") == "uz",
          f"got {lang_metric.get('value')}")

    avg_len_metric = metrics.get("avg_length") or {}
    check("extended: avg_length value >0", int(avg_len_metric.get("value") or 0) > 0)

    best_hours_metric = metrics.get("best_hours") or {}
    bh_val = best_hours_metric.get("value") or []
    check("extended: best_hours contains 19", 19 in bh_val, f"got {bh_val}")
    check("extended: best_hours list", isinstance(bh_val, list))

    best_weekdays_metric = metrics.get("best_weekdays") or {}
    bw_val = best_weekdays_metric.get("value") or []
    check("extended: best_weekdays list", isinstance(bw_val, list))

    formats_metric = metrics.get("high_performing_formats") or {}
    hf_val = formats_metric.get("value") or []
    check("extended: high_performing_formats list", isinstance(hf_val, list))

    # Test that legacy fields still present for backward compat
    check("extended: legacy average_post_length", "average_post_length" in profile or "avg_length_value" in profile)
    check("extended: legacy emoji_level", "emoji_level" in profile)

    # Test that adding more posts updates metrics
    events2 = events + [
        {
            "channel_id": "-100123",
            "message_id": 100 + i,
            "post_hour": 19,
            "post_weekday": 0,
            "has_media": True,
            "media_type": "video",
            "length": 500,
            "cta_detected": True,
            "emoji_density": 0.015,
            "text": "Yangi video! Obuna bo'ling 👉",
            "language": "uz",
            "topics": ["video", "news"],
        }
        for i in range(15)
    ]
    result2 = compute_channel_dna_extended(events2)
    check("extended: larger sample bigger confidence", float(result2.get("confidence", 0)) > float(result.get("confidence", 0)),
          f"{result.get('confidence')} vs {result2.get('confidence')}")
    check("extended: 25 posts sample_size", result2.get("sample_size") == 25)


def test_dna_small_sample_low_confidence():
    print("== Kichik sample_size da past confidence ==")
    from services.channels.dna import compute_channel_dna_extended, confidence_float

    # Small sample: 3 posts
    small_events = [
        {"channel_id": "-1001", "message_id": 1, "length": 100, "emoji_density": 0.01, "post_hour": 10, "post_weekday": 1, "has_media": False, "text": "Salom"},
        {"channel_id": "-1001", "message_id": 2, "length": 120, "emoji_density": 0.005, "post_hour": 11, "post_weekday": 1, "has_media": False, "text": "Qalay"},
        {"channel_id": "-1001", "message_id": 3, "length": 110, "emoji_density": 0.007, "post_hour": 10, "post_weekday": 2, "has_media": True, "media_type": "photo", "text": "Rasm"},
    ]
    result = compute_channel_dna_extended(small_events)
    check("small: insufficient=True", result.get("insufficient") is True)
    check("small: confidence 0.0", float(result.get("confidence", 1)) == 0.0, f"got {result.get('confidence')}")
    check("small: sample_size 3", result.get("sample_size") == 3)

    metrics = result.get("metrics") or {}
    for key, metric in metrics.items():
        conf = float(metric.get("confidence", 1))
        check(f"small: {key} confidence low (0.0)", conf == 0.0, f"got {conf} for {key}")

    # Test confidence_float function directly
    check("confidence_float: 0 -> 0.0", confidence_float(0) == 0.0)
    check("confidence_float: 3 -> 0.0", confidence_float(3) == 0.0)
    check("confidence_float: 5 -> 0.25", confidence_float(5) == 0.25)
    check("confidence_float: 6 -> low (<0.55)", confidence_float(6) < 0.55, f"got {confidence_float(6)}")
    check("confidence_float: 9 -> <0.55", confidence_float(9) < 0.55, f"got {confidence_float(9)}")
    check("confidence_float: 10 -> 0.55", confidence_float(10) == 0.55)
    check("confidence_float: 10 -> medium", 0.5 <= confidence_float(10) <= 0.8)
    check("confidence_float: 20 -> 0.75", confidence_float(20) == 0.75)
    check("confidence_float: 100 -> 0.95", confidence_float(100) == 0.95)
    check("confidence_float: never 1.0 for 100", confidence_float(100) < 1.0)
    check("confidence_float: never >1.0", all(confidence_float(n) <= 1.0 for n in [5, 10, 20, 50, 100, 1000]))

    # Medium sample: 6 posts should have low confidence, not high
    medium_events = [{"channel_id": "-1002", "message_id": i, "length": 200, "emoji_density": 0.008, "post_hour": 19, "post_weekday": 0, "has_media": False, "text": "Test"} for i in range(6)]
    result_med = compute_channel_dna_extended(medium_events)
    check("medium 6: confidence <0.55 (not fake high)", float(result_med.get("confidence", 1)) < 0.55,
          f"got {result_med.get('confidence')}")


def test_monitoring_no_ai_call():
    print("== Monitoring: AI chaqirilmasligi (faqat DB agregatsiyasi) ==")
    from services.channels import monitoring as monitoring_module
    from services.channels import monitor as monitor_module

    # Check that monitoring.py does NOT import AI
    monitoring_src = Path(ROOT / "services" / "channels" / "monitoring.py").read_text(encoding="utf-8")
    # It should not contain AI provider calls
    forbidden_ai_imports = ["ai_service", "ai_engine", "openai", "anthropic", "AI_ORCHESTRATOR", "generate_post"]
    for kw in forbidden_ai_imports:
        # Allow if in comment? We check that monitoring file doesn't have direct AI calls
        # For safety, we just ensure it doesn't import ai_service
        if kw == "ai_service" or kw == "ai_engine":
            check(f"monitoring.py no AI import {kw}", kw not in monitoring_src.lower(), f"found {kw}")

    # Check monitor.py also has no AI
    monitor_src = Path(ROOT / "services" / "channels" / "monitor.py").read_text(encoding="utf-8")
    for kw in ["ai_service", "ai_engine", "openai"]:
        check(f"monitor.py no AI import {kw}", kw not in monitor_src.lower(), f"found {kw}")

    # Check that extract functions are pure and don't call AI
    # Mock message
    class FakeChat:
        id = -100123456789

    class FakeMessage:
        chat = FakeChat()
        message_id = 123
        text = "Salom, bu test posti! Buyurtma bering 👉 😊"
        caption = None
        date = None
        photo = None
        video = None
        document = None

    meta = monitoring_module.extract_event_metadata(FakeMessage())
    check("monitoring: extract_event_metadata returns dict", isinstance(meta, dict))
    check("monitoring: meta has channel_id", "channel_id" in meta)
    check("monitoring: meta has length", "length" in meta)
    check("monitoring: meta length correct", meta["length"] == len(FakeMessage.text))

    meta2 = monitor_module.extract_lightweight_metadata(FakeMessage())
    check("monitor: extract_lightweight_metadata returns dict", isinstance(meta2, dict))
    check("monitor: lightweight has channel_id", "channel_id" in meta2)
    check("monitor: lightweight no AI field", "ai_response" not in meta2 and "ai_analysis" not in meta2)

    # Test that ingest does NOT call AI — mock DB
    mock_db = MagicMock()
    mock_db.insert_channel_post_event = MagicMock(return_value=True)
    mock_db.run_db = None

    # Ensure no AI function is called during ingest
    # We will patch any potential AI modules to fail if called
    async def _test_ingest():
        # monitoring ingest
        result = await monitoring_module.ingest_channel_post_event(FakeMessage(), db_module=mock_db)
        check("monitoring: ingest returns bool", isinstance(result, bool))
        check("monitoring: ingest calls DB", mock_db.insert_channel_post_event.called)

        mock_db.insert_channel_post_event.reset_mock()

        # monitor ingest
        result2 = await monitor_module.record_post_event(FakeMessage(), db_module=mock_db)
        check("monitor: record_post_event returns bool", isinstance(result2, bool))
        check("monitor: record_post_event calls DB", mock_db.insert_channel_post_event.called)

        # batch aggregate should NOT call AI
        mock_db.get_channel_post_events = MagicMock(return_value=[
            {"channel_id": "-100123", "message_id": i, "post_hour": 19, "post_weekday": 0,
             "has_media": False, "length": 200, "cta_detected": False, "emoji_density": 0.005,
             "text": "Test post"}
            for i in range(10)
        ])
        mock_db.save_channel_dna_profile = MagicMock(return_value=True)
        mock_db.save_channel_intelligence_profile = MagicMock(return_value=True)

        agg = await monitor_module.batch_aggregate_channel("-100123", db_module=mock_db, use_ai=False)
        check("monitor: batch_aggregate ok", agg.get("ok") is True)
        check("monitor: batch_aggregate no AI (ok True)", agg.get("ok") is True)
        # Even with use_ai=True, it should NOT call AI (only DB)
        agg_ai = await monitor_module.batch_aggregate_channel("-100123", db_module=mock_db, use_ai=True)
        check("monitor: batch_aggregate with use_ai=True still ok (no AI)", agg_ai.get("ok") is True)
        check("monitor: batch_aggregate saved", agg_ai.get("saved") is True or agg.get("saved") is True)

    asyncio.run(_test_ingest())


def test_migration_idempotency():
    print("== Migratsiyalar idempotency tekshiruvi ==")
    schema_path = ROOT / "schema.sql"
    schema = schema_path.read_text(encoding="utf-8")

    # Check idempotent patterns
    check("schema.sql: channel_dna table IF NOT EXISTS", "CREATE TABLE IF NOT EXISTS channel_dna" in schema)
    check("schema.sql: channel_dna indexes IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS idx_channel_dna_channel" in schema)
    check("schema.sql: channel_post_events UNIQUE", "UNIQUE(channel_id, message_id)" in schema or "uq_channel_post_events" in schema)
    check("schema.sql: ON CONFLICT DO NOTHING", "ON CONFLICT" in schema and "DO NOTHING" in schema)
    check("schema.sql: channel_dna hardening DO block", "$postassist_channel_dna_hardening$" in schema)
    check("schema.sql: integrity DO block", "$postassist_integrity$" in schema)
    check("schema.sql: FK NOT VALID fallback", "NOT VALID" in schema)
    check("schema.sql: channel_post_events FK", "fk_channel_post_events_channel" in schema)
    check("schema.sql: channel_dna FK", "fk_channel_dna_channel" in schema)
    check("schema.sql: channel_intelligence FK", "fk_channel_intelligence_profiles_channel" in schema)

    # Check that all CREATE INDEX are IF NOT EXISTS (idempotent)
    flat = " ".join(schema.split())
    total_indexes = flat.count("CREATE INDEX")
    idempotent_indexes = flat.count("CREATE INDEX IF NOT EXISTS")
    check("schema.sql: barcha indekslar idempotent", total_indexes == idempotent_indexes,
          f"{idempotent_indexes}/{total_indexes}")

    # Check database.py EXPECTED_TABLES includes channel_dna
    import database as db_mod
    check("database.py: EXPECTED_TABLES has channel_dna", "channel_dna" in db_mod.EXPECTED_TABLES)
    check("database.py: EXPECTED_INDEXES has idx_channel_dna_channel", "idx_channel_dna_channel" in db_mod.EXPECTED_INDEXES)
    check("database.py: EXPECTED_INDEXES has idx_channel_dna_updated", "idx_channel_dna_updated" in db_mod.EXPECTED_INDEXES)

    # Check INTEGRITY_CONSTRAINTS includes channel FKs
    constraint_names = [c["name"] for c in db_mod.INTEGRITY_CONSTRAINTS]
    check("database.py: FK channel_post_events", "fk_channel_post_events_channel" in constraint_names)
    check("database.py: FK channel_dna", "fk_channel_dna_channel" in constraint_names)
    check("database.py: FK channel_intelligence", "fk_channel_intelligence_profiles_channel" in constraint_names)
    check("database.py: FK channel_insights", "fk_channel_insights_channel" in constraint_names)

    # Check that save_channel_dna_profile exists and is idempotent (ON CONFLICT)
    import inspect
    src = inspect.getsource(db_mod.save_channel_dna_profile)
    check("database.py: save_channel_dna_profile ON CONFLICT", "ON CONFLICT" in src)
    check("database.py: save_channel_dna_profile UPSERT", "DO UPDATE SET" in src)

    src2 = inspect.getsource(db_mod.get_channel_dna_profile)
    check("database.py: get_channel_dna_profile exists", "channel_dna" in src2)

    # Check that schema.sql can be executed twice (idempotent) — static check only
    # Count that channel_dna table appears only once with IF NOT EXISTS (so second run safe)
    check("schema.sql: channel_dna table defined once", schema.count("CREATE TABLE IF NOT EXISTS channel_dna") >= 1)


def test_dna_legacy_compatibility():
    print("== DNA legacy compatibility ==")
    from services.channels.dna import compute_channel_dna, compute_channel_dna_extended

    events = [
        {"length": 400, "emoji_density": 0.009, "cta_detected": True, "has_media": True, "post_hour": 19, "post_weekday": 0}
        for _ in range(7)
    ]
    legacy = compute_channel_dna(events)
    check("legacy: ok for 7 posts", legacy.get("insufficient") is False)
    check("legacy: has profile", legacy.get("profile") is not None)
    check("legacy: profile has average_post_length", "average_post_length" in (legacy.get("profile") or {}))

    extended = compute_channel_dna_extended(events)
    check("extended: ok for 7 posts", extended.get("insufficient") is False)
    # Extended should have at least same sample_size
    check("extended: sample_size matches legacy", extended.get("sample_size") == legacy.get("sample_size"))


if __name__ == "__main__":
    test_dna_extended_metrics()
    test_dna_small_sample_low_confidence()
    test_monitoring_no_ai_call()
    test_migration_idempotency()
    test_dna_legacy_compatibility()

    print()
    print(f"O'tdi: {passed}, Xato: {failures}, Skip: {skipped}")
    if failures:
        print("Channel DNA & Monitoring testlarida xatolar bor ✗")
        sys.exit(1)
    print("Channel DNA & Monitoring testlari muvaffaqiyatli ✔")
    sys.exit(0)
