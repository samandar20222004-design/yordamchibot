import os
import asyncio
import contextvars
import hashlib
import itertools as _itertools
import json
import logging
import random
import string
import threading
import time as _time
from datetime import datetime, timedelta
from contextlib import contextmanager, asynccontextmanager
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
import pytz
from config import DATABASE_URL

tashkent_tz = pytz.timezone("Asia/Tashkent")

logger = logging.getLogger(__name__)

# Render Free PostgreSQL uchun ulanishlar soni cheklangan (odatda 5 ta).
# DB_POOL_MAX ni oshirishdan oldin Render'da Postgres ulanish limitini tekshiring.
DB_POOL_MIN = max(0, int(os.getenv("DB_POOL_MIN", "0")))
DB_POOL_MAX = max(DB_POOL_MIN + 1, int(os.getenv("DB_POOL_MAX", "5")))
# Har bir scheduler ishlashida ko'pi bilan shuncha post yuboriladi
# (ulkan navbat bitta tick'ni to'sib qo'ymasligi uchun).
POST_BATCH_SIZE = max(1, int(os.getenv("POST_BATCH_SIZE", "100")))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "20"))

# Kanonik sxema fayli (database.py bilan bir katalogda yuradi).
SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

# Startup schema check: bot ishga tushganda mavjudligi tasdiqlanadigan
# jadvallar va indekslar (schema.sql bilan bir xil bo'lishi shart —
# tests/schema_test.py buni tekshirib turadi). Legacy ro'yxatlar saqlanadi;
# P0 obyektlari alohida REQUIRED_P0_* orqali ham startup'da tekshiriladi.
EXPECTED_TABLES = (
    "users", "channels", "sponsor_channels", "system_settings",
    "bot_settings", "ad_pool", "channel_post_counters", "scheduled_posts",
    "post_reactions", "sent_post_messages", "promo_codes", "payments",
    "payment_receipts", "channel_posts_history",
    # PostAssist V2 (6-bosqich): RBAC rollari va admin auditi.
    "admin_roles", "admin_audit_logs",
)
EXPECTED_INDEXES = (
    "idx_ad_pool_scope",
    "idx_channel_post_counters_updated",
    "idx_payments_user_id",
    "idx_payment_receipts_status",
    "idx_scheduled_posts_status_time",
    "idx_scheduled_posts_user_id",
    "idx_channels_user_id",
    "idx_post_reactions_post_id",
    "idx_channel_posts_history_channel_date",
    # PostAssist V2 (5-bosqich): scheduler/bot tezligi va FK ustunlari.
    "idx_posts_sched_status",
    "idx_deliveries_lookup",
    "idx_payments_user",
    "idx_channels_owner",
    "idx_scheduled_posts_channel",
    "idx_deliveries_post",
    # PostAssist V2 (6-bosqich): admin harakatlari auditi indeksi.
    "idx_audit_admin",
)
REQUIRED_P0_TABLES = ("promo_redemptions", "post_deliveries")
REQUIRED_P0_INDEXES = ("idx_deliveries_sched", "idx_deliveries_retry", "uq_payments_telegram_charge_id")

# --- MA'LUMOTLAR BUTUNLIGI (PostAssist V2 — 5-bosqich) -------------------
# Kanonik ro'yxat: schema.sql'dagi "5-BOSQICH" bo'limi bilan bir xil bo'lishi
# shart (tests/db_integrity_test.py buni tekshirib turadi). Har bir element
# idempotent: obyekt allaqachon bo'lsa qayta yaratilmaydi, mavjud ma'lumotlar
# esa umidan o'chirilmaydi yoki o'zgartirilmaydi.
#
# ``kind`` qiymatlari:
#   fk    — jadvallararo bog'lanish (ota yozuv bo'lmasa — yangi qator rad etiladi);
#   check — qiymatlar to'plami (noma'lum status yozib bo'lmaydi);
#   unique— takrorlanmas juftlik.
#
# Xavfsizlik qoidasi: eski (legacy) yozuvlar talabga javob bermasa, constraint
# ``NOT VALID`` holatida qo'shiladi — ya'ni tarix tekshirilmaydi (ma'lumot
# buzilmaydi), lekin BARCHA YANGI yozuvlar baribir himoyalanadi.
INTEGRITY_CONSTRAINTS = (
    {
        "table": "channels",
        "name": "fk_channels_user",
        "kind": "fk",
        "definition": "FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE",
        "note": "har bir kanal mavjud foydalanuvchiga tegishli bo'ladi",
    },
    {
        "table": "scheduled_posts",
        "name": "fk_scheduled_posts_channel",
        "kind": "fk",
        "definition": "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "note": "post faqat ro'yxatdan o'tgan kanalga rejalanadi",
    },
    {
        "table": "post_deliveries",
        "name": "fk_post_deliveries_post",
        "kind": "fk",
        "definition": "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "note": "delivery markeri doim haqiqiy postga bog'liq",
    },
    {
        "table": "post_reactions",
        "name": "fk_post_reactions_post",
        "kind": "fk",
        "definition": "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "note": "yetim reaksiyalar endi DB tomonidan yo'q qilinadi",
    },
    {
        "table": "promo_redemptions",
        "name": "uq_promo_user",
        "kind": "unique",
        "definition": "UNIQUE (promo_id, user_id)",
        "note": "bitta kod — bitta foydalanuvchi uchun bir marta",
    },
    {
        "table": "post_deliveries",
        "name": "chk_post_deliveries_status",
        "kind": "check",
        "definition": "CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter'))",
        "note": "delivery holatlari faqat 3-bosqich jadvalidagilar",
    },
    {
        "table": "scheduled_posts",
        "name": "chk_scheduled_posts_status",
        "kind": "check",
        "definition": (
            "CHECK (status IN ('pending', 'processing', 'posted', 'failed', "
            "'cancelled', 'completed'))"
        ),
        "note": (
            "5-bosqich topshig'ida 4 ta status so'ralgan, biroq bot "
            "'processing' (claim) va 'completed' (recurring tick) holatlarini "
            "ham ishlatadi — ularsiz CHECK scheduler'ni buzardi"
        ),
    },
    {
        "table": "payments",
        "name": "chk_payments_status",
        "kind": "check",
        "definition": "CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded'))",
        "note": "Stars/To'lov audit holatlari (yangi ustun)",
    },
)

#: Startup'da mavjudligi tekshiriladigan constraintlar (schema.sql bilan bir xil).
INTEGRITY_CONSTRAINT_NAMES = tuple(item["name"] for item in INTEGRITY_CONSTRAINTS)

#: Kompozit indekslar: (nom, jadval, ustunlar ifodasi, SQL). ``ddl`` — schema.sql
# bilan bir xil matn; ``require_all`` — testlar bu indekslarni talab qiladi.
INTEGRITY_INDEXES = (
    {
        "name": "idx_posts_sched_status",
        "table": "scheduled_posts",
        "columns": "(status, scheduled_time)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_posts_sched_status "
               "ON scheduled_posts (status, scheduled_time) WHERE status = 'pending'",
        "note": "scheduler'ning eng issiq so'rovi: pending navbati (get_due_posts)",
    },
    {
        "name": "idx_deliveries_lookup",
        "table": "post_deliveries",
        "columns": "(status, post_id, channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_deliveries_lookup "
               "ON post_deliveries (status, post_id, channel_id)",
        "note": "delivery holati bo'yicha filtr + post/kanal bo'yicha izlash",
    },
    {
        "name": "idx_payments_user",
        "table": "payments",
        "columns": "(user_id, status)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_payments_user ON payments (user_id, status)",
        "note": "foydalanuvchi to'lov tarixi (holat bo'yicha)",
    },
    {
        "name": "idx_channels_owner",
        "table": "channels",
        "columns": "(user_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_channels_owner ON channels (user_id) WHERE is_active = TRUE",
        "note": "get_user_channels (faqat faol kanallar) — idx_channels_user_id'ni takrorlamaydi",
    },
    {
        "name": "idx_scheduled_posts_channel",
        "table": "scheduled_posts",
        "columns": "(channel_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_scheduled_posts_channel ON scheduled_posts (channel_id)",
        "note": "FK (channel_id) tufayli kanal o'chirish/cascade tekshiruvlari tez bo'ladi",
    },
    {
        "name": "idx_deliveries_post",
        "table": "post_deliveries",
        "columns": "(post_id)",
        "ddl": "CREATE INDEX IF NOT EXISTS idx_deliveries_post ON post_deliveries (post_id)",
        "note": "post o'chirilganda cascade tekshiruvi uchun",
    },
)
INTEGRITY_INDEX_NAMES = tuple(item["name"] for item in INTEGRITY_INDEXES)


def resolve_sslmode(url: str = None) -> str:
    """Ulanish uchun sslmode'ni aniqlaydi (bo'sh satr = aralashmaslik).

    Tartib:
      1) URL ichida ``sslmode=`` bo'lsa — hech narsa qo'shmaymiz (URL g'olib).
      2) ``DB_SSLMODE`` env berilgan bo'lsa — aynan shu ishlatiladi
         (masalan: disable | allow | prefer | require | verify-full).
      3) Aks holda avtomatik: lokal host (localhost/127.0.0.1/::1) uchun
         ``prefer``, masofaviy host (Neon, Render va h.k.) uchun ``require`` —
         Neon TLS'siz ulanishni umuman qabul qilmaydi.
    """
    url = DATABASE_URL if url is None else url
    url = url or ""
    if "sslmode=" in url:
        return ""
    env_mode = os.getenv("DB_SSLMODE", "").strip().lower()
    if env_mode:
        return env_mode
    host = ""
    try:
        from urllib.parse import urlparse
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        pass
    if host in ("", "localhost", "127.0.0.1", "::1"):
        return "prefer"
    return "require"


def _connect_kwargs() -> dict:
    """psycopg2.connect()/ThreadedConnectionPool uchun umumiy parametrlar.

    SSL (Neon talab qiladi) va TCP keepalive'lar (serverless bazalar bo'sh
    turuvchi ulanishlarni o'chirib qo'yadi — keepalive buni yumshatadi).
    """
    kwargs = {
        "connect_timeout": DB_CONNECT_TIMEOUT,
        "application_name": "yordamchibot",
        "keepalives": 1,
        "keepalives_idle": 45,
        "keepalives_interval": 10,
        "keepalives_count": 5,
    }
    sslmode = resolve_sslmode()
    if sslmode:
        kwargs["sslmode"] = sslmode
    return kwargs

# Tez-tez o'qiladigan (va kam o'zgaradigan) ma'lumotlar uchun kichik TTL kesh.
# Render Free'da har bir Telegram click DB so'rovini kamaytirish jiddiy
# yuklama pasaytiradi. Yozish funksiyalarida tegishli kesh avtomatik tozalanadi.
DB_CACHE_ENABLED = os.getenv("DB_CACHE_ENABLED", "1") == "1"
DB_SETTINGS_CACHE_TTL = max(1, int(os.getenv("DB_SETTINGS_CACHE_TTL", "60")))
DB_SPONSORS_CACHE_TTL = max(1, int(os.getenv("DB_SPONSORS_CACHE_TTL", "30")))
DB_USER_CACHE_TTL = max(1, int(os.getenv("DB_USER_CACHE_TTL", "15")))
DB_STATS_CACHE_TTL = max(1, int(os.getenv("DB_STATS_CACHE_TTL", "30")))

_pool = None
_pool_lock = threading.Lock()
_pool_sem = None

# Kesh holati. ``_CACHE[key] = (expiry_timestamp, value)``
_CACHE = {}
_CACHE_LOCK = threading.Lock()
_MISS = object()


def _get_pool() -> ThreadedConnectionPool:
    """Pool'ni yaratib beradi (bir marta, keyin qayta ishlatiladi)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    DB_POOL_MIN, DB_POOL_MAX, DATABASE_URL,
                    **_connect_kwargs(),
                )
    return _pool


def _get_semaphore() -> threading.BoundedSemaphore:
    """Pool'dagi ulanishlar sonini qat'iy cheklaydigan semafor.

    psycopg2 ning ThreadedConnectionPool.getconn() ixtiyoriy vaqt cheklovisiz
    bloklanishi mumkin, shuning uchun ulanishlar sonini semafor orqali
    boshqaramiz — bu ham pool to'lib qolganda botni osib qo'ymaydi.
    """
    global _pool_sem
    if _pool_sem is None:
        with _pool_lock:
            if _pool_sem is None:
                _pool_sem = threading.BoundedSemaphore(DB_POOL_MAX)
    return _pool_sem


def _reset_pool():
    global _pool, _pool_sem
    with _pool_lock:
        if _pool is not None:
            try:
                _pool.closeall()
            except Exception:
                pass
            _pool = None
        _pool_sem = None


def close_pool():
    """Bot to'xtatilganda barcha DB ulanishlarini yopish."""
    _reset_pool()
    logger.info("DB pool yopildi.")


# ---------------- Kichik TTL kesh ----------------

def _cache_get(key):
    """TTL keshidan qiymat olish; topilmasa ``_MISS`` qaytaradi."""
    if not DB_CACHE_ENABLED:
        return _MISS
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item is not None:
            expires_at, value = item
            if _time.time() < expires_at:
                return value
            _CACHE.pop(key, None)
    return _MISS


def _cache_set(key, value, ttl):
    if not DB_CACHE_ENABLED:
        return
    with _CACHE_LOCK:
        _CACHE[key] = (_time.time() + max(1, int(ttl)), value)


def _cache_clear(prefix=None):
    """Keshni tozalash. ``prefix`` berilsa faqat shu old qo'shimchali kalitlar o'chadi."""
    with _CACHE_LOCK:
        if prefix is None:
            _CACHE.clear()
            return
        for k in [k for k in _CACHE if k.startswith(prefix)]:
            _CACHE.pop(k, None)


def _cache_size() -> int:
    with _CACHE_LOCK:
        return len(_CACHE)


def cache_clear():
    """Admin panel uchun: barcha TTL keshini qo'lda tozalash."""
    _cache_clear()
    logger.info("DB kesh tozalandi.")


def _invalidate_user(user_id: int):
    """Bitta foydalanuvchiga tegishli kesh yozuvlarini tozalash."""
    for prefix in ("user_credits", "user_code", "user_channels", "user_stats", "user_lang"):
        _cache_clear(f"{prefix}:{user_id}")


def _invalidate_stats():
    _cache_clear("system_stats")


def get_db_pool_status() -> dict:
    """Admin/health uchun DB pool va kesh holati."""
    pool = _pool
    if pool is None:
        return {
            "ready": False,
            "message": "DB pool hali yaratilmagan",
            "max": DB_POOL_MAX,
            "min": DB_POOL_MIN,
            "used": 0,
            "available": 0,
            "collapsed": False,
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
            "sslmode": resolve_sslmode() or "url",
        }
    try:
        used = len(getattr(pool, "_used", {}))
        available = len(getattr(pool, "_pool", []))
        return {
            "ready": True,
            "message": "OK",
            "max": getattr(pool, "maxconn", DB_POOL_MAX),
            "min": getattr(pool, "minconn", DB_POOL_MIN),
            "used": used,
            "available": available,
            "collapsed": bool(getattr(pool, "closed", False)),
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
            "sslmode": resolve_sslmode() or "url",
        }
    except Exception as e:
        logger.warning("DB pool holatini o'qishda xato: %s", e)
        return {
            "ready": True,
            "message": f"o'qish xatosi: {e}",
            "max": DB_POOL_MAX,
            "min": DB_POOL_MIN,
            "used": 0,
            "available": 0,
            "collapsed": False,
            "cache_enabled": DB_CACHE_ENABLED,
            "cache_entries": _cache_size(),
        }


def _acquire_connection():
    """Pool'dan ulanish olish (maks. 15 soniya kutish). Xatolikda qayta urinadi."""
    sem = _get_semaphore()
    if not sem.acquire(timeout=15):
        raise TimeoutError("DB pool band: 15 soniya ichida bo'sh ulanish topilmadi")
    try:
        try:
            return _get_pool().getconn()
        except Exception as e:
            logger.warning("DB pool xatosi (%s); pool qayta qurilmoqda...", e)
            _reset_pool()
            return _get_pool().getconn()
    except Exception:
        sem.release()
        raise


def _release_connection(conn):
    """Ulanishni pool'ga qaytarish (yana ishlatilishi mumkin)."""
    sem = _get_semaphore()
    try:
        try:
            _get_pool().putconn(conn)
        except Exception:
            conn.close()
    finally:
        sem.release()


def _discard_connection(conn):
    """Buzilgan ulanishni pool'dan butunlay o'chirish."""
    sem = _get_semaphore()
    try:
        try:
            _get_pool().putconn(conn, close=True)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass
    finally:
        sem.release()


# ============================================================
# ATOMIK TRANZAKSIYA YORDAMCHILARI (PostAssist V2 — 5-bosqich)
# ------------------------------------------------------------
# ``db_cursor(commit=True)`` avvallari ham bitta ulanishda implicit BEGIN +
# COMMIT/ROLLBACK qilardi. 5-bosqichda bu xatti-harakat rasmiy, ismli API'ga
# chiqarildi, shunda istalgan qavat (DB funksiyasi, servis yoki async handler)
# nechta SQL bo'lsin — BITTA atomik blokda bajariladi:
#
#   * blok ichida istisno ko'tarilsa  → avtomatik ROLLBACK (qismiy yozuv qolmaydi);
#   * blok muvaffaqiyatli tugasa      → COMMIT;
#   * ich-ma-ich chaqiruvda yangi tranzaksiya OCHILMAYDI — bir ulanishda
#     SAVEPOINT ishlatiladi va qaror tashqi blokka bo'ysunadi;
#   * tranzaksiya ichidagi ``db_cursor()`` qo'shimcha ulanish olmaydi (pool
#     to'lib, o'z-o'zini bloqlab qo'yishi mumkin, shuning uchun bir ulanish
#     va bir tranzaksiya davom etadi);
#   * server ulanishni uzsa — buzilgan ulanish pool'ga qaytarilmaydi.
#
# Sinkron kod uchun:  ``with db_transaction() as cur:``
# Asinxron kod uchun: ``async with transaction() as cur:``
# ============================================================

#: Ruxsat etilgan izolatsiya darajalari (SQL'ga string konkatensiyasi uchun
# oq ro'yxat — chaqiruvchi xato satri hech qachon SQL bo'la olmaydi).
TX_ISOLATION_LEVELS = ("read committed", "repeatable read", "serializable")

#: Tranzaksiya holati (faol blokningsiz o'zi). ContextVar — chunki
# ``asyncio.to_thread`` kontekstni ko'chirib oladi, ya'ni async blok ichida
# ishga tushadigan sinkron ``db_cursor()`` ham shu tranzaksiyani ko'radi.
_TX_CTX = contextvars.ContextVar("postassist_tx", default=None)
_TX_SEQ = _itertools.count(1)


