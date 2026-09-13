"""🆕 Onboarding — yangi foydalanuvchilar uchun SODDA klaviatura mantiqi.

Nima uchun kerak
----------------
Standart bosh menyu 6 ta tugmadan iborat (UX V2: ✨ Kontent yaratish,
📢 Kanallarim, 📅 Rejalashtirilgan, 📊 Statistika, 💎 PRO, ⚙️ Sozlamalar).
Birinchi 1-3 kun ichida foydalanuvchi uchun bu ko'p — u "nima qilishim
kerak?" degan savolga javob olmaydi. Shu sababli yangi foydalanuvchiga
faqat 3 ta katta, harakatga undovchi tugma ko'rsatiladi:

    [🚀 1 daqiqada post yaratish]   — AI orqali post yozish
    [🖼 Rasmdan post olish]         — Vision (rasm → post) oqimi
    [📢 Kanal ulash]                — kanal/guruh ulash
    [⚙️ To'liq menyuni ochish]      — istalgan paytda to'liq menyuga o'tish

Qoida (talab bo'yicha)
----------------------
Sodda menyu ko'rsatiladi, agar:
  * foydalanuvchi ro'yxatdan o'tganiga **3 kundan kam** bo'lsa
    (``users.created_at``) **YOKI**
  * u hali **3 ta post chiqarmagan** bo'lsa
    (``scheduled_posts.status = 'posted'``),
  * VA u "⚙️ To'liq menyuni ochish" tugmasini bosmagan bo'lsa
    (``users.full_menu_unlocked``),
  * VA ro'yxatdan o'tganiga 3 kundan OSHMAGAN bo'lsa (qat'iy chegarа —
    3 kundan keyin standart menyu avtomatik qaytadi).

Ushbu modul **sof mantiq** (pure logic): DB, Telegram yoki AI'ga bog'liq
EMAS — shuning uchun unit-testlar bazasiz to'liq qamrab oladi. Ma'lumotni
bazadan olish ``database.get_user_onboarding`` vazifasi.
"""

import logging
import threading
import time
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)

# Butun bot uchun yagona vaqt zonasi (scheduler.TIMEZONE_NAME bilan bir xil).
# Bu yerda ataylab alohida e'lon qilinadi: modul hech qanday lokal modulni
# import qilmaydi — aks holda keyboards.default → onboarding → scheduler →
# keyboards.inline kabi aylanma (circular) import xavfi tug'ilardi.
TIMEZONE_NAME = "Asia/Tashkent"
tashkent_tz = pytz.timezone(TIMEZONE_NAME)

# --- Talab chegaralari ------------------------------------------------------
#: Ro'yxatdan o'tganiga shu sondan KAM kun bo'lsa — foydalanuvchi "yangi".
NEW_USER_WINDOW_DAYS = 3
#: Shu sondan kam post chiqargan bo'lsa — sodda menyu saqlanadi.
NEW_USER_POSTS_THRESHOLD = 3

#: ``context.user_data`` ichidagi belgi (eslatma: ``clear_fsm_data`` uni
#: har menyu bosilishida tozalaydi — shuning uchun asosiy kesh pastdagi
#: ``_SIMPLE_MENU_CACHE``).
SIMPLE_MENU_KEY = "simple_menu"

# --- Qisqa muddatli kesh ----------------------------------------------------
# Har /start, ❌ Bekor qilish yoki "orqaga" bosilishida bazaga so'rov
# yubormaslik uchun qaror bir necha daqiqa eslab qolinadi. Neon'ga ortiqcha
# yuklama tushmaydi, foydalanuvchi esa bir xil menyuni ko'radi.
SIMPLE_MENU_CACHE_TTL = 300.0
_SIMPLE_MENU_CACHE: dict = {}
_SIMPLE_MENU_CACHE_LOCK = threading.Lock()
SIMPLE_MENU_CACHE_MAX = 50000


def now_tashkent() -> datetime:
    """Hozirgi vaqt Toshkent zonasida (aware datetime)."""
    return datetime.now(tashkent_tz)


def as_tashkent(value):
    """DB'dan kelgan sana/vaqtni Toshkent zonasiga o'tkazadi.

    ``users.created_at`` — ``TIMESTAMP`` (timezone'siz) ustun; PostgreSQL
    ``CURRENT_TIMESTAMP`` ni sessiya vaqt zonasida yozadi (Neon/Render'da
    amalda UTC). Shu sababli timezone'siz qiymat **UTC** deb qabul qilinadi.
    3 kunlik oynada 5 soatlik siljish xatoga olib kelmaydi.

    Qaytadi: aware ``datetime`` (Toshkent) yoki ``None`` (aniqlab bo'lmasa).
    """
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            # "2026-09-01 12:30:45" / ISO-8601 (T belgisi bilan ham)
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        value = parsed
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = pytz.utc.localize(value)
    return value.astimezone(tashkent_tz)


