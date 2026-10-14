"""🖼 ALBOM (media_group) YIG'UVCHI — bir nechta rasm/video BITTA post.

Qamrov:
  1) ``MediaGroupCollector``: debounce, tartib, dublikat, chegara, bekor qilish,
     xato izolyatsiyasi, parallel albomlar;
  2) 🧹 Post tozalagich: albom fayllari bitta post (``album``) bo'lib yig'iladi,
     izoh butun albomga biriktiriladi, imzo qo'shiladi, kanalga yoki kanal
     tanlash tugmalari bilan yuboriladi;
  3) scheduler albom formati bilan moslik (``parse_album_items`` /
     ``_build_album_media``).

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/media_group_album_test.py
"""
import asyncio
import json
import os
import sys
import time
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:ALBUM_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from telegram import MessageEntity  # noqa: E402

from handlers import post_cleaner_flow as clf  # noqa: E402
from services.media_group_collector import (  # noqa: E402
    ADDED,
    ADDED_STARTED,
    DUPLICATE,
    FULL,
    MediaGroupCollector,
)

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ====================================================================== 1) KOLLEKTOR
print("== kollektor: bufer va debounce ==")


async def collector_basic():
    got = []

    async def ready(items):
        got.append([i["n"] for i in items])

    c = MediaGroupCollector(delay=0.05, max_wait=1.0)
    r1 = c.add("g", {"message_id": 3, "n": "c"}, ready)
    r2 = c.add("g", {"message_id": 1, "n": "a"}, ready)
    r3 = c.add("g", {"message_id": 2, "n": "b"}, ready)
    check("birinchi fayl buferni ochadi", r1 == ADDED_STARTED, r1)
    check("keyingilari qo'shiladi", r2 == ADDED and r3 == ADDED, f"{r2},{r3}")
    check("yig'ilayotgan fayllar soni", c.pending("g") == 3 and c.is_collecting("g"))
    check("jimlikdan OLDIN on_ready chaqirilmaydi", got == [])
    await c.wait_idle()
    check("jimlikdan keyin BIR marta chaqiriladi", len(got) == 1, str(got))
    check("fayllar message_id bo'yicha tartiblangan", got == [["a", "b", "c"]], str(got))
    check("chaqiruvdan keyin bufer bo'sh", c.pending() == 0 and not c.is_collecting("g"))


asyncio.run(collector_basic())


async def collector_debounce():
    got = []

    async def ready(items):
        got.append((time.monotonic(), len(items)))

    c = MediaGroupCollector(delay=0.15, max_wait=5.0)
    t0 = time.monotonic()
    c.add("g", {"message_id": 1}, ready)
    await asyncio.sleep(0.10)
    c.add("g", {"message_id": 2}, ready)      # jimlik oynasi qayta boshlanadi
    await asyncio.sleep(0.10)
    c.add("g", {"message_id": 3}, ready)
    check("oyna ichida kelgan fayllar chaqiruvni kechiktiradi", got == [])
    await c.wait_idle()
    elapsed = got[0][0] - t0 if got else 0
    check("oxirgi fayldan keyin ~delay o'tgach yakunlanadi", len(got) == 1 and got[0][1] == 3
          and elapsed >= 0.34, f"{got} elapsed={elapsed:.3f}")


asyncio.run(collector_debounce())


async def collector_five_rapid_updates():
    """Regression: 5 ta 100ms-oraliqli update hech qachon 5 preview bo'lmaydi."""
    posts = []
    worker_ids = set()

    async def create_aggregated_post(items):
        posts.append([item["file_id"] for item in items])

    collector = MediaGroupCollector()  # production: last-item + 2.0s
    for index in range(5):
        collector.add(
            "same-media-group-id",
            {"message_id": 100 + index, "file_id": f"rapid-{index}"},
            create_aggregated_post,
        )
        worker_ids.add(id(collector.task_for("same-media-group-id")))
        if index < 4:
            await asyncio.sleep(0.1)

    check("5 rapid update davomida partial preview yaratilmaydi", posts == [], str(posts))
    check("bir media_group uchun faqat bitta worker ishlaydi", len(worker_ids) == 1,
          str(worker_ids))
    await collector.wait_idle()
    check("5 rapid update faqat BIR aggregated post yaratadi", len(posts) == 1,
          str(posts))
    check("aggregated post barcha 5 itemni saqlaydi",
          posts == [[f"rapid-{i}" for i in range(5)]], str(posts))


asyncio.run(collector_five_rapid_updates())


