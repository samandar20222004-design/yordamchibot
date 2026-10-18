"""💰 Reklama birjasi: sof hisob-kitoblar (DB/tarmoqsiz) va ma'lumot yig'ish yordamchilari.

Halollik qoidasi (analitika bilan bir xil): raqam noma'lum bo'lsa ``None`` — soxta 0 yoki taxmin YO'Q.
  * obunachilar — kunlik snapshot yoki e'lon paytidagi jonli son;
  * o'rtacha ko'rish — FAQAT haqiqiy (NULL bo'lmagan) so'nggi postlardan, kamida ``MIN_POSTS_FOR_VIEWS`` ta;
  * ER = o'rtacha ko'rish / obunachilar (%); o'sish — snapshot farqi (``services.channels.growth``).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

CATEGORIES = ("news", "tech", "business", "education", "entertainment", "lifestyle", "sport", "shop", "auto", "other")

MIN_POSTS_FOR_VIEWS = 3
STATS_TTL_HOURS = 6
PRICE_MIN = 1_000
PRICE_MAX = 1_000_000_000
DESCRIPTION_MAX = 400
INQUIRY_MAX = 1000
INQUIRY_MIN = 10

_NEGOTIABLE = {"0", "kelishiladi", "kelishamiz", "договорная", "договорная цена", "negotiable", "-"}
_PRICE_RE = re.compile(r"^(\d+(?:[.,]\d+)?)\s*(k|ming|тыс|тыс\.|m|mln|млн|million)?$", re.IGNORECASE)
_MULT = {"k": 1_000, "ming": 1_000, "тыс": 1_000, "тыс.": 1_000, "m": 1_000_000, "mln": 1_000_000,
         "млн": 1_000_000, "million": 1_000_000}


def normalize_category(value: str | None) -> str:
    return value if value in CATEGORIES else "other"


def parse_price(text: str) -> tuple[str, int | None]:
    """Narx matnini tahlil qiladi. Qaytadi ``("ok", so'm)`` | ``("negotiable", None)`` | ``("error", None)``.

    «50000», «50 000», «50k», «50 ming», «1.5 mln», «kelishiladi», «0» qabul qilinadi.
    """
    raw = (text or "").strip().lower()
    if raw in _NEGOTIABLE:
        return "negotiable", None
    compact = re.sub(r"(?<=\d)[  _](?=\d{3}\b)", "", raw)
    m = _PRICE_RE.match(compact)
    if not m:
        return "error", None
    number = float(m.group(1).replace(",", "."))
    value = int(round(number * _MULT.get((m.group(2) or "").lower(), 1)))
    if value < PRICE_MIN or value > PRICE_MAX:
        return "error", None
    return "ok", value


def clean_text(text: str | None, limit: int) -> str:
    """Bo'sh joylarni tartiblaydi va uzunlikka kesadi (HTML'ga aylantirish chiqarishda ``html_escape`` bilan)."""
    value = re.sub(r"[ \t]+", " ", (text or "").replace("\r", "")).strip()
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value[:limit]


def format_count(n: int | None) -> str:
    """12400 -> «12.4k», 1250000 -> «1.25M», None -> «—»."""
    if n is None:
        return "—"
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}".rstrip("0").rstrip(".") + "M"
    if n >= 10_000:
        return f"{n / 1_000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"{n:,}".replace(",", " ")


def format_price(price: int | None, negotiable_label: str) -> str:
    return negotiable_label if price is None else f"{int(price):,}".replace(",", " ")


def compute_stats(*, live_members: int | None, history: list[dict], views: list[int], posts_30d: int) -> dict:
    """Kanal ko'rsatkichlari. ``history`` — ``get_channel_member_history`` natijasi (yangidan eskiga)."""
    from services.channels.growth import compute_member_growth

    growth = compute_member_growth(history)
    members = live_members if isinstance(live_members, int) and live_members >= 0 else growth.get("current")
    avg_views = None
    if len(views) >= MIN_POSTS_FOR_VIEWS:
        avg_views = int(round(sum(views) / len(views)))
    er = None
    if avg_views is not None and members:
        er = round(avg_views / members * 100, 1)
    return {"members": members, "avg_views": avg_views, "er_percent": er,
            "growth_30d": growth.get("delta_30d"), "posts_30d": int(posts_30d)}


def stats_are_stale(listing: dict, now: datetime | None = None) -> bool:
    updated = listing.get("stats_updated_at")
    if not updated:
        return True
    now = now or datetime.now(timezone.utc)
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return now - updated > timedelta(hours=STATS_TTL_HOURS)


def listing_badges(listing: dict) -> list[str]:
    """Faqat o'lchangan faktlardan nishonlar (kalitlar; matn tarjimasi handlerda)."""
    badges = []
    members = listing.get("members") or 0
    growth = listing.get("growth_30d")
    if growth is not None and members and growth > 0 and growth / members >= 0.02:
        badges.append("growing")
    er = listing.get("er_percent")
    if er is not None and er >= 30:
        badges.append("engaged")
    if (listing.get("posts_30d") or 0) >= 15:
        badges.append("active")
    return badges


def refresh_listing_stats(listing_id: int, channel_id: str, live_members: int | None = None) -> dict:
    """Ko'rsatkichlarni bazadagi ma'lumotlardan qayta hisoblab saqlaydi (sinxron; ``run_db`` ichida chaqiriladi)."""
    from repositories import ad_market_repository as repo
    from repositories.channels_repository import get_channel_member_history

    stats = compute_stats(
        live_members=live_members,
        history=get_channel_member_history(channel_id, days=60),
        views=repo.get_recent_views(channel_id),
        posts_30d=repo.count_recent_posts(channel_id, 30),
    )
    repo.save_listing_stats(listing_id, stats)
    return stats


async def verify_channel_ownership(bot, user_id: int, channel_ref) -> dict:
    """Birjaga chiqarishdan oldin JONLI tekshiruv (bot ham, foydalanuvchi ham kanal admini, kanal ochiq).

    Qaytadi: ``{"ok": True, "username", "title", "members"}`` yoki ``{"ok": False, "reason": "private"|"not_admin"|"tg_error"}``.
    """
    from telegram.error import BadRequest, Forbidden, TelegramError

    chat_ref = int(channel_ref) if str(channel_ref).lstrip("-").isdigit() else channel_ref
    try:
        chat = await bot.get_chat(chat_ref)
        if not chat.username:
            return {"ok": False, "reason": "private"}
        bot_member = await bot.get_chat_member(chat.id, bot.id)
        user_member = await bot.get_chat_member(chat.id, user_id)
        members = await bot.get_chat_member_count(chat.id)
    except (Forbidden, BadRequest):
        return {"ok": False, "reason": "not_admin"}
    except TelegramError:
        return {"ok": False, "reason": "tg_error"}
    if bot_member.status not in ("administrator", "creator") or user_member.status not in ("administrator", "creator"):
        return {"ok": False, "reason": "not_admin"}
    return {"ok": True, "username": chat.username, "title": chat.title or chat.username, "members": int(members)}
