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


# ---------- 5-BOSQICH: sxema butunligi bilan mos test ma'lumotlari ----------
# PostAssist V2 5-bosqichdan so'ng bazada FK constraintlar ishlaydi:
#   channels.user_id → users(user_id)
#   scheduled_posts.channel_id → channels(channel_id)
# Shuning uchun testlar post yozishdan OLDIN foydalanuvchi va kanal
# qatorlarini yaratadi ("seed"). Bu yozuvlar sxemaga to'liq mos — ya'ni test
# endi nafaqat logichni, balki constraintlar orqali ma'lumot butunligini ham
# tekshiradi.
TEST_CHANNEL_OWNERS = {
    "-1000": 1, "-1001": 1, "-1002": 1,
    "-100111": 1, "-100222": 1, "-100333": 1, "-100444": 1,
    "-100XXX": 555001, "-100YYY": 555001,
    "-1009900": 990001, "-1009902": 990002,
}
PARALLEL_CHANNELS = 24


def ensure_user(db, user_id, username=None):
    """FK ota-yozuvi: users qatori (idempotent)."""
    db.save_user(int(user_id), username or f"load_user_{user_id}", "Load test user")


def ensure_channels(db, owners=None):
    """FK ota-yozuvlari: kanallar (va ularning egalari)."""
    owners = TEST_CHANNEL_OWNERS if owners is None else owners
    for channel_id, owner in owners.items():
        ensure_user(db, owner)
        db.save_channel(int(owner), str(channel_id), f"Load kanal {channel_id}")
    ensure_user(db, 990001)
    for i in range(PARALLEL_CHANNELS):
        db.save_channel(990001, f"-100parallel{i}", f"Parallel kanal {i}")


def force_insert(db, sql, params=None, expect_error=None):
    """Qatorni majburan yozadi (test seed uchun) va natijani qaytaradi.

    ``expect_error`` berilsa — xatolik kutilmoqda: ``True`` (rad etildi)
    yoki ``False`` (kutilmagan muvaffaqiyat) qaytadi.
    """
    try:
        with db.db_cursor(commit=True) as cur:
            cur.execute(sql, params)
            return False if expect_error else True
    except Exception:
        if expect_error:
            return True
        raise


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
    # 5-bosqich FK: "-100parallel{i}" kanallari oldindan ro'yxatdan o'tgan
    ensure_channels(db, owners={})   # idempotent seed (paralel kanallar)
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

    # 1) Eski 'posted' post yaratamiz (kanal oldindan ulangan — FK talabi)
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
        # 3) Reaksiya — HAQIQIY post uchun (5-bosqich: yetim reaksiya yozib bo'lmaydi)
        cur.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, 1, '👍')",
                    (old_post_id,))

    # 4) 5-bosqich (FK): bazada yo'q post uchun reaksiya DB tomonidan rad etiladi,
    #    ya'ni "yetim yozuvlar" endi umudan paydo bo'lmaydi.
    orphan_rejected = force_insert(
        db,
        "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (999999, 1, '👍')",
        expect_error=True,
    )
    check("yetim reaksiya rad etildi (fk_post_reactions_post)", orphan_rejected is True)

    result = db.cleanup_old_data()
    check("eski posted post o'chirildi", result["scheduled_posts"] >= 1, str(result))
    check("eski sent_post_messages o'chirildi", result["sent_post_messages"] >= 1, str(result))
    with db.db_cursor() as cur:
        # Post o'chirilganda reaksiyasi ham CASCADE bilan ketadi.
        cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s", (old_post_id,))
        left = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id NOT IN (SELECT id FROM scheduled_posts)")
        orphans = cur.fetchone()[0]
    check("eski post reaksiyasi cascade bilan o'chdi", left == 0, str(left))
    check("bazada yetim reaksiya qolmadi", orphans == 0, str(orphans))
    check("cleanup sorovi xatosiz ishladi", result["post_reactions"] >= 0, str(result))


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
    print("== albom yuborish + majburiy brand nishoni yo'q ==")
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
    # Oldingi testlardan qolgan (qayta rejalashtirilgan) postlar ham yuborilishi
    # mumkin — shuning uchun FAQAT shu albom matnini tekshiramiz.
    texts = [t or "" for _, t in bot.sent]
    album_texts = [t for t in texts if "Albom matni" in t]
    check("albom kamida 2 ta media", len(bot.sent) >= 2, f"sent={len(bot.sent)}")
    check("albom matni chiqdi", bool(album_texts), str(texts)[:200])
    # user_id=1 — bepul foydalanuvchi: scheduler qoidasiga ko'ra post boshiga
    # @PostAssistrobot (via/watermark) QO'SHILADI. Admin belgilagan majburiy
    # nishon (post_tag_text) bo'sh — shuning uchun matn oxirida ikkinchi
    # belgi paydo bo'lmasligi kerak.
    check("free foydalanuvchi → @PostAssistrobot belgisi bor",
          all(t.startswith("@PostAssistrobot") for t in album_texts), str(album_texts)[:200])
    check("majburiy brand nishoni yo'q (bitta belgi, oxirida qo'shimcha yo'q)",
          all(t.count("@PostAssistrobot") == 1 and t.endswith("Albom matni") for t in album_texts),
          str(album_texts)[:200])



