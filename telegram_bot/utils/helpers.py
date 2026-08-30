import html
import time
import pytz
import database as db

tashkent_tz = pytz.timezone("Asia/Tashkent")

_USER_HISTORY = {}
_USER_WARNED = {}
_USER_MSG_COUNT = {}
_AI_HISTORY = {}
_AI_DAILY = {}
_DUP_HISTORY = {}
_GLOBAL_FLOOD = []  # so'nggi 1 soniyadagi barcha update'lar vaqtlari

# Hujum / ortiqcha yuklama himoyasi chegaralari
GLOBAL_MAX_UPDATES_PER_SEC = 60     # butun bot bo'yicha 1 soniyada 60 tadan ortiq update
USER_MAX_UPDATES_PER_2SEC = 20      # bitta foydalanuvchi 2 soniyada 20 tadan ortiq
DUP_WINDOW_SECONDS = 1.5            # bir xil xabar shu vaqt ichida qayta yuborilsa — tashlab yuboriladi
AI_MAX_PER_MINUTE = 4               # AI: daqiqasiga 4 ta
AI_MAX_PER_DAY = 30                 # AI: kuniga 30 ta (bepul limitlarni tejash)


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


def check_ai_rate_limit(user_id: int, max_per_minute: int = AI_MAX_PER_MINUTE) -> bool:
    """AI so'rovlari uchun alohida rate-limit (daqiqasiga maks. N ta).

    True qaytsa — foydalanuvchi bloklangan (AI API'ga ortiqcha so'rov
    yubormaslik va bepul balansni tejash uchun).
    """
    now = time.time()
    if len(_AI_HISTORY) > 5000:
        _AI_HISTORY.clear()

    history = [t for t in _AI_HISTORY.get(user_id, []) if now - t < 60]
    if len(history) >= max_per_minute:
        _AI_HISTORY[user_id] = history
        return True

    history.append(now)
    _AI_HISTORY[user_id] = history
    return False


def check_ai_daily_limit(user_id: int, max_per_day: int = AI_MAX_PER_DAY) -> bool:
    """AI so'rovlari uchun kunlik limit (24 soatlik sirg'aluvchi oyna).

    True qaytsa — kunlik limit tugagan (bepul API kunlik kvotalarini
    himoya qiladi va bitta foydalanuvchi botning AI byudjetini yeb qo'ymaydi).
    """
    now = time.time()
    if len(_AI_DAILY) > 5000:
        _AI_DAILY.clear()

    history = [t for t in _AI_DAILY.get(user_id, []) if now - t < 24 * 3600]
    if len(history) >= max_per_day:
        _AI_DAILY[user_id] = history
        return True

    history.append(now)
    _AI_DAILY[user_id] = history
    return False


def check_global_flood() -> bool:
    """Butun bot bo'yicha flood tekshiruvi (update/s soniya).

    True qaytsa — hozir juda ko'p update kelmoqda (DDoS/flood), bot
    qisqa pauza qilib ishlashda davom etadi.
    """
    now = time.time()
    _GLOBAL_FLOOD.append(now)
    # Eski yozuvlarni tozalash (o'sishni cheklash)
    while _GLOBAL_FLOOD and _GLOBAL_FLOOD[0] < now - 1.0:
        _GLOBAL_FLOOD.pop(0)
    return len(_GLOBAL_FLOOD) > GLOBAL_MAX_UPDATES_PER_SEC


def is_duplicate_message(user_id: int, text: str) -> bool:
    """Bir xil xabarni qisqa vaqt ichida qayta yuborishni aniqlash.

    Botga spam/retry hujumlarini to'xtatadi (masalan, bitta xabarni
    avtomatik qayta-qayta yuborish).
    """
    if not text:
        return False
    now = time.time()
    key = (user_id, text[:200])
    last = _DUP_HISTORY.get(key)
    if last and now - last < DUP_WINDOW_SECONDS:
        return True
    _DUP_HISTORY[key] = now
    if len(_DUP_HISTORY) > 8000:
        # Eski yozuvlarni tozalash
        cutoff = now - 10
        for k in [k for k, v in _DUP_HISTORY.items() if v < cutoff]:
            _DUP_HISTORY.pop(k, None)
    return False

def get_smart_reply_ad(user_id: int) -> str:
    ad_text = db.get_setting("bot_reply_ad_text", "").strip()
    if not ad_text:
        return ""

    count = _USER_MSG_COUNT.get(user_id, 0) + 1
    _USER_MSG_COUNT[user_id] = count

    # Xotira o'sishini cheklash: 10 000 dan oshsa eski yozuvlarni tozalaymiz
    if len(_USER_MSG_COUNT) > 10000:
        _USER_MSG_COUNT.clear()

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
