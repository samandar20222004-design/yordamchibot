#!/usr/bin/env python3
"""🪄 POSTASSIST POLISH — QABUL TESTI (AI HALLUCINATION + MENYU + YORLIQ STANDARTI).

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1 — AI PROMPT DINAMIK SANASI (ANTI-HALLUCINATION):
           PromptEngine HAR chaqiruvda tizimga joriy sanani uzatadi
           («Joriy yil va sana: YYYY-MM-DD»); 2024 yoki undan eski
           voqealarni hozirgi kunda sodir bo'lgandek taqdim etish
           TAQIQLANGAN; aniq fakt/raqam/oyin natijasi berilmagan bo'lsa
           soxta statistika ixtiro qilinmaydi; «Kanalga obuna bo'ling»,
           «bizning kanal eng yaxshisi» kabi quruq shablon CTA'lar
           generatsiyada butunlay TAQIQLANGAN. ``now=`` injeksiyasi bilan
           sana muqtada (deterministik) ham tekshiriladi.

  TEST 2 — ⚙️ SOZLAMALAR: SIMMETRIK 8 TUGMA / 4 QATOR × 2 (3 TILDA):
           r1 [🌐 Til][✍️ Post sozlamalari]; r2 [🔔 Bildirishnomalar]
           [👥 Do'stlarni taklif]; r3 [💳 To'lovlar tarixi][ℹ️ Bot haqida];
           r4 [💬 Qo'llab-quvvatlash][❌ Yopish]. Yolg'iz tugmali qator
           YO'Q; callback'lar tilga bog'liq emas va KANONIK tartibda.

  TEST 3 — ℹ️ BOT HAQIDA (stgs_about):
           ekranda bot VERSIYASI (config.BOT_VERSION), maqsad va qisqa
           yo'riqnoma; callback registry'da ro'yxatdan o'tgan.

  TEST 4 — INLINE YORLIQ 18-BELGI STANDARTI:
           barcha STATIK tugma yorliqlari (i18n btn_* kalitlari +
           kanonik klaviaturalar) vizual uzunlikda ≤18 belgi
           (feyk/spacer belgilar hisobga olinmaydi). Foydalanuvchi
           chizgan speskdan 3 ta yorliq oq imtiyozida.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/postassist_polish_test.py
"""
import ast
import asyncio
import os
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:POLISH_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10003")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0

LANGS = ("uz", "ru", "en")


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def header(code, title):
    print(f"\n=== {code}) {title} " + "=" * max(0, 48 - len(title)))


# ---------------------------------------------------------------------------
# TEST 1 — AI PROMPT: DINAMIK SANA + ANTI-HALLUCINATION + TAQIQLANGAN SHABLONLAR
# ---------------------------------------------------------------------------
def test_1_prompt_dynamic_date_and_anti_hallucination():
    header("1", "🤖 AI PROMPT — DINAMIK SANA + ANTI-HALLUCINATION")
    from services.ai_engine.prompts import PromptEngine, current_date

    today = datetime.now().strftime("%Y-%m-%d")
    check("current_date() = bugungi sana (YYYY-MM-DD)",
          current_date() == today, f"{current_date()} != {today}")

    # 1a) Standart chaqiruv — bugungi sana tizimga uzatiladi.
    _prompt, policy = PromptEngine.build("Bugun qanday post yozsam?", lang="uz")
    check("sana formati: «Joriy yil va sana: YYYY-MM-DD»",
          f"Joriy yil va sana: {today}" in policy, policy[:200])
    check("sana formati: «Today's date is YYYY-MM-DD»",
          f"Today's date is {today}" in policy, policy[:200])
    check("[CURRENT_DATE] bo'limi bor", "[CURRENT_DATE]" in policy)
    check("[ANTI_HALLUCINATION] bo'limi bor", "[ANTI_HALLUCINATION]" in policy)
    check("[FORBIDDEN_TEMPLATES] bo'limi bor", "[FORBIDDEN_TEMPLATES]" in policy)

    # 1b) Eski yangiliklarni yangi deb taqdim etish taqiqlangan (2024+).
    check("eski (2024 yoki undan oldingi) voqealar taqiqlangan",
          "2024" in policy and "outdated" in policy.lower(), policy)
    check("sana joriy emasligi tekshiriladi (predates the current date)",
          "predates the current date" in policy, policy)

    # 1c) Aniq fakt berilmaganda soxta statistika ixtiro qilinmaydi.
    check("soxta statistika/natija ixtiro qilish taqiqlangan",
          "do NOT invent statistics" in policy, policy)
    check("noma'lum faktda chalap o'tkazish emas, aniq aytiladi",
          "say so briefly instead of guessing" in policy, policy)

    # 1d) Quruq shablon CTA'lar butunlay taqiqlangan.
    check("obuna/follow CTA taqiqlangan",
          "Never generate subscription or follow CTAs" in policy, policy)
    check("kanal o'zini olqishlash (self-praise) taqiqlangan",
          "self-praise superlatives" in policy, policy)

    # 1e) now= injeksiyasi — sana muqtada (deterministik test).
    frozen = datetime(2031, 1, 2, 13, 5)
    _prompt, frozen_policy = PromptEngine.build("Salom", now=frozen)
    m = re.search(r"Joriy yil va sana: (\d{4}-\d{2}-\d{2})", frozen_policy)
    check("now= injeksiyasi: sana aynan berilgan sanaga teng (2031-01-02)",
          m is not None and m.group(1) == "2031-01-02",
          (m.group(1) if m else "not found") + " | " + frozen_policy[:160])
    check("now= berilganda bugungi sana ARALASHMAYDI",
          f"Joriy yil va sana: {today}" not in frozen_policy)

    # 1f) Foydalanuvchi so'rovi untrusted_input o'ramida (prompt injection himoyasi).
    prompt, _ = PromptEngine.build("salom", lang="uz")
    check("foydalanuvchi so'rovi [USER_REQUEST] bo'limida",
          "[USER_REQUEST]" in prompt and "salom" in prompt, prompt[:160])
    check("untrusted_input o'rami faol", "untrusted" in prompt.lower(), prompt[:160])


