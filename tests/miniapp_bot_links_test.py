"""Bot <-> Mini App bog'lanishi: bot tugmalari Mini App'ni kerakli bo'limda ochadi, o'chiq bo'lsa hech narsa o'zgarmaydi."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "telegram_bot"))
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:5432/x")
os.environ.pop("MINIAPP_ENABLED", None)
os.environ.pop("MINIAPP_URL", None)

from telegram import InlineKeyboardMarkup  # noqa: E402

from handlers import analytics, queue  # noqa: E402
from keyboards.inline import get_settings_profile_keyboard  # noqa: E402
from locales.translations import get_text  # noqa: E402
from miniapp_api import menu  # noqa: E402

passed = failed = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [XATO] {name} {extra}")


def webapp_urls(markup):
    return [b.web_app.url for row in markup.inline_keyboard for b in row if getattr(b, "web_app", None)]


def enable():
    os.environ["MINIAPP_ENABLED"] = "1"
    os.environ["MINIAPP_URL"] = "https://bot.example.com/app/"
    os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN"
    os.environ["MINIAPP_PROXY_ASSERT_EDGE_ONLY"] = "1"  # prod sozlamasi: HTTPS + ishonchli proksi


def disable():
    os.environ.pop("MINIAPP_ENABLED", None)
    os.environ.pop("MINIAPP_URL", None)
    os.environ.pop("MINIAPP_PROXY_ASSERT_EDGE_ONLY", None)


print("== Mini App o'chiq: bot ekranlari O'ZGARMAYDI ==")
off_settings = get_settings_profile_keyboard("uz")
off_queue = queue._get_queue_list_keyboard([], 0, 0, "uz")
off_an = analytics._get_analytics_view_keyboard(False, "uz")
check("Sozlamalar: 3 qator (6 tugma), web_app yo'q", len(off_settings.inline_keyboard) == 3 and not webapp_urls(off_settings))
check("Rejalashtirilgan ro'yxat: web_app yo'q", not webapp_urls(off_queue))
check("Tahlil: web_app yo'q", not webapp_urls(off_an))
check("miniapp_tab_url / miniapp_button: None", menu.miniapp_tab_url("me") is None and menu.miniapp_button("uz") is None)
check("with_miniapp_row: markup o'zgarishsiz", menu.with_miniapp_row(off_settings, "uz", "me") is off_settings)

print("== Mini App yoqilgan: tugmalar to'g'ri bo'limda ==")
enable()
check("tab=me URL", menu.miniapp_tab_url("me") == "https://bot.example.com/app/?tab=me", str(menu.miniapp_tab_url("me")))
check("tab yo'q: asl URL", menu.miniapp_tab_url() == "https://bot.example.com/app/")
check("noma'lum tab: qo'shilmaydi", menu.miniapp_tab_url("evil") == "https://bot.example.com/app/")
os.environ["MINIAPP_URL"] = "https://bot.example.com/app/?v=2"
check("mavjud query saqlanadi", menu.miniapp_tab_url("post") == "https://bot.example.com/app/?v=2&tab=post", str(menu.miniapp_tab_url("post")))
os.environ["MINIAPP_URL"] = "http://insecure.example.com/app/"
check("http (xavfsiz emas) manzil: tugma YO'Q", menu.miniapp_tab_url("me") is None)
os.environ["MINIAPP_URL"] = "https://bot.example.com/app/"

st = get_settings_profile_keyboard("uz")
check("Sozlamalar: 4-qatorda Mini App (tab=me), asl 3 qator saqlangan",
      len(st.inline_keyboard) == 4 and webapp_urls(st) == ["https://bot.example.com/app/?tab=me"])
q = queue._get_queue_list_keyboard([], 0, 0, "uz")
check("Rejalashtirilgan: Mini App (tab=schedule) Yopish'dan OLDIN",
      webapp_urls(q) == ["https://bot.example.com/app/?tab=schedule"]
      and q.inline_keyboard[-1][0].callback_data == "qclose" and q.inline_keyboard[-2][0].web_app is not None)
an = analytics._get_analytics_view_keyboard(False, "uz")
check("Tahlil: Mini App (tab=me), Orqaga oxirida", webapp_urls(an) == ["https://bot.example.com/app/?tab=me"]
      and an.inline_keyboard[-1][0].callback_data == "an_overview")
for lang in ("uz", "ru", "en"):
    label = menu.miniapp_button(lang, "me").text
    check(f"[{lang}] tugma yorlig'i <=18 belgi va to'ldirilgan", 0 < len(label) <= 18, label)
    check(f"[{lang}] /app matni va 'yoqilmagan' matni bor", bool(get_text("miniapp_app_msg", lang)) and bool(get_text("miniapp_unavailable", lang))
          and get_text("miniapp_app_msg", lang) != get_text("miniapp_unavailable", lang))

print("== /app buyrug'i ==")
from handlers import start as start_mod  # noqa: E402,F401

smod = sys.modules["handlers.start"]


class Msg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, reply_markup=None, **kw):
        self.sent.append((text, reply_markup))


class Upd:
    def __init__(self):
        self.effective_user = type("U", (), {"id": 5})()
        self.message = Msg()


async def fake_lang(context, uid):
    return "uz"


smod.ensure_user_lang = fake_lang
u = Upd()
asyncio.run(smod.app_command(u, object()))
text, kb = u.message.sent[0]
check("/app (yoqilgan): matn + web_app tugma (tab=home)", isinstance(kb, InlineKeyboardMarkup) and webapp_urls(kb) == ["https://bot.example.com/app/?tab=home"], str(kb))
disable()
u = Upd()
asyncio.run(smod.app_command(u, object()))
text, kb = u.message.sent[0]
check("/app (o'chiq): 'yoqilmagan' matni, tugmasiz", kb is None and text == get_text("miniapp_unavailable", "uz"))

import inspect  # noqa: E402

reg = inspect.getsource(sys.modules["handlers"])
check('CommandHandler(["app", "miniapp"], app_command) ro\'yxatga olingan', 'CommandHandler(["app", "miniapp"], app_command)' in reg)

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(1 if failed else 0)
