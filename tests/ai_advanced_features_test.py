#!/usr/bin/env python3
"""🚀 PHASE 11 & 12 — AI ADVANCED SMM FEATURES (33, 48, 49, 50, 51-bandlar).

Tekshiriladigan kontraktlar:

  TEST 1 (48-band) — Multi-variant generator:
      bitta mavzudan AYNAN 5 ta variant; har biri o'z uslubida (🔥 viral,
      💎 premium, 💰 sales, 📚 informative, 🤳 blogger); variantlar bir-birining
      SINONIMI EMAS (fingerprint + Jaccard); har birida hook/CTA/hashtag bor.

  TEST 2 (49-band) — Repurpose: 5 platforma formati (Telegram Post | Instagram
      Caption | Stories ssenariy | Reels/Shorts hook-ssenariy | Reklama matni)
      QAT'İY struktura bilan: IG ≤2200 va 5-10 hashtag, Stories 3-5 slayd
      (≤120 belgi), Reels 0-3s hook + tayminglar, Ads Meta maydonlari
      (headline ≤40, primary ≤125, description ≤30, CTA ≤20).

  TEST 3 (33/50-band) — Deep audit: 6 mezon (Hook, Clarity, Value, Structure,
      CTA, Engagement) 1-10 ball, umumiy 0-100 score + baho, kuchli tomonlar,
      Top 3 yaxshilanish va YAXSHILANGAN yakuniy namuna post. Ballar
      deterministik — model ballni o'zgartira olmaydi; kuchsiz post kuchli
      postdan past baholanadi.

  TEST 4 (51-band) — Kontent reja: 1/7/14/30 kun; har bir kunda Mavzu, Format,
      Hook, Maqsad va CTA; kunlar ketma-ket va sanalar o'sib boradi; 14/30 kun
      FAQAT PRO; noto'g'ri davomiylik rad etiladi.

  TEST 5 — MOCK REJIM: API kalitsiz muhitda (GEMINI/GROQ/OPENROUTER o'chirilgan)
      to'rt xizmat ham 100% muvaffaqiyatli ishlaydi, provider = Mock.

  TEST 6 — INTEGRATSIYA: Phase 3 AIOrchestrator/ProviderChain; Phase 2 atomik
      kvota (butun batch uchun BITTA reserve_ai_request, ichki chaqiruvlar
      skip_quota), rad etilganda AI'ga CHIQMAYDI, AI yiqilsa bron refund
      qilinadi; Phase 2 sanitize_html — hech qanday chiqishda xavfli teg
      qolmaydi va Telegram 4096 chegarasi buzilmaydi.

  TEST 7 — REGRESSIYA QO'RIQONLARI: avvalgi fazalar buzilmagan — services.ai
      eksportlari, Intent Router, MockProvider'ning eski javoblari, sanitizer
      limiti va database AI_OPERATION_TYPES (yangi oqim asoslari) o'rnida turibdi.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh      # 3u bosqichi
    $HOME/venv/bin/python tests/ai_advanced_features_test.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import warnings
from datetime import timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — import'dan OLDIN (config BOT_TOKEN/DATABASE_URL talab qiladi).
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:AI_ADVANCED_SMM_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10011")
# P0-A: bu to'plam API kalitlarisiz, MockProvider bilan OFFLINE ishlaydi —
# test muhitini e'lon qilamiz (production'da Mock zanjirdan chiqariladi).
os.environ.setdefault("ENVIRONMENT", "test")
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Poydevor
# ---------------------------------------------------------------------------
from services.ai import (  # noqa: E402
    AIOrchestrator,
    AUDIT_CRITERIA,
    AUDIT_CRITERION_KEYS,
    MockProvider,
    PLAN_DURATIONS,
    ProviderChain,
    REPURPOSE_PLATFORM_KEYS,
    VARIANT_STYLE_KEYS,
)
from services.ai.audit import (  # noqa: E402
    CRITERION_MAX,
    OVERALL_MAX,
    PostAuditService,
    grade_for,
    overall_from_criteria,
    score_post_heuristics,
)
from services.ai.planner import (  # noqa: E402
    AI_BATCH_DAYS,
    ContentPlanService,
    FREE_MAX_DAYS,
    normalize_days,
    parse_plan_json,
    plan_entitlement,
    resolve_start_date,
)
from services.ai.repurpose import (  # noqa: E402
    AD_DESCRIPTION_LIMIT,
    AD_HEADLINE_LIMIT,
    AD_PRIMARY_LIMIT,
    INSTAGRAM_CAPTION_LIMIT,
    STORIES_SLIDE_LIMIT,
    ContentRepurposeService,
    build_digest,
)
from services.ai.smm_common import (  # noqa: E402
    TELEGRAM_TEXT_LIMIT,
    chunk_blocks,
    fingerprint,
    get_default_orchestrator,
    html_length,
    sanitize_html,
    set_default_orchestrator,
    same_content,
    strip_html,
)
from services.ai.variants import (  # noqa: E402
    VARIANT_COUNT,
    MultiVariantGenerator,
    build_variant_prompt,
    resolve_style,
)

PASSED = 0
FAILURES = 0


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


def balanced_tags(text):
    """Telegram HTML parse muvaffaqiyati uchun teglar muvozanati tekshiruvi."""
    for tag in ("b", "i", "u", "s", "code", "pre", "blockquote", "a", "tg-spoiler"):
        opened = len(re.findall(rf"<{tag}(?:\s[^>]*)?>", text))
        closed = len(re.findall(rf"</{tag}>", text))
        if opened != closed:
            return False
    return True


def mock_orchestrator():
    """Faqat MockProvider'li orchestrator — to'liq deterministik, tarmoqsiz."""
    return AIOrchestrator(provider_chain=ProviderChain(providers=[MockProvider()]))


STRONG_POST = """🔥 Nega mijozlaringiz 30% ga kamaymoqda?

Yangi servis paketimiz — 7 kun ichida birinchi natija.

📌 Nima olasiz?
• Kuniga 20 daqiqa vaqt tejash
• 3 ta kanal boshqaruvi bir panelden
• 100% kafolat: natija bo'lmasa — qaytamiz

💬 Sizning holat qanday? Izohga yozing.
👉 Hoziroq yozing: t.me/postassist (faqat shu hafta)

#smm #servis #chegirma"""

