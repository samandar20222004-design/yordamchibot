#!/usr/bin/env python3
"""PHASE A — PRODUCTION SAFETY & AI VALIDATOR HARDENING (P0-A, P0-B, P0-C).

Phase 0 auditida topilgan uchta P0 muammoning tuzatilganini QAT'IY tekshiradi:

  P0-A — Mock production siyosati (services/ai/providers.py):
      * ``ENVIRONMENT=production`` + ``AI_ALLOW_MOCK=0`` (default) bo'lganda
        MockProvider zanjirda ISHLATILMAYDI (hatto aniq uzatilgan bo'lsa ham);
        haqiqiy provayder/kalit bo'lmasa — ``NoConfiguredProviderError`` /
        ``AllProvidersFailedError``;
      * orkestrator foydalanuvchiga xavfsiz xabar qaytaradi
        («AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring») va bron
        qilingan kvotani TO'LIQ qaytaradi — SOXTA generatsiya YO'Q;
      * ``ENVIRONMENT=test`` (yoki ``AI_ALLOW_MOCK=1``) bo'lganda Mock
        qonuniy ishlaydi (testlar/offline rejim buzilmaydi).

  P0-B — Validator bypass'i olib tashlandi (services/ai/orchestrator.py):
      * endi ``len(retry_output) >= 20`` uzunlik bypass'i YO'Q — 20+ belgili
        yaroqsiz javob ham validator tomonidan rad etiladi;
      * qat'iy sikl: urinish → validator → AYNAN 1 retry → validator →
        keyingi HAQIQIY provayder → validator → barchasi yaroqsiz bo'lsa
        xavfsiz xato + TO'LIQ refund.

  P0-C — Prompt/retry ko'rsatmalarining sizib chiqishi (services/ai/prompt_guard.py):
      * «MUHIM: Oldingi javob juda qisqa ...» kabi tizim ko'rsatmalari
        provayder javobidan tozalanadi va foydalanuvchiga HECH QACHON
        yetib bormaydi (kirish va chiqish tomonida ikki qatlamli himoya).

Ishga tushirish (repo ildizidan):
    PYTHON=$HOME/venv/bin/python python3 tests/production_safety_and_validator_test.py
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

# MUHIT — import'dan OLDIN (config BOT_TOKEN/DATABASE_URL talab qiladi).
os.environ.setdefault("BOT_TOKEN", "123456:PRODUCTION_SAFETY_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

from services.ai.orchestrator import AIOrchestrator  # noqa: E402
from services.ai.prompt_guard import (  # noqa: E402
    has_instruction_leak,
    sanitize_output,
    strip_instruction_leaks,
)
from services.ai.providers import (  # noqa: E402
    AIProvider,
    AIProviderError,
    AllProvidersFailedError,
    MockProvider,
    NoConfiguredProviderError,
    ProviderChain,
    ai_unavailable_message,
    get_environment,
    mock_is_allowed,
)
from services.ai.validator import AIOutputValidator  # noqa: E402

PASSED = 0
FAILURES = 0
AI_KEY_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")
FULL_REFUND_MSG = "AI hozirda mavjud emas, iltimos keyinroq urinib ko'ring"

VALID_POST = (
    "🔥 <b>Yangi mahsulot sotuvda!</b>\n\n"
    "Biz sizga eng sifatli va qulay yechimlarni taqdim etamiz.\n"
    "📌 Hoziroq buyurtma bering va chegirmaga ega bo'ling!\n\n"
    "#yangi #chegirma #smm #toshkent"
)


def check(condition, label):
    """Bitta tekshiruv — natija hisoboti (repo standarti: [OK] / [FAIL])."""
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
    """AI muhit o'zgaruvchilarini vaqtincha o'rnatadi (test tugagach 100% tiklanadi)."""
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
    """Atomik kvota bron/refund'ni mock qiladi: (reserve, release)."""
    reserve = AsyncMock(return_value={"allowed": True, "reservation_id": reservation_id,
                                      "source": "credit"})
    release = AsyncMock(return_value={"refunded": True})
    return reserve, release


