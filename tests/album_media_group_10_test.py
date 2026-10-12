#!/usr/bin/env python3
"""🖼 10 TA MEDIA (ALBOM) = BITTA POST — konsolidatsiya testlari.

Qamrab olinadigan talablar:
  1. Telegram media-guruhi (album) 10 tagacha rasm/video bilan yuborilsa —
     barcha fayllar BITTA post bo'ladi (alohida postlar YO'Q, kvota birligi
     1 ta, DB'da 1 qator).
  2. Ketma-ket (har biri alohida xabar bo'lib) qisqa vaqt ichida yuborilgan
     fayllar ham BITTA albomga birlashtiriladi.
  3. Caption butun guruhga bir xil bog'lanadi (qaysi faylda kelganidan qat'i
     nazar) va hech qanday fayl yo'qolmaydi/takrorlanmaydi.
  4. Foydalanuvchi albom qabul qilingani haqida ANIQ tasdiq oladi
     ("N ta media — bitta post") — takroriy/tarqoq so'rovlar (prompt) yo'q.
  5. Albom 10 ta faylga to'lganda qo'shimcha fayl JIMGINA yo'qolmaydi —
     aniq ogohlantirish chiqadi va joriy albom buzilmaydi.
  6. ✍️ ODDIY POST (AI'siz) oqimida ham 10 rasmli albom bitta post bo'ladi
     (avval har fayl uchun alohida preview chiqib, postda oxirgi rasm qolardi).
  7. Scheduler albomni BITTA ``send_media_group`` chaqiruvi bilan yuboradi
     (caption faqat birinchi elementda).

Ishga tushirish:
    cd telegram_bot && python ../tests/album_media_group_10_test.py
"""
import asyncio
import json
import os
import sys
import warnings
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
os.environ.setdefault("CARD_NUMBER", "8600060950825589")
os.environ.setdefault("CARD_HOLDER", "Test S.")
os.environ["SENT_JOURNAL_PATH"] = "off"  # sent-journal fayl yozmasin

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

from telegram import (  # noqa: E402
    Update, Message, Chat, User, PhotoSize, Video,
)
from telegram.ext import ApplicationBuilder, ConversationHandler  # noqa: E402

import handlers as h_mod  # noqa: E402
from handlers import register_all_handlers  # noqa: E402
import handlers.new_post as np_mod  # noqa: E402
from handlers.new_post import (  # noqa: E402
    GET_CONTENT, GET_BTN_TITLE, content_received, confirm_post_callback,
    _ALBUM_MAX_ITEMS, _ALBUM_BUFFERS, _bind_album_caption,
    _album_items_to_post, _build_preview_text, _album_received_text,
    _album_items_count_of, reset_callback_throttle,
)
from locales.translations import (  # noqa: E402
    get_text, has_key, translation_parity_report, translation_format_report,
    format_args,
)
import scheduler as sched  # noqa: E402
from scheduler import parse_album_items, _build_album_media, _execute_send  # noqa: E402
import handlers.manual_post as MP  # noqa: E402
from handlers.manual_post import (  # noqa: E402
    MANUAL_PREVIEW, manual_content_received,
    UD_CONTENT, UD_POST_TYPE, UD_FILE_ID, UD_MEDIA_GROUP, UD_ALBUM_ITEMS,
)

CHECKS = []


def check(msg, cond, detail=""):
    CHECKS.append((bool(cond), msg, detail))
    if not cond:
        print(f"  [FAIL] {msg}: {detail}")
    else:
        print(f"  [OK] {msg}")


# ======================================================================
# Test infratuzilmasi
# ======================================================================
class _RecBot:
    """send_message / send_media_group chaqiruvlarini yozib boradi."""
    id = 1
    username = "TestBot"
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, reply_markup=None,
                           parse_mode=None, **kw):
        self.sent.append({"kind": "message", "text": text,
                          "reply_markup": reply_markup})
        return SimpleNamespace(message_id=len(self.sent))

    async def send_media_group(self, chat_id=None, media=None, **kw):
        self.sent.append({"kind": "media_group", "count": len(media or [])})
        return [SimpleNamespace(message_id=i) for i in range(len(media or []))]

    def texts(self):
        return [s.get("text") or "" for s in self.sent]

    def count(self, needle):
        return sum(1 for t in self.texts() if needle in t)


