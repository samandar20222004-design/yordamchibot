import html
import re
import threading
import time
from datetime import datetime, timedelta
import pytz
from config import ADMIN_IDS_SET
import database as db

tashkent_tz = pytz.timezone("Asia/Tashkent")


def is_user_ad_free(user_id: int) -> bool:
    """Reklamasiz rejim AVTOMATIK aniqlanadi (qo'lda yoqish/o'chirish yo'q).

    Qoida:
      * admin yoki PRO/Enterprise (``db.is_premium`` → True) → reklama UMUMAN
        qo'shilmaydi (100% toza) — kanal postlariga ham, bot javoblariga ham;
      * oddiy foydalanuvchi → False, ya'ni admin belgilagan reklama oralig'i
        (ad_pool) bo'yicha reklama ko'rsatiladi.
    DB xatosi bo'lsa xavfsiz tomon — reklamali (False) deb olinadi.
    """
    if user_id in ADMIN_IDS_SET:
        return True
    try:
        return bool(db.is_premium(user_id))
    except Exception:
        return False


async def is_user_ad_free_async(user_id: int) -> bool:
    """``is_user_ad_free`` ning async varianti — DB event loopdan tashqarida o'qiladi."""
    if user_id in ADMIN_IDS_SET:
        return True
    try:
        return bool(await db.run_db(db.is_premium, user_id))
    except Exception:
        return False


async def apply_post_watermark(text: str, user_id: int, bot_username: str) -> str:
    """Bepul foydalanuvchilar postlariga bot username'ini avtomatik qo'shadi.

    Qoidalar:
      - PRO foydalanuvchilar va adminlar uchun matn o'zgarmaydi.
      - Bepul foydalanuvchilar uchun matn boshiga @username qo'shiladi.
      - Agar matn allaqachon username bilan boshlangan bo'lsa, takrorlanmaydi.
    """
    from config import ADMIN_IDS_SET

    # Admin va PRO foydalanuvchilarga watermark qo'yilmaydi
    if user_id in ADMIN_IDS_SET:
        return text

    try:
        is_pro = await db.run_db(db.is_premium, user_id)
        if is_pro:
            return text
    except Exception:
        pass

    # Username'ni tozalash va formatlash
    clean_username = bot_username if bot_username.startswith("@") else f"@{bot_username}"

    # Bo'sh matn bo'lsa, faqat username qaytariladi
    if not text:
        return clean_username

    # Agar matn allaqachon username bilan boshlangan bo'lsa, o'zgartirilmaydi
    if not text.startswith(clean_username):
        return f"{clean_username}\n\n{text}"

    return text


_USER_HISTORY = {}
_USER_WARNED = {}
_USER_MSG_COUNT = {}
_AI_HISTORY = {}
_AI_DAILY = {}
_DUP_HISTORY = {}
_GLOBAL_FLOOD = []  # so'nggi 1 soniyadagi barcha update'lar vaqtlari

# --- Avtomatik reklama rotatsiya holati ---
# Har bir scope ('channel' / 'reply') uchun navbatdagi reklama indeksi.
# Bot postlar va javoblarga puldagi reklamalarni navbatma-navbat qo'shadi.
_AD_ROTATION_INDEX = {}
_AD_ROTATION_LOCK = threading.Lock()


def _next_ad_text(ads, scope: str) -> str:
    """Round-robin: puldagi keyingi reklama matnini qaytaradi (bo'sh bo'lsa '').

    ``ads`` — [(id, text), ...] ko'rinishidagi faol reklamalar. Scheduler
    thread'da, javoblar esa event loop'da ishlagani uchun thread-xavfsizlik
    Lock orqali ta'minlanadi.
    """
    if not ads:
        return ""
    with _AD_ROTATION_LOCK:
        idx = _AD_ROTATION_INDEX.get(scope, 0) % len(ads)
        _AD_ROTATION_INDEX[scope] = idx + 1
    return ads[idx][1]


