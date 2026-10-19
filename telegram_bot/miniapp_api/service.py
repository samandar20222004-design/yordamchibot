"""Mini App servis qatlami: ruxsat + o'qish + javob shakli (HTTP'dan mustaqil).

Har bir autentifikatsiyalangan so'rov BITTA read-only tranzaksiyada:
foydalanuvchi qatori -> ruxsat qarori -> (ruxsat bo'lsa) ma'lumot.
PRO holati faqat ``users.plan_type`` / ``subscription_expires_at`` dan, DB vaqti
bo'yicha hisoblanadi (``SubscriptionService.get_status`` ishlatilmaydi: u muddati
o'tgan obunani YOZADI, bu esa o'qish tranzaksiyasi).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import drafts, prefs
from . import repository as repo
from .access import evaluate_access
from .db import ReadOnlyRunner
from .errors import ApiError, SUPPORTED_LANGS, DEFAULT_LANG
from .settings import MiniAppSettings

_PRO_TYPES = ("pro", "ultra", "enterprise")


def _is_admin(user_id: int, stored_role) -> bool:
    """Keep write/AI role limits independent of the removed beta access gate."""
    from services.rbac_service import ADMIN_ROLES, resolve_role

    return resolve_role(user_id, stored_role) in ADMIN_ROLES


def iso_utc(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return None


def plan_limits() -> dict:
    """Tarif -> limitlar (``config.TIER_LIMITS`` — bot va to'lov oqimlari bilan BIR manba)."""
    import config

    out = {}
    for name, lim in config.TIER_LIMITS.items():
        out[name] = {"max_channels": int(lim["max_channels"]), "daily_ai_requests": int(lim["daily_ai_requests"]),
                     "queued_posts": int(lim["queued_posts"]), "voice_daily": int(lim["voice_daily"])}
    out["pro"] = dict(out["pro"])
    return out


def tier_catalog() -> dict:
    """Mijozga ko'rsatiladigan tariflar (``config`` — bot bilan BIR manba): limitlar, 1 oylik narx (so'm) va barcha davrlar.

    ``periods``: har davr uchun ``months``, ``days``, ``uzs``, ``stars`` va 1 oylikka nisbatan HAQIQIY tejam foizi (``save_pct``).
    """
    import config

    limits = plan_limits()

    def periods(tier: str) -> list[dict]:
        keys = config.tariff_keys_for(tier)
        base = config.TARIFF_CATALOG[keys[0]]
        out = []
        for key in keys:
            info = config.TARIFF_CATALOG[key]
            out.append({
                "months": int(info["months"]), "days": int(info["days"]),
                "uzs": int(info["uzs"]), "stars": int(info["stars"]), "usd": float(info["usd"]),
                "save_pct": int(config.plan_discount_percent(info["stars"], base["stars"], info["months"])),
            })
        return out

    return {
        "free": {"limits": limits["free"], "price_from_uzs": 0, "periods": []},
        "pro": {"limits": limits["pro"], "price_from_uzs": int(config.TARIFF_CATALOG["1m"]["uzs"]), "periods": periods("pro")},
        "ultra": {"limits": limits["ultra"], "price_from_uzs": int(config.TARIFF_CATALOG["u1m"]["uzs"]), "periods": periods("ultra")},
    }


def resolve_plan(account: dict) -> dict:
    plan_type = (account.get("plan_type") or "free").lower()
    expires = account.get("subscription_expires_at")
    now = account.get("db_now")
    active = False
    if plan_type in _PRO_TYPES:
        active = expires is None or (now is not None and expires > now)
    effective = plan_type if active else "free"
    limit_key = effective
    legacy_until = account.get("pro_legacy_until")
    if effective == "pro" and (expires is None or (legacy_until is not None and now is not None and legacy_until > now)):
        limit_key = "pro_legacy"  # tarif yangilanishidan oldin to'langan muddat: eski limitlar tugaguncha saqlanadi
    limits = plan_limits().get(limit_key) or plan_limits()["free"]
    return {
        "type": effective,
        "is_pro": active,
        "expires_at": iso_utc(expires) if active else None,
        "limits": limits,
    }


def pay_region(account: dict) -> str:
    """Narx mintaqasi (bot bilan BIR qoida, TILGA BOG'LIQ EMAS): 'uz' (so'm) faqat tasdiqlangan +998 yoki avval mahalliy to'lagan
    foydalanuvchiga va u o'zi dollarni tanlamagan bo'lsa; qolganlarga 'intl' (dollar)."""
    if account.get("uz_eligible") and account.get("pay_region") != "intl":
        return "uz"
    return "intl"


def resolve_timezone(name, country) -> str:
    from services.user_timezone import resolve

    return resolve(name, country)


def _language(account: dict) -> str:
    lang = (account.get("language_code") or "").lower()
    return lang if lang in SUPPORTED_LANGS else DEFAULT_LANG


class MiniAppService:
    def __init__(self, settings: MiniAppSettings, runner: ReadOnlyRunner, *,
                 admin_check=_is_admin) -> None:
        self._settings = settings
        self._runner = runner
        self._is_admin = admin_check

    async def _authorized(self, user_id: int, query_fn):
        def work(cur):
            account = repo.load_account(cur, user_id)
            decision = evaluate_access(
                user_exists=bool(account),
                deleted=bool(account and account["deleted"]),
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
            try:
                notifications = prefs.read_notifications(cur, user_id)
            except Exception:  # noqa: BLE001 — jadval yo'q/xato: standart qiymatlar (profil ochilishi to'xtamasin)
                notifications = dict(prefs.NOTIFICATION_DEFAULTS)
            return {
                "user": {"id": account["user_id"], "name": account["full_name"],
                         "username": account["username"],
                         "language": _language(account),
                         "timezone": resolve_timezone(account.get("timezone"), account.get("phone_country"))},
                "plan": plan,
                "pay_region": pay_region(account),
                "tiers": tier_catalog(),
                "usage": {"channels": channels, "pending_posts": pending,
                          "ai_requests_today": account["ai_requests_today"],
                          "ai_credits": account["ai_credits"]},
                "posts": posts,
                "settings": {"notifications": notifications},
                "next_post_at": iso_utc(next_at),
                "bot": {"username": self._settings.bot_username or None},
                # 👑 Super admin rejimi tugmasini ko'rsatish uchun (ruxsat HAR admin so'rovida serverda qayta tekshiriladi).
                "is_admin": bool(self._is_admin(user_id, account["role"])),
            }

        return await self._authorized(user_id, query)

    async def channels(self, user_id: int) -> dict:
        def query(cur, _account):
            items = repo.list_channels(cur, user_id)
            return {"items": items, "total": len(items)}

        return await self._authorized(user_id, query)

    async def channel_analytics(self, user_id: int, channel_id: str) -> dict:
        """Kanal analitikasi (faqat EGASI). Begona / yo'q kanal bir xil ``not_found`` (mavjudlik sizdirilmaydi).

        Faqat haqiqiy ma'lumotlar: obunachi snapshot'lari (o'sish extrapolyatsiyasiz), botning o'z postlari va MANBALI
        ko'rishlar. Ma'lumot yo'q -> ``None`` / ``available=False`` (0 emas).
        """
        from services.channels.growth import compute_member_growth, tashkent_today

        def query(cur, _account):
            title = repo.channel_title(cur, user_id, channel_id)
            if title is None:
                raise ApiError("not_found")
            today = tashkent_today()
            history = repo.member_history(cur, channel_id, today - timedelta(days=60))
            growth = compute_member_growth(history, today=today)
            growth["history"] = [{"date": h["date"], "member_count": h["member_count"]} for h in history[:30]]
            return {
                "channel": {"id": str(channel_id), "title": title},
                "members": growth,
                "posts": repo.channel_post_counts(cur, user_id, channel_id),
                "views": repo.views_summary(cur, channel_id),
            }

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

    async def calendar(self, user_id: int, start, end) -> dict:
        """Kalendar: [start, end) oralig'idagi kutilayotgan postlar (kunlarga bo'lishni mijoz o'z zonasida qiladi)."""
        def query(cur, _account):
            rows = repo.list_posts_between(cur, user_id, start, end)
            truncated = len(rows) > repo.CALENDAR_LIMIT
            items = [{**row, "scheduled_time": iso_utc(row["scheduled_time"])}
                     for row in rows[:repo.CALENDAR_LIMIT]]
            return {"items": items, "truncated": truncated, "from": iso_utc(start), "to": iso_utc(end)}

        return await self._authorized(user_id, query)

    async def post(self, user_id: int, post_id: int) -> dict:
        def query(cur, _account):
            row = repo.get_post(cur, user_id, post_id)
            if row is None:
                raise ApiError("not_found")
            return {**row, "scheduled_time": iso_utc(row["scheduled_time"])}

        return await self._authorized(user_id, query)

    async def post_media_ref(self, user_id: int, post_id: int) -> dict:
        """Ichki: postning ``post_type``/``file_id`` si (egasi bo'yicha; mijozga QAYTARILMAYDI)."""
        def query(cur, _account):
            ref = repo.get_post_media_ref(cur, user_id, post_id)
            if ref is None:
                raise ApiError("not_found")
            return ref

        return await self._authorized(user_id, query)

    async def draft(self, user_id: int) -> dict:
        """Botdan kelgan joriy qoralama (yo'q bo'lsa ``{"draft": None}``)."""
        def query(cur, _account):
            row = drafts.read_draft(cur, user_id)
            return {"draft": drafts.public_view(row, iso_utc) if row else None}

        return await self._authorized(user_id, query)

    async def draft_raw(self, user_id: int) -> dict | None:
        """Ichki: ``file_id`` bilan to'liq qoralama (mijozga QAYTARILMAYDI)."""
        def query(cur, _account):
            row = drafts.read_draft(cur, user_id)
            return row["payload"] if row else None

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
