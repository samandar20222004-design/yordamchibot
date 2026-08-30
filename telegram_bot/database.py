import os
import asyncio
import logging
import random
import string
import threading
import time as _time
from datetime import datetime, date, timedelta
from contextlib import contextmanager
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from config import DATABASE_URL

logger = logging.getLogger(__name__)

# Render Free PostgreSQL uchun ulanishlar soni cheklangan (odatda 5 ta).
# DB_POOL_MAX ni oshirishdan oldin Render'da Postgres ulanish limitini tekshiring.
DB_POOL_MIN = max(0, int(os.getenv("DB_POOL_MIN", "0")))
DB_POOL_MAX = max(DB_POOL_MIN + 1, int(os.getenv("DB_POOL_MAX", "5")))
# Har bir scheduler ishlashida ko'pi bilan shuncha post yuboriladi
# (ulkan navbat bitta tick'ni to'sib qo'ymasligi uchun).
POST_BATCH_SIZE = max(1, int(os.getenv("POST_BATCH_SIZE", "100")))
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "20"))

_pool = None
_pool_lock = threading.Lock()
_pool_sem = None


def _get_pool() -> ThreadedConnectionPool:
    """Pool'ni yaratib beradi (bir marta, keyin qayta ishlatiladi)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    DB_POOL_MIN, DB_POOL_MAX, DATABASE_URL,
                    connect_timeout=DB_CONNECT_TIMEOUT,
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


@contextmanager
def db_cursor(commit: bool = False):
    conn = None
    try:
        conn = _acquire_connection()
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except psycopg2.OperationalError:
            # Server ulanishni uzgan bo'lsa (masalan, Render DB uyquda) —
            # buzilgan ulanishni tashlab, xatoni chaqiruvchiga uzatamiz.
            _discard_connection(conn)
            conn = None
            raise
        _release_connection(conn)
        conn = None
    except Exception:
        if conn is not None:
            _discard_connection(conn)
        raise


async def run_in_thread(func, *args, **kwargs):
    """Sync DB funksiyasini alohida thread'da bajaradi — event loop bloklanmaydi.

    Scheduler va og'ir operatsiyalarda DB chaqiruvlarini shu orqali qiling:
        result = await db.run_in_thread(db.get_due_posts, now)
    """
    return await asyncio.to_thread(func, *args, **kwargs)


def ping_db() -> bool:
    """Health-check uchun baza bilan tez aloqa tekshiruvi."""
    try:
        with db_cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone()[0] == 1
    except Exception as e:
        logger.warning(f"DB ping xatosi: {e}")
        return False

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


def _init_db_once():
    with db_cursor(commit=True) as cur:
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
                channel_id VARCHAR(255) UNIQUE NOT NULL,
                channel_title VARCHAR(255),
                channel_url VARCHAR(255) NOT NULL,
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
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                post_type VARCHAR(50) NOT NULL,
                content TEXT,
                file_id VARCHAR(255),
                inline_button_text VARCHAR(255),
                inline_button_url TEXT,
                enable_reactions BOOLEAN DEFAULT FALSE,
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

        migrations = [
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
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS delete_after_hours INTEGER DEFAULT 0;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS sent_message_id BIGINT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS user_post_number INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_type VARCHAR(20) DEFAULT 'none';",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_day INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_time TIME;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS end_date TIMESTAMP WITH TIME ZONE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMP WITH TIME ZONE;",
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

        # Server crash paytida processing holatida qolgan postlarni qayta navbatga qaytaramiz.
        cur.execute("""
            UPDATE scheduled_posts
            SET status = 'pending', processing_started_at = NULL
            WHERE status = 'processing'
              AND processing_started_at < NOW() - INTERVAL '10 minutes'
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);")

# --- SETTINGS ---
def set_setting(key: str, value: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, value))
    except Exception as e:
        logger.error(f"Sozlama xatosi: {e}")

def get_setting(key: str, default: str = "") -> str:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.error(f"Sozlama olish xatosi: {e}")
        return default

