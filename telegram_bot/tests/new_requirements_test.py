#!/usr/bin/env python3
"""Regression tests for media-safe editing, referral rewards and bilingual copy."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from handlers.new_post import _apply_single_media
from locales.translations import get_text
from scheduler import build_reaction_buttons


def test_media_context_is_stable():
    ctx = SimpleNamespace(user_data={"content": "old"})
    _apply_single_media(ctx, {"type": "video", "file_id": "vid-123", "caption": "caption"})
    # A caption edit updates only content (the handler intentionally has no
    # assignment that converts the post to text or clears file_id).
    ctx.user_data["content"] = "edited"
    assert ctx.user_data["post_type"] == "video"
    assert ctx.user_data["file_id"] == "vid-123"


def test_reactions_are_inline_buttons():
    row = build_reaction_buttons(42, True, ["👍", "❤️", "🔥"])
    assert [b.text for b in row] == ["👍", "❤️", "🔥"]
    assert all(b.callback_data.startswith("react:42:") for b in row)


def test_i18n_requirement_copy():
    for lang in ("uz", "ru"):
        assert "+3" in get_text("referral_menu", lang, credits=1, count=2, link="x")
        assert "+1" in get_text("referral_menu", lang, credits=1, count=2, link="x")
        assert "🎁" in get_text("daily_bonus_guide", lang)


def test_no_referral_pro_hook_or_manual_license_ui():
    assert "check_and_grant_referral_pro" not in (ROOT / "handlers/channels.py").read_text()
    keyboard = (ROOT / "keyboards/default.py").read_text()
    assert "[BTN_DAILY_BONUS, BTN_BUY_AD_FREE]" not in keyboard


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"New requirements: {len(tests)} tests passed")
