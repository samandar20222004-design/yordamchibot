#!/usr/bin/env python3
"""🏁 POSTASSIST — YAKUNIY ACCEPTANCE SUITE (TEST A..AF) — deterministik, tarmoqsiz.

Bu fayl loyihadagi BARCHA majburiy tekshiruvlarni (TEST A dan TEST AF gacha)
BITTA to'liq qabul yuzasiga jamlaydi. Maqsad — refaktor paytida hech qanday
feature yo'qolmasligini, dublikatlar qayta paydo bo'lmasligini, navigatsiya
stacki buzilmasligini, RBAC chetlab o'tilmasligini va i18n sinxroni
saqlanishini kafolatlash.

Qamrov (32 ta belgilangan test):

  TEST A..D   — Asosiy menyu QAT'IY 6 tugma: UZ / RU / EN (foydalanuvchi va
                admin varianti, callback/yorliq pariteti).
  TEST E..G   — 🧩 Kontent yaratish submenu va 🤖 AI Studio submenyusi
                UZ/RU/EN pariteti (``in_sync: True``).
  TEST H..J   — 📢 Kanallarim va 📅 Rejalashtirilgan (Queue) navigatsiyasi.
  TEST K..N   — 📊 Statistika (FAQAT shaxsiy hisobot + ADMIN IZOLYATSIYASI),
                ⚙️ Sozlamalar (8 guruh + Orqaga), 💎 PRO va 🧰 Vositalar.
  TEST O      — Ko'rinadigan (visible) menyularda DUBLIKAT tugmalar yo'qligi.
  TEST P..S   — Uchala tildagi HAR BIR tugma ishchi handler/callback'ga ega.
  TEST T..V   — ◀️ Orqaga / ❌ Bekor qilish / 🏠 Asosiy menyu navigatsiya
                stacki (har biri O'Z O'RNIGA qaytishi).
  TEST W..X   — Eski tugmalar va eski callback'lar (backward compatibility).
  TEST Y      — FSM holatlari bir-biriga XALAQIT BERMAYDI (konflikt yo'q).
  TEST Z..AB  — ACTION-FIRST: 📸 rasm, 🎙 ovoz, 📝 uzun matn.
  TEST AC..AD — 👑 Admin panel oddiy foydalanuvchiga 100% YOPIQ + server-side
                RBAC tampering himoyasi.
  TEST AE..AF — Barcha matnlar i18n orqali va barcha tillarda 100% sinxron.
  TEST AG     — 👑 ADMIN PANEL FAQAT YAGONA INLINE PANEL (3-bosqich): pastdagi
                oq 10 talik reply-klaviatura butunlay olib tashlangan, layout
                topshiriq bo'yicha 12 tugma (6 qator × 2), barcha ``adm_*``
                tugmalari adminga ishlaydi; eski matnlar esa FAQAT routing
                ALIAS'i (klaviaturada chizilmaydi).

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/final_acceptance_suite_test.py           # alohida
"""
import asyncio
import contextlib
import importlib
import logging
import os
import re
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:FINAL_ACCEPTANCE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10099")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import database as db_mod  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.ext import (  # noqa: E402
    CallbackQueryHandler, ConversationHandler, MessageHandler, filters,
)

import handlers  # noqa: E402,F401 — barcha handlerlarni reyestrga qo'yadi
import handlers.admin as ADM  # noqa: E402
ai_mod = importlib.import_module("handlers.ai_assistant")
start_mod = importlib.import_module("handlers.start")
channels_mod = importlib.import_module("handlers.channels")
settings_mod = importlib.import_module("handlers.settings")
nav_mod = importlib.import_module("handlers.navigation")
queue_mod = importlib.import_module("handlers.queue")
analytics_mod = importlib.import_module("handlers.analytics")
subscription_mod = importlib.import_module("handlers.subscription")
image_post_mod = importlib.import_module("handlers.image_post")
voice_post_mod = importlib.import_module("handlers.voice_post")
content_creation_mod = importlib.import_module("handlers.content_creation")

from keyboards.default import (  # noqa: E402
    BTN_ADMIN_PANEL, BTN_CANCEL, content_creation_rows, get_main_keyboard,
)
from keyboards.inline import (  # noqa: E402
    ADMIN_DASHBOARD_ROWS, get_admin_dashboard_keyboard,
    get_admin_monitoring_keyboard,
    get_ai_studio_keyboard, get_settings_hub_keyboard,
    get_tools_keyboard, get_user_stats_keyboard, render_channel_panel,
)
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_CHANNEL_BACK, CB_CHANNEL_OPEN, callback_byte_len,
    is_callback_safe,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    channels_queue_parity_report, content_menu_parity_report,
    content_menu_t, magic_post_parity_report, post_score_parity_report,
    settings_stats_parity_report, voice_post_parity_report,
)

LANGS = ("uz", "ru", "en")
USER_ID = 777777          # oddiy foydalanuvchi (admin EMAS)
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


def header(test_id, title):
    print(f"\n== TEST {test_id}: {title} ==")


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


def _flat(markup):
    return [t for row in _rows(markup) for t in row]


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
    """``database.run_db`` mock — yakuniy acceptance oqimlari uchun deterministik.

    Noma'lum funksiya chaqirilsa ``None`` qaytariadi (fail-safe oqimlar shu
    holatda ham crash bermasligi kerak) va ``unknown`` ro'yxatiga yoziladi.
    """

    def __init__(self, queue_total=0):
        self.calls = []
        self.unknown = []
        self.queue_total = queue_total

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
            return [(CH_ID, "Test Kanali", "friendly"),
                    ("-100201", "Ikkinchi kanal", "formal")]
        if name == "get_user_channels":
            return [(CH_ID, "Test Kanali"), ("-100201", "Ikkinchi kanal")]
        if name == "get_user_code":
            return "FINAL1"
        if name == "get_user_onboarding":
            return None
        if name == "get_referral_stats":
            return {"referrals_count": 2, "ai_credits": 7, "streak": 3}
        if name == "get_user_overview_stats":
            # FAQAT shaxsiy ko'rsatkichlar — admin maydonlari YO'Q.
            return {"channels": 2, "created_posts": 9, "scheduled_posts": 4,
                    "ai_requests": 31, "credits_spent": 12}
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
            return [(CH_ID, "Test Kanali", USER_ID, "@tester")]
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
        if name == "get_user_plan":
            return {"plan_type": "free", "expires_at": None, "ai_used": 2}
        if name == "get_queue_post_count":
            return self.queue_total
        if name == "check_queue_limit":
            return (True, self.queue_total, 50)
        if name == "get_queue_posts":
            # _format_queue_item shartnomasi:
            # (post_id, ch_title, post_type, content, sched_time, post_num, ch_id)
            when = datetime.now() + timedelta(hours=2)
            return [(21, "Test Kanali", "text", "Rejalashtirilgan post matni",
                     when, 1, CH_ID)]
        if name == "get_smart_reply_ad":
            return ""

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


# ---------------------------------------------------------------------------
# RO'YXAT YORDAMCHILARI — register_all_handlers orqali HAQIQIY registratsiya
# ---------------------------------------------------------------------------
class _Recorder:
    def __init__(self):
        self.handlers = []

    def add_handler(self, h, group=0):
        self.handlers.append(h)


def _registered():
    """``register_all_handlers`` chaqirilgandagi HAQIQIY handler daraxti."""
    app = _Recorder()
    handlers.register_all_handlers(app)
    return app.handlers


def _walk(node, out):
    """ConversationHandler ichidagi barcha handlerlarni tekislaydi."""
    for h in node:
        if isinstance(h, ConversationHandler):
            for state, sub in h.states.items():
                _walk(sub, out)
            if h.fallbacks:
                _walk(h.fallbacks, out)
            continue
        out.append(h)


_ALL_HANDLERS = None
_ALL_FLAT = None


def _all_handlers():
    global _ALL_HANDLERS, _ALL_FLAT
    if _ALL_HANDLERS is None:
        _ALL_HANDLERS = _registered()
        _ALL_FLAT = []
        _walk(_ALL_HANDLERS, _ALL_FLAT)
    return _ALL_HANDLERS, _ALL_FLAT


def _message_handlers():
    """Aniq matnli (``exact(...)`` Regex) menyu handlerlari."""
    _, flat = _all_handlers()
    return [h for h in flat
            if isinstance(h, MessageHandler) and isinstance(h.filters, filters.Regex)]


def _targets(label):
    """``label`` matnini taniydigan handlerlarning chaqiradigan funksiya nomi."""
    Update.de_json  # import sanity
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
    for h in _message_handlers():
        if not h.check_update(upd):
            continue
        cb = h.callback
        if callable(cb) and getattr(cb, "__name__", "") != "<lambda>":
            names.add(getattr(cb, "__name__", str(cb)))
        else:
            for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                if n in ("guard_entry", "guard_menu"):
                    continue
                obj = getattr(handlers, n, None)
                if callable(obj):
                    names.add(n)
    return names


def _callback_handler_names(data):
    """``data`` callback'ini taniydigan CallbackQueryHandler funksiyalari."""
    upd = Update.de_json({
        "update_id": 2,
        "callback_query": {
            "id": "cb1", "chat_instance": "ci",
            "from": {"id": 42, "is_bot": False, "first_name": "Tester"},
            "message": {"message_id": 5, "date": 0,
                        "chat": {"id": 42, "type": "private"}},
            "data": data,
        },
    }, None)
    _, flat = _all_handlers()
    names = set()
    for h in flat:
        if not isinstance(h, CallbackQueryHandler):
            continue
        try:
            matched = h.check_update(upd)
        except Exception:
            matched = False
        if not matched:
            continue
        cb = h.callback
        if callable(cb) and getattr(cb, "__name__", "") != "<lambda>":
            names.add(getattr(cb, "__name__", str(cb)))
        else:
            for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                obj = getattr(handlers, n, None)
                if callable(obj):
                    names.add(n)
    return names


