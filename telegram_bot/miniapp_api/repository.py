"""Mini App uchun FAQAT-O'QISH so'rovlari (kursor ``db.ReadOnlyRunner`` beradi).

Mavjud ``get_user_channels`` / ``get_queue_posts`` ishlatilmaydi: ular xatoni
yutib ``[]`` qaytaradi (DB xatosi "kanal yo'q" bo'lib ko'rinardi), birinchisi
esa keshlanadi. Bu yerda har bir so'rov xatoda istisno ko'taradi va egalik sharti
(``user_id = %s``) SQL ichida turadi.

Ishlatilgan ustunlar ``schema.sql`` dan: users(user_id, username, full_name,
language_code, plan_type, subscription_expires_at, role, ai_credits,
ai_requests_today, last_limit_reset, deleted_at), channels(channel_id,
channel_title, is_active, deleted_at, user_id), scheduled_posts(id, user_id,
channel_id, post_type, content, file_id, scheduled_time, status,
user_post_number, recurrence_type), system_settings(key, value).
"""
from __future__ import annotations

CHANNELS_HARD_LIMIT = 200
MAX_OFFSET = 100_000
PREVIEW_CHARS = 200


def load_account(cur, user_id: int) -> dict | None:
    cur.execute(
        """
        SELECT user_id, username, full_name, language_code, plan_type,
               subscription_expires_at, role, COALESCE(ai_credits, 0),
               CASE WHEN last_limit_reset >= CURRENT_DATE
                    THEN COALESCE(ai_requests_today, 0) ELSE 0 END,
               (deleted_at IS NOT NULL), NOW()
          FROM users WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "user_id": row[0], "username": row[1], "full_name": row[2],
        "language_code": row[3], "plan_type": row[4],
        "subscription_expires_at": row[5], "role": row[6],
        "ai_credits": int(row[7] or 0), "ai_requests_today": int(row[8] or 0),
        "deleted": bool(row[9]), "db_now": row[10],
    }


def channel_owned(cur, user_id: int, channel_id: str) -> bool:
    cur.execute(
        "SELECT 1 FROM channels WHERE user_id = %s AND channel_id = %s "
        "AND is_active = TRUE AND deleted_at IS NULL LIMIT 1",
        (user_id, str(channel_id)),
    )
    return cur.fetchone() is not None


def channel_title(cur, user_id: int, channel_id: str):
    """Egasining faol kanali nomi; kanal yo'q / begona / o'chirilgan bo'lsa ``None`` (egalik tekshiruvi shu yerda)."""
    cur.execute(
        "SELECT channel_title FROM channels WHERE user_id = %s AND channel_id = %s "
        "AND is_active = TRUE AND deleted_at IS NULL LIMIT 1",
        (user_id, str(channel_id)),
    )
    row = cur.fetchone()
    return None if row is None else (row[0] or "")


def member_history(cur, channel_id: str, since) -> list[dict]:
    """Obunachilar snapshot'lari (yangidan eskiga). Egalik chaqiruvchi tomonidan ``channel_title`` bilan tekshirilgan."""
    cur.execute(
        "SELECT snapshot_date, member_count, source, collected_at FROM channel_member_counts "
        "WHERE channel_id = %s AND snapshot_date >= %s ORDER BY snapshot_date DESC LIMIT 400",
        (str(channel_id), since),
    )
    return [{"date": r[0].isoformat(), "member_count": int(r[1]), "source": r[2],
             "collected_at": r[3].isoformat() if r[3] else None} for r in cur.fetchall()]


def channel_post_counts(cur, user_id: int, channel_id: str) -> dict:
    """Botning O'Z postlari bo'yicha hisob (kanalning haqiqiy natijasi EMAS): shu kanal va shu egasi."""
    cur.execute(
        "SELECT "
        "COUNT(*) FILTER (WHERE status = 'posted' AND scheduled_time >= NOW() - INTERVAL '7 days'), "
        "COUNT(*) FILTER (WHERE status = 'posted' AND scheduled_time >= NOW() - INTERVAL '30 days'), "
        "COUNT(*) FILTER (WHERE status = 'posted'), "
        "COUNT(*) FILTER (WHERE status = 'pending'), "
        "COUNT(*) FILTER (WHERE status = 'failed'), "
        "COUNT(*) FILTER (WHERE status = 'unknown') "
        "FROM scheduled_posts WHERE user_id = %s AND channel_id = %s",
        (user_id, str(channel_id)),
    )
    r = cur.fetchone() or (0, 0, 0, 0, 0, 0)
    keys = ("sent_7d", "sent_30d", "sent_all", "pending", "failed", "unknown")
    return {k: int(v or 0) for k, v in zip(keys, r)}


def views_summary(cur, channel_id: str) -> dict:
    """Ko'rishlar xulosasi — FAQAT manbasi (``views_source``) bor qiymatlar bo'yicha.

    Eski soxta ``0`` (manbasiz) va ``NULL`` hisobga olinmaydi: ular "o'lchanmagan". Oxirgi 90 kun.
    """
    cur.execute(
        "SELECT COUNT(*) FILTER (WHERE views_source IS NOT NULL AND views IS NOT NULL), "
        "AVG(views) FILTER (WHERE views_source IS NOT NULL), "
        "MAX(views) FILTER (WHERE views_source IS NOT NULL), "
        "MAX(views_collected_at), "
        "ARRAY_AGG(DISTINCT views_source) FILTER (WHERE views_source IS NOT NULL) "
        "FROM channel_posts_history WHERE channel_id = %s AND post_date >= NOW() - INTERVAL '90 days'",
        (str(channel_id),),
    )
    r = cur.fetchone() or (0, None, None, None, None)
    count = int(r[0] or 0)
    return {
        "available": count > 0,
        "with_views": count,
        "avg": round(float(r[1]), 1) if count and r[1] is not None else None,
        "max": int(r[2]) if count and r[2] is not None else None,
        "collected_at": r[3].isoformat() if (count and r[3]) else None,
        "sources": sorted(r[4]) if (count and r[4]) else [],
    }


def count_channels(cur, user_id: int) -> int:
    cur.execute(
        "SELECT COUNT(*) FROM channels "
        "WHERE user_id = %s AND is_active = TRUE AND deleted_at IS NULL",
        (user_id,),
    )
    return int(cur.fetchone()[0])


MEMBERS_FRESH_DAYS = 8  # 7 kun + Toshkent/DB sana zonasi farqi uchun 1 kun zaxira


def list_channels(cur, user_id: int) -> list[dict]:
    """Faol kanallar + kanal bo'yicha: rejadagi postlar soni va OXIRGI obunachi snapshot'i.

    `members` faqat `MEMBERS_FRESH_DAYS` kundan eski bo'lmagan snapshot bo'lsa beriladi; aks holda `None`
    (eskirgan raqam "joriy" deb ko'rsatilmaydi, 0 ham to'qilmaydi).
    """
    cur.execute(
        "SELECT c.channel_id, c.channel_title, "
        "       (SELECT COUNT(*) FROM scheduled_posts sp "
        "         WHERE sp.user_id = c.user_id AND sp.channel_id = c.channel_id AND sp.status = 'pending'), "
        "       m.member_count, m.snapshot_date "
        "  FROM channels c "
        "  LEFT JOIN LATERAL (SELECT member_count, snapshot_date FROM channel_member_counts "
        "                      WHERE channel_id = c.channel_id AND snapshot_date >= CURRENT_DATE - %s "
        "                      ORDER BY snapshot_date DESC LIMIT 1) m ON TRUE "
        " WHERE c.user_id = %s AND c.is_active = TRUE AND c.deleted_at IS NULL "
        " ORDER BY c.id ASC LIMIT %s",
        (MEMBERS_FRESH_DAYS, user_id, CHANNELS_HARD_LIMIT),
    )
    return [{"id": str(r[0]), "title": r[1], "pending_posts": int(r[2]),
             "members": int(r[3]) if r[3] is not None else None,
             "members_as_of": r[4].isoformat() if r[4] is not None else None}
            for r in cur.fetchall()]


def pending_summary(cur, user_id: int) -> tuple[int, object]:
    cur.execute(
        "SELECT COUNT(*), MIN(scheduled_time) FROM scheduled_posts "
        "WHERE user_id = %s AND status = 'pending'",
        (user_id,),
    )
    row = cur.fetchone()
    return int(row[0]), row[1]


# Tarix = yakunlangan holatlar (schema.sql: chk_scheduled_posts_status).
HISTORY_STATUSES = ("posted", "published", "completed", "failed", "cancelled")
SENT_STATUSES = ("posted", "published", "completed")

_POST_SELECT = """
        SELECT sp.id, sp.channel_id, c.channel_title, sp.post_type,
               LEFT(COALESCE(sp.content, ''), %s), (sp.file_id IS NOT NULL),
               sp.scheduled_time, sp.user_post_number, sp.recurrence_type, sp.status,
               sp.recurrence_day, sp.recurrence_time
          FROM scheduled_posts sp
          LEFT JOIN channels c
                 ON c.channel_id = sp.channel_id AND c.user_id = sp.user_id
"""


def _post_dict(r) -> dict:
    return {"id": r[0], "channel_id": str(r[1]), "channel_title": r[2],
            "post_type": r[3], "preview": r[4], "has_media": bool(r[5]),
            "scheduled_time": r[6], "number": r[7], "recurrence": r[8],
            "status": r[9], "recurrence_day": r[10],
            "recurrence_time": r[11].strftime("%H:%M") if r[11] is not None else None}


def count_posts(cur, user_id: int, history: bool) -> int:
    if history:
        cur.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = ANY(%s)",
            (user_id, list(HISTORY_STATUSES)),
        )
    else:
        cur.execute(
            "SELECT COUNT(*) FROM scheduled_posts WHERE user_id = %s AND status = 'pending'",
            (user_id,),
        )
    return int(cur.fetchone()[0])