# --- SPONSORS ---
def add_sponsor_channel(channel_id: str, channel_title: str, channel_url: str) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO sponsor_channels (channel_id, channel_title, channel_url, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET is_active = TRUE, channel_title = EXCLUDED.channel_title, channel_url = EXCLUDED.channel_url
            """, (str(channel_id), channel_title, channel_url))
        return True
    except Exception as e:
        logger.error(f"Sponsor xatosi: {e}")
        return False

def get_active_sponsors() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id, channel_id, channel_title, channel_url FROM sponsor_channels WHERE is_active = TRUE ORDER BY id ASC")
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Sponsorlar olish xatosi: {e}")
        return []

def remove_sponsor_channel(sponsor_id: int) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM sponsor_channels WHERE id = %s", (sponsor_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Sponsor o'chirish xatosi: {e}")
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
def _generate_user_code(cur) -> str:
    letters = string.ascii_lowercase
    for _ in range(50):
        code = "".join(random.choice(letters) for _ in range(2)) + random.choice(string.digits)
        cur.execute("SELECT 1 FROM users WHERE user_code = %s", (code,))
        if not cur.fetchone():
            return code
    return "".join(random.choice(letters) for _ in range(3)) + "".join(random.choice(string.digits) for _ in range(2))

def save_user(user_id: int, username: str, full_name: str = "", referrer_id: int = None) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            if row:
                cur.execute("UPDATE users SET username = %s, full_name = %s WHERE user_id = %s", (username, full_name, user_id))
                return False
            else:
                code = _generate_user_code(cur)
                valid_ref = referrer_id if referrer_id and referrer_id != user_id else None
                cur.execute("""
                    INSERT INTO users (user_id, username, full_name, user_code, referrer_id, ai_credits, ad_free_posts, ad_free_active, streak_days, created_at)
                    VALUES (%s, %s, %s, %s, %s, 5, 0, TRUE, 0, NOW())
                """, (user_id, username, full_name, code, valid_ref))
                
                if valid_ref:
                    cur.execute("UPDATE users SET ai_credits = ai_credits + 3 WHERE user_id = %s", (valid_ref,))
                return True
    except Exception as e:
        logger.error(f"User saqlash xatosi: {e}")
        return False

def claim_daily_streak_bonus(user_id: int) -> dict:
    today = date.today()
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

def buy_ad_free_posts(user_id: int) -> tuple[bool, str]:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT ai_credits FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or row[0] < 1:
                return False, "Hisobingizda yetarli ball mavjud emas."
            
            cur.execute("UPDATE users SET ai_credits = ai_credits - 1, ad_free_posts = ad_free_posts + 5, ad_free_active = TRUE WHERE user_id = %s", (user_id,))
            return True, "✅ <b>5 ta reklamasiz toza post</b> litsenziyasi qo'shildi!"
    except Exception as e:
        logger.error(f"Xarid xatosi: {e}")
        return False, f"Xatolik: {e}"

def refund_ad_free_posts(user_id: int) -> tuple[bool, str]:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT ad_free_posts FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row or row[0] < 5:
                return False, "Ballni qaytarish uchun kamida <b>5 ta</b> ishlatilmagan post litsenziyasi bo'lishi kerak."
            
            refund_credits = row[0] // 5
            remaining_posts = row[0] % 5
            
            cur.execute("""
                UPDATE users 
                SET ai_credits = ai_credits + %s, ad_free_posts = %s 
                WHERE user_id = %s
            """, (refund_credits, remaining_posts, user_id))
            
            return True, f"✅ <b>{refund_credits * 5} ta post litsenziyasi</b> bekor qilindi va hisobingizga <b>+{refund_credits} ta AI ball</b> qaytarildi!"
    except Exception as e:
        logger.error(f"Qaytarish xatosi: {e}")
        return False, f"Xatolik: {e}"

def toggle_ad_free_status(user_id: int) -> tuple[bool, bool]:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT ad_free_active, ad_free_posts FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if not row:
                return False, False
            new_status = not (row[0] if row[0] is not None else True)
            cur.execute("UPDATE users SET ad_free_active = %s WHERE user_id = %s", (new_status, user_id))
            return True, new_status
    except Exception as e:
        logger.error(f"Status o'zgartirish xatosi: {e}")
        return False, False

def consume_ad_free_post(user_id: int) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT ad_free_posts, ad_free_active FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
            row = cur.fetchone()
            if row and row[0] > 0 and (row[1] is True or row[1] is None):
                cur.execute("UPDATE users SET ad_free_posts = ad_free_posts - 1 WHERE user_id = %s", (user_id,))
                return True
            return False
    except Exception as e:
        logger.error(f"Litsenziya sarflash xatosi: {e}")
        return False


def peek_ad_free_post(user_id: int) -> bool:
    """Litsenziya mavjudligini tekshiradi, lekin SARCHFAMAYDI.

    Scheduler postni yuborishdan oldin shu orqali tekshiradi va faqat
    muvaffaqiyatli yuborilgandan keyin consume_ad_free_post() bilan sarflaydi.
    """
    try:
        with db_cursor() as cur:
            cur.execute("SELECT ad_free_posts, ad_free_active FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return bool(row and row[0] is not None and row[0] > 0 and (row[1] is True or row[1] is None))
    except Exception as e:
        logger.error(f"Litsenziya tekshirish xatosi: {e}")
        return False

def add_user_credit(user_id: int, amount: int = 1) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE users SET ai_credits = ai_credits + %s WHERE user_id = %s", (amount, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Ball qaytarish xatosi: {e}")
        return False

def get_user_credits(user_id: int) -> int:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] is not None else 0
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
            return cur.fetchone() is not None
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
            if created_at and (datetime.now() - created_at).days < 3:
                return False, "⚠️ <b>Xavfsizlik qoidasi:</b> Yangi ro'yxatdan o'tgan foydalanuvchilar ballarni <b>3 kun o'tgach</b> boshqalarga ulasha oladi."
                
            if credits < amount:
                return False, "Hisobingizda yetarli ball mavjud emas."

            cur.execute("SELECT user_id FROM users WHERE user_id = %s", (to_user_id,))
            if not cur.fetchone():
                return False, "Qabul qiluvchi foydalanuvchi topilmadi."

            cur.execute("UPDATE users SET ai_credits = ai_credits - %s WHERE user_id = %s", (amount, from_user_id))
            cur.execute("UPDATE users SET ai_credits = ai_credits + %s WHERE user_id = %s", (amount, to_user_id))
            return True, "Ballar muvaffaqiyatli o'tkazildi!"
    except Exception as e:
        logger.error(f"Ball o'tkazish xatosi: {e}")
        return False, f"Tizim xatoligi: {e}"

def get_referral_stats(user_id: int) -> dict:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (user_id,))
            ref_count = cur.fetchone()[0]
            cur.execute("SELECT ai_credits, ad_free_posts, streak_days, ad_free_active FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            credits = row[0] if row and row[0] is not None else 0
            ad_free = row[1] if row and len(row) > 1 and row[1] is not None else 0
            streak = row[2] if row and len(row) > 2 and row[2] is not None else 0
            active = row[3] if row and len(row) > 3 and row[3] is not None else True
            return {"referrals_count": ref_count, "ai_credits": credits, "ad_free_posts": ad_free, "streak": streak, "ad_free_active": active}
    except Exception as e:
        logger.error(f"Referral xatosi: {e}")
        return {"referrals_count": 0, "ai_credits": 0, "ad_free_posts": 0, "streak": 0, "ad_free_active": True}

def get_all_user_ids() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Foydalanuvchilar xatosi: {e}")
        return []

def get_user_code(user_id: int) -> str:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else str(user_id)
    except Exception as e:
        logger.error(f"User kod xatosi: {e}")
        return str(user_id)

# --- CHANNELS ---
def get_user_channels(user_id: int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND is_active = TRUE ORDER BY id ASC", (user_id,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanallar olish xatosi: {e}")
        return []

def get_all_channels() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT c.channel_id, c.channel_title, c.user_id, u.username
                FROM channels c
                LEFT JOIN users u ON u.user_id = c.user_id
                WHERE c.is_active = TRUE
                ORDER BY c.id ASC
            """)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Barcha kanallar xatosi: {e}")
        return []

