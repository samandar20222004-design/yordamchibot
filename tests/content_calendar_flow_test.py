"""SMART CONTENT CALENDAR contract tests (deterministic, no network)."""
import sys
sys.path.insert(0, "telegram_bot")
from handlers.content_calendar import can_create_calendar, render_calendar, selected_topic_for_magic_post
from translations.content_calendar import content_calendar_parity

class DB:
    def __init__(self, pro=False): self.pro = pro
    def is_premium(self, _): return self.pro

def test_seven_day_calendar_for_business():
    assert can_create_calendar(1, 7, DB(False), 0) == (True, "ok")
    text = render_calendar([{"rubric":"Foyda", "topic":"5 maslahat", "tip":"Misol keltiring"}] * 7, "Ayollar kiyimi")
    assert "1-kun" in text and "Ayollar kiyimi" in text

def test_free_cannot_create_thirty_days():
    assert can_create_calendar(1, 30, DB(False)) == (False, "pro_required")

def test_selected_day_is_magic_post_topic():
    assert selected_topic_for_magic_post({"topic":"Yangi chegirma", "rubric":"Chegirma"}) == "Yangi chegirma"

def test_i18n_parity_and_weekly_limit():
    assert all(content_calendar_parity().values())
    assert can_create_calendar(1, 7, DB(False), 1) == (False, "weekly_limit")

if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"): fn()
    print("content calendar: OK")
