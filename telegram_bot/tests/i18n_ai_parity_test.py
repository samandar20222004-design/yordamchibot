#!/usr/bin/env python3
"""3 TILLIK (UZ / RU / EN) PARITET + AI TIL MOSLASHUVI — regression testlari.

Nima uchun bu fayl bor?
    PostAssist V2 da uchta til (o'zbek, rus, ingliz) va AI javoblari
    bir-biridan mustaqil rivojlanishi natijasida ikki xil "jimgina
    buzilish" yuzaga keladi:

      1. **Lug'at pariteti**: ``locales/translations.py`` (UZ/RU) va
         ``locales/en_overlay.py`` (EN) dagi kalitlar yoki ularning
         ``{placeholder}`` lari farq qilib qolsa, ``get_text`` formatlashdan
         qochib boshqa til variantiga o'tadi — foydalanuvchi noto'g'ri
         tildagi matnni ko'radi (yoki ``KeyError`` bilan handler qulaydi).

      2. **AI til aralashuvi**: AI tizim promptlari tarixan faqat o'zbekcha
         yozilgani uchun rus/ingliz foydalanuvchi ham o'zbekcha (yoki
         aralash) javob olardi.

    Bu test ikkalasini ham 100% qo'riqlaydi:

      I.   UZ/RU/EN lug'atlari — kalitlar, format argumentlari,
           ``safe_t`` xavfsizligi va HTML/formatlash butunligi.
      II.  AI tizim promptlari — har bir til o'z qat'iy qoidasini oladi,
           begona til qoidasi qolmaydi, til bloki idempotent.
      III. Til o'zgarganda pastki (ReplyKeyboard) menyu DARHOL yangi tilda
           yuboriladi va inline menyular ham yangi tilda ochiladi.

Ishga tushirish:
    cd telegram_bot && python tests/i18n_ai_parity_test.py
"""
import asyncio
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locales.translations import (  # noqa: E402
    TRANSLATIONS,
    SUPPORTED_LANGS,
    AI_LANGUAGE_RULES,
    AI_LANGUAGE_MARKER,
    build_ai_language_directive,
    format_args,
    get_text,
    safe_t,
    translation_format_report,
    translation_parity_report,
)
from locales.en_overlay import EN_OVERLAY  # noqa: E402

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


CYRILLIC = re.compile(r"[\u0400-\u04FF]")
#: O'zbekcha matnning o'ziga xos belgilari (boshqa tillarda uchramaydi).
UZ_MARKERS = ("O'ZBEK", "O'zbek", "o'zbek", "Toshkent", " kerak", " bo'lsin")


# ================================================================
# I. LUG'AT PARITETI (UZ / RU / EN)
# ================================================================
def test_key_parity():
    """Uchala lug'atning kalitlar to'plami 100% bir xil."""
    print("== 1. Kalitlar pariteti (uz/ru/en) ==")
    sizes = {code: len(TRANSLATIONS.get(code) or {}) for code in SUPPORTED_LANGS}
    check("3 ta lug'at mavjud", all(sizes.values()), str(sizes))
    check("kalitlar soni teng", len(set(sizes.values())) == 1, str(sizes))
    check("lug'at bo'sh emas (500+)", min(sizes.values()) >= 500, str(sizes))

    uz = set(TRANSLATIONS["uz"])
    ru = set(TRANSLATIONS["ru"])
    en = set(TRANSLATIONS["en"])
    check("UZ \\ RU bo'sh", not (uz - ru), str(sorted(uz - ru)[:5]))
    check("RU \\ UZ bo'sh", not (ru - uz), str(sorted(ru - uz)[:5]))
    check("UZ \\ EN bo'sh", not (uz - en), str(sorted(uz - en)[:5]))
    check("EN \\ UZ bo'sh", not (en - uz), str(sorted(en - uz)[:5]))


def test_en_overlay_coverage():
    """EN overlay barcha kalitlarni qoplaydi (aks holda EN'da uz matn chiqadi)."""
    print("== 2. EN_OVERLAY qamrovi ==")
    missing = sorted(set(TRANSLATIONS["uz"]) - set(EN_OVERLAY))
    check("EN_OVERLAY hamma kalitni qoplaydi", not missing, str(missing[:8]))
    check("EN_OVERLAY bo'sh emas", len(EN_OVERLAY) >= 500, str(len(EN_OVERLAY)))
    extra = sorted(set(EN_OVERLAY) - set(TRANSLATIONS["uz"]))
    check("EN_OVERLAY'da ortiqcha kalit yo'q", not extra, str(extra[:8]))

    rep = translation_parity_report()
    check("paritet hisoboti: uz_only bo'sh", not rep["uz_only"], str(rep["uz_only"][:5]))
    check("paritet hisoboti: ru_only bo'sh", not rep["ru_only"], str(rep["ru_only"][:5]))
    check("paritet hisoboti: en_missing bo'sh", not rep["en_missing"], str(rep["en_missing"][:5]))
    check("paritet hisoboti: in_sync", rep["in_sync"] is True)
    check("paritet hisoboti: en_in_sync", rep["en_in_sync"] is True)
    check("paritet hisoboti: all_in_sync", rep["all_in_sync"] is True)


