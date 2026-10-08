#!/usr/bin/env python3
"""🎨 REAKSIYALAR · ✏️ TAHRIRLASH MENYUSI · ❌ BEKOR QILISH · 💡 AI ESLATMA · 📸 VISION.

5 TA ANIQ UX VA LOGIKA TUZATISHI (topshiriq bilan birma-bir):

  TEST 1 — REAKSIYA EMOJILARINI ERKIN KIRITISH
      «➕ O'zim kiritaman» bosilganda bot AYNAN quyidagi ko'rsatmani chiqaradi:
      «Post ostida chiqadigan emojilarni oralariga bo'sh joy (probel) tashlab
      yuboring (5 tagacha). Masalan: 🔥 ❤️ 👍 🎉»; foydalanuvchi matni PROBEL
      bo'yicha ajratiladi va 5 tagacha emojidan inline tugmalar yaratiladi.

  TEST 2 — TAHRIRLASH TANLOV MENYUSI
      «✏️ Tahrirlash» (``p_edit:``) bosilganda to'g'ridan-to'g'ri yangi matn
      SO'RALMAYDI — tanlov oynasi chiqadi::

          [📝 Matnni o'zgartirish]   [🔘 Tugma qo'shish]
          [❤️ Reaksiyalar]           [⏰ Vaqtni surish]
                      [◀️ Orqaga]

  TEST 3 — BEKOR QILISH OQIMI
      Rejalashtirilgan postni tahrirlashda «❌ Bekor qilish» bosilsa
      «Kontent yaratish» sahifasiga O'TIB KETMAYDI — foydalanuvchi 📅
      Rejalashtirilgan postlar ro'yxatiga qaytadi va FSM tozalanadi.

  TEST 4 — AI YANGILIKLAR ISHONCHLILIGI
      AI umumiy mavzudan post tayyorlaganda bot xabari tagiga eslatma
      qo'shiladi: «💡 Eslatma: Ushbu post AI tomonidan tuzildi. Rasmiy
      manbalardan faktlarni tekshirib olishingiz tavsiya etiladi.»

  TEST 5 — VISION AI: MAHSULOT EMAS VOQEALAR
      Rasmda kiyim/tovar bo'lmasa (mashhur shaxslar, futbol, yangilik,
      tabiat) bot «Mahsulot: Rang/Material» deb so'ramaydi — toifa
      AVTOMATIK tanlanadi: «Mahsulot posti» yoki
      «Voqea / Qiziqarli kontent posti».

Ishga tushirish:
    python3 tests/reactions_edit_cancel_vision_flow_test.py
    bash tests/run_tests.sh        # to'liq regressiya
"""
import asyncio
import os
import re
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:REACTIONS_EDIT_VISION_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

import pytz  # noqa: E402

passed = 0
failures = 0
LANGS = ("uz", "ru", "en")
TASHKENT = pytz.timezone("Asia/Tashkent")


def check(name, cond, extra="") -> bool:
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")
    return bool(cond)


def header(title: str) -> None:
    print()
    print("=" * 70)
    print(f" {title}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# MOCK INFRASTRUKTURA (Telegram update/query/context taqlidi)
# ---------------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, data: str, user_id: int):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = _FakeMessage()
        self.answers: list[tuple] = []
        self.edits: list[dict] = []
        self.reply_markups: list = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append({"text": str(text), "reply_markup": reply_markup})
        return True

    async def edit_message_reply_markup(self, reply_markup=None):
        self.reply_markups.append(reply_markup)
        return True


class _FakeMessage:
    def __init__(self, text: str = ""):
        self.text = text
        self.chat_id = 987654321
        self.sent: list[dict] = []
        self.replies: list[dict] = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"text": str(text), "reply_markup": reply_markup})
        self.replies.append(str(text))
        return self

    async def reply_photo(self, photo=None, caption=None, reply_markup=None, **kw):
        self.sent.append({"text": str(caption), "reply_markup": reply_markup})
        return self


class _FakeBot:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": str(text),
                          "reply_markup": reply_markup})
        return _FakeMessage()


class _FakeContext:
    def __init__(self, lang: str = "uz", **ud):
        self.user_data: dict = {"lang": lang, **ud}
        self.bot = _FakeBot()


