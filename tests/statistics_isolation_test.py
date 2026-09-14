#!/usr/bin/env python3
"""📊 STATISTIKA IZOLYATSIYASI — shaxsiy statistika vs ADMIN statistikasi.

Bu test «📊 Statistika» va admin «To'liq statistika» ekranlarining
DISPATCHER darajasida chalkashib ketmasligini qat'iy qo'riqlaydi.

Tarix: avval asosiy menyudagi «📊 Statistika» tugmasi
``handlers/__init__.py::statistics_button`` ichida ADMIN_IDS bo'yicha
shartlangan edi — admin foydalanuvchi o'z shaxsiy hisoboti o'rniga ADMIN
PANEL statistikasini («Jami foydalanuvchilar», «Homiy kanallar», «Bekor
qilingan postlar») ko'rardi. Endi bu qat'iy ajratildi.

Tekshiriladigan qoidalar:
  T1) Asosiy menyu «📊 Statistika» (oddiy foydalanuvchi) — matnda
      «Jami foydalanuvchilar» / «Homiy kanallar» / «Bekor qilingan»
      va boshqa admin markerlari YO'Q (QAT'IY assert).
  T2) ADMIN ham shu tugmani bosganda — ADMIN STATISTIKASI CHIQMAYDI
      (asosiy regressiya qo'riqoni).
  T3) Matnda FAQAT foydalanuvchining O'Z ma'lumotlari bor — 4 ta shaxsiy
      qator va ularning qiymatlari get_user_overview_stats /
      get_user_credits dan keladi; hech qanday tizim (bot) hisoboti yo'q.
  T4) Uchala tilda (uz/ru/en) ham izolyatsiya saqlanadi.
  T5) Tugmalar: [📈 Kanal bo'yicha batafsil] [◀️ Orqaga] = an_detail/an_close.
  T6) Admin (bot bo'yicha) statistikasi FAQAT ⚙️ Admin Panel →
      «📊 To'liq statistika» ichida; admin panel klaviaturasida endi
      oddiy «📊 Statistika» yorlig'i YO'Q.
  T7) ``statistics_button`` manbasida ADMIN_IDS sharti yo'q (bir yo'nalish).
  T8) Haqiqiy router: «📊 Statistika» (uz/ru/en) → show_user_statistics;
      «📊 To'liq statistika» → show_statistics.
  T9) Kanal analitikasi: an_detail → kanal tanlash; an_overview → shaxsiy
      statistikaga QAYTISH.
  T10) Registry (MENU_TEXTS): «📊 Statistika» — yagona egalik (statistics),
      admin_stats oilasida bu yorliq YO'Q.
  T11) i18n UZ/RU/EN 100% paritet (in_sync: True).

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/statistics_isolation_test.py             # alohida
"""
import asyncio
import contextlib
import importlib
import logging
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:STATS_ISOLATION_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10099")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import database as db_mod  # noqa: E402
from telegram import Update  # noqa: E402
from telegram.ext import ConversationHandler, MessageHandler  # noqa: E402

import handlers  # noqa: E402,F401 — barcha handlerlarni reyestrga qo'yadi
import handlers.admin as ADM  # noqa: E402

analytics_mod = importlib.import_module("handlers.analytics")
statistics_mod = importlib.import_module("handlers.statistics")

from keyboards.default import (  # noqa: E402
    BTN_FULL_STATS, BTN_STATS, BTN_STATISTICS, BTN_STATISTICS_EN,
    BTN_STATISTICS_RU, MENU_TEXTS, get_admin_panel_keyboard, get_main_keyboard,
)
from keyboards.inline import (  # noqa: E402
    get_user_overview_keyboard, get_user_stats_keyboard,
)
from locales.translations import get_text  # noqa: E402
from translations import (  # noqa: E402
    MY_STATS_ROW_KEYS, CB_STATS_DETAIL, settings_stats_parity_report,
    settings_stats_t,
)

LANGS = ("uz", "ru", "en")
USER_ID = 777777          # oddiy foydalanuvchi (admin EMAS)
ADMIN_ID = 123456789      # config.ADMIN_ID → OWNER
CH_ID = "-100200"

# ADMIN (bot bo'yicha) STATISTIKA markerlari — handlers/admin.py dagi
# ``_build_full_stats_text`` chizadigan qatorlar. Bular asosiy menyudagi
# «📊 Statistika» ekranida HECH QACHON paydo bo'lmasligi kerak.
ADMIN_STATS_MARKERS = (
    "Jami foydalanuvchilar",
    "Homiy kanallar",
    "Bekor qilingan",
    "To'liq Statistika",
    "To'liq statistika",
    "Kutilayotgan postlar",
    "Yuborilgan postlar",
    "PRO obunachilar",
    "Stars tushumi",
    "Xatolik:",
    # RU/EN variantlari — admin ekrani boshqa tilda chizilsa ham ushlanadi.
    "Всего пользователей",
    "Спонсорские каналы",
    "Отменено",
    "Total users",
    "Sponsor channels",
    "Cancelled",
)