def test_format_args_parity():
    """Format argumentlari ({user_id}, {days}, {balance}, ...) uchala tilda bir xil."""
    print("== 3. Format argumentlari pariteti ==")
    report = translation_format_report()
    check("format hisoboti: in_sync (100%)", report["in_sync"] is True,
          str(report["mismatch"][:3]))
    check("format hisoboti: kalitlar soni", report["keys"] >= 500, str(report["keys"]))
    check("bo'sh qiymatli kalit yo'q", not report["empty"], str(report["empty"][:5]))

    # Muhim (ko'p ishlatiladigan) kalitlar alohida tekshiriladi.
    critical = [
        "cabinet_title", "cabinet_streak", "credits_value",
        "no_credits", "ai_limit_msg", "daily_bonus_claimed",
        "referral_menu", "transfer_success", "card_payment_steps",
        "receipt_admin_user_id_line", "cp_plan_header_new",
        "an_dash_header", "an_dash_7d", "queue_view_title",
        "enh_btns_line", "sub_required", "start_hello",
    ]
    bad = []
    for key in critical:
        per_lang = {
            code: format_args((TRANSLATIONS.get(code) or {}).get(key))
            for code in SUPPORTED_LANGS
        }
        if len({frozenset(v) for v in per_lang.values()}) != 1:
            bad.append((key, {c: sorted(a) for c, a in per_lang.items()}))
    check("muhim kalitlar: argumentlar bir xil", not bad, str(bad[:3]))

    # Har bir argument uchala tilda ham formatlanishi shart ({user_id}, {days}, ...).
    unfmt = []
    for key in sorted(TRANSLATIONS["uz"]):
        args = format_args(TRANSLATIONS["uz"][key])
        if not args:
            continue
        values = {a: "X" for a in args}
        for code in SUPPORTED_LANGS:
            out = safe_t(key, code, **values)
            if "{" in out or "}" in out:
                unfmt.append((key, code, out[:60]))
                break
    check("barcha kalitlar 3 tilda formatlanadi (qavs qolmaydi)", not unfmt, str(unfmt[:3]))


def test_safe_t_never_crashes():
    """``safe_t`` — kalit/argument xato bo'lsa ham bot qulab tushmaydi."""
    print("== 4. safe_t xavfsizligi (KeyError/IndexError yo'q) ==")
    ok = True
    detail = ""
    try:
        # 1) Noma'lum kalit — kalitning o'zi qaytadi, istisno yo'q.
        missing = safe_t("bu_kalit_mavjud_emas_123", "en")
        ok = ok and missing == "bu_kalit_mavjud_emas_123"
        # 2) Noto'g'ri format argumentlari (KeyError o'rniga asl matn).
        r1 = safe_t("credits_value", "ru")           # {n} berilmadi
        r2 = safe_t("credits_value", "en", boshqa=5)  # noto'g'ri nom
        ok = ok and isinstance(r1, str) and isinstance(r2, str)
        # 3) Bo'sh / None / raqamli kalit.
        ok = ok and safe_t(None, "uz") == ""
        ok = ok and safe_t("", "ru") == ""
        ok = ok and isinstance(safe_t(12345, "en"), str)
        # 4) Noma'lum til kodi — uz'ga tushadi (crash emas).
        r3 = safe_t("btn_new_post", "de-DE")
        ok = ok and r3 == get_text("btn_new_post", "uz")
        # 5) Barcha qiymatlar uchun: hech qanday istisno chiqmasin.
        for code in SUPPORTED_LANGS:
            for key in list(TRANSLATIONS[code])[:120]:
                safe_t(key, code)
                safe_t(key, code, n=1, user_id=2, days=3, balance=4, plan=5, code=6, date=7)
    except Exception as exc:  # noqa: BLE001
        ok = False
        detail = f"{type(exc).__name__}: {exc}"
    check("safe_t hech qachon istisno bermaydi", ok, detail)
    check("noma'lum kalit → kalit nomi (fallback)",
          safe_t("yoq_kalit_xyz", "uz") == "yoq_kalit_xyz")