async def collector_edge():
    got = []

    async def ready(items):
        got.append(len(items))

    c = MediaGroupCollector(delay=0.05, max_wait=1.0, max_items=3)
    results = [c.add("g", {"message_id": i}, ready) for i in (1, 1, 2, 3, 4)]
    check("dublikat message_id bir marta hisoblanadi", results[1] == DUPLICATE, str(results))
    check("chegaradan oshgan fayl qo'shilmaydi (FULL)", results[4] == FULL, str(results))
    await c.wait_idle()
    check("faqat 3 ta fayl yetkazildi", got == [3], str(got))

    # max_wait: fayllar to'xtamay kelsa ham cheksiz kutilmaydi
    got.clear()
    c = MediaGroupCollector(delay=0.2, max_wait=0.3)
    c.add("g", {"message_id": 1}, ready)
    for i in range(2, 5):
        await asyncio.sleep(0.1)
        c.add("g", {"message_id": i}, ready)
    await c.wait_idle()
    check("max_wait: doimiy oqimda ham yakunlanadi", len(got) >= 1, str(got))

    # parallel albomlar mustaqil
    got.clear()
    seen = {}

    async def ready_key(items):
        seen[items[0]["g"]] = len(items)

    c = MediaGroupCollector(delay=0.05)
    c.add("A", {"message_id": 1, "g": "A"}, ready_key)
    c.add("B", {"message_id": 5, "g": "B"}, ready_key)
    c.add("A", {"message_id": 2, "g": "A"}, ready_key)
    await c.wait_idle()
    check("parallel albomlar aralashmaydi", seen == {"A": 2, "B": 1}, str(seen))

    # xato izolyatsiyasi
    ok = []

    async def boom(items):
        raise RuntimeError("on_ready xatosi")

    async def fine(items):
        ok.append(len(items))

    import logging
    noisy = logging.getLogger("services.media_group_collector")
    noisy.disabled = True  # kutilgan xato logini CI chiqishidan olib tashlaymiz
    c = MediaGroupCollector(delay=0.03)
    c.add("bad", {"message_id": 1}, boom)
    c.add("good", {"message_id": 2}, fine)
    await c.wait_idle()
    noisy.disabled = False
    check("bir albom xatosi boshqasini to'xtatmaydi", ok == [1], str(ok))

    # bekor qilish va darhol yakunlash
    called = []

    async def spy(items):
        called.append(len(items))

    c = MediaGroupCollector(delay=0.05)
    c.add("x", {"message_id": 1}, spy)
    check("cancel: bufer olib tashlanadi", c.cancel("x") is True and c.cancel("x") is False)
    await asyncio.sleep(0.12)
    check("cancel: on_ready chaqirilmaydi", called == [], str(called))
    c.add("y", {"message_id": 1}, spy)
    c.add("y", {"message_id": 2}, spy)
    check("flush: kutmasdan darhol yetkazadi", await c.flush("y") is True and called == [2], str(called))
    await asyncio.sleep(0.1)
    check("flush: ikki marta chaqirilmaydi", called == [2], str(called))

    # xabarlar message_id siz ham ishlaydi
    c = MediaGroupCollector(delay=0.03)
    done = []

    async def r(items):
        done.append(len(items))

    c.add("n", {"file": 1}, r)
    c.add("n", {"file": 2}, r)
    await c.wait_idle()
    check("message_id siz elementlar (dublikat tekshiruvisiz)", done == [2], str(done))


asyncio.run(collector_edge())


# =========================================== 1b) 🖼 BIRLASHTIRILGAN (UNIFIED) PREVIEW
# Albom to'liq yig'ilgach preview BITTA tuzilgan javob bo'lishi kerak:
# muqova media + butun albomga tegishli caption + boshqaruv tugmalari.
# Media fayllar va menyu IKKI alohida xabarga ajratilmaydi.
print("== unified albom preview: media + caption + tugmalar = BITTA xabar ==")

from services.media_group_collector import (  # noqa: E402
    ALBUM_CAPTION_LIMIT,
    ALBUM_TEXT_LIMIT,
    AlbumPayload,
    build_album_preview,
    send_album_preview,
    _utf16_length,
)


class _PreviewTransport:
    """Unified preview transporti (bot yoki xabar adapteri o'rniga)."""

    def __init__(self, *, media_error=None, text_error=None):
        self.calls = []
        self.media_error = media_error
        self.text_error = text_error

    async def _record(self, method, kwargs, error=None):
        self.calls.append((method, dict(kwargs)))
        if error is not None:
            raise error
        return SimpleNamespace(method=method)

    def _text_error(self, kwargs):
        return self.text_error if kwargs.get("parse_mode") else None

    async def reply_photo(self, **kw):
        return await self._record("reply_photo", kw, self.media_error)

    async def reply_video(self, **kw):
        return await self._record("reply_video", kw, self.media_error)

    async def reply_text(self, **kw):
        return await self._record("reply_text", kw, self._text_error(kw))

    async def send_photo(self, **kw):
        return await self._record("send_photo", kw, self.media_error)

    async def send_message(self, **kw):
        return await self._record("send_message", kw, self._text_error(kw))

    def methods(self):
        return [m for m, _ in self.calls]