class _FakeMsg:
    """reply_text / reply_photo ... ni yozib boruvchi minimal xabar."""

    def __init__(self, user_id=42, chat_id=42):
        self.replies = []
        self.caption = None
        self.text = None
        self.photo = None
        self.video = None
        self.document = None
        self.audio = None
        self.animation = None
        self.voice = None
        self.sticker = None
        self.video_note = None
        self.media_group_id = None
        self.chat_id = chat_id
        self.from_user = SimpleNamespace(id=user_id)

    async def reply_text(self, text, **kw):
        self.replies.append({"kind": "text", "text": text,
                             "reply_markup": kw.get("reply_markup")})
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_photo(self, photo=None, **kw):
        self.replies.append({"kind": "photo", "caption": kw.get("caption", ""),
                             "reply_markup": kw.get("reply_markup")})
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_video(self, video=None, **kw):
        self.replies.append({"kind": "video", "caption": kw.get("caption", ""),
                             "reply_markup": kw.get("reply_markup")})
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_document(self, document=None, **kw):
        self.replies.append({"kind": "document", "caption": kw.get("caption", ""),
                             "reply_markup": kw.get("reply_markup")})
        return SimpleNamespace(message_id=len(self.replies))

    async def reply_animation(self, animation=None, **kw):
        self.replies.append({"kind": "animation", "caption": kw.get("caption", ""),
                             "reply_markup": kw.get("reply_markup")})
        return SimpleNamespace(message_id=len(self.replies))

    def texts(self):
        return [r.get("text") or "" for r in self.replies]


def _photo_update(uid, file_id, caption="", media_group_id=None, message_id=1,
                  bot=None):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    kw = dict(message_id=message_id, date=datetime.now(), chat=chat, from_user=user)
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


def _video_update(uid, file_id, caption="", media_group_id=None, message_id=2):
    user = User(id=uid, first_name="Ali", is_bot=False)
    chat = Chat(id=uid, type="private")
    kw = dict(message_id=message_id, date=datetime.now(), chat=chat, from_user=user)
    if file_id:
        kw["video"] = Video(file_id=file_id, file_unique_id=file_id + "_u",
                            width=320, height=240, duration=3)
    if caption:
        kw["caption"] = caption
    if media_group_id:
        kw["media_group_id"] = media_group_id
    upd = Update(update_id=1, message=Message(**kw))
    return upd


def _ctx(user_data, bot=None, user_id=42):
    return SimpleNamespace(user_data=user_data, bot=bot,
                           _user_id=user_id, chat_id=user_id)


def _reset_album_state():
    _ALBUM_BUFFERS.clear()
    np_mod._ALBUM_LIMIT_NOTICES.clear()


# ======================================================================
# 1. i18n: tasdiq va chegara matnlari uchala tilda
# ======================================================================
def test_i18n_album_ack_keys():
    print("== 1. Albom tasdig'i (np_album_received) uchala tilda ==")
    for key in ("np_album_received", "np_album_limit_notice"):
        for lang in ("uz", "ru", "en"):
            check(f"{lang}: {key} mavjud", has_key(key, lang))

    report = translation_parity_report()
    check("i18n paritet buzilmagan (uz↔ru)", report["in_sync"], str(report))
    check("EN overlay qamrovi to'liq", not report["en_missing"],
          str(report["en_missing"][:5]))

    fmt = translation_format_report()
    check("format argumentlari paritetda", fmt["in_sync"], str(fmt)[:200])

    for lang in ("uz", "ru", "en"):
        args = format_args(get_text("np_album_received", lang))
        check(f"{lang}: np_album_received'da {{{{count}}}} bor", "count" in args,
              str(args))
        args2 = format_args(get_text("np_album_limit_notice", lang))
        check(f"{lang}: np_album_limit_notice'da {{{{limit}}}} bor",
              "limit" in args2, str(args2))
        text = get_text("np_album_received", lang, count=10)
        check(f"{lang}: tasdiqda fayllar soni ko'rinadi", "10" in text, text)

    check("_album_received_text: tasdiq + cheklov bitta xabarda",
          get_text("np_album_received", "uz", count=3) in
          _album_received_text(3, "uz")
          and get_text("np_album_warning", "uz") in _album_received_text(3, "uz"))


