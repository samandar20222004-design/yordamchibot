#!/usr/bin/env python3
"""Davlat bo'yicha vaqt mintaqasi: zona tanlash, kiritish/ko'rsatish, takrorlanish, matnlar, /timezone (real PostgreSQL qismi bor).

Faqat SINOV bazasi (URL bo'lmasa DB qismi SKIP). Faqat o'z qatorlarini (user_id >= 9_810_000_000) yozadi va o'chiradi.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("MINIAPP_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "INTEGRITY_TEST_DATABASE_URL", server_dir="yordamchi_pg_tz")
if URL:
    os.environ["DATABASE_URL"] = URL
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("BOT_TOKEN", "123456789:TESTtokenABCDEFGHIJKLMNOPQRSTUV")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

passed = failed = skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [OK] {label}")
    else:
        failed += 1
        print(f"  [XATO] {label} {detail}")


import pytz  # noqa: E402

from services import user_timezone as tzs  # noqa: E402

print("\n== 1. Davlat -> zona ==")
check("UZ -> Asia/Tashkent", tzs.country_default_tz("UZ") == "Asia/Tashkent")
check("DE -> Europe/Berlin", tzs.country_default_tz("de") == "Europe/Berlin")
check("US asosiy zona New_York, boshqa zonalar ham bor", tzs.country_default_tz("US") == "America/New_York" and "America/Los_Angeles" in tzs.country_zones("US"))
check("RU -> Moskva, KZ -> Almaty, IN -> Kolkata", tzs.country_default_tz("RU") == "Europe/Moscow" and tzs.country_default_tz("KZ") == "Asia/Almaty" and tzs.country_default_tz("IN") == "Asia/Kolkata")
check("noma'lum davlat (ZZ/None/bo'sh) -> zona yo'q", tzs.country_default_tz("ZZ") is None and tzs.country_default_tz(None) is None and tzs.country_zones("") == [])
check("resolve: qo'lda tanlangan > davlat > Toshkent", tzs.resolve("Asia/Tokyo", "DE") == "Asia/Tokyo" and tzs.resolve(None, "DE") == "Europe/Berlin" and tzs.resolve(None, None) == "Asia/Tashkent")
check("resolve: yaroqsiz zona e'tiborsiz", tzs.resolve("Mars/Olympus", "DE") == "Europe/Berlin")
check("UTC+5 -> Etc/GMT-5 (POSIX belgisi teskari), UTC-3 -> Etc/GMT+3", tzs.offset_zone(5) == "Etc/GMT-5" and tzs.offset_zone(-3) == "Etc/GMT+3" and tzs.offset_zone(0) == "Etc/GMT")
check("parse_offset_choice: 'UTC+5' ha, 'UTC+99' yo'q, ixtiyoriy matn yo'q", tzs.parse_offset_choice("UTC+5") == "Etc/GMT-5" and tzs.parse_offset_choice("UTC+99") is None and tzs.parse_offset_choice("x") is None)
berlin = pytz.timezone("Europe/Berlin")
check("offset_label: Toshkent UTC+5, Hindiston UTC+5:30", tzs.offset_label(pytz.timezone("Asia/Tashkent")) == "UTC+5" and tzs.offset_label(pytz.timezone("Asia/Kolkata")) == "UTC+5:30")
check("utz() standarti Toshkent", tzs.utz().zone == "Asia/Tashkent")
with tzs.use_tz("Europe/Berlin"):
    inside = tzs.utz().zone
check("use_tz blok ichida zona almashadi va chiqqach tiklanadi", inside == "Europe/Berlin" and tzs.utz().zone == "Asia/Tashkent")
allz = [z for cc in pytz.country_timezones for z in pytz.country_timezones[cc]]
check("hamma davlat zonalari pytz'da yaroqli", all(tzs.valid_tz(z) for z in allz))

print("\n== 2. Kiritish: foydalanuvchi o'z vaqtida ==")
from utils.helpers import parse_schedule_input  # noqa: E402

now_utc = datetime(2026, 10, 15, 8, 0, tzinfo=pytz.utc)
with tzs.use_tz("Europe/Berlin"):
    dt, reason = parse_schedule_input("2026-10-16 18:00", now_utc.astimezone(tzs.utz()))
check("Berlin: '16.10 18:00' = 16:00 UTC", reason == "" and dt is not None and dt.astimezone(pytz.utc).hour == 16, str((dt, reason)))
with tzs.use_tz("Asia/Tashkent"):
    dt2, reason2 = parse_schedule_input("2026-10-16 18:00", now_utc.astimezone(tzs.utz()))
check("Toshkent: xuddi shu matn = 13:00 UTC (eski xulq o'zgarmadi)", reason2 == "" and dt2.astimezone(pytz.utc).hour == 13, str((dt2, reason2)))
with tzs.use_tz("America/New_York"):
    dt3, _ = parse_schedule_input("2026-10-16 18:00", now_utc.astimezone(tzs.utz()))
check("Nyu-York (yozgi vaqt): 18:00 = 22:00 UTC", dt3 is not None and dt3.astimezone(pytz.utc).hour == 22, str(dt3))

print("\n== 3. Takrorlanuvchi post egasi zonasida ==")
from scheduler import _build_sent_marker, calculate_next_time  # noqa: E402

cur = berlin.localize(datetime(2026, 10, 15, 10, 0))
with tzs.use_tz("Europe/Berlin"):
    nxt = calculate_next_time("daily", None, time(18, 30), cur)
check("daily 18:30 Berlin -> keyingi kun 18:30 Berlin", nxt.tzinfo is not None and nxt.astimezone(berlin).strftime("%H:%M") == "18:30", str(nxt))
marker = _build_sent_marker(1, 2, "c", 0, [], "daily", None, time(18, 30), None, None, owner_tz="Europe/Berlin")
nt = datetime.fromisoformat(marker["next_time"])
check("fon vazifa (owner_tz=Berlin): next_time Berlin 18:30", nt.astimezone(berlin).strftime("%H:%M") == "18:30", marker["next_time"])
marker_t = _build_sent_marker(1, 2, "c", 0, [], "daily", None, time(18, 30), None, None)
nt_t = datetime.fromisoformat(marker_t["next_time"])
check("owner_tz berilmasa Toshkent 18:30 (eski xulq)", nt_t.astimezone(pytz.timezone("Asia/Tashkent")).strftime("%H:%M") == "18:30")
with tzs.use_tz("Europe/Berlin"):
    over = calculate_next_time("daily", None, time(18, 30), berlin.localize(datetime(2026, 10, 24, 20, 0)))
check("DST: Berlin kuz o'tishi (25.10) arafasida ham keyingi post 18:30 mahalliy", over.astimezone(berlin).strftime("%H:%M") == "18:30" and over.astimezone(berlin).day == 25, str(over))

print("\n== 4. Matnlar: [[TZ]] hamma tilda almashadi ==")
from locales.translations import TRANSLATIONS, get_text  # noqa: E402

leak = [(lg, k) for lg, tbl in TRANSLATIONS.items() if isinstance(tbl, dict) for k, v in tbl.items() if isinstance(v, str) and "[[TZ]]" in v and "[[TZ]]" in get_text(k, lg, **{p: "x" for p in ("now", "time", "example")})]
check("get_text hech qaysi tilda [[TZ]] qoldirmaydi", not leak, str(leak[:3]))
with tzs.use_tz("Europe/Berlin"):
    texts = [get_text("np_confirm_time_single", lg, time="18:00") + get_text("tz_title", lg, zone="Europe/Berlin", offset="UTC+1") for lg in ("uz", "ru", "en")]
    sched = [get_text("np_confirm_time_single", lg, time="18:00") for lg in ("uz", "ru", "en")]
check("/timezone matni uch tilda bor", all("Berlin" in t for t in texts), str(texts))
check("tasdiq matnlarida Berlin va 'Toshkent' yo'q", all("Berlin" in t and "Toshkent" not in t and "Ташкент" not in t for t in sched), str(sched))
check("tz tugma yorlig'i <= 18 belgi (uch tilda)", all(len(get_text(k, lg)) <= 18 for k in ("tz_btn_offset", "tz_btn_auto", "tz_btn_back") for lg in ("uz", "ru", "en")))

print("\n== 5. AI vaqt ko'rsatmasi foydalanuvchi zonasida ==")
from utils import ai_agent  # noqa: E402

with tzs.use_tz("Europe/Berlin"):
    prompt = ai_agent._get_time_system_instruction("en")
check("AI ko'rsatmasi Berlin zonasini aytadi, Toshkent emas", "Berlin" in prompt and "Tashkent" not in prompt and "[[TZ]]" not in prompt, prompt[:200])

print("\n== 6. Real PostgreSQL ==")
if not URL:
    skipped += 1
    print("  [SKIP] real PostgreSQL URL yo'q")
else:
    import psycopg2

    import database as db
    from handlers import timezone_flow as tf

    db.init_db()
    conn = psycopg2.connect(URL)
    conn.autocommit = True
    cur_db = conn.cursor()
    A, B, C = 9_810_000_001, 9_810_000_002, 9_810_000_003
    ids = [A, B, C]

    def cleanup():
        cur_db.execute("DELETE FROM users WHERE user_id = ANY(%s)", (ids,))

    cleanup()
    try:
        for uid in ids:
            cur_db.execute("INSERT INTO users (user_id, username, full_name, language_code, plan_type) VALUES (%s,%s,%s,'uz','free')", (uid, f"t{uid}", f"N{uid}"))
        tzs.invalidate(A)
        check("yangi foydalanuvchi: zona Toshkent", tzs.tz_name_for(A) == "Asia/Tashkent")
        country = db.verify_phone(A, "+4915112345678", A)
        check("nemis raqami tasdiqlandi -> DE", country == "DE", str(country))
        check("telefon tasdig'idan keyin zona Europe/Berlin (kesh yangilandi)", tzs.tz_name_for(A) == "Europe/Berlin")
        cur_db.execute("SELECT target_country FROM users WHERE user_id = %s", (A,))
        check("standart 'UZ' bayram kalendari DE ga o'tdi", cur_db.fetchone()[0] == "DE")
        check("UZ raqami: zona Toshkent, target_country UZ", db.verify_phone(B, "+998901234567", B) == "UZ" and tzs.tz_name_for(B) == "Asia/Tashkent")
        cur_db.execute("UPDATE users SET target_country = 'KZ' WHERE user_id = %s", (C,))
        db.verify_phone(C, "+4915112345679", C)
        cur_db.execute("SELECT target_country FROM users WHERE user_id = %s", (C,))
        check("qo'lda tanlangan target_country (KZ) saqlanadi", cur_db.fetchone()[0] == "KZ")
        check("set_user_timezone yaroqsiz zonani rad etadi", db.set_user_timezone(A, "Mars/X") is False and tzs.tz_name_for(A) == "Europe/Berlin")
        check("set_user_timezone qo'lda zonani saqlaydi", db.set_user_timezone(A, "Europe/Vienna") and tzs.tz_name_for(A) == "Europe/Vienna")
        check("set_user_timezone(None) -> avto (davlat zonasi)", db.set_user_timezone(A, None) and tzs.tz_name_for(A) == "Europe/Berlin")
        check("get_timezone_row: (timezone, phone_country)", db.get_timezone_row(A) == (None, "DE"))

        async def cb(uid, data):
            q = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
            upd = SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=uid))
            with patch.object(tf, "ensure_user_lang", AsyncMock(return_value="uz")):
                await tf.timezone_callback(upd, SimpleNamespace(user_data={}))
            return q

        async def go():
            q = await cb(A, "tz:s:Europe/Busingen")
            r1 = tzs.tz_name_for(A)
            await cb(A, "tz:s:Asia/Tokyo")  # DE foydalanuvchi uchun taqiqlangan (boshqa davlat zonasi)
            r2 = tzs.tz_name_for(A)
            await cb(A, "tz:s:Etc/GMT-5")  # UTC+5 siljishi — hammaga ruxsat
            r3 = tzs.tz_name_for(A)
            await cb(A, "tz:auto")
            r4 = tzs.tz_name_for(A)
            qo = await cb(A, "tz:off")
            return q, r1, r2, r3, r4, qo

        q, r1, r2, r3, r4, qo = asyncio.run(go())
        check("callback: o'z davlati zonasi (Byuzingen) saqlandi", r1 == "Europe/Busingen")
        check("callback: begona davlat zonasi (Tokio) rad etildi, oldingisi qoladi", r2 == "Europe/Busingen", r2)
        check("callback: UTC siljishi (Etc/GMT-5) qabul", r3 == "Etc/GMT-5")
        check("callback: 'avto' davlat zonasiga qaytaradi", r4 == "Europe/Berlin")
        kb = qo.edit_message_text.await_args.kwargs["reply_markup"].inline_keyboard
        datas = [b.callback_data for row in kb for b in row]
        check("UTC ro'yxati: barcha callback_data <= 64 bayt", all(len(d.encode()) <= 64 for d in datas))

        async def mw(uid):
            tzs.set_current(None)
            upd = SimpleNamespace(effective_user=SimpleNamespace(id=uid))
            await tf.load_user_timezone(upd, SimpleNamespace())
            return tzs.utz().zone

        zone_a = asyncio.run(mw(A))
        zone_b = asyncio.run(mw(B))
        check("middleware: joriy yangilanish zonasi foydalanuvchiniki (Berlin / Toshkent)", zone_a == "Europe/Berlin" and zone_b == "Asia/Tashkent", f"{zone_a} {zone_b}")

        seen = []
        proc = tf.TimezoneUpdateProcessor(4)

        async def handler_body():
            seen.append(tzs.utz().zone)

        class _U(tf.Update):
            def __init__(self, uid):
                object.__setattr__(self, "_uid", uid)

            @property
            def effective_user(self):
                return SimpleNamespace(id=self._uid)

        tzs.set_current(None)
        asyncio.run(proc.do_process_update(_U(A), handler_body()))
        check("TimezoneUpdateProcessor: handlerdan oldin foydalanuvchi zonasi o'rnatiladi", seen == ["Europe/Berlin"], str(seen))
        check("jarayon parallelligi o'zgarmadi (max_concurrent_updates)", proc.max_concurrent_updates == 4)

        from miniapp_api import repository as mrepo
        from miniapp_api.service import resolve_timezone

        cur_db.execute("SELECT 1")
        with conn.cursor() as c2:
            acc = mrepo.load_account(c2, A)
        check("Mini App load_account: timezone/phone_country", acc["phone_country"] == "DE" and resolve_timezone(acc["timezone"], acc["phone_country"]) == "Europe/Berlin", str(acc))
    finally:
        cleanup()
        conn.close()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip={skipped}")
sys.exit(1 if failed else 0)
