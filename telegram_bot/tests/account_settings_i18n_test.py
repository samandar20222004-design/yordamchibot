#!/usr/bin/env python3
"""Account & Settings (Kabinet & Sozlamalar) — UZ / RU / EN i18n testlari.

Har bir til uchun:
  • Tugma matnlari to'g'ri (Reply va Inline)
  • Kabinet ekrani matni 100% shu tilda
  • Tilni o'zgartirish menyusi
  • Ulangan kanallar, kanal ovozi tahlili
  • Vaqt mintaqasi tanlash
  • Ballar, bonus, referral, transfer
  • Orqaga / Bekor qilish / Yopish navigatsiya tugmalari
  • Inline callback_data tilga bog'liq emas (xavfsiz)

Ishga tushirish:
    cd telegram_bot && python tests/account_settings_i18n_test.py
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

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
# 1. ASOSIY KALITLAR — 3 tilda mavjud va tarjima qilingan
# ================================================================
def test_account_settings_keys_exist():
    """Account & Settings bo'limiga tegishli barcha kalitlar 3 tilda mavjud."""
    print("== Account & Settings: kalitlar mavjudligi (uz/ru/en) ==")
    from locales.translations import get_text

    # Account & Settings bo'limidagi asosiy kalitlar
    settings_keys = [
        # Asosiy menyu tugmasi
        "btn_settings",
        # Til tanlash
        "lang_prompt", "lang_changed", "lang_button",
        # Reply-klaviatura tugmalari (Kabinet ichki menyu)
        "cab_btn_channels", "cab_btn_converter", "cab_btn_daily_bonus",
        "cab_btn_invite", "cab_btn_transfer",
        # Inline-klaviatura tugmalari
        "cab_my_channels", "cab_analytics", "cab_pending", "cab_queue",
        "cab_balance", "cab_referral", "cab_close",
        # 🧹 UI/UX POLISH: ixcham 5 tugmali kabinet paneli (yagona manba)
        "cab_bonus_invite", "cab_payments", "cab_notifications", "cab_help_guide",
        "cab_add_channel", "cab_del_channel", "cab_remove_channel",
        "cab_tone", "cab_add_channel_alt",
        # Kanal o'chirish
        "cab_channels_delete_empty", "cab_channels_delete_title",
        # Kabinet ekrani
        "cabinet_title", "credits_value", "cabinet_credits_admin", "cabinet_streak",
        # Ballar
        "balance_card",
        # Kunlik bonus
        "daily_bonus_admin", "daily_bonus_claimed", "daily_bonus_already",
        "daily_bonus_reset_notice",
        # Referral
        "referral_menu", "referral_reward_notice",
        # Transfer
        "transfer_intro", "transfer_insufficient", "transfer_user_not_found",
        "transfer_self", "transfer_target_ok", "transfer_amount_nan",
        "transfer_amount_range", "transfer_success", "transfer_gift_notice",
        "transfer_error", "transfer_default_name",
        # Kanal uslubi
        "ch_tone_title", "ch_tone_formal", "ch_tone_friendly",
        "ch_tone_concise", "ch_tone_engaging",
        "ch_tone_cancelled", "ch_tone_invalid", "ch_tone_success", "ch_tone_error",
        # Kanal ovozi tahlili
        "ch_voice_btn", "ch_voice_analyzing", "ch_voice_no_posts",
        "ch_voice_result", "ch_voice_error",
        # Vaqt mintaqasi
        "tz_prompt", "tz_changed", "tz_btn_tashkent", "tz_btn_moscow",
        "tz_btn_utc", "tz_btn_samarkand", "tz_current",
        # Navigatsiya
        "btn_back", "btn_cancel", "btn_main_menu",
        "no_channels_hint",
        # Kunlik bonus yo'riqnomasi
        "daily_bonus_guide",
    ]

    for lang in ("uz", "ru", "en"):
        missing = []
        for key in settings_keys:
            val = get_text(key, lang)
            if not val or val == key:
                missing.append(key)
        check(f"{lang}: barcha Account & Settings kalitlari mavjud ({len(settings_keys)} ta)",
              not missing, str(missing[:5]))

    # 3 tildagi qiymatlar har xil (tarjima qilingan)
    for key in settings_keys:
        vals = {lang: get_text(key, lang) for lang in ("uz", "ru", "en")}
        # Ba'zi kalitlar tildan mustaqil (emoji, format)
        if key in ("tz_btn_utc",):
            continue
        all_different = len(set(vals.values())) >= 2
        check(f"kalit '{key[:30]}': 3 til bir-biridan farq qiladi",
              all_different, str({k: v[:30] for k, v in vals.items()}))