# ======================================================================
# 2. 10 ta faylli media-guruh = BITTA post
# ======================================================================
def test_ten_item_group_single_post():
    print("== 2. 10 rasmli media-guruh → bitta albom posti ==")
    _reset_album_state()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    user_data = {"lang": "uz"}
    bot = _RecBot()
    ctx = _ctx(user_data, bot=bot)
    caption = "Bugungi yangiliklar — 10 ta rasm bir postda"
    files = [f"p{i}" for i in range(1, _ALBUM_MAX_ITEMS + 1)]

    async def run():
        for i, fid in enumerate(files):
            upd = _photo_update(42, fid, caption=(caption if i == 0 else ""),
                                media_group_id="g10", message_id=100 + i, bot=bot)
            state = await np_mod.content_received(upd, ctx)
            check(f"{i + 1}-fayl: GET_CONTENT da qoladi (alohida post YO'Q)",
                  state == GET_CONTENT, str(state))
        buffers = [b for b in _ALBUM_BUFFERS.values()]
        check("buferda 10 ta fayl yig'ildi",
              buffers and len(buffers[0]["items"]) == _ALBUM_MAX_ITEMS,
              str([len(b["items"]) for b in buffers]))
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)

    try:
        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("post_type == album", user_data.get("post_type") == "album",
          str(user_data)[:160])
    items = json.loads(user_data.get("file_id") or "[]")
    check("saqlangan fayllar soni 10", len(items) == 10, str(len(items)))
    check("fayllar tartibi saqlandi",
          [i["file_id"] for i in items] == files,
          str([i.get("file_id") for i in items]))
    check("_album_count == 10", user_data.get("_album_count") == 10,
          str(user_data.get("_album_count")))
    check("_album_ready belgisi o'rnatildi", user_data.get("_album_ready") is True)
    check("caption TO'LIQ saqlandi", user_data.get("content") == caption,
          str(user_data.get("content"))[:60])
    check("caption birinchi elementga bog'landi (qolganlarda bo'sh)",
          items[0]["caption"] == caption
          and all(i["caption"] == "" for i in items[1:]),
          str([i["caption"] for i in items])[:80])
    check("bufer tozalandi (split state yo'q)", not _ALBUM_BUFFERS,
          str(list(_ALBUM_BUFFERS)))

    # Tasdiq xabari: nechta fayl + Telegram cheklovi (bitta xabar)
    ack = get_text("np_album_received", "uz", count=10)
    check("tasdiq xabari yuborildi (10 ta media)",
          any(ack.split("{")[0] in t and "10" in t for t in bot.texts()),
          str(bot.texts())[:200])
    check("tasdiqda Telegram cheklovi ham bor",
          bot.count(get_text("np_album_warning", "uz")) == 1,
          str(bot.texts())[:200])
    check("takroriy tugma so'rovi (np_button_ask) chiqMADI",
          bot.count(get_text("np_button_ask", "uz")) == 0,
          str(bot.texts())[:160])
    warn = [s for s in bot.sent
            if get_text("np_album_warning", "uz") in (s.get("text") or "")]
    check("tanlov klaviaturasi (2 tugma) tasdiq xabarida",
          warn and warn[0]["reply_markup"] is not None
          and len(warn[0]["reply_markup"].inline_keyboard) == 2,
          str(warn)[:160])
    check("faqat BITTA albom xabari yuborildi",
          sum(1 for t in bot.texts()
              if get_text("np_album_received", "uz").split("{")[0] in t) == 1,
          str(bot.texts())[:200])


# ======================================================================
# 3. Ketma-ket yuborilgan fayllar ham bitta albomga birlashadi
# ======================================================================
def test_sequential_files_merge_into_one_album():
    print("== 3. Ketma-ket (media_group_id'siz) fayllar → bitta post ==")
    _reset_album_state()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    user_data = {"lang": "uz"}
    bot = _RecBot()
    ctx = _ctx(user_data, bot=bot, user_id=777)

    async def run():
        states = []
        for i, fid in enumerate(["s1", "s2", "s3", "s4"]):
            upd = _photo_update(777, fid, caption=("Seriya izohi" if i == 0 else ""),
                                message_id=200 + i, bot=bot)
            states.append(await np_mod.content_received(upd, ctx))
        check("1-fayl: yakka rasm uchun odatdagi so'rov (GET_BTN_TITLE)",
              states[0] == GET_BTN_TITLE, str(states))
        check("2+ fayllar: GET_CONTENT (albom yig'ilmoqda)",
              all(s == GET_CONTENT for s in states[1:]), str(states))
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)

    try:
        asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("ketma-ket fayllar → post_type album",
          user_data.get("post_type") == "album", str(user_data)[:160])
    items = json.loads(user_data.get("file_id") or "[]")
    check("barcha 4 fayl saqlandi", len(items) == 4, str(len(items)))
    check("birinchi fayl ham yo'qolmadi", items[0]["file_id"] == "s1",
          str([i.get("file_id") for i in items]))
    check("caption butun guruhga bog'landi",
          user_data.get("content") == "Seriya izohi"
          and items[0]["caption"] == "Seriya izohi",
          str(user_data.get("content"))[:60])
    check("bitta tasdiq xabari (4 ta media)",
          sum(1 for t in bot.texts()
              if get_text("np_album_received", "uz").split("{")[0] in t) == 1,
          str(bot.texts())[:200])
    check("4 ta fayl uchun bitta albom so'rovi (takroriy prompt yo'q)",
          bot.count(get_text("np_album_warning", "uz")) == 1,
          str(bot.texts())[:200])
    check("bufer tozalandi", not _ALBUM_BUFFERS)


