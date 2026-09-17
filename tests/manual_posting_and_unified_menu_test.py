#!/usr/bin/env python3
"""✍️ ODDIY (AI'SIZ) POSTING + BIRLASHTIRILGAN MENYU — QABUL TESTI.

DIQQAT: BOTNI ODDIY (AI'SIZ) POSTINGGA MOSLASH VA TUGMALARNI BIRLASHTIRISH.
QAT'IY QOIDA: bot faqat AI uchun bo'lib qolmasligi kerak — oddiy
foydalanuvchilar o'zlarining TAYYOR postlarini (matn, rasm, video) hech
qanday AI aralashuvisiz, to'g'ridan-to'g'ri kanalga chiqarishi va
rejalashtirishi shart.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  Tayyor MATN yuborilganda AI'ga bormasdan DARHOL preview hosil
           bo'ladi (uslub tanlash/generatsiya savollari YO'Q); xuddi shu
           oqim rasm va video uchun ham ishlaydi.
  TEST 2:  [🚀 Hozir yuborish] — post darhol kanalga chiqadi (db.add_post,
           scheduled_time≈hozir); ko'p kanalda avval kanal tanlanadi.
  TEST 3:  [📅 Vaqtni belgilash] — oddiy reja: "ertagi 19:30" kabi aniq
           vaqtga rejalashtiriladi; [🗑 24 soatlik e'lon] va [🔄 Takroriy
           e'lon] ham to'liq ishlaydi.
  TEST 4:  Universal panel speksdagi BARCHA tugmalarga ega: 🚀 / 📅 / 🗑 /
           🔄 / ✏️ / ❌ — va ularning har biri real amalga ulangan.
  TEST 5:  BIRLASHTIRILGAN MENYU — Kontent yaratish menyusida aynan 3 ta
           yo'nalish (✍️ Oddiy post / ✨ AI bilan yaratish / 🤖 AI Studio)
           + ◀️ Orqaga; eski tugmalar faqat routing aliasi.
  TEST 6:  PROFIL TOZALIGI — «👤 Profil»dan takroriy «🌐 Til» tugmasi
           chiqarilgan; til faqat Sozlamalar ichida (stgs_lang) qolgan;
           profilda ID/obuna/balans ma'lumotlari bor.
  TEST 7:  i18n PARITET — manual_post va content_menu lug'atlari UZ/RU/EN
           100% sinxron; regressiya qo'riqonlari (FSM noyobligi, 64 bayt).

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/manual_posting_and_unified_menu_test.py
"""
import asyncio
import os
import re
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:MANUAL_POST_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10003")

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


# ---------------------------------------------------------------------------
# MODULLAR (env sozlangandan KEYIN import qilinadi)
# ---------------------------------------------------------------------------
from telegram.ext import ConversationHandler  # noqa: E402

import handlers as H  # noqa: E402
import handlers.manual_post as MP  # noqa: E402
import handlers.settings as STG  # noqa: E402
import database as db_mod  # noqa: E402
from keyboards.default import get_main_keyboard  # noqa: E402
from keyboards.inline import (  # noqa: E402
    CB_MANUAL_24H, CB_MANUAL_CANCEL, CB_MANUAL_CHANNEL, CB_MANUAL_EDIT,
    CB_MANUAL_NOW, CB_MANUAL_PANEL, CB_MANUAL_REACT, CB_MANUAL_REPEAT,
    CB_MANUAL_TIME, CB_MANUAL_URL_BTN,
    get_cabinet_inline_keyboard, get_manual_post_panel,
    get_settings_hub_keyboard, manual_channel_callback,
)
from translations import (  # noqa: E402
    MANUAL_POST_I18N, content_menu_parity_report, content_menu_t,
    manual_post_parity_report, manual_post_t,
)

USER_ID = 4242


# ---------------------------------------------------------------------------
# YORDAMCHILAR — yengil Update/Context/DB fakeri (tarmoqqa chiqmaydi)
# ---------------------------------------------------------------------------
class _Msg:
    """reply_text / reply_photo ... yozib boruvchi soxta xabar."""

    def __init__(self, text=None, chat_id=USER_ID):
        self.text = text
        self.caption = None
        self.photo = None
        self.video = None
        self.document = None
        self.animation = None
        self.voice = None
        self.sticker = None
        self.chat_id = chat_id
        self.message_id = 1
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append(dict(kind="text", text=text, **kwargs))
        return SimpleNamespace(message_id=10)

    async def reply_photo(self, photo=None, **kwargs):
        self.sent.append(dict(kind="photo", photo=photo, **kwargs))
        return SimpleNamespace(message_id=11)

    async def reply_video(self, video=None, **kwargs):
        self.sent.append(dict(kind="video", video=video, **kwargs))
        return SimpleNamespace(message_id=12)

    async def reply_document(self, document=None, **kwargs):
        self.sent.append(dict(kind="document", document=document, **kwargs))
        return SimpleNamespace(message_id=13)

    async def reply_animation(self, animation=None, **kwargs):
        self.sent.append(dict(kind="animation", animation=animation, **kwargs))
        return SimpleNamespace(message_id=14)