WEAK_POST = ("Salom. Bizda krossovka bor. Arzon. Kelib oling. "
             "Lekin nega kelish kerakligi, qachon ochilishi, narxi qanchaligi, "
             "qaysi o'lchamlar borligi va manzil qayerda ekanligi umuman "
             "yozilmagan, shuning uchun butun matnni qayta o'qib chiqsangiz "
             "ham hech qanday aniq javob topa olmaysiz, chunki muallif barcha "
             "muhim ma'lumotlarni chetlab o'tgan va faqat umumiy iboralar "
             "bilan cheklangan holda postni yakunlagan.")

SOURCE_CONTENT = """Konteiner suv yetkazib berish — yangi bosqich.

📌 Shartlar:
• 19 litr idish, depozit yo'q
• Kuniga 2 marta yetkazish
• To'lov — keyinroq, hisob-faktura bilan

👉 Buyurtma: +998 90 000 00 00
#suv #yetkazish #biznes"""


# ===========================================================================
# TEST 1 — MULTI-VARIANT GENERATOR (48-band)
# ===========================================================================
async def test_multi_variant_generator():
    print("== 1) ✨ MULTI-VARIANT GENERATOR (48-band) ==")
    result = await MultiVariantGenerator(orchestrator=mock_orchestrator()).generate(
        None, "Yangi krossovka kolleksiyasi", "uz")

    check(result.success is True, f"generatsiya muvaffaqiyatli (error={result.error})")
    check(result.count == 5, f"AYNAN 5 ta variant yaratildi (topildi: {result.count})")
    check(result.styles() == list(VARIANT_STYLE_KEYS),
          f"variantlar tartib va to'plami: {result.styles()}")
    check(VARIANT_STYLE_KEYS == ("viral", "premium", "sales", "informative", "blogger")
          and VARIANT_COUNT == 5,
          "5 uslub kaliti qat'iy belgilangan (viral/premium/sales/informative/blogger)")

    styles = {variant.style for variant in result.variants}
    check(len(styles) == 5, f"har bir variant o'z uslubida (noyob: {len(styles)})")
    check(all(variant.content and variant.chars >= 120 for variant in result.variants),
          "har bir variantda yetarli hajmdagi post matni bor")

    # 🚫 Sinonim bo'lmasligi SHART.
    distinct_pairs = 0
    total_pairs = 0
    for i, left in enumerate(result.variants):
        for right in result.variants[i + 1:]:
            total_pairs += 1
            if (fingerprint(left.content) != fingerprint(right.content)
                    and not same_content(left.content, right.content, threshold=0.85)):
                distinct_pairs += 1
    check(distinct_pairs == total_pairs == 10,
          f"barcha 10 juftlik mazmunan FARQ QILADI ({distinct_pairs}/{total_pairs})")

    for variant in result.variants:
        if variant.style == "viral":
            check("?" in strip_html(variant.content) or "?" in variant.content,
                  "🔥 viral variantda munozarali savol bor")
        if variant.style == "sales":
            check("🛒" in variant.content or "buyurtma" in variant.content.lower(),
                  "💰 sales variantda sotuv CTA bor")
        if variant.style == "informative":
            check("1." in variant.content or "•" in variant.content or "✅" in variant.content,
                  "📚 informative variantda tuzilmali punktlar bor")
        if variant.style == "premium":
            check("chegirma" not in variant.content.lower()
                  and "aksiya" not in variant.content.lower(),
                  "💎 premium variantda chegirma/aksiya toni yo'q")
        if variant.style == "blogger":
            check("men" in variant.content.lower() or "🤳" in variant.content,
                  "🤳 blogger variantda shaxsiy tajribaga oid birinchi shaxs bor")

    check(all(len(variant.hashtags) >= 3 for variant in result.variants),
          "har bir variantda kamida 3 ta hashtag")
    check(all("<script>" not in variant.content for variant in result.variants),
          "hech bir variantda xavfli teg yo'q (sanitizer)")

    labels = [variant.label for variant in result.variants]
    check(all(label for label in labels), "har bir variantda UI ko'rinadigan uslub nomi bor")
    prompt = build_variant_prompt("Test mavzu", resolve_style("viral"), "uz")
    check("5 variants" in prompt and "viral" in prompt.lower(),
          "prompt uslubni va 'variant' niyatini aniq belgilaydi")
    check(len(result.chunks) >= 1 and all(html_length(c) <= TELEGRAM_TEXT_LIMIT
                                          for c in result.chunks),
          f"variantlar Telegram xabarlariga sig'adi (chunks={len(result.chunks)})")
    return result