def test_ad_pool_crud_real_db(db):
    """ad_pool: matn, inline tugma, toggle va o'chirish — haqiqiy PostgreSQL."""
    print("== ad_pool CRUD (real DB) ==")
    db.clear_ads("channel")
    db.clear_ads("reply")

    ad_id = db.add_ad("channel", "<b>Birinchi</b> reklama")
    check("reklama qo'shildi", ad_id > 0, str(ad_id))
    ad = db.get_ad(ad_id)
    check("get_ad: matn", ad and ad["text"] == "<b>Birinchi</b> reklama", str(ad))
    check("get_ad: standart holat faol", ad["is_active"] is True)
    check("get_ad: tugma bo'sh", ad["button_text"] == "" and ad["button_url"] == "")

    # Tugma bilan qo'shish
    ad2 = db.add_ad("channel", "Ikkinchi", "Batafsil", "https://t.me/kanal")
    row2 = db.get_ad(ad2)
    check("tugma bilan qo'shildi",
          row2["button_text"] == "Batafsil" and row2["button_url"] == "https://t.me/kanal", str(row2))

    # Yarim tugma saqlanmaydi
    ad3 = db.add_ad("reply", "Uchinchi", "Faqat matn", "")
    row3 = db.get_ad(ad3)
    check("URL'siz tugma saqlanmaydi", row3["button_text"] == "", str(row3))

    # Matnni tahrirlash
    check("update_ad: matn", db.update_ad(ad_id, "<i>Yangilangan</i>") is True)
    check("matn yangilandi", db.get_ad(ad_id)["text"] == "<i>Yangilangan</i>")

    # Tugmani tahrirlash (matn o'zgarmaydi)
    check("update_ad: tugma", db.update_ad(ad_id, None, "Bosing", "https://t.me/x") is True)
    updated = db.get_ad(ad_id)
    check("tugma saqlandi", updated["button_text"] == "Bosing" and updated["button_url"] == "https://t.me/x")
    check("matn o'zgarmadi", updated["text"] == "<i>Yangilangan</i>")

    # Tugmani olib tashlash
    db.update_ad(ad_id, None, "", "")
    check("tugma olib tashlandi", db.get_ad(ad_id)["button_text"] == "")

    # Toggle Active/Inactive
    new_state = db.toggle_ad_active(ad_id)
    check("toggle: nofaol bo'ldi", new_state is False, str(new_state))
    active_ids = [a["id"] for a in db.get_ads_full("channel")]
    check("nofaol reklama faol ro'yxatda yo'q", ad_id not in active_ids, str(active_ids))
    all_ids = [a["id"] for a in db.get_ads_full("channel", include_inactive=True)]
    check("nofaol reklama to'liq ro'yxatda bor", ad_id in all_ids, str(all_ids))
    check("toggle: qayta faol", db.toggle_ad_active(ad_id) is True)
    check("set_ad_active(False)", db.set_ad_active(ad_id, False) is True)
    check("set_ad_active natijasi", db.get_ad(ad_id)["is_active"] is False)
    db.set_ad_active(ad_id, True)

    # Orqaga moslik: get_ads faqat (id, text) juftliklari
    pairs = db.get_ads("channel")
    check("get_ads: (id, text) juftliklari",
          all(isinstance(x, tuple) and len(x) == 2 for x in pairs), str(pairs))
    check("count_ads faol sonini beradi", db.count_ads("channel") == len(pairs))

    # O'chirish
    check("delete_ad ishlaydi", db.delete_ad(ad2) is True)
    check("o'chirilgan reklama yo'q", db.get_ad(ad2) is None)
    removed = db.clear_ads("channel")
    check("clear_ads soni", removed >= 1, str(removed))
    check("pul bo'shadi", db.get_ads_full("channel", include_inactive=True) == [])
    db.clear_ads("reply")