class _Transaction:
    """Bitta atomik blokning holati: ulanish, kursor, savepoint va yakun.

    ``enter()`` — ulanishni oladi (yoki mavjud tranzaksiyada savepoint ochadi),
    ``finish(exc)`` — COMMIT/ROLLBACK va ulanishni pool'ga qaytaradi.
    """

    __slots__ = ("commit", "isolation_level", "readonly", "conn", "cur",
                 "savepoint", "parent", "owns_conn", "_token")

    def __init__(self, commit: bool = True, isolation_level: str = None,
                 readonly: bool = False):
        self.commit = bool(commit)
        level = (isolation_level or "").strip().lower() or None
        if level is not None and level not in TX_ISOLATION_LEVELS:
            raise ValueError(
                f"Noma'lum izolatsiya darajasi: {isolation_level!r} "
                f"(ruxsat etilgan: {', '.join(TX_ISOLATION_LEVELS)})"
            )
        self.isolation_level = level
        self.readonly = bool(readonly)
        self.conn = None
        self.cur = None
        self.savepoint = None
        self.parent = None
        self.owns_conn = True
        self._token = None

    # ---- kirish -------------------------------------------------------
    def enter(self):
        parent = _TX_CTX.get()
        if parent is not None and parent.conn is not None:
            # Ich-ma-ich: BITTA ulanish, SAVEPOINT. Alohida kursor ochiladi —
            # shunda tashqi blokning natijalari (fetchone/fetchall) buzilmaydi.
            self.parent = parent
            self.conn = parent.conn
            self.owns_conn = False
            self.savepoint = f"postassist_tx_{next(_TX_SEQ)}"
            self.cur = self.conn.cursor()
            self.cur.execute(f"SAVEPOINT {self.savepoint}")
            self._token = _TX_CTX.set(self)
            return self.cur

        conn = _acquire_connection()
        self.conn = conn
        try:
            self.cur = conn.cursor()
            if getattr(conn, "autocommit", False):
                # Autocommit ulanishda tranzaksiyani qo'lbella ochamiz.
                self.cur.execute("BEGIN")
            if self.isolation_level:
                self.cur.execute(
                    "SET LOCAL TRANSACTION ISOLATION LEVEL " + self.isolation_level
                )
            if self.readonly:
                self.cur.execute("SET LOCAL TRANSACTION READ ONLY")
            self._token = _TX_CTX.set(self)
        except Exception:
            self._reset_ctx()
            try:
                _discard_connection(conn)
            except Exception:
                pass
            self.conn = None
            raise
        return self.cur

    # ---- chiqish ------------------------------------------------------
    def finish(self, exc: BaseException = None):
        """``exc`` None bo'lsa — COMMIT (yoki savepoint release), aks holda ROLLBACK."""
        self._reset_ctx()
        if self.savepoint is not None:
            try:
                if exc is None:
                    self.cur.execute(f"RELEASE SAVEPOINT {self.savepoint}")
                else:
                    self.cur.execute(f"ROLLBACK TO SAVEPOINT {self.savepoint}")
            except Exception:
                # Ulanish buzilgan bo'lsa savepoint ham yo'q — tashqi blok
                # xatolikni o'zi boshqaradi.
                if exc is None:
                    raise
            finally:
                self._close_cursor()
            return

        conn, self.conn = self.conn, None
        if conn is None:
            return
        try:
            self._close_cursor()
        except Exception:
            pass
        if exc is None:
            try:
                if self.commit:
                    conn.commit()
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                self._retire(conn, broken=True)
                raise
            except Exception:
                # COMMIT o'zi xato berdi — ulanish aniq holatda emas, tashlaymiz.
                self._retire(conn, broken=True)
                raise
            else:
                self._retire(conn, broken=False)
            return
        # Xatolik yo'li: rollback, keyin ulanishni saqlab qolish.
        if isinstance(exc, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            self._retire(conn, broken=True)
            return
        try:
            conn.rollback()
        except Exception:
            self._retire(conn, broken=True)
            return
        self._retire(conn, broken=False)

    # ---- ichki yordamchilar -------------------------------------------
    def _reset_ctx(self):
        token, self._token = self._token, None
        if token is not None:
            try:
                _TX_CTX.reset(token)
            except Exception:
                pass

    def _close_cursor(self):
        cur, self.cur = self.cur, None
        if cur is None:
            return
        try:
            cur.close()
        except Exception:
            pass

    @staticmethod
    def _retire(conn, broken: bool):
        try:
            if broken:
                _discard_connection(conn)
            else:
                _release_connection(conn)
        except Exception:
            try:
                conn.close()
            except Exception:
                pass


@contextmanager
def db_transaction(commit: bool = True, isolation_level: str = None,
                   readonly: bool = False):
    """Atomik tranzaksiya bloki (sync).

    Muvaffaqiyatli yakunda COMMIT, istisnoda avtomatik ROLLBACK qilinadi.
    Ich-ma-ich chaqirilganda yangi tranzaksiya ochilmaydi — SAVEPOINT
    ishlatiladi (ichki blok xatosi tashqi blokni buzmaydi).

    Ishlatish::

        with db_transaction() as cur:
            cur.execute("INSERT INTO payments ...", (...))
            cur.execute("UPDATE users SET ...", (...))   # bitta atomik blok

    Args:
        commit: ``False`` — o'qish uchun (hech qachon COMMIT qilinmaydi).
        isolation_level: ``read committed`` | ``repeatable read`` | ``serializable``.
        readonly: ``True`` — ``SET LOCAL TRANSACTION READ ONLY`` (tasodifiy
            yozishlarni bloklaydi).
    """
    tx = _Transaction(commit=commit, isolation_level=isolation_level, readonly=readonly)
    cur = tx.enter()
    try:
        yield cur
    except BaseException as exc:
        tx.finish(exc)
        raise
    tx.finish(None)


def current_transaction() -> _Transaction:
    """Faol tranzaksiya obyekti yoki ``None`` (tashqi chaqiruvlar uchun)."""
    return _TX_CTX.get()


@asynccontextmanager
async def transaction(commit: bool = True, isolation_level: str = None,
                     readonly: bool = False):
    """Asinxron atomik tranzaksiya bloki — ``db_transaction`` o'rami.

    psycopg2 sinkron, shuning uchun BEGIN/COMMIT/ROLLBACK alohida thread'da
    bajariladi (event loop bloklanmaydi). ``asyncio.to_thread`` kontekstni
    ko'chirib olgani uchun blok ichidagi sinkron ``db_cursor()`` chaqiruvlari
    ham shu tranzaksiyaga qo'shiladi.

    Ishlatish::

        async with transaction() as cur:
            await asyncio.to_thread(cur.execute, "INSERT INTO ...", (...))
    """
    holder = {}

    def _begin():
        tx = _Transaction(commit=commit, isolation_level=isolation_level,
                          readonly=readonly)
        cur = tx.enter()
        holder["tx"] = tx
        return cur

    cur = await asyncio.to_thread(_begin)
    # ``_begin`` alohida thread'da ishlagani uchun ContextVar shu thread'ning
    # nusxa ko'chirilgan kontekstiga yozildi — uni joriy (task) kontekstga ham
    # o'rnatamiz, shunda blok ichidagi sinkron ``db_cursor()`` chaqiruvlari ham
    # shu tranzaksiyani ko'radi.
    token = _TX_CTX.set(holder["tx"])
    try:
        yield cur
    except BaseException as exc:
        _TX_CTX.reset(token)
        await asyncio.to_thread(holder["tx"].finish, exc)
        raise
    else:
        _TX_CTX.reset(token)
        await asyncio.to_thread(holder["tx"].finish, None)


#: Asinxron API uchun qo'shimcha nom (chaqiruvchi uslubiga qarab).
atransaction = transaction


def db_cursor(commit: bool = False):
    """DB kursori (kanalik nomi). ``transaction()`` yordamchisiga delegat.

    ``commit=True`` — blok muvaffaqiyatli tugaganda COMMIT (atomik tranzaksiya),
    ``commit=False`` — o'qish rejimi (xatoda rollback, lekin COMMIT yo'q).
    Faol tranzaksiya ichida chaqirilsa, yangi ulanish OLINMAYDI — mavjud
    tranzaksiyaning SAVEPOINT'ida ishlanadi.
    """
    return db_transaction(commit=commit)


async def run_db(func, *args, **kwargs):
    """Sync DB funksiyasini alohida thread'da bajaradi — event loop bloklanmaydi.

    Async handler/scheduler ichida to'g'ridan-to'g'ri sync DB chaqirmang:
        result = await db.run_db(db.get_due_posts, now)
    """
    return await asyncio.to_thread(func, *args, **kwargs)


# Eski nom — mavjud chaqiruvlar ishlashi uchun
run_in_thread = run_db


def ping_db() -> bool:
    """Health-check uchun baza bilan tez aloqa tekshiruvi."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1
    except Exception as e:
        logger.warning(f"DB ping xatosi: {e}")
        return False


# ============================================================
# 🩺 SYSTEM HEALTH CHECK (PostAssist V2 — 7-BOSQICH)
# ------------------------------------------------------------
# HealthService (services/health_service.py) ishlatadigan yengil
# DB so'rovlari. HECH QANDAY mavjud funksiyani o'zgartirmaydi —
# faqat QO'SHIMCHA, xatosiz (hech qachon istisno ko'tarmaydi).
# ============================================================

def ping_db_with_latency() -> dict:
    """Neon DB ga oddiy ``SELECT 1`` ping + javob vaqti (latency ms).

    Returns:
        dict: ``{"ok": bool, "latency_ms": float | None, "error": str | None}``
              ``error`` matni FAQAT log/monitoring uchun — foydalanuvchiga
              hech qachon ko'rsatilmaydi (buning uchun global error handler
              va ``safe_html`` javobgar).
    """
    started = _time.perf_counter()
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
            ok = bool(row and row[0] == 1)
        elapsed_ms = (_time.perf_counter() - started) * 1000.0
        if ok:
            return {"ok": True, "latency_ms": round(elapsed_ms, 2), "error": None}
        return {"ok": False, "latency_ms": None,
                "error": "SELECT 1 kutilmagan natija qaytardi"}
    except Exception as e:
        logger.warning("DB ping (latency) xatosi: %s", e)
        return {
            "ok": False,
            "latency_ms": None,
            "error": f"{type(e).__name__}: {e}"[:200],
        }


def get_post_health_counts() -> dict:
    """Scheduler monitoringi uchun postlar holati bo'yicha hisob-kitob.

    Ikki yengil COUNT so'rovi (indekslangan ustunlar):

    * ``scheduled_posts``  → ``pending`` / ``processing`` / ``failed`` /
      ``stale_processing`` (10+ daqiqa 'processing'da qotib qolganlar —
      stale-recovery bilan bir xil chegara);
    * ``post_deliveries``  → ``delivery_failed`` / ``dead_letter``.

    Xato bo'lsa hech qachon istisno ko'tarmaydi — hisoblanagan qismi va
    ``error`` kaliti qaytariladi (health hisoboti yarim bo'lsa ham ishlaydi).
    """
    counts = {
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "stale_processing": 0,
        "delivery_failed": 0,
        "dead_letter": 0,
    }
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'pending'),
                    COUNT(*) FILTER (WHERE status = 'processing'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'processing'
                                     AND processing_started_at
                                         < NOW() - INTERVAL '10 minutes')
                FROM scheduled_posts
            """)
            row = cur.fetchone() or (0, 0, 0, 0)
            counts["pending"] = int(row[0] or 0)
            counts["processing"] = int(row[1] or 0)
            counts["failed"] = int(row[2] or 0)
            counts["stale_processing"] = int(row[3] or 0)

            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'dead_letter')
                FROM post_deliveries
            """)
            drow = cur.fetchone() or (0, 0)
            counts["delivery_failed"] = int(drow[0] or 0)
            counts["dead_letter"] = int(drow[1] or 0)
    except Exception as e:
        logger.warning("Post health hisob-kitobida xato: %s", e)
        counts["error"] = f"{type(e).__name__}: {e}"[:200]
    return counts

def init_db():
    last_err = None
    for attempt in range(3):
        try:
            _init_db_once()
            logger.info("Baza jadvallari tayyor.")
            return
        except psycopg2.OperationalError as e:
            last_err = e
            logger.warning(f"DB ishga tushirishda xatolik ({attempt + 1}/3 urinish): {e}")
            _time.sleep(3)
    raise last_err


def _apply_schema_file(cur) -> bool:
    """Kanonik ``schema.sql`` faylini bajaradi (idempotent).

    Fayl topilmasa (masalan, deploy'da nusxalanmagan bo'lsa) ogohlantirib
    ``False`` qaytaradi — eski ichki DDL zaxira sifatida ishlashda davom etadi.
    """
    if not os.path.exists(SCHEMA_FILE):
        logger.warning("schema.sql topilmadi (%s) — ichki DDL ishlatiladi.", SCHEMA_FILE)
        return False
    with open(SCHEMA_FILE, "r", encoding="utf-8") as f:
        cur.execute(f.read())
    return True


def _sql_literal(value: str) -> str:
    """SQL satr literali (bitta tirnoqlar ikkilantiriladi)."""
    return "'" + str(value).replace("'", "''") + "'"


def _integrity_values_rows() -> str:
    """``INTEGRITY_CONSTRAINTS`` ro'yxatidan DO blokidagi VALUES qatorlari."""
    rows = []
    for item in INTEGRITY_CONSTRAINTS:
        rows.append("            ({table}, {name}, {kind}, {definition})".format(
            table=_sql_literal(item["table"]),
            name=_sql_literal(item["name"]),
            kind=_sql_literal(item["kind"]),
            definition=_sql_literal(item["definition"]),
        ))
    return ",\n".join(rows)


def build_integrity_block() -> str:
    """Ma'lumotlar butunligi (FK/CHECK/UNIQUE) migratsiyasini qaytaradi.

    Ushbu blok ``INTEGRITY_CONSTRAINTS`` ro'yxatidan quriladi va schema.sql'dagi
    statik nusxasi bilan bir xil ish qiladi. Kafolatlar:

      * **Idempotent** — obyekt mavjud bo'lsa (``pg_constraint`` bo'yicha)
        hech narsa qilinmaydi, qayta-qayta bajarish xavfsiz;
      * **Ma'lumot buzilmaydi** — eski (legacy) yozuvlar talabga javob
        bermasa, constraint ``NOT VALID`` holatida qo'shiladi: tarix
        tekshirilmaydi, lekin barcha YANGI yozuvlar himoyalanadi;
      * **Bot to'xtamaydi** — har bir DDL alohida ``BEGIN ... EXCEPTION``
        blokida: bitta muvaffaqiyatsiz constraint qolganlarini va tranzaksiyani
        buzmaydi (faqat RAISE WARNING).
    """
    return """DO $postassist_integrity$
DECLARE
    spec RECORD;
BEGIN
    FOR spec IN
        SELECT * FROM (VALUES
{rows}
        ) AS t(tbl, cname, kind, cdef)
    LOOP
        IF to_regclass(spec.tbl) IS NULL THEN
            RAISE NOTICE 'integrity: % jadvali topilmadi -- % otkazib yuborildi', spec.tbl, spec.cname;
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM pg_constraint c
             WHERE c.conrelid = spec.tbl::regclass AND c.conname = spec.cname
        ) THEN
            CONTINUE;  -- idempotent: constraint allaqachon mavjud
        END IF;
        BEGIN
            EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s', spec.tbl, spec.cname, spec.cdef);
            RAISE NOTICE 'integrity: %.% qoshildi', spec.tbl, spec.cname;
        EXCEPTION
            WHEN foreign_key_violation THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s NOT VALID',
                                   spec.tbl, spec.cname, spec.cdef);
                    RAISE WARNING 'integrity: %.% NOT VALID holatda qoshildi (yetim yozuvlar bor) -- '
                                  'VALIDATE CONSTRAINT orqali tekshirish tugallanadi',
                                  spec.tbl, spec.cname;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
                END;
            WHEN check_violation THEN
                BEGIN
                    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I %s NOT VALID',
                                   spec.tbl, spec.cname, spec.cdef);
                    RAISE WARNING 'integrity: %.% NOT VALID holatda qoshildi (eski qiymatlar chekka mos emas)',
                                  spec.tbl, spec.cname;
                EXCEPTION WHEN OTHERS THEN
                    RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
                END;
            WHEN unique_violation THEN
                RAISE WARNING 'integrity: %.% qoshilmadi -- jadvalda dublikat qatorlar bor, '
                              'avval tozalash kerak', spec.tbl, spec.cname;
            WHEN OTHERS THEN
                RAISE WARNING 'integrity: %.% qoshilmadi: %', spec.tbl, spec.cname, SQLERRM;
        END;
    END LOOP;
END
$postassist_integrity$;""".format(rows=_integrity_values_rows())


#: schema.sql'dagi statik blokning belgisi (testlar shu orqali tekshiradi).
INTEGRITY_BLOCK_MARKER = "$postassist_integrity$"

#: ``integrity_orphan_counts()`` uchun tekshiruvlar:
# (bola jadval, bola ustun, ota jadval, ota ustun).
INTEGRITY_ORPHAN_CHECKS = (
    ("channels", "user_id", "users", "user_id"),
    ("scheduled_posts", "channel_id", "channels", "channel_id"),
    ("post_deliveries", "post_id", "scheduled_posts", "id"),
    ("post_reactions", "post_id", "scheduled_posts", "id"),
    ("promo_redemptions", "promo_id", "promo_codes", "id"),
    ("promo_redemptions", "user_id", "users", "user_id"),
)


def _integrity_indexes_statements() -> list:
    """5-bosqich indekslarining DDL ro'yxati (schema.sql bilan bir xil)."""
    return [item["ddl"] + ";" for item in INTEGRITY_INDEXES]


def _apply_integrity_indexes(cur) -> None:
    """Kompozit indekslarni yaratadi (barchasi ``IF NOT EXISTS`` — idempotent)."""
    for ddl in _integrity_indexes_statements():
        try:
            cur.execute(ddl)
        except Exception as e:
            # Indeksdan xato chiqsa bot ishlashda davom etsin (masalan,
            # ustun migratsiyasi hali bajarmagan eski bazada).
            logger.warning("Integrity indeks yaratilmadi (%s): %s", ddl.split()[5], e)


def _apply_integrity_constraints(cur) -> None:
    """FK/CHECK/UNIQUE constraintlarini qo'llaydi (idempotent DO bloki)."""
    try:
        cur.execute(build_integrity_block())
    except Exception as e:
        # Bitta xato butun init'ni buzmasin: schema.sql allaqachon buni
        # qilgan bo'lishi mumkin yoki DB eski versiya bo'lishi mumkin.
        logger.warning("Integrity constraintlar qo'llanmadi: %s", e)


def _list_integrity_constraints(cur) -> dict:
    """``INTEGRITY_CONSTRAINT_NAMES`` bo'yicha {nom: {"valid": bool}} qaytaradi.

    Jadvallar bo'lmasa yoki bazada xato bo'lsa — bo'sh dict (fail-open).
    """
    if not INTEGRITY_CONSTRAINT_NAMES:
        return {}
    try:
        cur.execute(
            """
            SELECT c.conname, c.convalidated, r.relname
              FROM pg_constraint c
              JOIN pg_class r ON r.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = r.relnamespace
             WHERE n.nspname = current_schema()
               AND c.conname = ANY(%s)
            """,
            (list(INTEGRITY_CONSTRAINT_NAMES),),
        )
        rows = cur.fetchall()
    except Exception as e:
        logger.warning("Integrity constraintlar ro'yxati o'qilmadi: %s", e)
        return {}
    found = {}
    for conname, convalidated, _relname in rows:
        found[conname] = {"valid": bool(convalidated)}
    for name in INTEGRITY_CONSTRAINT_NAMES:
        found.setdefault(name, {"missing": True, "valid": False})
    return found


def integrity_orphan_counts() -> dict:
    """Yetim (ota-yozuvi yo'q) qatorlar soni: ``{"channels.user_id": 0, ...}``.

    Faqat ikkala jadval mavjud bo'lsa sanaladi. Xatoda 0 emas, belgilash
    uchun ``-1`` qaytadi (admin diagnostikasi shuni "tekshirib bo'lmadi"
    deb talqin qiladi).
    """
    counts = {}
    try:
        with db_cursor() as cur:
            for child, ccol, parent, pcol in INTEGRITY_ORPHAN_CHECKS:
                label = f"{child}.{ccol}"
                try:
                    cur.execute("SELECT to_regclass(%s), to_regclass(%s)", (child, parent))
                    child_reg, parent_reg = cur.fetchone()
                    if not child_reg or not parent_reg:
                        counts[label] = 0
                        continue
                    cur.execute(
                        f"SELECT COUNT(*) FROM {child} c "
                        f"LEFT JOIN {parent} p ON p.{pcol} = c.{ccol} "
                        f"WHERE p.{pcol} IS NULL AND c.{ccol} IS NOT NULL"
                    )
                    counts[label] = int(cur.fetchone()[0])
                except Exception as e:
                    logger.warning("Yetim sanagichi xatosi (%s): %s", label, e)
                    counts[label] = -1
    except Exception as e:
        logger.warning("integrity_orphan_counts xatosi: %s", e)
    return counts


