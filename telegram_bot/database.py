import logging
import random
import string
from contextlib import contextmanager
import psycopg2
from config import DATABASE_URL

logger = logging.getLogger(__name__)

def get_connection():
    return psycopg2.connect(DATABASE_URL)

@contextmanager
def db_cursor(commit: bool = False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db_cursor(commit=True) as cur:
        # Users jadvali
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
                full_name VARCHAR(255),
                user_code VARCHAR(8) UNIQUE,
                referrer_id BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Channels jadvali
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
        
        # Majburiy a'zolik homiy kanallari
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

        # Tizim sozlamalari (Global reklama matni va havolasi)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            );
        """)
        
        # Scheduled posts jadvali
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
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                user_post_number INTEGER,
                is_recurring BOOLEAN DEFAULT FALSE,
                recurrence_day INTEGER,
                recurrence_time TIME,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Reaksiya bosganlarni saqlash jadvali
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

        # Barcha yetishmayotgan ustunlarni eski bazaga xavfsiz qo'shish
        migrations = [
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name VARCHAR(255);",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS user_code VARCHAR(8) UNIQUE;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;",
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_text VARCHAR(255);",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS inline_button_url TEXT;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS enable_reactions BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS user_post_number INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS is_recurring BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_day INTEGER;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS recurrence_time TIME;",
            "ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        ]
        for m in migrations:
            try:
                cur.execute(m)
            except Exception as e:
                logger.warning(f"Migratsiya eslatmasi ({m}): {e}")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time ON scheduled_posts (status, scheduled_time);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_channels_user ON channels (user_id);")
    logger.info("Baza jadvallari tayyor.")

# --- SETTINGS & SPONSORS ---
def set_setting(key: str, value: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO system_settings (key, value)
                VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, value))
    except Exception as e:
        logger.error(f"Sozlamani saqlash xatosi: {e}")

def get_setting(key: str, default: str = "") -> str:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    except Exception as e:
        logger.error(f"Sozlamani olish xatosi: {e}")
        return default

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
        logger.error(f"Homiy kanal saqlash xatosi: {e}")
        return False

def get_active_sponsors() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT id, channel_id, channel_title, channel_url FROM sponsor_channels WHERE is_active = TRUE ORDER BY id ASC")
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Homiy kanallarni olish xatosi: {e}")
        return []

def remove_sponsor_channel(sponsor_id: int) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM sponsor_channels WHERE id = %s", (sponsor_id,))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Homiy kanal o'chirish xatosi: {e}")
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

            cur.execute("""
                SELECT reaction_type, COUNT(*) 
                FROM post_reactions 
                WHERE post_id = %s 
                GROUP BY reaction_type
            """, (post_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Reaksiya xatosi: {e}")
        return {}

def get_reaction_counts(post_id: int) -> dict:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT reaction_type, COUNT(*) 
                FROM post_reactions 
                WHERE post_id = %s 
                GROUP BY reaction_type
            """, (post_id,))
            return {r[0]: r[1] for r in cur.fetchall()}
    except Exception as e:
        logger.error(f"Reaksiya hisobini olish xatosi: {e}")
        return {}

# --- USERS & REFERRAL ---
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
                cur.execute(
                    "UPDATE users SET username = %s, full_name = %s WHERE user_id = %s",
                    (username, full_name, user_id)
                )
                return False
            else:
                code = _generate_user_code(cur)
                valid_ref = referrer_id if referrer_id and referrer_id != user_id else None
                cur.execute("""
                    INSERT INTO users (user_id, username, full_name, user_code, referrer_id, created_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                """, (user_id, username, full_name, code, valid_ref))
                return True
    except Exception as e:
        logger.error(f"User saqlash xatosi: {e}")
        return False

def get_referral_stats(user_id: int) -> dict:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (user_id,))
            count = cur.fetchone()[0]
            return {"referrals_count": count}
    except Exception as e:
        logger.error(f"Referral stats xatosi: {e}")
        return {"referrals_count": 0}

def get_all_user_ids() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Foydalanuvchilar ro'yxati xatosi: {e}")
        return []

def get_user_code(user_id: int) -> str:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_code FROM users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
            return row[0] if row and row[0] else str(user_id)
    except Exception as e:
        logger.error(f"User kodini olish xatosi: {e}")
        return str(user_id)

# --- CHANNELS ---
def get_user_channels(user_id: int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT channel_id, channel_title FROM channels
                WHERE user_id = %s AND is_active = TRUE
                ORDER BY id ASC
            """, (user_id,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Kanallarni olish xatosi: {e}")
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
        logger.error(f"Barcha kanallarni olish xatosi: {e}")
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
                cur.execute(
                    "UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND user_id = %s",
                    (str(channel_id), user_id)
                )
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
    is_recurring: bool = False,
    recurrence_day=None,
    recurrence_time=None,
    btn_text: str = None,
    btn_url: str = None,
    enable_reactions: bool = False
) -> int:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                "SELECT COALESCE(MAX(user_post_number), 0) + 1 FROM scheduled_posts WHERE user_id = %s",
                (user_id,)
            )
            next_num = cur.fetchone()[0]
            cur.execute("""
                INSERT INTO scheduled_posts
                    (user_id, channel_id, post_type, content, file_id, inline_button_text, inline_button_url,
                     enable_reactions, scheduled_time, status, user_post_number, is_recurring, recurrence_day, recurrence_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id, str(channel_id), post_type, content, file_id, btn_text, btn_url,
                enable_reactions, scheduled_time, next_num, is_recurring, recurrence_day, recurrence_time
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
                       sp.user_post_number, sp.is_recurring, sp.recurrence_day, sp.recurrence_time
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                WHERE sp.user_id = %s AND sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
            """, (user_id,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Pending posts xatosi: {e}")
        return []

def get_all_pending_posts() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time,
                       sp.user_id, u.username, sp.user_post_number,
                       sp.is_recurring, sp.recurrence_day, sp.recurrence_time, u.user_code
                FROM scheduled_posts sp
                LEFT JOIN channels c ON sp.channel_id = c.channel_id
                LEFT JOIN users u ON u.user_id = sp.user_id
                WHERE sp.status = 'pending'
                ORDER BY sp.scheduled_time ASC
            """)
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Barcha postlarni olish xatosi: {e}")
        return []

def get_post_owner(post_id: int):
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id, status FROM scheduled_posts WHERE id = %s", (post_id,))
            return cur.fetchone()
    except Exception as e:
        logger.error(f"Post egasini aniqlash xatosi: {e}")
        return None

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
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, channel_id, post_type, content, file_id,
                       inline_button_text, inline_button_url, enable_reactions, scheduled_time,
                       is_recurring, recurrence_day, recurrence_time
                FROM scheduled_posts
                WHERE status = 'pending' AND scheduled_time <= %s
            """, (now,))
            return cur.fetchall()
    except Exception as e:
        logger.error(f"Yuborilishi kerak bo'lgan postlarni olish xatosi: {e}")
        return []

def mark_post_status(post_id: int, status: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s", (status, post_id))
    except Exception as e:
        logger.error(f"Post statusini yangilash xatosi: {e}")

def reschedule_recurring_post(post_id: int, next_time):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE scheduled_posts SET scheduled_time = %s WHERE id = %s", (next_time, post_id))
    except Exception as e:
        logger.error(f"Takrorlanuvchi postni qayta rejalashtirish xatosi: {e}")

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
