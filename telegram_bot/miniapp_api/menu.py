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