def integrity_report() -> dict:
    """Ma'lumotlar butunligi holati — admin diagnostika va testlar uchun.

    Qaytadi::

        {"constraints": {nom: {"valid": bool, ...}},
         "missing": [nom, ...],          # umuman yo'q
         "not_valid": [nom, ...],        # bor, lekin eski yozuvlar tekshirilmagan
         "orphans": {"jadval.ustun": n}, # yetim qatorlar soni
         "indexes": {nom: True|False}}
    """
    report = {"constraints": {}, "missing": [], "not_valid": [], "orphans": {},
              "indexes": {}}
    try:
        with db_cursor() as cur:
            report["constraints"] = _list_integrity_constraints(cur)
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
            )
            indexes = {row[0] for row in cur.fetchall()}
    except Exception as e:
        logger.warning("integrity_report xatosi: %s", e)
        report["error"] = str(e)
        return report
    for name, info in report["constraints"].items():
        if info.get("missing"):
            report["missing"].append(name)
        elif not info.get("valid"):
            report["not_valid"].append(name)
    for name in INTEGRITY_INDEX_NAMES:
        report["indexes"][name] = name in indexes
    report["orphans"] = integrity_orphan_counts()
    return report


def validate_integrity_constraints(names=None) -> dict:
    """``NOT VALID`` holatdagi constraintlarni tekshiradi (VALIDATE CONSTRAINT).

    Katta jadvallarda bu amol READ ONLY qulfini oladi (yozishlar to'xtab
    turadi), shuning uchun avtomatik ishga tushirilmaydi — tungi tekshiruv
    yoki admin buyrug'i uchun ajratilgan. ``DB_VALIDATE_INTEGRITY=1`` bo'lsa
    startup paytida ham bajariladi.

    Qaytadi: ``{nom: 'validated' | 'ok' | 'xato: ...'}``.
    """
    result = {}
    wanted = list(names) if names else list(INTEGRITY_CONSTRAINT_NAMES)
    try:
        with db_cursor(commit=True) as cur:
            current = _list_integrity_constraints(cur)
            for name in wanted:
                info = current.get(name) or {}
                if info.get("missing"):
                    result[name] = "missing"
                    continue
                if info.get("valid"):
                    result[name] = "ok"
                    continue
                table = next((it["table"] for it in INTEGRITY_CONSTRAINTS
                              if it["name"] == name), None)
                if not table:
                    result[name] = "unknown"
                    continue
                try:
                    cur.execute(f"SAVEPOINT validate_{name}")
                    cur.execute(
                        f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}"
                    )
                    cur.execute(f"RELEASE SAVEPOINT validate_{name}")
                    result[name] = "validated"
                except Exception as e:
                    try:
                        cur.execute(f"ROLLBACK TO SAVEPOINT validate_{name}")
                        cur.execute(f"RELEASE SAVEPOINT validate_{name}")
                    except Exception:
                        pass
                    result[name] = f"xato: {e}"
                    logger.warning("VALIDATE CONSTRAINT %s xatosi: %s", name, e)
    except Exception as e:
        logger.error("validate_integrity_constraints xatosi: %s", e)
    return result


def _verify_schema(cur) -> None:
    """Startup schema check: server versiyasi va barcha kutilgan jadvallar
    hamda indekslarning mavjudligi tekshiriladi.

    Jadvallar topilmasa — schema.sql qayta qo'llanadi (o'z-o'zini tiklash) va
    baribir topilmasa RuntimeError: bot yarmi ishlagan holda xato yig'ishidan
    ko'ra, aniq sabab bilan tez o'chishi yaxshi.
    """
    cur.execute("SELECT version()")
    server = str((cur.fetchone() or [""])[0])
    provider = "Neon" if "Neon" in server else server.split(",")[0]
    logger.info("DB server: %s", provider)

    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = current_schema()"
    )
    tables = {row[0] for row in cur.fetchall()}
    required_tables = (*EXPECTED_TABLES, *REQUIRED_P0_TABLES)
    missing_tables = [t for t in required_tables if t not in tables]

    cur.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()"
    )
    indexes = {row[0] for row in cur.fetchall()}
    required_indexes = (*EXPECTED_INDEXES, *REQUIRED_P0_INDEXES)
    missing_indexes = [i for i in required_indexes if i not in indexes]

    if missing_indexes:
        logger.warning("Sxema tekshiruvi: indekslar topilmadi: %s (schema.sql ularni yaratadi)",
                       ", ".join(missing_indexes))

    if missing_tables:
        logger.warning("Sxema tekshiruvi: jadvallar topilmadi: %s — schema.sql qayta qo'llanadi...",
                       ", ".join(missing_tables))
        _apply_schema_file(cur)
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema()"
        )
        tables = {row[0] for row in cur.fetchall()}
        missing_tables = [t for t in required_tables if t not in tables]
        if missing_tables:
            raise RuntimeError(
                "DB sxemasi to'liq emas, jadvallar yaratilmadi: "
                + ", ".join(missing_tables)
                + ". Deploy'da telegram_bot/schema.sql fayli kod bilan birga "
                  "yuborilganini tekshiring."
            )

    logger.info(
        "Sxema tekshiruvi OK: %d/%d jadval, %d/%d indeks.",
        len(required_tables) - len(missing_tables), len(required_tables),
        len(required_indexes) - len(missing_indexes), len(required_indexes),
    )

    # 5-bosqich: ma'lumotlar butunligi (FK / CHECK / UNIQUE) ham tekshiriladi.
    # Topilmasa — schema.sql + ichki migratsiya bloki qayta qo'llanadi; baribir
    # bo'lmasa ogohlantiramiz (bot ishlashda davom etadi — eski bazalarda
    # constraint qo'shish ma'lumot hajmi/tartibi tufayli imkonsiz bo'lishi mumkin).
    constraints = _list_integrity_constraints(cur)
    missing_constraints = [n for n, info in constraints.items() if info.get("missing")]
    if missing_constraints:
        logger.warning("Sxema tekshiruvi: integrity constraintlar topilmadi: %s — qayta qo'llanilmoqda...",
                       ", ".join(missing_constraints))
        _apply_integrity_indexes(cur)
        _apply_integrity_constraints(cur)
        constraints = _list_integrity_constraints(cur)
        missing_constraints = [n for n, info in constraints.items() if info.get("missing")]
        if missing_constraints:
            logger.warning("Integrity constraintlar qo'shib bo'lmadi: %s "
                           "(mavjud ma'lumotni buzmaslik uchun davom etamiz)",
                           ", ".join(missing_constraints))
    not_valid = [n for n, info in constraints.items()
                 if not info.get("missing") and not info.get("valid")]
    if not_valid:
        logger.warning("Integrity: %d ta constraint NOT VALID holatda (eski yozuvlar tekshirilmagan): %s. "
                       "Tungi yuklama kam paytda validate_integrity_constraints() bajaring.",
                       len(not_valid), ", ".join(not_valid))
    if os.getenv("DB_VALIDATE_INTEGRITY", "").strip().lower() in ("1", "true", "yes", "on"):
        validated = validate_integrity_constraints()
        ok = sum(1 for v in validated.values() if v in ("ok", "validated"))
        logger.info("Integrity VALIDATE: %d/%d tayyor.", ok, len(validated))


def _init_db_once():
    with db_cursor(commit=True) as cur:
        # 1) Kanonik sxema — schema.sql (barcha operatorlar idempotent).
        _apply_schema_file(cur)

        # 2) Zaxira ichki DDL: schema.sql fayli topilmasa yoki buzilgan bo'lsa
        # ham baza ishlayverishi uchun saqlanadi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                full_name VARCHAR(255),
                user_code VARCHAR(8) UNIQUE,
                referrer_id BIGINT,
                ai_credits INTEGER DEFAULT 5,
                ad_free_posts INTEGER DEFAULT 0,
                ad_free_active BOOLEAN DEFAULT TRUE,
                streak_days INTEGER DEFAULT 0,
                last_bonus_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                full_menu_unlocked BOOLEAN DEFAULT FALSE
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) UNIQUE NOT NULL,
                channel_title VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sponsor_channels (
                id SERIAL PRIMARY KEY,
                channel_id BIGINT UNIQUE,
                title TEXT,
                username TEXT,
                invite_link TEXT,
                channel_title VARCHAR(255),
                channel_url VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            );
        """)

        # Avtomatik reklama rotatsiya puli. Har bir reklama (kanal posti yoki
        # bot javobi uchun) alohida qator; bot navbatma-navbat (round-robin)
        # ishlatadi. scope: 'channel' | 'reply'.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ad_pool (
                id SERIAL PRIMARY KEY,
                scope VARCHAR(20) NOT NULL,
                text TEXT NOT NULL,
                button_text VARCHAR(64),
                button_url TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_ad_pool_scope ON ad_pool (scope, is_active);")

        # Har bir kanal uchun yuborilgan postlar sanagichi (reklama oralig'i
        # shu sanagich bo'yicha hisoblanadi — kanallar bir-biriga ta'sir qilmaydi).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_post_counters (
                channel_id VARCHAR(255) PRIMARY KEY,
                post_count INTEGER NOT NULL DEFAULT 0,
                ad_count INTEGER NOT NULL DEFAULT 0,
                last_ad_post_number INTEGER NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_post_counters_updated "
            "ON channel_post_counters (updated_at DESC);"
        )

        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                post_type VARCHAR(50) NOT NULL,
                content TEXT,
                file_id TEXT,
                inline_button_text VARCHAR(255),
                inline_button_url TEXT,
                enable_reactions BOOLEAN DEFAULT FALSE,
                reaction_emojis TEXT,
                delete_after_hours INTEGER DEFAULT 0,
                sent_message_id BIGINT,
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                user_post_number INTEGER,
                recurrence_type VARCHAR(20) DEFAULT 'none',
                recurrence_day INTEGER,
                recurrence_time TIME,
                end_date TIMESTAMP WITH TIME ZONE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # P0-01: doimiy, DB-backed delivery idempotency registry.
        # PostAssist V2 (3-bosqich): backoff uchun next_retry_at va kalit
        # tarkibidagi scheduled_time ustunlari qo'shildi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_deliveries (
                id BIGSERIAL PRIMARY KEY,
                post_id BIGINT NOT NULL,
                channel_id BIGINT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'pending',
                attempt_count INT DEFAULT 0,
                telegram_message_id BIGINT,
                idempotency_key TEXT UNIQUE NOT NULL,
                last_error TEXT,
                scheduled_time TIMESTAMPTZ,
                next_retry_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_sched ON post_deliveries(status, post_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_retry ON post_deliveries(status, next_retry_at);")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS post_reactions (
                id SERIAL PRIMARY KEY,
                post_id INTEGER NOT NULL,
                user_id BIGINT NOT NULL,
                reaction_type VARCHAR(10) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(post_id, user_id)
            );
        """)
        # Har bir recurring yuborishni alohida saqlaymiz: eski xabarlar ham o'chadi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sent_post_messages (
                id SERIAL PRIMARY KEY,
                post_id INTEGER NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                message_id BIGINT NOT NULL,
                delete_at TIMESTAMP WITH TIME ZONE,
                deleted_at TIMESTAMP WITH TIME ZONE
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_codes (
                id SERIAL PRIMARY KEY,
                code VARCHAR(50) UNIQUE NOT NULL,
                plan_type VARCHAR(20) NOT NULL DEFAULT 'pro',
                duration_days INTEGER NOT NULL DEFAULT 30,
                max_uses INTEGER DEFAULT NULL,
                current_uses INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS promo_redemptions (
                id BIGSERIAL PRIMARY KEY,
                promo_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                redeemed_at TIMESTAMPTZ DEFAULT NOW(),
                CONSTRAINT uq_promo_user UNIQUE (promo_id, user_id)
            );
        """)

        # Real vaqtli kanal postlari tarixi
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channel_posts_history (
                id SERIAL PRIMARY KEY,
                channel_id VARCHAR(255) NOT NULL,
                message_id BIGINT,
                content TEXT,
                views INTEGER DEFAULT 0,
                post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_channel_posts_history_channel_date "
            "ON channel_posts_history (channel_id, post_date DESC);"
        )

        # Stars to'lovlari uchun alohida audit jadvali.
        # To'lovlar promo_codes jadvaliga yozilmaydi — har bir to'lov o'z
        # qatori bilan audit qilinadi (summa, valyuta, payload, charge_id).
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                amount INT,
                currency VARCHAR(10),
                payload TEXT,
                telegram_payment_charge_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(20) NOT NULL DEFAULT 'succeeded'
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments (user_id);")
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_telegram_charge_id "
            "ON payments (telegram_payment_charge_id) "
            "WHERE telegram_payment_charge_id IS NOT NULL;"
        )

        # 💳 Karta orqali to'lov cheklari — Admin Approval Flow.
        # Foydalanuvchi chek yuborganida pending holatida saqlanadi, adminlarga
        # yuboriladi. Admin tasdiqlaganda status='approved' + PRO uzaytiriladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payment_receipts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username VARCHAR(255),
                full_name VARCHAR(255),
                language_code VARCHAR(10) DEFAULT 'uz',
                media_type VARCHAR(20) DEFAULT 'photo',
                file_id TEXT,
                caption TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP WITH TIME ZONE,
                decided_by BIGINT,
                days_granted INTEGER DEFAULT 30
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_payment_receipts_status "
            "ON payment_receipts (status, created_at);"
        )

        migrations = [
            # P0 backward-compatible migrations (har bir statement savepoint bilan bajariladi).
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS telegram_payment_charge_id TEXT UNIQUE;",
            "ALTER TABLE promo_codes ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_code VARCHAR(8) UNIQUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_credits INTEGER DEFAULT 5;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_posts INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_free_active BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS streak_days INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_bonus_date DATE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_text VARCHAR(255);",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_url TEXT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS enable_reactions BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS reaction_emojis TEXT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS delete_after_hours INTEGER DEFAULT 0;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS sent_message_id BIGINT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS user_post_number INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_type VARCHAR(20) DEFAULT 'none';",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_day INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_time TIME;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS end_date TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE scheduled_posts ALTER COLUMN file_id TYPE TEXT;",
            "ALTER TABLE channels ADD COLUMN IF NOT EXISTS tone_of_voice VARCHAR(30) DEFAULT 'friendly';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS plan_type VARCHAR(20) DEFAULT 'free';",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_expires_at TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS ai_requests_today INTEGER DEFAULT 0;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_limit_reset DATE DEFAULT CURRENT_DATE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS language_code VARCHAR(10) DEFAULT 'uz';",
            # 🆕 Onboarding: "⚙️ To'liq menyuni ochish" bosilganini eslab qolamiz
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_menu_unlocked BOOLEAN DEFAULT FALSE;",
            # 🆕 6-bosqich (RBAC): foydalanuvchi roli. DEFAULT 'user' — barcha
            # eski yozuvlar oddiy foydalanuvchi bo'lib qoladi (backward-compatible).
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS title TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS username TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS invite_link TEXT;",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_title VARCHAR(255);",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS channel_url VARCHAR(255);",
            "ALTER TABLE sponsor_channels ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
            # Reklama puli: HTML matn + inline URL tugma (matn va havola).
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_text VARCHAR(64);",
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS button_url TEXT;",
            "ALTER TABLE ad_pool ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            # Kanal postlari tarixi migratsiyalari
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS message_id BIGINT;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS content TEXT;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS views INTEGER DEFAULT 0;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS post_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE channel_posts_history ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            # PostAssist V2 (3-bosqich): persistent delivery + backoff ustunlari.
            "ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS scheduled_time TIMESTAMPTZ;",
            "ALTER TABLE post_deliveries ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ;",
            # PostAssist V2 (5-bosqich): to'lov audit holati + idx_payments_user
            # (user_id, status) shu ustun bilan quriladi. DEFAULT tufayli eski
            # yozuvlar ham 'succeeded' hisoblanadi (ma'lumot o'zgarmaydi).
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'succeeded';",
        ]
        for index, migration in enumerate(migrations):
            # Bitta migration xatosi qolgan migrationlarni transaction aborted
            # holatiga tushirib qo'ymasligi uchun har birini savepoint bilan bajarish.
            savepoint = f"migration_{index}"
            try:
                cur.execute(f"SAVEPOINT {savepoint}")
                cur.execute(migration)
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception as e:
                cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                cur.execute(f"RELEASE SAVEPOINT {savepoint}")
                logger.warning(f"Migratsiya eslatmasi: {e}")

        # Server crash paytida processing holatida qolgan postlarni qayta navbatga qaytaramiz (idempotent himoya bilan).
        cur.execute("""
            UPDATE scheduled_posts
            SET status = 'posted'
            WHERE status = 'processing'
              AND (sent_message_id IS NOT NULL 
                   OR id IN (SELECT post_id FROM sent_post_messages));
        """)
        cur.execute("""
            UPDATE scheduled_posts
            SET status = 'pending', processing_started_at = NULL
            WHERE status = 'processing'
              AND sent_message_id IS NULL
              AND id NOT IN (SELECT post_id FROM sent_post_messages)
              AND processing_started_at < NOW() - INTERVAL '10 minutes';
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);")
        # Eng ko'p ishlatiladigan foydalanuvchi/post qidiruvlari uchun indekslar.
        # users.user_id PRIMARY KEY bo'lgani uchun u yerda indeks avtomatik mavjud.
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_user_id ON scheduled_posts (user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channels_user_id ON channels (user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_post_reactions_post_id ON post_reactions (post_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channel_posts_history_channel_date ON channel_posts_history (channel_id, post_date DESC);")

        # 2b) PostAssist V2 (6-bosqich): RBAC rollari va admin auditi.
        # schema.sql fayli topilmasa ham bu jadvallar albatta yaratiladi.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_roles (
                user_id BIGINT PRIMARY KEY,
                role VARCHAR(20) NOT NULL DEFAULT 'admin',
                granted_by BIGINT,
                granted_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_logs (
                id BIGSERIAL PRIMARY KEY,
                admin_id BIGINT NOT NULL,
                action VARCHAR(64) NOT NULL,
                target_type VARCHAR(64),
                target_id VARCHAR(64),
                old_value JSONB,
                new_value JSONB,
                ip_or_metadata JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_admin "
            "ON admin_audit_logs(admin_id, created_at);"
        )

        # 3) PostAssist V2 (5-bosqich): scheduler tezligi uchun kompozit indekslar
        # va jadvallararo FK/CHECK/UNIQUE constraintlar. Ikkalasi ham idempotent
        # va ma'lumotni o'zgartirmaydi (tafsilot: ``build_integrity_block``).
        _apply_integrity_indexes(cur)
        _apply_integrity_constraints(cur)

        # 4) Startup schema check: server versiyasi, jadvallar, indekslar va
        #    ma'lumotlar butunligi constraintlari.
        _verify_schema(cur)

# --- SETTINGS ---
# Reklama rotatsiya pullarini aniqlovchi doimiy qadriyatlar
AD_SCOPE_CHANNEL = "channel"
AD_SCOPE_REPLY = "reply"
AD_SCOPES = (AD_SCOPE_CHANNEL, AD_SCOPE_REPLY)

# Reklama matni/tugmasi uchun chegaralar (Telegram limitlariga mos).
AD_TEXT_MAX_LEN = 1024
AD_BUTTON_TEXT_MAX_LEN = 64
AD_BUTTON_URL_MAX_LEN = 2048


def _normalize_ad_button(button_text: str = "", button_url: str = "") -> tuple:
    """Tugma matni/havolasini normallashtiradi.

    Ikkalasi ham to'liq bo'lmasa tugma saqlanmaydi (``(None, None)``) —
    Telegram matnsiz yoki havolasiz inline tugmani qabul qilmaydi.
    """
    btn_text = (button_text or "").strip()[:AD_BUTTON_TEXT_MAX_LEN]
    btn_url = (button_url or "").strip()[:AD_BUTTON_URL_MAX_LEN]
    if not btn_text or not btn_url:
        return None, None
    return btn_text, btn_url


def _ad_row_to_dict(row) -> dict:
    """``ad_pool`` qatorini qulay dict ko'rinishiga o'giradi."""
    ad_id, scope, text, btn_text, btn_url, is_active = row[:6]
    return {
        "id": int(ad_id),
        "scope": scope,
        "text": text or "",
        "button_text": btn_text or "",
        "button_url": btn_url or "",
        "is_active": bool(is_active),
    }


def add_ad(scope: str, text: str, button_text: str = "", button_url: str = "") -> int:
    """Rotatsiya puliga yangi reklama qo'shadi. Id qaytaradi (xato: -1)."""
    if scope not in AD_SCOPES:
        return -1
    text = (text or "").strip()
    if not text:
        return -1
    btn_text, btn_url = _normalize_ad_button(button_text, button_url)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO ad_pool (scope, text, button_text, button_url) "
                "VALUES (%s, %s, %s, %s) RETURNING id",
                (scope, text, btn_text, btn_url),
            )
            row = cur.fetchone()
        _cache_clear("ad_pool:")
        return int(row[0]) if row else -1
    except Exception as e:
        logger.error(f"Reklama qo'shish xatosi: {e}")
        return -1


def get_ads(scope: str) -> list:
    """Faol reklamalar ro'yxati: [(id, text), ...]. Bo'sh bo'lsa [].

    Orqaga moslik uchun soddalashtirilgan ko'rinish saqlanadi; tugma bilan
    to'liq ma'lumot kerak bo'lsa ``get_ads_full`` ishlatiladi.
    """
    return [(ad["id"], ad["text"]) for ad in get_ads_full(scope)]


def get_ads_full(scope: str, include_inactive: bool = False) -> list:
    """Reklamalarning to'liq ro'yxati (matn + inline tugma + holat).

    Har bir element: ``{"id", "scope", "text", "button_text",
    "button_url", "is_active"}``.
    """
    if scope not in AD_SCOPES:
        return []
    cache_key = f"ad_pool:{scope}:{'all' if include_inactive else 'active'}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            query = (
                "SELECT id, scope, text, button_text, button_url, is_active "
                "FROM ad_pool WHERE scope = %s"
            )
            if not include_inactive:
                query += " AND is_active = TRUE"
            query += " ORDER BY id ASC"
            cur.execute(query, (scope,))
            rows = [_ad_row_to_dict(r) for r in cur.fetchall()]
            _cache_set(cache_key, rows, DB_SETTINGS_CACHE_TTL)
            return rows
    except Exception as e:
        logger.error(f"Reklamalar olish xatosi: {e}")
        return []


def get_ad(ad_id: int) -> dict | None:
    """Bitta reklamani id bo'yicha qaytaradi (topilmasa None)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, scope, text, button_text, button_url, is_active "
                "FROM ad_pool WHERE id = %s",
                (int(ad_id),),
            )
            row = cur.fetchone()
        return _ad_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"Reklama olish xatosi: {e}")
        return None


def count_ads(scope: str) -> int:
    """Berilgan scope uchun faol reklamalar soni."""
    return len(get_ads_full(scope) or [])


def update_ad(ad_id: int, text: str = None, button_text: str = None,
              button_url: str = None) -> bool:
    """Reklamani tahrirlaydi. Faqat berilgan (None bo'lmagan) maydonlar yangilanadi.

    ``button_text``/``button_url`` ga bo'sh satr berilsa tugma o'chiriladi.
    """
    fields = []
    params = []

    if text is not None:
        text = str(text).strip()
        if not text:
            return False
        fields.append("text = %s")
        params.append(text[:AD_TEXT_MAX_LEN])

    if button_text is not None or button_url is not None:
        # Tugma butunlay yangilanadi: ikkalasi ham berilishi kerak,
        # aks holda mavjud qiymat asos qilib olinadi.
        current = get_ad(ad_id) if (button_text is None or button_url is None) else None
        new_text = button_text if button_text is not None else (current or {}).get("button_text", "")
        new_url = button_url if button_url is not None else (current or {}).get("button_url", "")
        btn_text, btn_url = _normalize_ad_button(new_text, new_url)
        fields.append("button_text = %s")
        params.append(btn_text)
        fields.append("button_url = %s")
        params.append(btn_url)

    if not fields:
        return False

    fields.append("updated_at = CURRENT_TIMESTAMP")
    params.append(int(ad_id))
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                f"UPDATE ad_pool SET {', '.join(fields)} WHERE id = %s",
                tuple(params),
            )
            updated = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return updated
    except Exception as e:
        logger.error(f"Reklama tahrirlash xatosi: {e}")
        return False


def set_ad_active(ad_id: int, is_active: bool) -> bool:
    """Reklamani faollashtiradi yoki o'chiradi (Toggle Active/Inactive)."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE ad_pool SET is_active = %s, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s",
                (bool(is_active), int(ad_id)),
            )
            updated = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return updated
    except Exception as e:
        logger.error(f"Reklama holatini o'zgartirish xatosi: {e}")
        return False


def toggle_ad_active(ad_id: int):
    """Reklama holatini teskarisiga o'giradi. Yangi holat (bool) yoki None."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE ad_pool SET is_active = NOT COALESCE(is_active, FALSE), "
                "updated_at = CURRENT_TIMESTAMP WHERE id = %s RETURNING is_active",
                (int(ad_id),),
            )
            row = cur.fetchone()
        _cache_clear("ad_pool:")
        return bool(row[0]) if row else None
    except Exception as e:
        logger.error(f"Reklama toggle xatosi: {e}")
        return None


def delete_ad(ad_id: int) -> bool:
    """Reklamani puldan butunlay o'chiradi.

    Vaqtincha o'chirish uchun ``set_ad_active(ad_id, False)`` ishlatiladi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM ad_pool WHERE id = %s", (int(ad_id),))
            removed = cur.rowcount > 0
        _cache_clear("ad_pool:")
        return removed
    except Exception as e:
        logger.error(f"Reklama o'chirish xatosi: {e}")
        return False


def clear_ads(scope: str) -> int:
    """Scope bo'yicha barcha reklamalarni o'chiradi. O'chirilgan soni."""
    if scope not in AD_SCOPES:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM ad_pool WHERE scope = %s", (scope,))
            removed = cur.rowcount
        _cache_clear("ad_pool:")
        return int(removed or 0)
    except Exception as e:
        logger.error(f"Reklamalarni tozalash xatosi: {e}")
        return 0


# --- KANAL POST SANAGICHLARI (reklama oralig'i uchun) ---
# Reklama har nechanchi postda chiqishi admin panelda sozlanadi (3-5 ta post).
CHANNEL_AD_INTERVAL_KEY = "channel_ad_interval"
CHANNEL_AD_INTERVAL_DEFAULT = 3
AD_INTERVAL_MIN = 1
AD_INTERVAL_MAX = 100


def clamp_ad_interval(value, default: int = CHANNEL_AD_INTERVAL_DEFAULT) -> int:
    """Interval qiymatini xavfsiz butun songa keltiradi (1..100)."""
    try:
        interval = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return max(AD_INTERVAL_MIN, min(AD_INTERVAL_MAX, interval))


def bump_channel_post_count(channel_id) -> int:
    """Kanal post sanagichini 1 ga oshiradi va YANGI qiymatni qaytaradi.

    Sanagich har bir kanal uchun ALOHIDA yuritiladi. Atomik UPSERT bo'lgani
    uchun bir nechta scheduler tick'i parallel ishlasa ham qiymat buzilmaydi.
    Xatoda 0 qaytadi (0 hech qachon reklama chiqarmaydi).
    """
    ch = str(channel_id or "").strip()
    if not ch:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_post_counters (channel_id, post_count, updated_at)
                VALUES (%s, 1, CURRENT_TIMESTAMP)
                ON CONFLICT (channel_id) DO UPDATE
                SET post_count = channel_post_counters.post_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING post_count
                """,
                (ch,),
            )
            row = cur.fetchone()
        _cache_clear("channel_counter:")
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Kanal post sanagichi xatosi: {e}")
        return 0


def mark_channel_ad_shown(channel_id, post_number: int) -> bool:
    """Kanalga reklama chiqarilganini belgilaydi (statistika/audit uchun)."""
    ch = str(channel_id or "").strip()
    if not ch:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO channel_post_counters
                    (channel_id, post_count, ad_count, last_ad_post_number, updated_at)
                VALUES (%s, %s, 1, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (channel_id) DO UPDATE
                SET ad_count = channel_post_counters.ad_count + 1,
                    last_ad_post_number = EXCLUDED.last_ad_post_number,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (ch, int(post_number or 0), int(post_number or 0)),
            )
        _cache_clear("channel_counter:")
        return True
    except Exception as e:
        logger.error(f"Kanal reklama belgisi xatosi: {e}")
        return False


def get_channel_post_count(channel_id) -> int:
    """Kanalning joriy post sanagichi (yo'q bo'lsa 0)."""
    ch = str(channel_id or "").strip()
    if not ch:
        return 0
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT post_count FROM channel_post_counters WHERE channel_id = %s",
                (ch,),
            )
            row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"Kanal sanagichini olish xatosi: {e}")
        return 0


def reset_channel_post_count(channel_id=None) -> bool:
    """Bitta kanal (yoki hammasi) uchun post sanagichini nolga qaytaradi."""
    try:
        with db_cursor(commit=True) as cur:
            if channel_id is None:
                cur.execute(
                    "UPDATE channel_post_counters SET post_count = 0, "
                    "last_ad_post_number = 0, updated_at = CURRENT_TIMESTAMP"
                )
            else:
                cur.execute(
                    "UPDATE channel_post_counters SET post_count = 0, "
                    "last_ad_post_number = 0, updated_at = CURRENT_TIMESTAMP "
                    "WHERE channel_id = %s",
                    (str(channel_id),),
                )
        _cache_clear("channel_counter:")
        return True
    except Exception as e:
        logger.error(f"Kanal sanagichini tozalash xatosi: {e}")
        return False


def get_channel_post_counters(limit: int = 10) -> list:
    """Eng faol kanallar sanagichi: [(channel_id, title, post_count, ad_count), ...]."""
    try:
        limit = max(1, int(limit))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT cpc.channel_id,
                       COALESCE(c.channel_title, '') AS title,
                       cpc.post_count, cpc.ad_count
                FROM channel_post_counters cpc
                LEFT JOIN channels c ON c.channel_id = cpc.channel_id
                ORDER BY cpc.updated_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanal sanagichlari ro'yxati xatosi: {e}")
        return []


def get_channel_ad_interval() -> int:
    """Kanal postlarida reklama har nechanchi postda chiqishi (standart 3)."""
    cached = _cache_get("channel_ad_interval")
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT value FROM bot_settings WHERE key = %s",
                (CHANNEL_AD_INTERVAL_KEY,),
            )
            row = cur.fetchone()
        interval = clamp_ad_interval(row[0] if row else None)
        _cache_set("channel_ad_interval", interval, DB_SETTINGS_CACHE_TTL)
        return interval
    except Exception as e:
        logger.error(f"Kanal reklama oralig'ini olish xatosi: {e}")
        return CHANNEL_AD_INTERVAL_DEFAULT


def set_channel_ad_interval(interval) -> bool:
    """Kanal postlari reklama oralig'ini saqlaydi (masalan 3, 4 yoki 5)."""
    value = clamp_ad_interval(interval)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO bot_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (CHANNEL_AD_INTERVAL_KEY, str(value)),
            )
        _cache_clear("channel_ad_interval")
        _cache_clear("ad_settings")
        return True
    except Exception as e:
        logger.error(f"Kanal reklama oralig'ini saqlash xatosi: {e}")
        return False


