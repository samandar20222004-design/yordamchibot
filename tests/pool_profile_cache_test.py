#!/usr/bin/env python3
"""DB pool (``_WarmPool``) va foydalanuvchi PROFIL keshi testlari (PostgreSQL'siz).

Ishga tushirish:
    cd telegram_bot && python tests/pool_profile_cache_test.py

Tekshiradi:
  * pool bo'sh ulanishlarni ``maxconn`` gacha SAQLAYDI (minconn=2 da yopib yubormaydi);
  * ROLLBACK va yangi ulanish ochish umumiy pool lock'ini USHLAMAYDI;
  * uzoq bo'sh turgan o'lik ulanish ishlatishdan oldin topilib, faqat o'zi tashlanadi;
  * profil keshi: 1 so'rov, nusxa, TTL, invalidatsiya, write-through, expiry-aware PRO;
  * tranzaksiya ICHIDA chaqirilgan ``_invalidate_user`` COMMIT'dan keyin yana bajariladi;
  * /start va Sozlamalar keshdan DB'siz javob beradi, kesh yo'q bo'lsa eski yo'l ishlaydi.
"""
import asyncio
import importlib
import os
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
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


try:
    import psycopg2
    from psycopg2 import extensions as ext
    import database as db
    _ = db._WarmPool
except Exception as exc:  # psycopg2 yo'q (CI stub) — bu test faqat haqiqiy psycopg2 bilan ma'noli
    print(f"[SKIP] psycopg2/database import qilinmadi: {exc!r}")
    sys.exit(0)

IDLE, INTRANS = ext.TRANSACTION_STATUS_IDLE, ext.TRANSACTION_STATUS_INTRANS


class FakeConn:
    created = 0
    _lock = threading.Lock()
    connect_gate = None  # Event: berilsa, connect() shuni kutadi

    def __init__(self):
        with FakeConn._lock:
            FakeConn.created += 1
        self.closed = 0
        self.autocommit = False
        self.status = IDLE
        self.ping_fail = False
        self.rollback_hook = None

    @property
    def info(self):
        return SimpleNamespace(transaction_status=self.status)

    def cursor(self):
        return FakeConnCursor(self)

    def commit(self):
        self.status = IDLE

    def rollback(self):
        if self.rollback_hook:
            self.rollback_hook()
        self.status = IDLE

    def close(self):
        self.closed = 1


class FakeConnCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        if sql.strip() == "SELECT 1" and self.conn.ping_fail:
            raise psycopg2.OperationalError("server closed the connection unexpectedly")
        self.conn.status = INTRANS

    def fetchone(self):
        return (1,)

    def close(self):
        pass


@contextmanager
def fake_psycopg():
    orig = psycopg2.connect
    FakeConn.created = 0
    FakeConn.connect_gate = None

    def fake_connect(*a, **k):
        gate = FakeConn.connect_gate
        if gate is not None:
            gate.wait(5)
        return FakeConn()

    psycopg2.connect = fake_connect
    try:
        yield
    finally:
        psycopg2.connect = orig


