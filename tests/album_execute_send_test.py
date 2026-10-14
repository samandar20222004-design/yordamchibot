#!/usr/bin/env python3
"""Albom: `_execute_send` darajasidagi test — tugma-xabari xatosi albomni QAYTA yubormaydi
va postni noto'g'ri "failed" holatiga o'tkazmaydi.

Haqiqiy (mock QILINMAGAN) kod: `_execute_send` orkestratori, `_dispatch_post_to_telegram`,
`_build_album_media`, `parse_album_items`, `_build_sent_marker`, `_delivery_is_dead`,
`flood_wait_seconds`, except-shoxlar mantiqi.
MOCK QILINGAN: Telegram yuborish (`_delivery_send`), `_send_precheck_and_claim` (DB claim),
`_build_send_payload`, `_verify_no_duplicate_before_send`, `delivery_service` lock'lari,
`db.run_db` (retry_post / mark_post_status chaqiruvlari YOZIB boriladi), `_mark_delivery_failed`,
`_handle_ambiguous_send_error`, `_finalize_sent_post` (unga berilgan marker yozib boriladi).
Haqiqiy DB / Telegram ishlatilmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

SECRET_TOKEN = "987654:SECRETtokenMUSTNOTAPPEARinLOGS1234567"
os.environ.setdefault("BOT_TOKEN", SECRET_TOKEN)
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
POST_TEXT = "MAXFIY POST MATNI 12345"
MARKUP = InlineKeyboardMarkup([[InlineKeyboardButton("x", url="https://example.com")]])


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage() + " " + str(record.exc_info or ""))


def run_scenario(media_exc=None, follow_exc=None):
    """`_execute_send` ni to'liq yuritadi; nima chaqirilganini qaytaradi."""
    rec = {"sent": [], "db": [], "finalize": [], "mark_failed": [], "ambiguous": [], "released": 0}

    async def fake_send(bot, method, **kw):
        rec["sent"].append(method)
        if method == "send_media_group":
            if media_exc is not None:
                raise media_exc
            return [NS(message_id=11), NS(message_id=12)]
        if follow_exc is not None:
            raise follow_exc
        return NS(message_id=13)

    ctx = dict(
        post_id=77, user_id=5, channel_id="-1001", post_type="album", file_id=ALBUM,
        delivery_kwargs={}, delivery_key="dk", delivery_marker_key="dmk",
        delete_after_hours=0, recurrence_type=None, recurrence_day=None, recurrence_time=None,
        end_date=None, delivery_claim_verify_attempt=0,
    )
    payload = dict(final_content=POST_TEXT, text_limit=1024, reply_markup=MARKUP)

    async def precheck(bot, post):
        return ctx

    async def build(c):
        return payload

    async def nodup(bot, c, text):
        return True

    async def acquire(key):
        return "tok"

    async def release(key, tok):
        rec["released"] += 1

    async def run_db(fn, *a, **kw):
        rec["db"].append((getattr(fn, "__name__", str(fn)), a))
        return None

    async def mark_failed(key, err, is_transient=True):
        rec["mark_failed"].append((type(err).__name__, is_transient))
        # doimiy xato -> dead_letter, vaqtinchalik -> retry (haqiqiy delivery_service semantikasi)
        return {"status": s.delivery_service.STATUS_DEAD_LETTER if not is_transient else "retry"}

    async def ambiguous(*a, **kw):
        rec["ambiguous"].append(type(a[-1]).__name__ if a else None)

    async def finalize(bot, c, marker, msg_id, target):
        rec["finalize"].append((marker, msg_id, target))

    saved = {n: getattr(s, n) for n in (
        "_delivery_send", "_send_precheck_and_claim", "_build_send_payload",
        "_verify_no_duplicate_before_send", "_mark_delivery_failed",
        "_handle_ambiguous_send_error", "_finalize_sent_post", "flood_wait_inline_sleep")}
    saved_lock = (s.delivery_service.acquire_delivery_lock, s.delivery_service.release_delivery_lock)
    saved_run_db = s.db.run_db
    s._delivery_send = fake_send
    s._send_precheck_and_claim = precheck
    s._build_send_payload = build
    s._verify_no_duplicate_before_send = nodup
    s._mark_delivery_failed = mark_failed
    s._handle_ambiguous_send_error = ambiguous
    s._finalize_sent_post = finalize
    s.flood_wait_inline_sleep = lambda w: 0
    s.delivery_service.acquire_delivery_lock = acquire
    s.delivery_service.release_delivery_lock = release
    s.db.run_db = run_db
    cap = Capture()
    s.logger.addHandler(cap)
    try:
        asyncio.run(s._execute_send(None, {"id": 77}))
    finally:
        s.logger.removeHandler(cap)
        for n, v in saved.items():
            setattr(s, n, v)
        s.delivery_service.acquire_delivery_lock, s.delivery_service.release_delivery_lock = saved_lock
        s.db.run_db = saved_run_db
    rec["logs"] = cap.lines
    return rec


