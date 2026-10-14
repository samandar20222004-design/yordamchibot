#!/usr/bin/env python3
"""`on_channel_post`: Bot API xabarida `views` YO'Q — soxta 0 yozilmaydi (DB'siz) — audit analitika asosi.

Oldin: `views = getattr(msg, "views", 0) or 0` -> har doim 0 ("0 ko'rish" va "ma'lumot yo'q" aralashardi).
Endi: atribut yo'q -> `views=None` (NULL); agar kelajakda mavjud bo'lsa (boshqa transport) -> raqam va manba bilan.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456789:TESTMOCKTOKENabcdefghijklmnopqrstu")
os.environ.setdefault("ADMIN_ID", "111")
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


print("== on_channel_post: halol views (DB'siz) ==")
import handlers.channels as CH  # noqa: E402

calls = []
orig = CH.db.run_db


async def fake_run_db(fn, *a, **k):
    calls.append((getattr(fn, "__name__", ""), k))
    return 1


def update_for(**extra):
    msg = SimpleNamespace(chat=SimpleNamespace(id=-100777), message_id=5, text="Salom kanal", caption=None,
                          date=None, photo=None, video=None, document=None, audio=None, animation=None, **extra)
    return SimpleNamespace(channel_post=msg, edited_channel_post=None, effective_message=msg)


try:
    CH.db.run_db = fake_run_db
    asyncio.run(CH.on_channel_post(update_for(), SimpleNamespace()))
    save = [c for c in calls if c[0] == "save_channel_post_history"]
    check("save_channel_post_history chaqirildi", len(save) == 1, str(calls))
    kw = save[0][1] if save else {}
    check("Bot API xabarida views yo'q -> views=None (soxta 0 EMAS)", kw.get("views", "yo'q") is None, str(kw))
    check("views noma'lum bo'lsa manba berilmaydi", not kw.get("views_source"), str(kw))

    calls.clear()
    asyncio.run(CH.on_channel_post(update_for(views=55), SimpleNamespace()))
    kw = [c for c in calls if c[0] == "save_channel_post_history"][0][1]
    check("views mavjud bo'lsa (boshqa transport) raqam va manba bilan saqlanadi",
          kw.get("views") == 55 and kw.get("views_source") == "bot_api_event", str(kw))
finally:
    CH.db.run_db = orig

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
