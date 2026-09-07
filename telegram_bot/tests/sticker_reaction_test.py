#!/usr/bin/env python3
"""STICKER → REAKSIYA testlari (GET_REACTIONS / reaksiya tanlash bosqichi).

Ssenariy: post yaratishda reaksiya tanlash bosqichida foydalanuvchi stiker
yuborsa — ConversationHandler uni qabul qilishi, global
"Kechirasiz, men bu xabarni tushunmadim" fallback'iga tushib butun post
yaratish jarayonini bekor qilib yubormasligi shart:

  1. Stikerning emojisi (update.message.sticker.emoji) ajratib olinadi va
     postning reaksiyalari ro'yxatiga qo'shiladi;
  2. Tasdiq xabari chiqadi va inline klaviaturada o'sha emoji TANLANGAN
     (✅) holatda ko'rinadi;
  3. Reaksiyalar HECH QACHON post matniga (caption/text) qo'shilmaydi —
     ular faqat post pastidagi inline tugma bo'lib turadi;
  4. Stikerning emojisi bo'lmasa — xushmuomala tushuntirish berilib,
     jarayon (GET_REACTIONS) saqlanadi.

Ishga tushirish:
    cd telegram_bot && python tests/sticker_reaction_test.py
"""
import asyncio
import inspect
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Test S.")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telegram import (  # noqa: E402
    Update, Message, Chat, User, Sticker,
)
from telegram.ext import (  # noqa: E402
    ApplicationBuilder, CallbackContext, ConversationHandler, MessageHandler,
)

import handlers as h_mod  # noqa: E402
from handlers import register_all_handlers  # noqa: E402
import handlers.new_post as np_mod  # noqa: E402
from handlers.new_post import (  # noqa: E402
    GET_REACTIONS, GET_AUTO_DELETE,
    handle_reaction_sticker, reactions_received,
)
from keyboards.inline import strip_leading_reaction_glyphs  # noqa: E402
from locales.translations import get_text  # noqa: E402
from scheduler import build_reaction_buttons  # noqa: E402

CHECKS = []


def check(msg, cond, detail=""):
    CHECKS.append((bool(cond), msg, detail))
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [FAIL] {msg} — {detail}")


# ----------------------------------------------------------------------
# Test infratuzilmasi
# ----------------------------------------------------------------------
class _RecBot:
    """send_message chaqiruvlarini yozib boradigan yechita bot."""
    id = 1
    username = "StickerTestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"chat_id": chat_id, "text": text,
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))


def _sticker(emoji):
    """PTB Sticker modeli (emoji=None — emojisi bo'lmagan stiker)."""
    return Sticker(
        file_id="stk1", file_unique_id="stku1", width=512, height=512,
        is_animated=False, is_video=False, type="regular", emoji=emoji,
    )


def _sticker_update(sticker_emoji, bot=None, message_id=1):
    user = User(id=777, first_name="Ali", is_bot=False)
    chat = Chat(id=777, type="private")
    msg = Message(message_id=message_id, date=datetime.now(), chat=chat,
                  from_user=user, sticker=_sticker(sticker_emoji))
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _text_update(text, bot=None, message_id=1):
    user = User(id=777, first_name="Ali", is_bot=False)
    chat = Chat(id=777, type="private")
    msg = Message(message_id=message_id, date=datetime.now(), chat=chat,
                  from_user=user, text=text)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _callback_update(data, bot=None):
    """Inline tugma bosilishi (callback_query) uchun minimal Update."""
    user = User(id=777, first_name="Ali", is_bot=False)
    chat = Chat(id=777, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user,
                  text="reaksiya kartasi")
    if bot is not None:
        msg.set_bot(bot)

    class _Msg:
        def __init__(self, real):
            self.real = real
            self.chat_id = 777
            self.replies = []

        async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
            self.replies.append(text)
            if bot is not None:
                bot.sent.append({"kind": "message", "chat_id": self.chat_id,
                                 "text": text, "reply_markup": reply_markup})
            return SimpleNamespace(message_id=1)

        def __getattr__(self, item):
            return getattr(self.real, item)

    msgw = _Msg(msg)

    class _Query:
        def __init__(self):
            self.data = data
            self.from_user = user
            self.message = msgw
            self.game_short_name = None
            self.inline_message_id = None

        async def answer(self, text=None, show_alert=False):
            return None

    upd = Update(update_id=2, callback_query=_Query())
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _build_app():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    return app


def _main_conv(app):
    return [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]


