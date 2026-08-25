import psycopg2
import logging
from config import DATABASE_URL

logger = logging.getLogger(__name__)

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        # Foydalanuvchilar jadvali
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id BIGINT UNIQUE NOT NULL,
                username VARCHAR(255),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        # Kanallar jadvali
        cur.execute("""
            CREATE TABLE IF NOT EXISTS channels (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id TEXT UNIQUE NOT NULL,
                channel_title TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        # Postlar jadvali
        cur.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_posts (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                channel_id TEXT NOT NULL,
                post_type VARCHAR(50) NOT NULL,
                content TEXT,
                file_id TEXT,
                scheduled_time TIMESTAMP WITH TIME ZONE NOT NULL,
                status VARCHAR(50) DEFAULT 'pending',
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        
        conn.commit()
        cur.close()
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Database init error: {e}")
    finally:
        if conn:
            conn.close()