# Foydalanuvchining O'Z ma'lumotlari (deterministik mock qiymatlari).
MY_STATS = {
    "channels": 3,
    "created_posts": 42,
    "scheduled_posts": 5,
    "ai_requests": 12,
    "credits_spent": 12,
}
MY_CREDITS = 17

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
# SOXTA TELEGRAM OB'EKTLARI
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


def _cbs(markup):
    if markup is None:
        return []
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _labels(markup):
    if markup is None:
        return []
    return [b.text for row in markup.inline_keyboard for b in row]


def _plain(text):
    """HTML teglarini tozalaydi — matn solishtirish oson bo'lishi uchun."""
    for tag in ("<b>", "</b>", "<i>", "</i>", "<code>", "</code>"):
        text = text.replace(tag, "")
    return text


class _FakeDB:
    """``database.run_db`` mock — deterministik va chaqiruvlarni yozadi.

    ``get_system_stats`` (ADMIN statistikasi) chaqirilishi ALOHIDA kuzatiladi:
    asosiy menyu «📊 Statistika» oqimida u HECH QACHON chaqirilmasligi kerak.
    """

    def __init__(self, overview=None, credits=MY_CREDITS):
        self.calls = []
        self.system_stats_calls = 0
        self.overview = dict(overview if overview is not None else MY_STATS)
        self.credits = credits

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append(name)

        if name == "get_system_stats":
            self.system_stats_calls += 1
            return {"users": 100, "channels": 12, "sponsors": 2, "pending": 5,
                    "sent": 40, "cancelled": 3, "failed": 1}
        if name == "get_admin_dashboard_stats":
            return {"users": 100, "pro_subscribers": 4, "channels": 12,
                    "posts_today": 6, "pending_posts": 5, "stars_revenue": 250}
        if name == "get_user_overview_stats":
            return dict(self.overview)
        if name == "get_user_credits":
            return self.credits
        if name == "get_user_language":
            return "uz"
        if name == "is_premium":
            return False
        if name == "is_admin":
            return False
        # Majburiy obuna tekshiruvi (guard_entry → _deny_if_unsubscribed):
        # homiy kanallar yo'q → foydalanuvchi obunachi hisoblanadi va
        # «📊 Statistika» ekrani normal ochiladi.
        if name == "get_sponsor_channels":
            return []
        if name == "get_ads_full":
            return []
        if name == "get_user_channels":
            return [(CH_ID, "Test Kanali"), ("-100201", "Ikkinchi kanal")]
        if name == "get_user_channel_list_for_analytics":
            return [(CH_ID, "Test Kanali"), ("-100201", "Ikkinchi kanal")]
        if name == "get_channel_post_stats":
            return {"sent_7d": 1, "sent_30d": 2, "sent_all": 3, "pending": 0,
                    "peak_hours": [], "type_distribution": {}}
        if name == "get_recent_posts":
            return []
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


def _press_statistics(user_id=USER_ID, lang="uz"):
    """Asosiy menyudagi «📊 Statistika» tugmasini bosishni simulyatsiya qiladi.

    HAQIQIY dispatcher (``handlers.statistics_button``) chaqiriladi — shunda
    test aynan production routing'ini tekshiradi.

    Qaytadi: ``(soxta_db, xabar, holat)``.
    """
    fake = _FakeDB()
    msg = _Msg()
    label = get_text("btn_statistics", lang)
    with _with_db(fake), _quiet():
        state = _run(handlers.statistics_button(
            _msg_update(msg, label, user_id=user_id), _ctx(lang)))
    return fake, msg, state


def _assert_no_admin_stats(tag, fake, text):
    """QAT'IY izolyatsiya assertlari — matn va DB chaqiruvlari bo'yicha."""
    leaked = [m for m in ADMIN_STATS_MARKERS if m in text]
    check(f"{tag}: ADMIN statistikasi markerlari YO'Q", not leaked, f"topildi={leaked}")
    for marker in ("Jami foydalanuvchilar", "Homiy kanallar", "Bekor qilingan"):
        check(f"{tag}: QAT'IY — {marker!r} yo'q", marker not in text, text[:200])
    check(f"{tag}: db.get_system_stats (ADMIN) CHAQIRILMADI",
          fake.system_stats_calls == 0, f"{fake.system_stats_calls} marta chaqirildi")
    check(f"{tag}: chaqiruvlar orasida get_system_stats yo'q",
          "get_system_stats" not in fake.calls, str(fake.calls))