def set_setting(key: str, value: str) -> bool:
    """``system_settings`` jadvaliga sozlamani yozadi (upsert).

    Muvaffaqiyatda True qaytadi — chaqiruvchi saqlanganini tekshira oladi.
    """
    key = str(key or "").strip()
    if not key:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, "" if value is None else str(value)))
        _cache_clear("setting:")
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Sozlama xatosi: {e}")
        return False


def get_setting(key: str, default: str = "") -> str:
    """``system_settings`` dan qiymat o'qiydi.

    Kesh faqat BAZADAGI qiymatni saqlaydi — ``default`` keshlanmaydi, shuning
    uchun turli default bilan chaqirilganda ham to'g'ri natija qaytadi.
    """
    key = str(key or "").strip()
    if not key:
        return default
    cache_key = f"setting:{key}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return default if cached is None else cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            value = row[0] if row else None
            _cache_set(cache_key, value, DB_SETTINGS_CACHE_TTL)
            return default if value is None else value
    except Exception as e:
        logger.error(f"Sozlama olish xatosi: {e}")
        return default


def get_settings_map(keys=None) -> dict:
    """Bir nechta sozlamani bitta so'rovda o'qiydi: ``{key: value}``.

    ``keys`` berilmasa — barcha sozlamalar qaytadi. Admin paneldagi
    "tizim sozlamalari" ekrani shu funksiyadan foydalanadi.
    """
    try:
        with db_cursor() as cur:
            if keys is not None:
                keys = [str(k) for k in keys if str(k).strip()]
                if not keys:
                    return {}
                cur.execute(
                    "SELECT key, value FROM system_settings WHERE key = ANY(%s) ORDER BY key",
                    (keys,),
                )
            else:
                cur.execute("SELECT key, value FROM system_settings ORDER BY key")
            return {k: (v or "") for k, v in cur.fetchall()}
    except Exception as e:
        logger.error(f"Sozlamalarni olish xatosi: {e}")
        return {}


def delete_setting(key: str) -> bool:
    """Sozlamani o'chiradi (default qiymatga qaytarish uchun)."""
    key = str(key or "").strip()
    if not key:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (key,))
            removed = cur.rowcount > 0
        _cache_clear("setting:")
        return removed
    except Exception as e:
        logger.error(f"Sozlamani o'chirish xatosi: {e}")
        return False

# --- SPONSORS ---
def add_sponsor_channel(
    channel_id: int | str,
    title: str = "",
    username: str = "",
    invite_link: str = "",
    **kwargs
) -> bool:
    """Yangi sponsor kanal qo'shadi yoki mavjudini yangilaydi.

    Qo'llab-quvvatlaydi:
      - add_sponsor_channel(channel_id, title, username, invite_link)
      - add_sponsor_channel(channel_id, channel_title, channel_url)
    """
    # Orqaga moslik: agar 3 ta argument berilgan bo'lsa (channel_id, title, url)
    if not invite_link and username and (username.startswith("http://") or username.startswith("https://") or username.startswith("t.me")):
        invite_link = username
        username = ""

    title = (title or kwargs.get("channel_title") or "").strip()
    invite_link = (invite_link or kwargs.get("channel_url") or "").strip()
    username = (username or "").strip()
    if username.startswith("@"):
        username = username[1:]
    if not invite_link and username:
        invite_link = f"https://t.me/{username}"

    ch_id_str = str(channel_id).strip()
    try:
        ch_id_bigint = int(ch_id_str)
    except ValueError:
        ch_id_bigint = None

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sponsor_channels (channel_id, title, username, invite_link, channel_title, channel_url, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET title = COALESCE(NULLIF(EXCLUDED.title, ''), sponsor_channels.title, EXCLUDED.channel_title),
                    username = COALESCE(NULLIF(EXCLUDED.username, ''), sponsor_channels.username),
                    invite_link = COALESCE(NULLIF(EXCLUDED.invite_link, ''), sponsor_channels.invite_link, EXCLUDED.channel_url),
                    channel_title = COALESCE(NULLIF(EXCLUDED.channel_title, ''), sponsor_channels.channel_title, EXCLUDED.title),
                    channel_url = COALESCE(NULLIF(EXCLUDED.channel_url, ''), sponsor_channels.channel_url, EXCLUDED.invite_link),
                    is_active = TRUE
            """, (
                ch_id_bigint if ch_id_bigint is not None else ch_id_str,
                title,
                username,
                invite_link,
                title,
                invite_link
            ))
        _cache_clear("sponsors")
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Sponsor xatosi: {e}")
        return False


def get_sponsor_channels() -> list:
    """Faol sponsor kanallar ro'yxatini qaytaradi (fail-closed: xatoda None).

    Har bir qator: (id, channel_id, title, username, invite_link)
    """
    cached = _cache_get("sponsors")
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, channel_id,
                       COALESCE(title, channel_title, '') AS title,
                       COALESCE(username, '') AS username,
                       COALESCE(invite_link, channel_url, '') AS invite_link
                FROM sponsor_channels
                WHERE is_active = TRUE
                ORDER BY id ASC
            """)
            rows = cur.fetchall()
            _cache_set("sponsors", rows, DB_SPONSORS_CACHE_TTL)
            return rows
    except Exception as e:
        logger.error(f"Sponsorlar olish xatosi: {e}")
        return None


def get_active_sponsors():
    """Faol homiy kanallar (get_sponsor_channels aliasi)."""
    return get_sponsor_channels()


def remove_sponsor_channel(sponsor_id: int | str) -> bool:
    """Sponsor kanalni o'chiradi (id yoki channel_id bo'yicha)."""
    try:
        s_id_str = str(sponsor_id).strip()
        try:
            s_id_int = int(s_id_str)
        except ValueError:
            s_id_int = -999999999
        with db_cursor(commit=True) as cur:
            cur.execute(
                "DELETE FROM sponsor_channels WHERE id = %s OR channel_id = %s OR CAST(channel_id AS TEXT) = %s",
                (s_id_int, s_id_int, s_id_str),
            )
            removed = cur.rowcount > 0
        _cache_clear("sponsors")
        _cache_clear("system_stats")
        return removed
    except Exception as e:
        logger.error(f"Sponsor o'chirish xatosi: {e}")
        return False


# --- AUTO-AD INJECTOR SETTINGS ---
def get_ad_settings() -> dict:
    """Reklama sozlamalari.

    Qaytadi: ``auto_ad_text``, ``auto_ad_interval`` (bot javoblari uchun),
    ``auto_ad_status``, ``channel_ad_interval`` (kanal postlari uchun —
    reklama har nechanchi postda chiqishi) va ``channel_ad_status``
    (kanal postlari reklamasi yoqilgan/o'chirilgan).
    """
    cached = _cache_get("ad_settings")
    if cached is not _MISS:
        return cached
    settings = {
        "auto_ad_text": "",
        "auto_ad_interval": 4,
        "auto_ad_status": False,
        "channel_ad_interval": CHANNEL_AD_INTERVAL_DEFAULT,
        # Kanal postlari reklamasi standart HOLATDA YOQILGAN — mavjud bot
        # xatti-harakati o'zgarmasligi uchun (orqaga moslik).
        "channel_ad_status": True,
    }
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT key, value FROM bot_settings
                WHERE key IN ('auto_ad_text', 'auto_ad_interval', 'auto_ad_status',
                              'channel_ad_interval', 'channel_ad_status')
            """)
            rows = cur.fetchall()
            for k, v in rows:
                if k == "auto_ad_text":
                    settings["auto_ad_text"] = v or ""
                elif k == "auto_ad_interval":
                    settings["auto_ad_interval"] = clamp_ad_interval(v, 4)
                elif k == "channel_ad_interval":
                    settings["channel_ad_interval"] = clamp_ad_interval(
                        v, CHANNEL_AD_INTERVAL_DEFAULT)
                elif k == "auto_ad_status":
                    settings["auto_ad_status"] = str(v).lower() in ("true", "1", "yes", "on")
                elif k == "channel_ad_status":
                    settings["channel_ad_status"] = str(v).lower() in ("true", "1", "yes", "on")
        _cache_set("ad_settings", settings, DB_SETTINGS_CACHE_TTL)
        return settings
    except Exception as e:
        logger.error(f"get_ad_settings xatosi: {e}")
        return settings


def update_ad_text(text: str) -> bool:
    """Auto-ad matnini yangilaydi."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_text', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (str(text or ""),))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"update_ad_text xatosi: {e}")
        return False


def set_ad_status(status: bool) -> bool:
    """Auto-ad faollik holatini o'zgartiradi (True/False)."""
    val = "true" if status else "false"
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_status', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"set_ad_status xatosi: {e}")
        return False