def _patch_db(responses=None):
    import database as db_mod
    responses = responses or {}

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name in responses:
            val = responses[name]
            return val(*args, **kwargs) if callable(val) else val
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    return lambda: setattr(db_mod, "run_db", orig)


async def _dispatch(app, upd):
    """Birinchi mos handlerni haqiqiy CallbackContext bilan ishga tushiradi."""
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            check_ = handler.check_update(upd)
            if check_ is None or check_ is False:
                continue
            ctx = CallbackContext(app, chat_id=upd.effective_chat.id,
                                  user_id=upd.effective_user.id)
            await handler.handle_update(upd, app, check_, ctx)
            return handler
    return None


def _button_labels(markup):
    """InlineKeyboardMarkup dagi barcha tugma yorliqlari (ro'yxat)."""
    if markup is None or not hasattr(markup, "inline_keyboard"):
        return []
    out = []
    for row in markup.inline_keyboard:
        for btn in row:
            out.append(btn.text)
    return out


class _FakeMsg:
    """Bepul birlik testlari uchun stiker xabar modeli."""

    def __init__(self, sticker_emoji):
        self.replies = []
        self.text = None
        self.chat_id = 777
        self.sticker = SimpleNamespace(file_id="stk1", emoji=sticker_emoji)

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append((text, reply_markup))
        return SimpleNamespace(message_id=len(self.replies))


def _upd(msg):
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=777),
                           effective_message=msg)


def _ctx(user_data):
    return SimpleNamespace(user_data=user_data, bot=None)


# ----------------------------------------------------------------------
# 1. Alohida handler mavjudligi
# ----------------------------------------------------------------------
def test_handler_exists_and_wired():
    print("== handle_reaction_sticker: alohida handler va ulanish ==")
    check("handlers.new_post da handle_reaction_sticker mavjud",
          hasattr(np_mod, "handle_reaction_sticker"))
    check("async handler funksiya",
          inspect.iscoroutinefunction(np_mod.handle_reaction_sticker))
    src = (ROOT / "handlers/new_post.py").read_text(encoding="utf-8")
    check("reactions_received stiker xabarini handle_reaction_sticker'ga "
          "delegatsiya qiladi",
          "return await handle_reaction_sticker(update, context)" in src)
    init_src = (ROOT / "handlers/__init__.py").read_text(encoding="utf-8")
    check("GET_REACTIONS: filters.Sticker.ALL ro'yxatdan o'tgan",
          "MessageHandler(filters.Sticker.ALL, reactions_received)" in init_src)


# ----------------------------------------------------------------------
# 2. Stiker emojisi → reaksiya ro'yxati + tasdiq + klaviaturada ✅
# ----------------------------------------------------------------------
def test_sticker_emoji_added_with_confirmation_and_selected_keyboard():
    print("== stiker 👍: reaksiyaga qo'shiladi, klaviaturada ✅, matn toza ==")
    msg = _FakeMsg(sticker_emoji="👍")
    ud = {"lang": "uz", "content": "Salom, dunyo!", "post_type": "text",
          "file_id": None}
    state = asyncio.run(handle_reaction_sticker(_upd(msg), _ctx(ud)))
    check("jarayon uzilmaydi — holat GET_REACTIONS da qoladi",
          state == GET_REACTIONS, str(state))
    check("stiker emojisi (👍) reaksiyalar ro'yxatiga qo'shildi",
          ud.get("selected_reactions") == ["👍"], str(ud.get("selected_reactions")))
    check("tasdiq xabari chiqdi (np_reactions_selected)",
          bool(msg.replies)
          and msg.replies[0][0] == get_text("np_reactions_selected", "uz", emojis="👍"),
          str(msg.replies)[:160])
    labels = _button_labels(msg.replies[0][1])
    check("inline klaviaturada o'sha emoji TANLANGAN holatda: '👍 ✅'",
          "👍 ✅" in labels, str(labels))
    check("tanlanmagan emoji belgisisiz qoladi: '❤️'",
          "❤️" in labels, str(labels))
    check("post matni (content) O'ZGARMADI — reaksiya caption'ga qo'shilmadi",
          ud.get("content") == "Salom, dunyo!" and "👍" not in (ud.get("content") or ""),
          str(ud.get("content")))


