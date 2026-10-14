#!/usr/bin/env python3
"""Post `failed` / `unknown` bo'lganda EGASIGA xabar (real PostgreSQL, faqat sinov bazasi) — audit D-4.

Oldin doimiy xato / noaniq yetkazish faqat logga yozilardi: foydalanuvchi postining nima bo'lganini bilmasdi.
Yetkazish yo'llariga TEGILMAYDI: `notify_post_problems(bot)` davriy ish yaqinda `dead_letter` / `unknown` bo'lgan yetkazishlarni topadi.
Telegram yuborish natijasi noaniq bo'lishi mumkin; bu test exactly-once VA'DA QILMAYDI.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_notify")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


print("== Post muammosi: egasiga xabar (real PG) ==")

# --- Matnlar uch tilda (DB shart emas) ---
from locales.translations import get_text  # noqa: E402

KEYS = ("post_problem_header", "post_problem_line", "post_problem_footer_failed", "post_problem_footer_unknown",
        "post_problem_reason_rights", "post_problem_reason_format", "post_problem_reason_network",
        "post_problem_reason_unknown", "post_problem_reason_generic")
for lang in ("uz", "ru", "en"):
    missing = [k for k in KEYS if get_text(k, lang) == k]
    check(f"[{lang}] barcha post_problem_* matnlari mavjud", not missing, str(missing))
# `post_problem_line` — tilga bog'liq bo'lmagan tuzilma shabloni (faqat {channel}/{preview}/{reason}); qolganlari tarjima qilingan.
same = [k for k in KEYS if k != "post_problem_line" and len({get_text(k, lang) for lang in ("uz", "ru", "en")}) < 3]
check("uz/ru/en matnlari bir-biridan farq qiladi (tarjima qilingan)", not same, str(same))

if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q — DB qismi o'tkazildi")
    print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=1")
    sys.exit(0 if failed == 0 else 1)

from telegram.error import Forbidden  # noqa: E402

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

import scheduler as sched  # noqa: E402

USER, CHAN = 9_601_000, "-1009601000"
USER_B, CHAN_B = 9_601_001, "-1009601001"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    for uid in (USER, USER_B):
        q("DELETE FROM post_deliveries WHERE post_id IN (SELECT id FROM scheduled_posts WHERE user_id = %s)", (uid,))
        q("DELETE FROM scheduled_posts WHERE user_id = %s", (uid,))
        q("DELETE FROM channels WHERE user_id = %s", (uid,))
        q("DELETE FROM users WHERE user_id = %s", (uid,))


class Bot:
    def __init__(self, raises=None):
        self.sent = []
        self.raises = raises

    async def send_message(self, chat_id, text, **kw):
        if self.raises:
            raise self.raises
        self.sent.append((chat_id, text))


def mk_post(uid, chan, text, post_status, dstatus, err, age_seconds=5):
    pid = int(db.add_post(uid, chan, "text", text, None, datetime.now(timezone.utc)))
    q("UPDATE scheduled_posts SET status = %s WHERE id = %s", (post_status, pid))
    key = f"post_{pid}_{chan}_notify"
    q("INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, last_error, updated_at) "
      "VALUES (%s, %s, %s, %s, %s, NOW() - (%s || ' seconds')::INTERVAL)",
      (pid, int(chan), dstatus, key, err, str(age_seconds)))
    return pid


def run(bot):
    return asyncio.run(sched.notify_post_problems(bot))


cleanup()
try:
    q("INSERT INTO users (user_id, username, plan_type, language_code) VALUES (%s, %s, 'free', 'ru')", (USER, "notify_ru"))
    q("INSERT INTO users (user_id, username, plan_type, language_code) VALUES (%s, %s, 'free', 'uz')", (USER_B, "notify_uz"))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'Kanal <A>', TRUE)", (USER, CHAN))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'Kanal B', TRUE)", (USER_B, CHAN_B))
    sched._PROBLEM_NOTIFIED.clear()

    # 1) ikki muammoli post (huquq + noaniq) -> BITTA guruhlangan xabar, egasining tilida (ru), HTML escape
    p1 = mk_post(USER, CHAN, "Birinchi <b>post", "failed", "dead_letter", "Forbidden: bot was kicked from the channel chat")
    p2 = mk_post(USER, CHAN, "Ikkinchi post", "unknown", "unknown", "TimedOut: album")
    bot = Bot()
    n = run(bot)
    check("2 ta muammoli post egasiga BITTA xabar bilan (guruhlangan)", len(bot.sent) == 1 and bot.sent[0][0] == USER, str(bot.sent)[:200])
    text = bot.sent[0][1] if bot.sent else ""
    check("xabar egasining tilida (ru)", get_text("post_problem_reason_rights", "ru") in text, text[:300])
    check("noaniq yetkazish sababi ham bor", get_text("post_problem_reason_unknown", "ru") in text)
    check("kanal nomi va post matni HTML-escape qilingan (xom '<A>' / '<b>' yo'q)", "<A>" not in text and "&lt;A&gt;" in text and "<b>post" not in text, text[:300])
    check("notify_post_problems xabar yuborilgan postlar sonini qaytaradi", n == 2, str(n))

    # 2) ikkinchi ishga tushirish -> takroriy xabar YO'Q
    bot2 = Bot()
    run(bot2)
    check("takroriy ishga tushirishda yana xabar yuborilmaydi (dedup)", bot2.sent == [], str(bot2.sent))

    # 3) eski yozuv (1 soat oldin) e'tiborsiz
    mk_post(USER_B, CHAN_B, "Eski post", "failed", "dead_letter", "BadRequest: Wrong URL host", age_seconds=3600)
    bot3 = Bot()
    run(bot3)
    check("1 soat oldingi muammo uchun xabar yuborilmaydi (lookback)", bot3.sent == [], str(bot3.sent))

    # 4) yangi, boshqa foydalanuvchi (uz) + format sababi
    mk_post(USER_B, CHAN_B, "Format post", "failed", "dead_letter", "BadRequest: Can't parse entities")
    bot4 = Bot()
    run(bot4)
    check("boshqa foydalanuvchiga uz tilida, format sababi bilan",
          len(bot4.sent) == 1 and bot4.sent[0][0] == USER_B and get_text("post_problem_reason_format", "uz") in bot4.sent[0][1],
          str(bot4.sent)[:200])

    # 5) post allaqachon qayta rejalangan ('pending') bo'lsa xabar yo'q
    mk_post(USER_B, CHAN_B, "Qayta rejalangan", "pending", "dead_letter", "BadRequest: x")
    bot5 = Bot()
    run(bot5)
    check("post 'failed'/'unknown' emas (qayta rejalangan) -> xabar yo'q", bot5.sent == [], str(bot5.sent))

    # 6) bot bloklangan (Forbidden) -> istisno chiqmaydi, qayta-qayta urinilmaydi
    mk_post(USER_B, CHAN_B, "Bloklangan", "failed", "dead_letter", "Forbidden: bot was kicked")
    bot6 = Bot(raises=Forbidden("bot was blocked by the user"))
    try:
        run(bot6)
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", type(exc).__name__, exc)
    check("foydalanuvchi botni bloklagan bo'lsa job qulamaydi", ok)
    bot7 = Bot()
    run(bot7)
    check("bloklangan foydalanuvchiga qayta-qayta urinilmaydi", bot7.sent == [], str(bot7.sent))
finally:
    sched._PROBLEM_NOTIFIED.clear()
    cleanup()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