def get_channel_ad_next() -> str:
    """Sinxron: kanal posti uchun navbatdagi reklama. Pul bo'sh bo'lsa eski
    ``channel_ad_text`` sozlamasiga (orqaga moslik) qaytadi."""
    ads = db.get_ads(db.AD_SCOPE_CHANNEL) or []
    if ads:
        return _next_ad_text(ads, db.AD_SCOPE_CHANNEL)
    return db.get_setting("channel_ad_text", "").strip()


async def get_channel_ad_next_async() -> str:
    """Async: kanal posti uchun navbatdagi reklama (DB thread'da o'qiladi)."""
    ads = (await db.run_db(db.get_ads, db.AD_SCOPE_CHANNEL)) or []
    if ads:
        return _next_ad_text(ads, db.AD_SCOPE_CHANNEL)
    return (await db.run_db(db.get_setting, "channel_ad_text", "")).strip()


# --- Reklama oralig'i (har N-postda) va to'liq reklama (matn + tugma) ---

EMPTY_AD = {"id": 0, "text": "", "button_text": "", "button_url": ""}


def should_show_channel_ad(post_count, interval) -> bool:
    """Kanalning ``post_count``-posti reklama posti bo'ladimi?

    Reklama har ``interval`` postda bir marta chiqadi: interval 3 bo'lsa
    3-, 6-, 9-... postlarda. Sanagich har bir kanal uchun ALOHIDA yuritilgani
    uchun kanallar bir-biriga ta'sir qilmaydi.
    """
    try:
        count = int(post_count)
        step = int(interval)
    except (TypeError, ValueError):
        return False
    if count <= 0 or step <= 0:
        return False
    return count % step == 0


def _next_ad_full(ads, scope: str) -> dict:
    """Round-robin: puldagi keyingi reklama (matn + inline tugma).

    ``ads`` — ``db.get_ads_full`` qaytargan dict ro'yxati.
    """
    if not ads:
        return dict(EMPTY_AD)
    with _AD_ROTATION_LOCK:
        idx = _AD_ROTATION_INDEX.get(scope, 0) % len(ads)
        _AD_ROTATION_INDEX[scope] = idx + 1
    ad = ads[idx] or {}
    return {
        "id": ad.get("id", 0),
        "text": (ad.get("text") or "").strip(),
        "button_text": (ad.get("button_text") or "").strip(),
        "button_url": (ad.get("button_url") or "").strip(),
    }


async def get_channel_ad_next_full_async() -> dict:
    """Kanal posti uchun navbatdagi to'liq reklama: matn + inline URL tugma.

    Pul bo'sh bo'lsa eski yagona ``channel_ad_text`` sozlamasiga qaytadi
    (u holda tugma bo'lmaydi).
    """
    ads = (await db.run_db(db.get_ads_full, db.AD_SCOPE_CHANNEL)) or []
    if ads:
        return _next_ad_full(ads, db.AD_SCOPE_CHANNEL)
    legacy = (await db.run_db(db.get_setting, "channel_ad_text", "") or "").strip()
    ad = dict(EMPTY_AD)
    ad["text"] = legacy
    return ad


# --- Reklama matni va inline tugmasini tekshirish (validatsiya) ---

# Reklamada ruxsat etilgan HTML teglar (Telegram Bot API qo'llaydiganlari).
AD_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "a", "code", "pre", "tg-spoiler", "blockquote", "span",
}
_TAG_RE = re.compile(r"<\s*(/?)\s*([a-zA-Z0-9-]+)([^>]*)>")
_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.IGNORECASE)


