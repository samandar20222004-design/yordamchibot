import html
import time
import pytz

tashkent_tz = pytz.timezone("Asia/Tashkent")

# Foydalanuvchilarning oxirgi so'rov vaqtlarini saqlash
_USER_LAST_ACTION = {}

def check_user_flood(user_id: int, cooldown_seconds: float = 0.8) -> bool:
    """
    Foydalanuvchi ketma-ket juda tez bosayotganini aniqlaydi.
    Agar vaqt oralig'i juda qisqa bo'lsa, True qaytaradi.
    """
    now = time.time()
    last_action = _USER_LAST_ACTION.get(user_id, 0)
    
    # Xotira to'lib ketmasligi uchun tozalash
    if len(_USER_LAST_ACTION) > 5000:
        _USER_LAST_ACTION.clear()
        
    if now - last_action < cooldown_seconds:
        return True
        
    _USER_LAST_ACTION[user_id] = now
    return False

def html_escape(text) -> str:
    """HTML maxsus belgilarini xavfsiz holatga keltiradi."""
    if not text:
        return ""
    return html.escape(str(text))

def md_escape(text) -> str:
    return html_escape(text)

def format_post_code(user_code, user_post_number) -> str:
    return f"{user_code}-{user_post_number}" if user_post_number else str(user_code)

def format_post_type_label(post_type: str, content: str = "") -> str:
    pt = str(post_type).lower()
    if pt == "photo":
        return "Rasm"
    elif pt == "video":
        return "Video"
    elif pt == "animation":
        return "GIF"
    elif pt == "document":
        return "Hujjat"
    elif pt == "audio":
        return "Audio"
    elif pt == "voice":
        return "Ovozli xabar"
    elif pt == "video_note":
        return "Dumaloq video"
    elif pt == "sticker":
        return "Stiker"
    elif pt == "text":
        return "Matn"
    elif pt in ("original_message", "forward_copy"):
        return "Post"
    return "Xabar"

def format_schedule_line(s_time, recurrence_type, recurrence_day, recurrence_time):
    from keyboards.default import WEEKDAY_LABELS
    if recurrence_type == 'daily':
        time_str = recurrence_time.strftime("%H:%M") if hasattr(recurrence_time, 'strftime') else str(recurrence_time)[:5]
        return f"🔁 <b>Har kuni</b>, soat <b>{time_str}</b> da"
    elif recurrence_type == 'weekly':
        day_label = WEEKDAY_LABELS.get(recurrence_day, "?")
        time_str = recurrence_time.strftime("%H:%M") if hasattr(recurrence_time, 'strftime') else str(recurrence_time)[:5]
        return f"📅 <b>Har {day_label}</b>, soat <b>{time_str}</b> da"
        
    if s_time:
        if s_time.tzinfo is None:
            s_time = pytz.utc.localize(s_time).astimezone(tashkent_tz)
        else:
            s_time = s_time.astimezone(tashkent_tz)
        return f"⏰ Vaqti: <b>{s_time.strftime('%Y-%m-%d %H:%M')}</b>"
    return "⏰ Vaqti: Noma'lum"
