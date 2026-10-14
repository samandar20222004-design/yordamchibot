"""Mini App servis qatlami: ruxsat + o'qish + javob shakli (HTTP'dan mustaqil).

Har bir autentifikatsiyalangan so'rov BITTA read-only tranzaksiyada:
foydalanuvchi qatori -> beta holati -> ruxsat qarori -> (ruxsat bo'lsa) ma'lumot.
PRO holati faqat ``users.plan_type`` / ``subscription_expires_at`` dan, DB vaqti
bo'yicha hisoblanadi (``SubscriptionService.get_status`` ishlatilmaydi: u muddati
o'tgan obunani YOZADI, bu esa o'qish tranzaksiyasi).
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import repository as repo
from .access import evaluate_access
from .db import ReadOnlyRunner
from .errors import ApiError, SUPPORTED_LANGS, DEFAULT_LANG
from .settings import MiniAppSettings

_PRO_TYPES = ("pro", "enterprise")


def iso_utc(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def _config_invite_only() -> bool:
    from services.beta_gate import _config_invite_only as fn

    return fn()


def _is_admin(user_id: int, stored_role) -> bool:
    from services.rbac_service import ADMIN_ROLES, resolve_role

    return resolve_role(user_id, stored_role) in ADMIN_ROLES


def plan_limits() -> dict:
    import config
    from repositories.users_repository import FREE_QUEUE_MAX_POSTS

    return {
        "free": {"max_channels": int(config.FREE_MAX_CHANNELS),
                 "daily_ai_requests": int(config.FREE_DAILY_AI),
                 "queued_posts": int(FREE_QUEUE_MAX_POSTS)},
        "pro": {"max_channels": int(config.PRO_MAX_CHANNELS),
                "daily_ai_requests": int(config.PRO_DAILY_AI),
                "queued_posts": 999},
    }


def resolve_plan(account: dict) -> dict:
    plan_type = (account.get("plan_type") or "free").lower()
    expires = account.get("subscription_expires_at")
    now = account.get("db_now")
    active = False
    if plan_type in _PRO_TYPES:
        active = expires is None or (now is not None and expires > now)
    effective = plan_type if active else "free"
    limits = plan_limits()["pro" if active else "free"]
    return {
        "type": effective,
        "is_pro": active,
        "expires_at": iso_utc(expires) if active else None,
        "limits": limits,
    }


def _language(account: dict) -> str:
    lang = (account.get("language_code") or "").lower()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


class MiniAppService:
    def __init__(self, settings: MiniAppSettings, runner: ReadOnlyRunner, *,
                 invite_only_getter=_config_invite_only, admin_check=_is_admin) -> None:
        self._settings = settings
        self._runner = runner
        self._invite_only = invite_only_getter
        self._is_admin = admin_check

    async def _authorized(self, user_id: int, query_fn):
        invite_only = bool(self._invite_only())

        def work(cur):
            account = repo.load_account(cur, user_id)
            beta_raw = repo.load_beta_state_raw(cur) if account else None
            admin = bool(account) and self._is_admin(user_id, account["role"])
            decision = evaluate_access(
                user_id, user_exists=bool(account),
                deleted=bool(account and account["deleted"]),
                is_admin=admin, beta_raw=beta_raw, config_invite_only=invite_only,
            )
            if not decision.allowed:
                return decision, None
            return decision, query_fn(cur, account)

        decision, data = await self._runner.run(work)
        if not decision.allowed:
            raise ApiError(decision.code or "forbidden_unknown")
        return data

    # ------------------------------------------------------------ endpointlar
    async def me(self, user_id: int) -> dict:
        def query(cur, account):
            channels = repo.count_channels(cur, user_id)
            pending, next_at = repo.pending_summary(cur, user_id)
            plan = resolve_plan(account)
            posts = repo.post_status_counts(cur, user_id)
            return {
                "user": {"id": account["user_id"], "name": account["full_name"],
                         "username": account["username"],
                         "language": _language(account)},
                "plan": plan,
                "usage": {"channels": channels, "pending_posts": pending,
                          "ai_requests_today": account["ai_requests_today"],
                          "ai_credits": account["ai_credits"]},
                "posts": posts,
                "next_post_at": iso_utc(next_at),
                "bot": {"username": self._settings.bot_username or None},
            }

        return await self._authorized(user_id, query)

    async def channels(self, user_id: int) -> dict:
        def query(cur, _account):
            items = repo.list_channels(cur, user_id)
            return {"items": items, "total": len(items)}

        return await self._authorized(user_id, query)

    async def scheduled_posts(self, user_id: int, limit: int, offset: int,
                              history: bool = False) -> dict:
        def query(cur, _account):
            total = repo.count_posts(cur, user_id, history)
            rows = repo.list_posts(cur, user_id, history, limit, offset)
            items = [{**row, "scheduled_time": iso_utc(row["scheduled_time"])}
                     for row in rows]
            return {"items": items, "total": total, "limit": limit,
                    "offset": offset, "has_more": offset + len(items) < total}

        return await self._authorized(user_id, query)

    async def post(self, user_id: int, post_id: int) -> dict:
        def query(cur, _account):
            row = repo.get_post(cur, user_id, post_id)
            if row is None:
                raise ApiError("not_found")
            return {**row, "scheduled_time": iso_utc(row["scheduled_time"])}

        return await self._authorized(user_id, query)

    async def authorize(self, user_id: int) -> dict:
        """Yozuv/AI amallari uchun: ruxsat qarori + (admin, til, owned-kanal tekshiruvi yo'q)."""
        def query(_cur, account):
            return {"is_admin": bool(self._is_admin(user_id, account["role"])),
                    "language": _language(account)}

        return await self._authorized(user_id, query)

    async def owns_channel(self, user_id: int, channel_id: str) -> bool:
        def work(cur):
            return repo.channel_owned(cur, user_id, channel_id)

        return bool(await self._runner.run(work))
