#!/usr/bin/env python3
"""Yakuniy bosqich: YORDAMCHI BO'LIMLAR, ONBOARDING VA SMOKE TEST (uz/ru/en).

Qamrov (handlers/onboarding.py, handlers/converter.py, handlers/start.py):
  1. ⚙️ Qo'shimcha funksiyalar / Extra features — extras + konverter matnlari
     va tugmalari 3 tilda tarjima qilingan, EN'da o'zbekcha qoldiq yo'q.
  2. 🔤 Lotin ⇄ Kirill konverter — barcha oqim matnlari 3 tilda.
  3. 🎁 Kunlik bonus (Streak) va ballar tizimi — 3 tilda regressiya qo'riqchisi.
  4. 📖 Qo'llanma / Bot haqida — guide + FAQ foydalanuvchi tilida ochiladi;
     tezkor buyruqlar (/start, /newpost, /profile, /help) 3 tilda ham ro'yxatda.
  5. 🆕 3 kunlik sodda Onboarding — 3+1 tugma 3 tilda chiziladi va routing'da
     taniladi; 3 kunlik mantiq (kun/post/unlock) DB'siz tekshiriladi.
  6. 🔌 Integratsiya — CONVERT_INPUT holati boshqa FSM holatlari bilan
     to'qnashmaydi; handler funksiyalar import qilinadi va korutina.
  7. 🧷 Xavfsizlik — {placeholder} va HTML teglar UZ bilan bir xil; get_text
     hech qachon kalit nomini qaytarmaydi; uz/ru paritet buzilmagan.

Ishga tushirish:
    cd telegram_bot && python tests/extras_onboarding_i18n_test.py
"""
import asyncio
import inspect
import os
import re
import sys
from datetime import datetime, timedelta
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


# Yakuniy bosqich kalitlari: extras + konverter + guide/FAQ + tizim xabarlari.
FINAL_KEYS = [
    "extras_menu_body", "extras_btn_enhancer", "extras_btn_converter",
    "extras_closed",
    "conv_intro", "conv_no_text", "conv_received", "conv_btn_cyr",
    "conv_btn_lat", "conv_no_saved_text", "conv_result_title",
    "conv_result_part1", "conv_result_part2", "conv_copy_hint",
    "conv_cont_title", "conv_error", "cab_converter_info",
    "help_guide", "help_guide_admin", "help_btn_faq", "help_btn_support",
    "help_support_line", "help_admin_fallback", "help_faq", "cab_guide_text",
    "msg_closed", "conv_timeout_msg", "no_channels_hint",
    "btn_pending", "btn_queue",
    "sys_busy", "sys_stale_button", "sys_unexpected_error",
]

# Ballar tizimi regressiya qo'riqchisi (ilgari tarjima qilingan — buzilmasligi shart).
CREDITS_KEYS = [
    "daily_bonus_claimed", "daily_bonus_reset_notice", "daily_bonus_already",
    "daily_bonus_admin", "daily_bonus_guide",
    "balance_card", "ad_mode_admin", "ad_mode_pro", "ad_mode_free",
    "referral_menu", "referral_reward_notice",
    "transfer_intro", "transfer_insufficient", "transfer_user_not_found",
    "transfer_self", "transfer_target_ok", "transfer_amount_nan",
    "transfer_amount_range", "transfer_success", "transfer_gift_notice",
    "transfer_error",
]

QUICK_KEYS = [
    "quick_menu_hint", "quick_btn_ai_post", "quick_btn_photo_post",
    "quick_btn_add_channel", "quick_btn_full_menu", "quick_full_menu_opened",
]

