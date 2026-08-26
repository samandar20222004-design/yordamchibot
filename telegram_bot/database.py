import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Foydalanuvchilar jadvali
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username VARCHAR(255),
            full_name VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Kanallar jadvali
    cur.execute("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id BIGINT PRIMARY KEY,
            owner_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            title VARCHAR(255),
            username VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Rejalashtirilgan postlar jadvali
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            channel_id BIGINT,
            message_type VARCHAR(50),
            text_content TEXT,
            file_id VARCHAR(255),
            buttons_data TEXT,
            scheduled_time TIMESTAMP,
            status VARCHAR(50) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    conn.commit()
    cur.close()
    conn.close()

def add_user(user_id: int, username: str, full_name: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, username, full_name)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE 
        SET username = EXCLUDED.username, full_name = EXCLUDED.full_name;
    """, (user_id, username, full_name))
    conn.commit()
    cur.close()
    conn.close()

def add_channel(channel_id: int, owner_id: int, title: str, username: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO channels (channel_id, owner_id, title, username)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (channel_id) DO UPDATE 
        SET title = EXCLUDED.title, username = EXCLUDED.username;
    """, (channel_id, owner_id, title, username))
    conn.commit()
    cur.close()
    conn.close()

def get_user_channels(owner_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM channels WHERE owner_id = %s;", (owner_id,))
    channels = cur.fetchall()
    cur.close()
    conn.close()
    return channels

def delete_channel(channel_id: int, owner_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM channels WHERE channel_id = %s AND owner_id = %s;", (channel_id, owner_id))
    conn.commit()
    cur.close()
    conn.close()

def save_scheduled_post(user_id: int, channel_id: int, message_type: str, text_content: str, file_id: str, buttons_data: str, scheduled_time):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO scheduled_posts (user_id, channel_id, message_type, text_content, file_id, buttons_data, scheduled_time)
        VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id;
    """, (user_id, channel_id, message_type, text_content, file_id, buttons_data, scheduled_time))
    post_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return post_id

def get_pending_posts(user_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM scheduled_posts WHERE user_id = %s AND status = 'pending' ORDER BY scheduled_time ASC;", (user_id,))
    posts = cur.fetchall()
    cur.close()
    conn.close()
    return posts

def delete_scheduled_post(post_id: int, user_id: int):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM scheduled_posts WHERE id = %s AND user_id = %s;", (post_id, user_id))
    conn.commit()
    cur.close()
    conn.close()

def update_post_status(post_id: int, status: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s;", (status, post_id))
    conn.commit()
    cur.close()
    conn.close()
