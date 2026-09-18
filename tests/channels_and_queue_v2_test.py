#!/usr/bin/env python3
"""📢 KANALLARIM + 📅 REJALASHTIRILGAN — PostAssist V2 (4-mikro qadam).

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  📢 KANALLAR RO'YXATI — [📢 Kanallarim] bosilganda ulangan kanallar
           ro'yxati va [➕ Kanal qo'shish] tugmasi chiziladi; kanal yo'q
           bo'lsa ham tushunarli ekran + qo'shish tugmasi qaytadi.
  TEST 2:  📢 KANAL SUBMENYUSI — kanal tanlanganda QAT'IY layout ochiladi:
               [➕ Post yaratish]
               [📅 Rejalashtirilgan]   [📊 Statistika]
               [⚙️ Kanal sozlamalari]  [◀️ Orqaga]
           va har bir tugma O'Z amalini bajaradi (post/reja/statistika/
           sozlamalar/orqaga) — hech biri asosiy menyuga chiqib ketmaydi.
  TEST 3:  📅 REJALASHTIRILGAN RO'YXATI — postlar VAQT BO'YICHA tartiblangan
           inline formatda ("🕐 Bugun 18:00 — [Matn qisqartmasi]") va har bir
           post ostida [✏️ Tahrirlash] [⏰ Vaqtni o'zgartirish] [🗑 O'chirish].
  TEST 4:  🔐 XAVFSIZLIK — begona kanal/post ochilmaydi (fail-closed), amal
           handlerlari xatosiz ishlaydi, callback_data 64 baytdan oshmaydi.
  TEST 5:  🌐 I18N — UZ/RU/EN 100% paritet; eskirgan texnik nomlar
           («Postlar navbati», «Очередь постов», «Queued posts») foydalanuvchi
           matnlaridan olib tashlandi, lekin ALIAS sifatida routing'da qoldi.
  TEST 6:  🛡 REGRESSIYA QO'RIQONLARI — asosiy menyu 7 tugma (3-QISM),
           fallback ENG oxirgi handler, eski callback'lar (ch_del:/ch_set:/
           qdel:/qpush:/qview:) va FSM dialoglari buzilmadi.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/channels_and_queue_v2_test.py
"""
import asyncio
import os
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:CHANNELS_QUEUE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10003")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")

USER_ID = 777001
CH_ID = "-1001234567890"
CH_TITLE = "Mening kanalim"
OTHER_CH_ID = "-1009999999999"

# Kanal boshqaruv ekranining QAT'IY layouti (har tilda bir xil tartib).
# 🧠 PHASE B: [🧠 Kanal DNA] va [⏰ Eng yaxshi vaqt] tugmalari qo'shildi
# (Channel Intelligence — DNA profili va optimal post vaqti).
# 📥 PHASE D (2/2): [📥 Kontent manbalari] — URL→post, RSS/ATOM oqimi va
# Content Recycle (alohida qator, to'liq eni).
EXPECTED_PANEL = {
    "uz": [["➕ Post yaratish"],
           ["📅 Rejalashtirilgan", "📊 Statistika"],
           ["🧠 Kanal DNA", "⏰ Eng yaxshi vaqt"],
           ["🚀 AI Avtopilot", "📋 Shablonlar"],
           ["📥 Kontent manbalari"],
           ["⚙️ Kanal sozlamalari", "◀️ Orqaga"]],
    "ru": [["➕ Создать пост"],
           ["📅 Запланированные", "📊 Статистика"],
           ["🧠 DNA канала", "⏰ Лучшее время"],
           ["🚀 AI Автопилот", "📋 Шаблоны"],
           ["📥 Источники контента"],
           ["⚙️ Настройки канала", "◀️ Назад"]],
    "en": [["➕ Create post"],
           ["📅 Scheduled", "📊 Statistics"],
           ["🧠 Channel DNA", "⏰ Best time"],
           ["🚀 AI Autopilot", "📋 Templates"],
           ["📥 Content sources"],
           ["⚙️ Channel settings", "◀️ Back"]],
}

