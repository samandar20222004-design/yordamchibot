"""Telegram «Menu» tugmasini Mini App'ga yo'naltirish (ixtiyoriy, xavfsiz fallback).

Faqat ``MINIAPP_ENABLED=1`` VA ``MINIAPP_URL`` to'g'ri HTTPS manzil bo'lsa
``MenuButtonWebApp`` qaytadi. Aks holda ``None`` — chaqiruvchi mavjud
«commands» tugmasida qoladi (bot xulqi o'zgarmaydi). URL faqat muhit
o'zgaruvchisidan olinadi (frontend/foydalanuvchi kiritmasidan emas).
"""
from __future__ import annotations

import logging
import os
import re
from urllib.parse import urlsplit

from .settings import load_settings

logger = logging.getLogger(__name__)

_BAD_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f<>\"'\\]")
BUTTON_TEXT = "PostAssist"


def valid_miniapp_url(url: str) -> bool:
    url = (url or "").strip()
    if not url or len(url) > 512 or _BAD_URL_CHARS.search(url):
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    return "." in host or host == "localhost"  # to'liq domen; xom IP-lar ham "." bor


def miniapp_menu_button(env=None):
    """``MenuButtonWebApp`` yoki ``None`` (o'chiq / URL yaroqsiz / xavfsiz emas)."""
    env = os.environ if env is None else env
    settings = load_settings(env)
    if not settings.enabled or settings.config_errors:
        return None
    url = (env.get("MINIAPP_URL") or "").strip()
    if not url:
        return None
    if not valid_miniapp_url(url):
        logger.warning("MINIAPP_URL yaroqsiz (faqat to'liq https:// manzil) — Menu tugmasi o'zgartirilmadi.")
        return None
    from telegram import MenuButtonWebApp, WebAppInfo

    return MenuButtonWebApp(text=BUTTON_TEXT, web_app=WebAppInfo(url=url))


def miniapp_webapp_url(env=None):
    """Bot tugmalari uchun Mini App manzili (``MINIAPP_ENABLED=1`` va to'g'ri HTTPS bo'lsa), aks holda ``None``."""
    env = os.environ if env is None else env
    settings = load_settings(env)
    if not settings.enabled or settings.config_errors:
        return None
    url = (env.get("MINIAPP_URL") or "").strip()
    return url if url and valid_miniapp_url(url) else None


MINIAPP_TABS = ("home", "post", "schedule", "market", "me", "admin")
MINIAPP_EXTRA_KEYS = ("thread", "ws")


def miniapp_tab_url(tab: str | None = None, env=None, extra: dict | None = None):
    """Mini App manzili + ``?tab=`` (Mini App shu bo'limni to'g'ridan-to'g'ri ochadi). O'chiq bo'lsa ``None``.

    Telegram ``web_app`` manzilidagi QUERY'ni saqlaydi (``#`` qismi esa ishga tushirish parametrlari uchun band).
    """
    url = miniapp_webapp_url(env)
    if not url:
        return None
    if tab in MINIAPP_TABS:
        parts = urlsplit(url)
        # `extra` — faqat butun sonli ID'lar (masalan thread=12): foydalanuvchi matni URL'ga tushmaydi.
        extras = [f"{k}={int(v)}" for k, v in (extra or {}).items() if k in MINIAPP_EXTRA_KEYS and isinstance(v, int)]
        query = "&".join(q for q in (parts.query, f"tab={tab}", *extras) if q)
        url = parts._replace(query=query).geturl()
    return url


def miniapp_button(lang: str, tab: str | None = None, key: str = "btn_miniapp_open", extra: dict | None = None,
                   label: str | None = None):
    """Inline ``web_app`` tugmasi yoki ``None`` (Mini App o'chiq / manzil yaroqsiz)."""
    url = miniapp_tab_url(tab, extra=extra)
    if not url:
        return None
    from telegram import InlineKeyboardButton, WebAppInfo

    from locales.translations import get_text

    return InlineKeyboardButton(label or get_text(key, lang), web_app=WebAppInfo(url=url))


def with_miniapp_row(markup, lang: str, tab: str | None = None, before_last: bool = False):
    """Mavjud ``InlineKeyboardMarkup`` ga «📱 Mini App» qatorini qo'shadi (o'chiq bo'lsa o'zgarishsiz qaytaradi).

    ``before_last`` — qator oxirgi (odatda «Orqaga/Yopish») qatordan oldin turadi.
    """
    try:
        button = miniapp_button(lang, tab)
        if button is None or markup is None:
            return markup
        from telegram import InlineKeyboardMarkup

        rows = [list(r) for r in markup.inline_keyboard]
        rows.insert(len(rows) - 1 if before_last and rows else len(rows), [button])
        return InlineKeyboardMarkup(rows)
    except Exception:  # noqa: BLE001 — qo'shimcha tugma hech qachon asosiy ekranni buzmasin
        logger.debug("Mini App tugmasi qo'shilmadi", exc_info=True)
        return markup


def miniapp_reply_button(tab: str | None = None, lang: str = "uz"):
    """Pastki (reply) klaviatura uchun ``web_app`` tugmasi yoki ``None`` (Mini App o'chiq): «📱 Mini App'da»."""
    url = miniapp_tab_url(tab)
    if not url:
        return None
    from telegram import KeyboardButton, WebAppInfo

    from translations import market_t

    return KeyboardButton(market_t("mk_btn_open_app", lang), web_app=WebAppInfo(url=url))
