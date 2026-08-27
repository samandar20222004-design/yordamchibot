def md_escape(text) -> str:
    if not text:
        return ""
    text = str(text)
    for ch in ("\\", "_", "*", "`", "["):
        text = text.replace(ch, "\\" + ch)
    return text

def format_post_code(user_code, user_post_number) -> str:
    return f"{user_code}-{user_post_number}" if user_post_number else str(user_code)

def format_schedule_line(s_time, is_recurring, recurrence_day, recurrence_time):
    from keyboards.default import WEEKDAY_LABELS
    if is_recurring:
        day_label = WEEKDAY_LABELS.get(recurrence_day, "?")
        time_str = recurrence_time.strftime("%H:%M") if recurrence_time else "?"
        return f"🔄 Har {day_label}, soat `{time_str}`"
    return f"🕒 `{s_time.strftime('%Y-%m-%d %H:%M')}`"
