# -*- coding: utf-8 -*-
"""💰 UMUMIY AI BYUDJETI — PostgreSQL'da ATOMIK rezervatsiya.

Qatlam: REPOSITORY. Bir nechta bot instance'i ham umumiy kunlik (UTC) AI
xarajat chegarasini (``AI_GLOBAL_DAILY_USD``) oshira olmasligi uchun bron va
yakunlash PostgreSQL'da, ``pg_advisory_xact_lock`` bilan seriyalanadi.

Jadvallar (``schema.sql`` + ``database._ddl_ai_budget``; ikkalasi ham idempotent):

* ``ai_budget_reservations`` — har bir bron (ticket) va uning holati;
* ``ai_budget_days`` — kun bo'yicha yig'indilar (O(1) tekshiruv).

Kun hisobi (``used``) uch QISMDAN iborat va ALOHIDA saqlanadi:

* ``spent_usd``   — yakunlangan haqiqiy/estimated sarf (``estimated_cost``);
* ``assumed_usd`` — narxi noma'lum muvaffaqiyatli so'rovlar uchun budjet taxmini
  (haqiqiy sarf EMAS, ``spent_usd`` bilan aralashtirilmaydi);
* ``unknown_usd`` — natijasi NOMA'LUM bronlar (timeout, eskirgan ticket):
  bron summasi konservativ ravishda hisobda QOLADI.

``used = spent + assumed + unknown + SUM(est_usd) FROM bronlar(state='reserved')``.

Ticket holatlari::

    reserved ──settle──────────▶ settled     (haqiqiy sarf yozildi)
    reserved ──release─────────▶ released    (sarf yo'q: provayder chaqirilmadi/xato)
    reserved ──mark_unknown────▶ unknown     (timeout/bekor: sarf noma'lum → bron hisobda)
    reserved ──TTL─────────────▶ expired     (jarayon o'ldi/yakunlanmadi: bron hisobda QOLADI)
    expired  ──settle─────────▶ settled      (kechikkan yakunlash: bron o'rniga haqiqiy sarf)
    expired  ──release────────▶ released     (kechikkan: sarf yo'qligi aniq bo'ldi)
    settled/released/unknown ──istalgan────▶ o'zgarmaydi (idempotent)

TTL bronni O'CHIRMAYDI: eskirgan bron ``unknown_usd`` ga o'tadi, ya'ni hali
tugamagan provayder chaqiruvining xarajati hisobdan tushib qolmaydi. Faqat aniq
``settle`` yoki ``release`` uni qaytaradi. Har bir qiymat ticket'ning bron kuniga
yoziladi (yarim tunda ham hisob mos qoladi).

``release`` bron yetib kelmasdan oldin kelsa (so'rov vaqt chegarasi tufayli
tashlab yuborilgan fon tranzaksiyasi) — qabr belgisi (``released``) yoziladi va
keyingi ``reserve`` rad etiladi: bron "sizib" qolmaydi.
"""

from __future__ import annotations

import logging
import os
import socket

from repositories.runtime import db_transaction

logger = logging.getLogger(__name__)

#: ``pg_advisory_xact_lock`` kaliti (global byudjet seriyalash qulfi).
AI_BUDGET_LOCK_KEY = 7_021_001

#: Eski yopilgan ticket'lar shuncha kundan keyin tozalanadi (hisob ``ai_budget_days`` da).
AI_BUDGET_KEEP_DAYS = 7

_INSTANCE = f"{socket.gethostname()}:{os.getpid()}"

_UTC_DAY_SQL = "(NOW() AT TIME ZONE 'UTC')::date"


def _num(value) -> float:
    return round(float(value or 0), 6)


def _add_day(cur, day, *, spent=0.0, assumed=0.0, unknown=0.0) -> None:
    """Kun yig'indisiga atomik qo'shadi (``unknown`` o'zgarishi manfiy bo'lishi mumkin)."""
    cur.execute(
        "INSERT INTO ai_budget_days (day, spent_usd, assumed_usd, unknown_usd) "
        "VALUES (%s, %s, %s, GREATEST(0, %s)) "
        "ON CONFLICT (day) DO UPDATE SET "
        "spent_usd = ai_budget_days.spent_usd + EXCLUDED.spent_usd, "
        "assumed_usd = ai_budget_days.assumed_usd + EXCLUDED.assumed_usd, "
        "unknown_usd = GREATEST(0, ai_budget_days.unknown_usd + %s), "
        "updated_at = NOW()",
        (day, spent, assumed, unknown, unknown),
    )


