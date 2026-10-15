"""`/start` da markazda animatsiyali yuklash ko'rsatkichi (logo animatsiyasi, MP4).

Foydalanuvchi botga kirganda javob tayyorlanguncha animatsiya ko'rinadi, asosiy javob yuborilgach o'chadi.
Hech qachon `/start` ni buzmaydi: har bir xato yutiladi, yuborish vaqt bilan cheklangan.
Fayl bir marta yuklanadi, keyin Telegram `file_id` si xotirada saqlanadi (qayta yuklash yo'q).
O'chirish: START_SPLASH=0.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SPLASH_PATH = Path(__file__).resolve().parent.parent / "assets" / "loading.mp4"
SEND_TIMEOUT_SECONDS = 1.5
_file_id: str | None = None


def splash_enabled() -> bool:
    return os.getenv("START_SPLASH", "1").strip().lower() not in ("0", "false", "no", "off")


async def send_splash(message):
    """Animatsiyani yuboradi; muvaffaqiyatsiz bo'lsa None (jim)."""
    global _file_id
    if not splash_enabled() or message is None or not hasattr(message, "reply_animation"):
        return None
    try:
        if _file_id:
            return await asyncio.wait_for(message.reply_animation(animation=_file_id), SEND_TIMEOUT_SECONDS)
        if not SPLASH_PATH.is_file():
            return None
        with SPLASH_PATH.open("rb") as fh:
            sent = await asyncio.wait_for(message.reply_animation(animation=fh), SEND_TIMEOUT_SECONDS * 4)
        anim = getattr(sent, "animation", None) or getattr(sent, "document", None)
        fid = getattr(anim, "file_id", None)
        if isinstance(fid, str) and fid:
            _file_id = fid
        return sent
    except Exception as exc:  # noqa: BLE001 — animatsiya ixtiyoriy
        logger.debug("Yuklash animatsiyasi yuborilmadi (%s)", type(exc).__name__)
        return None


async def remove_splash(sent) -> None:
    """Animatsiya xabarini o'chiradi (xato yutiladi)."""
    if sent is None:
        return
    try:
        await sent.delete()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Yuklash animatsiyasi o'chirilmadi (%s)", type(exc).__name__)
