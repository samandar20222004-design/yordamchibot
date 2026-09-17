#!/usr/bin/env python3
"""PHASE E acceptance checks: team RBAC, approval, audience insights, advisor."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:PHASE_E_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
ROOT = Path(__file__).resolve().parent.parent / "telegram_bot"
sys.path.insert(0, str(ROOT))

from services.channels.advisor import compute_weekly_insights  # noqa: E402
from services.channels.comments import (  # noqa: E402
    analyze_repeated_questions, build_faq_draft, redact_personal_data,
)
from services.channels.team import (  # noqa: E402
    ApprovalWorkflow, ChannelRole, authorize, can_role,
)


class FakeTeamDB:
    def __init__(self):
        self.owner = {"channel-1": 10}
        self.members = {("channel-1", 20): ("channel-1", 20, "editor", None),
                        ("channel-1", 30): ("channel-1", 30, "scheduler", None),
                        ("channel-1", 40): ("channel-1", 40, "analyst", None)}

    def get_channel_owner_id(self, channel_id):
        return self.owner.get(str(channel_id))

    def get_channel_member(self, channel_id, user_id):
        return self.members.get((str(channel_id), int(user_id)))


def check(label, condition):
    if not condition:
        raise AssertionError(label)
    print("  [OK]", label)


def main():
    check("role vocabulary", can_role("owner", "approve") and can_role("editor", "edit"))
    check("scheduler cannot approve", not can_role(ChannelRole.SCHEDULER, "approve"))
    check("analyst only sees analytics", can_role("analyst", "view_analytics") and not can_role("analyst", "edit"))

    fake = FakeTeamDB()
    check("owner authorization", asyncio.run(authorize("channel-1", 10, "approve", fake)).allowed)
    check("editor authorization", asyncio.run(authorize("channel-1", 20, "approve", fake)).allowed)
    check("analyst cannot edit", not asyncio.run(authorize("channel-1", 40, "edit", fake)).allowed)
    check("IDOR is denied", not asyncio.run(authorize("channel-1", 999, "view", fake)).allowed)

    flow = ApprovalWorkflow()
    flow.create("channel-1", 10, "Draft post", post_id=1)
    check("new post is draft", flow.get(1)["status"] == "draft")
    check("submit moves to approval", flow.submit_for_approval(1, 10) and flow.get(1)["status"] == "pending_approval")
    check("scheduler cannot bypass approval", not flow.schedule(1, "scheduler"))
    check("editor approves", flow.approve(1, "editor") and flow.get(1)["status"] == "approved")
    check("scheduler queues only approved", flow.schedule(1, "scheduler") and flow.get(1)["status"] == "scheduled")
    check("publish is final", flow.publish(1, "owner") and flow.get(1)["status"] == "published")

    comments = [
        {"text": "Narxi qancha? email me@example.com"},
        {"text": "Narxi qancha? @private_user"},
        {"text": "Narxi qancha?"},
        {"text": "Rahmat, juda yaxshi."},
    ]
    redacted = redact_personal_data(comments[0]["text"])
    check("personal data is redacted", "me@example.com" not in redacted and "[contact]" in redacted)
    questions = analyze_repeated_questions(comments)
    check("repeated question detected", len(questions) == 1 and questions[0]["count"] == 3)
    faq = build_faq_draft(questions)
    check("FAQ draft is offered", faq and faq["requires_editor_review"] and faq["type"] == "faq")

    now = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)
    posts = []
    for index in range(6):
        posts.append({"status": "published", "published": True, "format": "photo",
                      "post_date": (now - timedelta(days=index)).isoformat(),
                      "post_hour": 19, "views": 100 + index})
    report = compute_weekly_insights(posts, now=now)
    check("weekly report count", report["published_posts"] == 6)
    check("weekly report has format and time", report["formats"] and report["best_time"]["time"] == "19:00")
    text = " ".join(report["recommendations"])
    check("advisor uses cautious language", "ko'rin" in text or "o'xsh" in text)
    check("advisor does not claim certainty", "aniq sabab shu" not in text.lower())
    print("PHASE E TEAM/INSIGHTS TESTS PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL:", exc)
        raise SystemExit(1)
