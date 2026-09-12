#!/usr/bin/env python3
"""🌐 Uch tilli reply-klaviatura filtrlari + sana/vaqt lokalizatsiyasi +
   📷 rasm moderatsiyasi (photo_check) — regressingiya testlari.

Nima uchun bu fayl bor?
    Uchta mustaqil bo'shliq bitta testda yig'ilgan:

    1. **Tugma filtrlari faqat bitta/ikkita tilni tanir edi.**
       Reply-klaviatura foydalanuvchi TILIDA chiziladi (UZ "➕ Yangi post",
       RU "➕ Новый пост", EN "➕ New post"), lekin routing filtrlari
       ``MessageHandler(exact(BTN_NEW_POST, BTN_NEW_POST_RU), ...)`` ko'rinishida
       yozilgani uchun EN klaviaturasi bilan yuborilgan xabar hech qanday
       handlerga tushmay, "kutilmagan xabar" fallback'iga yutilardi.
       Hozir :data:`keyboards.default.MENU_TEXTS` — yagona registry:
       :func:`keyboards.default.exact` har bir matnni shu tugma oilasidagi
       BARCHA tillar bilan kengaytiradi.

    2. **Sana/vaqt tilga bog'liq emas edi.**
       Post preview va rejalash xabarlarida ``strftime("%Y-%m-%d %H:%M")`` va
       ``WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS`` ishlatilardi —
       ya'ni EN foydalanuvchi hafta kunini o'zbekcha ("Juma") deb o'qirdi,
       navbat ro'yxatida esa Python ``%d-%b`` har doim C-locale (Sep, Jan…) oy
       nomini qaytarardi. Hozir yagona manba — :mod:`utils.date_format`.

    3. **Rasm moderatsiyasi (photo_check) faqat o'zbekcha edi.**
       Admin tugmalari, caption va qaror xabarlari qotirilgan holda yozilgan —
       endi ular ``pc_*`` lug'at kalitlari orqali uz/ru/en.

    Qo'shimcha: kanalga yuborishdan oldin kesiladigan "texnik preview"
    qatorlari ham EN bilan to'ldirildi (avval faqat uz/ru sanalgan) va
    ``<b>`` teg bilan o'ralgan qatorlar ham endi ushlanadi.

Ishga tushirish:
    cd telegram_bot && python tests/reply_filters_i18n_dates_test.py
"""
import ast
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Test S.")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402

import keyboards.default as kd  # noqa: E402
from keyboards.default import (  # noqa: E402
    MENU_TEXTS,
    exact,
    is_menu_text,
    menu_texts,
    weekday_index,
)
from locales.translations import (  # noqa: E402
    button_texts,
    button_variants,
    get_text,
    has_key,
    is_button_text,
    normalize_button_text,
    translation_format_report,
    translation_parity_report,
)
from utils.helpers import parse_schedule_input  # noqa: E402
from utils.date_format import (  # noqa: E402
    format_date,
    format_datetime,
    format_list_datetime,
    format_time,
    locale_for,
    schedule_hint,
    weekday_label,
)

TZ = pytz.timezone("Asia/Tashkent")
LANGS = ("uz", "ru", "en")

passed = 0
failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {('| ' + str(extra)) if extra else ''}")


def filter_matches(flt, text) -> bool:
    """PTB ``filters.Regex``/``filters.Text``ni qo'lda qo'llab tekshirish.

    PTB 22.x da ``Regex.pattern`` — TAYYOR ``re.Pattern`` obyekti; eski
    versiyalarda ``filters.Text.patterns`` satrlar to'plami bo'lgani uchun
    ikkala ko'rinish ham qo'llab-quvvatlanadi (bu test filtrlash MANTIG'ini
    tekshiradi, shu sababli matnni o'zimiz ``re.match`` bilan solishtiramiz).
    """
    patterns = []
    for attr in ("patterns", "pattern", "_patterns"):
        value = getattr(flt, attr, None)
        if value is None:
            continue
        if isinstance(value, (str, bytes)) or hasattr(value, "match"):
            patterns.append(value)
        else:
            try:
                patterns.extend(value)
            except TypeError:
                patterns.append(value)
    for pat in patterns:
        if hasattr(pat, "match"):
            if pat.match(text):
                return True
        elif isinstance(pat, str) and re.match(pat, text):
            return True
    return False


def _aware(**kw) -> datetime:
    base = dict(year=2026, month=9, day=5, hour=14, minute=0)
    base.update(kw)
    return TZ.localize(datetime(**base))


# ==========================================================================
# 1. QISM: TUGMA REGISTRY'SI VA FILTRLARI (uz/ru/en)
# ==========================================================================
def test_registry_covers_three_languages():
    print("== 1. MENU_TEXTS registry — har tugma 3 tilda ==")
    # Asosiy doimiy menyu kalitlari: klaviatura shu kalitlardan chiziladi,
    # routing esa registry orqali uchala tilni ham bilishi kerak.
    routes = {
        "btn_new_post": "new_post",
        "btn_ai_studio": "ai_studio",
        "btn_premium": "premium",
        "btn_settings": "settings",
        "btn_help": "help",
        "btn_extras": "extras",
        "btn_main_menu": "main_menu",
        "btn_back": "back",
        "btn_cancel": "cancel",
        "btn_pending": "pending",
        "btn_queue": "queue",
    }
    # Eski kalit nomi (btn_cabinet) ham shu tugma oilasiga kiradi — alohida
    # tekshiriladi, chunki u lug'atda emas, aliaslar ro'yxatida yashaydi.
    check("'👤 Kabinet' aliasi settings oilasida", is_menu_text("👤 Kabinet", "settings"))
    check("'👤 Кабинет' aliasi settings oilasida", is_menu_text("👤 Кабинет", "settings"))
    for key, action in routes.items():
        family = MENU_TEXTS.get(action, ())
        for lang in LANGS:
            label = get_text(key, lang)
            # EN qiymati UZ'dan meros bo'lib qolgan kalitlar (btn_premium,
            # btn_ai_studio, …) uchun bu tekshiruv shunchaki qayta tasdiqlaydi.
            check(f"registry[{action}] '{lang}' tugmasini o'z ichiga oladi: {label}",
                  label in family, str(sorted(family)))
            # ``is_button_text`` — kalit bo'yicha ham shu natijani berishi kerak.
            check(f"is_button_text({label!r}, {key!r})", is_button_text(label, key))
            check(f"is_menu_text('{label}', '{action}') → True",
                  is_menu_text(label, action))

    # Ikkita tugma bir-birini "yeb" masligi kerak: har bir yorliq faqat O'ZI
    # kiritilgan amallar to'plamiga mos keladi.
    for key, action in routes.items():
        label = get_text(key, "en")
        wrong = [a for a in MENU_TEXTS if a != action and is_menu_text(label, a)
                 and not is_menu_text(label, action)]
        check(f"EN tugma noto'g'ri amalgan tushmaydi: {label}", not wrong, str(wrong))