def test_sticker_custom_emoji_added():
    print("== stiker 😍 (kanonik bo'lmagan): u ham reaksiyaga qo'shiladi ==")
    msg = _FakeMsg(sticker_emoji="😍")
    ud = {"lang": "ru", "content": "Привет", "post_type": "text", "file_id": None}
    state = asyncio.run(handle_reaction_sticker(_upd(msg), _ctx(ud)))
    check("holat GET_REACTIONS", state == GET_REACTIONS, str(state))
    check("😍 tanlovga qo'shildi", ud.get("selected_reactions") == ["😍"],
          str(ud.get("selected_reactions")))
    check("matn o'zgarmadi", ud.get("content") == "Привет", str(ud.get("content")))
    check("tasdiq xabari (ru) chiqdi",
          bool(msg.replies) and "😍" in msg.replies[0][0], str(msg.replies)[:160])


def test_sticker_keeps_existing_selection_and_no_duplicates():
    print("== stiker 🔥: mavjud tanlov saqlanadi, takrorlanish yo'q ==")
    msg = _FakeMsg(sticker_emoji="🔥")
    ud = {"lang": "uz", "content": "Post", "post_type": "text",
          "file_id": None, "selected_reactions": ["👍"]}
    state = asyncio.run(handle_reaction_sticker(_upd(msg), _ctx(ud)))
    check("holat GET_REACTIONS", state == GET_REACTIONS, str(state))
    check("mavjud 👍 saqlanib, 🔥 qo'shildi: ['👍', '🔥']",
          ud.get("selected_reactions") == ["👍", "🔥"],
          str(ud.get("selected_reactions")))
    check("tasdiqda ikkala emoji bor",
          bool(msg.replies) and "👍" in msg.replies[0][0] and "🔥" in msg.replies[0][0],
          str(msg.replies)[:160])

    # Xuddi shu stiker qaytadan yuborilsa — takrorlanmaydi.
    msg2 = _FakeMsg(sticker_emoji="👍")
    state2 = asyncio.run(handle_reaction_sticker(_upd(msg2), _ctx(ud)))
    check("takror stiker — ro'yxat o'zgarmaydi",
          state2 == GET_REACTIONS and ud.get("selected_reactions") == ["👍", "🔥"],
          str(ud.get("selected_reactions")))


# ----------------------------------------------------------------------
# 3. Emojisi yo'q stiker — xushmuomala tushuntirish, jarayon saqlanadi
# ----------------------------------------------------------------------
def test_sticker_without_emoji_polite_explanation_flow_preserved():
    print("== emojisiz stiker: xushmuomala tushuntirish + jarayon saqlanadi ==")
    msg = _FakeMsg(sticker_emoji=None)
    ud = {"lang": "uz", "content": "Post", "post_type": "text", "file_id": None}
    state = asyncio.run(handle_reaction_sticker(_upd(msg), _ctx(ud)))
    check("holat GET_REACTIONS da qoladi (jarayon bekor qilinmadi)",
          state == GET_REACTIONS, str(state))
    check("xushmuomala tushuntirish berildi (np_reactions_use_inline)",
          bool(msg.replies) and msg.replies[0][0] == get_text("np_reactions_use_inline", "uz"),
          str(msg.replies)[:160])
    check("rejim javobi (fallback) EMAS — klaviatura yana taklif qilinadi",
          msg.replies and msg.replies[0][1] is not None
          and any("Davom etish" in t for t in _button_labels(msg.replies[0][1])),
          str(_button_labels(msg.replies[0][1])))
    check("tanlov ro'yxati buzilmadi",
          ud.get("selected_reactions", []) == [], str(ud.get("selected_reactions")))
    check("post matni o'zgarmadi", ud.get("content") == "Post", str(ud.get("content")))

    # Bo'sh emoji ("") ham shu yo'l bilan ishloq qilinadi.
    msg2 = _FakeMsg(sticker_emoji="")
    ud2 = {"lang": "ru", "content": "Пост"}
    state2 = asyncio.run(handle_reaction_sticker(_upd(msg2), _ctx(ud2)))
    check("bo'sh emoji: holat saqlanadi + ru tushuntirish",
          state2 == GET_REACTIONS
          and msg2.replies[0][0] == get_text("np_reactions_use_inline", "ru"),
          str(msg2.replies)[:120])


