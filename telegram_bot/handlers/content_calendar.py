"""SMART CONTENT CALENDAR: validation, entitlement and safe rendering."""
from datetime import datetime, timezone
from html import escape
from translations.content_calendar import calendar_t

FREE_WEEKLY_LIMIT = 1

def is_pro_user(user_id, db_module):
    """Fail closed: database/entitlement errors never grant PRO."""
    try:
        return bool(db_module.is_premium(user_id))
    except Exception:
        return False

def can_create_calendar(user_id, days, db_module, recent_count=0):
    days = int(days)
    if days not in (7, 30):
        return False, "invalid_duration"
    if days == 30 and not is_pro_user(user_id, db_module):
        return False, "pro_required"
    if days == 7 and not is_pro_user(user_id, db_module) and int(recent_count or 0) >= FREE_WEEKLY_LIMIT:
        return False, "weekly_limit"
    return True, "ok"

def normalize_items(items, days):
    """Keep only bounded, dictionary-shaped AI output; pad nothing silently."""
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict): continue
        result.append({"rubric": str(item.get("rubric", "Foydali maslahat"))[:120], "topic": str(item.get("topic", item.get("title", "")))[:240], "tip": str(item.get("tip", item.get("idea", "")))[:400]})
        if len(result) >= days: break
    return result

def render_calendar(items, business, lang="uz"):
    """Render untrusted AI text with HTML escaping (safe_html contract)."""
    lines = [calendar_t("header", lang, business=escape(str(business)[:200]))]
    for n, item in enumerate(normalize_items(items, len(items)), 1):
        lines.append(calendar_t("day", lang, n=n, rubric=escape(item["rubric"]), topic=escape(item["topic"]), tip=escape(item["tip"])))
    return "".join(lines).strip()

def selected_topic_for_magic_post(item):
    """Stable hand-off payload used by Magic Post entry flow."""
    item = item if isinstance(item, dict) else {}
    return (item.get("topic") or item.get("title") or item.get("idea") or "").strip()