def test_button_labels_3_langs():
    """Asosiy menyu tugmalari uchala tilda mavjud, farqli va bo'sh emas."""
    print("== 5. Tugma yorliqlari (reply + inline) ==")
    from keyboards.default import get_refreshed_main_keyboard

    # UX V2 (6-tugma standarti): birinchi tugma — «✨ Kontent yaratish».
    expected_first = {
        "uz": "✨ Kontent yaratish",
        "ru": "✨ Создать контент",
        "en": "✨ Create content",
    }
    for code, expected in expected_first.items():
        kb = get_refreshed_main_keyboard(code)
        labels = [b.text for row in kb.keyboard for b in row]
        check(f"{code}: pastki menyu birinchi tugmasi",
              labels and labels[0] == expected, str(labels[:2]))
        check(f"{code}: pastki menyu bo'sh tugmasiz",
              all(str(x).strip() for x in labels), str(labels))

    all_labels = {
        code: [b.text for row in get_refreshed_main_keyboard(code).keyboard for b in row]
        for code in SUPPORTED_LANGS
    }
    check("3 tilning menyusi farqli (tarjima qilingan)",
          len({tuple(v) for v in all_labels.values()}) == 3, str(all_labels["en"][:2]))

    # Inline kabinet menyusi ham uchala tilda to'liq tarjima qilingan.
    from keyboards.inline import get_cabinet_inline_keyboard, get_language_keyboard
    for code in SUPPORTED_LANGS:
        inline_labels = [
            b.text for row in get_cabinet_inline_keyboard(code).inline_keyboard for b in row
        ]
        # 🧹 UI/UX POLISH (1-qadam): kabinet — ixcham 5 tugmali panel.
        check(f"{code}: kabinet inline menyusi to'liq (5 ta tugma — ixcham panel)",
              len(inline_labels) == 5 and all(str(x).strip() for x in inline_labels),
              str(inline_labels[:3]))
        lang_cbs = [
            b.callback_data
            for row in get_language_keyboard(code).inline_keyboard
            for b in row
        ]
        check(f"{code}: til menyusida 3 ta til tugmasi",
              all(c in lang_cbs for c in ("cab_lang_uz", "cab_lang_ru", "cab_lang_en")),
              str(lang_cbs))


# ================================================================
# II. AI TIZIM PROMPTLARI — TIL MOSLASHUVI
# ================================================================
def test_single_source_of_truth():
    """Til qoidalari yagona manbada (``locales`` ↔ ``ai_agent``)."""
    print("== 6. AI til qoidalari — yagona manba ==")
    from utils import ai_agent

    check("ai_agent.AI_LANGUAGE_RULES == locales.AI_LANGUAGE_RULES",
          ai_agent.AI_LANGUAGE_RULES == AI_LANGUAGE_RULES,
          str(ai_agent.AI_LANGUAGE_RULES))
    for code in SUPPORTED_LANGS:
        check(f"{code}: qoida matni to'g'ri birikadi",
              ai_agent.language_directive(code) == build_ai_language_directive(code))
        check(f"{code}: qoida bo'sh emas",
              len(AI_LANGUAGE_RULES.get(code, "")) > 20, str(AI_LANGUAGE_RULES.get(code)))

    # Noma'lum/noto'g'ri til → xavfsiz 'uz'.
    cases = {"ru": "ru", "ru-RU": "ru", "RU": "ru", "en": "en", "en-US": "en",
             "EN": "en", "uz": "uz", "uz-UZ": "uz", None: "uz", "": "uz",
             "de": "uz", "fr-FR": "uz", 123: "uz"}
    bad = [(raw, ai_agent.normalize_ai_lang(raw), want)
           for raw, want in cases.items() if ai_agent.normalize_ai_lang(raw) != want]
    check("normalize_ai_lang: 3 tilga xavfsiz normallashtirish", not bad, str(bad[:3]))


def test_with_language_rules():
    """``with_language`` — idempotent, til almashganda yangilanadi, aralashmaydi."""
    print("== 7. with_language: idempotentlik va til almashinuvi ==")
    from utils import ai_agent

    base = "Siz professional SMM mutaxassisisiz. Post matnini tahlil qiling."
    for code in SUPPORTED_LANGS:
        prompt = ai_agent.with_language(base, code)
        rule = AI_LANGUAGE_RULES[code]
        check(f"{code}: qoida prompt tepasida", prompt.startswith("=" * 10), prompt[:40])
        check(f"{code}: o'z qoidasi bor", rule in prompt, prompt[:120])
        others = [AI_LANGUAGE_RULES[c] for c in SUPPORTED_LANGS if c != code]
        check(f"{code}: begona til qoidasi YO'Q",
              all(o not in prompt for o in others), prompt[:200])
        # Idempotentlik: qayta qo'llash blokni ko'paytirmaydi.
        twice = ai_agent.with_language(prompt, code)
        check(f"{code}: idempotent (blok ko'paymaydi)", twice == prompt,
              f"{len(prompt)} → {len(twice)}")
        check(f"{code}: marker bitta marta", twice.count(AI_LANGUAGE_MARKER) == 1,
              str(twice.count(AI_LANGUAGE_MARKER)))

    # Til almashinuvi: ru → en da eski (ruscha) blok olib tashlanadi.
    ru_prompt = ai_agent.with_language(base, "ru")
    en_prompt = ai_agent.with_language(ru_prompt, "en")
    check("til almashganda eski blok o'chiriladi",
          AI_LANGUAGE_RULES["ru"] not in en_prompt, en_prompt[:160])
    check("til almashganda yangi qoida qo'shiladi",
          AI_LANGUAGE_RULES["en"] in en_prompt, en_prompt[:160])

    # Buzilgan kirish (None/raqam) ham xavfsiz.
    check("with_language(None) xavfsiz", AI_LANGUAGE_MARKER in ai_agent.with_language(None, "ru"))
    check("with_language(123) xavfsiz", AI_LANGUAGE_MARKER in ai_agent.with_language(123, "en"))


