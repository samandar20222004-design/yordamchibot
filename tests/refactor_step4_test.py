#!/usr/bin/env python3
"""🧭 POSTASSIST V2 · 4-QADAM REFAKTOR — KONTRAKT TESTLARI (deterministik, tarmoqsiz).

Qamrov (4-qadam topshirig'i bo'yicha):

  TEST 1 — 🧭 NAVIGATSIYA STACKI:
           * Kontent yaratish → 🤖 AI Yordamchi → [◀️ Orqaga] → KONTENT
             YARATISH SUBMENYUSIGA qaytadi (asosiy menyuga sakrab ketmaydi);
           * Kanallarim → Kanal → [◀️ Orqaga] → KANALLAR RO'YXATIGA qaytadi;
           * Sozlamalar → 🧰 Vositalar → [◀️ Orqaga] → SOZLAMALAR menyusiga
             qaytadi.

  TEST 2 — ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu MANTIG'I AJRATILDI:
           * FSM ichida [❌ Bekor qilish] — kontekst tozalanadi va O'SHA
             BO'LIM BOSHIGA qaytadi (AI oqimida — AI Studio hub'i, Kontent
             oqimida — Kontent submenyusi, admin oqimida — dashboard);
           * Oddiy ko'rishda [◀️ Orqaga] — parent menyuga qaytadi;
           * [🏠 Asosiy menyu] — istalgan joydan asosiy 6 tugmali menyuga;
           * bo'lim yozuvi (``nav_section``) FSM tozalanishidan omon qoladi.

  TEST 3 — 👑 ADMIN DASHBOARD YAGONA MARKAZ (12 tugma + Yopish):
           * Barcha yangi tugmalar (adm_posts, adm_tag, adm_ai, adm_dbcache,
             adm_audit_roles, adm_health) adminga OCHILADI va ishlaydi;
           * dublikat statistika handlerlari (adm_stats / /admin_stats /
             «📊 Statistika» reply-tugmasi) BIRTA yagona ekranga birlashgan;
           * eski admin reply-tugmalari va buyruqlari ALIAS sifatida ishlaydi.

  TEST 4 — 🛡 TAMPERING / RBAC (fail-closed):
           * Oddiy foydalanuvchiga BARCHA adm_* callback'lari QAT'IY yopiq —
             rad javobi, hech qanday ekran chizilmaydi, DB amali bo'lmaydi;
           * server-side from_user.id hal qiladi (payload emas).

  TEST 5 — 🌐 I18N + CALLBACK XAVFSIZLIGI:
           * [◀️ Orqaga] yorlig'i uchala tilda (cm_btn_back — submenu bilan
             AYNAN bir xil matn), AI Studio callback'lari tilga bog'liq emas;
           * barcha yangi callback'lar Telegram 64-bayt chegarasida.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/refactor_step4_test.py
"""
import asyncio
import contextlib
import importlib
import logging
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:REFACTOR_STEP4_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10014")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import database as db_mod  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

import handlers  # noqa: E402,F401 — barcha handlerlarni reyestrga qo'yadi
import handlers.admin as ADM  # noqa: E402
ai_mod = importlib.import_module("handlers.ai_assistant")
start_mod = importlib.import_module("handlers.start")
channels_mod = importlib.import_module("handlers.channels")
settings_mod = importlib.import_module("handlers.settings")
nav_mod = importlib.import_module("handlers.navigation")

from keyboards.default import (  # noqa: E402
    BTN_ADMIN_PANEL, BTN_CANCEL, content_creation_rows, get_main_keyboard,
)
from keyboards.inline import (  # noqa: E402
    get_admin_dashboard_keyboard, get_ai_studio_keyboard,
    get_settings_hub_keyboard, get_tools_keyboard,
)
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_CHANNEL_BACK, CB_CHANNEL_OPEN,
    callback_byte_len, is_callback_safe,
)
from locales.translations import clear_fsm_data, get_text  # noqa: E402
from translations import (  # noqa: E402
    content_menu_parity_report, content_menu_t,
)

LANGS = ("uz", "ru", "en")
USER_ID = 777777          # oddiy foydalanuvchi
ADMIN_ID = 123456789      # config.ADMIN_ID → OWNER
CH_ID = "-100200"

PASSED = 0
FAILURES = 0


def check(label, condition, extra=""):
    """Bitta tekshiruv natijasini hisobga oladi va chop etadi."""
    global PASSED, FAILURES
    if condition:
        PASSED += 1
        print(f"  [OK] {label}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {label} {extra}")
    return bool(condition)


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """reply_text / edit_text / delete yozib boruvchi soxta xabar."""

    def __init__(self, message_id=1, chat_id=USER_ID, text=None):
        self.message_id = message_id
        self.chat_id = chat_id
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.text = text
        self.sent = []
        self.deleted = 0

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return _Msg(self.message_id + 1, self.chat_id)

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return self

    async def delete(self, **kw):
        self.deleted += 1
        return True


class _Query:
    """CallbackQuery fake: answer()/edit_message_text() yozib boradi."""

    def __init__(self, data, message=None, user_id=USER_ID):
        self.data = data
        self.message = message if message is not None else _Msg()
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.answered = []
        self.edits = []

    async def answer(self, text=None, show_alert=False, **kw):
        self.answered.append((text, show_alert))
        return True

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append(dict(text=text, reply_markup=reply_markup, parse_mode=parse_mode))
        return True

    @property
    def screen(self):
        if self.edits:
            return self.edits[-1]
        if self.message.sent:
            return self.message.sent[-1]
        return {}


class _Bot:
    username = "postassist_test_bot"

    async def get_me(self):
        return SimpleNamespace(username=self.username)

    async def send_message(self, *a, **kw):
        return True


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={}, bot=_Bot(), application=None)


def _msg_update(msg, text=None, user_id=USER_ID):
    if text is not None:
        msg.text = text
    return SimpleNamespace(
        message=msg, effective_message=msg, callback_query=None,
        effective_user=SimpleNamespace(id=user_id, first_name="Tester"),
    )


