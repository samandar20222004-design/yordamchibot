#!/usr/bin/env python3
"""ALBOM (media_group) + TUGMA/REAKSIYA cheklovi ogohlantirishi testlari.

Telegram Bot API qoidasi: sendMediaGroup'ga inline_keyboard (URL tugma yoki
reaksiya) ulab bo'lmaydi. Foydalanuvchi bir nechta rasmli albom yuborgani
dalolatida tugma/reaksiya bosqichiga yetganda bot xushmuomala ogohlantirish
beradi va 2 ta tanlov taklif etadi:
  [🖼 1-rasm qolsin + tugma qo'shilsin] — post bitta rasmga aylanadi;
  [⏩ Tugmalarsiz to'liq albom chiqsin] — 10 tagacha to'liq albom chiqadi.

Qo'shimcha: kanalga faqat foydalanuvchining ASL matni (caption/text) chiqishi
kerak — "Postni tasdiqlang:", "Kanal:", "Turi: Albom...", "Tugma:",
"Reaksiyalar:", "Avto-o'chirish:" kabi ichki preview/xizmat yozuvlari
scheduler tomonidan yuborishdan oldin tozalanadi.

Ishga tushirish:
    cd telegram_bot && python tests/album_warning_test.py
"""
import asyncio
import json
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
os.environ["SENT_JOURNAL_PATH"] = "off"  # sent-journal fayl yozmasin (test tozaligi)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telegram import (  # noqa: E402
    Update, Message, Chat, User, PhotoSize, CallbackQuery,
)
from telegram.ext import ApplicationBuilder, ConversationHandler, CallbackContext  # noqa: E402

import handlers as h_mod  # noqa: E402
from handlers import register_all_handlers  # noqa: E402
import handlers.new_post as np_mod  # noqa: E402
from handlers.new_post import (  # noqa: E402
    GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL, GET_REACTIONS, GET_AUTO_DELETE,
    content_received, btn_title_received, reactions_received,
    album_choice_callback, _ask_reactions_step, _proceed_after_reactions,
    _is_multi_album, _album_items_of, _album_choice_keyboard,
    _strip_unsupported_album_options, confirm_post_callback,
)
from keyboards.default import BTN_SKIP_BUTTON  # noqa: E402
from locales.translations import get_text, has_key, translation_parity_report  # noqa: E402
import scheduler as sch  # noqa: E402
from scheduler import (  # noqa: E402
    sanitize_channel_content, _execute_send, _build_album_media,
)

CHECKS = []


def check(msg, cond, detail=""):
    CHECKS.append((bool(cond), msg, detail))
    if not cond:
        print(f"  [FAIL] {msg}: {detail}")
    else:
        print(f"  [OK] {msg}")


# ----------------------------------------------------------------------
# Test infratuzilmasi
# ----------------------------------------------------------------------
class _RecBot:
    """Bot chaqiruvlarini yozib boradi (conversation dispatch uchun yetarli)."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []
        self.callback_answers = []
        self._mid = 0

    async def _next(self):
        self._mid += 1
        return SimpleNamespace(message_id=self._mid)

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"kind": "message", "text": text, "reply_markup": reply_markup})
        return await self._next()

    async def send_photo(self, chat_id=None, photo=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"kind": "photo", "caption": caption, "reply_markup": reply_markup})
        return await self._next()

    async def send_video(self, chat_id=None, video=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        self.sent.append({"kind": "video", "caption": caption, "reply_markup": reply_markup})
        return await self._next()

    async def send_media_group(self, chat_id=None, media=None, **kw):
        self.sent.append({"kind": "media_group", "media": list(media or []),
                          "reply_markup": kw.get("reply_markup")})
        return [await self._next() for _ in (media or [])]

    async def answer_callback_query(self, callback_query_id=None, **kw):
        self.callback_answers.append(callback_query_id)
        return True


def _text_update(uid, text, bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text=text)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _photo_update(uid, file_id, caption="", media_group_id=None, bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    kw = dict(message_id=1, date=datetime.now(), chat=chat, from_user=user)
    if file_id:
        from telegram import PhotoSize
        kw["photo"] = [PhotoSize(file_id=file_id, file_unique_id=file_id + "_u",
                                 width=320, height=240)]
    if caption:
        kw["caption"] = caption
    if media_group_id:
        kw["media_group_id"] = media_group_id
    msg = Message(**kw)
    if bot is not None:
        msg.set_bot(bot)
    upd = Update(update_id=1, message=msg)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _callback_update(uid, data, bot=None, msg_id=555):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    msg = Message(message_id=msg_id, date=datetime.now(), chat=chat,
                  from_user=user, text="⚠️ ogohlantirish")
    q = CallbackQuery(id="cb1", from_user=user, chat_instance=str(uid),
                      message=msg, data=data)
    if bot is not None:
        msg.set_bot(bot)
        q.set_bot(bot)
    upd = Update(update_id=1, callback_query=q)
    if bot is not None:
        upd.set_bot(bot)
    return upd


def _build_app():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    return app


def _first_matching_handler(app, upd):
    for group in sorted(app.handlers):
        for handler in app.handlers[group]:
            check_ = handler.check_update(upd)
            if check_ is None or check_ is False:
                continue
            return group, handler, check_
    return None


async def _dispatch(app, upd, lang="uz", user_data=None):
    """Birinchi mos handlerni haqiqiy CallbackContext bilan ishga tushiradi."""
    found = _first_matching_handler(app, upd)
    if not found:
        return None
    group, handler, check = found
    ctx = CallbackContext(app, chat_id=upd.effective_chat.id, user_id=upd.effective_user.id)
    ctx.user_data["lang"] = lang
    if user_data is not None:
        ctx.user_data.update(user_data)
    await handler.handle_update(upd, app, check, ctx)
    return handler


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


def _album_user_data(n=3, captions=None, lang="uz"):
    """n ta rasmli albom user_data'si (collector yakunlagandek)."""
    items = []
    for i in range(n):
        items.append({
            "type": "photo",
            "file_id": f"ap{i + 1}",
            "caption": (captions[i] if captions and i < len(captions) else
                        ("Asl caption" if i == 0 else "")),
        })
    return {
        "lang": lang,
        "post_type": "album",
        "file_id": json.dumps(items, ensure_ascii=False),
        "content": "Asl caption",
        "_album_ready": True,
        "_album_count": n,
    }