async def unified_preview_build():
    items = [{"type": "photo", "file_id": "p1", "caption": "Izoh"},
             {"type": "video", "file_id": "v2", "caption": ""},
             {"type": "photo", "file_id": "p3", "caption": ""}]
    markup = SimpleNamespace(inline_keyboard=[[SimpleNamespace(text="btn")]])
    preview = build_album_preview(items, text="Albom: 3 ta fayl", reply_markup=markup)
    check("muqova — birinchi renderlanadigan fayl",
          preview.kind == "photo" and preview.file_id == "p1", str(preview.to_dict())[:160])
    check("butun albom birlashtirilgan javobda saqlanadi (3 fayl)",
          preview.count == 3 and len(preview.items) == 3 and preview.is_album)
    check("boshqaruv tugmalari SHU javobga biriktiriladi (alohida xabar yo'q)",
          preview.reply_markup is markup)
    check("caption va zaxira matn bitta manbadan",
          preview.caption == "Albom: 3 ta fayl" and preview.body() == preview.caption)

    mixed = [{"type": "voice", "file_id": "vx"}, {"type": "video", "file_id": "v"}]
    p2 = build_album_preview(mixed, text="t")
    check("qo'llab-quvvatlanmaydigan tur muqova bo'lmaydi (keyingi fayl)",
          p2.kind == "video" and p2.file_id == "v", str(p2.to_dict())[:160])

    p3 = build_album_preview([], text="matn", reply_markup=markup)
    check("bo'sh albom → matnli karta (tugmalar baribir biriktiriladi)",
          not p3.is_media and p3.body() == "matn" and p3.reply_markup is markup)

    p4 = build_album_preview(items, text="a" * 5000)
    check("caption Telegram chegarasida (1024)",
          _utf16_length(p4.caption) <= ALBUM_CAPTION_LIMIT, str(len(p4.caption)))
    check("zaxira matn Telegram chegarasida (4096)",
          _utf16_length(p4.text) <= ALBUM_TEXT_LIMIT, str(len(p4.text)))
    p5 = build_album_preview(items, text="🖼" * 900)
    check("emoji (UTF-16 = 2 birlik) hisobida ham caption 1024 dan oshmaydi",
          _utf16_length(p5.caption) <= ALBUM_CAPTION_LIMIT
          and p5.caption.endswith("…"), str(_utf16_length(p5.caption)))

    def fake_sanitizer(text, limit):
        return f"<b>{text[:limit]}</b>"

    p6 = build_album_preview(items, text="salom", sanitizer=fake_sanitizer)
    check("HTML sanitizer natijasi caption'da ishlatiladi",
          p6.caption == "<b>salom</b>", p6.caption)

    many = [{"type": "photo", "file_id": f"f{i}"} for i in range(14)]
    p7 = build_album_preview(many, text="t")
    check("albom 10 fayldan oshmaydi (Telegram chegarasi)", p7.count == 10, str(p7.count))

    payload = AlbumPayload(media_group_id="G", items=[dict(i) for i in items],
                           caption="Izoh")
    p8 = payload.preview(reply_markup=markup)
    check("AlbumPayload.preview: media + caption + tugmalar BITTA javobda",
          p8.is_media and p8.caption == "Izoh" and p8.reply_markup is markup
          and p8.count == 3, str(p8.to_dict())[:160])
    p9 = payload.preview(text="maxsus matn")
    check("AlbumPayload.preview: berilgan matn ustun", p9.caption == "maxsus matn")


asyncio.run(unified_preview_build())


async def unified_preview_send():
    items = [{"type": "photo", "file_id": "p1"}, {"type": "photo", "file_id": "p2"}]
    markup = SimpleNamespace(inline_keyboard=[])
    preview = build_album_preview(items, text="caption matni", reply_markup=markup)

    t1 = _PreviewTransport()
    await send_album_preview(t1, preview, reply=True)
    check("xabar adapteri: AYNAN BITTA xabar (reply_photo)",
          t1.methods() == ["reply_photo"], str(t1.calls)[:160])
    kw = t1.calls[0][1]
    check("bitta xabarda media + caption + tugmalar birga",
          kw.get("photo") == "p1" and kw.get("caption") == "caption matni"
          and kw.get("reply_markup") is markup and kw.get("parse_mode") == "HTML",
          str(kw)[:200])
    check("xabar adapteridan chat_id so'ralmaydi", "chat_id" not in kw, str(kw)[:120])

    t2 = _PreviewTransport()
    await send_album_preview(t2, preview, chat_id=42)
    check("bot: AYNAN BITTA xabar (send_photo) + chat_id",
          t2.methods() == ["send_photo"] and t2.calls[0][1].get("chat_id") == 42,
          str(t2.calls)[:160])

    t3 = _PreviewTransport(media_error=RuntimeError("media xatosi"))
    await send_album_preview(t3, preview, reply=True)
    check("media xatosida matnli kartaga o'tiladi (oqim to'xtamaydi)",
          t3.methods() == ["reply_photo", "reply_text"], str(t3.methods()))
    check("zaxira kartada ham caption va tugmalar bor (ajratilmagan)",
          t3.calls[-1][1].get("reply_markup") is markup
          and t3.calls[-1][1].get("text") == preview.text, str(t3.calls[-1])[:200])

    t4 = _PreviewTransport(text_error=RuntimeError("can't parse entities"))
    text_only = build_album_preview([], text="matn", reply_markup=markup)
    await send_album_preview(t4, text_only, reply=True)
    check("HTML xatosida parse_mode=None bilan qayta urinish",
          len(t4.calls) == 2 and t4.calls[-1][1].get("parse_mode") is None,
          str(t4.calls)[:200])

    class _TextOnlyAdapter:
        def __init__(self):
            self.calls = []

        async def reply_text(self, **kw):
            self.calls.append(kw)
            return SimpleNamespace(message_id=1)

    t5 = _TextOnlyAdapter()
    await send_album_preview(t5, preview, reply=True)
    check("media metodi yo'q adapterda ham BITTA xabar (matn + tugmalar)",
          len(t5.calls) == 1 and t5.calls[0].get("reply_markup") is markup
          and t5.calls[0].get("text") == preview.text, str(t5.calls)[:200])

    check("bo'sh preview/transport xato qaytarmaydi",
          await send_album_preview(None, preview) is None
          and await send_album_preview(_PreviewTransport(), None) is None)