def validate_ad_html(text: str, max_len: int = 1024) -> tuple[bool, str]:
    """Reklama matnini Telegram HTML qoidalari bo'yicha tekshiradi.

    Qaytadi: ``(ok, xato_xabari)``. Tekshiriladi:
      • matn bo'sh emasligi va uzunlik chegarasi,
      • faqat ruxsat etilgan teglar (``b``, ``i``, ``a`` va h.k.),
      • teglar to'g'ri yopilgani (ochiq qolgan teg yo'q),
      • ``<a>`` tegida to'g'ri ``href`` borligi.
    """
    raw = (text or "").strip()
    if not raw:
        return False, "Reklama matni bo'sh bo'lishi mumkin emas."
    if len(raw) > max_len:
        return False, f"Reklama matni juda uzun (maksimal {max_len} belgi)."

    stack = []
    for match in _TAG_RE.finditer(raw):
        closing, name, attrs = match.group(1), match.group(2).lower(), match.group(3)
        if name not in AD_ALLOWED_TAGS:
            return False, (
                f"&lt;{html_escape(name)}&gt; tegi qo'llab-quvvatlanmaydi. "
                "Ruxsat etilgan teglar: b, i, u, s, a, code, pre, blockquote."
            )
        if closing:
            if not stack or stack[-1] != name:
                return False, f"&lt;/{html_escape(name)}&gt; tegi noto'g'ri yopilgan."
            stack.pop()
            continue
        if attrs.strip().endswith("/"):
            continue
        if name == "a":
            href = _HREF_RE.search(attrs or "")
            if not href or not href.group(1).strip():
                return False, "Havola tegida <code>href=\"...\"</code> ko'rsatilishi shart."
            ok, err = validate_button_url(href.group(1).strip())
            if not ok:
                return False, err
        stack.append(name)

    if stack:
        return False, f"&lt;{html_escape(stack[-1])}&gt; tegi yopilmagan."
    return True, ""


def validate_button_url(url: str) -> tuple[bool, str]:
    """Inline tugma havolasini tekshiradi. Qaytadi: ``(ok, xato_xabari)``."""
    value = (url or "").strip()
    if not value:
        return False, "Havola bo'sh bo'lishi mumkin emas."
    if len(value) > 2048:
        return False, "Havola juda uzun (maksimal 2048 belgi)."
    if " " in value:
        return False, "Havolada bo'sh joy bo'lishi mumkin emas."
    lowered = value.lower()
    allowed_prefixes = ("http://", "https://", "tg://")
    if not lowered.startswith(allowed_prefixes):
        return False, (
            "Havola <code>https://</code>, <code>http://</code> yoki "
            "<code>tg://</code> bilan boshlanishi kerak."
        )
    if lowered.startswith(("http://", "https://")):
        rest = value.split("//", 1)[1]
        host = rest.split("/", 1)[0]
        if not host or "." not in host:
            return False, "Havola domeni noto'g'ri (masalan: https://t.me/kanal)."
    return True, ""


def validate_button_text(text: str) -> tuple[bool, str]:
    """Inline tugma matnini tekshiradi. Qaytadi: ``(ok, xato_xabari)``."""
    value = (text or "").strip()
    if not value:
        return False, "Tugma matni bo'sh bo'lishi mumkin emas."
    if len(value) > 64:
        return False, "Tugma matni juda uzun (maksimal 64 belgi)."
    return True, ""


def parse_button_input(text: str) -> tuple[str, str]:
    """``Tugma matni | https://havola`` ko'rinishidagi kiritmani ajratadi.

    Ajratgich sifatida ``|`` yoki ``-`` ishlatilishi mumkin; topilmasa
    ``("", "")`` qaytadi.
    """
    raw = (text or "").strip()
    if not raw:
        return "", ""
    for sep in ("|", " - ", "—"):
        if sep in raw:
            left, _, right = raw.partition(sep)
            return left.strip(), right.strip()
    return "", ""

# Hujum / ortiqcha yuklama himoyasi chegaralari
GLOBAL_MAX_UPDATES_PER_SEC = 60     # butun bot bo'yicha 1 soniyada 60 tadan ortiq update
USER_MAX_UPDATES_PER_2SEC = 20      # bitta foydalanuvchi 2 soniyada 20 tadan ortiq
DUP_WINDOW_SECONDS = 1.5            # bir xil xabar shu vaqt ichida qayta yuborilsa — tashlab yuboriladi
AI_MAX_PER_MINUTE = 4               # AI: daqiqasiga 4 ta
AI_MAX_PER_DAY = 30                 # AI: kuniga 30 ta (bepul limitlarni tejash)

