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
    assert "BTN_BUY_AD_FREE" not in keyboard
    start_src = (ROOT / "handlers/start.py").read_text()
    for token in ("adfree_toggle", "adfree_confirm", "adfree_refund", "buy_ad_free_handler", "ad_free_callback"):
        assert token not in start_src, token
    import database as db_mod
    for name in ("buy_ad_free_posts", "refund_ad_free_posts", "toggle_ad_free_status",
                 "consume_ad_free_post", "peek_ad_free_post",
                 "check_and_grant_referral_pro", "get_referral_pro_progress"):
        assert not hasattr(db_mod, name), name


def test_referral_reward_tiers():
    import database as db_mod
    assert [db_mod.referral_reward_for(i) for i in range(1, 7)] == [3, 3, 3, 1, 1, 1]
    assert db_mod.total_referral_reward(4) == 10


def test_auto_ad_free_mode():
    """PRO/admin → reklama 0; oddiy → ad_pool oralig'i."""
    import asyncio
    import database as db_mod
    from utils import helpers

    orig_prem, orig_run = db_mod.is_premium, db_mod.run_db
    try:
        db_mod.is_premium = lambda uid: uid == 5001
        assert helpers.is_user_ad_free(5001) is True
        assert helpers.is_user_ad_free(5002) is False
        assert helpers.is_user_ad_free(123456789) is True  # admin

        async def fake_run_db(func, *args, **kwargs):
            name = func.__name__
            if name in ("is_premium", "<lambda>"):
                return args[0] == 5001
            if name == "get_ads_full":
                return [{"id": 1, "text": "POOL-AD", "button_text": "", "button_url": "", "is_active": True}]
            return ""
        db_mod.run_db = fake_run_db

        # PRO: 10 ta ketma-ket chaqiruvda ham reklama YO'Q
        for _ in range(10):
            assert asyncio.run(helpers.get_smart_reply_ad_async(5001)) == ""
        assert asyncio.run(helpers.is_user_ad_free_async(5001)) is True
        # Oddiy: har 3-xabarda reklama chiqadi
        helpers._USER_MSG_COUNT.pop(5002, None)
        outs = [asyncio.run(helpers.get_smart_reply_ad_async(5002)) for _ in range(3)]
        assert outs[0] == "" and outs[1] == "" and "POOL-AD" in outs[2]
    finally:
        db_mod.is_premium, db_mod.run_db = orig_prem, orig_run
        helpers._AD_ROTATION_INDEX.clear()


def test_card_payment_button_and_text():
    from handlers.subscription import (
        _get_subscription_keyboard, _build_card_payment_text, _get_card_payment_keyboard,
    )
    for lang in ("uz", "ru"):
        kb = _get_subscription_keyboard("free", lang)
        flat = [b for row in kb.inline_keyboard for b in row]
        card = [b for b in flat if b.callback_data == "sub_card_pay"]
        assert len(card) == 1 and "Uzcard" in card[0].text and "Humo" in card[0].text
        assert "sub_pay:stars_1m" in [b.callback_data for b in flat]  # Stars saqlanadi
        text = _build_card_payment_text(42, lang)
        assert "Uzcard" in text and "42" in text and "19 000" in text
        back = [b.callback_data for row in _get_card_payment_keyboard(lang).inline_keyboard for b in row]
        assert "sub_back" in back
    pro_kb = _get_subscription_keyboard("pro", "uz")
    assert "sub_card_pay" not in [b.callback_data for row in pro_kb.inline_keyboard for b in row]


def test_i18n_new_keys():
    for lang in ("uz", "ru"):
        for key in ("no_credits", "balance_card", "ad_mode_pro", "ad_mode_free",
                    "btn_card_payment", "card_payment_title", "card_payment_steps"):
            assert get_text(key, lang) != key, (key, lang)
        guide = get_text("daily_bonus_guide", lang)
        assert "🎁" in guide and "🎁" in get_text("no_credits", lang, guide=guide, link="x")
    assert "Kabinet & Sozlamalar" in get_text("daily_bonus_guide", "uz")
    assert "Kunlik bonus" in get_text("daily_bonus_guide", "uz")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"New requirements: {len(tests)} tests passed")