def _sweep_expired(cur) -> int:
    """TTL o'tgan ``reserved`` ticket'larni ``expired`` qiladi; summalar ``unknown_usd`` da QOLADI."""
    cur.execute(
        "WITH ex AS ("
        " UPDATE ai_budget_reservations SET state = 'expired', closed_at = NOW() "
        " WHERE state = 'reserved' AND expires_at < NOW() "
        " RETURNING day, est_usd), "
        "agg AS (SELECT day, SUM(est_usd) AS usd, COUNT(*) AS n FROM ex GROUP BY day), "
        "ins AS ("
        " INSERT INTO ai_budget_days (day, unknown_usd) SELECT day, usd FROM agg "
        " ON CONFLICT (day) DO UPDATE SET "
        "  unknown_usd = ai_budget_days.unknown_usd + EXCLUDED.unknown_usd, updated_at = NOW() "
        " RETURNING 1) "
        "SELECT COALESCE(SUM(n), 0) FROM agg"
    )
    return int((cur.fetchone() or (0,))[0] or 0)


def _purge_old(cur, limit: int = 200) -> None:
    cur.execute(
        "DELETE FROM ai_budget_reservations WHERE ticket_id IN ("
        " SELECT ticket_id FROM ai_budget_reservations "
        " WHERE state <> 'reserved' "
        "   AND created_at < NOW() - make_interval(days => %s) LIMIT %s)",
        (AI_BUDGET_KEEP_DAYS, limit),
    )


def reserve_ai_budget(ticket_id: str, user_id, est_usd: float, cap_usd: float,
                      ttl_seconds: float = 180.0) -> dict:
    """Umumiy kunlik chegara ichida bo'lsa bron yozadi (atomik, instance'lararo).

    Qaytadi: ``{"granted": bool, "reason": str, "used": float, "cap": float, "day": str}``.
    ``reason``: ``ok`` | ``global_daily_usd`` (chegaradan oshadi) | ``released``
    (bu ticket allaqachon bo'shatilgan/yopilgan — qayta urinish xavfsiz).
    Idempotent: bir xil ``ticket_id`` ikki marta bron qilinmaydi.
    """
    est = max(0.0, float(est_usd or 0.0))
    cap = max(0.0, float(cap_usd or 0.0))
    with db_transaction() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (AI_BUDGET_LOCK_KEY,))
        _sweep_expired(cur)
        _purge_old(cur)
        cur.execute(
            "SELECT state FROM ai_budget_reservations WHERE ticket_id = %s FOR UPDATE",
            (ticket_id,),
        )
        row = cur.fetchone()
        cur.execute(f"SELECT {_UTC_DAY_SQL}")  # nosec B608 — kod-konstanta
        day = (cur.fetchone())[0]
        if row is not None:
            granted = row[0] == "reserved"
            return {"granted": granted, "reason": "ok" if granted else "released",
                    "used": 0.0, "cap": cap, "day": str(day)}
        # BITTA so'rov = bitta snapshot: yakunlash bilan poyga ikki marta sanash bilan
        # (ehtiyotkor tomonga) tugaydi, hech qachon kam sanash bilan emas.
        cur.execute(
            "SELECT COALESCE((SELECT spent_usd + assumed_usd + unknown_usd "
            "                  FROM ai_budget_days WHERE day = %s), 0) "
            "     + COALESCE((SELECT SUM(est_usd) FROM ai_budget_reservations "
            "                  WHERE state = 'reserved' AND day = %s), 0)",
            (day, day),
        )
        used = _num((cur.fetchone() or (0,))[0])
        # float xatosi (0.29 + 0.01 > 0.30) tufayli noto'g'ri rad etilmasin: 6 xonagacha.
        if round(used + est, 6) > round(cap, 6):
            return {"granted": False, "reason": "global_daily_usd", "used": used,
                    "cap": cap, "day": str(day)}
        cur.execute(
            "INSERT INTO ai_budget_reservations "
            "(ticket_id, day, user_id, est_usd, state, expires_at, instance) "
            "VALUES (%s, %s, %s, %s, 'reserved', NOW() + make_interval(secs => %s), %s)",
            (ticket_id, day, user_id, est, float(ttl_seconds), _INSTANCE),
        )
        return {"granted": True, "reason": "ok", "used": used, "cap": cap, "day": str(day)}


def _lock_ticket(cur, ticket_id: str):
    cur.execute(
        "SELECT day, est_usd, state FROM ai_budget_reservations "
        "WHERE ticket_id = %s FOR UPDATE",
        (ticket_id,),
    )
    return cur.fetchone()