# ===========================================================================
# TEST 2 — REPURPOSE (49-band)
# ===========================================================================
async def test_repurpose_formats():
    print("== 2) 🔄 CONTENT REPURPOSE (49-band) ==")
    result = await ContentRepurposeService(orchestrator=mock_orchestrator()).repurpose(
        None, SOURCE_CONTENT, "uz")

    check(result.success is True, f"repurpose muvaffaqiyatli (error={result.error})")
    check(result.platforms() == list(REPURPOSE_PLATFORM_KEYS),
          f"5 platforma formati shu tartibda: {result.platforms()}")

    telegram = result.by_platform("telegram")
    instagram = result.by_platform("instagram")
    stories = result.by_platform("stories")
    reels = result.by_platform("reels")
    ads = result.by_platform("ads")
    check(all(x is not None for x in (telegram, instagram, stories, reels, ads)),
          "har bir platforma uchun alohida natija qaytdi")

    # 2.1 Telegram Post
    check(telegram is not None and "<b>" in telegram.content
          and "Konteiner suv yetkazib berish" in telegram.content,
          "📢 Telegram: qalin hook + mavzu saqlangan")
    check(telegram is not None and telegram.content.count("✅") >= 2,
          f"📢 Telegram: punktli struktura (✅ x {telegram.content.count('✅') if telegram else 0})")
    check(telegram is not None and telegram.meta.get("hashtags", 0) >= 3,
          "📢 Telegram: 3+ hashtag")
    check(telegram is not None and telegram.chars <= TELEGRAM_TEXT_LIMIT,
          f"📢 Telegram: {telegram.chars if telegram else 0} belgi (limit {TELEGRAM_TEXT_LIMIT})")

    # 2.2 Instagram Caption
    check(instagram is not None
          and instagram.meta["caption_chars"] <= INSTAGRAM_CAPTION_LIMIT,
          f"📸 Instagram: caption ≤ {INSTAGRAM_CAPTION_LIMIT} "
          f"(topildi {instagram.meta['caption_chars'] if instagram else 0})")
    check(instagram is not None and 5 <= instagram.meta["hashtag_count"] <= 10,
          f"📸 Instagram: 5-10 hashtag bloki (topildi {instagram.meta['hashtag_count'] if instagram else 0})")
    check(instagram is not None and instagram.content.split("\n\n")[0]
          == instagram.meta["hook_first_line"],
          "📸 Instagram: birinchi qator — hook")
    check(instagram is not None and instagram.meta.get("link_in_bio") is True,
          "📸 Instagram: 'havola bio'da' konvensiyasi qayd etilgan")

    # 2.3 Stories
    slides = stories.blocks if stories else []
    check(3 <= len(slides) <= 5, f"🖼 Stories: 3-5 slayd (topildi {len(slides)})")
    check(all(len(strip_html(str(slide.get('text', '')))) <= STORIES_SLIDE_LIMIT
              for slide in slides),
          f"🖼 Stories: har bir slayd ≤ {STORIES_SLIDE_LIMIT} belgi")
    check(all(slide.get("role") and slide.get("sticker") for slide in slides),
          "🖼 Stories: har bir slaydda rol (muammo→dalil→yechim→CTA) va stiker ko'rsatmasi")
    check([slide.get("index") for slide in slides] == list(range(1, len(slides) + 1)),
          "🖼 Stories: slaydlar raqamlangan")

    # 2.4 Reels / Shorts
    scenes = reels.blocks if reels else []
    check(reels is not None and len(reels.meta.get("hook", "")) >= 8,
          "🎬 Reels: 0-3s uchun alohida hook yozilgan")
    timings_ok = bool(scenes) and len(scenes) >= 4 and all(
        re.match(r"^\d+-\d+s$", str(scene.get("time", ""))) for scene in scenes)
    check(timings_ok,
          "🎬 Reels: har bir sahnada tayming "
          f"({', '.join(str(s.get('time')) for s in scenes[:5])})")
    check(reels is not None and scenes and scenes[0]["time"] == "0-3s",
          "🎬 Reels: sahna ro'yxati 0-3s hook bilan boshlanadi")
    check(reels is not None and all(scene.get("overlay") for scene in scenes),
          "🎬 Reels: har bir sahna uchun overlay (ekrandagi yozuv) bor")

    # 2.5 Reklama
    meta = ads.meta if ads else {}
    check(len(meta.get("headline", "")) <= AD_HEADLINE_LIMIT,
          f"📣 Ads: headline ≤ {AD_HEADLINE_LIMIT} (topildi {len(meta.get('headline', ''))})")
    check(0 < len(meta.get("primary_text", "")) <= AD_PRIMARY_LIMIT,
          f"📣 Ads: primary text ≤ {AD_PRIMARY_LIMIT} (topildi {len(meta.get('primary_text', ''))})")
    check(0 < len(meta.get("description", "")) <= AD_DESCRIPTION_LIMIT,
          f"📣 Ads: description ≤ {AD_DESCRIPTION_LIMIT}")
    check(0 < len(meta.get("cta_button", "")) <= 20,
          "📣 Ads: bitta CTA tugma matni (≤20 belgi)")

    check(all("<script>" not in item.content for item in result.outputs),
          "barcha platforma natijalari sanitizerdan o'tgan")
    check(all(html_length(chunk) <= TELEGRAM_TEXT_LIMIT for chunk in result.chunks),
          f"repurpose xabarlari Telegram limitida (chunks={len(result.chunks)})")
    digest = build_digest(SOURCE_CONTENT, "uz")
    check(digest.headline and digest.bullets and digest.has_cta and digest.links,
          "manba matn digesti to'g'ri ajratildi (headline/punktlar/CTA/havola)")
    return result


# ===========================================================================
# TEST 3 — DEEP AUDIT (33/50-band)
# ===========================================================================
async def test_post_audit():
    print("== 3) 🔍 KENGAYTIRILGAN POST AUDIT (33/50-band) ==")
    service = PostAuditService(orchestrator=mock_orchestrator())
    strong = await service.audit_post(None, STRONG_POST, "uz")
    weak = await service.audit_post(None, WEAK_POST, "uz")

    check(strong.success is True and weak.success is True, "audit ikkala postda ham yiqilmadi")
    check(tuple(item.key for item in AUDIT_CRITERIA) == AUDIT_CRITERION_KEYS
          and AUDIT_CRITERION_KEYS == ("hook", "clarity", "value", "structure", "cta", "engagement"),
          f"6 ta mezon: {', '.join(AUDIT_CRITERION_KEYS)}")
    check(set(strong.criteria.keys()) == set(AUDIT_CRITERION_KEYS),
          "hisobotda 6 ta mezonning barchasi bor")
    check(all(1 <= item.score <= CRITERION_MAX for item in strong.criteria.values()),
          f"har bir mezon 1-{CRITERION_MAX} oralig'ida")
    check(sum(item.weight for item in AUDIT_CRITERIA) == OVERALL_MAX,
          "mezon og'irliklari yig'indisi 100 ga teng")
    check(0 <= strong.overall_score <= OVERALL_MAX and 0 <= weak.overall_score <= OVERALL_MAX,
          f"umumiy score 0-{OVERALL_MAX} oralig'ida "
          f"(kuchli: {strong.overall_score}, kuchsiz: {weak.overall_score})")
    check(strong.overall_score > weak.overall_score,
          "yaxshi post kuchsiz postdan YUQORI baholandi (mantiqiy tartib)")
    check(strong.overall_score == overall_from_criteria(strong.scores),
          "umumiy score mezon ballaridan qayta hisoblanadi (kalkulyatsiya ochiq)")
    check(strong.grade == grade_for(strong.overall_score), f"baho darajasi mos: {strong.grade}")
    check(f"{strong.overall_score}/{OVERALL_MAX}" in strong.report,
          "hisobotda '88/100' tipidagi umumiy ball ko'rsatilgan")

    check(len(strong.strengths) >= 1, "kuchli tomonlar ro'yxati bo'sh emas")
    check(len(strong.improvements) == 3, f"Top 3 yaxshilanish (topildi: {len(strong.improvements)})")
    check([tip.rank for tip in strong.improvements] == [1, 2, 3],
          "yaxshilanishlar 1-2-3 tartibida raqamlangan")
    check(all(tip.criterion in AUDIT_CRITERION_KEYS and len(tip.fix) >= 12 for tip in strong.improvements),
          "har bir yaxshilanish aniq bir mezonga bog'langan va amaliy tuzatish beradi")
    check(all(tip.gain >= 0 for tip in strong.improvements),
          "har bir tavsiyada kutilayotgan ball o'sishi ko'rsatilgan")

    check(strong.improved_post and len(strip_html(strong.improved_post)) >= 120,
          "yaxshilangan yakuniy namuna post mavjud va to'liq")
    check(strong.improved_post != strip_html(STRONG_POST),
          "yaxshilangan namuna asl matndan farq qiladi")
    check("#" in strong.improved_post, "yaxshilangan namunada hashtaglar saqlangan")

    # Ballar — deterministik; model aralashuviga yopiq.
    scores_a, _ = score_post_heuristics(STRONG_POST, "uz")
    scores_b, _ = score_post_heuristics(STRONG_POST, "uz")
    check(scores_a == scores_b, "lokal hisoblagich deterministik (ikki marta bir xil)")
    optimistic = {
        "criteria": {key: 10 for key in AUDIT_CRITERION_KEYS},
        "verdict": "Ajoyib",
        "strengths": ["Zo'r"],
        "improvements": [],
        "improved_post": "AI posti",
    }
    check(overall_from_criteria(optimistic["criteria"]) == OVERALL_MAX,
          "hisoblagich formulasi to'g'ri (10 ball → 100)")
    check(all(strong.criteria[key].score == scores_a[key] for key in AUDIT_CRITERION_KEYS),
          "AI javobi KELIB-KETSA HAM ballar o'zgarmaydi (manipulyatsiyaga yopiq)")

    # 🛡 Xavfsizlik va chegaralar
    hostile = await service.audit_post(
        None, "<script>alert(1)</script> " + STRONG_POST + " <iframe src=x></iframe>", "uz")
    check(hostile.success is True and "<script>" not in hostile.report
          and "<iframe" not in hostile.report,
          "zararli teglar hisobotga o'tmaydi (escape/filtr)")
    check(all(html_length(chunk) <= TELEGRAM_TEXT_LIMIT for chunk in hostile.chunks),
          f"zararli kiritishda ham chunk'lar limitda (chunks={len(hostile.chunks)})")
    empty = await service.audit_post(None, "   ", "uz")
    check(empty.success is False and empty.error_code == "INVALID_INPUT",
          "bo'sh matnda audit xavfsiz rad etadi (INVALID_INPUT, istisno yo'q)")
    for lang in ("uz", "ru", "en"):
        local = await service.audit_post(None, STRONG_POST, lang, use_ai=False)
        check(local.success is True and len(local.report) > 400 and local.ai_merged is False,
              f"{lang.upper()}: AI'siz ham to'liq hisobot (bepul/rezerv) — {local.overall_score}/{OVERALL_MAX}")
    check(strong.metrics.get("words", 0) > 0 and "first_line_chars" in strong.metrics,
          "o'lchanadigan metrikalar ham hisobotda (shaffoflik)")
    return strong, weak


