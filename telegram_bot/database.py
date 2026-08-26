import psycopg2
from config import DATABASE_URL

def get_connection():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn = get_connection()
    cur = conn.cursor()
    
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
    
    conn.commit()
    cur.close()
    conn.close()