class _FakeUpdate:
    def __init__(self, query=None, user_id: int = 1, message=None):
        self.callback_query = query
        self.effective_user = SimpleNamespace(id=user_id)
        self.effective_chat = SimpleNamespace(id=user_id)
        self.message = message
        self.effective_message = message or (query.message if query else None)


def _buttons(reply_markup):
    """InlineKeyboardMarkup → [(matn, callback_data), ...] ro'yxati (tekis)."""
    rows = getattr(reply_markup, "inline_keyboard", None) or []
    out = []
    for row in rows:
        for btn in row:
            out.append((getattr(btn, "text", ""), getattr(btn, "callback_data", None)))
    return out


# ============================================================================
# TEST 1 — 🎨 REAKSIYA EMOJILARINI ERKIN KIRITISH
# ============================================================================
def test_custom_reaction_emojis() -> None:
    import handlers.manual_post as mp
    from translations import manual_post_t

    header("TEST 1 — 🎨 «➕ O'zim kiritaman»: probel bilan 5 tagacha emoji")

    required = ("Post ostida chiqadigan emojilarni oralariga bo'sh joy (probel) "
                "tashlab yuboring (5 tagacha). Masalan: 🔥 ❤️ 👍 🎉")
    prompt = manual_post_t("mp_react_custom_prompt", "uz")
    check("ko'rsatma matni AYNAN topshiriqdagi ko'rsatma (uz)",
          required in prompt, prompt)
    check("eski «10 tagacha» cheklovi yo'q", "10 tagacha" not in prompt, prompt)
    for lang in ("ru", "en"):
        text = manual_post_t("mp_react_custom_prompt", lang)
        check(f"ko'rsatma {lang} tilida mavjud va «5» cheklovini aytadi",
              bool(text) and "5" in text and "10" not in text
              and "🔥 ❤️ 👍 🎉" in text, text)

    # 1a) PROBEL bo'yicha ajratish — 5 tagacha (tartib saqlanadi).
    emojis = mp.split_custom_reaction_emojis("🔥 ❤️ 👍 🎉 😍 🚀")
    check("probel bo'yicha ajratildi va 5 tagacha kesildi",
          emojis == ["🔥", "❤️", "👍", "🎉", "😍"], str(emojis))
    emojis4 = mp.split_custom_reaction_emojis("🔥 ❤️ 👍 🎉")
    check("4 ta emoji — 4 ta natija (kesilmaydi)",
          emojis4 == ["🔥", "❤️", "👍", "🎉"], str(emojis4))
    check("probel bilan kiritilgan FAQAT emojilar olinadi",
          mp.split_custom_reaction_emojis("salom dunyo") == [],
          str(mp.split_custom_reaction_emojis("salom dunyo")))
    check("takror emojilar olib tashlanadi",
          mp.split_custom_reaction_emojis("🔥 🔥 🎉") == ["🔥", "🎉"],
          str(mp.split_custom_reaction_emojis("🔥 🔥 🎉")))
    check("probel orasida matn bo'lsa ham emojilar topiladi",
          mp.split_custom_reaction_emojis("reja 🔥 juda ❤️ zo'r 👍") ==
          ["🔥", "❤️", "👍"],
          str(mp.split_custom_reaction_emojis("reja 🔥 juda ❤️ zo'r 👍")))

    # 1b) Handler: yuborilgan matn saqlanadi va preview 5 tagacha TUGMA chiqaradi.
    context = _FakeContext(**{mp.UD_CONTENT: "Salom, bu post matni",
                             "mnp_post_type": "text"})
    msg = _FakeMessage(text="🔥 ❤️ 👍 🎉 😍 🚀")
    update = _FakeUpdate(message=msg, user_id=555001)
    state = asyncio.run(mp.manual_reaction_custom_received(update, context))
    check("handler 5 tagacha emojini saqladi",
          context.user_data.get(mp.UD_REACTIONS) == ["🔥", "❤️", "👍", "🎉", "😍"],
          str(context.user_data.get(mp.UD_REACTIONS)))
    check("handler preview holatiga qaytdi", state == mp.MANUAL_PREVIEW, str(state))
    markup_rows = _buttons(mp._manual_preview_markup(context, "uz"))
    emoji_buttons = [text for text, _cb in markup_rows
                     if text in ("🔥", "❤️", "👍", "🎉", "😍")]
    check("preview'da 5 tagacha INLINE reaksiya tugmasi chizildi",
          sorted(emoji_buttons) == sorted(["🔥", "❤️", "👍", "🎉", "😍"]),
          str(emoji_buttons))
    check("kanalga yuboriladigan tugmalar soni 5 tadan oshmaydi",
          len(emoji_buttons) <= 5, str(len(emoji_buttons)))

    # 1c) «➕ O'zim kiritaman» tugmasi AYNAN shu ko'rsatmani chiqaradi.
    query = _FakeQuery("mnp_radd", 555001)
    context2 = _FakeContext(**{mp.UD_CONTENT: "Salom"})
    state2 = asyncio.run(mp.manual_panel_callback(
        _FakeUpdate(query=query, user_id=555001), context2))
    sent_texts = list(query.message.replies)
    check("«➕ O'zim kiritaman» → ko'rsatma yuborildi",
          any(required in text for text in sent_texts), str(sent_texts)[:200])
    check("«➕ O'zim kiritaman» → MANUAL_REACTION_CUSTOM holati",
          state2 == mp.MANUAL_REACTION_CUSTOM, str(state2))

    # 1d) Emoji bo'lmagan matn — muloyim xato, holat saqlanadi.
    bad_ctx = _FakeContext(**{mp.UD_CONTENT: "Salom"})
    bad_msg = _FakeMessage(text="bugun nima yozsam bo'ladi")
    bad_state = asyncio.run(mp.manual_reaction_custom_received(
        _FakeUpdate(message=bad_msg, user_id=555001), bad_ctx))
    check("emoji topilmasa — xato xabari va holat saqlanadi",
          bad_state == mp.MANUAL_REACTION_CUSTOM
          and any(manual_post_t("mp_react_custom_invalid", "uz") in t
                  for t in bad_msg.replies),
          str(bad_msg.replies)[:160])


