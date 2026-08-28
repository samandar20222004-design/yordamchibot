import html
import time
import pytz

tashkent_tz = pytz.timezone("Asia/Tashkent")

# Foydalanuvchilarning bosish vaqtlari tarixi
_USER_HISTORY = {}
_USER_WARNED = {}

def check_rate_limit(user_id: int, max_requests: int = 3, window_seconds: float = 3.0) -> tuple[bool, bool]:
    """
    Foydalanuvchi window_seconds ichida max_requests dan ko'p so'rov yuborganini tekshiradi.
    Qaytaradi: (is_blocked, should_warn)
    """
    now = time.time()
    
    # Xotirani tozalash
    if len(_USER_HISTORY) > 5000:
        _USER_HISTORY.clear()
        _USER_WARNED.clear()
        
    history = _USER_HISTORY.get(user_id, [])
    # Faqat so'nggi window_seconds ichidagi so'rovlarni qoldiramiz
    history = [t for t in history if now - t < window_seconds]
    
    if len(history) >= max_requests:
        # Bloklangan
        warned = _USER_WARNED.get(user_id, 0)
        should_warn = (now - warned > window_seconds)
        if should_warn:
            _USER_WARNED[user_id] = now
        _USER_HISTORY[user_id] = history
        return True, should_warn
        
    history.append(now)
    _USER_HISTORY[user_id] = history
    return False, False

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