asyncio.run(unified_preview_send())


# ====================================================================== 2) TOZALAGICH
print("== tozalagich: albom BITTA post ==")

SIG = '<a href="https://t.me/mening_kanalim">📢 Bizning kanal</a>'
OWN = frozenset({"mening_kanalim"})


class FakeSent:
    def __init__(self, bot, kind):
        self.bot, self.kind = bot, kind
        self.edits = []

    async def edit_text(self, text, **kw):
        self.edits.append(text)


class FakeBot:
    def __init__(self):
        self.groups, self.texts = [], []
        # 🖼 BIRLASHTIRILGAN preview kartalari: media + caption + tugmalar
        # BITTA xabarda (muqova fayl turi va file_id bilan yozib boriladi).
        self.cards = []

    async def send_media_group(self, chat_id, media=None, **kw):
        self.groups.append((chat_id, list(media)))
        return [SimpleNamespace(message_id=i) for i in range(len(media))]

    async def send_message(self, chat_id, text, **kw):
        self.texts.append((chat_id, text, kw.get("reply_markup")))
        return FakeSent(self, "text")

    def _record_card(self, kind, chat_id, file_id, kw):
        self.cards.append({
            "kind": kind, "chat_id": chat_id, "file_id": file_id,
            "caption": kw.get("caption"), "reply_markup": kw.get("reply_markup"),
            "parse_mode": kw.get("parse_mode"),
        })
        return FakeSent(self, kind)

    async def send_photo(self, chat_id, photo=None, **kw):
        return self._record_card("photo", chat_id, photo, kw)

    async def send_video(self, chat_id, video=None, **kw):
        return self._record_card("video", chat_id, video, kw)

    async def send_animation(self, chat_id, animation=None, **kw):
        return self._record_card("animation", chat_id, animation, kw)

    async def send_document(self, chat_id, document=None, **kw):
        return self._record_card("document", chat_id, document, kw)

    async def send_audio(self, chat_id, audio=None, **kw):
        return self._record_card("audio", chat_id, audio, kw)


class Msg:
    def __init__(self, mid, group, kind="photo", file_id=None, caption=None, ents=(), chat_id=42):
        self.message_id, self.media_group_id, self.chat_id = mid, group, chat_id
        self.text, self.caption, self.caption_entities, self.entities = None, caption, ents, ()
        self.replies = []
        for k in ("photo", "video", "animation", "document", "audio", "voice"):
            setattr(self, k, None)
        fid = file_id or f"F{mid}"
        setattr(self, kind, [SimpleNamespace(file_id=fid)] if kind == "photo" else SimpleNamespace(file_id=fid))

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        return self


def setup(channels, autosend=False, premium=True):
    calls = {"add_post": [], "deliver": 0}

    async def run_db(func, *a, **k):
        return func(*a, **k)

    clf.db = SimpleNamespace(
        run_db=run_db,
        get_user_post_signature_html=lambda uid: SIG,
        get_user_setting=lambda uid, key, default=False: autosend,
        get_user_channels=lambda uid: channels,
        is_premium=lambda uid: premium,
        add_post=lambda **kw: calls["add_post"].append(kw) or 99,
        get_post_status=lambda pid, uid: "posted",
    )

    async def own(uid):
        return OWN

    async def lang(context, uid):
        return "uz"

    async def guard(uid, channel_id, action="create"):
        return True

    clf.own_channel_usernames = own
    clf._lang = lang
    import handlers.manual_post as mp
    mp.manual_channel_guard = guard
    import utils.handler_timeout as ht

    def run_bg(coro, name=None, **kw):
        calls["deliver"] += 1
        coro.close()

    ht.run_background_task = run_bg
    clf._ALBUMS = MediaGroupCollector(delay=0.05, max_wait=1.0)
    return calls


def upd(msg):
    return SimpleNamespace(message=msg, effective_user=SimpleNamespace(id=7),
                           effective_message=msg, effective_chat=SimpleNamespace(id=42))