# ======================================================================
# 4. Caption istalgan faylda kelsa ham butun albomga bog'lanadi
# ======================================================================
def test_caption_binding_from_any_item():
    print("== 4. Caption istalgan faylda kelsa ham guruhga bir xil bog'lanadi ==")
    items = [
        {"type": "photo", "file_id": "m1", "caption": ""},
        {"type": "video", "file_id": "m2", "caption": "  Kechagi hisobot  "},
        {"type": "photo", "file_id": "m3", "caption": ""},
    ]
    caption = _bind_album_caption(items)
    check("caption topildi va tozalandi", caption == "Kechagi hisobot", caption)
    check("caption birinchi elementga bog'landi",
          items[0]["caption"] == "Kechagi hisobot", str(items[0]))
    check("qolgan elementlarda caption yo'q",
          all(i["caption"] == "" for i in items[1:]), str(items))

    post = _album_items_to_post(
        [{"type": "photo", "file_id": "x1", "caption": ""},
         {"type": "photo", "file_id": "x2", "caption": "Ikkala fayl uchun izoh"}])
    check("post: content = yagona caption", post["content"] == "Ikkala fayl uchun izoh",
          post["content"])
    stored = json.loads(post["file_id"])
    check("post: file_id'da 2 element va yagona caption",
          len(stored) == 2 and stored[0]["caption"] == "Ikkala fayl uchun izoh"
          and stored[1]["caption"] == "", str(stored))

    post1 = _album_items_to_post([{"type": "photo", "file_id": "one",
                                   "caption": "Bitta izoh"}])
    check("bitta fayl → yakka media (albom emas)",
          post1["post_type"] == "photo" and post1["file_id"] == "one"
          and post1["content"] == "Bitta izoh", str(post1))
    check("_album_items_count_of: 2 va 0",
          _album_items_count_of(json.dumps(stored)) == 2
          and _album_items_count_of("not-json") == 0)


# ======================================================================
# 5. 11-fayl: ogohlantirish + joriy albom buzilmaydi
# ======================================================================
def test_eleventh_file_notice_and_album_kept():
    print("== 5. 11-fayl → aniq ogohlantirish, albom o'zgarmaydi ==")
    _reset_album_state()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    user_data = {"lang": "uz"}
    bot = _RecBot()
    ctx = _ctx(user_data, bot=bot, user_id=888)
    files = [f"e{i}" for i in range(_ALBUM_MAX_ITEMS)]

    async def run():
        for i, fid in enumerate(files):
            await np_mod.content_received(
                _photo_update(888, fid, caption=("Chegara izohi" if i == 0 else ""),
                              media_group_id="gfull", message_id=300 + i, bot=bot), ctx)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)
        before = user_data.get("file_id")
        # 11-fayl (bir xil guruh, oyna ichida)
        await np_mod.content_received(
            _photo_update(888, "e10", media_group_id="gfull", message_id=399,
                          bot=bot), ctx)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)
        return before

    try:
        before = asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("chegara ogohlantirishi yuborildi",
          bot.count(get_text("np_album_limit_notice", "uz", limit=10)) == 1,
          str(bot.texts())[:200])
    check("albom baribir 10 fayl", len(json.loads(user_data["file_id"])) == 10)
    check("albom tarkibi O'ZGARMADI (11-fayl qo'shilmadi)",
          user_data.get("file_id") == before)
    check("11-fayl yangi post ochmadi (post_type album)",
          user_data.get("post_type") == "album", str(user_data.get("post_type")))


