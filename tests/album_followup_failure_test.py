#!/usr/bin/env python3
"""Albom: tugma-xabari (follow-up) xatosi allaqachon yuborilgan albomni QAYTA yubormasligi kerak.

sendMediaGroup tugmalarni qo'llamaydi, shuning uchun tugmalar alohida `send_message` bilan
yuboriladi. Albom kanalda bo'lgach bu xabar xato bersa (RetryAfter / BadRequest / TimedOut),
istisno ko'tarilmasligi shart: aks holda `_execute_send` postni qayta navbatga qo'yadi (dublikat
albom) yoki "failed" deb belgilaydi (nashr qilingan post xato holatida).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import scheduler as s  # noqa: E402
from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # noqa: E402
from telegram.error import BadRequest, NetworkError, RetryAfter, TimedOut  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


ALBUM = '[{"type":"photo","file_id":"a"},{"type":"photo","file_id":"b"}]'
MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("x", url="https://example.com")]])


def run(follow_exc=None, markup=MARKUP):
    calls = []

    async def fake_send(bot, method, **kw):
        calls.append(method)
        if method == "send_media_group":
            return [NS(message_id=11), NS(message_id=12)]
        if follow_exc is not None:
            raise follow_exc
        return NS(message_id=13)

    original = s._delivery_send
    s._delivery_send = fake_send
    try:
        ctx = dict(post_id=1, channel_id="-1001", post_type="album", file_id=ALBUM, delivery_kwargs={})
        payload = dict(final_content="hi", text_limit=1024, reply_markup=markup)
        state = {"album_api_started": False}
        result = asyncio.run(s._dispatch_post_to_telegram(None, ctx, payload, state))
    finally:
        s._delivery_send = original
    return result, calls, state


print("== Albom follow-up xabari ==")
result, calls, _ = run()
check("follow-up OK: albom + tugma xabari yuborildi", calls == ["send_media_group", "send_message"])
check("follow-up OK: extra_ids albom va follow-up id'larini o'z ichiga oladi", result["extra_ids"] == [12, 13])

for exc in (RetryAfter(3), BadRequest("Wrong URL host"), TimedOut("t"), NetworkError("n")):
    name = type(exc).__name__
    try:
        result, calls, state = run(exc)
        raised = None
    except Exception as e:  # noqa: BLE001
        raised, result, calls, state = e, None, [], {}
    check(f"follow-up {name}: istisno ko'tarilmaydi (albom qayta yuborilmaydi)", raised is None,
          f"(ko'tarildi: {type(raised).__name__})")
    if raised is None:
        check(f"follow-up {name}: nashr belgisi saqlanadi (sent_msg bor)", result["sent_msg"].message_id == 11)
        check(f"follow-up {name}: extra_ids faqat albom elementlari", result["extra_ids"] == [12])
        check(f"follow-up {name}: send_media_group aynan 1 marta", calls.count("send_media_group") == 1)

result, calls, _ = run(markup=None)
check("tugmasiz albom: follow-up chaqirilmaydi", calls == ["send_media_group"])

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(0 if failed == 0 else 1)
