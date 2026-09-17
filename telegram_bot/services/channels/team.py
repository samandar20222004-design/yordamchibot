"""Team roles and approval workflow for channel posts.

This module deliberately keeps the workflow separate from the legacy single-owner
posting flow.  Legacy ``add_post`` rows keep their ``pending`` status and are
still handled by the existing scheduler.  Team-created rows use the explicit
workflow ``draft -> pending_approval -> approved -> scheduled -> published``.

The service is fail-closed: a missing channel, an unknown member, or a database
error never grants a permission.  The channel owner is also recognised when no
``channel_members`` row exists, which preserves the original single-owner mode.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

logger = logging.getLogger(__name__)


class ChannelRole(str, Enum):
    OWNER = "owner"
    EDITOR = "editor"
    SCHEDULER = "scheduler"
    ANALYST = "analyst"


ROLES = tuple(role.value for role in ChannelRole)
WORKFLOW_STATUSES = (
    "draft", "pending_approval", "approved", "scheduled", "published",
)
LEGACY_STATUSES = ("pending", "processing", "posted", "failed", "cancelled", "completed", "unknown")

# Permission names are intentionally small and action-oriented.  Callers may
# use either ``approve`` or ``approve_post``; aliases are normalised below.
ROLE_PERMISSIONS = {
    "owner": frozenset({"view", "view_analytics", "create", "edit", "approve", "reject", "schedule", "publish", "manage_members"}),
    "editor": frozenset({"view", "create", "edit", "approve", "reject"}),
    # These two roles are deliberately narrow: a scheduler cannot inspect
    # analytics and an analyst cannot edit/schedule or access general controls.
    "scheduler": frozenset({"schedule"}),
    "analyst": frozenset({"view_analytics"}),
}
_ACTION_ALIASES = {
    "approve_post": "approve", "reject_post": "reject", "edit_post": "edit",
    "schedule_post": "schedule", "publish_post": "publish", "statistics": "view_analytics",
    "analytics": "view_analytics", "stats": "view_analytics", "manage": "manage_members",
}


@dataclass(frozen=True)
class ChannelMember:
    channel_id: str
    user_id: int
    role: str
    created_at: datetime | None = None

    def as_dict(self) -> dict:
        return {"channel_id": self.channel_id, "user_id": self.user_id,
                "role": self.role, "created_at": self.created_at}


@dataclass(frozen=True)
class ApprovalButtons:
    """Callback-safe labels used when an approval request is sent to an admin."""
    approve: str = "✅ Tasdiqlash"
    edit: str = "✏️ Tahrirlash"
    reject: str = "❌ Rad etish"


@dataclass(frozen=True)
class PermissionResult:
    allowed: bool
    role: str | None = None
    reason: str = ""

    def __bool__(self):
        return self.allowed


def normalize_role(role: Any) -> str | None:
    value = str(role or "").strip().lower()
    return value if value in ROLES else None


def normalize_action(action: Any) -> str:
    value = str(action or "").strip().lower()
    return _ACTION_ALIASES.get(value, value)


def can_role(role: Any, action: Any) -> bool:
    """Pure role check, useful for handlers and tests."""
    normalized = normalize_role(role)
    return bool(normalized and normalize_action(action) in ROLE_PERMISSIONS[normalized])


def role_permissions(role: Any) -> frozenset:
    normalized = normalize_role(role)
    return ROLE_PERMISSIONS.get(normalized, frozenset())


def _row_to_member(row: Any, channel_id: str | None = None, user_id: int | None = None) -> ChannelMember | None:
    if not row:
        return None
    try:
        if isinstance(row, dict):
            ch = row.get("channel_id", channel_id)
            uid = row.get("user_id", user_id)
            role = row.get("role")
            created = row.get("created_at")
        else:
            # DB rows are (id, channel_id, user_id, role, created_at), while small
            # fakes often return (channel_id, user_id, role, created_at).
            if len(row) >= 5:
                _, ch, uid, role, created = row[:5]
            else:
                ch, uid, role, created = row[:4]
        normalized = normalize_role(role)
        if normalized is None:
            return None
        return ChannelMember(str(ch), int(uid), normalized, created)
    except (TypeError, ValueError, IndexError, AttributeError):
        return None


async def _db_call(db: Any, name: str, *args, **kwargs):
    """Call a database adapter without assuming a concrete fake shape."""
    if db is None:
        return None
    fn = getattr(db, name, None)
    if not callable(fn):
        return None
    runner = getattr(db, "run_db", None)
    if callable(runner):
        try:
            value = runner(fn, *args, **kwargs)
        except TypeError:
            # A few lightweight test adapters expose positional-only methods.
            value = runner(fn, *args)
        return await value if asyncio.iscoroutine(value) else value
    value = fn(*args, **kwargs)
    if asyncio.iscoroutine(value):
        return await value
    return value


async def resolve_member_role(channel_id: str | int, user_id: int, db_module: Any = None) -> str | None:
    """Resolve a user's role, including the implicit legacy channel owner."""
    db = db_module or _load_database()
    channel = str(channel_id or "").strip()
    try:
        owner = await _db_call(db, "get_channel_owner_id", channel)
        if owner is not None and int(owner) == int(user_id):
            return ChannelRole.OWNER.value
    except Exception:  # fail closed below
        logger.debug("Owner lookup failed for channel %s", channel, exc_info=True)
    try:
        member = await _db_call(db, "get_channel_member", channel, int(user_id))
        parsed = _row_to_member(member, channel, user_id)
        return parsed.role if parsed else None
    except Exception:
        logger.debug("Member lookup failed for channel %s", channel, exc_info=True)
        return None