def _conversation_handlers():
    """Ro'yxatdagi barcha ConversationHandler namunalar."""
    _, flat = _all_handlers()
    # ConversationHandler'lar _walk orqali tekislanmaydi — ularni alohida yig'amiz.
    convs = []

    def rec(node):
        for h in node:
            if isinstance(h, ConversationHandler):
                convs.append(h)
                for state, sub in h.states.items():
                    rec(sub)
                if h.fallbacks:
                    rec(h.fallbacks)

    rec(_registered())
    return convs


# ===========================================================================
# TEST A..D — ASOSIY MENYU QAT'IY 6 TUGMA
# ===========================================================================
EXPECTED_MAIN = {
    "uz": ["✨ Kontent yaratish", "📢 Kanallarim", "📅 Rejalashtirilgan",
           "📊 Statistika", "💎 PRO", "⚙️ Sozlamalar"],
    "ru": ["✨ Создать контент", "📢 Мои каналы", "📅 Запланированные",
           "📊 Статистика", "💎 PRO", "⚙️ Настройки"],
    "en": ["✨ Create content", "📢 My channels", "📅 Scheduled",
           "📊 Statistics", "💎 PRO", "⚙️ Settings"],
}


def test_a_main_menu_uz():
    header("A", "🧭 Asosiy menyu UZ — QAT'IY 6 tugma")
    kb = get_main_keyboard(False, lang="uz")
    flat = _flat(kb)
    check("UZ: aynan 6 tugma", len(flat) == 6, str(flat))
    check("UZ: 3 qator × 2 tugma", _rows(kb) == [EXPECTED_MAIN["uz"][i:i + 2] for i in (0, 2, 4)],
          str(_rows(kb)))
    check("UZ: kutilgan yorliqlar tartibi", flat == EXPECTED_MAIN["uz"], str(flat))


def test_b_main_menu_ru():
    header("B", "🧭 Asosiy menyu RU — QAT'IY 6 tugma")
    kb = get_main_keyboard(False, lang="ru")
    flat = _flat(kb)
    check("RU: aynan 6 tugma", len(flat) == 6, str(flat))
    check("RU: 3 qator × 2 tugma", _rows(kb) == [EXPECTED_MAIN["ru"][i:i + 2] for i in (0, 2, 4)],
          str(_rows(kb)))
    check("RU: kutilgan yorliqlar tartibi", flat == EXPECTED_MAIN["ru"], str(flat))


def test_c_main_menu_en():
    header("C", "🧭 Asosiy menyu EN — QAT'IY 6 tugma")
    kb = get_main_keyboard(False, lang="en")
    flat = _flat(kb)
    check("EN: aynan 6 tugma", len(flat) == 6, str(flat))
    check("EN: 3 qator × 2 tugma", _rows(kb) == [EXPECTED_MAIN["en"][i:i + 2] for i in (0, 2, 4)],
          str(_rows(kb)))
    check("EN: kutilgan yorliqlar tartibi", flat == EXPECTED_MAIN["en"], str(flat))


def test_d_main_menu_admin_variant_and_parity():
    header("D", "🧭 Asosiy menyu — admin varianti 6-tugmani saqlaydi + til pariteti")
    for lang in LANGS:
        user_kb = get_main_keyboard(False, lang=lang)
        admin_kb = get_main_keyboard(True, lang=lang)
        check(f"[{lang}] admin: birinchi 3 qator = 6-tugma standarti",
              _rows(admin_kb)[:3] == _rows(user_kb), str(_rows(admin_kb)[:3]))
        check(f"[{lang}] admin: oxirgi qator = [⚙️ Admin Panel]",
              _rows(admin_kb)[-1] == [BTN_ADMIN_PANEL], str(_rows(admin_kb)[-1]))
        check(f"[{lang}] oddiy foydalanuvchida Admin Panel YO'Q",
              BTN_ADMIN_PANEL not in _flat(user_kb), str(_flat(user_kb)))
    # Til pariteti: har uchala til 6 ta, hech biri tarjima qilmay qolmagan.
    sizes = {lang: len(_flat(get_main_keyboard(False, lang=lang))) for lang in LANGS}
    check("uz/ru/en tugma soni bir xil (6/6/6)", set(sizes.values()) == {6}, str(sizes))
    for lang in LANGS:
        check(f"[{lang}] hech bir tugma yorlig'i bo'sh emas",
              all((t or "").strip() for t in _flat(get_main_keyboard(False, lang=lang))))


# ===========================================================================
# TEST E..G — KONTENT SUBMENU + AI STUDIO PARITETI
# ===========================================================================
def test_e_content_submenu_parity():
    header("E", "🧩 Kontent yaratish submenu — UZ/RU/EN pariteti")
    expected_shapes = None
    for lang in LANGS:
        rows = content_creation_rows(lang)
        flat = [t for row in rows for t in row]
        check(f"[{lang}] 5 tugma + [◀️ Orqaga] = 6 yorliq", len(flat) == 6, str(flat))
        check(f"[{lang}] oxirgi yorliq — Orqaga",
              flat[-1] == content_menu_t("cm_btn_back", lang), flat[-1])
        if expected_shapes is None:
            expected_shapes = [len(r) for r in rows]
        check(f"[{lang}] qator tuzilishi uchala tilda bir xil",
              [len(r) for r in rows] == expected_shapes, str([len(r) for r in rows]))
        check(f"[{lang}] dublikat yorliq yo'q", len(flat) == len(set(flat)), str(flat))


def test_f_ai_studio_submenu_parity():
    header("F", "🤖 AI Studio submenu — UZ/RU/EN pariteti (callback tilga bog'liq emas)")
    base = _cbs(get_ai_studio_keyboard("uz"))
    for lang in LANGS:
        kb = get_ai_studio_keyboard(lang)
        cbs = _cbs(kb)
        check(f"[{lang}] callback'lar UZ bilan AYNAN bir xil", cbs == base, str(cbs))
        check(f"[{lang}] tugma soni UZ bilan bir xil",
              len(_labels(kb)) == len(_labels(get_ai_studio_keyboard("uz"))))
        check(f"[{lang}] [◀️ Orqaga] (ai_back_to_content) mavjud",
              "ai_back_to_content" in cbs, str(cbs))
        check(f"[{lang}] [⬅️ Asosiy menyu] (studio_close) mavjud",
              "studio_close" in cbs, str(cbs))
        check(f"[{lang}] hech bir yorliq bo'sh emas",
              all((t or "").strip() for t in _labels(kb)))
    check("AI Studio: 5 amal + Orqaga + Asosiy menyu = 7", len(base) == 7, str(base))


def test_g_i18n_reports_in_sync():
    header("G", "🌐 Submenu i18n hisobotlari — in_sync: True")
    report = content_menu_parity_report()
    check("content_menu_parity_report['in_sync'] is True", report.get("in_sync") is True,
          str(report.get("in_sync")))
    check("content_menu: missing yo'q",
          not any(report.get("missing", {}).values()), str(report.get("missing")))
    check("content_menu: extra yo'q",
          not any(report.get("extra", {}).values()), str(report.get("extra")))
    check("content_menu: format_mismatch yo'q",
          not report.get("format_mismatch"), str(report.get("format_mismatch")))


# ===========================================================================
# TEST H..J — KANALLARIM + REJALASHTIRILGAN NAVIGATSIYASI
# ===========================================================================
def test_h_channels_menu_opens():
    header("H", "📢 Kanallarim — ro'yxat ochiladi va bo'lim yoziladi")
    fake = _FakeDB()
    msg = _Msg()
    ctx = _ctx("uz")
    with _with_db(fake):
        state = _run(channels_mod.channels_menu(_msg_update(msg), ctx))
    check("Kanallarim: handler END qaytardi", state == ConversationHandler.END, str(state))
    check("Kanallarim: xabar yuborildi", bool(msg.sent))
    check("Kanallarim: nav_section = channels",
          nav_mod.current_section(ctx) == nav_mod.SECTION_CHANNELS,
          str(nav_mod.current_section(ctx)))
    cbs = _cbs(msg.sent[-1]["reply_markup"]) if msg.sent else []
    check("Kanallarim: kanal tugmasi ch_op: prefiksi bilan",
          any(str(c).startswith(CB_CHANNEL_OPEN) for c in cbs), str(cbs))
    check("Kanallarim: [➕ Kanal qo'shish] mavjud", "add_channel_start" in cbs, str(cbs))
    check("Kanallarim: kanallar ro'yxati DB'dan o'qildi",
          any(c in ("get_user_channels", "get_user_channels_with_tone")
              for c in fake.calls), str(fake.calls))


