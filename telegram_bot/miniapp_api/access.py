"""Mini App account access. Telegram authentication happens before this check.

An existing, non-deleted bot account can use the API; /start creates that
account. The API itself never registers users or restores deleted accounts.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    code: str | None
    reason: str


def evaluate_access(*, user_exists: bool, deleted: bool) -> AccessDecision:
    if not user_exists or deleted:
        return AccessDecision(False, "not_registered", "not_registered")
    return AccessDecision(True, None, "registered_user")