# Rejalashtirilgan post amallari (3 ta, speks tartibida).
EXPECTED_ACTIONS = {
    "uz": ["✏️ Tahrirlash", "⏰ Vaqtni o'zgartirish", "🗑 O'chirish"],
    "ru": ["✏️ Редактировать", "⏰ Изменить время", "🗑 Удалить"],
    "en": ["✏️ Edit", "⏰ Change time", "🗑 Delete"],
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
    return [[b.text for b in row] for row in markup.inline_keyboard]


def kb_flat(markup):
    return [t for row in kb_rows(markup) for t in row]


def cb_flat(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
import pytz  # noqa: E402
from telegram.ext import (  # noqa: E402
    CallbackQueryHandler, ConversationHandler,
)

import database as db_mod  # noqa: E402
import handlers as H  # noqa: E402
import handlers.channels as CH  # noqa: E402
import handlers.queue as Q  # noqa: E402
from keyboards.callback_data import (  # noqa: E402
    CALLBACK_DATA_MAX_BYTES, CB_CHANNEL_BACK, CB_CHANNEL_BEST_TIME,
    CB_CHANNEL_DELETE, CB_CHANNEL_DNA, CB_CHANNEL_NEW_POST, CB_CHANNEL_OPEN,
    CB_CHANNEL_SCHEDULED, CB_CHANNEL_SETTINGS, CB_CHANNEL_STATS,
    CB_CHANNEL_VOICE, CB_SCHED_DELETE, CB_SCHED_EDIT, CB_SCHED_TIME,
    callback_byte_len,
)
from keyboards.default import (  # noqa: E402
    BTN_QUEUE, BTN_QUEUE_RU, MENU_TEXTS, QUEUE_ALIASES, get_main_keyboard,
    is_menu_text,
)
from keyboards.inline import (  # noqa: E402
    render_channel_panel, render_channel_settings, render_channels_list,
    render_my_channels_list, render_scheduled_actions,
)
from locales.translations import TRANSLATIONS, get_text  # noqa: E402
from translations import (  # noqa: E402
    CHANNEL_PANEL_BUTTON_KEYS, CHANNELS_QUEUE_I18N, CHANNELS_QUEUE_KEYS,
    SCHEDULED_ACTION_KEYS, channels_queue_parity_report, channels_queue_t,
)

TZ = pytz.timezone("Asia/Tashkent")


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """reply_text yozib boruvchi soxta xabar."""

    def __init__(self, user_id=USER_ID):
        self.from_user = SimpleNamespace(id=user_id, first_name="Tester")
        self.chat = SimpleNamespace(id=user_id, type="private")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(text=text, **kwargs))
        return SimpleNamespace(message_id=1, chat=self.chat)


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

    # Oxirgi ekran matni va klaviaturasi (edit yoki reply — qaysi bo'lsa).
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


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(user_data=ud, chat_data={},
                           bot=SimpleNamespace(username="postassist_test_bot"),
                           application=None)


def _sched(days=0, hour=18, minute=0):
    now = datetime.now(TZ)
    base = now + timedelta(days=days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _post_row(pid, sched_time, content="Yangi mahsulot chegirmasi",
              ptype="text", ch_id=CH_ID, title=CH_TITLE):
    """``get_queue_posts`` qaytaradigan qator formati."""
    return (pid, title, ptype, content, sched_time, pid, ch_id)


class _FakeDB:
    """``database.run_db`` ni almashtiruvchi deterministik mock.

    Faqat shu testlarga kerak bo'lgan funksiyalar; kutilmagan chaqiruv
    AssertionError beradi (jim o'tib ketish yo'q).
    """

    def __init__(self, channels=None, posts=None, stats=None):
        self.channels = channels if channels is not None else [
            (CH_ID, CH_TITLE, "friendly")]
        self.posts = posts if posts is not None else []
        self.stats = stats or {}
        self.calls = []

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args))
        if name in ("get_user_channels_with_tone", "get_user_channels"):
            return list(self.channels)
        if name == "get_queue_post_count":
            return len(self.posts)
        if name == "get_queue_posts":
            offset = args[1] if len(args) > 1 else 0
            limit = args[2] if len(args) > 2 else 5
            return list(self.posts)[offset:offset + limit]
        if name == "check_queue_limit":
            return (True, len(self.posts), 5)
        if name == "get_channel_post_stats":
            return dict(self.stats)
        if name == "cancel_post":
            return True
        if name == "get_queue_post_detail":
            pid = args[0]
            for p in self.posts:
                if p[0] == pid:
                    return (p[0], USER_ID, p[6], p[1], p[2], p[3], None,
                            None, None, False, 0, p[4], p[5])
            return None
        raise AssertionError(f"kutilmagan db chaqiruvi: {name}")


def _with_db(fake, coro_factory):
    """``db.run_db`` ni vaqtincha mock bilan almashtirib, korutinani bajaradi."""
    original = db_mod.run_db
    db_mod.run_db = fake.run_db
    try:
        return asyncio.run(coro_factory())
    finally:
        db_mod.run_db = original


def _build_app():
    """Haqiqiy PTB Application + register_all_handlers (tarmoqqa chiqmaydi)."""
    import warnings as _w
    from telegram.ext import ApplicationBuilder
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:CHANNELS_QUEUE_TEST").build()
    H.register_all_handlers(app)
    return app


def _all_handlers(app):
    return [h for group in sorted(app.handlers) for h in app.handlers[group]]


def _cb_update(data, user_id=USER_ID):
    """Haqiqiy ``telegram.Update`` (router tekshiruvlari uchun)."""
    from telegram import Update
    return Update.de_json({
        "update_id": 1,
        "callback_query": {
            "id": "cbq-1",
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "chat_instance": "ci-1",
            "data": data,
            "message": {
                "message_id": 5, "date": 0,
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": 1, "is_bot": True, "first_name": "Bot"},
            },
        },
    }, None)


def _msg_update(text, user_id=USER_ID):
    from telegram import Update
    return Update.de_json({
        "update_id": 2,
        "message": {
            "message_id": 10, "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Tester"},
            "text": text,
        },
    }, None)


def _handler_for(app, update):
    """Update'ni BIRINCHI bo'lib ushlaydigan handler (fallback tekshiruvi)."""
    for group in sorted(app.handlers):
        for h in app.handlers[group]:
            res = h.check_update(update)
            if res is not None and res is not False:
                return h
    return None