def list_posts(cur, user_id: int, history: bool, limit: int, offset: int) -> list[dict]:
    if history:
        cur.execute(
            _POST_SELECT + " WHERE sp.user_id = %s AND sp.status = ANY(%s)"
            " ORDER BY sp.scheduled_time DESC, sp.id DESC OFFSET %s LIMIT %s",
            (PREVIEW_CHARS, user_id, list(HISTORY_STATUSES), offset, limit),
        )
    else:
        cur.execute(
            _POST_SELECT + " WHERE sp.user_id = %s AND sp.status = 'pending'"
            " ORDER BY sp.scheduled_time ASC, sp.id ASC OFFSET %s LIMIT %s",
            (PREVIEW_CHARS, user_id, offset, limit),
        )
    return [_post_dict(r) for r in cur.fetchall()]


CALENDAR_LIMIT = 500


def list_posts_between(cur, user_id: int, start, end, limit: int | None = None) -> list[dict]:
    """Kutilayotgan postlar [start, end) oralig'ida (faqat egasiniki), vaqt bo'yicha o'sish tartibida.

    `limit + 1` qator so'raladi: chaqiruvchi kesilganini (`truncated`) halol bildiradi.
    """
    limit = CALENDAR_LIMIT if limit is None else limit
    cur.execute(
        _POST_SELECT + " WHERE sp.user_id = %s AND sp.status = 'pending'"
        " AND sp.scheduled_time >= %s AND sp.scheduled_time < %s"
        " ORDER BY sp.scheduled_time ASC, sp.id ASC LIMIT %s",
        (PREVIEW_CHARS, user_id, start, end, limit + 1),
    )
    return [_post_dict(r) for r in cur.fetchall()]