# ---------------------------------------------------------------------------
# TEST 2 — ⚙️ SOZLAMALAR: SIMMETRIK 8 TUGMA / 4 QATOR × 2
# ---------------------------------------------------------------------------
EXPECTED_SETTINGS_CBS = (
    "stgs_lang", "stgs_post", "stgs_notif", "stgs_referral",
    "stgs_pay", "stgs_about", "help_support", "stgs_back",
)


def _kb_rows(kb):
    return [[(b.text, b.callback_data) for b in row] for row in kb.inline_keyboard]


def test_2_settings_symmetric_8_button_layout():
    header("2", "⚙️ SOZLAMALAR — SIMMETRIK 8 TUGMA / 4×2 (3 TIL)")
    from keyboards.inline import (get_cabinet_inline_keyboard,
                                  get_settings_hub_keyboard,
                                  get_settings_profile_keyboard)
    from translations.settings_stats import settings_stats_t

    for lang in LANGS:
        kb = get_settings_profile_keyboard(lang)
        rows = _kb_rows(kb)
        cbs = [c for row in rows for _t, c in row]

        check(f"[{lang}] 4 qator, har birida AYNAN 2 tugma",
              len(rows) == 4 and all(len(r) == 2 for r in rows), str(rows))
        check(f"[{lang}] jami 8 tugma", len(cbs) == 8, str(cbs))
        check(f"[{lang}] callback'lar KANONIK tartibda",
              cbs == list(EXPECTED_SETTINGS_CBS), str(cbs))
        check(f"[{lang}] r1: [Til | Post sozlamalari]",
              rows[0][0][1] == "stgs_lang" and rows[0][1][1] == "stgs_post", str(rows[0]))
        check(f"[{lang}] r2: [Bildirishnomalar | Do'stlarni taklif]",
              rows[1][0][1] == "stgs_notif" and rows[1][1][1] == "stgs_referral", str(rows[1]))
        check(f"[{lang}] r3: [To'lovlar | Bot haqida]",
              rows[2][0][1] == "stgs_pay" and rows[2][1][1] == "stgs_about", str(rows[2]))
        check(f"[{lang}] r4: [Qo'llab-quvvatlash | Yopish]",
              rows[3][0][1] == "help_support" and rows[3][1][1] == "stgs_back", str(rows[3]))
        check(f"[{lang}] r4 yorliqlari i18n'dan (support/close)",
              rows[3][0][0] == settings_stats_t("ss_help_hub_support", lang)
              and rows[3][1][0] == settings_stats_t("ss_btn_close", lang), str(rows[3]))

    # Kanonik manba — barcha alias'larni bir panel qaytaradi.
    canon = get_settings_profile_keyboard("uz")
    check("get_cabinet_inline_keyboard == kanonik",
          _kb_rows(get_cabinet_inline_keyboard("uz")) == _kb_rows(canon))
    check("get_settings_hub_keyboard == kanonik",
          _kb_rows(get_settings_hub_keyboard("uz")) == _kb_rows(canon))
    check("include_legacy=True ham layout'ni buzmaydi",
          _kb_rows(get_settings_hub_keyboard("uz", include_legacy=True)) == _kb_rows(canon))