def test_exact_filter_expands_languages():
    print("== 2. exact() filtri tillarni avtomatik kengaytiradi ==")
    # Filtrlar qatori aynan shunday yozilgan (handlers/__init__.py):
    #   MessageHandler(exact(BTN_NEW_POST, BTN_NEW_POST_RU), new_post_entry)
    flt = exact(kd.BTN_NEW_POST, kd.BTN_NEW_POST_RU)
    for text in ("➕ Yangi post", "➕ Новый пост", "➕ New post", "  ➕ New post  "):
        check(f"exact(BTN_NEW_POST, BTN_NEW_POST_RU) → {text!r}", filter_matches(flt, text))

    flt2 = exact(kd.BTN_SETTINGS, kd.BTN_CABINET, kd.BTN_SETTINGS_RU, kd.BTN_SETTINGS_EN)
    for text in ("👤 Kabinet & Sozlamalar", "👤 Кабинет & Настройки",
                 "👤 Account & Settings", "👤 Profile & Settings"):
        check(f"exact(BTN_SETTINGS, …) → {text!r}", filter_matches(flt2, text))

    # Eski/legacy yorliqlar ham ishlaydi (chat tarixidagi klaviatura xabarlari).
    flt3 = exact("⏳ Kutilayotgan postlar", "⏳ Ожидающие посты")
    check("exact(...) eski yorliqdan EN '⏳ Pending posts' ni topadi",
          filter_matches(flt3, "⏳ Pending posts"))

    # Noto'g'ri matn MOS KELMASLIGI kerak (fallback'ga tushsin).
    check("exact(...) — begona matnni ushlamaydi",
          not filter_matches(flt, "➕ Bugun post") and not filter_matches(flt, "/start"))

    # Bo'sh filtr crash bermasin, hech narsa bilan mos kelmasin.
    empty = exact(None, "", "   ")
    check("exact() bo'sh arg bilan xavfli emas", not filter_matches(empty, "salom"))

    # Bir nechta filtr birlashmasi (asosiy menyu qatori).
    # DIQQAT: bu repozitorida ``BTN_BACK`` ataylab ``BTN_MAIN_MENU`` ga teng
    # ("🔙 Asosiy menyu"); "⬅️ Orqaga" (``btn_back``) esa inline klaviaturalarda
    # callback_data bilan boshqariladi. Meros nomlash buzilmasligi kerak.
    check("BTN_BACK — meros bo'yicha asosiy menyu yorlig'i", kd.BTN_BACK == kd.BTN_MAIN_MENU)
    flt4 = exact(kd.BTN_BACK, kd.BTN_MAIN_MENU, kd.BTN_BACK_RU)
    for text in ("🔙 Asosiy menyu", "🔙 Главное меню", "🔙 Main menu"):
        check(f"exact(BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU) → {text!r}",
              filter_matches(flt4, text))
    # "⬅️ Orqaga" matni qo'lda yozilsa ham orqaga olib qaytadi.
    for text in ("⬅️ Orqaga", "⬅️ Назад", "⬅️ Back"):
        check(f"is_menu_text({text!r}, 'back')", is_menu_text(text, "back"))


def test_normalization_tolerance():
    print("== 3. Matn normallashtirish (NBSP, emoji, homoglyph) ==")
    check("NBSP bardoshli", is_menu_text("➕ Yangi\u00a0post", "new_post"))
    check("zero-width bardoshli", is_menu_text("➕ Yang\u200bi post", "new_post"))
    check("emoji variatsiya tanlagichi bardoshli",
          normalize_button_text("⭐️ Premium") == normalize_button_text("⭐ Premium")
          and is_menu_text("⭐ Premium", "premium"))
    check("katta/kichik harf farqi yo'q", is_menu_text("➕ NEW POST", "new_post"))
    check("kirill homoglyph bardoshli", is_menu_text("👤 Prоfile & Settings", "settings"))  # 'о' = kirill
    check("begona matn ushlanmaydi", not is_menu_text("➕ Bugun nima", "new_post"))
    check("bo'sh/None matn istisno bermaydi",
          normalize_button_text(None) == "" and not is_menu_text(None, "new_post")
          and not is_menu_text("", "new_post"))
    check("button_variants to'liq + sof shakl qaytaradi",
          button_variants("➕ New post") == ("➕ new post", "new post"))
    check("button_texts mavjud kalitlarni yig'adi",
          "➕ New post" in button_texts("btn_new_post"))
    check("button_texts yo'q kalitni tugma qilib qo'shmaydi",
          "no_such_button_key" not in button_texts("no_such_button_key"))


