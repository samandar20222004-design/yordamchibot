#!/usr/bin/env python3
"""Public onboarding: old beta settings/payloads cannot re-enable approval."""
import asyncio
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BOT = Path(__file__).resolve().parents[1] / "telegram_bot"
sys.path.insert(0, str(BOT))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:PUBLIC_ACCESS_TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")
# Simulate a deployment still carrying the old closed-beta environment setting.
os.environ["BETA_INVITE_ONLY"] = "true"

import database as db  # noqa: E402
from locales.translations import get_text  # noqa: E402

start_mod = importlib.import_module("handlers.start")


class Message:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append((text, kwargs))


class Bot:
    def __init__(self):
        self.admin_messages = []

    async def send_message(self, **kwargs):
        self.admin_messages.append(kwargs)


async def run_start(*, is_new=True, args=()):
    calls = []
    menu = object()
    message = Message()
    bot = Bot()
    user = SimpleNamespace(id=900001, username="guest", full_name="Guest",
                           first_name="Guest", language_code="uz")
    update = SimpleNamespace(effective_user=user, message=message)
    context = SimpleNamespace(args=list(args), bot=bot, user_data={}, chat_data={})

    async def fake_run_db(fn, *pos, **kw):
        calls.append((fn.__name__, pos, kw))
        if fn.__name__ == "save_user":
            return is_new
        return "uz"

    async def subscribed(*args):
        return True, []

    async def no_ad(*args):
        return ""

    async def no_menu(*args):
        return None

    async def main_menu(*args):
        return menu

    async def no_suffix(*args):
        return ""

    def bg(coro, **kwargs):
        coro.close()

    with (patch.object(db, "run_db", fake_run_db),
          patch.object(start_mod, "peek_profile", return_value=None),
          patch.object(start_mod, "check_user_subscribed", subscribed),
          patch.object(start_mod, "get_smart_reply_ad_async", no_ad),
          patch.object(start_mod, "user_wants_simple_menu", no_menu),
          patch.object(start_mod, "resolve_main_keyboard", main_menu),
          patch.object(start_mod, "main_menu_intro_suffix", no_suffix),
          patch.object(start_mod, "run_background_task", bg)):
        await start_mod.start(update, context)
    return message.replies, bot.admin_messages, calls, menu


def main():
    for is_new, payload in ((True, ()), (True, ("INVALID-CODE",)),
                            (True, ("ref_123", "INVALID-CODE")),
                            (False, ())):
        replies, admin_messages, calls, menu = asyncio.run(run_start(is_new=is_new, args=payload))
        assert len(replies) == 1, (is_new, payload, replies)
        assert replies[0][1]["reply_markup"] is menu, payload
        assert replies[0][0].startswith(get_text("start_onboarding" if is_new else "start_hello", "uz",
                                                    name="Guest"))
        assert not admin_messages, (payload, admin_messages)
        saves = [c for c in calls if c[0] == "save_user"]
        assert len(saves) == 1 and saves[0][1][0] == 900001, calls
        assert all("beta" not in name.lower() for name, _, _ in calls), calls
        if payload and payload[0] == "ref_123":
            assert saves[0][2]["referrer_id"] == 123
        else:
            assert saves[0][2]["referrer_id"] is None
    from telegram.ext import ApplicationBuilder, CommandHandler
    from handlers import register_all_handlers

    app = ApplicationBuilder().token(os.environ["BOT_TOKEN"]).build()
    register_all_handlers(app)
    commands = {cmd for group in app.handlers.values() for h in group
                if isinstance(h, CommandHandler) for cmd in h.commands}
    assert "beta" not in commands
    print("Public /start, referral, no admin requests, no /beta command: PASS")


if __name__ == "__main__":
    main()
