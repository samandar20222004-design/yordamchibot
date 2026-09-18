#!/usr/bin/env python3
"""❤️ REAKSIYALAR + 🔗 HAVOLALI TUGMA — MANUAL POST PREVIEW BOYITISH (2-QADAM).

DIQQAT: POSTASSIST UI/UX POLISH — oddiy (AI'siz) post preview paneli
boyitildi: admin kanalga chiqarishdan oldin reaksiyalar (👍/❤️/🔥...) va
havolali inline tugma (URL button) qo'sha oladi. QAT'IY QOIDA: hech
qanday chalkashlik — barcha mavjud oqimlar (🚀/📅/🗑/🔄/✏️/❌) saqlanadi.

Qamrov (topshiriq spetsifikatsiyasi bilan birma-bir):

  TEST 1:  Preview paneli SPEKSDAGI 4 qatorli tartibda:
           [🚀 Hozir yuborish | 📅 Vaqtni belgilash]
           [❤️ Reaksiyalar | 🔗 Havolali tugma]
           [🗑 24 soatlik e'lon | 🔄 Takroriy e'lon]
           [✏️ Tahrirlash | ❌ Bekor qilish]
           (uz/ru/en yorliqlar, 64-bayt kafolati).
  TEST 2:  ❤️ REAKSIYALAR oqimi — preset klaviatura ([👍/👎] | [🔥/❤️/👏]
           | [➕ O'zim kiritaman | ◀️ Orqaga]), toggle tanlash, qo'lda
           kiritish, preview yangilanishi va add_post'ga uzatilishi.
  TEST 3:  🔗 HAVOLALI TUGMA oqimi — format yo'riqnomasi, to'g'ri kiritma
           qabuli (preview'da HAQIQIY URL tugma), XAVFLI URL'larning
           (javascript:, file:, data:, ftp:) rad etilishi va add_post'ga
           btn_text/btn_url sifatida uzatilishi.
  TEST 4:  SCHEDULER/DELIVERY birlashmasi — reaksiyalar va URL tugma
           db.add_post → scheduled_posts → scheduler reply_markup zanjirida
           to'liq saqlanadi.
  TEST 5:  FSM/ROUTING/I18N qo'riqonlari — yangi holatlar (455/456)
           noyob, yangi callback'lar MANUAL_PREVIEW'da ushlanadi, stale
           himoya (``^mnp_``) ularni ham qamrab oladi, uz/ru/en paritet.

Ishga tushirish:
    PYTHON=/tmp/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/manual_post_reactions_and_url_buttons_test.py
"""
import asyncio
import inspect
import os
import re
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:MANUAL_REACT_URL_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10004")

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
import database as db_mod  # noqa: E402
from keyboards.inline import (  # noqa: E402
    CB_MANUAL_24H, CB_MANUAL_CANCEL, CB_MANUAL_EDIT, CB_MANUAL_NOW,
    CB_MANUAL_REACT, CB_MANUAL_REACT_BACK, CB_MANUAL_REACT_CUSTOM,
    CB_MANUAL_REACT_TOGGLE, CB_MANUAL_REPEAT, CB_MANUAL_TIME,
    CB_MANUAL_URL_BTN, build_reaction_button_rows, get_manual_post_panel,
    manual_reaction_toggle_callback,
)
from translations import (  # noqa: E402
    MANUAL_POST_I18N, manual_post_parity_report, manual_post_t,
)

USER_ID = 7777


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


def _markup_rows(markup):
    return [[b for b in row] for row in markup.inline_keyboard]