def days_since_registration(created_at, now=None):
    """Ro'yxatdan o'tganiga necha kun bo'ldi (butun kun, pastga yaxlitlangan).

    Qaytadi: ``int`` (>= 0) yoki ``None`` — ``created_at`` aniqlanmasa.
    """
    moment = as_tashkent(created_at)
    if moment is None:
        return None
    reference = now if now is not None else now_tashkent()
    reference = as_tashkent(reference) or now_tashkent()
    delta = reference - moment
    if delta < timedelta(0):
        # Kelajakdagi sana (soat siljishi / qo'lda kiritilgan yozuv) —
        # foydalanuvchini "eski" deb hisoblab qo'ymaymiz.
        return 0
    return int(delta.total_seconds() // 86400)


def is_new_by_days(created_at, now=None) -> bool:
    """Ro'yxatdan o'tganiga ``NEW_USER_WINDOW_DAYS`` dan kam kun bo'ldimi?"""
    days = days_since_registration(created_at, now)
    if days is None:
        return False
    return days < NEW_USER_WINDOW_DAYS


def has_few_posts(posts_published) -> bool:
    """Foydalanuvchi hali ``NEW_USER_POSTS_THRESHOLD`` ta post chiqarmaganmi?"""
    try:
        count = int(posts_published or 0)
    except (TypeError, ValueError):
        return True
    return count < NEW_USER_POSTS_THRESHOLD


def should_show_simple_menu(created_at=None, posts_published=0,
                            full_menu_unlocked=False, now=None) -> bool:
    """Sodda (3 tugmali) klaviatura ko'rsatilishi kerakmi?

    Qoida (yuqoridagi modul hujjatida batafsil):
      1. ``full_menu_unlocked`` — foydalanuvchi "To'liq menyuni ochish"ni
         bosgan → HAR DOIM to'liq menyu.
      2. Ro'yxatdan o'tganiga ``NEW_USER_WINDOW_DAYS`` dan oshgan → to'liq
         menyu (qat'iy chegarа; talabning 2-bandini bajaradi).
      3. Aks holda: kun < 3 YOKI postlar soni < 3 → sodda menyu.
      4. ``created_at`` umuman yo'q bo'lsa (eski hisob / test) — faqat postlar
         soni bo'yicha hal qilinadi.
    """
    if full_menu_unlocked:
        return False

    days = days_since_registration(created_at, now)
    if days is None:
        return has_few_posts(posts_published)
    if days > NEW_USER_WINDOW_DAYS:
        return False
    return days < NEW_USER_WINDOW_DAYS or has_few_posts(posts_published)


def simple_menu_reason(created_at=None, posts_published=0,
                       full_menu_unlocked=False, now=None):
    """Nima uchun sodda/to'liq menyu tanlanganini qisqa kod bilan qaytaradi.

    Log/analytics uchun: ``"unlocked"`` | ``"expired"`` | ``"new_days"`` |
    ``"few_posts"`` | ``"unknown"`` (created_at yo'q, postlar yetarli).
    """
    if full_menu_unlocked:
        return "unlocked"
    days = days_since_registration(created_at, now)
    if days is None:
        return "few_posts" if has_few_posts(posts_published) else "unknown"
    if days > NEW_USER_WINDOW_DAYS:
        return "expired"
    if days < NEW_USER_WINDOW_DAYS:
        return "new_days"
    return "few_posts" if has_few_posts(posts_published) else "unknown"


def decide_menu_mode(onboarding: dict, now=None) -> str:
    """``database.get_user_onboarding`` natijasidan menyu rejimini aniqlaydi.

    Qaytadi: ``"simple"`` | ``"full"``. ``onboarding`` bo'sh/None bo'lsa
    (foydalanuvchi topilmadi yoki DB xatosi) — **xavfsiz tomon**: ``"full"``.
    Bu muhim: ma'lumot bo'lmasa foydalanuvchini hech qachon cheklamaymiz.
    """
    if not onboarding:
        return "full"
    simple = should_show_simple_menu(
        created_at=onboarding.get("created_at"),
        posts_published=onboarding.get("posts_published", 0),
        full_menu_unlocked=bool(onboarding.get("full_menu_unlocked")),
        now=now,
    )
    return "simple" if simple else "full"


# ---------------------------------------------------------------------------
# Qisqa muddatli kesh (thread-safe)
# ---------------------------------------------------------------------------

def cache_simple_menu(user_id, simple: bool) -> None:
    """Qarorni keshga yozadi (TTL: ``SIMPLE_MENU_CACHE_TTL``)."""
    if not user_id:
        return
    now = time.time()
    with _SIMPLE_MENU_CACHE_LOCK:
        if len(_SIMPLE_MENU_CACHE) > SIMPLE_MENU_CACHE_MAX:
            _SIMPLE_MENU_CACHE.clear()
        _SIMPLE_MENU_CACHE[int(user_id)] = (now, bool(simple))


def get_cached_simple_menu(user_id):
    """Keshdagi qarorni qaytaradi: ``True``/``False`` yoki ``None`` (yo'q/eskirgan)."""
    if not user_id:
        return None
    with _SIMPLE_MENU_CACHE_LOCK:
        entry = _SIMPLE_MENU_CACHE.get(int(user_id))
    if not entry:
        return None
    stamp, simple = entry
    if time.time() - stamp > SIMPLE_MENU_CACHE_TTL:
        return None
    return bool(simple)


def invalidate_simple_menu(user_id=None) -> None:
    """Keshni tozalaydi: ``user_id`` berilsa faqat shu foydalanuvchi, aks holda hammasi."""
    with _SIMPLE_MENU_CACHE_LOCK:
        if user_id is None:
            _SIMPLE_MENU_CACHE.clear()
        else:
            _SIMPLE_MENU_CACHE.pop(int(user_id), None)


def cache_size() -> int:
    """Keshdagi yozuvlar soni (testlar uchun)."""
    with _SIMPLE_MENU_CACHE_LOCK:
        return len(_SIMPLE_MENU_CACHE)