# O'zbekchaga xos belgilar — EN matnida uchrasa, kalit tarjima qilinmagan.
# (Eslatma: cab_converter_info EN'dagi ataylab qoldirilgan misol
# "Salom dunyo → Салом дунё" marker'ga tushmasligi uchun ro'yxat shu
# misoldagi so'zlarni o'z ichiga olmaydi.)
UZ_MARKER_WORDS = (
    "Qo'shimcha", "qo'shimcha", "Qo'llanma", "qo'llanma",
    "alifbo", "Alifbo", "o'gir", "O'gir", "konvertor", "Konvertor",
    "nusxasi", "Nusxa", "qabul qilindi", "Qabul qilindi",
    "Tezkor", "tezkor", "Yordam kerakmi", "Kunlik bonus", "kunlik bonus",
    "tugmasini bosing", "tugma qo'shish", "Tugma & Reaksiya",
    "tanlang", "yuboring", "kiring", "bosing",
    " uchun ", " bilan ", " qiling", " bo'limi", " bo'limidan",
    "matnni", "Matn ", "Natija", "natija", "Xatolik", "xatolik",
    "Yopildi", "yopildi", "Suhbat", "suhbat",
    "sizning", "Sizning", "Tizim ", "Kutilmagan", "kutilmagan",
    " tugma", "Tugma", "kanal", "Kanal", "so'rov", "ball",
    "Mening kanallarim", "Asosiy menyu", "Bosh menyu",
)

PH = re.compile(r"\{(\w+)\}")


def placeholders(text):
    return set(PH.findall(str(text)))


def test_final_keys_present_and_translated():
    print("== 1. Yakuniy bosqich kalitlari 3 tilda mavjud va tarjima qilingan ==")
    uz, ru, en = TRANSLATIONS["uz"], TRANSLATIONS["ru"], TRANSLATIONS["en"]
    for lang, table in (("uz", uz), ("ru", ru), ("en", en)):
        missing = [k for k in FINAL_KEYS if not str(table.get(k) or "").strip()]
        check(f"{lang}: {len(FINAL_KEYS)} ta kalit mavjud va bo'sh emas",
              not missing, str(missing[:5]))
    same_ru = [k for k in FINAL_KEYS if str(uz.get(k)) == str(ru.get(k))]
    check("uz != ru (barcha kalitlar ruschada tarjima)", not same_ru, str(same_ru[:5]))
    same_en = [k for k in FINAL_KEYS if str(en.get(k)) == str(uz.get(k))]
    check("en != uz (barcha kalitlar inglizchada tarjima)", not same_en, str(same_en[:5]))
    same_en_ru = [k for k in FINAL_KEYS if str(en.get(k)) == str(ru.get(k))]
    check("en != ru (EN alohida tarjima)", not same_en_ru, str(same_en_ru[:5]))
    check("kalitlar soni 30 dan katta", len(FINAL_KEYS) > 30, str(len(FINAL_KEYS)))


def test_no_uz_leak_in_en():
    print("== 2. EN matnida o'zbekcha qoldiq yo'q ==")
    leaked = []
    for k in FINAL_KEYS + QUICK_KEYS:
        text = str(get_text(k, "en"))
        hits = [m for m in UZ_MARKER_WORDS if m in text]
        if hits:
            leaked.append((k, hits[:2]))
    check("o'zbekcha so'z qoldig'i topilmadi", not leaked, str(leaked[:5]))
    # EN o'ziga xos so'zlar — tarjima haqiqiy ekanini tasdiqlaydi.
    check("extras EN: 'Extra features'",
          "Extra features" in get_text("extras_menu_body", "en"))
    check("conv EN: 'Converter' + 'Cyrillic'",
          "Converter" in get_text("conv_intro", "en")
          and "Cyrillic" in get_text("conv_btn_cyr", "en"))
    check("guide EN: 'Full Guide' + 'Quick commands'",
          "Full Guide" in get_text("help_guide", "en", support="")
          and "Quick commands" in get_text("help_guide", "en", support=""))
    check("faq EN: 'FAQ'",
          "FAQ" in get_text("help_faq", "en", support=""))


