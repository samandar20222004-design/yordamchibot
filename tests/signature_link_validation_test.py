"""✍️ Imzo / havola saqlash — Telegram kanal havolalari va formatlangan matn qabul qilinadi.

Muammo: «Sozlamalar → Post tozalash va imzo»da kanal havolasi
(``https://t.me/mirzachollgagarin``, ``@mirzachollgagarin``) yoki formatlangan
matn yuborilganda «❌ Saqlab bo'lmadi» chiqmasligi kerak.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/signature_link_validation_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:SIGNATURE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from telegram import MessageEntity as ME  # noqa: E402

from handlers import post_cleaner_flow as clf  # noqa: E402
from services import post_cleaner as pc  # noqa: E402
from translations import settings_stats_t as t  # noqa: E402

passed = failures = 0


def check(name, cond, extra=""):
    global passed, failures
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


LINK = "https://t.me/mirzachollgagarin"

print("== link_to_url: qabul qilinadigan ko'rinishlar ==")
for raw, expected in (
    (LINK, LINK),
    ("@mirzachollgagarin", LINK),
    ("t.me/mirzachollgagarin", LINK),
    ("http://t.me/mirzachollgagarin", "http://t.me/mirzachollgagarin"),
    ("telegram.me/mirzachollgagarin", "https://telegram.me/mirzachollgagarin"),
    ("  https://t.me/mirzachollgagarin  ", LINK),
    ("<https://t.me/mirzachollgagarin>", LINK),
    ("(t.me/mirzachollgagarin).", LINK),
    ('"@mirzachollgagarin"', LINK),
    ("https://t.me/mirzachollgagarin/", LINK + "/"),
    ("https://t.me/+AbCdEf12", "https://t.me/+AbCdEf12"),
    ("https://t.me/mirzachollgagarin/123", LINK + "/123"),
    ("example.com", "https://example.com"),
    ("www.example.uz/yol?x=1", "https://www.example.uz/yol?x=1"),
    ("tg://resolve?domain=mirzachollgagarin", "tg://resolve?domain=mirzachollgagarin"),
):
    check(f"link_to_url({raw!r})", pc.link_to_url(raw) == expected, pc.link_to_url(raw))

print("== link_to_url: rad etiladiganlar ==")
for raw in ("javascript:alert(1)", "data:text/html,x", "ftp://x.com/a", "vbscript:x",
            "salom dunyo", "@abc", "", "   ", None, "http://"):
    check(f"rad: {raw!r}", pc.link_to_url(raw) == "", repr(pc.link_to_url(raw)))

print("== find_link_url: izoh bilan yozilgan havola ==")
check("«👉 Obuna: @kanal»", pc.find_link_url("👉 Obuna: @mirzachollgagarin") == LINK)
check("«Bizning kanal: https://t.me/x_kanal»",
      pc.find_link_url("Bizning kanal: https://t.me/x_kanal") == "https://t.me/x_kanal")
check("havolasiz matn → bo'sh", pc.find_link_url("Salom, bu oddiy matn") == "")
check("xavfli sxema o'tmaydi", pc.find_link_url("bosing javascript:alert(1)") == "")

print("== signature_problems: havola cheklovga to'sqinlik qilmaydi ==")
for raw in (LINK, "@mirzachollgagarin", "t.me/mirzachollgagarin"):
    check(f"cheklov: {raw}", pc.signature_problems(raw) == {})


# ---------------------------------------------------------------- handler oqimi
class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return SimpleNamespace()


class FakeMessage:
    def __init__(self, text, entities=()):
        self.text, self.entities = text, entities
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        return self


def setup(save_ok=True):
    saved = []

    async def run_db(func, *a, **k):
        return func(*a, **k)

    def set_sig(uid, html, plain):
        saved.append((uid, html, plain))
        return save_ok

    clf.db = SimpleNamespace(
        run_db=run_db, set_user_post_signature_html=set_sig,
        get_user_post_signature_html=lambda uid: saved[-1][1] if saved else "",
        get_user_setting=lambda uid, key, default=False: False,
    )

    async def lang(context, uid):
        return "uz"

    clf._lang = lang
    return saved


def run_text(text, entities=(), save_ok=True):
    saved = setup(save_ok)
    bot = FakeBot()
    ctx = SimpleNamespace(user_data={}, bot=bot)
    msg = FakeMessage(text, entities)
    update = SimpleNamespace(message=msg, effective_message=msg,
                             effective_user=SimpleNamespace(id=7),
                             effective_chat=SimpleNamespace(id=42))
    state = asyncio.run(clf.signature_received(update, ctx))
    return state, saved, msg, bot, ctx


REJECTED = t("ss_clean_sig_rejected", "uz")
SAVED = t("ss_cl_sig_saved", "uz")

print("== handler: kanal havolasi birdaniga saqlanadi ==")
for label, text, ents in (
    ("https://t.me/... (url entity)", LINK, [ME("url", 0, len(LINK))]),
    ("https://t.me/... (entity'siz)", LINK, ()),
    ("@mirzachollgagarin (mention entity)", "@mirzachollgagarin", [ME("mention", 0, 18)]),
    ("t.me/mirzachollgagarin", "t.me/mirzachollgagarin", [ME("url", 0, 22)]),
    ("qalin matn + havola", "Obuna: " + LINK, [ME("bold", 0, 6), ME("url", 8, len(LINK))]),
    ("havolali so'z (text_link)", "Bizning kanal", [ME("text_link", 0, 13, url=LINK)]),
):
    state, saved, msg, bot, ctx = run_text(text, ents)
    check(f"{label}: saqlandi", len(saved) == 1, str(saved))
    check(f"{label}: «Saqlab bo'lmadi» chiqmadi", REJECTED not in msg.replies, str(msg.replies))
    check(f"{label}: «saqlandi» xabari", SAVED in msg.replies, str(msg.replies))
    check(f"{label}: oqim tugadi", state == clf.ConversationHandler.END, str(state))

state, saved, msg, bot, ctx = run_text(LINK, [ME("url", 0, len(LINK))])
check("saqlangan HTML: havola ko'rinadi", LINK in saved[0][1], saved[0][1])
check("oddiy matn nusxasi: havola", saved[0][2] == LINK, saved[0][2])

print("== handler: havolasiz matn → havola so'raladi, keyin saqlanadi ==")
state, saved, msg, bot, ctx = run_text("Bizning kanalga qo'shiling")
check("havolasiz: hali saqlanmadi", saved == [], str(saved))
check("havolasiz: havola so'raladi", state == clf.CLEANER_SIGNATURE_LINK, str(state))
setup()
for reply in (LINK, "@mirzachollgagarin", "t.me/mirzachollgagarin", "👉 @mirzachollgagarin",
              "<https://t.me/mirzachollgagarin>"):
    saved = setup()
    ctx2 = SimpleNamespace(user_data={clf._UD_SIG_DRAFT: "Bizning kanalga qo'shiling"}, bot=FakeBot())
    m2 = FakeMessage(reply)
    up2 = SimpleNamespace(message=m2, effective_message=m2, effective_user=SimpleNamespace(id=7),
                          effective_chat=SimpleNamespace(id=42))
    st = asyncio.run(clf.signature_link_received(up2, ctx2))
    check(f"havola javobi {reply!r}: saqlandi, ulanadi",
          len(saved) == 1 and f'<a href="{LINK}">' in saved[0][1], str(saved))
    check(f"havola javobi {reply!r}: oqim tugadi", st == clf.ConversationHandler.END)

saved = setup()
ctx3 = SimpleNamespace(user_data={clf._UD_SIG_DRAFT: "Matn"}, bot=FakeBot())
m3 = FakeMessage("bu havola emas")
st = asyncio.run(clf.signature_link_received(SimpleNamespace(
    message=m3, effective_message=m3, effective_user=SimpleNamespace(id=7),
    effective_chat=SimpleNamespace(id=42)), ctx3))
check("yaroqsiz havola: saqlanmaydi va qayta so'raladi",
      saved == [] and st == clf.CLEANER_SIGNATURE_LINK, str(st))

print("== xavfsizlik: xavfli havola imzoga tushmaydi ==")
state, saved, msg, bot, ctx = run_text("Bosing", [ME("text_link", 0, 5, url="javascript:alert(1)")])
check("javascript: havola olib tashlanadi",
      saved == [] or "javascript" not in saved[0][1], str(saved))

print("== baza yozolmasa: aniq xabar, oqim ochiq qoladi ==")
state, saved, msg, bot, ctx = run_text(LINK, [ME("url", 0, len(LINK))], save_ok=False)
check("DB xatosi: «Saqlab bo'lmadi» + qayta urinish",
      REJECTED in msg.replies and state == clf.CLEANER_SIGNATURE_INPUT, str(msg.replies))

print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