def test_channel_counters_real_db(db):
    """Kanal post sanagichlari va reklama oralig'i — haqiqiy PostgreSQL."""
    print("== kanal post sanagichlari (real DB) ==")
    db.reset_channel_post_count()

    # Har bir kanal alohida sanaladi
    for _ in range(4):
        db.bump_channel_post_count("-100AAA")
    for _ in range(2):
        db.bump_channel_post_count("-100BBB")
    check("A kanal sanagichi = 4", db.get_channel_post_count("-100AAA") == 4,
          str(db.get_channel_post_count("-100AAA")))
    check("B kanal sanagichi = 2", db.get_channel_post_count("-100BBB") == 2)
    check("noma'lum kanal → 0", db.get_channel_post_count("-100ZZZ") == 0)
    check("bo'sh kanal id → 0", db.bump_channel_post_count("") == 0)

    # Reklama belgisi
    check("mark_channel_ad_shown", db.mark_channel_ad_shown("-100AAA", 3) is True)
    counters = {row[0]: row for row in db.get_channel_post_counters(10)}
    check("sanagichlar ro'yxatida A bor", "-100AAA" in counters, str(counters))
    check("A uchun reklama soni 1", counters["-100AAA"][3] == 1, str(counters["-100AAA"]))

    # Interval saqlash/o'qish
    check("interval saqlandi", db.set_channel_ad_interval(5) is True)
    check("interval o'qildi", db.get_channel_ad_interval() == 5)
    db.set_channel_ad_interval(0)
    check("interval min chegarada", db.get_channel_ad_interval() == db.AD_INTERVAL_MIN)
    db.set_channel_ad_interval(3)
    check("interval 3 ga qaytdi", db.get_channel_ad_interval() == 3)
    check("get_ad_settings ichida ham bor",
          db.get_ad_settings()["channel_ad_interval"] == 3, str(db.get_ad_settings()))

    # Nolga qaytarish
    db.reset_channel_post_count("-100AAA")
    check("A sanagichi nolga qaytdi", db.get_channel_post_count("-100AAA") == 0)
    check("B sanagichi tegilmadi", db.get_channel_post_count("-100BBB") == 2)
    db.reset_channel_post_count()
    check("hammasi nolga qaytdi", db.get_channel_post_count("-100BBB") == 0)