# ============================================================================
# TEST 2 — ✏️ TAHRIRLASH TANLOV MENYUSI
# ============================================================================
def test_edit_selection_menu() -> None:
    import database as db_mod
    import handlers.pending as P
    from keyboards.inline import get_post_edit_menu_keyboard
    from keyboards.callback_data import (
        CB_POST_EDIT_BACK, CB_POST_EDIT_TEXT, is_registered_callback,
    )
    from locales.translations import get_text
    from telegram.ext import ConversationHandler

    header("TEST 2 — ✏️ «Tahrirlash»: to'g'ridan-to'g'ri matn emas, TANLOV menyusi")

    OWNER = 700100001
    POST_ID = 777
    kb = get_post_edit_menu_keyboard(POST_ID, "uz")
    rows = [[(b.text, b.callback_data) for b in row]
            for row in kb.inline_keyboard]
    check("menyu 3 qator: 2 + 2 + 1 (topshiriqdagi tartib)",
          len(rows) == 3 and len(rows[0]) == 2 and len(rows[1]) == 2
          and len(rows[2]) == 1, str(rows))
    check("qator 1: [📝 Matnni o'zgartirish] [🔘 Tugma qo'shish]",
          [t for t, _c in rows[0]] == [get_text("pend_edit_btn_text", "uz"),
                                       get_text("pend_edit_btn_button", "uz")],
          str(rows[0]))
    check("qator 2: [❤️ Reaksiyalar] [⏰ Vaqtni surish]",
          [t for t, _c in rows[1]] == [get_text("pend_edit_btn_react", "uz"),
                                       get_text("pend_edit_btn_time", "uz")],
          str(rows[1]))
    check("qator 3: [◀️ Orqaga] (yagona tugma)",
          [t for t, _c in rows[2]] == [get_text("pend_edit_btn_back", "uz")],
          str(rows[2]))
    check("matn tugmasi → p_edtx:<post_id>",
          rows[0][0][1] == f"{CB_POST_EDIT_TEXT}{POST_ID}", str(rows[0][0]))
    check("tugma/reaksiya/vaqt → mavjud oqimlar (p_btn:/p_react:/p_time:)",
          rows[0][1][1] == f"p_btn:{POST_ID}"
          and rows[1][0][1] == f"p_react:{POST_ID}"
          and rows[1][1][1] == f"p_time:{POST_ID}", str(rows))
    check("◀️ Orqaga → p_edbk (📅 ro'yxatiga qaytish)",
          rows[2][0][1] == CB_POST_EDIT_BACK, str(rows[2][0]))
    check("yangi callback'lar registry'da (tampering fail-closed)",
          is_registered_callback(f"{CB_POST_EDIT_TEXT}{POST_ID}")
          and is_registered_callback(CB_POST_EDIT_BACK), "")

    original_run_db = db_mod.run_db

    def _patch(owner=OWNER):
        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", repr(fn))
            if name == "get_post_by_id":
                if args and args[0] == POST_ID and owner is not None:
                    return (POST_ID, owner, -100123456, "text", None, None, None, 1)
                return None
            return None
        return fake_run_db

    try:
        # 2a) p_edit: — menyu chiqadi, MATN SO'RALMAYDI.
        db_mod.run_db = _patch()
        query = _FakeQuery(f"p_edit:{POST_ID}", OWNER)
        ctx = _FakeContext()
        state = asyncio.run(P.edit_post_content_start(
            _FakeUpdate(query=query, user_id=OWNER), ctx))
        sent = ctx.bot.sent
        check("p_edit: → EDIT_POST_CONTENT holati", state == P.EDIT_POST_CONTENT,
              str(state))
        check("p_edit: → FSM ma'lumoti saqlandi (editing_post_id)",
              ctx.user_data.get("editing_post_id") == POST_ID, str(ctx.user_data))
        check("p_edit: → menyu sarlavhasi yuborildi (yangi matn so'ralmadi)",
              len(sent) == 1
              and get_text("pend_edit_menu_title", "uz") in sent[0]["text"]
              and get_text("pend_content_ask", "uz") not in sent[0]["text"],
              str(sent)[:200])
        menu_buttons = _buttons(sent[0]["reply_markup"]) if sent else []
        check("p_edit: → 5 ta tugma (4 amal + Orqaga)",
              len(menu_buttons) == 5, str(menu_buttons))

        # 2b) p_edtx: — «📝 Matnni o'zgartirish» → endi matn so'raladi.
        db_mod.run_db = _patch()
        query2 = _FakeQuery(f"{CB_POST_EDIT_TEXT}{POST_ID}", OWNER)
        ctx2 = _FakeContext()
        state2 = asyncio.run(P.edit_post_text_start(
            _FakeUpdate(query=query2, user_id=OWNER), ctx2))
        check("p_edtx: → EDIT_POST_CONTENT + matn so'rovi",
              state2 == P.EDIT_POST_CONTENT
              and len(ctx2.bot.sent) == 1
              and get_text("pend_content_ask", "uz") in ctx2.bot.sent[0]["text"],
              str(ctx2.bot.sent)[:160])

        # 2c) IDOR — begona post uchun menyu ham, matn so'rovi ham yo'q.
        for data, fn in ((f"p_edit:{POST_ID}", P.edit_post_content_start),
                         (f"{CB_POST_EDIT_TEXT}{POST_ID}", P.edit_post_text_start)):
            db_mod.run_db = _patch(owner=999999)
            q = _FakeQuery(data, OWNER)
            c = _FakeContext()
            st = asyncio.run(fn(_FakeUpdate(query=q, user_id=OWNER), c))
            check(f"{data}: begona post → END + xabar yo'q",
                  st == ConversationHandler.END and not c.bot.sent
                  and "editing_post_id" not in c.user_data, str(st))
    finally:
        db_mod.run_db = original_run_db

    # 2d) Routing: yangi callback'lar entry point + global ro'yxatda.
    source = (Path(__file__).resolve().parent.parent
              / "telegram_bot" / "handlers" / "__init__.py").read_text(encoding="utf-8")
    check("routing: ^p_edtx: entry point va global handler",
          source.count(r'pattern=r"^p_edtx:"') >= 2
          and source.count("edit_post_text_start") >= 3, "")
    check("routing: ^p_edbk$ entry point va global handler",
          source.count(r'pattern=r"^p_edbk$"') >= 2, "")
    check("routing: menyu tugmalari FSM holatlarida ham ro'yxatga olingan",
          "_edit_post_menu_handlers" in source
          and source.count("list(_edit_post_menu_handlers)") == 4, "")