def save_channel(user_id: int, channel_id: str, channel_title: str) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO channels (user_id, channel_id, channel_title, is_active)
                VALUES (%s, %s, %s, TRUE)
                ON CONFLICT (channel_id) DO UPDATE
                SET is_active = TRUE, channel_title = EXCLUDED.channel_title, user_id = EXCLUDED.user_id
            """, (user_id, str(channel_id), channel_title))
        return True
    except Exception as e:
        logger.error(f"Kanal saqlash xatosi: {e}")
        return False

def remove_channel(user_id: int, channel_id: str, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s", (str(channel_id),))
            else:
                cur.execute("UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND user_id = %s", (str(channel_id), user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Kanal o'chirish xatosi: {e}")
        return False

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
    delete_after_hours: int = 0
) -> int:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT COALESCE(MAX(user_post_number), 0) + 1 FROM scheduled_posts WHERE user_id = %s", (user_id,))
            next_num = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO scheduled_posts
                    (user_id, channel_id, post_type, content, file_id, inline_button_text, inline_button_url,
                     enable_reactions, delete_after_hours, scheduled_time, status, user_post_number, 
                     recurrence_type, recurrence_day, recurrence_time, end_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id, str(channel_id), post_type, content, file_id, btn_text, btn_url,
                enable_reactions, delete_after_hours, scheduled_time, next_num,
                recurrence_type, recurrence_day, recurrence_time, end_date
            ))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Post saqlash xatosi: {e}")
        return 0

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

def cancel_post(post_id: int, user_id: int, is_admin: bool = False) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND status = 'pending'", (post_id,))
            else:
                cur.execute("UPDATE scheduled_posts SET status = 'cancelled' WHERE id = %s AND user_id = %s AND status = 'pending'", (post_id, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Post bekor qilish xatosi: {e}")
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
                          sp.recurrence_time, sp.end_date, sp.delete_after_hours
            """, (now, POST_BATCH_SIZE))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Due posts xatosi: {e}")
        return []

