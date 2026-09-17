#!/usr/bin/env python3
"""⚙️ POSTASSIST V2 · 3-QADAM REFAKTOR — KONTRAKT TESTLARI (deterministik, tarmoqsiz).

Qamrov (3-qadam topshirig'i bo'yicha):

  TEST 1 — ⚙️ SOZLAMALAR menyusidagi LEGACY DUBLIKATLAR tozalandi:
           eski kabinet tezkor tugmalari (📢 Mening kanallarim, 📊 Analitika,
           📅 Kutilayotgan/Rejalashtirilgan, 💎 Ballar & reklama rejimi,
           🎁 bonus) menyu KO'RINISHIDAN olib tashlandi — ular o'z asosiy
           menyularida bor. Menyu yagona, tartibli va TO'LIQ ko'rinishga
           (8 guruh + [◀️ Orqaga]) keltirildi va bu uchala tilda AYNAN
           speks tartibida chiziladi:
               [👤 Profil]            [🌐 Til / Язык]
               [💎 Ballarim]          [🔄 Ballar o'tkazish]
               [🎁 Kunlik bonus]      [👥 Do'stlarni taklif]
               [🔔 Bildirishnomalar]  [🎨 Post sozlamalari]
               [💳 To'lovlar tarixi]  [🧰 Vositalar]
               [❓ Yordam]            [ℹ️ Bot haqida]
                            [◀️ Orqaga]
  TEST 2 — 💎 Ballarim / 🔄 Ballar o'tkazish / 🎁 Kunlik bonus /
           👥 Do'stlarni taklif tugmalari O'Z oqimlarini ochadi:
           Ballar o'tkazish mavjud TRANSFER_TARGET → TRANSFER_AMOUNT FSM
           oqimiga kiradi (yangi holat yo'q), kunlik bonus mavjud
           `claim_daily_streak_bonus` amalini chaqiradi, referral ekrani
           havolani ko'rsatadi.
  TEST 3 — 🧰 VOSITALAR submenyusi: [🔤 Kirill-Lotin Konvertor] va
           [✨ Tugma & Reaksiyalar (Post Enhancer)] — avval yashirinib qolgan
           Konvertor (#38) va Post Enhancer (#9) endi aniq, ko'rinadigan
           mantiqiy joyida; ikkala tugma mavjud, sinovdan o'tgan oqimlarga
           (CONVERT_INPUT / ENH_POST) ulanadi, [◀️ Orqaga] sozlamalarga
           qaytaradi.
  TEST 4 — 🛡 XAVFSIZLIK/ORQAGA MOSLIK: eski `cab_*` callback'lari va legacy
           reply-tugma/buyruqlar O'CHIRILMAGAN — ular xavfsiz alias/redirect
           sifatida ishlashda davom etadi va crash bermaydi.
  TEST 5 — 🌐 I18N: UZ/RU/EN 100% paritet (``in_sync: True``), barcha yangi
           tugma/bo'lim matnlari uchala tilda mavjud, callback'lar tilga
           bog'liq emas va Telegram 64-bayt chegarasiga mos.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/refactor_step3_test.py
"""
import asyncio
import contextlib
import logging
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:REFACTOR_STEP3_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10012")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import importlib  # noqa: E402

import database as db_mod  # noqa: E402
from telegram.ext import ConversationHandler  # noqa: E402

# Eslatma: ``handlers.start`` paket atributi sifatida import qilinmaydi
# (``handlers/__init__`` dagi funksiya nomi uni shadow qiladi) — aniq modul
# importlib orqali olinadi.
import handlers  # noqa: E402,F401 — barcha handlerlarni reyestrga qo'yadi
start_mod = importlib.import_module("handlers.start")
settings_mod = importlib.import_module("handlers.settings")
tools_mod = importlib.import_module("handlers.tools")
converter_mod = importlib.import_module("handlers.converter")
enhancer_mod = importlib.import_module("handlers.post_enhancer")

from keyboards.inline import (  # noqa: E402
    get_extras_inline_keyboard, get_settings_back_keyboard,
    get_settings_hub_keyboard, get_tools_keyboard,
)
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, callback_byte_len, is_callback_safe,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    CB_SETTINGS_HUB, CB_TOOLS_HUB, SETTINGS_MENU_BUTTON_KEYS,
    TOOLS_MENU_BUTTON_KEYS, settings_stats_parity_report, settings_stats_t,
)