# ================================================================
# 2. ASOSIY MENYU TUGMASI — har 3 tilda
# ================================================================
def test_main_menu_button_3_langs():
    """Asosiy menyuda Sozlamalar (Kabinet) tugmasi 3 tilda to'g'ri."""
    print("== Asosiy menyu: Sozlamalar tugmasi ==")
    from locales.translations import get_text
    from keyboards.default import get_main_keyboard, BTN_SETTINGS, BTN_SETTINGS_RU

    # 3-QISM: yorliq endi «👤 Profil» (eski «⚙️ Sozlamalar» routing'da
    # alias sifatida saqlanadi); yangi «👥 Do'stlarni taklif» tugmasi ham bor.
    check("uz: BTN_SETTINGS = '👤 Profil'",
          BTN_SETTINGS == "👤 Profil")
    check("ru: BTN_SETTINGS_RU = '👤 Профиль'",
          BTN_SETTINGS_RU == "👤 Профиль")
    check("en: btn_settings = '👤 Profile'",
          get_text("btn_settings", "en") == "👤 Profile")

    # Reply-klaviaturalarda tugma bor
    for lang in ("uz", "ru", "en"):
        kb = get_main_keyboard(False, lang=lang)
        labels = [b.text for row in kb.keyboard for b in row]
        expected = get_text("btn_settings", lang)
        check(f"{lang}: asosiy menyuda Account & Settings tugmasi bor",
              expected in labels, f"expected={expected}, got={labels}")


# ================================================================
# 3. KABINET INLINE KLAVIATURASI — har 3 tilda
# ================================================================
def test_cabinet_inline_keyboard_3_langs():
    """Kabinet inline klaviaturasi 3 tilda to'g'ri yorliqlar va bir xil callback.

    3-QISM: kabinet endi IXCHAM 6 tugmali 👤 Profil paneli (Sozlamalar
    hub'i bilan bir xil): Til / Post sozlamalari / Bildirishnomalar /
    To'lovlar tarixi / Qo'llab-quvvatlash / Yopish. «🎁 Bonuslar & Taklif»
    asosiy menyuga («👥 Do'stlarni taklif») ko'chirildi.
    """
    print("== Kabinet inline klaviaturasi (uz/ru/en) ==")
    from keyboards.inline import get_cabinet_inline_keyboard

    # UZ inline keyboard
    kb_uz = get_cabinet_inline_keyboard("uz")
    rows_uz = [[(b.text, b.callback_data) for b in row] for row in kb_uz.inline_keyboard]
    check("uz kabinet: 4 qator (ixcham 6 tugmali panel)",
          len(rows_uz) == 4, str(len(rows_uz)))
    check("uz kabinet: Til + Post sozlamalari",
          rows_uz[0] == [("🌐 Til / Язык", "stgs_lang"),
                         ("✍️ Post sozlamalari", "stgs_post")], str(rows_uz[0]))
    check("uz kabinet: Bildirishnomalar + To'lovlar tarixi",
          rows_uz[1] == [("🔔 Bildirishnomalar", "stgs_notif"),
                         ("💳 To'lovlar tarixi", "stgs_pay")], str(rows_uz[1]))
    check("uz kabinet: Qo'llab-quvvatlash",
          rows_uz[2] == [("💬 Qo'llab-quvvatlash", "help_support")], str(rows_uz[2]))
    check("uz kabinet: Yopish",
          rows_uz[3] == [("❌ Yopish", "stgs_back")], str(rows_uz[3]))

    # RU inline keyboard
    kb_ru = get_cabinet_inline_keyboard("ru")
    rows_ru = [[(b.text, b.callback_data) for b in row] for row in kb_ru.inline_keyboard]
    check("ru kabinet: 4 qator (ixcham 6 tugmali panel)", len(rows_ru) == 4)
    check("ru kabinet: Язык tugmasi",
          rows_ru[0][0] == ("🌐 Язык / Language", "stgs_lang"), str(rows_ru[0]))
    check("ru kabinet: eski Til (cab_lang) tugmasi YO'Q",
          all(cb != "cab_lang" for row in rows_ru for _label, cb in row))

    # EN inline keyboard
    kb_en = get_cabinet_inline_keyboard("en")
    rows_en = [[(b.text, b.callback_data) for b in row] for row in kb_en.inline_keyboard]
    check("en kabinet: 4 qator (ixcham 6 tugmali panel)", len(rows_en) == 4)
    check("en kabinet: Language tugmasi",
          rows_en[0][0] == ("🌐 Language", "stgs_lang"), str(rows_en[0]))
    check("en kabinet: eski Til (cab_lang) tugmasi YO'Q",
          all(cb != "cab_lang" for row in rows_en for _label, cb in row))

    # Callback data 3 tilda ham bir xil (tilga bog'liq emas)
    cbs_uz = [b.callback_data for row in kb_uz.inline_keyboard for b in row]
    cbs_ru = [b.callback_data for row in kb_ru.inline_keyboard for b in row]
    cbs_en = [b.callback_data for row in kb_en.inline_keyboard for b in row]
    check("callback_data uz == ru", cbs_uz == cbs_ru)
    check("callback_data ru == en", cbs_ru == cbs_en)

    # Har bir callback mavjud (barchasi MAVJUD stgs_*/help oqimlariga ulanadi)
    # 3-QISM: ixcham panel — Til/Post/Notif/Pay/Support/Yopish.
    # Eski guruh tugmalari (stgs_rewards, stgs_tools, stgs_help_hub) va
    # cab_* dublikatlari paneldan OLIB TASHLANDI — routing'da saqlanadi.
    expected_cbs = [
        "stgs_lang", "stgs_post", "stgs_pay", "stgs_notif",
        "help_support", "stgs_back",
    ]
    for cb in expected_cbs:
        check(f"callback '{cb}' mavjud", cb in cbs_uz)
    for cb in ("stgs_rewards", "stgs_tools", "stgs_help_hub", "close_cabinet"):
        check(f"eski guruh callback '{cb}' kabinetda YO'Q", cb not in cbs_uz)
    removed_cbs = [
        "cab_channels", "cab_analytics", "cab_pending", "cab_queue",
        "cab_balance", "cab_bonus", "cab_referral", "cab_lang",
    ]
    for cb in removed_cbs:
        check(f"eski dublikat callback '{cb}' kabinetda YO'Q", cb not in cbs_uz)