@contextmanager
def patched(obj, **attrs):
    old = {k: getattr(obj, k) for k in attrs}
    for k, v in attrs.items():
        setattr(obj, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(obj, k, v)


# ------------------------------------------------------------------ pool
def test_pool_keeps_idle_connections_up_to_maxconn():
    print("== _WarmPool: bo'sh ulanishlar maxconn gacha saqlanadi ==")
    check("_WarmPool — ThreadedConnectionPool ostki klassi",
          issubclass(db._WarmPool, db.ThreadedConnectionPool))
    with fake_psycopg():
        pool = db._WarmPool(2, 10, "dsn")
        check("minconn=2 ta ulanish darhol ochildi", FakeConn.created == 2)
        conns = [pool.getconn() for _ in range(10)]
        check("10 ta parallel ulanish (maxconn) berildi", FakeConn.created == 10 and len(pool._used) == 10)
        try:
            pool.getconn()
            exhausted = False
        except db.PoolError:
            exhausted = True
        check("11-chi so'rov PoolError (maxconn oshmaydi)", exhausted and FakeConn.created == 10)
        for c in conns:
            pool.putconn(c)
        check("hammasi qaytgach 10 ta bo'sh ulanish SAQLANDI (standart pool: 2 ta)",
              len(pool._pool) == 10 and not pool._used, f"{len(pool._pool)}/{len(pool._used)}")
        again = [pool.getconn() for _ in range(10)]
        check("2-to'lqin YANGI ulanish ochmadi (handshake yo'q)", FakeConn.created == 10)
        for c in again:
            pool.putconn(c)
        # nomaʼlum/ikki marta qaytarilgan ulanish — standart xatti-harakat
        try:
            pool.putconn(again[0])
            twice = False
        except db.PoolError:
            twice = True
        check("ikkinchi marta putconn → PoolError (leak/dublikat himoyasi)", twice)
        # putconn(close=True) — ulanish yopiladi va pool'ga qaytmaydi
        c = pool.getconn()
        pool.putconn(c, close=True)
        check("putconn(close=True) ulanishni yopdi", c.closed == 1 and c not in pool._pool)
        pool.closeall()


def test_idle_ttl_shrinks_to_minconn():
    print("== _WarmPool: IDLE_TTL dan keyin minconn gacha qisqaradi ==")
    with fake_psycopg(), patched(db, DB_POOL_IDLE_TTL=0.05):
        pool = db._WarmPool(2, 6, "dsn")
        conns = [pool.getconn() for _ in range(6)]
        for c in conns:
            pool.putconn(c)
        check("qaytgach 6 ta bo'sh", len(pool._pool) == 6)
        time.sleep(0.12)
        c = pool.getconn()
        pool.putconn(c)
        check("TTL o'tgach ortiqchalari yopildi (minconn=2 qoldi)", len(pool._pool) == 2, str(len(pool._pool)))
        check("yopilganlar haqiqatan close() qilindi", sum(1 for x in conns if x.closed) >= 4)
        pool.closeall()


def test_rollback_and_connect_do_not_hold_pool_lock():
    print("== _WarmPool: ROLLBACK va connect umumiy lock'ni ushlamaydi ==")
    with fake_psycopg():
        pool = db._WarmPool(2, 4, "dsn")
        a, b = pool.getconn(), pool.getconn()
        # 1) sekin ROLLBACK (o'qish-tranzaksiya poolga qaytayotgan payt)
        a.status = INTRANS
        in_rollback, release = threading.Event(), threading.Event()
        a.rollback_hook = lambda: (in_rollback.set(), release.wait(5))
        t = threading.Thread(target=pool.putconn, args=(a,))
        t.start()
        started = in_rollback.wait(2)
        t0 = time.monotonic()
        c = pool.getconn()  # boshqa ulanish (yangi) — lock bo'sh bo'lishi shart
        dt = time.monotonic() - t0
        check("sekin ROLLBACK paytida boshqa getconn() bloklanmadi", started and dt < 0.5, f"{dt:.2f}s")
        release.set()
        t.join(2)
        check("ROLLBACK tugagach ulanish poolga qaytdi", not t.is_alive() and a in pool._pool)
        pool.putconn(c)
        pool.closeall()
        # 2) sekin connect (yangi ulanish ochilayotgan payt)
        pool = db._WarmPool(2, 5, "dsn")
        a, b = pool.getconn(), pool.getconn()  # ikkalasi band, bo'sh ulanish yo'q
        FakeConn.connect_gate = gate = threading.Event()
        box = {}
        t2 = threading.Thread(target=lambda: box.setdefault("conn", pool.getconn()))
        t2.start()
        time.sleep(0.1)  # t2 connect() da kutmoqda (lock bo'sh bo'lishi kerak)
        t0 = time.monotonic()
        pool.putconn(a)
        w = pool.getconn()
        dt2 = time.monotonic() - t0
        check("sekin connect() paytida putconn/getconn bloklanmadi", dt2 < 0.5 and w is a, f"{dt2:.2f}s")
        check("ochilayotgan ulanish maxconn hisobiga kirdi", pool._opening == 1)
        gate.set()
        t2.join(2)
        check("ochilayotgan ulanish tugagach berildi", box.get("conn") is not None and pool._opening == 0)
        check("used hisobi to'g'ri (b, w, yangi)", len(pool._used) == 3, str(len(pool._used)))
        del b
        pool.closeall()


def test_dead_idle_connection_is_detected_and_replaced():
    print("== _WarmPool: uzoq bo'sh turgan o'lik ulanish ishlatishdan OLDIN topiladi ==")
    with fake_psycopg(), patched(db, DB_POOL_PING_AFTER=0.05):
        pool = db._WarmPool(2, 5, "dsn")
        c1, c2 = pool.getconn(), pool.getconn()
        pool.putconn(c1)
        pool.putconn(c2)  # LIFO: keyingi getconn c2 ni beradi
        c2.ping_fail = True
        before = FakeConn.created
        time.sleep(0.12)
        got = pool.getconn()
        check("o'lik c2 berilmadi", got is not c2 and not got.closed)
        check("o'lik ulanish yopildi", c2.closed == 1)
        check("boshqa (tirik) bo'sh ulanish ishlatildi — yangi ochilmadi", got is c1 and FakeConn.created == before)
        check("pool hisobi to'g'ri (used=1)", len(pool._used) == 1)
        pool.putconn(got)
        # yangi qaytgan ulanish (idle < PING_AFTER) ping'siz beriladi
        c1.ping_fail = True
        fresh = pool.getconn()
        check("yaqinda ishlatilgan ulanishga ping yuborilmadi", fresh is c1 and not c1.closed)
        pool.closeall()


def test_get_pool_builds_warm_pool_with_min_max():
    print("== _get_pool: minconn/maxconn bilan _WarmPool ==")
    with fake_psycopg():
        db._reset_pool()
        pool = db._get_pool()
        check("_get_pool() → _WarmPool", isinstance(pool, db._WarmPool))
        check("minconn/maxconn DB_POOL_MIN/DB_POOL_MAX dan", pool.minconn == db.DB_POOL_MIN and pool.maxconn == db.DB_POOL_MAX)
        conn = db._acquire_connection()
        st = db.get_db_pool_status()
        check("get_db_pool_status: used=1", st.get("used") == 1, str(st))
        db._release_connection(conn)
        st = db.get_db_pool_status()
        check("qaytgach used=0 va ulanish saqlandi", st.get("used") == 0 and st.get("available", 0) >= 1, str(st))
        check("semafor tiklandi", db._get_semaphore()._value == db.DB_POOL_MAX)
        db._reset_pool()


def test_acquire_does_not_reset_pool_on_connect_error():
    print("== _acquire_connection: connect xatosi butun poolni buzmaydi ==")
    with fake_psycopg():
        db._reset_pool()
        pool = db._get_pool()
        busy = db._acquire_connection()  # band ulanish (boshqa so'rov)
        real = psycopg2.connect
        boom = {"n": 1}

        def flaky(*a, **k):
            if boom["n"]:
                boom["n"] -= 1
                raise psycopg2.OperationalError("timeout expired")
            return real(*a, **k)

        # bo'sh ulanishlarni band qilamiz — keyingi getconn yangi ulanish ochishga majbur
        held = [pool.getconn() for _ in range(max(0, len(pool._pool)))]
        psycopg2.connect = flaky
        try:
            conn = db._acquire_connection()  # 1-urinish xato, 2-urinish muvaffaqiyatli
        finally:
            psycopg2.connect = real
        check("bitta connect xatosidan keyin qayta urinish ishladi", conn is not None)
        check("pool obyekti QAYTA QURILMADI (band ulanishlar tirik)", db._pool is pool and not pool.closed and not busy.closed)
        db._release_connection(conn)
        db._release_connection(busy)
        for h in held:
            pool.putconn(h)
        db._reset_pool()


# ------------------------------------------------------------------ profil keshi
ROW = ("ru", "abc", "user1", "Full Name", 7, 3, "pro", None, 2, 4)


class ProfileCur:
    queries = 0
    row = ROW
    rowcount = 1

    def execute(self, sql, params=None):
        if "language_code, u.user_code" in sql or "FROM users u" in sql:
            ProfileCur.queries += 1

    def fetchone(self):
        return ProfileCur.row


@contextmanager
def fake_profile_db():
    ProfileCur.queries = 0
    ProfileCur.row = ROW

    @contextmanager
    def cursor(commit=False):
        yield ProfileCur()

    db._cache_clear()
    with patched(db, db_cursor=cursor):
        try:
            yield
        finally:
            db._cache_clear()


def test_profile_cache_roundtrip():
    print("== profil keshi: bitta so'rov, nusxa, TTL, invalidatsiya ==")
    with fake_profile_db():
        check("kesh sovuq: peek None", db.peek_user_profile(1) is None)
        p = db.get_user_profile(1)
        check("profil BITTA so'rov bilan o'qildi", ProfileCur.queries == 1 and p is not None)
        check("maydonlar to'g'ri", (p["lang"], p["user_code"], p["ai_credits"], p["streak"],
                                    p["referrals_count"], p["channels_count"], p["is_pro"])
              == ("ru", "abc", 7, 3, 2, 4, True), str(p))
        p["lang"] = "XX"
        check("qaytarilgan nusxani o'zgartirish keshga tegmaydi", db.peek_user_profile(1)["lang"] == "ru")
        db.get_user_profile(1)
        check("2-chaqiruv keshdan (0 so'rov)", ProfileCur.queries == 1)
        # eski accessor'lar profil RAM'da bo'lsa DB'ga bormaydi
        db._cache_clear("user_")
        check("get_referral_stats RAM profilidan",
              db.get_referral_stats(1) == {"referrals_count": 2, "ai_credits": 7, "streak": 3} and ProfileCur.queries == 1)
        check("get_user_code RAM profilidan", db.get_user_code(1) == "abc" and ProfileCur.queries == 1)
        check("get_user_language RAM profilidan", db.get_user_language(1) == "ru" and ProfileCur.queries == 1)
        # til almashtirish — write-through (qayta o'qish YO'Q)
        check("set_user_language True", db.set_user_language(1, "en") is True)
        check("til RAM profilida yangilandi (write-through), qayta so'rov yo'q",
              db.peek_user_profile(1)["lang"] == "en" and ProfileCur.queries == 1)
        # invalidatsiya
        db._invalidate_user(1)
        check("_invalidate_user profilni o'chirdi", db.peek_user_profile(1) is None)
        db.get_user_profile(1)
        check("invalidatsiyadan keyin qayta yuklandi", ProfileCur.queries == 2)
        db._cache_clear()
        check("_cache_clear() profilni ham tozaladi", db.peek_user_profile(1) is None)
        # foydalanuvchi yo'q → None (chaqiruvchi eski yo'lga qaytadi), keshlanmaydi
        ProfileCur.row = None
        check("noma'lum foydalanuvchi → None", db.get_user_profile(999) is None and db.peek_user_profile(999) is None)
        ProfileCur.row = ROW
        # TTL
        db.get_user_profile(2)
        real_mono = db._time.monotonic
        with patched(db._time, monotonic=lambda: real_mono() + db.DB_PROFILE_CACHE_TTL + 1):
            check("TTL o'tgach profil eskirdi", db.peek_user_profile(2) is None)
        check("TTL default 5 daqiqa (30..3600 oralig'ida)", 30 <= db.DB_PROFILE_CACHE_TTL <= 3600)
        # kanal o'chirilganda (egasi noma'lum) — barcha profillar tozalanadi
        db.get_user_profile(3)
        db._profile_clear_all()
        check("_profile_clear_all barcha profilni tozaladi", db.peek_user_profile(3) is None)


def test_profile_is_pro_is_expiry_aware():
    print("== profil: PRO muddati o'qish paytida hisoblanadi ==")
    now = datetime.now(timezone.utc)
    with fake_profile_db():
        ProfileCur.row = ROW[:6] + ("pro", now + timedelta(days=3)) + ROW[8:]
        check("faol PRO → is_pro True", db.get_user_profile(11)["is_pro"] is True)
        ProfileCur.row = ROW[:6] + ("pro", now - timedelta(seconds=1)) + ROW[8:]
        db._invalidate_user(12)
        check("muddati o'tgan PRO → is_pro False", db.get_user_profile(12)["is_pro"] is False)
        ProfileCur.row = ROW[:6] + ("free", None) + ROW[8:]
        check("free → is_pro False", db.get_user_profile(13)["is_pro"] is False)
        ProfileCur.row = ROW[:6] + ("enterprise", None) + ROW[8:]
        check("enterprise (cheksiz) → is_pro True", db.get_user_profile(14)["is_pro"] is True)
        # keshdagi PRO obuna vaqti o'tib ketsa, kesh yangilanmasa ham False bo'ladi
        ProfileCur.row = ROW[:6] + ("pro", now + timedelta(seconds=30)) + ROW[8:]
        db.get_user_profile(15)
        real = db.datetime
        later = now + timedelta(seconds=60)

        class _Later(real):
            @classmethod
            def now(cls, tz=None):
                return later if tz else later.replace(tzinfo=None)

        with patched(db, datetime=_Later):
            check("kesh ichida muddat tugadi → is_pro False", db.peek_user_profile(15)["is_pro"] is False)


class TxPool:
    def __init__(self):
        self.got = self.put = 0

    def getconn(self):
        self.got += 1
        return FakeConn()

    def putconn(self, conn, close=False):
        self.put += 1


def test_invalidate_inside_transaction_runs_again_after_commit():
    print("== _invalidate_user tranzaksiya ichida: COMMIT'dan keyin yana bajariladi ==")
    snap = {"user_id": 77, "lang": "uz", "user_code": "c", "username": "", "full_name": "",
            "ai_credits": 1, "streak": 0, "plan_type": "free", "expires_at": None,
            "referrals_count": 0, "channels_count": 0}
    with fake_profile_db():
        pool = TxPool()
        with patched(db, _get_pool=lambda: pool):
            with db.db_transaction():
                db._invalidate_user(77)
                # COMMIT'dan oldin boshqa thread eski qiymatni qayta o'qib keshladi (poyga)
                db._profile_store(77, dict(snap), time.monotonic())
                check("(poyga simulyatsiyasi) tranzaksiya ichida eski profil keshlandi",
                      db.peek_user_profile(77) is not None)
            check("COMMIT'dan keyin eski profil BEKOR qilindi", db.peek_user_profile(77) is None)
            # o'qish rejimidagi tranzaksiyada ilgak ishlatilmaydi va xato bermaydi
            with db.db_transaction(commit=False):
                db._invalidate_user(77)
            check("ROLLBACK bo'lgan tranzaksiyada ilgak ishlamaydi (xatosiz)", True)
            try:
                with db.db_transaction():
                    db._invalidate_user(78)
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            check("ulanishlar qaytdi (getconn == putconn)", pool.got == pool.put, f"{pool.got}/{pool.put}")
        # yuklash boshlangan, keyin bekor qilingan → eskirgan natija keshlanmaydi
        started = time.monotonic()
        db._invalidate_user(79)
        db._profile_store(79, dict(snap, user_id=79), started)
        check("yuklash paytida bekor qilingan natija keshlanmadi", db.peek_user_profile(79) is None)
        started = time.monotonic()
        db._cache_clear()
        db._profile_store(80, dict(snap, user_id=80), started)
        check("_cache_clear() paytida yuklangan natija keshlanmadi", db.peek_user_profile(80) is None)


class _NullCur:
    """Yangi foydalanuvchi oqimi uchun eng sodda kursor: hech narsa topilmaydi."""
    rowcount = 1

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return None


def test_register_new_user_retries_on_user_code_collision():
    print("== register_new_user: user_code UNIQUE to'qnashuvida qayta uriniladi ==")
    from services.referral_service import ReferralService
    collision = 'duplicate key value violates unique constraint "users_user_code_key"'
    state = {"n": 0, "fail_times": 1, "error": collision}

    @contextmanager
    def flaky_tx(*a, **k):
        state["n"] += 1
        if state["n"] <= state["fail_times"]:
            raise RuntimeError(state["error"])
        yield _NullCur()

    with patched(db, db_transaction=flaky_tx):
        res = ReferralService.register_new_user(990001, "u", "N")
        check("1-urinishda to'qnashuv, 2-urinishda muvaffaqiyat: foydalanuvchi ro'yxatdan o'tdi",
              res.get("is_new") is True and not res.get("error") and state["n"] == 2, f"{res} {state}")
        state.update(n=0, fail_times=99)
        res = ReferralService.register_new_user(990002, "u", "N")
        check("doimiy to'qnashuv: 1 + 3 marta urinib, xato qaytaradi (cheksiz sikl yo'q)",
              state["n"] == 4 and res.get("error") and res.get("is_new") is False, f"{res} {state}")
        state.update(n=0, fail_times=99, error="connection refused")
        res = ReferralService.register_new_user(990003, "u", "N")
        check("boshqa xato (to'qnashuv emas): qayta urinilmaydi", state["n"] == 1 and res.get("error"), str(state))


# ------------------------------------------------------------------ handlerlar
def _user(uid, username="tester", full_name="Test User"):
    return SimpleNamespace(id=uid, username=username, full_name=full_name,
                           first_name="Test", language_code="uz")


class _Msg:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kw):
        self.replies.append(text)