def settle_ai_budget(ticket_id: str, actual_usd: float, assumed_usd: float = 0.0) -> str:
    """Bronni haqiqiy sarf bilan yakunlaydi. Qaytadi: ``settled`` | ``noop`` | ``missing``.

    ``actual_usd`` (estimated_cost) va ``assumed_usd`` (narxi noma'lum so'rov
    taxmini) ALOHIDA yoziladi. ``expired`` ticket'ni ham yakunlaydi (kechikkan
    javob): eskirganda ``unknown_usd`` da turgan bron summasi haqiqiy sarfga
    almashtiriladi. Takroriy chaqiruv hech narsani o'zgartirmaydi.
    """
    actual = max(0.0, float(actual_usd or 0.0))
    assumed = max(0.0, float(assumed_usd or 0.0))
    with db_transaction() as cur:
        row = _lock_ticket(cur, ticket_id)
        if row is None:
            return "missing"
        day, est, state = row
        if state not in ("reserved", "expired"):
            return "noop"
        cur.execute(
            "UPDATE ai_budget_reservations SET state = 'settled', closed_at = NOW(), "
            "settled_usd = %s, assumed_usd = %s WHERE ticket_id = %s",
            (actual, assumed, ticket_id),
        )
        _add_day(cur, day, spent=actual, assumed=assumed,
                 unknown=(-_num(est) if state == "expired" else 0.0))
        return "settled"


def release_ai_budget(ticket_id: str) -> str:
    """Bronni sarfsiz bo'shatadi (provayder chaqirilmadi/aniq xato). Idempotent.

    Qaytadi: ``released`` | ``noop`` | ``tombstone`` (bron hali yetib kelmagan).
    """
    with db_transaction() as cur:
        row = _lock_ticket(cur, ticket_id)
        if row is None:
            cur.execute(
                f"INSERT INTO ai_budget_reservations "  # nosec B608 — kod-konstanta
                f"(ticket_id, day, est_usd, state, expires_at, closed_at, instance) "
                f"VALUES (%s, {_UTC_DAY_SQL}, 0, 'released', NOW(), NOW(), %s) "
                f"ON CONFLICT (ticket_id) DO NOTHING",
                (ticket_id, _INSTANCE),
            )
            return "tombstone"
        day, est, state = row
        if state not in ("reserved", "expired"):
            return "noop"
        cur.execute(
            "UPDATE ai_budget_reservations SET state = 'released', closed_at = NOW() "
            "WHERE ticket_id = %s",
            (ticket_id,),
        )
        if state == "expired":
            _add_day(cur, day, unknown=-_num(est))
        return "released"


def mark_ai_budget_unknown(ticket_id: str) -> str:
    """Natijasi noma'lum (timeout/bekor): bron summasi hisobda QOLADI. Idempotent.

    ``wait_for`` timeout'i provayder xarajatini nol deb isbotlamaydi, shuning
    uchun bunday ticket qaytarilmaydi. Qaytadi: ``unknown`` | ``noop`` | ``missing``.
    """
    with db_transaction() as cur:
        row = _lock_ticket(cur, ticket_id)
        if row is None:
            return "missing"
        day, est, state = row
        if state not in ("reserved", "expired"):
            return "noop"
        cur.execute(
            "UPDATE ai_budget_reservations SET state = 'unknown', closed_at = NOW() "
            "WHERE ticket_id = %s",
            (ticket_id,),
        )
        if state == "reserved":
            _add_day(cur, day, unknown=_num(est))
        return "unknown"


def get_ai_budget_status(day=None) -> dict | None:
    """Kun holati (diagnostika): ``spent/assumed/unknown/open/used``. Xatoda ``None``."""
    try:
        with db_transaction(commit=False) as cur:
            if day is None:
                cur.execute(f"SELECT {_UTC_DAY_SQL}")  # nosec B608 — kod-konstanta
                day = cur.fetchone()[0]
            cur.execute(
                "SELECT COALESCE((SELECT spent_usd FROM ai_budget_days WHERE day=%s),0), "
                "COALESCE((SELECT assumed_usd FROM ai_budget_days WHERE day=%s),0), "
                "COALESCE((SELECT unknown_usd FROM ai_budget_days WHERE day=%s),0), "
                "COALESCE((SELECT SUM(est_usd) FROM ai_budget_reservations "
                "          WHERE state='reserved' AND day=%s),0)",
                (day, day, day, day),
            )
            spent, assumed, unknown, open_ = (_num(v) for v in cur.fetchone())
        return {"day": str(day), "spent_usd": spent, "assumed_usd": assumed,
                "unknown_usd": unknown, "open_usd": open_,
                "used_usd": round(spent + assumed + unknown + open_, 6)}
    except Exception as exc:  # noqa: BLE001
        logger.error("get_ai_budget_status xatosi: %s", exc)
        return None


__all__ = [
    "AI_BUDGET_LOCK_KEY", "get_ai_budget_status", "mark_ai_budget_unknown",
    "release_ai_budget", "reserve_ai_budget", "settle_ai_budget",
]