async def send_album(ctx, msgs, gap=0.0):
    states = []
    for m in msgs:
        states.append(await clf.post_received(upd(m), ctx))
        if gap:
            await asyncio.sleep(gap)
    return states


async def scenario_autosend():
    calls = setup([("-100111", "Kanal A")], autosend=True)
    bot = FakeBot()
    ctx = SimpleNamespace(user_data={}, bot=bot)
    t0 = time.monotonic()
    msgs = [Msg(11, "G1", caption="Yangilik\nReklama: @promo_bot"),
            Msg(12, "G1"), Msg(13, "G1", kind="video")]
    states = await send_album(ctx, msgs)
    handler_time = time.monotonic() - t0
    check("handler albom fayllarida darhol qaytadi (bloklanmaydi)", handler_time < 0.04, f"{handler_time:.3f}")
    check("har bir fayl uchun rejim davom etadi", states == [clf.CLEANER_POST_INPUT] * 3, str(states))
    check("jimlikdan OLDIN hech narsa yuborilmaydi", calls["add_post"] == [])
    await clf._ALBUMS.wait_idle()
    check("albom BITTA post bo'lib saqlandi", len(calls["add_post"]) == 1, str(calls["add_post"]))
    post = calls["add_post"][0] if calls["add_post"] else {}
    files = json.loads(post.get("file_id") or "[]")
    check("post turi 'album'", post.get("post_type") == "album", str(post.get("post_type")))
    check("barcha 3 fayl bitta postda, tartibi saqlangan",
          [f["file_id"] for f in files] == ["F11", "F12", "F13"], str(files))
    check("fayl turlari saqlangan (photo, photo, video)",
          [f["type"] for f in files] == ["photo", "photo", "video"], str(files))
    check("izoh tozalandi (begona reklama qatori olindi) + imzo qo'shildi",
          post.get("content") == f"Yangilik\n\n{SIG}", str(post.get("content")))
    check("izoh faqat BIRINCHI faylda", files[0]["caption"] == post.get("content")
          and all(f["caption"] == "" for f in files[1:]), str(files))
    check("kanal to'g'ri", post.get("channel_id") == "-100111")
    check("yetkazish darhol boshlandi (1 marta)", calls["deliver"] == 1, str(calls["deliver"]))

    # scheduler formati bilan moslik
    from scheduler import _build_album_media, parse_album_items
    items = parse_album_items(post.get("file_id"))
    check("scheduler.parse_album_items 3 elementni o'qiydi", len(items) == 3, str(items))
    media = _build_album_media(items, post.get("content"))
    check("scheduler albom: caption faqat birinchi mediada",
          media[0].caption and all(m.caption is None for m in media[1:]), str([m.caption for m in media]))


asyncio.run(scenario_autosend())


async def scenario_order_and_caption():
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    # Telegram tartibi: kelish tartibi aralash, izoh 2-faylda
    msgs = [Msg(23, "G2"), Msg(21, "G2"), Msg(22, "G2", caption="Matn bu yerda")]
    await send_album(ctx, msgs)
    await clf._ALBUMS.wait_idle()
    post = calls["add_post"][0] if calls["add_post"] else {}
    files = json.loads(post.get("file_id") or "[]")
    check("aralash kelgan fayllar message_id bo'yicha tartiblanadi",
          [f["file_id"] for f in files] == ["F21", "F22", "F23"], str(files))
    check("izoh boshqa faylda bo'lsa ham butun albomga biriktiriladi",
          post.get("content") == f"Matn bu yerda\n\n{SIG}" and files[0]["caption"] == post.get("content"),
          str(post))

    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(31, "G3"), Msg(32, "G3")])
    await clf._ALBUMS.wait_idle()
    post = calls["add_post"][0] if calls["add_post"] else {}
    check("izohsiz albom: faqat imzo", post.get("content") == SIG, str(post.get("content")))

    # bitta fayllik "albom" — oddiy media post
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(41, "G4", caption="Yagona")])
    await clf._ALBUMS.wait_idle()
    post = calls["add_post"][0] if calls["add_post"] else {}
    check("bitta fayl: oddiy 'photo' post (albom emas)",
          post.get("post_type") == "photo" and post.get("file_id") == "F41", str(post))

    # dublikat update
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(51, "G5"), Msg(51, "G5"), Msg(52, "G5")])
    await clf._ALBUMS.wait_idle()
    files = json.loads((calls["add_post"][0] if calls["add_post"] else {}).get("file_id") or "[]")
    check("takroriy update ikki marta qo'shilmaydi", [f["file_id"] for f in files] == ["F51", "F52"], str(files))

    # qalin matn formatlash saqlanadi
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(61, "G6", caption="Muhim xabar", ents=[MessageEntity("bold", 0, 5)]), Msg(62, "G6")])
    await clf._ALBUMS.wait_idle()
    post = calls["add_post"][0] if calls["add_post"] else {}
    check("albom izohidagi formatlash (qalin) saqlanadi",
          str(post.get("content", "")).startswith("<b>Muhim</b> xabar"), str(post.get("content")))