# ======================================================================
# 6. Saqlash: 10 faylli albom → DB'da BITTA qator (1 kvota birligi)
# ======================================================================
def test_confirm_saves_single_row_for_ten_files():
    print("== 6. Tasdiqlash: 10 fayl → 1 ta add_post (1 kvota birligi) ==")
    reset_callback_throttle(4321)
    calls = []

    def fake_add_post(**kwargs):
        calls.append(kwargs)
        return 999

    user_data = {
        "lang": "uz",
        "post_type": "album",
        "file_id": json.dumps([{"type": "photo", "file_id": f"q{i}",
                                "caption": ("Katta albom izohi" if i == 0 else "")}
                               for i in range(_ALBUM_MAX_ITEMS)]),
        "content": "Katta albom izohi",
        "_album_count": _ALBUM_MAX_ITEMS,
        "_album_ready": True,
        "selected_channel_id": "-1001234567890",
        "selected_channel_title": "Mening Kanalim",
        "confirm_post_time": datetime.now(),
        "confirm_recurrence_type": "none",
        "confirm_recurrence_day": None,
        "confirm_recurrence_time_str": None,
        "confirm_end_date": None,
        "btn_text": "Batafsil",          # albomda ruxsat etilmaydi
        "btn_url": "https://x.uz",
        "enable_reactions": True,        # albomda ruxsat etilmaydi
        "reaction_emojis": ["👍"],
        "delete_after_hours": 0,
    }
    msg = _FakeMsg(user_id=4321, chat_id=4321)

    class _Q:
        data = "confirm_post:ok"

        def __init__(self):
            self.message = msg
            self.from_user = SimpleNamespace(id=4321)

        async def answer(self, *a, **k):
            return True

        async def edit_message_reply_markup(self, *a, **k):
            return True

    upd = SimpleNamespace(callback_query=_Q(), effective_user=SimpleNamespace(id=4321),
                          message=msg)
    ctx = SimpleNamespace(user_data=user_data, bot=None)

    async def run():
        import database as db_mod

        async def fake_run_db(fn, *args, **kwargs):
            name = getattr(fn, "__name__", "")
            if name == "get_user_channels":
                return [("-1001234567890", "Mening Kanalim")]
            if name == "add_post":
                return fake_add_post(**kwargs)
            if name == "is_premium":
                return True
            if name == "get_ad_settings":
                return {}
            if name == "get_setting":
                return ""
            return None

        orig = db_mod.run_db
        db_mod.run_db = fake_run_db
        try:
            return await confirm_post_callback(upd, ctx)
        finally:
            db_mod.run_db = orig

    state = asyncio.run(run())
    check("suhbat yakunlandi (END)",
          state == h_mod.ConversationHandler.END, str(state))
    check("DB'ga AYNAN bitta post yozildi (10 fayl = 1 kvota birligi)",
          len(calls) == 1, str(len(calls)))
    row = calls[0] if calls else {}
    check("post_type = album", row.get("post_type") == "album", str(row.get("post_type")))
    check("file_id: 10 fayl JSON sifatida",
          isinstance(row.get("file_id"), str)
          and len(json.loads(row["file_id"])) == _ALBUM_MAX_ITEMS,
          str(row.get("file_id"))[:80])
    check("albom postida tugma YO'Q", row.get("btn_text") is None
          and row.get("btn_url") is None, str(row.get("btn_text")))
    check("albom postida reaksiya YO'Q",
          row.get("enable_reactions") is False
          and row.get("reaction_emojis") == [], str(row.get("enable_reactions")))
    check("caption to'liq saqlandi", row.get("content") == "Katta albom izohi",
          str(row.get("content"))[:60])