# ===========================================================================
# TEST 4 — CONTENT PLAN (51-band)
# ===========================================================================
async def test_content_plan():
    print("== 4) 🗓 KONTENT REJA GENERATORI (51-band) ==")
    service = ContentPlanService(orchestrator=mock_orchestrator())
    plans = {}
    for days in PLAN_DURATIONS:
        result = await service.generate_plan(None, "Ayollar kiyimi do'koni", days, "uz",
                                             start_date="2026-09-16", is_pro=True)
        plans[days] = result
        check(result.success is True and len(result.items) == days,
              f"{days} kunlik reja: AYNAN {days} ta kun (topildi {len(result.items)})")

    check(PLAN_DURATIONS == (1, 7, 14, 30), "qo'llab-quvvatlanadigan davomiyliklar 1/7/14/30")
    seven = plans[7]
    required = ("day", "date", "weekday", "format", "topic", "hook", "goal", "cta")
    sample = seven.items[0].as_dict()
    check(all(sample.get(key) not in (None, "") for key in required),
          f"har bir kunda Mavzu/Format/Hook/Maqsad/CTA bor: {sorted(sample)}")
    check([item.day for item in seven.items] == list(range(1, 8)),
          "kunlar 1..7 ketma-ket va to'liq")
    check(all(len({item.format for item in plans[key].items}) >= 5 for key in (7, 14, 30)),
          "hafta ichida kamida 5 xil format rotatsiyasi (bir xil kontent emas)")
    check(len({item.cta for item in plans[30].items}) >= 3,
          "30 kunlik rejada CTA'lar xilma-xil")

    start = resolve_start_date("2026-09-16")
    dates = [resolve_start_date(item.date) for item in seven.items]
    check(dates == [start + timedelta(days=n) for n in range(len(dates))],
          "sanalar ketma-ket kunlarga to'g'ri bog'langan")
    check(all(b > a for a, b in zip(dates, dates[1:])), "sanalar qat'iy o'sib boradi")
    check(seven.weeks and seven.weeks[0]["days"] == [1, 2, 3, 4, 5, 6, 7],
          "1-hafta bloki 7 kundan tuzilgan")
    check(len(plans[30].weeks) == 5, f"30 kunlik reja 5 haftaga bo'lindi: {len(plans[30].weeks)}")

    # 🎯 Entitlement siyosati
    check(plan_entitlement(7, False) == (True, "ok"), "FREE: 7 kunlik reja ruxsat etilgan")
    check(plan_entitlement(1, False) == (True, "ok"), "FREE: 1 kunlik reja ruxsat etilgan")
    check(plan_entitlement(14, False) == (False, "pro_required"), "FREE: 14 kun → pro_required")
    check(plan_entitlement(30, False) == (False, "pro_required"), "FREE: 30 kun → pro_required")
    check(plan_entitlement(30, True) == (True, "ok"), "PRO: 30 kunlik reja ochiq")
    check(plan_entitlement(5, True) == (False, "invalid_duration"),
          "ruxsat etilmagan davomiylik (5 kun) rad etiladi")
    blocked = await service.generate_plan(None, "Do'kon", 30, "uz", is_pro=False)
    check(blocked.success is False and blocked.error_code == "PRO_REQUIRED"
          and blocked.entitlement == "pro_required",
          "FREE foydalanuvchi 30 kunlik rejani OLMAAYDI (oqim yiqilmaydi)")
    invalid = await service.generate_plan(None, "Do'kon", 11, "uz", is_pro=True)
    check(invalid.success is False and invalid.error_code == "INVALID_DURATION",
          "noto'g'ri davomiylik xavfsiz rad etiladi")
    empty = await service.generate_plan(None, "", 7, "uz", is_pro=True)
    check(empty.success is False and empty.error_code == "INVALID_INPUT",
          "bo'sh yo'nalish (topic) rad etiladi")

    check(normalize_days("30 kun") == 30 and normalize_days("14") == 14
          and normalize_days(" ") == 0 and normalize_days("5") == 5,
          "davomiylikni normalallashtirish (matn/kirill-lotin aralash) ishyarli")
    check(FREE_MAX_DAYS == 7 and AI_BATCH_DAYS == 7,
          "FREE maksimal 7 kun va AI batch'i 7 kun (4096 limitiga urilmaydi)")

    # AI reja maydonlarini qo'shadi, lekin kunlar sonini o'zgartira olmaydi
    parsed = parse_plan_json({"plan": [{"day": 2, "topic": "Yangi burchak", "hook": "E'tibor: yangi"}]
                              + [{"day": n, "topic": f"Qoshimcha kun mavzusi {n}"}
                                 for n in range(1, 40)]}, 7, 1)
    check(len(parsed) <= 7 and 2 in parsed and parsed[2]["topic"] == "Yangi burchak",
          f"AI javobi kunlar soni bilan cheklanadi ({len(parsed)} yaroqli yozuv)")
    check(7 in parsed and 8 not in parsed and parsed[7]["topic"].endswith("7"),
          "AI berib yuborgan ortiqcha kunlar (8..39) kesiladi")
    check(parse_plan_json({"plan": ["not-a-dict", None, {"day": "x"}]}, 7, 1) is not None,
          "buzuq JSON yozuvlarida ham istisno ko'tarilmaydi")

    merged = plans[7].items[0].as_dict()
    check(plans[7].ai_merged is True and len(merged["topic"]) >= 5,
          f"MockProvider rejası AI maydonlarini birlashtirdi: {merged['topic'][:60]}")
    for days in PLAN_DURATIONS:
        result = plans[days]
        bad = [chunk for chunk in result.chunks if html_length(chunk) > TELEGRAM_TEXT_LIMIT]
        check(not bad, f"{days} kunlik reja Telegram chegarasida "
                       f"(chunks={len(result.chunks)}, max_visible={max(html_length(c) for c in result.chunks)})")
    check(all("<script>" not in chunk for chunk in plans[30].chunks),
          "30 kunlik rejada ham zararli teg yo'q")
    return plans