# Qatlamli rate-limit konstantalari (2 soniyalik oyna bo'yicha)
NAV_RATE_LIMIT_MAX = 20             # 20 req/2s: Kabinet, AI Studio, Premium, Asosiy menyu navigatsiyasi
ENTRY_RATE_LIMIT_MAX = 12           # 12 req/2s: Yangi oqimlarga kirish (entry points)
REACTION_RATE_LIMIT_MAX = 10        # 10 req/2s: Reaksiya bosishlar (reaction taps)


def parse_reactions_input(text: str) -> bool | None:
    """Post reaksiyalari bo'yicha kiritilgan matn/emojini moslashuvchan tahlil qiladi.

    Qo'llab-quvvatlanadi:
      • Alohida emojilar: '👍', '❤️' (\ufe0f bilan/siz), '🔥', '👏' va boshqa emojilar
      • Emoji kombinatsiyalari: '👍 ❤️ 🔥 👏', '👍❤️🔥👏', '👍, ❤️'
      • Matnli tasdiqlash: 'ha', 'yoqish', 'reaksiya', 'reaksiyalar', 'yes'
      • Reaksiyasiz / o'chirish: '➡️ Reaksiyasiz davom etish', 'yo'q', 'yoq', 'o'chirish', 'no', '-'
      • Noto'g'ri / begona matn: None (foydalanuvchiga qayta taklif)
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    # Variation selector va ko'rinmas belgilarni tozalash (\ufe0f = VS16, \ufe0e = VS15)
    cleaned = raw.replace("\ufe0f", "").replace("\ufe0e", "").strip()
    lower = cleaned.lower()

    # 1) Reaksiyasiz / o'chirish variantlari -> False
    no_react_keywords = {
        "➡️ reaksiyasiz davom etish",
        "reaksiyasiz davom etish",
        "reaksiyasiz",
        "reaksiya kerakmas",
        "reaksiyasiz bo'lsin",
        "yo'q",
        "yoq",
        "yo'qsin",
        "kerakmas",
        "kerak emas",
        "o'chirish",
        "o'chir",
        "ochirish",
        "ochir",
        "no",
        "none",
        "off",
        "disable",
        "-",
        "0",
        "skip",
    }
    if lower in no_react_keywords or lower.startswith("➡️ reaksiyasiz") or "reaksiyasiz" in lower:
        return False

    # 2) Aniq matnli tasdiqlash variantlari -> True
    yes_react_keywords = {
        "ha",
        "ha albatta",
        "ha, albatta",
        "ha bo'lsin",
        "reaksiya",
        "reaksiyalar",
        "reaksiyali",
        "reaksiyalar bilan",
        "yoqish",
        "yoqilsin",
        "yes",
        "on",
        "enable",
        "1",
        "albatta",
        "mayli",
    }
    if lower in yes_react_keywords:
        return True

    # 3) Emojilar va emoji kombinatsiyalari (yakka yoki guruh)
    import unicodedata
    emoji_stripped = re.sub(r"[\s,|+/.\-_]+", "", cleaned)
    if emoji_stripped:
        is_all_emoji = True
        for ch in emoji_stripped:
            cat = unicodedata.category(ch)
            if cat not in ("So", "Sm", "Sk", "Mn", "Mc", "Me", "Cf", "No"):
                is_all_emoji = False
                break
        if is_all_emoji:
            return True

    return None


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

# --- Auto-Ad Injector (Har 3-5 ta so'rovda reklama) ---
_USER_INTERACTION_COUNT = {}
_USER_INTERACTION_LOCK = threading.Lock()


def get_user_interaction_count(user_id: int) -> int:
    with _USER_INTERACTION_LOCK:
        return _USER_INTERACTION_COUNT.get(user_id, 0)


def reset_user_interaction_count(user_id: int):
    with _USER_INTERACTION_LOCK:
        _USER_INTERACTION_COUNT.pop(user_id, None)


async def get_auto_ad_injection_async(user_id: int) -> str:
    """Har 3-5 ta so'rovda bot javobiga avtomatik reklama qo'shish (async).

    Qoidalar:
      1. Adminlarga va PRO foydalanuvchilarga reklama ko'rsatilmaydi.
      2. auto_ad_status FALSE bo'lsa yoki matn bo'sh bo'lsa reklama chiqmaydi.
      3. Foydalanuvchi hisoblagichi har N (interval, standart 4) marta yetganda reklama qo'shiladi.
    """
    if user_id in ADMIN_IDS_SET:
        return ""
    try:
        is_pro = await db.run_db(db.is_premium, user_id)
        if is_pro:
            return ""
    except Exception:
        pass

    try:
        settings = await db.run_db(db.get_ad_settings)
    except Exception:
        return ""

    if not settings.get("auto_ad_status"):
        return ""

    ad_text = (settings.get("auto_ad_text") or "").strip()
    if not ad_text:
        return ""

    interval = max(1, int(settings.get("auto_ad_interval", 4)))

    with _USER_INTERACTION_LOCK:
        count = _USER_INTERACTION_COUNT.get(user_id, 0) + 1
        _USER_INTERACTION_COUNT[user_id] = count
        if len(_USER_INTERACTION_COUNT) > 25000:
            _USER_INTERACTION_COUNT.clear()
            _USER_INTERACTION_COUNT[user_id] = count

    if count % interval == 0:
        return f"\n\n📢 <b>Homiy:</b> {html_escape(ad_text)}"
    return ""


def get_auto_ad_injection(user_id: int) -> str:
    """Sinxron variant (testlar va skriptlar uchun)."""
    if user_id in ADMIN_IDS_SET:
        return ""
    try:
        if db.is_premium(user_id):
            return ""
    except Exception:
        pass
    try:
        settings = db.get_ad_settings()
    except Exception:
        return ""

    if not settings.get("auto_ad_status"):
        return ""

    ad_text = (settings.get("auto_ad_text") or "").strip()
    if not ad_text:
        return ""

    interval = max(1, int(settings.get("auto_ad_interval", 4)))

    with _USER_INTERACTION_LOCK:
        count = _USER_INTERACTION_COUNT.get(user_id, 0) + 1
        _USER_INTERACTION_COUNT[user_id] = count
        if len(_USER_INTERACTION_COUNT) > 25000:
            _USER_INTERACTION_COUNT.clear()
            _USER_INTERACTION_COUNT[user_id] = count

    if count % interval == 0:
        return f"\n\n📢 <b>Homiy:</b> {html_escape(ad_text)}"
    return ""


async def inject_auto_ad_async(user_id: int, base_text: str) -> str:
    """Matn oxiriga avtomatik reklamani qo'shib beradi."""
    ad = await get_auto_ad_injection_async(user_id)
    return f"{base_text}{ad}" if ad else base_text


