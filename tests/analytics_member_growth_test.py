#!/usr/bin/env python3
"""Obunachilar o'sishi (sof hisob) va kunlik snapshot ishi (DB'siz) — analitika asosi.

Halollik qoidalari: faqat HAQIQIY snapshot'lar; yetarli eski snapshot yo'q bo'lsa delta = None (extrapolyatsiya YO'Q);
ma'lumot kam/eski bo'lsa ishonch darajasi pasayadi. Snapshot ishi bitta kanal xatosida to'xtamaydi; FloodWait'da to'xtaydi
(qolgani keyingi ishga tushirishda).
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

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


print("== Obunachilar o'sishi: sof hisob ==")
from services.channels.growth import compute_member_growth  # noqa: E402

TODAY = date(2026, 10, 14)


def snap(days_ago, count, source="bot_api_getChatMemberCount"):
    d = TODAY - timedelta(days=days_ago)
    return {"date": d.isoformat(), "member_count": count, "source": source, "collected_at": d.isoformat() + "T03:00:00+00:00"}


g = compute_member_growth([], today=TODAY)
check("bo'sh tarix: current=None, delta=None, ishonch 'none'",
      g["current"] is None and g["delta_7d"] is None and g["delta_30d"] is None and g["confidence"] == "none", str(g))

g = compute_member_growth([snap(0, 1000)], today=TODAY)
check("bitta snapshot: joriy son bor, delta YO'Q (extrapolyatsiya qilinmaydi), ishonch 'low'",
      g["current"] == 1000 and g["delta_7d"] is None and g["delta_30d"] is None and g["confidence"] == "low", str(g))

hist = [snap(0, 1150), snap(7, 1100), snap(30, 1000)]
g = compute_member_growth(hist, today=TODAY)
check("7 va 30 kunlik delta haqiqiy snapshot'lardan", g["delta_7d"] == 50 and g["delta_30d"] == 150, str(g))
check("3 nuqta: ishonch 'low' (ma'lumot kam)", g["confidence"] == "low", str(g))

dense = [snap(i, 1000 + (30 - i)) for i in range(0, 31)]
g = compute_member_growth(dense, today=TODAY)
check("zich 31 kunlik tarix: ishonch 'high', delta aniq", g["confidence"] == "high" and g["delta_7d"] == 7 and g["delta_30d"] == 30, str(g))

mid = [snap(i, 1000 + (10 - i)) for i in range(0, 11)]
g = compute_member_growth(mid, today=TODAY)
check("11 kunlik zich tarix: 7 kunlik delta bor, 30 kunlik YO'Q, ishonch 'medium'",
      g["delta_7d"] == 7 and g["delta_30d"] is None and g["confidence"] == "medium", str(g))

gap = [snap(0, 1200), snap(20, 1000)]
g = compute_member_growth(gap, today=TODAY)
check("7 kunlik delta uchun mos snapshot yo'q (20 kunlik bo'shliq) -> None (yaqin-eng-yaqinga taxmin qilinmaydi)",
      g["delta_7d"] is None, str(g))

stale = [snap(6, 1000), snap(13, 950)]
g = compute_member_growth(stale, today=TODAY)
check("eskirgan ma'lumot (oxirgi snapshot 6 kun oldin): stale=True, ishonch 'low' dan oshmaydi",
      g["stale"] is True and g["confidence"] in ("low", "none"), str(g))

g = compute_member_growth([snap(0, 900), snap(7, 1000)], today=TODAY)
check("kamayish manfiy delta sifatida ko'rsatiladi", g["delta_7d"] == -100, str(g))

g = compute_member_growth([{"date": "xato", "member_count": "x"}, snap(0, 500)], today=TODAY)
check("buzuq yozuv e'tiborsiz qoldiriladi, qolgani ishlaydi", g["current"] == 500, str(g))

g = compute_member_growth([snap(0, 1000, source="bot_api_getChatMemberCount")], today=TODAY)
check("manba va yig'ilgan vaqt oshkor qilinadi", g["source"] == "bot_api_getChatMemberCount" and g["collected_at"], str(g))


print("\n== Kunlik snapshot ishi ==")
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut  # noqa: E402

import scheduler as sched  # noqa: E402

saved = []
CHANNELS = ["-1001", "-1002", "-1003", "-1004", "-1005", "-1006"]


async def fake_run_db(fn, *a, **k):
    name = getattr(fn, "__name__", "")
    if name == "get_channels_for_member_snapshot":
        return list(CHANNELS)
    if name == "save_channel_member_count":
        saved.append((a[0], a[1]))
        return True
    return None


class Bot:
    def __init__(self, plan):
        self.plan = plan
        self.asked = []

    async def get_chat_member_count(self, chat_id):
        self.asked.append(chat_id)
        out = self.plan[str(chat_id)]
        if isinstance(out, BaseException):
            raise out
        return out


async def _no_sleep(*_a, **_k):
    return None


orig_run_db, orig_sleep = sched.db.run_db, sched.asyncio.sleep
try:
    sched.db.run_db = fake_run_db
    sched.asyncio.sleep = _no_sleep
    plan = {"-1001": 1234, "-1002": Forbidden("bot was kicked"), "-1003": BadRequest("Chat not found"),
            "-1004": TimedOut("t"), "-1005": 77, "-1006": 5}
    bot = Bot(plan)
    res = asyncio.run(sched.snapshot_channel_member_counts_job(bot))
    check("muvaffaqiyatli kanallar saqlandi, xatolilari o'tkazib yuborildi (ish to'xtamadi)",
          saved == [("-1001", 1234), ("-1005", 77), ("-1006", 5)], str(saved))
    check("natija hisobi: saved=3, skipped/failed=3", res.get("saved") == 3 and res.get("skipped", 0) + res.get("failed", 0) == 3, str(res))
    check("raqamli kanal ID int sifatida yuborildi (Telegram chat_id)", all(isinstance(c, int) for c in bot.asked), str(bot.asked))

    # FloodWait: ish to'xtaydi, qolgan kanallar keyingi ishga tushirishga qoladi
    saved.clear()
    plan = {"-1001": 10, "-1002": RetryAfter(30), "-1003": 20, "-1004": 30, "-1005": 40, "-1006": 50}
    bot = Bot(plan)
    res = asyncio.run(sched.snapshot_channel_member_counts_job(bot))
    check("RetryAfter'da ish to'xtaydi (qolgan kanallar keyingi ishga tushirishga)",
          saved == [("-1001", 10)] and len(bot.asked) == 2 and res.get("rate_limited") is True, f"{saved} {bot.asked} {res}")

    # noto'g'ri javob (int emas) saqlanmaydi
    saved.clear()
    plan = {"-1001": "ko'p", "-1002": None, "-1003": -3, "-1004": 9, "-1005": 8, "-1006": 7}
    asyncio.run(sched.snapshot_channel_member_counts_job(Bot(plan)))
    check("yaroqsiz javoblar (matn/None/manfiy) saqlanmaydi", [s for s in saved if s[0] in ("-1001", "-1002", "-1003")] == [], str(saved))

    # DB ro'yxat xatosi ishni qulatmaydi
    async def boom_run_db(fn, *a, **k):
        raise RuntimeError("db down")
    sched.db.run_db = boom_run_db
    try:
        res = asyncio.run(sched.snapshot_channel_member_counts_job(Bot({})))
        ok = True
    except Exception as exc:  # noqa: BLE001
        ok = False
        print("   ", type(exc).__name__, exc)
    check("DB xatosida job qulamaydi", ok)
finally:
    sched.db.run_db, sched.asyncio.sleep = orig_run_db, orig_sleep

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