# ---------------------------------------------------------------------------
# TEST 3 — ℹ️ BOT HAQIDA: VERSIYA + MAQSAD + QISQA YO'RIQNOMA
# ---------------------------------------------------------------------------
class _FakeAboutQuery:
    """_render_about uchun yopishma: edit_message_text'ni ushlaydi."""

    def __init__(self):
        self.edited = None
        self.replied = None
        self.message = self

    async def answer(self, *a, **k):
        return None

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edited = (text, reply_markup, parse_mode)

    async def reply_text(self, text, reply_markup=None, parse_mode=None):
        self.replied = (text, reply_markup, parse_mode)


ABOUT_KEYWORDS = {
    "uz": ("PostAssist", "Maqsad", "Imkoniyatlar", "yo'riqnoma"),
    "ru": ("PostAssist", "Цель", "Возможности", "инструкция"),
    "en": ("PostAssist",),
}


def test_3_about_screen_version_and_purpose():
    header("3", "ℹ️ BOT HAQIDA — VERSIYA + MAQSAD + YO'RIQNOMA")
    import handlers.settings as ST
    from config import BOT_VERSION
    from keyboards.callback_data import is_registered_callback

    check("config.BOT_VERSION sozlangan", bool(str(BOT_VERSION).strip()),
          str(BOT_VERSION))
    check("stgs_about callback registry'da", is_registered_callback("stgs_about"))
    check("help_support callback registry'da", is_registered_callback("help_support"))

    for lang in LANGS:
        q = _FakeAboutQuery()
        asyncio.run(ST._render_about(q, lang))
        rendered = q.edited or q.replied
        check(f"[{lang}] ekran chizildi (edit yoki reply)", rendered is not None)
        if rendered is None:
            continue
        text, markup, parse_mode = rendered
        check(f"[{lang}] HTML parse_mode", parse_mode == "HTML", str(parse_mode))
        check(f"[{lang}] versiya ko'rsatiladi (v{BOT_VERSION})",
              f"v{BOT_VERSION}" in text, text[:120])
        missing = [w for w in ABOUT_KEYWORDS[lang] if w not in text]
        check(f"[{lang}] maqsad + qisqa yo'riqnoma kalit so'zlari bor",
              not missing, f"yo'q: {missing} | {text[:160]}")
        check(f"[{lang}] orqaga tugmasi bilan (stgs_hub/stgs_back)",
              markup is not None and any(
                  b.callback_data in ("stgs_hub", "stgs_back")
                  for row in markup.inline_keyboard for b in row),
              str([b.callback_data for row in markup.inline_keyboard for b in row])
              if markup else "markup None")

    # Hub orqali ham shu ekran ochiladi: stgs_about → _render_about (manba).
    src = Path(ST.__file__).read_text(encoding="utf-8")
    check("settings_menu_callback: stgs_about → _render_about",
          'if data == "stgs_about"' in src and "_render_about(query, lang)" in src)


# ---------------------------------------------------------------------------
# TEST 4 — INLINE YORLIQ 18-BELGI STANDARTI (STATIK YORLIQLAR)
# ---------------------------------------------------------------------------
# Vizual uzunlik: Telegram kengligini belgilamaydigan feyk/spacer belgilar
# hisobga olinmaydi (variation selector, ZWJ, skin-tone modifikatorlari).
_INVISIBLE = "\ufe0f\u200d" + "".join(chr(c) for c in range(0x1F3FB, 0x1F400))


def vlen(label: str) -> int:
    return len(label.replace(_INVISIBLE, "").replace("\u200e", ""))


# Foydalanuvchi chizgan SPEKSDAGI yorliqlar (imtiyozli ro'yxat):
WHITELIST_LABELS = {
    "💬 Qo'llab-quvvatlash",      # 20 — speskda aniq yozilgan
    "👥 Do'stlarni taklif",        # 19 — speskda aniq yozilgan (uz)
    "👥 Пригласить друзей",  # 19 — speskda aniq yozilgan (ru)
    "✍️ Post sozlamalari",        # 19 — speskda aniq yozilgan (uz)
    "✍️ Настройки постов",  # 19 — speskning ru varianti
}

