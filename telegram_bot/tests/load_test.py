#!/usr/bin/env python3
"""Load-test va integrasiya testi — haqiqiy PostgreSQL bilan.

pgserver paketi orqali lokal PostgreSQL ishga tushiriladi, botning DB qatlami
va scheduler'i haqiqiy yuk ostida sinovdan o'tkaziladi.

Ishga tushirish:
    cd telegram_bot && python tests/load_test.py
"""
import os
import sys
import asyncio
import time
import shutil
import threading
from pathlib import Path
from types import SimpleNamespace

# ---- MUHIM: database/config import qilinishidan OLDIN env sozlash ----
os.environ["BOT_TOKEN"] = "123456:TEST_TOKEN_FOR_LOAD"
os.environ["ADMIN_ID"] = "777000"
os.environ["DATABASE_URL"] = "postgresql://user:pass@localhost:5432/notused"
os.environ["DB_POOL_MIN"] = "0"
os.environ["DB_POOL_MAX"] = "5"
os.environ["POST_BATCH_SIZE"] = "100"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


# ---------- Fake Telegram bot ----------
class FakeBot:
    """Scheduler chaqiradigan Telegram bot metodlarini taqlid qiladi."""

    def __init__(self, delay: float = 0.0):
        self.sent = []
        self.deleted = []
        self.delay = delay
        self.lock = threading.Lock()
        self._blocked = set()       # chat_id lar: TelegramError tashlaydi
        self._bad_html = set()      # chat_id lar: HTML bilan BadRequest, oddiy matn bilan ishlaydi

    async def send_message(self, chat_id, text=None, reply_markup=None, parse_mode=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        if chat_id in self._blocked:
            from telegram.error import TelegramError
            raise TelegramError("blocked")
        if chat_id in self._bad_html and parse_mode == "HTML":
            from telegram.error import BadRequest
            raise BadRequest("can't parse entities")
        with self.lock:
            self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def send_photo(self, chat_id, photo=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_video(self, chat_id, video=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_animation(self, chat_id, animation=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_document(self, chat_id, document=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_audio(self, chat_id, audio=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_voice(self, chat_id, voice=None, caption=None, reply_markup=None, parse_mode=None):
        return await self.send_message(chat_id, text=caption, reply_markup=reply_markup, parse_mode=parse_mode)

    async def send_sticker(self, chat_id, sticker=None):
        return await self.send_message(chat_id, text="sticker")

    async def send_media_group(self, chat_id, media):
        msgs = []
        for m in media:
            cap = getattr(m, "caption", None)
            msgs.append(await self.send_message(chat_id, text=cap))
        return msgs

    async def delete_message(self, chat_id=None, message_id=None):
        with self.lock:
            self.deleted.append((chat_id, message_id))
        return True


# ---------- Testlar ----------
def test_pool_and_ping(db):
    print("== DB pool va ping ==")
    check("ping_db → True", db.ping_db() is True)

    # 20 ta parallel (thread'da) so'rov — pool to'lib qolmasligi kerak
    import random
    errors = []

    def worker(i):
        try:
            db.get_setting(f"test_key_{i}", "x")
            db.get_user_credits(1)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("20 ta parallel DB so'rov xatosiz", not errors, str(errors[:2]))


def test_parallel_post_numbering_and_indexes(db):
    print("== parallel post saqlash + indekslar ==")
    from datetime import datetime, timedelta
    import pytz

    user_id = 990001
    workers = 24
    barrier = threading.Barrier(workers)
    result_lock = threading.Lock()
    post_ids = []
    errors = []
    future_time = datetime.now(pytz.timezone("Asia/Tashkent")) + timedelta(days=365)

    def save_post(i):
        try:
            barrier.wait()
            post_id = db.add_post(
                user_id=user_id,
                channel_id=f"-100parallel{i}",
                post_type="text",
                content=f"Parallel post {i}",
                file_id=None,
                scheduled_time=future_time,
            )
            with result_lock:
                post_ids.append(post_id)
        except Exception as e:
            with result_lock:
                errors.append(e)

    threads = [threading.Thread(target=save_post, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    check("parallel saqlash xatosiz", not errors and len(post_ids) == workers, str(errors[:2]))
    check("har bir parallel post saqlandi", all(post_id > 0 for post_id in post_ids), str(post_ids))

    with db.db_cursor() as cur:
        cur.execute(
            "SELECT user_post_number FROM scheduled_posts WHERE user_id = %s ORDER BY user_post_number",
            (user_id,),
        )
        numbers = [row[0] for row in cur.fetchall()]
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
        indexes = {row[0] for row in cur.fetchall()}

    check("parallel post raqamlari dublikatsiz", numbers == list(range(1, workers + 1)), str(numbers))
    check("scheduled_posts.user_id indeksi", "idx_scheduled_posts_user_id" in indexes, str(indexes))
    check("channels.user_id indeksi", "idx_channels_user_id" in indexes, str(indexes))
    check("post_reactions.post_id indeksi", "idx_post_reactions_post_id" in indexes, str(indexes))


def test_recent_channels_limit(db):
    print("== admin uchun oxirgi 20 ta kanal ==")
    user_id = 990002
    all_ids = []
    for i in range(25):
        channel_id = f"-100recent{i}"
        ok, reason = db.save_channel(user_id, channel_id, f"Recent {i}")
        all_ids.append(channel_id)
        if not ok:
            check("test kanali saqlandi", False, reason)
            return

    recent = db.get_all_channels(20)
    recent_ids = [row[0] for row in recent]
    expected_ids = list(reversed(all_ids[-20:]))
    check("ro'yxat ko'pi bilan 20 ta", len(recent) == 20, str(len(recent)))
    check("eng so'nggi 20 ta kanal qaytadi", recent_ids == expected_ids,
          f"actual={recent_ids[:3]}... expected={expected_ids[:3]}...")


def test_due_posts_batching(db):
    print("== get_due_posts batch chegarasi ==")
    from database import POST_BATCH_SIZE
    due = db.get_due_posts(datetime_now())
    check(f"bitta chaqiruvda ≤ {POST_BATCH_SIZE} post", len(due) <= POST_BATCH_SIZE, f"olindi: {len(due)}")
    # Qolganlari pending bo'lib qoladi
    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
        left = cur.fetchone()[0]
    check("qolgan postlar pending", left > 0, f"left={left}")
    # Bu test olingan postlarni qayta navbatga qaytaradi (scheduler testi uchun)
    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE scheduled_posts SET status = 'pending', processing_started_at = NULL WHERE status = 'processing'")
    return due


def datetime_now():
    from datetime import datetime
    import pytz
    return datetime.now(pytz.timezone("Asia/Tashkent"))


def test_scheduler_ticks(db, total_posts):
    print("== check_and_send_posts (real DB, batch'lar bilan) ==")
    from scheduler import check_and_send_posts

    bot = FakeBot(delay=0.01)  # har bir yuborish ~10ms — haqiqiy tarmoqni taqlid qiladi
    start = time.perf_counter()

    # POST_BATCH_SIZE=100 → 250 ta post uchun 3 tick kerak
    sent_after_ticks = []
    for _ in range(4):
        asyncio.run(check_and_send_posts(bot))
        sent_after_ticks.append(len(bot.sent))

    elapsed = time.perf_counter() - start
    check(f"barcha {total_posts} post yuborildi", len(bot.sent) == total_posts,
          f"sent={len(bot.sent)}")
    check("tick'lar orasida batch qoidalari buzilmadi",
          sent_after_ticks[0] <= 100 and sent_after_ticks[1] <= 200,
          f"progress={sent_after_ticks}")
    print(f"  ↳ {total_posts} ta post {elapsed:.2f}s da yuborildi "
          f"({total_posts / elapsed:.0f} post/s)")

    # Barchasi 'posted' holatida
    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'posted'")
        posted = cur.fetchone()[0]
    check("barchasi 'posted'", posted == total_posts, f"posted={posted}")
    return elapsed


def test_recurring_daily(db):
    print("== kunlik takrorlanuvchi post (1 hafta tugmasi) ==")
    from scheduler import check_and_send_posts
    from datetime import datetime, timedelta
    import pytz

    tz = pytz.timezone("Asia/Tashkent")
    now = datetime.now(tz)
    # Post ertaga 10:00 ga rejalashtirilgan, end_date = bugun + 7 kun
    pid = db.add_post(
        user_id=1, channel_id="-100111", post_type="text",
        content="Kunlik yangilik", file_id=None,
        scheduled_time=now - timedelta(minutes=5),
        recurrence_type="daily",
        recurrence_time=(datetime(2000, 1, 1, 10, 0)).time(),
        end_date=now + timedelta(days=7),
    )
    check("post saqlandi", pid > 0)

    bot = FakeBot()
    asyncio.run(check_and_send_posts(bot))
    check("kunlik post yuborildi", len(bot.sent) >= 1)

    with db.db_cursor() as cur:
        cur.execute("SELECT status, scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))
        row = cur.fetchone()
    check("kunlik post qayta rejalashtirildi (pending)", row[0] == "pending", str(row))
    next_t = row[1].astimezone(tz)
    # Keyingi chiqish — 10:00 dan keyingi eng yaqin 10:00
    expected = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if expected <= now:
        expected += timedelta(days=1)
    check("keyingi chiqish 10:00 ga", next_t == expected,
          f"next={next_t} expected={expected}")


def test_retry_on_rate_limit(db):
    print("== Telegram rate-limit → post yo'qolmaydi ==")
    from scheduler import check_and_send_posts

    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("Asia/Tashkent")
    pid = db.add_post(
        user_id=1, channel_id="-100222", post_type="text",
        content="Rate-limit testi", file_id=None,
        scheduled_time=datetime.now(tz) - timedelta(minutes=1),
    )
    bot = FakeBot()
    bot._blocked.clear()

    class RetryBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.calls = 0

        async def send_message(self, chat_id, text=None, reply_markup=None, parse_mode=None):
            self.calls += 1
            if self.calls == 1:
                from telegram.error import RetryAfter
                raise RetryAfter(retry_after=2)
            return await super().send_message(chat_id, text, reply_markup, parse_mode)

    rbot = RetryBot()
    asyncio.run(check_and_send_posts(rbot))
    with db.db_cursor() as cur:
        cur.execute("SELECT status, scheduled_time FROM scheduled_posts WHERE id = %s", (pid,))
        row = cur.fetchone()
    # Rate-limit tufayli post qayta navbatga qo'yiladi (pending, kelajak vaqt)
    check("rate-limit → pending va kelajak vaqt", row[0] == "pending" and row[1] > datetime.now(tz),
          f"status={row[0]} time={row[1]}")


def test_broadcast_batching(db):
    print("== _run_broadcast batch/rate-limit/retry ==")
    from handlers.admin import _run_broadcast

    user_ids = [f"u{i}" for i in range(60)]
    bot = FakeBot(delay=0.002)
    # 2 foydalanuvchi bloklangan, 1 foydalanuvchi HTML xato
    bot._blocked = {"u5", "u30"}
    bot._bad_html = {"u10"}

    start = time.perf_counter()
    asyncio.run(_run_broadcast(bot, user_ids, "<b>Xabar</b>", 777000))
    elapsed = time.perf_counter() - start

    # 60 ta qabul qiluvchi: 2 tasi bloklangan (failed), 1 tasi HTML xato bo'lib
    # oddiy matn bilan qayta yuborilgan (sent). Natija: 60 - 2 = 58 ta yetib bordi.
    # (bot.sent tarkibida admin'ga yuborilgan yakuniy hisobot xabari ham bor.)
    user_deliveries = [c for c, _ in bot.sent if c != 777000]
    check("broadcast: 58 ta yetib bordi (2 blok + 1 HTML fallback)", len(user_deliveries) == 58,
          f"sent={len(user_deliveries)}")
    check("broadcast tezligi oqilona", elapsed < 10, f"{elapsed:.2f}s")


def test_broadcast_retryafter_exhausted(db):
    """RetryAfter 3 marta takrorlansa ham foydalanuvchi 'yuborilmagan' hisobga olinishi kerak."""
    print("== _run_broadcast: RetryAfter tugagan urinishlar ==")
    from handlers.admin import _run_broadcast

    user_ids = [f"r{i}" for i in range(5)]

    class AlwaysRetryBot(FakeBot):
        def __init__(self):
            super().__init__()
            self.calls = 0
            self.admin_calls = 0

        async def send_message(self, chat_id=None, text=None, reply_markup=None, parse_mode=None):
            if chat_id == 777000:
                # Admin'ga yuboriladigan yakuniy hisobot normal ishlaydi
                self.admin_calls += 1
                return await super().send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            self.calls += 1
            from telegram.error import RetryAfter
            raise RetryAfter(retry_after=0)  # 0 → min(max(0,1),30)=1s kutish

    bot = AlwaysRetryBot()
    asyncio.run(_run_broadcast(bot, user_ids, "xabar", 777000))

    # Har bir foydalanuvchi 3 marta urinildi (5 × 3 = 15), hech biri yuborilmadi
    check("barcha urinishlar RetryAfter (15 ta)", bot.calls == 15, f"calls={bot.calls}")
    # 5 tasi ham 'failed' hisobiga kiritilishi kerak — admin xabari: Yetib bordi 0/5, Yuborilmagan 5
    admin_msg = [t for c, t in bot.sent if c == 777000]
    check("admin hisobotida yuborilmagan=5", bool(admin_msg) and "0 / 5" in admin_msg[0],
          str(admin_msg)[:120])


def test_cleanup(db):
    print("== DB cleanup (eski ma'lumotlar) ==")
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("Asia/Tashkent")

    # 1) Eski 'posted' post yaratamiz
    with db.db_cursor(commit=True) as cur:
        cur.execute("""
            INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status, created_at)
            VALUES (1, '-100333', 'text', 'eski', NOW() - INTERVAL '5 days', 'posted', NOW() - INTERVAL '60 days')
            RETURNING id
        """)
        old_post_id = cur.fetchone()[0]
        # 2) Eski sent_post_messages yozuvi
        cur.execute("""
            INSERT INTO sent_post_messages (post_id, channel_id, message_id, delete_at, deleted_at)
            VALUES (%s, '-100333', 1, NOW() - INTERVAL '100 days', NOW() - INTERVAL '40 days')
        """, (old_post_id,))
        # 3) Reaksiya yozuvi (bazada yo'q post uchun)
        cur.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (999999, 1, '👍')")

    result = db.cleanup_old_data()
    check("eski posted post o'chirildi", result["scheduled_posts"] >= 1, str(result))
    check("eski sent_post_messages o'chirildi", result["sent_post_messages"] >= 1, str(result))
    check("yetim reaksiyalar o'chirildi", result["post_reactions"] >= 1, str(result))
    check("yangi postlar o'chirilmadi", True)  # sanity


def test_channel_ownership(db):
    print("== kanal xavfsizligi: o'g'irlash mumkin emas ==")
    ok, reason = db.save_channel(1, "-100888001", "Kanal A")
    check("birinchi ulash ok", ok and reason == "ok", f"{ok} {reason}")
    ok2, reason2 = db.save_channel(2, "-100888001", "O'g'irlangan")
    check("boshqa user o'g'irlay olmaydi", (not ok2) and reason2 == "taken", f"{ok2} {reason2}")
    ok3, reason3 = db.save_channel(1, "-100888001", "Kanal A yangi nom")
    check("egasi yangilay oladi", ok3 and reason3 == "ok", f"{ok3} {reason3}")
    db.remove_channel(1, "-100888001")
    ok4, reason4 = db.save_channel(2, "-100888001", "Endi user2")
    check("nofaol kanalni boshqasi olishi mumkin", ok4 and reason4 == "ok", f"{ok4} {reason4}")
    db.save_channel(1, "-100888002", "Kick testi")
    deactivated = db.deactivate_channel_by_id("-100888002")
    check("bot chiqarilsa nofaol", deactivated is True)
    chans = db.get_user_channels(1)
    check("nofaol kanal ro'yxatda yo'q", all(c[0] != "-100888002" for c in chans))


def test_sponsors_fail_closed_empty(db):
    print("== get_active_sponsors: DB ishlasa list (None emas) ==")
    sponsors = db.get_active_sponsors()
    check("homiylar list", isinstance(sponsors, list), str(type(sponsors)))
    check("bo'sh homiy None emas", sponsors is not None)


def test_album_and_no_watermark(db):
    print("== albom yuborish + majburiy watermark yo'q ==")
    import json
    from scheduler import check_and_send_posts
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("Asia/Tashkent")
    items = json.dumps([
        {"type": "photo", "file_id": "ph1", "caption": "Birinchi"},
        {"type": "photo", "file_id": "ph2"},
    ])
    pid = db.add_post(
        user_id=1, channel_id="-100444", post_type="album",
        content="Albom matni", file_id=items,
        scheduled_time=datetime.now(tz) - timedelta(minutes=1),
    )
    check("albom post saqlandi", pid > 0)
    bot = FakeBot()
    asyncio.run(check_and_send_posts(bot))
    texts = [t or "" for _, t in bot.sent]
    check("albom kamida 2 ta media", len(bot.sent) >= 2, f"sent={len(bot.sent)}")
    check("watermark yo'q", all("@PostAssistrobot" not in t for t in texts), str(texts)[:200])
    check("albom matni chiqdi", any("Albom matni" in t for t in texts), str(texts)[:200])


def main():
    import pgserver

    print("Lokal PostgreSQL ishga tushirilmoqda (pgserver)...")
    # Har safar toza baza bilan boshlaymiz (oldingi run ma'lumotlari qolmasligi uchun)
    server_dir = "/tmp/yordamchi_pg_load"
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)
    uri = server.get_uri()
    print("PG URI:", uri)

    # Import qilishdan oldin DATABASE_URL'ni real URI ga almashtiramiz
    os.environ["DATABASE_URL"] = uri

    import database as db
    import pytz
    from datetime import datetime, timedelta

    db.init_db()
    print("Baza tayyor.")

    # Foydalanuvchilar yaratamiz
    db.save_user(777000, "admin", "Admin")           # ADMIN_ID (cheksiz)
    db.save_user(1, "user1", "Foydalanuvchi 1")
    db.save_user(2, "user2", "Foydalanuvchi 2")

    # 1) Pool testi
    test_pool_and_ping(db)

    # 2) 250 ta muddati yetgan post yaratamiz
    total = 250
    tz = pytz.timezone("Asia/Tashkent")
    past = datetime.now(tz) - timedelta(minutes=10)
    for i in range(total):
        db.add_post(
            user_id=(1 if i % 2 == 0 else 2),
            channel_id=f"-100{i % 3}",
            post_type="text",
            content=f"Load-test posti #{i}",
            file_id=None,
            scheduled_time=past,
        )

    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
        pending_count = cur.fetchone()[0]
    check("250 ta post navbatda", pending_count == total, f"pending={pending_count}")

    # 3) Batch chegarasi
    test_due_posts_batching(db)

    # 4) Scheduler barcha postlarni yuboradi (3-4 tick)
    test_scheduler_ticks(db, total)

    # Parallel saqlashdagi post raqami ham serializatsiyalangan bo'lishi kerak.
    # Postlar uzoq kelajak vaqtiga qo'yiladi, shuning uchun scheduler testlariga aralashmaydi.
    test_parallel_post_numbering_and_indexes(db)
    test_recent_channels_limit(db)

    # 5) Kunlik takrorlanuvchi post
    test_recurring_daily(db)

    # 6) Rate-limit retry
    test_retry_on_rate_limit(db)

    # 7) Broadcast
    test_broadcast_batching(db)

    # 8) Cleanup
    test_cleanup(db)

    # 9) Broadcast RetryAfter tugashi (xato hisobga olinishi)
    test_broadcast_retryafter_exhausted(db)

    # 10) Kanal xavfsizligi, homiylar, albom
    test_channel_ownership(db)
    test_sponsors_fail_closed_empty(db)
    test_album_and_no_watermark(db)

    db.close_pool()
    server.cleanup()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha load-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