LANGS = ("uz", "ru", "en")
USER_ID = 777777
ADMIN_ID = 123456789

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
# SPEKS: menyu tarkibi va yorliqlari (uchala til)
# ---------------------------------------------------------------------------
HUB_LABELS = {
    # 🧹 UI/UX POLISH (1-qadam): «👤 Profil» yo'q — hub matnining o'zi profil;
    # «🎁 Bonuslar & Ballar» → yagona «🎁 Bonuslar & Taklif».
    "uz": (("🌐 Til / Язык", "🎁 Bonuslar & Taklif"),
           ("🎨 Post sozlamalari", "🔔 Bildirishnomalar"),
           ("💳 To'lovlar tarixi", "🧰 Vositalar"),
           ("❓ Yordam & Ma'lumot",)),
    "ru": (("🌐 Язык / Language", "🎁 Бонусы и приглашения"),
           ("🎨 Настройки постов", "🔔 Уведомления"),
           ("💳 История платежей", "🧰 Инструменты"),
           ("❓ Помощь и информация",)),
    "en": (("🌐 Language", "🎁 Bonuses & Invites"),
           ("🎨 Post settings", "🔔 Notifications"),
           ("💳 Payment history", "🧰 Tools"),
           ("❓ Help & Info",)),
}

#: Legacy kabinet callback'lari — menyu KO'RINISHIDA bo'lmasligi shart
#: (routing'da esa SAQLANADI — TEST 4 shuni tekshiradi).
LEGACY_HUB_CALLBACKS = (
    "cab_channels", "cab_channels_delete", "cab_analytics", "cab_pending",
    "cab_queue", "cab_balance", "cab_bonus", "close_cabinet",
)

#: Legacy kabinet yorliqlari — dublikat bo'lib chiqmasligi shart.
LEGACY_HUB_LABEL_KEYS = (
    "cab_my_channels", "cab_analytics", "cab_pending", "cab_queue",
    "cab_balance",
)

#: Eski `cab_*` callback'lari — barchasi crash bermasdan javob berishi shart.
LEGACY_CABINET_CALLBACKS = (
    "cab_main", "cab_channels", "cab_channels_delete", "cab_analytics",
    "cab_converter", "cab_bonus", "cab_referral", "cab_balance",
    "cab_pending", "cab_queue", "cab_guide", "cab_lang", "close_cabinet",
)


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
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def _labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def _cbs(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class _FakeDB:
    """``database.run_db`` mock — 3-qadam oqimlari uchun deterministik.

    Noma'lum funksiya chaqirilsa ``None`` qaytadi (fail-safe oqimlar shu
    holatda ham crash bermasligi kerak) va ``unknown`` ro'yxatiga yoziladi.
    """

    def __init__(self, credits=7, premium=False, language="uz",
                 bonus_success=True, channels=None, queue_total=0):
        self.credits = credits
        self.premium = premium
        self.language = language
        self.bonus_success = bonus_success
        self.channels = channels if channels is not None else [
            ("-1001", "Kanal A", "friendly"), ("-1002", "Kanal B", "formal"),
        ]
        self.queue_total = queue_total
        self.set_language_calls = []
        self.calls = []
        self.unknown = []

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append(name)

        if name == "get_user_language":
            return self.language
        if name == "set_user_language":
            self.set_language_calls.append((args[0], args[1]))
            self.language = args[1]
            return True
        if name == "get_referral_stats":
            return {"referrals_count": 2, "ai_credits": self.credits, "streak": 3}
        if name == "get_user_channels":
            return list(self.channels)
        if name == "get_user_code":
            return "TST777"
        if name == "get_user_credits":
            return self.credits
        if name == "is_premium":
            return self.premium
        if name == "get_ads_full":
            return []
        if name == "get_setting":
            return args[1] if len(args) > 1 else ""
        if name == "get_user_onboarding":
            return None
        if name == "claim_daily_streak_bonus":
            if self.bonus_success:
                return {"success": True, "streak": 4, "bonus_amount": 1,
                        "credits": self.credits + 1}
            return {"success": False, "msg": "already claimed",
                    "credits": self.credits}
        if name == "get_channel_post_stats":
            return {"posts": 3, "views": 10, "reactions": 1}
        if name == "get_queue_post_count":
            return self.queue_total
        if name == "get_queue_posts":
            return []
        if name == "check_queue_limit":
            return (True, self.queue_total, 5)
        if name == "get_admin_dashboard_stats":
            return {"users": 1, "pro_subscribers": 0, "channels": 1,
                    "posts_today": 0, "pending_posts": 0, "stars_revenue": 0}

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
# APP/ROUTING YORDAMCHILARI (haqiqiy PTB ilovasi, tarmoqsiz)
# ---------------------------------------------------------------------------
def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:REFACTOR_STEP3_TEST").build()
    handlers.register_all_handlers(app)
    return app


def _conversation_handlers(app):
    out = []
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            if isinstance(handler, ConversationHandler):
                out.append(handler)
    return out


def _entry_points(app):
    points = []
    for conv in _conversation_handlers(app):
        points.extend(conv.entry_points)
    return points


def _cb_update(data, user_id=USER_ID):
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "1", "chat_instance": "x", "data": data,
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "message": {
                "message_id": 9, "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 999, "is_bot": True, "first_name": "Bot"},
                "text": "⚙️ Sozlamalar",
            },
        },
    }, None)


_RAW_BOT = None


