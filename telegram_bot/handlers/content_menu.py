"""Backward-compatible content menu entry point.
The submenu implementation remains in :mod:`content_creation`; calendar logic
is deliberately isolated in :mod:`content_calendar` so existing FSMs are safe.
"""
from handlers.content_creation import *  # noqa: F401,F403
from handlers.content_calendar import (
    can_create_calendar, is_pro_user, normalize_items, render_calendar,
    selected_topic_for_magic_post,
)
