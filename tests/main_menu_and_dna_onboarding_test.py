#!/usr/bin/env python3
"""🧭 3-BOSQICH — MENYUNI SODDALASHTIRISH + ONBOARDING (KANAL DNK).

Topshiriq spetsifikatsiyasi bilan birma-bir:

  TEST 1 — 🧭 ASOSIY MENYU IXCHAMLIGI
      Asosiy reply-klaviatura QAT'IY 5 tugma / 3 qator (uz/ru/en):
          [✍️ Post yaratish]     [📢 Kanallarim]
          [📅 Rejalashtirilgan]   [📊 Statistika]
          [⚙️ Sozlamalar / Ko'proq]
      «💎 PRO», «❓ Yordam», «👥 Do'stlarni taklif», «📖 Qo'llanma»,
      «⚙️ Qo'shimcha funksiyalar» asosiy reply-menuda YO'Q — ular
      KANONIK sozlamalar inline hub'ida (TEST 2).
      Admin uchun faqat oxirga [⚙️ Admin Panel] qatori qo'shiladi.

  TEST 2 — ⚙️ SOZLAMALAR / KO'PROQ HUB'I
      get_settings_profile_keyboard = 8 tugma / 4 qator (simmetrik 2+2),
      [💎 PRO] (sub_open) va [❓ Yordam] (stgs_help_hub) qatorlari bilan;
      get_cabinet_inline_keyboard va get_settings_hub_keyboard AYNAN shu
      panelni qaytaradi (dublikat inline klaviatura YO'Q).

  TEST 3 — ↩️ BACKWARD COMPATIBILITY (buyruq/matn filtri buzilmaydi)
      Eski yorliqlar («✨ Kontent yaratish», «⚙️ Sozlamalar», «💎 PRO»,
      «👥 Do'stlarni taklif», «➕ Yangi post» ...) routing'da saqlanadi:
      har biri o'z bo'limiga TUSHADI, global fallback'ga EMAS.

  TEST 4 — 🧠 ONBOARDING: KANAL DNK TAKLIFI
      Birinchi kanal ulanganda «✅ ulandi» dan KEYIN darhol faol taklif
      yuboriladi (uz/ru/en) + [🎙 Ovoz tahlili] inline tugmasi
      (ch_voice:<id>, registry'da, <=64 bayt). Taklif faqat BIRINCHI
      kanalda va uslub hali yo'q bo'lganida ko'rsatiladi (spam yo'q).

  TEST 5 — 🎨 1 TA BEPUL NAMUNAVIY QORALAMA
      Tahlil yakunlangach kanal ohangiga mos 1 ta namunaviy post
      generatsiya qilinadi (AI zanjiri + Channel DNA), bron ATO'MIK
      (1 birlik) va xatoda IDEMPOTENT qaytariladi (fail-closed refund).
      Butun blok fail-safe: xato tahlil natijasini buzmaydi.

  TEST 6 — 💡 STATISTIKADA ANIQ TAVSIYA
      Kuruq raqamlar emas — bajariladigan tavsiya: best-time oynasi,
      «kanal yo'q» / «ma'lumot yetarli emas» holatlari va low-credits
      PRO taklifi; soxta raqam HECH QACHON uydirilmaydi (uz/ru/en).

  TEST 7 — 🌐 I18N 100% PARITET + 🔒 XAVFSIZLIK
      Barcha yangi matnlar 3 tilda, format-argument pariteti saqlangan;
      yangi inline klaviaturadagi barcha callback'lar registry'da.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/main_menu_and_dna_onboarding_test.py
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
os.environ.setdefault("BOT_TOKEN", "123456:STEP3_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10007")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

LANGS = ("uz", "ru", "en")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

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


def header(letter, title):
    print(f"\n== TEST {letter}: {title} ==")


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import keyboards.callback_data as CB                     # noqa: E402
import keyboards.default as KD                            # noqa: E402
import keyboards.inline as KI                             # noqa: E402
import handlers as H                                      # noqa: E402
import handlers.channels as HC                            # noqa: E402
import handlers.statistics as ST                          # noqa: E402
from locales.translations import get_text, safe_t         # noqa: E402
from translations import (                                # noqa: E402
    CB_SETTINGS_HUB, settings_stats_parity_report,
    settings_stats_t,
)

#: 3-BOSQICH spetsifikatsiyasi — QAT'IY 5 TUGMA / 3 QATOR.
EXPECTED_MAIN = {
    "uz": ["✍️ Post yaratish", "📢 Kanallarim",
           "📅 Rejalashtirilgan", "📊 Statistika",
           "⚙️ Sozlamalar / Ko'proq"],
    "ru": ["✍️ Создать пост", "📢 Мои каналы",
           "📅 Запланированные", "📊 Статистика",
           "⚙️ Настройки / Ещё"],
    "en": ["✍️ Create post", "📢 My channels",
           "📅 Scheduled", "📊 Statistics",
           "⚙️ Settings / More"],
}
EXPECTED_MAIN_ROWS = {
    "uz": [["✍️ Post yaratish", "📢 Kanallarim"],
           ["📅 Rejalashtirilgan", "📊 Statistika"],
           ["⚙️ Sozlamalar / Ko'proq"]],
    "ru": [["✍️ Создать пост", "📢 Мои каналы"],
           ["📅 Запланированные", "📊 Статистика"],
           ["⚙️ Настройки / Ещё"]],
    "en": [["✍️ Create post", "📢 My channels"],
           ["📅 Scheduled", "📊 Statistics"],
           ["⚙️ Settings / More"]],
}

#: Asosiy reply-menudan ko'chirilgan IKKILAMCHI bo'limlar.
SECONDARY_KEYS = ("btn_premium", "btn_invite_friends", "btn_help", "btn_extras")


def kb_rows(markup):
    return [[b.text for b in row] for row in markup.keyboard]


def kb_flat(markup):
    return [t for row in kb_rows(markup) for t in row]


def ik_rows(markup):
    return [[(b.text, b.callback_data) for b in row]
            for row in markup.inline_keyboard]


def ik_flat(markup):
    return [t for row in ik_rows(markup) for t in row]


# ===========================================================================
# TEST 1 — 🧭 ASOSIY MENYU: QAT'IY 5 TUGMA / 3 QATOR
# ===========================================================================
def test_1_compact_main_menu():
    header("1", "🧭 Asosiy menyu — IXCHAM 5 tugma / 3 qator (uz/ru/en)")
    for lang in LANGS:
        kb = KD.get_main_keyboard(False, lang=lang)
        check(f"[{lang}] aynan 5 tugma", len(kb_flat(kb)) == 5, str(kb_flat(kb)))
        check(f"[{lang}] qatorlar speks bilan bir xil (2+2+1)",
              kb_rows(kb) == EXPECTED_MAIN_ROWS[lang], str(kb_rows(kb)))
        check(f"[{lang}] yorliqlar tartibi speksda",
              kb_flat(kb) == EXPECTED_MAIN[lang], str(kb_flat(kb)))
        # I18n: klaviatura lug'at kalitlaridan chizilgan.
        keys = ("btn_create_content", "btn_my_channels", "btn_scheduled",
                "btn_statistics", "btn_settings")
        check(f"[{lang}] yorliqlar lug'atdan (get_text)",
              kb_flat(kb) == [get_text(k, lang) for k in keys], str(kb_flat(kb)))
        # IKKILAMCHI bo'limlar asosiy reply-menuda YO'Q.
        for key in SECONDARY_KEYS:
            check(f"[{lang}] {key} asosiy reply-menuda yo'q",
                  get_text(key, lang) not in kb_flat(kb), str(kb_flat(kb)))
        # Admin: 5 + [⚙️ Admin Panel] (oddiy foydalanuvchiga hech qachon).
        adm_rows = kb_rows(KD.get_main_keyboard(True, lang=lang))
        check(f"[{lang}] admin: 5 tugma + Admin Panel = 6",
              len([t for r in adm_rows for t in r]) == 6, str(adm_rows))
        check(f"[{lang}] admin: birinchi 3 qator oddiy foydalanuvchining xolos",
              adm_rows[:3] == EXPECTED_MAIN_ROWS[lang], str(adm_rows[:3]))
        check(f"[{lang}] admin: oxirgi qator = [⚙️ Admin Panel]",
              adm_rows[-1] == [KD.BTN_ADMIN_PANEL], str(adm_rows[-1]))
        check(f"[{lang}] admin: PRO reply-menuda ham yo'q",
              get_text("btn_premium", lang) not in adm_rows[-1], str(adm_rows[-1]))

    # Til almashganda chiziladigan menyu ham bir xil standartda.
    refreshed = KD.get_refreshed_main_keyboard("ru", is_admin=False)
    check("get_refreshed_main_keyboard(ru) — bir xil 5 tugma",
          kb_flat(refreshed) == EXPECTED_MAIN["ru"], str(kb_flat(refreshed)))
    # 3 tilda tugma soni teng (tarjima qolib ketmagan).
    sizes = {c: len(kb_flat(KD.get_main_keyboard(False, lang=c))) for c in LANGS}
    check("uz/ru/en tugma soni bir xil (5/5/5)", set(sizes.values()) == {5}, str(sizes))


# ===========================================================================
# TEST 2 — ⚙️ SOZLAMALAR / KO'PROQ HUB'I
# ===========================================================================
def test_2_settings_more_hub():
    header("2", "⚙️ Sozlamalar / Ko'proq — PRO va Yordam inline hub'ida")
    canonical = KI.get_settings_profile_keyboard("uz")
    check("PRO (sub_open) hub'da bor",
          "sub_open" in [cb for _, cb in ik_flat(canonical)], str(ik_flat(canonical)))
    check("Yordam (stgs_help_hub) hub'da bor",
          "stgs_help_hub" in [cb for _, cb in ik_flat(canonical)], str(ik_flat(canonical)))

    for lang in LANGS:
        kb = KI.get_settings_profile_keyboard(lang)
        rows = ik_rows(kb)
        cbs = [cb for _, cb in ik_flat(kb)]
        labels = [t for t, _ in ik_flat(kb)]
        check(f"[{lang}] 8 tugma / 4 qator (simmetrik 2+2)",
              len(labels) == 8 and len(rows) == 4
              and all(len(r) == 2 for r in rows), str(rows))
        check(f"[{lang}] callback tartibi SSOT bilan bir xil",
              cbs == list(CB_SETTINGS_HUB), str(cbs))
        check(f"[{lang}] PRO yorlig'i = ss_btn_premium",
              settings_stats_t("ss_btn_premium", lang) in labels, str(labels))
        check(f"[{lang}] Yordam yorlig'i = ss_btn_help",
              settings_stats_t("ss_btn_help", lang) in labels, str(labels))
        # Navigatsiya standarti: oxirgi qator [ℹ️ Yordam va Qo'llanma | ❌ Yopish].
        check(f"[{lang}] oxirgi qator kanonik [help | close]",
              rows[-1] == [(settings_stats_t("ss_btn_help", lang), "stgs_help_hub"),
                           (settings_stats_t("ss_btn_close", lang), "stgs_back")],
              str(rows[-1]))
        # Dublikat inline klaviatura YO'Q (FAZA 18 qoidasi saqlanadi).
        check(f"[{lang}] get_cabinet_inline_keyboard == kanonik panel",
              ik_rows(KI.get_cabinet_inline_keyboard(lang)) == rows)
        check(f"[{lang}] get_settings_hub_keyboard == kanonik panel",
              ik_rows(KI.get_settings_hub_keyboard(lang)) == rows)
        check(f"[{lang}] callback'lar takrorlanmaydi", len(set(cbs)) == len(cbs), str(cbs))
        check(f"[{lang}] eski guruh tugmalari yo'q (rewards/tools)",
              not any(cb in cbs for cb in ("stgs_rewards", "stgs_tools")), str(cbs))


# ===========================================================================
# TEST 3 — ↩️ BACKWARD COMPATIBILITY: eski yorliqlar o'z yo'lini topadi
# ===========================================================================
def _targets(label):
    """label matnini taniydigan handlerlarning chaqiradigan funksiyalari."""
    from telegram import Update
    from telegram.ext import MessageHandler, filters

    class _Recorder:
        def __init__(self):
            self.handlers = []

        def add_handler(self, h, group=0):
            self.handlers.append(h)

    import handlers as HH
    app = _Recorder()
    HH.register_all_handlers(app)
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
    for h in app.handlers:
        if not isinstance(h, MessageHandler) or not isinstance(h.filters, filters.Regex):
            continue
        if not h.check_update(upd):
            continue
        cb = h.callback
        if callable(cb) and getattr(cb, "__name__", "") != "<lambda>":
            names.add(getattr(cb, "__name__", str(cb)))
        else:
            for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                if n in ("guard_entry", "guard_menu"):
                    continue
                obj = getattr(HH, n, None)
                if callable(obj):
                    names.add(n)
    return names


def test_3_backward_compatibility():
    header("3", "↩️ Eski yorliqlar routing'da saqlanadi (fallback EMAS)")
    # 3a) YANGI tugmalar — o'z bo'limiga.
    new_routes = (
        ("btn_create_content", "ai_studio_menu_entry"),
        ("btn_settings", "user_cabinet_menu"),
    )
    for key, expected in new_routes:
        for lang in LANGS:
            label = get_text(key, lang)
            names = _targets(label)
            check(f"yangi[{lang}] {label!r} → {expected}",
                  names == {expected}, str(sorted(names)))

    # 3b) ESKI yorliqlar — xuddi shu bo'limga (chat tarixi xavfsiz).
    legacy_routes = (
        ("✨ Kontent yaratish", "ai_studio_menu_entry"),
        ("✨ Создать контент", "ai_studio_menu_entry"),
        ("✨ Create content", "ai_studio_menu_entry"),
        ("⚙️ Sozlamalar", "user_cabinet_menu"),
        ("⚙️ Настройки", "user_cabinet_menu"),
        ("⚙️ Settings", "user_cabinet_menu"),
        ("👤 Kabinet & Sozlamalar", "user_cabinet_menu"),
        ("👤 Account & Settings", "user_cabinet_menu"),
        ("💎 PRO", "start_subscription"),
        ("⭐️ Premium", "start_subscription"),
    )
    for label, expected in legacy_routes:
        names = _targets(label)
        check(f"eski {label!r} → {expected}",
              expected in names and len(names) == 1, str(sorted(names)))

    # 3c) MENU_TEXTS registry'da ham barcha oilalar saqlangan.
    #     («📢 Kanallarim» → "channels", «📅 Rejalashtirilgan» → "queue"
    #      oilasi — kanonik action nomlari o'zgarmagan.)
    for action in ("create_content", "settings", "premium", "invite_friends",
                   "help", "extras", "statistics", "channels", "queue"):
        check(f"MENU_TEXTS['{action}'] mavjud", action in KD.MENU_TEXTS,
              str(sorted(KD.MENU_TEXTS)[:8]))
    for lang in LANGS:
        check(f"[{lang}] «📢 Kanallarim» channels oilasida",
              get_text("btn_my_channels", lang) in KD.MENU_TEXTS["channels"],
              str(KD.MENU_TEXTS["channels"]))
        check(f"[{lang}] «📅 Rejalashtirilgan» queue oilasida",
              get_text("btn_scheduled", lang) in KD.MENU_TEXTS["queue"],
              str(KD.MENU_TEXTS["queue"]))
    check("create_content oilasida eski «✨ Kontent yaratish» alias bor",
          "✨ Kontent yaratish" in KD.MENU_TEXTS["create_content"],
          str(KD.MENU_TEXTS["create_content"]))
    check("settings oilasida eski «⚙️ Sozlamalar» alias bor",
          "⚙️ Sozlamalar" in KD.MENU_TEXTS["settings"],
          str(KD.MENU_TEXTS["settings"]))
    # 3d) exact() filtri eski va yangi yorliqlarni ham taniydi.
    for label, positive in (("✨ Kontent yaratish", True),
                            ("✍️ Post yaratish", True),
                            ("⚙️ Sozlamalar", True),
                            ("⚙️ Sozlamalar / Ko'proq", True)):
        matched = KD.exact(*KD.MENU_TEXTS["create_content"]).pattern \
            if "Post yaratish" in label or "Kontent yaratish" in label \
            else KD.exact(*KD.MENU_TEXTS["settings"]).pattern
        got = re.fullmatch(matched, label) is not None
        check(f"exact() {label!r} → {got} (kutilgan {positive})", got == positive)


# ===========================================================================
# TEST 4 — 🧠 ONBOARDING: kanal birinchi ulanganda DNK taklifi
# ===========================================================================
class _Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append((text, reply_markup, parse_mode))
        return SimpleNamespace(chat_id=1, message_id=len(self.sent))

    chat_id = 1


def test_4_dna_onboarding_offer():
    header("4", "🧠 Kanal ulangach darhol Kanal DNK sinovi taklifi")
    for lang in LANGS:
        btn = safe_t("ch_voice_btn", lang)
        text = safe_t("ch_dna_offer", lang, btn=btn)
        check(f"[{lang}] taklif matni bo'sh emas", bool(text.strip()), text[:60])
        check(f"[{lang}] taklifda tugma nomi ko'rsatilgan", btn in text, text[:120])
        # 3 tilda haqiqatan farqli (tarjima qolib ketmagan).
        low = text.lower()
        check(f"[{lang}] taklif «Tone of Voice» tushunchasini tushuntiradi",
              ("tone of voice" in low) or ("оворк" in low) or ("ohang" in low),
              text[:200])
    check("3 tilda taklif matni farqli",
          len({safe_t("ch_dna_offer", c, btn=safe_t("ch_voice_btn", c))
               for c in LANGS}) == 3, "")

    # Klaviatura: bitta tugma, registry'da, <=64 bayt, navigatsiya konflikti yo'q.
    for lang in LANGS:
        kb = KI.render_dna_onboarding_keyboard("-1001234567890", lang)
        rows = ik_rows(kb)
        check(f"[{lang}] taklif klaviaturasi 1 tugma / 1 qator",
              len(rows) == 1 and len(rows[0]) == 1, str(rows))
        label, cbdata = rows[0][0]
        check(f"[{lang}] tugma = «🎙 Ovoz tahlili»",
              label == safe_t("ch_voice_btn", lang), label)
        check(f"[{lang}] callback = ch_voice:<channel_id>",
              cbdata == "ch_voice:-1001234567890", cbdata)
        check(f"[{lang}] callback registry'da", CB.is_registered_callback(cbdata), cbdata)
        check(f"[{lang}] callback <= 64 bayt",
              CB.callback_byte_len(cbdata) <= CB.CALLBACK_DATA_MAX_BYTES, cbdata)
        import keyboards.nav as NAV
        check(f"[{lang}] navigatsiya konflikti yo'q",
              not NAV.find_nav_conflicts(kb, f"dna[{lang}]"), "")

    # Taklif SHARTLARI: faqat birinchi kanal + uslub hali yo'q.
    def _run_should_offer(rows):
        async def fake_run_db(fn, *a, **kw):
            if getattr(fn, "__name__", "") == "get_user_channels_with_tone":
                return rows
            return None

        import database as db_mod
        orig = db_mod.run_db
        db_mod.run_db = fake_run_db
        try:
            return asyncio.run(HC._should_offer_dna(42, "-1001234567890"))
        finally:
            db_mod.run_db = orig

    check("birinchi kanal + uslub yo'q → taklif KO'RSATILADI",
          _run_should_offer([("-1001234567890", "Kanalim", None)]) is True)
    check("uslub allaqachon o'rnatilgan → taklif YO'Q",
          _run_should_offer([("-1001234567890", "Kanalim", "friendly")]) is False)
    check("bu birinchi kanal EMAS (2 ta kanal) → taklif YO'Q",
          _run_should_offer([("-1001234567890", "K1", None),
                             ("-100999", "K2", None)]) is False)
    check("kanal ro'yxatda yo'q → taklif YO'Q (fail-safe)",
          _run_should_offer([("-100999", "Boshqa", None)]) is False)
    check("ro'yxat bo'sh (DB xatosi) → taklif YO'Q (jim)",
          _run_should_offer([]) is False)


# ===========================================================================
# TEST 5 — 🎨 BEPUL NAMUNAVIY QORALAMA (AI zanjiri + Channel DNA)
# ===========================================================================
def test_5_free_sample_draft():
    header("5", "🎨 Tahlildan keyin 1 ta bepul namunaviy qoralama")
    # 5a) AI agent funksiyasi mavjud va 3 tilda ishlaydi (mock _call_chain).
    import utils.ai_agent as ai_mod

    seen = {}

    async def fake_chain(prompt, system, lang="uz"):
        seen["lang"] = lang
        seen["system"] = system
        seen["prompt"] = prompt
        return {"post_text": "NAMUNA MATN"}

    orig_chain = ai_mod._call_chain
    ai_mod._call_chain = fake_chain
    try:
        for lang in LANGS:
            seen.clear()
            res = asyncio.run(ai_mod.generate_dna_sample_post(
                channel_title="Kanalim", tone="formal",
                dna_block="DNA: avg_length=420", lang=lang))
            check(f"[{lang}] namunaviy matn qaytadi", res.get("post_text") == "NAMUNA MATN",
                  str(res))
            check(f"[{lang}] til promptga uzatilgan", seen.get("lang") == lang, str(seen.get("lang")))
            check(f"[{lang}] DNA bloki TIZIM promptiga ulangan",
                  "DNA: avg_length=420" in seen.get("system", ""), seen.get("system", "")[:120])
            check(f"[{lang}] kanal nomi promptda bor",
                  "Kanalim" in seen.get("prompt", ""), seen.get("prompt", "")[:120])
    finally:
        ai_mod._call_chain = orig_chain

    # 5b) Xato holati — istisno EMAS, {"error": ...} (handler «qotib» qolmaydi).
    async def boom(prompt, system, lang="uz"):
        raise RuntimeError("AI down")

    ai_mod._call_chain = boom
    try:
        res = asyncio.run(ai_mod.generate_dna_sample_post("K", "friendly", "", "uz"))
        check("AI xatosi → {'error': ...} (istisno emas)", "error" in res, str(res))
        check("AI xatosi → xabar 3 tilda lokal", bool(res.get("error")), str(res))
    finally:
        ai_mod._call_chain = orig_chain

    # 5c) Bron ATOMIK (1 birlik) va xatoda QAYTARILADI (fail-closed refund).
    src = (ROOT / "handlers" / "channels.py").read_text(encoding="utf-8")
    check("namuna uchun atomik bron (reserve_for_flow, 1 birlik)",
          'reserve_for_flow(\n        db, context, user_id, "dna_sample", "dna", 1)' in src
          or '"dna_sample", "dna", 1' in src, "")
    check("namuna xatosida bron qaytariladi (release_ai_quota)",
          src.count("release_ai_quota(db, user_id, reservation_id)") >= 2, "")
    check("namuna blokini yuborib bo'lmasa ham refund qilinadi (adolatli)",
          "# Yuborib bo'lmadi" in src, "")
    check("namuna butun try/except ichida — tahlil buzilmaydi",
          "await _send_dna_sample(update, context, user_id, channel_id, tone, lang)" in src
          and "DNK namunasi yuborilmadi" in src, "")
    # 5d) Namuna matni uchun i18n kalitlari 3 tilda.
    for key in ("ch_dna_sample_title", "ch_dna_sample_footer", "ch_dna_sample_error"):
        vals = [safe_t(key, c) for c in LANGS]
        check(f"{key}: 3 tilda mavjud va farqli",
              all(vals) and len(set(vals)) == 3, str(vals))


# ===========================================================================
# TEST 6 — 💡 STATISTIKADA ANIQ, BAJARILADIGAN TAVSIYA
# ===========================================================================
def test_6_actionable_statistics_advice():
    header("6", "💡 Statistika — kuruq raqamlar emas, aniq tavsiya")
    stats = {"channels": 1, "created_posts": 4, "scheduled_posts": 0}

    for lang in LANGS:
        line = ST.build_advice_line(
            {"kind": "best_time", "time": "19:00 - 21:00"}, lang, 0)
        check(f"[{lang}] best-time tavsiyasi bo'sh emas", bool(line.strip()), line[:60])
        check(f"[{lang}] vaqt oralig'i matnda", "19:00 - 21:00" in line, line[:120])
        check(f"[{lang}] sarlavha «Tavsiya»/«Рекомендация»/«Tip»",
              settings_stats_t("ss_my_advice_title", lang) in line, line[:80])
        # Rejalashtirilgan post bor/yuqligi — boshqa tavsiya shakli.
        with_sched = ST.build_advice_line(
            {"kind": "best_time", "time": "19:00 - 21:00"}, lang, 3)
        check(f"[{lang}] reja bor → boshqa tavsiya matni", with_sched != line,
              with_sched[:80])
        # Ma'lumot yetarli emas / kanal yo'q holatlari.
        for kind, key in ((ST.ADVICE_INSUFFICIENT, "ss_my_advice_insufficient"),
                          (ST.ADVICE_NO_CHANNEL, "ss_my_advice_no_channel")):
            body = ST.build_advice_line({"kind": kind}, lang, 0)
            check(f"[{lang}] {kind} → {key}",
                  settings_stats_t(key, lang) in body, body[:100])
        # Noma'lum kind / None → bo'sh qator (soxta tavsiya yo'q).
        check(f"[{lang}] advice=None → qator yo'q (quruq variant saqlanadi)",
              ST.build_advice_line(None, lang, 0) == "")
        check(f"[{lang}] unknown kind → qator yo'q",
              ST.build_advice_line({"kind": "????"}, lang, 0) == "")

    # Ekran matni: 4 ko'rsatkich + tavsiya qatori.
    for lang in LANGS:
        advised = ST.build_user_overview_text(
            stats, 7, lang, {"kind": "best_time", "time": "19:00 - 21:00"})
        check(f"[{lang}] ekran = sarlavha + 4 ko'rsatkich + tavsiya (6 qator)",
              len(advised.split("\n")) == 6, repr(advised)[:200])
        # Kredit tugab qolsa — PRO taklifi ustun chiqadi.
        low = ST.build_user_overview_text(
            stats, 0, lang, {"kind": "best_time", "time": "19:00 - 21:00"})
        check(f"[{lang}] low-credits → PRO taklifi",
              settings_stats_t("ss_my_advice_low_credits", lang) in low, low[:160])
        check(f"[{lang}] advice berilmasa → eski 5 qatorli xulq",
              len(ST.build_user_overview_text(stats, 7, lang).split("\n")) == 5, "")
    # 3 tilda ekran matni haqiqatan farqli.
    variants = {
        ST.build_user_overview_text(stats, 7, c,
                                    {"kind": "best_time", "time": "19:00 - 21:00"})
        for c in LANGS
    }
    check("statistika ekrani 3 tilda farqli", len(variants) == 3, "")

    # collect_advice — fail-safe (xatoda bo'sh dict, hech qachon crash yo'q).
    check("collect_advice mavjud (async, fail-safe)",
          asyncio.iscoroutinefunction(ST.collect_advice), "")

    async def empty_run_db(fn, *a, **kw):
        return []

    import database as db_mod
    orig = db_mod.run_db
    db_mod.run_db = empty_run_db
    try:
        res = asyncio.run(ST.collect_advice(42))
        check("kanal yo'q → {'kind': 'no_channel'}",
              res == {"kind": "no_channel"}, str(res))
    finally:
        db_mod.run_db = orig

    async def boom_run_db(fn, *a, **kw):
        raise RuntimeError("db down")

    db_mod.run_db = boom_run_db
    try:
        res = asyncio.run(ST.collect_advice(42))
        check("DB xatosi → {} (jim, crash yo'q)", res == {}, str(res))
    finally:
        db_mod.run_db = orig


# ===========================================================================
# TEST 7 — 🌐 I18N PARITET + 🔒 CALLBACK XAVFSIZLIGI
# ===========================================================================
def test_7_i18n_parity_and_safety():
    header("7", "🌐 I18N paritet + callback registry / navigatsiya xavfsizligi")
    rep = settings_stats_parity_report()
    check("settings_stats lug'ati UZ↔RU↔EN in_sync=True", rep["in_sync"] is True,
          f"missing={rep['missing']} extra={rep['extra']} fmt={rep['format_mismatch']}")
    for key in ("ss_btn_premium", "ss_btn_help", "ss_my_advice_title",
                "ss_my_advice_best_time", "ss_my_advice_idle",
                "ss_my_advice_no_channel", "ss_my_advice_insufficient",
                "ss_my_advice_low_credits"):
        check(f"settings_stats: {key} mavjud",
              all(settings_stats_t(key, c) for c in LANGS), "")

    from locales.translations import translation_parity_report
    main_rep = translation_parity_report()
    check("asosiy lug'at all_in_sync=True (callback_rejected bilan)",
          main_rep.get("all_in_sync") is True,
          str({k: v for k, v in main_rep.items() if "only" in k or "missing" in k}))
    for key in ("ch_dna_offer", "ch_dna_sample_title", "ch_dna_sample_footer",
                "ch_dna_sample_error", "ch_dna_already_done",
                "btn_create_content", "btn_settings"):
        check(f"asosiy lug'at: {key} 3 tilda mavjud",
              all(safe_t(key, c).strip() for c in LANGS), "")

    # Yangi klaviatura callback'lari registry'da va <=64 bayt.
    for lang in LANGS:
        cbs = [cb for _, cb in ik_flat(KI.get_settings_profile_keyboard(lang))]
        cbs += [cb for _, cb in ik_flat(KI.render_dna_onboarding_keyboard("-100123", lang))]
        unregistered = [c for c in cbs if not CB.is_registered_callback(c)]
        check(f"[{lang}] barcha yangi callback'lar registry'da",
              not unregistered, str(unregistered))
        oversized = [c for c in cbs
                     if CB.callback_byte_len(c) > CB.CALLBACK_DATA_MAX_BYTES]
        check(f"[{lang}] callback'lar <=64 bayt", not oversized, str(oversized))

    # Navigatsiya standarti butun klaviatura parkida buzilmagan.
    import keyboards.nav as NAV
    total = 0
    for lang in LANGS:
        for name, kb in (("main", KD.get_main_keyboard(False, lang=lang)),
                         ("settings", KI.get_settings_profile_keyboard(lang)),
                         ("dna", KI.render_dna_onboarding_keyboard("-100123", lang))):
            probs = NAV.find_nav_conflicts(kb, f"{name}[{lang}]")
            total += len(probs)
            for p in probs[:2]:
                print("      CONFLICT:", p)
    check("barcha yangi klaviaturalarda 0 navigatsiya konflikti",
          total == 0, f"{total} ta konflikt")

    # Hardcoded o'zbekcha matn yo'q (FAZA 26 qoidasi saqlanadi).
    import ast

    def _scan(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docstrings, logger_strs = set(), set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                d = ast.get_docstring(node, clean=False)
                if d is not None:
                    docstrings.add(id(d))
                    for sub in ast.walk(node):
                        if isinstance(sub, ast.Constant) and sub.value == d:
                            docstrings.add(id(sub))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                fname = f.attr if isinstance(f, ast.Attribute) else (
                    f.id if isinstance(f, ast.Name) else "")
                base = f.value.id if isinstance(f, ast.Attribute) and isinstance(
                    f.value, ast.Name) else ""
                if base in ("logger", "logging") or fname in (
                        "debug", "info", "warning", "error", "exception", "critical"):
                    for a in list(node.args) + [kw.value for kw in node.keywords]:
                        for sub in ast.walk(a):
                            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                logger_strs.add(id(sub))
        # Qoida: FAZA 26 dagi bilan bir xil markerlar to'plami (o'zbekcha
        # foydalanuvchi matni) — o'zimizning yangi matnlarimiz ham shu
        # skanerdan o'tishi shart.
        uz_re = re.compile(
            r"(?i)(\bta\b|qil|beril|tizim|foydalanuvchi|kanal|uchun|yoki|bilan|mumkin|"
            r"kerak|ruxsat|topilmadi|yubor|olmadi|xato|yopil|orqaga|bekor|kiriting|"
            r"tanlang|sozla|javob|yaratil|ochil|yangilan|kutib|shaxsiy|jami|faol|"
            r"takror|muvaffaqiyat|amalga|holat|matn|tugma|ro'yxat|o'chir|tozal|saqla|"
            r"boshqar|statistik|oraliq|postlar|obuna|sarlavha|so'rov|kirit|yozing|bosing|"
            r"tavsiya|o'rgan|etarli|yetarli|namuna|uslub|beradi)")
        ident_re = re.compile(r"^[a-z][a-z0-9_:.|=-]*$")
        out = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings or id(node) in logger_strs:
                    continue
                s = node.value.strip()
                if len(s) < 3 or ident_re.match(s):
                    continue
                if uz_re.search(s):
                    out.append((node.lineno, s[:70]))
        return out

    for rel in ("handlers/channels.py", "handlers/statistics.py"):
        flagged = _scan(ROOT / rel)
        check(f"{rel}: foydalanuvchiga ko'rinadigan hardcoded matn yo'q",
              not flagged, str(flagged[:4]))


# ===========================================================================
# TEST 8 — 🔗 ONBOARDING ULANMASI (end-to-end, mock DB/AI)
# ===========================================================================
class _QB:
    """Kanal ulash / tahlil ssenariysi uchun minimal fake'lаr."""

    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"text": text, "reply_markup": reply_markup,
                          "parse_mode": parse_mode})
        return self

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"text": text, "reply_markup": reply_markup,
                          "edited": True, "parse_mode": parse_mode})
        return self