# ======================================================================
# 7. Scheduler: bitta send_media_group, caption faqat birinchi elementda
# ======================================================================
def test_scheduler_sends_one_media_group():
    print("== 7. Scheduler: 10 fayl → BITTA send_media_group ==")
    items = [{"type": "photo" if i % 2 == 0 else "video",
              "file_id": f"d{i}", "caption": ""} for i in range(_ALBUM_MAX_ITEMS)]
    raw = json.dumps(items, ensure_ascii=False)
    parsed = parse_album_items(raw)
    check("parse_album_items: 10 element", len(parsed) == 10, str(len(parsed)))
    media = _build_album_media(parsed, "Umumiy caption")
    check("10 ta InputMedia", len(media) == 10, str(len(media)))
    check("caption faqat birinchi elementda",
          media[0].caption == "Umumiy caption"
          and all(m.caption is None for m in media[1:]),
          str([m.caption for m in media])[:80])

    calls = {}

    def fake_add_post(**kwargs):
        calls.update(kwargs)
        return 55

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "get_post_delivery_options":
            return None
        if name == "get_setting":
            return ""
        if name == "is_premium":
            return True
        if name == "bump_channel_post_count":
            return 1
        if name == "add_post":
            return fake_add_post(**kwargs)
        return None

    bot = MagicMock()
    bot.send_media_group = AsyncMock(return_value=[SimpleNamespace(message_id=7)])
    bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=8))
    bot.pin_chat_message = AsyncMock(return_value=True)

    post = (1, 4321, "-100123", "album", "Umumiy caption", raw, None, None,
            False, None, "none", None, None, None, 0, None)

    async def run():
        import database as db_mod
        with patch.object(db_mod, "run_db", side_effect=fake_run_db), \
             patch.object(sched, "is_sent_but_unpersisted", return_value=False), \
             patch.object(sched, "resolve_channel_ad", AsyncMock(return_value={})), \
             patch.object(sched, "apply_post_watermark", AsyncMock(return_value="Umumiy caption")), \
             patch.object(sched, "_persist_sent_marker", AsyncMock()):
            await _execute_send(bot, post)

    asyncio.run(run())
    check("send_media_group BIR MARTA chaqirildi",
          bot.send_media_group.await_count == 1, str(bot.send_media_group.await_count))
    sent_media = bot.send_media_group.await_args.kwargs["media"]
    check("guruhda 10 ta fayl (hech biri tushib qolmadi)",
          len(sent_media) == 10, str(len(sent_media)))
    check("kanalga faqat bitta xizmat xabari chiqmadi (tugmasiz albom)",
          bot.send_message.await_count == 0, str(bot.send_message.await_count))


# ======================================================================
# 8. Preview: albom xulosasida fayllar soni ko'rinadi
# ======================================================================
def test_preview_shows_ten_files_summary():
    print("== 8. Preview: '10 ta fayl' xulosasi ==")
    items = [{"type": "photo", "file_id": f"v{i}", "caption": ""}
             for i in range(_ALBUM_MAX_ITEMS)]
    for lang in ("uz", "ru", "en"):
        ctx = SimpleNamespace(user_data={
            "lang": lang, "selected_channel_title": "Kanal",
            "post_type": "album", "file_id": json.dumps(items),
            "content": "", "confirm_post_time": None,
            "confirm_recurrence_type": "none",
        })
        preview = _build_preview_text(ctx)
        check(f"{lang}: preview'da '10' bor", "10" in preview, preview[:160])
        check(f"{lang}: albom xulosasi lokalizatsiya qilingan",
              get_text("np_confirm_album_photos", lang, count=10) in preview,
              preview[:160])


# ======================================================================
# 9. ✍️ ODDIY POST (AI'siz): 10 rasmli albom = bitta post, bitta preview
# ======================================================================
def test_manual_album_ten_photos_single_post():
    print("== 9. Oddiy post: 10 rasm → bitta album posti, preview SPAM yo'q ==")
    MP._MANUAL_ALBUM_TASKS.clear()
    old_wait = MP._MANUAL_ALBUM_WAIT_SECONDS
    MP._MANUAL_ALBUM_WAIT_SECONDS = 0.1
    bot = _RecBot()
    ctx = _ctx({"lang": "uz"}, bot=bot, user_id=555)
    msg = _FakeMsg(user_id=555, chat_id=555)
    caption = "10 rasmli albom izohi"
    files = [f"a{i}" for i in range(_ALBUM_MAX_ITEMS)]
    preview_counts = []

    async def run():
        for i, fid in enumerate(files):
            m = _FakeMsg(user_id=555, chat_id=555)
            m.photo = [SimpleNamespace(file_id=fid)]
            m.media_group_id = "mg1"
            m.caption = caption if i == 0 else ""
            upd = SimpleNamespace(message=m, effective_user=SimpleNamespace(id=555),
                                  effective_message=m)
            state = await manual_content_received(upd, ctx)
            check(f"{i + 1}-rasm: holat MANUAL_PREVIEW", state == MANUAL_PREVIEW,
                  str(state))
            preview_counts.append(len(m.replies))
        check("oraliq fayllar uchun preview SPAM qilinmadi (faqat 1-xabar)",
              preview_counts == [1, 0, 0, 0, 0, 0, 0, 0, 0, 0], str(preview_counts))
        await asyncio.sleep(MP._MANUAL_ALBUM_WAIT_SECONDS + 0.4)

    try:
        asyncio.run(run())
    finally:
        MP._MANUAL_ALBUM_WAIT_SECONDS = old_wait

    ud = ctx.user_data
    check("post_type == album", ud.get(UD_POST_TYPE) == "album", str(ud)[:160])
    stored = json.loads(ud.get(UD_FILE_ID) or "[]")
    check("10 ta fayl saqlandi (oxirgisi emas — HAMMASI)",
          len(stored) == 10 and [i["file_id"] for i in stored] == files,
          str([i.get("file_id") for i in stored]))
    check("albom belgisi (tugma/reaksiya cheklovi)", ud.get(UD_MEDIA_GROUP) is True)
    check("caption butun albomga bog'landi", ud.get(UD_CONTENT) == caption,
          str(ud.get(UD_CONTENT))[:60])
    check("yakuniy tasdiq xabari yuborildi (10 ta media)",
          bot.count(get_text("np_album_received", "uz").split("{")[0]) == 1
          and "10" in "".join(bot.texts()), str(bot.texts())[:200])
    check("yakuniy xabarda panel (inline tugmalar) bor",
          bool(bot.sent and bot.sent[0]["reply_markup"] is not None), "panel yo'q")

    # 🚀 Saqlash: DB'ga BITTA qator (kvota birligi)
    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "add_post":
            calls.append(kwargs)
            return 777
        if name == "get_user_channels":
            return [("-1001", "Kanal A")]
        return None

    async def run_save():
        import database as db_mod
        with patch.object(db_mod, "run_db", side_effect=fake_run_db), \
             patch.object(MP, "manual_channel_guard", AsyncMock(return_value=True)):
            return await MP._publish(msg, ctx, 555, "-1001", "Kanal A", "uz")

    asyncio.run(run_save())
    check("oddiy post: DB'ga AYNAN bitta yozuv (10 rasm = 1 post)",
          len(calls) == 1, str(len(calls)))
    row = calls[0] if calls else {}
    check("oddiy post: post_type = album", row.get("post_type") == "album",
          str(row.get("post_type")))
    check("oddiy post: file_id'da 10 ta fayl",
          len(json.loads(row.get("file_id") or "[]")) == 10,
          str(row.get("file_id"))[:80])
    MP._MANUAL_ALBUM_TASKS.clear()