# ============================================================================
# TEST 3 — ❌ BEKOR QILISH OQIMI
# ============================================================================
def _scheduled_db(total=2):
    """📅 ro'yxatni chizish uchun ``run_db`` taqlidi (funksiya nomi bo'yicha)."""
    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", repr(fn))
        if name == "get_queue_post_count":
            return total
        if name == "check_queue_limit":
            return (True, total, 5)
        if name == "get_queue_posts":
            rows = []
            for i in range(total):
                rows.append((100 + i, f"Kanal {i + 1}", "text",
                             f"Post matni {i + 1}", datetime.now(TASHKENT),
                             None, -100123456))
            return rows
        if name == "get_post_by_id":
            return (777, 700100001, -100123456, "text", None, None, None, 1)
        return None
    return fake_run_db


def test_cancel_flow_returns_to_scheduled_list() -> None:
    import database as db_mod
    from telegram.ext import ConversationHandler
    from handlers.start import cancel_handler
    from translations import channels_queue_t, content_menu_t
    from locales.translations import get_text

    header("TEST 3 — ❌ «Bekor qilish»: Kontent yaratishga EMAS, 📅 ro'yxatga")

    original_run_db = db_mod.run_db
    try:
        # 3a) Tahrirlash konteksti + nav_section=content (aynan xato holat).
        db_mod.run_db = _scheduled_db(total=2)
        ctx = _FakeContext(nav_section="content", editing_post_id=777,
                           edit_mode="menu", np_title="Post matni")
        msg = _FakeMessage(text=get_text("btn_cancel", "uz"))
        state = asyncio.run(cancel_handler(
            _FakeUpdate(message=msg, user_id=700100001), ctx))
        last = msg.sent[-1] if msg.sent else {"text": ""}
        list_title = channels_queue_t("cq_sch_title", "uz", count=2)
        check("Bekor qilish → ConversationHandler.END",
              state == ConversationHandler.END, str(state))
        check("oxirgi xabar — 📅 Rejalashtirilgan ro'yxati",
              list_title in last["text"], str(last)[:200])
        check("«Kontent yaratish» menyusi CHIZILMADI (asosiy xato yo'q)",
              get_text("cm_menu_intro", "uz") not in last["text"], "")
        check("FSM state tozalandi (editing_post_id/np_title yo'q)",
              "editing_post_id" not in ctx.user_data
              and "edit_mode" not in ctx.user_data
              and "np_title" not in ctx.user_data, str(ctx.user_data))
        check("ro'yxat klaviaturasi 📅 ekranining o'zi (post amallari)",
              any(cb and str(cb).startswith(("qview:", "p_edit:"))
                  for _t, cb in _buttons(last.get("reply_markup"))), "")

        # 3b) Bo'sh navbat ham — baribir 📅 ekraniga qaytadi.
        db_mod.run_db = _scheduled_db(total=0)
        ctx2 = _FakeContext(nav_section="content", editing_post_id=777)
        msg2 = _FakeMessage(text=get_text("btn_cancel", "uz"))
        asyncio.run(cancel_handler(_FakeUpdate(message=msg2, user_id=700100001),
                                   ctx2))
        check("bo'sh navbat → «📅 Rejalashtirilgan» bo'sh ekrani",
              msg2.sent and channels_queue_t("cq_sch_empty", "uz") in msg2.sent[-1]["text"],
              str(msg2.sent)[:160])

        # 3c) REGRESSIYA: tahrirlash konteksti BO'LMASA eski xulq saqlanadi.
        ctx3 = _FakeContext(nav_section="content", np_title="Post matni")
        msg3 = _FakeMessage(text=get_text("btn_cancel", "uz"))
        state3 = asyncio.run(cancel_handler(
            _FakeUpdate(message=msg3, user_id=700100001), ctx3))
        check("oddiy FSM + Bekor → KONTENT submenyusi (eski xulq buzilmadi)",
              state3 == ConversationHandler.END and msg3.sent
              and content_menu_t("cm_menu_intro", "uz") in msg3.sent[-1]["text"],
              str(msg3.sent)[:160])

        # 3d) «◀️ Orqaga» (p_edbk) — menyu 📅 ro'yxatiga qaytadi + FSM tozalanadi.
        import handlers.pending as P
        db_mod.run_db = _scheduled_db(total=2)
        query = _FakeQuery("p_edbk", 700100001)
        ctx4 = _FakeContext(editing_post_id=777, edit_mode="menu")
        state4 = asyncio.run(P.edit_post_menu_back(
            _FakeUpdate(query=query, user_id=700100001), ctx4))
        edited = query.edits[-1] if query.edits else {"text": ""}
        check("◀️ Orqaga → 📅 ro'yxati (joriy xabar tahrirlandi)",
              list_title in edited["text"], str(edited)[:160])
        check("◀️ Orqaga → FSM tozalandi + END",
              state4 == ConversationHandler.END
              and "editing_post_id" not in ctx4.user_data, str(state4))
    finally:
        db_mod.run_db = original_run_db