def inject_auto_ad(user_id: int, base_text: str) -> str:
    ad = get_auto_ad_injection(user_id)
    return f"{base_text}{ad}" if ad else base_text


async def check_user_sponsorship(bot, user_id: int):
    """Foydalanuvchining majburiy homiy kanallarga obunasini tekshiradi."""
    from handlers.start import check_user_subscribed
    return await check_user_subscribed(bot, user_id)


def ad_link_suffix(ad) -> str:
    """Reklamaning inline tugmasini HTML havola ko'rinishida qaytaradi.

    Bot javoblariga inline klaviatura biriktirilmaydi, shuning uchun tugma
    matn ichida havola sifatida ko'rsatiladi.
    """
    if not isinstance(ad, dict):
        return ""
    btn_text = (ad.get("button_text") or "").strip()
    btn_url = (ad.get("button_url") or "").strip()
    if not btn_text or not btn_url:
        return ""
    return f' <a href="{html_escape(btn_url)}">{html_escape(btn_text)}</a>'


def get_smart_reply_ad(user_id: int) -> str:
    """Sinxron variant (test/skript uchun). Handlerlarda
    ``get_smart_reply_ad_async`` ishlatiladi — u DB'ni event loopdan tashqarida
    o'qiydi. Rotatsiya pulidan navbatdagi reklamani oladi.
    PRO va adminlarga reklama chiqmaydi."""
    if user_id in ADMIN_IDS_SET:
        return ""
    try:
        if db.is_premium(user_id):
            return ""
    except Exception:
        pass
    ads = db.get_ads_full(db.AD_SCOPE_REPLY) or []
    if ads:
        ad = _next_ad_full(ads, db.AD_SCOPE_REPLY)
        return _format_reply_ad(user_id, ad["text"], ad_link_suffix(ad))
    # Orqaga moslik: eski bitta reklama sozlamasi.
    ad_text = db.get_setting("bot_reply_ad_text", "").strip()
    return _format_reply_ad(user_id, ad_text)


