"""🆓 BEPUL TARIF NISHONI — «🤖 @bot» post OXIRIGA qo'shiladi.

Qoidalar:
  * bepul foydalanuvchi: har bir post (matn/caption/albom) oxiriga ``\\n\\n🤖 @PostAssistrobot``;
  * PRO va admin: post toza;
  * nishon takrorlanmaydi va Telegram limiti (caption 1024) tufayli kesilmaydi.

Ishga tushirish:
    BOT_TOKEN=123456789:TEST_MOCK_TOKEN PYTHONPATH=telegram_bot python3 tests/free_watermark_footer_test.py
"""
import asyncio
import os
import sys
import warnings
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:WATERMARK_TEST_TOKEN")
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


import database as db_mod  # noqa: E402
from config import ADMIN_IDS_SET  # noqa: E402
from scheduler import compose_post_text  # noqa: E402
from utils.helpers import (  # noqa: E402
    apply_post_watermark,
    split_watermark_footer,
    watermark_footer,
    watermark_footer_length,
    watermark_line,
)

BOT = "PostAssistrobot"
LINE = "🤖 @PostAssistrobot"
FREE, PRO = 555, 777
ADMIN = next(iter(ADMIN_IDS_SET), 123456789)

_orig_run_db = db_mod.run_db


async def _fake_run_db(fn, *args, **kwargs):
    if getattr(fn, "__name__", "") == "is_premium":
        return args[0] == PRO
    return await _orig_run_db(fn, *args, **kwargs)


db_mod.run_db = _fake_run_db


def run(coro):
    return asyncio.run(coro)


print("== nishon qatori ==")
check("watermark_line: @ siz username", watermark_line("PostAssistrobot") == LINE)
check("watermark_line: @ bilan username", watermark_line("@PostAssistrobot") == LINE)
check("watermark_line: username bo'sh → nishon yo'q", watermark_line("") == "")
check("watermark_footer: \\n\\n bilan", watermark_footer(BOT) == "\n\n" + LINE)
check("watermark_footer_length: UTF-16 (emoji = 2)", watermark_footer_length(BOT) == 2 + 3 + 16,
      str(watermark_footer_length(BOT)))

print("== bepul / PRO / admin ==")
check("bepul: matn OXIRIGA nishon", run(apply_post_watermark("Salom", FREE, BOT)) == "Salom\n\n" + LINE)
check("bepul: nishon BOSHIGA qo'yilmaydi",
      not run(apply_post_watermark("Salom", FREE, BOT)).startswith("@"))
check("bepul: bo'sh matn → faqat nishon qatori", run(apply_post_watermark("", FREE, BOT)) == LINE)
check("bepul: None matn → faqat nishon qatori", run(apply_post_watermark(None, FREE, BOT)) == LINE)
once = run(apply_post_watermark("Salom\n\n", FREE, BOT))
check("bepul: oxiridagi bo'sh qatorlar tozalanadi", once == "Salom\n\n" + LINE, repr(once))
check("bepul: takrorlanmaydi", run(apply_post_watermark(once, FREE, BOT)) == once)
check("bepul: HTML post ham oxiriga", run(apply_post_watermark("<b>Salom</b>", FREE, BOT))
      == "<b>Salom</b>\n\n" + LINE)
check("bepul: ko'p qatorli matn butun saqlanadi",
      run(apply_post_watermark("1-qator\n2-qator", FREE, BOT)) == "1-qator\n2-qator\n\n" + LINE)
check("PRO: toza", run(apply_post_watermark("Salom", PRO, BOT)) == "Salom")
check("admin: toza", run(apply_post_watermark("Salom", ADMIN, BOT)) == "Salom")
check("PRO: bo'sh matn o'zgarmaydi", run(apply_post_watermark("", PRO, BOT)) == "")

print("== ajratish (split) ==")
check("split: nishon ajraladi", split_watermark_footer("Salom\n\n" + LINE, BOT) == ("Salom", LINE))
check("split: faqat nishon", split_watermark_footer(LINE, BOT) == ("", LINE))
check("split: nishon yo'q", split_watermark_footer("Salom", BOT) == ("Salom", ""))
check("split: o'rtadagi nishon tegilmaydi",
      split_watermark_footer(LINE + "\n\nSalom", BOT) == (LINE + "\n\nSalom", ""))

print("== yetkazish: limit nishonni kesmaydi ==")
long_text = "A" * 5000
for label, limit in (("caption 1024", 1024), ("matn 4096", 4096)):
    body, tail = split_watermark_footer(run(apply_post_watermark(long_text, FREE, BOT)), BOT)
    final = compose_post_text(body, False, "", "", limit=limit, footer=tail)
    check(f"{label}: nishon oxirida saqlanadi", final.endswith("\n\n" + LINE), final[-40:])
    check(f"{label}: limitdan oshmaydi", len(final.encode('utf-16-le')) // 2 <= limit,
          str(len(final.encode('utf-16-le')) // 2))
    check(f"{label}: nishon bitta", final.count("@PostAssistrobot") == 1)

body, tail = split_watermark_footer(run(apply_post_watermark("Salom", FREE, BOT)), BOT)
check("reklama + nishon: tartib (matn → reklama → nishon)",
      compose_post_text(body, False, "REKLAMA", "", limit=1024, footer=tail)
      == "Salom\n\nREKLAMA\n\n" + LINE)
check("admin brendi + nishon: brend, keyin nishon",
      compose_post_text(body, True, "", "@brend", limit=1024, footer=tail)
      == "Salom\n\n@brend\n\n" + LINE)
check("PRO: footer bo'sh → matn toza",
      compose_post_text("Salom", True, "", "", limit=1024, footer="") == "Salom")
check("eski chaqiruv (footer berilmagan) o'zgarmagan",
      compose_post_text("Salom", False, "REKLAMA", "@PostAssistrobot")
      == "Salom\n\nREKLAMA\n\n@PostAssistrobot")

print("== tozalagich: nishon uchun joy qoldiriladi ==")
from handlers.post_cleaner_flow import _load_session  # noqa: E402


def _stub_session(user_id):
    async def go():
        import handlers.post_cleaner_flow as flow
        orig = (flow.db.run_db, flow.own_channel_usernames)

        async def fake_run_db(fn, *a, **k):
            name = getattr(fn, "__name__", "")
            if name == "is_premium":
                return a[0] == PRO
            if name == "get_user_channels":
                return []
            if name == "get_user_post_signature_html":
                return "imzo"
            return False

        async def fake_own(_uid):
            return set()

        flow.db.run_db, flow.own_channel_usernames = fake_run_db, fake_own
        try:
            return await _load_session(user_id)
        finally:
            flow.db.run_db, flow.own_channel_usernames = orig
    return run(go())


from config import BOT_USERNAME  # noqa: E402

check("tozalagich: bepul → zahira = nishon uzunligi",
      _stub_session(FREE)["reserve"] == watermark_footer_length(BOT_USERNAME),
      str(_stub_session(FREE)["reserve"]))
check("tozalagich: PRO → zahira 0", _stub_session(PRO)["reserve"] == 0)

db_mod.run_db = _orig_run_db
print(f"\nNATIJA: [OK]={passed}  [FAIL]={failures}")
sys.exit(1 if failures else 0)