def set_channel_ad_status(status: bool) -> bool:
    """Kanal postlari reklamasini yoqish/o'chirish (True/False)."""
    val = "true" if status else "false"
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('channel_ad_status', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("channel_ad_interval")
        return True
    except Exception as e:
        logger.error(f"set_channel_ad_status xatosi: {e}")
        return False


def set_ad_interval(interval: int) -> bool:
    """Bot javoblari reklama intervalini o'zgartiradi (standart: 4)."""
    try:
        val = str(clamp_ad_interval(interval, 4))
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO bot_settings (key, value)
                VALUES ('auto_ad_interval', %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (val,))
        _cache_clear("ad_settings")
        _cache_clear("setting:")
        return True
    except Exception as e:
        logger.error(f"set_ad_interval xatosi: {e}")
        return False

# --- REACTIONS ---
def toggle_reaction(post_id: int, user_id: int, reaction: str) -> dict:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT reaction_type FROM post_reactions WHERE post_id = %s AND user_id = %s", (post_id, user_id))
            row = cur.fetchone()
            if row:
                if row[0] == reaction:
                    cur.execute("DELETE FROM post_reactions WHERE post_id = %s AND user_id = %s", (post_id, user_id))
                else:
                    cur.execute("UPDATE post_reactions SET reaction_type = %s WHERE post_id = %s AND user_id = %s", (reaction, post_id, user_id))
            else:
                cur.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, %s)", (post_id, user_id, reaction))

            cur.execute("SELECT reaction_type, COUNT(*) FROM post_reactions WHERE post_id = %s GROUP BY reaction_type", (post_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Reaksiya xatosi: {e}")
        return {}

# --- USERS & CREDITS ---
def _normalize_language_code(language_code) -> str:
    """Telegram language_code → 'ru', 'en' yoki 'uz'."""
    raw = str(language_code or "").strip().lower()
    if raw.startswith("ru"):
        return "ru"
    if raw.startswith("en"):
        return "en"
    return "uz"


def _generate_user_code(cur) -> str:
    letters = string.ascii_lowercase
    for _ in range(50):
        code = "".join(random.choice(letters) for _ in range(2)) + random.choice(string.digits)
        cur.execute("SELECT 1 FROM users WHERE user_code = %s", (code,))
        if not cur.fetchone():
            return code
    return "".join(random.choice(letters) for _ in range(3)) + "".join(random.choice(string.digits) for _ in range(2))

# ============================================================
# REFERAL MUKOFOTI — FAQAT AI BALL (PRO berilmaydi)
# ============================================================
REFERRAL_TOP_TIER_FRIENDS = 3   # dastlabki nechta do'st "katta" mukofot oladi
REFERRAL_TOP_TIER_REWARD = 3    # 1-, 2-, 3-do'st uchun har biriga
REFERRAL_BASE_REWARD = 1        # 4-do'st va undan keyingilar uchun har biriga


def referral_reward_for(friend_number: int) -> int:
    """N-chi taklif qilingan do'st uchun beriladigan AI ball miqdori.

    ``friend_number`` — bu do'st referrer uchun nechanchi ekani (1 dan boshlab).
    1, 2, 3 → +3; 4 va undan keyingi barchasi → +1. Noto'g'ri (0 yoki manfiy)
    qiymat 1-do'st sifatida qaraladi.
    """
    try:
        n = int(friend_number)
    except (TypeError, ValueError):
        n = 1
    if n < 1:
        n = 1
    return REFERRAL_TOP_TIER_REWARD if n <= REFERRAL_TOP_TIER_FRIENDS else REFERRAL_BASE_REWARD


def total_referral_reward(friends_count: int) -> int:
    """``friends_count`` ta do'st uchun jami beriladigan AI ball (yig'indi)."""
    try:
        n = max(0, int(friends_count))
    except (TypeError, ValueError):
        n = 0
    return sum(referral_reward_for(i) for i in range(1, n + 1))


def save_user(user_id: int, username: str, full_name: str = "", referrer_id: int = None,
              language_code: str = None) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE users SET username = %s, full_name = %s WHERE user_id = %s", (username, full_name, user_id))
                _invalidate_user(user_id)
                return False
            else:
                code = _generate_user_code(cur)
                valid_ref = referrer_id if referrer_id and referrer_id != user_id else None
                lang = _normalize_language_code(language_code)
                cur.execute("""
                    INSERT INTO users (user_id, username, full_name, user_code, referrer_id, ai_credits, streak_days, created_at, language_code)
                    VALUES (%s, %s, %s, %s, %s, 5, 0, NOW(), %s)
                """, (user_id, username, full_name, code, valid_ref, lang))

                if valid_ref:
                    # Referal mukofoti FAQAT AI ball: 1-, 2-, 3-do'st uchun +3 tadan,
                    # 4-do'stdan boshlab har biri uchun +1. PRO berilmaydi.
                    # Hisoblash va yozish bitta tranzaksiyada — parallel /start
                    # chaqiruvlari poyga (race) hosil qilmaydi.
                    cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (valid_ref,))
                    referral_count = int((cur.fetchone() or (0,))[0] or 0)
                    reward = referral_reward_for(referral_count)
                    cur.execute("UPDATE users SET ai_credits = ai_credits + %s WHERE user_id = %s", (reward, valid_ref))
                    _invalidate_user(valid_ref)
                _invalidate_user(user_id)
                _cache_clear("system_stats")
                return True
    except Exception as e:
        logger.error(f"User saqlash xatosi: {e}")
        return False

def _today_tashkent():
    """Toshkent vaqtidagi bugungi sana (Render serveri UTC da bo'lgani uchun
    `date.today()` noto'g'ri kun ko'rsatishi mumkin edi)."""
    return datetime.now(tashkent_tz).date()


def claim_daily_streak_bonus(user_id: int) -> dict:
    today = _today_tashkent()
    reward_map = {1: 1, 2: 1, 3: 2, 4: 1, 5: 2, 6: 2, 7: 4}

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT last_bonus_date, streak_days, ai_credits FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "msg": "Foydalanuvchi topilmadi."}

            last_date, streak, credits = row
            streak = streak or 0

            if last_date == today:
                return {
                    "success": False,
                    "msg": "Siz bugungi bonusingizni olgansiz! Ertaga yana kiring.",
                    "streak": streak,
                    "credits": credits
                }

            if last_date == today - timedelta(days=1):
                streak = streak + 1 if streak < 7 else 1
            else:
                streak = 1

            bonus_amount = reward_map.get(streak, 1)
            new_credits = credits + bonus_amount

            cur.execute("""
                UPDATE users 
                SET ai_credits = %s, streak_days = %s, last_bonus_date = %s 
                WHERE user_id = %s
            """, (new_credits, streak, today, user_id))
            _invalidate_user(user_id)
            _cache_clear("system_stats")

            return {
                "success": True,
                "streak": streak,
                "bonus_amount": bonus_amount,
                "credits": new_credits,
                "is_reset": (streak == 1 and last_date is not None and last_date != today - timedelta(days=1))
            }
    except Exception as e:
        logger.error(f"Streak bonus xatosi: {e}")
        return {"success": False, "msg": "Tizim xatoligi yuz berdi."}

# Eslatma: avvalgi "reklamasiz postlar litsenziyasi" (buy/refund/toggle/
# consume/peek_ad_free_*) funksiyalari OLIB TASHLANDI. Reklamasiz rejim endi
# to'liq avtomatik: PRO (is_premium) yoki admin → reklama umuman qo'shilmaydi,
# oddiy foydalanuvchi → admin belgilagan reklama oralig'i (ad_pool) qo'llanadi.
# ``users.ad_free_posts`` / ``users.ad_free_active`` ustunlari mavjud bazani
# buzmaslik uchun saqlanadi, lekin endi o'qilmaydi/yozilmaydi.


def add_user_credit(user_id: int, amount: int = 1) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE users SET ai_credits = ai_credits + %s WHERE user_id = %s", (amount, user_id))
            changed = cur.rowcount > 0
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return changed
    except Exception as e:
        logger.error(f"Ball qaytarish xatosi: {e}")
        return False

def get_user_credits(user_id: int) -> int:
    cache_key = f"user_credits:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            credits = row[0] if row and row[0] is not None else 0
            _cache_set(cache_key, credits, DB_USER_CACHE_TTL)
            return credits
    except Exception as e:
        logger.error(f"Ball olish xatosi: {e}")
        return 0

def use_user_credit(user_id: int) -> bool:
    """Atomically spend one credit; prevents double-spending on concurrent updates."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET ai_credits = ai_credits - 1 "
                "WHERE user_id = %s AND ai_credits > 0 RETURNING user_id",
                (user_id,),
            )
            spent = cur.fetchone() is not None
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return spent
    except Exception as e:
        logger.error(f"Ball ayirish xatosi: {e}")
        return False

def find_user_by_target(target: str):
    target_clean = target.strip().lstrip("@").lower()
    try:
        with db_cursor() as cur:
            if target_clean.isdigit():
                cur.execute("SELECT user_id, full_name, username, user_code, ai_credits FROM users WHERE user_id = %s", (int(target_clean),))
            else:
                cur.execute("SELECT user_id, full_name, username, user_code, ai_credits FROM users WHERE LOWER(user_code) = %s OR LOWER(username) = %s", (target_clean, target_clean))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Foydalanuvchi qidirish xatosi: {e}")
        return None

def transfer_user_credits(from_user_id: int, to_user_id: int, amount: int) -> tuple[bool, str]:
    if from_user_id == to_user_id:
        return False, "O'zingizga ball o'tkaza olmaysiz."
    if amount < 3 or amount > 20:
        return False, "O'tkazish miqdori kamida 3 ta, ko'pi bilan 20 ta bo'lishi kerak."

    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT ai_credits, created_at FROM users WHERE user_id = %s FOR UPDATE", (from_user_id,))
            row_from = cur.fetchone()
            if not row_from:
                return False, "Foydalanuvchi topilmadi."
            
            credits, created_at = row_from
            if created_at:
                now_tz = datetime.now(tashkent_tz)
                created_tz = tashkent_tz.localize(created_at) if created_at.tzinfo is None else created_at.astimezone(tashkent_tz)
                if (now_tz - created_tz).days < 3:
                    return False, "⚠️ <b>Xavfsizlik qoidasi:</b> Yangi ro'yxatdan o'tgan foydalanuvchilar ballarni <b>3 kun o'tgach</b> boshqalarga ulasha oladi."
                
            if credits < amount:
                return False, "Hisobingizda yetarli ball mavjud emas."

            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (to_user_id,))
            if not cur.fetchone():
                return False, "Qabul qiluvchi foydalanuvchi topilmadi."

            cur.execute("UPDATE users SET ai_credits = ai_credits - %s WHERE user_id = %s", (amount, from_user_id))
            cur.execute("UPDATE users SET ai_credits = ai_credits + %s WHERE user_id = %s", (amount, to_user_id))
            _invalidate_user(from_user_id)
            _invalidate_user(to_user_id)
            _cache_clear("system_stats")
            return True, "Ballar muvaffaqiyatli o'tkazildi!"
    except Exception as e:
        logger.error(f"Ball o'tkazish xatosi: {e}")
        return False, f"Tizim xatoligi: {e}"

def get_referral_stats(user_id: int) -> dict:
    cache_key = f"user_stats:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (user_id,))
            ref_count = cur.fetchone()[0]
            cur.execute("SELECT ai_credits, streak_days FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            credits = row[0] if row and row[0] is not None else 0
            streak = row[1] if row and len(row) > 1 and row[1] is not None else 0
            data = {"referrals_count": ref_count, "ai_credits": credits, "streak": streak}
            _cache_set(cache_key, data, DB_USER_CACHE_TTL)
            return data
    except Exception as e:
        logger.error(f"Referral xatosi: {e}")
        return {"referrals_count": 0, "ai_credits": 0, "streak": 0}

def get_all_user_ids() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Foydalanuvchilar xatosi: {e}")
        return []

def get_user_language(user_id: int) -> str:
    """Foydalanuvchi tilini qaytaradi ('uz' yoki 'ru'). Topilmasa 'uz'."""
    cache_key = f"user_lang:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT language_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            lang = _normalize_language_code(row[0] if row else None)
            _cache_set(cache_key, lang, DB_USER_CACHE_TTL)
            return lang
    except Exception as e:
        logger.error(f"User tilini olish xatosi: {e}")
        return "uz"


def set_user_language(user_id: int, language_code: str) -> bool:
    """Foydalanuvchi tilini yangilaydi ('uz' | 'ru')."""
    lang = _normalize_language_code(language_code)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET language_code = %s WHERE user_id = %s",
                (lang, user_id),
            )
            updated = cur.rowcount > 0
        _cache_clear(f"user_lang:{user_id}")
        return updated
    except Exception as e:
        logger.error(f"User tilini saqlash xatosi: {e}")
        return False


# ============================================================
# 🆕 ONBOARDING — yangi foydalanuvchilar uchun sodda klaviatura
# ============================================================
# Qaror mantiqi (3 kun / 3 post) ``onboarding.py`` da — bu funksiya faqat
# xom faktlarni qaytaradi: created_at, chiqarilgan postlar soni va
# foydalanuvchi to'liq menyuni o'zi ochganmi.

def get_user_onboarding(user_id: int) -> dict:
    """Onboarding uchun xom ma'lumotlarni qaytaradi.

    Qaytadi::

        {"created_at": datetime | None,
         "posts_published": int,          # status = 'posted' postlar soni
         "full_menu_unlocked": bool}      # "⚙️ To'liq menyuni ochish" bosilganmi

    Foydalanuvchi topilmasa yoki DB xatosi bo'lsa **bo'sh dict** qaytadi —
    chaqiruvchi (``onboarding.decide_menu_mode``) bo'sh ma'lumotni "to'liq
    menyu" deb hisoblaydi, ya'ni xatolik hech qachon foydalanuvchini
    cheklamaydi (fail-open).
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT created_at, COALESCE(full_menu_unlocked, FALSE) "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return {}
            created_at, unlocked = row
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts "
                "WHERE user_id = %s AND status = 'posted'",
                (user_id,),
            )
            posts_published = int((cur.fetchone() or (0,))[0] or 0)
            return {
                "created_at": created_at,
                "posts_published": posts_published,
                "full_menu_unlocked": bool(unlocked),
            }
    except Exception as e:
        logger.error(f"get_user_onboarding xatosi: {e}")
        return {}


def set_user_full_menu_unlocked(user_id: int, unlocked: bool = True) -> bool:
    """"⚙️ To'liq menyuni ochish" belgisini yozadi.

    ``True`` qaytsa — yozuv yangilandi. Onboarding keshi ham tozalanadi,
    shunda keyingi menyu darhol to'liq ko'rinishda chiqadi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE users SET full_menu_unlocked = %s WHERE user_id = %s",
                (bool(unlocked), int(user_id)),
            )
            updated = cur.rowcount > 0
        if updated:
            _invalidate_user(user_id)
            try:
                import onboarding
                onboarding.invalidate_simple_menu(user_id)
            except Exception:
                pass
        return updated
    except Exception as e:
        logger.error(f"To'liq menyu belgisini saqlash xatosi: {e}")
        return False


def get_user_code(user_id: int) -> str:
    cache_key = f"user_code:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            code = row[0] if row and row[0] else str(user_id)
            _cache_set(cache_key, code, DB_USER_CACHE_TTL)
            return code
    except Exception as e:
        logger.error(f"User kod xatosi: {e}")
        return str(user_id)

# --- CHANNELS ---
def get_user_channels(user_id: int) -> list:
    cache_key = f"user_channels:{user_id}"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    try:
        with db_cursor() as cur:
            cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC", (user_id,))
            channels = cur.fetchall()
            _cache_set(cache_key, channels, DB_USER_CACHE_TTL)
            return channels
    except Exception as e:
        logger.error(f"Kanallar olish xatosi: {e}")
        return []

def get_all_channels(limit: int = None) -> list:
    """Faol kanallarni qaytaradi.

    ``limit`` berilsa, eng so'nggi qo'shilgan kanallar birinchi qaytadi.
    Admin ro'yxati shu yo'l bilan katta bazada ham bitta Telegram xabari
    chegarasidan oshib ketmaydi.
    """
    try:
        with db_cursor() as cur:
            query = """
                SELECT c.channel_id, c.channel_title, c.user_id, u.username
                FROM channels c
                LEFT JOIN users u ON u.user_id = c.user_id
                WHERE c.is_active = TRUE
                ORDER BY c.id DESC
            """
            params = ()
            if limit is not None:
                # LIMIT parametr sifatida beriladi; manfiy yoki nol qiymat
                # kutilmagan katta ro'yxat qaytarmasligi uchun 1 ga tenglanadi.
                limit = max(1, int(limit))
                query += " LIMIT %s"
                params = (limit,)
            cur.execute(query, params)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Barcha kanallar xatosi: {e}")
        return []

def save_channel(user_id: int, channel_id: str, channel_title: str, is_admin: bool = False) -> tuple[bool, str]:
    """Kanalni foydalanuvchiga ulash.

    Qaytadi: (True, 'ok') yoki (False, 'taken'|'error').
    Faol kanalni boshqa foydalanuvchi o'g'irlay olmaydi — faqat o'chirilgan
    (nofaol) kanalni qayta ulash yoki admin qayta biriktirishi mumkin.
    """
    try:
        with db_cursor(commit=True) as cur:
            # Kanal avval kimga tegishli bo'lganini bilib olamiz — admin uni
            # boshqa foydalanuvchiga biriktirsa, ESKI EGASINING keshi ham
            # bekor qilinishi kerak (aks holda unda kanal ko'rinib turadi).
            cur.execute(
                "SELECT user_id FROM channels WHERE channel_id = %s",
                (str(channel_id),),
            )
            prev_row = cur.fetchone()
            prev_owner = prev_row[0] if prev_row else None
            cur.execute(
                """
                INSERT INTO channels (user_id, channel_id, channel_title, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET is_active = TRUE,
                    channel_title = EXCLUDED.channel_title,
                    user_id = CASE
                        WHEN channels.is_active = FALSE THEN EXCLUDED.user_id
                        WHEN channels.user_id = EXCLUDED.user_id THEN EXCLUDED.user_id
                        WHEN EXCLUDED.user_id = %s THEN EXCLUDED.user_id
                        ELSE channels.user_id
                    END
                RETURNING user_id
                """,
                (user_id, str(channel_id), channel_title, user_id if is_admin else -1),
            )
            row = cur.fetchone()
            if not row:
                return False, "error"
            if row[0] != user_id:
                return False, "taken"
        _invalidate_user(user_id)
        if prev_owner is not None and prev_owner != user_id:
            _invalidate_user(prev_owner)
        _cache_clear("system_stats")
        return True, "ok"
    except Exception as e:
        logger.error(f"Kanal saqlash xatosi: {e}")
        return False, "error"


def deactivate_channel_by_id(channel_id: str) -> bool:
    """Bot kanal/guruhdan chiqarilganda yozuvni nofaol qilish."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND is_active = TRUE",
                (str(channel_id),),
            )
            changed = cur.rowcount > 0
        _cache_clear("user_channels:")
        _cache_clear("system_stats")
        return changed
    except Exception as e:
        logger.error(f"Kanalni nofaol qilish xatosi: {e}")
        return False

def remove_channel(user_id: int, channel_id: str, is_admin: bool = False) -> bool:
    try:
        owner_id = None
        with db_cursor(commit=True) as cur:
            if is_admin:
                # Admin boshqa foydalanuvchining kanalini olib tashlashi mumkin —
                # o'sha egasining keshi ham bekor qilinishi shart.
                cur.execute(
                    "SELECT user_id FROM channels WHERE channel_id = %s",
                    (str(channel_id),),
                )
                row = cur.fetchone()
                owner_id = row[0] if row else None
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s", (str(channel_id),))
            else:
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND user_id = %s", (str(channel_id), user_id))
            changed = cur.rowcount > 0
        _invalidate_user(user_id)
        if owner_id is not None and owner_id != user_id:
            _invalidate_user(owner_id)
        _cache_clear("system_stats")
        return changed
    except Exception as e:
        logger.error(f"Kanal o'chirish xatosi: {e}")
        return False

# --- CHANNEL TONE OF VOICE ---
VALID_TONES = ("formal", "friendly", "concise", "engaging")


