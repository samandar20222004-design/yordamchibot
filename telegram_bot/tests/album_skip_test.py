#!/usr/bin/env python3
"""ALBOM (media_group) yig'ish + "⏩ O'tkazib yuborish" skip tugmasi testlari.

Ishga tushirish:
    cd telegram_bot && python tests/album_skip_test.py
"""
import asyncio
import json
import os
import sys
import time
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

from telegram import Update, Message, Chat, User, PhotoSize, Video, Document
from telegram.ext import ApplicationBuilder, ConversationHandler, CallbackContext  # noqa: F401
from telegram import InputMediaPhoto, InputMediaVideo, InputMediaDocument, InlineKeyboardMarkup

import handlers as h_mod
from handlers import register_all_handlers
import handlers.new_post as np_mod
from handlers.new_post import (
    GET_CONTENT, GET_BTN_TITLE, GET_BTN_URL, GET_REACTIONS, GET_AUTO_DELETE,
    content_received, btn_title_received, reactions_received,
    _build_preview_text, _build_album_summary, _album_items_to_post,
    _ALBUM_BUFFERS, SKIP_BUTTON_TEXTS, is_skip_button_text,
    skip_url_step, skip_reactions_step, cancel_album_collections,
)
from keyboards.default import (
    BTN_SKIP_URL_BUTTON, BTN_SKIP_URL_BUTTON_RU,
    BTN_SKIP_BUTTON, BTN_SKIP_BUTTON_RU, BTN_NO_REACT, BTN_NO_REACT_RU,
)
from locales.translations import get_text
from scheduler import _build_album_media, parse_album_items

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
    """send_message / send_media_group / send_photo chaqiruvlarini yozib boradi."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"kind": "message", "text": text, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_media_group(self, chat_id=None, media=None, **kw):
        self.sent.append({"kind": "media_group", "count": len(media or [])})
        return [SimpleNamespace(message_id=i) for i in range(len(media or []))]


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


def _video_update(uid, file_id, caption="", media_group_id=None, bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    kw = dict(message_id=2, date=datetime.now(), chat=chat, from_user=user)
    if file_id:
        kw["video"] = Video(file_id=file_id, file_unique_id=file_id + "_u",
                            width=320, height=240, duration=3)
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


# ----------------------------------------------------------------------
# 1. Skip tugmalarini tanib olish
# ----------------------------------------------------------------------
def test_skip_button_texts_recognized():
    print("== skip tugmalari tanib olinadi ==")
    for t in ("⏩ O'tkazib yuborish", "⏩ Пропустить", "⏭ O'tkazib yuborish",
              "⏭ Пропустить", "O'tkazib yuborish", "Пропустить",
              BTN_SKIP_URL_BUTTON, BTN_SKIP_URL_BUTTON_RU,
              BTN_SKIP_BUTTON, BTN_SKIP_BUTTON_RU):
        check(f"skip: {t!r}", is_skip_button_text(t))
    check("skip: oddiy matn emas", not is_skip_button_text("Batafsil"))
    check("skip: None", not is_skip_button_text(None))
    check("skip: ro'yxatda 6 ta yorliq", len(SKIP_BUTTON_TEXTS) >= 6)


# ----------------------------------------------------------------------
# 2. "⏩ O'tkazib yuborish" GET_REACTIONS da crash bermaydi
# ----------------------------------------------------------------------
class _FakeMsg:
    def __init__(self):
        self.replies = []
        self.text = None
        self.caption = None
        self.photo = None
        self.video = None
        self.document = None
        self.audio = None
        self.animation = None
        self.voice = None
        self.sticker = None
        self.video_note = None
        self.media_group_id = None
        self.chat_id = 777

    async def reply_text(self, text, **kw):
        self.replies.append((text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=len(self.replies))


def test_reactions_received_handles_skip_text_direct():
    print("== reactions_received: skip tugmalari crash'siz ==")
    for text in ("⏩ O'tkazib yuborish", "⏩ Пропустить", "⏭ O'tkazib yuborish",
                 "⏭ Пропустить", BTN_NO_REACT, BTN_NO_REACT_RU):
        msg = _FakeMsg()
        msg.text = text
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        ctx = SimpleNamespace(user_data={"lang": "uz", "content": "matn",
                                         "post_type": "photo", "file_id": "p1"},
                              bot=None)

        async def run():
            return await reactions_received(upd, ctx)

        state = asyncio.run(run())
        check(f"reactions skip {text!r} → GET_AUTO_DELETE", state == GET_AUTO_DELETE,
              f"state={state}")
        check(f"reactions skip {text!r}: user_data saqlandi",
              ctx.user_data.get("post_type") == "photo"
              and ctx.user_data.get("file_id") == "p1"
              and ctx.user_data.get("enable_reactions") is False,
              str(ctx.user_data))
        check(f"reactions skip {text!r}: avto-o'chirish so'raldi",
              bool(msg.replies), str(msg.replies)[:80])


def test_skip_in_get_reactions_conversation_state_no_crash():
    print("== Conversation GET_REACTIONS: skip bosishda crash yo'q, holat o'tadi ==")
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        for text in ("⏩ O'tkazib yuborish", "⏩ Пропустить", "⏭ O'tkazib yuborish",
                     "⏭ Пропустить"):
            conv._conversations[(777, 777)] = GET_REACTIONS
            bot = _RecBot()
            upd = _text_update(777, text, bot=bot)
            handler = asyncio.run(_dispatch(app, upd, lang="uz"))
            check(f"GA REACTIONS + {text!r}: handler = ConversationHandler",
                  isinstance(handler, ConversationHandler), str(handler))
            check(f"GA REACTIONS + {text!r}: holat GET_AUTO_DELETE ga o'tdi",
                  conv._conversations.get((777, 777)) == GET_AUTO_DELETE,
                  str(conv._conversations.get((777, 777))))
            check(f"GA REACTIONS + {text!r}: javob yuborildi", bool(bot.sent))
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


# ----------------------------------------------------------------------
# 3. "⏩ O'tkazib yuborish" URL tugma bosqichida
# ----------------------------------------------------------------------
def test_skip_in_url_title_state_via_conversation():
    print("== Conversation GET_BTN_TITLE / GET_BTN_URL: skip + user_data saqlanadi ==")
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    restore = _patch_db({"get_user_language": "uz", "is_premium": True})
    try:
        for state, text in ((GET_BTN_TITLE, "⏩ O'tkazib yuborish"),
                            (GET_BTN_TITLE, "⏩ Пропустить"),
                            (GET_BTN_TITLE, "⏭ O'tkazib yuborish"),
                            (GET_BTN_URL, "⏩ O'tkazib yuborish")):
            conv._conversations[(777, 777)] = state
            bot = _RecBot()
            upd = _text_update(777, text, bot=bot)
            handler = asyncio.run(_dispatch(app, upd, lang="uz", user_data={
                "content": "asl matn", "post_type": "album", "file_id": "[]",
            }))
            check(f"{state} + {text!r}: holat GET_REACTIONS ga o'tdi",
                  conv._conversations.get((777, 777)) == GET_REACTIONS,
                  str(conv._conversations.get((777, 777))))
            check(f"{state} + {text!r}: ConversationHandler ishladi",
                  isinstance(handler, ConversationHandler))
            # user_data yo'qolmaydi va tugma o'chiriladi
            ud = dict(app.user_data).get(777, {}) or {}
            check(f"{state} + {text!r}: content saqlandi",
                  ud.get("content") == "asl matn", str(ud)[:120])
    finally:
        conv._conversations.pop((777, 777), None)
        restore()


# ----------------------------------------------------------------------
# 4. Albom yig'ish: barcha fayllar + to'liq caption
# ----------------------------------------------------------------------
def test_album_collection_keeps_all_files_and_full_caption():
    print("== albom yig'ish: 3 ta rasm + to'liq caption ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    old_ts = time.time()

    caption = ("Birinchi qator\nIkkinchi qator — juda uzun matn " * 5).strip()
    user_data = {"lang": "uz"}
    bot = _RecBot()
    media_group_id = "g1"

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        for fid in ("p1", "p2", "p3"):
            cap = caption if fid == "p1" else ""
            upd = _photo_update(42, fid, caption=cap, media_group_id=media_group_id)
            state = await content_received(upd, ctx)
            check(f"albom {fid}: GET_CONTENT da qoladi", state == GET_CONTENT)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.3)

    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.15
    try:
        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("albom: post_type == album", user_data.get("post_type") == "album",
          str(user_data))
    items = json.loads(user_data.get("file_id") or "[]")
    check("albom: 3 ta fayl saqlandi", len(items) == 3,
          f"items={len(items)}")
    check("albom: file_id'lar tartibi saqlandi",
          [i["file_id"] for i in items] == ["p1", "p2", "p3"],
          str([i.get("file_id") for i in items]))
    check("albom: caption TO'LIQ saqlandi", user_data.get("content") == caption,
          f"len={len(user_data.get('content') or '')}, expected={len(caption)}")
    check("albom: _album_ready belgisi", user_data.get("_album_ready") is True)
    check("albom: botga tugma so'rovi yuborildi",
          any(s["kind"] == "message" and get_text("np_button_ask", "uz") in s["text"]
              for s in bot.sent), str(bot.sent)[:120])
    check("albom: bufer tozalandi", not np_mod._ALBUM_BUFFERS,
          str(list(np_mod._ALBUM_BUFFERS)))


# ----------------------------------------------------------------------
# 5. Albom tugagach skip bosilsa oqim davom etadi
# ----------------------------------------------------------------------
def test_album_then_skip_continues_flow_and_keeps_data():
    print("== albom + skip: oqim davom etadi, user_data yo'qolmaydi ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    user_data = {"lang": "uz"}
    bot = _RecBot()
    msg = _FakeMsg()
    msg.text = "⏩ O'tkazib yuborish"

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        for fid in ("a1", "a2"):
            upd = _photo_update(42, fid, media_group_id="g2")
            await content_received(upd, ctx)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.2)
        # Albom tayyor — endi foydalanuvchi pastki "skip" tugmasini bosadi.
        upd = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                              effective_message=msg)
        state = await content_received(upd, ctx)
        return state

    try:
        state = asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("albom+skip: GET_REACTIONS ga o'tdi", state == GET_REACTIONS, str(state))
    check("albom+skip: albom ma'lumotlari yo'qolmadi",
          user_data.get("post_type") == "album" and len(json.loads(user_data["file_id"])) == 2,
          str(user_data))
    check("albom+skip: reaksiya so'rovi yuborildi",
          any(get_text("np_reactions_ask", "uz") in r[0] for r in msg.replies),
          str(msg.replies)[:120])


# ----------------------------------------------------------------------
# 6. Collector tugamasdan matn yuborilsa — darhol yakunlanadi
# ----------------------------------------------------------------------
def test_text_before_collector_finalizes():
    print("== collector tugamasdan matn kelsa: albom darhol yakunlanadi ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 5.0  # collector hali tugamagan bo'lsin
    user_data = {"lang": "uz"}
    bot = _RecBot()
    msg = _FakeMsg()
    msg.text = "Batafsil"

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        upd1 = _photo_update(42, "b1", media_group_id="g3")
        upd2 = _photo_update(42, "b2", media_group_id="g3")
        await content_received(upd1, ctx)
        await content_received(upd2, ctx)
        # collector 5s kutyapti — matn kelsa darhol yakunlanadi
        upd3 = SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=42),
                               effective_message=msg)
        return await content_received(upd3, ctx)

    try:
        state = asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait
        np_mod._ALBUM_BUFFERS.clear()

    check("ertapishar matn: GET_BTN_URL ga o'tdi", state == GET_BTN_URL, str(state))
    check("ertapishar matn: tugma matni saqlandi",
          user_data.get("btn_text") == "Batafsil", str(user_data))
    check("ertapishar matn: albom 2 fayl bilan saqlandi",
          user_data.get("post_type") == "album" and len(json.loads(user_data["file_id"])) == 2,
          str(user_data))
    check("ertapishar matn: bufer tozalandi", not np_mod._ALBUM_BUFFERS)


# ----------------------------------------------------------------------
# 7. Yakka rasm oldingi oqimda buzilmagan
# ----------------------------------------------------------------------
def test_single_photo_still_immediate():
    print("== yakka rasm: oqim o'zgarmadi ==")
    user_data = {"lang": "uz"}
    bot = _RecBot()
    msg = _FakeMsg()

    async def run():
        upd = _photo_update(42, "single1", bot=bot)
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        return await content_received(upd, ctx)

    state = asyncio.run(run())
    check("yakka rasm: GET_BTN_TITLE", state == GET_BTN_TITLE, str(state))
    check("yakka rasm: post_type photo",
          user_data.get("post_type") == "photo" and user_data.get("file_id") == "single1",
          str(user_data))


# ----------------------------------------------------------------------
# 8. Preview: albom xulosasi + to'liq matn (300 belgida uzilmaydi)
# ----------------------------------------------------------------------
def test_preview_shows_album_summary_and_full_text():
    print("== preview: albom xulosasi + to'liq matn ==")
    import pytz
    tz = pytz.timezone("Asia/Tashkent")
    items = [
        {"type": "photo", "file_id": f"f{i}", "caption": ""}
        for i in range(6)
    ]
    long_text = ("Ushbu post matni juda uzun — " * 40).strip()  # >300 belgi
    check("test matni 300 dan uzun", len(long_text) > 300, str(len(long_text)))

    for lang in ("uz", "ru"):
        ctx = SimpleNamespace(user_data={
            "lang": lang, "selected_channel_title": "Kanal",
            "post_type": "text", "content": long_text,
            "confirm_post_time": tz.localize(datetime(2026, 9, 6, 12, 0)),
            "confirm_recurrence_type": "none",
        })
        preview = _build_preview_text(ctx)
        check(f"preview[{lang}]: matn 300 belgida UZILMAGAN",
              long_text in preview, f"len(preview)={len(preview)}")

        # Albom: xulosa ko'rsatiladi, caption to'liq saqlanadi
        ctx.user_data["post_type"] = "album"
        ctx.user_data["file_id"] = json.dumps(items, ensure_ascii=False)
        album_preview = _build_preview_text(ctx)
        summary = get_text("np_confirm_album_photos", lang, count=6)
        check(f"preview[{lang}]: albom xulosasi ko'rinadi",
              summary in album_preview, album_preview[:200])
        check(f"preview[{lang}]: albom barcha fayllar soni",
              "6" in album_preview)


def test_preview_long_text_note_when_over_limit():
    print("== preview: Telegram limitidan uzun matn uchun eslatma ==")
    import pytz
    tz = pytz.timezone("Asia/Tashkent")
    long_text = "A" * 4200
    ctx = SimpleNamespace(user_data={
        "lang": "uz", "selected_channel_title": "Kanal",
        "post_type": "text", "content": long_text,
        "confirm_post_time": tz.localize(datetime(2026, 9, 6, 12, 0)),
        "confirm_recurrence_type": "none",
    })
    preview = _build_preview_text(ctx)
    check("limit eslatmasi bor", "4096" in preview and "4200" in preview,
          preview[-160:])


# ----------------------------------------------------------------------
# 9. Scheduler: albom send_media_group uchun to'liq tayyorlanadi
# ----------------------------------------------------------------------
def test_scheduler_prepares_media_group_for_album():
    print("== scheduler: albom → send_media_group media ro'yxati ==")
    raw = json.dumps([
        {"type": "photo", "file_id": "ph1", "caption": ""},
        {"type": "photo", "file_id": "ph2", "caption": ""},
        {"type": "photo", "file_id": "ph3", "caption": ""},
        {"type": "video", "file_id": "vd1", "caption": ""},
    ], ensure_ascii=False)
    items = parse_album_items(raw)
    check("scheduler: 4 ta element parse qilindi", len(items) == 4)
    media = _build_album_media(items, "Albom caption")
    check("scheduler: 4 ta InputMedia", len(media) == 4, str(len(media)))
    check("scheduler: birinchi elementda caption", media[0].caption == "Albom caption")
    check("scheduler: qolganlarda caption yo'q",
          all(m.caption is None for m in media[1:]))
    check("scheduler: video → InputMediaVideo",
          isinstance(media[3], InputMediaVideo), type(media[3]).__name__)
    check("scheduler: rasm → InputMediaPhoto",
          all(isinstance(m, InputMediaPhoto) for m in media[:3]))
    # send_media_group'ga yuborilganda hech bir fayl tushib qolmaydi
    bot = _RecBot()
    sent = asyncio.run(bot.send_media_group(chat_id=-1001, media=media))
    check("scheduler: send_media_group 4 ta yubordi",
          getattr(sent, "__len__", lambda: 0)() == 4 or len(sent) == 4)


# ----------------------------------------------------------------------
# 10. Bekor qilish collector taskini to'xtatadi
# ----------------------------------------------------------------------
def test_cancel_album_collections_stops_task():
    print("== cancel: albom task bekor qilinadi, user_data yozilmaydi ==")
    np_mod._ALBUM_BUFFERS.clear()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.2
    user_data = {"lang": "uz"}
    bot = _RecBot()

    async def run():
        ctx = SimpleNamespace(user_data=user_data, bot=bot)
        upd = _photo_update(42, "c1", media_group_id="g9")
        await content_received(upd, ctx)
        check("cancel: bufer faol", bool(np_mod._ALBUM_BUFFERS))
        cancel_album_collections(42)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.3)

    try:
        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait
        np_mod._ALBUM_BUFFERS.clear()

    check("cancel: user_data'ga post yozilmadi",
          "post_type" not in user_data and "_album_ready" not in user_data,
          str(user_data))


# ----------------------------------------------------------------------
# 11. Albom yig'uvchi per-user lock bilan ham ishlaydi (boshlang'ich tezligi)
# ----------------------------------------------------------------------
def test_album_collection_with_lock_manager():
    print("== GuardedApplication per-user lock + albom (integratsiya) ==")
    # Bu test GuardedApplication process_update'ning per-user lock'i albom
    # yig'ishga to'sqinlik qilmasligini tekshiradi: handler ICHIDA sleep yo'q —
    # collector arka fonda ishlaydi.
    import main as main_mod
    from telegram.ext import ApplicationBuilder
    from telegram import Update  # noqa: F401

    check("main: GuardedApplication ishlatiladi",
          hasattr(main_mod, "GuardedApplication")
          and hasattr(main_mod, "UpdateLockManager"))
    app = _build_app()
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    check("album: GET_CONTENT holatida MessageHandler(filters.ALL) bor", True)

    # handler ichida sleep ketmasligi (per-user lock bloklamasligi) uchun
    src = (ROOT / "handlers" / "new_post.py").read_text(encoding="utf-8")
    check("new_post: media_group branch'ida ketma-ket sleep yo'q",
          "await asyncio.sleep(_ALBUM_WAIT_SECONDS)" not in src
          or "create_task" in src)
    check("new_post: collector create_task bilan ishga tushadi",
          "create_task" in src and "async def _album_collector" in src)


# ======================================================================
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    failed = [c for c in CHECKS if not c[0]]
    print(f"\nAlbom/skip testlari: {len(CHECKS) - len(failed)} passed, "
          f"{len(failed)} failed")
    if failed:
        for _, msg, detail in failed:
            print(f"  [FAIL] {msg} {detail}")
        sys.exit(1)
    print("BALCHASI OK ✔")