async def authorize(channel_id: str | int, user_id: int, action: str,
                    db_module: Any = None) -> PermissionResult:
    role = await resolve_member_role(channel_id, user_id, db_module)
    normalized_action = normalize_action(action)
    if role is None:
        return PermissionResult(False, None, "not_a_channel_member")
    if normalized_action not in ROLE_PERMISSIONS.get(role, frozenset()):
        return PermissionResult(False, role, "insufficient_role")
    return PermissionResult(True, role, "")


def _load_database():
    try:
        import database
        return database
    except Exception:
        return None


class TeamService:
    """Team membership and approval operations.

    ``db_module`` can be a real database module or a deterministic adapter in
    tests.  Every mutating method returns a small dict instead of leaking a DB
    exception into a Telegram update handler.
    """
    def __init__(self, db_module: Any = None):
        self.db = db_module or _load_database()

    async def role(self, channel_id, user_id) -> str | None:
        return await resolve_member_role(channel_id, user_id, self.db)

    async def can(self, channel_id, user_id, action) -> bool:
        return bool((await authorize(channel_id, user_id, action, self.db)).allowed)

    async def add_member(self, channel_id, actor_id, member_id, role: str = "editor") -> dict:
        if not await self.can(channel_id, actor_id, "manage_members"):
            return {"ok": False, "error": "forbidden"}
        normalized = normalize_role(role)
        if normalized in (None, "owner"):
            return {"ok": False, "error": "invalid_role"}
        row = await _db_call(self.db, "add_channel_member", str(channel_id), int(member_id), normalized, int(actor_id))
        return {"ok": bool(row), "member": row, "error": None if row else "db_error"}

    async def remove_member(self, channel_id, actor_id, member_id) -> dict:
        if not await self.can(channel_id, actor_id, "manage_members"):
            return {"ok": False, "error": "forbidden"}
        removed = await _db_call(self.db, "remove_channel_member", str(channel_id), int(member_id), int(actor_id))
        return {"ok": bool(removed), "error": None if removed else "not_found"}

    async def set_role(self, channel_id, actor_id, member_id, role) -> dict:
        if not await self.can(channel_id, actor_id, "manage_members"):
            return {"ok": False, "error": "forbidden"}
        normalized = normalize_role(role)
        if normalized in (None, "owner"):
            return {"ok": False, "error": "invalid_role"}
        ok = await _db_call(self.db, "set_channel_member_role", str(channel_id), int(member_id), normalized, int(actor_id))
        return {"ok": bool(ok), "role": normalized if ok else None,
                "error": None if ok else "not_found"}

    async def members(self, channel_id):
        return await _db_call(self.db, "list_channel_members", str(channel_id)) or []

    async def create_post(self, channel_id, user_id, content, *, post_type="text", scheduled_time=None, file_id=None) -> dict:
        if not await self.can(channel_id, user_id, "create"):
            return {"ok": False, "error": "forbidden"}
        post_id = await _db_call(self.db, "create_workflow_post", int(user_id), str(channel_id), str(content or ""),
                                 post_type, scheduled_time, file_id, int(user_id))
        return {"ok": bool(post_id), "post_id": post_id or None, "status": "draft" if post_id else None,
                "error": None if post_id else "db_error"}

    async def submit_for_approval(self, post_id: int, user_id: int) -> dict:
        post = await _db_call(self.db, "get_workflow_post", int(post_id))
        if not post:
            return {"ok": False, "error": "not_found"}
        channel_id = _post_channel(post)
        if not channel_id or not await self.can(channel_id, user_id, "edit"):
            return {"ok": False, "error": "forbidden"}
        ok = await _db_call(self.db, "submit_post_for_approval", int(post_id), int(user_id))
        return {"ok": bool(ok), "status": "pending_approval" if ok else None,
                "error": None if ok else "invalid_transition"}

    async def approve(self, post_id: int, user_id: int) -> dict:
        return await self._transition(post_id, user_id, "approve_post", "approve_post", "approved")

    async def submit_and_notify(self, post_id: int, user_id: int, bot: Any,
                                approver_chat_ids: Iterable[int], *, preview: str = "") -> dict:
        """Submit a writer/assistant post and deliver the three approval controls.

        Notification is intentionally an explicit opt-in at the integration
        boundary: the service never guesses who should receive a private
        message.  The state transition happens before notifications, and a
        Telegram failure is reported without reopening the approved queue.
        """
        result = await self.submit_for_approval(post_id, user_id)
        if not result.get("ok"):
            return result
        from handlers.team import send_approval_request
        sent = 0
        for chat_id in approver_chat_ids or ():
            try:
                await send_approval_request(bot, int(chat_id), int(post_id), preview)
                sent += 1
            except Exception:
                logger.warning("Approval request yuborilmadi (post=%s, chat=%s)", post_id, chat_id,
                               exc_info=True)
        result["notifications_sent"] = sent
        return result

    async def reject(self, post_id: int, user_id: int, reason: str = "") -> dict:
        result = await self._transition(post_id, user_id, "reject_post", "reject_post", "draft", reason=reason)
        if result["ok"]:
            result["status"] = "draft"
        return result

    async def edit(self, post_id: int, user_id: int, content: str) -> dict:
        post = await _db_call(self.db, "get_workflow_post", int(post_id))
        if not post:
            return {"ok": False, "error": "not_found"}
        channel_id = _post_channel(post)
        if not channel_id or not await self.can(channel_id, user_id, "edit"):
            return {"ok": False, "error": "forbidden"}
        ok = await _db_call(self.db, "edit_workflow_post", int(post_id), int(user_id), str(content or ""))
        return {"ok": bool(ok), "status": "draft" if ok else None,
                "error": None if ok else "invalid_transition"}

    async def schedule(self, post_id: int, user_id: int, when=None) -> dict:
        post = await _db_call(self.db, "get_workflow_post", int(post_id))
        if not post:
            return {"ok": False, "error": "not_found"}
        channel_id = _post_channel(post)
        if not channel_id or not await self.can(channel_id, user_id, "schedule"):
            return {"ok": False, "error": "forbidden"}
        ok = await _db_call(self.db, "schedule_approved_post", int(post_id), when, int(user_id))
        return {"ok": bool(ok), "status": "scheduled" if ok else None,
                "error": None if ok else "not_approved"}

    async def _transition(self, post_id, user_id, action, db_name, target, **kwargs) -> dict:
        post = await _db_call(self.db, "get_workflow_post", int(post_id))
        if not post:
            return {"ok": False, "error": "not_found"}
        channel_id = _post_channel(post)
        if not channel_id or not await self.can(channel_id, user_id, action):
            return {"ok": False, "error": "forbidden"}
        fn_kwargs = kwargs
        ok = await _db_call(self.db, db_name, int(post_id), int(user_id), **fn_kwargs)
        return {"ok": bool(ok), "status": target if ok else None,
                "error": None if ok else "invalid_transition"}

    # Explicit names make integration from handlers and external clients clear.
    submit = submit_for_approval
    request_approval = submit_for_approval
    request_approval_and_notify = submit_and_notify
    approve_post = approve
    reject_post = reject
    edit_post = edit
    schedule_post = schedule