# ============================================================================
# TEST 4 — 💡 AI ISHONCHLILIGI ESLATMASI
# ============================================================================
def test_ai_reliability_note() -> None:
    from services.ai.prompts import (
        AI_RELIABILITY_NOTE, needs_reliability_note, reliability_note,
    )
    from handlers.ai_assistant import _studio_preview_text
    from handlers.magic_post import _magic_result_text

    header("TEST 4 — 💡 AI post tagida ishonchlilik eslatmasi")

    required = ("💡 Eslatma: Ushbu post AI tomonidan tuzildi. "
                "Rasmiy manbalardan faktlarni tekshirib olishingiz tavsiya etiladi.")
    check("eslatma matni AYNAN topshiriqdagi ko'rsatma (uz)",
          AI_RELIABILITY_NOTE["uz"] == required, AI_RELIABILITY_NOTE["uz"])
    for lang in LANGS:
        check(f"eslatma {lang} tilida mavjud", bool(reliability_note(lang)), "")
    check("noma'lum til → o'zbekcha (fail-safe)",
          reliability_note("de") == required, reliability_note("de"))

    # 4a) Umumiy/axborot mavzular → eslatma KERAK.
    for topic in ("yangiliklar", "sport", "futbol", "biznes", "ob-havo"):
        check(f"umumiy mavzu «{topic}» → eslatma kerak",
              needs_reliability_note(topic) is True, topic)
    # 4b) Sotuv/mahsulot mavzusi → eslatma SHART EMAS (faktlar foydalanuvchidan).
    check("sotuv mavzusi (narx/chegirma) → eslatma kerak emas",
          needs_reliability_note("Yangi kolleksiya sumkalar narxi 150 000 so'm") is False, "")
    check("bo'sh mavzu → eslatma kerak emas",
          needs_reliability_note("") is False, "")

    # 4c) AI Studio preview: bot xabari tagida eslatma bor.
    preview = _studio_preview_text("Post matni", "friendly", None, "uz",
                                   topic="yangiliklar")
    check("AI Studio (umumiy mavzu) → eslatma bot xabari tagida",
          preview.rstrip().endswith(required), preview[-160:])
    product_preview = _studio_preview_text(
        "Post matni", "friendly", None, "uz",
        topic="Yangi kolleksiya sumkalar narxi 150 000 so'm")
    check("AI Studio (mahsulot mavzusi) → eslatma qo'shilmaydi",
          required not in product_preview, product_preview[-160:])
    check("eski chaqiruv (topic berilmagan) ishlashda davom etadi",
          isinstance(_studio_preview_text("Post matni", "friendly", None, "uz"), str), "")

    # 4d) Magic Post natijasi ham umumiy mavzuda eslatma bilan.
    magic = _magic_result_text("Post matni", "casual", "uz", topic="futbol")
    check("Magic Post (umumiy mavzu) → eslatma tagida",
          required in magic and magic.rstrip().endswith(required), magic[-160:])
    magic_product = _magic_result_text("Post matni", "casual", "uz",
                                       topic="Chegirma: narx 99 000 so'm")
    check("Magic Post (mahsulot mavzusi) → eslatma yo'q",
          required not in magic_product, magic_product[-160:])