def test_placeholders_and_html_match():
    print("== 3. {placeholder} va HTML teglar UZ bilan bir xil ==")
    uz = TRANSLATIONS["uz"]
    bad_ph, bad_html, fmt_bad = [], [], []
    for k in FINAL_KEYS:
        if k not in EN_OVERLAY:
            continue
        v = EN_OVERLAY[k]
        if placeholders(v) != placeholders(uz[k]):
            bad_ph.append(k)
        for tag in ("b", "i", "code"):
            if (str(v).count(f"<{tag}>") != str(uz[k]).count(f"<{tag}>")
                    or str(v).count(f"</{tag}>") != str(uz[k]).count(f"</{tag}>")):
                bad_html.append((k, tag))
                break
        try:
            out = str(v).format(**{p: "X" for p in placeholders(v)})
            if "{" in out or "}" in out:
                fmt_bad.append((k, "leftover"))
        except Exception as exc:  # noqa: BLE001
            fmt_bad.append((k, repr(exc)))
    check("format ko'rsatkichlari mos", not bad_ph, str(bad_ph[:5]))
    check("HTML teglar (<b>/<i>/<code>) mos", not bad_html, str(bad_html[:5]))
    check("formatlash xatosiz, qavs qoldirmaydi", not fmt_bad, str(fmt_bad[:5]))
    # Muhim bog'lanishlar: support/admin/error almashtiriladi.
    check("help_guide {support} 3 tilda",
          all("{support}" not in get_text("help_guide", lg, support="S")
              and "S" in get_text("help_guide", lg, support="S")
              for lg in ("uz", "ru", "en")))
    check("help_support_line {admin} 3 tilda",
          all("@adm" in get_text("help_support_line", lg, admin="@adm")
              for lg in ("uz", "ru", "en")))
    check("conv_error {error} 3 tilda",
          all("E1" in get_text("conv_error", lg, error="E1")
              for lg in ("uz", "ru", "en")))
    keyfall = [k for k in FINAL_KEYS
               if any(get_text(k, lg) == k for lg in ("uz", "ru", "en"))]
    check("kalit nomi ekran matnida chiqmaydi", not keyfall, str(keyfall[:5]))


def test_credits_system_regression():
    print("== 4. Kunlik bonus (Streak) va ballar tizimi — 3 tilda ==")
    uz, ru, en = TRANSLATIONS["uz"], TRANSLATIONS["ru"], TRANSLATIONS["en"]
    for lang, table in (("uz", uz), ("ru", ru), ("en", en)):
        missing = [k for k in CREDITS_KEYS if not str(table.get(k) or "").strip()]
        check(f"{lang}: {len(CREDITS_KEYS)} ta ballar kaliti mavjud",
              not missing, str(missing[:5]))
    same = [k for k in CREDITS_KEYS
            if str(en.get(k)) == str(uz.get(k)) or str(ru.get(k)) == str(uz.get(k))]
    check("ballar kalitlari ru/en'da tarjima (uz'dan farq)", not same, str(same[:5]))
    # Streak xabari barcha maydonlar bilan formatlanadi.
    for lg in ("uz", "ru", "en"):
        try:
            out = get_text("daily_bonus_claimed", lg, reset_notice="", streak=5,
                           bar="🟩🟩🟩🟩🟩⬜⬜", bonus=3, credits=12)
            ok = ("5" in out and "12" in out and "{" not in out and "}" not in out)
        except Exception:  # noqa: BLE001
            ok = False
        check(f"daily_bonus_claimed format ({lg})", ok)
    for lg in ("uz", "ru", "en"):
        try:
            out = get_text("balance_card", lg, credits="X", ad_mode="Y")
            ok = "X" in out and "Y" in out
        except Exception:  # noqa: BLE001
            ok = False
        check(f"balance_card format ({lg})", ok)
    for lg in ("uz", "ru", "en"):
        try:
            out = get_text("referral_menu", lg, credits="X", count=2, link="L")
            ok = "L" in out and "2" in out
        except Exception:  # noqa: BLE001
            ok = False
        check(f"referral_menu format ({lg})", ok)


