import html
import time
import pytz
import database as db

tashkent_tz = pytz.timezone("Asia/Tashkent")

_USER_HISTORY = {}
_USER_WARNED = {}
_USER_MSG_COUNT = {}

def check_rate_limit(user_id: int, max_requests: int = 3, window_seconds: float = 3.0) -> tuple[bool, bool]:
    now = time.time()
    if len(_USER_HISTORY) > 5000:
        _USER_HISTORY.clear()
        _USER_WARNED.clear()
        
    history = _USER_HISTORY.get(user_id, [])
    history = [t for t in history if now - t < window_seconds]
    
    if len(history) >= max_requests:
        warned = _USER_WARNED.get(user_id, 0)
        should_warn = (now - warned > window_seconds)
        if should_warn:
            _USER_WARNED[user_id] = now
        _USER_HISTORY[user_id] = history
        return True, should_warn
        
    history.append(now)
    _USER_HISTORY[user_id] = history
    return False, False

def get_smart_reply_ad(user_id: int) -> str:
    ad_text = db.get_setting("bot_reply_ad_text", "").strip()
    if not ad_text:
        return ""
        
    count = _USER_MSG_COUNT.get(user_id, 0) + 1
    _USER_MSG_COUNT[user_id] = count
    
    if count % 3 == 0:
        return f"\n\n🏷 <i>({html_escape(ad_text)})</i>"
    return ""

def html_escape(text) -> str:
    if not text:
        return ""
    return html.escape(str(text))

def format_post_type_label(post_type: str) -> str:
    pt = str(post_type).lower()
    mapping = {
        "photo": "Rasm",
        "video": "Video",
        "animation": "GIF",
        "document": "Hujjat",
        "audio": "Audio",
        "voice": "Ovozli xabar",
        "sticker": "Stiker",
        "text": "Matn"
    }
    return mapping.get(pt, "Xabar")

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