# ===========================================================================
# TEST 1 — P0-A: production'da Mock ISHLAMAYDI (soxta generatsiya yo'q + refund)
# ===========================================================================
async def test_p0a_production_blocks_mock_and_refunds():
    print("== 1) 🚫 P0-A: production'da Mock taqiqlangan (xato + TO'LIQ refund) ==")
    with ai_env(environment="production", allow_mock="0"):
        check(get_environment() == "production", "ENVIRONMENT=production o'qildi")
        check(mock_is_allowed() is False,
              "production + AI_ALLOW_MOCK=0 → mock_is_allowed()=False")

        # 1.1 Default zanjir: faqat HAQIQIY provayderlar
        chain = ProviderChain()
        names = [p.name for p in chain.providers]
        check("Mock" not in names,
              f"default ProviderChain'ga Mock QO'SHILMADI (zanjir: {names})")
        check([p.name for p in chain.usable_providers()] == [],
              "kalitlar yo'q → ishlatilishi mumkin bo'lgan provayder YO'Q")

        # 1.2 Aniq uzatilgan Mock ham production'da filtrlanadi
        explicit = ProviderChain(providers=[MockProvider()])
        check(explicit.usable_providers() == [],
              "aniq uzatilgan MockProvider ham production'da chiqarib tashlanadi")

        # 1.3 MockProvider o'zi ham soxta matn qaytarmaydi
        check(MockProvider().is_available() is False,
              "MockProvider.is_available() production'da False")
        mock_blocked = False
        try:
            await MockProvider().generate("Futbol haqida post yoz", {"lang": "uz"})
        except AIProviderError:
            mock_blocked = True
        check(mock_blocked, "MockProvider.generate() production'da xato beradi (fake text yo'q)")

        # 1.4 Zanjir oshkora xato bilan tugaydi (jim Mock fallback yo'q)
        explicit_error = None
        try:
            await chain.execute("Futbol haqida post yoz", {"lang": "uz", "intent": "CREATE_POST"})
        except NoConfiguredProviderError as exc:
            explicit_error = "NoConfiguredProviderError"
            check("production" in str(exc), "xato matnida muhit ko'rsatilgan (diagnostika uchun)")
        except AllProvidersFailedError:
            explicit_error = "AllProvidersFailedError"
        except AIProviderError as exc:  # noqa: BLE001
            explicit_error = f"boshqa AIProviderError: {exc}"
        check(explicit_error in ("NoConfiguredProviderError", "AllProvidersFailedError"),
              f"ProviderChain.execute() oshkora xato berdi: {explicit_error}")

        # 1.5 Orkestrator: AI_UNAVAILABLE + xavfsiz xabar + TO'LIQ refund
        mock_db = MagicMock()
        reserve, release = quota_patches(55501)
        with patch("services.ai_quota.reserve_ai_quota", reserve), \
                patch("services.ai_quota.release_ai_quota", release):
            result = await AIOrchestrator().orchestrate(
                user_id=4242, prompt="Futbol haqida post yoz", lang="uz", db_module=mock_db)

        check(result.success is False, "production'da generatsiya MUVOFFAQIYATSIZ (fail-closed)")
        check(result.error_code == "AI_UNAVAILABLE",
              f"error_code == AI_UNAVAILABLE (topildi: {result.error_code})")
        check(result.user_message is not None and FULL_REFUND_MSG in result.user_message,
              f"foydalanuvchiga xavfsiz xabar: {result.user_message!r}")
        check(ai_unavailable_message("uz") == result.user_message,
              "xabar providers.ai_unavailable_message('uz') bilan bir xil (yagona manba)")
        check(result.provider_used in ("none", "", None) and MockProvider.name not in str(result.provider_used),
              f"soxta provayder ishlatilmadi (provider_used={result.provider_used!r})")
        check(result.content == "" and result.raw_content == "",
              "SOXTA kontent qaytarilmadi (content/raw_content bo'sh)")
        check(release.await_count == 1 and release.call_args_list[0].args == (mock_db, 4242, 55501),
              f"bron qilingan kvota TO'LIQ qaytarildi: {release.call_args_list}")

        # 1.6 Kalitlar bor, lekin hammasi yiqilsa — Mock baribir ishlamaydi
        class BrokenProvider(AIProvider):
            name = "BrokenReal"

            async def generate(self, prompt, context=None):
                raise AIProviderError("503 service unavailable")

        reserve2, release2 = quota_patches(55502)
        with patch("services.ai_quota.reserve_ai_quota", reserve2), \
                patch("services.ai_quota.release_ai_quota", release2):
            result2 = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[BrokenProvider()])
            ).orchestrate(user_id=4243, prompt="Post yoz", lang="uz", db_module=mock_db)

        check(result2.success is False and result2.error_code == "ORCHESTRATION_FAILED",
              f"haqiqiy provayder yiqildi → ORCHESTRATION_FAILED (topildi: {result2.error_code})")
        check(result2.user_message is not None and FULL_REFUND_MSG in result2.user_message,
              "bu holatda ham foydalanuvchi xavfsiz xabarni oladi")
        check(release2.await_count == 1, "kvota TO'LIQ qaytarildi (ikkinchi holat)")
        check("Mock" not in (result2.provider_used or ""),
              f"Mock ishlatilmadi (provider_used={result2.provider_used!r})")