def test_quick_commands_listed():
    print("== 5. Tezkor buyruqlar ro'yxati (/start, /newpost, /profile, /help) ==")
    for lg in ("uz", "ru", "en"):
        guide = get_text("help_guide", lg, support="")
        check(f"help_guide {lg}: 4 ta buyruq",
              all(c in guide for c in ("/start", "/newpost", "/profile", "/help")),
              guide[-120:] if lg == "en" else "")
    for lg in ("uz", "ru", "en"):
        cab = get_text("cab_guide_text", lg)
        check(f"cab_guide_text {lg}: /start /profile /help",
              all(c in cab for c in ("/start", "/profile", "/help")))
    # Bot buyruqlari Telegram menyusida ro'yxatdan o'tgan.
    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for cmd in ("start", "profile", "help", "cancel", "newpost", "queue"):
        check(f'CommandHandler("{cmd}") ro\'yxatda', f'CommandHandler("{cmd}"' in src)


def test_extras_help_keyboards_trilingual():
    print("== 6. Extras/Guide inline klaviaturalari — 3 tilda, bir xil callback ==")
    from keyboards.inline import (
        get_extras_inline_keyboard, get_help_keyboard, get_help_back_keyboard,
    )

    def rows(kb):
        return [[(b.text, b.callback_data, b.url) for b in row]
                for row in kb.inline_keyboard]

    cbs = {}
    for lg in ("uz", "ru", "en"):
        r = rows(get_extras_inline_keyboard(lg))
        cbs[lg] = [c for row in r for _, c, _ in row]
        check(f"extras kb {lg}: 3 qator",
              len(r) == 3, str([t for row in r for t, _, _ in row]))
        check(f"extras kb {lg}: yorliqlar lug'atdan",
              r[0][0][0] == get_text("extras_btn_enhancer", lg)
              and r[1][0][0] == get_text("extras_btn_converter", lg)
              and r[2][0][0] == get_text("cab_close", lg))
    check("extras kb: callback'lar 3 tilda bir xil",
          cbs["uz"] == cbs["ru"] == cbs["en"] == ["extra_enhancer", "extra_converter", "extra_close"],
          str(cbs))
    for lg in ("uz", "ru", "en"):
        hk = rows(get_help_keyboard("support_user", lg))
        flat = [b for row in hk for b in row]
        check(f"help kb {lg}: support URL + FAQ callback",
              any(u == "https://t.me/support_user"
                  and t == get_text("help_btn_support", lg) for t, _, u in flat)
              and any(c == "help:faq"
                      and t == get_text("help_btn_faq", lg) for t, c, _ in flat),
              str(flat))
    for lg in ("uz", "ru", "en"):
        hb = rows(get_help_back_keyboard(lg))
        check(f"help back kb {lg}: Orqaga → help:guide",
              hb[0][0][0] == get_text("btn_back", lg) and hb[0][0][1] == "help:guide",
              str(hb))
    # Qo'llanma matni FAQ matnidan farq qiladi (ikki sahifa almashadi).
    for lg in ("uz", "ru", "en"):
        check(f"guide != faq ({lg})",
              get_text("help_guide", lg, support="S") != get_text("help_faq", lg, support="S"))


