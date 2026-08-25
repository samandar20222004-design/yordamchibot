import logging
from datetime import datetime
import pytz
from database import get_connection

logger = logging.getLogger(__name__)
tashkent_tz = pytz.timezone("Asia/Tashkent")

async def check_and_send_posts(bot):
    now = datetime.now(tashkent_tz)
    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, user_id, channel_id, post_type, content, file_id 
            FROM scheduled_posts 
            WHERE status = 'pending' AND scheduled_time <= %s
        """, (now,))
        
        posts = cur.fetchall()
        
        for post in posts:
            post_id, user_id, channel_id, post_type, content, file_id = post
            try:
                target_chat = int(channel_id) if str(channel_id).lstrip('-').isdigit() else channel_id
                
                if post_type == "photo" and file_id:
                    await bot.send_photo(chat_id=target_chat, photo=file_id, caption=content or "")
                else:
                    await bot.send_message(chat_id=target_chat, text=content or "")
                
                cur.execute("UPDATE scheduled_posts SET status = 'posted' WHERE id = %s", (post_id,))
                conn.commit()
                logger.info(f"Post #{post_id} sent successfully.")
                
            except Exception as e:
                logger.error(f"Error sending post #{post_id}: {e}")
                cur.execute("UPDATE scheduled_posts SET status = 'failed' WHERE id = %s", (post_id,))
                conn.commit()
                
        cur.close()
    except Exception as e:
        logger.error(f"Scheduler execution error: {e}")
    finally:
        if conn:
            conn.close()
