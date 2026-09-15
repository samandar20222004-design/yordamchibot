#!/usr/bin/env python3
"""PHASE 3 — AI ENGINE VA SMM ORKESTRATSIYASI TESTLARI.

Qamrov:
  1) Intent Router: Barcha asosiy intentlar (CREATE_POST, IMPROVE_POST, SHORTEN,
     EXPAND, GENERATE_VARIANTS, POST_AUDIT, CONTENT_IDEAS, UNKNOWN) to'g'ri aniqlanishi;
  2) Provider Fallback Chain: Birlamchi provayder xato berganda navbatdagisiga
     xavfsiz o'tishi va Mock fallback kafolati;
  3) AIOutputValidator & Controlled Retry: Bo'sh, yupqa yoki nosoz chiqishlarning
     aniqlanishi va kuchaytirilgan prompt bilan AYNAN 1 marta qayta so'rov yuborilishi;
  4) Phase 2 Transactional Quota integratsiyasi: reserve_ai_request va fail-closed
     refund kafolati;
  5) Telegram HTML Sanitization integratsiyasi.
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:AI_ORCHESTRATOR_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ADMIN_ID", "123456789")

from services.ai.router import SMMIntent, detect_intent
from services.ai.validator import AIOutputValidator, ValidationResult
from services.ai.providers import (
    AIProvider,
    AIProviderError,
    GeminiProvider,
    GroqProvider,
    OpenRouterProvider,
    MockProvider,
    ProviderChain,
)
from services.ai.orchestrator import AIOrchestrator, AIOrchestrationResult


# ============================================================
# 1. INTENT ROUTING TESTLARI
# ============================================================

def test_intent_routing_all_intents():
    """Barcha asosiy SMM intentlarining aniq topilishini tekshirish."""
    test_cases = [
        # CREATE_POST
        ("Futbol haqida post yoz", SMMIntent.CREATE_POST),
        ("Krossovka sotuvi bo'yicha yangi post yarat", SMMIntent.CREATE_POST),
        ("Yangi mahsulotimiz haqida post tayyorlab ber", SMMIntent.CREATE_POST),
        ("Write a post about productivity", SMMIntent.CREATE_POST),
        ("Напиши пост про осенние скидки", SMMIntent.CREATE_POST),

        # IMPROVE_POST
        ("Shu postni yaxshilab ber", SMMIntent.IMPROVE_POST),
        ("Matnni sayqallab ber, tushunarli bo'lsin", SMMIntent.IMPROVE_POST),
        ("Improve this marketing post", SMMIntent.IMPROVE_POST),
        ("Улучши этот пост для телеграм-канала", SMMIntent.IMPROVE_POST),
        ("Доработай текст, чтобы лучше продавалось", SMMIntent.IMPROVE_POST),

        # GENERATE_VARIANTS
        ("5 xil variant ber", SMMIntent.GENERATE_VARIANTS),
        ("Ushbu post uchun variantlar ber", SMMIntent.GENERATE_VARIANTS),
        ("Give me 3 variants of this headline", SMMIntent.GENERATE_VARIANTS),
        ("Предложи 3 варианта текста", SMMIntent.GENERATE_VARIANTS),

        # CONTENT_IDEAS
        ("Bugunga post g'oyasi kerak", SMMIntent.CONTENT_IDEAS),
        ("Ertangi kun uchun kontent g'oyalari ber", SMMIntent.CONTENT_IDEAS),
        ("Top content ideas for retail store", SMMIntent.CONTENT_IDEAS),
        ("Идеи для постов на неделю", SMMIntent.CONTENT_IDEAS),

        # SHORTEN
        ("Postni qisqartir", SMMIntent.SHORTEN),
        ("Qisqa qilib ber, juda cho'zilib ketibdi", SMMIntent.SHORTEN),
        ("Shorten this message into two sentences", SMMIntent.SHORTEN),
        ("Сделай короче этот текст", SMMIntent.SHORTEN),

        # EXPAND
        ("Batafsilroq yoz", SMMIntent.EXPAND),
        ("Postni kengaytirib ber, ma'lumot kam", SMMIntent.EXPAND),
        ("Expand this point with examples", SMMIntent.EXPAND),
        ("Напиши подробнее про каждую деталь", SMMIntent.EXPAND),

        # POST_AUDIT
        ("Postni audit qil", SMMIntent.POST_AUDIT),
        ("Ushbu postni tahlil qil va bahola", SMMIntent.POST_AUDIT),
        ("Audit this telegram post for flaws", SMMIntent.POST_AUDIT),
        ("Сделай аудит поста и оцени качество", SMMIntent.POST_AUDIT),

        # UNKNOWN
        ("Salom bot, ahvollaring qanday?", SMMIntent.UNKNOWN),
        ("12345", SMMIntent.UNKNOWN),
        ("", SMMIntent.UNKNOWN),
        (None, SMMIntent.UNKNOWN),
    ]

    for prompt, expected_intent in test_cases:
        detected = detect_intent(prompt)
        assert detected == expected_intent, f"Xato: '{prompt}' uchun kutilgan {expected_intent}, topildi {detected}"

    print("  [OK] Barcha 8 ta SMM intenti (UZ/RU/EN) 100% to'g'ri aniqlandi")


# ============================================================
# 2. PROVIDER FALLBACK ZANJIRI TESTLARI
# ============================================================

class FailingProvider(AIProvider):
    def __init__(self, name: str, error_msg: str = "Provider down"):
        self.name = name
        self.error_msg = error_msg
        self.called = False

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        self.called = True
        raise AIProviderError(self.error_msg)


class SuccessfulProvider(AIProvider):
    def __init__(self, name: str, return_text: str = "Test response"):
        self.name = name
        self.return_text = return_text
        self.called = False

    async def generate(self, prompt: str, context: dict | None = None) -> str:
        self.called = True
        return self.return_text


async def test_provider_fallback_chain_success():
    """Birlamchi provayder ishlamaganda avtomatik ikkinchisiga o'tish."""
    p1 = FailingProvider("GeminiPrimary", "HTTP 500 error")
    p2 = SuccessfulProvider("GroqSecondary", "🔥 <b>Ajoyib Groq posti</b>\n\n#smm #toshkent")
    p3 = SuccessfulProvider("OpenRouterTertiary", "OpenRouter javobi")

    chain = ProviderChain(providers=[p1, p2, p3])
    content, used = await chain.execute("SMM post yoz", {"lang": "uz"})

    assert p1.called is True, "P1 chaqirilmadi"
    assert p2.called is True, "P2 chaqirilmadi"
    assert p3.called is False, "P3 chaqirilmasligi kerak edi (P2 muvaffaqiyatli bo'ldi)"
    assert used == "GroqSecondary"
    assert "Groq posti" in content
    print("  [OK] Provider Fallback: Gemini (500) -> Groq muvaffaqiyatli ishladi")