def _warn_markup(markup):
    """Ogohlantirish inline klaviaturasi: 2 qator, 2 callback."""
    if markup is None:
        return []
    rows = markup.inline_keyboard
    return [[(b.text, b.callback_data) for b in row] for row in rows]


# ----------------------------------------------------------------------
# 1. I18N: ogohlantirish matnlari uz/ru da, aniq so'zlar bilan
# ----------------------------------------------------------------------
def test_warning_i18n_keys():
    print("== 1. Ogohlantirish matnlari (uz/ru) ==")
    for key in ("np_album_warning", "np_album_choice_first_photo",
                "np_album_choice_full", "np_album_first_photo_done",
                "np_album_full_done"):
        check(f"uz: {key} mavjud", has_key(key, "uz"))
        check(f"ru: {key} mavjud", has_key(key, "ru"))
    check("i18n paritet buzilmagan", translation_parity_report()["in_sync"])

    uz = get_text("np_album_warning", "uz")
    check("uz: 'Telegram qoidalariga ko'ra' bor", "Telegram qoidalariga ko'ra" in uz, uz)
    check("uz: 'bo'lmaydi' ogohlantirishi", "qo'shib bo'lmaydi" in uz, uz)
    check("uz: 'faqat 1 ta rasm' cheklovi", "faqat 1 ta rasm" in uz, uz)
    ru = get_text("np_album_warning", "ru")
    check("ru: 'По правилам Telegram' bor", "По правилам Telegram" in ru, ru)
    check("ru: 'нельзя добавить' ogohlantirishi", "нельзя добавить" in ru, ru)
    check("uz: 1-rasm tanlovi aniq",
          get_text("np_album_choice_first_photo", "uz") == "🖼 1-rasm qolsin + tugma qo'shilsin")
    check("uz: to'liq albom tanlovi aniq",
          get_text("np_album_choice_full", "uz") == "⏩ Tugmalarsiz to'liq albom chiqsin")
    check("ru: tanlov tugmalari mavjud",
          "Оставить 1 фото" in get_text("np_album_choice_first_photo", "ru")
          and "альбом без кнопок" in get_text("np_album_choice_full", "ru"))


# ----------------------------------------------------------------------
# 2. _is_multi_album / _album_items_of
# ----------------------------------------------------------------------
def test_is_multi_album_helpers():
    print("== 2. _is_multi_album / _album_items_of ==")
    ctx = SimpleNamespace(user_data=_album_user_data(3))
    check("3 rasmli albom → True", _is_multi_album(ctx) is True)
    check("_album_items_of: 3 ta", len(_album_items_of(ctx)) == 3)

    ctx1 = SimpleNamespace(user_data={
        "post_type": "photo", "file_id": "single_photo_id", "content": ""})
    check("yakka rasm → False", _is_multi_album(ctx1) is False)
    check("yakka rasm: items []", _album_items_of(ctx1) == [])

    ctx_t = SimpleNamespace(user_data={"post_type": "text", "file_id": None})
    check("matn → False", _is_multi_album(ctx_t) is False)

    ctx_bad = SimpleNamespace(user_data={"post_type": "album", "file_id": "not-json"})
    check("buzilgan JSON → False (crash yo'q)", _is_multi_album(ctx_bad) is False)

    ctx_single_album = SimpleNamespace(user_data={
        "post_type": "album",
        "file_id": json.dumps([{"type": "photo", "file_id": "x1", "caption": ""}])})
    check("1 faylli albom (post_type=album) → False", _is_multi_album(ctx_single_album) is False)


# ----------------------------------------------------------------------
# 3. Tanlov klaviaturasi
# ----------------------------------------------------------------------
def test_album_choice_keyboard():
    print("== 3. Tanlov klaviaturasi (2 inline tugma) ==")
    kb = _album_choice_keyboard("uz")
    rows = _warn_markup(kb)
    check("2 qator", len(rows) == 2, str(rows))
    check("1-tugma: 1-rasm + callback",
          rows and rows[0] == [("🖼 1-rasm qolsin + tugma qo'shilsin", "album_choice:first_photo")],
          str(rows))
    check("2-tugma: to'liq albom + callback",
          rows and len(rows) > 1 and rows[1] == [("⏩ Tugmalarsiz to'liq albom chiqsin", "album_choice:full_album")],
          str(rows))

    kb_ru = _album_choice_keyboard("ru")
    rows_ru = _warn_markup(kb_ru)
    check("ru: 2 qator", len(rows_ru) == 2, str(rows_ru))
    check("ru: callback'lar o'zgarmaydi",
          rows_ru and rows_ru[0][0][1] == "album_choice:first_photo"
          and rows_ru[1][0][1] == "album_choice:full_album", str(rows_ru))


# ----------------------------------------------------------------------
# 4. Collector: albom yakunlangach OG'HOHLANTIRISH (tugma so'rovi emas)
# ----------------------------------------------------------------------
def test_collector_shows_album_warning():
    print("== 4. Collector: bir nechta rasmli albom → ogohlantirish ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.12
    user_data = {"lang": "uz"}
    bot = _RecBot()

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        for fid in ("c1", "c2", "c3"):
            upd = _photo_update(42, fid, caption="Caption" if fid == "c1" else "",
                                media_group_id="g4")
            await content_received(upd, ctx)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.3)

    try:
        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait
        np_mod._ALBUM_BUFFERS.clear()

    check("collector: ogohlantirish yuborildi",
          any(s["kind"] == "message" and get_text("np_album_warning", "uz") in (s["text"] or "")
              for s in bot.sent), str(bot.sent)[:150])
    check("collector: eski tugma so'rovi YO'Q",
          not any(get_text("np_button_ask", "uz") in (s["text"] or "") for s in bot.sent),
          str(bot.sent)[:150])
    warn = [s for s in bot.sent
            if s["kind"] == "message" and get_text("np_album_warning", "uz") in (s["text"] or "")]
    check("collector: ogohlantirishda 2 tanlov tugmasi",
          warn and len(_warn_markup(warn[0]["reply_markup"])) == 2,
          str(warn)[:150] if warn else "yo'q")
    check("collector: _album_warning_stage=button belgilandi",
          user_data.get("_album_warning_stage") == "button", str(user_data))


