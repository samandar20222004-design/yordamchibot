# -*- coding: utf-8 -*-
"""
=====================================================================
 👥 TEAMS — jamoa a'zolari, rollar, taklif/tasdiq oqimi, audens insight
=====================================================================

Kanal a'zolari va ularning rollari (owner/editor/scheduler/analyst), post taklif -> tasdiq -> nashr ish jarayoni va audens savollari insightlari.

Qatlam: REPOSITORY — domain ma'lumotlariga kirish.

Bu modul yadroga (``database``: pool / tranzaksiya / kesh / sxema)
``repositories.runtime`` orqali **kech bog'lanadi**: ``db_cursor``,
``transaction``, ``_cache_*`` va boshqa yadro yordamchilari chaqiruv
paytida ``database`` modulining joriy atributiga qarab yuradi. Shu
sabab ``unittest.mock.patch("database.db_cursor")`` kabi mavjud mock
nuqtalari bu modulga ko'chirilgandan keyin ham kuchini yo'qotmaydi.
"""

import logging

from repositories.runtime import (  # noqa: F401
    _cache_clear, db_cursor, get_channel_owner_id
)

logger = logging.getLogger(__name__)


# ====================================================================
# 👥 TEAMS — jamoa a'zolari, rollar, taklif/tasdiq oqimi, audens insight
# ====================================================================

# ============================================================
# PHASE E — TEAM ROLES, APPROVAL WORKFLOW & WEEKLY ADVISOR DATA
# ============================================================
# These CRUD helpers are additive.  Existing single-owner helpers above remain
# unchanged; the owner is always inferred from channels.user_id when needed.

TEAM_ROLES = ("owner", "editor", "scheduler", "analyst")


def _invalidate_rbac_resource_cache(user_id=None, channel_id=None) -> None:
    """PHASE 3 — RBAC resurs (kanal) keshini bekor qiladi.

    A'zolik yoki kanal egaligi o'zgarganda chaqiriladi: rol o'zgarishi darhol
    kuchga kirishi kerak (kesh TTL'i kutib o'tirilmaydi).  Import sikli va
    xatolar jim yutiladi — bu shunchaki kesh, biznes amal emas.
    """
    try:
        from services import rbac_service
        rbac_service.invalidate_resource_cache(user_id, channel_id)
    except Exception:  # pragma: no cover - kesh xatosi amalni to'xtatmaydi
        logger.debug("RBAC resurs keshini tozalab bo'lmadi", exc_info=True)


def _member_role_valid(role):
    value = str(role or "").strip().lower()
    return value if value in TEAM_ROLES else None


def get_channel_member(channel_id: str | int, user_id: int):
    """Return ``(id, channel_id, user_id, role, created_at)`` or ``None``."""
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, channel_id, user_id, role, created_at "
                "FROM channel_members WHERE channel_id = %s AND user_id = %s",
                (str(channel_id), int(user_id)),
            )
            return cur.fetchone()
    except Exception as e:
        logger.error("get_channel_member xatosi: %s", e)
        return None


def list_channel_members(channel_id: str | int) -> list:
    try:
        with db_cursor() as cur:
            cur.execute(
                "SELECT id, channel_id, user_id, role, created_at "
                "FROM channel_members WHERE channel_id = %s ORDER BY created_at, id",
                (str(channel_id),),
            )
            return cur.fetchall()
    except Exception as e:
        logger.error("list_channel_members xatosi: %s", e)
        return []


def get_channel_member_role(channel_id: str | int, user_id: int) -> str | None:
    row = get_channel_member(channel_id, user_id)
    try:
        return _member_role_valid(row[3]) if row else None
    except (IndexError, TypeError):
        return None