#: Har bir shaxsiy qator kaliti → kutilgan qiymat (mock ma'lumotlardan).
MY_STATS_EXPECTED = {
    "ss_my_channels": MY_STATS["channels"],
    "ss_my_created": MY_STATS["created_posts"],
    "ss_my_scheduled": MY_STATS["scheduled_posts"],
    "ss_my_credits": MY_CREDITS,
}


def _assert_personal_only(tag, text):
    """Matnda FAQAT foydalanuvchining O'Z ma'lumotlari borligini tekshiradi."""
    plain = _plain(text)
    for key in MY_STATS_ROW_KEYS:
        # Qator shabloni kutilgan qiymat bilan formatlanadi va AYNAN shu
        # ko'rinishda ekranda bo'lishi kerak (faqat foydalanuvchi ma'lumoti).
        row = settings_stats_t(key, "uz", n=MY_STATS_EXPECTED[key])
        check(f"{tag}: shaxsiy qator bor — {row!r}", row in text, plain[:240])
    check(f"{tag}: kanallar soni (3) ko'rsatilgan", str(MY_STATS["channels"]) in plain, plain[:200])
    check(f"{tag}: yaratilgan postlar (42) ko'rsatilgan", str(MY_STATS["created_posts"]) in plain, plain[:200])
    check(f"{tag}: rejalashtirilgan (5) ko'rsatilgan", str(MY_STATS["scheduled_posts"]) in plain, plain[:200])
    check(f"{tag}: qolgan kreditlar (17) ko'rsatilgan", str(MY_CREDITS) in plain, plain[:200])
    check(f"{tag}: sarflangan kreditlar (12) ekranda YO'Q — faqat QOLGAN kredit",
          "Sarflangan" not in plain and "Потрачено" not in plain, plain[:200])
    # Shaxsiy ekran aynan 5 qatordan iborat: sarlavha + 4 ta ko'rsatkich.
    check(f"{tag}: ekran 5 qatordan iborat (sarlavha + 4 ko'rsatkich)",
          len([ln for ln in text.split("\n") if ln.strip()]) == 5, repr(text)[:300])


# ===========================================================================
# T1 — ODDIY FOYDALANUVCHI: asosiy menyu «📊 Statistika»
# ===========================================================================
def test_t1_regular_user_no_admin_stats():
    header("T1", "Asosiy menyu «📊 Statistika» (oddiy user) — ADMIN matni YO'Q")

    fake, msg, state = _press_statistics(USER_ID, "uz")
    check("T1: ekran ochildi", bool(msg.sent), str(msg.sent)[:120])
    check("T1: holat ANALYTICS_VIEW", state == analytics_mod.ANALYTICS_VIEW, str(state))

    text = msg.sent[-1]["text"] if msg.sent else ""
    _assert_no_admin_stats("T1(user)", fake, text)
    check("T1(user): get_user_overview_stats chaqirildi",
          "get_user_overview_stats" in fake.calls, str(fake.calls))
    check("T1(user): get_user_credits chaqirildi",
          "get_user_credits" in fake.calls, str(fake.calls))
    _assert_personal_only("T1(user)", text)

    check("T1(user): sarlavha — «Sizning statistikangiz»",
          "Sizning statistikangiz" in _plain(text), _plain(text)[:120])
    kb = msg.sent[-1]["reply_markup"] if msg.sent else None
    check("T1(user): tugmalar [📈 Kanal bo'yicha batafsil][◀️ Orqaga]",
          _cbs(kb) == [CB_STATS_DETAIL, "an_close"], str(_cbs(kb)))
    check("T1(user): tugma yorliqlari i18n'dan",
          _labels(kb) == [settings_stats_t("ss_btn_channel_detail", "uz"),
                          settings_stats_t("ss_btn_back", "uz")], str(_labels(kb)))


# ===========================================================================
# T2 — ADMIN: asosiy menyudan ham SHAXSIY statistika chiqadi
# ===========================================================================
def test_t2_admin_main_menu_is_personal():
    header("T2", "ADMIN ham asosiy menyuda SHAXSIY hisobotni ko'radi (regressiya)")

    fake, msg, state = _press_statistics(ADMIN_ID, "uz")
    check("T2(admin): ekran ochildi", bool(msg.sent), str(msg.sent)[:120])

    text = msg.sent[-1]["text"] if msg.sent else ""
    _assert_no_admin_stats("T2(admin)", fake, text)
    _assert_personal_only("T2(admin)", text)
    check("T2(admin): get_user_overview_stats chaqirildi",
          "get_user_overview_stats" in fake.calls, str(fake.calls))

    kb = msg.sent[-1]["reply_markup"] if msg.sent else None
    check("T2(admin): tugmalar ham shaxsiy (an_detail/an_close)",
          _cbs(kb) == [CB_STATS_DETAIL, "an_close"], str(_cbs(kb)))

    # Oddiy foydalanuvchi va admin bir xil ekranni ko'radi (matn bir xil).
    _, user_msg, _ = _press_statistics(USER_ID, "uz")
    check("T2: admin va oddiy user matni AYNAN bir xil",
          (user_msg.sent[-1]["text"] if user_msg.sent else None) == text,
          f"admin={text[:80]!r} user={(user_msg.sent[-1]['text'] if user_msg.sent else '')[:80]!r}")

    # /stats buyrug'i va show_statistics o'zi fail-closed qoladi — bu
    # izolyatsiyani buzmaydi (admin panel ichidagi yo'l).
    fake_leak = _FakeDB()
    msg_leak = _Msg()
    with _with_db(fake_leak), _quiet():
        _run(ADM.show_statistics(_msg_update(msg_leak, user_id=USER_ID), _ctx("uz")))
    check("T2: show_statistics oddiy user uchun fail-closed (xabar yo'q)",
          not msg_leak.sent, str(msg_leak.sent)[:120])


