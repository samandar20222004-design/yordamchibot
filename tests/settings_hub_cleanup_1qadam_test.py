#!/usr/bin/env python3
"""Regression guard for the 6-button (3×2) primary Settings grid and its submenus."""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "123")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "telegram_bot"))

import database as db_mod  # noqa: E402
from handlers import settings as settings_mod  # noqa: E402
from keyboards.inline import (  # noqa: E402
    get_profile_menu_keyboard,
    get_settings_help_hub_keyboard,
    get_settings_hub_keyboard,
    get_settings_profile_keyboard,
)
from translations import settings_stats_t  # noqa: E402


EXPECTED_LABELS = {
    "uz": [
        "🌐 Til / Язык",
        "🔔 Bildirishnomalar",
        "💎 PRO va Tariflar",
        "👥 Do'stlarni taklif",
        "ℹ️ Yordam va Qo'llanma",
    ],
    "ru": [
        "🌐 Язык",
        "🔔 Уведомления",
        "💎 PRO и тарифы",
        "👥 Пригласить друзей",
        "ℹ️ Помощь и руководство",
    ],
    "en": [
        "🌐 Language",
        "🔔 Notifications",
        "💎 PRO & Plans",
        "👥 Invite friends",
        "ℹ️ Help and Guide",
    ],
}


def test():
    expected = [
        "stgs_lang",
        "stgs_notif",
        "sub_open",
        "stgs_referral",
        "stgs_help_hub",
    ]
    for lang in ("uz", "ru", "en"):
        kb = get_settings_hub_keyboard(lang)
        cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
        texts = [b.text for row in kb.inline_keyboard for b in row]
        assert cbs == expected, f"[{lang}] unexpected Settings callbacks: {cbs}"
        assert texts == EXPECTED_LABELS[lang], f"[{lang}] unexpected labels: {texts}"
        assert [len(row) for row in kb.inline_keyboard] == [2, 2, 1]
        assert get_settings_profile_keyboard(lang).inline_keyboard == kb.inline_keyboard
        # Secondary destinations (billing history, privacy, data deletion) remain nested.
        assert not {"stgs_pay", "stgs_privacy", "stgs_delete_data"}.intersection(cbs)
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
        forbidden = ("💳 To'lovlar tarixi", "🔐 Maxfiylik", "🗑 O'chirish")
        assert not any(label in texts for label in forbidden), (lang, texts)

    # Verify both restored buttons trigger their sub-handlers & localized texts seamlessly.
    async def _fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        if name == "get_referral_stats":
            return {"ai_credits": 15, "streak": 2, "referrals_count": 4}
        if name == "get_user_lang":
            return "uz"
        return {}

    orig_run_db = db_mod.run_db
    db_mod.run_db = _fake_run_db
    try:
        for lang in ("uz", "ru", "en"):
            edits = []

            async def _edit(text, reply_markup=None, **kw):
                edits.append((text, reply_markup))

            async def _noop(*a, **kw):
                return None

            ctx = SimpleNamespace(
                user_data={"lang": lang},
                chat_data={},
                bot=SimpleNamespace(username="postassist_test_bot"),
            )

            # 1) 👥 Do'stlarni taklif -> stgs_referral
            q_ref = SimpleNamespace(
                data="stgs_referral",
                from_user=SimpleNamespace(id=777),
                message=SimpleNamespace(chat_id=777, reply_text=_edit),
                answer=_noop,
                edit_message_text=_edit,
            )
            upd_ref = SimpleNamespace(
                callback_query=q_ref,
                effective_user=q_ref.from_user,
                effective_message=q_ref.message,
            )
            asyncio.run(settings_mod.settings_menu_callback(upd_ref, ctx))
            assert edits, f"[{lang}] stgs_referral did not render"
            ref_text, ref_kb = edits[-1]
            ref_cbs = [b.callback_data for row in ref_kb.inline_keyboard for b in row]
            assert "https://t.me/postassist_test_bot?start=ref_777" in ref_text
            assert "claim_bonus" in ref_cbs and "stgs_hub" in ref_cbs
            back_labels = [
                b.text for row in ref_kb.inline_keyboard for b in row
                if b.callback_data == "stgs_hub"
            ]
            assert back_labels == [settings_stats_t("ss_btn_back", lang)]

            # 2) ℹ️ Yordam va Qo'llanma -> stgs_help_hub
            q_help = SimpleNamespace(
                data="stgs_help_hub",
                from_user=SimpleNamespace(id=777),
                message=SimpleNamespace(chat_id=777, reply_text=_edit),
                answer=_noop,
                edit_message_text=_edit,
            )
            upd_help = SimpleNamespace(
                callback_query=q_help,
                effective_user=q_help.from_user,
                effective_message=q_help.message,
            )
            asyncio.run(settings_mod.settings_help_hub_callback(upd_help, ctx))
            help_text, help_kb = edits[-1]
            help_kb_cbs = [b.callback_data for row in help_kb.inline_keyboard for b in row]
            assert "<b>PostAssist</b>" in help_text and "/help" in help_text
            assert help_kb_cbs == ["help_support", "stgs_privacy", "stgs_delete_data", "stgs_hub"]
    finally:
        db_mod.run_db = orig_run_db

    print("✅ Settings primary grid is 3×2 (6 buttons); referral & help sub-handlers work in uz/ru/en")


if __name__ == "__main__":
    test()