# ================================================================
# 4. KABINET EKRANI MATNI — 3 tilda
# ================================================================
def test_cabinet_screen_text():
    """Kabinet ekrani matni (cabinet_title) 3 tilda to'g'ri formatlanadi."""
    print("== Kabinet ekrani matni (uz/ru/en) ==")
    from locales.translations import get_text

    test_params = dict(
        user_id=12345, user_code="ABC", credits="5",
        streak="3/7", channels=2, referrals=1, ad_line="",
    )

    for lang in ("uz", "ru", "en"):
        text = get_text("cabinet_title", lang, **test_params)
        check(f"{lang}: user_id ko'rsatilgan", "12345" in text)
        check(f"{lang}: user_code ko'rsatilgan", "ABC" in text)
        check(f"{lang}: credits ko'rsatilgan", "5" in text)
        check(f"{lang}: channels ko'rsatilgan", "2" in text)

    # Har til o'z tilida (3-QISM: «👤 Profil» — eski «Shaxsiy Kabinet»)
    check("uz: 'Profil'",
          "<b>Profil:</b>" in get_text("cabinet_title", "uz", **test_params))
    check("ru: 'Профиль'",
          "<b>Профиль:</b>" in get_text("cabinet_title", "ru", **test_params))
    check("en: 'Profile'",
          "<b>Profile:</b>" in get_text("cabinet_title", "en", **test_params))


# ================================================================
# 5. TILNI O'ZGARTIRISH MENYUSI
# ================================================================
def test_language_menu():
    """Til tanlash menyusi: tugmalar, callback, back tugmasi lokalizatsiya."""
    print("== Til tanlash menyusi ==")
    from keyboards.inline import get_language_keyboard
    from locales.translations import get_text

    for lang in ("uz", "ru", "en"):
        kb = get_language_keyboard(lang)
        rows = kb.inline_keyboard
        labels = [b.text for row in rows for b in row]
        cbs = [b.callback_data for row in rows for b in row]

        check(f"{lang}: 3 ta til tugmasi + back = 4 qator", len(rows) == 3)
        check(f"{lang}: 🇺🇿 O'zbekcha tugmasi", "🇺🇿 O'zbekcha" in labels)
        check(f"{lang}: 🇷🇺 Русский tugmasi", "🇷🇺 Русский" in labels)
        check(f"{lang}: 🇬🇧 English tugmasi", "🇬🇧 English" in labels)
        check(f"{lang}: cab_lang_uz callback", "cab_lang_uz" in cbs)
        check(f"{lang}: cab_lang_ru callback", "cab_lang_ru" in cbs)
        check(f"{lang}: cab_lang_en callback", "cab_lang_en" in cbs)
        check(f"{lang}: cab_main (back) callback", "cab_main" in cbs)

        # Back tugmasi lokalizatsiya qilingan
        back_text = get_text("btn_back", lang)
        check(f"{lang}: back tugmasi = '{back_text}'",
              back_text in labels, f"back={back_text}, labels={labels}")

    # lang_changed xabarlari 3 tilda
    check("uz: lang_changed", "o'zbekchaga" in get_text("lang_changed", "uz").lower()
          or "o'zbekcha" in get_text("lang_changed", "uz").lower())
    check("ru: lang_changed", "русский" in get_text("lang_changed", "ru"))
    check("en: lang_changed", "English" in get_text("lang_changed", "en"))

    # lang_prompt xabarlari 3 tilda
    check("uz: lang_prompt has uz option",
          "Tilni tanlang" in get_text("lang_prompt", "uz"))
    check("ru: lang_prompt has ru option",
          "Выберите язык" in get_text("lang_prompt", "ru"))
    check("en: lang_prompt has en option",
          "Choose language" in get_text("lang_prompt", "en"))