asyncio.run(scenario_order_and_caption())


async def scenario_multi_channel_and_buttons():
    calls = setup([("-100111", "Kanal A"), ("-100222", "Kanal B")], autosend=True)
    bot = FakeBot()
    ctx = SimpleNamespace(user_data={}, bot=bot)
    await send_album(ctx, [Msg(71, "G7", caption="Post"), Msg(72, "G7")])
    await clf._ALBUMS.wait_idle()
    check("ko'p kanal: avtomatik yuborilmaydi", calls["add_post"] == [])
    check("ko'p kanal: albom preview (send_media_group) yuborildi",
          len(bot.groups) == 1 and len(bot.groups[0][1]) == 2, str(bot.groups))
    cap = [m.caption for m in bot.groups[0][1]] if bot.groups else []
    check("preview: izoh faqat birinchi mediada, imzo bilan",
          cap and cap[0] == f"Post\n\n{SIG}" and cap[1] is None, str(cap))
    markup = bot.texts[-1][2] if bot.texts else None
    data = [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []
    check("kanal tanlash tugmalari (har bir kanal alohida) chiqdi", len(data) == 2
          and all(d.startswith("stgs_clean_pub:") for d in data), str(data))
    check("tugmalar xabari albom soni bilan", "2" in bot.texts[-1][1], bot.texts[-1][1])

    # tugma bosiladi → tanlangan kanalga albom post
    token = data[1].split(":")[1]
    query = SimpleNamespace(data=data[1], from_user=SimpleNamespace(id=7),
                            message=Msg(80, None, kind="photo"))

    async def answer(text=None, show_alert=False):
        return None

    async def edit_markup(reply_markup=None):
        return None

    query.answer, query.edit_message_reply_markup = answer, edit_markup

    async def reply_text(text, **kw):
        return FakeSent(bot, "status")

    query.message.reply_text = reply_text
    await clf.publish_callback(SimpleNamespace(callback_query=query), ctx)
    post = calls["add_post"][0] if calls["add_post"] else {}
    check("tanlangan kanalga albom sifatida saqlandi",
          post.get("channel_id") == "-100222" and post.get("post_type") == "album"
          and len(json.loads(post.get("file_id") or "[]")) == 2, str(post))
    check("token bir marta ishlaydi (ikki marta yuborilmaydi)", token not in ctx.user_data.get(clf._UD_PENDING, {}))


asyncio.run(scenario_multi_channel_and_buttons())


async def scenario_limits_and_stop():
    calls = setup([("-100111", "Kanal A")], autosend=True)
    bot = FakeBot()
    ctx = SimpleNamespace(user_data={}, bot=bot)
    await send_album(ctx, [Msg(91, "G9", caption="x" * 1030), Msg(92, "G9")])
    await clf._ALBUMS.wait_idle()
    check("albom izohi 1024 dan oshsa: yuborilmaydi va tushuntiriladi",
          calls["add_post"] == [] and bot.texts and "1024" in bot.texts[-1][1], str(bot.texts[-1:]))

    # rejim to'xtatilsa fon vazifa hech narsa qilmaydi
    calls = setup([("-100111", "Kanal A")], autosend=True)
    bot = FakeBot()
    ctx = SimpleNamespace(user_data={}, bot=bot)
    await send_album(ctx, [Msg(101, "GA", caption="a"), Msg(102, "GA")])
    ctx.user_data.pop(clf._UD_SESSION, None)
    await clf._ALBUMS.wait_idle()
    check("rejim to'xtatilgach albom yuborilmaydi", calls["add_post"] == [] and bot.texts == [])

    # ikkita turli albom — ikkita post
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(111, "GB", caption="1"), Msg(112, "GC", caption="2"),
                           Msg(113, "GB"), Msg(114, "GC")])
    await clf._ALBUMS.wait_idle()
    groups = sorted(len(json.loads(p["file_id"])) for p in calls["add_post"])
    check("ikki xil albom aralash kelsa ham ikki alohida post", groups == [2, 2], str(groups))

    # 10 fayl chegarasi
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await send_album(ctx, [Msg(200 + i, "GD", caption="c" if i == 0 else None) for i in range(12)])
    await clf._ALBUMS.wait_idle()
    n = len(json.loads((calls["add_post"][0] if calls["add_post"] else {}).get("file_id") or "[]"))
    check("albom 10 fayldan oshmaydi (Telegram chegarasi)", n == 10, str(n))

    # qo'llab-quvvatlanmaydigan tur (ovoz) albomda yo'q
    calls = setup([("-100111", "Kanal A")], autosend=True)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    voice = Msg(300, "GE", kind="voice")
    st = await clf.post_received(upd(voice), ctx)
    check("albomdagi qo'llab-quvvatlanmagan tur: tushuntiriladi, oqim davom etadi",
          st == clf.CLEANER_POST_INPUT and voice.replies and calls["add_post"] == [])


asyncio.run(scenario_limits_and_stop())