# ===========================================================================
# TEST 5 — MOCK REJIM: API KAL'ITSIZ 100% YASHIL
# ===========================================================================
async def test_mock_mode_without_api_keys():
    print("== 5) 🧪 MOCK REJIM — API kal'itsiz to'liq ishlash ==")
    saved = {key: os.environ.pop(key, None)
             for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY",
                         "OPENROUTER_API_KEY", "AI_MOCK", "AI_OFFLINE")}
    set_default_orchestrator(None)  # global singleton'ni qayta quramiz
    try:
        from services.ai.orchestrator import AIOrchestrator as DefaultOrch
        default = DefaultOrch()
        for name, provider in (("Gemini", default.provider_chain.providers[0]),
                               ("Groq", default.provider_chain.providers[1]),
                               ("OpenRouter", default.provider_chain.providers[2])):
            check(provider.is_available() is False, f"{name} provayderi kal'itsiz — mavjud emas")
        check(default.provider_chain.providers[-1].is_available() is True,
              "MockProvider doim mavjud (oxirgi zaxira)")

        variants = await MultiVariantGenerator(default).generate(None, "Onlayn masa", "uz")
        repurpose = await ContentRepurposeService(default).repurpose(None, SOURCE_CONTENT, "ru")
        audit = await PostAuditService(default).audit_post(None, STRONG_POST, "en")
        plan = await ContentPlanService(default).generate_plan(None, "Onlayn masa", 14, "uz",
                                                                is_pro=True, start_date="2026-09-16")
        check(variants.success and variants.count == 5 and variants.provider_used == "Mock",
              f"variants mock rejimida: {variants.count} ta, provider={variants.provider_used}")
        check(repurpose.success and len(repurpose.outputs) == 5 and repurpose.provider_used == "Mock",
              f"repurpose mock rejimida: {len(repurpose.outputs)} platforma")
        check(audit.success and audit.overall_score > 0 and audit.provider_used == "Mock",
              f"audit mock rejimida: score={audit.overall_score}/{OVERALL_MAX}")
        check(plan.success and len(plan.items) == 14,
              f"planner mock rejimida: {len(plan.items)} kun")
        check(all(x.success for x in (variants, repurpose, audit, plan)),
              "API kal'itsiz TO'RT xizmat ham yiqilmadi (100% green)")

        determinism_a = await MultiVariantGenerator(mock_orchestrator()).generate(
            None, "Onlayn masa", "uz")
        determinism_b = await MultiVariantGenerator(mock_orchestrator()).generate(
            None, "Onlayn masa", "uz")
        check([strip_html(v.content) for v in determinism_a.variants]
              == [strip_html(v.content) for v in determinism_b.variants],
              "MockProvider javoblari deterministik (qayta chaqirishda bir xil)")
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
        set_default_orchestrator(None)


# ===========================================================================
# TEST 6 — ORKESTRATSIYA / KVOTA / SANITIZER INTEGRATSIYASI
# ===========================================================================
class StubResult:
    """AIOrchestrationResult'ning yengil substituti."""

    def __init__(self, success, content="", provider="Stub", error=None, error_code=None,
                 intent="CREATE_POST"):
        self.success = success
        self.content = content
        self.raw_content = content
        self.provider_used = provider
        self.retried = False
        self.cost = 1
        self.reservation_id = None
        self.error = error
        self.error_code = error_code
        self.generation_id = "gen_stub"
        self.intent = intent


class StubOrchestrator:
    """Orchestrator o'rniga — chaqiruvlarni sanaydi va natijani boshqaradi."""

    def __init__(self, ok=True, text=None, error_code=None):
        self.ok = ok
        self.text = text if text is not None else (
            "🔥 <b>AI natijasi</b>\n\nBu test uchun AI yozgan to'liq matn.\n"
            "✅ Aniq foyda\n\n👉 Yozing\n\n#ai #test #smm")
        self.error_code = error_code
        self.calls = []

    async def orchestrate(self, user_id, prompt, lang="uz", context=None, db_module=None):
        self.calls.append({"prompt": prompt, "context": dict(context or {}),
                           "db_module": db_module, "user_id": user_id})
        if not self.ok:
            return StubResult(False, "", provider="none", error="provider down",
                              error_code=self.error_code or "ORCHESTRATION_FAILED")
        return StubResult(True, self.text, provider="Mock")


