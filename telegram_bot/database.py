import sqlite3
from datetime import datetime

DB_NAME = "bot_database.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            joined_at TEXT
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            channel_title TEXT,
            UNIQUE(user_id, channel_id)
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            channel_id TEXT,
            text TEXT,
            photo TEXT,
            scheduled_time TEXT,
            status TEXT DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

def register_user(user_id: int, username: str, full_name: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO users (user_id, username, full_name, joined_at)
        VALUES (?, ?, ?, ?)
    """, (user_id, username, full_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()

def add_channel(user_id: int, channel_id: str, channel_title: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT OR REPLACE INTO channels (user_id, channel_id, channel_title)
            VALUES (?, ?, ?)
        """, (user_id, str(channel_id), channel_title))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def get_user_channels(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = ?", (user_id,))
    channels = cursor.fetchall()
    conn.close()
    return channels

def delete_user_channel(user_id: int, channel_id: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM channels WHERE user_id = ? AND channel_id = ?", (user_id, str(channel_id)))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def add_post(user_id: int, channel_id: str, text: str, photo: str, scheduled_time: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO posts (user_id, channel_id, text, photo, scheduled_time)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, str(channel_id), text, photo, scheduled_time))
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id

def get_user_posts(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.id, c.channel_title, p.text, p.scheduled_time 
        FROM posts p
        LEFT JOIN channels c ON p.channel_id = c.channel_id AND p.user_id = c.user_id
        WHERE p.user_id = ? AND p.status = 'pending'
        ORDER BY p.scheduled_time ASC
    """, (user_id,))
    posts = cursor.fetchall()
    conn.close()
    return posts

def delete_user_post(user_id: int, post_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM posts WHERE id = ? AND user_id = ?", (post_id, user_id))
    affected = cursor.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_due_posts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    cursor.execute("""
        SELECT id, channel_id, text, photo 
        FROM posts 
        WHERE scheduled_time <= ? AND status = 'pending'
    """, (now_str,))
    posts = cursor.fetchall()
    conn.close()
    return posts

def mark_post_sent(post_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE posts SET status = 'sent' WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()

def get_system_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM channels")
    channels_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM posts WHERE status = 'pending'")
    pending_posts = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM posts WHERE status = 'sent'")
    sent_posts = cursor.fetchone()[0]
    conn.close()
    return {
        "users": users_count,
        "channels": channels_count,
        "pending": pending_posts,
        "sent": sent_posts
    }

def get_all_user_ids():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users