# ======================================================================
# 10. Konversatsiya zanjiri: rasm → albom → 1-post holati
# ======================================================================
def test_conversation_registers_media_handlers():
    print("== 10. Conversation: albom uchun media handlerlar ro'yxatda ==")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = ApplicationBuilder().token("123456:TEST_TOKEN").build()
        register_all_handlers(app)
    conv = [h for h in app.handlers[0] if isinstance(h, ConversationHandler)][0]
    from telegram.ext import MessageHandler

    content_cbs = [h.callback for state, hs in conv.states.items()
                   if state in (GET_CONTENT, GET_BTN_TITLE)
                   for h in hs if isinstance(h, MessageHandler)]
    check("GET_CONTENT/GET_BTN_TITLE'da content_received bor",
          content_received in content_cbs,
          str([getattr(c, "__name__", c) for c in content_cbs]))
    check("albom chegarasi konstantasi 10", _ALBUM_MAX_ITEMS == 10,
          str(_ALBUM_MAX_ITEMS))
    src = (ROOT / "handlers" / "new_post.py").read_text(encoding="utf-8")
    check("new_post: idle-oynali collector mavjud",
          "async def _album_collector" in src and "_ALBUM_MAX_WAIT_SECONDS" in src)
    check("new_post: ketma-ket birlashtirish oynasi mavjud",
          "_ALBUM_MERGE_WINDOW_SECONDS" in src and "_recent_draft_items" in src)


# ======================================================================
# 11. Collector idempotentligi: bitta albom → bitta post, takroriy so'rov yo'q
# ======================================================================
def test_collector_is_idempotent():
    print("== 11. Collector idempotent: bitta albom → bitta post ==")
    _reset_album_state()
    old_wait = np_mod._ALBUM_WAIT_SECONDS
    np_mod._ALBUM_WAIT_SECONDS = 0.1
    user_data = {"lang": "uz"}
    bot = _RecBot()
    ctx = _ctx(user_data, bot=bot, user_id=909)
    files = [f"i{i}" for i in range(6)]

    async def run():
        for i, fid in enumerate(files):
            await np_mod.content_received(
                _photo_update(909, fid, caption=("Idempotent izoh" if i == 0 else ""),
                              media_group_id="gidem", message_id=500 + i, bot=bot), ctx)
        await asyncio.sleep(np_mod._ALBUM_WAIT_SECONDS + 0.4)
        # Collector allaqachon yakunlagan — qayta yakunlash HECH NARSA qilmaydi.
        buf_key = (909, "gidem")
        again = np_mod._finalize_album_buffer(buf_key)
        return again

    try:
        again = asyncio.run(run())
    finally:
        np_mod._ALBUM_WAIT_SECONDS = old_wait

    check("yakunlangan bufer qayta yakunlanmaydi (None)", again is None, str(again))
    check("buferlar bo'sh (split state yo'q)", not _ALBUM_BUFFERS,
          str(list(_ALBUM_BUFFERS)))
    check("faqat BITTA albom xabari (takroriy prompt yo'q)",
          sum(1 for t in bot.texts()
              if get_text("np_album_received", "uz").split("{")[0] in t) == 1,
          str(bot.texts())[:200])
    items = json.loads(user_data.get("file_id") or "[]")
    check("6 ta fayl bitta postda", len(items) == 6
          and [i["file_id"] for i in items] == files,
          str([i.get("file_id") for i in items]))
    check("_album_count == 6 va _album_ready bir marta",
          user_data.get("_album_count") == 6
          and user_data.get("_album_ready") is True,
          str(user_data.get("_album_count")))