class AtomicQuotaDB:
    """``run_db.__module__ == 'database'`` → services.ai_quota ATOMIK yo'lni tanlaydi.

    Shu orqali tekshiriladi: xizmatlar Phase 2 ``database.reserve_ai_request`` /
    ``refund_ai_request`` kontraktidan foydalanadyimi (eski 2 qadamli
    ``check_ai_limit`` + ``use_user_credit`` EMAS).
    """

    def __init__(self, allowed=True, reason="ok", raise_on_reserve=False):
        self.allowed = allowed
        self.reason = reason
        self.raise_on_reserve = raise_on_reserve
        self.reserve_calls = []
        self.refund_calls = []
        self.legacy_calls = []

        async def run_db(func, *args, **kwargs):
            if getattr(func, "__name__", "") == "check_ai_limit":
                self.legacy_calls.append("check_ai_limit")
            return func(*args, **kwargs)

        self.run_db = run_db
        # services.ai_quota._is_real_db_adapter shu belgiga qaraydi.
        self.run_db.__module__ = "database"

    def reserve_ai_request(self, user_id, operation_type, cost):
        self.reserve_calls.append((int(user_id), str(operation_type), int(cost)))
        if self.raise_on_reserve:
            raise RuntimeError("database unavailable")
        if not self.allowed:
            return {"allowed": False, "reason": self.reason, "reservation_id": None,
                    "source": None, "cost": 0, "used": 5, "max_ai": 5,
                    "credits_left": 0, "legacy": False}
        return {"allowed": True, "reason": "ok", "reservation_id": 90001,
                "source": "credit", "cost": int(cost), "used": 2, "max_ai": 10,
                "credits_left": 3, "legacy": False}

    def refund_ai_request(self, user_id, reservation_id):
        self.refund_calls.append((int(user_id), reservation_id))
        return {"success": True, "reason": "refunded", "reservation_id": reservation_id,
                "source": "credit"}

    def is_premium(self, user_id):
        return True