# ============================================================================
# TEST 5 — 📸 VISION AI: MAHSULOT EMAS, VOQEA
# ============================================================================
def test_vision_event_classification() -> None:
    from utils.vision_analyzer import (
        IMAGE_CATEGORY_EVENT, IMAGE_CATEGORY_PRODUCT, IMAGE_TYPE_EVENT,
        IMAGE_TYPE_PRODUCT, analyze_image, build_vision_system_prompt,
        detect_image_type, image_category_label, is_product_analysis,
        normalize_analysis,
    )
    from handlers.image_post import _analysis_summary
    from services.ai_service import _image_analysis_text
    from locales.translations import get_text

    header("TEST 5 — 📸 Vision: mahsulot ⇄ voqea va AVTOMATIK toifa")

    check("avtomatik toifa yorliqlari topshiriq matniga mos",
          IMAGE_CATEGORY_PRODUCT == "Mahsulot posti"
          and IMAGE_CATEGORY_EVENT == "Voqea / Qiziqarli kontent posti", "")
    check("toifa tilga mos ko'rinishda (uz/ru/en)",
          "Mahsulot posti" in image_category_label(IMAGE_TYPE_PRODUCT, "uz")
          and "Voqea / Qiziqarli kontent posti" in image_category_label(IMAGE_TYPE_EVENT, "uz")
          and image_category_label(IMAGE_TYPE_EVENT, "ru") != image_category_label(IMAGE_TYPE_EVENT, "uz"),
          "")

    # 5a) Model maydoni bo'yicha aniqlash.
    check("image_type=event → event",
          detect_image_type({"image_type": "event"}) == IMAGE_TYPE_EVENT, "")
    check("image_type=product → product",
          detect_image_type({"image_type": "product"}) == IMAGE_TYPE_PRODUCT, "")
    # 5b) Zaxira aniqlash: mashhur shaxslar, futbol, yangilik, tabiat → EVENT.
    for payload in (
        {"category": "Yangilik", "product_name": "Mashhur aktyor sahnada"},
        {"product_name": "Futbol o'yini", "category": "Sport"},
        {"summary": "Tog' manzarasi tabiat qo'ynida"},
        {"product_name": "Chempionat finali", "category": "Sport"},
    ):
        check(f"zaxira aniqlash: {payload} → event",
              detect_image_type(payload) == IMAGE_TYPE_EVENT, str(payload))
    check("mahsulot rasmi baribir product (regressiya)",
          detect_image_type({"product_name": "Sumka", "category": "Aksessuar"})
          == IMAGE_TYPE_PRODUCT, "")
    check("sport poyabzali — VOQEA emas, MAHSULOT",
          detect_image_type({"product_name": "Sport poyabzal", "category": "Oyoq kiyim"})
          == IMAGE_TYPE_PRODUCT, "")

    # 5c) normalize_analysis: tur + toifa + neytrallashtirilgan xususiyatlar.
    event = normalize_analysis({
        "image_type": "event", "product_name": "Futbol o'yini",
        "category": "Sport", "summary": "Chempionat finali",
        "visual_features": {"color": "yashil", "material": "paxta"},
    })
    check("normalize: image_type=event saqlanadi",
          event.get("image_type") == IMAGE_TYPE_EVENT, str(event))
    check("normalize: avtomatik toifa = «Voqea / Qiziqarli kontent posti»",
          event.get("category_label") == IMAGE_CATEGORY_EVENT
          or IMAGE_CATEGORY_EVENT in str(event.get("category_label")), str(event))
    check("normalize: voqea uchun rang/material uydirilmaydi",
          all(v == "noma'lum" for v in event["visual_features"].values()),
          str(event["visual_features"]))
    check("is_product_analysis(event) False / product True",
          is_product_analysis(event) is False
          and is_product_analysis(normalize_analysis({"product_name": "Sumka"})) is True, "")

    # 5d) Bot xabari: «Mahsulot: Rang/Material» SO'RALMAYDI.
    summary = _analysis_summary(event, "uz")
    check("voqea xulosasi — «Voqea / Qiziqarli kontent posti» sarlavhasi",
          "Voqea / Qiziqarli kontent posti" in summary, summary[:200])
    check("voqea xulosasida «Rang:» / «Material:» YO'Q",
          "Rang:" not in summary and "Material:" not in summary, summary[:200])
    check("voqea xulosasida «Mahsulot aniqlandi» YO'Q",
          "Mahsulot aniqlandi" not in summary, summary[:200])
    product_summary = _analysis_summary(
        normalize_analysis({"product_name": "Sumka", "category": "Aksessuar",
                            "visual_features": {"color": "qora", "material": "charm"}}),
        "uz")
    check("mahsulot xulosasi o'z kartochkasini saqladi (regressiya)",
          "Mahsulot aniqlandi" in product_summary and "Rang:" in product_summary,
          product_summary[:200])

    # 5e) Generation prompti: voqea uchun sotuv tafsilotlari TAQIQLANADI.
    event_prompt = _image_analysis_text(event)
    check("generation prompti: VOQEA deb belgilangan",
          "VOQEA" in event_prompt, event_prompt[:160])
    check("generation prompti: narx/material yozmaslik aytilgan",
          "mahsulot sotilmaydi" in event_prompt.lower()
          or "yozmang" in event_prompt.lower(), event_prompt[:200])
    check("generation prompti: voqea uchun «Material:» qatori YO'Q",
          "Material:" not in event_prompt, event_prompt[:200])
    product_prompt = _image_analysis_text(normalize_analysis(
        {"product_name": "Sumka", "visual_features": {"material": "charm"}}))
    check("generation prompti: mahsulot uchun kartochka saqlanadi",
          "MAHSULOT" in product_prompt and "Material:" in product_prompt,
          product_prompt[:160])

    # 5f) Vision system prompti rasm turini so'raydi.
    system_prompt = build_vision_system_prompt("uz")
    check("system prompt: image_type (product/event) majburiy maydon",
          "image_type" in system_prompt and '"event"' in system_prompt
          and '"product"' in system_prompt, system_prompt[:200])
    check("system prompt: voqea uchun rang/material uydirmaslik qoidasi",
          "noma'lum" in system_prompt and "uydirmang" in system_prompt, "")
    check("analyze_image imzosi saqlanadi (regressiya)",
          "lang" in analyze_image.__code__.co_varnames, "")

    # 5g) Voqea rasmini tahlil qilgach «sotuv posti» uslub savoli berilmaydi:
    # mahsulot uchun avvalgi savol, voqea uchun neytral variant ishlatiladi.
    ip_src = (ROOT / "handlers" / "image_post.py").read_text(encoding="utf-8")
    check("vision ekrani: voqea uchun neytral uslub savoli tanlanadi",
          re.search(r'"image_choose_style_event"\s*\n\s*if analysis\.get\('
                    r'"image_type"\) == IMAGE_TYPE_EVENT', ip_src) is not None,
          "")
    check("vision ekrani: mahsulot uchun avvalgi savol saqlanadi",
          'else "image_choose_style"' in ip_src, "")

    # 5h) i18n: yangi kalitlar uchala tilda mavjud.
    for key in ("image_event_summary", "image_product_category",
                "image_choose_style_event",
                "pend_edit_menu_title", "pend_edit_btn_text",
                "pend_edit_btn_button", "pend_edit_btn_react",
                "pend_edit_btn_time", "pend_edit_btn_back"):
        values = [get_text(key, lang) for lang in LANGS]
        check(f"i18n «{key}»: uz/ru/en mavjud",
              all(v and not str(v).startswith(key) for v in values), str(values)[:140])


# ============================================================================
def main() -> bool:
    print("=" * 70)
    print(" 🎨 REAKSIYALAR · ✏️ TAHRIRLASH · ❌ BEKOR · 💡 ESLATMA · 📸 VISION")
    print("=" * 70)
    test_custom_reaction_emojis()
    test_edit_selection_menu()
    test_cancel_flow_returns_to_scheduled_list()
    test_ai_reliability_note()
    test_vision_event_classification()
    print()
    print("=" * 70)
    print(f" JAMI: o'tdi={passed}, xato={failures}")
    if failures == 0:
        print(" 5 TA UX/LOGIKA TUZATISHI 100% YASHIL ✔")
    else:
        print(" XATOLIK: yuqoridagi [FAIL] qatorlarini ko'ring.")
    print("=" * 70)
    return failures == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
