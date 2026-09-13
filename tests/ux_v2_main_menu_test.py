#!/usr/bin/env python3
"""UX V2 (2-MIKRO QADAM) — ASOSIY MENYU QAT'IY 6 TUGMA STANDARTI.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  Asosiy menyuda FAQAT va FAQAT 6 ta tugma (UZ/RU/EN):
           [✨ Kontent yaratish]   [📢 Kanallarim]
           [📅 Rejalashtirilgan]   [📊 Statistika]
           [💎 PRO]                [⚙️ Sozlamalar]
  TEST 2:  Oddiy foydalanuvchiga HECH QACHON "Admin Panel" ko'rinmaydi;
           faqat ADMIN_IDS a'zolariga 6 tugma + alohida [⚙️ Admin Panel].
           Eski tarqoq tugmalar (Qo'llanma / Qo'shimcha funksiyalar /
           Yangi post / AI Studio / Magic Post / Image Post / Post Score /
           eski PRO & Kabinet yorliqlari) asosiy menyuda YO'Q.
  TEST 3:  ROUTING — yangi 6 tugma va barcha ESKI tugmalar (keshda qolgan
           eski xabarlar uchun) real router'da to'g'ri bo'limga tushadi,
           fallback'ga emas (backward compatibility).
  TEST 4:  STARS_PLANS SSOT — handlers/subscription.py da lokal shadowing
           YO'Q; precheckout (_validate_stars_payload) va PaymentService
           config.STARS_PLANS (yagona manba) bilan to'liq mos.
  TEST 5:  /start ONBOARDING — 3 tilda ixcham matn (PostAssist + rasm/matn/
           ovoz) + standart 6-tugma menyu; admin 7-tugma; qayta foydalanuvchi
           start_hello matnini oladi.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/ux_v2_main_menu_test.py
"""
import asyncio
import os
import re
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:UX_V2_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10001")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0

# Spetsifikatsiyadagi UZ yorliqlari (qat'iy).
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
LANGS = ("uz", "ru", "en")

# Asosiy menyu — QAT'IY 6 TUGMA (3 tilda, tartibi bilan).
EXPECTED_MAIN = {
    "uz": (
        "✨ Kontent yaratish", "📢 Kanallarim",
        "📅 Rejalashtirilgan", "📊 Statistika",
        "💎 PRO", "⚙️ Sozlamalar",
    ),
    "ru": (
        "✨ Создать контент", "📢 Мои каналы",
        "📅 Запланированные", "📊 Статистика",
        "💎 PRO", "⚙️ Настройки",
    ),
    "en": (
        "✨ Create content", "📢 My channels",
        "📅 Scheduled", "📊 Statistics",
        "💎 PRO", "⚙️ Settings",
    ),
}

# Asosiy menyudan OLIB TASHLANGAN eski tugmalar (orqaga moslikda qoladi).
OLD_MAIN_BUTTONS = {
    "uz": (
        "➕ Yangi post", "✨ AI Studio", "⭐️ Premium",
        "👤 Kabinet & Sozlamalar", "📖 Qo'llanma / Bot haqida",
        "⚙️ Qo'shimcha funksiyalar", "✨ Magic Post",
        "📸 Rasm → Post", "📊 Post Score",
    ),
    "ru": (
        "➕ Новый пост", "✨ AI Studio", "⭐️ Premium",
        "👤 Кабинет & Настройки", "📖 Руководство / О боте",
        "⚙️ Дополнительные функции", "✨ Magic Post",
        "📸 Фото → Пост", "📊 Post Score",
    ),
    "en": (
        "➕ New post", "✨ AI Studio", "⭐️ Premium",
        "👤 Account & Settings", "📖 Guide / About",
        "⚙️ Extra features", "✨ Magic Post",
        "📸 Image → Post", "📊 Post Score",
    ),
}


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def kb_rows(markup):
    return [[b.text for b in row] for row in markup.keyboard]


def kb_flat(markup):
    return [t for row in kb_rows(markup) for t in row]


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import config                                             # noqa: E402
from handlers import register_all_handlers as _reg        # noqa: E402
from handlers.subscription import (                       # noqa: E402
    STARS_PLANS as SUB_STARS_PLANS,
    _validate_stars_payload,
)
from keyboards.default import (                           # noqa: E402
    get_main_keyboard, BTN_ADMIN_PANEL,
)
from locales.translations import get_text                 # noqa: E402
from services.payment_service import PaymentService       # noqa: E402