def _flat_cbs(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _flat_buttons(markup):
    return [b for row in markup.inline_keyboard for b in row]


class _FakeDB:
    """database.run_db'ni soxtalashtiradi va chaqiruvlarni yozib boradi."""

    def __init__(self, values=None):
        self.values = values or {}
        self.calls = []
        self._orig = db_mod.run_db
        db_mod.run_db = self._fake

    async def _fake(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        try:
            bound = inspect.signature(fn).bind_partial(*args, **kwargs)
            record = dict(bound.arguments)
        except Exception:
            record = dict(kwargs)
        self.calls.append((name, record))
        return self.values.get(name)

    def calls_of(self, name):
        return [kw for n, kw in self.calls if n == name]

    def restore(self):
        db_mod.run_db = self._orig


def _run(coro):
    return asyncio.run(coro)


def _start_manual_flow(ctx, channels=(("-1001", "Kanal A"),)):
    """✍️ entry → kontent → PREVIEW. Qaytaradi: (preview msg, state, fake)."""
    fake = _FakeDB({"get_user_channels": list(channels), "add_post": 555})
    msg = _Msg(text="Yangi mahsulot: endi -30% chegirma!")
    state = _run(MP.manual_post_entry(_update_msg(msg), ctx))
    if state != MP.MANUAL_AWAIT_CONTENT:
        fake.restore()
        return None, state, fake
    msg2 = _Msg(text="Yangi mahsulot: endi -30% chegirma!")
    state2 = _run(MP.manual_content_received(_update_msg(msg2), ctx))
    return msg2, state2, fake


def _build_app():
    from telegram.ext import ApplicationBuilder
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:REACT_URL_TEST").build()
    H.register_all_handlers(app)
    return app


def _main_conv(app):
    from telegram.ext import ConversationHandler
    return [h for h in (h for g in sorted(app.handlers) for h in app.handlers[g])
            if isinstance(h, ConversationHandler)][0]


# ============================================================================
# TEST 1 — 4 QATORLI BOYITILGAN PREVIEW PANELI (SPEKS)
# ============================================================================
def test_panel_four_rows_spec():
    print("\n== TEST 1: preview paneli — 4 qatorli boyitilgan speks ==")
    expected_rows = [
        [(CB_MANUAL_NOW, "🚀"), (CB_MANUAL_TIME, "📅")],
        [(CB_MANUAL_REACT, "❤️"), (CB_MANUAL_URL_BTN, "🔗")],
        [(CB_MANUAL_24H, "🗑"), (CB_MANUAL_REPEAT, "🔄")],
        [(CB_MANUAL_EDIT, "✏️"), (CB_MANUAL_CANCEL, "❌")],
    ]
    for lang in LANGS:
        kb = get_manual_post_panel(lang)
        rows = _markup_rows(kb)
        check(f"[{lang}] panel AYNAN 4 qator", len(rows) == 4, str(len(rows)))
        ok_shape = all(len(r) == 2 for r in rows)
        check(f"[{lang}] har qatorda 2 tadan tugma", ok_shape, str(rows))
        for i, row in enumerate(rows):
            for j, btn in enumerate(row):
                exp_cb, exp_emoji = expected_rows[i][j]
                check(f"[{lang}] qator{i+1}[{j+1}] callback={exp_cb}",
                      btn.callback_data == exp_cb, str(btn.callback_data))
                check(f"[{lang}] qator{i+1}[{j+1}] emoji {exp_emoji}",
                      btn.text.startswith(exp_emoji), str(btn.text))
        # Yorliqlar i18n lug'atidan olinadi.
        labels = [b.text for b in _flat_buttons(kb)]
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
        check(f"[{lang}] 8 yorliq i18n orqali", labels == expected_labels,
              str(labels))

    # Yangi tugma callback'lari kanonik va 64-bayt chegarasida.
    from keyboards.callback_data import CALLBACK_DATA_MAX_BYTES, callback_byte_len
    check("yangi callback konstantalari kanonik",
          CB_MANUAL_REACT == "mnp_react" and CB_MANUAL_URL_BTN == "mnp_url"
          and CB_MANUAL_REACT_TOGGLE == "mnp_rt:"
          and CB_MANUAL_REACT_CUSTOM == "mnp_radd"
          and CB_MANUAL_REACT_BACK == "mnp_rback", "")
    for data in [CB_MANUAL_REACT, CB_MANUAL_URL_BTN, CB_MANUAL_REACT_CUSTOM,
                 CB_MANUAL_REACT_BACK,
                 manual_reaction_toggle_callback("👍"),
                 manual_reaction_toggle_callback("❤️")]:
        check(f"callback {data!r} 1..64 bayt",
              1 <= callback_byte_len(data) <= CALLBACK_DATA_MAX_BYTES, data)

    # Mavjud oqimlar buzilmagan: eski 6 amal ham panelda qolgan.
    uz_cbs = _flat_cbs(get_manual_post_panel("uz"))
    for legacy in [CB_MANUAL_NOW, CB_MANUAL_TIME, CB_MANUAL_24H,
                   CB_MANUAL_REPEAT, CB_MANUAL_EDIT, CB_MANUAL_CANCEL]:
        check(f"mavjud oqim saqlangan: {legacy}", legacy in uz_cbs, str(uz_cbs))
    check("panel: dublikat tugma yo'q", len(uz_cbs) == len(set(uz_cbs)),
          str(uz_cbs))


# ============================================================================
# TEST 2 — ❤️ REAKSIYALAR OQIMI (presetlar, toggle, qo'lda, preview, publish)
# ============================================================================
def test_reactions_flow():
    print("\n== TEST 2: ❤️ Reaksiyalar — presetlar, toggle, preview, publish ==")
    # a) [❤️ Reaksiyalar] → preset klaviatura (SPEKS: [👍/👎] | [🔥/❤️/👏]
    #    | [➕ O'zim kiritaman | ◀️ Orqaga]).
    for lang in LANGS:
        ctx = _ctx(lang)
        try:
            msg, state, fake = _start_manual_flow(ctx)
            check(f"[{lang}] preview tayyor", state == MP.MANUAL_PREVIEW, str(state))
            q = _Query(CB_MANUAL_REACT, msg)
            st = _run(MP.manual_panel_callback(_update_query(q), ctx))
            check(f"[{lang}] ❤️ → MANUAL_PREVIEW saqlanadi",
                  st == MP.MANUAL_PREVIEW, str(st))
            prompt = q.message.sent[-1]
            check(f"[{lang}] reaksiya yo'riqnomasi chiqdi",
                  prompt["text"] == manual_post_t("mp_react_prompt", lang),
                  str(prompt.get("text"))[:80])
            kb = prompt.get("reply_markup")
            check(f"[{lang}] reaksiya klaviaturasi bor", kb is not None, "")
            rows = _markup_rows(kb)
            check(f"[{lang}] preset: 3 qator (2 / 3 / 2 tugma)",
                  [len(r) for r in rows] == [2, 3, 2], str([len(r) for r in rows]))
            check(f"[{lang}] qator1: 👍 va 👎",
                  [b.callback_data for b in rows[0]] == [
                      manual_reaction_toggle_callback("👍"),
                      manual_reaction_toggle_callback("👎")],
                  str([b.callback_data for b in rows[0]]))
            check(f"[{lang}] qator2: 🔥 ❤️ 👏",
                  [b.callback_data for b in rows[1]] == [
                      manual_reaction_toggle_callback(e)
                      for e in ("🔥", "❤️", "👏")],
                  str([b.callback_data for b in rows[1]]))
            check(f"[{lang}] qator3: ➕ O'zim kiritaman | ◀️ Orqaga",
                  [b.callback_data for b in rows[2]] == [
                      CB_MANUAL_REACT_CUSTOM, CB_MANUAL_REACT_BACK],
                  str([b.callback_data for b in rows[2]]))
        finally:
            fake.restore()

    # b) Toggle: 👍 va 🔥 tanlanadi → ✅ belgi; preview'da aks etadi.
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_REACT, msg)), ctx))
        q1 = _Query(manual_reaction_toggle_callback("👍"), _Msg())
        st1 = _run(MP.manual_panel_callback(_update_query(q1), ctx))
        check("toggle 👍 → MANUAL_PREVIEW + user_data saqlandi",
              st1 == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_REACTIONS) == ["👍"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        check("toggle 👍 → klaviatura joyida yangilandi (edit_message_reply_markup)",
              len(q1.edits) == 1 and q1.edits[0].get("reply_markup") is not None,
              str(q1.edits)[:120])
        q2 = _Query(manual_reaction_toggle_callback("🔥"), _Msg())
        _run(MP.manual_panel_callback(_update_query(q2), ctx))
        check("toggle 🔥 → tanlov ['👍', '🔥']",
              ctx.user_data.get(MP.UD_REACTIONS) == ["👍", "🔥"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        edited_kb = q2.edits[0]["reply_markup"]
        edited_labels = [b.text for b in _flat_buttons(edited_kb)]
        check("tanlanganlar ✅ bilan belgilangan",
              "✅ 👍" in edited_labels and "✅ 🔥" in edited_labels
              and "❤️" in edited_labels, str(edited_labels))

        # Takror bosish → tanlovdan O'CHADI.
        q3 = _Query(manual_reaction_toggle_callback("👍"), _Msg())
        _run(MP.manual_panel_callback(_update_query(q3), ctx))
        check("toggle 👍 (takror) → o'chirildi",
              ctx.user_data.get(MP.UD_REACTIONS) == ["🔥"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))

        # ◀️ Orqaga → preview YANGILANADI: reaksiya xulosasi + preview tugmalar.
        q_back = _Query(CB_MANUAL_REACT_BACK, _Msg())
        st_back = _run(MP.manual_panel_callback(_update_query(q_back), ctx))
        check("◀️ Orqaga → MANUAL_PREVIEW", st_back == MP.MANUAL_PREVIEW, str(st_back))
        preview = q_back.message.sent[-1]
        check("preview matnida reaksiya xulosasi bor",
              manual_post_t("mp_reactions_on", "uz", emojis="🔥")
              in preview["text"], preview["text"][:140])
        pv_cbs = _flat_cbs(preview["reply_markup"])
        check("preview markup'da reaksiya preview tugmalari bor",
              "enh:noop" in pv_cbs and CB_MANUAL_NOW in pv_cbs, str(pv_cbs))
        pv_labels = [b.text for b in _flat_buttons(preview["reply_markup"])]
        check("preview markup'da 🔥 emoji tugmasi ko'rinadi",
              "🔥" in pv_labels, str(pv_labels))

        # Publish: reaksiyalar db.add_post'ga to'liq uzatiladi.
        q_go = _Query(CB_MANUAL_NOW, q_back.message)
        st_go = _run(MP.manual_panel_callback(_update_query(q_go), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("publish: add_post chaqirildi + END",
              st_go == ConversationHandler.END and kw, str(st_go))
        check("publish: enable_reactions=True",
              kw.get("enable_reactions") is True, str(kw))
        check("publish: reaction_emojis='🔥'",
              kw.get("reaction_emojis") == "🔥", str(kw.get("reaction_emojis")))
    finally:
        fake.restore()

    # c) ➕ O'zim kiritaman — qo'lda emoji kiritish FSM oqimi.
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_REACT, msg)), ctx))
        q_add = _Query(CB_MANUAL_REACT_CUSTOM, _Msg())
        st_add = _run(MP.manual_panel_callback(_update_query(q_add), ctx))
        check("➕ O'zim kiritaman → MANUAL_REACTION_CUSTOM (455)",
              st_add == MP.MANUAL_REACTION_CUSTOM
              and MP.MANUAL_REACTION_CUSTOM == 455, str(st_add))
        check("qo'lda kiritish yo'riqnomasi chiqdi",
              q_add.message.sent[-1]["text"]
              == manual_post_t("mp_react_custom_prompt", "uz"),
              str(q_add.message.sent[-1].get("text"))[:80])

        # Noto'g'ri kiritma (emoji yo'q) — holat SAQLANADI.
        bad = _Msg(text="salom dunyo")
        st_bad = _run(MP.manual_reaction_custom_received(_update_msg(bad), ctx))
        check("emoji'siz matn rad etiladi (holat saqlanadi)",
              st_bad == MP.MANUAL_REACTION_CUSTOM
              and bad.sent[-1]["text"] == manual_post_t("mp_react_custom_invalid", "uz"),
              str(st_bad))
        check("emoji'siz matn tanlovga TA'SIR qilmaydi",
              not ctx.user_data.get(MP.UD_REACTIONS),
              str(ctx.user_data.get(MP.UD_REACTIONS)))

        # To'g'ri kiritma → preview yangilanadi.
        good = _Msg(text="😍 💯 va albatta 🙏")
        st_good = _run(MP.manual_reaction_custom_received(_update_msg(good), ctx))
        check("qo'lda emoji → MANUAL_PREVIEW", st_good == MP.MANUAL_PREVIEW,
              str(st_good))
        check("qo'lda emoji saqlandi (emoji'siz so'zlar tashlandi)",
              ctx.user_data.get(MP.UD_REACTIONS) == ["😍", "💯", "🙏"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        check("qo'lda emoji bilan preview yangilandi",
              good.sent and manual_post_t(
                  "mp_reactions_on", "uz", emojis="😍 💯 🙏") in good.sent[-1]["text"],
              str(good.sent)[:140])
    finally:
        fake.restore()


# ============================================================================
# TEST 2b — SMART EMOJI QABUL QILISH (preview + custom) — 2-QISM BUGFIX
# ============================================================================
def test_smart_emoji_reception():
    print("\n== TEST 2b: SMART EMOJI — preview va custom holatida to'g'ridan-to'g'ri emoji ==")
    # a) MANUAL_PREVIEW holatida to'g'ridan-to'g'ri emoji yuborish (masalan 😎)
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        check(f"[preview] holat tayyor", state == MP.MANUAL_PREVIEW, str(state))
        # Foydalanuvchi to'g'ridan-to'g'ri 😎 yuboradi
        emoji_msg = _Msg(text="😎")
        st = _run(MP.manual_preview_emoji_received(_update_msg(emoji_msg), ctx))
        check("preview'da 😎 qabul qilindi → MANUAL_PREVIEW",
              st == MP.MANUAL_PREVIEW, str(st))
        check("preview'da 😎 saqlandi",
              ctx.user_data.get(MP.UD_REACTIONS) == ["😎"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        check("preview'da 😎 bilan preview yangilandi",
              emoji_msg.sent and "😎" in emoji_msg.sent[-1]["text"],
              str(emoji_msg.sent)[:200] if emoji_msg.sent else "no sent")
        # Ikki emoji bo'shliq bilan
        emoji_msg2 = _Msg(text="🔥 👍")
        st2 = _run(MP.manual_preview_emoji_received(_update_msg(emoji_msg2), ctx))
        check("preview'da '🔥 👍' qabul qilindi → MANUAL_PREVIEW",
              st2 == MP.MANUAL_PREVIEW, str(st2))
        check("preview'da '🔥 👍' saqlandi (2 ta)",
              ctx.user_data.get(MP.UD_REACTIONS) == ["🔥", "👍"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        # Maksimal 5 tagacha
        many = _Msg(text="😎 🔥 👍 ❤️ 👏 🎉")  # 6 ta
        st_many = _run(MP.manual_preview_emoji_received(_update_msg(many), ctx))
        check("preview'da 6 ta emoji → faqat 5 tasi saqlanadi",
              st_many == MP.MANUAL_PREVIEW
              and len(ctx.user_data.get(MP.UD_REACTIONS) or []) == 5,
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        # Preview markup'da reaksiya tugmalari bor
        preview_many = many.sent[-1]
        pv_labels = [b.text for b in _flat_buttons(preview_many["reply_markup"])]
        check("preview markup'da 5 ta emoji tugmasi ko'rinadi",
              all(e in pv_labels for e in (ctx.user_data.get(MP.UD_REACTIONS) or [])[:5]),
              str(pv_labels))
    finally:
        fake.restore()

    # b) MANUAL_REACTION_CUSTOM holatida ham smart emoji (max 5)
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_REACT, msg)), ctx))
        q_add = _Query(CB_MANUAL_REACT_CUSTOM, _Msg())
        st_add = _run(MP.manual_panel_callback(_update_query(q_add), ctx))
        check("custom holat ochildi", st_add == MP.MANUAL_REACTION_CUSTOM, str(st_add))
        # To'g'ridan-to'g'ri 😎
        direct = _Msg(text="😎")
        st_direct = _run(MP.manual_reaction_custom_received(_update_msg(direct), ctx))
        check("custom'da 😎 qabul qilindi → PREVIEW",
              st_direct == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_REACTIONS) == ["😎"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        # 🔥 👍
        ctx.user_data[MP.UD_REACTIONS] = []
        direct2 = _Msg(text="🔥 👍")
        st_direct2 = _run(MP.manual_reaction_custom_received(_update_msg(direct2), ctx))
        check("custom'da '🔥 👍' → 2 ta saqlandi",
              st_direct2 == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_REACTIONS) == ["🔥", "👍"],
              str(ctx.user_data.get(MP.UD_REACTIONS)))
        # 6 ta → 5 tagacha
        ctx.user_data[MP.UD_REACTIONS] = []
        # custom holatga qaytish uchun qayta ochamiz
        q_add2 = _Query(CB_MANUAL_REACT_CUSTOM, _Msg())
        _run(MP.manual_panel_callback(_update_query(q_add2), ctx))
        # Endi custom handlerni chaqiramiz (holat CUSTOM bo'lishi shart emas, funksiya o'zi tekshiradi)
        many2 = _Msg(text="👍 ❤️ 🔥 👏 🎉 😍")
        st_many2 = _run(MP.manual_reaction_custom_received(_update_msg(many2), ctx))
        check("custom'da 6 ta emoji → faqat 5 tasi saqlanadi",
              st_many2 == MP.MANUAL_PREVIEW
              and len(ctx.user_data.get(MP.UD_REACTIONS) or []) == 5,
              str(ctx.user_data.get(MP.UD_REACTIONS)))
    finally:
        fake.restore()

    # c) FSM routing: MANUAL_PREVIEW holatida TEXT handleri mavjud
    app = _build_app()
    conv = _main_conv(app)
    from telegram.ext import MessageHandler as MH
    preview_text_handlers = [h for h in conv.states.get(MP.MANUAL_PREVIEW, []) if isinstance(h, MH)]
    check("MANUAL_PREVIEW'da TEXT handleri mavjud (smart emoji uchun)",
          len(preview_text_handlers) >= 1,
          str(preview_text_handlers))
    # U handler aynan manual_preview_emoji_received ekanini tekshiramiz
    has_smart = any(getattr(h, 'callback', None) == MP.manual_preview_emoji_received for h in preview_text_handlers)
    check("MANUAL_PREVIEW TEXT handleri manual_preview_emoji_received ga ulanadi",
          has_smart, str([getattr(h, 'callback', None).__name__ if hasattr(getattr(h, 'callback', None), '__name__') else str(getattr(h, 'callback', None)) for h in preview_text_handlers]))


# ============================================================================
# TEST 3 — 🔗 HAVOLALI (URL) TUGMA OQIMI (format + xavfsizlik + preview)
# ============================================================================
def test_url_button_flow():
    print("\n== TEST 3: 🔗 Havolali tugma — format, xavfsizlik, preview ==")
    # a) [🔗 Havolali tugma] → yo'riqnoma + MANUAL_URL_INPUT.
    for lang in LANGS:
        ctx = _ctx(lang)
        try:
            msg, state, fake = _start_manual_flow(ctx)
            q = _Query(CB_MANUAL_URL_BTN, msg)
            st = _run(MP.manual_panel_callback(_update_query(q), ctx))
            check(f"[{lang}] 🔗 → MANUAL_URL_INPUT (456)",
                  st == MP.MANUAL_URL_INPUT and MP.MANUAL_URL_INPUT == 456,
                  str(st))
            prompt_text = q.message.sent[-1]["text"]
            check(f"[{lang}] yo'riqnoma matni lug'atdan",
                  prompt_text == manual_post_t("mp_url_prompt", lang),
                  prompt_text[:80])
            check(f"[{lang}] yo'riqnomada format namunasi bor",
                  "Batafsil - https://t.me/kanal" in prompt_text
                  or "https://t.me/kanal" in prompt_text, prompt_text[:120])
        finally:
            fake.restore()

    # b) To'g'ri kiritma → preview'da HAQIQIY inline URL tugma.
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        good = _Msg(text="Batafsil - https://t.me/kanal")
        st = _run(MP.manual_url_received(_update_msg(good), ctx))
        check("'Batafsil - https://t.me/kanal' qabul qilindi → PREVIEW",
              st == MP.MANUAL_PREVIEW, str(st))
        check("btn_text/btn_url user_data'da saqlandi",
              ctx.user_data.get(MP.UD_URL_BTN_TEXT) == "Batafsil"
              and ctx.user_data.get(MP.UD_URL_BTN_URL) == "https://t.me/kanal",
              str({MP.UD_URL_BTN_TEXT: ctx.user_data.get(MP.UD_URL_BTN_TEXT),
                   MP.UD_URL_BTN_URL: ctx.user_data.get(MP.UD_URL_BTN_URL)}))
        preview = good.sent[-1]
        url_btns = [b for b in _flat_buttons(preview["reply_markup"])
                    if getattr(b, "url", None)]
        check("preview ostida HAQIQIY URL tugma paydo bo'ldi",
              len(url_btns) == 1 and url_btns[0].url == "https://t.me/kanal"
              and url_btns[0].text == "Batafsil",
              str([(b.text, getattr(b, "url", None))
                   for b in _flat_buttons(preview["reply_markup"])])[:160])
        check("URL tugma panel ustida (birinchi qator)",
              preview["reply_markup"].inline_keyboard[0][0].url
              == "https://t.me/kanal", "")
        check("preview matnida tugma xulosasi bor",
              "Batafsil" in preview["text"] and "https://t.me/kanal" in preview["text"],
              preview["text"][:140])
        check("panel tugmalari preview'da qoldi",
              CB_MANUAL_NOW in _flat_cbs(preview["reply_markup"]), "")

        # Publish: btn_text/btn_url db.add_post'ga uzatiladi.
        q_go = _Query(CB_MANUAL_NOW, good)
        st_go = _run(MP.manual_panel_callback(_update_query(q_go), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("publish: add_post chaqirildi + END",
              st_go == ConversationHandler.END and kw, str(st_go))
        check("publish: btn_text='Batafsil'", kw.get("btn_text") == "Batafsil",
              str(kw.get("btn_text")))
        check("publish: btn_url='https://t.me/kanal'",
              kw.get("btn_url") == "https://t.me/kanal", str(kw.get("btn_url")))
    finally:
        fake.restore()

    # c) tg:// protokoliga ruxsat.
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        tg = _Msg(text="Ochish - tg://resolve?domain=kanal")
        st = _run(MP.manual_url_received(_update_msg(tg), ctx))
        check("tg:// havolaga ruxsat beriladi",
              st == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_URL_BTN_URL) == "tg://resolve?domain=kanal",
              str(st))
    finally:
        fake.restore()

    # d) XAVFLI URL'lar rad etiladi (javascript:, file:, data:, ftp:...).
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        dangerous = [
            "Batafsil - javascript:alert(1)",
            "Ochish - file:///etc/passwd",
            "Ko'rish - data:text/html;base64,PHNjcmlwdD4=",
            "Yuklash - ftp://server.uz/fayl.zip",
            "Havola - https://user:parol@sayt.uz",   # credentials — rad
        ]
        for text in dangerous:
            m = _Msg(text=text)
            st = _run(MP.manual_url_received(_update_msg(m), ctx))
            check(f"xavfli URL rad etildi: {text.split(' - ')[-1][:32]}",
                  st == MP.MANUAL_URL_INPUT
                  and not ctx.user_data.get(MP.UD_URL_BTN_URL)
                  and m.sent and m.sent[-1]["text"]
                  == manual_post_t("mp_url_invalid", "uz"), str(st))
        # Format buzilishi ham rad etiladi (faqat matn yoki noto'g'ri format).
        # SMART URL BUGFIX: endi yakka URL (masalan https://t.me/kanal) qabul qilinadi,
        # shuning uchun uni bu ro'yxatdan olib tashladik — u alohida testda tekshiriladi.
        for text in ["shunchaki matn", "Batafsil"]:
            m = _Msg(text=text)
            st = _run(MP.manual_url_received(_update_msg(m), ctx))
            check(f"format buzilishi rad etildi: {text[:24]!r}",
                  st == MP.MANUAL_URL_INPUT
                  and not ctx.user_data.get(MP.UD_URL_BTN_URL), str(st))
        check("xavfli urinishlar add_post'ga yetib bormadi",
              not fake.calls_of("add_post"), str(fake.calls))
    finally:
        fake.restore()

    # e) SMART URL PARSER — faqat bitta URL yuborilganda avtomatik tugma yasalishi
    print("\n  -- SMART URL PARSER (yakka URL → avtomatik matn) --")
    ctx = _ctx("uz")
    try:
        msg, state, fake = _start_manual_flow(ctx)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg)), ctx))
        # t.me havolasi → "📢 Kanalga o'tish"
        single_tme = _Msg(text="https://t.me/kanal")
        st_tme = _run(MP.manual_url_received(_update_msg(single_tme), ctx))
        check("yakka t.me URL qabul qilindi → PREVIEW",
              st_tme == MP.MANUAL_PREVIEW
              and ctx.user_data.get(MP.UD_URL_BTN_URL) == "https://t.me/kanal",
              str(st_tme))
        check("yakka t.me URL uchun avtomatik matn '📢 Kanalga o'tish'",
              ctx.user_data.get(MP.UD_URL_BTN_TEXT) == "📢 Kanalga o'tish",
              str(ctx.user_data.get(MP.UD_URL_BTN_TEXT)))
        # preview ostida haqiqiy URL tugma bor
        preview_tme = single_tme.sent[-1]
        url_btns_tme = [b for b in _flat_buttons(preview_tme["reply_markup"]) if getattr(b, "url", None)]
        check("yakka t.me URL preview'da haqiqiy URL tugma",
              len(url_btns_tme) == 1 and url_btns_tme[0].url == "https://t.me/kanal"
              and url_btns_tme[0].text == "📢 Kanalga o'tish",
              str([(b.text, getattr(b, "url", None)) for b in _flat_buttons(preview_tme["reply_markup"])])[:200])

        # Boshqa veb-sayt → "🔗 Batafsil"
        ctx2 = _ctx("uz")
        msg2, state2, fake2 = _start_manual_flow(ctx2)
        _run(MP.manual_panel_callback(_update_query(_Query(CB_MANUAL_URL_BTN, msg2)), ctx2))
        single_web = _Msg(text="https://sayt.uz/maqola")
        st_web = _run(MP.manual_url_received(_update_msg(single_web), ctx2))
        check("yakka veb URL qabul qilindi → PREVIEW",
              st_web == MP.MANUAL_PREVIEW
              and ctx2.user_data.get(MP.UD_URL_BTN_URL) == "https://sayt.uz/maqola",
              str(st_web))
        check("yakka veb URL uchun avtomatik matn '🔗 Batafsil'",
              ctx2.user_data.get(MP.UD_URL_BTN_TEXT) == "🔗 Batafsil",
              str(ctx2.user_data.get(MP.UD_URL_BTN_TEXT)))
        preview_web = single_web.sent[-1]
        url_btns_web = [b for b in _flat_buttons(preview_web["reply_markup"]) if getattr(b, "url", None)]
        check("yakka veb URL preview'da haqiqiy URL tugma",
              len(url_btns_web) == 1 and url_btns_web[0].url == "https://sayt.uz/maqola"
              and url_btns_web[0].text == "🔗 Batafsil",
              str([(b.text, getattr(b, "url", None)) for b in _flat_buttons(preview_web["reply_markup"])])[:200])
        fake2.restore()
    finally:
        try:
            fake.restore()
        except:
            pass
        try:
            fake2.restore()
        except:
            pass


# ============================================================================
# TEST 4 — SCHEDULER/DELIVERY BIRASHMASI (reaksiyalar + URL tugma kanalga)
# ============================================================================
def test_scheduler_delivery_integration():
    print("\n== TEST 4: scheduler/delivery — reply_markup bilan kanalga ==")
    # a) db.add_post imzosi barcha kerakli ustunlarni qabul qiladi.
    sig = inspect.signature(db_mod.add_post)
    for param in ("btn_text", "btn_url", "enable_reactions", "reaction_emojis"):
        check(f"db.add_post parametri mavjud: {param}", param in sig.parameters,
              str(list(sig.parameters)))

    # b) Reaksiya + URL tugma bir vaqtda saqlanadi (to'liq preview oqimi).
    ctx = _ctx("uz")
    fake = None
    try:
        msg, state, fake = _start_manual_flow(ctx)
        ctx.user_data[MP.UD_REACTIONS] = ["👍", "❤️", "🔥"]
        ctx.user_data[MP.UD_URL_BTN_TEXT] = "Batafsil"
        ctx.user_data[MP.UD_URL_BTN_URL] = "https://t.me/kanal"
        q_go = _Query(CB_MANUAL_NOW, msg)
        st_go = _run(MP.manual_panel_callback(_update_query(q_go), ctx))
        kw = fake.calls_of("add_post")[-1]
        check("bir vaqtda reaksiya + URL tugma saqlandi (END)",
              st_go == ConversationHandler.END
              and kw.get("enable_reactions") is True
              and kw.get("reaction_emojis") == "👍 ❤️ 🔥"
              and kw.get("btn_text") == "Batafsil"
              and kw.get("btn_url") == "https://t.me/kanal", str(kw))
    finally:
        if fake:
            fake.restore()

    # c) Scheduler delivery zanjiri: DB so'rovi ustunlarni o'qiydi va
    #    _execute_send reply_markup quradi (statik + dinamik tekshiruv).
    db_src = (ROOT / "database.py").read_text(encoding="utf-8")
    check("scheduled_posts: inline_button_text/url ustunlari mavjud",
          "inline_button_text" in db_src and "inline_button_url" in db_src, "")
    check("delivery SELECT'i reaksiya ustunini o'qiydi",
          "reaction_emojis" in db_src and "enable_reactions" in db_src, "")
    sch_src = (ROOT / "scheduler.py").read_text(encoding="utf-8")
    check("scheduler URL tugmani reply_markup'ga qo'shadi",
          "InlineKeyboardButton(text=btn_text, url=btn_url)" in sch_src, "")
    check("scheduler reaksiya qatorini reply_markup'ga qo'shadi",
          "build_reaction_buttons(post_id, enable_reactions, reaction_emojis)"
          in sch_src, "")
    check("scheduler yakuniy InlineKeyboardMarkup quradi",
          "InlineKeyboardMarkup(buttons)" in sch_src, "")

    # d) Reaksiya tugmalari saqlangan emojilardan quriladi (dinamik).
    rows = build_reaction_button_rows(123, ["👍", "❤️", "🔥"], preview=True)
    flat = [b for r in rows for b in r]
    check("preview reaksiya qatori: 3 emoji (enh:noop)",
          [b.text for b in flat] == ["👍", "❤️", "🔥"]
          and all(b.callback_data == "enh:noop" for b in flat),
          str([(b.text, b.callback_data) for b in flat]))
    from scheduler import build_reaction_buttons
    live_row = build_reaction_buttons(123, True, "👍 ❤️ 🔥")
    check("kanal reaksiya tugmalari: react:<post_id>:<emoji>",
          len(live_row) == 3
          and all(str(b.callback_data).startswith("react:123:")
                  for b in live_row),
          str([b.callback_data for b in live_row]))
    check("kanal reaksiya tugmalari saqlangan emojilardan",
          [b.text for b in live_row] == ["👍", "❤️", "🔥"],
          str([b.text for b in live_row]))
    check("reaksiya o'chiq bo'lsa tugma yo'q",
          build_reaction_buttons(123, False, "👍") == [], "")


# ============================================================================
# TEST 5 — FSM/ROUTING/I18N QO'RIQONLARI
# ============================================================================
def test_fsm_routing_i18n_guards():
    print("\n== TEST 5: FSM/ routing / i18n qo'riqonlari ==")
    # a) FSM holatlari noyob (butun kod bazasida).
    import handlers.magic_post as magic_mod
    import handlers.post_score as ps_mod
    import handlers.autopilot as ap_mod
    import handlers.templates as tpl_mod
    import handlers.content_calendar_flow as cal_mod
    others = {magic_mod.MAGIC_INPUT, magic_mod.MAGIC_STYLE_SELECT,
              magic_mod.MAGIC_RESULT, magic_mod.MAGIC_SEND_CHOOSE,
              ps_mod.POST_SCORE_INPUT, ps_mod.POST_SCORE_RESULT,
              ps_mod.POST_SCORE_SEND_CHOOSE,
              ap_mod.AUTOPILOT_TOPIC, ap_mod.AUTOPILOT_VIEW,
              tpl_mod.TPL_MENU, tpl_mod.TPL_NEW_NAME,
              cal_mod.CALENDAR_BUSINESS, cal_mod.CALENDAR_DURATION}
    manual_states = {MP.MANUAL_AWAIT_CONTENT, MP.MANUAL_PREVIEW,
                     MP.MANUAL_CHANNEL_SELECT, MP.MANUAL_TIME_INPUT,
                     MP.MANUAL_EDIT_INPUT, MP.MANUAL_REACTION_CUSTOM,
                     MP.MANUAL_URL_INPUT}
    check("yangi manual FSM holatlari (455/456) noyob",
          not (manual_states & others)
          and MP.MANUAL_REACTION_CUSTOM == 455 and MP.MANUAL_URL_INPUT == 456,
          str(sorted(manual_states & others)))

    # b) conv.states: yangi holatlar ro'yxatdan o'tgan va TEXT handlerli.
    from telegram.ext import CallbackQueryHandler as CQH, MessageHandler as MH
    app = _build_app()
    conv = _main_conv(app)
    check("conv.states: MANUAL_REACTION_CUSTOM ro'yxatda",
          MP.MANUAL_REACTION_CUSTOM in conv.states, "")
    check("conv.states: MANUAL_URL_INPUT ro'yxatda",
          MP.MANUAL_URL_INPUT in conv.states, "")
    check("MANUAL_REACTION_CUSTOM: matn handleri ulangan",
          any(isinstance(h, MH) for h in conv.states[MP.MANUAL_REACTION_CUSTOM]), "")
    check("MANUAL_URL_INPUT: matn handleri ulangan",
          any(isinstance(h, MH) for h in conv.states[MP.MANUAL_URL_INPUT]), "")

    # c) MANUAL_PREVIEW pattern handleri yangi callback'larni ushlaydi.
    preview_handlers = [h for h in conv.states[MP.MANUAL_PREVIEW]
                        if isinstance(h, CQH) and getattr(h, "pattern", None)]
    new_cbs = [CB_MANUAL_REACT, CB_MANUAL_URL_BTN, CB_MANUAL_REACT_CUSTOM,
               CB_MANUAL_REACT_BACK, manual_reaction_toggle_callback("👍"),
               manual_reaction_toggle_callback("❤️")]
    matched = set()
    for h in preview_handlers:
        for data in new_cbs:
            if re.search(h.pattern, data):
                matched.add(data)
    check("yangi callback'lar MANUAL_PREVIEW'da ushlanadi",
          set(new_cbs) <= matched, str(set(new_cbs) - matched))

    # d) Stale himoya: ManualEntryHandler (^mnp_) yangi tugmalarni ham oladi
    #    (main_conv entry_points ichida — dialog tashqarisidagi eski tugmalar).
    manual_entry = [h for h in conv.entry_points
                    if isinstance(h, MP.ManualEntryHandler)]
    check("ManualEntryHandler (mnp_) entry point'ida",
          len(manual_entry) == 1
          and manual_entry[0].pattern.pattern == "^mnp_",
          str([getattr(h, "pattern", None) for h in manual_entry]))
    for data in new_cbs:
        check(f"stale himoya qamrovi: {data}", data.startswith("mnp_"), data)

    # e) Stale bosilganda muloyim javob (sessiyasiz).
    ctx = _ctx("uz")
    q = _Query(CB_MANUAL_REACT)
    st = _run(MP.manual_stale_callback(_update_query(q), ctx))
    check("stale mnp_react → sessiya eskirgan xabar + END",
          st == ConversationHandler.END
          and q.message.sent[-1]["text"] == manual_post_t("mp_session_expired", "uz"),
          str(q.message.sent)[:100])

    # f) Sessiyasiz panel: kontent yo'q bo'lsa yangi tugmalar ham xavfsiz.
    ctx2 = _ctx("uz")
    q2 = _Query(CB_MANUAL_URL_BTN)
    st2 = _run(MP.manual_panel_callback(_update_query(q2), ctx2))
    check("kontentsiz mnp_url → sessiya eskirgan xabar (crash yo'q)",
          st2 == ConversationHandler.END
          and q2.message.sent[-1]["text"] == manual_post_t("mp_session_expired", "uz"),
          str(q2.message.sent)[:100])

    # g) i18n paritet: yangi kalitlar uchala tilda, format arglari teng.
    rep = manual_post_parity_report()
    check("manual_post pariteti in_sync (yangi kalitlar bilan)",
          rep["in_sync"] is True,
          str({k: rep.get(k) for k in ("missing", "extra", "empty",
                                       "format_mismatch")}))
    new_keys = ["mp_btn_reactions", "mp_btn_url_btn", "mp_react_prompt",
                "mp_react_custom", "mp_react_custom_prompt",
                "mp_react_custom_invalid", "mp_reactions_on",
                "mp_url_prompt", "mp_url_invalid", "mp_url_on"]
    for key in new_keys:
        values = {lang: manual_post_t(key, lang) for lang in LANGS}
        check(f"yangi kalit {key}: 3 tilda mavjud va farqli",
              all(v and not v.startswith(key) for v in values.values())
              and len(set(values.values())) == 3, str(values)[:120])
    check("mp_url_invalid: protokol qoidasi uchala tilda tilga olingan",
          all("http" in manual_post_t("mp_url_invalid", lang)
              and "tg://" in manual_post_t("mp_url_invalid", lang)
              for lang in LANGS), "")
    check("lug'at kalitlari MANUAL_POST_KEYS bilan sinxron",
          set(MANUAL_POST_I18N["uz"]) == set(MANUAL_POST_I18N["ru"])
          == set(MANUAL_POST_I18N["en"]), "")


# ============================================================================
def main():
    print("=" * 70)
    print(" ❤️ REAKSIYALAR + 🔗 HAVOLALI TUGMA — MANUAL PREVIEW BOYITISH")
    print("=" * 70)
    test_panel_four_rows_spec()
    test_reactions_flow()
    test_smart_emoji_reception()
    test_url_button_flow()
    test_scheduler_delivery_integration()
    test_fsm_routing_i18n_guards()
    print("\n" + "=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" REAKSIYALAR VA URL TUGMALAR TESTLARI 100% YASHIL ✔")
    print("=" * 70)
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
