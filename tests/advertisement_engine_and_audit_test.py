#!/usr/bin/env python3
"""📢 FAZA 15 & 16 — REKLAMA DVIGATELI VA REKLAMA AUDITI.

Tekshiriladigan kontraktlar:

  TEST 1 (FAZA 15) — REKLAMA GENERATSIYASI DVIGATELI:
      bitta briefdan AYNAN 4 ta reklama varianti — 🧬 native (Channel DNA
      ohangi), ⚡ short, 🎓 educational, 🌿 soft; har biri o'z burchagida,
      bir-birining sinonimi EMAS; brief validatsiyasi (mahsulot nomi,
      faktlar, havola sxemasi); CTA/havola variantlarga tushadi; chiqish
      sanitize qilinadi va 4096 chegarasida qoladi.

  TEST 2 (FAZA 15, NO FABRICATION) — TO'QIMA DA'VOLAR TAQIQLANADI:
      AI narx (120 000 so'm), chegirma (50%), kafolat («100% natijaga
      kafolat»), reyting (4.9 yulduz, №1), sertifikat (ISO 9001) va
      statistika (10 000+ mijoz) to'qib chiqarsa — bu da'volar postga
      TUSHMAYDI (jumla darajasida olib tashlanadi), ``removed_claims``
      qayd etiladi. Ijobiy nazorat: faktlarda BOR narx/muddat to'qima
      deb hisoblanmaydi. Zaxira (fallback) shablonlar ham raqamsiz.

  TEST 3 (FAZA 16) — REKLAMA AUDITI:
      4 mezon — 🧬 DNA mosligi, 📣 CTA aniqligi, 🚫 asossiz da'volar,
      📖 uzunlik/o'qilish; asossiz da'vo topilganda ogohlantirish +
      ``requires_admin_approval=True``; ball deterministik (model o'z
      reklamasiga «100/100» yoza olmaydi); hisobot sanitize qilinadi.

  TEST 4 (FAZA 16) — NASHR DARVOZASI (FAIL-CLOSED):
      audit muammoli bo'lsa nashr ADMIN tasdig'isiz AMALGA OSHMAYDI;
      admin tasdiqlasa ruxsat etiladi (``approved_by`` qayd etiladi);
      audit yo'q/bajarilmagan bo'lsa — hatto admin tasdig'i bilan ham
      nashr to'siladi.

  TEST 5 — POYDEVOR INTEGRATSIYASI (noldan yozilmagan):
      Phase 3 AIOrchestrator, Phase 2 ATOMIK kvota (4 ta AI chaqiruvi
      uchun BITTA bron, rad etilsa AI'ga chiqilmaydi, AI yiqilsa refund),
      Phase 2 sanitize_html + 4096 chunk va Channel DNA
      (``services.channels.dna``) qayta ishlatilishi.

  TEST 6 — REGRESSIYA: services.ads eksportlari, MockProvider ``ADS``
      rejimi (mavjud VARIANTS/AUDIT rejimlari buzilmagan), uz/ru/en i18n
      pariteti va runner ro'yxatdan o'tishi.

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh
    /tmp/venv/bin/python tests/advertisement_engine_and_audit_test.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import warnings
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — import'dan OLDIN (config BOT_TOKEN/DATABASE_URL talab qiladi).
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:ADS_ENGINE_AUDIT_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10017")
# Bu to'plam API kalitlarisiz, MockProvider bilan OFFLINE ishlaydi.
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Poydevor
# ---------------------------------------------------------------------------
from services.ads import (  # noqa: E402
    AD_AUDIT_CRITERIA,
    AD_FORMATS,
    AD_FORMAT_KEYS,
    CLAIM_CERTIFICATE,
    CLAIM_GUARANTEE,
    CLAIM_PRICE,
    CLAIM_RATING,
    SEVERITY_CRITICAL,
    AdBrief,
    AdEngine,
    AdPublishDecision,
    audit_ad,
    build_ad_prompt,
    build_ad_text,
    build_dna_block,
    evaluate_publish,
    formats_for,
    gate_with_workflow,
    is_safe_link,
    render_audit_report,
    resolve_format,
    scan_unsupported_claims,
    score_cta,
    score_dna_fit,
    score_readability,
    strip_unsupported_claims,
)
from services.ads.audit import (  # noqa: E402
    AD_AUDIT_WEIGHTS,
    AUDIT_PASS_SCORE,
    CRITERION_MAX,
    DNA_FIT_MIN,
    OVERALL_MAX,
    AdAuditService,
    collect_claim_spans,
    normalize_number,
    number_variants,
)
from services.ai import smm_mock  # noqa: E402
from services.ai.smm_common import (  # noqa: E402
    TELEGRAM_TEXT_LIMIT,
    html_length,
    same_content,
    strip_html,
)

PASSED = 0
FAILURES = 0


def check(condition, label, extra=""):
    """Bitta tekshiruv — repo standarti ([OK] / [FAIL])."""
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label}" + (f" — {extra}" if extra else ""))
    return bool(condition)


def balanced_tags(text):
    """Telegram HTML parse muvaffaqiyati uchun teglar muvozanati."""
    for tag in ("b", "i", "u", "s", "code", "pre", "blockquote"):
        if len(re.findall(rf"<{tag}(?:\s[^>]*)?>", text)) != \
                len(re.findall(rf"</{tag}>", text)):
            return False
    return True


# ---------------------------------------------------------------------------
# TEST MA'LUMOTLARI
# ---------------------------------------------------------------------------
BRIEF_KWARGS = dict(
    product="Onlayn ingliz tili kursi",
    facts=[
        "Darslar haftasiga 3 marta, jonli formatda o'tiladi",
        "Guruhlar 6 kishigacha cheklangan",
        "O'qituvchi — 8 yillik tajribaga ega metodist",
    ],
    offer="Birinchi dars bepul",
    audience="Boshlang'ich darajadagi kattalar",
    cta="Bepul darsga yoziling",
    link="https://t.me/postassist_demo",
)

#: To'qima (hallucination) reklama — AI shu matnni qaytarganini simulyatsiya qilamiz.
FABRICATED_AD = (
    "🔥 <b>Onlayn ingliz tili kursi</b>\n\n"
    "Faqat 120 000 so'm! 50% chegirma bugun tugaydi.\n"
    "100% natijaga kafolat beramiz — natija bo'lmasa pul qaytariladi.\n"
    "4.9 yulduzli reyting, 10 000+ mijoz bizni tanladi.\n"
    "ISO 9001 sertifikati bilan tasdiqlangan, bozorda №1 platforma.\n"
    "30 kun ichida natija, kuniga 15 daqiqa vaqt ajratasiz.\n\n"
    "👉 Bepul darsga yoziling: https://t.me/postassist_demo\n\n"
    "#reklama #aksiya #ingliztili"
)

#: To'qima da'volarning postda QOLMASLIGI kerak bo'lgan belgilari.
FABRICATION_TOKENS = (
    "120 000", "50%", "100%", "kafolat", "pul qaytariladi", "4.9",
    "yulduzli", "10 000", "ISO 9001", "sertifikat", "№1",
)


class StubResult:
    def __init__(self, success, content, provider="Mock", error=None, error_code=None):
        self.success = success
        self.content = content
        self.raw_content = content
        self.provider_used = provider
        self.retried = False
        self.intent = "CREATE_POST"
        self.error = error
        self.error_code = error_code
        self.generation_id = "stub-1"


class StubOrchestrator:
    """Orchestrator o'rniga — chaqiruvlarni sanaydi va javobni boshqaradi."""

    def __init__(self, ok=True, text=None, error_code=None, provider="Mock"):
        self.ok = ok
        self.text = text if text is not None else ""
        self.error_code = error_code
        self.provider = provider
        self.calls = []

    async def orchestrate(self, user_id, prompt, lang="uz", context=None,
                          db_module=None):
        self.calls.append({"prompt": prompt, "context": dict(context or {}),
                           "db_module": db_module, "user_id": user_id})
        if not self.ok:
            return StubResult(False, "", provider="none", error="provider down",
                              error_code=self.error_code or "ORCHESTRATION_FAILED")
        return StubResult(True, self.text, provider=self.provider)