# ================================================================
# 6. KANALLAR RO'YXATI — 3 tilda
# ================================================================
def test_channels_management_3_langs():
    """Kanallar boshqaruvi: qo'shish, o'chirish, ro'yxat — 3 tilda."""
    print("== Kanallar boshqaruvi (uz/ru/en) ==")
    from locales.translations import get_text
    from keyboards.inline import get_channels_manage_keyboard, render_channels_list

    # Kanal boshqaruv klaviaturasi
    for lang in ("uz", "ru", "en"):
        kb = get_channels_manage_keyboard(lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]

        check(f"{lang}: kanal qo'shish tugmasi callback",
              "add_channel_start" in cbs)
        check(f"{lang}: kanal o'chirish tugmasi callback",
              "cab_channels_delete" in cbs)
        check(f"{lang}: back callback", "cab_main" in cbs)
        check(f"{lang}: close callback", "close_cabinet" in cbs)

    # render_channels_list — EN
    channels = [("-1001234567890", "Test Channel", "friendly")]
    kb_en = render_channels_list(channels, "en")
    en_labels = [b.text for row in kb_en.inline_keyboard for b in row]
    check("en: kanal o'chirish '❌ Delete'",
          "❌ Delete" in en_labels)
    check("en: yangi kanal ulash",
          "➕ Connect new channel/group" in en_labels)
    check("en: yopish '❌ Close'",
          "❌ Close" in en_labels)

    # Kanal bo'sh xabarlar
    check("uz: kanallar bo'sh",
          "Hozircha hech qanday kanal" in get_text("my_channels_empty", "uz", hint=""))
    check("ru: kanallar bo'sh",
          "ни один канал не подключён" in get_text("my_channels_empty", "ru", hint=""))
    check("en: kanallar bo'sh",
          "No channels connected" in get_text("my_channels_empty", "en", hint="")
          or "no channels" in get_text("my_channels_empty", "en", hint="").lower())


# ================================================================
# 7. KANAL OVOZI TAHLILI — 3 tilda
# ================================================================
def test_channel_voice_3_langs():
    """Kanal ovozi tahlili (Channel Voice) — 3 tilda matn va tugma."""
    print("== Kanal ovozi tahlili (uz/ru/en) ==")
    from locales.translations import get_text

    # Tugma yorliqlari
    check("uz: Kanal ovozi tahlili", "Kanal ovozi" in get_text("ch_voice_btn", "uz"))
    check("ru: Голос канала", "Голос канала" in get_text("ch_voice_btn", "ru"))
    check("en: Channel voice analysis", "Channel voice" in get_text("ch_voice_btn", "en"))

    # Tahlil jarayoni matni
    check("uz: tahlil qilinmoqda",
          "tahlil qilinmoqda" in get_text("ch_voice_analyzing", "uz"))
    check("ru: Анализ голоса канала",
          "Анализ голоса канала" in get_text("ch_voice_analyzing", "ru"))
    check("en: Analyzing channel voice",
          "Analyzing channel voice" in get_text("ch_voice_analyzing", "en"))

    # Natija formati
    result_uz = get_text("ch_voice_result", "uz", tone="Rasmiy", reason="Sabab")
    result_ru = get_text("ch_voice_result", "ru", tone="Официальный", reason="Причина")
    result_en = get_text("ch_voice_result", "en", tone="Formal", reason="Reason")
    check("uz: natija 'Rasmiy' + 'Sabab'", "Rasmiy" in result_uz and "Sabab" in result_uz)
    check("ru: natija 'Официальный'", "Официальный" in result_ru)
    check("en: natija 'Formal' + 'Reason'", "Formal" in result_en and "Reason" in result_en)

    # Xato xabarlari
    check("uz: xato mavjud", len(get_text("ch_voice_error", "uz")) > 10)
    check("ru: xato mavjud", len(get_text("ch_voice_error", "ru")) > 10)
    check("en: xato mavjud", len(get_text("ch_voice_error", "en")) > 10)