def list_pending_posts(cur, user_id: int, limit: int, offset: int) -> list[dict]:
    return list_posts(cur, user_id, False, limit, offset)


def get_post(cur, user_id: int, post_id: int) -> dict | None:
    """Postni EGASI bo'yicha oladi (boshqa foydalanuvchi posti -> None)."""
    cur.execute(_POST_SELECT + " WHERE sp.id = %s AND sp.user_id = %s",
                (PREVIEW_CHARS, int(post_id), user_id))
    row = cur.fetchone()
    if not row:
        return None
    post = _post_dict(row)
    # Tahrirlash uchun TO'LIQ matn (ro'yxatda faqat qisqa ko'rinish): egasi sharti yana SQL ichida.
    cur.execute("SELECT COALESCE(content, '') FROM scheduled_posts WHERE id = %s AND user_id = %s",
                (int(post_id), user_id))
    full = cur.fetchone()
    post["text"] = full[0] if full else post["preview"]
    return post


def post_status_counts(cur, user_id: int) -> dict:
    """Postlar soni (faqat haqiqiy DB holatlari; qoralama tushunchasi bu jadvalda yo'q)."""
    cur.execute(
        "SELECT status, COUNT(*) FROM scheduled_posts WHERE user_id = %s GROUP BY status",
        (user_id,),
    )
    by_status = {str(r[0]): int(r[1]) for r in cur.fetchall()}
    return {
        "pending": by_status.get("pending", 0),
        "sent": sum(by_status.get(k, 0) for k in SENT_STATUSES),
        "failed": by_status.get("failed", 0),
        "cancelled": by_status.get("cancelled", 0),
    }