# ============================================================================
# TEST 1 — 📢 KANALLAR RO'YXATI + [➕ Kanal qo'shish]
# ============================================================================
def test_channels_list_screen():
    print("\n== TEST 1: 📢 Kanallarim — ro'yxat va [➕ Kanal qo'shish] ==")

    channels = [(CH_ID, CH_TITLE, "friendly"), ("-100222", "Ikkinchi kanal", "formal")]
    for lang in LANGS:
        kb = render_my_channels_list(channels, lang)
        labels = kb_flat(kb)
        cbs = cb_flat(kb)
        # Har bir kanal — BITTA tugma (ro'yxat toza, amal tugmalari yo'q).
        check(f"[{lang}] har kanal bitta tugma",
              labels[:2] == [f"📢 {CH_TITLE}", "📢 Ikkinchi kanal"], str(labels))
        check(f"[{lang}] kanal tugmasi ch_op: callback'i",
              cbs[0] == f"{CB_CHANNEL_OPEN}{CH_ID}", str(cbs))
        check(f"[{lang}] [➕ Kanal qo'shish] tugmasi bor",
              channels_queue_t("cq_ch_add_btn", lang) in labels
              and "add_channel_start" in cbs, str(labels))
        check(f"[{lang}] ro'yxatda amal tugmalari YO'Q (ch_del/ch_set)",
              not any(c.startswith(CB_CHANNEL_DELETE) or c.startswith(CB_CHANNEL_SETTINGS)
                      for c in cbs), str(cbs))

    # channels_menu — REAL handler (mock DB bilan).
    fake = _FakeDB(channels=channels)
    msg = _Msg()
    state = _with_db(fake, lambda: CH.channels_menu(_upd_msg(msg), _ctx("uz")))
    check("channels_menu: ConversationHandler.END", state == ConversationHandler.END, str(state))
    check("channels_menu: bitta ekran yubordi", len(msg.sent) == 1, str(msg.sent))
    sent = msg.sent[0]
    check("channels_menu: sarlavhada kanal soni",
          "2" in sent["text"] and "Kanallarim" in sent["text"], sent["text"][:80])
    check("channels_menu: ro'yxat klaviaturasi",
          f"{CB_CHANNEL_OPEN}{CH_ID}" in cb_flat(sent["reply_markup"]),
          str(cb_flat(sent["reply_markup"])))

    # Kanal YO'Q holati — baribir [➕ Kanal qo'shish] chiqadi.
    empty = _FakeDB(channels=[])
    msg2 = _Msg()
    _with_db(empty, lambda: CH.channels_menu(_upd_msg(msg2), _ctx("uz")))
    check("kanal yo'q: javob bor (qotmaydi)", len(msg2.sent) == 1, str(msg2.sent))
    check("kanal yo'q: qo'shish tugmasi bor",
          "add_channel_start" in cb_flat(msg2.sent[0]["reply_markup"]))

    # Eski render_channels_list ATAYLAB saqlangan (kabinet ekrani + eski xabarlar).
    legacy = render_channels_list([(CH_ID, CH_TITLE, "friendly")], "uz")
    legacy_cbs = cb_flat(legacy)
    check("orqaga moslik: render_channels_list hali ham ch_del:/ch_set: beradi",
          any(c.startswith(CB_CHANNEL_DELETE) for c in legacy_cbs)
          and any(c.startswith(CB_CHANNEL_SETTINGS) for c in legacy_cbs), str(legacy_cbs))


