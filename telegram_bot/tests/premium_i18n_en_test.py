#!/usr/bin/env python3
"""⭐️ Premium / 💳 to'lov / 📸 chek / 🔒 obuna oqimi — EN i18n regression testlari.

Nima uchun bu fayl bor?
    ``locales/translations.py`` oxirida EN lug'ati alohida yozilmaydi —
    u UZ blokasidan nusxalanib, faqat ``EN_OVERLAY`` kalitlari bilan
    to'ldiriladi::

        TRANSLATIONS["en"] = dict(TRANSLATIONS["uz"])
        TRANSLATIONS["en"].update(EN_OVERLAY)

    Shuning uchun overlay'da BO'LMAGAN har bir kalit EN foydalanuvchisiga
    jimgina **o'zbekcha** matn qaytaradi — bot crash bo'lmaydi, log'da ham
    xato yo'q, lekin UI yarim tarjima bo'ladi. Kalitlar soni (601/601/601)
    bo'yicha parity hisoboti buni KO'RSATMAYDI, chunki kalitlar bor —
    faqat qiymatlar tarjimasi tekshirilishi kerak.

    Aynan shu "jimgina buzilish"ni bu test ushlaydi:

      1. Premium oqimi kalitlarida EN qiymati UZ bilan bir xil bo'lmasin.
      2. Har bir overlay kalitida ``{placeholder}`` to'plami UZ bilan bir xil
         (mos kelmasa — ``get_text`` formatdan qochib UZ'ga qaytadi).
      3. EN matnida o'zbekcha so'z qoldig'i bo'lmasin.
      4. HTML teglari (<b>/<i>/<code>) UZ bilan bir xil sonlarda.
      5. UZ/RU/EN parity buzilmagan bo'lsin.
      6. Reply/inline tugma yorliqlari routing'da tanilishda davom etsin.

Ishga tushirish:
    cd telegram_bot && python tests/premium_i18n_en_test.py
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locales.en_overlay import EN_OVERLAY  # noqa: E402
from locales.translations import (  # noqa: E402
    TRANSLATIONS,
    get_text,
    translation_parity_report,
)

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


# ⭐️ Premium bo'limi, 💳 karta to'lovi, 📸 chek va 🔒 obuna ekranlari kalitlari.
PREMIUM_KEYS = [
    # Premium / tarif
    "btn_premium", "ch_pro_btn", "ad_mode_admin", "ad_mode_pro", "ad_mode_free",
    # AI limitlari (PRO/HUDUD) va kunlik bonus
    "ai_credits_unlimited", "ai_credits_unlimited_pro", "no_credits",
    "daily_bonus_guide", "ai_prompt_hint", "ai_audit_prompt_hint", "ai_time_prompt_hint",
    # ✨ Post enhancer (PRO eslatmalari)
    "enh_note_pro", "enh_again_prompt", "enh_replace_prompt", "enh_edit_prompt",
    "enh_manual_prompt", "enh_preset_prompt", "np_ai_proposal", "np_ai_retry_proposal",
    # 💳 Karta to'lovi
    "btn_card_payment", "card_tariff_title", "card_plan_1m", "card_plan_3m", "card_plan_1y",
    "card_tariff_1m", "card_tariff_3m", "card_tariff_1y", "card_payment_title",
    "card_payment_prices", "card_payment_selected", "card_payment_card",
    "card_payment_no_card", "card_payment_admin_missing", "card_payment_steps",
    # 📸 Chek oqimi
    "btn_send_receipt", "receipt_prompt", "receipt_saved", "receipt_bad_media",
    "receipt_approved_user", "receipt_rejected_user", "receipt_admin_title",
    "receipt_admin_ask", "receipt_admin_already", "receipt_admin_done_ok",
    "receipt_admin_done_reject", "receipt_admin_user_line", "receipt_admin_user_nick_line",
    "receipt_admin_user_id_line", "receipt_admin_tarif_line", "receipt_admin_time_line",
    "receipt_btn_approve", "receipt_btn_reject",
    # 🔒 Kanalga obuna
    "sub_required", "sub_confirmed", "sub_not_yet_alert", "sub_not_yet_msg",
]

# Talab bo'yicha 3 tilda ham BIR XIL yoziladigan kalitlar (brend / ID qatori).
LANG_NEUTRAL = {"btn_premium", "receipt_admin_user_id_line"}

# O'zbekchaga xos so'zlar — EN matnida uchrasa, demak kalit tarjima qilinmagan.
UZ_MARKER_WORDS = (
    " uchun", " bo'ling", " yuboring", " bilan ", " qiling", " tasdiqlandi",
    " tanlang", " sizning", " Sizning", " bo'lmadingiz", " so'rovlar",
)

PH = re.compile(r"\{(\w+)\}")


def placeholders(text):
    return set(PH.findall(str(text)))


def test_premium_en_translated():
    print("== Premium oqimi: EN qiymatlari UZ'dan farq qiladi ==")
    en, uz = TRANSLATIONS["en"], TRANSLATIONS["uz"]
    same = [k for k in PREMIUM_KEYS if k not in LANG_NEUTRAL and str(en.get(k)) == str(uz.get(k))]
    check("barcha Premium/to'lov/obuna kalitlari EN'da tarjima qilingan",
          not same, str(same[:8]))
    missing = [k for k in PREMIUM_KEYS if not str(en.get(k) or "").strip()]
    check("bo'sh EN qiymati yo'q", not missing, str(missing))
    for k in sorted(LANG_NEUTRAL):
        check(f"til-neutral kalit '{k}' 3 tilda ham bir xil",
              str(en.get(k)) == str(uz.get(k)) == str(TRANSLATIONS['ru'].get(k)), k)
    check("Premium kalitlar soni 40 dan katta", len(PREMIUM_KEYS) > 40, str(len(PREMIUM_KEYS)))


def test_no_uz_leak_in_en():
    print("== EN matnida o'zbekcha qoldiq yo'q ==")
    leaked = []
    for k in PREMIUM_KEYS:
        text = str(get_text(k, "en"))
        if any(mark in text for mark in UZ_MARKER_WORDS):
            leaked.append(k)
    check("o'zbekcha so'z qoldig'i topilmadi", not leaked, str(leaked[:8]))


def test_placeholders_match():
    print("== Overlay kalitlarida {placeholder} to'plami UZ bilan bir xil ==")
    uz = TRANSLATIONS["uz"]
    bad = []
    for k, v in EN_OVERLAY.items():
        if k not in uz:
            continue
        if placeholders(v) != placeholders(uz[k]):
            bad.append((k, sorted(placeholders(uz[k])), sorted(placeholders(v))))
    check(f"{len(EN_OVERLAY)} ta overlay kalitining format ko'rsatkichlari mos",
          not bad, str(bad[:5]))
    orphans = [k for k in EN_OVERLAY if k not in uz]
    check("overlay'da UZ'da bo'lmagan (yetim) kalit yo'q", not orphans, str(orphans[:5]))


def test_html_tags_and_format_safety():
    print("== HTML teglari va format xavfsizligi ==")
    uz = TRANSLATIONS["uz"]
    tag_bad, fmt_bad = [], []
    for k, v in EN_OVERLAY.items():
        if k not in uz:
            continue
        for tag in ("b", "i", "code"):
            if str(v).count(f"<{tag}>") != str(uz[k]).count(f"<{tag}>") or \
               str(v).count(f"</{tag}>") != str(uz[k]).count(f"</{tag}>"):
                tag_bad.append((k, tag))
                break
        phs = placeholders(v)
        try:
            out = str(v).format(**{p: "X" for p in phs})
            if "{" in out or "}" in out:
                fmt_bad.append((k, "leftover"))
        except Exception as exc:  # noqa: BLE001
            fmt_bad.append((k, repr(exc)))
    check("HTML teglari (<b>/<i>/<code>) UZ bilan bir xil", not tag_bad, str(tag_bad[:5]))
    check("formatlash xatosiz o'tadi va qavs qoldirmaydi", not fmt_bad, str(fmt_bad[:5]))
    # get_text hech qachon kalit nomini qaytarmasin (fallback'ga tushmasin)
    keyfall = [k for k in PREMIUM_KEYS if get_text(k, "en") == k]
    check("EN'da kalit nomi ekran ko'rinishida chiqmaydi", not keyfall, str(keyfall[:5]))


def test_parity_intact():
    print("== UZ/RU/EN pariteti buzilmagan ==")
    rep = translation_parity_report()
    check("in_sync True", rep["in_sync"] is True, str(rep))
    check("uz_only bo'sh", not rep["uz_only"], str(rep["uz_only"][:5]))
    check("ru_only bo'sh", not rep["ru_only"], str(rep["ru_only"][:5]))
    sizes = {L: len(TRANSLATIONS[L]) for L in ("uz", "ru", "en")}
    check("3 tilning kalitlar soni teng", len(set(sizes.values())) == 1, str(sizes))
    check("EN overlay kalitlari soni 100+ (Premium bilan birga)",
          len(TRANSLATIONS["en"]) >= 600, str(sizes))


def test_button_labels_still_routed():
    """EN yorliqlar o'zgarganda routing sinmasligi kerak.

    ⚠️ Bu test i18n fix'lari uchun MUHIM: agar EN reply-tugma yorligi UZ/RU'dan
    farq qilsa-yu handler faqat UZ/RU konstantalarini tansa, EN foydalanuvchining
    bosishi global fallback'ga tushib qoladi.
    """
    print("== EN tugma yorliqlari routing'da taniladi ==")
    kb = (ROOT / "keyboards" / "default.py").read_text(encoding="utf-8")
    h = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("BTN_PREMIUM_EN aniqlangan", "BTN_PREMIUM_EN = get_text(\"btn_premium\", \"en\")" in kb)
    check("Premium tugmasi EN routing'da", "BTN_PREMIUM_EN" in h and "exact(BTN_PREMIUM_EN)" in h)
    # To'lov/chek tugmalari — inline (callback_data orqali), matn bo'yicha tanalmaydi.
    sub = (ROOT / "handlers" / "subscription.py").read_text(encoding="utf-8")
    check("btn_card_payment inline — callback_data sub_card_pay",
          "get_text(\"btn_card_payment\", lang)" in sub and "sub_card_pay" in sub)
    check("btn_send_receipt inline — callback_data sub_send_receipt",
          "get_text(\"btn_send_receipt\", lang)" in sub and "sub_send_receipt" in sub)
    # Inline tugma matni 64 bayt cheklovi (callback_data) ga ta'sir qilmaydi,
    # lekin tugma matni bo'sh bo'lmasin.
    for key in ("btn_card_payment", "btn_send_receipt", "ch_pro_btn", "receipt_btn_approve"):
        check(f"EN tugma matni bo'sh emas: {key}",
              bool(get_text(key, "en").strip()) and get_text(key, "en") != key, key)


def main():
    test_premium_en_translated()
    test_no_uz_leak_in_en()
    test_placeholders_match()
    test_html_tags_and_format_safety()
    test_parity_intact()
    test_button_labels_still_routed()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha Premium/EN i18n testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