# ===========================================================================
# T3/T4 — UCHALA TILDA IZOLYATSIYA
# ===========================================================================
def test_t3_all_languages_isolated():
    header("T3", "UZ/RU/EN — har uchala tilda admin matni YO'Q")

    for lang in LANGS:
        fake, msg, _state = _press_statistics(USER_ID, lang)
        text = msg.sent[-1]["text"] if msg.sent else ""
        _assert_no_admin_stats(f"T3[{lang}]", fake, text)
        check(f"T3[{lang}]: ekran bo'sh emas", bool(text.strip()), repr(text)[:120])
        check(f"T3[{lang}]: shaxsiy sarlavha (ss_my_title) bor",
              settings_stats_t("ss_my_title", lang) in text, _plain(text)[:160])
        for key in MY_STATS_ROW_KEYS:
            row = settings_stats_t(key, lang, n=1)
            check(f"T3[{lang}]: qator shabloni formatlanadi — {key}",
                  "{" not in row and bool(row.strip()), row)


# ===========================================================================
# T4 — BUILDER DARAJASIDA IZOLYATSIYA (to'g'ridan-to'g'ri chaqiruv)
# ===========================================================================
def test_t4_builder_is_pure():
    header("T4", "build_user_overview_text — admin maydonlarini O'Z ICHIGA OLMAYDI")

    for lang in LANGS:
        text = statistics_mod.build_user_overview_text(MY_STATS, MY_CREDITS, lang)
        leaked = [m for m in ADMIN_STATS_MARKERS if m in text]
        check(f"T4[{lang}]: admin markeri yo'q", not leaked, str(leaked))
        check(f"T4[{lang}]: 5 qator (sarlavha + 4)", len(text.split("\n")) == 5, repr(text)[:240])
        check(f"T4[{lang}]: sarlavha ss_my_title",
              text.split("\n")[0] == settings_stats_t("ss_my_title", lang), text.split("\n")[0])

    # Bo'sh / None ma'lumot ham xavfsiz — nollar chiziladi, crash yo'q.
    empty = statistics_mod.build_user_overview_text(None, None, "uz")
    check("T4: stats=None xavfsiz (nollar)", "0" in _plain(empty), _plain(empty)[:160])
    check("T4: stats=None — 5 qator", len(empty.split("\n")) == 5, repr(empty)[:240])

    # Admin builder'i esa O'Z navbatida shaxsiy qatorlarni chizmaydi —
    # ikki ekran matnshunosligi hech qayerda kesishmaydi.
    adm_text = ADM._build_full_stats_text(
        {"users": 100, "channels": 12, "sponsors": 2, "pending": 5,
         "sent": 40, "cancelled": 3, "failed": 1})
    personal_rows = [settings_stats_t(k, "uz", n=1) for k in MY_STATS_ROW_KEYS]
    overlap = [r for r in personal_rows if r in adm_text]
    check("T4: admin builder'da shaxsiy qatorlar YO'Q", not overlap, str(overlap))
    check("T4: admin builder'da admin markerlari BOR (ekran o'z joyida)",
          all(m in adm_text for m in ("Jami foydalanuvchilar", "Homiy kanallar",
                                      "Bekor qilingan")), adm_text[:160])


