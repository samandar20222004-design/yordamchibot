import html
import re
import time
from datetime import datetime, timedelta
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
        "text": "Matn",
        "album": "Albom",
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


# ---------------- Erkin tildagi vaqtni aniqlash (natural language) ----------------

def _norm_time_text(text: str) -> str:
    t = (text or "").lower().strip()
    # Ko'p uchraydigan yozilish variantlarini normallashtirish
    for ch in (".", ","):
        t = t.replace(ch, ":")
    t = t.replace("−", "-").replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", " ", t)
    return t


def parse_future_time(text: str, now: datetime = None) -> datetime | None:
    """Erkin tildagi vaqtni Toshkent vaqti bo'yicha kelajakdagi datetime'ga aylantiradi.

    Qo'llab-quvvatlanadi (o'zbek/ruscha aralash):
      • '5 daqiqadan keyin', '15 мин кейин', '1 soatdan keyin', '2 kun keyin'
      • '15:45 ga', 'bugun 15:45', 'ertaga ertalab 9', 'ertaga 18:00 da'
      • '2026-08-30 18:00', '30.08.2026 18:00', '2-sentyabr 18:00'
      • 'ertalab 9' (09:00), 'tushda 12' (12:00), 'kechqurun 8' (20:00)
    Aniqlanmasa yoki vaqt o'tib ketgan bo'lsa — None.
    """
    if not text:
        return None
    tz = tashkent_tz
    if now is None:
        now = datetime.now(tz)
    elif now.tzinfo is None:
        now = tz.localize(now)
    t = _norm_time_text(text)

    # 1) Nisbiy vaqt: "N daqiqa/soat/kun ... keyin"
    rel = re.search(
        r"(\d{1,3})\s*(daqiqa|minut|минут|мин|soat|час|kun|день|дня|сут)",
        t,
    )
    if rel:
        amount = int(rel.group(1))
        unit = rel.group(2)
        if unit.startswith(("daqiqa", "minut", "минут", "мин")):
            return now + timedelta(minutes=amount)
        if unit.startswith(("soat", "час")):
            return now + timedelta(hours=amount)
        if unit.startswith(("kun", "день", "дня", "сут")):
            return now + timedelta(days=amount)

    # 2) Kun ofseti: bugun / ertaga / indinga
    day_offset = 0
    if re.search(r"\b(ertaga|erta ga|эртага|завтра|ertasiga)\b", t):
        day_offset = 1
    elif re.search(r"\b(indinga|indini|послезавтра)\b", t):
        day_offset = 2

    month_names = {
        "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
        "iyul": 7, "avgust": 8, "sentyabr": 9, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
        "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "июн": 6, "июл": 7,
        "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    }

    def _safe_date(y, mo, d):
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            return None
        try:
            return datetime(y, mo, d).date()
        except ValueError:
            return None

    # 3) Sana qismi. Topilgach sana parchasi vaqt qidiriladigan matndan
    # chiqarib tashlanadi ("02:09:2026" vaqt deb o'qilib qolmasligi uchun).
    parsed_date = None
    t_time = t
    m_full = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    m_dmy = re.search(r"\b(\d{1,2})[:\-/](\d{1,2})[:\-/](\d{2,4})\b", t)
    m_mon = re.search(r"\b(\d{1,2})[-\s]+([a-zа-я]{3,12})\b", t)
    m_dm = re.search(r"\b(\d{1,2})[:\-/](\d{1,2})\b", t)

    if m_full:
        parsed_date = _safe_date(int(m_full.group(1)), int(m_full.group(2)), int(m_full.group(3)))
        t_time = t[:m_full.start()] + " " + t[m_full.end():]
    elif m_dmy:
        y = int(m_dmy.group(3))
        if y < 100:
            y += 2000
        parsed_date = _safe_date(y, int(m_dmy.group(2)), int(m_dmy.group(1)))
        t_time = t[:m_dmy.start()] + " " + t[m_dmy.end():]
    elif m_mon:
        mon_word = m_mon.group(2)
        mo = 0
        for name, num in month_names.items():
            if mon_word.startswith(name[:5]):
                mo = num
                break
        if mo:
            d = int(m_mon.group(1))
            cand = _safe_date(now.year, mo, d)
            if cand and cand < now.date() and day_offset == 0:
                cand = _safe_date(now.year + 1, mo, d)
            parsed_date = cand
            t_time = t[:m_mon.start()] + " " + t[m_mon.end():]
    if parsed_date is None and m_dm:
        a, b = int(m_dm.group(1)), int(m_dm.group(2))
        # O'zbekistonda sana kun.oy tartibida yoziladi (DD.MM): 05.09 → 5-sentyabr.
        # Faqat birinchi raqam haqiqiy oy bo'lolmasa (masalan 30.08) tartib almashtiriladi.
        d, mo = (a, b)
        if _safe_date(now.year, mo, d) is None and _safe_date(now.year, a, b) is not None:
            d, mo = b, a
        cand = _safe_date(now.year, mo, d)
        if cand:
            if cand < now.date() and day_offset == 0:
                cand = _safe_date(now.year + 1, mo, d)
            parsed_date = cand
            t_time = t[:m_dm.start()] + " " + t[m_dm.end():]

    # 4) Soat:daqiqa. Avval kun qismidagi so'zlar (ertalab/kechqurun...) —
    # ular "8 ga" kabi umumiy qoidadan oldin tekshiriladi.
    hour = None
    minute = 0
    hm = re.search(r"(\d{1,2})\s*[:hн]\s*(\d{2})\b", t_time)
    if hm:
        hour = int(hm.group(1))
        minute = int(hm.group(2))
    elif re.search(r"(ertalab|эрталаб|утром|tong|tongda)", t_time):
        mh = re.search(r"(\d{1,2})", t_time)
        if mh:
            hour = int(mh.group(1))
    elif re.search(r"(tushda|tush payt|tushlik|обед|в обед)", t_time):
        mh = re.search(r"(\d{1,2})", t_time)
        hour = int(mh.group(1)) if mh else 12
    elif re.search(r"(kechqurun|kechasi|kechki|вечером|ночью|окшом|oqshom)", t_time):
        mh = re.search(r"(\d{1,2})", t_time)
        if mh:
            hour = int(mh.group(1))
            if hour < 12:
                hour += 12  # "kechqurun 8" → 20:00
    else:
        # "8 ga", "20 da", "19:00 ga" kabi oddiy ko'rsatmalar
        standalone = re.search(r"\b(\d{1,2})(?:\s*:\s*(\d{2}))?\s*(ga|да|в|da)\b", t_time)
        if standalone:
            hour = int(standalone.group(1))
            if standalone.group(2):
                minute = int(standalone.group(2))
        else:
            # Yaxlit soat: "soat 20 ga" / "20:00"
            only_time = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", t_time)
            if only_time:
                hour = int(only_time.group(1))
                minute = int(only_time.group(2))

    if hour is None or not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    target_date = parsed_date or (now + timedelta(days=day_offset)).date()
    try:
        candidate = tz.localize(datetime(target_date.year, target_date.month, target_date.day, hour, minute))
    except ValueError:
        return None

    if candidate <= now:
        # Sana aniq berilmagan bo'lsa — keyingi kunga ko'chiramiz ("15:45 ga"
        # soat o'tib ketgan bo'lsa, ertaga 15:45 tushuniladi).
        if parsed_date is None:
            candidate += timedelta(days=1)
        if candidate <= now:
            return None
    return candidate
