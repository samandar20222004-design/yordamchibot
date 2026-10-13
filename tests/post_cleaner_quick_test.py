"""🧹 Tezkor post tozalash: dvigatel (oxirini tozalash + imzo) va handler oqimi."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from telegram import MessageEntity  # noqa: E402

from services import post_cleaner as pc  # noqa: E402
from handlers import post_cleaner_flow as clf  # noqa: E402

failures = 0


def check(name, cond, extra=""):
    global failures
    print(f"  [{'OK' if cond else 'FAIL'}] {name} {'' if cond else extra}")
    failures += 0 if cond else 1


SIG = '<a href="https://t.me/mening_kanalim">📢 Bizning kanal</a>'
OWN = frozenset({"mening_kanalim"})


def test_engine():
    print("== Dvigatel: faqat oxiri tozalanadi ==")
    body = "Bugun dollar kursi 12 650 so'm.\nMarkaziy bank ma'lumoti."
    post = body + "\n\n➖➖➖\n👉 Obuna bo'ling: @kun_uz\nReklama: @promo_bot\nt.me/kun_uz"
    r = pc.quick_clean(post, None, SIG, OWN)
    check("oxiridagi reklama qatorlari olib tashlandi", r.removed_lines == 4, str(r))
    check("post matni o'zgarmadi + imzo oxirida", r.html == f"{body}\n\n{SIG}", r.html)

    clean = "Ob-havo yaxshi.\nQuyoshli kun."
    r = pc.quick_clean(clean, None, SIG, OWN)
    check("toza post: hech narsa olinmaydi", r.removed_lines == 0)
    check("toza post: faqat imzo qo'shiladi", r.html == f"{clean}\n\n{SIG}", r.html)

    inner = "Ma'lumot @kun_uz da chiqdi va ko'p muhokama bo'ldi.\nOxirgi gap."
    r = pc.quick_clean(inner, None, SIG, OWN)
    check("matn ichidagi @eslatma tegilmaydi", r.html.startswith(inner), r.html)

    own_tail = "Post matni.\n@mening_kanalim"
    r = pc.quick_clean(own_tail, None, SIG, OWN)
    check("o'z kanali havolasi olinmaydi", r.removed_lines == 0 and "@mening_kanalim\n\n" in r.html, r.html)

    only_junk = "@foo_news"
    r = pc.quick_clean(only_junk, None, SIG, OWN)
    check("butun post 'reklama' bo'lsa ham o'chmaydi (fail-safe)", r.html.startswith("@foo_news"), r.html)

    code_tail = "Misol:\n@kun_uz"
    ents = [MessageEntity("code", 7, 7)]
    r = pc.quick_clean(code_tail, ents, SIG, OWN)
    check("kod ichidagi qator tozalanmaydi", r.removed_lines == 0 and "<code>@kun_uz</code>" in r.html, r.html)

    bold = "Muhim xabar matni\nManba: t.me/x_news"
    r = pc.quick_clean(bold, [MessageEntity("bold", 0, 5)], SIG, OWN)
    check("formatlash saqlanadi (bold)", r.html.startswith("<b>Muhim</b> xabar matni\n\n"), r.html)

    hidden = "Yangilik.\nBizning kanal"
    r = pc.quick_clean(hidden, [MessageEntity("text_link", 10, 13, url="https://t.me/foo")], SIG, OWN)
    check("yashirin begona havolali oxirgi qator olinadi", r.removed_lines == 1, r.html)

    already = pc.quick_clean("Post.\n\n📢 Bizning kanal", None, SIG, OWN)
    check("qayta yuborilgan postda imzo bitta bo'ladi",
          already.html.count("Bizning kanal") == 1, already.html)
    again = pc.quick_clean("Post.\n\nMening imzom", None, "Mening imzom", OWN)
    check("imzo allaqachon oxirida bo'lsa takrorlanmaydi",
          not again.signature_added and again.html.count("Mening imzom") == 1, again.html)

    emoji = pc.quick_clean("😀", None, "", OWN)
    check("uzunlik UTF-16 da hisoblanadi (emoji = 2)", emoji.length == 2, str(emoji.length))


def test_signature():
    print("== Imzo: cheklov va xavfsizlik ==")
    check("10 qatordan ortiq — rad", "lines" in pc.signature_problems("\n".join(["a"] * 11)))
    check("10 qator — ruxsat", not pc.signature_problems("\n".join(["a"] * 10)))
    check("300 so'zdan ortiq — rad", "words" in pc.signature_problems("so'z " * 301))
    check("2000 belgidan ortiq — rad", "chars" in pc.signature_problems("a" * 2001))
    check("@kanal → https://t.me/kanal", pc.link_to_url("@kanal_uz") == "https://t.me/kanal_uz")
    check("t.me/x → https://t.me/x", pc.link_to_url("t.me/abcd") == "https://t.me/abcd")
    check("javascript: rad etiladi", pc.link_to_url("javascript:alert(1)") == "")
    html, has_link = pc.signature_from_message(
        "Kanal <b>", [MessageEntity("text_link", 0, 5, url="javascript:x")])
    check("xavfli havola olib tashlanadi, matn escape qilinadi",
          html == "Kanal &lt;b&gt;" and not has_link, html)
    html, has_link = pc.signature_from_message("Kanal", [MessageEntity("text_link", 0, 5, url="https://t.me/k")])
    check("havolali so'z saqlanadi", has_link and html == '<a href="https://t.me/k">Kanal</a>', html)
    check("matnga havola ulash", pc.wrap_signature_link("Bizga qo'shiling", "https://t.me/a")
          == '<a href="https://t.me/a">Bizga qo\'shiling</a>')


# ---------------------------------------------------------------- handlerlar
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(("text", chat_id, text, kw.get("reply_markup")))
        return FakeMessage(self)

    async def send_photo(self, chat_id, file_id, caption=None, **kw):
        self.sent.append(("photo", chat_id, caption, kw.get("reply_markup")))
        return FakeMessage(self)


class FakeMessage:
    def __init__(self, bot, text=None, caption=None, photo=None, media_group_id=None):
        self.bot, self.text, self.caption = bot, text, caption
        self.photo, self.media_group_id = photo, media_group_id
        self.entities = self.caption_entities = ()
        self.chat_id = 42
        self.replies, self.edits = [], []
        for kind in ("video", "animation", "document", "audio", "voice"):
            setattr(self, kind, None)

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        return self

    async def edit_text(self, text, **kw):
        self.edits.append(text)


def _setup(channels, autosend=False, guard=True):
    calls = {"add_post": [], "deliver": 0}

    async def run_db(func, *args, **kwargs):
        return func(*args, **kwargs)

    fake_db = SimpleNamespace(
        run_db=run_db,
        get_user_post_signature_html=lambda uid: SIG,
        get_user_setting=lambda uid, key, default=False: autosend,
        get_user_channels=lambda uid: channels,
        is_premium=lambda uid: True,
        add_post=lambda **kw: calls["add_post"].append(kw) or 99,
        get_post_status=lambda pid, uid: "posted",
    )
    clf.db = fake_db

    async def own(uid):
        return OWN

    async def lang(context, uid):
        return "uz"

    async def guard_fn(uid, channel_id, action="create"):
        return guard

    clf.own_channel_usernames = own
    clf._lang = lang
    import handlers.manual_post as mp
    mp.manual_channel_guard = guard_fn
    import utils.handler_timeout as ht

    def run_bg(coro, name=None, **kw):
        calls["deliver"] += 1
        coro.close()

    ht.run_background_task = run_bg
    return calls


def _update(message):
    return SimpleNamespace(message=message, effective_user=SimpleNamespace(id=7),
                           effective_message=message, effective_chat=SimpleNamespace(id=42))


def test_handlers():
    print("== Handler: tozalash rejimi ==")
    bot = FakeBot()
    calls = _setup([("-100111", "Kanal A")], autosend=True)
    context = SimpleNamespace(user_data={}, bot=bot)
    msg = FakeMessage(bot, text="Yangilik matni.\nReklama: @promo_bot")
    state = asyncio.run(clf.post_received(_update(msg), context))
    check("rejim davom etadi", state == clf.CLEANER_POST_INPUT)
    check("darhol yuborish: bitta kanalga add_post", len(calls["add_post"]) == 1, str(calls))
    sent = calls["add_post"][0] if calls["add_post"] else {}
    check("kanalga tozalangan matn + imzo ketadi",
          sent.get("content") == f"Yangilik matni.\n\n{SIG}" and sent.get("post_type") == "text", str(sent))
    check("yetkazish darhol boshlandi", calls["deliver"] == 1)

    calls = _setup([("-100111", "Kanal A"), ("-100222", "Kanal B")], autosend=True)
    context = SimpleNamespace(user_data={}, bot=bot)
    bot.sent.clear()
    msg = FakeMessage(bot, text="Post.")
    asyncio.run(clf.post_received(_update(msg), context))
    check("bir nechta kanal: avtomatik yuborilmaydi", not calls["add_post"])
    markup = bot.sent[-1][3] if bot.sent else None
    buttons = [b.callback_data for row in markup.inline_keyboard for b in row] if markup else []
    check("bir nechta kanal: har biriga tugma", buttons == ["stgs_clean_pub:" + buttons[0].split(":")[1] + ":0",
                                                            "stgs_clean_pub:" + buttons[0].split(":")[1] + ":1"]
          if buttons else False, str(buttons))

    query = SimpleNamespace(data=buttons[1], from_user=SimpleNamespace(id=7), message=msg,
                            answers=[])

    async def answer(text=None, show_alert=False):
        query.answers.append(text)

    async def edit_markup(reply_markup=None):
        return None

    query.answer, query.edit_message_reply_markup = answer, edit_markup
    asyncio.run(clf.publish_callback(SimpleNamespace(callback_query=query), context))
    check("tugma: tanlangan kanalga yuboriladi",
          calls["add_post"] and calls["add_post"][0]["channel_id"] == "-100222", str(calls["add_post"]))
    asyncio.run(clf.publish_callback(SimpleNamespace(callback_query=query), context))
    check("ikkinchi bosish: qayta yuborilmaydi", len(calls["add_post"]) == 1, str(calls["add_post"]))

    calls = _setup([("-100111", "Kanal A")], autosend=True, guard=False)
    context = SimpleNamespace(user_data={}, bot=bot)
    msg = FakeMessage(bot, text="Post.")
    asyncio.run(clf.post_received(_update(msg), context))
    check("kanalga ruxsat yo'q: yuborilmaydi", not calls["add_post"])

    calls = _setup([("-100111", "Kanal A")], autosend=True)
    context = SimpleNamespace(user_data={}, bot=bot)
    msg = FakeMessage(bot, text="a" * 4090)
    asyncio.run(clf.post_received(_update(msg), context))
    check("limitdan oshsa: yuborilmaydi va tushuntiriladi",
          not calls["add_post"] and msg.replies and "4096" in msg.replies[-1], str(msg.replies))

    photo = [SimpleNamespace(file_id="F1")]
    msg = FakeMessage(bot, caption="b" * 1010, photo=photo)
    asyncio.run(clf.post_received(_update(msg), context))
    check("rasm izohi 1024 limiti bilan tekshiriladi",
          not calls["add_post"] and "1024" in msg.replies[-1], str(msg.replies))

    calls = _setup([("-100111", "Kanal A")], autosend=True)
    context = SimpleNamespace(user_data={}, bot=bot)
    msg = FakeMessage(bot, caption="x", photo=photo, media_group_id="g1")
    asyncio.run(clf.post_received(_update(msg), context))
    check("albom: handler darhol qaytadi, fayl alohida post bo'lmaydi (fonda yig'iladi)",
          not calls["add_post"] and clf._ALBUMS.is_collecting((7, "g1")))
    clf._ALBUMS.cancel((7, "g1"))


if __name__ == "__main__":
    test_engine()
    test_signature()
    test_handlers()
    print(f"JAMI xato: {failures}")
    sys.exit(1 if failures else 0)