def _test_bot():
    """PTB ``Bot`` nusxasi (``CommandHandler`` uchun Update'ga bog'lanadi).

    Tarmoqqa CHIQMAYDI — faqat ``Update.de_json`` ichida ``message.get_bot()``
    ishlashi uchun kerak (PTB CommandHandler shuni talab qiladi).
    """
    global _RAW_BOT
    if _RAW_BOT is None:
        from telegram import Bot
        _RAW_BOT = Bot("123456:REFACTOR_STEP3_TEST")
    return _RAW_BOT


def _msg_update_raw(text, user_id=USER_ID, as_command=False, bot=None):
    """Matnli xabar Update'i (``as_command=True`` — bot_command entity bilan).

    ``bot`` — PTB ``CommandHandler`` bot bilan bog'langan Update talab qiladi
    (``message.get_bot()``), shu sababli app.bot uzatiladi.
    """
    from telegram import Update
    message = {
        "message_id": 11, "date": 0, "text": text,
        "chat": {"id": user_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
    }
    if as_command:
        # Telegram'da buyruq har doim ``bot_command`` entity bilan keladi —
        # PTB ``CommandHandler`` aynan shu entity'ni tekshiradi.
        message["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(text.split()[0])}
        ]
    return Update.de_json({"update_id": 2, "message": message},
                          bot if bot is not None else _test_bot())


def _first_routed_name(app, update):
    """Update uchun BIRINCHI mos keladigan handler nomi (router tekshiruvi)."""
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            try:
                if handler.check_update(update):
                    return getattr(getattr(handler, "callback", None), "__name__",
                                   type(handler).__name__)
            except Exception:  # pragma: no cover - himoya
                continue
    return None


def _handler_fn_names(handler):
    """Handler callback'idagi funksiya nomlari (lambda uchun ``co_names``)."""
    names = set()
    callback = getattr(handler, "callback", None)
    if callable(callback) and getattr(callback, "__name__", "<lambda>") != "<lambda>":
        names.add(callback.__name__)
    code = getattr(callback, "__code__", None)
    if code is not None and code.co_names:
        names.update(code.co_names)
    return names


def _entry_fn_names(app, update):
    """``update``ni tanigan entry point'lardagi funksiya nomlari."""
    names = set()
    for handler in _entry_points(app):
        try:
            if not handler.check_update(update):
                continue
        except Exception:  # pragma: no cover - himoya
            continue
        names |= _handler_fn_names(handler)
    return names


def _cb_entry_fn_names(app, data):
    """Inline callback uchun entry point funksiya nomlari."""
    return _entry_fn_names(app, _cb_update(data))


def _msg_entry_fn_names(app, text, as_command=False):
    """Reply-tugma/buyruq matni uchun entry point funksiya nomlari."""
    return _entry_fn_names(
        app, _msg_update_raw(text, as_command=as_command, bot=_test_bot()))


# ===========================================================================
# TEST 1 — ⚙️ SOZLAMALAR MENYUSI: LEGACY DUBLIKATLAR YO'Q + SPEKS TARTIBI
# ===========================================================================
def test_settings_hub_has_no_legacy_duplicates():
    print("== TEST 1: ⚙️ Sozlamalar menyusi — 8 guruh + Orqaga ==")

    for lang in LANGS:
        kb = get_settings_hub_keyboard(lang)
        rows = _rows(kb)
        cbs = _cbs(kb)

        check(f"[{lang}] menyu 5 qator (3 juftlik + Yordam + ◀️ Orqaga)",
              len(rows) == 5, str(len(rows)))
        check(f"[{lang}] 7 guruh AYNAN speks tartibida (Profil olib tashlangan)",
              [[t for t, _ in row] for row in rows[:4]]
              == [list(pair) for pair in HUB_LABELS[lang]],
              str([[t for t, _ in row] for row in rows[:4]]))
        check(f"[{lang}] callback tartibi speks bilan bir xil",
              cbs[:7] == list(CB_SETTINGS_HUB[:7]), str(cbs))
        check(f"[{lang}] oxirgi qator = [◀️ Orqaga] → stgs_back",
              rows[-1] == [(settings_stats_t("ss_btn_back", lang), "stgs_back")],
              str(rows[-1]))
        check(f"[{lang}] jami 8 tugma (7 + Orqaga, Profil yo'q)",
              len(cbs) == 8, str(len(cbs)))
        check(f"[{lang}] stgs_profile hub'da YO'Q (matn o'zi profil)",
              "stgs_profile" not in cbs, str(cbs))
        check(f"[{lang}] callback'lar takrorlanmaydi",
              len(set(cbs)) == len(cbs), str(cbs))

        # 1a) LEGACY dublikatlar menyuda YO'Q (callback darajasida).
        found = [cb for cb in LEGACY_HUB_CALLBACKS if cb in cbs]
        check(f"[{lang}] legacy cab_* tugmalar yo'q", not found, str(found))

        # 1b) LEGACY dublikatlar menyuda YO'Q (yorliq darajasida).
        labels = _labels(kb)
        dup_labels = [get_text(key, lang) for key in LEGACY_HUB_LABEL_KEYS
                      if get_text(key, lang) in labels]
        check(f"[{lang}] legacy yorliqlar yo'q", not dup_labels, str(dup_labels))

        # 1c) `include_legacy=True` ham legacy tugmalarni chizmaydi
        #     (eski chaqiruv kod TypeError bilan yiqilmaydi ham).
        legacy_kb = get_settings_hub_keyboard(lang, include_legacy=True)
        check(f"[{lang}] include_legacy=True — natija o'zgarmaydi",
              _cbs(legacy_kb) == cbs, str(_cbs(legacy_kb)))

    # 1d) [⚙️ Sozlamalar] → user_cabinet_menu (reply) ham AYNAN shu menyuni
    #     chizadi: profil matni + hech qanday legacy dublikat yo'q.
    fake = _FakeDB()
    for lang in LANGS:
        with _with_db(fake):
            msg = _Msg()
            _run(start_mod.user_cabinet_menu(_msg_update(msg), _ctx(lang)))
        last = msg.sent[-1]
        cbs = _cbs(last["reply_markup"])
        check(f"[{lang}] hub ekrani 8 tugma bilan ochiladi (Profil yo'q)",
              len(cbs) == 8, str(cbs))
        check(f"[{lang}] hub ekrani legacy tugmasiz",
              not any(cb in cbs for cb in LEGACY_HUB_CALLBACKS), str(cbs))
        check(f"[{lang}] hub profil kartasi bilan (Shaxsiy Kabinet)",
              get_text("cabinet_title", lang, user_id=USER_ID, user_code="TST777",
                       credits="7", streak="3/7", channels=2, referrals=2,
                       ad_line="").splitlines()[0] in (last["text"] or ""),
              (last["text"] or "")[:80])

    # 1e) 8 guruh — rewards/help parent callback'lari ko'rinadi.
    uz_cbs = _cbs(get_settings_hub_keyboard("uz"))
    for cb in ("stgs_rewards", "stgs_tools", "stgs_help_hub"):
        check(f"hub: {cb} tugmasi mavjud", cb in uz_cbs, str(uz_cbs))


# ===========================================================================
# TEST 2 — BALLAR O'TKAZISH / KUNLIK BONUS / REFERRAL / BALLARIM OCHILADI
# ===========================================================================
def test_hub_actions_open_their_flows():
    print("== TEST 2: 💎 Ballarim · 🔄 Ballar o'tkazish · 🎁 Kunlik bonus · 👥 Referral ==")
    app = _build_app()

    # 2a) Menyu tugmalari to'g'ri handlerga ulanadi (real router).
    for data in ("stgs_rewards", "stgs_help_hub", "stgs_points", "stgs_bonus",
                 "stgs_referral", "stgs_tools", "stgs_hub", "stgs_profile",
                 "stgs_lang"):
        name = _first_routed_name(app, _cb_update(data))
        check(f"routing: {data} → settings handler",
              name in {"settings_menu_callback", "settings_rewards_callback",
                       "settings_help_hub_callback"}, str(name))

    # 2b) 🔄 Ballar o'tkazish — main_conv entry point'i (mavjud FSM oqimi).
    names = _cb_entry_fn_names(app, "stgs_transfer")
    check("routing: stgs_transfer entry point bor", bool(names), str(sorted(names)))
    check("routing: stgs_transfer → transfer_inline_entry",
          "transfer_inline_entry" in names, str(sorted(names)))
    convs = _conversation_handlers(app)
    transfer_states = [s for conv in convs for s in conv.states
                       if s in (start_mod.TRANSFER_TARGET, start_mod.TRANSFER_AMOUNT)]
    check("FSM: TRANSFER_TARGET / TRANSFER_AMOUNT holatlari saqlangan",
          len(set(transfer_states)) == 2, str(transfer_states))

    # 2c) Reply-tugma kirishi (start_transfer_credits) ham saqlangan.
    reply_names = _msg_entry_fn_names(app, get_text("cab_btn_transfer", "uz"))
    check("routing: reply-tugma transfer oqimi saqlangan",
          "start_transfer_credits" in reply_names
          or "transfer_inline_entry" in reply_names,
          str(sorted(reply_names)))

    # 2d) Yetarli ball: intro + TRANSFER_TARGET holati.
    fake = _FakeDB(credits=7)
    with _with_db(fake):
        q = _Query("stgs_transfer")
        state = _run(start_mod.transfer_inline_entry(_query_update(q), _ctx("uz")))
    check("ballar o'tkazish: intro ekrani yuborildi",
          any(get_text("transfer_intro", "uz") in (m["text"] or "")
              for m in q.message.sent), str(q.message.sent)[:120])
    check("ballar o'tkazish: state = TRANSFER_TARGET",
          state == start_mod.TRANSFER_TARGET, str(state))
    check("ballar o'tkazish: callback darhol javoblandi", bool(q.answered))

    # 2e) Ball yetarli bo'lmasa — xavfsiz ogohlantirish + dialog yopiladi.
    fake = _FakeDB(credits=1)
    with _with_db(fake):
        q = _Query("stgs_transfer")
        state = _run(start_mod.transfer_inline_entry(_query_update(q), _ctx("uz")))
    check("ballar yetarli emas: ogohlantirish matni",
          any("yetarli ball yo'q" in (m["text"] or "") for m in q.message.sent),
          str(q.message.sent)[:120])
    check("ballar yetarli emas: state = END",
          state == ConversationHandler.END, str(state))

    # 2f) 💎 Ballarim — kredit balansi va reklama rejimi kartasi.
    fake = _FakeDB(credits=7, premium=False)
    with _with_db(fake):
        q = _Query("stgs_points")
        _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
    text = q.screen.get("text", "")
    check("ballarim: balans kartasi (7 ta AI so'rov)", "7" in text, text[:100])
    check("ballarim: stgs_hub tugmasi",
          _cbs(q.screen.get("reply_markup")) == ["stgs_hub"],
          str(_cbs(q.screen.get("reply_markup"))))

    # 2g) 🎁 Kunlik bonus — mavjud claim amali chaqiriladi.
    fake = _FakeDB(credits=7, bonus_success=True)
    with _with_db(fake):
        q = _Query("stgs_bonus")
        _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
    text = q.screen.get("text", "")
    check("kunlik bonus: claim_daily_streak_bonus chaqirildi",
          "claim_daily_streak_bonus" in fake.calls, str(fake.calls[-3:]))
    check("kunlik bonus: natija ekrani (streak 4/7 + sovg'a)",
          "4/7" in text and "+1" in text, text[:160])
    check("kunlik bonus: stgs_hub tugmasi",
          _cbs(q.screen.get("reply_markup")) == ["stgs_hub"],
          str(_cbs(q.screen.get("reply_markup"))))

    # 2g-2) Bonus allaqachon olingan bo'lsa — xavfsiz "keyinroq" ekrani
    #       (DB xabari foydalanuvchi tiliga o'giriladi, crash yo'q).
    with _with_db(_FakeDB(bonus_success=False)):
        q = _Query("stgs_bonus")
        error = None
        try:
            _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
        except Exception as exc:  # pragma: no cover - kutilmaydi
            error = f"{type(exc).__name__}: {exc}"
    check("kunlik bonus (takror): crash yo'q", error is None, str(error))
    check("kunlik bonus (takror): ekran chizildi",
          bool(q.screen.get("text")) and "stgs_hub" in _cbs(q.screen.get("reply_markup")),
          str(q.screen)[:120])

    # 2h) Admin — cheksiz so'rovlar (claim qilinmaydi).
    with _with_db(_FakeDB()):
        q = _Query("stgs_bonus", user_id=ADMIN_ID)
        _run(settings_mod.settings_menu_callback(_query_update(q, user_id=ADMIN_ID),
                                                 _ctx("uz")))
    check("kunlik bonus (admin): 'Super Admin' ekrani",
          "Super Admin" in (q.screen.get("text") or ""), (q.screen.get("text") or "")[:80])

    # 2i) 👥 Do'stlarni taklif — referral havolasi shu menyu orqali ochiladi.
    with _with_db(_FakeDB()):
        q = _Query("stgs_referral")
        _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
    ref_text = q.screen.get("text", "")
    check("referral: shaxsiy havola ko'rsatiladi",
          f"https://t.me/postassist_test_bot?start=ref_{USER_ID}" in ref_text,
          ref_text[:160])
    check("referral: ekranda Orqaga bor",
          "stgs_hub" in _cbs(q.screen.get("reply_markup")),
          str(_cbs(q.screen.get("reply_markup"))))


# ===========================================================================
# TEST 3 — 🧰 VOSITALAR: KONVERTOR + POST ENHANCER O'Z JOYIDA
# ===========================================================================
def test_tools_submenu_wires_converter_and_enhancer():
    print("== TEST 3: 🧰 Vositalar — Konvertor (#38) + Post Enhancer (#9) ==")
    app = _build_app()

    # 3a) `handlers.tools` shartnomasi — yagona manba (testlar uchun).
    check("tools.TOOLS_MENU_CALLBACKS = speks tartibi",
          tuple(tools_mod.TOOLS_MENU_CALLBACKS) == tuple(CB_TOOLS_HUB),
          str(tools_mod.TOOLS_MENU_CALLBACKS))
    check("tools.TOOLS_BACK_CALLBACK = stgs_hub",
          tools_mod.TOOLS_BACK_CALLBACK == "stgs_hub",
          str(tools_mod.TOOLS_BACK_CALLBACK))
    check("tools ekrani quruvchilari mavjud",
          callable(tools_mod.build_tools_text)
          and callable(tools_mod.build_tools_keyboard)
          and callable(tools_mod.render_tools_menu), "")
    check("tools.build_tools_keyboard = get_tools_keyboard",
          _cbs(tools_mod.build_tools_keyboard("uz")) == _cbs(get_tools_keyboard("uz")),
          str(_cbs(tools_mod.build_tools_keyboard("uz"))))
    for cbdata, state, source in tools_mod.TOOLS_ENTRIES:
        check(f"tools entry: {cbdata} → {state}",
              cbdata in CB_TOOLS_HUB and bool(state) and "." in source,
              f"{cbdata} {state} {source}")

    # 3b) Klaviatura: speksdagi 2 vosita + [◀️ Orqaga], 3 tilda.
    for lang in LANGS:
        kb = get_tools_keyboard(lang)
        rows = _rows(kb)
        check(f"[{lang}] vositalar 3 tugma (2 vosita + Orqaga)",
              len(rows) == 3, str(rows))
        check(f"[{lang}] callback'lar: extra_converter / extra_enhancer / stgs_hub",
              _cbs(kb) == list(CB_TOOLS_HUB), str(_cbs(kb)))
        check(f"[{lang}] Konvertor yorlig'i i18n'dan",
              rows[0][0][0] == settings_stats_t("ss_tools_btn_converter", lang),
              str(rows[0]))
        check(f"[{lang}] Post Enhancer yorlig'i i18n'dan",
              rows[1][0][0] == settings_stats_t("ss_tools_btn_enhancer", lang),
              str(rows[1]))
        check(f"[{lang}] Orqaga = ss_btn_back (stgs_hub)",
              rows[2][0][0] == settings_stats_t("ss_btn_back", lang), str(rows[2]))

    # 3b) 「🧰 Vositalar] ekrani: sozlamalar menyusidan ochiladi.
    for lang in LANGS:
        with _with_db(_FakeDB()):
            q = _Query("stgs_tools")
            _run(settings_mod.settings_menu_callback(_query_update(q), _ctx(lang)))
        text = q.screen.get("text", "")
        check(f"[{lang}] vositalar ekrani sarlavhasi",
              "Vositalar" in text or "Инструменты" in text or "Tools" in text,
              text[:80])
        check(f"[{lang}] vositalar ekrani 3 tugma bilan",
              _cbs(q.screen.get("reply_markup")) == list(CB_TOOLS_HUB),
              str(_cbs(q.screen.get("reply_markup"))))
        # Matn ikkala vositani ham tushuntiradi (Konverter + Tugma/Reaksiya).
        converter_word = ("Konvertor", "Конвертер", "Converter")
        enhancer_word = ("Tugma", "Кнопки", "Buttons")
        check(f"[{lang}] matn Konvertorni ham, Post Enhancerni ham eslatadi",
              any(w in text for w in converter_word)
              and any(w in text for w in enhancer_word), text[:160])

    # 3c)「◀️ Orqaga] → ⚙️ Sozlamalar menyusi qayta chiziladi (yangi xabar yo'q).
    with _with_db(_FakeDB()):
        q = _Query("stgs_hub")
        _run(settings_mod.settings_menu_callback(_query_update(q), _ctx("uz")))
    check("vositalar → orqaga: sozlamalar 8 tugmasi qaytdi",
          _cbs(q.screen.get("reply_markup")) == list(CB_SETTINGS_HUB),
          str(_cbs(q.screen.get("reply_markup"))))
    check("vositalar → orqaga: yangi xabar yuborilmadi (edit)",
          not q.message.sent, str(q.message.sent)[:80])

    # 3d) Konvertor tugmasi — mavjud CONVERT_INPUT oqimiga kiradi.
    conv_names = _cb_entry_fn_names(app, "extra_converter")
    check("routing: extra_converter → converter_inline_entry",
          "converter_inline_entry" in conv_names, str(sorted(conv_names)))
    check("Konverter holati mavjud (CONVERT_INPUT)",
          hasattr(converter_mod, "CONVERT_INPUT"), "")
    with _with_db(_FakeDB()):
        q = _Query("extra_converter")
        state = _run(converter_mod.converter_inline_entry(_query_update(q), _ctx("uz")))
    check("Konverter: state = CONVERT_INPUT",
          state == converter_mod.CONVERT_INPUT, str(state))
    check("Konverter: yo'riqnoma matni yuborildi",
          any(get_text("conv_intro", "uz") in (m["text"] or "")
              for m in q.message.sent), str(q.message.sent)[:120])

    # 3e) Post Enhancer tugmasi — mavjud ENH_POST oqimiga kiradi.
    enh_names = _cb_entry_fn_names(app, "extra_enhancer")
    check("routing: extra_enhancer → post_enhancer_start",
          "post_enhancer_start" in enh_names, str(sorted(enh_names)))
    with _with_db(_FakeDB()):
        q = _Query("extra_enhancer")
        state = _run(enhancer_mod.post_enhancer_start(_query_update(q), _ctx("uz")))
    check("Post Enhancer: state = ENH_POST",
          state == enhancer_mod.ENH_POST, str(state))
    check("Post Enhancer: intro matni yuborildi",
          bool(q.message.sent) and bool(q.message.sent[-1]["text"]),
          str(q.message.sent)[:120])

    # 3f) Orqaga moslik: eski «⚙️ Qo'shimcha funksiyalar» klaviaturasi va
    #     `extra_close` callback'i O'ZGARMAGAN (o'chirilmagan).
    ex_cbs = _cbs(get_extras_inline_keyboard("uz"))
    check("eski extras menyusi saqlangan (3 tugma)",
          ex_cbs == ["extra_enhancer", "extra_converter", "extra_close"], str(ex_cbs))
    handlers_names = [getattr(getattr(h, "callback", None), "__name__", "")
                      for h in app.handlers[0]]
    check("extra_close handleri ro'yxatda (regressiya yo'q)",
          "extras_close_callback" in handlers_names, str(sorted(set(handlers_names))[:6]))


# ===========================================================================
# TEST 4 — 🛡 LEGACY cab_* CALLBACK'LAR VA BUYRUQLAR CRASH BERMAYDI
# ===========================================================================
def test_legacy_callbacks_and_commands_still_work():
    print("== TEST 4: 🛡 legacy cab_* va eski buyruqlar xavfsiz ishlaydi ==")
    app = _build_app()

    # 4a) Har bir eski cab_* callback'i crash bermasdan javob beradi.
    for data in LEGACY_CABINET_CALLBACKS:
        fake = _FakeDB()
        q = _Query(data)
        ctx = _ctx("uz")
        error = None
        with _quiet(), _with_db(fake):
            try:
                _run(start_mod.cabinet_callback(_query_update(q), ctx))
            except Exception as exc:  # pragma: no cover - kutilmaydi
                error = f"{type(exc).__name__}: {exc}"
        check(f"legacy {data}: crash yo'q", error is None, str(error))
        responded = bool(q.edits) or bool(q.message.sent) or bool(q.answered)
        check(f"legacy {data}: foydalanuvchi javob oldi", responded, "")

    # 4b) Til almashtirish (legacy cab_lang_*) ham ishlaydi.
    for data, code in (("cab_lang_uz", "uz"), ("cab_lang_ru", "ru"),
                       ("cab_lang_en", "en")):
        fake = _FakeDB(language="uz")
        q = _Query(data)
        error = None
        with _quiet(), _with_db(fake):
            try:
                _run(start_mod.cabinet_callback(_query_update(q), _ctx("uz")))
            except Exception as exc:  # pragma: no cover - kutilmaydi
                error = f"{type(exc).__name__}: {exc}"
        check(f"legacy {data}: crash yo'q", error is None, str(error))
        check(f"legacy {data}: til bazaga yozildi ({code})",
              (USER_ID, code) in fake.set_language_calls or bool(q.edits),
              str(fake.set_language_calls))

    # 4c) Legacy reply-tugmalar va buyruqlar router'da SAQLANADI.
    legacy_buttons = (
        ("👤 Kabinet & Sozlamalar", "user_cabinet_menu"),
        ("🔄 Ballarni ulashish", "start_transfer_credits"),
        ("🚀 Do'stlarni taklif qilish", "user_invite_menu"),
        ("🎁 Kunlik bonus", "daily_bonus_handler"),
        ("🔤 Krill-Lotin konvertor", "start_converter"),
        ("⚙️ Qo'shimcha funksiyalar", "extras_menu"),
    )
    for label, target in legacy_buttons:
        with _quiet():
            names = _msg_entry_fn_names(app, label)
        check(f"legacy tugma {label!r} → {target}",
              target in names, str(sorted(names)))

    # Buyruqlar (CommandHandler) — offline rejimda PTB ``check_update`` bot
    # ``getMe`` javobini talab qiladi (username), shu sababli ro'yxatdagi
    # bog'lanish statik tekshiriladi: /buyruq → funksiya.
    from telegram.ext import CommandHandler
    commands = {}
    all_handlers = [h for g in sorted(app.handlers) for h in app.handlers[g]]
    # Buyruqlar global reyestrda ham, `main_conv` entry point'lari ichida ham
    # bo'lishi mumkin (/queue — suhbatni ochuvchi entry point).
    all_handlers += _entry_points(app)
    for handler in all_handlers:
        if isinstance(handler, CommandHandler):
            # Lambda (`guard_menu(u, c, queue_menu)`) uchun ham funksiya
            # nomi ``co_names`` orqali olinadi.
            names = _handler_fn_names(handler) or {type(handler).__name__}
            for cmd in handler.commands:
                commands.setdefault(cmd, []).extend(sorted(names))
    for command, target in (("settings", "user_cabinet_menu"),
                            ("profile", "user_cabinet_menu"),
                            ("queue", "queue_menu")):
        check(f"legacy buyruq /{command} → {target}",
              target in commands.get(command, []), str(commands.get(command)))

    # 4d) Legacy callback handleri (^cab_|^close_cabinet) ro'yxatda.
    patterns = [str(getattr(h, "pattern", "")) for h in app.handlers[0]
                if getattr(h, "pattern", None)]
    joined = " | ".join(patterns)
    check("cab_/close_cabinet callback handleri ro'yxatda",
          any("cab_" in p for p in patterns), joined[:160])
    check("stgs_ callback handleri ro'yxatda",
          any("stgs_" in p for p in patterns), joined[:160])

    # 4e) Eski «Kutilayotgan»/«Rejalashtirilgan» ekranlari bitta manbaga
    #     yo'naltiriladi (2-qadam qarori buzilmagan).
    import handlers.queue as queue_mod
    fake = _FakeDB()
    with _with_db(fake):
        text_q, kb_q = _run(queue_mod.scheduled_view(USER_ID, "uz", False))
    check("legacy cab_pending/cab_queue → yagona rejalashtirilgan ekran",
          bool(text_q) and kb_q is not None, str(text_q)[:60])


# ===========================================================================
# TEST 5 — 🌐 I18N PARITET + CALLBACK XAVFSIZLIGI
# ===========================================================================
def test_i18n_parity_and_callback_safety():
    print("== TEST 5: 🌐 UZ/RU/EN 100% paritet + callback xavfsizligi ==")

    report = settings_stats_parity_report()
    check("paritet: in_sync = True", report["in_sync"] is True, str(report)[:160])
    check("paritet: kalitlar 45+", report["keys"] >= 45, str(report["keys"]))
    check("paritet: missing yo'q", not any(report["missing"].values()),
          str(report["missing"]))
    check("paritet: extra yo'q", not any(report["extra"].values()),
          str(report["extra"]))
    check("paritet: format-arg mosligi", not report["format_mismatch"],
          str(report["format_mismatch"]))
    check("paritet: bo'sh matn yo'q", not report["empty"], str(report["empty"]))

    # 5a) Yangi sozlamalar/vositalar kalitlari uchala tilda to'ldirilgan.
    for key in SETTINGS_MENU_BUTTON_KEYS + TOOLS_MENU_BUTTON_KEYS:
        values = [settings_stats_t(key, lang) for lang in LANGS]
        check(f"i18n: {key} uchala tilda mavjud",
              all(bool(v) and v != key for v in values), str(values))

    # 5b) Menyu tugmalari UZ/RU/EN da AYNAN bir xil callback'larga ega
    #     (routing tilga bog'liq emas).
    base = _cbs(get_settings_hub_keyboard("uz"))
    tools_base = _cbs(get_tools_keyboard("uz"))
    for lang in LANGS:
        check(f"[{lang}] hub callback'lari uz bilan bir xil",
              _cbs(get_settings_hub_keyboard(lang)) == base,
              str(_cbs(get_settings_hub_keyboard(lang))))
        check(f"[{lang}] vositalar callback'lari uz bilan bir xil",
              _cbs(get_tools_keyboard(lang)) == tools_base,
              str(_cbs(get_tools_keyboard(lang))))

    # 5c) Har bir callback Telegram 64-bayt chegarasiga mos.
    keyboards = []
    for lang in LANGS:
        keyboards.extend([get_settings_hub_keyboard(lang), get_tools_keyboard(lang),
                          get_settings_back_keyboard(lang)])
    for kb in keyboards:
        for cbdata in _cbs(kb):
            check(f"cb xavfsiz: {cbdata[:28]}… ({callback_byte_len(cbdata)} bayt)",
                  is_callback_safe(cbdata)
                  and callback_byte_len(cbdata) <= CALLBACK_DATA_MAX_BYTES, "")

    # 5d) Yangi callback'lar kanonik `stgs_` prefiksida (fail-closed routing).
    for cbdata in list(CB_SETTINGS_HUB) + list(CB_TOOLS_HUB):
        check(f"kanonik prefiks: {cbdata}",
              cbdata.startswith("stgs_") or cbdata.startswith("extra_"), cbdata)


# ===========================================================================
# MAIN
# ===========================================================================
def main():
    # speech: bo'sh qator — chiqish o'qishga qulay bo'lishi uchun.
    test_settings_hub_has_no_legacy_duplicates()
    test_hub_actions_open_their_flows()
    test_tools_submenu_wires_converter_and_enhancer()
    test_legacy_callbacks_and_commands_still_work()
    test_i18n_parity_and_callback_safety()

    print(f"\nJAMI: o'tdi={PASSED}, xato={FAILURES}")
    if FAILURES:
        sys.exit(1)
    print("Barcha 3-qadam refaktor testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