async def test_provider_fallback_to_mock():
    """Barcha tashqi provayderlar ishlamay qolganda Mock provayderga xavfsiz o'tish."""
    p1 = FailingProvider("Gemini", "timeout")
    p2 = FailingProvider("Groq", "rate limit")
    p3 = FailingProvider("OpenRouter", "service unavailable")
    mock = MockProvider()

    chain = ProviderChain(providers=[p1, p2, p3, mock])
    content, used = await chain.execute("Futbol haqida post yoz", {"lang": "uz", "intent": "CREATE_POST"})

    assert p1.called and p2.called and p3.called
    assert used == "Mock"
    assert len(content) > 50
    assert "Futbol haqida post yoz" in content or "yangilik" in content
    print("  [OK] Barcha provayderlar yiqilganda MockProvider xavfsiz ishga tushdi")


# ============================================================
# 3. OUTPUT VALIDATOR VA CONTROLLED RETRY TESTLARI
# ============================================================

def test_ai_output_validator_rules():
    """Validator qoidalarining to'g'ri ishlashi."""
    # 1. Bo'sh javob
    res_empty = AIOutputValidator.validate("")
    assert res_empty.is_valid is False
    assert res_empty.error_code == "EMPTY_OUTPUT"
    assert res_empty.needs_retry is True

    # 2. Yupqa javob
    res_thin = AIOutputValidator.validate("Salom")
    assert res_thin.is_valid is False
    assert res_thin.error_code == "THIN_OUTPUT"
    assert res_thin.needs_retry is True

    # 3. Taqiqlangan belgilar (NUL byte)
    res_ctrl = AIOutputValidator.validate("Yaxshi post\x00lekin NUL bor va uzunligi yetarli")
    assert res_ctrl.is_valid is False
    assert res_ctrl.error_code == "INVALID_CHARACTERS"
    assert res_ctrl.needs_retry is True

    # 4. Xavfli script
    res_script = AIOutputValidator.validate("<script>alert('xss')</script> Post matni davom etadi")
    assert res_script.is_valid is False
    assert res_script.error_code == "INVALID_CHARACTERS"

    # 5. Telegram limitidan oshishi
    res_long = AIOutputValidator.validate("A" * 4100)
    assert res_long.is_valid is False
    assert res_long.error_code == "LENGTH_EXCEEDED"

    # 6. Til mosligi (kutilgan RU, lekin sof inglizcha)
    res_lang = AIOutputValidator.validate("This is purely english text without any cyrillic letters at all.", expected_lang="ru")
    assert res_lang.is_valid is False
    assert res_lang.error_code == "LANGUAGE_MISMATCH"
    assert res_lang.needs_retry is True

    # 7. Sifatli to'liq post
    good_post = (
        "🔥 <b>Yangi mahsulot sotuvda!</b>\n\n"
        "Biz sizga eng sifatli va qulay yechimlarni taqdim etamiz.\n"
        "📌 Hoziroq buyurtma bering va chegirmaga ega bo'ling!\n\n"
        "#yangi #chegirma #smm #toshkent"
    )
    res_good = AIOutputValidator.validate(good_post, expected_lang="uz")
    assert res_good.is_valid is True
    assert res_good.error_code is None

    print("  [OK] AIOutputValidator barcha nosoz va xavfli chiqishlarni to'g'ri aniqladi")