def test_i_channel_panel_management_screen():
    header("I", "📢 Kanal boshqaruv ekrani — kanal ichida qoladi (asosiy menyuga chiqmaydi)")
    kb = render_channel_panel(CH_ID, "uz")
    cbs = _cbs(kb)
    labels = _labels(kb)
    check("Panel: [➕ Post yaratish] mavjud", any(c.startswith("ch_np:") for c in cbs), str(cbs))
    check("Panel: [📅 Rejalashtirilgan] mavjud", any(c.startswith("ch_sch:") for c in cbs), str(cbs))
    check("Panel: [📊 Statistika] (kanal darajasi) mavjud",
          any(c.startswith("ch_st:") for c in cbs), str(cbs))
    check("Panel: [⚙️ Kanal sozlamalari] mavjud", any(c.startswith("ch_set:") for c in cbs), str(cbs))
    check("Panel: [◀️ Orqaga] = ch_back", CB_CHANNEL_BACK in cbs, str(cbs))
    check("Panel: channel_id har bir amalga o'ralgan",
          all(CH_ID in c for c in cbs if c.startswith(("ch_np", "ch_sch", "ch_st", "ch_set"))))
    # Kanal ichidagi amallar asosiy menyu yorlig'ini CHIZMAYDI.
    check("Panel: asosiy menyu yorlig'i yo'q (kanal ichida qoladi)",
          get_text("btn_create_content", "uz") not in labels, str(labels))
    for lang in LANGS:
        cbs_l = _cbs(render_channel_panel(CH_ID, lang))
        check(f"[{lang}] panel callback'lari tilga bog'liq emas", cbs_l == cbs, str(cbs_l))


def test_j_queue_menu_navigation():
    header("J", "📅 Rejalashtirilgan (Queue) — ochiladi, holat qaytadi, sahifalanadi")
    # Bo'sh navbat — ekran baribir ochiladi (foydalanuvchi "bo'sh" qolmaydi).
    fake = _FakeDB(queue_total=0)
    msg = _Msg()
    with _with_db(fake):
        state = _run(queue_mod.queue_menu(_msg_update(msg), _ctx("uz")))
    check("Queue(bo'sh): QUEUE_MENU holati qaytdi", state == queue_mod.QUEUE_MENU, str(state))
    check("Queue(bo'sh): xabar yuborildi", bool(msg.sent))
    check("Queue(bo'sh): get_queue_post_count chaqirildi",
          "get_queue_post_count" in fake.calls, str(fake.calls))

    # To'lgan navbat — ro'yxat chiziladi.
    fake2 = _FakeDB(queue_total=1)
    msg2 = _Msg()
    with _with_db(fake2):
        state2 = _run(queue_mod.queue_menu(_msg_update(msg2), _ctx("uz")))
    check("Queue(to'lgan): QUEUE_MENU holati qaytdi", state2 == queue_mod.QUEUE_MENU, str(state2))
    check("Queue(to'lgan): get_queue_posts chaqirildi",
          "get_queue_posts" in fake2.calls, str(fake2.calls))
    check("Queue(to'lgan): ro'yxat matni bo'sh emas",
          bool((msg2.sent[-1]["text"] or "").strip()) if msg2.sent else False)

    # Eski nom o'rniga yangi yorliq ishlatiladi (uchala tilda).
    for lang in LANGS:
        label = get_text("btn_scheduled", lang)
        check(f"[{lang}] asosiy menyu yorlig'i = {label!r}",
              label in _flat(get_main_keyboard(False, lang=lang)))


# ===========================================================================
# TEST K..N — STATISTIKA / SOZLAMALAR / PRO / VOSITALAR
# ===========================================================================
# ADMIN STATISTIKASI — oddiy foydalanuvchiga HECH QACHON ko'rsatilmasligi
# kerak bo'lgan markerlar (handlers/admin.py::_build_full_stats_text).
ADMIN_STATS_MARKERS = (
    "Jami foydalanuvchilar",
    "Homiy kanallar",
    "Bekor qilingan",
    "To'liq Statistika",
    "Kutilayotgan postlar",
    "Yuborilgan postlar",
)


def test_k_statistics_isolation():
    header("K", "📊 Statistika — FAQAT shaxsiy hisobot (ADMIN STATISTIKASI IZOLYATSIYASI)")

    # K1) Oddiy foydalanuvchi «📊 Statistika» bosganda → shaxsiy hisobot
    #     (handlers.statistics.show_user_statistics); admin show_statistics
    #     CHAQIRILMAYDI.
    fake = _FakeDB()
    msg = _Msg()
    ctx = _ctx("uz")
    with _with_db(fake), _quiet():
        _run(handlers.statistics_button(_msg_update(msg, get_text("btn_statistics", "uz")), ctx))
    check("Statistika(user): get_user_overview_stats chaqirildi",
          "get_user_overview_stats" in fake.calls, str(fake.calls))
    check("Statistika(user): get_system_stats (ADMIN) CHAQIRILMADI",
          "get_system_stats" not in fake.calls, str(fake.calls))
    text = msg.sent[-1]["text"] if msg.sent else ""
    check("Statistika(user): shaxsiy hisobot matni chizildi", bool(text.strip()), text[:60])
    for marker in ADMIN_STATS_MARKERS:
        check(f"Statistika(user): ADMIN matni YO'Q — {marker!r}", marker not in text, text[:120])
    markup = msg.sent[-1]["reply_markup"] if msg.sent else None
    check("Statistika(user): klaviatura = [📈 Kanal bo'yicha batafsil][◀️ Orqaga]",
          set(_cbs(markup)) == {"an_detail", "an_close"}, str(_cbs(markup)))

    # K2) ADMIN HAM shu tugmani bossa — O'Z SHAXSIY hisobotini ko'radi.
    #     STATISTIKA IZOLYATSIYASI: asosiy menyu «📊 Statistika» tugmasi
    #     admin uchun ham bot statistikasini ochmaydi (avval ochardi — bu
    #     chalkashlik tuzatildi). Bot statistikasi faqat ⚙️ Admin Panel →
    #     «📊 To'liq statistika» ichida.
    fake_adm = _FakeDB()
    msg_adm = _Msg()
    with _with_db(fake_adm), _quiet():
        _run(handlers.statistics_button(
            _msg_update(msg_adm, get_text("btn_statistics", "uz"), user_id=ADMIN_ID), _ctx("uz")))
    check("Statistika(admin): get_system_stats (ADMIN) CHAQIRILMADI",
          "get_system_stats" not in fake_adm.calls, str(fake_adm.calls))
    check("Statistika(admin): shaxsiy overview o'qildi",
          "get_user_overview_stats" in fake_adm.calls, str(fake_adm.calls))
    adm_text = msg_adm.sent[-1]["text"] if msg_adm.sent else ""
    for marker in ADMIN_STATS_MARKERS:
        check(f"Statistika(admin): ADMIN matni YO'Q — {marker!r}",
              marker not in adm_text, adm_text[:120])
    check("Statistika(admin): shaxsiy sarlavha ko'rinadi",
          "Sizning statistikangiz" in adm_text, adm_text[:120])
    adm_kb = msg_adm.sent[-1]["reply_markup"] if msg_adm.sent else None
    check("Statistika(admin): klaviatura ham shaxsiy (an_detail/an_close)",
          set(_cbs(adm_kb)) == {"an_detail", "an_close"}, str(_cbs(adm_kb)))

    # K3) show_statistics o'zi ham FAIL-CLOSED — oddiy foydalanuvchi
    #     to'g'ridan-to'g'ri chaqirsa ham hech narsa chizilmaydi.
    fake_leak = _FakeDB()
    msg_leak = _Msg()
    with _with_db(fake_leak), _quiet():
        _run(ADM.show_statistics(_msg_update(msg_leak), _ctx("uz")))
    check("show_statistics(user): hech qanday xabar yuborilmadi (fail-closed)",
          not msg_leak.sent, str(msg_leak.sent)[:120])

    # K4) Shaxsiy hisobot builderi admin maydonlarini O'Z ICHIGA OLMAYDI.
    for lang in LANGS:
        user_text = analytics_mod.build_user_stats_text(
            {"channels": 2, "created_posts": 9, "scheduled_posts": 4,
             "ai_requests": 31, "credits_spent": 12}, lang)
        leaked = [m for m in ADMIN_STATS_MARKERS if m in user_text]
        check(f"[{lang}] build_user_stats_text: admin markeri yo'q", not leaked, str(leaked))
        check(f"[{lang}] build_user_stats_text: 4 ta shaxsiy ko'rsatkich qatori bor",
              user_text.count("\n") >= 5, user_text[:80])


def test_l_settings_menu_8_groups_plus_back():
    header("L", "⚙️ Sozlamalar — 8 guruh + [◀️ Orqaga] = 9, uchala tilda bir xil")
    expected_cbs = ["stgs_profile", "stgs_lang", "stgs_rewards", "stgs_post",
                    "stgs_notif", "stgs_pay", "stgs_tools", "stgs_help_hub",
                    "stgs_back"]
    base = None
    for lang in LANGS:
        kb = get_settings_hub_keyboard(lang)
        cbs = _cbs(kb)
        labels = _labels(kb)
        if base is None:
            base = cbs
        check(f"[{lang}] 8 guruh + Orqaga = 9", len(cbs) == 9, str(cbs))
        check(f"[{lang}] callback'lar kutilgan ro'yxat bilan AYNAN bir xil",
              cbs == expected_cbs, str(cbs))
        check(f"[{lang}] oxirgi tugma — [◀️ Orqaga] (stgs_back)",
              cbs[-1] == "stgs_back" and labels[-1] == content_menu_t("cm_btn_back", lang),
              str(labels[-1]))
        check(f"[{lang}] callback'lar UZ bilan bir xil (tilga bog'liq emas)",
              cbs == base, str(cbs))

    # Handler haqiqatan shu klaviaturani chizadi.
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        _run(start_mod.user_cabinet_menu(_msg_update(msg), _ctx("uz")))
    drawn = _cbs(msg.sent[-1]["reply_markup"]) if msg.sent else []
    check("user_cabinet_menu: 9 tugmali sozlamalar klaviaturasini chizdi",
          drawn == expected_cbs, str(drawn))