# ===========================================================================
# TEST 2 — P0-A: dev/test muhitida Mock qonuniy ishlaydi
# ===========================================================================
async def test_p0a_mock_allowed_in_development_and_test():
    print("\n== 2) 🧪 P0-A: ENVIRONMENT=test yoki AI_ALLOW_MOCK=1 → Mock ishlaydi ==")
    with ai_env(environment="test", allow_mock="0"):
        check(mock_is_allowed() is True, "ENVIRONMENT=test → mock_is_allowed()=True")
        names = [p.name for p in ProviderChain().providers]
        check(names[-1] == "Mock", f"default zanjirda Mock oxirgi zaxira: {names}")
        check([p.name for p in ProviderChain().usable_providers()] == ["Mock"],
              "kalitsiz test muhitida Mock ishlatilishi mumkin")
        content, used = await ProviderChain().execute(
            "Futbol haqida post yoz", {"lang": "uz", "intent": "CREATE_POST"})
        check(used == "Mock" and len(content) > 50,
              f"ProviderChain Mock orqali javob qaytardi ({used}, {len(content)} belgi)")

        result = await AIOrchestrator().orchestrate(
            user_id=1, prompt="Futbol haqida post yoz", lang="uz", db_module=False)
        check(result.success is True and result.provider_used == "Mock",
              f"orkestrator test muhitida ishlaydi (provider={result.provider_used})")
        check(FULL_REFUND_MSG not in (result.user_message or ""),
              "muvaffaqiyatli javobda xato xabari yo'q")
        check(MockProvider().is_available() is True, "MockProvider.is_available() test'da True")

    with ai_env(environment="production", allow_mock="1"):
        check(mock_is_allowed() is True,
              "AI_ALLOW_MOCK=1 → production'da ham Mock ruxsat etilgan (aniq override)")
        content, used = await ProviderChain().execute("Aksiya posti yoz", {"lang": "uz"})
        check(used == "Mock", f"override bilan zanjir ishladi ({used})")

    with ai_env(environment="production", allow_mock=None):
        check(get_environment() == "production" and mock_is_allowed() is False,
              "ENVIRONMENT sozlanmagan (default) → production + Mock taqiqlangan (fail-closed)")