def test_collector_single_photo_keeps_button_prompt():
    print("== 4b. Yakka rasm — eski oqim saqlanadi (tugma so'rovi) ==")
    user_data = {"lang": "uz"}
    bot = _RecBot()

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        upd = _photo_update(42, "solo1", caption="Salom", bot=bot)
        return await content_received(upd, ctx)

    state = asyncio.run(run())
    check("yakka rasm: GET_BTN_TITLE", state == GET_BTN_TITLE, str(state))
    check("yakka rasm: tugma so'rovi yuborildi",
          any(s["kind"] == "message" and get_text("np_button_ask", "uz") in (s["text"] or "")
              for s in bot.sent), str(bot.sent)[:150])
    check("yakka rasm: ogohlantirish YO'Q",
          not any(get_text("np_album_warning", "uz") in (s["text"] or "") for s in bot.sent))


# ----------------------------------------------------------------------
# 5. Tugma bosqichi: albom + matn → ogohlantirish (btn_text saqlanmaydi)
# ----------------------------------------------------------------------
def test_btn_title_intercept_for_album():
    print("== 5. Tugma bosqichi: albom + tugma matni → ogohlantirish ==")
    user_data = _album_user_data(3)
    msg = SimpleNamespace(text="Batafsil - https://site.uz", replies=[])
    msg.reply_text = _make_reply_text(msg)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                          effective_message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await btn_title_received(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_BTN_TITLE da qoladi", state == GET_BTN_TITLE, str(state))
    check("ogohlantirish yuborildi",
          any(get_text("np_album_warning", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("btn_text saqlanMAYDI", user_data.get("btn_text") is None, str(user_data))
    check("btn_url saqlanMAYDI", user_data.get("btn_url") is None, str(user_data))
    check("ogohlantirishda inline tanlov tugmalari",
          any(len(_warn_markup(m)) == 2 for t, m in msg.replies), str(msg.replies)[:120])
    check("stage=button belgilandi", user_data.get("_album_warning_stage") == "button")


def _make_reply_text(msg):
    async def reply_text(text, **kw):
        msg.replies.append((text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=len(msg.replies))
    return reply_text


# ----------------------------------------------------------------------
# 6. Tugma bosqichi: albom + skip → reaksiya bosqichi (u yerda ogohlantirish)
# ----------------------------------------------------------------------
def test_btn_title_skip_album_goes_to_reactions_warning():
    print("== 6. Tugma bosqichi: albom + skip → reaksiya bosqichida ogohlantirish ==")
    user_data = _album_user_data(2)
    msg = SimpleNamespace(text=BTN_SKIP_BUTTON, replies=[])
    msg.reply_text = _make_reply_text(msg)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                          effective_message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await btn_title_received(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_REACTIONS", state == GET_REACTIONS, str(state))
    check("reaksiya klaviaturasi O'RNIGA ogohlantirish chiqdi",
          any(get_text("np_album_warning", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("reaksiya so'rovi (np_reactions_ask) chiqMADI",
          not any(get_text("np_reactions_ask", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("stage=reactions belgilandi", user_data.get("_album_warning_stage") == "reactions")


# ----------------------------------------------------------------------
# 7. Reaksiya bosqichi: albom → ogohlantirish (stiker/emoji qo'shilmaydi)
# ----------------------------------------------------------------------
def test_ask_reactions_step_album_warning():
    print("== 7. Reaksiya bosqichi: albom → ogohlantirish ==")
    user_data = _album_user_data(2)
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await _ask_reactions_step(msg, ctx)

    state = asyncio.run(run())
    check("holat GET_REACTIONS da qoladi", state == GET_REACTIONS, str(state))
    check("ogohlantirish yuborildi",
          any(get_text("np_album_warning", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("reaksiya so'rovi chiqmadi",
          not any(get_text("np_reactions_ask", "uz") in t for t, _ in msg.replies))
    check("stage=reactions", user_data.get("_album_warning_stage") == "reactions")


def test_reactions_received_album_emoji_shows_warning():
    print("== 7b. reactions_received: albom + emoji → ogohlantirish ==")
    user_data = _album_user_data(2)
    msg = SimpleNamespace(text="👍 ❤️", replies=[])
    msg.reply_text = _make_reply_text(msg)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                          effective_message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await reactions_received(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_REACTIONS da qoladi", state == GET_REACTIONS, str(state))
    check("ogohlantirish yuborildi",
          any(get_text("np_album_warning", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("reaksiyalar saqlanMAYDI (selected_reactions bo'sh)",
          user_data.get("selected_reactions") in (None, []), str(user_data))
    check("enable_reactions True qilinmagan",
          user_data.get("enable_reactions") in (None, False), str(user_data))


def test_reactions_received_album_skip_proceeds_clean():
    print("== 7c. reactions_received: albom + skip → avto-o'chirish (toza) ==")
    user_data = _album_user_data(2)
    msg = SimpleNamespace(text=BTN_SKIP_BUTTON, replies=[])
    msg.reply_text = _make_reply_text(msg)
    upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                          effective_message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await reactions_received(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_AUTO_DELETE", state == GET_AUTO_DELETE, str(state))
    check("enable_reactions False", user_data.get("enable_reactions") is False)
    check("reaction_emojis bo'sh", user_data.get("reaction_emojis") == [], str(user_data))
    check("avto-o'chirish so'rovi yuborildi",
          any(get_text("np_auto_delete_ask", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("albom saqlanib qoladi", user_data.get("post_type") == "album"
          and len(json.loads(user_data["file_id"])) == 2)


def test_proceed_after_reactions_album_clears_emojis():
    print("== 7d. _proceed_after_reactions: albomda reaksiyalar o'chiriladi ==")
    user_data = _album_user_data(2)
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        return await _proceed_after_reactions(msg, ctx, ["👍", "❤️", "🔥"])

    state = asyncio.run(run())
    check("holat GET_AUTO_DELETE", state == GET_AUTO_DELETE, str(state))
    check("reaksiyalar albom uchun TOZALANDI",
          user_data.get("enable_reactions") is False
          and user_data.get("reaction_emojis") == [], str(user_data))

    # Boshqa tomondan: yakka rasm uchun reaksiyalar o'chirilmaydi
    user_data2 = {"lang": "uz", "post_type": "photo", "file_id": "p1", "content": ""}
    ctx2 = SimpleNamespace(user_data=user_data2, bot=None)
    msg2 = SimpleNamespace(replies=[])
    msg2.reply_text = _make_reply_text(msg2)

    async def run2():
        return await _proceed_after_reactions(msg2, ctx2, ["👍", "❤️"])

    state2 = asyncio.run(run2())
    check("yakka rasm: reaksiyalar saqlanadi",
          state2 == GET_AUTO_DELETE
          and user_data2.get("enable_reactions") is True
          and len(user_data2.get("reaction_emojis")) == 2, str(user_data2))


# ----------------------------------------------------------------------
# 8. Tanlov callback: first_photo / full_album
# ----------------------------------------------------------------------
class _FakeQuery:
    def __init__(self, data, msg):
        self.data = data
        self.message = msg
        self.from_user = SimpleNamespace(id=42)
        self.answers = []
        self.edits = []

    async def answer(self, *a, **k):
        self.answers.append((a, k))

    async def edit_message_reply_markup(self, reply_markup=None, **k):
        self.edits.append(reply_markup)


def _cb_ctx(msg, user_data):
    return SimpleNamespace(user_data=user_data, bot=None)


def test_album_choice_first_photo_button_stage():
    print("== 8. [🖼 1-rasm] tanlovi (tugma bosqichidan) ==")
    user_data = _album_user_data(3)
    user_data["_album_warning_stage"] = "button"
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("album_choice:first_photo", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = _cb_ctx(msg, user_data)

    async def run():
        return await album_choice_callback(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_BTN_TITLE (tugma so'rovi qayta)", state == GET_BTN_TITLE, str(state))
    check("post_type → yakka rasm (birinchi element)",
          user_data.get("post_type") == "photo", str(user_data))
    check("file_id → birinchi rasm", user_data.get("file_id") == "ap1", str(user_data))
    check("caption (content) saqlanib qoldi", user_data.get("content") == "Asl caption")
    check("albom belgilari tozalandi",
          user_data.get("_album_count") is None
          and user_data.get("_album_warning_stage") is None, str(user_data))
    check("tugma so'rovi qayta yuborildi",
          any(get_text("np_button_ask", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("tasdiq xabari yuborildi",
          any(get_text("np_album_first_photo_done", "uz") in t for t, _ in msg.replies))
    check("eski tanlov tugmalari yashirildi", q.edits == [None], str(q.edits))
    check("endidan keyin albom emas", _is_multi_album(ctx) is False)


def test_album_choice_first_photo_reactions_stage():
    print("== 8b. [🖼 1-rasm] tanlovi (reaksiya bosqichidan) ==")
    user_data = _album_user_data(2)
    user_data["_album_warning_stage"] = "reactions"
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("album_choice:first_photo", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = _cb_ctx(msg, user_data)

    async def run():
        return await album_choice_callback(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_REACTIONS (reaksiya bosqichi qayta)", state == GET_REACTIONS, str(state))
    check("reaksiya bosqichi qayta so'raldi",
          any(get_text("np_reactions_ask", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("ogohlantirish QAYTA chiqmadi (reaksiya klaviaturasi chiqdi)",
          not any(get_text("np_album_warning", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("post yakka media'ga o'zgartirildi",
          user_data.get("post_type") == "photo" and user_data.get("file_id") == "ap1")


def test_album_choice_full_album():
    print("== 9. [⏩ Tugmalarsiz to'liq albom] tanlovi ==")
    user_data = _album_user_data(4)
    user_data["btn_text"] = "Batafsil"
    user_data["btn_url"] = "https://x.uz"
    user_data["selected_reactions"] = ["👍"]
    user_data["_album_warning_stage"] = "button"
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("album_choice:full_album", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = _cb_ctx(msg, user_data)

    async def run():
        return await album_choice_callback(upd, ctx)

    state = asyncio.run(run())
    check("holat GET_AUTO_DELETE (tugma/reaksiya o'tkazib yuborildi)",
          state == GET_AUTO_DELETE, str(state))
    check("albom TO'LIQ saqlandi (4 fayl)",
          user_data.get("post_type") == "album"
          and len(json.loads(user_data["file_id"])) == 4, str(user_data)[:120])
    check("tugma olib tashlandi",
          user_data.get("btn_text") is None and user_data.get("btn_url") is None)
    check("reaksiya olib tashlandi", user_data.get("selected_reactions") == [])
    check("enable_reactions False", user_data.get("enable_reactions") is False)
    check("reaction_emojis bo'sh", user_data.get("reaction_emojis") == [])
    check("avto-o'chirish so'rovi yuborildi",
          any(get_text("np_auto_delete_ask", "uz") in t for t, _ in msg.replies),
          str(msg.replies)[:120])
    check("tasdiq xabari (4 ta fayl) yuborildi",
          any("4" in t and "albom" in t.lower() for t, _ in msg.replies),
          str(msg.replies)[:150])
    check("eski tanlov tugmalari yashirildi", q.edits == [None])


def test_album_choice_stale_press_no_crash():
    print("== 9b. Eskirgan/ikkilangan bosish — crash yo'q, o'zgarish yo'q ==")
    user_data = {"lang": "uz", "post_type": "photo", "file_id": "p1", "content": "matn"}
    msg = SimpleNamespace(replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("album_choice:first_photo", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = _cb_ctx(msg, user_data)

    async def run():
        return await album_choice_callback(upd, ctx)

    state = asyncio.run(run())
    check("crash yo'q (holat qaytadi)", state == GET_BTN_TITLE, str(state))
    check("post o'zgarmadi",
          user_data.get("post_type") == "photo" and user_data.get("file_id") == "p1")
    check("tugmalar yashirildi (spam tugmasi qolmasligi uchun)", q.edits == [None])


# ----------------------------------------------------------------------
# 10. _strip_unsupported_album_options (DB yozuvdan oldin qayta himoya)
# ----------------------------------------------------------------------
def test_strip_unsupported_album_options():
    print("== 10. _strip_unsupported_album_options ==")
    user_data = _album_user_data(3)
    user_data.update({"btn_text": "Batafsil", "btn_url": "https://x.uz",
                      "enable_reactions": True, "reaction_emojis": ["👍"],
                      "selected_reactions": ["👍"]})
    ctx = SimpleNamespace(user_data=user_data)
    _strip_unsupported_album_options(ctx)
    check("albom: tugma/reaksiya tozalandi",
          user_data["btn_text"] is None and user_data["btn_url"] is None
          and user_data["enable_reactions"] is False
          and user_data["reaction_emojis"] == []
          and user_data["selected_reactions"] == [], str(user_data))
    check("albom media o'zgarmadi",
          user_data["post_type"] == "album" and len(json.loads(user_data["file_id"])) == 3)

    ud2 = {"post_type": "photo", "file_id": "p1", "btn_text": "Batafsil",
           "btn_url": "https://x.uz", "enable_reactions": True, "reaction_emojis": ["👍"]}
    ctx2 = SimpleNamespace(user_data=ud2)
    _strip_unsupported_album_options(ctx2)
    check("yakka rasm: opsiyonlar O'ZGARMAYDI",
          ud2["btn_text"] == "Batafsil" and ud2["enable_reactions"] is True, str(ud2))


# ----------------------------------------------------------------------
# 11. Conversation darajasi: callback'lar uch holatda ro'yxatdan o'tgan
# ----------------------------------------------------------------------
def test_conversation_states_handle_album_choice():
    print("== 11. Conversation: album_choice callback uch holatda ishlaydi ==")
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        # --- GET_CONTENT (collector ogohlantirishi shu holatda yuborilgan) ---
        ud = _album_user_data(3)
        ud["_album_warning_stage"] = "button"
        conv._conversations[(777, 777)] = GET_CONTENT
        bot = _RecBot()
        # Conversation handler ichida user_data app.user_data da saqlanadi.
        app.user_data[777].update(ud)
        upd = _callback_update(777, "album_choice:first_photo", bot=bot)
        handler = asyncio.run(_dispatch(app, upd, lang="uz"))
        check("GET_CONTENT: ConversationHandler ishladi",
              isinstance(handler, ConversationHandler), str(handler))
        check("GET_CONTENT: first_photo → GET_BTN_TITLE",
              conv._conversations.get((777, 777)) == GET_BTN_TITLE,
              str(conv._conversations.get((777, 777))))

        # --- GET_BTN_TITLE (tugma bosqichida ogohlantirish) ---
        ud2 = _album_user_data(2)
        ud2["_album_warning_stage"] = "reactions"
        conv._conversations[(777, 777)] = GET_BTN_TITLE
        app.user_data[777].clear()
        app.user_data[777].update(ud2)
        bot2 = _RecBot()
        upd2 = _callback_update(777, "album_choice:first_photo", bot=bot2)
        handler2 = asyncio.run(_dispatch(app, upd2, lang="uz"))
        check("GET_BTN_TITLE: ConversationHandler ishladi",
              isinstance(handler2, ConversationHandler), str(handler2))
        check("GET_BTN_TITLE: first_photo (stage=reactions) → GET_REACTIONS",
              conv._conversations.get((777, 777)) == GET_REACTIONS,
              str(conv._conversations.get((777, 777))))

        # --- GET_REACTIONS (reaksiya bosqichida ogohlantirish) ---
        ud3 = _album_user_data(5)
        ud3["_album_warning_stage"] = "button"
        conv._conversations[(777, 777)] = GET_REACTIONS
        app.user_data[777].clear()
        app.user_data[777].update(ud3)
        bot3 = _RecBot()
        upd3 = _callback_update(777, "album_choice:full_album", bot=bot3)
        handler3 = asyncio.run(_dispatch(app, upd3, lang="uz"))
        check("GET_REACTIONS: ConversationHandler ishladi",
              isinstance(handler3, ConversationHandler), str(handler3))
        check("GET_REACTIONS: full_album → GET_AUTO_DELETE",
              conv._conversations.get((777, 777)) == GET_AUTO_DELETE,
              str(conv._conversations.get((777, 777))))
        check("GET_REACTIONS: albom 5 fayl saqlandi",
              len(json.loads(app.user_data[777].get("file_id", "[]"))) == 5,
              str(app.user_data[777])[:120])
        check("callback javoblari yuborildi (jim qolmadi)",
              len(bot.callback_answers) == 1 and len(bot2.callback_answers) == 1
              and len(bot3.callback_answers) == 1)
    finally:
        conv._conversations.pop((777, 777), None)
        app._user_data.pop(777, None)
        restore()


# ----------------------------------------------------------------------
# 12. Saqlash oqimi: albom postida tugma/reaksiya DB'ga yozilmaydi
# ----------------------------------------------------------------------
def test_confirm_save_album_no_buttons_in_db():
    print("== 12. confirm_post_callback: albom postida tugma/reaksiya DB'ga yozilmaydi ==")
    # throttle chegarasi (1.5s) testlar ketma-ket kelganda yakka rasm → albom holatiga
    # xalaqit bermasligi uchun — har bir confirm testi boshida tozalaymiz
    try:
        from handlers.new_post import reset_callback_throttle as _rst
        _rst(42)
    except Exception:
        pass
    captured = {}

    def fake_add_post(**kwargs):
        captured.update(kwargs)
        return 777

    user_data = _album_user_data(3)
    user_data.update({
        "selected_channel_id": "-1001234567890",
        "selected_channel_title": "Mening Kanalim",
        "confirm_post_time": datetime.now(),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
        "confirm_end_date": None,
        "btn_text": "Batafsil",          # albomga ruxsat etilmaydi
        "btn_url": "https://x.uz",
        "enable_reactions": True,        # albomga ruxsat etilmaydi
        "reaction_emojis": ["👍"],
        "delete_after_hours": 0,
    })
    msg = SimpleNamespace(chat_id=42, replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("confirm_post:ok", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)
    is_admin = 42 in __import__("config").ADMIN_IDS_SET

    async def run():
        import database as db_mod
        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "get_user_channels":
                return [("-1001234567890", "Mening Kanalim")]
            if name == "add_post":
                return fake_add_post(*args, **kwargs)
            if name == "is_premium":
                return True  # PRO — auto-reklama xizmatlari early-return qiladi
            if name == "get_ad_settings":
                return {}
            return None
        orig = db_mod.run_db
        db_mod.run_db = fake_run_db
        try:
            return await confirm_post_callback(upd, ctx)
        finally:
            db_mod.run_db = orig

    state = asyncio.run(run())
    check("holat END (suhbat tugadi)", state == h_mod.ConversationHandler.END, str(state))
    check("add_post chaqirildi", "post_type" in captured, str(captured)[:120])
    check("post_type = album", captured.get("post_type") == "album")
    check("DB: btn_text None (albom cheklovi)", captured.get("btn_text") is None,
          str(captured.get("btn_text")))
    check("DB: btn_url None (albom cheklovi)", captured.get("btn_url") is None,
          str(captured.get("btn_url")))
    check("DB: enable_reactions False (albom cheklovi)",
          captured.get("enable_reactions") is False, str(captured.get("enable_reactions")))
    check("DB: reaction_emojis bo'sh", captured.get("reaction_emojis") == [],
          str(captured.get("reaction_emojis")))
    check("DB: asl caption saqlandi", captured.get("content") == "Asl caption",
          str(captured.get("content"))[:80])
    check("DB: file_id (albom JSON) saqlandi",
          isinstance(captured.get("file_id"), str)
          and len(json.loads(captured["file_id"])) == 3)


def test_confirm_save_single_photo_keeps_buttons():
    print("== 12b. confirm_post_callback: yakka rasm — tugma/reaksiya saqlanadi ==")
    try:
        from handlers.new_post import reset_callback_throttle as _rst
        _rst(42)
    except Exception:
        pass
    captured = {}

    def fake_add_post(**kwargs):
        captured.update(kwargs)
        return 777

    user_data = {
        "lang": "uz",
        "post_type": "photo", "file_id": "p1", "content": "Salom",
        "selected_channel_id": "-1001234567890",
        "selected_channel_title": "Mening Kanalim",
        "confirm_post_time": datetime.now(),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
        "confirm_end_date": None,
        "btn_text": "Batafsil",
        "btn_url": "https://x.uz",
        "enable_reactions": True,
        "reaction_emojis": ["👍", "❤️"],
        "delete_after_hours": 24,
    }
    msg = SimpleNamespace(chat_id=42, replies=[])
    msg.reply_text = _make_reply_text(msg)
    q = _FakeQuery("confirm_post:ok", msg)
    upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=42),
                          message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        import database as db_mod
        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "get_user_channels":
                return [("-1001234567890", "Mening Kanalim")]
            if name == "add_post":
                return fake_add_post(*args, **kwargs)
            if name == "is_premium":
                return True  # PRO — auto-reklama xizmatlari early-return qiladi
            if name == "get_ad_settings":
                return {}
            return None
        orig = db_mod.run_db
        db_mod.run_db = fake_run_db
        try:
            return await confirm_post_callback(upd, ctx)
        finally:
            db_mod.run_db = orig

    state = asyncio.run(run())
    check("holat END", state == h_mod.ConversationHandler.END, str(state))
    check("DB: yakka rasm — tugma saqlanadi",
          captured.get("btn_text") == "Batafsil" and captured.get("btn_url") == "https://x.uz",
          str(captured)[:120])
    check("DB: yakka rasm — reaksiyalar saqlanadi",
          captured.get("enable_reactions") is True
          and len(captured.get("reaction_emojis") or []) == 2, str(captured)[:120])


# ----------------------------------------------------------------------
# 13. KANALGA TOZA MATN: sanitize_channel_content
# ----------------------------------------------------------------------
UZ_PREVIEW = (
    "📋 <b>Postni tasdiqlang:</b>\n"
    "\n"
    "📢 <b>Kanal:</b> Mening Kanalim\n"
    "📦 <b>Turi:</b> 🖼 Albom: 3 ta rasm\n"
    "⏰ 2026-09-07 14:00 (Toshkent vaqti)\n"
    "📋 <b>Matn:</b>\n"
    "ASL POST MATNI — bu saqlanishi shart\n"
    "Ikkinchi qator ham saqlanadi\n"
    "🔘 Tugma: <b>Batafsil</b>\n"
    "👍 Reaksiyalar: 👍 ❤️ 🔥\n"
    "⏳ Avto-o'chirish: 24 soat"
)

RU_PREVIEW = (
    "📋 <b>Подтвердите пост:</b>\n"
    "\n"
    "📢 <b>Канал:</b> Мой Канал\n"
    "📦 <b>Тип:</b> 🖼 Альбом: 3 фото\n"
    "⏰ 07.09.2026 14:00 (время Ташкента)\n"
    "📋 <b>Текст:</b>\n"
    "ASL POST MATNI — saqlanadi\n"
    "🔘 Кнопка: <b>Подробнее</b>\n"
    "👍 Реакции: 👍 ❤️\n"
    "⏳ Авто-удаление: 24 ч."
)


def test_sanitize_channel_content_uz():
    print("== 13. sanitize: UZ preview → faqat asl matn ==")
    out = sanitize_channel_content(UZ_PREVIEW)
    check("asl matn qoldi", "ASL POST MATNI — bu saqlanishi shart" in out, out)
    check("ikkinchi qator qoldi", "Ikkinchi qator ham saqlanadi" in out, out)
    check("'Postni tasdiqlang' olib tashlandi", "Postni tasdiqlang" not in out, out)
    check("'Kanal:' olib tashlandi", "Kanal:" not in out, out)
    check("'Turi:' olib tashlandi", "Turi:" not in out, out)
    check("'Albom: 3 ta rasm' olib tashlandi", "Albom: 3 ta rasm" not in out, out)
    check("vaqt qatori olib tashlandi", "Toshkent vaqti" not in out, out)
    check("'Matn:' yorlig'i olib tashlandi", "Matn:" not in out, out)
    check("'Tugma:' olib tashlandi", "Tugma:" not in out, out)
    check("'Reaksiyalar:' olib tashlandi", "Reaksiyalar:" not in out, out)
    check("'Avto-o'chirish:' olib tashlandi", "Avto-o'chirish" not in out, out)
    check("natija toza 2 qator", out.strip() ==
          "ASL POST MATNI — bu saqlanishi shart\nIkkinchi qator ham saqlanadi", out)


def test_sanitize_channel_content_ru():
    print("== 13b. sanitize: RU preview → faqat asl matn ==")
    out = sanitize_channel_content(RU_PREVIEW)
    check("asl matn qoldi", "ASL POST MATNI — saqlanadi" in out, out)
    check("'Подтвердите пост' olib tashlandi", "Подтвердите пост" not in out, out)
    check("'Канал:' olib tashlandi", "Канал:" not in out, out)
    check("'Тип:' olib tashlandi", "Тип:" not in out, out)
    check("'Альбом: 3 фото' olib tashlandi", "Альбом: 3 фото" not in out, out)
    check("vaqt (время Ташкента) olib tashlandi", "время Ташкента" not in out, out)
    check("'Текст:' yorlig'i olib tashlandi", "Текст:" not in out, out)
    check("'Кнопка:' olib tashlandi", "Кнопка:" not in out, out)
    check("'Реакции:' olib tashlandi", "Реакции:" not in out, out)
    check("'Авто-удаление:' olib tashlandi", "Авто-удаление" not in out, out)


def test_sanitize_channel_content_safe_for_plain_text():
    print("== 13c. sanitize: oddiy matnga ta'siri yo'q ==")
    plain = ("Salom dunyo!\n"
             "Bugun postimda reaksiyalar haqida so'z boradi.\n"
             "Kanal: mening kanalim (oddiy matn qator).\n"
             "Tugma: matn ichida oddiy so'z.")
    check("oddiy matn O'ZGARMAYDI", sanitize_channel_content(plain) == plain,
          sanitize_channel_content(plain))
    check("bo'sh matn → bo'sh", sanitize_channel_content("") == "")
    check("None → bo'sh (crash yo'q)", sanitize_channel_content(None) == "")
    # Foydalanuvchi o'zi yozgan emoji-boshli ODATIY qatorlar (preview emas):
    custom = "⏰ Bugun soat 10 da ochiq\n🔘 Bu mening oddiy qatorim"
    out = sanitize_channel_content(custom)
    check("'⏰ Bugun soat 10 da ochiq' saqlandi (preview emas)",
          "Bugun soat 10 da ochiq" in out, out)
    check("'🔘 Bu mening oddiy qatorim' saqlandi (kolonsiz preview emas)",
          "Bu mening oddiy qatorim" in out, out)
    # Lekin preview uslubidagi qator (emoji + Yorliq:) — kesiladi:
    check("'👍 Reaksiyalar: yo'q' kabi preview qatori kesiladi",
          sanitize_channel_content("Salom\n👍 Reaksiyalar: yo'q") == "Salom")
    # Takrorlash vaqt qatorlari: faqat preview formati (vaqt HH:MM bilan) kesiladi
    check("preview: '🔁 Har kuni, soat 10:00 da' kesiladi",
          sanitize_channel_content("Salom\n🔁 Har kuni, soat 10:00 da") == "Salom")
    check("preview: '📅 Каждый Понедельник, в 10:00' kesiladi",
          sanitize_channel_content("Salom\n📅 Каждый Понедельник, в 10:00") == "Salom")
    check("preview: '📅 Har Dushanba, soat 10:00 da' kesiladi",
          sanitize_channel_content("Salom\n📅 Har Dushanba, soat 10:00 da") == "Salom")
    check("oddiy: '🔁 Har kuni mashg'ulot' (vaqtsiz) saqlanadi",
          "Har kuni mashg'ulot" in sanitize_channel_content("🔁 Har kuni mashg'ulot boshlanadi"))
    check("oddiy: '📅 Har kuni, mashg'ulot' (raqamsiz) saqlanadi",
          "mashg'ulot" in sanitize_channel_content("📅 Har kuni, mashg'ulot bor"))


# ----------------------------------------------------------------------
# 14. SCHEDULER: _execute_send — kanalda faqat asl matn
# ----------------------------------------------------------------------
class _ChannelBot:
    """Scheduler send chaqiruvlarini yozib boradi."""

    def __init__(self):
        self.calls = []
        self._mid = 0

    def _rec(self, kind, **kw):
        self.calls.append((kind, kw))
        self._mid += 1
        return SimpleNamespace(message_id=self._mid)

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        return self._rec("send_message", chat_id=chat_id, text=text,
                         reply_markup=reply_markup)

    async def send_photo(self, chat_id=None, photo=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_photo", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_video(self, chat_id=None, video=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_video", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_document(self, chat_id=None, document=None, caption=None,
                            reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_document", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_audio(self, chat_id=None, audio=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_audio", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_voice(self, chat_id=None, voice=None, caption=None,
                         reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_voice", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_animation(self, chat_id=None, animation=None, caption=None,
                             reply_markup=None, parse_mode=None, **kw):
        return self._rec("send_animation", chat_id=chat_id, caption=caption,
                         reply_markup=reply_markup)

    async def send_sticker(self, chat_id=None, sticker=None, **kw):
        return self._rec("send_sticker", chat_id=chat_id)

    async def send_media_group(self, chat_id=None, media=None, **kw):
        self.calls.append(("send_media_group", {"chat_id": chat_id,
                                                "media": list(media or [])}))
        self._mid += len(media or [])
        return [SimpleNamespace(message_id=i) for i in range(1, len(media or []) + 1)]

    def kinds(self):
        return [c[0] for c in self.calls]

    def of(self, kind):
        return [c[1] for c in self.calls if c[0] == kind]


def _make_post(post_type="text", content="Salom", file_id=None, btn_text=None,
               btn_url=None, enable_reactions=False, reaction_emojis=None,
               delete_after_hours=0):
    """get_due_posts shaklidagi 16 maydonli post tuple'i."""
    return (
        9001, 42, "-1001234567890", post_type, content, file_id,
        btn_text, btn_url, enable_reactions, datetime.now(),
        "none", None, None, None, delete_after_hours, reaction_emojis,
    )


def _scheduler_db_sink():
    """scheduler db.run_db fake'i: yuborish markerlari uchun yetarli javoblar."""
    import database as db_mod
    sink = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        sink.append((name, args, kwargs))
        if name == "is_premium":
            return True  # PRO — watermark qo'shilmaydi (test matni toza)
        if name == "bump_channel_post_count":
            return 1  # interval 3 da 1-postda reklama chiqmaydi
        if name == "get_setting":
            return args[1] if len(args) > 1 else ""  # brand_text bo'sh
        # mark_post_processing / mark_post_as_sent / ... → None (muvaffaqiyat)
        return None

    orig = db_mod.run_db
    db_mod.run_db = fake_run_db
    return sink, lambda: setattr(db_mod, "run_db", orig)


def test_execute_send_text_post_strips_preview():
    print("== 14. _execute_send: matnli post — kanalda faqat ASL matn ==")
    post = _make_post(post_type="text", content=UZ_PREVIEW)
    bot = _ChannelBot()
    sink, restore = _scheduler_db_sink()
    try:
        asyncio.run(_execute_send(bot, post))
    finally:
        restore()
    msgs = bot.of("send_message")
    check("kanalga 1 ta matn xabar chiqdi", len(msgs) == 1, str(bot.kinds()))
    sent_text = msgs[0]["text"] if msgs else ""
    check("asl matn KANALDA", "ASL POST MATNI — bu saqlanishi shart" in sent_text, sent_text)
    check("'Postni tasdiqlang:' kanalda YO'Q", "Postni tasdiqlang" not in sent_text, sent_text)
    check("'Kanal:' kanalda YO'Q", "Kanal:" not in sent_text, sent_text)
    check("'Turi:' kanalda YO'Q", "Turi:" not in sent_text, sent_text)
    check("'Tugma:' kanalda YO'Q", "Tugma:" not in sent_text, sent_text)
    check("'Reaksiyalar:' kanalda YO'Q", "Reaksiyalar:" not in sent_text, sent_text)
    check("'Avto-o'chirish:' kanalda YO'Q", "Avto-o'chirish" not in sent_text, sent_text)
    check("kanalga qo'shimcha xizmat xabar chiqmadi",
          bot.kinds() == ["send_message"], str(bot.kinds()))


def test_execute_send_photo_post_clean_caption():
    print("== 14b. _execute_send: rasmli post — caption toza ==")
    post = _make_post(post_type="photo", content=RU_PREVIEW + "\nAsl izoh",
                      file_id="photo123")
    bot = _ChannelBot()
    _, restore = _scheduler_db_sink()
    try:
        asyncio.run(_execute_send(bot, post))
    finally:
        restore()
    photos = bot.of("send_photo")
    check("1 ta rasm chiqdi", len(photos) == 1, str(bot.kinds()))
    cap = photos[0]["caption"] if photos else ""
    check("caption'da asl matn bor", "ASL POST MATNI — saqlanadi" in cap, cap)
    check("caption'da 'Подтвердите пост' YO'Q", "Подтвердите пост" not in cap, cap)
    check("caption'da 'Кнопка:' YO'Q", "Кнопка:" not in cap, cap)
    check("caption'da 'Реакции:' YO'Q", "Реакции:" not in cap, cap)


def test_execute_send_album_no_buttons_no_followup():
    print("== 14c. _execute_send: albom (tugmasiz) — toza albom, '🔗' YO'Q ==")
    items = [{"type": "photo", "file_id": "m1", "caption": ""},
             {"type": "photo", "file_id": "m2", "caption": ""}]
    post = _make_post(post_type="album", content=UZ_PREVIEW,
                      file_id=json.dumps(items))
    bot = _ChannelBot()
    _, restore = _scheduler_db_sink()
    try:
        asyncio.run(_execute_send(bot, post))
    finally:
        restore()
    groups = bot.of("send_media_group")
    check("1 ta media_group chiqdi", len(groups) == 1, str(bot.kinds()))
    media = groups[0]["media"] if groups else []
    check("albom 2 fayldan iborat", len(media) == 2, str(len(media)))
    check("caption faqat birinchi elementda",
          media and "ASL POST MATNI" in (media[0].caption or "")
          and (len(media) < 2 or media[1].caption is None),
          str([getattr(m, "caption", None) for m in media])[:120])
    check("caption'da preview YO'Q",
          media and "Postni tasdiqlang" not in (media[0].caption or ""),
          str(getattr(media[0], "caption", None) if media else None)[:120])
    check("tugmasiz albomda '🔗' xizmat xabari chiqmadi",
          "send_message" not in bot.kinds(), str(bot.kinds()))


def test_execute_send_album_legacy_button_keeps_followup():
    print("== 14d. _execute_send: eski albom + tugma — '🔗' followup saqlanadi ==")
    items = [{"type": "photo", "file_id": "m1", "caption": ""},
             {"type": "photo", "file_id": "m2", "caption": ""}]
    post = _make_post(post_type="album", content="Asl izoh",
                      file_id=json.dumps(items),
                      btn_text="Batafsil", btn_url="https://x.uz")
    bot = _ChannelBot()
    _, restore = _scheduler_db_sink()
    try:
        asyncio.run(_execute_send(bot, post))
    finally:
        restore()
    groups = bot.of("send_media_group")
    check("media_group chiqdi", len(groups) == 1, str(bot.kinds()))
    msgs = bot.of("send_message")
    check("eski albom uchun tugma follow-up xabari bor (URL yo'qolmasligi uchun)",
          len(msgs) == 1 and msgs[0]["reply_markup"] is not None,
          str([(k, m.get("text")) for k, m in bot.calls])[:150])
    check("media_group'ning O'ZIDA reply_markup YO'Q (Telegram qoidasi)",
          groups and not any("reply_markup" in kw or kw.get("reply_markup")
                             for _, kw in bot.calls if _ == "send_media_group"),
          str(bot.kinds()))
    # Tugma xabari ichida preview/matn YO'Q — faqat tugma belgisi
    check("follow-up matni ichki preview emas",
          msgs and "Postni tasdiqlang" not in (msgs[0]["text"] or ""),
          str(msgs)[:120])


def test_build_album_media_clean_caption_only_first():
    print("== 14e. _build_album_media: caption faqat 1-elementda, toza ==")
    items = [
        {"type": "photo", "file_id": "m1", "caption": ""},
        {"type": "video", "file_id": "m2", "caption": ""},
    ]
    media = _build_album_media(items, "Toza asl caption")
    check("2 ta media", len(media) == 2, str(len(media)))
    check("1-elt: caption bor", media[0].caption == "Toza asl caption",
          str(media[0].caption))
    check("2-elt: caption YO'Q (None)", media[1].caption is None,
          str(media[1].caption))


def main():
    test_warning_i18n_keys()
    test_is_multi_album_helpers()
    test_album_choice_keyboard()
    test_collector_shows_album_warning()
    test_collector_single_photo_keeps_button_prompt()
    test_btn_title_intercept_for_album()
    test_btn_title_skip_album_goes_to_reactions_warning()
    test_ask_reactions_step_album_warning()
    test_reactions_received_album_emoji_shows_warning()
    test_reactions_received_album_skip_proceeds_clean()
    test_proceed_after_reactions_album_clears_emojis()
    test_album_choice_first_photo_button_stage()
    test_album_choice_first_photo_reactions_stage()
    test_album_choice_full_album()
    test_album_choice_stale_press_no_crash()
    test_strip_unsupported_album_options()
    test_conversation_states_handle_album_choice()
    test_confirm_save_album_no_buttons_in_db()
    test_confirm_save_single_photo_keeps_buttons()
    test_sanitize_channel_content_uz()
    test_sanitize_channel_content_ru()
    test_sanitize_channel_content_safe_for_plain_text()
    test_execute_send_text_post_strips_preview()
    test_execute_send_photo_post_clean_caption()
    test_execute_send_album_no_buttons_no_followup()
    test_execute_send_album_legacy_button_keeps_followup()
    test_build_album_media_clean_caption_only_first()

    passed = sum(1 for ok, _, _ in CHECKS if ok)
    failed = [m for ok, m, _ in CHECKS if not ok]
    print(f"\nAlbum-warning/clean-channel testlari: {passed} passed, {len(failed)} failed")
    if failed:
        print("FAILED:")
        for m in failed:
            print("  -", m)
        sys.exit(1)
    print("HAMIYASI OK ✔")


if __name__ == "__main__":
    main()
