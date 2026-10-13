"""📢 «KANALGA YUBORISH» — kanal tanlash va aniq nishon xabari.

Qoidalar:
  * bitta ulangan kanal → tanlovsiz, darhol shu kanalga yuboriladi;
  * bir nechta kanal → inline tanlov (har biri alohida + «Barcha kanallarga»);
  * yuborilgach xabarda kanal NOMI va USERNAME'i aniq ko'rsatiladi:
    ``✅ Post "Jizzax Yangiliklari" (@jizzax_ch) kanaliga yuborildi!``

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/channel_send_notice_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("BOT_TOKEN", "123456:CHANNEL_NOTICE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


from handlers import magic_post as mp  # noqa: E402
from utils.channel_labels import (  # noqa: E402
    channel_label,
    channel_label_html,
    channel_row,
    channel_username,
    sent_notice,
)

print("== kanal yorlig'i ==")
check("username: @ bilan", channel_username("@jizzax_ch") == "@jizzax_ch")
check("username: @ siz", channel_username("jizzax_ch") == "@jizzax_ch")
check("username: raqamli ID ko'rsatilmaydi", channel_username("-1001234567890") == "")
check("username: bo'sh", channel_username(None) == "")
check("yorliq: nom + username",
      channel_label("@jizzax_ch", "Jizzax Yangiliklari") == '"Jizzax Yangiliklari" (@jizzax_ch)')
check("yorliq: yopiq kanal — faqat nom (ID oshkor qilinmaydi)",
      channel_label("-1001234567890", "Yopiq kanal") == '"Yopiq kanal"')
check("yorliq: sarlavha o'rniga ID saqlangan — takrorlanmaydi",
      channel_label("@jizzax_ch", "@jizzax_ch") == "@jizzax_ch")
check("yorliq: nom ham, username ham yo'q", channel_label("-100123", "") == '"Kanal"')
check("yorliq HTML-xavfsiz",
      channel_label_html("@x_channel", "A <b>&</b>") == '"A &lt;b&gt;&amp;&lt;/b&gt;" (@x_channel)')
check("channel_row: tuple", channel_row(("@a_chan", "A")) == ("@a_chan", "A"))
check("channel_row: dict", channel_row({"channel_id": "@a_chan", "channel_title": "A"}) == ("@a_chan", "A"))

print("== xabar matni (uz/ru/en) ==")
one = '"Jizzax Yangiliklari" (@jizzax_ch)'
check("uz: bitta kanal",
      sent_notice("uz", [one]) == f"✅ Post {one} kanaliga yuborildi!", sent_notice("uz", [one]))
check("ru: bitta kanal", "канал" in sent_notice("ru", [one]) and one in sent_notice("ru", [one]))
check("en: bitta kanal", "channel" in sent_notice("en", [one]) and one in sent_notice("en", [one]))
many = sent_notice("uz", [one, '"Boshqa" (@boshqa_ch)'])
check("uz: ko'p kanal — soni va ikkala yorliq",
      "2 ta" in many and one in many and "@boshqa_ch" in many, many)
check("ko'p kanal: 10 tadan ortig'i qisqartiriladi",
      "+2" in sent_notice("uz", [f'"K{i}"' for i in range(12)]))


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id=None, text=None, parse_mode=None, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text})
        return SimpleNamespace(message_id=len(self.sent))


class FakeQuery:
    def __init__(self, data, user_id=777000):
        self.data = data
        self.from_user = SimpleNamespace(id=user_id)
        self.message = SimpleNamespace(chat_id=1, message_id=1)
        self.edits = []

    async def answer(self, *a, **k):
        pass

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        self.edits.append({"text": text, "reply_markup": reply_markup})


class FakeContext:
    def __init__(self, lang="uz"):
        self.user_data = {"lang": lang, "magic_post_text": "Salom post",
                          "magic_usage_counted": True}
        self.bot = FakeBot()


def upd(query):
    return SimpleNamespace(callback_query=query, message=None,
                           effective_user=SimpleNamespace(id=query.from_user.id))


def with_channels(channels):
    async def fake_run_db(func, *a, **kw):
        return list(channels) if func.__name__ == "get_user_channels" else None
    return patch("handlers.magic_post.db.run_db", new=fake_run_db)


def buttons(markup):
    return [(b.text, b.callback_data) for row in (markup.inline_keyboard if markup else []) for b in row]


print("== bitta kanal: tanlovsiz darhol yuborish ==")
ctx = FakeContext()
q = FakeQuery("mp_send")
with with_channels([("@jizzax_ch", "Jizzax Yangiliklari")]):
    state = asyncio.run(mp.magic_send_now_callback(upd(q), ctx))
check("sessiya tugadi", state == mp.ConversationHandler.END)
check("faqat shu kanalga yuborildi",
      len(ctx.bot.sent) == 1 and ctx.bot.sent[0]["chat_id"] == "@jizzax_ch", str(ctx.bot.sent))
check("tanlov klaviaturasi chiqmadi", all(e["reply_markup"] is None for e in q.edits), str(q.edits))
check("xabarda kanal nomi va username'i aniq ko'rsatilgan",
      q.edits and q.edits[-1]["text"] == '✅ Post "Jizzax Yangiliklari" (@jizzax_ch) kanaliga yuborildi!',
      str(q.edits[-1:]))

print("== bir nechta kanal: inline tanlov ==")
CHANNELS = [("@jizzax_ch", "Jizzax Yangiliklari"), ("-1009990001", "Yopiq kanal")]
ctx = FakeContext()
q = FakeQuery("mp_send")
with with_channels(CHANNELS):
    state = asyncio.run(mp.magic_send_now_callback(upd(q), ctx))
check("tanlov holati", state == mp.MAGIC_SEND_CHOOSE)
check("hech narsa yuborilmadi (avval tanlanadi)", ctx.bot.sent == [])
btns = buttons(q.edits[-1]["reply_markup"])
check("har bir kanal uchun alohida tugma + «Barcha kanallarga»",
      [d for _t, d in btns if d.startswith("mp_ch")] == ["mp_ch:0", "mp_ch:1", "mp_chall"], str(btns))

q2 = FakeQuery("mp_ch:0")
with with_channels(CHANNELS):
    state = asyncio.run(mp.magic_channel_picked_callback(upd(q2), ctx))
check("tanlangan kanalga yuborildi",
      len(ctx.bot.sent) == 1 and ctx.bot.sent[0]["chat_id"] == "@jizzax_ch", str(ctx.bot.sent))
check("tanlangan kanal nomi + username xabarda",
      '"Jizzax Yangiliklari" (@jizzax_ch)' in q2.edits[-1]["text"], q2.edits[-1]["text"])

ctx = FakeContext()
ctx.user_data["magic_channels"] = CHANNELS
q3 = FakeQuery("mp_chall")
with with_channels(CHANNELS):
    asyncio.run(mp.magic_channel_picked_callback(upd(q3), ctx))
text = q3.edits[-1]["text"]
check("«Barcha kanallarga»: ikkala kanalga yuborildi", len(ctx.bot.sent) == 2, str(ctx.bot.sent))
check("«Barcha kanallarga»: xabarda ikkala kanal, yopiq kanalning raqamli ID'si ko'rinmaydi",
      '"Jizzax Yangiliklari" (@jizzax_ch)' in text and '"Yopiq kanal"' in text
      and "-1009990001" not in text, text)

ctx = FakeContext(lang="ru")
q4 = FakeQuery("mp_send")
with with_channels([("@jizzax_ch", "Jizzax Yangiliklari")]):
    asyncio.run(mp.magic_send_now_callback(upd(q4), ctx))
check("ru: xabar ruscha va kanal yorlig'i bor",
      "канал" in q4.edits[-1]["text"] and "@jizzax_ch" in q4.edits[-1]["text"], q4.edits[-1]["text"])

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