class FabricatingOrchestrator(StubOrchestrator):
    """Har bir formatga bir xil «to'qima» reklama javobini beradi."""

    def __init__(self):
        super().__init__(ok=True, text=FABRICATED_AD, provider="Hallucinator")


class AtomicQuotaDB:
    """Phase 2 ATOMIK kvota yo'lini tekshirish uchun soxta DB adapteri."""

    def __init__(self, allowed=True, reason="ok", raise_on_reserve=False):
        self.allowed = allowed
        self.reason = reason
        self.raise_on_reserve = raise_on_reserve
        self.reserve_calls = []
        self.refund_calls = []

        async def run_db(func, *args, **kwargs):
            return func(*args, **kwargs)

        self.run_db = run_db
        self.run_db.__module__ = "database"

    def reserve_ai_request(self, user_id, operation_type, cost):
        self.reserve_calls.append((int(user_id), str(operation_type), int(cost)))
        if self.raise_on_reserve:
            raise RuntimeError("database unavailable")
        if not self.allowed:
            return {"allowed": False, "reason": self.reason, "reservation_id": None,
                    "source": None, "cost": 0, "used": 5, "max_ai": 5,
                    "credits_left": 0, "legacy": False}
        return {"allowed": True, "reason": "ok", "reservation_id": 91001,
                "source": "credit", "cost": int(cost), "used": 2, "max_ai": 10,
                "credits_left": 3, "legacy": False}

    def refund_ai_request(self, user_id, reservation_id):
        self.refund_calls.append((int(user_id), reservation_id))
        return {"success": True, "reason": "refunded",
                "reservation_id": reservation_id, "source": "credit"}


def channel_events(count=12, length=420, density=0.010, cta=True, media=False):
    """Channel DNA hisoblash uchun post eventlari."""
    return [{"length": length, "emoji_density": density, "cta_detected": cta,
             "has_media": media, "hour": 19, "weekday": 2} for _ in range(count)]


def dna_profile(count=12, length=420, density=0.010, cta=True):
    from services.channels.dna import compute_channel_dna
    result = compute_channel_dna(channel_events(count, length, density, cta))
    return result


# ===========================================================================
# TEST 1 — 4 XIL REKLAMA FORMATI
# ===========================================================================
async def test_four_ad_formats():
    print("\n== TEST 1: 4 xil reklama varianti (native/short/educational/soft) ==")

    brief = AdBrief.build(**BRIEF_KWARGS)
    ok, error = brief.validate()
    check(ok and error is None, "brief validatsiyasi o'tdi (mahsulot + faktlar + havola)")
    check(len(brief.facts) == 3 and brief.product.startswith("Onlayn"),
          f"brief maydonlari toza saqlandi (facts={len(brief.facts)})")

    engine = AdEngine()
    result = await engine.generate(777, brief, "uz")
    check(result.success is True, "generatsiya muvaffaqiyatli")
    check(result.count == 4, f"AYNAN 4 ta reklama varianti (bor: {result.count})")
    check(result.formats() == ["native", "short", "educational", "soft"],
          f"formatlar to'g'ri tartibda: {result.formats()}")
    check(set(result.formats()) == set(AD_FORMAT_KEYS),
          "format kalitlari AD_FORMAT_KEYS bilan bir xil")

    by_format = {variant.format: variant for variant in result.variants}
    for key in AD_FORMAT_KEYS:
        variant = by_format.get(key)
        if not check(variant is not None, f"{key} varianti mavjud"):
            continue
        meta = resolve_format(key)
        check(bool(strip_html(variant.content).strip()),
              f"{key}: matn bo'sh emas ({variant.chars} belgi)")
        check(variant.label and variant.angle and variant.emoji == meta.emoji,
              f"{key}: label/angle/emoji to'ldirilgan ({meta.emoji} {variant.label})")
        check(balanced_tags(variant.render()),
              f"{key}: HTML teglar muvozanatli (Telegram parse xatosi yo'q)")
        check(html_length(variant.render()) <= TELEGRAM_TEXT_LIMIT,
              f"{key}: xabar 4096 chegarasida")
        check("<script" not in variant.render().lower(),
              f"{key}: xavfli teg yo'q")

    # Formatlar bir-birining SINONIMI bo'lmasligi shart.
    contents = [variant.content for variant in result.variants]
    duplicates = [(a, b) for i, a in enumerate(contents)
                  for b in contents[i + 1:] if same_content(a, b, threshold=0.9)]
    check(not duplicates, "4 variant mazmunan farq qiladi (sinonim juftlik yo'q)")

    # Qisqa format — eng ixcham; ta'limiy — eng uzun (burchak mantig'i).
    check(by_format["short"].chars < by_format["educational"].chars,
          f"short ({by_format['short'].chars}) < educational "
          f"({by_format['educational'].chars})")
    check(by_format["short"].chars <= 600,
          f"short format 600 belgidan oshmaydi ({by_format['short'].chars})")

    # CTA va havola har bir variantda qatnashadi.
    for key in AD_FORMAT_KEYS:
        variant = by_format[key]
        plain = strip_html(variant.content).lower()
        check("yoziling" in plain, f"{key}: brief CTA'si postda bor")
        check(BRIEF_KWARGS["link"].lower() in plain, f"{key}: havola postda bor")

    # Prompt: faktlar + NO FABRICATION qoidalari + format ko'rsatmasi.
    prompt = build_ad_prompt(brief, resolve_format("native"), "uz")
    check(all(fact.lower() in prompt.lower() for fact in brief.facts),
          "prompt barcha berilgan faktlarni o'z ichiga oladi")
    check("QAT'IY QOIDALAR" in prompt and "UYDIRMANG" in prompt,
          "prompt'da NO FABRICATION qoidalari bor")
    check("[narx]" in prompt, "prompt noma'lum ma'lumot uchun placeholder talab qiladi")
    # Prompt tuzilishi: format ko'rsatmasi va vazifa bloki MAVJUD bo'lsin.
    format_line = [line for line in prompt.split("\n")
                   if line.startswith("FORMAT:")]
    check(bool(format_line) and "Native" in format_line[0],
          f"prompt'da format bloki bor: {format_line[0] if format_line else '-'}")
    check("VAZIFA:" in prompt and "MAX: 2200 belgi" in prompt,
          "prompt'da vazifa va hajm chegarasi ko'rsatilgan")
    check(BRIEF_KWARGS["link"] in prompt, "prompt'da CTA havolasi bor")

    # Tanlab generatsiya: faqat 2 format so'ralsa — aynan 2 ta qaytadi.
    two = await engine.generate(777, brief, "uz", formats=["short", "soft"])
    check(two.success and two.formats() == ["short", "soft"],
          f"formatlar tanlab olish mumkin: {two.formats()}")
    check(len(formats_for(None)) == 4 and len(formats_for(["nope"])) == 4,
          "noma'lum/bo'sh format ro'yxati → barcha 4 format")

    # Brief validatsiyasi — mahsulotsiz yoki faktsiz reklama YARATILMAYDI.
    stub = StubOrchestrator(text="bu matn ishlatilmasligi kerak")
    empty = await engine.generate(777, AdBrief.build(product=""), "uz",
                                  orchestrator=stub)
    check(empty.success is False and empty.error_code == "INVALID_INPUT"
          and empty.error == "EMPTY_PRODUCT",
          f"mahsulotsiz brief rad etildi: {empty.error}")
    check(not stub.calls, "rad etilgan briefda AI'ga UMUMAN chiqilmadi")

    no_facts = await engine.generate(777, AdBrief.build(product="Kurs"), "uz",
                                     orchestrator=stub)
    check(no_facts.success is False and no_facts.error == "NO_FACTS",
          f"faktsiz brief rad etildi (to'qima post yo'q): {no_facts.error}")

    # Lug'at ko'rinishidagi brief ham qabul qilinadi (handler qulayligi).
    from_dict = await engine.generate(777, dict(BRIEF_KWARGS), "uz")
    check(from_dict.success and from_dict.count == 4,
          "brief lug'at ko'rinishida ham 4 variant yaratildi")

    # Havola xavfsizligi: javascript:/data: sxemalari rad etiladi.
    check(is_safe_link("https://t.me/x") and is_safe_link("t.me/x")
          and is_safe_link(""),
          "https/t.me/bo'sh havola ruxsat etiladi")
    check(not is_safe_link("javascript:alert(1)") and not is_safe_link("data:text/html,x"),
          "javascript:/data: havolalari rad etiladi")
    unsafe = AdBrief.build(product="Kurs", facts=["Fakt bir"],
                           link="javascript:alert(1)")
    ok_link, err_link = unsafe.validate()
    check(ok_link is False and err_link == "INVALID_LINK",
          "xavfli havola brief validatsiyasidan o'tmaydi")