# ============================================================================
# TEST 2 — 📢 KANAL SUBMENYUSI (speksdagi QAT'IY layout + amallar)
# ============================================================================
def test_channel_panel_layout_and_actions():
    print("\n== TEST 2: 📢 Kanal boshqaruv ekrani (7 tugma + amallar) ==")

    for lang in LANGS:
        kb = render_channel_panel(CH_ID, lang)
        rows = kb_rows(kb)
        check(f"[{lang}] layout speksdagidek", rows == EXPECTED_PANEL[lang], str(rows))
        cbs = cb_flat(kb)
        check(f"[{lang}] har tugma KANAL kontekstini olib yuradi",
              cbs == [f"{CB_CHANNEL_NEW_POST}{CH_ID}",
                      f"{CB_CHANNEL_SCHEDULED}{CH_ID}",
                      f"{CB_CHANNEL_STATS}{CH_ID}",
                      f"{CB_CHANNEL_DNA}{CH_ID}",
                      f"{CB_CHANNEL_BEST_TIME}{CH_ID}",
                      f"ch_ap:{CH_ID}",
                      f"ch_tpl:{CH_ID}",
                      f"ch_src:{CH_ID}",
                      f"{CB_CHANNEL_SETTINGS}{CH_ID}",
                      CB_CHANNEL_BACK], str(cbs))

    # --- Kanal tanlash → boshqaruv ekrani ---
    fake = _FakeDB()
    q = _Query(f"{CB_CHANNEL_OPEN}{CH_ID}")
    _with_db(fake, lambda: CH.channel_open_callback(_upd_query(q), _ctx("uz")))
    check("kanal tanlandi: darhol answer qilindi", len(q.answered) == 1, str(q.answered))
    check("kanal tanlandi: ekran EDIT qilindi (yangi xabar emas)",
          len(q.edits) == 1 and not q.message.sent, str(q.edits))
    check("kanal tanlandi: sarlavhada kanal nomi",
          CH_TITLE in q.screen["text"], q.screen["text"][:80])
    check("kanal tanlandi: 7 tugmali panel (PHASE C: +Avtopilot, +Shablonlar)",
          kb_rows(q.screen["reply_markup"]) == EXPECTED_PANEL["uz"],
          str(kb_rows(q.screen["reply_markup"])))

    # --- [◀️ Orqaga] → kanallar RO'YXATI (asosiy menyuga EMAS) ---
    q_back = _Query(CB_CHANNEL_BACK)
    _with_db(_FakeDB(), lambda: CH.channels_list_callback(_upd_query(q_back), _ctx("uz")))
    back_cbs = cb_flat(q_back.screen["reply_markup"])
    check("[◀️ Orqaga] → kanallar ro'yxati qaytadi",
          f"{CB_CHANNEL_OPEN}{CH_ID}" in back_cbs, str(back_cbs))
    check("[◀️ Orqaga] asosiy menyuga CHIQMAYDI (reply-klaviatura yo'q)",
          not q_back.message.sent, str(q_back.message.sent))

    # --- [📊 Statistika] — kanal ichida, panelga qaytish tugmalari bilan ---
    stats = {"sent_7d": 3, "sent_30d": 9, "sent_all": 21, "pending": 2,
             "peak_hours": [(18, 5)], "type_distribution": {"text": 10, "photo": 11}}
    q_st = _Query(f"{CB_CHANNEL_STATS}{CH_ID}")
    _with_db(_FakeDB(stats=stats),
             lambda: CH.channel_stats_callback(_upd_query(q_st), _ctx("uz")))
    check("[📊 Statistika]: kanal nomi bilan dashboard",
          CH_TITLE in q_st.screen["text"], q_st.screen["text"][:120])
    check("[📊 Statistika]: kanal ekrani ichida qoladi (panel tugmalari)",
          kb_rows(q_st.screen["reply_markup"]) == EXPECTED_PANEL["uz"],
          str(kb_rows(q_st.screen["reply_markup"])))

    # --- [⚙️ Kanal sozlamalari] — uslub / AI ovoz / uzish + orqaga ---
    q_set = _Query(f"{CB_CHANNEL_SETTINGS}{CH_ID}")
    ctx_set = _ctx("uz")
    _with_db(_FakeDB(), lambda: CH.channel_settings_callback(_upd_query(q_set), ctx_set))
    set_cbs = cb_flat(q_set.screen["reply_markup"])
    check("[⚙️ Sozlamalar]: uslub (ch_set:) tugmasi",
          f"{CB_CHANNEL_SETTINGS}{CH_ID}" in set_cbs, str(set_cbs))
    check("[⚙️ Sozlamalar]: AI ovoz tahlili (ch_voice:) tugmasi",
          f"{CB_CHANNEL_VOICE}{CH_ID}" in set_cbs, str(set_cbs))
    check("[⚙️ Sozlamalar]: kanalni uzish (ch_del:) tugmasi",
          f"{CB_CHANNEL_DELETE}{CH_ID}" in set_cbs, str(set_cbs))
    check("[⚙️ Sozlamalar]: [◀️ Orqaga] kanal paneliga qaytaradi",
          f"{CB_CHANNEL_OPEN}{CH_ID}" in set_cbs, str(set_cbs))
    check("[⚙️ Sozlamalar]: ekran ochiqligi user_data'da belgilandi",
          ctx_set.user_data.get("ch_settings_open") == CH_ID, str(ctx_set.user_data))

    # Sozlamalar ochiq turganda «🎨 Uslub» bosilsa — ESKI uslub oqimi (SET_TONE).
    tone_calls = []

    async def _fake_tone(update, context):
        tone_calls.append(update.callback_query.data)
        return CH.SET_TONE

    original_tone = CH.tone_menu_callback
    CH.tone_menu_callback = _fake_tone
    try:
        q_tone = _Query(f"{CB_CHANNEL_SETTINGS}{CH_ID}")
        state = _with_db(_FakeDB(),
                         lambda: CH.channel_settings_callback(_upd_query(q_tone), ctx_set))
        check("«🎨 Uslub» → eski SET_TONE oqimi ochiladi",
              state == CH.SET_TONE and tone_calls == [f"{CB_CHANNEL_SETTINGS}{CH_ID}"],
              f"{state} / {tone_calls}")
        check("«🎨 Uslub» bosilgach bayroq tozalandi",
              "ch_settings_open" not in ctx_set.user_data, str(ctx_set.user_data))
    finally:
        CH.tone_menu_callback = original_tone

    # --- [➕ Post yaratish] — kanal tanlangan holda GET_CONTENT ---
    from handlers.new_post import GET_CONTENT
    q_np = _Query(f"{CB_CHANNEL_NEW_POST}{CH_ID}")
    ctx_np = _ctx("uz")
    state = _with_db(_FakeDB(),
                     lambda: CH.channel_new_post_callback(_upd_query(q_np), ctx_np))
    check("[➕ Post yaratish]: GET_CONTENT holatiga o'tdi", state == GET_CONTENT, str(state))
    check("[➕ Post yaratish]: kanal QAYTA so'ralmaydi (kontekst saqlandi)",
          ctx_np.user_data.get("selected_channel_id") == CH_ID
          and ctx_np.user_data.get("selected_channel_title") == CH_TITLE,
          str(ctx_np.user_data))
    check("[➕ Post yaratish]: yo'riqnoma xabari chiqdi",
          bool(q_np.message.sent) and CH_TITLE in q_np.message.sent[0]["text"],
          str(q_np.message.sent)[:160])