# Concurrent Telegram updates must produce one durable post, not one per file.
async def scenario_concurrent_delivery():
    from unittest.mock import AsyncMock, patch
    import scheduler
    import utils.helpers as helpers
    from services.media_group_collector import DEFAULT_DELAY_SECONDS

    # QAT'IY 2.0 SONIYA: albom TO'LIQ yig'ilishi uchun yagona standart
    # (``ALBUM_DEBOUNCE_SECONDS`` — butun loyiha uchun bitta manba).
    check("production debounce is 2.0 seconds",
          DEFAULT_DELAY_SECONDS == clf.ALBUM_DEBOUNCE_SECONDS == 2.0,
          f"{DEFAULT_DELAY_SECONDS}/{clf.ALBUM_DEBOUNCE_SECONDS}")
    for caption in (None, "Muhim xabar"):
        calls = setup([("-100111", "Kanal A")], autosend=True, premium=False)
        ctx = SimpleNamespace(user_data={}, bot=FakeBot())
        # Force actual coroutine interleaving during session loading.
        original_lang = clf._lang

        async def yielding_lang(context, uid):
            await asyncio.sleep(0)
            return await original_lang(context, uid)

        clf._lang = yielding_lang
        messages = [Msg(403, "concurrent", kind="video"),
                    Msg(401, "concurrent"),
                    Msg(402, "concurrent", caption=caption,
                        ents=[MessageEntity("bold", 0, 5)] if caption else ())]
        await asyncio.gather(*(clf.post_received(upd(m), ctx) for m in messages))
        await clf._ALBUMS.wait_idle()
        check("concurrent updates create exactly one DB post", len(calls["add_post"]) == 1)
        post = calls["add_post"][0]
        send_ctx = dict(post, post_id=99, btn_text=None, btn_url=None,
                        enable_reactions=False, reaction_emojis=None, delivery_kwargs={})
        async def run_db(fn, *args, **kwargs):
            if fn.__name__ == "is_premium":
                return False
            if fn.__name__ == "get_setting":
                return ""
            raise AssertionError(f"Unexpected DB call: {fn.__name__}")

        sent = []
        async def delivery(bot, method, **kwargs):
            sent.append((method, kwargs))
            return [SimpleNamespace(message_id=501 + i) for i in range(3)]

        # Exercise the actual shared immediate/scheduled publishing pipeline,
        # mocking only DB, entitlements and the outbound Telegram boundary.
        with patch.object(scheduler.db, "run_db", run_db), \
             patch.object(scheduler, "resolve_channel_ad", AsyncMock(return_value={})), \
             patch.object(helpers, "is_watermark_exempt", AsyncMock(return_value=False)), \
             patch.object(scheduler, "BOT_USERNAME", "PostAssistrobot"), \
             patch.object(scheduler, "_delivery_send", delivery):
            payload = await scheduler._build_send_payload(send_ctx)
            await scheduler._dispatch_post_to_telegram(ctx.bot, send_ctx, payload, {})
        check("scheduler calls sendMediaGroup exactly once",
              len(sent) == 1 and sent[0][0] == "send_media_group")
        media = sent[0][1]["media"]
        check("all concurrent file IDs reach channel in Telegram order",
              [m.media for m in media] == ["F401", "F402", "F403"])
        check("album caption includes cleaner signature and mandatory Free watermark",
              SIG in media[0].caption
              and media[0].caption.startswith("🤖 @PostAssistrobot\n\n"))
        check("formatted caption preserved, other media have no caption",
              (not caption or "<b>Muhim</b> xabar" in media[0].caption)
              and all(m.caption is None for m in media[1:]))

    setup([("-100111", "Kanal A")], premium=False)
    ctx = SimpleNamespace(user_data={}, bot=FakeBot())
    await asyncio.gather(*(clf.post_received(upd(Msg(i, "preview")), ctx) for i in (601, 602)))
    await clf._ALBUMS.wait_idle()
    check("Free preview is one album with signature and watermark",
          len(ctx.bot.groups) == 1 and SIG in ctx.bot.groups[0][1][0].caption
          and "🤖 @" in ctx.bot.groups[0][1][0].caption)
    check("preview remembers exactly one unified post", len(ctx.user_data[clf._UD_PENDING]) == 1)


asyncio.run(scenario_concurrent_delivery())


async def scenario_enhancer_serial_updates():
    from unittest.mock import AsyncMock, patch
    from handlers import post_enhancer as enh

    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=FakeBot())
    collector = MediaGroupCollector(delay=0.05)
    finish = AsyncMock()
    with patch.object(enh, "_ENH_ALBUMS", collector), patch.object(enh, "_finish_capture", finish):
        # Same order as GuardedApplication: await each handler before the next.
        for mid in (702, 701, 703):
            await asyncio.wait_for(enh.enh_message_received(
                upd(Msg(mid, "enh", kind="video" if mid == 703 else "photo",
                        caption="Album text" if mid == 702 else None)), ctx), timeout=0.04)
        check("enhancer returns before debounce without finalizing partial posts", finish.await_count == 0)
        await collector.wait_idle()
        post = enh._payload(ctx)["post"]
        check("enhancer finalizes serial updates exactly once", finish.await_count == 1)
        check("enhancer keeps all files and album caption",
              post["type"] == "album" and len(json.loads(post["file_id"])) == 3
              and post["content"] == "Album text")


