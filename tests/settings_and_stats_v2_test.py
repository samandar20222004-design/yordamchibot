#!/usr/bin/env python3
"""⚙️ SOZLAMALAR + 📊 STATISTIKA + ADMIN PANEL RBAC — PostAssist V2 (5-mikro qadam).

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  📊 STATISTIKA — «📊 Statistika» (uzun/noaniq nomlar emas) ekrani
           ixcham 4 ta asosiy ko'rsatkichni ko'rsatadi:
             📢 Ulangan kanallar soni / 📝 Yaratilgan postlar soni /
             📅 Rejalashtirilgan postlar soni / 🤖 AI so'rovlar & kreditlar.
           Natija ostida amallar: [🔄 Yangilash] [◀️ Orqaga]; Yangilash
           ma'lumotlarni qayta o'qiydi, Orqaga asosiy menyuga qaytaradi.
  TEST 2:  ⚙️ SOZLAMALAR — [⚙️ Sozlamalar] bosilganda bitta tartibli menyu
           (3-qadam refaktori: legacy dublikatlar olib tashlangan, 12 tugma):
             [👤 Profil]            [🌐 Til / Язык]
             [💎 Ballarim]          [🔄 Ballar o'tkazish]
             [🎁 Kunlik bonus]      [👥 Do'stlarni taklif]
             [🔔 Bildirishnomalar]  [🎨 Post sozlamalari]
             [💳 To'lovlar tarixi]  [🧰 Vositalar]
             [❓ Yordam]            [ℹ️ Bot haqida]
                          [◀️ Orqaga]
           Har bir 12 ta sub-tugma O'Z oqimini ochadi; [◀️ Orqaga] asosiy
           menyuga qaytaradi; profil va til almashtirish oqimlari buzilmagan.
           Eski cab_* callback'lari ALIAS sifatida ishlashda davom etadi.
  TEST 3:  ⚙️ ADMIN PANEL — oddiy foydalanuvchiga HECH QACHON ko'rinmaydi
           (klaviatura + handlerlar fail-closed); admin kirganda tizim
           monitoringi (Bot & DB, Scheduler, AI provayderlar, Pending manual
           to'lovlar) ko'rinadi; admin callback'larida server-side RBAC va
           tampering himoyasi saqlanadi.
  TEST 4:  🌐 I18N — translations/settings_stats.py UZ/RU/EN 100% paritet.
  TEST 5:  🛡 REGRESSIYA QO'RIQONLARI — asosiy menyu 6 tugma, FSM analytics
           holatlari, eski cab_*/an_* callback'lari va routing buzilmagan.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/settings_and_stats_v2_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:SETTINGS_STATS_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10005")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")

USER_ID = 777005
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))
NON_ADMIN_ID = 424242

# Statistika ekranining QAT'IY ko'rsatkich belgilari (har tilda).
EXPECTED_STATS_MARKERS = {
    "uz": ("📊 Statistika", "📢 Ulangan kanallar", "📝 Yaratilgan postlar",
           "📅 Rejalashtirilgan postlar", "🤖 AI so'rovlar", "Sarflangan kreditlar"),
    "ru": ("📊 Статистика", "📢 Подключено каналов", "📝 Создано постов",
           "📅 Запланировано постов", "🤖 AI-запросы", "Потрачено кредитов"),
    "en": ("📊 Statistics", "📢 Connected channels", "📝 Posts created",
           "📅 Scheduled posts", "🤖 AI requests", "Credits spent"),
}

# Sozlamalar menyusi — speksdagi 12 ta sub-tugma callback'lari (tartib bilan).
EXPECTED_SETTINGS_CBS = (
    "stgs_profile", "stgs_lang",
    "stgs_points", "stgs_transfer",
    "stgs_bonus", "stgs_referral",
    "stgs_notif", "stgs_post",
    "stgs_pay", "stgs_tools",
    "stgs_help", "stgs_about",
)

# Sozlamalar menyusi yorliqlari — SPEKS tartibi (uchala til).
# 3-qadam refaktori: legacy kabinet dublikatlari olib tashlandi va menyu
# 12 tugma + [◀️ Orqaga] ko'rinishiga keltirildi (tests/refactor_step3_test.py
# bu tarkibni alohida, qat'iy qo'riqlaydi).
EXPECTED_SETTINGS_LABELS = {
    "uz": (("👤 Profil", "🌐 Til / Язык"),
           ("💎 Ballarim", "🔄 Ballar o'tkazish"),
           ("🎁 Kunlik bonus", "👥 Do'stlarni taklif"),
           ("🔔 Bildirishnomalar", "🎨 Post sozlamalari"),
           ("💳 To'lovlar tarixi", "🧰 Vositalar"),
           ("❓ Yordam", "ℹ️ Bot haqida")),
    "ru": (("👤 Профиль", "🌐 Til / Язык"),
           ("💎 Мои баллы", "🔄 Перевести баллы"),
           ("🎁 Ежедневный бонус", "👥 Пригласить друзей"),
           ("🔔 Уведомления", "🎨 Настройки постов"),
           ("💳 История платежей", "🧰 Инструменты"),
           ("❓ Помощь", "ℹ️ О боте")),
    "en": (("👤 Profile", "🌐 Language"),
           ("💎 My credits", "🔄 Transfer credits"),
           ("🎁 Daily bonus", "👥 Invite friends"),
           ("🔔 Notifications", "🎨 Post settings"),
           ("💳 Payment history", "🧰 Tools"),
           ("❓ Help", "ℹ️ About")),
}


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def kb_rows_inline(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def kb_flat_cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import database as db_mod  # noqa: E402
import handlers.analytics as AN  # noqa: E402
import handlers.settings as STG  # noqa: E402
import handlers.admin as ADM  # noqa: E402
from keyboards.default import (  # noqa: E402
    BTN_ADMIN_PANEL, BTN_STATISTICS, BTN_STATISTICS_EN, BTN_STATISTICS_RU,
    get_main_keyboard,
)
from keyboards.inline import (  # noqa: E402
    get_settings_back_keyboard, get_settings_hub_keyboard, get_user_stats_keyboard,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    SETTINGS_MENU_BUTTON_KEYS, SETTINGS_STATS_I18N,
    settings_stats_parity_report, settings_stats_t,
)


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """reply_text yozib boruvchi soxta xabar."""

    def __init__(self, user_id=USER_ID):
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.sent = []
        self.deleted = False

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=len(self.sent), chat=self.chat)

    async def delete(self):
        self.deleted = True
        return True


class _Query:
    """edit_message_text / answer yozib boruvchi soxta callback query."""

    def __init__(self, data, user_id=USER_ID):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.message = _Msg(user_id)
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, **kwargs):
        return True

    @property
    def screen(self):
        if self.edits:
            return self.edits[-1]
        if self.message.sent:
            return self.message.sent[-1]
        return {}


def _upd_msg(msg):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=msg.from_user, callback_query=None)


def _upd_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user, callback_query=query)


class _Bot:
    username = "postassist_test_bot"

    async def get_me(self):
        return SimpleNamespace(username=self.username)


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={}, bot=_Bot(),
                           application=None)


class _FakeDB:
    """``database.run_db`` ni almashtiruvchi deterministik mock."""

    def __init__(self, overview=None, settings=None, payments=None):
        self.overview = overview if overview is not None else {
            "channels": 3, "created_posts": 42, "scheduled_posts": 5,
            "ai_requests": 12, "credits_spent": 12,
        }
        self.settings_store = dict(settings or {})
        self.payments = payments if payments is not None else []
        self.set_calls = []
        self.overview_reads = 0

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        if name == "get_user_overview_stats":
            self.overview_reads += 1
            return dict(self.overview)
        if name == "get_referral_stats":
            return {"referrals_count": 2, "ai_credits": 7, "streak": 3}
        if name == "get_user_channels":
            return [("-1001", "Kanal A", "friendly"), ("-1002", "Kanal B", "formal")]
        if name == "get_user_code":
            return "TST777"
        if name == "get_user_settings_bulk":
            keys = args[1] if len(args) > 1 else []
            defaults = args[2] if len(args) > 2 else {}
            out = {}
            for key in keys:
                out[key] = self.settings_store.get(key, bool(defaults.get(key, False)))
            return out
        if name == "set_user_setting":
            self.set_calls.append((args[0], args[1], args[2]))
            self.settings_store[args[1]] = bool(args[2])
            return True
        if name == "get_user_payment_history":
            return list(self.payments)
        if name == "get_admin_dashboard_stats":
            return {"users": 10, "pro_subscribers": 2, "channels": 4,
                    "posts_today": 3, "pending_posts": 1, "stars_revenue": 99}
        if name == "get_system_stats":
            return {"users": 10, "channels": 4, "sponsors": 1, "pending": 1,
                    "sent": 20, "cancelled": 2, "failed": 1}
        if name == "get_sponsor_channels":
            return []
        if name == "is_premium":
            return False
        if name == "get_ads_full":
            return []
        if name == "get_setting":
            return args[1] if len(args) > 1 else ""
        if name == "get_post_health_counts":
            return {"pending": 1, "processing": 0, "failed": 0,
                    "stale_processing": 0, "delivery_failed": 0,
                    "dead_letter": 0, "unknown_posts": 0, "unknown_delivery": 0}
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")


def _with_db(fake, coro):
    """``db.run_db`` ni vaqtincha mock bilan almashtirib, korutinani bajaradi.

    ``coro`` — tayyor korutina YOKI korutina qaytaruvchi funksiyani qabul
    qiladi (test o'quvchanligi uchun).
    """
    if callable(coro) and not asyncio.iscoroutine(coro):
        coro = coro()
    original = db_mod.run_db
    db_mod.run_db = fake.run_db
    try:
        return asyncio.run(coro)
    finally:
        db_mod.run_db = original


def _health_fixture():
    """Deterministik health natijasi (DB/tarmoqsiz)."""
    return {
        "status": "HEALTHY",
        "checked_at": "2026-09-14T06:00:00+00:00",
        "uptime_seconds": 123.0,
        "database": {"status": "OK", "ok": True, "latency_ms": 12, "pool": {}},
        "scheduler": {"status": "RUNNING", "running": True, "jobs": 5,
                      "pending": 1, "processing": 0, "failed": 0,
                      "stale_processing": 0, "delivery_failed": 0,
                      "dead_letter": 0, "unknown_posts": 0,
                      "unknown_delivery": 0},
        "ai_providers": {
            "status": "OK",
            "providers": [
                {"name": "gemini", "tier": 1, "status": "OK"},
                {"name": "groq", "tier": 2, "status": "OK"},
                {"name": "openrouter", "tier": 3, "status": "UNCONFIGURED"},
            ],
            "core_ok": 2, "core_total": 3, "breakers_open": 0,
            "consecutive_errors": 0,
        },
        "payments": {"status": "OK", "pending_receipts": 2,
                     "approved_24h": 1, "stars_24h": 300},
        "system": {"uptime_human": "2m 3s", "asyncio_tasks": 10,
                   "errors_last_hour": 0, "errors_last_24h": 0},
    }


# ============================================================================
# TEST 1 — 📊 STATISTIKA KO'RSATKICHLARI FORMATI
# ============================================================================
def test_statistics_overview_format():
    print("\n== TEST 1: 📊 Statistika — ixcham ko'rsatkichlar + amallar ==")

    # 1a) Nomi aniq «📊 Statistika» — uzun/noaniq nomlar emas (uchala til).
    check("uz: statistika yorlig'i = '📊 Statistika'", BTN_STATISTICS == "📊 Statistika")
    check("ru: statistika yorlag'i = '📊 Статистика'", BTN_STATISTICS_RU == "📊 Статистика")
    check("en: statistika yorlig'i = '📊 Statistics'", BTN_STATISTICS_EN == "📊 Statistics")

    fake = _FakeDB()
    for lang in LANGS:
        async def _run(lang=lang):
            msg = _Msg()
            ctx = _ctx(lang)
            state = await AN.start_analytics(_upd_msg(msg), ctx)
            return msg, ctx, state

        msg, ctx, state = _with_db(fake, _run())
        check(f"{lang}: statistika ekrani ochildi (state=ANALYTICS_VIEW)",
              state == AN.ANALYTICS_VIEW, str(state))
        text = msg.sent[-1]["text"]
        # HTML teglarini hisobga olmagan holda tekshiriladi.
        plain = text.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", "")
        for marker in EXPECTED_STATS_MARKERS[lang]:
            check(f"{lang}: ko'rsatkich bor — {marker!r}", marker in plain, plain[:120])
        # Qiymatlar to'g'ri ko'rsatiladi.
        check(f"{lang}: kanallar=3", "3" in text)
        check(f"{lang}: yaratilgan=42", "42" in text)
        check(f"{lang}: rejalashtirilgan=5", "5" in text)
        check(f"{lang}: ai=12", "12" in text)
        # Tartib: kanallar → postlar → reja → AI (speks ketma-ketligi).
        idx = [text.find(m) for m in EXPECTED_STATS_MARKERS[lang][1:5]]
        check(f"{lang}: ko'rsatkichlar tartibi to'g'ri", idx == sorted(idx), str(idx))
        # Natija ostida amallar: [🔄 Yangilash] [◀️ Orqaga].
        kb = msg.sent[-1]["reply_markup"]
        rows = kb_rows_inline(kb)
        check(f"{lang}: amallar bitta qatorda [Yangilash][Orqaga]",
              len(rows) == 1 and len(rows[0]) == 2, str(rows))
        check(f"{lang}: amallar callback'lari an_refresh/an_close",
              kb_flat_cbs(kb) == ["an_refresh", "an_close"], str(kb_flat_cbs(kb)))

    # 1b) 🔄 Yangilash — ma'lumotlar qayta o'qiladi, ekran yangilanadi.
    fake = _FakeDB()
    async def _refresh():
        msg = _Msg()
        ctx = _ctx("uz")
        await AN.start_analytics(_upd_msg(msg), ctx)
        reads_after_open = fake.overview_reads
        fake.overview = {"channels": 4, "created_posts": 50, "scheduled_posts": 6,
                         "ai_requests": 15, "credits_spent": 15}
        q = _Query("an_refresh")
        state = await AN.analytics_view_callback(_upd_query(q), ctx)
        return q, state, reads_after_open

    q, state, reads_before = _with_db(fake, _refresh())
    check("refresh: state ANALYTICS_VIEW saqlanadi", state == AN.ANALYTICS_VIEW)
    check("refresh: statistika qayta o'qildi", fake.overview_reads > reads_before)
    new_text = q.screen.get("text", "")
    check("refresh: yangi qiymatlar ekranda (4 kanal / 50 post)",
          "4" in new_text and "50" in new_text, new_text[:120])
    check("refresh: klaviatura [🔄 Yangilash][◀️ Orqaga]",
          kb_flat_cbs(q.screen["reply_markup"]) == ["an_refresh", "an_close"])

    # 1c) ◀️ Orqaga — asosiy menyu qaytadi, dialog yopiladi.
    from telegram.ext import ConversationHandler
    async def _back():
        msg = _Msg()
        ctx = _ctx("uz")
        await AN.start_analytics(_upd_msg(msg), ctx)
        q = _Query("an_close")
        state = await AN.analytics_view_callback(_upd_query(q), ctx)
        return q, state

    q, state = _with_db(_FakeDB(), _back())
    check("orqaga: dialog END", state == ConversationHandler.END)
    closed = q.message.sent[-1]
    check("orqaga: 'Yopildi' xabari", get_text("msg_closed", "uz") in closed["text"])
    main_labels = [b.text for row in closed["reply_markup"].keyboard for b in row]
    check("orqaga: asosiy 6 tugmali menyu qaytdi", len(main_labels) == 6, str(main_labels))

    # 1d) Kanallar yo'q bo'lsa ham statistika ekrani ochiladi (nollar bilan).
    async def _empty():
        msg = _Msg()
        ctx = _ctx("uz")
        state = await AN.start_analytics(_upd_msg(msg), ctx)
        return msg, state

    empty_fake = _FakeDB(overview={"channels": 0, "created_posts": 0,
                                    "scheduled_posts": 0, "ai_requests": 0,
                                    "credits_spent": 0})
    msg, state = _with_db(empty_fake, _empty())
    check("kanal yo'q: baribir statistika ekrani (END emas)",
          state == AN.ANALYTICS_VIEW and msg.sent)


# ============================================================================
# TEST 2 — ⚙️ SOZLAMALAR: 12 SUB-TUGMA + [◀️ ORQAGA] (legacy dublikatlarsiz)
# ============================================================================
def test_settings_menu_structure_and_flows():
    print("\n== TEST 2: ⚙️ Sozlamalar — yagona tartibli menyu (12+Orqaga) ==")
    from telegram.ext import ConversationHandler

    # Legacy kabinet tezkor tugmalari — menyuda KO'RINMASLIGI shart
    # (ular o'z asosiy menyularida bor: 📢 Kanallarim, 📅 Rejalashtirilgan...).
    legacy_cbs = ("cab_channels", "cab_analytics", "cab_pending", "cab_queue",
                  "cab_balance", "cab_bonus", "close_cabinet")

    # 2a) Menyu strukturasi — SPEKS tartibi (uchala til).
    for lang in LANGS:
        kb = get_settings_hub_keyboard(lang)
        rows = kb_rows_inline(kb)
        expected = EXPECTED_SETTINGS_LABELS[lang]
        check(f"{lang}: birinchi 6 qator = speksdagi 12 tugma",
              [[t for t, _ in row] for row in rows[:6]] == [
                  list(r) for r in expected],
              str(rows[:6]))
        check(f"{lang}: 12 tugma callback tartibi",
              kb_flat_cbs(kb)[:12] == list(EXPECTED_SETTINGS_CBS),
              str(kb_flat_cbs(kb)[:12]))
        check(f"{lang}: oxirgi qator = [◀️ Orqaga] (stgs_back)",
              rows[-1] == [(settings_stats_t("ss_btn_back", lang), "stgs_back")],
              str(rows[-1]))
        check(f"{lang}: legacy cab_* dublikatlar YO'Q",
              not any(cb in kb_flat_cbs(kb) for cb in legacy_cbs),
              str(kb_flat_cbs(kb)))
        for row in rows:
            for _label, cbdata in row:
                check(f"{lang}: cb <= 64 bayt ({cbdata})",
                      len(cbdata.encode("utf-8")) <= 64)

    # 2b) [⚙️ Sozlamalar] → user_cabinet_menu hub ekranini chizadi.
    import handlers  # noqa: F401 — modulni reyestrga qo'yadi
    ST = sys.modules["handlers.start"]  # atributni `start` funksiya soyalamaydi
    fake = _FakeDB()
    async def _open(lang="uz"):
        msg = _Msg()
        ctx = _ctx(lang)
        await ST.user_cabinet_menu(_upd_msg(msg), ctx)
        return msg

    for lang in LANGS:
        msg = _with_db(fake, lambda lang=lang: _open(lang))
        text = msg.sent[-1]["text"]
        cbs = kb_flat_cbs(msg.sent[-1]["reply_markup"])
        check(f"{lang}: hub profil matni bilan ochiladi",
              get_text("cabinet_title", lang, user_id=USER_ID, user_code="TST777",
                       credits="7", streak="3/7", channels=2, referrals=2,
                       ad_line="").splitlines()[0] in text, text[:80])
        check(f"{lang}: 12 stgs callback menyuda",
              all(cb in cbs for cb in EXPECTED_SETTINGS_CBS), str(cbs))
        check(f"{lang}: stgs_back menyuda", "stgs_back" in cbs)
        check(f"{lang}: legacy tugmalar yo'q (user_cabinet_menu)",
              not any(cb in cbs for cb in legacy_cbs), str(cbs))
        labels = [b.text for row in msg.sent[-1]["reply_markup"].inline_keyboard
                  for b in row]
        check(f"{lang}: legacy yorliqlar yo'q",
              get_text("cab_my_channels", lang) not in labels
              and get_text("cab_pending", lang) not in labels
              and get_text("cab_balance", lang) not in labels, str(labels))

    # 2c) 👤 Profil — mavjud kabinet ekrani (cabinet_title + cab_* klaviatura).
    fake = _FakeDB()
    async def _profile():
        q = _Query("stgs_profile")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(fake, _profile)
    prof_text = q.screen.get("text", "")
    prof_cbs = kb_flat_cbs(q.screen.get("reply_markup"))
    check("profil: cabinet_title matni", "Shaxsiy Kabinet" in prof_text, prof_text[:80])
    check("profil: eski cabinet klaviaturasi (cab_channels/cab_lang)",
          "cab_channels" in prof_cbs and "cab_lang" in prof_cbs, str(prof_cbs))

    # 2d) 🌐 Til / Язык — mavjud til almashtirish klaviaturasi.
    async def _lang():
        q = _Query("stgs_lang")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(_FakeDB(), _lang)
    lang_cbs = kb_flat_cbs(q.screen.get("reply_markup"))
    check("til: lang_prompt matni", "Tilni tanlang" in q.screen.get("text", ""))
    check("til: cab_lang_uz/ru/en callback'lari",
          {"cab_lang_uz", "cab_lang_ru", "cab_lang_en"} <= set(lang_cbs),
          str(lang_cbs))

    # 2e) 🔔 Bildirishnomalar — toggle ekrani + toggle amali.
    fake = _FakeDB(settings={"notify_news": False})
    async def _notif():
        q = _Query("stgs_notif")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        screen_text = q.screen.get("text", "")
        cbs = kb_flat_cbs(q.screen.get("reply_markup"))
        # Toggle: notify_news ni yoqish.
        q2 = _Query("stgs_tgl:notif:notify_news")
        await STG.settings_menu_callback(_upd_query(q2), _ctx("uz"))
        return screen_text, cbs, q2

    screen_text, notif_cbs, q2 = _with_db(fake, _notif)
    check("bildirishnomalar: sarlavha", "Bildirishnomalar" in screen_text, screen_text[:80])
    check("bildirishnomalar: ikki sozlama yorlig'i",
          "Rejalashtirilgan post eslatmalari" in screen_text
          and "Yangiliklar" in screen_text)
    check("bildirishnomalar: toggle callback'lari",
          "stgs_tgl:notif:notify_scheduled" in notif_cbs
          and "stgs_tgl:notif:notify_news" in notif_cbs, str(notif_cbs))
    check("bildirishnomalar: stgs_back bor", "stgs_back" in notif_cbs)
    check("bildirishnomalar: toggle DB'ga yozildi (True)",
          fake.set_calls == [(USER_ID, "notify_news", True)], str(fake.set_calls))
    toggled_text = q2.screen.get("text", "")
    check("bildirishnomalar: toggle'dan keyin ✅ belgisi",
          "✅" in toggled_text and "Yangiliklar" in toggled_text, toggled_text[:120])

    # 2f) 🎨 Post sozlamalari — toggle ekrani.
    fake = _FakeDB()
    async def _post_set():
        q = _Query("stgs_post")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(fake, _post_set)
    post_text = q.screen.get("text", "")
    post_cbs = kb_flat_cbs(q.screen.get("reply_markup"))
    check("post sozlamalari: sarlavha", "Post sozlamalari" in post_text, post_text[:80])
    check("post sozlamalari: watermark/imzo yorliqlari",
          "watermark" in post_text and "imzo" in post_text)
    check("post sozlamalari: toggle callback'lari",
          "stgs_tgl:post:post_watermark" in post_cbs
          and "stgs_tgl:post:post_signature" in post_cbs, str(post_cbs))

    # 2g) Toggle OQ RO'YXATI: payload'dan kelgan soxta kalit rad etiladi.
    fake = _FakeDB()
    async def _bad_toggle():
        q = _Query("stgs_tgl:notif:evil_key")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(fake, _bad_toggle)
    check("soxta toggle kaliti: DB amali YO'Q (fail-closed)", fake.set_calls == [])
    check("soxta toggle kaliti: ekran chizilmaydi", not q.edits and not q.message.sent)

    # 2h) 💳 To'lovlar tarixi — ro'yxat va bo'sh holat.
    from datetime import datetime, timezone
    pays = [
        {"date": datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc), "amount": 300,
         "currency": "XTR", "method": "stars", "status": "succeeded"},
        {"date": datetime(2026, 8, 15, 9, 30, tzinfo=timezone.utc), "amount": 19000,
         "currency": "UZS", "method": "card", "status": "approved"},
    ]
    fake = _FakeDB(payments=pays)
    async def _pay():
        q = _Query("stgs_pay")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(fake, _pay)
    pay_text = q.screen.get("text", "")
    check("to'lovlar: sarlavha", "To'lovlar tarixi" in pay_text, pay_text[:80])
    check("to'lovlar: Stars yozuvi", "300 XTR" in pay_text, pay_text)
    check("to'lovlar: karta yozuvi", "19000 UZS" in pay_text, pay_text)
    check("to'lovlar: jami 2 ta", "2" in pay_text)
    check("to'lovlar: stgs_back",
          "stgs_back" in kb_flat_cbs(q.screen.get("reply_markup")))

    fake = _FakeDB(payments=[])
    q = _with_db(fake, _pay)
    check("to'lovlar bo'sh: tushunarli ekran",
          "Hozircha to'lovlaringiz mavjud emas" in q.screen.get("text", ""))

    # 2i) 🎁 Do'stlarni taklif qilish — referral menyu shu yerda ochiladi.
    fake = _FakeDB()
    async def _ref():
        q = _Query("stgs_referral")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(fake, _ref)
    ref_text = q.screen.get("text", "")
    ref_cbs = kb_flat_cbs(q.screen.get("reply_markup"))
    check("referral: havola matnda",
          f"https://t.me/postassist_test_bot?start=ref_{USER_ID}" in ref_text,
          ref_text[:160])
    check("referral: share + stgs_back tugmalari", "stgs_back" in ref_cbs, str(ref_cbs))

    # 2j) ❓ Yordam — qo'llanma shu menyu orqali ochiladi.
    async def _help():
        q = _Query("stgs_help")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(_FakeDB(), _help)
    help_cbs = kb_flat_cbs(q.screen.get("reply_markup"))
    check("yordam: qo'llanma matni", len(q.screen.get("text", "")) > 50)
    check("yordam: FAQ tugmasi + stgs_back",
          "help:faq" in help_cbs and "stgs_back" in help_cbs, str(help_cbs))

    # 2k) ℹ️ Bot haqida — yangi bo'lim shu menyu orqali ochiladi.
    async def _about():
        q = _Query("stgs_about")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(_FakeDB(), _about)
    check("bot haqida: matn", "PostAssist" in q.screen.get("text", ""))
    check("bot haqida: stgs_back",
          kb_flat_cbs(q.screen.get("reply_markup")) == ["stgs_back"])

    # 2l) ◀️ Orqaga — asosiy menyuga qaytish.
    async def _back():
        q = _Query("stgs_back")
        await STG.settings_menu_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(_FakeDB(), _back)
    closed = q.message.sent[-1]
    check("orqaga: xabar o'chirildi", q.message.deleted is True)
    check("orqaga: 'Yopildi' + asosiy menyu",
          get_text("msg_closed", "uz") in closed["text"])
    main_labels = [b.text for row in closed["reply_markup"].keyboard for b in row]
    check("orqaga: asosiy menyu 6 tugma", len(main_labels) == 6, str(main_labels))


# ============================================================================
# TEST 3 — ⚙️ ADMIN PANEL: RBAC (oddiy foydalanuvchiga mutlaqo yopiq)
# ============================================================================
def test_admin_panel_rbac_and_health():
    print("\n== TEST 3: Admin Panel RBAC + tizim monitoringi ==")
    from telegram.ext import ConversationHandler
    import services.health_service as HS

    # 3a) Klaviatura: Admin Panel oddiy foydalanuvchiga HECH QACHON ko'rinmaydi.
    for lang in LANGS:
        user_labels = [b.text for row in get_main_keyboard(False, lang=lang).keyboard
                       for b in row]
        admin_labels = [b.text for row in get_main_keyboard(True, lang=lang).keyboard
                        for b in row]
        check(f"{lang}: oddiy foydalanuvchida Admin Panel YO'Q",
              BTN_ADMIN_PANEL not in user_labels, str(user_labels))
        check(f"{lang}: adminda Admin Panel bor (7 tugma)",
              BTN_ADMIN_PANEL in admin_labels and len(admin_labels) == 7,
              str(admin_labels))

    # 3b) admin_panel_menu: oddiy foydalanuvchi — JIM rad (fail-closed).
    fake = _FakeDB()
    async def _deny():
        msg = _Msg(NON_ADMIN_ID)
        ctx = _ctx("uz")
        state = await ADM.admin_panel_menu(_upd_msg(msg), ctx)
        return msg, state

    msg, state = _with_db(fake, _deny)
    check("non-admin: admin_panel_menu javob bermaydi", not msg.sent)
    check("non-admin: dialog END", state == ConversationHandler.END)

    # 3c) Admin kirganda tizim monitoringi (Health status) ko'rinadi.
    orig_get_health = HS.get_system_health

    async def _fake_health():
        return _health_fixture()

    HS.get_system_health = _fake_health
    try:
        async def _admin_open():
            msg = _Msg(ADMIN_ID)
            ctx = _ctx("uz")
            state = await ADM.admin_panel_menu(_upd_msg(msg), ctx)
            return msg, state

        msg, state = _with_db(fake, _admin_open)
        text = msg.sent[-1]["text"] if msg.sent else ""
        check("admin: panel ochildi", state == ConversationHandler.END and bool(msg.sent))
        check("admin: dashboard statistikasi bor", "Admin Boshqaruv Paneli" in text)
        check("admin: 🩺 Tizim monitoringi bloki bor", "Tizim monitoringi" in text, text[-400:])
        check("admin: Bot & DB holati", "Bot & DB" in text, text[-400:])
        check("admin: Scheduler holati", "Scheduler" in text, text[-400:])
        check("admin: AI provayderlar (Gemini/Groq/OpenRouter)",
              "gemini" in text and "groq" in text and "openrouter" in text,
              text[-400:])
        check("admin: Pending manual to'lovlar",
              "Pending manual to'lovlar" in text and "2" in text, text[-400:])
        check("admin: health inline klaviaturasi o'zgarmagan (7 tugma)",
              kb_flat_cbs(msg.sent[-1]["reply_markup"]).count("adm_stats") == 1)
    finally:
        HS.get_system_health = orig_get_health

    # 3d) Health bloki xato bo'lsa ham dashboard chiqadi (crash yo'q).
    async def _broken_health():
        raise RuntimeError("db down")

    HS.get_system_health = _broken_health
    try:
        msg, state = _with_db(fake, _admin_open)
        text = msg.sent[-1]["text"] if msg.sent else ""
        check("health yiqilsa ham panel chiqadi", "Admin Boshqaruv Paneli" in text)
        check("health yiqilsa blok chizilmaydi", "Tizim monitoringi" not in text)
    finally:
        HS.get_system_health = orig_get_health

    # 3e) Admin callback'lari: server-side RBAC + tampering himoyasi.
    from services.rbac_service import verify_admin_callback

    def _cb_update(data, user_id):
        from telegram import Update
        return Update.de_json({
            "update_id": 1,
            "callback_query": {
                "id": "cbq-1",
                "from": {"id": user_id, "is_bot": False, "first_name": "T"},
                "chat_instance": "ci-1",
                "data": data,
                "message": {
                    "message_id": 5, "date": 0,
                    "chat": {"id": user_id, "type": "private"},
                    "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                },
            },
        }, None)

    check("verify_admin_callback: non-admin → False",
          verify_admin_callback(_cb_update("adm_stats", NON_ADMIN_ID)) is False)
    check("verify_admin_callback: admin → True",
          verify_admin_callback(_cb_update("adm_stats", ADMIN_ID)) is True)

    # Non-admin adm_stats bosadi → rad javobi, DB amali YO'Q.
    fake = _FakeDB()
    async def _non_admin_cb():
        q = _Query("adm_stats", NON_ADMIN_ID)
        ctx = _ctx("uz")
        state = await ADM.admin_dashboard_callback(_upd_query(q), ctx)
        return q, state

    q, state = _with_db(fake, _non_admin_cb)
    check("non-admin adm_stats: rad javobi",
          any(a == "Ruxsat yo'q." for a in q.answered), str(q.answered))
    check("non-admin adm_stats: END, dashboard yo'q",
          state == ConversationHandler.END and not q.edits)

    # 3f) adm_health: ruxsat darajalari (RBAC).
    # Non-admin — umuman rad.
    async def _health_non_admin():
        q = _Query("adm_health", NON_ADMIN_ID)
        await ADM.admin_dashboard_callback(_upd_query(q), _ctx("uz"))
        return q

    q = _with_db(_FakeDB(), _health_non_admin)
    check("adm_health non-admin: rad", not q.edits and q.answered)

    # Admin, lekin system_settings ruxsati YO'Q (mock) — rad.
    orig_has_perm = ADM.has_permission
    ADM.has_permission = lambda uid, perm: False
    try:
        async def _health_no_perm():
            q = _Query("adm_health", ADMIN_ID)
            await ADM.admin_dashboard_callback(_upd_query(q), _ctx("uz"))
            return q

        q = _with_db(_FakeDB(), _health_no_perm)
        check("adm_health ruxsatsiz admin: rad", not q.edits and q.answered)
    finally:
        ADM.has_permission = orig_has_perm

    # OWNER (system_settings bor) — to'liq health hisoboti.
    HS.get_system_health = _fake_health
    try:
        async def _health_ok():
            q = _Query("adm_health", ADMIN_ID)
            await ADM.admin_dashboard_callback(_upd_query(q), _ctx("uz"))
            return q

        q = _with_db(_FakeDB(), _health_ok)
        rep_text = q.screen.get("text", "")
        check("adm_health OWNER: hisobot chiqdi", bool(rep_text), str(q.screen)[:80])
        check("adm_health: DB bo'limi", "Database" in rep_text or "DB" in rep_text,
              rep_text[:200])
        check("adm_health: Scheduler bo'limi", "Scheduler" in rep_text or "scheduler" in rep_text.lower())
        check("adm_health: AI provayderlar", "gemini" in rep_text and "groq" in rep_text)
        check("adm_health: pending manual to'lovlar",
              "2" in rep_text and ("to'lov" in rep_text.lower() or "платеж" in rep_text.lower()
                                    or "payment" in rep_text.lower()))
        check("adm_health: orqaga tugmasi",
              "adm_back" in kb_flat_cbs(q.screen.get("reply_markup")))
    finally:
        HS.get_system_health = orig_get_health

    # 3g) «📊 Statistika» dispatcher'i: STATISTIKA IZOLYATSIYASI — admin
    # bo'ladimi, oddiy foydalanuvchimi — FAQAT shaxsiy hisobot
    # (show_user_statistics). Admin (bot bo'yicha) statistikasiga bu yerdan
    # hech qanday yo'l yo'q; u faqat ⚙️ Admin Panel → 📊 To'liq statistika.
    import handlers as H
    stats_code = getattr(getattr(H, "statistics_button", None), "__code__", None)
    names = set(getattr(stats_code, "co_names", ()))
    check("statistics_button: show_user_statistics (shaxsiy hisobot) bor",
          "show_user_statistics" in names, str(sorted(names)))
    check("statistics_button: show_statistics (ADMIN) YO'Q",
          "show_statistics" not in names, str(sorted(names)))
    check("statistics_button: start_analytics (eski analitika) YO'Q",
          "start_analytics" not in names, str(sorted(names)))
    check("statistics_button: admin panelga yo'l YO'Q",
          "admin_panel_menu" not in names, str(sorted(names)))
    check("statistics_button: ADMIN_IDS bo'yicha shartlash YO'Q",
          "ADMIN_IDS_SET" not in names, str(sorted(names)))


# ============================================================================
# TEST 4 — 🌐 I18N: UZ/RU/EN 100% PARITET
# ============================================================================
def test_i18n_parity():
    print("\n== TEST 4: translations/settings_stats.py — UZ/RU/EN paritet ==")

    report = settings_stats_parity_report()
    check("paritet: in_sync", report["in_sync"] is True, str(report)[:200])
    check("paritet: kalitlar 40+", report["keys"] >= 40, str(report["keys"]))
    check("paritet: missing yo'q", not any(report["missing"].values()),
          str(report["missing"]))
    check("paritet: extra yo'q", not any(report["extra"].values()),
          str(report["extra"]))
    check("paritet: format-arg mosligi", not report["format_mismatch"],
          str(report["format_mismatch"]))
    check("paritet: bo'sh matn yo'q", not report["empty"], str(report["empty"]))

    # Sozlamalar menyusining 12+ kaliti uchala tilda bo'sh emas.
    for lang in LANGS:
        for key in SETTINGS_MENU_BUTTON_KEYS:
            value = settings_stats_t(key, lang)
            check(f"{lang}: menyu kaliti {key!r} bo'sh emas",
                  bool(value) and value != key, repr(value))

    # Statistika qatorlari uchala tilda formatlanadi (qiymatlar o'rniga tushadi).
    for lang in LANGS:
        row = settings_stats_t("ss_stats_channels", lang, n=5)
        check(f"{lang}: ss_stats_channels formatlanadi", "5" in row and "{" not in row, row)
        ai = settings_stats_t("ss_stats_ai", lang, ai=7, credits=7)
        check(f"{lang}: ss_stats_ai formatlanadi", "7" in ai and "{" not in ai, ai)

    # Har til lug'ati bir xil kalitlar to'plami (himoya qatlami).
    uz_keys = set(SETTINGS_STATS_I18N["uz"])
    for lang in ("ru", "en"):
        check(f"{lang}: kalitlar to'plami uz bilan bir xil",
              set(SETTINGS_STATS_I18N[lang]) == uz_keys)


# ============================================================================
# TEST 5 — 🛡 REGRESSIYA QO'RIQONLARI
# ============================================================================
def test_regression_guards():
    print("\n== TEST 5: regressiya qo'riqonlari ==")
    from telegram.ext import CallbackQueryHandler, ConversationHandler
    import handlers as H

    # 5a) Asosiy menyu — QAT'IY 6 tugma (o'zgarmagan).
    for lang in LANGS:
        labels = [b.text for row in get_main_keyboard(False, lang=lang).keyboard
                  for b in row]
        check(f"{lang}: asosiy menyu 6 tugma", len(labels) == 6, str(labels))
        check(f"{lang}: statistika tugmasi 2-qator 2-ustun",
              get_main_keyboard(False, lang=lang).keyboard[1][1].text
              == get_text("btn_statistics", lang))

    # 5b) Analytics FSM holatlari ro'yxatda (dialoglar buzilmagan).
    app_holder = {}

    class _Recorder:
        def add_handler(self, h, group=0):
            app_holder.setdefault("handlers", []).append((group, h))

    H.register_all_handlers(_Recorder())
    convs = [h for _g, h in app_holder["handlers"]
             if isinstance(h, ConversationHandler)]
    check("main_conv ro'yxatda", len(convs) >= 1)
    main_conv = convs[0]
    check("ANALYTICS_CHOOSE holati saqlangan", AN.ANALYTICS_CHOOSE in main_conv.states)
    check("ANALYTICS_VIEW holati saqlangan", AN.ANALYTICS_VIEW in main_conv.states)

    # 5c) Eski analytics yordamchilari joyida (kanal darajasidagi analitika).
    check("_get_analytics_channel_keyboard saqlangan",
          callable(AN._get_analytics_channel_keyboard))
    check("_get_analytics_view_keyboard saqlangan",
          callable(AN._get_analytics_view_keyboard))
    check("_build_dashboard saqlangan", callable(AN._build_dashboard))

    # 5d) Callback routing: stgs_, cab_ va an_ handlerlari ro'yxatda.
    cb_handlers = [h for _g, h in app_holder["handlers"]
                   if isinstance(h, CallbackQueryHandler)]
    patterns = [getattr(h, "pattern", None) for h in cb_handlers]
    joined = " | ".join(str(p.pattern if hasattr(p, 'pattern') else p)
                        for p in patterns if p)
    check("stgs_ handleri ro'yxatda", any("stgs_" in str(p.pattern if hasattr(p, 'pattern') else p)
                                          for p in patterns if p), joined[:200])
    check("cab_/close_cabinet handleri ro'yxatda",
          any("cab_" in str(p.pattern if hasattr(p, 'pattern') else p)
              for p in patterns if p))

    # an_refresh/an_close — ANALYTICS_VIEW holatida ishlanadi (routing).
    view_handlers = main_conv.states[AN.ANALYTICS_VIEW]
    matched = []
    from telegram import Update
    for data in ("an_refresh", "an_close", "an_other"):
        upd = Update.de_json({
            "update_id": 1,
            "callback_query": {
                "id": "cbq-1",
                "from": {"id": USER_ID, "is_bot": False, "first_name": "T"},
                "chat_instance": "ci-1",
                "data": data,
                "message": {
                    "message_id": 5, "date": 0,
                    "chat": {"id": USER_ID, "type": "private"},
                    "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                },
            },
        }, None)
        ok = any(h.check_update(upd) not in (None, False) for h in view_handlers)
        matched.append((data, ok))
    for data, ok in matched:
        check(f"ANALYTICS_VIEW routing: {data}", ok)

    # 5e) «📊 Statistika» routing — yagona statistics_button (admin/user).
    from keyboards.default import MENU_TEXTS
    check("statistics oilasi registry'da",
          BTN_STATISTICS in MENU_TEXTS.get("statistics", ()),
          str(MENU_TEXTS.get("statistics", ())[:4]))

    # 5f) Sozlamalar keyboard builder'lari callback xavfsizligi (64 bayt).
    from keyboards.callback_data import is_callback_safe
    for lang in LANGS:
        for kb in (get_settings_hub_keyboard(lang), get_settings_back_keyboard(lang),
                   get_user_stats_keyboard(lang)):
            for row in kb.inline_keyboard:
                for btn in row:
                    if btn.callback_data:
                        check(f"{lang}: cb xavfsiz ({btn.callback_data[:24]}…)",
                              is_callback_safe(btn.callback_data))

    # 5g) Statistika ekrani keyboard builder'i — an_refresh/an_close.
    kb = get_user_stats_keyboard("uz")
    check("stats kb: [🔄 Yangilash][◀️ Orqaga]",
          kb_flat_cbs(kb) == ["an_refresh", "an_close"], str(kb_flat_cbs(kb)))
    check("stats kb: yorliqlar i18n'dan",
          kb.inline_keyboard[0][0].text == settings_stats_t("ss_btn_refresh", "uz")
          and kb.inline_keyboard[0][1].text == settings_stats_t("ss_btn_back", "uz"))


# ============================================================================
# MAIN
# ============================================================================
def main():
    test_statistics_overview_format()
    test_settings_menu_structure_and_flows()
    test_admin_panel_rbac_and_health()
    test_i18n_parity()
    test_regression_guards()

    print(f"\nJAMI: o'tdi={passed}, xato={failures}")
    if failures:
        sys.exit(1)
    print("Barcha Sozlamalar & Statistika V2 testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
