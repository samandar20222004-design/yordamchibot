"""Public Telegram Channel Post Reader — ochiq kanallardan post o'qish.

https://t.me/s/<channel_username> sahifasini parse qilib, eng so'nggi postlarni
oladi. Faqat OCHIQ kanallar uchun ishlaydi — bot kanalda admin BO'LMASA ham
ochiq kanalning public postlarini web-preview orqali o'qiy oladi.

Imkoniyatlar:
  * ``extract_channel_username`` — ``@kanal``, ``kanal``, ``https://t.me/kanal``,
    ``https://t.me/s/kanal``, ``https://t.me/kanal/123`` kabi har qanday
    formatdan toza username ajratib oladi;
  * ``read_channel_posts`` — avval DB (bot admin bo'lgan kanallar tarixi),
    keyin t.me/s/ web-preview scraping; natija holati (ok/private/not_found/
    empty/invalid/error) bilan qaytadi;
  * ``read_webpage_for_ai`` — oddiy sayt havolasi (masalan https://kun.uz/)
    uchun <title>, <meta name="description"> va asosiy matnni (1000 belgigacha)
    AI tahlili uchun tayyorlaydi.
"""
import html as _html
import logging
import re
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

# --- HTTP sozlamalari ---
_CHANNEL_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=8)
_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 (compatible; PostAssistBot/2.0)"
    ),
    "Accept-Language": "uz,ru,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
# Juda katta sahifalarni cheklash (2 MB)
_MAX_HTML_BYTES = 2_000_000

# Kanal o'qish natija holatlari
STATUS_OK = "ok"                # postlar muvaffaqiyatli o'qildi
STATUS_PRIVATE = "private"      # kanal yopiq (private) yoki web-preview yo'q
STATUS_NOT_FOUND = "not_found"  # bunday kanal topilmadi
STATUS_EMPTY = "empty"          # kanal bor, lekin postlar yo'q
STATUS_INVALID = "invalid"      # kiritilgan manba noto'g'ri
STATUS_ERROR = "error"          # tarmoq/server xatosi

# Telegram manzillarini ajratish: t.me / telegram.me / telegram.dog
_TELEGRAM_HOSTS = r"(?:t\.me|telegram\.me|telegram\.dog)"

# https://t.me/kanal, t.me/s/kanal, https://t.me/kanal/123, @kanal, kanal
_TME_CHANNEL_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?" + _TELEGRAM_HOSTS +
    r"/(?:s/)?(?P<username>[A-Za-z][A-Za-z0-9_]{2,31})(?:/\d+)?/?",
    re.IGNORECASE,
)

# Yopiq kanal taklif havolalari: t.me/joinchat/xxx, t.me/+xxx, t.me/c/123456/7
_PRIVATE_INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?" + _TELEGRAM_HOSTS +
    r"/(?:(?:joinchat/|\+)[A-Za-z0-9_\-]+|c/\d+(?:/\d+)?)",
    re.IGNORECASE,
)

# Protokolsiz domain ko'rinishi: kun.uz, www.kun.uz, example.com/sahifa
_BARE_DOMAIN_RE = re.compile(
    r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,24}(?:/\S*)?",
    re.IGNORECASE,
)

# Telegram username qoidalari (ixcham — new_post.py bilan bir xil)
_USERNAME_FULL_RE = re.compile(r"[A-Za-z0-9_]{3,32}")

# --- t.me/s/ sahifasi HTML strukturasi ---

# Real (2024+) format: <div class="tgme_widget_message_wrap js-widget_message" ...>
_MESSAGE_WRAP_RE = re.compile(r'<div[^>]*class="tgme_widget_message_wrap')
# Eski format: <div class="tgme_widget_message " ...> (test-mocklar uchun zaxira)
_MESSAGE_OLD_RE = re.compile(r'<div[^>]*class="tgme_widget_message(?![A-Za-z0-9_])')
# data-post="kanal/123" — post havolasi va ID si uchun eng ishonchli manba
_DATA_POST_RE = re.compile(r'data-post="([^"/\s]+)/(\d+)"')
_DATA_POST_ATTR_RE = re.compile(r'data-post="[^"]*"')