# ===========================================================================
# T5 — ADMIN PANEL: bot statistikasi faqat shu yerda
# ===========================================================================
def test_t5_admin_panel_full_stats():
    header("T5", "Admin panel → «📊 To'liq statistika» (yagona admin yo'li)")

    kb_rows = [[b.text for b in row] for row in get_admin_panel_keyboard().keyboard]
    flat = [t for row in kb_rows for t in row]
    check("T5: admin panel'da «📊 To'liq statistika» bor", BTN_FULL_STATS in flat, str(flat))
    check("T5: admin panel'da oddiy «📊 Statistika» YO'Q", BTN_STATS not in flat, str(flat))
    check("T5: admin statistika yorlig'i shaxsiy yorliqdan farq qiladi",
          BTN_FULL_STATS != BTN_STATISTICS, f"{BTN_FULL_STATS!r} vs {BTN_STATISTICS!r}")

    # Asosiy 6 tugmali menyuda esa faqat shaxsiy «📊 Statistika» turadi.
    for lang in LANGS:
        for is_admin in (False, True):
            menu = get_main_keyboard(is_admin, lang=lang)
            labels = [b.text for row in menu.keyboard for b in row]
            check(f"T5[{lang},admin={is_admin}]: menyuda «📊 Statistika» bor",
                  get_text("btn_statistics", lang) in labels, str(labels))
            check(f"T5[{lang},admin={is_admin}]: menyuda «📊 To'liq statistika» YO'Q",
                  BTN_FULL_STATS not in labels, str(labels))

    # «📊 To'liq statistika» bosilganda HAQIQATAN admin statistikasi chiqadi.
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        _run(ADM.show_statistics(_msg_update(msg, user_id=ADMIN_ID), _ctx("uz")))
    adm_text = msg.sent[-1]["text"] if msg.sent else ""
    check("T5: admin panel tugmasi → get_system_stats chaqirildi",
          fake.system_stats_calls == 1, str(fake.calls))
    check("T5: admin panel ekranida «Jami foydalanuvchilar» BOR",
          "Jami foydalanuvchilar" in adm_text, adm_text[:160])
    check("T5: admin panel ekranida «Homiy kanallar» BOR",
          "Homiy kanallar" in adm_text, adm_text[:160])
    check("T5: admin panel ekranida «Bekor qilingan» BOR",
          "Bekor qilingan" in adm_text, adm_text[:160])


# ===========================================================================
# T6 — DISPATCHER MANBASI: ADMIN sharti YO'Q
# ===========================================================================
def test_t6_dispatcher_has_no_admin_branch():
    header("T6", "statistics_button — ADMIN_IDS shartisiz, yagona yo'nalish")

    code = getattr(getattr(handlers, "statistics_button", None), "__code__", None)
    check("T6: statistics_button mavjud", code is not None)
    names = set(getattr(code, "co_names", ()))
    check("T6: show_user_statistics chaqiriladi",
          "show_user_statistics" in names, str(sorted(names)))
    check("T6: show_statistics (ADMIN) chaqirilmaydi",
          "show_statistics" not in names, str(sorted(names)))
    check("T6: start_analytics (eski oqim) chaqirilmaydi",
          "start_analytics" not in names, str(sorted(names)))
    check("T6: ADMIN_IDS_SET bo'yicha shartlash YO'Q",
          "ADMIN_IDS_SET" not in names, str(sorted(names)))
    check("T6: admin_panel_menu'ga yo'l YO'Q",
          "admin_panel_menu" not in names, str(sorted(names)))

    # Modul darajasida: handlers.statistics faqat shaxsiy ma'lumotlarni o'qiydi.
    src = Path(ROOT / "handlers" / "statistics.py").read_text(encoding="utf-8")
    check("T6: handlers/statistics.py get_system_stats ISHLATMAYDI",
          "get_system_stats" not in src, "get_system_stats topildi")
    check("T6: handlers/statistics.py get_user_overview_stats ishlatadi",
          "get_user_overview_stats" in src)
    check("T6: handlers/statistics.py get_user_credits ishlatadi",
          "get_user_credits" in src)