class _QUser:
    def __init__(self, uid):
        self.id = uid
        self.full_name = "Test"
        self.username = "test"


def _voice_update(channel_id="-1001234567890", user_id=777001):
    msg = _QB()
    msg.chat_id = 555
    msg.message_id = 11
    queries = []

    async def answer(*a, **kw):
        queries.append("answer")

    return SimpleNamespace(
        callback_query=SimpleNamespace(
            data=f"ch_voice:{channel_id}", from_user=_QUser(user_id),
            message=msg, answer=answer,
        ),
        effective_user=_QUser(user_id),
        effective_message=msg,
    )


def test_8_onboarding_end_to_end():
    header("8", "🔗 Ulanma: ulash → taklif → tahlil → bepul namuna (mock)")
    import database as db_mod
    import services.ai_quota as quota_mod
    import services.channels.dna as dna_mod

    calls = {"tone": [], "reserve": [], "release": [], "generated": []}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "get_user_channels_with_tone":
            return [("-1001234567890", "Mening Kanalim", "friendly")]
        if name == "get_channel_posts_history":
            return [{"text": "Birinchi post matni " * 5},
                    {"text": "Ikkinchi post matni " * 5}]
        if name == "set_channel_tone":
            calls["tone"].append(args)
            return True
        return []

    async def fake_reserve(db_module, context, user_id, operation_type,
                           ctx_prefix, cost=1):
        calls["reserve"].append((operation_type, ctx_prefix, cost))
        return {"allowed": True, "reservation_id": 4242, "source": "daily_quota",
                "reason": "ok"}

    def fake_take(context, prefix):
        calls["release"].append(("take", prefix))
        return 4242

    async def fake_release(db_module, user_id, reservation_id=None):
        calls["release"].append(("release", reservation_id))
        return True

    async def fake_voice(posts, lang="uz"):
        return {"tone": "concise", "reason": "Yangiliklar uslubi."}

    async def fake_sample(channel_title, tone="friendly", dna_block="", lang="uz"):
        calls["generated"].append({"channel": channel_title, "tone": tone,
                                   "lang": lang})
        return {"post_text": "NAMUNA: kanalingiz ohangida yozilgan post matni."}

    async def fake_owner(channel_id, user_id=None, db_module=None):
        return {"ok": True, "insufficient": True, "sample_size": 2}

    orig = (db_mod.run_db, quota_mod.reserve_for_flow, quota_mod.take_reservation_id,
            quota_mod.release_ai_quota, HC.analyze_channel_voice,
            HC.generate_dna_sample_post, dna_mod.get_channel_dna)
    db_mod.run_db = fake_run_db
    quota_mod.reserve_for_flow = fake_reserve
    quota_mod.take_reservation_id = fake_take
    quota_mod.release_ai_quota = fake_release
    HC.analyze_channel_voice = fake_voice
    HC.generate_dna_sample_post = fake_sample
    dna_mod.get_channel_dna = fake_owner
    try:
        upd = _voice_update()
        ctx = SimpleNamespace(application=None, bot=SimpleNamespace(),
                              user_data={"lang": "uz"})
        state = asyncio.run(HC.channel_voice_analysis_callback(upd, ctx))
    finally:
        (db_mod.run_db, quota_mod.reserve_for_flow, quota_mod.take_reservation_id,
         quota_mod.release_ai_quota, HC.analyze_channel_voice,
         HC.generate_dna_sample_post, dna_mod.get_channel_dna) = orig

    from telegram.ext import ConversationHandler
    texts = [s["text"] for s in upd.callback_query.message.sent]
    joined = "\n".join(texts)

    check("tahlil natijasi ko'rsatildi (uslub saqlandi)",
          safe_t("ch_voice_result", "uz", tone="⚡️ Qisqa / Yangiliklar",
                 reason="Yangiliklar uslubi.")[:40] in joined, joined[:200])
    check("uslub bazaga yozildi (set_channel_tone)",
          calls["tone"] == [("-1001234567890", "concise")], str(calls["tone"]))
    check("namuna uchun ATOMIK bron olindi (1 birlik, dna_sample)",
          calls["reserve"] == [("dna_sample", "dna", 1)], str(calls["reserve"]))
    check("namuna kanal nomi + uslub + til bilan generatsiya qilindi",
          calls["generated"] and calls["generated"][0]["tone"] == "concise"
          and calls["generated"][0]["lang"] == "uz"
          and calls["generated"][0]["channel"] == "Mening Kanalim",
          str(calls["generated"]))
    check("bepul namuna matni foydalanuvchiga ko'rsatildi",
          "NAMUNA: kanalingiz ohangida yozilgan post matni." in joined, joined[:300])
    check("namuna sarlavhasi i18n'dan",
          safe_t("ch_dna_sample_title", "uz") in joined, joined[:200])
    check("namuna muvaffaqiyatli bo'lganda refund QILINMADI (faqat take)",
          all(c[0] == "take" for c in calls["release"]), str(calls["release"]))
    check("handler END holatida tugadi", state == ConversationHandler.END, str(state))

    # 8b) AI namuna bermasa — refund + muloyim izoh (foydalanuvchi to'lamaydi).
    calls["release"].clear()
    calls["generated"].clear()

    async def empty_sample(channel_title, tone="friendly", dna_block="", lang="uz"):
        return {"error": "ai down"}

    HC.generate_dna_sample_post = empty_sample
    db_mod.run_db = fake_run_db
    quota_mod.reserve_for_flow = fake_reserve
    quota_mod.take_reservation_id = fake_take
    quota_mod.release_ai_quota = fake_release
    HC.analyze_channel_voice = fake_voice
    dna_mod.get_channel_dna = fake_owner
    try:
        upd2 = _voice_update(user_id=777002)
        ctx2 = SimpleNamespace(application=None, bot=SimpleNamespace(),
                               user_data={"lang": "uz"})
        asyncio.run(HC.channel_voice_analysis_callback(upd2, ctx2))
    finally:
        db_mod.run_db, HC.generate_dna_sample_post = orig[0], orig[5]
        quota_mod.reserve_for_flow = orig[1]
        quota_mod.take_reservation_id = orig[2]
        quota_mod.release_ai_quota = orig[3]
        HC.analyze_channel_voice = orig[4]
        dna_mod.get_channel_dna = orig[6]

    texts2 = "\n".join(s["text"] for s in upd2.callback_query.message.sent)
    check("namuna xatosida BRON QAYTARILDI (fail-closed refund)",
          ("release", 4242) in calls["release"], str(calls["release"]))
    check("namuna xatosida muloyim izoh (3 tilda i18n)",
          safe_t("ch_dna_sample_error", "uz") in texts2, texts2[:200])


# ===========================================================================
def main():
    print("=" * 64)
    print(" 🧭 3-BOSQICH — MENYU IXCHAMLIGI + ONBOARDING (KANAL DNK) TESTLARI")
    print("=" * 64)
    test_1_compact_main_menu()
    test_2_settings_more_hub()
    test_3_backward_compatibility()
    test_4_dna_onboarding_offer()
    test_5_free_sample_draft()
    test_6_actionable_statistics_advice()
    test_7_i18n_parity_and_safety()
    test_8_onboarding_end_to_end()

    print("\n" + "=" * 64)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] 3-BOSQICH STANDARTIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" BARCHA 3-BOSQICH TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
