"""Deterministic, low-cost content-retention helpers for Telegram nudges."""

from __future__ import annotations

import html
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

SUPPORTED_LANGS = ("uz", "ru", "en")
DEFAULT_CONTENT_GAP_HOURS = 48

# A single source for all retention copy keeps scheduler jobs and callbacks in
# parity. Formatting is performed only with escaped user/channel data.
RETENTION_TEXTS: dict[str, dict[str, str]] = {
    "uz": {
        "digest_title": "🔔 Kanalingizda 2 kundan beri post yo'q. Bugun uchun 3 ta tayyor g'oya tayyorladik:",
        "channel_label": "📢 Kanal",
        "ideas_prompt": "⚡ Qaysi g'oyadan post tayyorlaymiz?",
        "cancel": "❌ Bekor qilish",
        "cancelled": "✅ Bekor qilindi.",
        "disabled": "🔕 Ertalabki post takliflari o'chirildi. Istalgan payt Sozlamalar → Bildirishnomalar bo'limidan yoqishingiz mumkin.",
        "calendar_reminder": "🗓 3 kundan keyin <b>{holiday}</b>! Kanalga tabrik yoki mavzuviy post tayyorlaymizmi?",
        "calendar_create": "🎉 Tabrik post tayyorlash",
        "calendar_error": "⚠️ Kanal yoki bayram ma'lumoti eskirgan. Iltimos, kanalingizni qayta tanlang.",
        "idea_templates": (
            "{topic} bo'yicha auditoriyaga foydali 3 maslahat",
            "{topic} haqida tez-tez beriladigan savolga qisqa javob",
            "{topic} bo'yicha auditoriya uchun savol yoki mini-so'rov",
        ),
        "generic_ideas": (
            "Auditoriyangizga bugun kerak bo'ladigan bitta foydali maslahat",
            "Mijozlar tez-tez beradigan savolga aniq va qisqa javob",
            "Obunachilar fikrini bilish uchun bitta savol yoki mini-so'rov",
        ),
        "calendar_topic": "{holiday} munosabati bilan kanal uchun samimiy tabrik yoki mavzuviy post yoz.",
        "holiday_suffix": " bayrami",
    },
    "ru": {
        "digest_title": "🔔 В вашем канале не было публикаций 2 дня. Подготовили 3 идеи на сегодня:",
        "channel_label": "📢 Канал",
        "ideas_prompt": "⚡ По какой идее подготовим пост?",
        "cancel": "❌ Отмена",
        "cancelled": "✅ Отменено.",
        "disabled": "🔕 Утренние предложения отключены. Их можно включить в Настройки → Уведомления.",
        "calendar_reminder": "🗓 Через 3 дня — <b>{holiday}</b>! Подготовим для канала поздравление или тематический пост?",
        "calendar_create": "🎉 Создать поздравительный пост",
        "calendar_error": "⚠️ Данные канала или праздника устарели. Пожалуйста, выберите канал заново.",
        "idea_templates": (
            "3 полезных совета для аудитории на тему «{topic}»",
            "Короткий ответ на частый вопрос о теме «{topic}»",
            "Вопрос или мини-опрос для аудитории о теме «{topic}»",
        ),
        "generic_ideas": (
            "Один полезный совет, который пригодится аудитории сегодня",
            "Короткий и понятный ответ на частый вопрос клиентов",
            "Вопрос или мини-опрос, чтобы узнать мнение подписчиков",
        ),
        "calendar_topic": "Подготовь для канала тёплое поздравление или тематический пост к празднику «{holiday}».",
        "holiday_suffix": "",
    },
    "en": {
        "digest_title": "🔔 Your channel has been quiet for 2 days. Here are 3 ideas for today:",
        "channel_label": "📢 Channel",
        "ideas_prompt": "⚡ Which idea should we turn into a post?",
        "cancel": "❌ Cancel",
        "cancelled": "✅ Cancelled.",
        "disabled": "🔕 Morning post suggestions are off. You can turn them back on in Settings → Notifications.",
        "calendar_reminder": "🗓 <b>{holiday}</b> is in 3 days! Shall we prepare a greeting or themed post for your channel?",
        "calendar_create": "🎉 Create a greeting post",
        "calendar_error": "⚠️ The channel or holiday details are out of date. Please select your channel again.",
        "idea_templates": (
            "3 useful tips for your audience about {topic}",
            "A short answer to a frequently asked question about {topic}",
            "A question or mini-poll for your audience about {topic}",
        ),
        "generic_ideas": (
            "One useful tip your audience can use today",
            "A clear, short answer to a question customers often ask",
            "A question or mini-poll to hear from your subscribers",
        ),
        "calendar_topic": "Write a warm greeting or themed channel post for {holiday}.",
        "holiday_suffix": "",
    },
}


