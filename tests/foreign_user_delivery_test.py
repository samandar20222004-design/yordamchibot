"""Chet eldagi foydalanuvchi: vaqt zonasi eslatmasi, post kanalga chiqmasa SABAB aytiladi, har zonada yetkazish (real PG — FOREIGN_TEST_DATABASE_URL)."""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "telegram_bot"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
PG = os.environ.get("FOREIGN_TEST_DATABASE_URL", "")
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ["DATABASE_URL"] = PG or "postgresql://u:p@localhost:5432/x"

import handlers.manual_post as mp  # noqa: E402
from handlers.timezone_flow import tz_hint  # noqa: E402
from locales.translations import get_text  # noqa: E402
from services.user_timezone import use_tz  # noqa: E402

passed = failed = skipped = 0


def check(name, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [XATO] {name} {extra}")


print("== vaqt zonasi eslatmasi (chet elda vaqt jimgina Toshkent bo'yicha hisoblanmasin) ==")
en_user = SimpleNamespace(language_code="en")
uz_user = SimpleNamespace(language_code="uz")
for lang in ("uz", "ru", "en"):
    hint = tz_hint(en_user, lang)
    check(f"[{lang}] Toshkent standarti + o'zbekcha bo'lmagan Telegram tili -> eslatma (/timezone va zona nomi)", "/timezone" in hint and "Asia/Tashkent" in hint and "UTC+5" in hint, hint)
check("o'zbekcha Telegram tili -> eslatma yo'q", tz_hint(uz_user, "uz") == "")
with use_tz("Europe/Berlin"):
    check("zona tanlangan (Berlin) -> eslatma yo'q", tz_hint(en_user, "en") == "")
check("foydalanuvchi noma'lum -> eslatma (yiqilmaydi)", isinstance(tz_hint(None, "en"), str))

print("== «Hozir yuborish» chiqmasa: aniq SABAB aytiladi ==")
import database as _db_mod  # noqa: E402

_ORIG_RUN_DB = _db_mod.run_db
import scheduler as _sched  # noqa: E402

_ORIG_DELIVER_NOW = _sched.deliver_due_posts_now


class Status:
    def __init__(self):
        self.text = None

    async def edit_text(self, text, **kw):
        self.text = text


async def run_report(status, last_error, lang):
    async def fake_run_db(fn, *a, **k):
        name = getattr(fn, "__name__", "")
        if name == "get_post_status":
            return status
        if name == "get_post_last_error":
            return last_error
        return None

    mp.db.run_db = fake_run_db
    mp._NOW_POLLS = 1
    mp._NOW_POLL_DELAY = 0
    import scheduler

    async def noop(bot):
        return None

    scheduler.deliver_due_posts_now = noop
    st = Status()
    await mp._deliver_now_and_report(None, 7, lang, 11, "Kanal", st)
    return st.text


for lang in ("uz", "ru", "en"):
    rights = get_text("post_problem_reason_rights", lang)
    text = asyncio.run(run_report("failed", "Forbidden: bot is not a member of the channel chat", lang))
    check(f"[{lang}] failed + Forbidden -> «bot admin emas» sababi ko'rinadi", text and rights in text, str(text)[:200])
    text = asyncio.run(run_report("pending", "Forbidden: not enough rights to send messages", lang))
    check(f"[{lang}] navbatda + xato bor -> sabab ko'rinadi", text and rights in text and get_text("post_problem_reason_generic", lang) not in text)
    text = asyncio.run(run_report("failed", "", lang))
    check(f"[{lang}] xato matni yo'q -> eski umumiy xabar (sabab qatori yo'q)", text and "⚠️" not in text)
    text = asyncio.run(run_report("posted", "", lang))
    check(f"[{lang}] posted -> muvaffaqiyat, sabab yo'q", text and "⚠️" not in text)

_db_mod.run_db = _ORIG_RUN_DB
_sched.deliver_due_posts_now = _ORIG_DELIVER_NOW
print("== har zonadagi foydalanuvchi uchun scheduler yetkazadi (real PG) ==")
if not PG:
    skipped += 1
    print("  [SKIP] FOREIGN_TEST_DATABASE_URL yo'q")
else:
    import pytz

    import database as db
    from load_test import FakeBot
    from scheduler import check_and_send_posts
    from services.user_timezone import utz

    db.init_db()

    async def deliver(uid, tzname, country, label):
        db.save_user(uid, f"u{uid}", label)
        with db.db_cursor(commit=True) as cur:
            cur.execute("UPDATE users SET timezone=%s, phone_country=%s WHERE user_id=%s", (tzname, country, uid))
            cur.execute("DELETE FROM scheduled_posts WHERE user_id=%s", (uid,))
        ch = f"-100{uid}"
        db.save_channel(uid, ch, f"Kanal {uid}")
        db.add_post(user_id=uid, channel_id=ch, post_type="text", content=f"HOZIR {label}", file_id=None, scheduled_time=datetime.now(pytz.utc))
        with use_tz(tzname or "Asia/Tashkent"):
            past = utz().localize(datetime.now(utz()).replace(tzinfo=None) - timedelta(minutes=2))
        db.add_post(user_id=uid, channel_id=ch, post_type="text", content=f"MAHALLIY {label}", file_id=None, scheduled_time=past)
        bot = FakeBot()
        await check_and_send_posts(bot)
        return [t for (c, t) in bot.sent if str(c) == ch]

    for uid, tzname, country, label in ((910001, None, None, "UZ"), (910002, "Europe/Berlin", "DE", "DE"), (910003, "America/New_York", "US", "US"),
                                         (910004, None, "US", "US-country"), (910005, "Asia/Tokyo", "JP", "JP"), (910006, "Etc/GMT-3", None, "UTC+3")):
        got = asyncio.run(deliver(uid, tzname, country, label))
        check(f"[{label}] «hozir» va «mahalliy o'tgan vaqt» postlari kanalga chiqdi", len(got) == 2, str(got))

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(1 if failed else 0)