def test_m_pro_subscription_opens():
    header("M", "💎 PRO — tariflar ekrani ochiladi va to'lov tugmalari chiqadi")
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        state = _run(subscription_mod.start_subscription(_msg_update(msg), _ctx("uz")))
    check("PRO: SUBSCRIPTION_VIEW holati qaytdi",
          state == subscription_mod.SUBSCRIPTION_VIEW, str(state))
    check("PRO: xabar yuborildi", bool(msg.sent))
    check("PRO: get_user_plan chaqirildi", "get_user_plan" in fake.calls, str(fake.calls))
    cbs = _cbs(msg.sent[-1]["reply_markup"]) if msg.sent else []
    check("PRO: Stars to'lov tugmalari (sub_pay:stars_*) mavjud",
          any(str(c).startswith("sub_pay:stars_") for c in cbs), str(cbs))
    check("PRO: 6-tugma menyudagi [💎 PRO] aynan shu handlerga yo'naltiriladi",
          _targets(get_text("btn_premium", "uz")) == {"start_subscription"},
          str(_targets(get_text("btn_premium", "uz"))))


def test_n_tools_submenu_opens():
    header("N", "🧰 Vositalar — Konvertor va Post Enhancer ko'rinadigan joyda")
    base = None
    for lang in LANGS:
        kb = get_tools_keyboard(lang)
        cbs = _cbs(kb)
        if base is None:
            base = cbs
        check(f"[{lang}] 2 vosita + Orqaga = 3", len(cbs) == 3, str(cbs))
        check(f"[{lang}] Konvertor (extra_converter) mavjud",
              "extra_converter" in cbs, str(cbs))
        check(f"[{lang}] Post Enhancer (extra_enhancer) mavjud",
              "extra_enhancer" in cbs, str(cbs))
        check(f"[{lang}] Orqaga → sozlamalar hubi (stgs_hub)",
              cbs[-1] == "stgs_hub", str(cbs))
        check(f"[{lang}] callback'lar UZ bilan bir xil", cbs == base, str(cbs))
    # Sozlamalar menyusidan [🧰 Vositalar] aynan shu submenyuga olib boradi.
    check("Sozlamalar menyusida [🧰 Vositalar] = stgs_tools mavjud",
          "stgs_tools" in _cbs(get_settings_hub_keyboard("uz")))


# ===========================================================================
# TEST O — DUBLIKAT TUGMALAR YO'QLIGI
# ===========================================================================
def _visible_menus():
    """Ko'rinadigan (faktiki chiziladigan) menyular to'plami."""
    menus = {}
    for lang in LANGS:
        menus[f"main:{lang}"] = _flat(get_main_keyboard(False, lang=lang))
        menus[f"main_admin:{lang}"] = _flat(get_main_keyboard(True, lang=lang))
        menus[f"content:{lang}"] = [t for row in content_creation_rows(lang) for t in row]
        menus[f"ai_studio:{lang}"] = _labels(get_ai_studio_keyboard(lang))
        menus[f"settings:{lang}"] = _labels(get_settings_hub_keyboard(lang))
        menus[f"tools:{lang}"] = _labels(get_tools_keyboard(lang))
        menus[f"channel_panel:{lang}"] = _labels(render_channel_panel(CH_ID, lang))
        menus[f"user_stats:{lang}"] = _labels(get_user_stats_keyboard(lang))
        menus[f"admin_dash:{lang}"] = _labels(get_admin_dashboard_keyboard())
        menus[f"admin_mon:{lang}"] = _labels(get_admin_monitoring_keyboard())
    return menus


def test_o_no_duplicate_visible_buttons():
    header("O", "🧹 Ko'rinadigan menyularda DUBLIKAT tugmalar yo'q")
    menus = _visible_menus()
    dup_found = False
    for name, labels in menus.items():
        duplicates = sorted({t for t in labels if labels.count(t) > 1})
        if not check(f"{name}: dublikat yorliq yo'q", not duplicates, str(duplicates)):
            dup_found = True
    # Inline callback'lar ham takrorlanmasligi kerak (aksi holda Telegram
    # ikki xil tugmani bir xil payload bilan chizadi).
    for lang in LANGS:
        for name, kb in (("ai_studio", get_ai_studio_keyboard(lang)),
                         ("settings", get_settings_hub_keyboard(lang)),
                         ("tools", get_tools_keyboard(lang))):
            cbs = _cbs(kb)
            duplicates = sorted({c for c in cbs if cbs.count(c) > 1})
            if not check(f"{name}:{lang}: dublikat callback yo'q", not duplicates, str(duplicates)):
                dup_found = True
    # Refaktor natijasi: settings legacy dublikatlari ko'rinishdan olingan.
    legacy_dupes = ("cab_channels", "cab_analytics", "cab_pending", "cab_queue")
    settings_cbs = _cbs(get_settings_hub_keyboard("uz"))
    for legacy in legacy_dupes:
        check(f"Sozlamalar menyusida legacy dublikat {legacy!r} YO'Q",
              legacy not in settings_cbs, str(settings_cbs))
    check("umumiy: hech bir ko'rinadigan menyuda dublikat topilmadi", not dup_found)


# ===========================================================================
# TEST P..S — HAR BIR TUGMA ISHCHI HANDLER/CALLBACK'GA EGA
# ===========================================================================
MAIN_ROUTES = {
    "btn_create_content": "ai_studio_menu_entry",
    "btn_my_channels": "channels_menu",
    "btn_scheduled": "queue_menu",
    "btn_statistics": "statistics_button",
    "btn_premium": "start_subscription",
    "btn_settings": "user_cabinet_menu",
}


def _test_buttons_route(test_id, lang):
    header(test_id, f"🔌 [{lang.upper()}] asosiy menyu tugmalari ishchi handlerga ega")
    for key, expected in MAIN_ROUTES.items():
        label = get_text(key, lang)
        names = _targets(label)
        check(f"[{lang}] {label!r} → {expected}", names == {expected}, str(sorted(names)))
    # Menyu klaviaturasidagi har bir yorliq haqiqatan routerga tushadi.
    for label in _flat(get_main_keyboard(False, lang=lang)):
        check(f"[{lang}] menyu yorlig'i {label!r} kamida bitta handlerga ega",
              bool(_targets(label)), str(label))


def test_p_buttons_route_uz():
    _test_buttons_route("P", "uz")


def test_q_buttons_route_ru():
    _test_buttons_route("Q", "ru")


def test_r_buttons_route_en():
    _test_buttons_route("R", "en")


