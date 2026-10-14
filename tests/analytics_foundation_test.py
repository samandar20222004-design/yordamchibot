#!/usr/bin/env python3
"""Kanal analitikasi ASOSI: halol ko'rishlar (NULL = ma'lumot yo'q) va obunachilar kunlik snapshot'i (real PostgreSQL, faqat sinov bazasi).

Muammo (audit): Bot API `Message` da `views` YO'Q, `on_channel_post` esa `getattr(msg, "views", 0)` bilan har doim 0 yozardi —
"0 ko'rish" va "ma'lumot yo'q" aralashardi; obunachilar tarixi umuman yig'ilmasdi. Bu test quyidagilarni qotiradi:
  * `views` noma'lum bo'lsa NULL (soxta 0 emas); manba (`views_source`) va yig'ilgan vaqt (`views_collected_at`) saqlanadi;
  * eski iste'molchilar uchun `get_channel_posts_history` hamon `views` (int) qaytaradi, lekin `views_known` bilan ajratiladi;
  * `channel_member_counts`: kuniga BITTA snapshot (idempotent), tarix, eskirganini tozalash, maxfiylik bilan o'chirishga qo'shilgan.
Telegram Bot API bermaydigan qiymat to'qilmaydi.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pg_support import real_pg_url  # noqa: E402

URL = real_pg_url("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "STEP5_TEST_DATABASE_URL",
                  "MINIAPP_TEST_DATABASE_URL", server_dir="yordamchi_pg_analytics")
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


print("== Analitika asosi (real PG) ==")
if not URL:
    print("  [SKIP] real PostgreSQL URL yo'q")
    print("\n JAMI: o'tdi=0, xato=0, skip=1")
    sys.exit(0)

import database as db  # noqa: E402

db.DATABASE_URL = URL
db._reset_pool()
db.init_db()

CH, CH2 = "-1009700100", "-1009700200"


def q(sql, params=()):
    with db.db_cursor(commit=True) as cur:
        cur.execute(sql, params)
        try:
            return cur.fetchall()
        except Exception:  # noqa: BLE001
            return []


def cleanup():
    q("DELETE FROM channel_posts_history WHERE channel_id = ANY(%s)", ([CH, CH2],))
    q("DELETE FROM channel_member_counts WHERE channel_id = ANY(%s)", ([CH, CH2],))
    q("DELETE FROM channels WHERE channel_id = ANY(%s)", ([CH, CH2],))
    q("DELETE FROM users WHERE user_id = ANY(%s)", ([9_700_001, 9_700_002],))


cleanup()
try:
    # --- sxema ---
    cols = {r[0] for r in q("SELECT column_name FROM information_schema.columns WHERE table_name = 'channel_posts_history'")}
    check("channel_posts_history: views_source va views_collected_at ustunlari bor", {"views_source", "views_collected_at"} <= cols, str(cols))
    check("channel_member_counts jadvali bor", bool(q("SELECT 1 FROM information_schema.tables WHERE table_name = 'channel_member_counts'")))
    check("startup tekshiruvi yangi jadvalni talab qiladi (ANALYTICS_TABLES)",
          "channel_member_counts" in getattr(db, "ANALYTICS_TABLES", ()))

    # --- views: noma'lum = NULL ---
    pid = db.save_channel_post_history(channel_id=CH, message_id=1, content="Birinchi", views=None, post_date=datetime.now(timezone.utc))
    row = q("SELECT views, views_source, views_collected_at FROM channel_posts_history WHERE id = %s", (pid,))[0]
    check("views noma'lum (None) -> NULL (soxta 0 EMAS), manba va vaqt yo'q", row == (None, None, None), str(row))

    # eski chaqiruv uslubi (views berilmagan) ham soxta 0 yozmaydi
    pid_default = db.save_channel_post_history(channel_id=CH, message_id=2, content="Standart", post_date=datetime.now(timezone.utc))
    check("views berilmagan chaqiruv ham NULL yozadi", q("SELECT views FROM channel_posts_history WHERE id = %s", (pid_default,))[0][0] is None)

    # haqiqiy qiymat manba bilan
    db.save_channel_post_history(channel_id=CH, message_id=1, content="Birinchi", views=120, views_source="tme_preview",
                                 post_date=datetime.now(timezone.utc))
    row = q("SELECT views, views_source, views_collected_at IS NOT NULL FROM channel_posts_history WHERE id = %s", (pid,))[0]
    check("haqiqiy ko'rishlar manba (tme_preview) va yig'ilgan vaqt bilan saqlanadi", row == (120, "tme_preview", True), str(row))

    # noma'lum keyingi yozuv bilganni O'CHIRMAYDI
    db.save_channel_post_history(channel_id=CH, message_id=1, content="Birinchi", views=None, post_date=datetime.now(timezone.utc))
    row = q("SELECT views, views_source FROM channel_posts_history WHERE id = %s", (pid,))[0]
    check("keyingi 'noma'lum' yozuv bilingan ko'rishlarni o'chirmaydi", row == (120, "tme_preview"), str(row))

    # kamaygan qiymat (GREATEST) hamon ishlaydi
    db.save_channel_post_history(channel_id=CH, message_id=1, content="Birinchi", views=90, views_source="tme_preview",
                                 post_date=datetime.now(timezone.utc))
    check("ko'rishlar kamaymaydi (GREATEST semantikasi saqlangan)", q("SELECT views FROM channel_posts_history WHERE id = %s", (pid,))[0][0] == 120)

    # --- o'qish: eski kalitlar + views_known ---
    hist = db.get_channel_posts_history(CH, 10)
    by_msg = {h["message_id"]: h for h in hist}
    check("get_channel_posts_history: 'views' hamon int (eski iste'molchilar buzilmaydi)",
          all(isinstance(h["views"], int) for h in hist), str(hist)[:200])
    check("views_known: noma'lum=False, bilingan=True", by_msg[2]["views_known"] is False and by_msg[1]["views_known"] is True, str(by_msg)[:300])
    check("views_source oshkor qilinadi", by_msg[1]["views_source"] == "tme_preview" and by_msg[2]["views_source"] is None)

    # --- SQL agregatlari NULL'ni 0 deb hisoblamaydi ---
    avg = q("SELECT AVG(views) FROM channel_posts_history WHERE channel_id = %s", (CH,))[0][0]
    check("AVG faqat bilingan qiymatlar bo'yicha (NULL e'tiborsiz)", float(avg) == 120.0, str(avg))

    # --- obunachilar snapshot'i ---
    today = date.today()
    ok = db.save_channel_member_count(CH, 1000, snapshot_date=today - timedelta(days=30))
    db.save_channel_member_count(CH, 1100, snapshot_date=today - timedelta(days=7))
    db.save_channel_member_count(CH, 1150, snapshot_date=today)
    check("snapshot saqlandi (True)", ok is True)
    db.save_channel_member_count(CH, 1160, snapshot_date=today)
    cnt = q("SELECT COUNT(*) FROM channel_member_counts WHERE channel_id = %s AND snapshot_date = %s", (CH, today))[0][0]
    last = q("SELECT member_count FROM channel_member_counts WHERE channel_id = %s AND snapshot_date = %s", (CH, today))[0][0]
    check("bir kunda BITTA snapshot (idempotent), oxirgi qiymat yangilanadi", cnt == 1 and last == 1160, f"{cnt} {last}")
    hist = db.get_channel_member_history(CH, 60)
    check("tarix yangidan eskiga, (sana, soni, manba, yig'ilgan vaqt)",
          [h["member_count"] for h in hist] == [1160, 1100, 1000] and hist[0]["source"] and hist[0]["collected_at"], str(hist)[:300])
    check("boshqa kanal tarixi aralashmaydi", db.get_channel_member_history(CH2, 60) == [])
    check("noto'g'ri qiymatlar rad etiladi (manfiy / None / bo'sh kanal)",
          db.save_channel_member_count(CH, -5) is False and db.save_channel_member_count(CH, None) is False
          and db.save_channel_member_count("", 10) is False)
    # --- faol kanallar: faqat BUGUN snapshot'i yo'qlari (qayta ishga tushirish xavfsiz) ---
    OWNER, STRANGER = 9_700_001, 9_700_002
    q("DELETE FROM channels WHERE channel_id = ANY(%s)", ([CH, CH2],))
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, 'an_owner', 'free') ON CONFLICT (user_id) DO NOTHING", (OWNER,))
    q("INSERT INTO users (user_id, username, plan_type) VALUES (%s, 'an_stranger', 'free') ON CONFLICT (user_id) DO NOTHING", (STRANGER,))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'AN1', TRUE)", (OWNER, CH))
    q("INSERT INTO channels (user_id, channel_id, channel_title, is_active) VALUES (%s, %s, 'AN2', TRUE)", (OWNER, CH2))
    pending = set(db.get_channels_for_member_snapshot())
    check("bugun snapshot'i BOR kanal (CH) ro'yxatda yo'q, yo'q kanal (CH2) bor", CH not in pending and CH2 in pending, str(pending)[:200])

    # --- IDOR: tarix faqat kanal egasi uchun ---
    check("egasi o'z kanalining tarixini ko'radi", len(db.get_channel_member_history(CH, 60, user_id=OWNER)) == 3)
    check("begona foydalanuvchi boshqaning kanal tarixini KO'RMAYDI (IDOR yopiq)", db.get_channel_member_history(CH, 60, user_id=STRANGER) == [])

    # --- tozalash ---
    db.save_channel_member_count(CH2, 50, snapshot_date=today - timedelta(days=500))
    db.save_channel_member_count(CH2, 60, snapshot_date=today - timedelta(days=10))
    res = db.cleanup_old_data()
    left = {r[0] for r in q("SELECT member_count FROM channel_member_counts WHERE channel_id = %s", (CH2,))}
    check("cleanup_old_data: 400 kundan eski snapshot o'chadi, yangisi qoladi", left == {60}, str(left))
    check("cleanup natijasida 'channel_member_counts' hisoblagichi bor", "channel_member_counts" in (res or {}), str(res))

    # --- maxfiylik bilan o'chirish (account delete) qamrovi ---
    from repositories import users_repository as ur
    check("hisobni o'chirish qamroviga channel_member_counts kiritilgan",
          any(t[0] == "channel_member_counts" for t in ur._ACCOUNT_DELETE_CHANNEL_SCOPED))
finally:
    cleanup()
    db.close_pool()

print(f"\n JAMI: o'tdi={passed}, xato={failed}, skip=0")
sys.exit(0 if failed == 0 else 1)