# ===========================================================================
# TEST 2 — NO FABRICATION (to'qima da'volar taqiqlanadi)
# ===========================================================================
async def test_no_fabrication():
    print("\n== TEST 2: NO FABRICATION — to'qima narx/kafolat/reyting postga tushmaydi ==")

    brief = AdBrief.build(**BRIEF_KWARGS)
    corpus = brief.corpus()

    # 2.1 Skanner to'qima da'volarni TOPADI (ijobiy nazorat).
    findings = scan_unsupported_claims(FABRICATED_AD, corpus, "uz")
    kinds = {item.kind for item in findings}
    check(len(findings) >= 6, f"skanner to'qima da'volarni topdi ({len(findings)} ta)")
    check({CLAIM_PRICE, CLAIM_GUARANTEE, CLAIM_RATING, CLAIM_CERTIFICATE} <= kinds,
          f"narx/kafolat/reyting/sertifikat turlari ushlandi: {sorted(kinds)}")
    check(any(item.kind == CLAIM_PRICE and "120 000" in item.snippet
              for item in findings),
          "to'qima narx «120 000 so'm» aniqlandi")
    check(any(item.kind == CLAIM_GUARANTEE for item in findings),
          "to'qima kafolat («kafolat», «pul qaytariladi») aniqlandi")
    check(any(item.kind == CLAIM_RATING and ("4.9" in item.snippet or "№1" in item.snippet)
              for item in findings),
          "to'qima reyting (4.9 yulduz / №1) aniqlandi")
    check(any(item.kind == CLAIM_CERTIFICATE for item in findings),
          "to'qima sertifikat (ISO 9001) aniqlandi")
    check(any(item.severity == SEVERITY_CRITICAL for item in findings),
          "topilgan da'volar orasida KRITIK daraja bor")

    # 2.2 Ijobiy nazorat: FAKTLARDA BOR narx/muddat — to'qima EMAS.
    priced = AdBrief.build(
        product="Kofe mashinasi",
        facts=["Narxi 1 200 000 so'm", "12 oy texnik xizmat kafolati bor"],
        offer="Bugun 10% chegirma", cta="Buyurtma bering")
    legit = ("☕ <b>Kofe mashinasi</b>\n\nNarxi 1 200 000 so'm, bugun 10% chegirma.\n"
             "12 oy texnik xizmat kafolati bor.\n\n👉 Buyurtma bering")
    legit_findings = scan_unsupported_claims(legit, priced.corpus(), "uz")
    check(legit_findings == [],
          f"faktlarda BOR narx/muddat to'qima deb hisoblanmadi "
          f"(findings={[f.snippet for f in legit_findings]})")

    tampered = legit.replace("1 200 000", "990 000").replace("12 oy", "24 oy")
    tampered_findings = scan_unsupported_claims(tampered, priced.corpus(), "uz")
    check(any(item.kind == CLAIM_PRICE and "990 000" in item.snippet
              for item in tampered_findings),
          "narx O'ZGARTIRILSA (990 000) — darhol ushlanadi")
    check(any(item.snippet.startswith("24") for item in tampered_findings),
          "muddat O'ZGARTIRILSA (24 oy) — ushlanadi")

    # 2.3 Tozalash: da'volar matndan OLIB TASHLANADI va qayta tekshiruv toza.
    cleaned, removed = strip_unsupported_claims(FABRICATED_AD, corpus, "uz")
    check(len(removed) >= 6, f"tozalashda {len(removed)} ta da'vo olib tashlandi")
    # Offset darajasi: da'volar asl (HTML'li) matnda TO'G'RI joyda topiladi.
    spans = collect_claim_spans(FABRICATED_AD,
                                scan_unsupported_claims(FABRICATED_AD, corpus, "uz"))
    check(len(spans) >= 6, f"da'vo oraliqlari topildi ({len(spans)} ta)")
    check(all(0 <= start < end <= len(FABRICATED_AD) for start, end, _ in spans),
          "barcha oraliqlar matn chegarasida")
    check(any("120 000" in FABRICATED_AD[start:end] for start, end, _ in spans),
          "narx da'vosining oraliqi aynan narxni qamrab oladi")
    check(collect_claim_spans(FABRICATED_AD, []) == [],
          "da'vo bo'lmasa oraliq ham yo'q")
    rescan = scan_unsupported_claims(cleaned, corpus, "uz")
    check(rescan == [], f"tozalangan matn qayta tekshiruvda toza ({len(rescan)})")
    lowered = strip_html(cleaned).lower()
    leaked = [token for token in FABRICATION_TOKENS if token.lower() in lowered]
    check(not leaked, f"tozalangan matnda to'qima belgi qolmadi (qolgan: {leaked})")
    check("yoziling" in lowered, "tozalash CTA'ni saqlab qoldi")

    # 2.4 DVIGATEL: to'qimachi AI bo'lsa ham hech bir variantda da'vo qolmaydi.
    result = await AdEngine().generate(888, brief, "uz",
                                       orchestrator=FabricatingOrchestrator())
    check(result.success and result.count == 4,
          f"to'qimachi AI bilan ham 4 variant chiqdi ({result.provider_used})")
    check(len(result.removed_claims) > 0,
          f"dvigatel {len(result.removed_claims)} ta to'qima da'voni olib tashladi")
    all_leaks = []
    for variant in result.variants:
        plain = strip_html(variant.content).lower()
        all_leaks += [token for token in FABRICATION_TOKENS
                      if token.lower() in plain]
        leaked_scan = scan_unsupported_claims(variant.content, corpus, "uz")
        if not check(leaked_scan == [],
                     f"{variant.format}: variantda asossiz da'vo qolmadi",
                     str([f.snippet for f in leaked_scan])):
            continue
        check(len(variant.removed_claims) > 0 or variant.source == "fallback",
              f"{variant.format}: olib tashlangan da'volar qayd etildi "
              f"({len(variant.removed_claims)})")
    check(not all_leaks, f"HECH BIR variantda to'qima belgi yo'q (leaks={all_leaks})")

    # 2.5 Zaxira (fallback) shablonlar ham raqamsiz va to'qimasiz.
    digit_free = AdBrief.build(product="Yoga kursi", facts=["Kichik guruhlar",
                                                            "Tajribali murabbiy"],
                               offer="Birinchi mashg'ulot bepul",
                               cta="Yoziling", link="https://t.me/yoga_demo")
    for key in AD_FORMAT_KEYS:
        text = build_ad_text(key, digit_free.product, list(digit_free.facts),
                             offer=digit_free.offer, cta=digit_free.cta,
                             link=digit_free.link, lang="uz")
        claims = scan_unsupported_claims(text, digit_free.corpus(), "uz")
        if not check(claims == [], f"fallback/{key}: asossiz da'vo yo'q",
                     str([c.snippet for c in claims])):
            continue
        plain = strip_html(text)
        check(len(plain) >= 60, f"fallback/{key}: matn yetarli ({len(plain)} belgi)")

    # 2.6 Mock/offline rejim (API kalitsiz) — provider Mock, da'vo yo'q.
    offline = await AdEngine().generate(888, brief, "uz")
    check(offline.success and offline.count == 4,
          f"API kalitsiz rejimda 4 variant ({offline.provider_used})")
    offline_leaks = []
    for variant in offline.variants:
        offline_leaks += [f.snippet for f in
                          scan_unsupported_claims(variant.content, corpus, "uz")]
    check(not offline_leaks, f"mock chiqishida ham asossiz da'vo yo'q ({offline_leaks})")
    check(offline.provider_used == "Mock",
          f"API kalitsiz muhitda MockProvider ishlatildi ({offline.provider_used})")

    # ADS rejimi kontekst orqali uzatilishi — chaqiruvlar YOZIB OLINADI.
    recorder = StubOrchestrator(text="")
    await AdEngine(recorder).generate(888, brief, "uz")
    check(len(recorder.calls) == 4,
          f"4 ta alohida AI chaqiruvi qayd etildi ({len(recorder.calls)})")
    check(all(call["context"].get("smm_mode") == "ADS" for call in recorder.calls),
          "har bir chaqiruvda smm_mode=ADS uzatilgan")
    check([call["context"].get("smm_ads_format") for call in recorder.calls] ==
          ["native", "short", "educational", "soft"],
          "har bir chaqiruv o'z formati bilan yuborilgan")
    check(all(call["context"].get("smm_ads_brief", {}).get("product") == brief.product
              for call in recorder.calls),
          "brief payload'i (mahsulot) kontekst orqali yetkazilgan")
    check(all(brief.facts[0] in call["prompt"] for call in recorder.calls),
          "faktlar prompt matnida ham bor (mock'siz provayderlar uchun)")

    # 2.7 Sonlarni normallashtirish — "120 000" va "120000" bir xil.
    check(normalize_number("120 000") == normalize_number("120000") == "120000",
          "son normalizatsiyasi: '120 000' == '120000'")
    check(normalize_number("1.5") == "1.5", "o'nlik kasr saqlanadi (1.5)")
    check({"1500", "1.500"} <= number_variants("1,500"),
          "'1,500' ikki talqinda ham taqqoslanadi (1500 va 1.500)")
    priced_variants = AdBrief.build(product="Kurs",
                                    facts=["Narxi 1,500 so'm"], cta="Yozing")
    check(scan_unsupported_claims("Narxi 1500 so'm. 👉 Yozing",
                                  priced_variants.corpus(), "uz") == [],
          "faktdagi '1,500' postda '1500' deb yozilsa ham to'qima emas")

    # 2.8 Placeholder'lar to'qima deb hisoblanmaydi (lekin raqam emas).
    placeholder_text = "💰 <b>Kurs</b>\n\nNarxi: [narx] so'm.\n\n👉 Yozing"
    check(scan_unsupported_claims(placeholder_text, "Kurs Yozing", "uz") == [],
          "[narx] placeholder'i to'qima deb hisoblanmaydi")