async def get_smart_reply_ad_async(user_id: int) -> str:
    """Reklama satri; DB o'qish alohida thread'da (event loop bloklanmaydi).
    Rotatsiya pulidan navbatdagi reklamani oladi; pul bo'sh bo'lsa eski
    ``bot_reply_ad_text`` sozlamasiga qaytadi.

    PRO va adminlar uchun HECH QACHON reklama qaytarilmaydi (avtomatik
    reklamasiz rejim)."""
    if user_id in ADMIN_IDS_SET:
        return ""
    try:
        if await db.run_db(db.is_premium, user_id):
            return ""
    except Exception:
        pass
    ads = (await db.run_db(db.get_ads_full, db.AD_SCOPE_REPLY)) or []
    if ads:
        ad = _next_ad_full(ads, db.AD_SCOPE_REPLY)
        return _format_reply_ad(user_id, ad["text"], ad_link_suffix(ad))
    ad_text = (await db.run_db(db.get_setting, "bot_reply_ad_text", "")).strip()
    return _format_reply_ad(user_id, ad_text)


def _format_reply_ad(user_id: int, ad_text: str, link_suffix: str = "") -> str:
    if not ad_text:
        return ""

    count = _USER_MSG_COUNT.get(user_id, 0) + 1
    _USER_MSG_COUNT[user_id] = count

    # Xotira o'sishini cheklash: 10 000 dan oshsa eski yozuvlarni tozalaymiz
    if len(_USER_MSG_COUNT) > 10000:
        _USER_MSG_COUNT.clear()

    if count % 3 == 0:
        return f"\n\n🏷 <i>({html_escape(ad_text)})</i>{link_suffix}"
    return ""

def html_escape(text) -> str:
    if not text:
        return ""
    return html.escape(str(text))


# Telegram qo'llab-quvvatlaydigan HTML teglar
_TELEGRAM_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
                  "code", "pre", "a", "tg-spoiler", "blockquote", "tg-emoji"}