def _post_channel(post: Any) -> str | None:
    if isinstance(post, dict):
        value = post.get("channel_id")
    else:
        try:
            value = post[2]
        except (IndexError, TypeError):
            value = getattr(post, "channel_id", None)
    return str(value) if value not in (None, "") else None


# Stateless helper names are convenient for handler code and hidden integrations.
async def check_permission(channel_id, user_id, action, db_module=None) -> bool:
    return bool((await authorize(channel_id, user_id, action, db_module)).allowed)


def approval_keyboard_labels() -> ApprovalButtons:
    return ApprovalButtons()


def build_approval_keyboard(post_id: int):
    """Build the exact three-button approval card used by Telegram handlers."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from keyboards.callback_data import (
        CB_TEAM_APPROVE, CB_TEAM_EDIT, CB_TEAM_REJECT, cb,
    )
    pid = int(post_id)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=cb(CB_TEAM_APPROVE, pid)),
        InlineKeyboardButton("✏️ Tahrirlash", callback_data=cb(CB_TEAM_EDIT, pid)),
        InlineKeyboardButton("❌ Rad etish", callback_data=cb(CB_TEAM_REJECT, pid)),
    ]])


class ApprovalWorkflow:
    """Small deterministic state machine for adapters and offline tests.

    Production persistence is supplied by the database helpers above; this
    class mirrors its transitions and is useful for a handler preview before a
    DB write succeeds.  No transition can skip approval.
    """
    def __init__(self):
        self.posts: dict[int, dict] = {}
        self._next_id = 1

    def create(self, channel_id, author_id, content, post_id=None) -> dict:
        pid = int(post_id if post_id is not None else self._next_id)
        self._next_id = max(self._next_id, pid + 1)
        self.posts[pid] = {"id": pid, "channel_id": str(channel_id), "author_id": int(author_id),
                           "content": str(content), "status": "draft", "approved_by": None}
        return dict(self.posts[pid])

    def get(self, post_id):
        row = self.posts.get(int(post_id))
        return dict(row) if row else None

    def _allowed(self, post, actor, action):
        role = (actor if isinstance(actor, str) else None)
        if role is None:
            role = "owner" if int(actor) == int(post["author_id"]) else None
        return can_role(role, action)

    def submit_for_approval(self, post_id, actor_id) -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor_id, "edit") or post["status"] != "draft":
            return False
        post["status"] = "pending_approval"
        return True

    def approve(self, post_id, actor="owner") -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor, "approve") or post["status"] != "pending_approval":
            return False
        post["status"] = "approved"
        post["approved_by"] = actor
        return True

    def schedule(self, post_id, actor="scheduler") -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor, "schedule") or post["status"] != "approved":
            return False
        post["status"] = "scheduled"
        return True

    def publish(self, post_id, actor="owner") -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor, "publish") or post["status"] != "scheduled":
            return False
        post["status"] = "published"
        return True

    def reject(self, post_id, actor="owner", reason="") -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor, "reject") or post["status"] != "pending_approval":
            return False
        post["status"] = "draft"
        post["rejection_reason"] = str(reason or "")[:500]
        return True

    def edit(self, post_id, actor="editor", content="") -> bool:
        post = self.posts.get(int(post_id))
        if not post or not self._allowed(post, actor, "edit") or post["status"] not in ("draft", "pending_approval"):
            return False
        value = str(content or "").strip()
        if not value:
            return False
        post["content"] = value
        post["status"] = "draft"
        return True


ChannelMemberService = TeamService
ApprovalService = TeamService
has_channel_permission = check_permission
get_role_permissions = role_permissions


__all__ = [
    "ApprovalButtons", "ApprovalService", "ApprovalWorkflow", "ChannelMember", "ChannelRole", "LEGACY_STATUSES",
    "ChannelMemberService", "PermissionResult", "ROLE_PERMISSIONS", "ROLES", "TeamService",
    "WORKFLOW_STATUSES", "approval_keyboard_labels", "build_approval_keyboard", "authorize", "can_role",
    "check_permission", "get_role_permissions", "has_channel_permission", "normalize_action", "normalize_role", "resolve_member_role",
    "role_permissions",
]