# ===========================================================================
# TEST 3 — REKLAMA AUDITI
# ===========================================================================
async def test_ad_audit():
    print("\n== TEST 3: Reklama auditi — DNA, CTA, asossiz da'volar, o'qilish ==")

    brief = AdBrief.build(**BRIEF_KWARGS)
    corpus = brief.corpus()

    # 3.1 Toza post — audit yashil, nashr ruxsat etiladi.
    clean_post = build_ad_text("native", brief.product, list(brief.facts),
                               offer=brief.offer, audience=brief.audience,
                               cta=brief.cta, link=brief.link, lang="uz")
    clean = audit_ad(clean_post, facts=list(brief.facts), product=brief.product,
                     offer=brief.offer, audience=brief.audience, cta=brief.cta,
                     link=brief.link, format="native", lang="uz")
    check(clean.ok and clean.passed, "toza reklama auditi o'tdi")
    check(clean.score >= AUDIT_PASS_SCORE,
          f"toza reklama balli yuqori ({clean.score}/100, baho {clean.grade})")
    check(clean.claims == [], "toza reklamada asossiz da'vo yo'q")
    check(clean.requires_admin_approval is False,
          "muammosiz reklama admin tasdig'ini talab qilmaydi")
    check({item.key for item in clean.checks} ==
          {"dna_fit", "cta_clarity", "unsupported_claims", "readability"},
          "audit 4 mezonni qamrab oladi")
    check(all(0 <= item.score <= CRITERION_MAX for item in clean.checks),
          "har bir mezon balli 0..10 oralig'ida")
    check(sum(AD_AUDIT_WEIGHTS.values()) == OVERALL_MAX,
          f"mezon og'irliklari yig'indisi 100 ({sum(AD_AUDIT_WEIGHTS.values())})")

    # 3.2 To'qima reklama — audit USHLAYDI va ogohlantiradi.
    dirty = audit_ad(FABRICATED_AD, facts=list(brief.facts), product=brief.product,
                     offer=brief.offer, audience=brief.audience,
                     cta=brief.cta, link=brief.link, format="native", lang="uz")
    check(len(dirty.claims) >= 6,
          f"audit asossiz da'volarni ushladi ({len(dirty.claims)} ta)")
    check({CLAIM_PRICE, CLAIM_GUARANTEE, CLAIM_RATING, CLAIM_CERTIFICATE} <=
          {item.kind for item in dirty.claims},
          "audit narx/kafolat/reyting/sertifikat turlarini ajratadi")
    check(dirty.blockers, f"bloklovchi muammolar qaytdi ({len(dirty.blockers)})")
    check(dirty.requires_admin_approval is True,
          "muammoli reklama ADMIN tasdig'ini talab qiladi")
    check(dirty.score < clean.score and dirty.score <= 40,
          f"to'qima reklama balli keskin pasaydi ({dirty.score} < {clean.score})")
    check("UNSUPPORTED_PRICE" in dirty.reason_codes
          and "UNSUPPORTED_GUARANTEE" in dirty.reason_codes,
          f"reason_codes aniqlik bilan qaytdi: {dirty.reason_codes[:4]}")
    claims_check = dirty.check("unsupported_claims")
    check(claims_check is not None and claims_check.passed is False
          and claims_check.severity == SEVERITY_CRITICAL,
          "unsupported_claims mezoni KRITIK darajada yiqildi")
    check(claims_check is not None and claims_check.fix,
          "muammoli mezon uchun aniq tuzatish tavsiyasi berildi")

    # 3.3 Determinizm — bir xil kirish → bir xil ball (model manipulyatsiyasi yo'q).
    again = audit_ad(FABRICATED_AD, facts=list(brief.facts), product=brief.product,
                     offer=brief.offer, audience=brief.audience, cta=brief.cta,
                     link=brief.link, format="native", lang="uz")
    check(again.score == dirty.score and len(again.claims) == len(dirty.claims),
          f"audit deterministik (ball {again.score} == {dirty.score})")
    check(not isinstance(audit_ad("", format="native"), type(None)),
          "bo'sh postda audit istisno bermaydi")
    empty = audit_ad("   ", format="native")
    check(empty.ok is False and empty.error == "empty_post"
          and empty.requires_admin_approval is True,
          "bo'sh post: audit bajarilmadi va nashr talab qiladi")

    # 3.4 CTA mezoni — chaqiruv yo'q / oxirida emas / havola tushmagan.
    no_cta = ("🧬 <b>Kurs</b>\n\nDarslar haftasiga uch marta o'tiladi.\n"
              "Guruhlar kichik, e'tibor har bir talabaga.\n\nKurs haqida "
              "ma'lumot kanalda joylashtirilgan.")
    no_cta_info = score_cta(no_cta, cta="Bepul darsga yoziling",
                            link="https://t.me/postassist_demo", lang="uz")
    check(no_cta_info["score"] <= 5 and no_cta_info["metrics"]["has_cta_verb"] is False,
          f"CTA'siz post past baholandi ({no_cta_info['score']}/10)")
    with_cta = no_cta + "\n\n👉 Bepul darsga yoziling\n🔗 https://t.me/postassist_demo"
    cta_info = score_cta(with_cta, cta="Bepul darsga yoziling",
                         link="https://t.me/postassist_demo", lang="uz")
    check(cta_info["score"] == CRITERION_MAX,
          f"CTA + havola bilan to'liq ball ({cta_info['score']}/10)")
    missing_link = score_cta(no_cta + "\n\n👉 Bepul darsga yoziling",
                             cta="Bepul darsga yoziling",
                             link="https://t.me/postassist_demo", lang="uz")
    check(missing_link["score"] <= 5 and missing_link["metrics"]["link_present"] is False,
          "brief'dagi havola postga tushmasa — CTA mezoni yiqiladi")

    # 3.5 O'qilish mezoni — juda qisqa / juda uzun / emoji spam.
    short_info = score_readability("Qisqa.", "native")
    check(short_info["score"] < CRITERION_MAX, "juda qisqa matn past baholandi")
    long_info = score_readability("Juda uzun qator. " * 200, "short")
    check(long_info["score"] < CRITERION_MAX,
          "short formatda juda uzun matn past baholandi")
    spam = "🔥" * 60 + " reklama matni"
    spam_info = score_readability(spam, "native")
    check(spam_info["metrics"]["emoji_density"] > 0.08 and spam_info["score"] < CRITERION_MAX,
          "emoji spam aniqlandi va ball pasaytirildi")
    ok_info = score_readability(clean_post, "native")
    check(ok_info["score"] >= 8, f"normal reklama o'qilishi yuqori ({ok_info['score']}/10)")

    # 3.6 DNA mezoni — yetarli ma'lumot bo'lmasa SOXTA ball yo'q (skip).
    no_dna = audit_ad(clean_post, facts=list(brief.facts), product=brief.product,
                      offer=brief.offer, audience=brief.audience, cta=brief.cta,
                      link=brief.link, format="native", lang="uz",
                      dna={"insufficient": True, "profile": None, "sample_size": 2})
    dna_check = no_dna.check("dna_fit")
    check(dna_check is not None and dna_check.skipped is True,
          "kam postda DNA mezoni o'tkazib yuborildi (soxta baho yo'q)")
    check(no_dna.dna_applied is False, "DNA qo'llanmadi deb belgilandi")
    info = score_dna_fit(clean_post, {"average_post_length": 400}, "uz")
    check(info["skipped"] is True, "sample_size bo'lmagan profil ham skip qilinadi")

    # 3.7 Hisobot — sanitize qilingan, balli va xulosasi bilan.
    report = render_audit_report(dirty, "uz")
    check("Reklama auditi" in report and f"{dirty.score}/100" in report,
          "hisobotda sarlavha va ball bor")
    check("ADMIN" in report, "muammoli hisobotda admin tasdig'i talabi ko'rsatilgan")
    check(balanced_tags(report) and html_length(report) <= TELEGRAM_TEXT_LIMIT,
          "hisobot Telegram'ga tayyor (teglar muvozanatli, limit ichida)")
    clean_report = render_audit_report(clean, "uz")
    check("Nashr uchun yaroqli" in clean_report,
          "toza reklama hisobotida nashr ruxsati bor")

    # 3.8 Audit servisi AI chaqirmaydi (ballar lokal, deterministik) —
    # xizmat orchestrator'ga UMUMAN bog'lanmagan bo'lishi shart.
    service = AdAuditService()
    check(not hasattr(service, "orchestrator") and not hasattr(service, "ask"),
          "audit xizmati orchestrator/AI chaqiruv interfeysiga ega emas")
    from services.ai.smm_common import SMMFeatureService
    check(not isinstance(service, SMMFeatureService),
          "audit SMMFeatureService emas — kvota/AI talab qilmaydi")
    check(service.feature == "ads_audit", "audit xizmati nomi 'ads_audit'")
    check(len(AD_AUDIT_CRITERIA) == 4,
          f"audit mezonlari soni 4 ({[c.key for c in AD_AUDIT_CRITERIA]})")
    check(corpus and brief.product in corpus,
          "audit faktlar korpusi brief'dan yig'iladi")