# ============================================================================
# TEST 1 — QAT'IY 6 TUGMA (UZ/RU/EN, oddiy foydalanuvchi)
# ============================================================================
def test_strict_six_buttons():
    print("\n== TEST 1: asosiy menyu — QAT'IY 6 tugma (uz/ru/en) ==")
    for lang in LANGS:
        expected = EXPECTED_MAIN[lang]
        kb = get_main_keyboard(False, lang=lang)
        rows = kb_rows(kb)
        flat = kb_flat(kb)
        check(f"user[{lang}]: aynan 6 tugma", len(flat) == 6, str(flat))
        check(f"user[{lang}]: 3 qator x 2 tugma",
              rows == [list(expected[0:2]), list(expected[2:4]), list(expected[4:6])],
              str(rows))
        # Production yo'li (context bilan) ham aynan 6 tugma.
        kb_ctx = get_main_keyboard(False, lang=lang, context=object())
        check(f"user[{lang}]: context bilan ham aynan 6 tugma",
              kb_flat(kb_ctx) == list(expected), str(kb_flat(kb_ctx)))
        # I18n paritet: klaviatura lug'at kalitlaridan chizilgan.
        keys = ("btn_create_content", "btn_my_channels", "btn_scheduled",
                "btn_statistics", "btn_premium", "btn_settings")
        check(f"user[{lang}]: yorliqlar lug'atdan (get_text)",
              flat == [get_text(k, lang) for k in keys], str(flat))


# ============================================================================
# TEST 2 — ADMIN PANEL FAQAT ADMIN'LARGA + ESKI TUGMALAR YO'Q
# ============================================================================
def test_admin_panel_visibility_and_removals():
    print("\n== TEST 2: Admin Panel faqat adminlar uchun + eski tugmalar olingan ==")
    for lang in LANGS:
        user_flat = kb_flat(get_main_keyboard(False, lang=lang))
        admin_rows = kb_rows(get_main_keyboard(True, lang=lang))
        admin_flat = [t for row in admin_rows for t in row]

        # Oddiy foydalanuvchiga Admin Panel HECH QACHON.
        check(f"user[{lang}]: Admin Panel ko'rinmaydi",
              BTN_ADMIN_PANEL not in user_flat, str(user_flat))
        # Admin: 6 tugma + alohida Admin Panel qatori (oxirida).
        check(f"admin[{lang}]: 6 tugma + Admin Panel = 7",
              len(admin_flat) == 7, str(admin_flat))
        check(f"admin[{lang}]: oxirgi qator = [Admin Panel]",
              admin_rows[-1] == [BTN_ADMIN_PANEL], str(admin_rows[-1]))
        check(f"admin[{lang}]: birinchi 3 qator = 6-tugma standart",
              admin_rows[:3] == [[EXPECTED_MAIN[lang][0], EXPECTED_MAIN[lang][1]],
                                 [EXPECTED_MAIN[lang][2], EXPECTED_MAIN[lang][3]],
                                 [EXPECTED_MAIN[lang][4], EXPECTED_MAIN[lang][5]]],
              str(admin_rows[:3]))
        # Eski tarqoq tugmalar asosiy menyudan olingan (user VA admin).
        for old in OLD_MAIN_BUTTONS[lang]:
            check(f"user[{lang}]: eski tugma yo'q — {old!r}", old not in user_flat)
            check(f"admin[{lang}]: eski tugma yo'q — {old!r}", old not in admin_flat)


# ============================================================================
# TEST 3 — ROUTING: yangi tugmalar + eski tugmalar (backward compatibility)
# ============================================================================
def _menu_handlers():
    """register_all_handlers orqali ro'yxatdagi exact(...) menyu handlerlari."""
    from telegram.ext import MessageHandler, filters

    class _Recorder:
        def __init__(self):
            self.handlers = []

        def add_handler(self, h, group=0):
            self.handlers.append(h)

    import handlers as H
    app = _Recorder()
    H.register_all_handlers(app)
    return H, [h for h in app.handlers
               if isinstance(h, MessageHandler) and isinstance(h.filters, filters.Regex)]


def _targets(H, handlers, label):
    """label matnini taniydigan handlerlarning chaqiradigan funksiya to'plami."""
    from telegram import Update
    upd = Update.de_json({
        "update_id": 1,
        "message": {
            "message_id": 10, "date": 0,
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42, "is_bot": False, "first_name": "Tester"},
            "text": label,
        },
    }, None)
    names = set()
    for h in handlers:
        if not h.check_update(upd):
            continue
        cb = h.callback
        if callable(cb) and getattr(cb, "__name__", "") != "<lambda>":
            names.add(getattr(cb, "__name__", str(cb)))
        else:
            # Lambda: guard_* o'ramalarini saqlamay, ichki funksiya nomini olamiz.
            for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                if n in ("guard_entry", "guard_menu"):
                    continue
                obj = getattr(H, n, None)
                if callable(obj):
                    names.add(n)
    return names