async def test_orchestration_quota_and_sanitizer():
    print("== 6) ⚙️ ORKESTRATSIYA + ATOMIK KVOTA + SANITIZER ==")

    # 6.1 Provider zanjiri va orchestratordan haqiqiy foydalanish
    real = AIOrchestrator(provider_chain=ProviderChain(providers=[MockProvider()]))
    outcome = await MultiVariantGenerator(real).generate(None, "Sport kiyim", "uz")
    check(outcome.success and outcome.provider_used == "Mock",
          f"xizmat Phase 3 AIOrchestrator + ProviderChain'ni ishlatadi ({outcome.provider_used})")

    # 6.2 Butun batch uchun BITTA atomik bron
    db = AtomicQuotaDB()
    stub = StubOrchestrator()
    res = await MultiVariantGenerator(stub).generate(7, "Aksessuarlar", "uz", db_module=db)
    check(len(stub.calls) == 5, f"5 ta uslub uchun 5 ta AI chaqiruvi ({len(stub.calls)})")
    check(db.reserve_calls == [(7, "magic_post:variants", 1)],
          f"butun batch uchun AYNAN BITTA atomik bron: {db.reserve_calls}")
    check(not db.legacy_calls,
          "eski 2 qadamli check_ai_limit+use_user_credit zanjiri ishlatilmadi")
    check(all(call["context"].get("skip_quota") is True for call in stub.calls)
          and all(call["db_module"] is False for call in stub.calls),
          "ichki chaqiruvlar skip_quota=True + db_module=False (2 marta yechilmaydi)")
    check(res.cost == 1 and res.paid is True and not db.refund_calls,
          f"muvaffaqiyatli batch: cost={res.cost}, refund yo'q")

    # 6.3 Kvota rad etilsa — AI'ga umuman chiqmaydi
    db2 = AtomicQuotaDB(allowed=False, reason="insufficient_balance")
    stub2 = StubOrchestrator()
    denied = await MultiVariantGenerator(stub2).generate(7, "Aksessuarlar", "uz", db_module=db2)
    check(denied.success is False and denied.error_code == "QUOTA_EXCEEDED",
          f"kvota yetmasa: success=False, {denied.error_code}")
    check(not stub2.calls, "rad etilganda AI'ga BIR TA ham so'rov bormadi (fail-closed)")
    check(not db2.refund_calls, "bron olinmagan bo'lsa refund ham chaqirilmaydi")

    # 6.4 DB xatosida FAIL-CLOSED
    db3 = AtomicQuotaDB(raise_on_reserve=True)
    stub3 = StubOrchestrator()
    failed_db = await MultiVariantGenerator(stub3).generate(7, "Aksessuarlar", "uz", db_module=db3)
    check(failed_db.success is False and failed_db.error_code == "QUOTA_UNAVAILABLE",
          f"DB xatosida ruxsat YO'Q (fail-closed): {failed_db.error_code}")
    check(not stub3.calls, "DB xatosida ham AI'ga chiqmadi")

    # 6.5 AI yiqilsa — bron qaytariladi (fallback uchun pul olinmaydi)
    db4 = AtomicQuotaDB()
    broken = await MultiVariantGenerator(StubOrchestrator(ok=False)).generate(
        7, "Aksessuarlar", "uz", db_module=db4)
    check(broken.success is True and broken.paid is False and broken.refund_issued is True
          and broken.cost == 0,
          f"AI ishlamasa: bron qaytarildi (cost={broken.cost}, refund={db4.refund_calls})")
    check(db4.refund_calls == [(7, 90001)], "refund reservation_id bilan va bir marta chaqirildi")
    check(broken.count == 5, "shunga qaramay foydalanuvchi 5 ta variantni oladi (fallback)")

    # 6.6 Bepul qadam — bron umuman qilinmaydi
    db5 = AtomicQuotaDB()
    free_audit = await PostAuditService(StubOrchestrator()).audit_post(
        7, STRONG_POST, "uz", db_module=db5, improve=False)
    check(free_audit.success and db5.reserve_calls == [] and free_audit.cost == 0,
          f"audit (baholash, yaxshilashsiz) BEPUL: reserve={db5.reserve_calls}")
    db6 = AtomicQuotaDB()
    paid_audit = await PostAuditService(StubOrchestrator()).audit_post(
        7, STRONG_POST, "uz", db_module=db6, improve=True)
    check(paid_audit.success and len(db6.reserve_calls) == 1 and paid_audit.paid is True,
          f'«✨ yaxshilangan namuna» uchun 1 bron: {db6.reserve_calls}')
    db7 = AtomicQuotaDB()
    broken_audit = await PostAuditService(StubOrchestrator(ok=False)).audit_post(
        7, STRONG_POST, "uz", db_module=db7, improve=True)
    check(broken_audit.success is True and broken_audit.cost == 0
          and broken_audit.refund_issued is True,
          "yaxshilash AI'si yiqilsa — hisobot baribir chiqadi va bron qaytariladi")

    # 6.7 Repurpose va planner — bir bron / bepul 1 kunlik reja
    db8 = AtomicQuotaDB()
    rep = await ContentRepurposeService(StubOrchestrator()).repurpose(
        7, SOURCE_CONTENT, "uz", db_module=db8)
    check(rep.success and db8.reserve_calls == [(7, "magic_post:repurpose", 1)]
          and len(db8.refund_calls) == 0,
          f"repurpose: 5 platforma uchun 1 bron {db8.reserve_calls}")
    db9 = AtomicQuotaDB()
    rep_broken = await ContentRepurposeService(StubOrchestrator(ok=False)).repurpose(
        7, SOURCE_CONTENT, "uz", db_module=db9)
    check(rep_broken.success and rep_broken.cost == 0 and len(db9.refund_calls) == 1,
          "repurpose: AI ishlamasa bron qaytarildi")
    db10 = AtomicQuotaDB()
    plan14_stub = StubOrchestrator(text=(
        '{"plan": [{"day": 1, "topic": "Yangi burchak", '
        '"hook": "Elingizga oladigan natija"}]}'))
    plan14 = await ContentPlanService(plan14_stub).generate_plan(
        7, "Do'kon", 14, "uz", db_module=db10, is_pro=True)
    check(plan14.success and len(db10.reserve_calls) == 1 and db10.refund_calls == [],
          f"14 kunlik reja: 1 ta bron, refund yo'q (calls={len(plan14_stub.calls)})")
    check(len(plan14_stub.calls) == 2 and all(
        call["context"].get("smm_mode") == "PLANNER" for call in plan14_stub.calls),
          f"14 kun 2 ta 7 kunlik AI batch'ga bo'lindi ({len(plan14_stub.calls)} chaqiruv)")
    db11 = AtomicQuotaDB()
    plan1 = await ContentPlanService(StubOrchestrator()).generate_plan(
        7, "Do'kon", 1, "uz", db_module=db11, is_pro=True)
    check(plan1.success and db11.reserve_calls == [],
          f"1 kunlik reja bron QE'LMAYDI (kredit tejaladi): {db11.reserve_calls}")
    db12 = AtomicQuotaDB()
    plan_novalue = await ContentPlanService(StubOrchestrator(
        text='{"plan": []}')).generate_plan(7, "Do'kon", 14, "uz", db_module=db12, is_pro=True)
    check(plan_novalue.success and plan_novalue.cost == 0 and len(db12.refund_calls) == 1,
          "AI hech bir kunga hech narsa qo'shmasa — bron qaytariladi")

    # 6.8 Phase 2 sanitizeri — barcha chiqishlarda
    hostile_text = ("<b>Salom</b> <script>alert(1)</script> narx: 5 < 10 & 20 > 15 "
                    "👉 <a href=\"https://t.me/x\">havola</a> " + "qo'shimcha matn " * 60)
    db13 = AtomicQuotaDB()
    hostile = await MultiVariantGenerator(StubOrchestrator(
        text=hostile_text)).generate(7, "Xavfli kiritish", "uz", db_module=db13)
    over = [chunk for chunk in hostile.chunks if html_length(chunk) > TELEGRAM_TEXT_LIMIT]
    check(not over and all("<script>" not in chunk for chunk in hostile.chunks),
          f"zararli + uzun AI javobi: {len(hostile.chunks)} chunk, limit ichida va escape qilingan")
    check("&lt;script&gt;" in hostile.variants[0].content
          or "<script>" not in hostile.variants[0].content,
          "variant matnida <script> faqat ko'rinish sifatida qoladi (xavfsiz)")
    chunked = chunk_blocks([f"blok {i}\n\n" + "söz " * 400 for i in range(6)], limit=1200)
    check(len(chunked) >= 6 and all(html_length(c) <= 1200 for c in chunked),
          f"chunk_blocks uzun bloklarni bo'ladi (chunks={len(chunked)})")

    # 🧩 Chunk'langan xabarlarda HTML teglar MUVOZANATLI bo'lishi shart
    # (aks holda Telegram «can't parse entities» beradi).
    # <b> ... </b> BUTUN blokni qamrab oladi: chunk o'rtada kesilganda
    # teg muvozanati buziladi — sanitizer qayta ishlashi shuni tuzatadi.
    huge = "<b>Katta post " + ("juda kerakli ma'lumot. " * 300) + "</b>\n\n#smm #tag"
    db14 = AtomicQuotaDB()
    big_variants = await MultiVariantGenerator(StubOrchestrator(text=huge)).generate(
        7, "Uzun kontent", "uz", db_module=db14)
    big_repurpose = await ContentRepurposeService(StubOrchestrator(text=huge)).repurpose(
        7, huge, "uz", db_module=AtomicQuotaDB())
    big_audit = await PostAuditService(StubOrchestrator(
        text='{"improved_post": "' + huge.replace('"', '') + '"}')).audit_post(
        7, STRONG_POST, "uz", db_module=AtomicQuotaDB())
    big_plan = await ContentPlanService(StubOrchestrator(text=huge)).generate_plan(
        7, "Uzun yo'nalish", 30, "uz", db_module=AtomicQuotaDB(), is_pro=True)
    all_chunks = (list(big_variants.chunks) + list(big_repurpose.chunks)
                  + list(big_audit.chunks) + list(big_plan.chunks))
    check(all_chunks and all(html_length(c) <= TELEGRAM_TEXT_LIMIT for c in all_chunks),
          f"katta hajmdagi 4 xizmat chiqishi ham limitda (chunks={len(all_chunks)})")
    check(all(balanced_tags(c) for c in all_chunks),
          "chunk'langan xabarlarda <b>/<i> teglar yopilgan (Telegram parse xatosi yo'q)")
    check(get_default_orchestrator() is not None, "global orchestrator lazy rezolyutsiya qilinadi")