def normalize_lang(lang: str | None) -> str:
    code = str(lang or "uz").strip().lower().split("-")[0]
    return code if code in SUPPORTED_LANGS else "uz"


def retention_t(key: str, lang: str = "uz", **values: Any) -> str:
    """Localized retention text, with Uzbek fallback for unknown input."""
    table = RETENTION_TEXTS[normalize_lang(lang)]
    template = table.get(key) or RETENTION_TEXTS["uz"].get(key) or ""
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        return template


def _clean_topics(topics: Any) -> list[str]:
    """Normalize channel DNA topics from JSON/list/string into short strings."""
    value = topics
    if isinstance(value, str):
        raw = value.strip()
        if raw.startswith(("[", "{")):
            try:
                import json
                value = json.loads(raw)
            except (TypeError, ValueError):
                value = [raw]
        else:
            value = [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(value, dict):
        # Common DNA shape: {"value": [...]} or a mapping of topic scores.
        value = value.get("value") or value.get("topics") or list(value.keys())
    if not isinstance(value, (list, tuple, set)):
        return []
    result = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("value") or item.get("topic") or item.get("name")
        topic = " ".join(str(item or "").split()).strip(" \t\r\n-•")
        if not topic:
            continue
        # Strip HTML/control characters before interpolating into copy.
        topic = " ".join(html.unescape(topic).split())[:72]
        token = topic.casefold()
        if token not in seen:
            seen.add(token)
            result.append(topic)
        if len(result) >= 3:
            break
    return result


def build_content_ideas(channel_title: str = "", topics: Any = None,
                        lang: str = "uz") -> tuple[str, str, str]:
    """Build three deterministic ideas, using Channel DNA topics if available.

    This intentionally has no AI/provider call: the 09:00 retention task is
    lightweight and does not consume credits or invent channel statistics.
    """
    code = normalize_lang(lang)
    topic_list = _clean_topics(topics)
    if not topic_list:
        fallback = RETENTION_TEXTS[code]["generic_ideas"]
        return tuple(fallback[:3])  # type: ignore[return-value]
    templates = RETENTION_TEXTS[code]["idea_templates"]
    return tuple(
        templates[index].format(topic=topic_list[index % len(topic_list)])
        for index in range(3)
    )  # type: ignore[return-value]


def build_daily_digest_text(channel_title: str, ideas: Iterable[str],
                            lang: str = "uz") -> str:
    """Render the localized morning message with safe HTML for channel data."""
    code = normalize_lang(lang)
    title = " ".join(str(channel_title or "").split())[:120]
    safe_title = html.escape(title) if title else ""
    idea_list = [str(x or "").strip() for x in (ideas or ()) if str(x or "").strip()]
    if len(idea_list) < 3:
        idea_list.extend(build_content_ideas(lang=code)[len(idea_list):])
    lines = [retention_t("digest_title", code)]
    if safe_title:
        lines.extend(["", f"{retention_t('channel_label', code)}: <b>{safe_title}</b>"])
    lines.append("")
    lines.extend(f"{index}. {html.escape(idea)}" for index, idea in enumerate(idea_list[:3], 1))
    return "\n".join(lines)


def _as_utc(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def has_content_gap(last_post_at: Any, now: Any, *,
                    hours: int = DEFAULT_CONTENT_GAP_HOURS) -> bool:
    """Whether there has been no observed/published post for at least N hours.

    ``last_post_at=None`` means there is no known post history. A timestamp in
    the future is not considered a gap (fail-safe against bad data).
    """
    try:
        threshold = max(1, int(hours))
        current = _as_utc(now)
        if current is None:
            return False
        last_post = _as_utc(last_post_at)
        if last_post is None:
            return last_post_at is None
        elapsed = current - last_post
        return timedelta(0) <= elapsed and elapsed >= timedelta(hours=threshold)
    except (TypeError, ValueError, OverflowError):
        return False


def pick_one_channel_per_user(rows: Iterable[Any]) -> list[Any]:
    """Return the first row for each valid user ID, preserving DB order."""
    result = []
    seen: set[int] = set()
    for row in rows or ():
        try:
            user_id = row.get("user_id") if isinstance(row, dict) else row[2]
            user_id = int(user_id)
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        result.append(row)
    return result


__all__ = [
    "DEFAULT_CONTENT_GAP_HOURS",
    "RETENTION_TEXTS",
    "build_content_ideas",
    "build_daily_digest_text",
    "has_content_gap",
    "normalize_lang",
    "pick_one_channel_per_user",
    "retention_t",
]