def add_channel_member(channel_id: str | int, user_id: int, role: str = "editor",
                       granted_by: int | None = None):
    """Add/update a member. ``granted_by`` is checked when supplied.

    The owner is not inserted as an ordinary member, preventing an editor from
    replacing the owner role.  Unique(channel_id,user_id) makes retries safe.
    """
    ch = str(channel_id or "").strip()
    normalized = _member_role_valid(role)
    if not ch or normalized in (None, "owner"):
        return None
    try:
        if granted_by is not None:
            owner = get_channel_owner_id(ch)
            if owner is None or int(owner) != int(granted_by):
                return None
        with db_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO channel_members (channel_id, user_id, role)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (channel_id, user_id) DO UPDATE
                     SET role = EXCLUDED.role
                   RETURNING id, channel_id, user_id, role, created_at""",
                (ch, int(user_id), normalized),
            )
            row = cur.fetchone()
        # 🔐 PHASE 3: rol darhol kuchga kirishi uchun RBAC keshini bekor qilamiz.
        _invalidate_rbac_resource_cache(user_id, ch)
        return row
    except Exception as e:
        logger.error("add_channel_member xatosi: %s", e)
        return None


def remove_channel_member(channel_id: str | int, user_id: int,
                          removed_by: int | None = None) -> bool:
    try:
        ch = str(channel_id or "")
        if removed_by is not None:
            owner = get_channel_owner_id(ch)
            if owner is None or int(owner) != int(removed_by):
                return False
        with db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM channel_members WHERE channel_id = %s AND user_id = %s",
                        (ch, int(user_id)))
            removed = cur.rowcount > 0
        if removed:
            # 🔐 PHASE 3: a'zolik olib tashlandi — ruxsat darhol bekor bo'lsin.
            _invalidate_rbac_resource_cache(user_id, ch)
        return removed
    except Exception as e:
        logger.error("remove_channel_member xatosi: %s", e)
        return False


def set_channel_member_role(channel_id: str | int, user_id: int, role: str,
                             changed_by: int | None = None) -> bool:
    normalized = _member_role_valid(role)
    if normalized in (None, "owner"):
        return False
    try:
        if changed_by is not None:
            owner = get_channel_owner_id(channel_id)
            if owner is None or int(owner) != int(changed_by):
                return False
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE channel_members SET role = %s WHERE channel_id = %s AND user_id = %s",
                        (normalized, str(channel_id), int(user_id)))
            changed = cur.rowcount > 0
        if changed:
            # 🔐 PHASE 3: yangi rol darhol kuchga kirishi kerak.
            _invalidate_rbac_resource_cache(user_id, channel_id)
        return changed
    except Exception as e:
        logger.error("set_channel_member_role xatosi: %s", e)
        return False


def create_workflow_post(user_id: int, channel_id: str, content: str,
                         post_type: str = "text", scheduled_time=None,
                         file_id: str | None = None, created_by: int | None = None) -> int:
    """Create a team post in ``draft`` state, never directly in the queue."""
    text = str(content or "").strip()
    ch = str(channel_id or "").strip()
    if not ch or not text:
        return 0
    creator = int(created_by if created_by is not None else user_id)
    try:
        with db_cursor(commit=True) as cur:
            cur.execute("SELECT COALESCE(MAX(user_post_number), 0) + 1 FROM scheduled_posts WHERE user_id = %s", (int(user_id),))
            number = int((cur.fetchone() or (1,))[0] or 1)
            cur.execute(
                """INSERT INTO scheduled_posts
                    (user_id, channel_id, post_type, content, file_id, scheduled_time,
                     status, user_post_number, created_by)
                   VALUES (%s, %s, %s, %s, %s, COALESCE(%s, NOW()), 'draft', %s, %s)
                   RETURNING id""",
                (int(user_id), ch, str(post_type or "text")[:50], text, file_id,
                 scheduled_time, number, creator),
            )
            row = cur.fetchone()
        _cache_clear("system_stats")
        return int(row[0]) if row else 0
    except Exception as e:
        logger.error("create_workflow_post xatosi: %s", e)
        return 0


def get_workflow_post(post_id: int):
    """Return a workflow post dict, including its channel for IDOR checks."""
    try:
        with db_cursor() as cur:
            cur.execute(
                """SELECT id, user_id, channel_id, post_type, content, file_id,
                          scheduled_time, status, created_by, approved_by,
                          approved_at, rejection_reason
                   FROM scheduled_posts WHERE id = %s""", (int(post_id),))
            row = cur.fetchone()
        if not row:
            return None
        keys = ("id", "user_id", "channel_id", "post_type", "content", "file_id",
                "scheduled_time", "status", "created_by", "approved_by",
                "approved_at", "rejection_reason")
        return dict(zip(keys, row))
    except Exception as e:
        logger.error("get_workflow_post xatosi: %s", e)
        return None


def submit_post_for_approval(post_id: int, requested_by: int) -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE scheduled_posts
                      SET status = 'pending_approval', approval_requested_at = NOW(),
                          rejection_reason = NULL
                    WHERE id = %s AND status = 'draft'""",
                (int(post_id),),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("submit_post_for_approval xatosi: %s", e)
        return False