# ===========================================================================
# T7 — HAQIQIY ROUTER: yorliq → handler
# ===========================================================================
def test_t7_real_router_routes():
    header("T7", "Haqiqiy router: yorliq → handler (uz/ru/en)")

    from telegram.ext import ApplicationBuilder
    from handlers import register_all_handlers

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:STATS_ISOLATION_ROUTER").build()
    register_all_handlers(app)

    def _routed(update):
        for group in sorted(app.handlers):
            for handler in app.handlers[group]:
                try:
                    if handler.check_update(update):
                        cb = getattr(handler, "callback", None)
                        found = set()
                        code = getattr(cb, "__code__", None)
                        if code is not None:
                            found.update(code.co_names)
                        if getattr(cb, "__name__", "") != "<lambda>":
                            found.add(cb.__name__)
                        return found
                except Exception:
                    continue
        return set()

    def _text_update(text, user_id=USER_ID):
        return Update.de_json({
            "update_id": 1,
            "message": {
                "message_id": 1, "date": 0, "text": text,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "T"},
            },
        }, None)

    # Asosiy menyu «📊 Statistika» — uchala tilda ham statistics_button,
    # va u ichida show_user_statistics (admin statistikasi emas).
    for label in (BTN_STATISTICS, BTN_STATISTICS_RU, BTN_STATISTICS_EN):
        names = _routed(_text_update(label))
        check(f"T7: «{label}» → statistics_button",
              "statistics_button" in names, str(sorted(names)))
        check(f"T7: «{label}» show_statistics'ga YO'NALTIRILMAYDI",
              "show_statistics" not in names, str(sorted(names)))

    # Admin uchun ham xuddi shu (router darajasida ADMIN farqi yo'q).
    names_admin = _routed(_text_update(BTN_STATISTICS, user_id=ADMIN_ID))
    check("T7: admin «📊 Statistika» ham statistics_button",
          "statistics_button" in names_admin, str(sorted(names_admin)))
    check("T7: admin «📊 Statistika» show_statistics emas",
          "show_statistics" not in names_admin, str(sorted(names_admin)))

    # Admin «📊 To'liq statistika» — show_statistics.
    names_full = _routed(_text_update(BTN_FULL_STATS, user_id=ADMIN_ID))
    check(f"T7: «{BTN_FULL_STATS}» → show_statistics",
          "show_statistics" in names_full, str(sorted(names_full)))
    check(f"T7: «{BTN_FULL_STATS}» statistics_button emas",
          "statistics_button" not in names_full, str(sorted(names_full)))

    # Bir yorliq — BITTA maxsus handler. ConversationHandler (ichida
    # all_menu_jumps orqali o'zi shu handlerga delegatsiya qiladi) va eng
    # pastdagi ``unknown_message_fallback`` catch-all hisobga olinmaydi:
    # ular har qanday matn uchun mos keladi.
    upd = _text_update(BTN_STATISTICS)
    specific = []
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            if not isinstance(handler, MessageHandler):
                continue
            name = getattr(getattr(handler, "callback", None), "__name__", "")
            if name == "unknown_message_fallback":
                continue
            try:
                if handler.check_update(upd):
                    specific.append(handler)
            except Exception:
                continue
    check("T7: «📊 Statistika» uchun aynan BITTA maxsus handler mos keladi",
          len(specific) == 1, f"{len(specific)} ta handler mos keldi")
    check("T7: o'sha handler statistics_button'ga tegishli",
          len(specific) == 1 and "statistics_button" in
          set(getattr(getattr(specific[0], "callback", None), "__code__",
                      SimpleNamespace(co_names=())).co_names),
          str(specific)[:200])


# ===========================================================================
# T8 — KANAL ANALITIKASI KELIB CHIQISHI (an_detail / an_overview)
# ===========================================================================
def test_t8_channel_analytics_round_trip():
    header("T8", "📈 Kanal bo'yicha batafsil → [◀️ Orqaga] → shaxsiy statistika")

    # 1) Shaxsiy ekrandan [📈 Kanal bo'yicha batafsil] → kanal tanlash.
    fake = _FakeDB()
    msg = _Msg()
    with _with_db(fake), _quiet():
        _run(handlers.statistics_button(_msg_update(msg, BTN_STATISTICS), _ctx("uz")))
        q = _Query(CB_STATS_DETAIL, message=msg)
        state = _run(analytics_mod.analytics_view_callback(_query_update(q), _ctx("uz")))
    check("T8: an_detail → ANALYTICS_CHOOSE", state == analytics_mod.ANALYTICS_CHOOSE, str(state))
    choose_kb = q.message.sent[-1]["reply_markup"] if q.message.sent else None
    check("T8: kanal tanlash ro'yxati chizildi", bool(q.message.sent), str(q.message.sent)[:120])
    check("T8: ro'yxatda kanallar bor (an_ch:)",
          any(str(c).startswith("an_ch:") for c in _cbs(choose_kb)), str(_cbs(choose_kb)))
    check("T8: ro'yxatda [◀️ Orqaga] = an_overview",
          "an_overview" in _cbs(choose_kb), str(_cbs(choose_kb)))

    # 2) Kanal tanlanadi → kanal dashboard'i; [◀️ Orqaga] = an_overview.
    q2 = _Query(f"an_ch:{CH_ID}", message=msg)
    with _with_db(fake), _quiet():
        state2 = _run(analytics_mod.analytics_channel_chosen(_query_update(q2), _ctx("uz")))
    check("T8: kanal tanlandi → ANALYTICS_VIEW", state2 == analytics_mod.ANALYTICS_VIEW, str(state2))
    dash_kb = q2.message.sent[-1]["reply_markup"] if q2.message.sent else None
    check("T8: dashboard'da [◀️ Orqaga] = an_overview (shaxsiy ekranga)",
          "an_overview" in _cbs(dash_kb), str(_cbs(dash_kb)))
    check("T8: dashboard [◀️ Orqaga] endi asosiy menyuga EMAS (an_close yo'q)",
          "an_close" not in _cbs(dash_kb), str(_cbs(dash_kb)))

    # 3) [◀️ Orqaga] → SHAXSIY statistika qaytadi (admin matni yo'q).
    q3 = _Query("an_overview", message=msg)
    with _with_db(fake), _quiet():
        state3 = _run(analytics_mod.analytics_view_callback(_query_update(q3), _ctx("uz")))
    back_text = q3.message.sent[-1]["text"] if q3.message.sent else ""
    check("T8: an_overview → ANALYTICS_VIEW (dialog yopilmadi)",
          state3 == analytics_mod.ANALYTICS_VIEW, str(state3))
    check("T8: qaytgan ekran — shaxsiy statistika",
          "Sizning statistikangiz" in _plain(back_text), _plain(back_text)[:160])
    _assert_no_admin_stats("T8(an_overview)", fake, back_text)
    back_kb = q3.message.sent[-1]["reply_markup"] if q3.message.sent else None
    check("T8: qaytgan ekran tugmalari an_detail/an_close",
          _cbs(back_kb) == [CB_STATS_DETAIL, "an_close"], str(_cbs(back_kb)))

    # 4) an_close — asosiy 6 tugmali menyuga chiqadi.
    q4 = _Query("an_close", message=msg)
    with _with_db(fake), _quiet():
        state4 = _run(analytics_mod.analytics_view_callback(_query_update(q4), _ctx("uz")))
    check("T8: an_close → ConversationHandler.END", state4 == ConversationHandler.END, str(state4))
    closed = q4.message.sent[-1] if q4.message.sent else {}
    closed_labels = [b.text for row in (closed.get("reply_markup").keyboard
                                        if closed.get("reply_markup") else []) for b in row]
    check("T8: an_close — asosiy 6 tugmali menyu qaytdi",
          len(closed_labels) == 6, str(closed_labels))