# ----------------------------------------------------------------------
# 4. Ro'yxatdan o'tish: GET_REACTIONS stikerni qabul qiladi (fallback'ga emas)
# ----------------------------------------------------------------------
def test_registration_get_reactions_accepts_sticker():
    print("== GET_REACTIONS holatida filters.Sticker.ALL handler faol ==")
    app = _build_app()
    conv = _main_conv(app)
    upd = _sticker_update("👍", bot=_RecBot())
    matching = [h for h in conv.states[GET_REACTIONS]
                if isinstance(h, MessageHandler) and h.check_update(upd)]
    check("stiker xabarini qabul qiluvchi MessageHandler bor", bool(matching),
          str(conv.states[GET_REACTIONS])[:200])
    check("stiker handleri reaksiya modulidan (reactions_received → "
          "handle_reaction_sticker)",
          any(h.callback is reactions_received for h in matching),
          str([getattr(h, "callback", None) for h in matching]))


# ----------------------------------------------------------------------
# 5. To'liq zanjir: stiker → tasdiq → "Davom etish" → reaction_emojis (caption toza)
# ----------------------------------------------------------------------
def test_full_conversation_chain_sticker_to_reactions():
    print("== zanjir: stiker 👍 → tasdiq (✅) → nprt:done → reaction_emojis ==")
    app = _build_app()
    conv = _main_conv(app)
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = GET_REACTIONS
        app._user_data.setdefault(777, {}).update(
            {"lang": "uz", "content": "Yangi post matni", "post_type": "text",
             "file_id": None})
        bot = _RecBot()

        # 1) Stiker yuboriladi — ConversationHandler qabul qiladi (fallback EMAS).
        upd = _sticker_update("👍", bot=bot)
        handler = asyncio.run(_dispatch(app, upd))
        check("stiker ConversationHandler tomonidan qabul qilindi",
              isinstance(handler, ConversationHandler), str(handler))
        check("global 'tushunmadim' fallback'iga tushmadi",
              all(s["text"] != get_text("unknown_message_fallback", "uz")
                  for s in bot.sent), str(bot.sent)[:160])
        check("holat GET_REACTIONS da qoldi (jarayon bekor bo'lmadi)",
              conv._conversations.get((777, 777)) == GET_REACTIONS,
              str(conv._conversations.get((777, 777))))
        check("tasdiq xabari yuborildi",
              bool(bot.sent)
              and bot.sent[0]["text"] == get_text("np_reactions_selected", "uz", emojis="👍"),
              str(bot.sent)[:160])
        labels = _button_labels(bot.sent[0]["reply_markup"])
        check("inline klaviaturada '👍 ✅' (tanlangan holat)",
              "👍 ✅" in labels, str(labels))
        check("reaction emoji caption'ga qo'shilmadi",
              app.user_data.get(777, {}).get("content") == "Yangi post matni",
              str(app.user_data.get(777, {}).get("content")))

        # 2) "➡️ Davom etish" (nprt:done) — keyingi qadamga o'tiladi.
        qupd = _callback_update("nprt:done", bot=bot)
        handler2 = asyncio.run(_dispatch(app, qupd))
        check("nprt:done ConversationHandler ichida ishlaydi",
              isinstance(handler2, ConversationHandler), str(handler2))
        check("holat GET_AUTO_DELETE ga o'tdi",
              conv._conversations.get((777, 777)) == GET_AUTO_DELETE,
              str(conv._conversations.get((777, 777))))

        ud = app.user_data.get(777, {})
        check("reaction_emojis saqlandi: ['👍']",
              ud.get("reaction_emojis") == ["👍"], str(ud.get("reaction_emojis")))
        check("enable_reactions = True", ud.get("enable_reactions") is True,
              str(ud.get("enable_reactions")))
        check("post matni (caption) TOZA — stiker emojisi YO'Q",
              ud.get("content") == "Yangi post matni"
              and "👍" not in (ud.get("content") or ""),
              str(ud.get("content")))
        check("DB matni: reaksiya glyph caption'ga qo'shilmaydi",
              np_mod._content_for_db(ud.get("content"), ud.get("reaction_emojis"))
              == "Yangi post matni")
        # 3) Scheduler: reaksiya post MATNI emas — pastidagi INLINE TUGMA.
        row = build_reaction_buttons(42, True, ud.get("reaction_emojis"))
        check("scheduler: reaksiya inline tugma sifatida chiqadi",
              [b.text for b in row] == ["👍"], str([b.text for b in row]))
        check("scheduler: tugmalar caption matni bilan bog'liq emas",
              all(b.callback_data.startswith("react:42:") for b in row),
              str([b.callback_data for b in row]))
    finally:
        conv._conversations.pop((777, 777), None)
        app._user_data.pop(777, None)
        restore()