# ============================================================================
# TEST 3 — 📅 REJALASHTIRILGAN: format, tartib, amallar
# ============================================================================
def test_scheduled_list_format_and_actions():
    print("\n== TEST 3: 📅 Rejalashtirilgan — format, tartib, 3 amal ==")

    today = _sched(days=0, hour=18, minute=0)
    row = _post_row(101, today, "Yangi mahsulot chegirmasi boshlandi")

    # --- Speksdagi format: "🕐 Bugun 18:00 — [Matn qisqartmasi]" ---
    item_uz = Q._format_queue_item(row, 1, "uz")
    check("format: raqamlangan qator", item_uz.startswith("1. "), item_uz)
    check("format: 🕐 vaqt belgisi", "🕐" in item_uz, item_uz)
    check("format: 'Bugun 18:00' (nisbiy sana, tilga mos)",
          f"{get_text('dt_today', 'uz')} 18:00" in item_uz, item_uz)
    check("format: matn qisqartmasi ko'rinadi",
          "Yangi mahsulot chegirmasi" in item_uz, item_uz)
    check("format: kanal nomi ko'rinadi", CH_TITLE in item_uz, item_uz)
    check("format: ajratgich '—' bor", "—" in item_uz, item_uz)

    item_ru = Q._format_queue_item(row, 1, "ru")
    item_en = Q._format_queue_item(row, 1, "en")
    check("format[ru]: 'Сегодня 18:00'",
          f"{get_text('dt_today', 'ru')} 18:00" in item_ru, item_ru)
    check("format[en]: 'Today 18:00'",
          f"{get_text('dt_today', 'en')} 18:00" in item_en, item_en)

    # Media (matnsiz) post — chiziqcha "osilib" qolmaydi.
    media_item = Q._format_queue_item(
        _post_row(102, today, "", ptype="photo"), 2, "uz")
    check("format: matnsiz media postda ham toza qator",
          "🖼" in media_item and not media_item.rstrip().endswith("—"), media_item)
    check("format: bo'sh sana bilan crash bermaydi",
          Q._format_queue_item(_post_row(103, None), 3, "uz").startswith("3. "))

    # --- Vaqt bo'yicha TARTIB (DB ORDER BY + ro'yxat tartibi) ---
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    q_body = db_src.split("def get_queue_posts(", 1)[1].split("\ndef ", 1)[0]
    check("tartib: get_queue_posts ORDER BY scheduled_time ASC",
          "ORDER BY sp.scheduled_time ASC" in q_body, q_body[:200])

    posts = [
        _post_row(201, _sched(days=0, hour=9)),
        _post_row(202, _sched(days=0, hour=18)),
        _post_row(203, _sched(days=1, hour=10)),
    ]
    fake = _FakeDB(posts=posts)
    text, markup = _with_db(fake, lambda: Q._build_queue_view(USER_ID, False, "uz"))
    lines = [l for l in text.split("\n") if l.strip().startswith(("1.", "2.", "3."))]
    check("ro'yxat: 3 ta post chiqdi", len(lines) == 3, str(lines))
    check("ro'yxat: DB tartibi saqlangan (vaqt bo'yicha o'sish)",
          lines[0].startswith("1. ") and lines[1].startswith("2. ")
          and lines[2].startswith("3. "), str(lines))
    check("ro'yxat: sarlavha «📅 Rejalashtirilgan»",
          "Rejalashtirilgan" in text and "Navbat" not in text, text[:100])

    # --- Har bir post ostida 3 ta amal ---
    for lang in LANGS:
        actions = render_scheduled_actions(201, lang)
        labels = [b.text for b in actions]
        cbs = [b.callback_data for b in actions]
        check(f"amallar[{lang}] speksdagi 3 tugma", labels == EXPECTED_ACTIONS[lang], str(labels))
        check(f"amallar[{lang}] callback'lari mavjud oqimlarga",
              cbs == [f"{CB_SCHED_EDIT}201", f"{CB_SCHED_TIME}201", f"{CB_SCHED_DELETE}201"],
              str(cbs))

    list_cbs = cb_flat(markup)
    for pid in (201, 202, 203):
        check(f"ro'yxat kb: #{pid} uchun 3 amal bor",
              f"{CB_SCHED_EDIT}{pid}" in list_cbs
              and f"{CB_SCHED_TIME}{pid}" in list_cbs
              and f"{CB_SCHED_DELETE}{pid}" in list_cbs, str(list_cbs))
    check("ro'yxat kb: eski amallar (qview:/qpush:) saqlangan",
          "qview:201" in list_cbs and "qpush:201" in list_cbs, str(list_cbs))

    # --- Bo'sh holat ---
    empty_text, empty_kb = _with_db(_FakeDB(posts=[]),
                                    lambda: Q._build_queue_view(USER_ID, False, "uz"))
    check("bo'sh: «Rejalashtirilgan» matni", "Rejalashtirilgan" in empty_text, empty_text[:80])
    check("bo'sh: eskirgan 'Navbat' so'zi yo'q", "Navbat" not in empty_text, empty_text[:120])
    check("bo'sh: klaviatura bor (qotmaydi)", empty_kb is not None)

    # --- Kanal ichidagi «📅 Rejalashtirilgan» ---
    mixed = posts + [_post_row(301, _sched(days=0, hour=12), "Boshqa kanal posti",
                               ch_id=OTHER_CH_ID, title="Boshqa kanal")]
    ch_text, ch_kb = _with_db(
        _FakeDB(posts=mixed),
        lambda: Q.build_channel_scheduled_view(USER_ID, CH_ID, CH_TITLE, "uz"))
    check("kanal reja: faqat SHU kanal postlari",
          "Boshqa kanal posti" not in ch_text and CH_TITLE in ch_text, ch_text[:200])
    ch_cbs = cb_flat(ch_kb)
    check("kanal reja: har post ostida 3 amal",
          f"{CB_SCHED_EDIT}201" in ch_cbs and f"{CB_SCHED_TIME}201" in ch_cbs
          and f"{CB_SCHED_DELETE}201" in ch_cbs, str(ch_cbs))
    check("kanal reja: [◀️ Orqaga] kanal paneliga qaytaradi",
          f"{CB_CHANNEL_OPEN}{CH_ID}" in ch_cbs, str(ch_cbs))
    check("kanal reja: begona kanal posti amallari YO'Q",
          f"{CB_SCHED_EDIT}301" not in ch_cbs, str(ch_cbs))

    # Kanalda post bo'lmasa — tushunarli ekran, panelga qaytish.
    e_text, e_kb = _with_db(
        _FakeDB(posts=[]),
        lambda: Q.build_channel_scheduled_view(USER_ID, CH_ID, CH_TITLE, "uz"))
    check("kanal reja: bo'sh holatda ham javob bor", bool(e_text) and e_kb is not None)
    check("kanal reja: bo'sh holatda panel tugmalari",
          kb_rows(e_kb) == EXPECTED_PANEL["uz"], str(kb_rows(e_kb)))

    # --- Kanal submenyusidagi [📅 Rejalashtirilgan] tugmasi (real handler) ---
    q_sch = _Query(f"{CB_CHANNEL_SCHEDULED}{CH_ID}")
    _with_db(_FakeDB(posts=posts),
             lambda: CH.channel_scheduled_callback(_upd_query(q_sch), _ctx("uz")))
    check("[📅 Rejalashtirilgan] (kanal ichida): ekran chizildi",
          bool(q_sch.edits), str(q_sch.edits)[:120])
    check("[📅 Rejalashtirilgan] (kanal ichida): amallar bor",
          f"{CB_SCHED_EDIT}201" in cb_flat(q_sch.screen["reply_markup"]),
          str(cb_flat(q_sch.screen["reply_markup"])))