def test_simple_onboarding_keyboard_trilingual():
    print("== 7. Sodda Onboarding klaviatura (3+1 tugma) — 3 tilda ==")
    from keyboards.default import get_simple_keyboard
    for lg in ("uz", "ru", "en"):
        kb = get_simple_keyboard(lg)
        labels = [b.text for row in kb.keyboard for b in row]
        check(f"simple kb {lg}: 4 qator (3 katta + to'liq menyu)",
              len(kb.keyboard) == 4 and all(len(row) == 1 for row in kb.keyboard),
              str(labels))
        check(f"simple kb {lg}: yorliqlar lug'atdan",
              labels == [get_text("quick_btn_ai_post", lg),
                         get_text("quick_btn_photo_post", lg),
                         get_text("quick_btn_add_channel", lg),
                         get_text("quick_btn_full_menu", lg)],
              str(labels))
    # 3 til yorliqlari o'zaro farq qiladi (tarjima qilingan).
    from keyboards.default import (
        BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_AI_POST_EN,
        BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_PHOTO_POST_EN,
        BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU, BTN_QUICK_ADD_CHANNEL_EN,
        BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU, BTN_OPEN_FULL_MENU_EN,
        QUICK_MENU_BUTTONS,
    )
    check("quick AI post: uz/ru/en farq qiladi",
          len({BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_AI_POST_EN}) == 3)
    check("quick photo post: uz/ru/en farq qiladi",
          len({BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_PHOTO_POST_EN}) == 3)
    check("quick add channel: uz/ru/en farq qiladi",
          len({BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU, BTN_QUICK_ADD_CHANNEL_EN}) == 3)
    check("quick full menu: uz/ru/en farq qiladi",
          len({BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU, BTN_OPEN_FULL_MENU_EN}) == 3)
    check("QUICK_MENU_BUTTONS: 12 ta (4 tugma × 3 til)",
          len(QUICK_MENU_BUTTONS) == 12, str(len(QUICK_MENU_BUTTONS)))


def test_onboarding_three_day_logic():
    print("== 8. 3 kunlik Onboarding mantiqi (DB'siz, sof mantiq) ==")
    import onboarding as ob
    now = datetime(2026, 9, 10, 12, 0, 0)
    check("yangi (0 kun, 0 post) → sodda",
          ob.should_show_simple_menu(created_at=now, posts_published=0, now=now) is True)
    check("2 kun, 1 post → sodda",
          ob.should_show_simple_menu(created_at=now - timedelta(days=2),
                                     posts_published=1, now=now) is True)
    check("2 kun, 9 post → sodda (kun < 3)",
          ob.should_show_simple_menu(created_at=now - timedelta(days=2),
                                     posts_published=9, now=now) is True)
    check("3 kun, 1 post → sodda (post < 3)",
          ob.should_show_simple_menu(created_at=now - timedelta(days=3),
                                     posts_published=1, now=now) is True)
    check("3 kun, 9 post → to'liq",
          ob.should_show_simple_menu(created_at=now - timedelta(days=3),
                                     posts_published=9, now=now) is False)
    check("4 kun → to'liq (qat'iy chegara)",
          ob.should_show_simple_menu(created_at=now - timedelta(days=4),
                                     posts_published=0, now=now) is False)
    check("unlock bosilgan → har doim to'liq",
          ob.should_show_simple_menu(created_at=now, posts_published=0,
                                     full_menu_unlocked=True, now=now) is False)
    check("created_at yo'q + 0 post → sodda",
          ob.should_show_simple_menu(created_at=None, posts_published=0, now=now) is True)
    check("created_at yo'q + 9 post → to'liq",
          ob.should_show_simple_menu(created_at=None, posts_published=9, now=now) is False)
    check("decide_menu_mode: bo'sh → full (fail-open)",
          ob.decide_menu_mode(None, now=now) == "full"
          and ob.decide_menu_mode({}, now=now) == "full")
    check("decide_menu_mode: yangi → simple",
          ob.decide_menu_mode({"created_at": now, "posts_published": 0,
                               "full_menu_unlocked": False}, now=now) == "simple")
    # Kesh: yozish → o'qish → bekor qilish.
    ob.invalidate_simple_menu(424242)
    check("kesh: dastlab None", ob.get_cached_simple_menu(424242) is None)
    ob.cache_simple_menu(424242, True)
    check("kesh: True saqlandi", ob.get_cached_simple_menu(424242) is True)
    ob.invalidate_simple_menu(424242)
    check("kesh: bekor qilindi", ob.get_cached_simple_menu(424242) is None)


