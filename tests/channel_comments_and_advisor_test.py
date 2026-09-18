#!/usr/bin/env python3
"""FAZA 10/11/12/13/14/24 smoke tests for comment intelligence."""
from datetime import datetime, timezone
import asyncio
import os, sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:test")
os.environ.setdefault("DATABASE_URL", "postgresql://x:x@localhost/x")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from services.channels.comments import (  # noqa: E402
    analyze_repeated_questions, build_faq_draft, classify_comment,
    redact_personal_data,
)
from services.channels.advisor import compute_weekly_insights, proactive_insight  # noqa: E402
from services.channels.weekly_report import build_weekly_report  # noqa: E402


def main():
    comments = [{"text": x, "author": {"username": "secret"}} for x in
                ("Narxi?", "Qancha?", "Necha pul?", "Цена?")]
    clusters = analyze_repeated_questions(comments, min_occurrences=3)
    assert len(clusters) == 1 and clusters[0]["category"] == "price"
    assert "secret" not in str(clusters)
    assert classify_comment("Rahmat, zo'r!") == "PRAISE"
    assert "me@example.com" not in redact_personal_data("Narxi? me@example.com")
    draft = build_faq_draft(clusters)
    assert draft and draft["requires_editor_review"]
    report = compute_weekly_insights([{"published": True, "format": "text"}],
                                     now=datetime.now(timezone.utc))
    assert report["period_days"] == 7
    weekly = build_weekly_report([], channel_title="Test")
    assert weekly["plan_callback"] == "weekly_plan:7"
    signal = proactive_insight(compute_weekly_insights([], now=datetime.now(timezone.utc)), channel_id="x")
    assert signal and proactive_insight(compute_weekly_insights([], now=datetime.now(timezone.utc)), channel_id="x") is None
    print("CHANNEL COMMENTS / ADVISOR TESTS PASSED")


if __name__ == "__main__":
    main()
