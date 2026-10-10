#!/usr/bin/env python3
"""Deterministic Sprint 3 digest, calendar and AI-progress contract tests."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"  [OK] {message}")


def test_deterministic_localized_digest():
    from services.retention import build_content_ideas, build_daily_digest_text

    expected_starts = {
        "uz": "Mahsulot",
        "ru": "3 полезных совета",
        "en": "3 useful tips",
    }
    for lang in ("uz", "ru", "en"):
        ideas = build_content_ideas("Kanal", ["Mahsulot"], lang)
        check(len(ideas) == 3, f"digest has three ideas ({lang})")
        check(ideas == build_content_ideas("Kanal", ["Mahsulot"], lang),
              f"digest ideas are deterministic ({lang})")
        if lang == "uz":
            check(expected_starts[lang] in ideas[0], "Uzbek idea uses Channel DNA topic")
        else:
            check(ideas[0].startswith(expected_starts[lang]),
                  f"localized idea language ({lang})")
        text = build_daily_digest_text("<Kanal & Co>", ideas, lang)
        check("&lt;Kanal &amp; Co&gt;" in text, f"digest HTML-escapes channel title ({lang})")
        check(len(text.splitlines()) >= 5, f"digest includes title and ideas ({lang})")


def test_calendar_event_coverage_and_localization():
    from services.uzbekistan_calendar import (
        calendar_reminder_text,
        get_calendar_events,
        get_events_for_date,
        get_events_for_reminder,
    )

    events = get_calendar_events(2026)
    by_key = {event.key: event for event in events}
    required = {
        "new_year", "navruz", "eid_al_fitr", "eid_al_adha",
        "independence_day", "remembrance_day", "teachers_day",
        "admission_exam_season",
    }
    check(required.issubset(by_key), "calendar covers fixed, seasonal and both Hayit events")
    check(by_key["navruz"].date == date(2026, 3, 21), "Navro'z date is fixed")
    check(by_key["independence_day"].date == date(2026, 9, 1), "Independence Day date is fixed")
    check(by_key["remembrance_day"].date == date(2026, 5, 9), "Remembrance Day date is fixed")
    check(by_key["teachers_day"].date == date(2026, 10, 1), "Teachers' Day date is fixed")
    check(by_key["admission_exam_season"].kind == "season", "admissions/exam entry is seasonal")

    # O'zbekiston milliy sanalari va mavsumiy savdo davrlari (2026-10 to'ldirish).
    check(by_key["defenders_day"].date == date(2026, 1, 14), "Vatan himoyachilari kuni = 14-yanvar")
    check(by_key["women_day"].date == date(2026, 3, 8), "Xotin-qizlar kuni = 8-mart")
    check(by_key["constitution_day"].date == date(2026, 12, 8), "Konstitutsiya kuni = 8-dekabr")
    check(by_key["defenders_day"].kind == "holiday" and by_key["women_day"].kind == "holiday"
          and by_key["constitution_day"].kind == "holiday", "yangi milliy sanalar holiday turida")
    check(by_key["back_to_school"].kind == "season" and by_key["back_to_school"].date.month == 8,
          "maktabga qaytish — avgust, mavsum (holiday emas)")
    check("ramadan_prep" in by_key and by_key["ramadan_prep"].kind == "season",
          "Ramazon tayyorgarligi — hijri hisobda mavsumiy marker")
    check(all(event.name(lang) for event in events for lang in ("uz", "ru", "en")),
          "yangi sanalar uchta tilda nomlangan")

    target = date(2026, 3, 21)
    reminders = get_events_for_reminder(target - timedelta(days=3), 3)
    check([event.key for event in reminders] == ["navruz"], "Navro'z reminder is exactly three days before")
    check(get_events_for_date(target) == reminders, "date lookup agrees with reminder lookup")
    texts = {lang: calendar_reminder_text(reminders[0], lang) for lang in ("uz", "ru", "en")}
    check("3 kundan keyin" in texts["uz"] and "Navro'z" in texts["uz"], "Uzbek calendar reminder is localized")
    check("Через 3 дня" in texts["ru"] and "Навруз" in texts["ru"], "Russian calendar reminder is localized")
    check("in 3 days" in texts["en"] and "Navruz" in texts["en"], "English calendar reminder is localized")

    override = {"eid_al_fitr": date(2026, 4, 1)}
    overridden = get_events_for_reminder(date(2026, 3, 29), 3,
                                         eid_date_overrides=override)
    check(any(event.key == "eid_al_fitr" and event.date == date(2026, 4, 1)
              for event in overridden), "official Hayit date override is deterministic")


def test_scheduled_digest_and_calendar_jobs():
    import scheduler
    from services.retention import DEFAULT_CONTENT_GAP_HOURS
    from keyboards.callback_data import validate_callback

    rows = [
        ("-10001", "Kanal One", 501, "ru", ["Ta'lim"], "friendly"),
        ("-10002", "Second channel", 501, "en", ["Tech"], "formal"),
    ]
    fake_bot = type("FakeBot", (), {"send_message": AsyncMock()})()

    async def run_digest():
        observed = {}

        async def fake_run_db(fn, *args):
            observed["fn"] = fn
            observed["args"] = args
            return rows

        now = scheduler.tashkent_tz.localize(datetime(2026, 5, 1, 9, 0))
        with patch.object(scheduler.db, "run_db", new=fake_run_db):
            result = await scheduler.daily_morning_digest_job(fake_bot, now=now)
        check(result == {"sent": 2, "skipped": 0},
              "digest sends one opt-in reminder for each qualifying channel")
        check(observed["fn"] is scheduler.db.get_channels_for_content_nudges,
              "digest calls the restricted content-nudge query")
        setting_key, since = observed["args"]
        check(setting_key == "notify_morning_digest", "digest query uses its settings toggle")
        check(since == now - timedelta(hours=DEFAULT_CONTENT_GAP_HOURS),
              "digest query excludes posts newer than the exact 48-hour cutoff")
        first, second = [call.kwargs for call in fake_bot.send_message.await_args_list]
        check(first["chat_id"] == second["chat_id"] == 501,
              "digest reminders are delivered privately to the channel owner")
        check("2 дня" in first["text"] and "2 days" in second["text"],
              "each channel reminder follows the owner's selected locale")
        buttons = [button for row in first["reply_markup"].inline_keyboard for button in row]
        second_buttons = [button for row in second["reply_markup"].inline_keyboard for button in row]
        check(len(buttons) == len(second_buttons) == 3,
              "each channel digest includes create, schedule and disable actions")
        check(all(validate_callback(button.callback_data)
                  for button in buttons + second_buttons),
              "digest action callbacks pass the central callback registry")
        check("-10001" in buttons[0].callback_data and "-10002" in second_buttons[0].callback_data,
              "each digest CTA remains targeted to its qualifying channel")
        check("Отключить уведомления" in buttons[-1].text,
              "digest opt-out action has a Russian label")

    async def run_calendar():
        fake_bot.send_message.reset_mock()
        observed = {}

        async def fake_run_db(fn, *args):
            observed["fn"] = fn
            observed["args"] = args
            return [("-10003", "Navruz channel", 502, "en", [], "")]

        with patch.object(scheduler.db, "run_db", new=fake_run_db):
            result = await scheduler.uzbekistan_calendar_reminders_job(
                fake_bot, today=date(2026, 3, 18),
            )
        check(result == {"sent": 1, "skipped": 0}, "calendar job sends the exact three-day reminder")
        check(observed["args"] == ("notify_uzbek_calendar", None),
              "calendar job respects its independent settings toggle")
        sent = fake_bot.send_message.await_args.kwargs
        check(sent["chat_id"] == 502, "calendar reminder is delivered to the channel owner")
        check("in 3 days" in sent["text"] and "Navruz" in sent["text"],
              "calendar job renders English reminder copy")
        button = sent["reply_markup"].inline_keyboard[0][0]
        check(button.text and validate_callback(button.callback_data),
              "calendar CTA is localized and callback-registered")

        fake_bot.send_message.reset_mock()
        with patch.object(scheduler.db, "run_db", new=AsyncMock()) as db_mock:
            result = await scheduler.uzbekistan_calendar_reminders_job(
                fake_bot, today=date(2026, 3, 1),
            )
        check(result == {"sent": 0, "skipped": 0} and db_mock.await_count == 0,
              "calendar job does not query or send when no event is three days away")

    asyncio.run(run_digest())
    asyncio.run(run_calendar())


def test_ai_progress_locales_and_edit_floor():
    from services.ai.progress import AI_PROGRESS_STAGES, AIProgressReporter

    check(set(AI_PROGRESS_STAGES) == {"uz", "ru", "en"}, "AI progress stages cover UZ/RU/EN")
    for lang, stages in AI_PROGRESS_STAGES.items():
        check(len(stages) >= 3 and all(stage.strip() for stage in stages),
              f"AI progress stages are non-empty ({lang})")
    reporter = AIProgressReporter(minimum_edit_interval=0.1)
    check(reporter.minimum_edit_interval >= 1.0,
          "AI progress edit interval cannot exceed Telegram's one-edit-per-second limit")


def test_recurring_stars_subscription_updates():
    from types import SimpleNamespace
    import handlers.subscription as subscription

    context = SimpleNamespace(user_data={})
    update = SimpleNamespace(subscription=SimpleNamespace(
        user=SimpleNamespace(id=601),
        invoice_payload="sub_stars_1m_601",
        state="canceled",
    ))
    db_call = AsyncMock(return_value=True)
    with (patch.object(subscription, "ensure_user_lang", new=AsyncMock(return_value="en")),
          patch.object(subscription.db, "run_db", new=db_call)):
        result = asyncio.run(subscription.bot_subscription_updated_callback(update, context))
    check(result is True, "valid BotSubscriptionUpdated state reaches the DB synchronizer")
    check(db_call.await_args.args[0] is subscription.db.sync_stars_subscription,
          "subscription update uses the dedicated Stars state synchronizer")
    check(db_call.await_args.args[1:] == (601, "canceled", None),
          "cancellation update carries the Telegram user and state")

    invalid = SimpleNamespace(subscription=SimpleNamespace(
        user=SimpleNamespace(id=601), invoice_payload="sub_stars_1m_999", state="active",
    ))
    db_call.reset_mock()
    with (patch.object(subscription, "ensure_user_lang", new=AsyncMock(return_value="en")),
          patch.object(subscription.db, "run_db", new=db_call)):
        result = asyncio.run(subscription.bot_subscription_updated_callback(invalid, context))
    check(result is False and db_call.await_count == 0,
          "subscription payload/user mismatch is rejected before database changes")

    handler = subscription.BotSubscriptionUpdatedHandler()
    check(handler.check_update(update) is True, "PTB subscription handler matches BotSubscriptionUpdated")
    check(handler.check_update(SimpleNamespace(message=object(), subscription=None)) is False,
          "PTB subscription handler does not shadow regular Telegram updates")

    from telegram import Update as TelegramUpdate
    raw_update = TelegramUpdate.de_json({
        "update_id": 7001,
        "subscription": {
            "user": {"id": 601, "is_bot": False, "first_name": "Test"},
            "invoice_payload": "sub_stars_1m_601",
            "state": "active",
        },
    })
    check(handler.check_update(raw_update) is True,
          "unknown PTB subscription field is detected in Update.api_kwargs")
    db_call.reset_mock()
    with (patch.object(subscription, "ensure_user_lang", new=AsyncMock(return_value="en")),
          patch.object(subscription.db, "run_db", new=db_call)):
        result = asyncio.run(subscription.bot_subscription_updated_callback(raw_update, context))
    check(result is True and db_call.await_args.args[1:] == (601, "active", None),
          "raw Telegram Bot API subscription update is decoded and synchronized")


def main():
    print("== Sprint 3 daily retention, calendar and progress ==")
    test_deterministic_localized_digest()
    test_calendar_event_coverage_and_localization()
    test_scheduled_digest_and_calendar_jobs()
    test_ai_progress_locales_and_edit_floor()
    test_recurring_stars_subscription_updates()
    print("\nSprint 3 deterministic tests passed.")


if __name__ == "__main__":
    main()