def _uz_only_sentences():
    """Eski promptlarda qolib ketgan 'faqat o'zbekcha yoz' ko'rsatmalari."""
    return (
        "Barcha javoblar O'ZBEK tilida bo'lishi SHART",
        "ruscha, inglizcha aralashtirilmasin",
        "emotsional O'zbek tili ishlating",
        "O'zbek tilida, jonli va jozibador yozing",
    )


def test_router_prompt_per_language():
    """Intent-router prompti to'liq foydalanuvchi tilida (aralashuvsiz)."""
    print("== 8. Intent-router prompti (3 til, aralashuvsiz) ==")
    from utils import ai_agent

    for code in SUPPORTED_LANGS:
        prompt = ai_agent._get_router_system_instruction(is_pro=True, lang=code)
        check(f"{code}: router prompt — o'z qoidasi", AI_LANGUAGE_RULES[code] in prompt)
        others = [AI_LANGUAGE_RULES[c] for c in SUPPORTED_LANGS if c != code]
        check(f"{code}: router prompt — begona qoida yo'q",
              all(o not in prompt for o in others))
        if code != "uz":
            leaked = [s for s in _uz_only_sentences() if s in prompt]
            check(f"{code}: o'zbekcha til ko'rsatmasi qolmagan", not leaked, str(leaked))

    # Tilga xos so'zlar: ru — kirill, en — lotin, uz — kirillsiz.
    uz_prompt = ai_agent._get_router_system_instruction(lang="uz")
    ru_prompt = ai_agent._get_router_system_instruction(lang="ru")
    en_prompt = ai_agent._get_router_system_instruction(lang="en")
    check("RU prompt kirill alifbosida", bool(CYRILLIC.search(ru_prompt)))
    check("EN prompt kirilldan xoli", not CYRILLIC.search(en_prompt),
          str(CYRILLIC.findall(en_prompt)[:5]))
    check("UZ prompt kirilldan xoli", not CYRILLIC.search(uz_prompt),
          str(CYRILLIC.findall(uz_prompt)[:5]))
    check("3 tilning promptlari farqli",
          len({uz_prompt, ru_prompt, en_prompt}) == 3)
    # JSON kontrakti (intent/reply/post_text) barcha tillarda saqlanadi.
    for code, prompt in (("uz", uz_prompt), ("ru", ru_prompt), ("en", en_prompt)):
        for field in ("intent", "reply", "post_text", "scheduled_time", "target_all"):
            check(f"{code}: JSON kontraktida '{field}' bor", f'"{field}"' in prompt)


