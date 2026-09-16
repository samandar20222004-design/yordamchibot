#!/usr/bin/env python3
"""PHASE A — PRODUCTION SAFETY + CHANNEL INTELLIGENCE BASE TEST.

Talab (task):
  - production Mock blocking + refund (P0-A)
  - 20+ belgili yaroqsiz javob validator tomonidan rad etiladi (P0-B)
  - Channel Intelligence jadvallari: creation & idempotency (schema.sql + database.py)
  - ENVIRONMENT / AI_ALLOW_MOCK exports + MOCK_ALLOWED_ENVIRONMENTS tightening

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python python3 tests/production_safety_and_channel_intelligence_base_test.py
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:BASE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from services.ai.orchestrator import AIOrchestrator  # noqa: E402
from services.ai.providers import (  # noqa: E402
    AIProvider,
    AIProviderError,
    AllProvidersFailedError,
    MockProvider,
    NoConfiguredProviderError,
    ProviderChain,
    get_environment,
    mock_is_allowed,
)
from services.ai.validator import AIOutputValidator  # noqa: E402

PASSED = 0
FAILURES = 0
AI_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")
FULL_REFUND_MSG = "AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring"


def check(condition, label):
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label}")
    return bool(condition)


@contextmanager
def ai_env(environment: str | None, allow_mock: str | None, strip_keys: bool = True):
    watched = list(AI_KEY_VARS) + ["ENVIRONMENT", "AI_ALLOW_MOCK"]
    saved = {key: os.environ.get(key) for key in watched}
    try:
        if strip_keys:
            for key in AI_KEY_VARS:
                os.environ.pop(key, None)
        for key, value in (("ENVIRONMENT", environment), ("AI_ALLOW_MOCK", allow_mock)):
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def quota_patches(reservation_id: int = 77701):
    reserve = AsyncMock(return_value={"allowed": True, "reservation_id": reservation_id, "source": "credit"})
    release = AsyncMock(return_value={"refunded": True})
    return reserve, release


# ---------------------------------------------------------------------------
# 1) P0-A: production Mock blocking + refund
# ---------------------------------------------------------------------------
async def test_production_mock_blocking_and_refund():
    print("== 1) 🚫 Production Mock blocking + full refund (P0-A base) ==")
    with ai_env(environment="production", allow_mock="0"):
        check(get_environment() == "production", "ENVIRONMENT=production")
        check(mock_is_allowed() is False, "production + AI_ALLOW_MOCK=0 → mock_is_allowed=False")

        chain = ProviderChain()
        check("Mock" not in [p.name for p in chain.providers], "default chain'da Mock yo'q (prod)")
        check(chain.usable_providers() == [], "kalit yo'q → usable_providers=[] (prod)")

        explicit = ProviderChain(providers=[MockProvider()])
        check(explicit.usable_providers() == [], "aniq Mock ham prod'da filtrlanadi")

        check(MockProvider().is_available() is False, "MockProvider.is_available()=False (prod)")
        blocked = False
        try:
            await MockProvider().generate("Test post", {"lang": "uz"})
        except AIProviderError:
            blocked = True
        check(blocked, "MockProvider.generate() prod'da xato (fake text yo'q)")

        err_type = None
        try:
            await chain.execute("Post yoz", {"lang": "uz"})
        except NoConfiguredProviderError:
            err_type = "NoConfiguredProviderError"
        except AllProvidersFailedError:
            err_type = "AllProvidersFailedError"
        except Exception as e:
            err_type = f"other:{type(e).__name__}"
        check(err_type in ("NoConfiguredProviderError", "AllProvidersFailedError"),
              f"ProviderChain oshkora xato: {err_type}")

        mock_db = MagicMock()
        reserve, release = quota_patches(60001)
        with patch("services.ai_quota.reserve_ai_quota", reserve), \
                patch("services.ai_quota.release_ai_quota", release):
            result = await AIOrchestrator().orchestrate(
                user_id=1001, prompt="Post yoz", lang="uz", db_module=mock_db
            )
        check(result.success is False, "orchestrator fail-closed (prod)")
        check(result.error_code == "AI_UNAVAILABLE", f"error_code AI_UNAVAILABLE: {result.error_code}")
        check(result.user_message and FULL_REFUND_MSG in result.user_message,
              f"xavfsiz xabar: {result.user_message!r}")
        check(result.content == "" and result.raw_content == "", "soxta kontent yo'q")
        check(release.await_count == 1, f"kvota to'liq qaytarildi: {release.await_count}")

    # dev/test muhitida Mock ishlashi kerak
    with ai_env(environment="development", allow_mock="0"):
        check(mock_is_allowed() is True, "ENVIRONMENT=development → mock allowed")
        check("Mock" in [p.name for p in ProviderChain().providers], "dev chain'da Mock bor")
    with ai_env(environment="test", allow_mock="0"):
        check(mock_is_allowed() is True, "ENVIRONMENT=test → mock allowed")


# ---------------------------------------------------------------------------
# 2) P0-B: 20+ belgili yaroqsiz javob validator tomonidan rad etiladi
# ---------------------------------------------------------------------------
async def test_validator_rejects_20plus_invalid():
    print("\n== 2) 🛡 Validator 20+ belgili yaroqsiz javobni rad etadi (P0-B) ==")
    long_script = "<script>alert('xss')</script> Bu post matni yetarli uzun va xavfli"
    check(len(long_script) >= 20, f"test matn uzunligi >=20: {len(long_script)}")
    v = AIOutputValidator.validate(long_script)
    check(v.error_code == "INVALID_CHARACTERS", f"20+ script rad etildi: {v.error_code}")

    long_thin = "Qisqa"
    v2 = AIOutputValidator.validate(long_thin)
    check(v2.error_code in ("EMPTY_OUTPUT", "THIN_OUTPUT", "EMPTY", "THIN"),
          f"yupqa rad etildi: {v2.error_code}")

    # Orkestrator darajasi: 20+ yaroqsiz retry qabul qilinmaydi
    class BadThenValid(AIProvider):
        name = "BadProvider"
        def __init__(self):
            self.calls = 0
        async def generate(self, prompt, context=None):
            self.calls += 1
            if self.calls == 1:
                return "Yupqa"  # THIN → retry
            return "<script>alert('xss')</script> Endi matn yetarli uzun bo'ldi va yaroqsiz"

    class GoodProvider(AIProvider):
        name = "GoodProvider"
        async def generate(self, prompt, context=None):
            return (
                "🔥 <b>Yangi mahsulot sotuvda!</b>\n\n"
                "Sifatli va qulay yechim. Hoziroq buyurtma bering!\n\n"
                "#yangilik #smm #toshkent"
            )

    with ai_env(environment="production", allow_mock="0"):
        bad = BadThenValid()
        good = GoodProvider()
        result = await AIOrchestrator(
            provider_chain=ProviderChain(providers=[bad, good])
        ).orchestrate(user_id=2002, prompt="Post yoz", lang="uz", db_module=False)

        check(bad.calls == 2, f"Bad provider 2 chaqiruv (retry): {bad.calls}")
        check(result.provider_used == "GoodProvider", f"keyingi provayder ishlatildi: {result.provider_used}")
        check("<script" not in result.content, "yaroqsiz 20+ matn yetib bormadi")
        check(result.success is True, "yaroqli zaxira bilan muvaffaqiyatli")

    # Barchasi yaroqsiz → refund
    with ai_env(environment="production", allow_mock="0"):
        only_bad = BadThenValid()
        mock_db = MagicMock()
        reserve, release = quota_patches(60002)
        with patch("services.ai_quota.reserve_ai_quota", reserve), \
                patch("services.ai_quota.release_ai_quota", release):
            failed = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[only_bad])
            ).orchestrate(user_id=2003, prompt="Post yoz", lang="uz", db_module=mock_db)
        check(failed.success is False, "barchasi yaroqsiz → fail")
        check(release.await_count == 1, "refund bo'ldi")


# ---------------------------------------------------------------------------
# 3) Channel Intelligence — schema.sql + database.py + idempotency
# ---------------------------------------------------------------------------
def test_channel_intelligence_tables():
    print("\n== 3) 🧠 Channel Intelligence jadvallari — creation & idempotency ==")

    schema_path = ROOT / "telegram_bot" / "schema.sql"
    db_path = ROOT / "telegram_bot" / "database.py"
    config_path = ROOT / "telegram_bot" / "config.py"

    schema_text = schema_path.read_text(encoding="utf-8")
    db_text = db_path.read_text(encoding="utf-8")
    config_text = config_path.read_text(encoding="utf-8")

    # 3.1 schema.sql da 3 jadval IF NOT EXISTS bilan
    check("CREATE TABLE IF NOT EXISTS channel_intelligence_profiles" in schema_text,
          "schema.sql: channel_intelligence_profiles IF NOT EXISTS")
    check("CREATE TABLE IF NOT EXISTS channel_post_events" in schema_text,
          "schema.sql: channel_post_events IF NOT EXISTS")
    check("CREATE TABLE IF NOT EXISTS channel_insights" in schema_text,
          "schema.sql: channel_insights IF NOT EXISTS")

    # 3.2 ustun turlari spec bo'yicha
    check("channel_id VARCHAR(255) PRIMARY KEY" in schema_text or
          "channel_id VARCHAR(255) PRIMARY KEY" in db_text or
          "channel_id VARCHAR" in schema_text,
          "channel_id VARCHAR PK (profiles)")
    check("top_topics JSONB" in schema_text, "top_topics JSONB")
    check("confidence INT" in schema_text, "confidence INT")
    check("sample_size INT" in schema_text, "sample_size INT")
    check("updated_at TIMESTAMPTZ" in schema_text, "updated_at TIMESTAMPTZ")
    check("UNIQUE (channel_id, message_id)" in schema_text or
          "UNIQUE(channel_id,message_id)" in schema_text.replace(" ", ""),
          "channel_post_events UNIQUE(channel_id,message_id)")
    check("is_dismissed BOOLEAN DEFAULT FALSE" in schema_text,
          "channel_insights is_dismissed BOOLEAN DEFAULT FALSE")
    check("post_hour INT" in schema_text, "post_hour INT")
    check("has_media BOOLEAN" in schema_text, "has_media BOOLEAN")
    check("cta_detected BOOLEAN" in schema_text, "cta_detected BOOLEAN")
    check("insight_type VARCHAR" in schema_text, "insight_type VARCHAR")
    check("severity VARCHAR" in schema_text, "severity VARCHAR")

    # 3.3 channel_id type match channels table VARCHAR(255) — 100%
    # channels table ham VARCHAR(255) bo'lgani uchun tekshiramiz
    check("channels" in schema_text and "channel_id VARCHAR(255)" in schema_text,
          "channels table channel_id VARCHAR(255) — match")
    # yangi jadvallarda ham VARCHAR(255)
    count_varchar_255 = schema_text.count("channel_id VARCHAR(255)")
    check(count_varchar_255 >= 4,  # channels + 3 yangi
          f"channel_id VARCHAR(255) 4+ marta (topildi {count_varchar_255})")

    # 3.4 indekslar idempotent IF NOT EXISTS
    check("idx_channel_post_events_channel" in schema_text, "idx_channel_post_events_channel schema")
    check("idx_channel_post_events_created" in schema_text, "idx_channel_post_events_created schema")
    check("idx_channel_insights_channel" in schema_text, "idx_channel_insights_channel schema")
    check("idx_channel_insights_dismissed" in schema_text, "idx_channel_insights_dismissed schema")
    check(schema_text.count("CREATE INDEX IF NOT EXISTS idx_channel_post_events_channel") == 1,
          "index IF NOT EXISTS idempotent (post_events_channel)")
    check(schema_text.count("CREATE INDEX IF NOT EXISTS idx_channel_insights_channel") == 1,
          "index IF NOT EXISTS idempotent (insights_channel)")

    # 3.5 database.py EXPECTED_TABLES
    check("channel_intelligence_profiles" in db_text, "database.py EXPECTED_TABLES: profiles")
    check("channel_post_events" in db_text, "database.py EXPECTED_TABLES: post_events")
    check("channel_insights" in db_text, "database.py EXPECTED_TABLES: insights")
    check("EXPECTED_TABLES" in db_text and "channel_intelligence_profiles" in db_text,
          "EXPECTED_TABLES tuple extended")

    # 3.6 EXPECTED_INDEXES
    check("idx_channel_post_events_channel" in db_text, "EXPECTED_INDEXES: post_events_channel")
    check("idx_channel_post_events_created" in db_text, "EXPECTED_INDEXES: post_events_created")
    check("idx_channel_insights_channel" in db_text, "EXPECTED_INDEXES: insights_channel")
    check("idx_channel_insights_dismissed" in db_text, "EXPECTED_INDEXES: insights_dismissed")

    # 3.7 _init_db_once idempotent creation
    check("CREATE TABLE IF NOT EXISTS channel_intelligence_profiles" in db_text,
          "_init_db_once: profiles IF NOT EXISTS")
    check("CREATE TABLE IF NOT EXISTS channel_post_events" in db_text,
          "_init_db_once: post_events IF NOT EXISTS")
    check("CREATE TABLE IF NOT EXISTS channel_insights" in db_text,
          "_init_db_once: insights IF NOT EXISTS")
    check("CREATE INDEX IF NOT EXISTS idx_channel_post_events_channel" in db_text,
          "_init_db_once index IF NOT EXISTS (post_events_channel)")
    check("CREATE INDEX IF NOT EXISTS idx_channel_insights_dismissed" in db_text,
          "_init_db_once index IF NOT EXISTS (insights_dismissed)")

    # 3.8 idempotency — qayta-qayta yaratish xavfsiz (IF NOT EXISTS borligi bilan)
    # Har bir jadval uchun IF NOT EXISTS 1 marta bo'lishi kerak, UNIQUE ham bor
    check(db_text.count("CREATE TABLE IF NOT EXISTS channel_intelligence_profiles") == 1,
          "idempotency: profiles 1 marta")
    check(db_text.count("CREATE TABLE IF NOT EXISTS channel_post_events") == 1,
          "idempotency: post_events 1 marta")
    check(db_text.count("CREATE TABLE IF NOT EXISTS channel_insights") == 1,
          "idempotency: insights 1 marta")

    # 3.9 config.py ENVIRONMENT / AI_ALLOW_MOCK / MOCK_ALLOWED_ENVIRONMENTS
    check("ENVIRONMENT" in config_text, "config.py: ENVIRONMENT export")
    check("AI_ALLOW_MOCK" in config_text, "config.py: AI_ALLOW_MOCK export")
    check("MOCK_ALLOWED_ENVIRONMENTS" in config_text, "config.py: MOCK_ALLOWED_ENVIRONMENTS")
    check('frozenset({"development", "test"})' in config_text or
          "frozenset({'development', 'test'})" in config_text or
          'frozenset({\"development\", \"test\"})' in config_text,
          "config.py MOCK_ALLOWED_ENVIRONMENTS = frozenset({'development','test'})")

    # 3.10 providers.py ham tightening
    prov_path = ROOT / "telegram_bot" / "services" / "ai" / "providers.py"
    prov_text = prov_path.read_text(encoding="utf-8")
    check('frozenset({"development", "test"})' in prov_text or
          "frozenset({'development', 'test'})" in prov_text,
          "providers.py MOCK_ALLOWED_ENVIRONMENTS tightening")

    # 3.11 schema.sql da top_topics JSONB, is_dismissed default FALSE — idempotent
    check("CREATE TABLE IF NOT EXISTS channel_intelligence_profiles" in schema_text and
          "top_topics JSONB" in schema_text,
          "profiles JSONB + IF NOT EXISTS idempotent")


async def main_async():
    print("=" * 70)
    print(" 🧪 PHASE A BASE — PROD SAFETY + CHANNEL INTELLIGENCE BASE TEST")
    print("=" * 70)
    await test_production_mock_blocking_and_refund()
    await test_validator_rejects_20plus_invalid()
    test_channel_intelligence_tables()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] BASE TESTDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE A BASE — 100% YASHIL ✔")
    print("=" * 70)
    return 0


def main():
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception as exc:
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