def test_channel_ad_interval_end_to_end(db):
    """Har 3-postda reklama + inline tugma — scheduler orqali to'liq sinov."""
    print("== reklama oralig'i: uchdan-uchiga (real DB) ==")
    from scheduler import check_and_send_posts
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("Asia/Tashkent")

    db.clear_ads("channel")
    db.reset_channel_post_count()
    db.set_channel_ad_interval(3)
    ad_id = db.add_ad("channel", "REKLAMA-MATNI", "Havola", "https://t.me/reklama")
    check("reklama tayyor", ad_id > 0)

    ch_x, ch_y = "-100XXX", "-100YYY"
    for i in range(3):
        db.add_post(user_id=555001, channel_id=ch_x, post_type="text",
                    content=f"X-post-{i}", file_id=None,
                    scheduled_time=datetime.now(tz) - timedelta(minutes=1))
    db.add_post(user_id=555001, channel_id=ch_y, post_type="text",
                content="Y-post-0", file_id=None,
                scheduled_time=datetime.now(tz) - timedelta(minutes=1))

    bot = FakeBot()
    asyncio.run(check_and_send_posts(bot))

    x_texts = [t or "" for c, t in bot.sent if str(c) == ch_x]
    y_texts = [t or "" for c, t in bot.sent if str(c) == ch_y]
    with_ad = [t for t in x_texts if "REKLAMA-MATNI" in t]
    check("X kanaliga 3 ta post yetdi", len(x_texts) == 3, str(x_texts))
    check("X: faqat 3-postda reklama", len(with_ad) == 1, str(x_texts))
    check("Y: 1-postda reklama yo'q",
          y_texts and all("REKLAMA-MATNI" not in t for t in y_texts), str(y_texts))
    check("X sanagichi 3", db.get_channel_post_count(ch_x) == 3)
    check("Y sanagichi 1", db.get_channel_post_count(ch_y) == 1)

    # Reklama nofaol bo'lsa umuman chiqmaydi
    db.set_ad_active(ad_id, False)
    db.reset_channel_post_count()
    for i in range(3):
        db.add_post(user_id=555001, channel_id=ch_x, post_type="text",
                    content=f"X2-post-{i}", file_id=None,
                    scheduled_time=datetime.now(tz) - timedelta(minutes=1))
    bot2 = FakeBot()
    asyncio.run(check_and_send_posts(bot2))
    texts2 = [t or "" for _, t in bot2.sent if "X2-post" in (t or "")]
    check("nofaol reklama chiqmaydi",
          texts2 and all("REKLAMA-MATNI" not in t for t in texts2), str(texts2))

    # Bo'lim butunlay O'CHIRILGAN bo'lsa reklama umuman chiqmaydi
    db.set_ad_active(ad_id, True)
    db.set_channel_ad_status(False)
    db._cache_clear("ad_settings")
    check("channel_ad_status=False saqlandi",
          db.get_ad_settings().get("channel_ad_status") is False)
    db.reset_channel_post_count()
    for i in range(3):
        db.add_post(user_id=555001, channel_id=ch_x, post_type="text",
                    content=f"X3-post-{i}", file_id=None,
                    scheduled_time=datetime.now(tz) - timedelta(minutes=1))
    bot3 = FakeBot()
    asyncio.run(check_and_send_posts(bot3))
    texts3 = [t or "" for _, t in bot3.sent if "X3-post" in (t or "")]
    check("bo'lim o'chirilganda reklama chiqmaydi",
          len(texts3) == 3 and all("REKLAMA-MATNI" not in t for t in texts3), str(texts3))
    check("sanagich o'sishda davom etadi (tartib buzilmaydi)",
          db.get_channel_post_count(ch_x) == 3, str(db.get_channel_post_count(ch_x)))

    # Qayta yoqilganda reklama yana chiqadi
    db.set_channel_ad_status(True)
    db._cache_clear("ad_settings")
    check("channel_ad_status=True saqlandi",
          db.get_ad_settings().get("channel_ad_status") is True)
    db.reset_channel_post_count()
    for i in range(3):
        db.add_post(user_id=555001, channel_id=ch_x, post_type="text",
                    content=f"X4-post-{i}", file_id=None,
                    scheduled_time=datetime.now(tz) - timedelta(minutes=1))
    bot4 = FakeBot()
    asyncio.run(check_and_send_posts(bot4))
    texts4 = [t or "" for _, t in bot4.sent if "X4-post" in (t or "")]
    check("qayta yoqilgach reklama chiqadi",
          any("REKLAMA-MATNI" in t for t in texts4), str(texts4))

    db.clear_ads("channel")
    db.reset_channel_post_count()


def test_system_settings_real_db(db):
    """system_settings o'qish/saqlash — haqiqiy PostgreSQL."""
    print("== system_settings (real DB) ==")
    check("saqlash True", db.set_setting("load_test_key", "qiymat") is True)
    check("o'qish", db.get_setting("load_test_key") == "qiymat")
    check("mavjud bo'lmagan kalit → default",
          db.get_setting("yoq_bunday_kalit", "default-1") == "default-1")
    check("boshqa default ham to'g'ri (kesh xatosi yo'q)",
          db.get_setting("yoq_bunday_kalit", "default-2") == "default-2")
    db.set_setting("load_test_key2", "ikki")
    mapping = db.get_settings_map(["load_test_key", "load_test_key2"])
    check("get_settings_map ikkalasini qaytardi",
          mapping == {"load_test_key": "qiymat", "load_test_key2": "ikki"}, str(mapping))
    check("delete_setting", db.delete_setting("load_test_key2") is True)
    check("o'chirilgach default", db.get_setting("load_test_key2", "yo'q") == "yo'q")


