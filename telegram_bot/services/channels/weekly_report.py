"""Public weekly-report facade (kept separate for scheduler/integration callers)."""
from __future__ import annotations

from .advisor import compute_weekly_insights, render_report_card


def build_weekly_report(posts, *, now=None, lang="uz", channel_title="Kanal") -> dict:
    report = compute_weekly_insights(posts, now=now, days=7)
    report["card"] = render_report_card(report, lang=lang, channel_title=channel_title)
    # Telegram adapters can turn this into InlineKeyboardButton without making
    # the analytics layer depend on python-telegram-bot.
    report["inline_actions"] = [{"text": "📅 7 kunlik reja tuzish", "callback_data": "weekly_plan:7"}]
    report["plan_callback"] = "weekly_plan:7"
    return report


weekly_report = build_weekly_report

__all__ = ["build_weekly_report", "weekly_report"]