# ======================================================================
# 12. ✍️ Oddiy post: albom preview'i (muqova + "N ta fayl") va i18n pariteti
# ======================================================================
def test_manual_album_preview_and_i18n():
    print("== 12. Oddiy post: albom preview'i (muqova) + i18n pariteti ==")
    from translations.manual_post import (  # noqa: E402
        manual_post_parity_report, manual_post_t, MANUAL_POST_I18N,
    )
    rep = manual_post_parity_report()
    check("manual_post i18n pariteti in_sync", rep["in_sync"] is True,
          str(rep["missing"]) + str(rep["format_mismatch"]))
    for lang in ("uz", "ru", "en"):
        check(f"{lang}: mp_album_summary mavjud",
              "mp_album_summary" in (MANUAL_POST_I18N.get(lang) or {}))
        text = manual_post_t("mp_album_summary", lang, count=10)
        check(f"{lang}: albom xulosasida 10 bor", "10" in text, text)

    items = [{"type": "photo", "file_id": f"z{i}", "caption": ""}
             for i in range(_ALBUM_MAX_ITEMS)]
    items[0]["caption"] = "Muqova izohi"
    ud = {
        "lang": "uz", UD_POST_TYPE: "album", UD_MEDIA_GROUP: True,
        UD_FILE_ID: json.dumps(items, ensure_ascii=False),
        UD_ALBUM_ITEMS: json.dumps(items, ensure_ascii=False),
        UD_CONTENT: "Muqova izohi", "selected_channel_title": "Kanal",
    }
    ctx = SimpleNamespace(user_data=ud, bot=_RecBot(), _user_id=321, chat_id=321)
    extras = MP._manual_extras_text(ctx, "uz")
    check("preview xulosasida fayllar soni ko'rinadi",
          MP.manual_post_t("mp_album_summary", "uz", count=10) in extras,
          extras[:160])

    msg = _FakeMsg(user_id=321, chat_id=321)
    asyncio.run(MP._show_preview(msg, ctx, "uz"))
    check("albom preview'i BITTA muqova media bilan chiqadi",
          len(msg.replies) == 1 and msg.replies[0]["kind"] == "photo",
          str(msg.replies)[:160])
    cap = msg.replies[0].get("caption") or ""
    check("muqova caption'ida albom xulosasi bor",
          MP.manual_post_t("mp_album_summary", "uz", count=10) in cap,
          cap[:200])
    check("muqova caption'ida asl izoh saqlanadi", "Muqova izohi" in cap,
          cap[:200])
    check("preview panelida tugmalar bor",
          msg.replies[0]["reply_markup"] is not None)


# ======================================================================
def main():
    test_i18n_album_ack_keys()
    test_ten_item_group_single_post()
    test_sequential_files_merge_into_one_album()
    test_caption_binding_from_any_item()
    test_eleventh_file_notice_and_album_kept()
    test_confirm_saves_single_row_for_ten_files()
    test_scheduler_sends_one_media_group()
    test_preview_shows_ten_files_summary()
    test_manual_album_ten_photos_single_post()
    test_conversation_registers_media_handlers()
    test_collector_is_idempotent()
    test_manual_album_preview_and_i18n()

    passed = sum(1 for ok, _, _ in CHECKS if ok)
    failed = [m for ok, m, _ in CHECKS if not ok]
    print(f"\n10 ta media (albom) testlari: {passed} passed, {len(failed)} failed")
    if failed:
        print("FAILED:")
        for m in failed:
            print("  -", m)
        sys.exit(1)
    print("HAMIYASI OK ✔")


if __name__ == "__main__":
    main()
