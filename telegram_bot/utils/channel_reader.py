"""Public Telegram Channel Post Reader — ochiq kanallardan post o'qish.

https://t.me/s/<channel_username> sahifasini parse qilib, eng so'nggi postlarni
oladi. Faqat OCHIQ kanallar uchun ishlaydi.
"""
import logging
import re
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

# Telegram web-preview sahifasi uchun timeout
_CHANNEL_FETCH_TIMEOUT = aiohttp.ClientTimeout(total=15, connect=8)

# Post HTML strukturasini ajratish uchun regex lar
_POST_BLOCK_RE = re.compile(
    r'<div class="tgme_widget_message_wrap[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>',
    re.DOTALL,
)
_TEXT_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
_DATE_RE = re.compile(
    r'<time[^>]*datetime="([^"]+)"',
)
_LINK_RE = re.compile(
    r'<a[^>]*class="tgme_widget_message_date[^"]*"[^>]*href="([^"]+)"',
)
_IMAGE_RE = re.compile(
    r'<img[^>]*class="tgme_widget_message_photo[^"]*"[^>]*src="([^"]+)"',
)
# Background image style dan rasm URL
_BG_IMAGE_RE = re.compile(
    r'background-image:\s*url\(\'([^\']+)\'\)',
)


def _strip_html_tags(text: str) -> str:
    """HTML teglarini olib tashlaydi, matnni toza qaytaradi."""
    if not text:
        return ""
    # <br> va <br/> ni yangi qatorga almashtirish
    text = re.sub(r'<br\s*/?>', '\n', text)
    # Boshqa barcha teglarni olib tashlash
    text = re.sub(r'<[^>]+>', '', text)
    # HTML entity larni decode qilish
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    # Ortiqcha bo'sh joylarni tozalash
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def _parse_channel_page(html: str, channel_username: str) -> list[dict]:
    """Telegram web-preview HTML dan postlarni ajratib oladi.

    Returns: list of {"text": str, "date": str, "media_url": str, "post_link": str}
    """
    posts = []

    # tgme_widget_message bloklarini topish
    # Har bir post <div class="tgme_widget_message ..."> dan boshlanadi
    msg_blocks = re.split(r'<div class="tgme_widget_message\b', html)

    for block in msg_blocks[1:]:  # birinchi bo'lik — header, o'tkazib yuboramiz
        post = {}

        # Matn
        text_match = _TEXT_RE.search(block)
        if text_match:
            raw_text = text_match.group(1)
            post["text"] = _strip_html_tags(raw_text)
        else:
            # Ba'zi postlarda matn yo'q (faqat rasm/video)
            post["text"] = ""

        # Sana
        date_match = _DATE_RE.search(block)
        if date_match:
            post["date"] = date_match.group(1)
        else:
            post["date"] = ""

        # Post havolasi
        link_match = _LINK_RE.search(block)
        if link_match:
            post["post_link"] = link_match.group(1)
        else:
            post["post_link"] = f"https://t.me/{channel_username}"

        # Rasm
        img_match = _IMAGE_RE.search(block)
        if img_match:
            post["media_url"] = img_match.group(1)
        else:
            # Background image dan tekshirish
            bg_match = _BG_IMAGE_RE.search(block)
            if bg_match:
                post["media_url"] = bg_match.group(1)
            else:
                post["media_url"] = ""

        # Faqat matn yoki rasm bor postlarni qo'shamiz
        if post["text"] or post["media_url"]:
            posts.append(post)

    return posts


async def fetch_latest_channel_posts(channel_username: str, limit: int = 3) -> list[dict]:
    """Ochiq Telegram kanalidan eng so'nggi postlarni oladi.

    Args:
        channel_username: kanal niki (masalan: "kunuzofficial" yoki "@kunuzofficial")
        limit: nechta post olish (default 3, max 10)

    Returns:
        list[dict]: [{"text": ..., "date": ..., "media_url": ..., "post_link": ...}, ...]

    Xatolikda: bo'sh ro'yxat qaytaradi (logger orqali xabar beriladi).
    """
    # Username tozalash
    username = (channel_username or "").strip().lstrip("@").strip("/")
    if not username:
        logger.warning("Kanal niki bo'sh")
        return []

    limit = max(1, min(limit, 10))

    url = f"https://t.me/s/{username}"

    try:
        async with aiohttp.ClientSession(timeout=_CHANNEL_FETCH_TIMEOUT) as session:
            async with session.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; PostAssistBot/2.0)",
                "Accept-Language": "uz,ru,en;q=0.9",
            }) as resp:
                if resp.status == 404:
                    logger.warning("Kanal topilmadi: @%s", username)
                    return []
                if resp.status != 200:
                    logger.warning("Kanal sahifasi xato (%s): HTTP %s", username, resp.status)
                    return []
                html = await resp.text()

        # "This channel can't be displayed" yoki web-preview yo'q
        if "tgme_widget_message" not in html:
            logger.warning("Kanal yopiq yoki postlar topilmadi: @%s", username)
            return []

        posts = _parse_channel_page(html, username)

        # Oxirgi postlar birinchi chiqadi (eng yangi)
        posts = posts[-limit:]
        posts.reverse()

        return posts

    except aiohttp.ClientError as e:
        logger.warning("Kanal o'qish xatosi (@%s): %s", username, e)
        return []
    except Exception as e:
        logger.error("Kutilmagan xato (@%s): %s", username, e)
        return []


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