def test_weekday_buttons_three_languages():
    print("== 4. Hafta kuni tugmalari (index'ga o'girish) ==")
    for idx, texts in enumerate(
        (("Dushanba", "Понедельник", "Monday"),
         ("Seshanba", "Вторник", "Tuesday"),
         ("Chorshanba", "Среда", "Wednesday"),
         ("Payshanba", "Четверг", "Thursday"),
         ("Juma", "Пятница", "Friday"),
         ("Shanba", "Суббота", "Saturday"),
         ("Yakshanba", "Воскресенье", "Sunday"))
    ):
        for text in texts:
            check(f"weekday_index({text!r}) == {idx}", weekday_index(text) == idx, str(weekday_index(text)))
        for lang in LANGS:
            check(f"weekday_label({idx}, {lang!r}) {texts[LANGS.index(lang)]!r} ga teng",
                  weekday_label(idx, lang) == texts[LANGS.index(lang)],
                  weekday_label(idx, lang))
    check("begona hafta kuni → None", weekday_index("salom") is None)
    check("klaviatura tugmalari ham taniyadi", weekday_index(get_text("np_weekday_4", "en")) == 4)


def test_registered_filters_are_trilingual():
    """``handlers/__init__.py``dagi HAR BIR ``exact(...)`` filtri EN/RU bilan ham kelishi kerak.

    Test manbani AST orqali o'qiydi: ``exact(...)`` chaqiruvlaridagi konstanta
    arqumentlar ``keyboards.default`` dan yechiladi, so'ng shu tugma oilasidagi
    UCHALA til yorlig'i hosil qilingan filtrga solinadi. Bu — "klaviatura EN
    bo'lsa tugma ishlamaydi" xatosining doimiy to'sig'i.
    """
    print("== 5. Ro'yxatdan o'tgan barcha exact(...) filtrlari 3 tilli ==")
    src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    ns = {name: getattr(kd, name) for name in dir(kd) if isinstance(getattr(kd, name), str)}
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("exact", "exact_i18n"):
            vals = []
            for arg in node.args:
                if isinstance(arg, ast.Name):
                    val = ns.get(arg.id)
                    if isinstance(val, str):
                        vals.append(val)
                elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    vals.append(arg.value)
                elif isinstance(arg, ast.Call) and getattr(arg.func, "id", "") == "get_text" \
                        and arg.args and isinstance(arg.args[0], ast.Constant):
                    for lang in LANGS:
                        vals.append(get_text(arg.args[0].value, lang))
            if vals:
                calls.append((node.lineno, vals))
    check("handlers/__init__.py da exact(...) filtrlari topildi", len(calls) >= 20, str(len(calls)))

    broken = []
    for lineno, vals in calls:
        flt = exact(*vals)
        for val in vals:
            shapes = button_variants(val)
            action = kd._LABEL_TO_ACTION.get(shapes[0]) if shapes else None
            for label in MENU_TEXTS.get(action or "", ()):
                if not filter_matches(flt, label):
                    broken.append((lineno, val, label))
    check("barcha exact(...) filtrlari tugma oilasining har bir tilini ushlaydi",
          not broken, str(broken[:6]))


def test_new_post_flow_buttons_three_languages():
    print("== 6. '➕ Yangi post' oqimidagi tugmalar (skip / vaqt / hafta kuni) ==")
    from handlers.new_post import SKIP_BUTTON_TEXTS, is_skip_button_text

    for text in ("➡️ Tugmasiz davom etish", "➡️ Продолжить без кнопки",
                 "➡️ Continue without button", "⏭ Skip", "Skip", "O'tkazib yuborish"):
        check(f"is_skip_button_text({text!r})", is_skip_button_text(text))
    check("SKIP_BUTTON_TEXTS EN variantini ham o'z ichiga oladi",
          any(normalize_button_text(t) == "skip" for t in SKIP_BUTTON_TEXTS),
          str(SKIP_BUTTON_TEXTS[:6]))
    check("skip ro'yxati bo'sh matnni ushlamaydi", not is_skip_button_text(""))

    # Vaqt/tugma/bosqich matnlari — klaviatura qaysi tilda bo'lishidan qat'iyoq.
    flows = {
        "np_time_5m": ("⚡ 5 daqiqa", "⚡ 5 минут", "⚡ 5 minutes"),
        "np_time_15m": ("⚡ 15 daqiqa", "⚡ 15 минут", "⚡ 15 minutes"),
        "np_time_1h": ("⚡ 1 soat", "⚡ 1 час", "⚡ 1 hour"),
        "np_time_daily": ("🔁 Har kuni (bir vaqtda)", "🔁 Ежедневно (в одно время)", "🔁 Daily (same time)"),
        "np_del_24h": ("⏳ 24 soat (1 kun)", "⏳ 24 часа (1 день)", "⏳ 24 hours (1 day)"),
        "np_del_never": ("❌ O'chirilmasin (Doimiy)", "❌ Не удалять (постоянно)", "❌ Never delete (Permanent)"),
        "np_dur_1w": ("1 hafta", "1 неделя", "1 week"),
        "np_dur_inf": ("♾ Cheksiz", "♾ Бессрочно", "♾ Forever"),
        "np_url_add": ("🔗 URL tugma qo'shish", "🔗 Добавить URL-кнопку", "🔗 Add URL button"),
        "np_all_channels": ("🌐 Barchasiga birdaniga", "🌐 Сразу во все", "🌐 To all at once"),
        "np_ai_assistant": ("✨ AI Yordamchi", "✨ ИИ-помощник", "✨ AI Assistant"),
    }
    for action, labels in flows.items():
        for label in labels:
            check(f"is_menu_text({label!r}, {action!r})", is_menu_text(label, action))
        for lang in LANGS:
            key = action  # np_btn_* kalitlari registry'ga shu nom bilan turgan
            if has_key(f"np_btn_{key[3:]}", lang):
                rendered = get_text(f"np_btn_{key[3:]}", lang)
                check(f"klaviatura({lang}) [{action}] → routing taniydi: {rendered!r}",
                      is_menu_text(rendered, action), rendered)

    # Reaksiyasiz/ortga qadamlar ham 3 tilda.
    check("'➡️ Reaksiyasiz davom etish' (uz) taniyladi",
          is_menu_text("➡️ Reaksiyasiz davom etish", "np_no_reactions"))
    check("'➡️ Продолжить без реакций' (ru) taniyladi",
          is_menu_text("➡️ Продолжить без реакций", "np_no_reactions"))
    check("'➡️ Continue without reactions' (en) taniyladi",
          is_menu_text("➡️ Continue without reactions", "np_no_reactions"))
    check("'🔙 Back' tasdiqlash ekranidan orqaga olib qaytadi",
          is_menu_text("🔙 Back", "np_back_confirm"))