def safe_html(text: str) -> str:
    """AI yoki tashqi matnni Telegram HTML uchun xavfsiz formatlaydi.

    - Faqat Telegram qo'llab-quvvatlaydigan teglar saqlanadi
    - Noto'g'ri yopilmagan teglar avtomatik yopiladi
    - Boshqa barcha HTML teglar olib tashlanadi
    - '&' belgisi teglar ichida escape qilinmaydi (Telegram API talabi)
    """
    if not text:
        return ""
    text = str(text)

    # Noto'g'ri teglarni tozalash: ruxs etilmagan teglarni olib tashlash
    import re as _re

    # Yopilgan teglarni tekshirish va tuzatish
    open_tags = []
    result = []
    i = 0
    while i < len(text):
        if text[i] == '<':
            # Tegni topish
            end = text.find('>', i)
            if end == -1:
                # Yopilmagan < — escape qilamiz
                result.append('&lt;')
                i += 1
                continue

            tag_content = text[i+1:end].strip()

            # Self-closing yoki closing teg
            if tag_content.startswith('/'):
                tag_name = tag_content[1:].split()[0].lower().rstrip('/')
                if tag_name in _TELEGRAM_TAGS and tag_name in open_tags:
                    # To'g'ri yopilgan teg
                    while open_tags and open_tags[-1] != tag_name:
                        # Oraliq teglarni avtomatik yopamiz
                        result.append(f'</{open_tags.pop()}>')
                    if open_tags:
                        open_tags.pop()
                    result.append(f'</{tag_name}>')
                # Noto'g'ri yoki ortiqcha yopilgan teg — o'tkazib yuboramiz
                i = end + 1
                continue

            # Ochiq teg
            tag_name = tag_content.split()[0].lower().rstrip('/')
            if tag_name in _TELEGRAM_TAGS:
                # Tegni saqlaymiz
                attrs = tag_content[len(tag_name):].strip()
                if attrs.endswith('/'):
                    # Self-closing
                    result.append(f'<{tag_name}{attrs}')
                else:
                    result.append(f'<{tag_name}{attrs}>')
                    open_tags.append(tag_name)
            # Ruxs etilmagan teg — o'tkazib yuboramiz (matnini saqlaymiz)
            i = end + 1
            continue

        result.append(text[i])
        i += 1

    # Ochiq qolgan teglarni yopamiz
    while open_tags:
        result.append(f'</{open_tags.pop()}>')

    return ''.join(result)

def format_post_type_label(post_type: str, lang: str = "uz") -> str:
    """Post turi yorlig'i — foydalanuvchi tilida (uz/ru).

    ``lang`` berilmasa o'zbekcha (eski chaqiruvlar uchun moslik).
    """
    from locales.translations import get_text, normalize_lang
    lang = normalize_lang(lang)
    pt = str(post_type).lower()
    mapping = {
        "photo": "np_type_photo", "video": "np_type_video",
        "animation": "np_type_animation", "document": "np_type_document",
        "audio": "np_type_audio", "voice": "np_type_voice",
        "sticker": "np_type_sticker", "text": "np_type_text",
        "album": "np_type_album",
    }
    key = mapping.get(pt, "np_type_unknown")
    # "🖼 Rasm" → "Rasm"; "🎬 Video" → "Video"; emoji qismi olib tashlanadi.
    return get_text(key, lang).split(" ", 1)[-1] if " " in get_text(key, lang) else get_text(key, lang)

def format_schedule_line(s_time, recurrence_type, recurrence_day, recurrence_time, lang: str = "uz"):
    """Post chiqish vaqtini foydalanuvchi tilida (uz/ru) formatlaydi."""
    from locales.translations import get_text, normalize_lang
    from keyboards.default import WEEKDAY_LABELS, WEEKDAY_LABELS_RU
    lang = normalize_lang(lang)
    if recurrence_type == 'daily':
        time_str = recurrence_time.strftime("%H:%M") if hasattr(recurrence_time, 'strftime') else str(recurrence_time)[:5]
        return get_text("pend_schedule_daily", lang, time=time_str)
    elif recurrence_type == 'weekly':
        labels = WEEKDAY_LABELS_RU if lang == "ru" else WEEKDAY_LABELS
        day_label = labels.get(recurrence_day, "?")
        time_str = recurrence_time.strftime("%H:%M") if hasattr(recurrence_time, 'strftime') else str(recurrence_time)[:5]
        return get_text("pend_schedule_weekly", lang, day=day_label, time=time_str)

    if s_time:
        if s_time.tzinfo is None:
            s_time = pytz.utc.localize(s_time).astimezone(tashkent_tz)
        else:
            s_time = s_time.astimezone(tashkent_tz)
        return get_text("pend_schedule_once", lang, time=s_time.strftime("%Y-%m-%d %H:%M"))
    return get_text("pend_schedule_unknown", lang)


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