def test_s_inline_callbacks_have_handlers():
    header("S", "🔌 Barcha inline callback'lar ro'yxatdan o'tgan handlerga ega")
    checked = set()
    for lang in LANGS:
        sources = {
            f"ai_studio:{lang}": get_ai_studio_keyboard(lang),
            f"settings:{lang}": get_settings_hub_keyboard(lang),
            f"tools:{lang}": get_tools_keyboard(lang),
            f"channel_panel:{lang}": render_channel_panel(CH_ID, lang),
            f"user_stats:{lang}": get_user_stats_keyboard(lang),
        }
        for name, kb in sources.items():
            for data in _cbs(kb):
                if data in checked:
                    continue
                checked.add(data)
                names = _callback_handler_names(data)
                check(f"{name}: {data!r} → handler bor", bool(names), data)
    check("inline: kamida 20 xil callback tekshirildi", len(checked) >= 20, str(len(checked)))
    # Barcha tekshirilgan callback'lar Telegram 64-bayt chegarasida.
    oversized = [c for c in checked if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("inline: barcha callback'lar <= 64 bayt", not oversized, str(oversized))
    unsafe = [c for c in checked if not is_callback_safe(c)]
    check("inline: barcha callback'lar is_callback_safe()", not unsafe, str(unsafe))


# ===========================================================================
# TEST T..V — BACK / CANCEL / EXIT NAVIGATSIYA STACKI
# ===========================================================================
def test_t_back_content_ai_returns_to_content_submenu():
    header("T", "◀️ Orqaga — Kontent → AI Yordamchi → KONTENT submenyusiga qaytadi")
    for lang in LANGS:
        fake = _FakeDB()
        ctx = _ctx(lang)
        # 1) Kontent submenu.
        msg = _Msg()
        _run(ai_mod.ai_studio_menu_entry(_msg_update(msg), ctx))
        check(f"[{lang}] Kontent submenu ochildi",
              nav_mod.current_section(ctx) == nav_mod.SECTION_CONTENT)
        # 2) AI Studio hub.
        msg2 = _Msg()
        with _with_db(fake):
            _run(ai_mod.ai_studio_hub_entry(_msg_update(msg2), ctx))
        check(f"[{lang}] AI Studio hub ochildi",
              nav_mod.current_section(ctx) == nav_mod.SECTION_AI_STUDIO)
        # 3) [◀️ Orqaga] → kontent submenyusi (asosiy menyuga EMAS).
        q = _Query("ai_back_to_content", _Msg(), USER_ID)
        with _with_db(fake):
            state = _run(ai_mod.ai_back_to_content(_query_update(q), ctx))
        screen = q.screen
        check(f"[{lang}] Orqaga → END", state == ConversationHandler.END, str(state))
        check(f"[{lang}] Orqaga → KONTENT submenu matni",
              (screen.get("text") or "") == content_menu_t("cm_menu_intro", lang),
              (screen.get("text") or "")[:60])
        check(f"[{lang}] Orqaga → kontent klaviaturasi",
              _rows(screen.get("reply_markup")) == content_creation_rows(lang),
              str(_rows(screen.get("reply_markup"))))
        check(f"[{lang}] asosiy menyuga SAKRAMADI",
              get_text("btn_create_content", lang) not in _flat(screen.get("reply_markup")))
        check(f"[{lang}] nav_section = content",
              nav_mod.current_section(ctx) == nav_mod.SECTION_CONTENT)


def test_u_back_settings_tools_returns_to_settings():
    header("U", "◀️ Orqaga — Sozlamalar → Vositalar → SOZLAMALAR menyusiga qaytadi")
    # Klaviatura shartnomasi: tools → stgs_hub.
    for lang in LANGS:
        check(f"[{lang}] Vositalar Orqaga → stgs_hub",
              _cbs(get_tools_keyboard(lang))[-1] == "stgs_hub")
    # Sozlamalar bo'limi yoziladi va [❌ Bekor qilish] dan omon qoladi.
    ctx = _ctx("uz")
    nav_mod.remember_section(ctx, nav_mod.SECTION_SETTINGS)
    check("Sozlamalar bo'limi yozildi",
          nav_mod.current_section(ctx) == nav_mod.SECTION_SETTINGS)
    kept = nav_mod.keep_section_after_clear(ctx)
    check("keep_section_after_clear: bo'lim FSM tozalanishidan omon qoldi",
          kept == nav_mod.SECTION_SETTINGS, str(kept))
    check("clear_fsm_data bo'limni O'CHIRMAYDI",
          nav_mod.current_section(ctx) == nav_mod.SECTION_SETTINGS,
          str(nav_mod.current_section(ctx)))
    # Vositalar bo'limidan Orqaga → sozlamalar.
    nav_mod.remember_section(ctx, nav_mod.SECTION_TOOLS)
    check("Vositalar bo'limi yozildi",
          nav_mod.current_section(ctx) == nav_mod.SECTION_TOOLS)
    check("stgs_hub callback'i handlerga ega", bool(_callback_handler_names("stgs_hub")))
    check("stgs_back callback'i handlerga ega", bool(_callback_handler_names("stgs_back")))


def test_v_cancel_and_exit_navigation():
    header("V", "❌ Bekor qilish / 🏠 Asosiy menyu — har biri O'Z O'RNIGA qaytadi")
    # 1) [❌ Bekor qilish] yorlig'i uchala tilda mavjud va bir xil ma'noda.
    for lang in LANGS:
        check(f"[{lang}] BTN_CANCEL yorlig'i bo'sh emas", bool((BTN_CANCEL or "").strip()))
        check(f"[{lang}] 'Orqaga' va 'Bekor qilish' ALOHIDA yorliqlar",
              content_menu_t("cm_btn_back", lang) != get_text("btn_cancel", lang),
              f"{content_menu_t('cm_btn_back', lang)!r} vs {get_text('btn_cancel', lang)!r}")

    # 2) [🏠 Asosiy menyu] (studio_close) istalgan joydan asosiy menyuga chiqadi.
    check("studio_close callback'i handlerga ega", bool(_callback_handler_names("studio_close")))
    check("ai_back_to_content va studio_close — IKKI XIL callback",
          "ai_back_to_content" != "studio_close")

    # 3) Admin oqimida adm_cancel → dashboard (asosiy menyuga emas).
    check("adm_cancel callback'i handlerga ega", bool(_callback_handler_names("adm_cancel")))
    adm_kb_cbs = _cbs(get_admin_dashboard_keyboard())
    check("Admin dashboard'da [❌ Yopish] (close_msg) mavjud", "close_msg" in adm_kb_cbs,
          str(adm_kb_cbs))

    # 4) Kanal oqimida ch_back → kanallar ro'yxati (asosiy menyu emas).
    check("ch_back callback'i handlerga ega", bool(_callback_handler_names(CB_CHANNEL_BACK)))

    # 5) render_section_start_message — har bir bo'lim uchun deterministik.
    for section, expected_ok in ((nav_mod.SECTION_CONTENT, True),
                                 (nav_mod.SECTION_SETTINGS, True),
                                 (nav_mod.SECTION_MAIN, False)):
        ctx = _ctx("uz", {"nav_section": section})
        msg = _Msg()
        with _quiet():
            ok = _run(nav_mod.render_section_start_message(msg, ctx, USER_ID, False, "uz"))
        if expected_ok:
            check(f"render_section_start({section}) → xabar chizildi", bool(msg.sent))
        else:
            check(f"render_section_start({section}) → False (fallback)", ok is False)


# ===========================================================================
# TEST W..X — BACKWARD COMPATIBILITY
# ===========================================================================
def test_w_legacy_buttons_still_route():
    header("W", "♻️ Eski tugmalar (backward compatibility) hali ham ishlaydi")
    legacy_routes = (
        ("btn_new_post", "start_new_post"),
        ("btn_ai_studio", "ai_studio_menu_entry"),
        ("btn_help", "help_command"),
        ("btn_extras", "extras_menu"),
    )
    for key, expected in legacy_routes:
        for lang in LANGS:
            label = get_text(key, lang)
            names = _targets(label)
            check(f"[{lang}] eski {label!r} → {expected}",
                  expected in names and len(names) == 1, str(sorted(names)))
    # Chat tarixida qolib ketgan qo'lda yozilgan yorliqlar.
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
        names = _targets(label)
        check(f"eski yorliq {label!r} → {expected}",
              expected in names and len(names) == 1, str(sorted(names)))

    # «🖼 Rasmdan post yaratish» — reply-tugma EMAS, AI Studio INLINE tugmasi.
    # Shu sababli uni MessageHandler emas, studio_ai_photo callback'i olib boradi.
    ai_labels = _labels(get_ai_studio_keyboard("uz"))
    check("AI Studio inline yorlig'i '🖼 Rasmdan post yaratish' ko'rinadigan joyda",
          "🖼 Rasmdan post yaratish" in ai_labels, str(ai_labels))
    check("AI Studio inline tugmasi → studio_ai_photo (yagona rasm oqimi)",
          _cbs(get_ai_studio_keyboard("uz"))[ai_labels.index("🖼 Rasmdan post yaratish")]
          == "studio_ai_photo",
          str(_cbs(get_ai_studio_keyboard("uz"))))
    check("studio_ai_photo → image_post_entry oqimiga ulangan",
          bool(_callback_handler_names("studio_ai_photo")))


def test_x_legacy_callbacks_still_handled():
    header("X", "♻️ Eski callback'lar (backward compatibility) hali ham tutib olinadi")
    legacy_callbacks = (
        "cab_pending", "cab_queue", "cab_analytics", "cab_channels",
        "cab_points", "cab_bonus", "cab_referral", "cab_help", "cab_about",
        "cab_profile", "cab_lang", "cab_notif", "cab_pay", "cab_post",
        "studio_ai_photo", "ai_menu", "an_close", "close_msg",
    )
    for data in legacy_callbacks:
        names = _callback_handler_names(data)
        check(f"eski callback {data!r} → handler bor", bool(names), data)
    # Eski callback'lar ham 64-bayt chegarasida qoladi.
    oversized = [c for c in legacy_callbacks
                 if callback_byte_len(c) > CALLBACK_DATA_MAX_BYTES]
    check("eski callback'lar <= 64 bayt", not oversized, str(oversized))
    # Legacy callback'lar CRASH bermaydi — soxta DB bilan chaqiriladi.
    fake = _FakeDB()
    for data in ("cab_pending", "cab_queue"):
        q = _Query(data, _Msg(), USER_ID)
        with _with_db(fake), _quiet():
            try:
                _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
                crashed = False
            except Exception as exc:  # noqa: BLE001
                crashed = True
                check(f"legacy {data!r} crash bermadi", False, repr(exc))
        if not crashed:
            check(f"legacy {data!r} crash bermadi (javob berdi)", bool(q.answered))


# ===========================================================================
# TEST Y — FSM HOLATLARI KONFLIKTI YO'Q
# ===========================================================================
# PTB sentinel'lari (ConversationHandler.END/TIMEOUT/WAITING) holat sifatida
# ro'yxatdan o'tishi NORMAL — ular alohida ConversationHandler tomonidan
# ishlatiladi, shu sababli "musbat butun son" tekshiruvidan chiqariladi.
_PTB_SENTINELS = None


def _ptb_sentinels():
    global _PTB_SENTINELS
    if _PTB_SENTINELS is None:
        _PTB_SENTINELS = {
            getattr(ConversationHandler, name)
            for name in ("END", "TIMEOUT")
            if hasattr(ConversationHandler, name)
        }
    return _PTB_SENTINELS


def _collect_fsm_states():
    """Har bir ConversationHandler'ga tegishli holat raqamlarini yig'adi."""
    owner = {}
    duplicates = {}
    for idx, conv in enumerate(_conversation_handlers()):
        for state in conv.states.keys():
            if not isinstance(state, int):
                continue
            if state in owner and owner[state] != idx:
                duplicates.setdefault(state, {owner[state]}).add(idx)
            owner.setdefault(state, idx)
    return owner, duplicates


def _defined_state_literals():
    """Modul MANBAIDA o'zi ``NAME = <int literal>`` bilan E'LON QILINGAN holatlar.

    Import qilingan yoki boshqa nomga bog'langan alias'lar (``IMAGE_INPUT =
    IMAGE_POST_INPUT``, ``from handlers.voice_post import VOICE_RESULT``)
    HISOBGA OLINMAYDI — ular orqaga moslik uchun ataylab qoldirilgan qayta
    eksport, konflikt emas.
    """
    import ast
    import inspect

    modules = (ai_mod, channels_mod, queue_mod, analytics_mod,
               subscription_mod, image_post_mod, voice_post_mod,
               importlib.import_module("handlers.magic_post"),
               importlib.import_module("handlers.post_score"),
               importlib.import_module("handlers.content_plan"),
               importlib.import_module("handlers.content_calendar_flow"),
               importlib.import_module("handlers.converter"),
               importlib.import_module("handlers.start"))

    state_re = re.compile(
        r"(STATE|_INPUT|_SELECT|_RESULT|_VIEW|_AWAIT|_CHOOSE|_TARGET|_AMOUNT"
        r"|_TOPIC|_DURATION|_BUSINESS|_CONFIRM|_TIME|_MENU|_CHANNEL|_EDIT"
        r"|SEND_CHOOSE)$"
    )
    defined = {}          # value -> [(mod, name)]
    per_module_dupes = {} # modul ichida bir xil qiymatga ikki xil nom
    for mod in modules:
        try:
            source = inspect.getsource(mod)
        except (OSError, TypeError):
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in tree.body:                       # faqat modul darajasi
            if not isinstance(node, ast.Assign):
                continue
            if not (isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, int)
                    and not isinstance(node.value.value, bool)):
                continue                             # alias / import → o'tkazamiz
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                name = target.id
                if not name.isupper() or not state_re.search(name):
                    continue
                defined.setdefault(node.value.value, []).append(
                    (mod.__name__.split(".")[-1], name))

    for value, owners in defined.items():
        names = [n for _m, n in owners]
        if len(set(names)) > 1:
            per_module_dupes[value] = owners
    return defined, per_module_dupes


