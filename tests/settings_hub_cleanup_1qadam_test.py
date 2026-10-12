#!/usr/bin/env python3
"""Regression guard for the compact primary Settings grid and its submenus."""
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

from keyboards.inline import (  # noqa: E402
    get_profile_menu_keyboard,
    get_settings_help_hub_keyboard,
    get_settings_hub_keyboard,
    get_settings_profile_keyboard,
)


def test():
    expected = ["stgs_lang", "stgs_clean", "stgs_notif", "sub_open",
    "stgs_rewards", "stgs_help_hub"]
    for lang in ("uz", "ru", "en"):
        kb = get_settings_hub_keyboard(lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert cbs == expected, f"[{lang}] unexpected Settings callbacks: {cbs}"
        assert [len(row) for row in kb.inline_keyboard] == [2, 2, 2]
        assert get_settings_profile_keyboard(lang).inline_keyboard == kb.inline_keyboard
        # Secondary destinations are grouped under their natural parent menus.
        assert not {"stgs_referral", "stgs_pay", "stgs_privacy",
                    "stgs_delete_data"}.intersection(cbs)
        assert "stgs_referral" in [
            b.callback_data for row in get_profile_menu_keyboard(lang).inline_keyboard
            for b in row
        ]
        help_cbs = [b.callback_data for row in
                    get_settings_help_hub_keyboard(lang).inline_keyboard for b in row]
        assert "stgs_privacy" in help_cbs and "stgs_delete_data" in help_cbs
        assert "stgs_hub" in help_cbs
        for callback in cbs:
            assert not callback.startswith("cab_"), f"[{lang}] legacy callback: {callback}"
        forbidden = ("👥 Do'stlarni taklif", "💳 To'lovlar tarixi", "🔐 Maxfiylik",
                     "🗑 O'chirish", "ℹ️ Yordam va Qo'llanma")
        assert not any(label in texts for label in forbidden), (lang, texts)
    print("✅ Settings grid is 3×2; Bonuses and Help own secondary actions")


if __name__ == "__main__":
    test()