_TEXT_RE = re.compile(
    r'<div[^>]*class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_DATE_RE = re.compile(
    r'<time[^>]*datetime="([^"]+)"',
)
_LINK_RE = re.compile(
    r'<a[^>]*class="tgme_widget_message_date[^"]*"[^>]*href="([^"]+)"',
)
_LINK_RE_ALT = re.compile(
    r'<a[^>]*href="([^"]+)"[^>]*class="tgme_widget_message_date[^"]*"',
)
_IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
# Background-image dan rasm/video URL: url('...'), url("..."), url(...)
_BG_IMAGE_RE = re.compile(
    r"background-image:\s*url\(['\"]?([^'\")]+)['\"]?\)",
    re.IGNORECASE,
)
_VIEWS_RE = re.compile(
    r'<span[^>]*class="[^"]*tgme_widget_message_views[^"]*"[^>]*>\s*([^<]+?)\s*</span>',
    re.IGNORECASE,
)

# --- Veb-sahifa uchun ---
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Meta description — qiymat ichida apostrof (O'zbekiston) bo'lsa ham to'g'ri
# o'qish uchun ochilgan va yopilgan qo'shtirnoq orqa havola (backreference) bilan.
_META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=(["\'])(?:description|og:description)\1'
    r'[^>]*content=(["\'])(.*?)\2',
    re.IGNORECASE | re.DOTALL,
)
_META_DESC_RE_ALT = re.compile(
    r'<meta[^>]+content=(["\'])(.*?)\1'
    r'[^>]*(?:name|property)=(["\'])(?:description|og:description)\3',
    re.IGNORECASE | re.DOTALL,
)


# ============================================================
# Manba turini aniqlash (username / private invite / sayt)
# ============================================================

def is_private_invite(raw) -> bool:
    """Yopiq kanal taklif havolasi (t.me/joinchat/..., t.me/+..., t.me/c/...)."""
    if raw is None:
        return False
    return bool(_PRIVATE_INVITE_RE.search(str(raw).strip()))


def extract_channel_username(raw):
    """Har qanday formatdagi kanal manzilidan toza username qaytaradi.

    Qabul qiladi: ``@kunuzofficial``, ``kunuzofficial``,
    ``https://t.me/kunuzofficial``, ``http://t.me/s/kunuzofficial``,
    ``https://t.me/kunuzofficial/173897``, ``https://telegram.me/kanal``.

    Returns:
        str: toza username yoki None (yopiq havola / noto'g'ri manba).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None

    # Yopiq taklif havolalari — username yo'q
    if is_private_invite(text):
        return None

    match = _TME_CHANNEL_LINK_RE.fullmatch(text)
    if match:
        return match.group("username")

    # @kanal yoki oddiy kanal nomi
    candidate = text.lstrip("@").strip().strip("/")
    if _USERNAME_FULL_RE.fullmatch(candidate):
        return candidate
    return None


def is_website_link(raw) -> bool:
    """Telegram havolasi BO'LMAGAN veb-sayt manzili (masalan https://kun.uz/)."""
    if raw is None:
        return False
    text = str(raw).strip()
    if not text or " " in text:
        return False
    # Telegram havolalari — sayt emas
    if is_private_invite(text) or _TME_CHANNEL_LINK_RE.fullmatch(text):
        return False
    lowered = text.lower()
    if lowered.startswith(("http://", "https://")):
        host = lowered.split("://", 1)[1].split("/", 1)[0]
        telegram_hosts = {
            "t.me", "www.t.me", "telegram.me", "www.telegram.me",
            "telegram.dog", "www.telegram.dog",
        }
        return host not in telegram_hosts
    # "kun.uz" / "www.kun.uz" / "example.com/sahifa" ko'rinishidagi domain
    return bool(_BARE_DOMAIN_RE.fullmatch(text))


# ============================================================
# HTML yordamchilari
# ============================================================

def _strip_html_tags(text: str) -> str:
    """HTML teglarini olib tashlaydi, matnni toza qaytaradi."""
    if not text:
        return ""
    # <br> va <br/> ni yangi qatorga almashtirish
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    # Boshqa barcha teglarni olib tashlash
    text = re.sub(r"<[^>]+>", "", text)
    # HTML entity larni decode qilish (&amp; &lt; &#39; va h.k.)
    text = _html.unescape(text)
    # Ortiqcha bo'sh joylarni tozalash
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_views(raw) -> int:
    """Telegram ko'rishlar sonini ("238K", "1.2M", "999") butun songa aylantiradi."""
    if not raw:
        return 0
    match = re.fullmatch(r"([\d.,]+)\s*([KkMm]?)", str(raw).strip())
    if not match:
        return 0
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return 0
    multiplier = {"k": 1_000, "m": 1_000_000}.get(match.group(2).lower(), 1)
    return int(number * multiplier)


def _extract_media_url(block: str) -> str:
    """Post blokidagi rasm/video URL ni topadi (attribute tartibidan qat'i nazar)."""
    for img_tag in _IMG_TAG_RE.findall(block):
        if "tgme_widget_message_photo" in img_tag:
            src = re.search(r'src="([^"]+)"', img_tag) or re.search(r"src='([^']+)'", img_tag)
            if src:
                return src.group(1)
    # Video/photo fon rasmi (background-image:url(...))
    bg = _BG_IMAGE_RE.search(block)
    if bg:
        return bg.group(1)
    return ""


def _parse_channel_page(html: str, channel_username: str) -> list[dict]:
    """Telegram web-preview HTML dan postlarni ajratib oladi.

    Real t.me/s/ formati: ``<div class="tgme_widget_message_wrap
    js-widget_message" data-post="kanal/123">``. Eski format ham qo'llanadi.

    Returns: list of {"text": str, "date": str, "media_url": str,
                      "post_link": str, "views": int}
    """
    if not html:
        return []

    # Har bir post <div class="tgme_widget_message_wrap ..."> dan boshlanadi
    blocks = _MESSAGE_WRAP_RE.split(html)
    if len(blocks) <= 1:
        # Eski format: <div class="tgme_widget_message ">
        blocks = _MESSAGE_OLD_RE.split(html)
    if len(blocks) <= 1:
        # Zaxira: data-post atributi bo'yicha
        blocks = _DATA_POST_ATTR_RE.split(html)

    posts = []
    for block in blocks[1:]:  # birinchi bo'lik — header, o'tkazib yuboramiz
        post = {"text": "", "date": "", "media_url": "", "post_link": "", "views": 0}

        # Matn
        text_match = _TEXT_RE.search(block)
        if text_match:
            post["text"] = _strip_html_tags(text_match.group(1))

        # Sana
        date_match = _DATE_RE.search(block)
        if date_match:
            post["date"] = date_match.group(1)

        # Post havolasi — eng ishonchli manba data-post="kanal/123"
        dp_match = _DATA_POST_RE.search(block)
        if dp_match:
            post["post_link"] = f"https://t.me/{dp_match.group(1)}/{dp_match.group(2)}"
        else:
            link_match = _LINK_RE.search(block) or _LINK_RE_ALT.search(block)
            if link_match:
                post["post_link"] = link_match.group(1)

        # Rasm/video
        post["media_url"] = _extract_media_url(block)

        # Ko'rishlar soni
        views_match = _VIEWS_RE.search(block)
        if views_match:
            post["views"] = _parse_views(views_match.group(1))

        # Faqat matn yoki rasm bor postlarni qo'shamiz
        if post["text"] or post["media_url"]:
            posts.append(post)

    # Havolasi topilmagan postlarga standart kanal havolasi
    for post in posts:
        if not post.get("post_link"):
            post["post_link"] = f"https://t.me/{channel_username}"

    return posts


# ============================================================
# HTTP (testlarda mock qilinadigan yagona nuqta)
# ============================================================

async def _fetch_html(url: str) -> tuple[int, str, str]:
    """URL ga HTTP GET so'rovi yuboradi.

    Returns:
        (status_code, html_text, content_type)
    """
    async with aiohttp.ClientSession(timeout=_CHANNEL_FETCH_TIMEOUT) as session:
        async with session.get(url, headers=_HTTP_HEADERS, allow_redirects=True) as resp:
            body = await resp.content.read(_MAX_HTML_BYTES)
            content_type = resp.headers.get("Content-Type", "")
            charset = "utf-8"
            m = re.search(r"charset=([\w-]+)", content_type, re.IGNORECASE)
            if m:
                charset = m.group(1)
            try:
                text = body.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                text = body.decode("utf-8", errors="replace")
            return resp.status, text, content_type


# ============================================================
# Kanal postlarini o'qish (DB + web-preview)
# ============================================================

async def read_channel_posts(channel_input, limit: int = 5) -> dict:
    """Ochiq Telegram kanalidan yoki bazadagi postlar tarixidan postlar oladi.

    Args:
        channel_input: ``@kanal``, ``kanal``, ``https://t.me/kanal``,
            ``https://t.me/s/kanal``, raqamli ID (``-100123...``) kabi manba.
        limit: nechta post olish (default 5, max 10)

    Returns:
        dict: ``{"status": ..., "channel": <toza_username>, "posts": [...]}``
        status: ok | private | not_found | empty | invalid | error

    1. Avval real vaqtli channel_posts_history jadvalidan tekshiradi
       (bot admin bo'lgan kanallar).
    2. Topilmasa yoki bo'sh bo'lsa — t.me/s/ web-preview scraping orqali
       o'qiydi (bot kanalda admin bo'lmasa ham ochiq kanalni o'qiy oladi).
    """
    raw = "" if channel_input is None else str(channel_input).strip()
    try:
        limit = max(1, min(int(limit or 5), 10))
    except (TypeError, ValueError):
        limit = 5

    result: dict = {"status": STATUS_ERROR, "channel": "", "posts": []}

    if not raw:
        result["status"] = STATUS_INVALID
        return result

    # Yopiq taklif havolasi (t.me/joinchat/..., t.me/+...)
    if is_private_invite(raw):
        result["status"] = STATUS_PRIVATE
        return result

    username = extract_channel_username(raw)
    if not username:
        if re.fullmatch(r"-?\d+", raw.lstrip("@").strip()):
            # Raqamli kanal ID (masalan -100123...) — faqat DB dan o'qiladi
            username = raw.lstrip("@").strip()
        else:
            result["status"] = STATUS_INVALID
            return result
    result["channel"] = username

    # --- 1) Real vaqtli baza (channel_posts_history) dan tekshirish ---
    try:
        import database as db
        history = await db.run_db(db.get_channel_posts_history, raw, limit)
        if not history and username != raw:
            history = await db.run_db(db.get_channel_posts_history, username, limit)
        if not history and username.isdigit():
            history = await db.run_db(db.get_channel_posts_history, f"-100{username}", limit)

        if history:
            posts = []
            for h in history:
                text = h.get("text") or h.get("content") or ""
                p_date = h.get("post_date") or h.get("date") or ""
                msg_id = h.get("message_id")
                post_link = (
                    f"https://t.me/{username}/{msg_id}"
                    if msg_id and not username.startswith("-")
                    else f"https://t.me/{username}"
                )
                posts.append({
                    "text": text,
                    "date": p_date,
                    "media_url": "",
                    "post_link": post_link,
                    "views": h.get("views", 0),
                })
            if posts:
                result["status"] = STATUS_OK
                result["posts"] = posts[:limit]
                return result
    except Exception as e:
        logger.debug("DB dan kanal postlarini olishda xato (scraping fallback ishlaydi): %s", e)

    # --- 2) Veb scraping fallback (t.me/s/username) ---
    # Raqamli ID bilan web-preview yo'q — bu yopiq kanal
    if username.lstrip("-").isdigit():
        result["status"] = STATUS_PRIVATE
        return result

    url = f"https://t.me/s/{username}"

    try:
        status_code, html, _ctype = await _fetch_html(url)
    except Exception as e:
        logger.warning("Kanal o'qish xatosi (@%s): %s", username, e)
        result["status"] = STATUS_ERROR
        return result

    if status_code == 404:
        logger.warning("Kanal topilmadi: @%s", username)
        result["status"] = STATUS_NOT_FOUND
        return result
    if status_code != 200:
        logger.warning("Kanal sahifasi xato (%s): HTTP %s", username, status_code)
        result["status"] = STATUS_ERROR
        return result

    # Web-preview yo'q — sababini aniqlaymiz:
    #   * "you can contact @name" → bunday kanal yo'q (yoki bu user profili);
    #   * "view and join" / tgme_page → kanal bor, lekin yopiq/cheklangan.
    if "tgme_widget_message" not in html:
        lowered = html.lower()
        if "you can contact" in lowered:
            result["status"] = STATUS_NOT_FOUND
        elif ("tgme_page" in lowered or "tgme_channel_info" in lowered
              or "view and join" in lowered or "can't be displayed" in lowered):
            logger.warning("Kanal yopiq yoki web-preview cheklangan: @%s", username)
            result["status"] = STATUS_PRIVATE
        else:
            result["status"] = STATUS_NOT_FOUND
        return result

    posts = _parse_channel_page(html, username)

    if not posts:
        result["status"] = STATUS_EMPTY
        return result

    # Sahifadagi oxirgi postlar eng yangisi — oxirgi `limit` tasini olamiz
    posts = posts[-limit:]
    posts.reverse()  # eng yangisi birinchi

    result["status"] = STATUS_OK
    result["posts"] = posts
    return result


async def fetch_latest_channel_posts(channel_username: str, limit: int = 3) -> list[dict]:
    """Ochiq Telegram kanalidan yoki bazadagi postlar tarixidan eng so'nggi postlarni oladi.

    Args:
        channel_username: kanal niki, to'liq havolasi (https://t.me/kanal) yoki
            ID raqami (masalan: "kunuzofficial", "@kunuzofficial", "-100123...")
        limit: nechta post olish (default 3, max 10)

    Returns:
        list[dict]: [{"text": ..., "date": ..., "media_url": ...,
                      "post_link": ..., "views": ...}, ...]
        Xatolarda bo'sh ro'yxat. Batafsil holat kerak bo'lsa
        ``read_channel_posts`` dan foydalaning.
    """
    result = await read_channel_posts(channel_username, limit)
    return result.get("posts") or []


# ============================================================
# Oddiy veb-sahifani o'qish (AI tahlili uchun)
# ============================================================

def _extract_main_text(html: str, max_chars: int = 1000) -> str:
    """Veb-sahifaning asosiy ko'rinadigan matnini ajratib oladi (max_chars gacha)."""
    # Kod/uslub/bosh qismlarini olib tashlash
    text = re.sub(
        r"(?is)<(script|style|noscript|svg|template|head|iframe)[^>]*>.*?</\1\s*>",
        " ", html,
    )
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    # Blok-yopuvchi teglar — yangi qator
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr|section|article|blockquote)>", "\n", text)
    # Qolgan teglarni olib tashlash
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    # Bo'sh joylarni ixchamlash
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)
    text = text.strip()
    return text[:max_chars]