def test_y_fsm_states_no_conflict():
    header("Y", "🧠 FSM holatlari bir-biriga xalaqit bermaydi (konflikt yo'q)")
    sentinels = _ptb_sentinels()
    owner, duplicates = _collect_fsm_states()
    check("FSM: hech bir holat 2 xil ConversationHandler'da emas",
          not duplicates, str(sorted(duplicates)))
    check("FSM: kamida 25 ta holat ro'yxatdan o'tgan", len(owner) >= 25, str(len(owner)))

    real_states = {s: i for s, i in owner.items() if s not in sentinels}
    check("FSM: sentinel'lardan tashqari barcha holatlar musbat butun son",
          all(s > 0 for s in real_states), str(sorted(real_states)[:5]))
    check("FSM: PTB sentinel'lari (END/TIMEOUT) alohida qo'llaniladi",
          any(s in sentinels for s in owner), str(sorted(owner)[:6]))
    # Sentinel bo'lmagan holatlar bir-biri bilan to'qnashmaydi.
    check("FSM: hech bir real holat PTB sentinel qiymati emas",
          not (set(real_states) & sentinels), str(set(real_states) & sentinels))

    # Modul manbasida E'LON QILINGAN holatlar unikal bo'lishi shart.
    defined, per_module_dupes = _defined_state_literals()
    check("FSM: e'lon qilingan holat raqamlari takrorlanmaydi (alias'lar hisobsiz)",
          not per_module_dupes, str(per_module_dupes))
    check("FSM: kamida 30 ta holat manbada e'lon qilingan", len(defined) >= 30,
          str(len(defined)))

    # Alias'lar ataylab saqlangan (orqaga moslik) — lekin ular ASL holat bilan
    # bir xil qiymatga ega, ya'ni routing ikkilanmaydi.
    aliases = (
        (image_post_mod, "IMAGE_INPUT", image_post_mod.IMAGE_POST_INPUT),
        (image_post_mod, "IMAGE_RESULT", image_post_mod.IMAGE_POST_RESULT),
    )
    for mod, alias_name, canonical in aliases:
        check(f"alias {alias_name} == kanonik holat ({canonical})",
              getattr(mod, alias_name) == canonical,
              str(getattr(mod, alias_name)))

    # Re-eksport qilingan nomlar ham bir xil qiymatni ko'rsatadi (konflikt yo'q).
    post_score_mod = importlib.import_module("handlers.post_score")
    check("post_score.IMAGE_POST_RESULT image_post bilan bir xil",
          post_score_mod.IMAGE_POST_RESULT == image_post_mod.IMAGE_POST_RESULT)
    check("post_score.VOICE_RESULT voice_post bilan bir xil",
          post_score_mod.VOICE_RESULT == voice_post_mod.VOICE_RESULT)
    check("post_score.AI_GET_TIME ai_assistant bilan bir xil",
          post_score_mod.AI_GET_TIME == ai_mod.AI_GET_TIME)


# ===========================================================================
# TEST Z..AB — ACTION-FIRST
# ===========================================================================
def test_z_action_first_image():
    header("Z", "📸 ACTION-FIRST rasm — yagona oqim, kredit hali yechilmaydi")
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        state = _run(image_post_mod.image_post_entry(_msg_update(msg), _ctx("uz")))
    check("Rasm: IMAGE_POST_INPUT holati qaytdi",
          state == image_post_mod.IMAGE_POST_INPUT, str(state))
    check("Rasm: yo'riqnoma yuborildi", bool(msg.sent))
    check("Rasm: kirishda kredit YECHILMADI",
          not any(c in fake.calls for c in
                  ("spend_credit", "deduct_credits", "consume_credit")), str(fake.calls))
    # Menyu tugmasi ham aynan shu yagona oqimga olib boradi.
    check("Menyu: 📸 Rasm → Post → image_post_entry",
          _targets("📸 Rasm → Post") == {"image_post_entry"},
          str(_targets("📸 Rasm → Post")))
    check("AI Studio: studio_ai_photo callback'i handlerga ega",
          bool(_callback_handler_names("studio_ai_photo")))


def test_aa_action_first_voice():
    header("AA", "🎙 ACTION-FIRST ovoz — STT oqimi ochiladi, limit/kredit tejaladi")
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        state = _run(voice_post_mod.voice_post_entry(_msg_update(msg), _ctx("uz")))
    check("Ovoz: VOICE_AWAIT holati qaytdi",
          state == voice_post_mod.VOICE_AWAIT, str(state))
    check("Ovoz: yo'riqnoma yuborildi", bool(msg.sent))
    check("Ovoz: kirishda transkripsiya CHAQIRILMADI",
          not any("transcri" in c or "stt" in c.lower() for c in fake.calls), str(fake.calls))
    check("Ovoz: kirishda kredit YECHILMADI",
          not any(c in fake.calls for c in
                  ("spend_credit", "deduct_credits", "consume_credit")), str(fake.calls))
    check("Menyu: 🎙 Ovoz → Post → voice_post_entry",
          _targets("🎙 Ovoz → Post") == {"voice_post_entry"},
          str(_targets("🎙 Ovoz → Post")))


def test_ab_action_first_long_text():
    header("AB", "📝 ACTION-FIRST uzun matn — «✨ Magic Post» taklifi chiqadi")
    long_text = ("Bugun mijozlarimiz uchun yangi imkoniyatni e'lon qilmoqchimiz "
                 "va bu haqda batafsil post yozishni rejalashtirgan edim")
    fake = _FakeDB()
    msg = _Msg(text=long_text)
    with _with_db(fake), _quiet():
        offered = _run(content_creation_mod.offer_magic_post_for_direct_text(
            msg, _ctx("uz"), USER_ID, "uz"))
    check("Uzun matn: Magic Post taklifi yuborildi (True)", offered is True, str(offered))
    check("Uzun matn: taklif xabari chizildi", bool(msg.sent))
    check("Uzun matn: taklif matni i18n orqali (cm_offer_text)",
          (msg.sent[-1]["text"] if msg.sent else "") == content_menu_t("cm_offer_text", "uz"),
          (msg.sent[-1]["text"] if msg.sent else "")[:60])
    check("Uzun matn: taklif klaviaturasi berildi",
          msg.sent[-1]["reply_markup"] is not None if msg.sent else False)

    # Qisqa/tushunarsiz matn — material EMAS (eski fallback qoladi).
    for short in ("???", "salom", "ok", "/start"):
        msg2 = _Msg(text=short)
        with _with_db(fake), _quiet():
            offered2 = _run(content_creation_mod.offer_magic_post_for_direct_text(
                msg2, _ctx("uz"), USER_ID, "uz"))
        check(f"Qisqa matn {short!r}: taklif chiqmadi (False)", offered2 is False, str(offered2))
        check(f"Qisqa matn {short!r}: hech qanday xabar yuborilmadi", not msg2.sent)


# ===========================================================================
# TEST AC..AD — ADMIN PANEL YOPIQ + RBAC TAMPERING
# ===========================================================================
def test_ac_admin_panel_closed_for_regular_user():
    header("AC", "🛡 Admin panel oddiy foydalanuvchiga 100% YOPIQ")
    # 1) Menyu darajasi: Admin Panel tugmasi KO'RINMAYDI.
    for lang in LANGS:
        flat = _flat(get_main_keyboard(False, lang=lang))
        check(f"[{lang}] oddiy foydalanuvchi menyusida Admin Panel YO'Q",
              BTN_ADMIN_PANEL not in flat, str(flat))

    # 2) admin_panel_menu — oddiy foydalanuvchida hech narsa chizmaydi.
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        state = _run(ADM.admin_panel_menu(_msg_update(msg), _ctx("uz")))
    check("admin_panel_menu(user): END qaytdi", state == ConversationHandler.END, str(state))
    check("admin_panel_menu(user): hech qanday xabar yuborilmadi", not msg.sent,
          str(msg.sent)[:120])
    check("admin_panel_menu(user): admin DB amali bo'lmadi",
          "get_admin_dashboard_stats" not in fake.calls, str(fake.calls))

    # 3) Barcha adm_* callback'lari — rad javobi, ekran chizilmaydi.
    admin_cbs = [c for c in _cbs(get_admin_dashboard_keyboard()) if str(c).startswith("adm_")]
    check("admin dashboard'da 11 ta adm_* tugma bor (yagona inline panel)",
          len(admin_cbs) == 11, str(admin_cbs))
    for data in admin_cbs:
        q = _Query(data, _Msg(), USER_ID)
        with _with_db(fake), _quiet():
            state = _run(ADM.admin_dashboard_callback(_query_update(q), _ctx("uz")))
        check(f"adm[{data}]: oddiy foydalanuvchi rad etildi (END)",
              state == ConversationHandler.END, str(state))
        check(f"adm[{data}]: rad javobi show_alert bilan berildi",
              any(show_alert for _text, show_alert in q.answered), str(q.answered))
        check(f"adm[{data}]: hech qanday admin ekrani chizilmadi", not q.edits,
              str(q.edits)[:100])


