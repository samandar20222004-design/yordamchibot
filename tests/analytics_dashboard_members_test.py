#!/usr/bin/env python3
"""Kanal dashboard'ida obunachilar qatori — halol ko'rsatish (DB'siz) — analitika asosi.

Qoidalar: haqiqiy snapshot bo'lsa ko'rsatiladi; ma'lumot yo'q delta "ma'lumot yetarli emas" deb yoziladi (0 emas);
ishonch past bo'lsa izoh; kanal tanlangan-u snapshot hali yo'q bo'lsa "yig'ilmoqda"; "barcha kanallar" ko'rinishi
(`member_growth` kaliti yo'q) o'zgarmaydi. Tarix FAQAT egasi uchun o'qiladi (IDOR).
"""
from __future__ import annotations

import asyncio
import os
import sys
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


print("== Dashboard: obunachilar qatori (DB'siz) ==")
import handlers.analytics as AN  # noqa: E402
from locales.translations import get_text  # noqa: E402

BASE = {"sent_7d": 3, "sent_30d": 10, "sent_all": 40, "pending": 2, "peak_hours": [(10, 5)], "type_distribution": {"text": 4}}
KEYS = ("an_dash_members", "an_dash_members_delta", "an_dash_members_nodata", "an_dash_members_low", "an_dash_members_pending")
for lang in ("uz", "ru", "en"):
    missing = [k for k in KEYS if get_text(k, lang) == k]
    check(f"[{lang}] obunachilar matnlari mavjud", not missing, str(missing))
check("uz/ru/en matnlari farq qiladi", all(len({get_text(k, l_) for l_ in ("uz", "ru", "en")}) == 3 for k in KEYS if k != "an_dash_members_delta"))

grow = {"current": 12345, "as_of": "2026-10-14", "delta_7d": 50, "delta_30d": None, "points": 9, "span_days": 12,
        "confidence": "medium", "stale": False, "source": "bot_api_getChatMemberCount", "collected_at": "2026-10-14T03:00:00+00:00"}
txt = AN._build_dashboard({**BASE, "member_growth": grow}, "Kanal <X>", "uz")
check("obunachilar soni ajratgich bilan (12 345) va sana ko'rsatiladi", "12 345" in txt and "2026-10-14" in txt, txt)
check("7 kunlik o'sish +50, 30 kunlik 'ma'lumot yetarli emas' (0 emas)",
      "+50" in txt and get_text("an_dash_members_nodata", "uz") in txt and "30" in txt, txt)
check("ishonch 'medium' da past-ishonch izohi YO'Q", get_text("an_dash_members_low", "uz") not in txt)

low = dict(grow, confidence="low", delta_7d=None, points=2)
txt = AN._build_dashboard({**BASE, "member_growth": low}, "Kanal", "ru")
check("ishonch past: izoh ko'rsatiladi (ru)", get_text("an_dash_members_low", "ru") in txt, txt)

neg = dict(grow, delta_7d=-120)
txt = AN._build_dashboard({**BASE, "member_growth": neg}, "Kanal", "en")
check("kamayish '-120' ko'rinishida", "-120" in txt, txt)

pending = {"current": None, "as_of": None, "delta_7d": None, "delta_30d": None, "points": 0, "confidence": "none", "stale": False}
txt = AN._build_dashboard({**BASE, "member_growth": pending}, "Kanal", "en")
check("kanal tanlangan, snapshot hali yo'q -> 'yig'ilmoqda' (soxta raqam yo'q)", get_text("an_dash_members_pending", "en") in txt, txt)

txt_all = AN._build_dashboard(dict(BASE), "Barcha", "uz")
check("'barcha kanallar' (kalit yo'q): obunachilar qatori YO'Q (o'zgarmagan)", "👥" not in txt_all)

empty = AN._build_dashboard({"sent_all": 0, "pending": 0, "member_growth": grow}, "Kanal", "uz")
check("post yo'q holati (empty state) o'zgarmagan", empty == get_text("an_dash_empty", "uz", channel="Kanal"), empty)

# --- _attach_member_growth: egalik bo'yicha o'qish, xatoga chidamli ---
calls = []
orig = AN.db.run_db


async def fake_run_db(fn, *a, **k):
    calls.append((getattr(fn, "__name__", ""), a, k))
    return [{"date": "2026-10-14", "member_count": 10, "source": "s", "collected_at": None}]


try:
    AN.db.run_db = fake_run_db
    out = asyncio.run(AN._attach_member_growth({"sent_all": 1}, 4242, "-100123"))
    name, args, kw = calls[0]
    check("tarix egasi (user_id) bilan o'qiladi (IDOR)", name == "get_channel_member_history" and (4242 in args or kw.get("user_id") == 4242), str(calls))
    check("stats'ga member_growth qo'shildi, asl kalitlar saqlandi", out.get("member_growth", {}).get("current") == 10 and out["sent_all"] == 1)
    check("kanal tanlanmagan (None) bo'lsa DB'ga umuman murojaat yo'q",
          asyncio.run(AN._attach_member_growth({"a": 1}, 4242, None)) == {"a": 1} and len(calls) == 1)

    async def boom(fn, *a, **k):
        raise RuntimeError("db down")
    AN.db.run_db = boom
    out = asyncio.run(AN._attach_member_growth({"a": 1}, 4242, "-100123"))
    check("DB xatosida dashboard buzilmaydi (stats o'zgarishsiz qaytadi)", out == {"a": 1}, str(out))
finally:
    AN.db.run_db = orig

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