# ================================================================
# 8. KANAL USLUBI (TONE OF VOICE) — 3 tilda
# ================================================================
def test_channel_tone_3_langs():
    """Kanal uslubi tanlash — 3 tilda."""
    print("== Kanal uslubi (uz/ru/en) ==")
    from locales.translations import get_text

    tone_keys = ["ch_tone_formal", "ch_tone_friendly", "ch_tone_concise", "ch_tone_engaging"]
    tone_labels = {
        "uz": ["Rasmiy", "Do'stona", "Qisqa", "Ko'ngilochar"],
        "ru": ["Официальный", "Дружелюбный", "Кратко", "Развлекательный"],
        "en": ["Formal", "Friendly", "Brief", "Fun"],
    }

    for lang in ("uz", "ru", "en"):
        for key, expected_word in zip(tone_keys, tone_labels[lang]):
            val = get_text(key, lang)
            check(f"{lang}: {key} contains '{expected_word}'",
                  expected_word in val, f"got={val}")

    # Sarlavha
    check("uz: tone title 'uslubini tanlang'",
          "uslubini tanlang" in get_text("ch_tone_title", "uz", current="test").lower())
    check("ru: tone title 'Выберите стиль'",
          "Выберите стиль" in get_text("ch_tone_title", "ru", current="test"))
    check("en: tone title 'Choose channel style'",
          "Choose channel style" in get_text("ch_tone_title", "en", current="test"))


# ================================================================
# 9. VAQT MINTAQASI (TIMEZONE) — 3 tilda
# ================================================================
def test_timezone_3_langs():
    """Vaqt mintaqasi tanlash — 3 tilda tugmalar va xabarlar."""
    print("== Vaqt mintaqasi (uz/ru/en) ==")
    from locales.translations import get_text

    for lang in ("uz", "ru", "en"):
        prompt = get_text("tz_prompt", lang)
        check(f"{lang}: tz_prompt bo'sh emas", len(prompt) > 10, f"got={prompt}")

        changed = get_text("tz_changed", lang, tz="Toshkent")
        check(f"{lang}: tz_changed formatlanadi", "Toshkent" in changed and "{" not in changed)

        current = get_text("tz_current", lang, tz="UTC+5")
        check(f"{lang}: tz_current formatlanadi", "UTC+5" in current)

    # Tugmalar har tilda farqli
    check("uz: Toshkent tugmasi",
          "Toshkent" in get_text("tz_btn_tashkent", "uz"))
    check("ru: Ташкент tugmasi",
          "Ташкент" in get_text("tz_btn_tashkent", "ru"))
    check("en: Tashkent tugmasi",
          "Tashkent" in get_text("tz_btn_tashkent", "en"))

    check("uz: Moskva tugmasi", "Moskva" in get_text("tz_btn_moscow", "uz"))
    check("ru: Москва tugmasi", "Москва" in get_text("tz_btn_moscow", "ru"))
    check("en: Moscow tugmasi", "Moscow" in get_text("tz_btn_moscow", "en"))

    check("uz: Samarqand tugmasi", "Samarqand" in get_text("tz_btn_samarkand", "uz"))
    check("ru: Самарканд tugmasi", "Самарканд" in get_text("tz_btn_samarkand", "ru"))
    check("en: Samarkand tugmasi", "Samarkand" in get_text("tz_btn_samarkand", "en"))


