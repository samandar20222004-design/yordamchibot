"""Mini App sozlamalari (muhit o'zgaruvchilaridan, xavfsiz standartlar bilan).

Barcha ``MINIAPP_*`` qiymatlari shu yerda yig'iladi. ``load_settings(env)``
sof funksiya — testlarda ``os.environ`` ga tegmasdan chaqiriladi.

Xavfsizlik standartlari:
  * ``MINIAPP_ENABLED`` — sukut ``0`` (o'chiq);
  * ``MINIAPP_RATE_REQUIRE_SHARED`` — sukut ``1``; ``development``/``test``
    muhitida ``0`` ga tushirish mumkin, **production'da hech qachon**;
  * ``MINIAPP_REQUIRE_HTTPS`` — sukut ``1``.

Noto'g'ri/xavfsiz bo'lmagan kombinatsiya ``MiniAppSettings.config_errors``
ro'yxatiga tushadi va :mod:`miniapp_api.app` marshrutlarni ULAMAYDI (bot
qolgan qismi bilan ishlashda davom etadi).
"""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from typing import Mapping

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}
_NON_PRODUCTION_ENVS = frozenset({"development", "test"})

#: ``BOT_TOKEN`` tuzilishi: ``<raqamli bot id>:<chop etiladigan ASCII sir>``.
#: Uzunlik yoki alfavit cheklovi KIRITILMAGAN (Telegram formatini o'zgartirishi
#: mumkin) — faqat bo'sh/Unicode/boshqaruv belgilari rad etiladi.
_BOT_TOKEN_RE = re.compile(r"\A[0-9]+:[\x21-\x7e]+\Z")


def is_valid_bot_token(token: object) -> bool:
    """``BOT_TOKEN`` tuzilishi yaroqlimi (tokenni hech qachon loglamaydi)."""
    return isinstance(token, str) and bool(_BOT_TOKEN_RE.match(token))