# ===========================================================================
# T9 — ANALYTICS_VIEW / ANALYTICS_CHOOSE FSM ROUTING
# ===========================================================================
def test_t9_fsm_routing_registered():
    header("T9", "FSM: an_detail / an_overview handlerlari ro'yxatdan o'tgan")

    from telegram.ext import ApplicationBuilder, CallbackQueryHandler, ConversationHandler
    from handlers import register_all_handlers

    # ``main_conv`` modul darajasida eksport qilinmaydi — uni haqiqiy
    # registratsiyadan olamiz (register_all_handlers orqali).
    app_holder = {}

    class _Recorder:
        def add_handler(self, h, group=0):
            app_holder.setdefault("handlers", []).append((group, h))

    register_all_handlers(_Recorder())
    convs = [h for _g, h in app_holder["handlers"] if isinstance(h, ConversationHandler)]
    check("T9: main ConversationHandler ro'yxatdan o'tgan", len(convs) >= 1, str(len(convs)))
    main_conv = convs[0]

    def _cb_update(data):
        return Update.de_json({
            "update_id": 2,
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

    for state, datas in (
        (analytics_mod.ANALYTICS_VIEW, ("an_detail", "an_overview", "an_refresh", "an_close")),
        (analytics_mod.ANALYTICS_CHOOSE, ("an_overview", "an_close", f"an_ch:{CH_ID}")),
    ):
        state_handlers = main_conv.states.get(state, [])
        for data in datas:
            upd = _cb_update(data)
            ok = any(h.check_update(upd) not in (None, False) for h in state_handlers)
            check(f"T9: state {state} — «{data}» ishlanadi", ok, str(data))

    # Global reyestrda ham adm_ callback'lari admin uchun qoladi
    # (admin panel izolyatsiyasi buzilmagan).
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:STATS_ISOLATION_FSM").build()
    register_all_handlers(app)
    adm_patterns = [
        str(getattr(getattr(h, "pattern", None), "pattern", "") or "")
        for g in sorted(app.handlers) for h in app.handlers[g]
        if isinstance(h, CallbackQueryHandler)
    ]
    check("T9: adm_ callback handleri ro'yxatda (admin panel ishlashda davom etadi)",
          any("adm_" in p for p in adm_patterns), str(adm_patterns)[:200])


# ===========================================================================
# T10 — REGISTRY: «📊 Statistika» yagona egalik
# ===========================================================================
def test_t10_registry_single_ownership():
    header("T10", "MENU_TEXTS: «📊 Statistika» — yagona egalik")

    stats_family = MENU_TEXTS.get("statistics", ())
    admin_family = MENU_TEXTS.get("admin_stats", ())

    for label in (BTN_STATISTICS, BTN_STATISTICS_RU, BTN_STATISTICS_EN):
        check(f"T10: «{label}» statistics oilasida", label in stats_family, str(stats_family))
        check(f"T10: «{label}» admin_stats oilasida YO'Q", label not in admin_family, str(admin_family))

    check(f"T10: «{BTN_FULL_STATS}» admin_stats oilasida",
          BTN_FULL_STATS in admin_family, str(admin_family))
    check(f"T10: «{BTN_FULL_STATS}» statistics oilasida YO'Q",
          BTN_FULL_STATS not in stats_family, str(stats_family))

    # Butun registry bo'yicha «📊 Statistika» faqat BITTA oilaga tegishli.
    owners = [action for action, texts in MENU_TEXTS.items() if BTN_STATISTICS in texts]
    check("T10: «📊 Statistika» butun registry'da BITTA egaga tegishli",
          owners == ["statistics"], str(owners))
    owners_ru = [action for action, texts in MENU_TEXTS.items() if BTN_STATISTICS_RU in texts]
    check("T10: «📊 Статистика» ham BITTA egaga tegishli",
          owners_ru == ["statistics"], str(owners_ru))

    # Ikkala oila umuman kesishmaydi.
    overlap = sorted(set(stats_family) & set(admin_family))
    check("T10: statistics va admin_stats oilalari kesishmaydi", not overlap, str(overlap))

    # Eski shaxsiy statistika klaviaturasi (legacy «📊 Analitika») buzilmagan.
    check("T10: legacy get_user_stats_keyboard hali ham an_refresh/an_close",
          _cbs(get_user_stats_keyboard("uz")) == ["an_refresh", "an_close"],
          str(_cbs(get_user_stats_keyboard("uz"))))
    check("T10: yangi get_user_overview_keyboard an_detail/an_close",
          _cbs(get_user_overview_keyboard("uz")) == [CB_STATS_DETAIL, "an_close"],
          str(_cbs(get_user_overview_keyboard("uz"))))


# ===========================================================================
# T11 — I18N PARITET
# ===========================================================================
def test_t11_i18n_parity():
    header("T11", "translations/settings_stats.py — UZ/RU/EN 100% paritet")

    report = settings_stats_parity_report()
    check("T11: in_sync = True", report["in_sync"] is True, str(report)[:300])
    check("T11: missing yo'q", not any(report["missing"].values()), str(report["missing"]))
    check("T11: extra yo'q", not any(report["extra"].values()), str(report["extra"]))
    check("T11: format_mismatch yo'q", not report["format_mismatch"], str(report["format_mismatch"]))
    check("T11: bo'sh matn yo'q", not report["empty"], str(report["empty"]))

    required = ("ss_my_title", "ss_my_channels", "ss_my_created",
                "ss_my_scheduled", "ss_my_credits", "ss_btn_channel_detail")
    from translations.settings_stats import SETTINGS_STATS_I18N
    for lang in LANGS:
        table = SETTINGS_STATS_I18N.get(lang, {})
        missing = [k for k in required if k not in table]
        check(f"T11[{lang}]: shaxsiy statistika kalitlari to'liq", not missing, str(missing))

    # Callback'lar tilga bog'liq emas va 64 bayt chegarasida.
    from keyboards.callback_data import is_callback_safe
    for lang in LANGS:
        kb = get_user_overview_keyboard(lang)
        cbs = _cbs(kb)
        check(f"T11[{lang}]: callback'lar bir xil (tilga bog'liq emas)",
              cbs == [CB_STATS_DETAIL, "an_close"], str(cbs))
        check(f"T11[{lang}]: callback'lar xavfsiz (<=64 bayt)",
              all(is_callback_safe(c) for c in cbs), str(cbs))
        check(f"T11[{lang}]: tugma yorliqlari farq qiladi (dublikat yo'q)",
              len(set(_labels(kb))) == 2, str(_labels(kb)))


def main():
    global FAILURES
    print("=" * 70)
    print(" 📊 STATISTIKA IZOLYATSIYASI — SHAXSIY vs ADMIN (T1..T11)")
    print("=" * 70)

    suite = (
        test_t1_regular_user_no_admin_stats,
        test_t2_admin_main_menu_is_personal,
        test_t3_all_languages_isolated,
        test_t4_builder_is_pure,
        test_t5_admin_panel_full_stats,
        test_t6_dispatcher_has_no_admin_branch,
        test_t7_real_router_routes,
        test_t8_channel_analytics_round_trip,
        test_t9_fsm_routing_registered,
        test_t10_registry_single_ownership,
        test_t11_i18n_parity,
    )
    print(f"\nBelgilangan testlar soni: {len(suite)} (T1..T11)")

    crashed = []
    for fn in suite:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 — bitta test yiqilsa ham
            FAILURES += 1
            crashed.append(fn.__name__)
            import traceback
            print(f"  [FAIL] {fn.__name__} istisno bilan yiqildi: {exc!r}")
            traceback.print_exc()

    print()
    print("=" * 70)
    if crashed:
        print(f"ISTISNO BILAN YIQILGAN: {', '.join(crashed)}")
    print(f"JAMI: o'tdi={PASSED}, xato={FAILURES}")
    print("=" * 70)
    if FAILURES:
        print("TESTS: FAIL ❌")
        sys.exit(1)
    print("TESTS: PASS ✔ — statistika izolyatsiyasi to'liq qo'riqlandi")
    sys.exit(0)


if __name__ == "__main__":
    main()