asyncio.run(scenario_enhancer_serial_updates())

async def scenario_manual_album_preview():
    from unittest.mock import AsyncMock, patch
    from handlers import manual_post as mp
    from locales.translations import get_text

    ack_prefix = get_text("np_album_received", "uz").split("{")[0].strip()
    ctx = SimpleNamespace(user_data={"lang": "uz"}, bot=FakeBot(), _user_id=7, chat_id=42)
    with patch.object(mp, "_MANUAL_ALBUM_WAIT_SECONDS", 0.05):
        messages = [Msg(803, "manual", kind="video"),
                    Msg(801, "manual", caption="Manual caption"),
                    Msg(802, "manual"), Msg(802, "manual")]
        await asyncio.gather(*(mp.manual_content_received(upd(m), ctx) for m in messages))
        check("manual handler does not preview an incomplete album",
              not ctx.bot.groups and not ctx.bot.cards and not ctx.bot.texts)
        await asyncio.gather(*list(mp._MANUAL_ALBUM_TASKS.values()))
    # 🖼 BIRLASHTIRILGAN (UNIFIED) PREVIEW: media + caption + boshqaruv
    # tugmalari BITTA xabarda chiqadi — media fayllar va menyu ikki alohida
    # (uzilgan) xabarga AJRATILMAYDI.
    check("manual collector sends exactly ONE unified album preview",
          len(ctx.bot.cards) == 1 and not ctx.bot.texts,
          f"cards={ctx.bot.cards} texts={ctx.bot.texts}")
    check("album media is NOT detached into a separate media-group message",
          ctx.bot.groups == [], str(ctx.bot.groups)[:160])
    card = ctx.bot.cards[0] if ctx.bot.cards else {}
    check("unified preview renders the album cover media",
          card.get("kind") == "photo" and card.get("file_id") == "F801", str(card)[:160])
    check("unified preview carries the control buttons",
          card.get("reply_markup") is not None, str(card.get("reply_markup"))[:120])
    check("album ack (file count) lives in the SAME caption",
          ack_prefix in (card.get("caption") or "")
          and "3" in (card.get("caption") or ""),
          str(card.get("caption"))[:160])
    draft = json.loads(ctx.user_data.get(mp.UD_ALBUM_ITEMS) or "[]")
    check("manual album sorted and duplicate update ignored",
          [i.get("file_id") for i in draft] == ["F801", "F802", "F803"], str(draft)[:160])
    check("manual caption belongs to the entire album",
          draft and draft[0]["caption"] == "Manual caption"
          and all(i["caption"] == "" for i in draft[1:]), str(draft)[:160])
    check("unified caption keeps the album caption",
          "Manual caption" in (card.get("caption") or ""), str(card.get("caption"))[:160])
    check("whole album stays in the draft (no file is lost)",
          ctx.user_data.get(mp.UD_POST_TYPE) == "album" and len(draft) == 3, str(draft)[:120])

    target = SimpleNamespace(reply_photo=AsyncMock(), reply_video=AsyncMock(),
                             reply_document=AsyncMock(), reply_animation=AsyncMock(),
                             reply_media_group=AsyncMock(), reply_text=AsyncMock())
    await mp._show_preview(target, ctx, "uz")
    check("manual preview screen renders ONE unified card (cover + caption + buttons)",
          target.reply_photo.await_count == 1
          and target.reply_photo.await_args.kwargs.get("reply_markup") is not None
          and "Manual caption" in (target.reply_photo.await_args.kwargs.get("caption") or ""),
          str(target.reply_photo.await_args)[:200])
    check("album controls are NOT detached into a second message",
          target.reply_text.await_count == 0
          and target.reply_media_group.await_count == 0,
          f"text={target.reply_text.await_count} group={target.reply_media_group.await_count}")


asyncio.run(scenario_manual_album_preview())


async def scenario_real_debounce_window():
    delivered = []
    collector = MediaGroupCollector()

    async def ready(items):
        delivered.append(items)

    collector.add("real-window", {"message_id": 1}, ready)
    await asyncio.sleep(1.0)
    last_arrival = time.monotonic()
    collector.add("real-window", {"message_id": 2}, ready)
    await asyncio.sleep(1.0)
    # 2.0s debounce: ikkinchi fayldan keyin 1.0s jimlik hali YETARLI EMAS.
    check("new update extends debounce beyond 2.0s from first arrival", not delivered)
    await collector.wait_idle()
    check("one album emitted after 2.0s of silence",
          len(delivered) == 1 and len(delivered[0]) == 2
          and time.monotonic() - last_arrival >= 2.0)


asyncio.run(scenario_real_debounce_window())

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