def _flag(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    return default


def _int(env: Mapping[str, str], name: str, default: int, *, lo: int, hi: int) -> int:
    raw = (env.get(name) or "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        return default
    return max(lo, min(hi, value))


def _parse_cidrs(raw: str) -> tuple[tuple, list[str]]:
    nets, bad = [], []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            bad.append("MINIAPP_TRUSTED_PROXY_CIDRS")
    return tuple(nets), bad


@dataclass(frozen=True)
class MiniAppSettings:
    enabled: bool = False
    environment: str = "production"
    bot_token: str = field(default="", repr=False)
    auth_max_age_seconds: int = 3600
    auth_future_skew_seconds: int = 60
    init_data_max_bytes: int = 4096
    require_https: bool = True
    trusted_proxy_cidrs: tuple = ()
    proxy_hops: int = 1
    proxy_assert_edge_only: bool = False
    rate_require_shared: bool = True
    rate_auth_limit: int = 120
    rate_auth_window: float = 60.0
    rate_user_limit: int = 60
    rate_user_window: float = 60.0
    rate_redis_concurrency: int = 4
    rate_write_limit: int = 30
    rate_write_window: float = 60.0
    rate_ai_limit: int = 4
    rate_ai_window: float = 60.0
    rate_upload_limit: int = 20
    rate_upload_window: float = 60.0
    upload_timeout_seconds: float = 240.0
    ai_concurrency: int = 4
    ai_timeout_seconds: float = 30.0
    max_body_bytes: int = 32768
    request_timeout_seconds: float = 8.0
    db_statement_timeout_ms: int = 5000
    max_inflight_db: int = 4
    db_queue_wait_seconds: float = 2.0
    db_max_queue: int = 64
    max_page_size: int = 50
    dist_dir: str = ""
    bot_username: str = ""
    config_errors: tuple = ()

    @property
    def is_production(self) -> bool:
        return self.environment not in _NON_PRODUCTION_ENVS

    @property
    def proxy_configured(self) -> bool:
        return bool(self.trusted_proxy_cidrs) or self.proxy_assert_edge_only


def default_dist_dir() -> str:
    """``miniapp/dist`` joyi: repozitoriy (``<repo>/miniapp/dist``) yoki Docker image
    (``/app/miniapp/dist``). ``index.html`` bor birinchi nomzod olinadi; hech biri yo'q bo'lsa
    birinchisi qaytadi (``/app/*`` shunda 404 beradi). ``MINIAPP_DIST_DIR`` ustun turadi."""
    bot_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # telegram_bot/ yoki /app
    candidates = (
        os.path.normpath(os.path.join(bot_root, "..", "miniapp", "dist")),
        os.path.normpath(os.path.join(bot_root, "miniapp", "dist")),
    )
    for path in candidates:
        if os.path.isfile(os.path.join(path, "index.html")):
            return path
    return candidates[0]


def load_settings(env: Mapping[str, str] | None = None) -> MiniAppSettings:
    env = os.environ if env is None else env
    errors: list[str] = []

    environment = (env.get("ENVIRONMENT") or "").strip().lower() or "production"
    enabled = _flag(env, "MINIAPP_ENABLED", False)

    cidrs, bad = _parse_cidrs(env.get("MINIAPP_TRUSTED_PROXY_CIDRS", ""))
    if bad:
        errors.append("MINIAPP_TRUSTED_PROXY_CIDRS noto'g'ri CIDR")
    edge_only = _flag(env, "MINIAPP_PROXY_ASSERT_EDGE_ONLY", False)
    require_https = _flag(env, "MINIAPP_REQUIRE_HTTPS", True)

    # Sukut: production'da umumiy limiter MAJBURIY; dev/test'da o'chirish mumkin.
    non_prod = environment in _NON_PRODUCTION_ENVS
    shared_default = not non_prod
    shared_raw = (env.get("MINIAPP_RATE_REQUIRE_SHARED") or "").strip()
    rate_shared = _flag(env, "MINIAPP_RATE_REQUIRE_SHARED", shared_default)
    if not non_prod and shared_raw and not rate_shared:
        errors.append("production'da MINIAPP_RATE_REQUIRE_SHARED=0 mumkin emas")

    token = env.get("BOT_TOKEN") or ""
    dist = (env.get("MINIAPP_DIST_DIR") or "").strip() or default_dist_dir()

    if enabled:
        if require_https and not (cidrs or edge_only):
            errors.append(
                "HTTPS majburiy, lekin ishonchli proksi sozlanmagan "
                "(MINIAPP_TRUSTED_PROXY_CIDRS yoki MINIAPP_PROXY_ASSERT_EDGE_ONLY=1)"
            )
        if not is_valid_bot_token(token):
            errors.append("BOT_TOKEN yo'q yoki yaroqsiz tuzilishda")

    return MiniAppSettings(
        enabled=enabled,
        environment=environment,
        bot_token=token,
        auth_max_age_seconds=_int(env, "MINIAPP_AUTH_MAX_AGE_SECONDS", 3600, lo=60, hi=86400),
        init_data_max_bytes=_int(env, "MINIAPP_INIT_DATA_MAX_BYTES", 4096, lo=512, hi=16384),
        require_https=require_https,
        trusted_proxy_cidrs=cidrs,
        proxy_hops=_int(env, "MINIAPP_PROXY_HOPS", 1, lo=1, hi=10),
        proxy_assert_edge_only=edge_only,
        rate_require_shared=rate_shared,
        rate_auth_limit=_int(env, "MINIAPP_RATE_AUTH_LIMIT", 120, lo=1, hi=10000),
        rate_auth_window=float(_int(env, "MINIAPP_RATE_AUTH_WINDOW", 60, lo=1, hi=3600)),
        rate_user_limit=_int(env, "MINIAPP_RATE_USER_LIMIT", 60, lo=1, hi=10000),
        rate_user_window=float(_int(env, "MINIAPP_RATE_USER_WINDOW", 60, lo=1, hi=3600)),
        rate_redis_concurrency=_int(env, "MINIAPP_RATE_REDIS_CONCURRENCY", 4, lo=1, hi=64),
        rate_write_limit=_int(env, "MINIAPP_RATE_WRITE_LIMIT", 30, lo=1, hi=10000),
        rate_write_window=float(_int(env, "MINIAPP_RATE_WRITE_WINDOW", 60, lo=1, hi=3600)),
        rate_ai_limit=_int(env, "MINIAPP_RATE_AI_LIMIT", 4, lo=1, hi=1000),
        rate_ai_window=float(_int(env, "MINIAPP_RATE_AI_WINDOW", 60, lo=1, hi=3600)),
        rate_upload_limit=_int(env, "MINIAPP_RATE_UPLOAD_LIMIT", 20, lo=1, hi=1000),
        rate_upload_window=float(_int(env, "MINIAPP_RATE_UPLOAD_WINDOW", 60, lo=1, hi=3600)),
        upload_timeout_seconds=float(_int(env, "MINIAPP_UPLOAD_TIMEOUT_SECONDS", 240, lo=30, hi=900)),
        ai_concurrency=_int(env, "MINIAPP_AI_CONCURRENCY", 4, lo=1, hi=32),
        ai_timeout_seconds=float(_int(env, "MINIAPP_AI_TIMEOUT_SECONDS", 30, lo=5, hi=120)),
        max_body_bytes=_int(env, "MINIAPP_MAX_BODY_BYTES", 32768, lo=1024, hi=262144),
        request_timeout_seconds=float(_int(env, "MINIAPP_REQUEST_TIMEOUT_SECONDS", 8, lo=1, hi=60)),
        db_statement_timeout_ms=_int(env, "MINIAPP_DB_STATEMENT_TIMEOUT_MS", 5000, lo=100, hi=60000),
        max_inflight_db=_int(env, "MINIAPP_MAX_INFLIGHT_DB", 4, lo=1, hi=64),
        db_queue_wait_seconds=float(_int(env, "MINIAPP_DB_QUEUE_WAIT_SECONDS", 2, lo=0, hi=10)),
        db_max_queue=_int(env, "MINIAPP_DB_MAX_QUEUE", 64, lo=0, hi=1000),
        max_page_size=_int(env, "MINIAPP_MAX_PAGE_SIZE", 50, lo=1, hi=200),
        dist_dir=dist,
        bot_username=(env.get("BOT_USERNAME") or "").strip().lstrip("@"),
        config_errors=tuple(errors),
    )