def test_user_onboarding_real_db(db):
    """🆕 get_user_onboarding / set_user_full_menu_unlocked — haqiqiy PostgreSQL."""
    print("== onboarding (real DB) ==")
    import onboarding
    import pytz
    from datetime import datetime, timedelta

    uid = 990001
    db.save_user(uid, "yangi_user", "Yangi User")

    # 1) Yangi foydalanuvchi: created_at ~hozir, post yo'q, belgi yo'q
    data = db.get_user_onboarding(uid)
    check("onboarding: yozuv topildi", bool(data), str(data))
    check("onboarding: created_at qaytdi", data.get("created_at") is not None)
    check("onboarding: postlar soni 0", data.get("posts_published") == 0, str(data))
    check("onboarding: full_menu_unlocked=False", data.get("full_menu_unlocked") is False)
    check("onboarding: yangi foydalanuvchi → sodda menyu",
          onboarding.decide_menu_mode(data) == "simple", str(data))

    # 2) 3 ta post chiqarildi → postlar soni o'sadi
    tz = pytz.timezone("Asia/Tashkent")
    future = datetime.now(tz) + timedelta(days=30)
    for i in range(3):
        pid = db.add_post(uid, "-1009900", "text", f"Onboarding posti {i}", None, future)
        db.mark_post_as_sent(pid, 5000 + i)
    data2 = db.get_user_onboarding(uid)
    check("onboarding: 3 ta chiqarilgan post sanaldi",
          data2.get("posts_published") == 3, str(data2))
    check("onboarding: 3 post + yangi hisob → hali sodda menyu",
          onboarding.decide_menu_mode(data2) == "simple", str(data2))

    # 3) created_at 5 kun oldinga surilsa (3 kundan oshgan) → to'liq menyu
    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET created_at = NOW() - INTERVAL '5 days' WHERE user_id = %s", (uid,))
    db._invalidate_user(uid)
    onboarding.invalidate_simple_menu(uid)
    data3 = db.get_user_onboarding(uid)
    check("onboarding: 5 kunlik hisob → to'liq menyu",
          onboarding.decide_menu_mode(data3) == "full", str(data3))

    # 4) "⚙️ To'liq menyuni ochish" belgisi yoziladi
    check("set_user_full_menu_unlocked → True",
          db.set_user_full_menu_unlocked(uid, True) is True)
    data4 = db.get_user_onboarding(uid)
    check("onboarding: belgi bazada saqlandi", data4.get("full_menu_unlocked") is True)
    check("onboarding: belgi bilan → to'liq menyu",
          onboarding.decide_menu_mode(data4) == "full", str(data4))

    # 5) Mavjud bo'lmagan foydalanuvchi → bo'sh dict (fail-open: to'liq menyu)
    check("onboarding: noma'lum user → {}", db.get_user_onboarding(424242) == {})
    check("onboarding: bo'sh dict → full", onboarding.decide_menu_mode({}) == "full")