# ===========================================================================
# TEST 3 — P0-B: 20+ belgili yaroqsiz javob validatorni CHETLAB O'TMAYDI
# ===========================================================================
async def test_p0b_no_length_bypass_in_validator():
    print("\n== 3) 🛡 P0-B: uzunlik bypass'i olib tashlandi (len >= 20 endi ishlamaydi) ==")

    # 3.1 Validator darajasida: 20+ belgili, lekin yaroqsiz chiqishlar rad etiladi
    long_bad_script = "<script>alert('xss')</script> Post matni davom etadi"
    long_bad_control = "Yaxshi post \x00 lekin NUL belgisi bor va uzun"
    long_bad_lang = "This is a purely english marketing text for the russian audience."
    check(len(long_bad_script) >= 20
          and AIOutputValidator.validate(long_bad_script).error_code == "INVALID_CHARACTERS",
          f"20+ belgili xavfli skript rad etildi ({len(long_bad_script)} belgi)")
    check(len(long_bad_control) >= 20
          and AIOutputValidator.validate(long_bad_control).error_code == "INVALID_CHARACTERS",
          f"20+ belgili control-belgili matn rad etildi ({len(long_bad_control)} belgi)")
    check(len(long_bad_lang) >= 20
          and AIOutputValidator.validate(long_bad_lang, expected_lang="ru").error_code
          == "LANGUAGE_MISMATCH",
          f"20+ belgili til mos kelmagan matn rad etildi ({len(long_bad_lang)} belgi)")
    check(len(VALID_POST) >= 20 and AIOutputValidator.validate(VALID_POST, expected_lang="uz").is_valid,
          "yaroqli post validatordan o'tadi (regressiya yo'q)")

    # 3.2 Orkestrator darajasida: retry'da 20+ belgili yaroqsiz javob qabul qilinmaydi
    class RetryBadThenValid(AIProvider):
        """1-urinish yupqa, 2-urinish (retry) 20+ belgili YAROQSIZ (eski bypass)."""

        name = "RetryBad"

        def __init__(self):
            self.calls = 0

        async def generate(self, prompt, context=None):
            self.calls += 1
            if self.calls == 1:
                return "Yupqa"  # THIN_OUTPUT → retry
            # 20+ belgi, lekin INVALID_CHARACTERS — eski kod buni QABUL qilardi
            return "<script>alert('xss')</script> Endi matn yetarli uzun bo'ldi"

    class SecondRealProvider(AIProvider):
        name = "IkkinchiReal"

        def __init__(self):
            self.calls = 0

        async def generate(self, prompt, context=None):
            self.calls += 1
            return VALID_POST

    with ai_env(environment="production", allow_mock="0"):
        bad, second = RetryBadThenValid(), SecondRealProvider()
        result = await AIOrchestrator(
            provider_chain=ProviderChain(providers=[bad, second])
        ).orchestrate(user_id=11, prompt="Sotuv uchun post yoz", lang="uz", db_module=False)

        check(bad.calls == 2, f"1-provayderda AYNAN 2 chaqiruv (urinish + 1 retry): {bad.calls}")
        check(result.retried is True, "retried belgisi o'rnatilgan (1 marta retry bo'ldi)")
        check(result.provider_used == "IkkinchiReal",
              f"yaroqsiz retry'dan keyin KEYINGI HAQIQIY provayder ishlatildi "
              f"(provider={result.provider_used})")
        check(second.calls == 1, "ikkinchi provayder AYNAN 1 marta chaqirildi")
        check("<script" not in result.content and "alert(" not in result.content,
              "20+ belgili yaroqsiz matn foydalanuvchiga YETIB BORMADI (bypass yo'q)")
        check(result.success is True, "yaroqli zaxira javob bilan oqim muvaffaqiyatli yakunlandi")

        # 3.3 Barcha provayderlar yaroqsiz → xavfsiz xato + TO'LIQ refund
        only_bad = RetryBadThenValid()
        mock_db = MagicMock()
        reserve, release = quota_patches(88801)
        with patch("services.ai_quota.reserve_ai_quota", reserve), \
                patch("services.ai_quota.release_ai_quota", release):
            failed = await AIOrchestrator(
                provider_chain=ProviderChain(providers=[only_bad])
            ).orchestrate(user_id=12, prompt="Sotuv uchun post yoz", lang="uz", db_module=mock_db)

        check(failed.success is False, "hamma provayder yaroqsiz → generatsiya to'xtatildi")
        check(failed.error_code == "ORCHESTRATION_FAILED",
              f"error_code == ORCHESTRATION_FAILED (topildi: {failed.error_code})")
        check(failed.content == "" and "<script" not in failed.raw_content,
              "yaroqsiz kontent qaytarilmadi (content bo'sh)")
        check(release.await_count == 1 and release.call_args_list[0].args == (mock_db, 12, 88801),
              "bron TO'LIQ qaytarildi (refund)")
        check(only_bad.calls == 2, f"aynan 2 chaqiruv (1 + 1 retry), ortiqcha emas: {only_bad.calls}")