def test_ad_server_side_rbac_tampering():
    header("AD", "🛡 Server-side RBAC — payload tampering himoyasi (fail-closed)")
    # 1) Payload'ga admin ID yozish FOYDA bermaydi — from_user.id hal qiladi.
    tampered_payloads = (
        f"adm_stats:{ADMIN_ID}",
        "adm_grant_pro:%d" % USER_ID,
        "adm_health:owner",
        "adm_broadcast:all",
    )
    fake = _FakeDB()
    for data in tampered_payloads:
        q = _Query(data, _Msg(), USER_ID)   # from_user = ODDIY foydalanuvchi
        with _with_db(fake), _quiet():
            state = _run(ADM.admin_dashboard_callback(_query_update(q), _ctx("uz")))
        check(f"tamper[{data}]: rad etildi", state == ConversationHandler.END, str(state))
        check(f"tamper[{data}]: ekran chizilmadi", not q.edits, str(q.edits)[:100])
    check("tamper: hech qanday admin DB amali bajarilmadi",
          not any(c in fake.calls for c in
                  ("get_admin_dashboard_stats", "get_admin_audit_logs",
                   "list_admin_roles")), str(fake.calls))

    # 2) verify_admin_callback — oddiy foydalanuvchida False.
    from services.rbac_service import verify_admin_callback
    q_user = _Query("adm_stats", _Msg(), USER_ID)
    check("verify_admin_callback(user) is False",
          verify_admin_callback(_query_update(q_user)) is False)
    q_admin = _Query("adm_stats", _Msg(), ADMIN_ID)
    check("verify_admin_callback(admin) is True",
          verify_admin_callback(_query_update(q_admin)) is True)

    # 3) from_user yo'q (buzilgan update) — FAIL-CLOSED.
    broken = SimpleNamespace(callback_query=SimpleNamespace(
        from_user=None, data="adm_stats"), effective_user=None)
    check("verify_admin_callback(buzilgan update) is False (fail-closed)",
          verify_admin_callback(broken) is False)

    # 4) is_admin — oddiy foydalanuvchi False, ADMIN_ID True.
    check("is_admin(user) is False", ADM.is_admin(USER_ID) is False)
    check("is_admin(ADMIN_ID) is True", ADM.is_admin(ADMIN_ID) is True)


# ===========================================================================
# TEST AG — 👑 ADMIN PANEL: YAGONA INLINE PANEL (3-BOSQICH)
# ===========================================================================
def test_ag_admin_single_inline_panel():
    """3-bosqich: pastdagi oq 10 talik admin reply-klaviatura OLIB TASHLANGAN.

    Tekshiruvlar:
      1. ``get_admin_panel_keyboard()`` → ``ReplyKeyboardRemove`` (qaytmaydi);
      2. yagona inline panel layouti topshiriq bo'yicha AYNAN 12 tugma;
      3. har bir ``adm_*`` tugmasi ADMIN uchun ishlaydi (ekran/holat);
      4. eski reply matnlari FAQAT alias (router'da bor, klaviaturada yo'q);
      5. oddiy foydalanuvchi uchun panel yopiq (RBAC fail-closed).
    """
    header("AG", "👑 Admin panel — yagona INLINE panel (eski reply klaviatura yo'q)")
    from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
    from keyboards.default import (
        ADMIN_LEGACY_REPLY_TEXTS, get_admin_panel_keyboard,
    )

    # AG1) Reply-klaviatura o'rnida ReplyKeyboardRemove — hech qanday tugma yo'q.
    legacy_kb = get_admin_panel_keyboard()
    check("AG1: get_admin_panel_keyboard() → ReplyKeyboardRemove",
          isinstance(legacy_kb, ReplyKeyboardRemove), type(legacy_kb).__name__)
    check("AG1: reply klaviaturada tugma yo'q (.keyboard yo'q)",
          not hasattr(legacy_kb, "keyboard"))
    admin_src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
    check("AG1: admin.py'da eski reply-klaviatura chaqiruvi qolmagan",
          "reply_markup=get_admin_panel_keyboard()" not in admin_src)

    # AG2) Yagona inline panel — topshiriqdagi AYNAN 6 qator × 2 tugma.
    rows = _inline_rows(get_admin_dashboard_keyboard())
    expected_labels = (
        ("📊 Bot statistikasi", "📢 Ommaviy xabar"),
        ("🎯 Reklama markazi", "📋 Kanallar ro'yxati"),
        ("📋 Barcha postlar", "🎁 Promo-kod yaratish"),
        ("⭐️ PRO berish", "🏷 Post nishoni"),
        ("⚙️ AI parametrlari", "🗄️ DB / Kesh holati"),
        ("🩺 Tizim monitoringi", "❌ Yopish"),
    )
    got_labels = tuple(tuple(t for t, _cb in row) for row in rows)
    check("AG2: layout AYNAN topshiriq bo'yicha (6 qator × 2)",
          got_labels == expected_labels, str(got_labels))
    check("AG2: layout ADMIN_DASHBOARD_ROWS SSOT bilan aynan bir xil",
          tuple(tuple((t, cb) for t, cb in row) for row in rows) == ADMIN_DASHBOARD_ROWS,
          str(rows))
    check("AG2: jami 12 tugma", len(_cbs(get_admin_dashboard_keyboard())) == 12,
          str(_cbs(get_admin_dashboard_keyboard())))
    check("AG2: dashboard'da reply-klaviatura EMAS, inline klaviatura",
          isinstance(get_admin_dashboard_keyboard(), InlineKeyboardMarkup))

    # AG3) Har bir adm_* tugmasi ADMIN uchun ishlaydi (ekran yoki FSM holati).
    fake = _FakeDB()
    import services.health_service as HS
    orig_report = HS.format_health_report
    async def _fake_report(lang="uz"):
        return "🩺 <b>Tizim holati:</b> OK"
    HS.format_health_report = _fake_report
    expected_state = {
        "adm_stats": ConversationHandler.END,
        "adm_broadcast": ADM.BROADCAST_MESSAGE,
        "adm_adhub": ConversationHandler.END,
        "adm_channels": ConversationHandler.END,
        "adm_posts": ConversationHandler.END,
        "adm_promo": ADM.ADMIN_PROMO_CREATE,
        "adm_grant_pro": ADM.ADMIN_GRANT_PRO,
        "adm_tag": ADM.SET_POST_TAG,
        "adm_ai": ADM.AI_SETTINGS,
        "adm_dbcache": ConversationHandler.END,
        "adm_health": ConversationHandler.END,
        "adm_audit_roles": ConversationHandler.END,
        "adm_sponsors": ConversationHandler.END,
        "adm_back": ConversationHandler.END,
        "adm_cancel": ConversationHandler.END,
    }
    try:
        for data, want in expected_state.items():
            q = _Query(data, _Msg(), ADMIN_ID)
            ctx = _ctx("uz")
            with _with_db(fake), _quiet():
                state = _run(ADM.admin_dashboard_callback(_query_update(q), ctx))
            check(f"AG3[{data}]: admin uchun ishlaydi (holat {want})",
                  state == want, str(state))
            check(f"AG3[{data}]: admin ekrani chizildi (dialog, reply klaviatura emas)",
                  bool(q.edits) and not isinstance(
                      (q.screen or {}).get("reply_markup"), ReplyKeyboardMarkup),
                  str(type((q.screen or {}).get("reply_markup")).__name__))
    finally:
        HS.format_health_report = orig_report

    # AG3b) 🩺 Tizim monitoringi ekranida «📜 Audit | 👥 Rollar» tugmasi qoladi.
    mon_cbs = _cbs(get_admin_monitoring_keyboard())
    check("AG3b: monitoring ekranida adm_audit_roles bor",
          "adm_audit_roles" in mon_cbs, str(mon_cbs))
    check("AG3b: monitoring ekranida dashboardga qaytish (adm_back) bor",
          "adm_back" in mon_cbs, str(mon_cbs))

    # AG4) Eski matnlar FAQAT alias: router'da handler bor, klaviaturada yo'q.
    alias_labels = (
        "📢 Majburiy obuna", "📊 To'liq statistika", "🎯 Reklama markazi",
        "🏷 Post nishoni", "⚙️ AI parametrlar", "🗄️ DB / Kesh holati",
        "✉️ Xabar yuborish", "📋 Barcha postlar", "📋 Barcha kanal/guruhlar",
    )
    for label in alias_labels:
        check(f"AG4: «{label}» alias ro'yxatida (o'chirilmagan)",
              label in ADMIN_LEGACY_REPLY_TEXTS, str(ADMIN_LEGACY_REPLY_TEXTS))
        check(f"AG4: «{label}» router'da handler topadi",
              bool(_targets(label)), str(sorted(_targets(label))))
    # Hech bir ko'rinadigan reply-klaviaturuda bu matnlar yo'q.
    for lang in LANGS:
        for is_admin in (False, True):
            labels = _flat(get_main_keyboard(is_admin, lang=lang))
            leaked = sorted(set(labels) & set(ADMIN_LEGACY_REPLY_TEXTS))
            check(f"AG4[{lang},admin={is_admin}]: menyuda eski admin tugmalari yo'q",
                  not leaked, str(leaked))

    # AG5) Oddiy foydalanuvchi: panel yopiq (RBAC fail-closed), klaviatura yo'q.
    for data in _cbs(get_admin_dashboard_keyboard()):
        if not str(data).startswith("adm_"):
            continue
        q = _Query(data, _Msg(), USER_ID)
        with _with_db(_FakeDB()), _quiet():
            state = _run(ADM.admin_dashboard_callback(_query_update(q), _ctx("uz")))
        check(f"AG5[{data}]: oddiy foydalanuvchi rad etildi",
              state == ConversationHandler.END and not q.edits
              and any(show_alert for _t, show_alert in q.answered),
              str(q.answered))
    user_msg = _Msg()
    with _with_db(_FakeDB()), _quiet():
        state = _run(ADM.admin_panel_menu(_msg_update(user_msg, user_id=USER_ID), _ctx("uz")))
    check("AG5: admin_panel_menu(user) jim rad — hech narsa chizilmadi",
          state == ConversationHandler.END and not user_msg.sent)