# ==========================================================================
# 2. QISM: SANA / VAQT LOKALIZATSIYASI
# ==========================================================================
def test_date_format_styles():
    print("== 7. utils.date_format — sana/vaqt ko'rinishlari ==")
    dt = _aware()
    check("uz schedule", format_datetime(dt, "uz") == "2026-09-05 14:00", format_datetime(dt, "uz"))
    check("ru schedule", format_datetime(dt, "ru") == "2026-09-05 14:00", format_datetime(dt, "ru"))
    check("en schedule", format_datetime(dt, "en") == "Sep 05, 2026 14:00", format_datetime(dt, "en"))
    check("uz list", format_datetime(dt, "uz", style="list") == "05 Sent 14:00", format_datetime(dt, "uz", style="list"))
    check("ru list", format_datetime(dt, "ru", style="list") == "05 сент 14:00", format_datetime(dt, "ru", style="list"))
    check("en list", format_datetime(dt, "en", style="list") == "Sep 05 14:00", format_datetime(dt, "en", style="list"))
    check("uz date", format_date(dt, "uz") == "05.09.2026", format_date(dt, "uz"))
    check("ru date", format_date(dt, "ru") == "05.09.2026", format_date(dt, "ru"))
    check("en date", format_date(dt, "en") == "Sep 05, 2026", format_date(dt, "en"))
    check("clock (uz)", format_time(dt, "uz") == "14:00")
    check("clock (str '09:30:00')", format_time("09:30:00", "en") == "09:30", format_time("09:30:00", "en"))
    check("month_day", format_datetime(dt, "en", style="month_day") == "Sep 05", format_datetime(dt, "en", style="month_day"))
    check("naive datetime ham qabul qilinadi",
          format_datetime(datetime(2026, 9, 5, 14, 0), "en") == "Sep 05, 2026 14:00")
    check("date obyekti ham ishlaydi",
          format_date(__import__("datetime").date(2026, 9, 5), "en") == "Sep 05, 2026")
    check("ISO satrdan o'qiladi", format_datetime("2026-09-05T14:00:00", "en") == "Sep 05, 2026 14:00")
    check("yaroqsiz kiritish → bo'sh satr (crash yo'q)",
          format_datetime("salom", "en") == "" and format_datetime(None, "uz") == "")
    check("hafta kuni indeksi buzilganda '?'", weekday_label(None, "en") == "?")
    check("norels til → standart (uz) formatga qaytadi",
          format_datetime(dt, "de") == format_datetime(dt, "uz"))
    check("locale_for", locale_for("ru").startswith("ru") and locale_for("en").startswith("en"))
    check("weekday_label oralangan indeksda ham xato bermaydi",
          weekday_label(99, "en") in ("?", "Sunday", ""))


def test_relative_day_labels():
    print("== 8. 'Bugun/Сегодня/Today' — nisbiy kunlar ==")
    now = TZ.localize(datetime(2026, 9, 4, 8, 0))
    today = TZ.localize(datetime(2026, 9, 4, 23, 30))
    tomorrow = TZ.localize(datetime(2026, 9, 5, 14, 0))
    far = TZ.localize(datetime(2026, 9, 20, 9, 0))
    check("uz bugun", format_list_datetime(today, "uz", now) == "Bugun 23:30", format_list_datetime(today, "uz", now))
    check("ru bugun", format_list_datetime(today, "ru", now) == "Сегодня 23:30")
    check("en bugun", format_list_datetime(today, "en", now) == "Today 23:30")
    check("uz ertaga", format_list_datetime(tomorrow, "uz", now) == "Ertaga 14:00")
    check("ru ertaga", format_list_datetime(tomorrow, "ru", now) == "Завтра 14:00")
    check("en ertaga", format_list_datetime(tomorrow, "en", now) == "Tomorrow 14:00")
    check("uz uzoq sana oy nomi bilan", format_list_datetime(far, "uz", now) == "20 Sent 09:00",
          format_list_datetime(far, "uz", now))
    check("en uzoq sana oy nomi bilan", format_list_datetime(far, "en", now) == "Sep 20 09:00",
          format_list_datetime(far, "en", now))
    check("ru uzoq sana — lotin oy nomi EMAS", "Сент" in format_list_datetime(far, "ru", now).title()
          or "сент" in format_list_datetime(far, "ru", now), format_list_datetime(far, "ru", now))
    check("dt_today/dt_tomorrow kalitlari 3 tilda bor",
          all(has_key("dt_today", l) and has_key("dt_tomorrow", l) for l in LANGS))
    check("kiritish bo'sh bo'lsa — bo'sh satr", format_list_datetime(None, "en", now) == "")


