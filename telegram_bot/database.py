import sqlite3
from datetime import datetime
from contextlib import closing

DB_PATH = "bot_database.db"


def init_db():
    """Ma'lumotlar bazasini va jadvalni yaratadi (agar mavjud bo'lmasa)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT,                    -- matn yoki media izohi (caption), bo'sh bo'lishi mumkin
                post_type TEXT NOT NULL,      -- 'once' yoki 'daily'
                send_time TEXT NOT NULL,      -- 'HH:MM'
                send_date TEXT,               -- 'once' uchun: 'YYYY-MM-DD'
                end_date TEXT,                -- 'daily' uchun tugash sanasi (bo'sh = cheksiz)
                media_type TEXT,              -- 'photo' | 'video' | 'document' | NULL (faqat matn)
                media_file_id TEXT,           -- Telegram file_id (faylning o'zi emas, faqat havolasi!)
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def add_post(text, post_type, send_time, send_date=None, end_date=None,
             media_type=None, media_file_id=None):
    """Yangi rejalashtirilgan xabar qo'shadi va uning ID sini qaytaradi.
    Diqqat: media_file_id — Telegram'ning o'zida saqlanadigan faylga ishora
    qiluvchi qisqa satr, fayl bayt-baytlab bu yerga yozilmaydi."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        cur = conn.execute(
            "INSERT INTO posts (text, post_type, send_time, send_date, end_date, "
            "media_type, media_file_id, active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (text, post_type, send_time, send_date, end_date,
             media_type, media_file_id, datetime.now().isoformat()),
        )
        conn.commit()
        return cur.lastrowid


def get_active_posts():
    """Barcha faol (hali o'chirilmagan) rejalashtirilgan xabarlarni qaytaradi."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM posts WHERE active = 1 ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_post(post_id):
    """Bitta xabarni ID bo'yicha qaytaradi (topilmasa None)."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return dict(row) if row else None


def deactivate_post(post_id):
    """Bir martalik xabar yuborilgandan keyin uni faolsizlantiradi."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("UPDATE posts SET active = 0 WHERE id = ?", (post_id,))
        conn.commit()


def delete_post(post_id):
    """Xabarni bazadan butunlay o'chiradi."""
    with closing(sqlite3.connect(DB_PATH)) as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()