def _prime(uid, **over):
    snap = {"user_id": uid, "lang": "ru", "user_code": "zz9", "username": "tester", "full_name": "Test User",
            "ai_credits": 12, "streak": 2, "plan_type": "free", "expires_at": None,
            "referrals_count": 5, "channels_count": 3}
    snap.update(over)
    db._profile_store(uid, snap, time.monotonic())


def test_start_and_settings_answer_from_cache_without_db():
    print("== /start va Sozlamalar: kesh bor → DB'ga tegilmaydi; yo'q → eski yo'l ==")
    st = importlib.import_module("handlers.start")
    calls = []

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        calls.append(name)
        return {"save_user": True, "get_user_language": "uz", "is_premium": False, "get_setting": "",
                "get_referral_stats": {"referrals_count": 1, "ai_credits": 9, "streak": 1},
                "get_user_channels": [("-100", "K")], "get_user_code": "old1"}.get(name)

    async def fake_check(bot, uid):
        return True, []

    async def no_ad(uid):
        return ""

    def run_start(user):
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=user, effective_message=msg)
        ctx = SimpleNamespace(bot=SimpleNamespace(), user_data={}, chat_data={}, args=[])
        asyncio.run(st.start(upd, ctx))
        return msg, ctx

    db._cache_clear()
    with patched(db, run_db=fake_run_db), patched(st, check_user_subscribed=fake_check,
                                                  get_smart_reply_ad_async=no_ad):
        # 1) kesh sovuq → eski yo'l: save_user chaqiriladi
        calls.clear()
        run_start(_user(880010))
        check("kesh sovuq: save_user chaqirildi (eski yo'l o'zgarmagan)", "save_user" in calls, str(calls))
        # 2) kesh bor, ma'lumot o'zgarmagan → save_user chaqirilmaydi, til keshdan
        _prime(880011)
        calls.clear()
        msg, ctx = run_start(_user(880011))
        check("kesh bor: save_user CHAQIRILMADI", "save_user" not in calls, str(calls))
        check("kesh bor: DB so'rovlari yo'q (get_user_language ham)",
              "get_user_language" not in calls and "get_referral_stats" not in calls, str(calls))
        check("javob profil tilida (ru) chiqdi", bool(msg.replies) and ctx.user_data.get("lang") == "ru", str(ctx.user_data))
        # 3) username o'zgardi → save_user chaqiriladi
        calls.clear()
        run_start(_user(880011, username="renamed"))
        check("username o'zgardi: save_user chaqirildi", "save_user" in calls, str(calls))
        # 4) ref-havola bilan har doim save_user
        _prime(880012)
        calls.clear()
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=_user(880012), effective_message=msg)
        ctx = SimpleNamespace(bot=SimpleNamespace(), user_data={}, chat_data={}, args=["ref_555"])
        asyncio.run(st.start(upd, ctx))
        check("ref-havola: save_user chaqirildi", "save_user" in calls, str(calls))

        # Sozlamalar: kesh bor → 0 ta DB chaqiruvi
        _prime(880013, lang="uz")
        calls.clear()
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=_user(880013), effective_message=msg)
        ctx = SimpleNamespace(bot=SimpleNamespace(), user_data={"lang": "uz"}, chat_data={}, args=[])
        asyncio.run(st.user_cabinet_menu(upd, ctx))
        check("Sozlamalar (kesh bor): DB chaqiruvi 0 ta", not calls, str(calls))
        text = msg.replies[0] if msg.replies else ""
        check("Sozlamalar matni profil ma'lumotlarini ko'rsatdi (kod, 12 ball, 3 kanal, 5 do'st)",
              all(x in text for x in ("zz9", "12", "3", "5")), text[:200])
        # Sozlamalar: kesh yo'q (fake run_db profilni yuklamaydi) → eski 3 ta chaqiruv
        db._cache_clear()
        calls.clear()
        msg = _Msg()
        upd = SimpleNamespace(message=msg, effective_user=_user(880014), effective_message=msg)
        ctx = SimpleNamespace(bot=SimpleNamespace(), user_data={"lang": "uz"}, chat_data={}, args=[])
        asyncio.run(st.user_cabinet_menu(upd, ctx))
        check("Sozlamalar (kesh yo'q): eski yo'l — stats, kanallar, kod",
              calls[:3] == ["get_referral_stats", "get_user_channels", "get_user_code"], str(calls))
        check("eski yo'lda matn to'g'ri (old1 kodi, 1 kanal, 9 ball)",
              bool(msg.replies) and all(x in msg.replies[0] for x in ("old1", "9")), msg.replies[:1])

    # reklama satri: PRO profil → is_premium so'ralmaydi
    from utils import helpers
    calls.clear()
    with patched(db, run_db=fake_run_db):
        _prime(880015, plan_type="pro", expires_at=datetime.now(timezone.utc) + timedelta(days=5))
        out = asyncio.run(helpers.get_smart_reply_ad_async(880015))
        check("PRO profil (RAM): reklama yo'q va is_premium so'ralmadi", out == "" and "is_premium" not in calls, str(calls))
        calls.clear()
        asyncio.run(helpers.get_smart_reply_ad_async(880016))
        check("profil yo'q: is_premium eski yo'l bilan so'raladi", "is_premium" in calls, str(calls))
    db._cache_clear()


if __name__ == "__main__":
    test_pool_keeps_idle_connections_up_to_maxconn()
    test_idle_ttl_shrinks_to_minconn()
    test_rollback_and_connect_do_not_hold_pool_lock()
    test_dead_idle_connection_is_detected_and_replaced()
    test_get_pool_builds_warm_pool_with_min_max()
    test_acquire_does_not_reset_pool_on_connect_error()
    test_profile_cache_roundtrip()
    test_profile_is_pro_is_expiry_aware()
    test_invalidate_inside_transaction_runs_again_after_commit()
    test_register_new_user_retries_on_user_code_collision()
    test_start_and_settings_answer_from_cache_without_db()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}")
        print("Pool/profil kesh testlarida xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0")
    print("Barcha pool/profil kesh testlari muvaffaqiyatli o'tdi ✔")