def test_input_format_hint_unchanged():
    print("== 9. Kiriting formati (parser) tilga bog'liq emas ==")
    # Parser faqat DD.MM.YYYY / ISO / 05/09/2026 ni o'qiydi — shu sababli
    # YO'RIQNOMA har tilda bir xil bo'lib qolishi KERAK (en: "Sep 05, 2026"
    # yozib kiritilsa, o'qilmaydi).
    for lang in LANGS:
        check(f"schedule_hint({lang!r}) == 'DD.MM.YYYY HH:MM'",
              schedule_hint(lang) == "DD.MM.YYYY HH:MM", schedule_hint(lang))
        check(f"np_time_ask[{lang}] formatni ko'rsatadi",
              "DD.MM.YYYY" in get_text("np_time_ask", lang))
        check(f"schedule_hint({lang!r}) matnda so'zma-so'z uchraydi",
              schedule_hint(lang) in get_text("np_time_ask", lang),
              get_text("np_time_ask", lang)[:120])
        check(f"np_time_ask[{lang}] misoli parser o'qiy oladi",
              parse_schedule_input("05.09.2026 14:00", _aware(year=2026, month=9, day=1))[0] is not None)


def test_post_preview_dates_localized():
    print("== 10. Post preview (tasdiqlash kartasi) sanasi ==")
    from handlers.new_post import _build_preview_text

    dt = _aware()
    for lang, expected in (("uz", "2026-09-05 14:00"), ("ru", "2026-09-05 14:00"),
                           ("en", "Sep 05, 2026 14:00")):
        ctx = SimpleNamespace(user_data={
            "lang": lang, "selected_channel_title": "Kanal", "post_type": "text",
            "content": "Salom, dunyo!", "confirm_post_time": dt,
            "confirm_recurrence_type": "none",
        })
        preview = _build_preview_text(ctx)
        check(f"preview[{lang}] sana: {expected}", expected in preview, preview[:200])

    # Haftalik takrorlanish — hafta kuni EN'da o'zbekcha bo'lmasin.
    weekly = SimpleNamespace(user_data={
        "lang": "en", "selected_channel_title": "News", "post_type": "text",
        "content": "Hello!", "confirm_recurrence_type": "weekly",
        "confirm_recurrence_time_str": "09:30", "confirm_recurrence_day": 4,
    })
    preview_en = _build_preview_text(weekly)
    check("preview[en] hafta kuni 'Friday'", "Friday" in preview_en, preview_en[:200])
    check("preview[en] hafta kuni o'zbekcha EMAS", "Juma" not in preview_en)
    check("preview[en] vaqt '09:30'", "09:30" in preview_en, preview_en[:200])

    weekly.user_data["lang"] = "uz"
    check("preview[uz] hafta kuni 'Juma'", "Juma" in _build_preview_text(weekly))
    weekly.user_data["lang"] = "ru"
    check("preview[ru] hafta kuni 'Пятница'", "Пятница" in _build_preview_text(weekly))

    # Kundalik takrorlanish vaqt ham tilga mos formatda (en: HH:MM).
    daily = SimpleNamespace(user_data={
        "lang": "en", "selected_channel_title": "News", "post_type": "text",
        "content": "Hi", "confirm_recurrence_type": "daily",
        "confirm_recurrence_time_str": "10:00:00",
    })
    check("preview[en] daily 'Daily at 10:00'", "Daily at 10:00" in _build_preview_text(daily),
          _build_preview_text(daily)[:200])