# ----------------------------------------------------------------------
# 6. To'liq zanjir: emojisiz stiker → jarayon saqlanib qoladi
# ----------------------------------------------------------------------
def test_conversation_chain_sticker_without_emoji():
    print("== zanjir: emojisiz stiker → tushuntirish, jarayon davom etadi ==")
    app = _build_app()
    conv = _main_conv(app)
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        h_mod._UNKNOWN_FALLBACK_LAST.clear()
        conv._conversations[(777, 777)] = GET_REACTIONS
        app._user_data.setdefault(777, {}).update(
            {"lang": "uz", "content": "Post matni", "post_type": "text",
             "file_id": None})
        bot = _RecBot()

        upd = _sticker_update(None, bot=bot)  # emojisiz stiker
        handler = asyncio.run(_dispatch(app, upd))
        check("ConversationHandler qabul qildi (fallback EMAS)",
              isinstance(handler, ConversationHandler), str(handler))
        check("holat GET_REACTIONS da qoldi — jarayon bekor qilinmadi",
              conv._conversations.get((777, 777)) == GET_REACTIONS,
              str(conv._conversations.get((777, 777))))
        check("xushmuomala tushuntirish berildi",
              bool(bot.sent)
              and bot.sent[0]["text"] == get_text("np_reactions_use_inline", "uz"),
              str(bot.sent)[:160])
        check("tanlov o'zgarmadi",
              not app.user_data.get(777, {}).get("selected_reactions"),
              str(app.user_data.get(777, {})))

        # Jarayon saqlangani isboti: endi emoji matni yuborsak ham qabul qilinadi.
        tupd = _text_update("👍 ❤️", bot=bot)
        handler2 = asyncio.run(_dispatch(app, tupd))
        check("keyingi emoji xabari ham qabul qilindi",
              isinstance(handler2, ConversationHandler), str(handler2))
        check("emoji tanlovga qo'shildi: ['👍', '❤️']",
              app.user_data.get(777, {}).get("selected_reactions") == ["👍", "❤️"],
              str(app.user_data.get(777, {})))
        check("holat hali GET_REACTIONS",
              conv._conversations.get((777, 777)) == GET_REACTIONS)
        check("caption hali ham toza",
              app.user_data.get(777, {}).get("content") == "Post matni",
              str(app.user_data.get(777, {}).get("content")))
    finally:
        conv._conversations.pop((777, 777), None)
        app._user_data.pop(777, None)
        restore()


# ----------------------------------------------------------------------
# 7. Reaksiyalar hech qachon caption'ga qo'shilmaydi (yordamchi tekshiruv)
# ----------------------------------------------------------------------
def test_reactions_never_enter_content():
    print("== garantiya: reaksiyalar caption/text ga hech qachon qo'shilmaydi ==")
    for lang in ("uz", "ru"):
        msg = _FakeMsg(sticker_emoji="👍")
        ud = {"lang": lang, "content": "Asl matn", "post_type": "text",
              "file_id": None}
        asyncio.run(handle_reaction_sticker(_upd(msg), _ctx(ud)))
        check(f"lang={lang}: content o'zgarmadi",
              ud.get("content") == "Asl matn", str(ud.get("content")))
        check(f"lang={lang}: DB matnida reaksiya glyph yo'q",
              strip_leading_reaction_glyphs(ud.get("content"),
                                            ud.get("selected_reactions"))
              == "Asl matn")


def main():
    print("=" * 64)
    print("STICKER → REAKSIYA TESTLARI (GET_REACTIONS bosqichi)")
    print("=" * 64)
    tests = [
        test_handler_exists_and_wired,
        test_sticker_emoji_added_with_confirmation_and_selected_keyboard,
        test_sticker_custom_emoji_added,
        test_sticker_keeps_existing_selection_and_no_duplicates,
        test_sticker_without_emoji_polite_explanation_flow_preserved,
        test_registration_get_reactions_accepts_sticker,
        test_full_conversation_chain_sticker_to_reactions,
        test_conversation_chain_sticker_without_emoji,
        test_reactions_never_enter_content,
    ]
    for t in tests:
        t()
        print()
    failed = [c for c in CHECKS if not c[0]]
    print("-" * 64)
    print(f"Jami tekshiruvlar: {len(CHECKS)}, "
          f"muvaffaqiyatli: {len(CHECKS) - len(failed)}, xato: {len(failed)}")
    if failed:
        for _ok, m, d in failed:
            print(f"  [FAIL] {m} — {d}")
        sys.exit(1)
    print("Barcha sticker→reaksiya testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