def test_trilingual_routing():
    print("== 9. Uch tilli routing (EN tugmalar fallback'ga tushmaydi) ==")
    kb_src = (ROOT / "keyboards" / "default.py").read_text(encoding="utf-8")
    h_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for const in ("BTN_QUICK_AI_POST_EN", "BTN_QUICK_PHOTO_POST_EN",
                  "BTN_QUICK_ADD_CHANNEL_EN", "BTN_OPEN_FULL_MENU_EN",
                  "BTN_EXTRAS_EN", "BTN_HELP_EN", "BTN_CONVERTER_EN",
                  "BTN_DAILY_BONUS_EN", "BTN_SETTINGS_EN", "BTN_NEW_POST_EN",
                  "BTN_PENDING_EN", "BTN_QUEUE_EN"):
        check(f"{const} aniqlangan", f"{const} = " in kb_src)
        check(f"{const} routing'da", const in h_src)
    # Sodda menyu handlerlari uchala tilni bitta exact() da taniydi.
    check("quick AI post routing (uz/ru/en)",
          "exact(BTN_QUICK_AI_POST, BTN_QUICK_AI_POST_RU, BTN_QUICK_AI_POST_EN)" in h_src)
    check("quick photo routing (uz/ru/en)",
          "exact(BTN_QUICK_PHOTO_POST, BTN_QUICK_PHOTO_POST_RU, BTN_QUICK_PHOTO_POST_EN)" in h_src)
    check("quick channel routing (uz/ru/en)",
          "exact(BTN_QUICK_ADD_CHANNEL, BTN_QUICK_ADD_CHANNEL_RU, BTN_QUICK_ADD_CHANNEL_EN)" in h_src)
    check("quick full-menu routing (uz/ru/en)",
          "exact(BTN_OPEN_FULL_MENU, BTN_OPEN_FULL_MENU_RU, BTN_OPEN_FULL_MENU_EN)" in h_src)
    # Qo'shimcha/konverter inline entry callback'lari ro'yxatda.
    for pat in ("^extra_converter$", "^extra_enhancer$", "^extra_close$",
                "^help:", "^conv_show:", "^conv_close$"):
        check(f"callback {pat} ro'yxatda", pat in h_src)