TRANSLATION_MODULES = [
    ROOT / "locales" / "translations.py",
    ROOT / "locales" / "en_overlay.py",
    *[p for p in sorted((ROOT / "translations").glob("*.py"))
      if p.name not in ("__init__.py", "parity.py")],
]


def _scan_btn_labels(path: Path):
    """i18n moduldan tugma yorliqi (btn_* / *_button) STATIK qiymatlari."""
    found = []
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Dict,)):
            continue
        for key, val in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            k = key.value
            if not isinstance(val, ast.Constant) or not isinstance(val.value, str):
                continue
            is_btn_key = ("btn" in k) or k.endswith("_button")
            if not is_btn_key:
                continue
            v = val.value
            if "{" in v:  # format shabloni — dinamik, standart tashqarisida
                continue
            # Xabar/alert matnlari (HTML tegi, satr almashtirishi, xitoy
            # nuqtasi bilan tugovchi gap, yoki >30 belgili qo'ng'iroq)
            # tugma yorlig'i EMAS — standart tashqarisida.
            if "<" in v or "\n" in v or v.endswith(".") or vlen(v) > 30:
                continue
            found.append((k, v))
    return found


def _reply_menu_keys():
    """keyboards/default.py da get_text orqali ishlatiladigan REPLY-menu
    kalitlari — 18-belgi standarti INLINE tugmalar uchun qat'iy shart
    (reply menyulari aynan shu kalitlar orqali tushiriladi)."""
    src = (ROOT / "keyboards" / "default.py").read_text(encoding="utf-8")
    keys = set(re.findall(r'get_text\(\s*"([^"]*btn[^"]*)"', src))
    # _content_menu_label("cm_btn_*") orqali reply-menyu yorliqlari
    keys |= set(re.findall(r'_content_menu_label\(\s*"(cm_btn[^"]*)"', src))
    return keys


