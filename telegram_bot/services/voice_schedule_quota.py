"""Ovozli rejalash kvotasi: free — butun umr bo'yicha bir martalik, PRO — kuniga cheklangan, admin — cheksiz.

Bron atomik (PostgreSQL advisory-lock). DB xatosida FAIL-CLOSED: imkoniyat berilmaydi (xarajatli ovoz->matn ishlatilmaydi).
Ovozni matnga o'girish (xarajat) FAQAT bron olingach boshlanadi; transkripsiya/aniqlash muvaffaqiyatsiz bo'lsa bron qaytariladi.
"""
from __future__ import annotations

import logging

import config

logger = logging.getLogger(__name__)

SCOPE_LIFETIME = "lifetime"
SCOPE_DAY = "day"
PRO_WINDOW_HOURS = 24


def limits_for(is_pro: bool) -> tuple[str, int, int | None]:
    """(scope, limit, window_hours). Free: butun umr; PRO: 24 soat."""
    if is_pro:
        return SCOPE_DAY, int(config.PRO_VOICE_SCHEDULE_DAILY), PRO_WINDOW_HOURS
    return SCOPE_LIFETIME, int(config.FREE_VOICE_SCHEDULE_TOTAL), None


async def reserve(db, user_id: int, is_pro: bool, is_admin: bool = False) -> dict:
    """``{"allowed", "reservation_id", "scope", "used", "limit", "reason"}`` — ``reason``: ok | limit | disabled | unavailable."""
    if is_admin:
        return {"allowed": True, "reservation_id": None, "scope": "admin", "used": 0, "limit": 0, "reason": "ok"}
    scope, limit, window = limits_for(is_pro)
    if limit <= 0:
        return {"allowed": False, "reservation_id": None, "scope": scope, "used": 0, "limit": 0, "reason": "disabled"}
    try:
        res = await db.run_db(db.reserve_voice_schedule, int(user_id), window, limit)
    except Exception as exc:  # noqa: BLE001 — fail-closed
        logger.warning("voice_schedule: bron DB xatosi (%s)", type(exc).__name__)
        return {"allowed": False, "reservation_id": None, "scope": scope, "used": 0, "limit": limit, "reason": "unavailable"}
    return {**res, "scope": scope, "reason": "ok" if res.get("allowed") else "limit"}


async def release(db, user_id: int, reservation_id) -> None:
    """Bronni qaytaradi (``None`` bo'lsa — admin yoki bron yo'q: hech narsa qilinmaydi). Xato yutiladi, lekin loglanadi."""
    if reservation_id is None:
        return
    try:
        await db.run_db(db.release_voice_schedule, int(user_id), int(reservation_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice_schedule: bron qaytarilmadi (%s)", type(exc).__name__)