def get_channel_tone(channel_id: str) -> str:
    """Kanalning tone_of_voice qiymatini qaytaradi (default: 'friendly')."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT tone_of_voice FROM channels WHERE channel_id = %s AND is_active = TRUE",
                (str(channel_id),),
            )
            row = cur.fetchone()
            if row and row[0]:
                return row[0]
    except Exception as e:
        logger.error(f"Kanal tone olish xatosi: {e}")
    return "friendly"


def set_channel_tone(channel_id: str, tone: str) -> bool:
    """Kanalning tone_of_voice qiymatini yangilaydi."""
    if tone not in VALID_TONES:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE channels SET tone_of_voice = %s WHERE channel_id = %s AND is_active = TRUE",
                (tone, str(channel_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Kanal tone yangilash xatosi: {e}")
        return False


def get_user_channels_with_tone(user_id: int) -> list:
    """Foydalanuvchi kanallarini tone_of_voice bilan qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT channel_id, channel_title, tone_of_voice FROM channels "
                "WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC",
                (user_id,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanallar (tone) olish xatosi: {e}")
        return []


# --- POSTS ---
def add_post(
    user_id: int,
    channel_id: str,
    post_type: str,
    content: str,
    file_id: str,
    scheduled_time,
    recurrence_type: str = 'none',
    recurrence_day=None,
    recurrence_time=None,
    end_date=None,
    btn_text: str = None,
    btn_url: str = None,
    enable_reactions: bool = False,
    delete_after_hours: int = 0,
    reaction_emojis=None
) -> int:
    # reaction_emojis: ro'yxat yoki bo'sh joy bilan ajratilgan satr — DB'da
    # bo'sh joy bilan ajratilgan satr ko'rinishida saqlanadi ("👍 ❤️ 🔥").
    if reaction_emojis:
        if isinstance(reaction_emojis, (list, tuple, set)):
            reaction_emojis = " ".join(str(e) for e in reaction_emojis if e)
        else:
            reaction_emojis = " ".join(str(reaction_emojis).split())
        if not reaction_emojis:
            reaction_emojis = None
    else:
        reaction_emojis = None
    try:
        with db_cursor(commit=True) as cur:
            # Bir foydalanuvchining post raqami MAX(...)+1 bilan tuziladi.
            # Parallel kelgan ikkita saqlash so'rovi bir xil raqam olmasligi
            # uchun transaction darajasidagi advisory qulf ishlatiladi.
            # Qulf commit/rollback bilan avtomatik bo'shaydi.
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(user_id),))
            cur.execute("SELECT COALESCE(MAX(user_post_number), 0) + 1 FROM scheduled_posts WHERE user_id = %s", (user_id,))
            next_num = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO scheduled_posts
                    (user_id, channel_id, post_type, content, file_id, inline_button_text, inline_button_url,
                     enable_reactions, reaction_emojis, delete_after_hours, scheduled_time, status, user_post_number,
                     recurrence_type, recurrence_day, recurrence_time, end_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id, str(channel_id), post_type, content, file_id, btn_text, btn_url,
                enable_reactions, reaction_emojis, delete_after_hours, scheduled_time, next_num,
                recurrence_type, recurrence_day, recurrence_time, end_date
            ))
            post_id = cur.fetchone()[0]
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return post_id
    except Exception as e:
        logger.error(f"Post saqlash xatosi: {e}")
        return 0


def schedule_week_posts(user_id: int, channel_id: str, posts: list,
                        post_type: str = "text") -> dict:
    """🚀 Bir necha postni (odatda 7 kunlik kontent-reja) BITTA tranzaksiyada navbatga qo'yadi.

    ``posts`` — ``(scheduled_time, content)`` juftliklari ro'yxati (tartib
    dushanba → yakshanba). Barcha INSERT'lar bitta ``db_cursor(commit=True)``
    blokida bajariladi: psycopg2 birinchi so'rovda tranzaksiyani boshlaydi va
    ``commit`` faqat blok muvaffaqiyatli tugaganda chaqiriladi. Biror INSERT
    yiqilsa — ``db_cursor`` ``ROLLBACK`` qiladi, ya'ni **yarim-yorti navbat
    hech qachon qolmaydi** (hammasi yoki hech narsa).

    ``add_post`` bilan bir xil himoya: ``pg_advisory_xact_lock(user_id)`` va
    ``MAX(user_post_number) + 1`` — parallel chaqiruvlar bir xil post raqamini
    olmaydi. Qulf commit/rollback bilan avtomatik bo'shaydi.

    Qaytadi::

        {"success": bool, "count": int, "ids": [int], "times": [datetime],
         "error": str}
    """
    result = {"success": False, "count": 0, "ids": [], "times": [], "error": ""}
    rows = [p for p in (posts or []) if p]
    if not rows:
        result["error"] = "empty"
        return result
    if not channel_id:
        result["error"] = "no_channel"
        return result
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        result["error"] = "bad_user"
        return result

    try:
        ids = []
        times = []
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (user_id,))
            cur.execute(
                "SELECT COALESCE(MAX(user_post_number), 0) FROM scheduled_posts WHERE user_id = %s",
                (user_id,),
            )
            next_num = int((cur.fetchone() or (0,))[0] or 0)
            for scheduled_time, content in rows:
                next_num += 1
                cur.execute("""
                    INSERT INTO scheduled_posts
                        (user_id, channel_id, post_type, content, file_id,
                         scheduled_time, status, user_post_number, recurrence_type)
                    VALUES (%s, %s, %s, %s, NULL, %s, 'pending', %s, 'none')
                    RETURNING id
                """, (
                    user_id, str(channel_id), post_type, content,
                    scheduled_time, next_num,
                ))
                ids.append(cur.fetchone()[0])
                times.append(scheduled_time)
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        result.update({"success": True, "count": len(ids), "ids": ids, "times": times})
        return result
    except Exception as e:
        logger.error(f"Haftalik postlarni navbatga qo'yish xatosi: {e}")
        result["error"] = str(e)
        return result