def test_4_static_label_18_char_standard():
    header("4", "📏 INLINE YORLIQ 18-BELGI STANDARTI (STATIK)")
    reply_keys = _reply_menu_keys()
    offenders = []
    total = 0
    for mod in TRANSLATION_MODULES:
        for key, label in _scan_btn_labels(mod):
            if key in reply_keys:
                continue
            total += 1
            if label in WHITELIST_LABELS:
                continue
            if vlen(label) > 18:
                offenders.append((mod.name, key, label, vlen(label)))
    check(f"i18n btn_* statik yorliqlar {total} ta skanerlandi", total > 100,
          str(total))
    check("barcha statik yorliqlar ≤18 belgi (imtiyozli ro'yxatdan tashqari)",
          not offenders,
          "; ".join(f"{m}:{k}={l!r}({n})" for m, k, l, n in offenders[:8]))

    # KANONIK KLAVIATURALARDA RENDERED yorliqlar (statik ma'lumot bilan) ≤18.
    from telegram import InlineKeyboardMarkup
    from keyboards.inline import (
        get_admin_dashboard_keyboard, get_admin_monitoring_keyboard,
        get_ai_studio_keyboard, get_ai_studio_plan_keyboard,
        get_ai_photo_keyboard, get_ai_back_keyboard, get_ai_tone_keyboard,
        get_ai_confirm_keyboard, get_cache_actions_keyboard,
        get_channels_manage_keyboard, get_close_keyboard,
        get_duplicate_warning_keyboard, get_extras_inline_keyboard,
        get_help_keyboard, get_language_keyboard, get_manual_post_panel,
        get_manual_reaction_keyboard, get_manual_channel_keyboard,
        get_payment_region_keyboard, get_referral_share_keyboard,
        get_settings_profile_keyboard, get_settings_back_keyboard,
        get_settings_rewards_keyboard, get_settings_help_hub_keyboard,
        get_support_ticket_keyboard, get_subscription_check_keyboard,
        get_sponsors_delete_keyboard, get_admin_sponsors_keyboard,
        get_hub_back_keyboard, get_ad_hub_keyboard, get_ad_pool_menu_keyboard,
        get_ad_interval_keyboard, get_ad_pool_back_keyboard,
        get_user_stats_keyboard, get_user_overview_keyboard,
        render_channels_list, render_my_channels_list, render_channel_panel,
        render_channel_advice_menu, render_channel_settings,
        render_pending_list, render_scheduled_actions,
        render_scheduled_full_actions,
    )
    CH = "-1001234567890"
    kbs = {
        "settings(uz)": get_settings_profile_keyboard("uz"),
        "settings(ru)": get_settings_profile_keyboard("ru"),
        "settings(en)": get_settings_profile_keyboard("en"),
        "settings back": get_settings_back_keyboard("uz"),
        "settings rewards": get_settings_rewards_keyboard("uz"),
        "settings help hub": get_settings_help_hub_keyboard("uz"),
        "admin dashboard": get_admin_dashboard_keyboard(),
        "admin monitoring": get_admin_monitoring_keyboard(),
        "ad hub": get_ad_hub_keyboard(),
        "ad pool (bo'sh)": get_ad_pool_menu_keyboard("channel", []),
        "ad pool reply (bo'sh)": get_ad_pool_menu_keyboard("reply", []),
        "ad interval": get_ad_interval_keyboard("channel", 4),
        "ad pool back": get_ad_pool_back_keyboard("channel"),
        "extras": get_extras_inline_keyboard(),
        "ai studio": get_ai_studio_keyboard("uz"),
        "ai studio (ru)": get_ai_studio_keyboard("ru"),
        "ai studio plan": get_ai_studio_plan_keyboard("uz"),
        "ai photo": get_ai_photo_keyboard("uz"),
        "ai tone": get_ai_tone_keyboard(),
        "ai confirm": get_ai_confirm_keyboard("uz"),
        "cache actions": get_cache_actions_keyboard(),
        "language": get_language_keyboard("uz"),
        "support ticket": get_support_ticket_keyboard("uz"),
        "subscription check": get_subscription_check_keyboard([CH], "uz"),
        "referral share": get_referral_share_keyboard(
            "https://t.me/x?startapp=a1b2c3d4", "uz"),
        "payment region": get_payment_region_keyboard("uz"),
        "user stats": get_user_stats_keyboard("uz"),
        "user overview": get_user_overview_keyboard("uz"),
        "channels manage": get_channels_manage_keyboard(),
        "channels list": render_channels_list(
            [("-1001", "Mening kanalim", "formal")], "uz"),
        "my channels": render_my_channels_list([("-1001", "Mening kanalim")], "uz"),
        "channel panel": render_channel_panel(CH, "uz"),
        "channel advice": render_channel_advice_menu(
            [("-1001", "Mening kanalim")], "uz"),
        "channel settings": render_channel_settings(CH, "uz"),
        "pending list": render_pending_list(
            [(1, "Kanal A", "text", "20:00", 1, "daily", None, "09:00")],
            "TST123", "uz"),
        "scheduled actions": InlineKeyboardMarkup(
            [render_scheduled_actions(1, "uz")]),
        "scheduled full actions": InlineKeyboardMarkup(
            render_scheduled_full_actions(1, "uz")),
        "manual post panel": get_manual_post_panel("uz"),
        "manual reactions": get_manual_reaction_keyboard(),
        "manual channel": get_manual_channel_keyboard(
            [("-1001", "Mening kanalim")], "uz"),
        "duplicate warning": get_duplicate_warning_keyboard(),
        "sponsors delete": get_sponsors_delete_keyboard([]),
        "admin sponsors": get_admin_sponsors_keyboard([]),
    }
    rendered_off = []
    rendered_total = 0
    for name, kb in kbs.items():
        for row in kb.inline_keyboard:
            for b in row:
                rendered_total += 1
                if vlen(b.text) > 18 and b.text not in WHITELIST_LABELS:
                    rendered_off.append((name, b.text, vlen(b.text)))
    check(f"kanonik klaviaturalarda {rendered_total} rendered yorliq ≤18",
          not rendered_off,
          "; ".join(f"{n}:{t!r}({l})" for n, t, l in rendered_off[:8]))


def main() -> int:
    print("=" * 62)
    print(" 🪄 POSTASSIST POLISH — QABUL TESTI")
    print("=" * 62)

    test_1_prompt_dynamic_date_and_anti_hallucination()
    test_2_settings_symmetric_8_button_layout()
    test_3_about_screen_version_and_purpose()
    test_4_static_label_18_char_standard()

    print("\n" + "=" * 62)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] POSTASSIST POLISH TESTLARIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA POSTASSIST POLISH TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