def test_schedule_week_posts_real_db(db):
    """🚀 schedule_week_posts — 7 post BITTA tranzaksiyada (haqiqiy PostgreSQL)."""
    print("== schedule_week_posts (real DB) ==")
    import pytz as _pytz
    from datetime import datetime as _dt, timedelta as _td
    from handlers.content_plan import week_schedule_times, build_plan_post_text

    uid = 990002
    db.save_user(uid, "reja_user", "Reja User")

    plan_items = [
        {"day": "Dushanba", "format": "Maslahat", "title": f"G'oya {i}", "idea": f"Tavsif {i}"}
        for i in range(1, 8)
    ]
    times = week_schedule_times(len(plan_items))
    posts = [(t, build_plan_post_text(it, i)) for i, (t, it) in enumerate(zip(times, plan_items))]

    res = db.schedule_week_posts(uid, "-1009902", posts)
    check("week: muvaffaqiyatli", res["success"] is True, str(res.get("error")))
    check("week: 7 ta post yozildi", res["count"] == 7, str(res))
    check("week: 7 ta id qaytdi", len(res["ids"]) == 7 and all(res["ids"]), str(res["ids"]))

    # Baza holati: barchasi 'pending', kanal to'g'ri, vaqtlar dushanba→yakshanba 12:00
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT id, status, channel_id, scheduled_time, user_post_number, content "
            "FROM scheduled_posts WHERE user_id = %s ORDER BY scheduled_time",
            (uid,),
        )
        rows = cur.fetchall()
    check("week: bazada 7 qator", len(rows) == 7, str(len(rows)))
    check("week: barchasi pending", all(r[1] == "pending" for r in rows))
    check("week: kanal saqlandi", all(r[2] == "-1009902" for r in rows))
    check("week: post raqamlari 1..7", [r[4] for r in rows] == list(range(1, 8)),
          str([r[4] for r in rows]))
    check("week: matn yozildi (HTML-escape bilan: ' → &#x27;)",
          all(r[5] and "G&#x27;oya" in r[5] and "Tavsif" in r[5] for r in rows),
          str(rows[0][5] if rows else None))
    check("week: xom apostrof saqlanmagan (HTML xavfsiz)",
          all("G'oya" not in (r[5] or "") for r in rows))

    tz = _pytz.timezone("Asia/Tashkent")
    stored = [r[3].astimezone(tz) for r in rows]
    check("week: kunlar dushanba(0)→yakshanba(6)",
          [m.weekday() for m in stored] == [0, 1, 2, 3, 4, 5, 6],
          str([m.weekday() for m in stored]))
    check("week: barchasi soat 12:00",
          all(m.hour == 12 and m.minute == 0 for m in stored),
          str([(m.hour, m.minute) for m in stored]))
    check("week: ketma-ket kunlar (24 soat)",
          all((stored[i + 1] - stored[i]) == _td(days=1) for i in range(6)))
    check("week: barcha vaqtlar kelajakda",
          all(m > _dt.now(tz) for m in stored))

    # Post raqami mavjud postlardan DAVOM etadi (MAX+1)
    extra = db.add_post(uid, "-1009902", "text", "Qo'shimcha", None,
                        _dt.now(tz) + _td(days=40))
    with db.db_cursor() as cur:
        cur.execute("SELECT user_post_number FROM scheduled_posts WHERE id = %s", (extra,))
        num = cur.fetchone()[0]
    check("week: keyingi post raqami 8", num == 8, str(num))

    # Tranzaksiya atomicligi: bitta yaroqsiz vaqt → HECH NARSA yozilmaydi
    before = db.get_queue_post_count(uid)
    bad_posts = list(posts[:3]) + [("bu-vaqt-emas", "buzilgan")]
    bad = db.schedule_week_posts(uid, "-1009902", bad_posts)
    check("week: xato holatda success=False", bad["success"] is False)
    check("week: xato holatda id bo'sh", bad["ids"] == [])
    after = db.get_queue_post_count(uid)
    check("week: ROLLBACK — yarim-yorti navbat qolmadi", before == after,
          f"before={before} after={after}")

    # Chekka holatlar
    check("week: bo'sh ro'yxat → empty", db.schedule_week_posts(uid, "-1009902", [])["error"] == "empty")
    check("week: kanalsiz → no_channel",
          db.schedule_week_posts(uid, "", posts)["error"] == "no_channel")


