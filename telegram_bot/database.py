import logging
from contextlib import contextmanager

import psycopg2

from config import DATABASE_URL

logger = logging.getLogger(__name__)


def get_connection():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def db_cursor(commit: bool = False):
    """
    Har doim ulanishni yopishni kafolatlaydigan xavfsiz cursor.
    Eski kodda xatolik yuz berganda conn.close() chaqirilmay, ulanish
    "osilib qolar" edi (connection leak). Endi try/finally bilan har doim yopiladi.
    """
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(255),
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
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id VARCHAR(255) NOT NULL,
                post_type VARCHAR(50) NOT NULL,
                content TEXT,
                file_id VARCHAR(255),
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_scheduled_posts_status_time
            ON scheduled_posts (status, scheduled_time);
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_channels_user
            ON channels (user_id);
        """)
    logger.info("Baza jadvallari tayyor.")


# ---------------------------------------------------------------------------
# USERS
# ---------------------------------------------------------------------------

def save_user(user_id: int, username: str):
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO users (user_id, username, created_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET username = EXCLUDED.username
            """, (user_id, username))
    except Exception as e:
        logger.error(f"User saqlash xatosi: {e}")


def get_all_user_ids() -> list:
    try:
        with db_cursor() as cur:
            cur.execute("SELECT user_id FROM users")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        logger.error(f"Foydalanuvchilar ro'yxatini olish xatosi: {e}")
        return []


# ---------------------------------------------------------------------------
# CHANNELS
# ---------------------------------------------------------------------------

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
    """Kanalni foydalanuvchi ro'yxatidan o'chiradi (soft-delete)."""
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute(
                    "UPDATE channels SET is_active = FALSE WHERE channel_id = %s",
                    (str(channel_id),)
                )
            else:
                cur.execute(
                    "UPDATE channels SET is_active = FALSE WHERE channel_id = %s AND user_id = %s",
                    (str(channel_id), user_id)
                )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Kanal o'chirish xatosi: {e}")
        return False


# ---------------------------------------------------------------------------
# POSTS
# ---------------------------------------------------------------------------

def add_post(user_id: int, channel_id: str, post_type: str, content: str, file_id: str, scheduled_time) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("""
                INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, file_id, scheduled_time, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
            """, (user_id, str(channel_id), post_type, content, file_id, scheduled_time))
        return True
    except Exception as e:
        logger.error(f"Post saqlash xatosi: {e}")
        return False


def get_pending_posts(user_id: int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time
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
                SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time, sp.user_id, u.username
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
    """Faqat 'pending' holatidagi postni bekor qiladi. Admin har qanday postni bekor qila oladi."""
    try:
        with db_cursor(commit=True) as cur:
            if is_admin:
                cur.execute("""
                    UPDATE scheduled_posts SET status = 'cancelled'
                    WHERE id = %s AND status = 'pending'
                """, (post_id,))
            else:
                cur.execute("""
                    UPDATE scheduled_posts SET status = 'cancelled'
                    WHERE id = %s AND user_id = %s AND status = 'pending'
                """, (post_id, user_id))
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"Post bekor qilish xatosi: {e}")
        return False


def get_due_posts(now) -> list:
    try:
        with db_cursor() as cur:
            cur.execute("""
                SELECT id, user_id, channel_id, post_type, content, file_id
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
        logger.error(f"Post holatini yangilash xatosi ({post_id} -> {status}): {e}")


# ---------------------------------------------------------------------------
# STATS
# ---------------------------------------------------------------------------

def get_system_stats() -> dict:
    stats = {"users": 0, "channels": 0, "pending": 0, "sent": 0, "cancelled": 0, "failed": 0}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            stats["users"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
            stats["channels"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
            stats["pending"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'posted'")
            stats["sent"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'cancelled'")
            stats["cancelled"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed'")
            stats["failed"] = cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Statistika olish xatosi: {e}")
    return stats