def db_names(rec):
    return [name for name, _ in rec["db"]]


def failed_marked(rec):
    return any(name == "mark_post_status" and "failed" in args for name, args in rec["db"])


print("== _execute_send: tugma-xabari (follow-up) xatolari ==")
secret_exc_text = f"boom {SECRET_TOKEN} {POST_TEXT}"
for exc in (RetryAfter(3), BadRequest(secret_exc_text), TimedOut(secret_exc_text), NetworkError(secret_exc_text)):
    name = type(exc).__name__
    rec = run_scenario(follow_exc=exc)
    check(f"{name}: send_media_group aynan 1 marta (albom dublikat emas)",
          rec["sent"].count("send_media_group") == 1, str(rec["sent"]))
    check(f"{name}: retry_post CHAQIRILMAYDI (qayta navbatga qo'yilmaydi)", "retry_post" not in db_names(rec), str(rec["db"]))
    check(f"{name}: post 'failed' qilinmaydi", not failed_marked(rec), str(rec["db"]))
    check(f"{name}: yetkazish 'failed' deb belgilanmaydi", rec["mark_failed"] == [], str(rec["mark_failed"]))
    check(f"{name}: noaniq-xato (ambiguous) yo'li ishlamaydi", rec["ambiguous"] == [], str(rec["ambiguous"]))
    check(f"{name}: nashr belgisi saqlanadi (finalize 1 marta)", len(rec["finalize"]) == 1)
    if rec["finalize"]:
        marker, msg_id, target = rec["finalize"][0]
        check(f"{name}: marker.message_id=11, extra_ids=[12] (follow-up id yo'q)",
              msg_id == 11 and marker["message_id"] == 11 and marker["extra_ids"] == [12], str(marker))
    check(f"{name}: delivery lock bo'shatildi", rec["released"] == 1)
    joined = "\n".join(rec["logs"])
    check(f"{name}: warning log yozildi", "tugma-xabari yuborilmadi" in joined)
    check(f"{name}: logda token yo'q", SECRET_TOKEN not in joined)
    check(f"{name}: logda post matni yo'q", POST_TEXT not in joined)
    check(f"{name}: logda istisno matni yo'q (faqat tur nomi)", "boom" not in joined and name in joined)

print("\n== Muvaffaqiyat: follow-up OK ==")
rec = run_scenario()
check("follow-up OK: extra_ids=[12, 13]", rec["finalize"] and rec["finalize"][0][0]["extra_ids"] == [12, 13])
check("follow-up OK: retry/failed yo'q", "retry_post" not in db_names(rec) and not failed_marked(rec))

print("\n== NAZORAT: albomning O'ZI yuborilmasa eski xatti-harakat saqlanadi (mock'lar haqiqatan ishlaydi) ==")
rec = run_scenario(media_exc=RetryAfter(3))
check("send_media_group RetryAfter: post qayta navbatga qo'yiladi (retry_post)", "retry_post" in db_names(rec), str(rec["db"]))
check("send_media_group RetryAfter: nashr belgisi yo'q (finalize chaqirilmaydi)", rec["finalize"] == [])
rec = run_scenario(media_exc=BadRequest("Wrong file identifier"))
check("send_media_group BadRequest: post 'failed' (haqiqiy albom xatosi)", failed_marked(rec), str(rec["db"]))
check("send_media_group BadRequest: DOIMIY xato sifatida belgilanadi (NetworkError subklassi bo'lsa ham)",
      rec["mark_failed"] == [("BadRequest", False)] and rec["ambiguous"] == [], str((rec["mark_failed"], rec["ambiguous"])))
check("send_media_group BadRequest: qayta navbatga qo'yilmaydi", "retry_post" not in db_names(rec))
check("BadRequest NetworkError subklassi (PTB) — regressiya sharti", issubclass(BadRequest, NetworkError))
rec = run_scenario(media_exc=TimedOut("t"))
check("send_media_group TimedOut: ambiguous yo'li ishlaydi", rec["ambiguous"] == ["TimedOut"], str(rec["ambiguous"]))

print(f"\n JAMI: o'tdi={passed}, xato={failed}")
sys.exit(0 if failed == 0 else 1)