# ===========================================================================
# TEST 4 — NASHR DARVOZASI (FAIL-CLOSED ADMIN TASDIG'I)
# ===========================================================================
async def test_publish_gate():
    print("\n== TEST 4: Nashr darvozasi — admin tasdig'isiz reklama chiqmaydi ==")

    brief = AdBrief.build(**BRIEF_KWARGS)
    dirty = audit_ad(FABRICATED_AD, facts=list(brief.facts), product=brief.product,
                     offer=brief.offer, audience=brief.audience,
                     cta=brief.cta, link=brief.link, format="native", lang="uz")
    clean_post = build_ad_text("soft", brief.product, list(brief.facts),
                               offer=brief.offer, audience=brief.audience,
                               cta=brief.cta, link=brief.link, lang="uz")
    clean = audit_ad(clean_post, facts=list(brief.facts), product=brief.product,
                     offer=brief.offer, audience=brief.audience, cta=brief.cta,
                     link=brief.link, format="soft", lang="uz")

    blocked = evaluate_publish(dirty)
    check(isinstance(blocked, AdPublishDecision), "publish qarori AdPublishDecision")
    check(blocked.allowed is False,
          "muammoli reklama admin tasdig'isiz NASHR QILINMAYDI")
    check(blocked.requires_admin_approval is True and blocked.admin_approved is False,
          "qaror admin tasdig'ini talab qilayotganini ko'rsatadi")
    check(blocked.blockers and blocked.reason_codes,
          "to'silish sabablari aniq qaytarildi")
    check("ADMIN" in blocked.message, "foydalanuvchiga tushunarli ogohlantirish berildi")

    approved = evaluate_publish(dirty, admin_approved=True, approved_by=555)
    check(approved.allowed is True and approved.admin_approved is True
          and approved.approved_by == 555,
          f"admin tasdiqladi → nashr ruxsat etildi (approved_by={approved.approved_by})")
    check(approved.blockers, "tasdiqlangan holda ham muammolar qayd etiladi")

    free = evaluate_publish(clean)
    check(free.allowed is True and free.requires_admin_approval is False,
          "toza reklama admin tasdig'isiz nashr qilinadi")

    none_decision = evaluate_publish(None)
    check(none_decision.allowed is False and "NO_AUDIT" in none_decision.reason_codes,
          "audit natijasi bo'lmasa nashr to'siladi (fail-closed)")

    failed = evaluate_publish(audit_ad("", format="native"), admin_approved=True,
                              approved_by=1)
    check(failed.allowed is False and "AUDIT_FAILED" in failed.reason_codes,
          "bo'sh/buzuq post admin tasdig'i bilan ham chiqmaydi")

    # Mavjud ApprovalWorkflow bilan bog'lanish — admin tasdig'isiz post
    # rejalashtirilib ham, chiqarilib ham bo'lmaydi (state machine o'tkazmaydi).
    from services.channels.team import ApprovalWorkflow
    workflow = ApprovalWorkflow()
    post = workflow.create("-100123", 999, FABRICATED_AD)
    gated = gate_with_workflow(workflow, post["id"], 999, dirty)
    check(gated["allowed"] is False and gated["submitted"] is True,
          "muammoli reklama tasdiq navbatiga yuborildi")
    check(gated["status"] == "pending_approval",
          f"post holati: {gated['status']} (admin tasdig'i kutilmoqda)")
    check(workflow.schedule(post["id"], "scheduler") is False,
          "admin tasdiqlamaguncha REJALASHTIRIB bo'lmaydi")
    check(workflow.publish(post["id"], "owner") is False,
          "admin tasdiqlamaguncha NASHR QILIB bo'lmaydi")
    check(workflow.approve(post["id"], "owner") is True
          and workflow.schedule(post["id"], "scheduler") is True,
          "admin tasdiqlagach rejalashtirish ochildi")

    clean_workflow = ApprovalWorkflow()
    clean_post_row = clean_workflow.create("-100123", 999, clean_post)
    clean_gated = gate_with_workflow(clean_workflow, clean_post_row["id"], 999, clean)
    check(clean_gated["allowed"] is True and clean_gated["requires_admin_approval"] is False
          and clean_gated["submitted"] is False,
          "toza reklama majburan tasdiq navbatiga tushirilmaydi")

    # Oqim: generatsiya → audit → nashr qarori (end-to-end).
    result = await AdEngine().generate(999, brief, "uz")
    variant = result.by_format("native")
    audit = audit_ad(variant.content, facts=list(brief.facts),
                     product=brief.product, offer=brief.offer,
                     audience=brief.audience, cta=brief.cta, link=brief.link,
                     format=variant.format, lang="uz")
    decision = evaluate_publish(audit)
    check(decision.allowed is True,
          "toza generatsiya → audit → nashr ruxsati (end-to-end)")
    check(audit.chars > 0 and audit.words > 0,
          f"audit metrikalari to'ldirilgan ({audit.chars} belgi, {audit.words} so'z)")