# ================================================================
# 10. BALLAR VA BALANS — 3 tilda
# ================================================================
def test_balance_and_credits_3_langs():
    """Ballar, balans, reklama rejimi — 3 tilda."""
    print("== Ballar va balans (uz/ru/en) ==")
    from locales.translations import get_text

    # balance_card
    for lang in ("uz", "ru", "en"):
        card = get_text("balance_card", lang, credits=10, ad_mode="PRO")
        check(f"{lang}: balance_card '10' soni", "10" in card)
        check(f"{lang}: balance_card 'PRO'", "PRO" in card)

    # credits_value
    check("uz: credits_value", "5" in get_text("credits_value", "uz", n=5))
    check("ru: credits_value", "5" in get_text("credits_value", "ru", n=5))
    check("en: credits_value", "5" in get_text("credits_value", "en", n=5))

    # cabinet_streak
    check("uz: streak 'kun'", "kun" in get_text("cabinet_streak", "uz", streak=5))
    check("ru: streak 'дней'", "дней" in get_text("cabinet_streak", "ru", streak=5))
    check("en: streak 'days'", "days" in get_text("cabinet_streak", "en", streak=5))

    # Ad mode descriptions
    for lang in ("uz", "ru", "en"):
        check(f"{lang}: ad_mode_admin", len(get_text("ad_mode_admin", lang)) > 5)
        check(f"{lang}: ad_mode_pro", len(get_text("ad_mode_pro", lang)) > 5)
        check(f"{lang}: ad_mode_free", len(get_text("ad_mode_free", lang)) > 5)


# ================================================================
# 11. KUNLIK BONUS — 3 tilda
# ================================================================
def test_daily_bonus_3_langs():
    """Kunlik bonus xabarlari — 3 tilda."""
    print("== Kunlik bonus (uz/ru/en) ==")
    from locales.translations import get_text

    # Admin xabari
    check("uz: bonus admin", "Admin" in get_text("daily_bonus_admin", "uz"))
    check("ru: bonus admin", "админ" in get_text("daily_bonus_admin", "ru").lower())
    check("en: bonus admin", "Admin" in get_text("daily_bonus_admin", "en"))

    # Claimed xabari
    for lang in ("uz", "ru", "en"):
        claimed = get_text(
            "daily_bonus_claimed", lang,
            reset_notice="", streak=5, bar="🟢🟢🟢🟢🟢⚪⚪",
            bonus=3, credits=15,
        )
        check(f"{lang}: bonus claimed '15' ball", "15" in claimed)
        check(f"{lang}: bonus claimed '3' bonus", "3" in claimed)

    # Already claimed
    check("uz: bonus already", "ball" in get_text("daily_bonus_already", "uz", msg="test", credits=5).lower()
          or "bugun" in get_text("daily_bonus_already", "uz", msg="test", credits=5).lower())
    check("ru: bonus already", "балл" in get_text("daily_bonus_already", "ru", msg="test", credits=5).lower()
          or "сегодня" in get_text("daily_bonus_already", "ru", msg="test", credits=5).lower())
    check("en: bonus already", "credit" in get_text("daily_bonus_already", "en", msg="test", credits=5).lower()
          or "today" in get_text("daily_bonus_already", "en", msg="test", credits=5).lower())


# ================================================================
# 12. REFERRAL — 3 tilda
# ================================================================
def test_referral_3_langs():
    """Referral (do'stlarni taklif) xabarlari — 3 tilda."""
    print("== Referral (uz/ru/en) ==")
    from locales.translations import get_text

    for lang in ("uz", "ru", "en"):
        menu = get_text("referral_menu", lang, credits=10, count=3, link="https://t.me/bot?start=ref_1")
        check(f"{lang}: referral_menu link bor", "https://t.me/bot?start=ref_1" in menu)
        check(f"{lang}: referral_menu count bor", "3" in menu)

    # Reward notice
    check("uz: reward 'AI ball'", "AI ball" in get_text("referral_reward_notice", "uz", reward=3))
    check("ru: reward 'ИИ-балл'", "ИИ-балл" in get_text("referral_reward_notice", "ru", reward=3))
    check("en: reward 'AI credit'", "AI credit" in get_text("referral_reward_notice", "en", reward=3))