# ============================================================================
# TEST 4 — 🔐 XAVFSIZLIK: fail-closed egalik + amal handlerlari
# ============================================================================
def test_safety_and_ownership():
    print("\n== TEST 4: 🔐 Egalik tekshiruvi, amallar xavfsizligi ==")

    # Begona kanal — HECH QANDAY ekran ochilmaydi.
    for name, fn, prefix in (
        ("ch_op", CH.channel_open_callback, CB_CHANNEL_OPEN),
        ("ch_sch", CH.channel_scheduled_callback, CB_CHANNEL_SCHEDULED),
        ("ch_st", CH.channel_stats_callback, CB_CHANNEL_STATS),
        ("ch_np", CH.channel_new_post_callback, CB_CHANNEL_NEW_POST),
        # 🧠 PHASE B — Channel Intelligence (IDOR: begona kanal DNA/vaqt ochilmaydi)
        ("ch_dna", CH.channel_dna_callback, CB_CHANNEL_DNA),
        ("ch_btm", CH.channel_best_time_callback, CB_CHANNEL_BEST_TIME),
    ):
        q = _Query(f"{prefix}{OTHER_CH_ID}")
        state = _with_db(_FakeDB(), lambda: fn(_upd_query(q), _ctx("uz")))
        screen = q.screen.get("text", "")
        check(f"begona kanal [{name}]: panel ochilmadi",
              CH_TITLE not in screen and state == ConversationHandler.END,
              f"{state} / {screen[:80]}")
        check(f"begona kanal [{name}]: tushunarli xato xabari",
              channels_queue_t("cq_ch_not_found", "uz")[:20] in screen, screen[:80])

    # Begona kanal uchun ham javob berildi (foydalanuvchi "qotmaydi").
    q = _Query(f"{CB_CHANNEL_OPEN}{OTHER_CH_ID}")
    _with_db(_FakeDB(), lambda: CH.channel_open_callback(_upd_query(q), _ctx("uz")))
    check("begona kanal: callback darhol answer qilindi", len(q.answered) == 1)

    # 🗑 O'chirish — begona post o'chirilmaydi (DB o'zi user_id bo'yicha filtrlaydi).
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    cancel_body = db_src.split("def cancel_post(", 1)[1].split("\ndef ", 1)[0]
    check("🗑 O'chirish: DB so'rovi user_id bo'yicha filtrlaydi",
          "AND user_id = %s" in cancel_body, cancel_body[:200])
    check("🗑 O'chirish: faqat 'pending' postga tegadi",
          "status = 'pending'" in cancel_body, cancel_body[:200])

    # 🗑 O'chirish handleri — xatosiz ishlaydi va ro'yxatni yangilaydi.
    posts = [_post_row(201, _sched(hour=9)), _post_row(202, _sched(hour=18))]
    fake = _FakeDB(posts=posts)
    q_del = _Query("qdel:201")
    _with_db(fake, lambda: Q.queue_delete_callback(_upd_query(q_del), _ctx("uz")))
    check("🗑 O'chirish: cancel_post chaqirildi (user_id bilan)",
          ("cancel_post", (201, USER_ID)) in fake.calls, str(fake.calls))
    check("🗑 O'chirish: toast ko'rsatildi",
          q_del.answered and "🗑" in (q_del.answered[0] or ""), str(q_del.answered))
    check("🗑 O'chirish: ro'yxat qayta chizildi", bool(q_del.edits), str(q_del.edits)[:120])

    # ✏️ Tahrirlash / ⏰ Vaqt — mavjud, sinovdan o'tgan pending oqimlari.
    from handlers.pending import (
        EDIT_POST_CONTENT, EDIT_POST_TIME, edit_post_content_start,
        edit_post_time_start,
    )
    check("✏️ Tahrirlash: p_edit: → edit_post_content_start oqimi",
          CB_SCHED_EDIT == "p_edit:" and callable(edit_post_content_start))
    check("⏰ Vaqtni o'zgartirish: p_time: → edit_post_time_start oqimi",
          CB_SCHED_TIME == "p_time:" and callable(edit_post_time_start))
    check("amallar yangi FSM yaratmaydi (mavjud holatlar qayta ishlatiladi)",
          EDIT_POST_CONTENT == 202 and EDIT_POST_TIME == 205)

    # callback_data 64-bayt xavfsizligi (Telegram qat'iy limiti).
    long_id = "-100" + "9" * 40
    keyboards = [
        ("panel", render_channel_panel(long_id, "ru")),
        ("settings", render_channel_settings(long_id, "en")),
        ("list", render_my_channels_list([(long_id, "K" * 80, "formal")], "uz")),
    ]
    oversized = []
    for name, kb in keyboards:
        for data in cb_flat(kb):
            if data and callback_byte_len(data) > CALLBACK_DATA_MAX_BYTES:
                oversized.append((name, data, callback_byte_len(data)))
    check("callback_data: hech biri 64 baytdan oshmaydi", not oversized, str(oversized))
    check("callback_data: bo'sh qiymat yo'q",
          all(bool(d) for _, kb in keyboards for d in cb_flat(kb)))
    check("uzun kanal nomi tugmani buzmaydi",
          all(0 < len(t) <= 64 for _, kb in keyboards for t in kb_flat(kb)))