def test_routing_new_and_legacy_buttons():
    print("\n== TEST 3: routing — yangi 6 tugma + eski tugmalar (fallback EMAS) ==")
    H, handlers = _menu_handlers()

    # Yangi 6-tugma standarti — HAR BIR TILDA aniq bir maqsadga.
    new_routes = (
        ("btn_create_content", "ai_studio_menu_entry"),
        ("btn_my_channels", "channels_menu"),
        ("btn_scheduled", "queue_menu"),
        ("btn_statistics", "statistics_button"),
        ("btn_premium", "start_subscription"),
        ("btn_settings", "user_cabinet_menu"),
    )
    for key, expected in new_routes:
        for lang in LANGS:
            label = get_text(key, lang)
            names = _targets(H, handlers, label)
            check(f"yangi[{lang}] {label!r} → {expected}",
                  names == {expected}, str(sorted(names)))

    # Eski (keshda qolgan) tugmalar — xavfsiz mos bo'limga yo'naltiriladi.
    legacy_routes = (
        ("btn_new_post", "start_new_post"),
        ("btn_ai_studio", "ai_studio_menu_entry"),
        ("btn_help", "help_command"),
        ("btn_extras", "extras_menu"),
    )
    for key, expected in legacy_routes:
        for lang in LANGS:
            label = get_text(key, lang)
            names = _targets(H, handlers, label)
            check(f"eski[{lang}] {label!r} → {expected}",
                  expected in names and len(names) == 1, str(sorted(names)))

    # Eski qo'lda yozilgan yorliqlar (chat tarixidagi xabarlar).
    hard_legacy = (
        ("⭐️ Premium", "start_subscription"),
        ("👤 Kabinet & Sozlamalar", "user_cabinet_menu"),
        ("👤 Кабинет & Настройки", "user_cabinet_menu"),
        ("👤 Account & Settings", "user_cabinet_menu"),
        ("✨ Magic Post", "magic_post_entry"),
        ("📸 Rasm → Post", "image_post_entry"),
        ("📊 Post Score", "post_score_entry"),
    )
    for label, expected in hard_legacy:
        names = _targets(H, handlers, label)
        check(f"eski yorliq {label!r} → {expected}",
              expected in names and len(names) == 1, str(sorted(names)))


# ============================================================================
# TEST 4 — STARS_PLANS: YAGONA MANBA (SSOT), shadowing yo'q
# ============================================================================
def test_stars_plans_ssot():
    print("\n== TEST 4: STARS_PLANS — config (SSOT), precheckout va PaymentService mos ==")
    check("handlers.subscription.STARS_PLANS is config.STARS_PLANS (yagona obyekt)",
          SUB_STARS_PLANS is config.STARS_PLANS)

    # payment_service — aynan config qiymatlaridan qurilgan.
    for key in ("stars_1m", "stars_3m", "stars_1y"):
        cfg = config.STARS_PLANS[key]
        ps = PaymentService.STARS_PLANS[key]
        check(f"PaymentService {key}: stars == config",
              ps["stars"] == int(cfg["stars"]), f"{ps} vs {cfg}")
        check(f"PaymentService {key}: days == config",
              ps["days"] == int(cfg["days"]), f"{ps} vs {cfg}")

    # precheckout (subscription._validate_stars_payload) — config summalari bilan.
    for key in ("stars_1m", "stars_3m", "stars_1y"):
        stars = int(config.STARS_PLANS[key]["stars"])
        plan, err = _validate_stars_payload(
            f"sub_{key}_123", user_id=123, amount=stars, currency="XTR")
        check(f"precheckout {key}: config summasi qabul qilinadi",
              err is None and plan is not None and plan["stars"] == stars,
              f"plan={plan}, err={err}")
        plan_bad, err_bad = _validate_stars_payload(
            f"sub_{key}_123", user_id=123, amount=stars + 1, currency="XTR")
        check(f"precheckout {key}: noto'g'ri summa rad etiladi",
              plan_bad is None and err_bad is not None,
              f"plan={plan_bad}, err={err_bad}")

    # Shadowing yo'qligi: modul manbaida lokal STARS_PLANS dict'ı YO'Q.
    src = (ROOT / "handlers" / "subscription.py").read_text(encoding="utf-8")
    check("manbada lokal 'STARS_PLANS = {' qattiq dict yo'q (F811 bartaraf)",
          re.search(r"^STARS_PLANS\s*=\s*\{", src, re.M) is None)
    check("manbada config'dan import qilingan",
          re.search(r"from config import[\s\S]*?STARS_PLANS[\s\S]*?\)", src) is not None)