def get_recent_posts(limit: int = 15) -> list:
    """Admin panel uchun eng so'nggi postlarni qaytaradi."""
    try:
        with db_cursor() as cur:
            limit = max(1, int(limit))
            cur.execute("""
                SELECT sp.id, sp.user_id, c.channel_title, sp.post_type, sp.scheduled_time, sp.status
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                ORDER BY sp.id DESC
                LIMIT %s
            """, (limit,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Oxirgi postlarni olish xatosi: {e}")
        return []


def get_pending_posts(user_id: int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time,
                       sp.user_post_number, sp.recurrence_type, sp.recurrence_day, sp.recurrence_time
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.user_id = %s AND sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
            """, (user_id,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Pending posts xatosi: {e}")
        return []

def get_post_by_id(post_id: int):
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, channel_id, post_type, scheduled_time, recurrence_type, recurrence_time, user_post_number
                FROM scheduled_posts WHERE id = %s
            """, (post_id,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Post olish xatosi: {e}")
        return None

def update_post_time(post_id: int, new_time, recurrence_time=None, user_id: int = None, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            owner_clause = "" if is_admin else " AND user_id = %s"
            params = [new_time]
            if recurrence_time:
                query = "UPDATE scheduled_posts SET scheduled_time = %s, recurrence_time = %s WHERE id = %s"; params = [new_time, recurrence_time, post_id]
            else:
                query = "UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s"; params = [new_time, post_id]
            query += owner_clause
            if not is_admin: params.append(user_id)
            cur.execute(query, tuple(params))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Post vaqtini yangilash xatosi: {e}")
        return False


def update_post_content(post_id: int, user_id: int,
                        content: str = None,
                        btn_text: str = None, btn_url: str = None,
                        enable_reactions: bool = None,
                        reaction_emojis=None,
                        is_admin: bool = False) -> bool:
    """Kutilayotgan postning matn, tugma va reaksiyalarini yangilash.

    Faqat o'zgartirish kerak bo'lgan maydonlar uzatiladi (None bo'lsa o'zgartirilmaydi).
    is_admin=True bo'lsa foydalanuvchi tekshiruvi (user_id) o'tkazib yuboriladi.
    """
    try:
        sets = []
        params = []
        if content is not None:
            sets.append("content = %s")
            params.append(content)
        if btn_text is not None:
            # Jadvaldagi ustun nomlari: inline_button_text / inline_button_url.
            sets.append("inline_button_text = %s")
            params.append(btn_text if btn_text else None)
        if btn_url is not None:
            sets.append("inline_button_url = %s")
            params.append(btn_url if btn_url else None)
        if enable_reactions is not None:
            sets.append("enable_reactions = %s")
            params.append(enable_reactions)
        if reaction_emojis is not None:
            if isinstance(reaction_emojis, (list, tuple, set)):
                reaction_emojis = " ".join(str(e) for e in reaction_emojis if e)
            else:
                reaction_emojis = " ".join(str(reaction_emojis).split())
            sets.append("reaction_emojis = %s")
            params.append(reaction_emojis or None)
        if not sets:
            return False

        query = f"UPDATE scheduled_posts SET {', '.join(sets)} WHERE id = %s AND status = 'pending'"
        params.append(post_id)
        if not is_admin:
            query += " AND user_id = %s"
            params.append(user_id)

        with db_cursor(commit=True) as cur:
            cur.execute(query, tuple(params))
            updated = cur.rowcount > 0
        if updated:
            _cache_clear(f"pending_posts:{user_id}")
        return updated
    except Exception as e:
        logger.error(f"Post kontentini yangilash xatosi: {e}")
        return False


def cancel_post(post_id: int, user_id: int, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND status = 'pending'", (post_id,))
            else:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND user_id = %s AND status = 'pending'", (post_id, user_id))
            cancelled = cur.rowcount > 0
        _invalidate_user(user_id)
        _cache_clear("system_stats")
        return cancelled
    except Exception as e:
        logger.error(f"Post bekor qilish xatosi: {e}")
        return False

def _delivery_channel_number(channel_id) -> int:
    """post_deliveries.channel_id BIGINT uchun kanalni deterministik kodlaydi.

    Telegram kanal ID'lari odatda BIGINT. Legacy konfiguratsiyada ``@username``
    ham uchrashi mumkin; bunday qiymat uchun stable signed 63-bit surrogate
    ishlatiladi. Haqiqiy idempotency_key esa original qiymatni saqlaydi.
    """
    try:
        return int(channel_id)
    except (TypeError, ValueError):
        digest = hashlib.sha256(str(channel_id).encode("utf-8")).digest()[:8]
        value = int.from_bytes(digest, "big") & ((1 << 63) - 1)
        return value or 1


def build_delivery_idempotency_key(post_id: int, channel_id, scheduled_timestamp) -> str:
    """Bir scheduled post/channel/vaqt uchun o'zgarmas delivery key."""
    if hasattr(scheduled_timestamp, "isoformat"):
        timestamp = scheduled_timestamp.isoformat()
    else:
        timestamp = str(scheduled_timestamp)
    return f"post_{int(post_id)}_{channel_id}_{timestamp}"


# PostAssist V2 (3-bosqich): delivery backoff jadvali (urinish → kutish, soniya).
# 1-urinishdagi transient xato → 30s, 2- → 2 daqiqa, 3- → 5 daqiqa,
# 4- → 15 daqiqa; 5-urinishda ham xato bo'lsa → 'dead_letter' (qayta urinilmaydi).
DELIVERY_BACKOFF_SECONDS = (30, 120, 300, 900)
DELIVERY_MAX_ATTEMPTS = 5
# 'processing' da qolib ketgan delivery crash deb hisoblanadigan muddat.
# scheduled_posts dagi 10 daqiqalik stale-recovery bilan bir xil.
DELIVERY_STALE_PROCESSING_SECONDS = 600


def claim_post_delivery(post_id: int, channel_id, scheduled_timestamp) -> dict:
    """Telegramga yuborish huquqini atomik claim qiladi.

    ``sent`` bo'lsa caller darhol skip qiladi (0 duplikat); ``processing``
    bo'lsa boshqa scheduler instance ishlayotgan bo'ladi; ``dead_letter``
    bo'lsa HECH QACHON qayta urinilmaydi. ``failed`` yozuv faqat backoff
    muddati (``next_retry_at``) o'tgan bo'lsa claim qilinadi.

    Urinish sanagichi (``attempt_count``) claim'da oshirilmaydi — u faqat
    ``SchedulerService.mark_as_failed`` da (real xatoda) yoki stale
    'processing' qayta olinganda (crash hisobi) oshadi.
    """
    key = build_delivery_idempotency_key(post_id, channel_id, scheduled_timestamp)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO post_deliveries "
                "(post_id, channel_id, status, idempotency_key, scheduled_time) "
                "VALUES (%s, %s, 'pending', %s, %s) ON CONFLICT DO NOTHING",
                (int(post_id), _delivery_channel_number(channel_id), key,
                 scheduled_timestamp),
            )
            cur.execute(
                "SELECT status, attempt_count, telegram_message_id, next_retry_at, updated_at "
                "FROM post_deliveries WHERE idempotency_key = %s FOR UPDATE",
                (key,),
            )
            row = cur.fetchone()
            if not row:
                return {"claimed": False, "status": "missing", "idempotency_key": key}
            status, attempt_count, message_id, next_retry_at, updated_at = row
            if status == "sent":
                return {"claimed": False, "sent": True, "status": status,
                        "message_id": message_id, "idempotency_key": key}
            if status == "dead_letter":
                # Doimiy xato yoki urinishlar tugagan — qayta yuborilmaydi.
                return {"claimed": False, "sent": False, "dead": True,
                        "status": status, "idempotency_key": key}
            if status == "processing":
                if not _delivery_processing_is_stale(updated_at):
                    return {"claimed": False, "sent": False, "status": status,
                            "idempotency_key": key}
                # Crash: avvalgi worker 'processing' da qolib ketgan. Urinishni
                # hisobga olamiz — cheksiz crash-loop bo'lmasligi uchun limit
                # oshsa to'g'ridan-to'g'ri 'dead_letter' qilinadi.
                new_attempt = (attempt_count or 0) + 1
                if new_attempt >= DELIVERY_MAX_ATTEMPTS:
                    cur.execute(
                        "UPDATE post_deliveries SET status = 'dead_letter', "
                        "attempt_count = %s, "
                        "last_error = 'stale processing: attempts exhausted', "
                        "next_retry_at = NULL, updated_at = NOW() "
                        "WHERE idempotency_key = %s",
                        (new_attempt, key),
                    )
                    return {"claimed": False, "sent": False, "dead": True,
                            "status": "dead_letter", "attempt_count": new_attempt,
                            "idempotency_key": key}
                cur.execute(
                    "UPDATE post_deliveries SET status = 'processing', "
                    "attempt_count = %s, updated_at = NOW() "
                    "WHERE idempotency_key = %s",
                    (new_attempt, key),
                )
                return {"claimed": True, "sent": False, "status": "processing",
                        "attempt_count": new_attempt, "stale_reclaim": True,
                        "idempotency_key": key}
            if status == "failed" and next_retry_at is not None:
                from datetime import timezone as _tz
                now_utc = datetime.now(_tz.utc)
                retry_at = next_retry_at
                if getattr(retry_at, "tzinfo", None) is None:
                    retry_at = retry_at.replace(tzinfo=_tz.utc)
                if retry_at > now_utc:
                    # Backoff hali o'tmagan — hozir claim qilib bo'lmaydi.
                    return {"claimed": False, "sent": False, "status": status,
                            "retry_pending": True, "next_retry_at": next_retry_at,
                            "attempt_count": attempt_count or 0,
                            "idempotency_key": key}
            cur.execute(
                "UPDATE post_deliveries SET status = 'processing', "
                "last_error = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s",
                (key,),
            )
            return {"claimed": True, "sent": False, "status": "processing",
                    "attempt_count": attempt_count or 0,
                    "idempotency_key": key}
    except Exception as e:
        logger.error("Delivery claim xatosi (post=%s, channel=%s): %s", post_id, channel_id, e)
        return {"claimed": False, "error": str(e), "idempotency_key": key}


def _delivery_processing_is_stale(updated_at) -> bool:
    """'processing' yozuv crash deb hisoblanadimi (10 daqiqadan eski)?"""
    if updated_at is None:
        return False
    try:
        from datetime import timezone as _tz
        now_utc = datetime.now(_tz.utc)
        stamp = updated_at
        if getattr(stamp, "tzinfo", None) is None:
            stamp = stamp.replace(tzinfo=_tz.utc)
        return (now_utc - stamp).total_seconds() > DELIVERY_STALE_PROCESSING_SECONDS
    except Exception:
        return False


def mark_post_delivery_sent(idempotency_key: str, telegram_message_id: int) -> bool:
    """Yuborilgan delivery'ni sent/message_id bilan idempotent belgilaydi.

    ``next_retry_at`` tozalanadi — 'sent' yozuv hech qachon retry navbatiga
    qaytmaydi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'sent', telegram_message_id = %s, "
                "last_error = NULL, next_retry_at = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s AND status <> 'sent'",
                (telegram_message_id, idempotency_key),
            )
            if cur.rowcount == 0:
                cur.execute(
                    "SELECT 1 FROM post_deliveries WHERE idempotency_key = %s AND status = 'sent'",
                    (idempotency_key,),
                )
                return cur.fetchone() is not None
        return True
    except Exception as e:
        logger.error("Delivery sent marker xatosi (%s): %s", idempotency_key, e)
        return False


def mark_post_delivery_failed(idempotency_key: str, error: str) -> bool:
    """Telegram yuborish xatosini qayd qiladi; keyingi retry claim qila oladi.

    Legacy imzo (PostAssist V2'gacha): backoff qo'ymaydi — keyingi urinish
    vaqti ``scheduled_posts.scheduled_time`` (``retry_post``) orqali boshqariladi.
    Backoff'li yangi oqim ``SchedulerService.mark_as_failed`` da.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET status = 'failed', last_error = %s, "
                "next_retry_at = NULL, updated_at = NOW() "
                "WHERE idempotency_key = %s AND status NOT IN ('sent', 'dead_letter')",
                (str(error)[:4000], idempotency_key),
            )
        return True
    except Exception as e:
        logger.error("Delivery failed marker xatosi (%s): %s", idempotency_key, e)
        return False


def get_due_posts(now) -> list:
    """Atomically claim due posts so concurrent scheduler runs cannot duplicate them.

    Bir tick'da ko'pi bilan POST_BATCH_SIZE ta post olinadi — qolganlari
    keyingi tick'da yuboriladi (ulkan navbat bitta ishlashni to'sib qo'ymaydi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                WITH due AS (
                    SELECT id FROM scheduled_posts
                    WHERE status = 'pending' AND scheduled_time <= %s
                    ORDER BY scheduled_time
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE scheduled_posts sp
                SET status = 'processing', processing_started_at = NOW()
                FROM due
                WHERE sp.id = due.id
                RETURNING sp.id, sp.user_id, sp.channel_id, sp.post_type, sp.content, sp.file_id,
                          sp.inline_button_text, sp.inline_button_url, sp.enable_reactions,
                          sp.scheduled_time, sp.recurrence_type, sp.recurrence_day,
                          sp.recurrence_time, sp.end_date, sp.delete_after_hours, sp.reaction_emojis
            """, (now, POST_BATCH_SIZE))
            rows = cur.fetchall()
        _cache_clear("system_stats")
        return rows
    except Exception as e:
        logger.error(f"Due posts xatosi: {e}")
        return []

def mark_post_processing(post_id: int) -> bool:
    """Postni Telegramga yuborishdan oldin statusini qat'iy 'processing' va processing_started_at ni NOW() deb belgilash.

    Qaytaradi: ``True`` — yozildi, ``False`` — DB xatosi (istisno tashlanmaydi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_posts SET status = 'processing', processing_started_at = NOW() WHERE id = %s",
                (post_id,)
            )
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post processing status xatosi (Post ID {post_id}): {e}")
        return False

def mark_post_status(post_id: int, status: str) -> bool:
    """Post statusini yangilaydi. ``True`` — yozildi, ``False`` — DB xatosi (istisno yo'q).

    Scheduler qaytgan qiymatga qarab transient DB xatosida qayta urinadi —
    aks holda 'yuborildi' fakti yo'qolib, restartdan keyin post ikki marta chiqishi mumkin.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s", (status, post_id))
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post status xatosi: {e}")
        return False

def mark_post_as_sent(post_id: int, sent_message_id: int, channel_id: str = None, delete_after_hours: int = 0, extra_message_ids: list = None) -> bool:
    """Telegramga yuborilgan postni 'posted' deb belgilaydi va xabar ID'larini saqlaydi.

    Bitta tranzaksiyada bajariladi (yarim yozilgan holat bo'lmaydi). Qaytaradi:
    ``True`` — commit bo'ldi; ``False`` — DB xatosi (istisno tashlanmaydi, chaqiruvchi
    qayta urinishi kerak: 'yuborildi' markeri idempotentlik kafolatining asosi).
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = 'posted', sent_message_id = %s WHERE id = %s", (sent_message_id, post_id))
            if channel_id is not None:
                ids = [sent_message_id]
                if extra_message_ids:
                    for mid in extra_message_ids:
                        if mid and mid not in ids:
                            ids.append(mid)
                for mid in ids:
                    cur.execute("""
                        INSERT INTO sent_post_messages (post_id, channel_id, message_id, delete_at)
                        VALUES (%s, %s, %s, CASE WHEN %s > 0 THEN NOW() + (%s || ' hours')::INTERVAL ELSE NULL END)
                    """, (post_id, str(channel_id), mid, delete_after_hours, delete_after_hours))
        _cache_clear("system_stats")
        return True
    except Exception as e:
        logger.error(f"Post yuborilganini belgilash xatosi: {e}")
        return False

def get_posts_to_delete(now) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, channel_id, message_id
                FROM sent_post_messages
                WHERE deleted_at IS NULL AND delete_at IS NOT NULL AND delete_at <= %s
            """, (now,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"O'chiriladigan postlar xatosi: {e}")
        return []

def mark_post_as_deleted(message_row_id: int):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE sent_post_messages SET deleted_at = NOW() WHERE id = %s", (message_row_id,))
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Post o'chirish xatosi: {e}")

def reschedule_recurring_post(post_id: int, next_time):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s", (next_time, post_id))
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Qayta rejalashtirish xatosi: {e}")


def retry_post(post_id: int, retry_at):
    """Telegram vaqtinchalik xatosi (rate-limit/tarmoq) tufayli postni qayta navbatga qo'yish."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE scheduled_posts SET scheduled_time = %s, status = 'pending', processing_started_at = NULL WHERE id = %s",
                (retry_at, post_id),
            )
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Post qayta navbatlash xatosi: {e}")


def recover_stale_processing_posts():
    """Server crash/restart paytida 'processing' holatida qolib ketgan postlarni tiklash (idempotent).

    1. Agar post allaqachon Telegramga yuborilgan bo'lsa (sent_message_id to'ldirilgan yoki
       sent_post_messages jadvalida qayd etilgan bo'lsa), statusi 'posted' deb belgilanadi —
       bunday postlar hech qachon qayta yuborilmaydi (idempotentlik kafolati).
    2. Yuborilmagan va 10 daqiqadan ko'p vaqt 'processing' holatida qolgan postlar
       qayta navbatga ('pending') qaytariladi.
    """
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'posted'
                WHERE status = 'processing'
                  AND (sent_message_id IS NOT NULL 
                       OR id IN (SELECT post_id FROM sent_post_messages));
            """)
            cur.execute("""
                UPDATE scheduled_posts
                SET status = 'pending', processing_started_at = NULL
                WHERE status = 'processing'
                  AND sent_message_id IS NULL
                  AND id NOT IN (SELECT post_id FROM sent_post_messages)
                  AND processing_started_at < NOW() - INTERVAL '10 minutes';
            """)
        _cache_clear("system_stats")
    except Exception as e:
        logger.error(f"Stale processing postlarni tiklashda xato: {e}")


def cleanup_old_data() -> dict:
    """Eski, keraksiz ma'lumotlarni o'chirish (scheduler har 6 soatda chaqiradi).

    Baza o'sib ketmasligi uchun: yuborilgan/ochilgan xabarlar, 30 kundan eski
    yakunlangan postlar va boshqa qoldiqlar tozalanadi.

    ⚠️ 5-bosqich: ``scheduled_posts.channel_id → channels(channel_id)`` FK'i
    ``ON DELETE CASCADE`` bilan, ya'ni kanal qatori o'chirilsa, uning BARCHA
    post tarixi (analitika shu ustunda qurilgan) ham ketadi. Shuning uchun bu
    tozalash endi kanal qatorini faqat unga bog'liq BIRORTA post qolmaganida
    o'chiradi — tarix hech qachon "reklama sanagichi tozalash" oqibatida
    yo'qolmaydi.
    """
    recover_stale_processing_posts()
    deleted = {"sent_post_messages": 0, "scheduled_posts": 0, "post_reactions": 0, "channels": 0}
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                DELETE FROM sent_post_messages
                WHERE (deleted_at IS NOT NULL AND deleted_at < NOW() - INTERVAL '30 days')
                   OR (delete_at IS NOT NULL AND delete_at < NOW() - INTERVAL '90 days')
            """)
            deleted["sent_post_messages"] = cur.rowcount

            cur.execute("""
                DELETE FROM scheduled_posts
                WHERE status IN ('posted', 'cancelled', 'failed', 'completed')
                  AND created_at < NOW() - INTERVAL '30 days'
            """)
            deleted["scheduled_posts"] = cur.rowcount

            # FK (fk_post_reactions_post) ishlaganda bunday yetim qatorlar
            # umudan paydo bo'lmaydi — bu sorov eski/nofaol (NOT VALID)
            # bazalarda himoya to'r sifatida qoladi.
            cur.execute("DELETE FROM post_reactions WHERE post_id NOT IN (SELECT id FROM scheduled_posts)")
            deleted["post_reactions"] = cur.rowcount

            cur.execute("""
                DELETE FROM channels c
                 WHERE c.is_active = FALSE
                   AND c.created_at < NOW() - INTERVAL '90 days'
                   AND NOT EXISTS (
                       SELECT 1 FROM scheduled_posts sp WHERE sp.channel_id = c.channel_id
                   )
            """)
            deleted["channels"] = cur.rowcount

            cur.execute("DELETE FROM channel_posts_history WHERE created_at < NOW() - INTERVAL '90 days'")
            deleted["channel_posts_history"] = cur.rowcount
        _cache_clear()
        return deleted
    except Exception as e:
        logger.error(f"DB tozalash xatosi: {e}")
        return deleted

# --- QUEUE SYSTEM ---
DEFAULT_QUEUE_SLOTS = ["09:00", "14:00", "19:00"]


def get_queue_slots(user_id: int) -> list:
    """Foydalanuvchining queue slotlarini qaytaradi."""
    import json as _json
    raw = get_setting(f"queue_slots:{user_id}", "")
    if not raw:
        return list(DEFAULT_QUEUE_SLOTS)
    try:
        slots = _json.loads(raw)
        if isinstance(slots, list) and all(isinstance(s, str) for s in slots):
            return slots
    except Exception:
        pass
    return list(DEFAULT_QUEUE_SLOTS)


def set_queue_slots(user_id: int, slots: list) -> bool:
    """Foydalanuvchining queue slotlarini saqlaydi."""
    import json as _json
    try:
        set_setting(f"queue_slots:{user_id}", _json.dumps(slots))
        return True
    except Exception:
        return False


def get_queue_occupied_times(user_id: int, channel_id: str, target_date) -> list:
    """Berilgan sana uchun band qilingan vaqtlarni qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT EXTRACT(HOUR FROM scheduled_time AT TIME ZONE 'Asia/Tashkent')::int,
                       EXTRACT(MINUTE FROM scheduled_time AT TIME ZONE 'Asia/Tashkent')::int
                FROM scheduled_posts
                WHERE user_id = %s
                  AND status = 'pending'
                  AND (channel_id = %s OR channel_id = 'ALL')
                  AND (scheduled_time AT TIME ZONE 'Asia/Tashkent')::date = %s
            """, (user_id, str(channel_id), target_date))
            return [(row[0], row[1]) for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Queue occupied times xatosi: {e}")
        return []


def find_next_queue_slot(slots: list, occupied: list, now, max_days: int = 7) -> tuple:
    """Eng yaqin bo'sh slotni topadi.

    Returns: (datetime, date_label) yoki (None, None).
    """
    from datetime import time as dtime

    parsed_slots = []
    for s in slots:
        try:
            hh, mm = s.split(":")
            parsed_slots.append((int(hh), int(mm)))
        except Exception:
            continue
    if not parsed_slots:
        return None, None

    parsed_slots.sort()
    occupied_set = set(occupied)
    today = now.date()

    for day_offset in range(max_days):
        target_date = today + timedelta(days=day_offset)
        is_today = (day_offset == 0)

        for hh, mm in parsed_slots:
            if is_today:
                slot_dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if slot_dt <= now:
                    continue
            else:
                slot_dt = tashkent_tz.localize(
                    datetime(target_date.year, target_date.month, target_date.day, hh, mm)
                )

            if (hh, mm) not in occupied_set:
                if day_offset == 0:
                    label = "Bugun"
                elif day_offset == 1:
                    label = "Ertaga"
                else:
                    label = target_date.strftime("%d.%m.%Y")
                return slot_dt, label

        occupied_set = set()

    return None, None


def get_queue_posts(user_id: int, offset: int = 0, limit: int = 5) -> list:
    """Foydalanuvchining navbatdagi postlarini sahifalab qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.content,
                       sp.scheduled_time, sp.user_post_number, sp.channel_id
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.user_id = %s AND sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
                OFFSET %s LIMIT %s
            """, (user_id, offset, limit))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Queue posts xatosi: {e}")
        return []


def get_queue_post_count(user_id: int) -> int:
    """Foydalanuvchining navbatdagi postlar soni."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) FROM scheduled_posts
                WHERE user_id = %s AND status = 'pending'
            """, (user_id,))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Queue count xatosi: {e}")
        return 0


def get_queue_post_detail(post_id: int, user_id: int):
    """Bitta queue postni to'liq ma'lumotlari bilan qaytaradi."""
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, sp.user_id, sp.channel_id, c.channel_title,
                       sp.post_type, sp.content, sp.file_id,
                       sp.inline_button_text, sp.inline_button_url,
                       sp.enable_reactions, sp.delete_after_hours,
                       sp.scheduled_time, sp.user_post_number
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.id = %s AND sp.user_id = %s AND sp.status = 'pending'
            """, (post_id, user_id))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Queue post detail xatosi: {e}")
        return None


# --- STATS ---
def get_system_stats() -> dict:
    cache_key = "system_stats"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    stats = {"users": 0, "channels": 0, "pending": 0, "sent": 0, "cancelled": 0, "failed": 0, "sponsors": 0}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            stats["users"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
            stats["channels"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM sponsor_channels WHERE is_active = TRUE")
            stats["sponsors"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
            stats["pending"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'posted'")
            stats["sent"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'cancelled'")
            stats["cancelled"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed'")
            stats["failed"] = cur.fetchone()[0]
        _cache_set(cache_key, stats, DB_STATS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Statistika xatosi: {e}")
    return stats


def get_admin_dashboard_stats() -> dict:
    """Admin panel dashboard uchun kengaytirilgan statistika."""
    cache_key = "admin_dashboard_stats"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    stats = {
        "users": 0, "pro_subscribers": 0, "channels": 0,
        "posts_today": 0, "pending_posts": 0, "stars_revenue": 0,
    }
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            stats["users"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE plan_type IN ('pro', 'enterprise') "
                "AND (subscription_expires_at IS NULL OR subscription_expires_at > NOW())"
            )
            stats["pro_subscribers"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
            stats["channels"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts "
                "WHERE status = 'posted' AND scheduled_time >= CURRENT_DATE"
            )
            stats["posts_today"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
            stats["pending_posts"] = cur.fetchone()[0]
            # Stars revenue: endi alohida payments jadvalidan yig'iladi
            # (promo_codes jadvalidagi STARS_ yozuvlari bilan emas).
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE currency = 'XTR'"
            )
            stats["stars_revenue"] = cur.fetchone()[0]
        _cache_set(cache_key, stats, DB_STATS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Admin dashboard stats xatosi: {e}")
    return stats


# ============================================================
# ANALYTICS & POST PERFORMANCE
# ============================================================

def get_channel_post_stats(user_id: int, channel_id: str = None) -> dict:
    """Kanal post statistikasini qaytaradi.

    Args:
        user_id: foydalanuvchi ID
        channel_id: kanal ID (None bo'lsa — barcha kanallar)

    Returns:
        {
            "sent_7d": int, "sent_30d": int, "sent_all": int,
            "pending": int,
            "peak_hours": [(hour, count), ...],
            "type_distribution": {"text": N, "photo": N, ...},
        }
    """
    result = {
        "sent_7d": 0, "sent_30d": 0, "sent_all": 0,
        "pending": 0,
        "peak_hours": [],
        "type_distribution": {},
    }
    try:
        with db_cursor() as cur:
            ch_filter = "AND sp.channel_id = %s" if channel_id else ""
            params_base = (user_id, str(channel_id)) if channel_id else (user_id,)

            # Sent counts by period
            for period, key in [("7", "sent_7d"), ("30", "sent_30d")]:
                q = (
                    f"SELECT COUNT(*) FROM scheduled_posts sp "
                    f"WHERE sp.user_id = %s AND sp.status = 'posted' "
                    f"AND sp.scheduled_time >= NOW() - INTERVAL '{period} days' "
                    f"{ch_filter}"
                )
                cur.execute(q, params_base)
                result[key] = cur.fetchone()[0]

            # All-time sent
            q = (
                f"SELECT COUNT(*) FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s AND sp.status = 'posted' {ch_filter}"
            )
            cur.execute(q, params_base)
            result["sent_all"] = cur.fetchone()[0]

            # Pending
            q = (
                f"SELECT COUNT(*) FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s AND sp.status = 'pending' {ch_filter}"
            )
            cur.execute(q, params_base)
            result["pending"] = cur.fetchone()[0]

            # Peak hours (top 3)
            q = (
                f"SELECT EXTRACT(HOUR FROM sp.scheduled_time)::int AS h, COUNT(*) AS cnt "
                f"FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s AND sp.status = 'posted' {ch_filter} "
                f"GROUP BY h ORDER BY cnt DESC LIMIT 3"
            )
            cur.execute(q, params_base)
            result["peak_hours"] = [(row[0], row[1]) for row in cur.fetchall()]

            # Post type distribution
            q = (
                f"SELECT sp.post_type, COUNT(*) AS cnt "
                f"FROM scheduled_posts sp "
                f"WHERE sp.user_id = %s AND sp.status = 'posted' {ch_filter} "
                f"GROUP BY sp.post_type ORDER BY cnt DESC"
            )
            cur.execute(q, params_base)
            result["type_distribution"] = {row[0]: row[1] for row in cur.fetchall()}

            # Real vaqtli kanal postlari tarixi statistikasi (views, count)
            try:
                if channel_id:
                    cur.execute(
                        "SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0) "
                        "FROM channel_posts_history WHERE channel_id = %s",
                        (str(channel_id),)
                    )
                else:
                    cur.execute(
                        "SELECT COUNT(*), COALESCE(SUM(cph.views), 0), COALESCE(AVG(cph.views), 0) "
                        "FROM channel_posts_history cph "
                        "INNER JOIN channels c ON c.channel_id = cph.channel_id "
                        "WHERE c.user_id = %s AND c.is_active = TRUE",
                        (user_id,)
                    )
                h_row = cur.fetchone()
                if h_row:
                    result["history_count"] = int(h_row[0] or 0)
                    result["total_views"] = int(h_row[1] or 0)
                    result["avg_views"] = round(float(h_row[2] or 0), 1)
            except Exception:
                pass

    except Exception as e:
        logger.error(f"Channel post stats xatosi: {e}")
    return result


def get_user_channel_list_for_analytics(user_id: int) -> list:
    """Foydalanuvchi kanallarini analitika uchun qaytaradi.

    Returns: [(channel_id, channel_title), ...]
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT channel_id, channel_title FROM channels "
                "WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC",
                (user_id,),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Analytics channel list xatosi: {e}")
        return []


# ============================================================
# SUBSCRIPTIONS, LIMITS & MONETIZATION
# ============================================================

# Tarif limitlari
PLAN_LIMITS = {
    "free": {"max_channels": 3, "daily_ai_requests": 5},
    "pro": {"max_channels": 999, "daily_ai_requests": 999},
    "enterprise": {"max_channels": 999, "daily_ai_requests": 999},
}

# Navbatda turishi mumkin bo'lgan postlar soni (free uchun).
# PRO/Enterprise — cheksiz (999).
FREE_QUEUE_MAX_POSTS = 5


def _ensure_limit_reset(cur, user_id: int):
    """Kunlik AI sanagichini yangilash (agar kun o'tgan bo'lsa)."""
    cur.execute(
        "UPDATE users SET ai_requests_today = 0, last_limit_reset = CURRENT_DATE "
        "WHERE user_id = %s AND last_limit_reset < CURRENT_DATE",
        (user_id,),
    )


def is_premium(user_id: int) -> bool:
    """Foydalanuvchi PRO yoki Enterprise ekanligini tekshiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``SubscriptionService.is_premium(user_id)``
    """
    from services.subscription_service import SubscriptionService
    return SubscriptionService.is_premium(user_id)


def get_user_plan(user_id: int) -> dict:
    """Foydalanuvchi obuna ma'lumotlarini qaytaradi."""
    try:
        with db_cursor() as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "SELECT plan_type, subscription_expires_at, ai_requests_today "
                "FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"plan_type": "free", "expires_at": None, "ai_used": 0}
            plan_type, expires_at, ai_used = row
            return {
                "plan_type": plan_type or "free",
                "expires_at": expires_at,
                "ai_used": ai_used or 0,
            }
    except Exception as e:
        logger.error(f"get_user_plan xatosi: {e}")
        return {"plan_type": "free", "expires_at": None, "ai_used": 0}


def check_channel_limit(user_id: int) -> tuple[bool, int, int]:
    """Kanal limitini tekshiradi. Returns: (can_add, current, max)."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            plan = (row[0] if row else "free") or "free"
            cur.execute(
                "SELECT COUNT(*) FROM channels WHERE user_id = %s AND is_active = TRUE",
                (user_id,),
            )
            count = cur.fetchone()[0]
            max_ch = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["max_channels"]
            return (count < max_ch, count, max_ch)
    except Exception as e:
        logger.error(f"check_channel_limit xatosi: {e}")
        return (True, 0, 2)


def check_ai_limit(user_id: int) -> tuple[bool, int, int]:
    """Kunlik AI so'rov limitini tekshiradi. Returns: (can_use, used, max)."""
    try:
        with db_cursor(commit=True) as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "SELECT plan_type, ai_requests_today FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return (True, 0, 5)
            plan, ai_used = row
            plan = plan or "free"
            ai_used = ai_used or 0
            max_ai = PLAN_LIMITS.get(plan, PLAN_LIMITS["free"])["daily_ai_requests"]
            return (ai_used < max_ai, ai_used, max_ai)
    except Exception as e:
        logger.error(f"check_ai_limit xatosi: {e}")
        return (True, 0, 5)


def increment_ai_usage(user_id: int):
    """AI so'rov sanagichini oshiradi."""
    try:
        with db_cursor(commit=True) as cur:
            _ensure_limit_reset(cur, user_id)
            cur.execute(
                "UPDATE users SET ai_requests_today = ai_requests_today + 1 WHERE user_id = %s",
                (user_id,),
            )
    except Exception as e:
        logger.error(f"increment_ai_usage xatosi: {e}")


def check_queue_limit(user_id: int) -> tuple[bool, int, int]:
    """Navbatdagi postlar soni limitini tekshiradi.

    Returns: (can_add, current, max).
    """
    try:
        with db_cursor() as cur:
            cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            plan = (row[0] if row else "free") or "free"
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = 'pending'",
                (user_id,),
            )
            count = cur.fetchone()[0]
            max_q = FREE_QUEUE_MAX_POSTS if plan == "free" else 999
            return (count < max_q, count, max_q)
    except Exception as e:
        logger.error(f"check_queue_limit xatosi: {e}")
        return (True, 0, FREE_QUEUE_MAX_POSTS)


def set_user_plan(user_id: int, plan: str, days: int = None,
                  admin_id: int = None) -> bool:
    """Foydalanuvchi tarifini o'zgartiradi.

    ``admin_id`` (6-bosqich) berilsa — PRO berish harakati
    ``admin_audit_logs`` jadvaliga yoziladi (atomik).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``SubscriptionService.activate(user_id, plan, days)``
    """
    from services.subscription_service import SubscriptionService
    if plan not in PLAN_LIMITS:
        return False
    if days and days > 0:
        return SubscriptionService.activate(user_id, plan, days, admin_id=admin_id)
    else:
        # Cheksiz (days=None yoki 0) — activate qiyin bo'lgani uchun
        # to'g'ridan-to'g'ri DB ga yozamiz
        try:
            with db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE users SET plan_type = %s, subscription_expires_at = NULL "
                    "WHERE user_id = %s",
                    (plan, user_id),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error(f"set_user_plan xatosi: {e}")
            return False


def create_promo_code(code: str, plan_type: str = "pro", duration_days: int = 30,
                      max_uses: int = None, admin_id: int = None) -> bool:
    """Promo-kod yaratadi (admin).

    ``admin_id`` (6-bosqich) berilsa — harakat ``admin_audit_logs``
    jadvaliga kod yaratilgan tranzaksiyada yoziladi (atomik).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PromoService.create_promo(code, duration_days, max_uses, expires_at, plan_type)``
    """
    from services.promo_service import PromoService
    return PromoService.create_promo(code, duration_days, max_uses, None,
                                     plan_type, admin_id=admin_id)


def redeem_promo_code(user_id: int, code: str) -> tuple[bool, str]:
    """Promo-kodni bir marta, race-free tarzda faollashtiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PromoService.redeem_promo(user_id, code)``
    """
    from services.promo_service import PromoService
    return PromoService.redeem_promo(user_id, code)


# ============================================================
# REFERAL — faqat ma'lumot funksiyalari (PRO mukofoti OLIB TASHLANGAN)
# ============================================================
# Avvalgi "3 ta faol do'st = 30 kun PRO" mantiqi (REFERRAL_PRO_THRESHOLD,
# get_active_referral_count, check_and_grant_referral_pro,
# get_referral_pro_progress) butunlay olib tashlandi. Do'st taklif qilish
# endi faqat AI ball beradi — qarang: ``referral_reward_for``.


def get_referrer_id(user_id: int) -> int | None:
    """Foydalanuvchini taklif qilgan (referrer) foydalanuvchi ID'si.

    Hech kim taklif qilmagan bo'lsa (ustun NULL) yoki baza xato bersa — None.

    Eslatma: ``run_db`` orqali chaqiriladi (``await db.run_db(db.get_referrer_id, user_id)``) —
    ichida kursor O'ZI ochiladi, tashqaridan kursor uzatilmaydi.
    """
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT referrer_id FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if row and row[0]:
                return int(row[0])
            return None
    except Exception as e:
        logger.error(f"get_referrer_id xatosi: {e}")
        return None


# ============================================================
# STARS PAYMENTS LOG
# ============================================================
# To'lov audit holatlari (5-bosqich). DB tomonida CHECK (chk_payments_status)
# bilan ham himolangan — Python to'plami bilan bir xil bo'lishi shart.
PAYMENT_STATUS_PENDING = "pending"
PAYMENT_STATUS_SUCCEEDED = "succeeded"
PAYMENT_STATUS_FAILED = "failed"
PAYMENT_STATUS_REFUNDED = "refunded"
PAYMENT_STATUSES = (
    PAYMENT_STATUS_PENDING,
    PAYMENT_STATUS_SUCCEEDED,
    PAYMENT_STATUS_FAILED,
    PAYMENT_STATUS_REFUNDED,
)


def log_stars_payment(user_id: int, amount: int, currency: str, payload: str, telegram_payment_id: str = "",
                      status: str = "succeeded") -> bool:
    """Stars to'lovini audit jadvaliga idempotent yozadi.

    ``telegram_payment_charge_id`` NULL bo'lishi mumkin (legacy/manual
    chaqiriqlar uchun), ammo haqiqiy Telegram charge ID doimo unique.

    ``status`` — 5-bosqich audit holati (``pending | succeeded | failed |
    refunded``); ``payments_status`` CHECK'i shu to'plamni DB darajasida
    qat'iy ushlab turadi va ``idx_payments_user (user_id, status)`` indeksini
    ishlatib to'lov tarixini holat bo'yicha chizadi.
    """
    if status not in PAYMENT_STATUSES:
        status = PAYMENT_STATUS_SUCCEEDED
    try:
        charge_id = (telegram_payment_id or "").strip() or None
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO payments (user_id, amount, currency, payload,
                                      telegram_payment_charge_id, status)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (user_id, amount, currency, payload, charge_id, status),
            )
            inserted = cur.rowcount > 0
        _cache_clear("system_stats")
        _cache_clear("admin_dashboard_stats")
        return inserted
    except Exception as e:
        logger.error(f"Stars payment log xatosi: {e}")
        return False


def process_stars_payment(
    user_id: int,
    amount: int,
    currency: str,
    payload: str,
    telegram_payment_id: str,
    plan: str = "pro",
    duration_days: int = 30,
) -> dict:
    """To'lovni audit qilish va obunani uzaytirishni bitta tranzaksiyada bajaradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_stars_payment(user_id, charge_id, amount, payload, plan, duration_days)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_stars_payment(
        user_id, telegram_payment_id, amount, payload, plan, duration_days
    )


# ============================================================
# CARD PAYMENT RECEIPTS — Admin Approval Flow
# ============================================================
# Foydalanuvchi karta orqali to'lagach chek (rasm/PDF) yuboradi. U
# ``payment_receipts`` jadvaliga ``pending`` holatida yoziladi va barcha
# adminlarga yuboriladi. Admin ✅ Tasdiqlash bosganda status ``approved``
# bo'lib, PRO muddati ATOMIK uzaytiriladi (bitta tranzaksiyada). ❌ Rad etishda
# ``rejected`` deb belgilanadi.

RECEIPT_STATUS_PENDING = "pending"
RECEIPT_STATUS_APPROVED = "approved"
RECEIPT_STATUS_REJECTED = "rejected"


def save_payment_receipt(
    user_id: int,
    media_type: str = "photo",
    file_id: str = "",
    caption: str = "",
    username: str = "",
    full_name: str = "",
    language_code: str = "uz",
    days_granted: int = 30,
) -> int:
    """Yangi karta chekini ``pending`` holatida saqlaydi.

    Returns: receipt id (xato: 0). ``media_type`` — 'photo' | 'document'.
    """
    if not file_id:
        return 0
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO payment_receipts
                    (user_id, username, full_name, language_code, media_type,
                     file_id, caption, status, days_granted)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s)
                RETURNING id
                """,
                (int(user_id), username or "", full_name or "",
                 _normalize_language_code(language_code) or "uz",
                 media_type if media_type in ("photo", "document") else "photo",
                 file_id, caption or "", int(days_granted) if days_granted else 30),
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    except Exception as e:
        logger.error(f"payment_receipt saqlash xatosi: {e}")
        return 0


def _payment_receipt_row_to_dict(row) -> dict:
    return {
        "id": int(row[0]),
        "user_id": int(row[1]),
        "username": row[2] or "",
        "full_name": row[3] or "",
        "language_code": row[4] or "uz",
        "media_type": row[5] or "photo",
        "file_id": row[6] or "",
        "caption": row[7] or "",
        "status": row[8] or "pending",
        "created_at": row[9],
        "reviewed_at": row[10],
        "decided_by": row[11],
        "days_granted": int(row[12]) if row[12] else 30,
    }


def get_payment_receipt(receipt_id: int):
    """Bitta chekni id bo'yicha qaytaradi (topilmasa None)."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, user_id, username, full_name, language_code, "
                "media_type, file_id, caption, status, created_at, reviewed_at, "
                "decided_by, days_granted "
                "FROM payment_receipts WHERE id = %s",
                (int(receipt_id),),
            )
            row = cur.fetchone()
        return _payment_receipt_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(f"payment_receipt olish xatosi: {e}")
        return None


def list_payment_receipts(status: str = "pending", limit: int = 20) -> list:
    """Berilgan holatdagi cheklarni (yangi birinchi) qaytaradi."""
    try:
        limit = max(1, min(int(limit), 100))
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, user_id, username, full_name, language_code, "
                "media_type, file_id, caption, status, created_at, reviewed_at, "
                "decided_by, days_granted "
                "FROM payment_receipts WHERE status = %s "
                "ORDER BY id DESC LIMIT %s",
                (status, limit),
            )
            return [_payment_receipt_row_to_dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error(f"payment_receiptlar ro'yxati xatosi: {e}")
        return []


def list_pending_payment_receipts(limit: int = 20) -> list:
    """Kutayotgan (tasdiqlanmagan) cheklar."""
    return list_payment_receipts(RECEIPT_STATUS_PENDING, limit)


def approve_payment_receipt(receipt_id: int, admin_id: int, days: int = None) -> dict:
    """Chekni tasdiqlaydi va PRO muddatini ATOMIK uzaytiradi.

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_receipt(receipt_id, admin_id, approved=True)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_receipt(receipt_id, admin_id, True)


def reject_payment_receipt(receipt_id: int, admin_id: int) -> dict:
    """Chekni rad etadi (faqat hali ko'rib chiqilmagan bo'lsa).

    .. deprecated:: v2
        Servis orqali chaqirish tavsiya etiladi:
        ``PaymentService.process_receipt(receipt_id, admin_id, approved=False)``
    """
    from services.payment_service import PaymentService
    return PaymentService.process_receipt(receipt_id, admin_id, False)


def get_pending_receipts_count() -> int:
    """Admin panel ko'rsatkichi uchun kutayotgan cheklar soni."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM payment_receipts WHERE status = 'pending'"
            )
            return int(cur.fetchone()[0])
    except Exception as e:
        logger.error(f"pending receipts count xatosi: {e}")
        return 0


# ============================================================
# CHANNEL POSTS HISTORY (Real-time Post History & AI Analytics)
# ============================================================

def save_channel_post_history(
    channel_id: str | int,
    message_id: int = None,
    content: str = "",
    views: int = 0,
    post_date=None
) -> int:
    """Yangi kelgan kanal postini channel_posts_history jadvaliga saqlaydi yoki yangilaydi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return -1
    text = str(content or "").strip()
    v_count = max(0, int(views or 0))
    if post_date is None:
        post_date = datetime.now(pytz.UTC)
    try:
        with db_cursor(commit=True) as cur:
            if message_id is not None:
                cur.execute(
                    "SELECT id FROM channel_posts_history WHERE channel_id = %s AND message_id = %s",
                    (ch_id, int(message_id))
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE channel_posts_history
                        SET content = COALESCE(NULLIF(%s, ''), content),
                            views = GREATEST(views, %s),
                            post_date = COALESCE(%s, post_date)
                        WHERE id = %s
                        RETURNING id
                        """,
                        (text, v_count, post_date, row[0])
                    )
                    res = cur.fetchone()
                    return int(res[0]) if res else row[0]
            cur.execute(
                """
                INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ch_id, message_id, text, v_count, post_date)
            )
            row = cur.fetchone()
            return int(row[0]) if row else -1
    except Exception as e:
        logger.error(f"Kanal post tarixini saqlashda xato: {e}")
        return -1


def get_channel_posts_history(channel_id: str | int, limit: int = 5) -> list[dict]:
    """Kanalning bazadagi oxirgi postlari tarixini qaytaradi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return []
    try:
        limit = max(1, min(int(limit), 50))
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, channel_id, message_id, content, views, post_date, created_at
                FROM channel_posts_history
                WHERE channel_id = %s
                ORDER BY post_date DESC, id DESC
                LIMIT %s
                """,
                (ch_id, limit)
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r[0],
                    "channel_id": r[1],
                    "message_id": r[2],
                    "text": r[3] or "",
                    "content": r[3] or "",
                    "views": r[4] or 0,
                    "post_date": r[5].isoformat() if r[5] else "",
                    "date": r[5].isoformat() if r[5] else "",
                    "created_at": r[6].isoformat() if r[6] else "",
                }
                for r in rows
            ]
    except Exception as e:
        logger.error(f"Kanal postlari tarixini olishda xato: {e}")
        return []


def is_channel_connected(channel_id: str | int) -> bool:
    """Kanal botga ulangan va faol ekanini tekshiradi."""
    ch_id = str(channel_id or "").strip()
    if not ch_id:
        return False
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM channels WHERE channel_id = %s AND is_active = TRUE",
                (ch_id,)
            )
            return cur.fetchone() is not None
    except Exception as e:
        logger.error(f"Kanal ulanganligini tekshirish xatosi: {e}")
        return False


def get_channel_posts_history_stats(channel_id: str | int = None) -> dict:
    """Kanal postlari tarixi bo'yicha umumiy statistika (soni, ko'rishlar)."""
    stats = {"history_count": 0, "total_views": 0, "avg_views": 0}
    try:
        with db_cursor() as cur:
            if channel_id:
                cur.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0)
                    FROM channel_posts_history
                    WHERE channel_id = %s
                    """,
                    (str(channel_id),)
                )
            else:
                cur.execute(
                    """
                    SELECT COUNT(*), COALESCE(SUM(views), 0), COALESCE(AVG(views), 0)
                    FROM channel_posts_history
                    """
                )
            row = cur.fetchone()
            if row:
                count = int(row[0] or 0)
                total_v = int(row[1] or 0)
                avg_v = round(float(row[2] or 0), 1)
                stats["history_count"] = count
                stats["total_views"] = total_v
                stats["avg_views"] = avg_v
    except Exception as e:
        logger.error(f"Kanal tarixi statistikasini olishda xato: {e}")
    return stats


# ============================================================
# POSTASSIST V2 — 6-BOSQICH: RBAC VA ADMIN AUDITI (DB CRUD)
# ------------------------------------------------------------
# Rollar ``admin_roles`` jadvalida saqlanadi (asosiy manba) va
# ``users.role`` ustunida aks ettiriladi (ko'rinish/moslik uchun).
# Admin harakatlari ``admin_audit_logs`` jadvaliga yoziladi.
# Biznes mantiq ``services/rbac_service.py`` va
# ``services/audit_service.py`` da; bu yerda faqat CRUD.
# ============================================================

#: Audit yozuvi uchun maydon chegaralari (jadval ustunlari bilan bir xil).
AUDIT_ACTION_MAX_LEN = 64
AUDIT_FIELD_MAX_LEN = 64


def _valid_admin_role(value):
    """Rol qiymatini tekshiradi (``services.rbac_service`` bilan bir xil to'plam)."""
    from services.rbac_service import parse_role
    return parse_role(value)


def get_admin_role(user_id):
    """Foydalanuvchining DB'dagi rolini qaytaradi (``None`` — rol yo'q).

    Avval ``admin_roles`` jadvali (aniq berilgan rol), keyin ``users.role``
    ustuni o'qiladi. Har qanday xato (jadval/ustun yo'q, DB uzilgan) —
    ``None``: RBAC qatlami legacy ``ADMIN_IDS`` ro'yxatiga tayanib ishlayveradi.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        with db_cursor() as cur:
            cur.execute("SELECT role FROM admin_roles WHERE user_id = %s", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.debug("get_admin_role(%s) admin_roles o'qishda xato: %s", uid, e)
    try:
        with db_cursor() as cur:
            cur.execute("SELECT role FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.debug("get_admin_role(%s) users.role o'qishda xato: %s", uid, e)
    return None


def set_admin_role(user_id, role, granted_by=None) -> bool:
    """Foydalanuvchiga rol beradi (upsert) va ``users.role`` ni yangilaydi.

    ``users`` jadvalidagi yozuv bo'lmasa ham rol saqlanadi (faqat
    ``admin_roles`` qatori qo'shiladi) — foydalanuvchi botga hali
    kirmagan bo'lishi mumkin.
    """
    parsed = _valid_admin_role(role)
    if parsed is None:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    try:
        actor = int(granted_by) if granted_by is not None else None
    except (TypeError, ValueError):
        actor = None

    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO admin_roles (user_id, role, granted_by, granted_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET role = EXCLUDED.role,
                        granted_by = EXCLUDED.granted_by,
                        updated_at = NOW()
                """,
                (uid, parsed.value, actor),
            )
            # users.role — ko'rinish uchun nusxa. Ich-ma-ich blok SAVEPOINT
            # ochadi: eski bazada ustun bo'lmasa faqat shu qism qaytariladi,
            # asosiy (admin_roles) yozuvi saqlanib qoladi.
            try:
                with db_cursor(commit=True) as mirror_cur:
                    mirror_cur.execute(
                        "UPDATE users SET role = %s WHERE user_id = %s",
                        (parsed.value, uid),
                    )
            except Exception as e:
                logger.debug("users.role yangilanmadi (user=%s): %s", uid, e)
        try:
            from services.rbac_service import invalidate_role_cache
            invalidate_role_cache(uid)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error("set_admin_role xatosi (user=%s, role=%s): %s", uid, parsed, e)
        return False


def delete_admin_role(user_id) -> bool:
    """Foydalanuvchi rolini o'chiradi (``users.role`` → 'user')."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM admin_roles WHERE user_id = %s", (uid,))
            deleted = cur.rowcount > 0
            try:
                with db_cursor(commit=True) as mirror_cur:
                    mirror_cur.execute(
                        "UPDATE users SET role = 'user' WHERE user_id = %s", (uid,)
                    )
            except Exception as e:
                logger.debug("users.role tozalanmadi (user=%s): %s", uid, e)
        try:
            from services.rbac_service import invalidate_role_cache
            invalidate_role_cache(uid)
        except Exception:
            pass
        return bool(deleted)
    except Exception as e:
        logger.error("delete_admin_role xatosi (user=%s): %s", uid, e)
        return False


def list_admin_roles(limit: int = 100) -> list:
    """``admin_roles`` jadvalidagi rollar ro'yxati (yangilari birinchi)."""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT user_id, role, granted_by, granted_at, updated_at "
                "FROM admin_roles ORDER BY updated_at DESC NULLS LAST LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return [
            {
                "user_id": int(row[0]),
                "role": str(row[1]),
                "granted_by": int(row[2]) if row[2] is not None else None,
                "granted_at": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("list_admin_roles xatosi: %s", e)
        return []


def log_admin_action(admin_id, action, target_type=None, target_id=None,
                     old_value=None, new_value=None, ip_or_metadata=None,
                     cur=None) -> bool:
    """Admin harakatini ``admin_audit_logs`` jadvaliga yozadi.

    ``cur`` berilsa — chaqiruvchining tranzaksiyasida (ATOMIK: biznes amali
    bilan birga commit/rollback bo'ladi). Berilmasa — o'z tranzaksiyasida.
    JSONB qiymatlar ``json.dumps`` orqali uzatiladi (``%s::jsonb``).
    """
    try:
        actor = int(admin_id)
    except (TypeError, ValueError):
        return False
    if actor <= 0:
        return False
    act = str(action or "").strip()[:AUDIT_ACTION_MAX_LEN]
    if not act:
        return False

    def _dump(value):
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"_repr": str(value)}, ensure_ascii=False)

    params = (
        actor,
        act,
        (str(target_type).strip()[:AUDIT_FIELD_MAX_LEN] or None)
        if target_type is not None else None,
        (str(target_id).strip()[:AUDIT_FIELD_MAX_LEN] or None)
        if target_id is not None else None,
        _dump(old_value),
        _dump(new_value),
        _dump(ip_or_metadata),
    )
    sql = (
        "INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id, "
        "old_value, new_value, ip_or_metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
    )
    if cur is not None:
        # Chaqiruvchi tranzaksiyasi ichida — xato yutilmaydi (ROLLBACK kafolati).
        cur.execute(sql, params)
        return True
    try:
        with db_cursor(commit=True) as own_cur:
            own_cur.execute(sql, params)
        return True
    except Exception as e:
        logger.error("log_admin_action xatosi (admin=%s, action=%s): %s", actor, act, e)
        return False


def get_admin_audit_logs(limit: int = 50, admin_id=None, action=None) -> list:
    """Audit yozuvlarini o'qish (eng yangisi birinchi)."""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50

    where = []
    params = []
    if admin_id is not None:
        try:
            where.append("admin_id = %s")
            params.append(int(admin_id))
        except (TypeError, ValueError):
            pass
    if action:
        where.append("action = %s")
        params.append(str(action).strip()[:AUDIT_ACTION_MAX_LEN])
    sql = (
        "SELECT id, admin_id, action, target_type, target_id, old_value, "
        "new_value, ip_or_metadata, created_at FROM admin_audit_logs"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    try:
        with db_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
        return [
            {
                "id": int(row[0]),
                "admin_id": int(row[1]),
                "action": row[2],
                "target_type": row[3],
                "target_id": row[4],
                "old_value": row[5],
                "new_value": row[6],
                "ip_or_metadata": row[7],
                "created_at": row[8],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("get_admin_audit_logs xatosi: %s", e)
        return []


def count_admin_audit_logs(admin_id=None, action=None) -> int:
    """Audit yozuvlari soni (filtrlar ixtiyoriy)."""
    where = []
    params = []
    if admin_id is not None:
        try:
            where.append("admin_id = %s")
            params.append(int(admin_id))
        except (TypeError, ValueError):
            pass
    if action:
        where.append("action = %s")
        params.append(str(action).strip()[:AUDIT_ACTION_MAX_LEN])
    sql = "SELECT COUNT(*) FROM admin_audit_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    try:
        with db_cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error("count_admin_audit_logs xatosi: %s", e)
        return 0