async def test_controlled_single_retry_on_thin_output():
    """Yupqa javob olinganda kuchaytirilgan prompt bilan AYNAN 1 marta retry qilinishi."""
    attempts = 0

    class FlakyProvider(AIProvider):
        name = "Flaky"

        async def generate(self, prompt: str, context: dict | None = None) -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return "Yupqa javob"  # 1-urinish: validator rad etadi
            return (
                "🔥 <b>Kuchaytirilgan to'liq post!</b>\n\n"
                "Endi post to'liq shaklda, barcha talablarga mos tarzda yozildi.\n"
                "👉 Batafsil ma'lumot havolada!\n\n"
                "#smm #kuchaytirilgan #sifatli"
            )

    provider = FlakyProvider()
    chain = ProviderChain(providers=[provider])
    orchestrator = AIOrchestrator(provider_chain=chain)

    result = await orchestrator.orchestrate(
        user_id=1001,
        prompt="Sotuv uchun post yoz",
        lang="uz",
        db_module=False,
    )

    assert result.success is True
    assert result.retried is True, "Retry bayrog'i o'rnatilmagan!"
    assert attempts == 2, f"Kutilgan aynan 2 urinish (1 original + 1 retry), lekin bo'ldi: {attempts}"
    assert "Kuchaytirilgan to'liq post" in result.content
    print("  [OK] Controlled Retry: Yupqa javob aniqlanib, aynan 1 marta muvaffaqiyatli qayta generatsiya qilindi")


# ============================================================
# 4. ATOMIK KVOTA VA FAIL-CLOSED INTEGRATSIYASI
# ============================================================

async def test_orchestrator_quota_exceeded_fail_closed():
    """Kvota yetarli bo'lmaganda fail-closed: generatsiya qilinmaydi va xato qaytadi."""
    mock_db = MagicMock()
    # reserve_ai_quota allowed=False qaytaradi
    fake_reserve = AsyncMock(return_value={
        "allowed": False,
        "reason": "insufficient_balance",
        "reservation_id": None,
    })

    with patch("services.ai_quota.reserve_ai_quota", fake_reserve):
        provider = SuccessfulProvider("MockProvider", "Generatsiya qilinmasligi kerak")
        orchestrator = AIOrchestrator(provider_chain=ProviderChain(providers=[provider]))

        res = await orchestrator.orchestrate(
            user_id=999,
            prompt="Futbol haqida post yoz",
            lang="uz",
            db_module=mock_db,
        )

        assert res.success is False
        assert res.error_code == "QUOTA_EXCEEDED"
        assert provider.called is False, "Kvotasiz provayder chaqirilmasligi kerak edi!"
    print("  [OK] Quota Exceeded: fail-closed tarzda generatsiya to'xtatildi")