class _Query:
    def __init__(self, data, message=None):
        self.data = data
        self.message = message or _Msg()
        self.from_user = SimpleNamespace(id=USER_ID, first_name="Tester")
        self.answered = []
        self.edits = []

    async def answer(self, text=None, **kwargs):
        self.answered.append(text)
        return True

    async def edit_message_text(self, text, **kwargs):
        self.edits.append(dict(text=text, **kwargs))
        return True

    async def edit_message_reply_markup(self, reply_markup=None):
        self.edits.append(dict(reply_markup=reply_markup))
        return True


def _update_msg(msg):
    return SimpleNamespace(message=msg, effective_message=msg,
                           effective_user=msg.from_user, callback_query=None)


def _update_query(query):
    return SimpleNamespace(message=None, effective_message=query.message,
                           effective_user=query.from_user, callback_query=query)


def _ctx(lang="uz", user_data=None):
    ud = {"lang": lang}
    ud.update(user_data or {})
    return SimpleNamespace(
        user_data=ud, chat_data={},
        bot=SimpleNamespace(username="postassist_test_bot"),
        application=None,
    )


def _panel_callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _panel_labels(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


class _FakeDB:
    """database.run_db'ni soxtalashtiradi va chaqiruvlarni yozib boradi."""

    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []          # (funksiya nomi, {param: qiymat})
        self._orig = db_mod.run_db
        db_mod.run_db = self._fake

    async def _fake(self, fn, *args, **kwargs):
        import inspect as _ins
        name = getattr(fn, "__name__", "")
        try:
            bound = _ins.signature(fn).bind_partial(*args, **kwargs)
            record = dict(bound.arguments)
        except Exception:
            record = dict(kwargs)
        self.calls.append((name, record))
        return self.values.get(name)

    def calls_of(self, name):
        return [kw for n, kw in self.calls if n == name]

    def restore(self):
        db_mod.run_db = self._orig


def _with_channels(fake, channels):
    fake.values["get_user_channels"] = channels


def _run(coro):
    return asyncio.run(coro)


def _to_utc_naive(dt):
    """Tashkent-tz aware datetime → UTC naive (taqqoslash uchun)."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _start_manual_flow(ctx, channels):
    """✍️ entry → kontent → PREVIEW. Qaytaradi: (preview msg, state, fake)."""
    fake = _FakeDB({"get_user_channels": channels, "add_post": 777})
    msg = _Msg(text="Savdo e'loni: bugun hammasi -20%!")
    state = _run(MP.manual_post_entry(_update_msg(msg), ctx))
    if state != MP.MANUAL_AWAIT_CONTENT:
        fake.restore()
        return None, state, fake
    msg2 = _Msg(text="Savdo e'loni: bugun hammasi -20%!")
    state2 = _run(MP.manual_content_received(_update_msg(msg2), ctx))
    return msg2, state2, fake


# ============================================================================
# TEST 1 — TAYYOR MATN/RASM → DARHOL PREVIEW (AI'SIZ)
# ============================================================================
def test_direct_preview_without_ai():
    print("\n== TEST 1: tayyor matn/rasm/video → AI'siz DARHOL preview ==")
    # a) Modul darajasida kafolat: manual oqimda AI chaqiruvi YO'Q.
    src = (ROOT / "handlers/manual_post.py").read_text(encoding="utf-8")
    check("manual_post modulida AI agenti importi YO'Q",
          "utils.ai_agent" not in src and "generate_ai_response" not in src
          and "analyze_user_prompt" not in src, "")
    check("manual_post modulida kvota/bron chaqiruvi YO'Q (AI sarflanmaydi)",
          "reserve_for_flow" not in src and "reserve_ai_request" not in src, "")

    for lang in LANGS:
        # b) Matn → preview.
        ctx = _ctx(lang)
        fake = _FakeDB({"get_user_channels": [("-1001", "Kanal A")]})
        try:
            entry_msg = _Msg()
            state = _run(MP.manual_post_entry(_update_msg(entry_msg), ctx))
            check(f"[{lang}] entry → MANUAL_AWAIT_CONTENT",
                  state == MP.MANUAL_AWAIT_CONTENT, str(state))
            intro = entry_msg.sent[0]["text"]
            check(f"[{lang}] entry yo'riqnomasi — AI'siz oqim matni",
                  intro == manual_post_t("mp_intro", lang), intro[:60])

            msg = _Msg(text="Tayyor post matni — o'zgarishsiz chiqadi!")
            state2 = _run(MP.manual_content_received(_update_msg(msg), ctx))
            check(f"[{lang}] matn → PREVIEW holati", state2 == MP.MANUAL_PREVIEW, str(state2))
            check(f"[{lang}] preview darhol chiqdi (bitta javob)", len(msg.sent) == 1, str(msg.sent))
            preview_text = msg.sent[0]["text"]
            check(f"[{lang}] preview'da foydalanuvchi matni O'ZGARISHSIZ",
                  "Tayyor post matni — o'zgarishsiz chiqadi!" in preview_text,
                  preview_text[:80])
            check(f"[{lang}] preview'da universal panel bor",
                  msg.sent[0].get("reply_markup") is not None
                  and _panel_callbacks(msg.sent[0]["reply_markup"]) == [
                      CB_MANUAL_NOW, CB_MANUAL_TIME, CB_MANUAL_REACT,
                      CB_MANUAL_URL_BTN, CB_MANUAL_24H,
                      CB_MANUAL_REPEAT, CB_MANUAL_EDIT, CB_MANUAL_CANCEL],
                  str(msg.sent[0].get("reply_markup")))
            # AI chaqiruvi UMUMAN bo'lmadi.
            check(f"[{lang}] AI/analiz chaqiruvi YO'Q (DB faqat kanal o'qidi)",
                  all(n == "get_user_channels" for n, _k in fake.calls),
                  str([n for n, _k in fake.calls]))
        finally:
            fake.restore()

        # c) Rasm → media preview (caption bilan).
        ctx = _ctx(lang)
        fake = _FakeDB({"get_user_channels": [("-1001", "Kanal A")]})
        try:
            _run(MP.manual_post_entry(_update_msg(_Msg()), ctx))
            photo_msg = _Msg()
            photo_msg.photo = [SimpleNamespace(file_id="ph-1")]
            photo_msg.caption = "Mahsulot rasmi"
            state3 = _run(MP.manual_content_received(_update_msg(photo_msg), ctx))
            check(f"[{lang}] rasm → PREVIEW holati", state3 == MP.MANUAL_PREVIEW, str(state3))
            check(f"[{lang}] rasm preview'si media sifatida chiqdi",
                  photo_msg.sent and photo_msg.sent[0]["kind"] == "photo",
                  str(photo_msg.sent)[:120])
            check(f"[{lang}] rasm caption'i preview'da saqlandi",
                  "Mahsulot rasmi" in str(photo_msg.sent[0].get("caption", "")),
                  str(photo_msg.sent[0].get("caption"))[:80])
        finally:
            fake.restore()

        # d) Video → media preview.
        ctx = _ctx(lang)
        fake = _FakeDB({"get_user_channels": [("-1001", "Kanal A")]})
        try:
            _run(MP.manual_post_entry(_update_msg(_Msg()), ctx))
            video_msg = _Msg()
            video_msg.video = SimpleNamespace(file_id="vid-1")
            state4 = _run(MP.manual_content_received(_update_msg(video_msg), ctx))
            check(f"[{lang}] video → PREVIEW holati", state4 == MP.MANUAL_PREVIEW, str(state4))
            check(f"[{lang}] video preview'si media sifatida chiqdi",
                  video_msg.sent and video_msg.sent[0]["kind"] == "video",
                  str(video_msg.sent)[:120])
        finally:
            fake.restore()

        # e) Qo'llab-quvvatlanmaydigan tur (stiker) rad etiladi, oqim qoladi.
        ctx = _ctx(lang)
        fake = _FakeDB({"get_user_channels": [("-1001", "Kanal A")]})
        try:
            _run(MP.manual_post_entry(_update_msg(_Msg()), ctx))
            st = _Msg()
            st.sticker = SimpleNamespace(file_id="stk-1")
            state5 = _run(MP.manual_content_received(_update_msg(st), ctx))
            check(f"[{lang}] stiker rad etiladi, AWAIT_CONTENT saqlanadi",
                  state5 == MP.MANUAL_AWAIT_CONTENT
                  and st.sent and st.sent[0]["text"] == manual_post_t("mp_unsupported", lang),
                  str(state5))
        finally:
            fake.restore()


# ============================================================================
# TEST 2 — [🚀 HOZIR YUBORISH] oddiy oqimda to'liq ishlaydi
# ============================================================================
def test_send_now_flow():
    print("\n== TEST 2: [🚀 Hozir yuborish] — darhol kanalga chiqarish ==")
    for lang in LANGS:
        ctx = _ctx(lang)
        try:
            msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
            check(f"[{lang}] preview tayyor", state == MP.MANUAL_PREVIEW, str(state))
            q = _Query(CB_MANUAL_NOW, msg)
            final_state = _run(MP.manual_panel_callback(_update_query(q), ctx))
            check(f"[{lang}] 🚀 → post saqlandi (db.add_post)",
                  len(fake.calls_of("add_post")) == 1, str(fake.calls))
            kw = fake.calls_of("add_post")[0]
            check(f"[{lang}] 🚀 → kanal to'g'ri (-1001)", kw.get("channel_id") == "-1001", str(kw))
            check(f"[{lang}] 🚀 → kontent o'zgarishsiz saqlandi",
                  "Savdo e'loni" in str(kw.get("content", "")), str(kw))
            sched = kw.get("scheduled_time")
            now = datetime.utcnow()
            check(f"[{lang}] 🚀 → scheduled_time HOZIR (darhol chiqadi)",
                  sched is not None
                  and abs(_to_utc_naive(sched) - now) < timedelta(minutes=2),
                  str(sched))
            check(f"[{lang}] 🚀 → yakuniy xabar mp_sent_now",
                  q.message.sent and q.message.sent[-1]["text"].startswith(
                      manual_post_t("mp_sent_now", lang, channel="x").split("<b>")[0]),
                  str(q.message.sent)[:120])
            check(f"[{lang}] 🚀 → END + asosiy menyu qaytdi",
                  final_state == ConversationHandler.END
                  and q.message.sent[-1].get("reply_markup") is not None,
                  str(final_state))
        finally:
            fake.restore()

    # Ko'p kanal: avval kanal TANLANADI, keyin yuboriladi.
    ctx = _ctx("uz")
    channels = [("-1001", "Kanal A"), ("-1002", "Kanal B")]
    try:
        msg, state, fake = _start_manual_flow(ctx, channels)
        q = _Query(CB_MANUAL_NOW, msg)
        st2 = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("ko'p kanal: 🚀 → MANUAL_CHANNEL_SELECT", st2 == MP.MANUAL_CHANNEL_SELECT, str(st2))
        choice_msg = q.message.sent[-1]
        cbs = _panel_callbacks(choice_msg["reply_markup"])
        check("ko'p kanal: tanlov klaviaturasi chiqdi",
              manual_channel_callback("-1001") in cbs
              and manual_channel_callback("-1002") in cbs
              and CB_MANUAL_PANEL in cbs, str(cbs))
        # «Kanal B» tanlanadi → post aynan o'shanga chiqadi.
        q2 = _Query(manual_channel_callback("-1002"), choice_msg and _Msg())
        st3 = _run(MP.manual_panel_callback(_update_query(q2), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("ko'p kanal: tanlangan kanalga (-1002) yuborildi",
              st3 == ConversationHandler.END
              and str(kw.get("channel_id")) == "-1002", str(kw))
    finally:
        fake.restore()

    # Kanal ulanmagan bo'lsa — muloyim xabar, post SAQLANMAYDI.
    ctx = _ctx("uz")
    fake = _FakeDB({"get_user_channels": [], "add_post": 777})
    try:
        msg = _Msg()
        ctx.user_data[MP.UD_CONTENT] = "matn"
        ctx.user_data[MP.UD_POST_TYPE] = "text"
        ctx.user_data[MP.UD_MODE] = MP.MODE_NOW
        q = _Query(CB_MANUAL_NOW, msg)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("kanalsiz: 🚀 → muloyim rad + add_post CHAQIRILMADI",
              st == ConversationHandler.END and not fake.calls_of("add_post")
              and msg.sent and "kanal" in msg.sent[-1]["text"].lower(),
              str(msg.sent)[:120])
    finally:
        fake.restore()


# ============================================================================
# TEST 3 — [📅 VAQTNI BELGILASH] + [🗑 24 SOAT] + [🔄 TAKRORIY]
# ============================================================================
def test_schedule_and_announcement_flows():
    print("\n== TEST 3: 📅 Vaqtni belgilash, 🗑 24 soatlik va 🔄 takroriy ==")
    # Ertangi 19:30 — deterministik kelajak vaqt.
    tomorrow = datetime.now() + timedelta(days=1)
    when_text = tomorrow.strftime("%d.%m.%Y") + " 19:30"

    for lang in LANGS:
        # --- 📅 Vaqtni belgilash ---
        ctx = _ctx(lang)
        try:
            msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
            q = _Query(CB_MANUAL_TIME, msg)
            st2 = _run(MP.manual_panel_callback(_update_query(q), ctx))
            check(f"[{lang}] 📅 → MANUAL_TIME_INPUT", st2 == MP.MANUAL_TIME_INPUT, str(st2))
            check(f"[{lang}] 📅 → vaqt so'rovi chiqdi",
                  q.message.sent and q.message.sent[-1]["text"]
                  == manual_post_t("mp_time_prompt", lang), str(q.message.sent)[:100])

            t_msg = _Msg(text=when_text)
            st3 = _run(MP.manual_time_received(_update_msg(t_msg), ctx))
            kw = fake.calls_of("add_post")[-1] if fake.calls_of("add_post") else {}
            sched = kw.get("scheduled_time")
            check(f"[{lang}] 📅 '{when_text}' → post rejalashtirildi",
                  st3 == ConversationHandler.END and sched is not None,
                  f"{st3} {sched}")
            check(f"[{lang}] 📅 → vaqt aniq saqlandi (19:30)",
                  sched is not None and sched.hour == 19 and sched.minute == 30,
                  str(sched))
            check(f"[{lang}] 📅 → yakuniy xabar mp_scheduled",
                  t_msg.sent and "📅" in t_msg.sent[-1]["text"]
                  and "19:30" in t_msg.sent[-1]["text"], str(t_msg.sent)[:160])
        finally:
            fake.restore()

    # Noto'g'ri vaqt rad etiladi (oqim saqlanadi).
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_TIME, msg)), ctx))
        bad = _Msg(text="salom")
        st_bad = _run(MP.manual_time_received(_update_msg(bad), ctx))
        check("📅 noto'g'ri vaqt → rad + MANUAL_TIME_INPUT saqlanadi",
              st_bad == MP.MANUAL_TIME_INPUT
              and bad.sent and bad.sent[-1]["text"] == manual_post_t("mp_time_invalid", "uz"),
              str(st_bad))
    finally:
        fake.restore()

    # --- 🗑 24 soatlik e'lon: darhol chiqadi + delete_after_hours=24 ---
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
        q = _Query(CB_MANUAL_24H, msg)
        st = _run(MP.manual_panel_callback(_update_query(q), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("🗑 24 soatlik e'lon → delete_after_hours=24",
              kw.get("delete_after_hours") == 24, str(kw))
        check("🗑 24 soatlik e'lon → darhol chiqadi (scheduled_time≈hozir)",
              abs(_to_utc_naive(kw.get("scheduled_time")) - datetime.utcnow())
              < timedelta(minutes=2), str(kw.get("scheduled_time")))
        check("🗑 24 soatlik e'lon → mp_sent_24h xabari + END",
              st == ConversationHandler.END and q.message.sent
              and "24" in q.message.sent[-1]["text"], str(q.message.sent)[:120])
    finally:
        fake.restore()

    # --- 🔄 Takroriy e'lon: har kuni 19:30 da ---
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
        q = _Query(CB_MANUAL_REPEAT, msg)
        st2 = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("🔄 takroriy → vaqt so'rovi (MANUAL_TIME_INPUT)",
              st2 == MP.MANUAL_TIME_INPUT, str(st2))
        t_msg = _Msg(text="19:30")
        st3 = _run(MP.manual_time_received(_update_msg(t_msg), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("🔄 takroriy → recurrence_type='daily'",
              kw.get("recurrence_type") == "daily", str(kw))
        check("🔄 takroriy → recurrence_time='19:30:00'",
              kw.get("recurrence_time") == "19:30:00", str(kw))
        check("🔄 takroriy → mp_repeat_ok xabari + END",
              st3 == ConversationHandler.END and t_msg.sent
              and "🔄" in t_msg.sent[-1]["text"], str(t_msg.sent)[:120])
    finally:
        fake.restore()

    # --- ✏️ Tahrirlash va ❌ Bekor qilish ---
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx, [("-1001", "Kanal A")])
        q = _Query(CB_MANUAL_EDIT, msg)
        st2 = _run(MP.manual_panel_callback(_update_query(q), ctx))
        check("✏️ tahrirlash → MANUAL_EDIT_INPUT", st2 == MP.MANUAL_EDIT_INPUT, str(st2))
        new_msg = _Msg(text="Yangilangan matn")
        st3 = _run(MP.manual_edit_received(_update_msg(new_msg), ctx))
        check("✏️ yangi matn → preview yangilandi (MANUAL_PREVIEW)",
              st3 == MP.MANUAL_PREVIEW and ctx.user_data[MP.UD_CONTENT] == "Yangilangan matn"
              and new_msg.sent and "Yangilangan matn" in new_msg.sent[-1]["text"],
              str(new_msg.sent)[:120])
        q2 = _Query(CB_MANUAL_CANCEL, new_msg)
        st4 = _run(MP.manual_panel_callback(_update_query(q2), ctx))
        check("❌ bekor qilish → END + mp_cancelled + kontent tozalandi",
              st4 == ConversationHandler.END
              and q2.message.sent and q2.message.sent[-1]["text"]
              == manual_post_t("mp_cancelled", "uz")
              and not ctx.user_data.get(MP.UD_CONTENT),
              str(q2.message.sent)[:120])
    finally:
        fake.restore()


# ============================================================================
# TEST 4 — UNIVERSAL PANEL SPEKSI (barcha tugmalar + i18n)
# ============================================================================
def test_universal_panel_spec():
    print("\n== TEST 4: universal boshqaruv paneli — speksdagi tugmalar ==")
    expected_cbs = [CB_MANUAL_NOW, CB_MANUAL_TIME, CB_MANUAL_REACT,
                    CB_MANUAL_URL_BTN, CB_MANUAL_24H,
                    CB_MANUAL_REPEAT, CB_MANUAL_EDIT, CB_MANUAL_CANCEL]
    for lang in LANGS:
        kb = get_manual_post_panel(lang)
        cbs = _panel_callbacks(kb)
        labels = _panel_labels(kb)
        check(f"[{lang}] panel callback'lari speks tartibida",
              cbs == expected_cbs, str(cbs))
        expected_labels = [
            manual_post_t("mp_btn_send_now", lang),
            manual_post_t("mp_btn_schedule", lang),
            manual_post_t("mp_btn_reactions", lang),
            manual_post_t("mp_btn_url_btn", lang),
            manual_post_t("mp_btn_24h", lang),
            manual_post_t("mp_btn_repeat", lang),
            manual_post_t("mp_btn_edit", lang),
            manual_post_t("mp_btn_cancel", lang),
        ]
        check(f"[{lang}] panel yorliqlari i18n orqali", labels == expected_labels, str(labels))
    # Yorliqlar speksdagi emojilar bilan boshlanadi.
    uz_labels = _panel_labels(get_manual_post_panel("uz"))
    check("panel: 🚀 / 📅 / ❤️ / 🔗 / 🗑 / 🔄 / ✏️ / ❌ emojilari mavjud",
          uz_labels[0].startswith("🚀") and uz_labels[1].startswith("📅")
          and uz_labels[2].startswith("❤️") and uz_labels[3].startswith("🔗")
          and uz_labels[4].startswith("🗑") and uz_labels[5].startswith("🔄")
          and uz_labels[6].startswith("✏️") and uz_labels[7].startswith("❌"),
          str(uz_labels))
    check("panel: «Hozir yuborish» va «Vaqtni belgilash» aniq",
          "Hozir yuborish" in uz_labels[0] and "Vaqtni belgilash" in uz_labels[1],
          str(uz_labels))
    check("panel: «Reaksiyalar» va «Havolali tugma» aniq",
          "Reaksiyalar" in uz_labels[2] and "Havolali tugma" in uz_labels[3],
          str(uz_labels))
    check("panel: «24 soatlik e'lon» va «Takroriy e'lon» aniq",
          "24 soatlik" in uz_labels[4] and "Takroriy" in uz_labels[5], str(uz_labels))
    check("panel: «Tahrirlash» | «Bekor qilish» aniq",
          "Tahrirlash" in uz_labels[6] and "Bekor qilish" in uz_labels[7], str(uz_labels))
    # Har bir tugma FSM'da real handlerga ulangan (conv.states tekshiruvi).
    from telegram.ext import CallbackQueryHandler as CQH
    app = _build_app()
    conv = [h for h in _all_handlers(app) if isinstance(h, ConversationHandler)][0]
    handlers_preview = conv.states[MP.MANUAL_PREVIEW]
    pattern_handlers = [h for h in handlers_preview
                        if isinstance(h, CQH) and getattr(h, "pattern", None)]
    matched = set()
    for h in pattern_handlers:
        for data in expected_cbs + [manual_channel_callback("-1001")]:
            if re.search(h.pattern, data):
                matched.add(data)
    check("panel: barcha tugmalar MANUAL_PREVIEW holatida ushlanadi",
          set(expected_cbs) <= matched and manual_channel_callback("-1001") in matched
          or set(expected_cbs) <= matched, str(matched))


def _build_app():
    import warnings as _w
    from telegram.ext import ApplicationBuilder
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:MANUAL_POST_TEST").build()
    H.register_all_handlers(app)
    return app


def _all_handlers(app):
    return [h for group in sorted(app.handlers) for h in app.handlers[group]]


# ============================================================================
# TEST 5 — BIRLASHTIRILGAN KONTENT YARATISH MENYUSI
# ============================================================================
def test_unified_content_menu():
    print("\n== TEST 5: birlashtirilgan kontent yaratish menyusi ==")
    from keyboards.default import content_creation_rows, get_content_creation_keyboard

    expected = {
        "uz": [["✍️ Oddiy post (AI'siz)"],
               ["✨ AI bilan yaratish (Magic Post)"],
               ["🤖 AI Studio"],
               ["◀️ Orqaga"]],
        "ru": [["✍️ Обычный пост (без AI)"],
               ["✨ Создать с AI (Magic Post)"],
               ["🤖 AI Studio"],
               ["◀️ Назад"]],
        "en": [["✍️ Regular post (no AI)"],
               ["✨ Create with AI (Magic Post)"],
               ["🤖 AI Studio"],
               ["◀️ Back"]],
    }
    for lang in LANGS:
        rows = content_creation_rows(lang)
        check(f"[{lang}] menyu aniq 3 yo'nalish + Orqaga",
              rows == expected[lang], str(rows))
        kb = get_content_creation_keyboard(lang)
        flat = [t for row in kb.keyboard for t in row]
        check(f"[{lang}] dublikat tugma yo'q", len(flat) == len(set(flat)), str(flat))

    # Eski chalkash tugmalar (AI Yordamchi, bir nechta Rasm->Post ...) endi
    # ko'rinadigan menyuda YO'Q.
    legacy = {"📝 Matn → Post", "📸 Rasm → Post", "🎙 Ovoz → Post", "🤖 AI Yordamchi"}
    visible = {t for lang in LANGS for t in
               [b for row in get_content_creation_keyboard(lang).keyboard for b in row]}
    check("eski bo'lingan tugmalar menyudan olib tashlangan",
          not (legacy & visible), str(legacy & visible))

    # Routing: har bir yo'nalish real handlerga ega.
    from telegram.ext import MessageHandler, filters as f
    app = _build_app()
    regex = [h for h in _all_handlers(app)
             if isinstance(h, MessageHandler) and isinstance(h.filters, f.Regex)]

    def targets(label):
        from telegram import Update
        upd = Update.de_json({
            "update_id": 1,
            "message": {"message_id": 10, "date": 0,
                        "chat": {"id": 42, "type": "private"},
                        "from": {"id": 42, "is_bot": False, "first_name": "T"},
                        "text": label},
        }, None)
        names = set()
        for h in regex:
            if not h.check_update(upd):
                continue
            cb = h.callback
            nm = getattr(cb, "__name__", "")
            if nm not in ("", "<lambda>"):
                names.add(nm)
                continue
            for n in getattr(getattr(cb, "__code__", None), "co_names", ()):
                if n in ("guard_entry", "guard_menu"):
                    continue
                if callable(getattr(H, n, None)):
                    names.add(n)
        return names

    checks = {
        "✍️ Oddiy post (AI'siz)": {"manual_post_entry"},
        "✨ AI bilan yaratish (Magic Post)": {"magic_post_entry"},
        "🤖 AI Studio": {"ai_studio_hub_entry"},
        "◀️ Orqaga": {"content_creation_back"},
        # eski aliaslar
        "📝 Matn → Post": {"manual_post_entry"},
        "🎙 Ovoz → Post": {"voice_post_entry"},
        "🤖 AI Yordamchi": {"ai_studio_hub_entry"},
        "📸 Rasm → Post": {"image_post_entry"},
        "✨ Magic Post": {"magic_post_entry"},
    }
    for label, expected_names in checks.items():
        got = targets(label)
        check(f"routing: {label!r} → {sorted(expected_names)}",
              got == expected_names, str(sorted(got)))

    # ✍️ Oddiy post oqimi AI'dan UMUMAN foydalanmaydi: entry'da kredit/limit
    # tekshiruvi yo'q (start_new_post'dan farqli o'laroq — bu yerda AI yo'q).
    entry_src = re.search(
        r"async def manual_post_entry.*?(?=\nasync def )", 
        (ROOT / "handlers/manual_post.py").read_text(encoding="utf-8"), re.S)
    check("manual_post_entry: AI limit/kredit tekshiruvi YO'Q",
          entry_src and "is_premium" not in entry_src.group(0)
          and "credits" not in entry_src.group(0), "")


# ============================================================================
# TEST 6 — PROFIL TOZALIGI: Til tugmasi profildan chiqarilgan
# ============================================================================
def test_profile_cleanup():
    print("\n== TEST 6: profil tozaligi — Til faqat Sozlamalar ichida ==")
    # 1) 👤 Profil inline klaviaturasida «🌐 Til» tugmasi YO'Q.
    for lang in LANGS:
        cbs = [b.callback_data for row in
               get_cabinet_inline_keyboard(lang).inline_keyboard for b in row]
        labels = [b.text for row in
                  get_cabinet_inline_keyboard(lang).inline_keyboard for b in row]
        check(f"[{lang}] profil klaviaturasida cab_lang YO'Q",
              "cab_lang" not in cbs, str(cbs))
        check(f"[{lang}] profil yorliqlarida 'Til/Язык/Language' YO'Q",
              not any(("Til" in lb and "🌐" in lb) or ("Язык" in lb and "🌐" in lb)
                      or (lb.strip().startswith("🌐")) for lb in labels), str(labels))

    # 2) 🌐 Til Sozlamalar hub'ida SAQLANGAN (yagona joy).
    for lang in LANGS:
        hub_cbs = [b.callback_data for row in
                   get_settings_hub_keyboard(lang).inline_keyboard for b in row]
        check(f"[{lang}] sozlamalar hub'ida stgs_lang bor",
              "stgs_lang" in hub_cbs, str(hub_cbs))

    # 3) Til almashtirish oqimi (cab_lang_*) o'zgarmagan — routing saqlanadi.
    from keyboards.inline import get_language_keyboard
    for lang in LANGS:
        lk_cbs = [b.callback_data for row in
                  get_language_keyboard(lang).inline_keyboard for b in row]
        check(f"[{lang}] til tanlash klaviaturasi (cab_lang_uz/ru/en) saqlangan",
              {"cab_lang_uz", "cab_lang_ru", "cab_lang_en"} <= set(lk_cbs), str(lk_cbs))

    # 4) 👤 Profil ekrani: ID, obuna holati, balans/kreditlar ko'rsatiladi.
    fake = _FakeDB({
        "get_referral_stats": {"ai_credits": 12, "streak": 3, "referrals_count": 2},
        "get_user_channels": [("-1001", "Kanal A")],
        "get_user_code": "AB1",
        "get_user_plan": {"plan_type": "pro",
                          "expires_at": datetime(2026, 10, 1, 0, 0)},
    })
    try:
        q = _Query("stgs_profile")
        ctx = _ctx("uz")
        _run(STG._render_profile_screen(q, ctx, USER_ID, "uz", False))
        screen = q.edits[0] if q.edits else (q.message.sent[0] if q.message.sent else {})
        text = screen.get("text", "")
        cbs = []
        markup = screen.get("reply_markup")
        if markup is not None:
            cbs = [b.callback_data for row in markup.inline_keyboard for b in row]
        check("profil ekran: ID ko'rsatiladi", str(USER_ID) in text, text[:120])
        check("profil ekran: obuna holati (PRO) ko'rsatiladi",
              "PRO" in text and "Obuna" in text, text[:160])
        check("profil ekran: balans/kredit ko'rsatiladi", "12" in text, text[:160])
        check("profil ekran: klaviaturada cab_lang YO'Q",
              "cab_lang" not in cbs, str(cbs))
        check("profil ekran: stgs_hub orqaga tugmasi bor", "stgs_hub" in cbs, str(cbs))
    finally:
        fake.restore()

    # 5) FREE foydalanuvchi uchun obuna holati — FREE.
    fake = _FakeDB({
        "get_referral_stats": {"ai_credits": 0, "streak": 0, "referrals_count": 0},
        "get_user_channels": [],
        "get_user_code": "CD2",
        "get_user_plan": {"plan_type": "free", "expires_at": None},
    })
    try:
        q = _Query("stgs_profile")
        ctx = _ctx("uz")
        _run(STG._render_profile_screen(q, ctx, USER_ID, "uz", False))
        screen = q.edits[0] if q.edits else {}
        check("profil ekran (free): FREE holati ko'rsatiladi",
              "FREE" in screen.get("text", ""), screen.get("text", "")[:160])
    finally:
        fake.restore()


# ============================================================================
# TEST 7 — i18n PARITET VA REGRESSIYA QO'RIQONLARI
# ============================================================================
def test_i18n_parity_and_guards():
    print("\n== TEST 7: i18n paritet + regressiya qo'riqonlari ==")
    rep_manual = manual_post_parity_report()
    check("manual_post pariteti in_sync", rep_manual["in_sync"] is True,
          str({k: rep_manual.get(k) for k in ("missing", "extra", "empty")}))
    check("manual_post kalitlar soni >= 20", rep_manual["keys"] >= 20,
          str(rep_manual["keys"]))
    check("MANUAL_POST_KEYS lug'at bilan bir xil",
          set(MANUAL_POST_I18N["uz"]) == set(__import__("translations", fromlist=["x"]).MANUAL_POST_KEYS), "")

    rep_content = content_menu_parity_report()
    check("content_menu pariteti in_sync", rep_content["in_sync"] is True,
          str({k: rep_content.get(k) for k in ("missing", "extra", "empty")}))

    # Uchala tilda preview panel matnlari FARQ qiladi (tarjima qilingan).
    texts = {lang: manual_post_t("mp_intro", lang) for lang in LANGS}
    check("mp_intro: 3 tilda farqli matn", len(set(texts.values())) == 3,
          str(list(texts.values()))[:120])
    foot = {lang: manual_post_t("mp_preview_foot", lang) for lang in LANGS}
    check("mp_preview_foot: 3 tilda farqli matn", len(set(foot.values())) == 3, "")

    # FSM holatlari noyobligi.
    import handlers.magic_post as mp_mod
    import handlers.post_score as ps_mod
    manual_states = {MP.MANUAL_AWAIT_CONTENT, MP.MANUAL_PREVIEW,
                     MP.MANUAL_CHANNEL_SELECT, MP.MANUAL_TIME_INPUT,
                     MP.MANUAL_EDIT_INPUT}
    check("manual FSM holatlari magic/post_score bilan to'qnashmaydi",
          not (manual_states & ({mp_mod.MAGIC_INPUT, mp_mod.MAGIC_STYLE_SELECT,
                                 mp_mod.MAGIC_RESULT, mp_mod.MAGIC_SEND_CHOOSE}
                                | {ps_mod.POST_SCORE_INPUT, ps_mod.POST_SCORE_RESULT,
                                   ps_mod.POST_SCORE_SEND_CHOOSE})), "")

    # Callback'lar 64-bayt chegarasida.
    from keyboards.callback_data import CALLBACK_DATA_MAX_BYTES, callback_byte_len
    for data in [CB_MANUAL_NOW, CB_MANUAL_TIME, CB_MANUAL_24H, CB_MANUAL_REPEAT,
                 CB_MANUAL_EDIT, CB_MANUAL_CANCEL, CB_MANUAL_PANEL,
                 manual_channel_callback("-1009876543210987")]:
        check(f"callback {data!r} <= 64 bayt",
              callback_byte_len(data) <= CALLBACK_DATA_MAX_BYTES, data)

    # Stale entry himoyasi: sessiyasiz mnp_ tugma muloyim javob beradi.
    ctx = _ctx("uz")
    q = _Query("mnp_now")
    st = _run(MP.manual_stale_callback(_update_query(q), ctx))
    check("stale mnp_ → sessiya eskirgani haqida javob + END",
          st == ConversationHandler.END
          and q.message.sent and q.message.sent[-1]["text"]
          == manual_post_t("mp_session_expired", "uz"), str(q.message.sent)[:120])

    # Sessiyasiz panel tugmasi (content yo'q) ham xavfsiz.
    ctx2 = _ctx("uz")
    q2 = _Query(CB_MANUAL_NOW)
    st2 = _run(MP.manual_panel_callback(_update_query(q2), ctx2))
    check("panelsiz content: 🚀 → sessiya eskirgan xabari (crash yo'q)",
          st2 == ConversationHandler.END and q2.message.sent
          and q2.message.sent[-1]["text"] == manual_post_t("mp_session_expired", "uz"),
          str(q2.message.sent)[:120])


# ============================================================================
def main():
    print("=" * 70)
    print(" ✍️ ODDIY (AI'SIZ) POSTING + BIRLASHTIRILGAN MENYU — QABUL TESTI")
    print("=" * 70)
    test_direct_preview_without_ai()
    test_send_now_flow()
    test_schedule_and_announcement_flows()
    test_universal_panel_spec()
    test_unified_content_menu()
    test_profile_cleanup()
    test_i18n_parity_and_guards()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" ODDIY POSTING VA BIRLASHTIRILGAN MENYU TESTLARI 100% YASHIL ✔")
    print("=" * 70)
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
