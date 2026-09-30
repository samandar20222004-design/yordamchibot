# -*- coding: utf-8 -*-
"""
=====================================================================
 🔐 AUDIT — xavfsizlik ro'llari, audit loglari, qo'llab-quvvatlash
=====================================================================

Admin rollari (RBAC), xavfsizlik/audit loglari (``admin_audit_logs``), bot bo'yicha tizim statistikasi va qo'llab-quvvatlash murojaatlari (ticket).

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import json
import logging


from database import DB_STATS_CACHE_TTL, _MISS
from repositories.runtime import (  # noqa: F401
    _cache_get, _cache_set, db_cursor
)

logger = logging.getLogger(__name__)


# ====================================================================
# 🔐 AUDIT — xavfsizlik ro'llari, audit loglari, qo'llab-quvvatlash
# ====================================================================

# --- STATS ---
def get_system_stats() -> dict:
    cache_key = "system_stats"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    stats = {"users": 0, "channels": 0, "pending": 0, "sent": 0, "cancelled": 0, "failed": 0, "sponsors": 0}
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            stats["users"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
            stats["channels"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM sponsor_channels WHERE is_active = TRUE")
            stats["sponsors"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
            stats["pending"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'posted'")
            stats["sent"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'cancelled'")
            stats["cancelled"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'failed'")
            stats["failed"] = cur.fetchone()[0]
        _cache_set(cache_key, stats, DB_STATS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Statistika xatosi: {e}")
    return stats


def get_admin_dashboard_stats() -> dict:
    """Admin panel dashboard uchun kengaytirilgan statistika."""
    cache_key = "admin_dashboard_stats"
    cached = _cache_get(cache_key)
    if cached is not _MISS:
        return cached
    stats = {
        "users": 0, "pro_subscribers": 0, "channels": 0,
        "posts_today": 0, "pending_posts": 0, "stars_revenue": 0,
    }
    try:
        with db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            stats["users"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE plan_type IN ('pro', 'enterprise') "
                "AND (subscription_expires_at IS NULL OR subscription_expires_at > NOW())"
            )
            stats["pro_subscribers"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
            stats["channels"] = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM scheduled_posts "
                "WHERE status = 'posted' AND scheduled_time >= CURRENT_DATE"
            )
            stats["posts_today"] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
            stats["pending_posts"] = cur.fetchone()[0]
            # Stars revenue: endi alohida payments jadvalidan yig'iladi
            # (promo_codes jadvalidagi STARS_ yozuvlari bilan emas).
            cur.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM payments WHERE currency = 'XTR'"
            )
            stats["stars_revenue"] = cur.fetchone()[0]
        _cache_set(cache_key, stats, DB_STATS_CACHE_TTL)
    except Exception as e:
        logger.error(f"Admin dashboard stats xatosi: {e}")
    return stats


# ============================================================
# POSTASSIST V2 — 6-BOSQICH: RBAC VA ADMIN AUDITI (DB CRUD)
# ------------------------------------------------------------
# Rollar ``admin_roles`` jadvalida saqlanadi (asosiy manba) va
# ``users.role`` ustunida aks ettiriladi (ko'rinish/moslik uchun).
# Admin harakatlari ``admin_audit_logs`` jadvaliga yoziladi.
# Biznes mantiq ``services/rbac_service.py`` va
# ``services/audit_service.py`` da; bu yerda faqat CRUD.
# ============================================================

#: Audit yozuvi uchun maydon chegaralari (jadval ustunlari bilan bir xil).
AUDIT_ACTION_MAX_LEN = 64


AUDIT_FIELD_MAX_LEN = 64


def _valid_admin_role(value):
    """Rol qiymatini tekshiradi (``services.rbac_service`` bilan bir xil to'plam)."""
    from services.rbac_service import parse_role
    return parse_role(value)


def get_admin_role(user_id):
    """Foydalanuvchining DB'dagi rolini qaytaradi (``None`` — rol yo'q).

    Avval ``admin_roles`` jadvali (aniq berilgan rol), keyin ``users.role``
    ustuni o'qiladi. Har qanday xato (jadval/ustun yo'q, DB uzilgan) —
    ``None``: RBAC qatlami legacy ``ADMIN_IDS`` ro'yxatiga tayanib ishlayveradi.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        with db_cursor() as cur:
            cur.execute("SELECT role FROM admin_roles WHERE user_id = %s", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.debug("get_admin_role(%s) admin_roles o'qishda xato: %s", uid, e)
    try:
        with db_cursor() as cur:
            cur.execute("SELECT role FROM users WHERE user_id = %s", (uid,))
            row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    except Exception as e:
        logger.debug("get_admin_role(%s) users.role o'qishda xato: %s", uid, e)
    return None


def set_admin_role(user_id, role, granted_by=None) -> bool:
    """Foydalanuvchiga rol beradi (upsert) va ``users.role`` ni yangilaydi.

    ``users`` jadvalidagi yozuv bo'lmasa ham rol saqlanadi (faqat
    ``admin_roles`` qatori qo'shiladi) — foydalanuvchi botga hali
    kirmagan bo'lishi mumkin.
    """
    parsed = _valid_admin_role(role)
    if parsed is None:
        return False
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    try:
        actor = int(granted_by) if granted_by is not None else None
    except (TypeError, ValueError):
        actor = None

    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO admin_roles (user_id, role, granted_by, granted_at, updated_at)
                VALUES (%s, %s, %s, NOW(), NOW())
                ON CONFLICT (user_id) DO UPDATE
                    SET role = EXCLUDED.role,
                        granted_by = EXCLUDED.granted_by,
                        updated_at = NOW()
                """,
                (uid, parsed.value, actor),
            )
            # users.role — ko'rinish uchun nusxa. Ich-ma-ich blok SAVEPOINT
            # ochadi: eski bazada ustun bo'lmasa faqat shu qism qaytariladi,
            # asosiy (admin_roles) yozuvi saqlanib qoladi.
            try:
                with db_cursor(commit=True) as mirror_cur:
                    mirror_cur.execute(
                        "UPDATE users SET role = %s WHERE user_id = %s",
                        (parsed.value, uid),
                    )
            except Exception as e:
                logger.debug("users.role yangilanmadi (user=%s): %s", uid, e)
        try:
            from services.rbac_service import invalidate_role_cache
            invalidate_role_cache(uid)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.error("set_admin_role xatosi (user=%s, role=%s): %s", uid, parsed, e)
        return False