# ===========================================================================
# TEST 7 — AVVALGI FAZALAR BUZILMAGANLIGI (regressiya qo'riqonlari)
# ===========================================================================
async def test_previous_phases_regression():
    print("== 7) 🧱 AVVALGI FAZALAR QO'RIQONLARI ==")
    # Phase 3 — intent router
    from services.ai.router import SMMIntent, detect_intent
    check(detect_intent("5 xil variant ber") == SMMIntent.GENERATE_VARIANTS,
          "Intent router: GENERATE_VARIANTS saqlangan")
    check(detect_intent("Postni audit qil") == SMMIntent.POST_AUDIT,
          "Intent router: POST_AUDIT saqlangan")
    check(detect_intent("Postni qisqartir") == SMMIntent.SHORTEN
          and detect_intent("nima haqida yozsam") == SMMIntent.CONTENT_IDEAS,
          "Intent router: SHORTEN / CONTENT_IDEAS o'rnida")
    check(detect_intent("") == SMMIntent.UNKNOWN and detect_intent(None) == SMMIntent.UNKNOWN,
          "Intent router: bo'sh/None → UNKNOWN (xavfsiz)")

    # Phase 3 — MockProvider eski javoblari O'ZGARMAGAN
    legacy = await MockProvider().generate("Futbol haqida post yoz", {"lang": "uz"})
    check("Futbol haqida post yoz" in legacy and len(legacy) > 60,
          "MockProvider: CREATE_POST javobi (eski kontrakt) buzilmagan")
    legacy_audit = await MockProvider().generate(
        "Postni audit qil", {"lang": "uz", "intent": "POST_AUDIT"})
    check("ball" in legacy_audit.lower() or "89" in legacy_audit,
          "MockProvider: POST_AUDIT javobi (eski kontrakt) buzilmagan")
    legacy_variants = await MockProvider().generate(
        "5 variant ber", {"lang": "uz", "intent": "GENERATE_VARIANTS"})
    check("varianti" in legacy_variants and "smm_mode" not in str(legacy_variants),
          "MockProvider: GENERATE_VARIANTS (eski 3-variantli) javobi saqlangan")
    thin = await MockProvider().generate("X", {"lang": "uz", "force_thin_output": True})
    check(thin == "Qisqa", "MockProvider: force_thin_output test nazorati ishlaydi")

    # Phase 2 — sanitizer
    escaped = sanitize_html("<b>bold</b> <script>bad()</script> & <i>i</i>")
    check(escaped == "<b>bold</b> &lt;script&gt;bad()&lt;/script&gt; &amp; <i>i</i>",
          "Phase 2 sanitizer: ruxsat etilmagan teg escape qilinadi")
    check(html_length(sanitize_html("A" * 5000)) <= TELEGRAM_TEXT_LIMIT,
          "Phase 2 sanitizer: 4096 chegarasi saqlangan")
    check(sanitize_html(sanitize_html("<b>x</b> &amp; y")) == sanitize_html("<b>x</b> & y"),
          "Sanitizer idempotent (qayta ishlash buzmaydi)")

    # Phase 2 — atomik kvota API'si o'rnida
    import database as repo_db
    check(callable(getattr(repo_db, "reserve_ai_request", None))
          and callable(getattr(repo_db, "refund_ai_request", None)),
          "database.reserve_ai_request / refund_ai_request mavjud")
    check(all(base in repo_db.AI_OPERATION_TYPES for base in
              ("magic_post", "post_score", "content_calendar")),
          "yangi oqimlarning kvota asoslari AI_OPERATION_TYPES oq ro'yxatida")
    from services.ai_quota import release_ai_quota, reserve_ai_quota
    check(callable(reserve_ai_quota) and callable(release_ai_quota),
          "services.ai_quota yagona kirish nuqtasi ishlaydi")

    # Phase 4/5 — concurrency manager orqali o'tish (queue)
    from services.ai.concurrency import ai_concurrency_manager
    status = ai_concurrency_manager.get_status()
    check(status["active_slots"] == 0 and status["max_concurrency"] >= 1,
          f"AI bounded queue bo'sh va sozlangan: {status['max_concurrency']}")

    # Validator
    from services.ai.validator import AIOutputValidator
    check(AIOutputValidator.validate("").error_code == "EMPTY_OUTPUT"
          and AIOutputValidator.validate("Salom").error_code == "THIN_OUTPUT",
          "AIOutputValidator qoidalari o'zgarmagan")

    # Paket eksportlari
    import services.ai as ai_package
    missing = [name for name in ai_package.__all__ if not hasattr(ai_package, name)]
    check(not missing, f"services.ai __all__ eksportlari to'liq (kam: {missing})")

    # Yangi xizmatlar sinfi bazadan meros olgan (yagona standart)
    from services.ai.smm_common import SMMFeatureService
    check(all(issubclass(cls, SMMFeatureService) for cls in
              (MultiVariantGenerator, ContentRepurposeService, PostAuditService,
               ContentPlanService)),
          "to'rt xizmat ham SMMFeatureService bazasida (kvota+sanitizer yagona)")
    for cls, operation in ((MultiVariantGenerator, "magic_post:variants"),
                           (ContentRepurposeService, "magic_post:repurpose"),
                           (PostAuditService, "post_score:audit"),
                           (ContentPlanService, "content_calendar:plan")):
        check(cls.quota_operation == operation and cls.quota_cost == 1,
              f"{cls.__name__}: kvota operatsiyasi {operation}, narx 1")

    # Test rejestratsiyasi — runner yangi qamrovni chaqirishi shart
    runner = (ROOT / "tests" / "run_tests.sh").read_text(encoding="utf-8")
    check("ai_advanced_features_test.py" in runner,
          "tests/run_tests.sh PHASE 11 & 12 test qamrovin chaqiradi")


# ===========================================================================
# RUNNER
# ===========================================================================
async def main_async():
    print("=" * 66)
    print(" 🚀 PHASE 11 & 12 — AI ADVANCED SMM FEATURES (33/48/49/50/51-bandlar)")
    print("=" * 66)

    print("\n== 0. Foydalanuvchi kirish nuqtalari (API kalitsiz) ==")
    saved = {key: os.environ.get(key) for key in
             ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")}
    for key in saved:
        os.environ.pop(key, None)
    check(not any(os.environ.get(key) for key in saved),
          "test muhitida AI kalitlari o'chirilgan — MockProvider rejimi")

    await test_multi_variant_generator()
    print()
    await test_repurpose_formats()
    print()
    await test_post_audit()
    print()
    await test_content_plan()
    print()
    await test_mock_mode_without_api_keys()
    print()
    await test_orchestration_quota_and_sanitizer()
    print()
    await test_previous_phases_regression()

    print("\n" + "=" * 66)
    print(f" JAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        print(" [FAIL] PHASE 11 & 12 TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" PHASE 11 & 12 — ADVANCED SMM TESTLARI 100% YASHIL ✔")
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