async def read_webpage_for_ai(url: str, max_chars: int = 1000) -> dict:
    """Oddiy veb-sahifani o'qib, AI tahlili uchun qisqa matn tayyorlaydi.

    Sahifaning <title>, <meta name="description"> (yoki og:description) va
    asosiy matnini (``max_chars`` belgigacha) o'qiydi.

    Args:
        url: sayt manzili (masalan ``https://kun.uz/`` yoki ``kun.uz``)
        max_chars: asosiy matn uzunligi chegarasi (default 1000)

    Returns:
        {"title": str, "description": str, "text": str, "content": str, "url": str}
        yoki {"error": "..."}.
        ``content`` — title + description + asosiy matn (AI ga yetkaziladigan qism).
    """
    raw = "" if url is None else str(url).strip()
    if not raw:
        return {"error": "⚠️ Sayt manzili bo'sh."}

    # Protokolsiz domain → https:// qo'shish
    if not raw.lower().startswith(("http://", "https://")):
        if _BARE_DOMAIN_RE.fullmatch(raw):
            raw = "https://" + raw
        else:
            return {"error": "⚠️ Noto'g'ri sayt manzili. Qaytadan kiriting."}

    # Telegram havolasi — bu funksiya uchun emas
    if is_private_invite(raw) or _TME_CHANNEL_LINK_RE.fullmatch(raw):
        return {"error": "⚠️ Bu Telegram havolasi. Iltimos, oddiy sayt manzilini yuboring."}

    try:
        status_code, html, content_type = await _fetch_html(raw)
    except Exception as e:
        logger.warning("Sayt o'qish xatosi (%s): %s", raw, e)
        return {"error": "⚠️ Saytga ulanib bo'lmadi. Manzilni tekshirib, qayta yuboring."}

    if status_code != 200:
        return {"error": f"⚠️ Sayt javob bermadi (HTTP {status_code}). Manzilni tekshirib, qayta yuboring."}

    ctype = (content_type or "").split(";")[0].strip().lower()
    allowed = ("text/html", "text/plain", "application/xhtml+xml", "application/xml", "text/xml")
    if ctype and ctype not in allowed:
        return {"error": "⚠️ Bu havola matnli sahifa emas (rasm/fayl). Matnli sahifa havolasini yuboring."}

    title = ""
    title_match = _TITLE_RE.search(html)
    if title_match:
        title = _strip_html_tags(title_match.group(1))

    description = ""
    desc_match = _META_DESC_RE.search(html)
    if desc_match:
        description = _html.unescape(desc_match.group(3)).strip()
    else:
        desc_match = _META_DESC_RE_ALT.search(html)
        if desc_match:
            description = _html.unescape(desc_match.group(2)).strip()

    main_text = _extract_main_text(html, max_chars=max_chars)

    if not (title or description or main_text):
        return {"error": "⚠️ Saytdan matn o'qib bo'lmadi. Boshqa havolani urinib ko'ring."}

    # AI ga yetkaziladigan birlashtirilgan matn
    parts = []
    if title:
        parts.append(title.strip())
    if description:
        parts.append(description.strip())
    if main_text:
        parts.append(main_text.strip())
    content = "\n\n".join(parts)[: max_chars + 500]

    return {
        "title": title,
        "description": description,
        "text": main_text,
        "content": content,
        "url": raw,
    }


# ============================================================
# Formatlash
# ============================================================

def format_post_list(posts: list[dict], channel_username: str) -> str:
    """Postlar ro'yxatini chiroyli matn ko'rinishida formatlaydi."""
    if not posts:
        return ""

    lines = [f"📢 <b>@{channel_username}</b> — so'nggi postlar:\n"]
    for i, post in enumerate(posts, 1):
        text = post.get("text", "")
        date = post.get("date", "")

        # Matnni qisqartirish
        preview = text[:200] if text else "(rasm/video)"
        if len(text) > 200:
            preview += "…"

        # Sanani formatlash
        date_str = ""
        if date:
            try:
                dt = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                date_str = date[:16]

        lines.append(f"<b>{i}.</b> {preview}")
        if date_str:
            lines.append(f"   🕒 {date_str}")
        lines.append("")

    lines.append("Qaysi postni qayta ishlashni tanlang 👇")
    return "\n".join(lines)