def test_schedule_line_and_queue_localized():
    print("== 11. format_schedule_line / navbat ro'yxati sanalari ==")
    from utils.helpers import format_schedule_line
    dt = _aware()
    once_en = format_schedule_line(dt, "none", None, None, "en")
    check("schedule_line[en] 'Sep 05, 2026 14:00'", "Sep 05, 2026 14:00" in once_en, once_en)
    check("schedule_line[uz] ISO ko'rinishi saqlangan",
          "2026-09-05 14:00" in format_schedule_line(dt, "none", None, None, "uz"))
    check("schedule_line[ru] ISO ko'rinishi saqlangan",
          "2026-09-05 14:00" in format_schedule_line(dt, "none", None, None, "ru"))
    daily_ru = format_schedule_line(None, "daily", None, datetime.strptime("10:00", "%H:%M").time(), "ru")
    check("schedule_line[ru] daily vaqt 10:00", "10:00" in daily_ru, daily_ru)
    weekly_en = format_schedule_line(None, "weekly", 4, datetime.strptime("10:00", "%H:%M").time(), "en")
    check("schedule_line[en] weekly 'Friday'", "Friday" in weekly_en, weekly_en)
    check("schedule_line unknown holatda ham tilga mos",
          get_text("pend_schedule_unknown", "en") == format_schedule_line(None, "none", None, None, "en"))

    # Navbat ro'yxati (%d-%b o'rniga til oy nomlari).
    from handlers.queue import _format_queue_item
    now = datetime.now(TZ)
    sched = (now + timedelta(days=5)).replace(hour=9, minute=0, second=0, microsecond=0)
    row = (7, "Kanal", "text", "Post matni", sched, 1, "-1001")
    item_en = _format_queue_item(row, 1, "en")
    item_ru = _format_queue_item(row, 1, "ru")
    item_uz = _format_queue_item(row, 1, "uz")
    month_en = sched.strftime("%b")
    check(f"queue[en] oy nomi lotincha ({month_en})", month_en in item_en, item_en)
    check("queue[ru] oy nomi ruscha (сент/окт/…)",
          not re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", item_ru), item_ru)
    check("queue[uz] oy nomi o'zbekcha",
          not re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", item_uz), item_uz)
    check("queue[en] raqam bilan boshlanadi", item_en.startswith("1. "), item_en)
    check("queue bo'sh sana bilan crash bermaydi",
          "1. " in _format_queue_item((7, "Kanal", "text", "x", None, 1, "-1"), 1, "en"))

    # Navbat sloti yorlig'i ("Bugun"/"Ertaga") ham tarjima qilinadi.
    from handlers.new_post import _queue_slot_label
    check("slot label[uz]", _queue_slot_label("Bugun", "uz") == get_text("np_label_today", "uz"))
    check("slot label[ru]", _queue_slot_label("Bugun", "ru") == get_text("np_label_today", "ru"))
    check("slot label[en]", _queue_slot_label("Bugun", "en") == get_text("np_label_today", "en"))
    check("slot label sana bo'lsa o'zgarmaydi", _queue_slot_label("05.09.2026", "en") == "05.09.2026")
    check("slot label bo'sh bo'lsa bo'sh satr", _queue_slot_label(None, "en") == "")


def test_technical_lines_stripped_in_all_languages():
    print("== 12. Kanalga chiqib qoladigan texnik qatorlar (uz/ru/en) ==")
    from scheduler import sanitize_channel_content

    header = {
        "uz": "📋 <b>Postni tasdiqlang:</b>",
        "ru": "📋 <b>Подтвердите пост:</b>",
        "en": "📋 <b>Confirm the post:</b>",
    }
    lines = {
        "uz": [
            "📢 <b>Kanal:</b> News", "📦 <b>Turi:</b> Text", "⏰ Vaqt belgilanmagan",
            "🔘 <b>Tugma:</b> Batafsil → https://x.uz", "👍 Reaksiyalar: 👍 ❤️",
            "⏳ <b>Avto-o'chirish:</b> 24 soat", "📋 <b>Matn:</b>",
            "🖼 <b>Albom:</b> 6 ta rasm", "🔁 Har kuni, soat 10:00 da",
            "📅 Har Juma, soat 09:30 da",
        ],
        "en": [
            "📢 <b>Channel:</b> News", "📦 <b>Type:</b> Text", "⏰ Time not set",
            "🔘 Button: Read more → https://x.com", "👍 Reactions: disabled",
            "⏳ <b>Auto-delete:</b> 24 h", "📋 <b>Text:</b>",
            "🖼 <b>Album:</b> 6 photos", "🔁 Daily at 10:00",
            "📅 Every Friday at 09:30",
            "⏰ <b>Sep 05, 2026 14:00</b> (Tashkent time)",
            "⚠️ Note: the text is 1500 characters — shortened to 1024 chars for publishing.",
        ],
        "ru": [
            "📢 <b>Канал:</b> News", "📦 <b>Тип:</b> Text", "⏰ <b>Время не указано</b>",
            "🔘 <b>Кнопка:</b> Подробнее → https://x.ru", "👍 Реакции: 👍 ❤️",
            "⏳ <b>Авто-удаление:</b> 24 ч.", "📋 <b>Текст:</b>",
            "🔁 Ежедневно, в 10:00", "📅 Каждый Пятница, в 09:30",
        ],
    }
    for lang, rows in lines.items():
        body = "Saklanishi kerak bo'lgan post matni."
        text = "\n".join([header[lang]] + rows + [body])
        out = sanitize_channel_content(text)
        check(f"sanitize[{lang}]: barcha texnik qatorlar o'chirildi",
              out == body, out)
    # Foydalanuvchining o'z matni — tegishli bo'lmasa — tegilsin.
    user_text = "📢 E'lon: yangi mahsulot keldi!\n👍 Biz bilan qoling"
    check("sanitize: foydalanuvchi matni buzilmaydi",
          sanitize_channel_content(user_text) == user_text, sanitize_channel_content(user_text))
    check("sanitize: bo'sh/None kiritish xavfsiz", sanitize_channel_content("") == "")


# ==========================================================================
# 3. QISM: 📷 RASM MODERATSIYASI VA VISION (photo_check / ai_assistant)
# ==========================================================================
def test_photo_check_is_trilingual():
    print("== 13. photo_check: admin klaviaturasi, caption va javoblar ==")
    from handlers.photo_check import admin_photo_caption, admin_photo_keyboard

    expect_buttons = {
        "uz": ("✅ Tasdiqlash", "❌ Rad etish"),
        "ru": ("✅ Подтвердить", "❌ Отклонить"),
        "en": ("✅ Approve", "❌ Reject"),
    }
    for lang, expected in expect_buttons.items():
        kb = admin_photo_keyboard(4242, lang)
        got = tuple(b.text for row in kb.inline_keyboard for b in row)
        check(f"admin klaviatura[{lang}] tugmalari", got == expected, str(got))
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        check(f"admin klaviatura[{lang}] callback_data'sida user_id bor",
              all("4242" in d for d in data), str(data))

    cap_uz = admin_photo_caption(4242, "uz")
    cap_ru = admin_photo_caption(4242, "ru")
    cap_en = admin_photo_caption(4242, "en")
    check("caption[uz] ID bilan", "4242" in cap_uz and "Rasm yuborildi" in cap_uz, cap_uz)
    check("caption[ru] tarjimasi", "Получено фото" in cap_ru and "4242" in cap_ru, cap_ru)
    check("caption[en] tarjimasi", "Photo received" in cap_en and "4242" in cap_en, cap_en)
    check("caption'da {user_id} o'rniga qolmagan", "{user_id}" not in cap_en)

    # Foydalanuvchi javobi: UZ metin spam-regressiya testi talab qilgan
    # iboralarni SAQLAB qolishi shart.
    sent_uz = get_text("pc_sent_user", "uz")
    check("pc_sent_user[uz] 'adminga yuborildi' iborasi saqlangan", "adminga yuborildi" in sent_uz, sent_uz)
    check("pc_sent_user[uz] 'Tasdiqlanishi kutilmoqda' saqlangan", "Tasdiqlanishi kutilmoqda" in sent_uz)
    sent_ru, sent_en = get_text("pc_sent_user", "ru"), get_text("pc_sent_user", "en")
    check("pc_sent_user[ru] ruscha", "администратору" in sent_ru and "Rasmingiz" not in sent_ru)
    check("pc_sent_user[en] inglizcha", "admin" in sent_en and "Rasmingiz" not in sent_en, sent_en)

    # Qaror xabarlari ham uchala tilda va HTML teglar bilan.
    for key in ("pc_approved_admin", "pc_rejected_admin", "pc_pro_granted", "pc_reject_notice",
                "pc_no_permission", "pc_bad_callback", "pc_db_error"):
        values = {l: get_text(key, l) for l in LANGS}
        check(f"{key} — 3 tilda to'liq va farqli",
              all(v.strip() and v != key for v in values.values()), str(values))
        check(f"{key} — uz/en qiymatlari bir xil emas",
              values["uz"] != values["en"] or key in (), str(values))
    check("pc_approved_admin[en] {user_id} joylashuvi",
          "{user_id}" in get_text("pc_approved_admin", "en"))

    # _pc_text kalit yo'q bo'lsa ham istisno bermaydi.
    from handlers.photo_check import _pc_text
    check("_pc_text noma'lum kalitda crash bermaydi", _pc_text("pc_nope_key", "en") in ("pc_nope_key", ""))


def test_ai_vision_messages_localized():
    print("== 14. Vision (rasm tahlili) xabarlari tillarga mos ==")
    from handlers.ai_assistant import AI_PHOTO_UNAVAILABLE_MSG, _photo_unavailable_msg

    msgs = {l: _photo_unavailable_msg(l) for l in LANGS}
    check("ai_photo_unavailable[en] inglizcha", "AI couldn't analyze" in msgs["en"], msgs["en"])
    check("ai_photo_unavailable[ru] ruscha", "ИИ не смог" in msgs["ru"], msgs["ru"])
    check("ai_photo_unavailable[uz] o'zbekcha", "rasmni tahlil qila olmadi" in msgs["uz"])
    check("konstanta eski qiymatni saqlaydi (orqaga moslik)",
          AI_PHOTO_UNAVAILABLE_MSG == get_text("ai_photo_unavailable", "uz"))
    check("noma'lum til → standart til (crash yo'q)", _photo_unavailable_msg("de") == msgs["uz"])
    # Kalitlar topilmasa xabarning o'rnida kalit ko'rinib qolmasin.
    for key in ("ai_photo_unavailable", "ai_target_all_line", "ai_target_all_name"):
        check(f"{key} 3 tilda mavjud", all(has_key(key, l) for l in LANGS))
    check("ai_target_all_line[en] HTML bilan",
          "<b>" in get_text("ai_target_all_line", "en") and "All connected channels" in get_text("ai_target_all_line", "en"))
    check("AI klaviaturasi tugmalari ham 3 tilda routing'da",
          is_menu_text(get_text("np_btn_ai_assistant", "en"), "np_ai_assistant"))


# ==========================================================================
# 4. QISM: LUG'AT PARITETI (yangi kalitlar bilan buzilmagan)
# ==========================================================================
def test_translation_parity_intact():
    print("== 15. Lug'at pariteti (uz/ru/en) buzilmagan ==")
    rep = translation_parity_report()
    check("paritet: faqat UZ'da qolgan kalit yo'q", not rep["uz_only"], str(rep["uz_only"][:5]))
    check("paritet: faqat RU'da qolgan kalit yo'q", not rep["ru_only"], str(rep["ru_only"][:5]))
    check("paritet: EN'da yetishmayotgan kalit yo'q", not rep["en_missing"], str(rep["en_missing"][:5]))
    fmt = translation_format_report()
    check("format: {joylashuv} kalitları bir xil argumentlar bilan",
          not fmt["mismatch"], str(fmt["mismatch"][:5]))
    # Yangi qo'shilgan kalitlar ham ro'yxatda bo'lsin.
    for key in ("dt_today", "dt_tomorrow", "pc_sent_user", "pc_admin_caption",
                "pc_btn_approve", "pc_btn_reject", "ai_photo_unavailable"):
        check(f"yangi kalit mavjud: {key}", all(has_key(key, l) for l in LANGS))
    # EN tugma yorliqlari o'zbekcha qoldiq bo'lmasin.
    for key in ("btn_new_post", "btn_settings", "btn_pending", "btn_queue", "np_btn_time_5m"):
        en, uz = get_text(key, "en"), get_text(key, "uz")
        if has_key(key, "en"):
            check(f"EN tugma [{key}] UZ'dan farq qiladi", en != uz, f"{en!r} vs {uz!r}")


def test_handler_source_contract():
    print("== 16. Handler shartnomasi: registry'dan foydalanish ==")
    src = (ROOT / "handlers" / "new_post.py").read_text(encoding="utf-8")
    check("new_post: registry importi bor",
          "is_menu_text" in src and "menu_texts" in src and "weekday_index" in src)
    check("new_post: date_format importi bor",
          "from utils.date_format import" in src)
    check("new_post: eski uz/ru qat'iy solishtiruvi qolmagan",
          "BTN_T_5MIN, BTN_T_5MIN_RU" not in src and "WEEKDAY_MAP_RU.get(text)" not in src)
    import inspect
    from handlers.new_post import _build_preview_text as _preview_fn
    preview_src = inspect.getsource(_preview_fn)
    # Docstring'dagi "avval shunday edi" izohi hisobga olinmaydi — faqat JISM.
    preview_body = preview_src.split('"""')[2] if preview_src.count('"""') >= 2 else preview_src
    check("new_post: preview sana uchun format_datetime ishlatadi",
          "format_datetime(" in preview_body and "strftime(" not in preview_body)
    check("new_post: preview hafta kuni tilga mos (WEEKDAY_LABELS_RU yo'q)",
          "WEEKDAY_LABELS_RU" not in preview_body and "weekday_label(" in preview_body)
    init_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for needle in ("exact(BTN_NEW_POST, BTN_NEW_POST_RU)",
                   "exact(BTN_AI_STUDIO, BTN_AI_STUDIO_RU)",
                   "exact(BTN_BACK, BTN_MAIN_MENU, BTN_BACK_RU)"):
        check(f"routing qatori saqlangan: {needle}", needle in init_src)
    pc_src = (ROOT / "handlers" / "photo_check.py").read_text(encoding="utf-8")
    check("photo_check: matnlar lug'atdan olinadi",
          '_pc_text("pc_' in pc_src and '"pc_sent_user"' in pc_src and 'safe_t(key, lang)' in pc_src)
    _pc_code_lines = [
        ln for ln in pc_src.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    check("photo_check: qotirilgan o'zbekcha javob qolmagan",
          not any("Rasmingiz adminga yuborildi" in ln for ln in _pc_code_lines),
          str([ln for ln in _pc_code_lines if "Rasmingiz adminga" in ln][:1]))
    check("photo_check: qotirilgan tugma yorlig'i qolmagan",
          not any('"✅ Tasdiqlash"' in ln or '"❌ Rad etish"' in ln for ln in _pc_code_lines))
    check("photo_check: moderatsiya iboralari lug'atda saqlangan",
          "adminga yuborildi" in (ROOT / "locales" / "translations.py").read_text(encoding="utf-8"))


def test_remaining_flow_gaps():
    """Qo'lda yozilgan solishtiruvlar ham registry'ga o'tkazilgan bo'lsin."""
    print("== 17. Qolgan oqimlar: uslub / AI vaqt / admin bekor qilish ==")
    from keyboards.default import tone_from_text, tone_labels

    tone_cases = {
        "formal": ("👔 Rasmiy / Biznes", "👔 Официальный / Бизнес", "👔 Formal / Business",
                   "Formal / Business", "👔 rasmiy / biznes"),
        "friendly": ("😊 Do'stona / Samimiy", "😊 Дружелюбный / Тёплый", "😊 Friendly / Warm"),
        "concise": ("⚡️ Qisqa / Yangiliklar", "⚡️ Кратко / Новости", "⚡️ Brief / News"),
        "engaging": ("🎉 Ko'ngilochar / Emotsional", "🎉 Развлекательный / Эмоциональный",
                     "🎉 Fun / Emotional"),
    }
    for tone, labels in tone_cases.items():
        for label in labels:
            check(f"tone_from_text({label!r}) == {tone!r}", tone_from_text(label) == tone,
                  str(tone_from_text(label)))
    check("tone_from_text begona matnda None qaytaradi", tone_from_text("salom") is None)
    check("tone_from_text bo'sh matnda xato bermaydi", tone_from_text(None) is None and tone_from_text("") is None)
    check("tone_labels[en] inglizcha yorliqlar bilan",
          tone_labels("en")["formal"] == get_text("ch_tone_formal", "en"))
    check("tone_labels noma'lum tilda UZ'ga qaytadi", tone_labels("de") == tone_labels("uz"))

    # AI Studio vaqt oqimi — endi qotirilgan BTN_T_* solishtiruvi yo'q.
    ai_src = (ROOT / "handlers" / "ai_assistant.py").read_text(encoding="utf-8")
    check("ai_assistant: vaqt tugmalar registry orqali o'qiladi",
          "is_menu_text(text, \"np_time_5m\")" in ai_src
          and "if text in (BTN_T_DAILY, BTN_T_WEEKLY)" not in ai_src)
    # Admin oqimi — "❌ Cancel" (EN) ham bekor qiladi.
    ad_src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("admin: bekor qilish registry orqali (uz/ru/en)",
          'is_menu_text(text, "cancel", "main_menu")' in ad_src)
    check("admin: AI sozlamalari bosqichida ham menyuga chiqish 3 tilda",
          'if text == BTN_MAIN_MENU:' not in ad_src
          and 'is_menu_text(text, "main_menu", "back", "cancel")' in ad_src)
    check("'❌ Cancel' / '❌ Отмена' bekor tugmasi sifatida taniyladi",
          is_menu_text("❌ Cancel", "cancel") and is_menu_text("❌ Отмена", "cancel"))
    # Queue slot qo'shish bosqichida ham orqaga qaytish 3 tilda.
    q_src = (ROOT / "handlers" / "queue.py").read_text(encoding="utf-8")
    check("queue: slot bekor qilish registry orqali",
          'is_menu_text(text, "back", "main_menu", "np_back_confirm")' in q_src)


# ==========================================================================
def main():
    print("=" * 70)
    print("== 🌐 UCH TILLI TUGMA FILTRLARI + SANA LOKALIZATSIYASI TESTI ==")
    print("=" * 70)
    test_registry_covers_three_languages()
    test_exact_filter_expands_languages()
    test_normalization_tolerance()
    test_weekday_buttons_three_languages()
    test_registered_filters_are_trilingual()
    test_new_post_flow_buttons_three_languages()
    test_date_format_styles()
    test_relative_day_labels()
    test_input_format_hint_unchanged()
    test_post_preview_dates_localized()
    test_schedule_line_and_queue_localized()
    test_technical_lines_stripped_in_all_languages()
    test_photo_check_is_trilingual()
    test_ai_vision_messages_localized()
    test_translation_parity_intact()
    test_handler_source_contract()
    test_remaining_flow_gaps()

    print("\n" + "=" * 70)
    print(f"O'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha uch tilli tugma/sana/photo_check testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