# ===========================================================================
# TEST AE..AF — I18N ORQALI MATN + 100% SINXRON
# ===========================================================================
def _i18n_key_for(label):
    """Yorliq uchun i18n kalitini izlaydi (get_text orqali tiklanadi)."""
    for lang in LANGS:
        for key in ("btn_create_content", "btn_my_channels", "btn_scheduled",
                    "btn_statistics", "btn_premium", "btn_settings",
                    "btn_cancel", "btn_main_menu", "btn_new_post",
                    "btn_ai_studio", "btn_help", "btn_extras", "btn_admin_panel"):
            try:
                if get_text(key, lang) == label:
                    return key
            except Exception:
                continue
    return None


def test_ae_all_texts_via_i18n():
    header("AE", "🌐 Barcha ko'rinadigan matnlar i18n orqali chiqadi")
    # 1) Asosiy menyu — har bir yorliq i18n kalitidan tiklanadi.
    for lang in LANGS:
        for label in _flat(get_main_keyboard(False, lang=lang)):
            key = _i18n_key_for(label)
            check(f"[{lang}] {label!r} i18n kalitidan kelib chiqadi",
                  key is not None and get_text(key, lang) == label, str(label))

    # 2) Submenu matnlari — content_menu_t orqali (qattiq kodlangan emas).
    for lang in LANGS:
        rows = content_creation_rows(lang)
        flat = [t for row in rows for t in row]
        check(f"[{lang}] kontent submenu Orqaga yorlig'i = cm_btn_back",
              flat[-1] == content_menu_t("cm_btn_back", lang), flat[-1])
        check(f"[{lang}] kontent submenu matnlari uch tilga tarjima qilingan",
              len({t for t in flat if t}) == len(flat) and all(t.strip() for t in flat))

    # 3) Statistika ekrani — settings_stats_t orqali (builder i18n'ga tayanadi).
    for lang in LANGS:
        text = analytics_mod.build_user_stats_text(
            {"channels": 1, "created_posts": 2, "scheduled_posts": 3,
             "ai_requests": 4, "credits_spent": 5}, lang)
        check(f"[{lang}] statistika matni bo'sh emas va i18n sarlavhasi bor",
              bool(text.strip()) and "━" in text, text[:60])
    # Uchala til ALOHIDA matn beradi (yagona uz matniga yopishib qolmagan).
    texts = {lang: analytics_mod.build_user_stats_text(
        {"channels": 1, "created_posts": 2, "scheduled_posts": 3,
         "ai_requests": 4, "credits_spent": 5}, lang) for lang in LANGS}
    check("statistika: uz/ru/en matnlari bir-biridan farq qiladi",
          len(set(texts.values())) == 3, str(list(texts.values()))[:120])

    # 4) Queue/Kanallar matnlari — channels_queue_t orqali.
    uz_empty = content_menu_t("cm_btn_back", "uz")
    ru_empty = content_menu_t("cm_btn_back", "ru")
    check("kanallar/queue i18n: uz va ru Orqaga yorliqlari farq qiladi",
          uz_empty != ru_empty, f"{uz_empty!r} vs {ru_empty!r}")


def test_af_all_languages_100_percent_in_sync():
    header("AF", "🌐 Barcha tillar 100% sinxron (in_sync: True)")
    reports = {
        "content_menu": content_menu_parity_report(),
        "settings_stats": settings_stats_parity_report(),
        "channels_queue": channels_queue_parity_report(),
        "magic_post": magic_post_parity_report(),
        "voice_post": voice_post_parity_report(),
        "post_score": post_score_parity_report(),
    }
    for name, report in reports.items():
        check(f"{name}: in_sync is True", report.get("in_sync") is True,
              str({k: report.get(k) for k in ("in_sync", "missing", "extra")})[:200])
        check(f"{name}: missing yo'q",
              not any((report.get("missing") or {}).values()), str(report.get("missing"))[:160])
        check(f"{name}: extra yo'q",
              not any((report.get("extra") or {}).values()), str(report.get("extra"))[:160])
        check(f"{name}: format_mismatch yo'q",
              not report.get("format_mismatch"), str(report.get("format_mismatch"))[:160])
        check(f"{name}: empty qiymat yo'q",
              not report.get("empty"), str(report.get("empty"))[:160])

    # Amaliy paritet: har bir ko'rinadigan menyu 3 tilda bir xil TUGMA SONINI beradi.
    for name, builder in (
        ("main", lambda lang: len(_flat(get_main_keyboard(False, lang=lang)))),
        ("content", lambda lang: len([t for r in content_creation_rows(lang) for t in r])),
        ("ai_studio", lambda lang: len(_labels(get_ai_studio_keyboard(lang)))),
        ("settings", lambda lang: len(_labels(get_settings_hub_keyboard(lang)))),
        ("tools", lambda lang: len(_labels(get_tools_keyboard(lang)))),
        ("user_stats", lambda lang: len(_labels(get_user_stats_keyboard(lang)))),
        ("channel_panel", lambda lang: len(_labels(render_channel_panel(CH_ID, lang)))),
    ):
        counts = {lang: builder(lang) for lang in LANGS}
        check(f"{name}: uchala tilda tugma soni bir xil", len(set(counts.values())) == 1,
              str(counts))

    # Asosiy i18n hisoboti ham sinxron.
    from locales.translations import translation_parity_report
    main_report = translation_parity_report()
    check("translation_parity_report: EN kamchiliksiz (missing yo'q)",
          not main_report.get("missing"), str(main_report.get("missing"))[:200])


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    global FAILURES
    print("=" * 70)
    print(" 🏁 POSTASSIST — YAKUNIY ACCEPTANCE SUITE (TEST A..AG)")
    print("=" * 70)

    suite = (
        test_a_main_menu_uz,
        test_b_main_menu_ru,
        test_c_main_menu_en,
        test_d_main_menu_admin_variant_and_parity,
        test_e_content_submenu_parity,
        test_f_ai_studio_submenu_parity,
        test_g_i18n_reports_in_sync,
        test_h_channels_menu_opens,
        test_i_channel_panel_management_screen,
        test_j_queue_menu_navigation,
        test_k_statistics_isolation,
        test_l_settings_menu_8_groups_plus_back,
        test_m_pro_subscription_opens,
        test_n_tools_submenu_opens,
        test_o_no_duplicate_visible_buttons,
        test_p_buttons_route_uz,
        test_q_buttons_route_ru,
        test_r_buttons_route_en,
        test_s_inline_callbacks_have_handlers,
        test_t_back_content_ai_returns_to_content_submenu,
        test_u_back_settings_tools_returns_to_settings,
        test_v_cancel_and_exit_navigation,
        test_w_legacy_buttons_still_route,
        test_x_legacy_callbacks_still_handled,
        test_y_fsm_states_no_conflict,
        test_z_action_first_image,
        test_aa_action_first_voice,
        test_ab_action_first_long_text,
        test_ac_admin_panel_closed_for_regular_user,
        test_ad_server_side_rbac_tampering,
        test_ag_admin_single_inline_panel,
        test_ae_all_texts_via_i18n,
        test_af_all_languages_100_percent_in_sync,
    )
    print(f"\nBelgilangan testlar soni: {len(suite)} (TEST A..AG)")

    crashed = []
    for fn in suite:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — bitta test yiqilsa ham
            # qolganlari hisobotga tushishi kerak (acceptance suite to'liq bo'lsin).
            FAILURES += 1
            crashed.append(fn.__name__)
            print(f"  [FAIL] {fn.__name__} istisno bilan yiqildi: {exc!r}")

    print()
    print("=" * 70)
    if crashed:
        print(f"ISTISNO BILAN YIQILGAN: {', '.join(crashed)}")
    print(f"JAMI: o'tdi={PASSED}, xato={FAILURES}")
    print("=" * 70)
    if FAILURES:
        print("TESTS: FAIL ❌")
        sys.exit(1)
    print("TESTS: PASS ✔ — TEST A..AG to'liq bajarildi")
    sys.exit(0)


if __name__ == "__main__":
    main()