def approve_post(post_id: int, approved_by: int) -> bool:
    """Approve only a pending post. It is still not scheduler-visible."""
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE scheduled_posts
                      SET status = 'approved', approved_by = %s, approved_at = NOW(),
                          rejection_reason = NULL
                    WHERE id = %s AND status = 'pending_approval'""",
                (int(approved_by), int(post_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("approve_post xatosi: %s", e)
        return False


def reject_post(post_id: int, rejected_by: int, reason: str = "") -> bool:
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE scheduled_posts
                      SET status = 'draft', rejection_reason = %s, approved_by = NULL,
                          approved_at = NULL
                    WHERE id = %s AND status = 'pending_approval'""",
                (str(reason or "")[:500] or None, int(post_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("reject_post xatosi: %s", e)
        return False


def edit_workflow_post(post_id: int, edited_by: int, content: str) -> bool:
    value = str(content or "").strip()
    if not value:
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE scheduled_posts
                      SET content = %s, status = 'draft', rejection_reason = NULL,
                          approved_by = NULL, approved_at = NULL
                    WHERE id = %s AND status IN ('draft', 'pending_approval')""",
                (value, int(post_id)),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("edit_workflow_post xatosi: %s", e)
        return False


def schedule_approved_post(post_id: int, scheduled_time=None, scheduled_by: int | None = None) -> bool:
    """Only ``approved`` rows enter the scheduler's explicit ``scheduled`` queue."""
    try:
        with db_cursor(commit=True) as cur:
            if scheduled_time is None:
                cur.execute(
                    "UPDATE scheduled_posts SET status = 'scheduled' WHERE id = %s AND status = 'approved'",
                    (int(post_id),),
                )
            else:
                cur.execute(
                    """UPDATE scheduled_posts SET scheduled_time = %s, status = 'scheduled'
                       WHERE id = %s AND status = 'approved'""",
                    (scheduled_time, int(post_id)),
                )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("schedule_approved_post xatosi: %s", e)
        return False


# Clear aliases used by handlers/integrations.
create_draft_post = create_workflow_post


request_post_approval = submit_post_for_approval


approve_workflow_post = approve_post


reject_workflow_post = reject_post


schedule_post_after_approval = schedule_approved_post


def get_channel_weekly_posts(channel_id: str | int, days: int = 7) -> list[dict]:
    """Return publish/legacy history in the shape consumed by ChannelAdvisor."""
    try:
        safe_days = max(1, min(int(days), 31))
        with db_cursor() as cur:
            cur.execute(
                """SELECT message_id, content, views, post_date, created_at
                   FROM channel_posts_history
                  WHERE channel_id = %s AND post_date >= NOW() - make_interval(days => %s)
                  ORDER BY post_date DESC, id DESC""", (str(channel_id), safe_days))
            rows = cur.fetchall()
        return [{"message_id": r[0], "content": r[1] or "", "views": int(r[2] or 0),
                 "post_date": r[3].isoformat() if r[3] else "",
                 "created_at": r[4].isoformat() if r[4] else "",
                 "status": "published", "published": True} for r in rows]
    except Exception as e:
        logger.error("get_channel_weekly_posts xatosi: %s", e)
        return []


def upsert_audience_question(channel_id: str | int, question_hash: str,
                             category: str = "general", count: int = 1) -> bool:
    """Persist aggregate insight only; raw comment text is intentionally absent."""
    digest = str(question_hash or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        return False
    try:
        with db_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO channel_comment_insights
                    (channel_id, question_hash, category, occurrence_count, last_seen_at)
                   VALUES (%s, %s, %s, %s, NOW())
                   ON CONFLICT (channel_id, question_hash) DO UPDATE
                     SET category = EXCLUDED.category,
                         occurrence_count = channel_comment_insights.occurrence_count + EXCLUDED.occurrence_count,
                         last_seen_at = NOW()""",
                (str(channel_id), digest, str(category or "general")[:32], max(1, int(count or 1))),
            )
            return True
    except Exception as e:
        logger.error("upsert_audience_question xatosi: %s", e)
        return False


def get_audience_question_insights(channel_id: str | int, limit: int = 20) -> list[dict]:
    try:
        with db_cursor() as cur:
            cur.execute(
                """SELECT question_hash, category, occurrence_count, first_seen_at, last_seen_at
                   FROM channel_comment_insights WHERE channel_id = %s
                   ORDER BY occurrence_count DESC, last_seen_at DESC LIMIT %s""",
                (str(channel_id), max(1, min(int(limit), 100))),
            )
            return [{"question_hash": r[0], "category": r[1], "count": int(r[2] or 0),
                     "occurrences": int(r[2] or 0), "first_seen_at": r[3], "last_seen_at": r[4]}
                    for r in cur.fetchall()]
    except Exception as e:
        logger.error("get_audience_question_insights xatosi: %s", e)
        return []