def delete_admin_role(user_id) -> bool:
    """Foydalanuvchi rolini o'chiradi (``users.role`` → 'user')."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM admin_roles WHERE user_id = %s", (uid,))
            deleted = cur.rowcount > 0
            try:
                with db_cursor(commit=True) as mirror_cur:
                    mirror_cur.execute(
                        "UPDATE users SET role = 'user' WHERE user_id = %s", (uid,)
                    )
            except Exception as e:
                logger.debug("users.role tozalanmadi (user=%s): %s", uid, e)
        try:
            from services.rbac_service import invalidate_role_cache
            invalidate_role_cache(uid)
        except Exception:
            pass
        return bool(deleted)
    except Exception as e:
        logger.error("delete_admin_role xatosi (user=%s): %s", uid, e)
        return False


def list_admin_roles(limit: int = 100) -> list:
    """``admin_roles`` jadvalidagi rollar ro'yxati (yangilari birinchi)."""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 100
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT user_id, role, granted_by, granted_at, updated_at "
                "FROM admin_roles ORDER BY updated_at DESC NULLS LAST LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall() or []
        return [
            {
                "user_id": int(row[0]),
                "role": str(row[1]),
                "granted_by": int(row[2]) if row[2] is not None else None,
                "granted_at": row[3],
                "updated_at": row[4],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("list_admin_roles xatosi: %s", e)
        return []


def log_admin_action(admin_id, action, target_type=None, target_id=None,
                     old_value=None, new_value=None, ip_or_metadata=None,
                     cur=None) -> bool:
    """Admin harakatini ``admin_audit_logs`` jadvaliga yozadi.

    ``cur`` berilsa — chaqiruvchining tranzaksiyasida (ATOMIK: biznes amali
    bilan birga commit/rollback bo'ladi). Berilmasa — o'z tranzaksiyasida.
    JSONB qiymatlar ``json.dumps`` orqali uzatiladi (``%s::jsonb``).
    """
    try:
        actor = int(admin_id)
    except (TypeError, ValueError):
        return False
    if actor <= 0:
        return False
    act = str(action or "").strip()[:AUDIT_ACTION_MAX_LEN]
    if not act:
        return False

    def _dump(value):
        if value is None:
            return None
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"_repr": str(value)}, ensure_ascii=False)

    params = (
        actor,
        act,
        (str(target_type).strip()[:AUDIT_FIELD_MAX_LEN] or None)
        if target_type is not None else None,
        (str(target_id).strip()[:AUDIT_FIELD_MAX_LEN] or None)
        if target_id is not None else None,
        _dump(old_value),
        _dump(new_value),
        _dump(ip_or_metadata),
    )
    sql = (
        "INSERT INTO admin_audit_logs (admin_id, action, target_type, target_id, "
        "old_value, new_value, ip_or_metadata) "
        "VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
    )
    if cur is not None:
        # Chaqiruvchi tranzaksiyasi ichida — xato yutilmaydi (ROLLBACK kafolati).
        cur.execute(sql, params)
        return True
    try:
        with db_cursor(commit=True) as own_cur:
            own_cur.execute(sql, params)
        return True
    except Exception as e:
        logger.error("log_admin_action xatosi (admin=%s, action=%s): %s", actor, act, e)
        return False