def test_week_posts_delivered_by_scheduler(db):
    """🚀➡️🤖 End-to-end: navbatga qo'yilgan 7 postni MAVJUD scheduler yuboradi.

    Yangi job yaratilmaydi — APScheduler'ning odatdagi ``check_and_send_posts``
    tick'i ``scheduled_posts`` jadvalidan o'zi o'qiydi. Shu test ikkala talabni
    bog'laydi: postlar chiqqach ``posts_published`` o'sadi va foydalanuvchi
    avtomatik to'liq menyuga o'tadi.
    """
    print("== 7 kunlik postlar → scheduler → kanal (end-to-end) ==")
    import pytz
    import onboarding
    from datetime import datetime, timedelta
    from scheduler import check_and_send_posts

    uid = 990003
    db.save_user(uid, "e2e_user", "E2E User")
    db.save_channel(uid, "-1009903", "E2E Kanal")

    tz = pytz.timezone("Asia/Tashkent")
    # Reja navbatga KELAJAKKA yoziladi; scheduler yuborishi uchun vaqtni
    # ataylab o'tmishga suramiz (funksiya vaqtni tekshirmaydi — bu test uchun).
    now = datetime.now(tz)
    times = [now - timedelta(minutes=10 - i) for i in range(7)]
    posts = [(t, f"<b>Hafta posti {i + 1}</b>\n\nKontent-reja matni {i + 1}")
             for i, t in enumerate(times)]

    res = db.schedule_week_posts(uid, "-1009903", posts)
    check("e2e: 7 post navbatga qo'yildi", res["success"] and res["count"] == 7, str(res.get("error")))
    check("e2e: barchasi hali pending", db.get_queue_post_count(uid) == 7,
          str(db.get_queue_post_count(uid)))

    # Mavjud scheduler tick'i (alohida job YARATILMAYDI)
    bot = FakeBot()
    asyncio.run(check_and_send_posts(bot))

    sent_to_channel = [m for m in bot.sent if str(m[0]) == "-1009903"]
    check("e2e: 7 post kanalga yuborildi", len(sent_to_channel) == 7,
          f"sent={len(sent_to_channel)} of {len(bot.sent)}: {bot.sent[:2]}")
    check("e2e: matn to'g'ri yetib bordi",
          len(sent_to_channel) == 7
          and all("Hafta posti" in (m[1] or "") for m in sent_to_channel),
          str(sent_to_channel[:1]))
    check("e2e: kanalga int chat_id bilan yuborildi (scheduler qoidasi)",
          all(m[0] == -1009903 for m in sent_to_channel), str(sent_to_channel[:1]))

    with db.db_cursor() as cur:
        cur.execute("SELECT status, sent_message_id FROM scheduled_posts WHERE user_id = %s", (uid,))
        rows = cur.fetchall()
    check("e2e: barchasi 'posted' holatida",
          len(rows) == 7 and all(r[0] == "posted" for r in rows), str(rows[:2]))
    check("e2e: sent_message_id yozildi (idempotentlik markeri)",
          all(r[1] for r in rows), str(rows[:2]))
    check("e2e: navbat bo'shadi", db.get_queue_post_count(uid) == 0,
          str(db.get_queue_post_count(uid)))

    # Ikkala talab bog'lanadi: postlar soni onboarding qaroriga ta'sir qiladi.
    data = db.get_user_onboarding(uid)
    check("e2e: posts_published = 7", data["posts_published"] == 7, str(data))
    # Hisob hozirgina yaratildi (0 kun) — talab bo'yicha "3 kundan kam" sharti
    # bajarilgani uchun menyu HALI sodda (postlar soni yetarli bo'lsa ham).
    check("e2e: 0 kunlik hisob + 7 post → hali sodda menyu (kun < 3)",
          onboarding.decide_menu_mode(data) == "simple", str(data))
    # 3 kun o'tgach va 3 tadan ko'p post chiqargach → standart bosh menyu.
    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET created_at = NOW() - INTERVAL '3 days' WHERE user_id = %s",
                    (uid,))
    db._invalidate_user(uid)
    onboarding.invalidate_simple_menu(uid)
    data2 = db.get_user_onboarding(uid)
    check("e2e: 3 kunlik hisob + 7 post → to'liq menyu",
          onboarding.decide_menu_mode(data2) == "full", str(data2))

    # Ikkinchi tick postlarni TAKRORAN yubormaydi (idempotentlik)
    before = len(bot.sent)
    asyncio.run(check_and_send_posts(bot))
    check("e2e: ikkinchi tick'da dublikat yo'q", len(bot.sent) == before,
          f"{before} → {len(bot.sent)}")


def main():
    try:
        import pgserver
    except ImportError:
        print("ℹ️ pgserver kutubxonasi o'rnatilmagan (pip install pgserver). Load-test o'tkazib yuborildi.")
        return

    print("Lokal PostgreSQL ishga tushirilmoqda (pgserver)...")
    import tempfile
    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_load")
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
    # 5-bosqich: FK constraintlar tufayli kanallar ham oldindan ulanadi.
    ensure_channels(db)
    check("test kanallari va foydalanuvchilari saqlandi",
          db.get_user_channels(1).__len__() >= 1)

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

    # 11) Reklama boshqaruvi: ad_pool CRUD, kanal sanagichlari, oraliq
    test_ad_pool_crud_real_db(db)
    test_channel_counters_real_db(db)
    test_channel_ad_interval_end_to_end(db)
    test_system_settings_real_db(db)

    # 12. 🆕 Onboarding (sodda klaviatura) va 🚀 7 kunlik rejani navbatga qo'yish
    test_user_onboarding_real_db(db)
    test_schedule_week_posts_real_db(db)
    test_week_posts_delivered_by_scheduler(db)

    db.close_pool()
    server.cleanup()

    print(f"\nO'tdi: {passed}, Xato: {failures}")
    if failures:
        sys.exit(1)
    print("Barcha load-testlar muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
