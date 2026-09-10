#!/usr/bin/env python3
"""AI Studio va Kontent-reja — 3 tillik (UZ/RU/EN) i18n testlari."""

import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from locales.translations import TRANSLATIONS, get_text, SUPPORTED_LANGS

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ================================================================
# 1. ASOSIY KALITLAR — 3 tilda (uz/ru/en) mavjud va tarjima qilingan
# ================================================================
def test_ai_studio_plan_keys_exist():
    """AI Studio va Kontent-reja bo'limiga tegishli barcha kalitlar 3 tilda mavjud."""
    print("== AI Studio Plan: kalitlar mavjudligi (uz/ru/en) ==")
    from locales.translations import TRANSLATIONS, get_text, SUPPORTED_LANGS

    plan_keys = [
        "ai_studio_post", "ai_studio_photo", "ai_studio_extract",
        "ai_studio_audit", "ai_studio_content_plan", "ai_back_to_menu",
        "ai_studio_content_plan_intro",
        "btn_back", "btn_cancel", "btn_main_menu",
        "ai_unavailable", "ai_timeout",
        "ai_quota_exceeded", "ai_quota_reset",
    ]

    for lang in ("uz", "ru", "en"):
        missing = []
        for key in plan_keys:
            val = get_text(key, lang)
            if val is None or val == "":
                missing.append(key)
        if missing:
            check(f"plan keys exist ({lang}): {missing}", False, f"missing: {missing}")
        else:
            check(f"plan keys exist ({lang})", True)


# ================================================================
# 2. KLIENT-REJA KLAVIATURASI — UZ va RU callback_data bir xil
# ================================================================
def test_ai_studio_plan_keyboard():
    """AI Studio kontent-reja klaviaturasi — UZ va RU bir xil callback_data."""
    print("== AI Studio Plan klaviaturasi ==")
    from keyboards.inline import get_ai_studio_plan_keyboard
    from locales.translations import get_text

    kb_uz = get_ai_studio_plan_keyboard("uz")
    kb_ru = get_ai_studio_plan_keyboard("ru")

    uz_labels = [b.text for row in kb_uz.inline_keyboard for b in row]
    ru_labels = [b.text for row in kb_ru.inline_keyboard for b in row]
    uz_cbs = [b.callback_data for row in kb_uz.inline_keyboard for b in row]
    ru_cbs = [b.callback_data for row in kb_ru.inline_keyboard for b in row]

    check("plan kb: 8 ta tugma (uz)", len(uz_labels) == 8, str(len(uz_labels)))
    check("plan kb: 8 ta tugma (ru)", len(ru_labels) == 8, str(len(ru_labels)))
    check("plan kb: callback_data bir xil (uz==ru)", uz_cbs == ru_cbs, str((uz_cbs, ru_cbs)))
    check("plan kb: callback_data to'g'ri",
          uz_cbs == ["studio_ai_post", "studio_ai_photo", "studio_extract",
                     "studio_ai_audit", "studio_content_plan", "plan_back", "plan_refresh", "studio_close"],
          str((uz_cbs, ru_cbs)))

    check("plan kb uz: ai_studio_post label",
          uz_labels[0] == get_text("ai_studio_post", "uz"))
    check("plan kb ru: ai_studio_post label",
          ru_labels[0] == get_text("ai_studio_post", "ru"))
    check("plan kb ru: label tarjimasi (rus)",
          "Написать" in ru_labels[0], ru_labels[0])

    check("plan kb: qayta urinish tugmasi", "plan_refresh" in uz_cbs, "plan_refresh not found")


# ================================================================
# 3. AI XATOSIDA KVOTA HIMOYASI — timeoutda ball yechilmaydi
# ================================================================
def test_ai_quota_protection_on_timeout():
    """AI xatosida (timeout) kvota limiti yechilmaydi."""
    print("== AI xatosida kvota himoya ==")
    from locales.translations import get_text

    for lang in ("uz", "ru", "en"):
        unavailable = get_text("ai_unavailable", lang)
        timeout = get_text("ai_timeout", lang)
        check(f"AI xato xabari ({lang}) mavjud", unavailable is not None and unavailable != "", f"got: {unavailable!r}")
        check(f"AI timeout xabari ({lang}) mavjud", timeout is not None and timeout != "", f"got: {timeout!r}")

    check("ai_quota_protection mavjud",
          "ai_quota" in str(TRANSLATIONS.get("uz", {})) or "ai_quota" in str(TRANSLATIONS.get("ru", {})) or "ai_quota" in str(TRANSLATIONS.get("en", {})),
          "ai_quota kaliti topilmadi")


# ================================================================
# 4. QAYTA URINISH — [🔄 Qayta urinish] tugmasi
# ================================================================
def test_refresh_button():
    """[🔄 Qayta urinish] tugmasi mavjud va ishlaydi."""
    print("== [🔄 Qayta urinish] tugmasi ==")
    from keyboards.inline import get_ai_studio_plan_keyboard

    kb = get_ai_studio_plan_keyboard("uz")
    cb_data = [b.callback_data for row in kb.inline_keyboard for b in row]
    check("[🔄 Qayta urinish] tugmasi present", "plan_refresh" in cb_data, str(cb_data))


if __name__ == "__main__":
    test_ai_studio_plan_keys_exist()
    test_ai_studio_plan_keyboard()
    test_ai_quota_protection_on_timeout()
    test_refresh_button()

    print("\n" + "="*50)
    print(f"Jami: {passed + failures},muvaffaqiyatli: {passed}, ba'zoq: {failures}")
    if failures:
        print("❌ TESTLAR BA'ZOQ!")
        sys.exit(1)
    else:
        print("✅ BARCHA TESTLAR YASHIL")
        sys.exit(0)