def get_admin_audit_logs(limit: int = 50, admin_id=None, action=None) -> list:
    """Audit yozuvlarini o'qish (eng yangisi birinchi)."""
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = 50

    where = []
    params = []
    if admin_id is not None:
        try:
            where.append("admin_id = %s")
            params.append(int(admin_id))
        except (TypeError, ValueError):
            pass
    if action:
        where.append("action = %s")
        params.append(str(action).strip()[:AUDIT_ACTION_MAX_LEN])
    sql = (
        "SELECT id, admin_id, action, target_type, target_id, old_value, "
        "new_value, ip_or_metadata, created_at FROM admin_audit_logs"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT %s"
    params.append(limit)

    try:
        with db_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall() or []
        return [
            {
                "id": int(row[0]),
                "admin_id": int(row[1]),
                "action": row[2],
                "target_type": row[3],
                "target_id": row[4],
                "old_value": row[5],
                "new_value": row[6],
                "ip_or_metadata": row[7],
                "created_at": row[8],
            }
            for row in rows
        ]
    except Exception as e:
        logger.error("get_admin_audit_logs xatosi: %s", e)
        return []


def count_admin_audit_logs(admin_id=None, action=None) -> int:
    """Audit yozuvlari soni (filtrlar ixtiyoriy)."""
    where = []
    params = []
    if admin_id is not None:
        try:
            where.append("admin_id = %s")
            params.append(int(admin_id))
        except (TypeError, ValueError):
            pass
    if action:
        where.append("action = %s")
        params.append(str(action).strip()[:AUDIT_ACTION_MAX_LEN])
    sql = "SELECT COUNT(*) FROM admin_audit_logs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    try:
        with db_cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error("count_admin_audit_logs xatosi: %s", e)
        return 0


#: Bazaga yoziladigan murojaat matnining maksimal uzunligi (Telegram 4096 +
#: admin xabaridagi sarlavha uchun zaxira bilan).
SUPPORT_TICKET_TEXT_LIMIT = 4000


def _support_ticket_row_to_dict(row) -> dict:
    """``support_tickets`` qatorini dict ko'rinishiga o'giradi."""
    return {
        "id": int(row[0]),
        "user_id": int(row[1] or 0),
        "username": row[2] or "",
        "message_text": row[3] or "",
        "has_media": bool(row[4]),
        "status": row[5] or "new",
        "created_at": row[6],
        "answered_at": row[7],
        "answered_by": int(row[8]) if row[8] else 0,
    }


def create_support_ticket(
    user_id: int,
    username: str | None = None,
    message_text: str = "",
    has_media: bool = False,
) -> int:
    """Yangi bir martalik murojaatni saqlaydi.

    Qaytadi: ``ticket_id`` yoki ``0`` (xato). Bo'sh murojaat ham qabul
    qilinadi (rasm + izohsiz holat) — matn o'rniga bo'sh satr yoziladi.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return 0
    if not uid:
        return 0
    uname = str(username or "").strip().lstrip("@")[:64]
    text = str(message_text or "").strip()[:SUPPORT_TICKET_TEXT_LIMIT]
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO support_tickets
                    (user_id, username, message_text, has_media, status)
                VALUES (%s, %s, %s, %s, 'new')
                RETURNING id
                """,
                (uid, uname or None, text, bool(has_media)),
            )
            return int(cur.fetchone()[0])
    except Exception as e:
        logger.error("create_support_ticket xatosi (user=%s): %s", uid, e)
        return 0