# ============================================================================
# TEST 5 — 🌐 I18N: UZ/RU/EN paritet + eskirgan nomlar aliasga o'tdi
# ============================================================================
def test_i18n_parity_and_renaming():
    print("\n== TEST 5: 🌐 UZ/RU/EN paritet va «📅 Rejalashtirilgan» nomlanishi ==")

    rep = channels_queue_parity_report()
    check("paritet: yetishmayotgan kalit yo'q",
          not any(rep["missing"].values()), str(rep["missing"]))
    check("paritet: ortiqcha kalit yo'q", not any(rep["extra"].values()), str(rep["extra"]))
    check("paritet: format argumentlari mos",
          not rep["format_mismatch"], str(rep["format_mismatch"]))
    check("paritet: bo'sh matn yo'q", not rep["empty"], str(rep["empty"]))
    check("paritet: in_sync = True", rep["in_sync"] is True, str(rep))
    check("paritet: kalitlar soni 3 tilda bir xil",
          len({len(CHANNELS_QUEUE_I18N[c]) for c in LANGS}) == 1,
          str({c: len(CHANNELS_QUEUE_I18N[c]) for c in LANGS}))

    # Tugma yorliqlari HAR TILDA tarjima qilingan (nusxa emas).
    for key in CHANNEL_PANEL_BUTTON_KEYS + SCHEDULED_ACTION_KEYS:
        values = {c: channels_queue_t(key, c) for c in LANGS}
        check(f"{key}: uchala tilda matn bor", all(values.values()), str(values))
        check(f"{key}: RU tarjimasi UZ'dan farq qiladi",
              values["ru"] != values["uz"], str(values))
        check(f"{key}: EN tarjimasi UZ'dan farq qiladi",
              values["en"] != values["uz"], str(values))

    # Noma'lum kalit asosiy lug'atga tushadi (fallback zanjiri buzilmagan).
    check("channels_queue_t: noma'lum kalit safe_t'ga tushadi",
          channels_queue_t("btn_settings", "ru") == get_text("btn_settings", "ru"))
    check("channels_queue_t: noma'lum til uz'ga normallashadi",
          channels_queue_t("cq_ch_btn_back", "de") == CHANNELS_QUEUE_I18N["uz"]["cq_ch_btn_back"])

    # --- ESKIRGAN TEXNIK NOMLAR foydalanuvchi matnlaridan ketdi ---
    obsolete = {
        "uz": ("Postlar navbati", "Navbatdagi postlar", "Navbat (Queue)"),
        "ru": ("Очередь постов", "Посты в очереди", "Очередь (Queue)"),
        "en": ("Post queue", "Queued posts"),
    }
    for lang, needles in obsolete.items():
        table = TRANSLATIONS[lang]
        for key in ("btn_queue", "cab_queue", "queue_title", "queue_title_range",
                    "queue_empty", "queue_empty_short", "queue_limit_msg",
                    "queue_db_error"):
            value = table.get(key) or ""
            for needle in needles:
                check(f"eskirgan nom yo'q [{lang}/{key}]: {needle!r}",
                      needle not in value, value[:90])

    # Yangi nom UCHALA tilda ishlatiladi.
    expected_name = {"uz": "Rejalashtirilgan", "ru": "Запланированные", "en": "Scheduled"}
    for lang, word in expected_name.items():
        for key in ("btn_queue", "cab_queue", "queue_title", "queue_empty"):
            value = TRANSLATIONS[lang].get(key) or ""
            check(f"yangi nom bor [{lang}/{key}]: {word!r}", word in value, value[:90])
        check(f"asosiy menyu tugmasi [{lang}] = btn_queue (dublikat nom yo'q)",
              get_text("btn_scheduled", lang) == TRANSLATIONS[lang]["btn_queue"],
              f"{get_text('btn_scheduled', lang)!r} vs {TRANSLATIONS[lang]['btn_queue']!r}")

    # --- ALIASLAR SAQLANDI: eski yorliqlar hali ham routing'da taniladi ---
    legacy_labels = (
        "📚 Navbat (Queue)", "📚 Очередь (Queue)", "📚 Queue",
        "⏳ Postlar navbati (Queue)", "⏳ Очередь постов (Queue)",
        "⏳ Post queue (Queue)",
    )
    for label in legacy_labels:
        check(f"alias saqlandi: {label!r} → queue oilasi",
              is_menu_text(label, "queue"), str(QUEUE_ALIASES))
    check("alias: yangi yorliqlar ham queue oilasida",
          all(is_menu_text(get_text("btn_scheduled", c), "queue") for c in LANGS))
    check("MENU_TEXTS['queue'] ichida uchala til + eski nomlar",
          len(MENU_TEXTS["queue"]) >= 9, str(MENU_TEXTS["queue"]))
    check("BTN_QUEUE / BTN_QUEUE_RU yangi nomga o'tdi",
          BTN_QUEUE == "📅 Rejalashtirilgan" and BTN_QUEUE_RU == "📅 Запланированные",
          f"{BTN_QUEUE!r} / {BTN_QUEUE_RU!r}")

    # Handler manbalarida eskirgan sarlavha qotirilmagan.
    q_src = (ROOT / "handlers" / "queue.py").read_text(encoding="utf-8")
    check("handlers/queue.py: sarlavhalar i18n orqali (channels_queue_t)",
          'channels_queue_t("cq_sch_title"' in q_src
          and 'channels_queue_t("cq_sch_empty"' in q_src)
    ch_src = (ROOT / "handlers" / "channels.py").read_text(encoding="utf-8")
    check("handlers/channels.py: matnlar i18n orqali (channels_queue_t)",
          'channels_queue_t("cq_ch_list_title"' in ch_src
          and 'channels_queue_t("cq_ch_panel_title"' in ch_src)