def test_ai_functions_inject_language():
    """AI funksiyalari tizim promptiga foydalanuvchi tilini biriktiradi."""
    print("== 9. AI funksiyalari: til promptga birikadi ==")
    from utils import ai_agent

    captured = []

    async def fake_chain(prompt, system_instruction):
        """Eski (2 argumentli) mock — orqaga moslik ham shu yerda tekshiriladi."""
        captured.append(system_instruction)
        return {"intent": "faq", "reply": "ok", "post_text": ""}

    async def run():
        orig = ai_agent._run_ai_chain
        ai_agent._run_ai_chain = fake_chain
        try:
            for code in SUPPORTED_LANGS:
                captured.clear()
                await ai_agent.generate_ai_response("Salom", lang=code)
                check(f"{code}: generate_ai_response — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0],
                      (captured[0][:120] if captured else "chaqiruv yo'q"))
                if code != "uz":
                    check(f"{code}: generate_ai_response — uz ko'rsatmasi yo'q",
                          not any(s in captured[0] for s in _uz_only_sentences()))

                captured.clear()
                await ai_agent.analyze_user_prompt("Post yoz", user_id=1, lang=code)
                check(f"{code}: analyze_user_prompt — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0],
                      (captured[0][:120] if captured else "chaqiruv yo'q"))

                captured.clear()
                await ai_agent.audit_post("Post matni", is_pro=True, lang=code)
                check(f"{code}: audit_post(PRO) — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0],
                      (captured[0][:120] if captured else "chaqiruv yo'q"))

                captured.clear()
                await ai_agent.audit_post("Post matni", is_pro=False, lang=code)
                check(f"{code}: audit_post(FREE) — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0])

                captured.clear()
                await ai_agent.generate_content_plan("Mavzu", "Kanal", lang=code)
                check(f"{code}: generate_content_plan — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0],
                      (captured[0][:120] if captured else "chaqiruv yo'q"))
                if code != "uz":
                    check(f"{code}: content-plan promptida uz qoldig'i yo'q",
                          "Barcha javoblar O'ZBEK tilida bo'lishi SHART" not in captured[0],
                          captured[0][:200])

                captured.clear()
                await ai_agent.extract_schedule_time("ertaga 10:00", lang=code)
                check(f"{code}: extract_schedule_time — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0])

                captured.clear()
                await ai_agent.format_post_text("Post matni", "grammar", lang=code)
                check(f"{code}: format_post_text — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0])

                captured.clear()
                await ai_agent.generate_post_from_plan("Mavzu", "Sarlavha", "G'oya", lang=code)
                check(f"{code}: generate_post_from_plan — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0])

                captured.clear()
                await ai_agent.rewrite_channel_post("Asl post", "kanal", lang=code)
                check(f"{code}: rewrite_channel_post — til bloki",
                      bool(captured) and AI_LANGUAGE_RULES[code] in captured[0])
        finally:
            ai_agent._run_ai_chain = orig

    async def fake_chain_dict(prompt, system_instruction):
        captured.append(system_instruction)
        return {"formatted": "OK", "post_text": "OK", "plan": [{"day": "1"}]}

    async def run2():
        orig = ai_agent._run_ai_chain
        ai_agent._run_ai_chain = fake_chain_dict
        try:
            for code in SUPPORTED_LANGS:
                captured.clear()
                res = await ai_agent.format_post_text("Salom", "grammar", lang=code)
                check(f"{code}: format_post_text natijasi", "formatted" in res, str(res))
                captured.clear()
                res = await ai_agent.generate_content_plan("Mavzu", "Kanal", lang=code)
                check(f"{code}: generate_content_plan natijasi", "plan" in res, str(res))
                captured.clear()
                res = await ai_agent.generate_post_from_plan("M", "S", "G", lang=code)
                check(f"{code}: generate_post_from_plan natijasi", "post_text" in res, str(res))
                captured.clear()
                res = await ai_agent.rewrite_channel_post("Asl post matni", "kanal", lang=code)
                check(f"{code}: rewrite_channel_post natijasi", "post_text" in res, str(res))
        finally:
            ai_agent._run_ai_chain = orig

    asyncio.run(run())
    asyncio.run(run2())

    # Timeout xabari ham foydalanuvchi tilida.
    from utils.ai_agent import ai_timeout_message
    check("timeout xabari (uz) — o'zbekcha", "urinib" in ai_timeout_message("uz"))
    check("timeout xabari (ru) — ruscha", "попробуйте" in ai_timeout_message("ru").lower())
    check("timeout xabari (en) — inglizcha", "try again" in ai_timeout_message("en").lower())


def test_resolve_ai_lang():
    """Yakuniy AI tili: tanlangan til ustun, bo'lmasa matndan aniqlanadi."""
    print("== 10. resolve_ai_lang: tanlangan til + matn aniqlovchisi ==")
    from utils import ai_agent

    # 1) Tanlangan til HAR DOIM ustun (murojaat matni boshqa tilda bo'lsa ham).
    cases = [
        (("uz", "Привет, напиши пост про кофе"), "uz"),
        (("ru", "Salom, kofe haqida post yoz"), "ru"),
        (("en", "Salom, menga post kerak"), "en"),
        (("uz", None), "uz"),
        (("ru", ""), "ru"),
        (("en-US", ""), "en"),
    ]
    bad = [(args, ai_agent.resolve_ai_lang(*args), want)
           for args, want in cases if ai_agent.resolve_ai_lang(*args) != want]
    check("tanlangan til ustun (matn tilidan qat'i nazar)", not bad, str(bad[:3]))

    # 2) Tanlangan til bo'lmasa — matn bo'yicha aniqlanadi.
    ru_text = ("Привет! Напиши пожалуйста красивый пост для моего канала "
               "про утренний кофе и продажи.")
    en_text = ("Hello! Please write a nice post for my channel about morning "
               "coffee and sales, and add a call to action.")
    check("matndan ruscha aniqlanadi", ai_agent.detect_text_lang(ru_text) == "ru",
          str(ai_agent.detect_text_lang(ru_text)))
    check("matndan inglizcha aniqlanadi", ai_agent.detect_text_lang(en_text) == "en",
          str(ai_agent.detect_text_lang(en_text)))
    check("tanlovsiz: ruscha matn → ru", ai_agent.resolve_ai_lang(None, ru_text) == "ru")
    check("tanlovsiz: inglizcha matn → en", ai_agent.resolve_ai_lang(None, en_text) == "en")
    check("tanlovsiz: qisqa matn → uz (xavfsiz)",
          ai_agent.resolve_ai_lang(None, "salom") == "uz")
    check("resolve_ai_lang hech qachon None qaytarmaydi",
          ai_agent.resolve_ai_lang(None, None) in SUPPORTED_LANGS)

    # 3) detect_text_lang — noto'g'ri tur (None/raqam) bilan ham xavfsiz.
    check("detect_text_lang(None) xavfsiz", ai_agent.detect_text_lang(None) is None)
    check("detect_text_lang(123) xavfsiz", ai_agent.detect_text_lang(123) is None)


def test_vision_prompt_per_language():
    """Vision (rasm → post) promptlari ham foydalanuvchi tilida."""
    print("== 11. Vision promptlari (3 til) ==")
    from utils import ai_agent

    for name, table in (("_VISION_SYSTEMS", ai_agent._VISION_SYSTEMS),
                        ("_VISION_REWRITE_SYSTEMS", ai_agent._VISION_REWRITE_SYSTEMS)):
        for code in SUPPORTED_LANGS:
            prompt = table.get(code) or ""
            check(f"{name}/{code}: mavjud va uzun", len(prompt) > 100, str(len(prompt)))
            check(f"{name}/{code}: JSON kontrakti", '"post_text"' in prompt)
    check("vision RU — kirill", bool(CYRILLIC.search(ai_agent._VISION_SYSTEMS["ru"])))
    check("vision EN — kirill yo'q", not CYRILLIC.search(ai_agent._VISION_SYSTEMS["en"]))

    # generate_vision_post tilni promptga biriktiradi (kalit so'zlar orqali).
    for code in SUPPORTED_LANGS:
        prompt = ai_agent.with_language(ai_agent._VISION_SYSTEMS[code], code)
        check(f"vision/{code}: til bloki birikadi", AI_LANGUAGE_RULES[code] in prompt)


def test_ai_service_language_enforcement():
    """``services/ai_service.py`` — orkestrator darajasidagi yakuniy himoya."""
    print("== 12. ai_service: til qoidasini qat'iy qo'llash ==")
    from services import ai_service

    base = "Siz SMM mutaxassisisiz."
    for code in SUPPORTED_LANGS:
        out = ai_service.enforce_system_language(base, code)
        check(f"{code}: enforce_system_language qoida qo'shadi",
              AI_LANGUAGE_RULES[code] in out, out[:120])
        twice = ai_service.enforce_system_language(out, code)
        check(f"{code}: enforce idempotent", twice == out, f"{len(out)} → {len(twice)}")
    check("lang=None → prompt o'zgarmaydi",
          ai_service.enforce_system_language(base, None) == base)
    check("lang='' → prompt o'zgarmaydi",
          ai_service.enforce_system_language(base, "") == base)

    # run_ai_chain(lang=...) orqali til bloki provayderga yetib boradi.
    seen = {}

    class _FakeProvider:
        name = "Fake"

        def is_available(self):
            return True

        async def complete(self, prompt, system_instruction, params, deadline=None):
            seen["system_instruction"] = system_instruction
            return {"post_text": "ok"}

    from utils import ai_agent
    service = ai_service.AIFallbackService(providers=[_FakeProvider()])
    for code in SUPPORTED_LANGS:
        ai_agent._BREAKERS.clear()
        seen.clear()
        res = asyncio.run(service.generate("Salom", base, lang=code))
        check(f"{code}: orkestrator javobi", res.get("post_text") == "ok", str(res)[:80])
        check(f"{code}: provayderga til bloki yetib bordi",
              AI_LANGUAGE_RULES[code] in (seen.get("system_instruction") or ""),
              str(seen.get("system_instruction"))[:120])

    # Yakuniy API: run_ai_chain ham lang qabul qiladi.
    ai_service.reset_default_service()
    import inspect as _inspect
    params = _inspect.signature(ai_service.run_ai_chain).parameters
    check("run_ai_chain: lang parametri bor", "lang" in params, str(list(params)))

    # Graceful xato xabari ham tilga mos.
    err = ai_service._graceful_error(["Gemini: timeout (10s)"], "ru")
    check("graceful xato (ru) — ruscha", "ИИ" in (err.get("error") or ""),
          str(err.get("error"))[:80])
    err_en = ai_service._graceful_error(["Gemini: timeout (10s)"], "en")
    check("graceful xato (en) — inglizcha",
          "not responding" in (err_en.get("error") or "").lower(),
          str(err_en.get("error"))[:80])


# ================================================================
# III. TIL O'ZGARGANDA PASTKI KLAVIATURA
# ================================================================
class _FakeMessage:
    """Telegram Message o'rnini bosuvchi (yuborilgan xabarlar yozib boriladi)."""

    def __init__(self, chat_id=111, message_id=1):
        self.chat_id = chat_id
        self.message_id = message_id
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append((text, reply_markup, parse_mode))
        return _FakeMessage(self.chat_id, self.message_id + 1)


class _FakeQuery:
    """CallbackQuery o'rnini bosuvchi (edit/reply yozib boriladi)."""

    def __init__(self, data, user_id=555, chat_id=111):
        self.data = data
        self.from_user = type("U", (), {"id": user_id})()
        self.message = _FakeMessage(chat_id=chat_id)
        self.edits = []
        self.answers = []

    async def answer(self, *a, **kw):
        self.answers.append(a)
        return True

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append((text, reply_markup, parse_mode))
        return True


class _FakeContext:
    def __init__(self, user_data=None):
        self.bot = type("B", (), {})()
        self.user_data = user_data if user_data is not None else {}


def test_language_switch_keyboard():
    """Til o'zgarganda pastki klaviatura YANGI tilda yuboriladi."""
    print("== 13. Til almashinuvi: reply-klaviatura yangilanishi ==")
    import database as db_mod
    from handlers.start import (
        send_language_reply_keyboard, switch_user_language,
    )

    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        calls.append((name, args))
        if name == "set_user_language":
            return True
        if name == "get_user_language":
            return "uz"
        if name == "get_user_onboarding":
            return None
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # UX V2 (6-tugma standarti): birinchi tugma — «✨ Kontent yaratish».
        expected = {
            "uz": "✨ Kontent yaratish",
            "ru": "✨ Создать контент",
            "en": "✨ Create content",
        }
        for code, first_btn in expected.items():
            ctx = _FakeContext({"lang": "uz"})
            new_lang = asyncio.run(switch_user_language(ctx, 555, code))
            check(f"{code}: switch_user_language → {code}", new_lang == code, new_lang)
            check(f"{code}: DB'ga yozildi",
                  ("set_user_language", (555, code)) in calls, str(calls[-2:]))
            check(f"{code}: kesh yangilandi", ctx.user_data.get("lang") == code,
                  str(ctx.user_data))

            msg = _FakeMessage()
            asyncio.run(
                send_language_reply_keyboard(msg, ctx, 555, False, code)
            )
            check(f"{code}: yangi klaviatura yuborildi", len(msg.replies) == 1,
                  str(len(msg.replies)))
            text, markup, _mode = msg.replies[0]
            labels = [b.text for row in markup.keyboard for b in row]
            check(f"{code}: pastki menyu yangi tilda", labels[0] == first_btn, str(labels[:2]))
            check(f"{code}: tasdiq xabari yangi tilda",
                  text == safe_t("lang_changed", code), text)
    finally:
        db_mod.run_db = orig


def test_language_callback_scenario():
    """To'liq ssenariy: kabinet → til tugmasi → inline + reply menyu yangi tilda."""
    print("== 14. Ssenariy: cab_lang_* → inline va reply menyu yangi tilda ==")
    import database as db_mod
    from handlers.start import cabinet_callback

    calls = []

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        calls.append((name, args))
        if name == "set_user_language":
            return True
        if name == "get_user_language":
            return "uz"
        if name == "get_referral_stats":
            return {"ai_credits": 12, "referrals_count": 3, "streak": 2}
        if name == "get_user_channels":
            return [("-1001", "Mening kanalim")]
        if name == "get_user_code":
            return "REF123"
        if name == "get_user_onboarding":
            return None
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        # UX V2 (6-tugma standarti): birinchi tugma — «✨ Kontent yaratish».
        expectations = {
            "cab_lang_uz": ("uz", "✨ Kontent yaratish", "🌐 Til / Язык"),
            "cab_lang_ru": ("ru", "✨ Создать контент", "🌐 Til / Язык"),
            "cab_lang_en": ("en", "✨ Create content", "🌐 Language"),
        }
        for data, (code, first_btn, lang_btn) in expectations.items():
            calls.clear()
            ctx = _FakeContext({"lang": "uz"})
            q = _FakeQuery(data, user_id=555)
            upd = type("U", (), {"callback_query": q})()
            asyncio.run(cabinet_callback(upd, ctx))

            check(f"{data}: til bazaga yozildi",
                  ("set_user_language", (555, code)) in calls, str(calls[:4]))
            check(f"{data}: kesh yangilandi", ctx.user_data.get("lang") == code,
                  str(ctx.user_data))
            check(f"{data}: inline menyu qayta chizildi", len(q.edits) == 1,
                  str(len(q.edits)))
            if q.edits:
                _text, inline_kb, _mode = q.edits[0]
                labels = [
                    b.text for row in inline_kb.inline_keyboard for b in row
                ]
                inline_cbs = [
                    b.callback_data for row in inline_kb.inline_keyboard for b in row
                ]
                # 🧹 UI/UX POLISH (1-qadam): kabinet — ixcham 5 tugmali panel;
                # birinchi tugma («🎁 Bonuslar & Taklif») tarjimasi til
                # to'g'riligini tekshiradi.
                check(f"{data}: inline menyu yangi tilda",
                      labels and labels[0] == safe_t("cab_bonus_invite", code),
                      str(labels[:4]))
                check(f"{data}: inline menyuda til tugmasi YO'Q (faqat Sozlamalarda)",
                      "cab_lang" not in inline_cbs, str(inline_cbs))
            check(f"{data}: pastki menyu yangi xabar bilan yuborildi",
                  len(q.message.replies) == 1, str(len(q.message.replies)))
            if q.message.replies:
                text, markup, _mode = q.message.replies[0]
                labels = [b.text for row in markup.keyboard for b in row]
                check(f"{data}: pastki menyu {code} tilida",
                      labels and labels[0] == first_btn, str(labels[:2]))
                check(f"{data}: tasdiq xabari {code} tilida",
                      text == safe_t("lang_changed", code), text)
    finally:
        db_mod.run_db = orig


def test_language_change_then_texts():
    """Til o'zgargach barcha matnlar (get_lang orqali) yangi tilda chiqadi."""
    print("== 15. Til o'zgargach handler matnlari yangi tilda ==")
    from locales.translations import get_lang, set_lang_cache
    from keyboards.default import get_main_keyboard, get_cancel_keyboard

    ctx = _FakeContext({"lang": "uz"})
    check("boshlang'ich til uz", get_lang(ctx) == "uz")

    for code in ("ru", "en", "uz"):
        set_lang_cache(ctx, code)
        check(f"{code}: get_lang yangi tilni qaytaradi", get_lang(ctx) == code)
        kb_labels = [b.text for row in get_main_keyboard(False, lang=get_lang(ctx)).keyboard
                     for b in row]
        cancel_labels = [b.text for row in get_cancel_keyboard(get_lang(ctx)).keyboard
                         for b in row]
        # UX V2: birinchi tugma — «✨ Kontent yaratish» (tilga mos).
        check(f"{code}: menyu matni '{safe_t('btn_create_content', code)}'",
              kb_labels[0] == safe_t("btn_create_content", code), str(kb_labels[:2]))
        check(f"{code}: bekor qilish tugmasi tarjimasi",
              cancel_labels[0] == safe_t("btn_cancel", code), str(cancel_labels))
        # AI Studio / kabinet matnlari ham yangi tilda.
        check(f"{code}: lang_changed matni",
              safe_t("lang_changed", code) != safe_t("lang_changed", "uz") or code == "uz")


def test_language_switch_simple_menu():
    """Onboarding (sodda menyu) rejimida ham klaviatura yangi tilda."""
    print("== 16. Sodda menyu (onboarding) yangi tilda ==")
    import database as db_mod
    from handlers.start import send_language_reply_keyboard
    from locales.en_overlay import EN_OVERLAY as _O  # noqa: F401

    from datetime import datetime as _dt, timedelta as _td

    async def fake_run_db(func, *args, **kwargs):
        name = getattr(func, "__name__", "")
        if name == "get_user_onboarding":
            # Yangi foydalanuvchi (2 soat oldin ro'yxatdan o'tgan) → sodda
            # menyu. Sana DINAMIK: NEW_USER_WINDOW_DAYS (3 kun) oynasidan
            # chiqib ketmasligi uchun (avvalgi qotirilgan sana eskirgan).
            fresh = (_dt.now() - _td(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
            return {"created_at": fresh, "posts_count": 0}
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    try:
        for code in SUPPORTED_LANGS:
            ctx = _FakeContext({"lang": code})
            msg = _FakeMessage()
            asyncio.run(send_language_reply_keyboard(msg, ctx, 777, False, code))
            check(f"{code}: sodda menyu yuborildi", len(msg.replies) == 1)
            if msg.replies:
                _text, markup, _m = msg.replies[0]
                labels = [b.text for row in markup.keyboard for b in row]
                check(f"{code}: sodda menyu 4 ta tugma", len(labels) == 4, str(labels))
                check(f"{code}: sodda menyu tarjimasi",
                      labels[0] == safe_t("quick_btn_ai_post", code), str(labels[:2]))
    finally:
        db_mod.run_db = orig


def main():
    print("=" * 64)
    print("  I. LUG'AT PARITETI (UZ / RU / EN)")
    print("=" * 64)
    test_key_parity()
    test_en_overlay_coverage()
    test_format_args_parity()
    test_safe_t_never_crashes()
    test_button_labels_3_langs()

    print()
    print("=" * 64)
    print("  II. AI TIZIM PROMPTLARI — TIL MOSLASHUVI (ARALASHUVSIZ)")
    print("=" * 64)
    test_single_source_of_truth()
    test_with_language_rules()
    test_router_prompt_per_language()
    test_ai_functions_inject_language()
    test_resolve_ai_lang()
    test_vision_prompt_per_language()
    test_ai_service_language_enforcement()

    print()
    print("=" * 64)
    print("  III. TIL O'ZGARGANDA PASTKI KLAVIATURA YANGILANISHI")
    print("=" * 64)
    test_language_switch_keyboard()
    test_language_callback_scenario()
    test_language_change_then_texts()
    test_language_switch_simple_menu()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha i18n + AI til pariteti testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