def attach_support_ticket_delivery(
    ticket_id: int,
    admin_chat_id: int,
    admin_message_id: int,
) -> bool:
    """Admin chatidagi yuborilgan xabar ID'sini murojaatga bog'laydi.

    Idempotent: bir xil (admin_chat_id, admin_message_id) qayta yozilsa
    mavjud qator yangilanadi (UNIQUE cheklovi bilan).
    """
    try:
        tid = int(ticket_id)
        chat_id = int(admin_chat_id)
        msg_id = int(admin_message_id)
    except (TypeError, ValueError):
        return False
    if not tid or not chat_id or not msg_id:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO support_ticket_deliveries
                    (ticket_id, admin_chat_id, admin_message_id)
                VALUES (%s, %s, %s)
                ON CONFLICT (admin_chat_id, admin_message_id)
                DO UPDATE SET ticket_id = EXCLUDED.ticket_id,
                              delivered_at = NOW()
                """,
                (tid, chat_id, msg_id),
            )
            return True
    except Exception as e:
        logger.error("attach_support_ticket_delivery xatosi (ticket=%s): %s", ticket_id, e)
        return False


def get_support_ticket(ticket_id: int) -> dict | None:
    """Murojaatni ID bo'yicha qaytaradi (topilmasa ``None``)."""
    try:
        tid = int(ticket_id)
    except (TypeError, ValueError):
        return None
    if not tid:
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, username, message_text, has_media, status,
                       created_at, answered_at, answered_by
                  FROM support_tickets
                 WHERE id = %s
                """,
                (tid,),
            )
            row = cur.fetchone()
        return _support_ticket_row_to_dict(row) if row else None
    except Exception as e:
        logger.error("get_support_ticket xatosi (ticket=%s): %s", ticket_id, e)
        return None


def get_support_ticket_by_admin_message(
    admin_chat_id: int,
    admin_message_id: int,
) -> dict | None:
    """Admin chatidagi xabar ID'si orqali murojaatni topadi.

    «Reply» (Javob berish) kuzatuvining YAGONA manbai: admin bot
    yuborgan murojaat xabariga javob yozganda, bot shu funksiya orqali
    murojaat egasini (``user_id``) aniqlaydi.
    """
    try:
        chat_id = int(admin_chat_id)
        msg_id = int(admin_message_id)
    except (TypeError, ValueError):
        return None
    if not chat_id or not msg_id:
        return None
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT t.id, t.user_id, t.username, t.message_text,
                       t.has_media, t.status, t.created_at, t.answered_at,
                       t.answered_by
                  FROM support_ticket_deliveries d
                  JOIN support_tickets t ON t.id = d.ticket_id
                 WHERE d.admin_chat_id = %s AND d.admin_message_id = %s
                """,
                (chat_id, msg_id),
            )
            row = cur.fetchone()
        return _support_ticket_row_to_dict(row) if row else None
    except Exception as e:
        logger.error(
            "get_support_ticket_by_admin_message xatosi (chat=%s, msg=%s): %s",
            admin_chat_id, admin_message_id, e,
        )
        return None


def mark_support_ticket_answered(ticket_id: int, admin_id: int) -> bool:
    """Murojaatga javob berilganini qayd etadi (birinchi javob vaqti saqlanadi).

    Takroriy javoblar ham qabul qilinadi: ``answered_at`` faqat BIRINCHI
    javobda yoziladi (``COALESCE``), ``answered_by`` esa oxirgi javob bergan
    adminni ko'rsatadi.
    """
    try:
        tid = int(ticket_id)
        aid = int(admin_id)
    except (TypeError, ValueError):
        return False
    if not tid:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE support_tickets
                   SET status = 'answered',
                       answered_at = COALESCE(answered_at, NOW()),
                       answered_by = %s
                 WHERE id = %s
                """,
                (aid or None, tid),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("mark_support_ticket_answered xatosi (ticket=%s): %s", ticket_id, e)
        return False


def count_user_support_tickets(user_id: int, since_hours: int = 24) -> int:
    """Foydalanuvchining oxirgi ``since_hours`` soatdagi murojaatlari soni.

    Anti-spam nazorati uchun (soft limit): chaqiruvchi tomonda ishlatiladi,
    bu funksiya faqat hisoblaydi va hech qachon istisno ko'tarmaydi.
    """
    try:
        uid = int(user_id)
        hours = max(1, min(int(since_hours), 24 * 30))
    except (TypeError, ValueError):
        return 0
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM support_tickets
                 WHERE user_id = %s
                   AND created_at >= NOW() - make_interval(hours => %s)
                """,
                (uid, hours),
            )
            return int(cur.fetchone()[0] or 0)
    except Exception as e:
        logger.error("count_user_support_tickets xatosi (user=%s): %s", user_id, e)
        return 0


def get_recent_support_tickets(limit: int = 20) -> list[dict]:
    """Oxirgi murojaatlar ro'yxati (admin panel/diagnostika uchun)."""
    try:
        safe_limit = max(1, min(int(limit), 100))
    except (TypeError, ValueError):
        safe_limit = 20
    try:
        with db_cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, username, message_text, has_media, status,
                       created_at, answered_at, answered_by
                  FROM support_tickets
                 ORDER BY created_at DESC, id DESC
                 LIMIT %s
                """,
                (safe_limit,),
            )
            return [_support_ticket_row_to_dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_recent_support_tickets xatosi: %s", e)
        return []