# ============================================================================
# TEST 6 — 🛡 REGRESSIYA QO'RIQONLARI
# ============================================================================
def test_regression_guards():
    print("\n== TEST 6: 🛡 Regressiya qo'riqonlari ==")

    app = _build_app()
    all_h = _all_handlers(app)
    conv = [h for h in all_h if isinstance(h, ConversationHandler)][0]

    # (1) Asosiy menyu — QAT'IY 7 tugma (3-QISM standarti buzilmadi).
    for lang in LANGS:
        rows = [[b.text for b in r] for r in get_main_keyboard(False, lang=lang).keyboard]
        flat = [t for r in rows for t in r]
        check(f"asosiy menyu[{lang}]: 7 tugma", len(flat) == 7, str(flat))
        check(f"asosiy menyu[{lang}]: 📢 Kanallarim + 📅 Rejalashtirilgan",
              get_text("btn_my_channels", lang) in flat
              and get_text("btn_scheduled", lang) in flat, str(flat))

    # (2) Yangi callback'lar router'da ro'yxatdan o'tgan va fallback'ga tushmaydi.
    routes = {
        f"{CB_CHANNEL_OPEN}{CH_ID}": "channel_open_callback",
        f"{CB_CHANNEL_SCHEDULED}{CH_ID}": "channel_scheduled_callback",
        f"{CB_CHANNEL_STATS}{CH_ID}": "channel_stats_callback",
        f"{CB_CHANNEL_SETTINGS}{CH_ID}": "channel_settings_callback",
        CB_CHANNEL_BACK: "channels_list_callback",
    }
    for data, expected in routes.items():
        h = _handler_for(app, _cb_update(data))
        name = getattr(getattr(h, "callback", None), "__name__", str(h))
        check(f"routing {data!r} → {expected}", name == expected, name)
        check(f"routing {data!r} stale-fallback'ga tushmaydi",
              name != "expired_session_callback", name)

    # ch_np: FSM holati qaytargani uchun conversation ENTRY POINT bo'lishi shart.
    entry_names = {getattr(h.callback, "__name__", "") for h in conv.entry_points
                   if isinstance(h, CallbackQueryHandler)}
    check("ch_np: conversation entry point (GET_CONTENT holatini qaytaradi)",
          "channel_new_post_callback" in entry_names, str(sorted(entry_names)))

    # (3) ESKI callback'lar buzilmagan (chat tarixidagi tugmalar).
    h_src = (ROOT / "handlers" / "__init__.py").read_text(encoding="utf-8")
    for prefix in ("ch_del:", "ch_set:", "ch_voice:", "qview:", "qdel:",
                   "qpush:", "qpage:", "qslots:", "p_edit:", "p_time:"):
        check(f"eski callback pattern saqlangan: {prefix}",
              f'pattern=r"^{prefix}"' in h_src or f'pattern="^{prefix}"' in h_src
              or 're.escape(CB_CHANNEL_VOICE)' in h_src, prefix)

    # (4) FSM holatlari va dialoglar buzilmagan.
    from handlers.new_post import CHOOSE_CHANNEL, GET_CONTENT
    check("new_post FSM holatlari o'zgarmagan",
          (CHOOSE_CHANNEL, GET_CONTENT) == (100, 101))
    check("queue FSM holatlari o'zgarmagan", (Q.QUEUE_MENU, Q.SLOT_ADD) == (200, 201))
    check("channels FSM holatlari o'zgarmagan", (CH.ADD_CHANNEL, CH.SET_TONE) == (301, 302))
    check("QUEUE_PAGE_SIZE o'zgarmagan", Q.QUEUE_PAGE_SIZE == 5)
    check("allow_reentry saqlangan", conv.allow_reentry is True)
    check("conversation timeout o'zgarmagan", conv.conversation_timeout == 600)

    # (5) Fallback ENG oxirgi handler bo'lib qoladi.
    check("oxirgi ro'yxatdan o'tgan handler — unknown_message_fallback",
          getattr(all_h[-1], "callback", None) is H.unknown_message_fallback,
          str(all_h[-1]))
    check("asosiy menyu tugmasi fallback'ga tushmaydi",
          not isinstance(_handler_for(app, _msg_update(get_text("btn_scheduled", "uz"))),
                         type(all_h[-1]))
          or _handler_for(app, _msg_update(get_text("btn_scheduled", "uz"))) is not all_h[-1])

    # (6) Slot sozlamalari (avtomatik rejalashtirish) buzilmagan.
    slots_kb = Q._get_slots_keyboard(["09:00", "18:00"], "ru")
    slot_cbs = cb_flat(slots_kb)
    check("slot sozlamalari: callback'lar o'zgarmagan",
          "qslots:rm:0" in slot_cbs and "qslots:add" in slot_cbs
          and "qslots:reset" in slot_cbs and "qpage:0" in slot_cbs, str(slot_cbs))
    detail_cbs = cb_flat(Q._get_post_detail_keyboard(7, "uz"))
    check("post kartochkasi: eski callback'lar o'zgarmagan",
          detail_cbs == ["qdel:7", "qpush:7", "qpage:0"], str(detail_cbs))

    # (7) i18n modul ro'yxatga olingan (syntax_test importi).
    syn_src = (ROOT / "tests" / "syntax_test.py").read_text(encoding="utf-8")
    check("syntax_test: translations.channels_queue import ro'yxatida",
          '"translations.channels_queue"' in syn_src)
    check("CHANNELS_QUEUE_KEYS to'liq (27+ kalit)",
          len(CHANNELS_QUEUE_KEYS) >= 27, str(len(CHANNELS_QUEUE_KEYS)))


# ============================================================================
def main():
    print("=" * 70)
    print(" 📢 KANALLARIM + 📅 REJALASHTIRILGAN — PostAssist V2 (4-MIKRO QADAM)")
    print("=" * 70)
    test_channels_list_screen()
    test_channel_panel_layout_and_actions()
    test_scheduled_list_format_and_actions()
    test_safety_and_ownership()
    test_i18n_parity_and_renaming()
    test_regression_guards()

    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures:
        print(" [FAIL] KANALLAR / REJALASHTIRILGAN BO'LIMIDA XATOLIKLAR BOR ^^^")
        return 1
    print(" KANALLAR VA REJALASHTIRILGAN TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