def test_handlers_import_and_states():
    print("== 10. Handlerlar importi va FSM holatlar to'qnashuvi yo'q ==")
    import handlers.converter as conv_mod
    import handlers.onboarding as ob_mod
    # Diqqat: handlers/__init__.py `from handlers.start import start` qiladi,
    # shuning uchun `handlers.start` atributi funksiya bilan soyalanadi —
    # real modul sys.modules orqali olinadi.
    start_mod = sys.modules["handlers.start"]
    for mod, fn in ((conv_mod, "start_converter"), (conv_mod, "converter_received"),
                    (conv_mod, "converter_callback"), (conv_mod, "converter_inline_entry"),
                    (conv_mod, "converter_close_callback"),
                    (ob_mod, "quick_ai_post_entry"), (ob_mod, "quick_photo_post_entry"),
                    (ob_mod, "quick_add_channel_entry"), (ob_mod, "open_full_menu"),
                    (ob_mod, "resolve_main_keyboard"), (ob_mod, "user_wants_simple_menu"),
                    (ob_mod, "main_menu_intro_suffix"),
                    (start_mod, "start"), (start_mod, "extras_menu"),
                    (start_mod, "help_command"), (start_mod, "help_menu_callback"),
                    (start_mod, "daily_bonus_handler"), (start_mod, "user_cabinet_menu")):
        check(f"{mod.__name__}.{fn} korutina",
              inspect.iscoroutinefunction(getattr(mod, fn, None)))
    # CONVERT_INPUT boshqa FSM holatlari bilan to'qnashmasligi shart.
    from handlers.converter import CONVERT_INPUT
    from handlers.start import TRANSFER_TARGET, TRANSFER_AMOUNT
    from handlers.new_post import (CHOOSE_CHANNEL, GET_CONTENT, GET_BTN_TITLE,
                                   GET_BTN_URL, GET_REACTIONS, GET_AUTO_DELETE,
                                   GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME,
                                   GET_DURATION, CONFIRM_POST, EDIT_CONFIRM_FIELD)
    from handlers.channels import ADD_CHANNEL, SET_TONE
    from handlers.pending import (EDIT_POST_TIME, EDIT_POST_CONTENT,
                                  EDIT_POST_BTN, EDIT_POST_REACT)
    from handlers.ai_assistant import (AI_INPUT, AI_CONFIRM, AI_GET_TIME,
                                       AI_MENU_STATE, AI_PROMPT_INPUT,
                                       AI_TONE_SELECT, AI_AUDIT_INPUT,
                                       AI_PHOTO_INPUT, AI_PHOTO_RESULT,
                                       AI_PHOTO_EDIT_INPUT)
    from handlers.content_plan import (PLAN_CHOOSE_CHANNEL, PLAN_GET_TOPIC,
                                       PLAN_VIEW)
    from handlers.analytics import ANALYTICS_CHOOSE, ANALYTICS_VIEW
    from handlers.subscription import SUBSCRIPTION_VIEW, PROMO_INPUT, RECEIPT_WAIT
    from handlers.channel_extract import EXTRACT_USERNAME, EXTRACT_CHOOSE_POST
    from handlers.queue import QUEUE_MENU, SLOT_ADD
    from handlers.post_enhancer import ENH_POST
    from handlers.photo_check import PHOTO_CHECK_WAIT
    from handlers.admin import (BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL,
                                SET_CHANNEL_AD, SET_BOT_REPLY_AD, AI_SETTINGS,
                                SET_POST_TAG, ADMIN_GRANT_PRO,
                                ADMIN_PROMO_CREATE, ADMIN_SPONSOR_ADD)
    others = [TRANSFER_TARGET, TRANSFER_AMOUNT, CHOOSE_CHANNEL, GET_CONTENT,
              GET_BTN_TITLE, GET_BTN_URL, GET_REACTIONS, GET_AUTO_DELETE,
              GET_TIME, DAILY_TIME, RECUR_DAY, RECUR_TIME, GET_DURATION,
              CONFIRM_POST, EDIT_CONFIRM_FIELD, ADD_CHANNEL, SET_TONE,
              EDIT_POST_TIME, EDIT_POST_CONTENT, EDIT_POST_BTN, EDIT_POST_REACT,
              AI_INPUT, AI_CONFIRM, AI_GET_TIME, AI_MENU_STATE, AI_PROMPT_INPUT,
              AI_TONE_SELECT, AI_AUDIT_INPUT, AI_PHOTO_INPUT, AI_PHOTO_RESULT,
              AI_PHOTO_EDIT_INPUT, PLAN_CHOOSE_CHANNEL, PLAN_GET_TOPIC,
              PLAN_VIEW, ANALYTICS_CHOOSE, ANALYTICS_VIEW, SUBSCRIPTION_VIEW,
              PROMO_INPUT, RECEIPT_WAIT, EXTRACT_USERNAME, EXTRACT_CHOOSE_POST,
              QUEUE_MENU, SLOT_ADD, ENH_POST, PHOTO_CHECK_WAIT,
              BROADCAST_MESSAGE, ADD_SPONSOR_CHANNEL, SET_CHANNEL_AD,
              SET_BOT_REPLY_AD, AI_SETTINGS, SET_POST_TAG, ADMIN_GRANT_PRO,
              ADMIN_PROMO_CREATE, ADMIN_SPONSOR_ADD]
    check(f"CONVERT_INPUT ({CONVERT_INPUT}) unikal",
          CONVERT_INPUT not in others, str(CONVERT_INPUT))
    check("barcha FSM holatlar unikal",
          len(set(others + [CONVERT_INPUT])) == len(others) + 1)