# ===========================================================================
# TEST 4 — P0-C: tizim/retry ko'rsatmalari sizib chiqmaydi
# ===========================================================================
async def test_p0c_no_prompt_instruction_leakage():
    print("\n== 4) 🕵️ P0-C: prompt/retry ko'rsatmalari javobga sizib chiqmaydi ==")

    uz_addon = AIOutputValidator.get_retry_prompt_addon("THIN_OUTPUT", expected_lang="uz")
    ru_addon = AIOutputValidator.get_retry_prompt_addon("LANGUAGE_MISMATCH", expected_lang="ru")
    en_addon = AIOutputValidator.get_retry_prompt_addon("LANGUAGE_MISMATCH", expected_lang="en")

    # 4.1 Guard funksiyalari
    check(has_instruction_leak(uz_addon) and has_instruction_leak(ru_addon)
          and has_instruction_leak(en_addon),
          "guard uz/ru/en retry ko'rsatmalarini aniqlaydi")
    dirty = f"🔥 <b>Yangi post</b>\n{uz_addon}\nAsosiy mazmun shu yerda davom etadi va yetarli uzun."
    cleaned, leaked = sanitize_output(dirty)
    check(leaked is True, "sanitize_output() sizib chiqishni bayroqladi (monitoring uchun)")
    check("MUHIM" not in cleaned and "TAQIQLANADI" not in cleaned,
          f"ko'rsatma matni olib tashlandi: {cleaned[:60]!r}")
    check("Yangi post" in cleaned and "Asosiy mazmun" in cleaned,
          "foydali kontent SAQLANIB qoldi (ortiqcha o'chirish yo'q)")
    check(strip_instruction_leaks(cleaned) == cleaned, "tozalash idempotent")
    legit = "<b>Diqqat!</b> Bugun do'kon yopiladi, ertaga kutamiz.\n\n#diqqat"
    check(sanitize_output(legit) == (legit, False),
          "oddiy post matni o'zgarmaydi ('Diqqat!' so'zi o'chirilmaydi)")

    with ai_env(environment="test", allow_mock="0"):
        # 4.2 MockProvider retry promptini javobiga KO'CHIRMAYDI (auditdagi asosiy yo'l)
        retry_prompt = "Futbol haqida post yoz" + uz_addon
        mock_out = await MockProvider().generate(
            retry_prompt, {"lang": "uz", "intent": "CREATE_POST"})
        check("MUHIM" not in mock_out and "TAQIQLANADI" not in mock_out,
              "MockProvider javobida ko'rsatma yo'q (prompt oldindan tozalanadi)")
        clean_out = await MockProvider().generate(
            "Futbol haqida post yoz", {"lang": "uz", "intent": "CREATE_POST"})
        check(mock_out == clean_out and len(mock_out) > 50,
              "ko'rsatma olib tashlangach javob toza prompt bilan bir xil va to'liq")

        # 4.3 Orkestrator: provayder promptni "echo" qilsa ham chiqish toza
        class EchoingProvider(AIProvider):
            name = "Echoing"

            async def generate(self, prompt, context=None):
                return ("🔥 <b>Yangi mahsulot</b>\n" + prompt
                        + "\nAsosiy mazmun shu yerda davom etadi va yetarli uzun.\n#smm")

        result = await AIOrchestrator(
            provider_chain=ProviderChain(providers=[EchoingProvider()])
        ).orchestrate(user_id=99, prompt="Sotuv posti" + uz_addon, lang="uz", db_module=False)

        # 4.4 Zanjir darajasida ham himoya
        chain_out, chain_used = await ProviderChain().execute(retry_prompt, {"lang": "uz"})
        check("MUHIM" not in chain_out and "TAQIQLANADI" not in chain_out,
              f"ProviderChain.execute() chiqishi ham toza ({chain_used})")

    check("MUHIM" not in result.content and "TAQIQLANADI" not in result.content,
          "orkestrator chiqishida ko'rsatma yo'q")
    check("Yangi mahsulot" in result.content,
          "provayderning haqiqiy kontenti saqlanib qoldi")
    check(result.success is True, "tozalashdan keyin oqim muvaffaqiyatli yakunlandi")

    # 4.5 Sizib chiqqan matn butunlay ko'rsatmadan iborat bo'lsa — validator rad etadi
    only_instruction = strip_instruction_leaks(uz_addon)
    check(only_instruction.strip() == "" or len(only_instruction.strip()) < 15,
          f"faqat ko'rsatmadan iborat javob bo'sh/yupqa bo'lib qoladi: {only_instruction!r}")


# ===========================================================================
# RUNNER
# ===========================================================================
async def main_async():
    print("=" * 70)
    print(" 🛡 PHASE A — PRODUCTION SAFETY & AI VALIDATOR HARDENING (P0-A/B/C)")
    print("=" * 70)
    await test_p0a_production_blocks_mock_and_refunds()
    await test_p0a_mock_allowed_in_development_and_test()
    await test_p0b_no_length_bypass_in_validator()
    await test_p0c_no_prompt_instruction_leakage()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] PHASE A TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE A — PRODUCTION SAFETY 100% YASHIL ✔")
    print("=" * 70)
    return 0


def main():
    try:
        sys.exit(asyncio.run(main_async()))
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
