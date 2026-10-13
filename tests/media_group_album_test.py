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

    async def send_media_group(self, chat_id, media=None, **kw):
        self.groups.append((chat_id, list(media)))
        return [SimpleNamespace(message_id=i) for i in range(len(media))]

    async def send_message(self, chat_id, text, **kw):
        self.texts.append((chat_id, text, kw.get("reply_markup")))
        return FakeSent(self, "text")


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

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