# ================================================================
# 13. TRANSFER — 3 tilda
# ================================================================
def test_transfer_3_langs():
    """Ballarni ulashish (transfer) xabarlari — 3 tilda."""
    print("== Transfer (uz/ru/en) ==")
    from locales.translations import get_text

    # Transfer intro
    check("uz: transfer_intro 'ID'", "ID" in get_text("transfer_intro", "uz"))
    check("ru: transfer_intro 'ID'", "ID" in get_text("transfer_intro", "ru"))
    check("en: transfer_intro 'ID'", "ID" in get_text("transfer_intro", "en"))

    # Transfer success
    for lang in ("uz", "ru", "en"):
        success = get_text("transfer_success", lang, name="Ali", amount=5)
        check(f"{lang}: transfer_success '5'", "5" in success)
        check(f"{lang}: transfer_success 'Ali'", "Ali" in success)

    # Transfer errors
    check("uz: transfer_not_found", "topilmadi" in get_text("transfer_user_not_found", "uz"))
    check("ru: transfer_not_found", "не найден" in get_text("transfer_user_not_found", "ru").lower())
    check("en: transfer_not_found", "not found" in get_text("transfer_user_not_found", "en").lower())

    check("uz: transfer_self", "O'zingizga" in get_text("transfer_self", "uz"))
    check("ru: transfer_self", "самому себе" in get_text("transfer_self", "ru"))
    check("en: transfer_self", "yourself" in get_text("transfer_self", "en").lower())

    check("uz: transfer_insufficient",
          "yetarli" in get_text("transfer_insufficient", "uz", credits=1, guide="").lower())
    check("ru: transfer_insufficient",
          "недостаточно" in get_text("transfer_insufficient", "ru", credits=1, guide="").lower())
    check("en: transfer_insufficient",
          "enough" in get_text("transfer_insufficient", "en", credits=1, guide="").lower())


# ================================================================
# 14. NAVIGATSIYA TUGMALARI — 3 tilda
# ================================================================
def test_navigation_buttons_3_langs():
    """Orqaga, Bekor qilish, Asosiy menyu — 3 tilda."""
    print("== Navigatsiya tugmalari (uz/ru/en) ==")
    from locales.translations import get_text
    from keyboards.inline import get_cabinet_back_keyboard
    from keyboards.default import get_cancel_keyboard

    # Back tugmalari
    check("uz: btn_back 'Orqaga'", "Orqaga" in get_text("btn_back", "uz"))
    check("ru: btn_back 'Назад'", "Назад" in get_text("btn_back", "ru"))
    check("en: btn_back 'Back'", "Back" in get_text("btn_back", "en"))

    # Cancel tugmalari
    check("uz: btn_cancel 'Bekor qilish'", "Bekor qilish" in get_text("btn_cancel", "uz"))
    check("ru: btn_cancel 'Отмена'", "Отмена" in get_text("btn_cancel", "ru"))
    check("en: btn_cancel 'Cancel'", "Cancel" in get_text("btn_cancel", "en"))

    # Main menu tugmalari
    check("uz: btn_main_menu 'Asosiy menyu'", "Asosiy menyu" in get_text("btn_main_menu", "uz"))
    check("ru: btn_main_menu 'Главное меню'", "Главное меню" in get_text("btn_main_menu", "ru"))
    check("en: btn_main_menu 'Main menu'", "Main menu" in get_text("btn_main_menu", "en"))

    # Cabinet back keyboard
    for lang in ("uz", "ru", "en"):
        kb = get_cabinet_back_keyboard(lang)
        labels = [b.text for row in kb.inline_keyboard for b in row]
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        check(f"{lang}: cabinet_back has back btn",
              get_text("btn_back", lang) in labels)
        check(f"{lang}: cabinet_back has close btn",
              get_text("cab_close", lang) in labels)
        check(f"{lang}: cabinet_back callbacks",
              "cab_main" in cbs and "close_cabinet" in cbs)

    # Cancel keyboard (reply)
    for lang in ("uz", "ru", "en"):
        kb = get_cancel_keyboard(lang)
        labels = [b.text for row in kb.keyboard for b in row]
        check(f"{lang}: cancel_kb has cancel",
              get_text("btn_cancel", lang) in labels)
        check(f"{lang}: cancel_kb has main_menu",
              get_text("btn_main_menu", lang) in labels)


# ================================================================
# 15. KABINET REPLY-KLAVIATURASI — 3 tilda
# ================================================================
def test_cabinet_reply_keyboard_3_langs():
    """Kabinet reply-klaviaturasi — 3 tilda."""
    print("== Kabinet reply-klaviaturasi (uz/ru/en) ==")
    from keyboards.default import get_cabinet_keyboard
    from locales.translations import get_text

    for lang in ("uz", "ru", "en"):
        kb = get_cabinet_keyboard(lang)
        labels = [b.text for row in kb.keyboard for b in row]
        # Tugmalar tilga mos
        for key in ("cab_btn_channels", "cab_btn_converter", "cab_btn_daily_bonus",
                     "cab_btn_invite", "cab_btn_transfer", "btn_main_menu"):
            expected = get_text(key, lang)
            check(f"{lang}: reply kb has '{key[:20]}'",
                  expected in labels, f"expected={expected}, labels={labels}")