# ===========================================================================
# TEST 5 — POYDEVOR INTEGRATSIYASI (kvota, DNA, sanitizer)
# ===========================================================================
async def test_infrastructure_reuse():
    print("\n== TEST 5: Poydevor — Phase 2 kvota, Channel DNA, Phase 2 sanitizer ==")

    brief = AdBrief.build(**BRIEF_KWARGS)
    stub = StubOrchestrator(text=("<b>Reklama</b>\n\n" + " ".join(brief.facts) +
                                  "\n\n👉 Bepul darsga yoziling\n\n"
                                  f"🔗 {BRIEF_KWARGS['link']}\n\n#reklama #kurs #til"))

    # 5.1 KVOTA — 4 ta AI chaqiruvi uchun BITTA atomik bron.
    db = AtomicQuotaDB()
    result = await AdEngine(stub).generate(7, brief, "uz", db_module=db)
    check(result.success and db.reserve_calls == [(7, "magic_post:ads", 1)],
          f"4 AI chaqiruvi uchun BITTA bron: {db.reserve_calls}")
    check(len(stub.calls) == 4,
          f"aynan 4 ta AI chaqiruvi orchestrator orqali ketti ({len(stub.calls)})")
    check(db.refund_calls == [], "muvaffaqiyatli batch'da refund qilinmadi")
    check(result.cost == 1 and result.paid is True,
          f"1 kredit yechildi (cost={result.cost})")
    check(all(call["db_module"] is False and call["context"].get("skip_quota") is True
              for call in stub.calls),
          "ichki chaqiruvlar kvotani ikki marta olmaydi (skip_quota=True)")

    # 5.2 Kvota rad etilsa — AI'ga UMUMAN chiqilmaydi (fail-closed).
    denied_db = AtomicQuotaDB(allowed=False, reason="insufficient_balance")
    denied_stub = StubOrchestrator(text=stub.text)
    denied = await AdEngine(denied_stub).generate(7, brief, "uz", db_module=denied_db)
    check(denied.success is False and denied.error_code == "QUOTA_EXCEEDED",
          f"kvota rad etildi → generatsiya yo'q ({denied.error})")
    check(not denied_stub.calls, "rad etilganda AI'ga chiqilmadi")

    # 5.3 DB xatosi — fail-closed (bron yo'q, AI yo'q).
    broken_db = AtomicQuotaDB(raise_on_reserve=True)
    broken_stub = StubOrchestrator(text=stub.text)
    broken = await AdEngine(broken_stub).generate(7, brief, "uz", db_module=broken_db)
    check(broken.success is False and broken.error_code == "QUOTA_UNAVAILABLE",
          f"DB xatosida fail-closed ({broken.error})")
    check(not broken_stub.calls, "DB xatosida ham AI'ga chiqilmadi")

    # 5.4 AI umuman ishlamasa — foydalanuvchi 4 variantni oladi, kredit qaytadi.
    refund_db = AtomicQuotaDB()
    dead = await AdEngine(StubOrchestrator(ok=False)).generate(
        7, brief, "uz", db_module=refund_db)
    check(dead.success is True and dead.count == 4,
          f"AI ishlamasa ham 4 variant (fallback) chiqdi ({dead.count})")
    check(dead.cost == 0 and dead.refund_issued is True
          and refund_db.refund_calls == [(7, 91001)],
          f"barcha variantlar fallback → bron qaytarildi: {refund_db.refund_calls}")
    check(dead.fallback_used is True, "fallback_used bayrog'i o'rnatildi")

    # 5.5 CHANNEL DNA — native formati DNA bilan bog'lanadi.
    dna = dna_profile()
    check(dna["insufficient"] is False,
          f"DNA hisoblandi (sample={dna['sample_size']}, "
          f"length={dna['profile']['average_post_length']})")
    block = build_dna_block(dna["profile"], "uz")
    check("CHANNEL DNA" in block.upper() or "DNA" in block.upper(),
          f"DNA prompt bloki qurildi: {block[:70]}")
    check(build_dna_block({}, "uz") == "" and build_dna_block(None, "uz") == "",
          "bo'sh/kam DNA uchun prompt bloki bo'sh (soxta uslub yo'q)")

    events = channel_events()
    with_dna = await AdEngine().generate(7, brief, "uz", channel_events=events)
    check(with_dna.dna_applied is True and with_dna.dna_sample_size == 12,
          f"DNA eventlardan hisoblandi va ulandi (sample={with_dna.dna_sample_size})")
    audit_dna = audit_ad(with_dna.by_format("native").content,
                         facts=list(brief.facts), product=brief.product,
                         offer=brief.offer, audience=brief.audience,
                         cta=brief.cta, link=brief.link, format="native",
                         lang="uz", dna=dna)
    dna_check = audit_dna.check("dna_fit")
    check(audit_dna.dna_applied is True and dna_check.skipped is False
          and dna_check.score >= DNA_FIT_MIN,
          f"DNA mosligi baholandi ({dna_check.score}/10)")

    # DNA'ga mos KELMAGAN reklama — ogohlantirish.
    mismatched = ("🧬 " + "Juda uzun reklama matni. " * 60 +
                  "\n\n👉 Bepul darsga yoziling")
    mismatch_audit = audit_ad(mismatched, facts=list(brief.facts),
                              product=brief.product, cta=brief.cta,
                              format="native", lang="uz", dna=dna)
    mismatch_check = mismatch_audit.check("dna_fit")
    check(mismatch_check.score < DNA_FIT_MIN,
          f"DNA'dan chetga chiqqan reklama past baholandi ({mismatch_check.score}/10)")
    check("DNA_MISMATCH" in mismatch_audit.reason_codes,
          "DNA mos kelmasligi reason_codes'ga yozildi")

    # 5.6 SANITIZER — zararli AI javobi xavfsizlantiriladi.
    hostile = ("<b>Kurs</b> <script>alert(1)</script>\n\n"
               + " ".join(brief.facts) + " & 5 < 10\n\n"
               "👉 Bepul darsga yoziling\n\n#reklama #kurs")
    hostile_result = await AdEngine(StubOrchestrator(text=hostile)).generate(7, brief, "uz")
    check(hostile_result.success and hostile_result.count == 4,
          "zararli javobda ham 4 variant chiqdi")
    check(all("<script>" not in chunk for chunk in hostile_result.chunks),
          "chunk'larda <script> tegi yo'q (escape qilingan)")
    check(all(html_length(chunk) <= TELEGRAM_TEXT_LIMIT
              for chunk in hostile_result.chunks),
          "barcha chunk'lar 4096 chegarasida")
    check(all(balanced_tags(chunk) for chunk in hostile_result.chunks),
          "chunk'larda HTML teglar muvozanatli")

    huge = ("<b>Uzun reklama</b>\n\n" + "Kurs haqida muhim ma'lumot. " * 400 +
            "\n\n👉 Bepul darsga yoziling\n\n#reklama")
    big = await AdEngine(StubOrchestrator(text=huge)).generate(7, brief, "uz")
    check(big.success and all(html_length(variant.render()) <= TELEGRAM_TEXT_LIMIT
                              for variant in big.variants),
          "juda uzun AI javobi format limitiga qisqartirildi")
    check(all(balanced_tags(variant.render()) for variant in big.variants),
          "qisqartirilgan variantlarda ham teglar muvozanatli")


