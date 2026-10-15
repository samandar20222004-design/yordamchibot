"""Ovozli rejalash kvotasi (PostgreSQL): atomik bron / qaytarish / hisob.

Bron advisory-lock ostida: bir foydalanuvchining parallel so'rovlari ketma-ket tekshiriladi, shuning uchun limit HECH QACHON
oshib ketmaydi (free bir martalik imkoniyat ikki marta berilmaydi). Faqat ``user_id`` va vaqt saqlanadi.
"""
from __future__ import annotations

from database import db_cursor

# Boshqa advisory-lock'lar bilan to'qnashmasligi uchun user_id ga katta siljish qo'shiladi (bigint ichida).
_LOCK_BASE = 7_100_000_000_000_000_000


def _count(cur, user_id: int, window_hours) -> int:
    if window_hours is None:
        cur.execute("SELECT COUNT(*) FROM voice_schedule_usage WHERE user_id = %s", (user_id,))
    else:
        cur.execute(
            "SELECT COUNT(*) FROM voice_schedule_usage "
            "WHERE user_id = %s AND used_at > NOW() - (%s || ' hours')::INTERVAL",
            (user_id, str(int(window_hours))),
        )
    return int(cur.fetchone()[0])


def reserve_voice_schedule(user_id: int, window_hours, limit: int) -> dict:
    """Bitta imkoniyatni bron qiladi. ``window_hours=None`` — butun umr bo'yicha hisob (free).

    Returns ``{"allowed": bool, "reservation_id": int|None, "used": int, "limit": int}`` (``used`` — bronni hisobga olgan holda).
    """
    uid = int(user_id)
    limit = int(limit)
    with db_cursor(commit=True) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_BASE + uid,))
        used = _count(cur, uid, window_hours)
        if limit <= 0 or used >= limit:
            return {"allowed": False, "reservation_id": None, "used": used, "limit": max(limit, 0)}
        cur.execute("INSERT INTO voice_schedule_usage (user_id) VALUES (%s) RETURNING id", (uid,))
        return {"allowed": True, "reservation_id": int(cur.fetchone()[0]), "used": used + 1, "limit": limit}


def release_voice_schedule(user_id: int, reservation_id: int) -> bool:
    """Bronni qaytaradi (transkripsiya/aniqlash muvaffaqiyatsiz bo'lsa). Boshqa foydalanuvchi bronini o'chirmaydi."""
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM voice_schedule_usage WHERE id = %s AND user_id = %s", (int(reservation_id), int(user_id)))
        return bool(cur.rowcount)


def voice_schedule_used(user_id: int, window_hours=None) -> int:
    with db_cursor() as cur:
        return _count(cur, int(user_id), window_hours)