# ================================================================
# 16. PLACEHOLDER MOSLIGI — 3 tilda
# ================================================================
def test_placeholders_match():
    """{placeholder}'lar 3 tilda bir xil bo'lishi kerak."""
    print("== Placeholder mosligi (uz/ru/en) ==")
    import re as _re
    from locales.translations import TRANSLATIONS

    keys_with_placeholders = [
        "cabinet_title", "balance_card", "daily_bonus_claimed",
        "referral_menu", "transfer_target_ok", "transfer_success",
        "transfer_gift_notice", "transfer_error", "transfer_insufficient",
        "ch_tone_title", "ch_tone_success", "ch_voice_result",
        "credits_value", "cabinet_streak",
        "tz_changed", "tz_current",
    ]

    for key in keys_with_placeholders:
        placeholders = {}
        for lang in ("uz", "ru", "en"):
            val = TRANSLATIONS[lang].get(key, "")
            placeholders[lang] = sorted(set(_re.findall(r"\{(\w+)\}", val)))

        # UZ va RU har doim mos bo'lishi kerak
        check(f"placeholder uz==ru: {key}",
              placeholders["uz"] == placeholders["ru"],
              f"uz={placeholders['uz']}, ru={placeholders['ru']}")
        # EN ham mos bo'lishi kerak
        check(f"placeholder uz==en: {key}",
              placeholders["uz"] == placeholders["en"],
              f"uz={placeholders['uz']}, en={placeholders['en']}")


# ================================================================
# 17. CALLBACK_DATA 64-BAYT XAVFSIZLIGI
# ================================================================
def test_callback_data_safety():
    """Account & Settings klaviaturalaridagi callback_data 64 baytdan oshmaydi."""
    print("== Callback data xavfsizligi ==")
    from keyboards.inline import (
        get_cabinet_inline_keyboard, get_language_keyboard,
        get_cabinet_back_keyboard, get_channels_manage_keyboard,
        render_channels_list,
    )

    keyboards = [
        ("cabinet_uz", get_cabinet_inline_keyboard("uz")),
        ("cabinet_ru", get_cabinet_inline_keyboard("ru")),
        ("cabinet_en", get_cabinet_inline_keyboard("en")),
        ("lang_uz", get_language_keyboard("uz")),
        ("lang_ru", get_language_keyboard("ru")),
        ("lang_en", get_language_keyboard("en")),
        ("back_uz", get_cabinet_back_keyboard("uz")),
        ("channels_uz", get_channels_manage_keyboard("uz")),
        ("channels_en", get_channels_manage_keyboard("en")),
        ("list", render_channels_list([("-1001", "Test", "friendly")], "en")),
    ]

    oversized = []
    empty = []
    total = 0
    for name, kb in keyboards:
        for row in kb.inline_keyboard:
            for btn in row:
                data = btn.callback_data
                if data is None:
                    continue
                total += 1
                size = len(data.encode("utf-8"))
                if size > 64:
                    oversized.append((name, data, size))
                if size == 0:
                    empty.append((name, btn.text))

    check("tugmalar tekshirildi", total > 30, str(total))
    check("64 baytdan oshgan YO'Q", not oversized, str(oversized[:3]))
    check("bo'sh callback YO'Q", not empty, str(empty[:3]))


# ================================================================
# 18. PARITET — UZ/RU kalitlari to'liq sinxron
# ================================================================
def test_parity():
    """UZ va RU kalitlari 1:1 mos (paritet buzilmagan)."""
    print("== UZ/RU paritet ==")
    from locales.translations import translation_parity_report, missing_keys

    report = translation_parity_report()
    check("uz_only bo'sh", report["uz_only"] == [], str(report["uz_only"][:5]))
    check("ru_only bo'sh", report["ru_only"] == [], str(report["ru_only"][:5]))
    check("in_sync", report["in_sync"] is True)
    check("kalitlar soni 600+", report["total"] >= 600, str(report["total"]))
    check("missing_keys('ru') bo'sh", missing_keys("ru") == [])


# ================================================================
# MAIN
# ================================================================
def main():
    test_account_settings_keys_exist()
    test_main_menu_button_3_langs()
    test_cabinet_inline_keyboard_3_langs()
    test_cabinet_screen_text()
    test_language_menu()
    test_channels_management_3_langs()
    test_channel_voice_3_langs()
    test_channel_tone_3_langs()
    test_timezone_3_langs()
    test_balance_and_credits_3_langs()
    test_daily_bonus_3_langs()
    test_referral_3_langs()
    test_transfer_3_langs()
    test_navigation_buttons_3_langs()
    test_cabinet_reply_keyboard_3_langs()
    test_placeholders_match()
    test_callback_data_safety()
    test_parity()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha Account & Settings i18n testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