def mark_post_status(post_id: int, status: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s", (status, post_id))
    except Exception as e:
        logger.error(f"Post status xatosi: {e}")

def mark_post_as_sent(post_id: int, sent_message_id: int, channel_id: str = None, delete_after_hours: int = 0):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = 'posted', sent_message_id = %s WHERE id = %s", (sent_message_id, post_id))
            if channel_id is not None:
                cur.execute("""
                    INSERT INTO sent_post_messages (post_id, channel_id, message_id, delete_at)
                    VALUES (%s, %s, %s, CASE WHEN %s > 0 THEN NOW() + (%s || ' hours')::INTERVAL ELSE NULL END)
                """, (post_id, str(channel_id), sent_message_id, delete_after_hours, delete_after_hours))
    except Exception as e:
        logger.error(f"Post yuborilganini belgilash xatosi: {e}")

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
    except Exception as e:
        logger.error(f"Post o'chirish xatosi: {e}")

def reschedule_recurring_post(post_id: int, next_time):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s", (next_time, post_id))
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
    except Exception as e:
        logger.error(f"Post qayta navbatlash xatosi: {e}")


def cleanup_old_data() -> dict:
    """Eski, keraksiz ma'lumotlarni o'chirish (scheduler har 6 soatda chaqiradi).

    Baza o'sib ketmasligi uchun: yuborilgan/ochilgan xabarlar, 30 kundan eski
    yakunlangan postlar va boshqa qoldiqlar tozalanadi.
    """
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

            cur.execute("DELETE FROM post_reactions WHERE post_id NOT IN (SELECT id FROM scheduled_posts)")
            deleted["post_reactions"] = cur.rowcount

            cur.execute("DELETE FROM channels WHERE is_active = FALSE AND created_at < NOW() - INTERVAL '90 days'")
            deleted["channels"] = cur.rowcount
        return deleted
    except Exception as e:
        logger.error(f"DB tozalash xatosi: {e}")
        return deleted

# --- STATS ---
def get_system_stats() -> dict:
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
    except Exception as e:
        logger.error(f"Statistika xatosi: {e}")
    return stats