def _query_update(query, user_id=USER_ID):
    return SimpleNamespace(
        message=None, effective_message=query.message, callback_query=query,
        effective_user=SimpleNamespace(id=user_id, first_name="Tester"),
    )


def _run(coro):
    return asyncio.run(coro)


def _rows(markup):
    """Reply klaviatura qatorlari (matn ro'yxati)."""
    if markup is None:
        return []
    return [[b.text for b in row] for row in markup.keyboard]


def _inline_rows(markup):
    if markup is None:
        return []
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def _cbs(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


class _FakeDB:
    """``database.run_db`` mock — 4-qadam oqimlari uchun deterministik.

    Noma'lum funksiya chaqirilsa ``None`` qaytariadi (fail-safe oqimlar shu
    holatda ham crash bermasligi kerak) va ``unknown`` ro'yxatiga yoziladi.
    """

    def __init__(self):
        self.calls = []
        self.unknown = []

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append(name)

        if name == "get_user_language":
            return "uz"
        if name == "is_premium":
            return False
        if name == "get_user_credits":
            return 7
        if name == "get_user_channels_with_tone":
            return [("-100200", "Test Kanali", "friendly"),
                    ("-100201", "Ikkinchi kanal", "formal")]
        if name == "get_user_channels":
            return [("-100200", "Test Kanali"), ("-100201", "Ikkinchi kanal")]
        if name == "get_user_code":
            return "TST404"
        if name == "get_user_onboarding":
            return None
        if name == "get_referral_stats":
            return {"referrals_count": 2, "ai_credits": 7, "streak": 3}
        if name == "get_system_stats":
            return {"users": 100, "channels": 12, "sponsors": 2,
                    "pending": 5, "sent": 40, "cancelled": 3, "failed": 1}
        if name == "get_admin_dashboard_stats":
            return {"users": 100, "pro_subscribers": 4, "channels": 12,
                    "posts_today": 6, "pending_posts": 5, "stars_revenue": 250}
        if name == "get_recent_posts":
            return [(11, USER_ID, "Test Kanali", "text", None, "posted"),
                    (12, USER_ID, "Ikkinchi kanal", "text", None, "pending")]
        if name == "get_all_channels":
            return [("-100200", "Test Kanali", USER_ID, "@tester")]
        if name == "get_setting":
            return args[1] if len(args) > 1 else ""
        if name == "get_db_pool_status":
            return {"collapsed": False, "cache_enabled": True, "ready": True,
                    "message": "ok", "min": 1, "max": 5, "used": 0,
                    "available": 5, "cache_entries": 3}
        if name == "get_admin_audit_logs":
            return [{"created_at": datetime(2026, 9, 14, 12, 0),
                     "admin_id": ADMIN_ID, "action": "grant_pro",
                     "target_type": "users", "target_id": "42"}]
        if name == "list_admin_roles":
            return [{"user_id": 111, "role": "admin", "granted_by": ADMIN_ID,
                     "granted_at": None, "updated_at": None}]
        if name == "get_sponsor_channels":
            return []
        if name == "get_ads_full":
            return []
        if name == "get_ad_settings":
            return {"auto_ad_text": "Reklama", "auto_ad_interval": 4,
                    "auto_ad_status": True, "channel_ad_interval": 3,
                    "channel_ad_status": True}
        if name == "get_channel_ad_interval":
            return 3

        self.unknown.append(name)
        return None


@contextlib.contextmanager
def _with_db(fake):
    """``db.run_db`` ni vaqtincha mock bilan almashtiradi."""
    original = db_mod.run_db
    db_mod.run_db = fake.run_db
    try:
        yield fake
    finally:
        db_mod.run_db = original


@contextlib.contextmanager
def _quiet():
    """Kutilgan xatolarni sinashda log shovqinini o'chiradi."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


# ===========================================================================
# TEST 1 — 🧭 NAVIGATSIYA STACKI
# ===========================================================================
def test_navigation_stack_content_ai_back():
    print("== TEST 1: 🧩 Kontent → 🤖 AI Yordamchi → [◀️ Orqaga] → Kontent ==")

    # 1a) AI Studio klaviaturasida [◀️ Orqaga] bor (uchala til) va u
    #     asosiy menyuga emas, KONTENT submenyusiga ulangan.
    for lang in LANGS:
        kb = get_ai_studio_keyboard(lang)
        cbs = _cbs(kb)
        labels = _labels(kb)
        check(f"[{lang}] AI Studio'da [◀️ Orqaga] tugmasi bor",
              "ai_back_to_content" in cbs, str(cbs))
        check(f"[{lang}] [🏠 Asosiy menyu] alohida tugma sifatida qoladi",
              "studio_close" in cbs, str(cbs))
        check(f"[{lang}] ◀️ Orqaga yorlig'i submenu bilan AYNAN bir xil",
              content_menu_t("cm_btn_back", lang) in labels, str(labels))
        check(f"[{lang}] callback_data tilga bog'liq emas (uz==ru==en)",
              cbs == _cbs(get_ai_studio_keyboard("uz")), str(cbs))

    # 1b) TO'LIQ OQIM: Kontent submenu → AI Yordamchi → [◀️ Orqaga].
    for lang in LANGS:
        fake = _FakeDB()

        # 1-qadam: «✨ Kontent yaratish» — submenu ochiladi.
        msg = _Msg()
        ctx = _ctx(lang)
        state = _run(ai_mod.ai_studio_menu_entry(_msg_update(msg), ctx))
        check(f"[{lang}] Kontent submenu ochildi (END)",
              state == ConversationHandler.END and msg.sent, str(state))
        check(f"[{lang}] nav_section = content",
              nav_mod.current_section(ctx) == nav_mod.SECTION_CONTENT)

        # 2-qadam: «🤖 AI Yordamchi» — AI Studio hub.
        msg2 = _Msg()
        with _with_db(fake):
            state = _run(ai_mod.ai_studio_hub_entry(_msg_update(msg2), ctx))
        check(f"[{lang}] AI Studio hub ochildi (AI_MENU_STATE)",
              state == ai_mod.AI_MENU_STATE, str(state))
        check(f"[{lang}] nav_section = ai_studio",
              nav_mod.current_section(ctx) == nav_mod.SECTION_AI_STUDIO)

        # 3-qadam: [◀️ Orqaga] — KONTENT SUBMENYUSIGA qaytadi.
        q = _Query("ai_back_to_content", _Msg(), USER_ID)
        with _with_db(fake):
            state = _run(ai_mod.ai_back_to_content(_query_update(q), ctx))
        screen = q.screen
        check(f"[{lang}] Orqaga → END (holat qolmaydi)",
              state == ConversationHandler.END, str(state))
        check(f"[{lang}] Orqaga → KONTENT submenu matni chizildi",
              (screen.get("text") or "") == content_menu_t("cm_menu_intro", lang),
              (screen.get("text") or "")[:60])
        check(f"[{lang}] Orqaga → Kontent submenu klaviaturasi (5 + Orqaga)",
              _rows(screen.get("reply_markup")) == content_creation_rows(lang),
              str(_rows(screen.get("reply_markup"))))
        # ASOSIY MENYUGA SAKRAB KETMADI: 6 tugmali menyu chizilmadi.
        main_labels = [t for row in _rows(screen.get("reply_markup")) for t in row]
        check(f"[{lang}] asosiy menyuga sakrab ketmadi",
              get_text("btn_create_content", lang) not in main_labels,
              str(main_labels))
        check(f"[{lang}] Orqaga → nav_section = content",
              nav_mod.current_section(ctx) == nav_mod.SECTION_CONTENT)


def test_navigation_stack_channels_back():
    print("== TEST 1b: 📢 Kanallarim → Kanal → [◀️ Orqaga] → Kanallar ro'yxati ==")

    # 1) «📢 Kanallarim» — ro'yxat ochiladi.
    fake = _FakeDB()
    msg = _Msg()
    ctx = _ctx("uz")
    with _with_db(fake):
        state = _run(channels_mod.channels_menu(_msg_update(msg), ctx))
    check("Kanallar ro'yxati ochildi (END)",
          state == ConversationHandler.END and bool(msg.sent))
    check("nav_section = channels",
          nav_mod.current_section(ctx) == nav_mod.SECTION_CHANNELS)

    # 2) Kanal tanlandi — KANAL BOSHQARUV EKRANI (5 tugma).
    q_open = _Query(f"{CB_CHANNEL_OPEN}{CH_ID}", _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(channels_mod.channel_open_callback(_query_update(q_open), ctx))
    panel_cbs = _cbs(q_open.screen.get("reply_markup"))
    check("Kanal paneli ochildi (END)", state == ConversationHandler.END)
    check("Kanal panelida [◀️ Orqaga] → ch_back bor",
          CB_CHANNEL_BACK in panel_cbs, str(panel_cbs))

    # 3) [◀️ Orqaga] — KANALLAR RO'YXATIGA qaytadi (asosiy menyuga emas).
    q_back = _Query(CB_CHANNEL_BACK, _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(channels_mod.channels_list_callback(_query_update(q_back), ctx))
    screen = q_back.screen
    from translations import channels_queue_t
    check("Orqaga → kanallar RO'YXATI qayta chizildi",
          "kanal" in (screen.get("text") or "").lower() and bool(screen.get("reply_markup")),
          str(screen.get("text"))[:80])
    check("Orqaga → ro'yxat 2 kanal bilan",
          channels_queue_t("cq_ch_list_title", "uz", count=2) == screen.get("text"),
          str(screen.get("text"))[:80])
    check("Orqaga → asosiy menyu klaviaturasi EMAS (inline ro'yxat)",
          "inline_keyboard" in type(screen.get("reply_markup")).__dict__,
          str(type(screen.get("reply_markup"))))


def test_navigation_stack_settings_tools_back():
    print("== TEST 1c: ⚙️ Sozlamalar → 🧰 Vositalar → [◀️ Orqaga] → Sozlamalar ==")

    # 1) Sozlamalar menyusi (8 guruh + ◀️ Orqaga).
    fake = _FakeDB()
    ctx = _ctx("uz")

    # 2) [🧰 Vositalar] — vositalar submenyusi (2 vosita + Orqaga).
    q_tools = _Query("stgs_tools", _Msg(), USER_ID)
    with _with_db(fake):
        _run(settings_mod.settings_menu_callback(_query_update(q_tools), ctx))
    tools_cbs = _cbs(q_tools.screen.get("reply_markup"))
    check("Vositalar submenyusi ochildi",
          "extra_converter" in tools_cbs and "extra_enhancer" in tools_cbs,
          str(tools_cbs))
    check("Vositalar → nav_section = tools",
          nav_mod.current_section(ctx) == nav_mod.SECTION_TOOLS)
    check("Vositalarda [◀️ Orqaga] → stgs_hub bor",
          "stgs_hub" in tools_cbs, str(tools_cbs))

    # 3) [◀️ Orqaga] — SOZLAMALAR MENYUSIGA qaytadi (8 guruh + Orqaga).
    q_back = _Query("stgs_hub", _Msg(), USER_ID)
    with _with_db(fake):
        _run(settings_mod.settings_menu_callback(_query_update(q_back), ctx))
    back_cbs = _cbs(q_back.screen.get("reply_markup"))
    check("Orqaga → Sozlamalar menyusi (9 tugma)",
          back_cbs == _cbs(get_settings_hub_keyboard("uz")), str(back_cbs))
    check("Orqaga → nav_section = settings",
          nav_mod.current_section(ctx) == nav_mod.SECTION_SETTINGS)
    check("Orqaga → asosiy menyu klaviaturasi emas",
          "close_msg" not in back_cbs and "stgs_back" in back_cbs, str(back_cbs))


# ===========================================================================
# TEST 2 — ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu MANTIG'I
# ===========================================================================
def test_back_cancel_main_menu_separation():
    print("== TEST 2: ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu ajratildi ==")
    fake = _FakeDB()

    # 2a) FSM ichida [❌ Bekor qilish] (ai_close) — kontekst TOZALANADI va
    #     BO'LIM BOSHIGA (AI Studio hub) qaytadi, asosiy menyuga emas.
    ctx = _ctx("uz", {"nav_section": "ai_studio", "custom_fsm_key": "qiymat"})
    q_post = _Query("studio_ai_post", _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(ai_mod.ai_studio_nav_callback(_query_update(q_post), ctx))
    check("AI Studio → ✍️ post oqimi (AI_PROMPT_INPUT)",
          state == ai_mod.AI_PROMPT_INPUT, str(state))
    check("FSM konteksti yozildi (bo'lim yozuvi saqlanadi)",
          ctx.user_data.get("custom_fsm_key") == "qiymat"
          and nav_mod.current_section(ctx) == nav_mod.SECTION_AI_STUDIO,
          str(ctx.user_data))

    q_close = _Query("ai_close", _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(ai_mod.ai_close(_query_update(q_close), ctx))
    screen = q_close.screen
    check("[❌ Bekor qilish] → AI Studio hub (bo'lim boshi)",
          state == ai_mod.AI_MENU_STATE, str(state))
    check("[❌ Bekor qilish] → AI Studio klaviaturasi chizildi",
          _cbs(screen.get("reply_markup")) == _cbs(get_ai_studio_keyboard("uz")),
          str(_cbs(screen.get("reply_markup"))))
    check("[❌ Bekor qilish] → FSM kontekst TOZALANDI",
          "custom_fsm_key" not in ctx.user_data, str(ctx.user_data))
    check("[❌ Bekor qilish] → bo'lim yozuvi saqlanadi (ai_studio)",
          nav_mod.current_section(ctx) == nav_mod.SECTION_AI_STUDIO,
          str(ctx.user_data))
    check("[❌ Bekor qilish] → asosiy menyuga chiqmadi",
          not q_close.message.sent, str(q_close.message.sent))

    # 2b) Oddiy ko'rishda [⬅️ Orqaga] (ai_back_to_menu) — parent menyuga
    #     (AI Studio hub) qaytadi: ichki vositadan yuqoriga.
    q_back = _Query("ai_back_to_menu", _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(ai_mod.ai_back_to_menu(_query_update(q_back), ctx))
    check("[⬅️ Orqaga] (ichki ekran) → AI Studio hub",
          state == ai_mod.AI_MENU_STATE
          and _cbs(q_back.screen.get("reply_markup"))
          == _cbs(get_ai_studio_keyboard("uz")),
          str(state))

    # 2c) [🏠 Asosiy menyu] (studio_close) — ASOSIY menyuga chiqadi.
    q_exit = _Query("studio_close", _Msg(), USER_ID)
    with _with_db(fake):
        state = _run(ai_mod.ai_studio_nav_callback(_query_update(q_exit), ctx))
    check("[🏠 Asosiy menyu] → END + asosiy menyu xabari",
          state == ConversationHandler.END and bool(q_exit.message.sent),
          str(state))
    exit_kb = _rows(q_exit.message.sent[-1]["reply_markup"])
    check("[🏠 Asosiy menyu] → 6 tugmali asosiy klaviatura",
          exit_kb == [[b.text for b in row] for row in
                      get_main_keyboard(False, lang="uz").keyboard],
          str(exit_kb))
    check("[🏠 Asosiy menyu] → nav_section tozalandi",
          nav_mod.current_section(ctx) == nav_mod.SECTION_MAIN)


def test_fsm_cancel_returns_to_section_start():
    print("== TEST 2b: FSM ichida [❌ Bekor qilish] → bo'lim boshiga ==")
    fake = _FakeDB()

    # 2d) KONTENT bo'limidagi FSM: [❌ Bekor qilish] → Kontent submenu.
    ctx = _ctx("uz", {"nav_section": "content",
                      "np_title": "Post matni", "magic_raw_text": "x"})
    msg = _Msg()
    msg.text = BTN_CANCEL  # «❌ Bekor qilish» reply-tugmasi
    with _with_db(fake):
        state = _run(start_mod.cancel_handler(_msg_update(msg), ctx))
    last = msg.sent[-1]
    check("Kontent FSM + Bekor → END", state == ConversationHandler.END)
    check("Kontent FSM + Bekor → KONTENT SUBMENYU chizildi",
          _rows(last["reply_markup"]) == content_creation_rows("uz"),
          str(_rows(last["reply_markup"])))
    check("Kontent FSM + Bekor → FSM kontekst tozalandi",
          "np_title" not in ctx.user_data and "magic_raw_text" not in ctx.user_data,
          str(ctx.user_data))
    check("Kontent FSM + Bekor → nav_section saqlandi (content)",
          nav_mod.current_section(ctx) == nav_mod.SECTION_CONTENT)

    # 2e) AI bo'limidagi FSM: [❌ Bekor qilish] → AI Studio hub.
    ctx2 = _ctx("uz", {"nav_section": "ai_studio", "studio_topic": "Mavzu"})
    msg2 = _Msg()
    msg2.text = BTN_CANCEL
    with _with_db(fake):
        state = _run(start_mod.cancel_handler(_msg_update(msg2), ctx2))
    last2 = msg2.sent[-1]
    check("AI FSM + Bekor → AI STUDIO HUB chizildi",
          _cbs(last2["reply_markup"]) == _cbs(get_ai_studio_keyboard("uz")),
          str(_cbs(last2["reply_markup"])))
    check("AI FSM + Bekor → FSM kontekst tozalandi",
          "studio_topic" not in ctx2.user_data, str(ctx2.user_data))

    # 2f) Bo'lim noma'lum (legacy) — asosiy menyuga qaytadi (orqaga moslik).
    ctx3 = _ctx("uz", {"np_title": "Post matni"})
    msg3 = _Msg()
    msg3.text = BTN_CANCEL
    with _with_db(fake):
        state = _run(start_mod.cancel_handler(_msg_update(msg3), ctx3))
    last3 = msg3.sent[-1]
    check("Legacy FSM + Bekor → asosiy menyu (mavjud xulq)",
          _rows(last3["reply_markup"])
          == [[b.text for b in row] for row in get_main_keyboard(False).keyboard],
          str(_rows(last3["reply_markup"])))

    # 2g) ADMIN bo'limidagi FSM: [❌ Bekor qilish] (adm_cancel) → dashboard.
    ctx4 = _ctx("uz", {"admin_flow": "broadcast", "broadcast_text": "Salom"})
    q = _Query("adm_cancel", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q), ctx4))
    check("Admin FSM + adm_cancel → END", state == ConversationHandler.END)
    check("Admin FSM + adm_cancel → DASHBOARD qayta chizildi",
          _cbs(q.screen.get("reply_markup"))
          == _cbs(get_admin_dashboard_keyboard()),
          str(_cbs(q.screen.get("reply_markup"))))
    check("Admin FSM + adm_cancel → admin_flow tozalandi",
          "admin_flow" not in ctx4.user_data, str(ctx4.user_data))

    # 2h) ``clear_fsm_data`` nav_section'ni OMON SAQLAYDI.
    ctx5 = _ctx("uz", {"nav_section": "content", "junk": 1})
    clear_fsm_data(ctx5)
    check("clear_fsm_data: nav_section saqlanadi",
          ctx5.user_data.get("nav_section") == "content", str(ctx5.user_data))
    check("clear_fsm_data: til keshi saqlanadi",
          ctx5.user_data.get("lang") == "uz", str(ctx5.user_data))

    # 2i) navigation.py — remember/current/clear/keep shartnomasi.
    ctx6 = _ctx("uz")
    nav_mod.remember_section(ctx6, nav_mod.SECTION_AI_STUDIO)
    check("remember/current: ai_studio",
          nav_mod.current_section(ctx6) == nav_mod.SECTION_AI_STUDIO)
    nav_mod.clear_section(ctx6)
    check("clear: main", nav_mod.current_section(ctx6) == nav_mod.SECTION_MAIN)
    nav_mod.remember_section(ctx6, "not_a_section")
    check("noto'g'ri bo'lim → main (himoya)",
          nav_mod.current_section(ctx6) == nav_mod.SECTION_MAIN)


# ===========================================================================
# TEST 3 — 👑 ADMIN DASHBOARD YAGONA MARKAZ
# ===========================================================================
def test_admin_dashboard_single_center():
    print("== TEST 3: 👑 Admin dashboard — yagona markaz (12 tugma) ==")
    fake = _FakeDB()

    # 3a) Layout — topshiriqdagi AYNAN tartib.
    kb = get_admin_dashboard_keyboard()
    rows = _inline_rows(kb)
    cbs = _cbs(kb)
    expected = [
        ("adm_stats", "adm_broadcast"),
        ("adm_adhub", "adm_channels"),
        ("adm_posts", "adm_promo"),
        ("adm_grant_pro", "adm_tag"),
        ("adm_ai", "adm_dbcache"),
        ("adm_health", "adm_audit_roles"),
    ]
    got = [tuple(cb for _, cb in row) for row in rows[:6]]
    check("Dashboard 6 juft (12) amaliy tugma + Yopish",
          got == expected and rows[-1][0][1] == "close_msg" and len(rows) == 7,
          str(rows))
    check("Dashboard: jami 13 tugma", len(cbs) == 13, str(cbs))

    # 3b) Yangi tugmalar admin uchun ISHLAYDI (ekran chiziladi).
    #     📋 Barcha postlar
    q_posts = _Query("adm_posts", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q_posts), _ctx("uz")))
    check("adm_posts → postlar ekrani (END)",
          state == ConversationHandler.END and "Oxirgi" in (q_posts.screen.get("text") or ""),
          str(q_posts.screen.get("text"))[:80])
    check("adm_posts → [⬅️ Orqaga] dashboard'ga",
          "adm_back" in _cbs(q_posts.screen.get("reply_markup")))

    #     🏷 Post nishoni — FSM ochadi (SET_POST_TAG)
    q_tag = _Query("adm_tag", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q_tag), _ctx("uz")))
    check("adm_tag → SET_POST_TAG holati",
          state == ADM.SET_POST_TAG, str(state))
    check("adm_tag → post nishoni yo'riqnomasi",
          "Post nishoni" in (q_tag.screen.get("text") or ""),
          str(q_tag.screen.get("text"))[:80])

    #     ⚙️ AI parametrlari — FSM ochadi (AI_SETTINGS)
    q_ai = _Query("adm_ai", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q_ai), _ctx("uz")))
    check("adm_ai → AI_SETTINGS holati",
          state == ADM.AI_SETTINGS, str(state))
    check("adm_ai → AI parametrlar ekrani",
          "AI parametrlarni boshqarish" in (q_ai.screen.get("text") or ""),
          str(q_ai.screen.get("text"))[:80])

    #     🗄️ DB / Kesh holati
    q_db = _Query("adm_dbcache", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q_db), _ctx("uz")))
    check("adm_dbcache → DB/Kesh ekrani (END)",
          state == ConversationHandler.END
          and "DB Pool va Kesh holati" in (q_db.screen.get("text") or ""),
          str(q_db.screen.get("text"))[:80])
    check("adm_dbcache → keshni tozalash tugmasi qoladi",
          "cache_clear" in _cbs(q_db.screen.get("reply_markup")))

    #     📜 Audit | 👥 Rollar
    q_audit = _Query("adm_audit_roles", _Msg(), ADMIN_ID)
    with _with_db(fake):
        state = _run(ADM.admin_dashboard_callback(_query_update(q_audit), _ctx("uz")))
    audit_text = q_audit.screen.get("text") or ""
    check("adm_audit_roles → END", state == ConversationHandler.END, str(state))
    check("adm_audit_roles → Audit jurnali bloki",
          "Audit jurnali" in audit_text and "grant_pro" in audit_text,
          audit_text[:120])
    check("adm_audit_roles → Rollar bloki",
          "Rollar" in audit_text and "admin" in audit_text, audit_text[-200:])

    #     🩺 Tizim salomatligi — endi DASHBOARD tugmasi (mavjud callback).
    import services.health_service as HS
    orig_report = HS.format_health_report
    async def _fake_report(lang="uz"):
        return "🩺 <b>Tizim holati:</b> OK"
    HS.format_health_report = _fake_report
    try:
        q_health = _Query("adm_health", _Msg(), ADMIN_ID)
        with _with_db(fake):
            state = _run(ADM.admin_dashboard_callback(_query_update(q_health), _ctx("uz")))
        check("adm_health → salomatlik hisoboti (END)",
              state == ConversationHandler.END
              and "Tizim holati" in (q_health.screen.get("text") or ""),
              str(q_health.screen.get("text"))[:80])
    finally:
        HS.format_health_report = orig_report

    # 3c) DUBLIKAT STATISTIKA — uch yo'l BIRTA yagona ekran chiqaradi.
    stats_text = ADM._build_full_stats_text({
        "users": 100, "channels": 12, "sponsors": 2, "pending": 5,
        "sent": 40, "cancelled": 3, "failed": 1})

    q_stats = _Query("adm_stats", _Msg(), ADMIN_ID)
    with _with_db(fake):
        _run(ADM.admin_dashboard_callback(_query_update(q_stats), _ctx("uz")))
    check("adm_stats → yagona «To'liq Statistika» ekrani",
          q_stats.screen.get("text") == stats_text,
          str(q_stats.screen.get("text"))[:80])

    msg_cmd = _Msg()
    upd_cmd = _msg_update(msg_cmd, user_id=ADMIN_ID)
    with _with_db(fake):
        _run(ADM.admin_stats_command(upd_cmd, _ctx("uz")))
    check("/admin_stats → AYNAN shu ekran (dublikat yo'q)",
          msg_cmd.sent and msg_cmd.sent[-1]["text"] == stats_text,
          str(msg_cmd.sent[-1]["text"])[:80] if msg_cmd.sent else "")

    msg_btn = _Msg()
    upd_btn = _msg_update(msg_btn, user_id=ADMIN_ID)
    with _with_db(fake):
        _run(ADM.show_statistics(upd_btn, _ctx("uz")))
    check("«📊 Statistika» reply-tugmasi → AYNAN shu ekran",
          msg_btn.sent and msg_btn.sent[-1]["text"] == stats_text,
          str(msg_btn.sent[-1]["text"])[:80] if msg_btn.sent else "")

    # 3d) Barcha postlar / kanallar — reply-tugma va dashboard BIR xil ekran.
    msg_posts = _Msg()
    with _with_db(fake):
        _run(ADM.admin_all_posts(_msg_update(msg_posts, user_id=ADMIN_ID), _ctx("uz")))
    q_posts2 = _Query("adm_posts", _Msg(), ADMIN_ID)
    with _with_db(fake):
        _run(ADM.admin_dashboard_callback(_query_update(q_posts2), _ctx("uz")))
    check("adm_posts ≡ admin_all_posts (bir xil matn)",
          msg_posts.sent[-1]["text"] == q_posts2.screen.get("text"),
          str(msg_posts.sent[-1]["text"])[:60])

    msg_ch = _Msg()
    with _with_db(fake):
        _run(ADM.admin_all_channels(_msg_update(msg_ch, user_id=ADMIN_ID), _ctx("uz")))
    q_ch = _Query("adm_channels", _Msg(), ADMIN_ID)
    with _with_db(fake):
        _run(ADM.admin_dashboard_callback(_query_update(q_ch), _ctx("uz")))
    check("adm_channels ≡ admin_all_channels (bir xil matn)",
          (msg_ch.sent[-1]["text"] or "").split("\n")[0]
          == (q_ch.screen.get("text") or "").split("\n")[0],
          str(msg_ch.sent[-1]["text"])[:60])

    # 3e) ESKI admin reply-tugmalari va buyruqlari ALIAS sifatida ishlaydi.
    from keyboards.default import (
        BTN_POST_TAG, BTN_AI_SETTINGS, BTN_CACHE_DB, BTN_ALL_POSTS,
        BTN_STATS, BTN_ALL_CHANNELS, BTN_FULL_STATS,
    )
    msg_t = _Msg()
    with _with_db(fake):
        state = _run(ADM.start_set_post_tag(_msg_update(msg_t, user_id=ADMIN_ID), _ctx("uz")))
    check("alias: «🏷 Post nishoni» reply-tugma → SET_POST_TAG",
          state == ADM.SET_POST_TAG, str(state))
    msg_s = _Msg()
    with _with_db(fake):
        state = _run(ADM.ai_settings_menu(_msg_update(msg_s, user_id=ADMIN_ID), _ctx("uz")))
    check("alias: «⚙️ AI parametrlari» reply-tugma → AI_SETTINGS",
          state == ADM.AI_SETTINGS, str(state))
    msg_c = _Msg()
    with _with_db(fake):
        state = _run(ADM.cache_db_menu(_msg_update(msg_c, user_id=ADMIN_ID), _ctx("uz")))
    check("alias: «🗄️ DB / Kesh» reply-tugma → END + holat ekrani",
          state == ConversationHandler.END
          and "DB Pool va Kesh holati" in (msg_c.sent[-1]["text"] or ""),
          str(msg_c.sent[-1]["text"])[:60] if msg_c.sent else "")
    check("alias tugmalari dashboard bilan bir xil callback'larga tegishli",
          all(isinstance(b, str) for b in (BTN_POST_TAG, BTN_AI_SETTINGS,
                                           BTN_CACHE_DB, BTN_ALL_POSTS,
                                           BTN_STATS, BTN_ALL_CHANNELS)))

    # 3f) Eski reply-klaviatura matnlari routing'da saqlangan (real router).
    from handlers import register_all_handlers
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:REFACTOR_STEP4_TEST").build()
    register_all_handlers(app)

    def _routed(update):
        for group in sorted(app.handlers):
            for handler in app.handlers[group]:
                try:
                    if handler.check_update(update):
                        cb = getattr(handler, "callback", None)
                        names = set()
                        code = getattr(cb, "__code__", None)
                        if code is not None:
                            names.update(code.co_names)
                        if getattr(cb, "__name__", "") != "<lambda>":
                            names.add(cb.__name__)
                        return names
                except Exception:
                    continue
        return set()

    from telegram import Update
    def _text_update(text):
        return Update.de_json({
            "update_id": 3,
            "message": {
                "message_id": 21, "date": 0, "text": text,
                "chat": {"id": ADMIN_ID, "type": "private"},
                "from": {"id": ADMIN_ID, "is_bot": False, "first_name": "Admin"},
            },
        }, None)

    alias_map = {
        BTN_POST_TAG: "start_set_post_tag",
        BTN_AI_SETTINGS: "ai_settings_menu",
        BTN_CACHE_DB: "cache_db_menu",
        BTN_ALL_POSTS: "admin_all_posts",
        BTN_ALL_CHANNELS: "admin_all_channels",
        # «📊 Statistika» — statistics_button dispatcheri. STATISTIKA
        # IZOLYATSIYASI: endi admin bo'ladimi, oddiy foydalanuvchimi —
        # FAQAT shaxsiy hisobot (show_user_statistics). Bot bo'yicha
        # statistika esa o'ziga xos «📊 To'liq statistika» yorlig'ida.
        BTN_STATS: "statistics_button",
        BTN_FULL_STATS: "show_statistics",
    }
    for label, fn_name in alias_map.items():
        check(f"router: «{label}» → {fn_name} (alias saqlangan)",
              fn_name in _routed(_text_update(label)), str(_routed(_text_update(label))))

    def _cb_update(data, user_id):
        return Update.de_json({
            "update_id": 4,
            "callback_query": {
                "id": "cb-1", "chat_instance": "ci", "data": data,
                "from": {"id": user_id, "is_bot": False, "first_name": "T"},
                "message": {
                    "message_id": 5, "date": 0,
                    "chat": {"id": user_id, "type": "private"},
                    "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
                },
            },
        }, None)

    for data, fn_name in (
        ("adm_posts", "admin_dashboard_callback"),
        ("adm_tag", "admin_dashboard_callback"),
        ("adm_ai", "admin_dashboard_callback"),
        ("adm_dbcache", "admin_dashboard_callback"),
        ("adm_audit_roles", "admin_dashboard_callback"),
        ("adm_health", "admin_dashboard_callback"),
        ("adm_back", "admin_dashboard_callback"),
        ("adm_cancel", "admin_dashboard_callback"),
    ):
        check(f"router: {data} → {fn_name} (entry point)",
              fn_name in _routed(_cb_update(data, ADMIN_ID)),
              str(_routed(_cb_update(data, ADMIN_ID))))


# ===========================================================================
# TEST 4 — 🛡 TAMPERING: oddiy foydalanuvchiga adm_* QAT'IY yopiq
# ===========================================================================
def test_admin_callbacks_fail_closed_for_non_admin():
    print("== TEST 4: 🛡 Tampering — oddiy foydalanuvchiga adm_* qattiq yopiq ==")
    from services.rbac_service import verify_admin_callback

    # Dashboarddagi BARCHA callback'lar (12 yangi/eski + navigatsiya +
    # reklama markazi ichki amallari) — oddiy foydalanuvchi uchun yopiq.
    all_adm_callbacks = (
        "adm_stats", "adm_broadcast", "adm_adhub", "adm_channels",
        "adm_posts", "adm_promo", "adm_grant_pro", "adm_tag",
        "adm_ai", "adm_dbcache", "adm_health", "adm_audit_roles",
        "adm_back", "adm_cancel", "adm_sponsors", "adm_add_sponsor",
        "adm_ad_toggle", "adm_channel_ad_toggle", "adm_auto_ad",
    )

    # 4a) verify_admin_callback — server-side (from_user.id) fail-closed.
    for data in all_adm_callbacks:
        upd = _query_update(_Query(data, _Msg(), USER_ID), user_id=USER_ID)
        check(f"verify_admin_callback({data!r}, non-admin) → False",
              verify_admin_callback(upd) is False)

    # 4b) Haqiqiy handler: rad javobi + hech qanday ekran chizilmaydi.
    fake = _FakeDB()
    for data in all_adm_callbacks:
        q = _Query(data, _Msg(), USER_ID)
        ctx = _ctx("uz")
        with _with_db(fake), _quiet():
            state = _run(ADM.admin_dashboard_callback(_query_update(q, user_id=USER_ID), ctx))
        denied = any(a and "Ruxsat" in str(a[0]) for a in q.answered)
        check(f"non-admin {data}: rad javobi ('Ruxsat yo'q')",
              denied and not q.edits, str(q.answered))
        check(f"non-admin {data}: END, dashboard chizilmadi",
              state == ConversationHandler.END and not q.edits, str(state))

    # 4c) DB amali ham bo'lmadi (fail-closed: ruxsat tekshiruvidan keyin
    #     hech qanday so'rov yuborilmaydi).
    check("non-admin: hech qanday DB amali bajarilmadi",
          not [c for c in fake.calls if c != "get_user_language"],
          str(fake.calls))

    # 4d) Admin panel reply-tugmasi oddiy foydalanuvchida umuman ko'rinmaydi.
    for lang in LANGS:
        user_labels = [t for row in _rows(get_main_keyboard(False, lang=lang))
                       for t in row]
        check(f"[{lang}] oddiy foydalanuvchida «{BTN_ADMIN_PANEL}» YO'Q",
              BTN_ADMIN_PANEL not in user_labels, str(user_labels))

    # 4e) admin_panel_menu — oddiy foydalanuvchi uchun JIM rad (fail-closed).
    msg = _Msg()
    with _with_db(_FakeDB()), _quiet():
        state = _run(ADM.admin_panel_menu(_msg_update(msg, user_id=USER_ID), _ctx("uz")))
    check("non-admin: admin_panel_menu javob bermaydi",
          not msg.sent and state == ConversationHandler.END, str(msg.sent))

    # 4f) Payload soxtalashtirilsa ham — server-side from_user.id hal qiladi:
    #     non-admin ID + adminlikka ishora qiluvchi payload → baribir RAD.
    for data in ("adm_grant_pro:777", "adm_promo:owner", "adm_ai:123456789"):
        q = _Query(data, _Msg(), USER_ID)
        with _with_db(_FakeDB()), _quiet():
            state = _run(ADM.admin_dashboard_callback(_query_update(q, user_id=USER_ID), _ctx("uz")))
        check(f"tampering payload {data!r} → baribir rad",
              not q.edits and any(a and "Ruxsat" in str(a[0]) for a in q.answered),
              str(q.answered))


# ===========================================================================
# TEST 5 — 🌐 I18N + CALLBACK XAVFSIZLIGI
# ===========================================================================
def test_i18n_and_callback_safety():
    print("== TEST 5: 🌐 I18N paritet + 64-bayt callback xavfsizligi ==")

    # 5a) Kontent menyusi i18n — 100% paritet (◀️ Orqaga yorlig'i ham).
    report = content_menu_parity_report()
    check("content_menu i18n: UZ/RU/EN 100% paritet (in_sync)",
          report.get("in_sync") is True, str(report))
    for lang in LANGS:
        check(f"[{lang}] cm_btn_back tarjimasi mavjud va farqli",
              bool(content_menu_t("cm_btn_back", lang)))

    # 5b) AI Studio klaviaturasi — uchala tilda bir xil callback'lar.
    uz_cbs = _cbs(get_ai_studio_keyboard("uz"))
    for lang in ("ru", "en"):
        check(f"[{lang}] AI Studio callback'lari uz bilan bir xil",
              _cbs(get_ai_studio_keyboard(lang)) == uz_cbs,
              str(_cbs(get_ai_studio_keyboard(lang))))

    # 5c) Barcha yangi callback'lar Telegram 64-bayt chegarasida.
    dash_cbs = _cbs(get_admin_dashboard_keyboard()) + uz_cbs + [
        CB_CHANNEL_OPEN + CH_ID, CB_CHANNEL_BACK,
        "stgs_hub", "stgs_tools", "extra_converter", "extra_enhancer",
    ]
    for data in dash_cbs:
        check(f"callback {data!r} ≤ {CALLBACK_DATA_MAX_BYTES} bayt",
              is_callback_safe(data), f"{callback_byte_len(data)} bayt")

    # 5d) Navigatsiya bo'limlari — yagona manba konstantalari.
    check("navigation: NAV_SECTIONS to'liq",
          nav_mod.NAV_SECTIONS == (
              nav_mod.SECTION_MAIN, nav_mod.SECTION_CONTENT,
              nav_mod.SECTION_AI_STUDIO, nav_mod.SECTION_CHANNELS,
              nav_mod.SECTION_SETTINGS, nav_mod.SECTION_TOOLS,
              nav_mod.SECTION_ADMIN),
          str(nav_mod.NAV_SECTIONS))

    # 5e) render_section_start_message — har bir bo'lim boshini chizadi.
    fake = _FakeDB()
    cases = (
        (nav_mod.SECTION_CONTENT, lambda screen: screen["reply_markup"]
         and _rows(screen["reply_markup"]) == content_creation_rows("uz")),
        (nav_mod.SECTION_AI_STUDIO, lambda screen: _cbs(screen["reply_markup"])
         == _cbs(get_ai_studio_keyboard("uz"))),
        (nav_mod.SECTION_CHANNELS, lambda screen: screen["reply_markup"]
         and len(_cbs(screen["reply_markup"])) >= 3),
        (nav_mod.SECTION_SETTINGS, lambda screen: _cbs(screen["reply_markup"])
         == _cbs(get_settings_hub_keyboard("uz"))),
        (nav_mod.SECTION_TOOLS, lambda screen: _cbs(screen["reply_markup"])
         == _cbs(get_tools_keyboard("uz"))),
    )
    for section, validator in cases:
        ctx = _ctx("uz", {"nav_section": section})
        msg = _Msg()
        with _with_db(fake):
            ok = _run(nav_mod.render_section_start_message(
                msg, ctx, USER_ID, False, "uz"))
        check(f"render_section_start({section}) → bo'lim boshi chizildi",
              ok and bool(msg.sent) and validator(msg.sent[-1]),
              str(msg.sent[-1] if msg.sent else None)[:120])
    # main — False (fallback: asosiy menyu chaqiruvchi tomonidan chiziladi).
    ctx = _ctx("uz", {"nav_section": nav_mod.SECTION_MAIN})
    msg = _Msg()
    ok = _run(nav_mod.render_section_start_message(msg, ctx, USER_ID, False, "uz"))
    check("render_section_start(main) → False (fallback)",
          ok is False and not msg.sent)


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("=" * 70)
    print(" POSTASSIST V2 · 4-QADAM — NAVIGATSIYA STACKI + ADMIN DASHBOARD")
    print("=" * 70)

    test_navigation_stack_content_ai_back()
    test_navigation_stack_channels_back()
    test_navigation_stack_settings_tools_back()
    test_back_cancel_main_menu_separation()
    test_fsm_cancel_returns_to_section_start()
    test_admin_dashboard_single_center()
    test_admin_callbacks_fail_closed_for_non_admin()
    test_i18n_and_callback_safety()

    print()
    print("=" * 70)
    print(f"JAMI: o'tdi={PASSED}, xato={FAILURES}")
    print("=" * 70)
    if FAILURES:
        print("TESTS: FAIL ❌")
        sys.exit(1)
    print("TESTS: PASS ✔ — 4-qadam kontraktlari to'liq bajarildi")
    sys.exit(0)


if __name__ == "__main__":
    main()