def test_converter_trilingual_smoke():
    print("== 11. Konverter oqimi smoke (uz/ru/en matnlar + tugmalar) ==")

    class _Msg:
        def __init__(self, text):
            self.text = text
            self.photo = self.video = self.document = None
            self.audio = self.voice = self.animation = None
            self.caption = None
            self.replies = []

        async def reply_text(self, text, **kw):
            self.replies.append((text, kw.get("reply_markup")))
            return None

    class _Ctx:
        def __init__(self, lang):
            self.user_data = {"lang": lang}

    class _Upd:
        def __init__(self, message):
            self.message = message

    import handlers.converter as conv_mod

    async def _run(lang):
        ctx = _Ctx(lang)
        msg = _Msg("Salom dunyo")
        out = await conv_mod.converter_received(_Upd(msg), ctx)
        return out, msg, ctx

    for lg in ("uz", "ru", "en"):
        out, msg, ctx = asyncio.run(_run(lg))
        check(f"converter_received {lg}: CONVERT_INPUT",
              out == conv_mod.CONVERT_INPUT, str(out))
        ok_text = msg.replies and msg.replies[0][0] == get_text("conv_received", lg)
        check(f"converter_received {lg}: matn lug'atdan", ok_text,
              str(msg.replies[0][0])[:60] if msg.replies else "no reply")
        kb = msg.replies[0][1] if msg.replies else None
        flat = [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row] \
            if kb is not None else []
        check(f"converter_received {lg}: 3 tugma + bir xil callback",
              [c for _, c in flat] == ["conv_show:cyr", "conv_show:lat", "conv_close"]
              and flat[0][0] == get_text("conv_btn_cyr", lg)
              and flat[1][0] == get_text("conv_btn_lat", lg)
              and flat[2][0] == get_text("cab_close", lg),
              str(flat))
        check(f"converter_received {lg}: cyr/lat saqlandi",
              ctx.user_data.get("cyr_text") == "Салом дунё"
              and ctx.user_data.get("lat_text") == "Salom dunyo",
              str({k: ctx.user_data.get(k) for k in ("cyr_text", "lat_text")}))
    # EN tugma yorliqlari uz/ru'dan farq qiladi.
    check("conv tugmalar EN: alohida tarjima",
          get_text("conv_btn_cyr", "en") == "🔤 Cyrillic version"
          and get_text("conv_btn_lat", "en") == "🔤 Latin version")


def test_parity_intact():
    print("== 12. UZ/RU/EN paritet buzilmagan ==")
    rep = translation_parity_report()
    check("in_sync True", rep["in_sync"] is True, str(rep))
    sizes = {lg: len(TRANSLATIONS[lg]) for lg in ("uz", "ru", "en")}
    check("3 tilning kalitlar soni teng", len(set(sizes.values())) == 1, str(sizes))
    check("EN overlay 180+ kalit (yakuniy bosqich bilan)",
          len(EN_OVERLAY) >= 180, str(len(EN_OVERLAY)))


def main():
    test_final_keys_present_and_translated()
    test_no_uz_leak_in_en()
    test_placeholders_and_html_match()
    test_credits_system_regression()
    test_quick_commands_listed()
    test_extras_help_keyboards_trilingual()
    test_simple_onboarding_keyboard_trilingual()
    test_onboarding_three_day_logic()
    test_trilingual_routing()
    test_handlers_import_and_states()
    test_converter_trilingual_smoke()
    test_parity_intact()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        print("Extras/Onboarding yakuniy testlari: XATOLAR BOR ❌")
        sys.exit(1)
    print("Barcha Extras/Onboarding yakuniy testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