# ===========================================================================
# TEST 6 — REGRESSIYA VA i18n
# ===========================================================================
async def test_regression_and_i18n():
    print("\n== TEST 6: Regressiya — eksportlar, mock rejimi, i18n paritet ==")

    # 6.1 services.ads eksportlari joyida.
    import services.ads as ads_pkg
    for name in ("AdEngine", "AdBrief", "AdAuditService", "audit_ad",
                 "evaluate_publish", "scan_unsupported_claims",
                 "strip_unsupported_claims", "AD_FORMATS", "build_ad_text"):
        check(hasattr(ads_pkg, name), f"services.ads.{name} eksport qilingan")

    # 6.2 MockProvider ADS rejimi — mavjud rejimlar buzilmagan.
    check("ADS" in smm_mock.SMM_MODES, "smm_mock ADS rejimini tanib oladi")
    payload = {"product": "Yoga kursi", "facts": ["Kichik guruhlar"],
               "offer": "Birinchi mashg'ulot bepul", "cta": "Yoziling",
               "link": "https://t.me/yoga", "lang": "uz"}
    ads_reply = smm_mock.smm_mock_reply(
        {"smm_mode": "ADS", "smm_ads_format": "short", "smm_ads_brief": payload},
        "Yoga kursi")
    check(bool(ads_reply) and "Yoga kursi" in ads_reply,
          "ADS rejimi brief'dagi mahsulot bilan javob berdi")
    check(scan_unsupported_claims(ads_reply, " ".join(
        [payload["product"], *payload["facts"], payload["offer"], payload["cta"]]),
        "uz") == [],
        "ADS mock javobida asossiz da'vo yo'q")
    check(bool(smm_mock.smm_mock_reply({"smm_mode": "VARIANTS",
                                        "smm_variant_style": "viral",
                                        "smm_topic": "Mavzu"})),
          "mavjud VARIANTS rejimi buzilmagan")
    check(bool(smm_mock.smm_mock_reply({"smm_mode": "AUDIT", "smm_topic": "Mavzu"})),
          "mavjud AUDIT rejimi buzilmagan")
    check(smm_mock.smm_mock_reply({"smm_mode": "YO'Q"}) is None,
          "noma'lum rejimda mock javob bermaydi (eski xatti-harakat)")

    # 6.3 i18n paritet — uz/ru/en.
    for fmt in AD_FORMATS:
        for lang in ("uz", "ru", "en"):
            check(bool(fmt.t_label(lang)) and bool(fmt.t_angle(lang))
                  and bool(fmt.t_instruction(lang)),
                  f"{fmt.key}/{lang}: label+angle+instruction to'ldirilgan")
    for criterion in AD_AUDIT_CRITERIA:
        for lang in ("uz", "ru", "en"):
            check(bool(criterion.t_label(lang)) and bool(criterion.t_problem(lang))
                  and bool(criterion.t_fix(lang)),
                  f"audit:{criterion.key}/{lang}: label+problem+fix to'ldirilgan")
    for lang in ("uz", "ru", "en"):
        text = build_ad_text("soft", "Kurs", ["Fakt biri"], offer="Bepul dars",
                             cta="Yozing", lang=lang)
        check(len(strip_html(text)) > 50, f"fallback/{lang}: matn yaratildi")

    # 6.4 Prompt barcha tillarda NO FABRICATION qoidalarini saqlaydi.
    brief = AdBrief.build(**BRIEF_KWARGS)
    for lang, marker in (("uz", "TAQIQLANADI"), ("ru", "ЗАПРЕЩ"), ("en", "FORBIDDEN")):
        prompt = build_ad_prompt(brief, resolve_format("native"), lang)
        check(marker in prompt, f"{lang}: prompt'da taqiq bloki bor")
        check(brief.product in prompt, f"{lang}: prompt'da mahsulot nomi bor")

    # 6.5 Kvota operatsiyasi oq ro'yxatda (database.AI_OPERATION_TYPES).
    try:
        import database as db_module
        allowed_ops = getattr(db_module, "AI_OPERATION_TYPES", ())
        base_op = AdEngine.quota_operation.split(":", 1)[0]
        check(base_op in allowed_ops,
              f"kvota operatsiyasi '{AdEngine.quota_operation}' oq ro'yxatda")
    except Exception as exc:  # noqa: BLE001
        check(False, "database import qilinib, kvota oq ro'yxati tekshirildi", str(exc))
    check(AdEngine.quota_cost == 1, "butun batch uchun narx 1 kredit")

    # 6.6 Runner va syntax-test ro'yxatdan o'tgan.
    runner = (ROOT / "tests" / "run_tests.sh").read_text(encoding="utf-8")
    check("advertisement_engine_and_audit_test.py" in runner,
          "tests/run_tests.sh yangi test qamrovini chaqiradi")
    syntax = (ROOT / "telegram_bot" / "tests" / "syntax_test.py").read_text(
        encoding="utf-8")
    check("services.ads" in syntax,
          "syntax_test services.ads modullarini import tekshiruvidan o'tkazadi")

    # 6.7 Mavjud SMM xizmatlari buzilmagan (regressiya).
    from services.ai import VARIANT_STYLE_KEYS, AUDIT_CRITERION_KEYS
    check(len(VARIANT_STYLE_KEYS) == 5 and len(AUDIT_CRITERION_KEYS) == 6,
          "mavjud variants (5) va post audit (6 mezon) o'zgarmagan")
    from services.channels.dna import MIN_POSTS_FOR_DNA
    check(MIN_POSTS_FOR_DNA == 5, "Channel DNA minimal post talabi o'zgarmagan (5)")


# ===========================================================================
# RUNNER
# ===========================================================================
async def main_async():
    print("=" * 68)
    print(" 📢 FAZA 15 & 16 — REKLAMA DVIGATELI VA REKLAMA AUDITI")
    print("=" * 68)

    print("\n== 0. Muhit (API kalitsiz, MockProvider) ==")
    saved = {key: os.environ.get(key) for key in
             ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")}
    for key in saved:
        os.environ.pop(key, None)
    check(not any(os.environ.get(key) for key in saved),
          "test muhitida AI kalitlari o'chirilgan")

    await test_four_ad_formats()
    print()
    await test_no_fabrication()
    print()
    await test_ad_audit()
    print()
    await test_publish_gate()
    print()
    await test_infrastructure_reuse()
    print()
    await test_regression_and_i18n()

    print("\n" + "=" * 68)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] REKLAMA DVIGATELI/AUDIT TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" 📢 REKLAMA DVIGATELI VA AUDITI — TESTLAR 100% YASHIL ✔")
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