async def test_orchestrator_refund_on_fatal_failure():
    """Halokatli xatolikda band qilingan kvota foydalanuvchiga qaytariladi (refund)."""
    mock_db = MagicMock()
    fake_reserve = AsyncMock(return_value={
        "allowed": True,
        "reservation_id": 77701,
        "source": "credit",
    })
    fake_release = AsyncMock(return_value={"refunded": True})

    with patch("services.ai_quota.reserve_ai_quota", fake_reserve), \
         patch("services.ai_quota.release_ai_quota", fake_release):

        failing_provider = FailingProvider("Broken", "Crash in provider")
        orchestrator = AIOrchestrator(provider_chain=ProviderChain(providers=[failing_provider]))

        # MockProvider'ni ham yiqiladigan qilamiz
        with patch.object(MockProvider, "generate", side_effect=RuntimeError("Mock also failed")):
            res = await orchestrator.orchestrate(
                user_id=999,
                prompt="Post yoz",
                lang="uz",
                db_module=mock_db,
            )

        assert res.success is False
        assert res.error_code == "ORCHESTRATION_FAILED"
        fake_release.assert_called_once_with(mock_db, 999, 77701)
    print("  [OK] Fail-closed: Halokatli xatoda kvota to'liq foydalanuvchiga qaytarildi (refund)")


# ============================================================
# 5. TELEGRAM HTML SANITIZATION INTEGRATSIYASI
# ============================================================

async def test_orchestrator_html_sanitization():
    """Generatsiya qilingan matn Telegram HTML standartida xavfsizlantiriladi."""
    raw_ai_text = (
        "<b>Aksiya!</b> Narx: 5 < 10 & 20 > 15.\n"
        "<unknown-tag>Noma'lum teg</unknown-tag>\n"
        "👉 <a href='https://t.me/kanal'>Kanalga o'tish</a>\n\n"
        "#aksiya #chegirma"
    )
    provider = SuccessfulProvider("MockProvider", raw_ai_text)
    orchestrator = AIOrchestrator(provider_chain=ProviderChain(providers=[provider]))

    res = await orchestrator.orchestrate(
        user_id=123,
        prompt="Aksiya haqida post yoz",
        lang="uz",
        db_module=False,
    )

    assert res.success is True
    # Xavfsiz escape bo'lganini tekshirish
    assert "&lt; 10 &amp;" in res.content
    assert "<b>Aksiya!</b>" in res.content
    assert "<unknown-tag>" not in res.content  # Noma'lum teg escape qilingan bo'lishi kerak
    print("  [OK] Telegram HTML Sanitization xavfsiz va to'liq tatbiq etildi")


# ============================================================
# ASOSIY RUNNER
# ============================================================

async def main_async():
    print("==============================================================")
    print(" PHASE 3: AI ENGINE VA SMM ORKESTRATSIYASI TESTLARI")
    print("==============================================================")

    print("\n== 1. Intent Router Testlari ==")
    test_intent_routing_all_intents()

    print("\n== 2. Provider Fallback Zanjiri Testlari ==")
    await test_provider_fallback_chain_success()
    await test_provider_fallback_to_mock()

    print("\n== 3. Output Validator va Controlled Retry Testlari ==")
    test_ai_output_validator_rules()
    await test_controlled_single_retry_on_thin_output()

    print("\n== 4. Atomik Kvota va Fail-Closed Testlari ==")
    await test_orchestrator_quota_exceeded_fail_closed()
    await test_orchestrator_refund_on_fatal_failure()

    print("\n== 5. HTML Sanitization Testlari ==")
    await test_orchestrator_html_sanitization()

    print("\n==============================================================")
    print(" BARCHA AI ORCHESTRATOR TESTLARI 100% MUVOFFAQIYATLI O'TDI ✔")
    print("==============================================================")


def main():
    try:
        asyncio.run(main_async())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