# ============================================================================
# TEST 5 — /start ONBOARDING (3 til) + 6-tugma menyu
# ============================================================================
def _run_start(is_new: bool, lang: str, user_id: int):
    """/start ni mock'lar bilan ishga tushirib (text, markup) qaytaradi."""
    import importlib
    import database as db_mod
    st_mod = importlib.import_module("handlers.start")

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "save_user":
            return is_new
        if name == "get_user_language":
            return lang
        if name == "get_user_onboarding":
            return None  # onboarding ma'lumoti yo'q → standart menyu
        if name == "is_premium":
            return False
        if name == "get_setting":
            return ""
        return None

    async def fake_check(bot, uid):
        return True, []

    async def fake_ad(uid):
        return ""

    class _Msg:
        def __init__(self):
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append((text, reply_markup, parse_mode))
            return None

    class _Bot:
        async def send_message(self, *a, **kw):
            return None

    user = SimpleNamespace(id=user_id, username="uxuser", full_name="Yangi User",
                           first_name="Yangi", language_code=lang)
    msg = _Msg()
    upd = SimpleNamespace(message=msg, effective_user=user, effective_message=msg)
    ctx = SimpleNamespace(bot=_Bot(), user_data={}, chat_data={}, args=[])

    orig = (db_mod.run_db, st_mod.check_user_subscribed, st_mod.get_smart_reply_ad_async)
    db_mod.run_db = fake_run_db
    st_mod.check_user_subscribed = fake_check
    st_mod.get_smart_reply_ad_async = fake_ad
    try:
        asyncio.run(st_mod.start(upd, ctx))
    finally:
        db_mod.run_db, st_mod.check_user_subscribed, st_mod.get_smart_reply_ad_async = orig
    assert msg.replies, "start() javob bermadi"
    return msg.replies[0]


def test_start_onboarding_three_langs():
    print("\n== TEST 5: /start onboarding (uz/ru/en) + 6-tugma menyu ==")
    for lang in LANGS:
        onb = get_text("start_onboarding", lang)
        # Matn: ixcham, tushunarli, 3 kirish usulini ko'rsatadi.
        check(f"onboarding[{lang}]: PostAssist taqdim etiladi", "PostAssist" in onb)
        check(f"onboarding[{lang}]: rasm/matn/ovoz (📸🎙) bor",
              "📸" in onb and "📝" in onb and "🎙" in onb, onb)

        # Yangi foydalanuvchi — onboarding matni + standart 6-tugma menyu.
        text, markup, parse_mode = _run_start(True, lang, 900001)
        check(f"/start[{lang}]: onboarding matni boshida",
              text.startswith(onb), text[:80])
        check(f"/start[{lang}]: HTML parse_mode", parse_mode == "HTML")
        labels = kb_flat(markup)
        check(f"/start[{lang}]: oddiy foydalanuvchida aynan 6 tugma",
              labels == list(EXPECTED_MAIN[lang]), str(labels))
        check(f"/start[{lang}]: Admin Panel YO'Q",
              BTN_ADMIN_PANEL not in labels, str(labels))

        # Qayta foydalanuvchi — start_hello (onboarding takrorlanmaydi).
        text2, markup2, _ = _run_start(False, lang, 900002)
        check(f"/start qayta[{lang}]: start_hello matni",
              text2.startswith(get_text("start_hello", lang, name="Yangi")),
              text2[:80])
        check(f"/start qayta[{lang}]: onboarding matni YO'Q",
              onb not in text2)
        check(f"/start qayta[{lang}]: menyu aynan 6 tugma",
              kb_flat(markup2) == list(EXPECTED_MAIN[lang]), str(kb_flat(markup2)))

    # Admin — 6 tugma + Admin Panel.
    text_a, markup_a, _ = _run_start(True, "uz", ADMIN_ID)
    labels_a = kb_flat(markup_a)
    check("/start[admin]: 6 tugma + Admin Panel = 7", len(labels_a) == 7, str(labels_a))
    check("/start[admin]: Admin Panel bor", BTN_ADMIN_PANEL in labels_a)
    check("/start[admin]: 6-tugma standart saqlangan",
          labels_a[:6] == list(EXPECTED_MAIN["uz"]), str(labels_a[:6]))

    # 3-til paritet: yorliqlar har tilda farqli (PRO brend-nomi mustasno).
    for key in ("btn_create_content", "btn_my_channels", "btn_scheduled",
                "btn_statistics", "btn_settings", "start_onboarding"):
        vals = [get_text(key, c) for c in LANGS]
        check(f"paritet: {key} — 3 tilda farqli", len(set(vals)) == 3, str(vals))
    check("paritet: btn_premium 3 tilda '💎 PRO'",
          {get_text("btn_premium", c) for c in LANGS} == {"💎 PRO"})


# ============================================================================
def main():
    print("=" * 62)
    print(" UX V2 — ASOSIY MENYU 6-TUGMA STANDARTI REGRESSIYA TESTLARI")
    print("=" * 62)
    test_strict_six_buttons()
    test_admin_panel_visibility_and_removals()
    test_routing_new_and_legacy_buttons()
    test_stars_plans_ssot()
    test_start_onboarding_three_langs()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] UX V2 STANDARDIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA UX V2 TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
