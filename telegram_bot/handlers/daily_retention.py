"""Daily retention and Uzbekistan-calendar Telegram entry points.

The scheduler only sends lightweight, deterministic suggestions. These
callbacks hand selected ideas to the existing Magic Post and channel-post FSMs;
AI quota is therefore reserved only when a user chooses a style and generates.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from keyboards.callback_data import (
    CB_CHANNEL_NEW_POST,
    CB_MORNING_DIGEST_CANCEL,
    CB_MORNING_DIGEST_CREATE,
    CB_MORNING_DIGEST_DISABLE,
    CB_MORNING_DIGEST_IDEA,
    CB_UZ_CALENDAR_CREATE,
    cb,
)
from locales.translations import clear_fsm_data, get_lang
from services.retention import (
    build_content_ideas,
    normalize_lang,
    retention_t,
)
from services.uzbekistan_calendar import (
    calendar_post_topic,
    get_calendar_event,
)

logger = logging.getLogger(__name__)

# Dedicated, unused ConversationHandler state. Callback entry points switch
# into this state and the selected idea then returns to Magic Post's own state.
MORNING_IDEA_SELECT = 9101

_RETENTION_TZ = ZoneInfo("Asia/Tashkent")


def build_morning_digest_keyboard(channel_id: str | int, lang: str = "uz") -> InlineKeyboardMarkup:
    """The 3 requested, localized actions for the morning reminder."""
    lang = normalize_lang(lang)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                {"uz": "⚡ Post yaratish", "ru": "⚡ Создать пост", "en": "⚡ Create a post"}.get(lang, "⚡ Post yaratish"),
                callback_data=cb(CB_MORNING_DIGEST_CREATE, channel_id),
            ),
            InlineKeyboardButton(
                {"uz": "📅 Rejalash", "ru": "📅 Запланировать", "en": "📅 Schedule"}.get(lang, "📅 Rejalash"),
                # Reuse the existing channel-aware new-post flow. Its preview
                # offers immediate publishing or the established scheduler.
                callback_data=cb(CB_CHANNEL_NEW_POST, channel_id),
            ),
        ],
        [InlineKeyboardButton(
            {"uz": "🔕 Bildirishnomani o'chirish", "ru": "🔕 Отключить уведомления", "en": "🔕 Turn off notifications"}.get(lang, "🔕 Bildirishnomani o'chirish"),
            callback_data=CB_MORNING_DIGEST_DISABLE,
        )],
    ])


def build_calendar_reminder_keyboard(event_key: str, channel_id: str | int,
                                    lang: str = "uz") -> InlineKeyboardMarkup:
    lang = normalize_lang(lang)
    label = retention_t("calendar_create", lang)
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            label,
            callback_data=cb(CB_UZ_CALENDAR_CREATE, event_key, channel_id),
        )
    ]])


async def _owned_channel(user_id: int, channel_id: str):
    """Server-side ownership check; callback payload is never trusted."""
    try:
        channels = await db.run_db(db.get_user_channels, int(user_id)) or []
    except Exception:
        logger.warning("Retention callback channel ownership lookup failed", exc_info=True)
        return None
    requested = str(channel_id or "")
    for row in channels:
        if not row:
            continue
        try:
            current_id = row.get("channel_id") if isinstance(row, dict) else row[0]
        except (IndexError, KeyError, TypeError):
            continue
        if str(current_id) == requested:
            if isinstance(row, dict):
                title = row.get("channel_title") or row.get("title") or current_id
            else:
                title = row[1] if len(row) > 1 and row[1] else current_id
            return {"channel_id": requested, "title": str(title)}
    return None


async def _channel_ideas(channel_id: str, channel_title: str, lang: str) -> tuple[str, str, str]:
    topics = None
    try:
        profile = await db.run_db(db.get_channel_dna_profile, channel_id)
        if isinstance(profile, dict):
            topics = profile.get("topics")
    except Exception:
        # Suggestions remain useful without a DNA profile; never block the CTA.
        logger.debug("Daily digest: Channel DNA is unavailable", exc_info=True)
    return build_content_ideas(channel_title, topics, lang)


async def morning_digest_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open a three-idea picker from the daily digest (Conversation entry point)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    data = str(getattr(query, "data", "") or "")
    channel_id = data[len(CB_MORNING_DIGEST_CREATE):] if data.startswith(CB_MORNING_DIGEST_CREATE) else ""
    owner = await _owned_channel(query.from_user.id, channel_id)
    if owner is None:
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END

    ideas = await _channel_ideas(channel_id, owner["title"], lang)
    context.user_data["morning_digest_channel_id"] = channel_id
    context.user_data["morning_digest_ideas"] = list(ideas)
    lines = [retention_t("ideas_prompt", lang), "", f"📢 <b>{html.escape(owner['title'])}</b>", ""]
    lines.extend(f"{index}. {html.escape(idea)}" for index, idea in enumerate(ideas, 1))
    rows = [[InlineKeyboardButton(
        f"{index + 1}. {idea[:42]}",
        callback_data=cb(CB_MORNING_DIGEST_IDEA, index, channel_id),
    )] for index, idea in enumerate(ideas)]
    rows.append([InlineKeyboardButton(
        retention_t("cancel", lang), callback_data=CB_MORNING_DIGEST_CANCEL,
    )])
    await query.edit_message_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode="HTML",
    )
    return MORNING_IDEA_SELECT


async def morning_digest_idea_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validate the selected channel/idea and open the existing Magic Post styles."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    parts = str(getattr(query, "data", "") or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "md_idea":
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END
    try:
        idea_index = int(parts[1])
    except (TypeError, ValueError):
        idea_index = -1
    channel_id = parts[2]
    owner = await _owned_channel(query.from_user.id, channel_id)
    if owner is None or idea_index not in range(3):
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END

    ideas = context.user_data.get("morning_digest_ideas")
    if (context.user_data.get("morning_digest_channel_id") != channel_id
            or not isinstance(ideas, (list, tuple)) or len(ideas) < 3):
        # Stale/restarted FSM: use the same deterministic evergreen ideas.
        ideas = build_content_ideas(owner["title"], None, lang)
    topic = str(ideas[idea_index])

    # Clear an unrelated in-flight FSM while preserving language/navigation.
    clear_fsm_data(context)
    context.user_data["magic_raw_text"] = topic
    context.user_data["magic_target_channel_id"] = channel_id
    try:
        from handlers.magic_post import MAGIC_STYLE_SELECT, _magic_style_keyboard, _magic_style_menu_text
        await query.edit_message_text(
            _magic_style_menu_text(topic, lang),
            reply_markup=_magic_style_keyboard(lang),
            parse_mode="HTML",
        )
        return MAGIC_STYLE_SELECT
    except Exception:
        logger.warning("Daily digest idea could not open Magic Post", exc_info=True)
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END


async def morning_digest_disable_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Opt the user out of future morning digests, same as the settings toggle."""
    query = update.callback_query
    await query.answer()
    user_id = getattr(getattr(query, "from_user", None), "id", None)
    lang = get_lang(context)
    if not user_id:
        return
    try:
        saved = await db.run_db(db.set_user_setting, int(user_id), "notify_morning_digest", False)
    except Exception:
        saved = False
    if not saved:
        logger.warning("Morning digest opt-out could not be saved (user=%s)", user_id)
        return
    try:
        await query.edit_message_text(retention_t("disabled", lang), reply_markup=None)
    except Exception:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            logger.debug("Could not clear digest keyboard", exc_info=True)


async def morning_digest_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop("morning_digest_channel_id", None)
    context.user_data.pop("morning_digest_ideas", None)
    try:
        await query.edit_message_text(retention_t("cancelled", get_lang(context)), reply_markup=None)
    except Exception:
        logger.debug("Could not close morning digest idea picker", exc_info=True)
    return ConversationHandler.END


async def uzbek_calendar_create_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open Magic Post with the localized holiday/season topic prefilled."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(context)
    data = str(getattr(query, "data", "") or "")
    prefix = CB_UZ_CALENDAR_CREATE
    parts = data[len(prefix):].split(":", 1) if data.startswith(prefix) else []
    if len(parts) != 2:
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END
    event_key, channel_id = parts
    owner = await _owned_channel(query.from_user.id, channel_id)
    if owner is None:
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END

    year = datetime.now(_RETENTION_TZ).year
    event = get_calendar_event(event_key, year)
    if event is None:
        event = get_calendar_event(event_key, year + 1)
    if event is None:
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END

    topic = calendar_post_topic(event, lang)
    clear_fsm_data(context)
    context.user_data["magic_raw_text"] = topic
    context.user_data["magic_target_channel_id"] = channel_id
    try:
        from handlers.magic_post import MAGIC_STYLE_SELECT, _magic_style_keyboard, _magic_style_menu_text
        await query.edit_message_text(
            _magic_style_menu_text(topic, lang),
            reply_markup=_magic_style_keyboard(lang),
            parse_mode="HTML",
        )
        return MAGIC_STYLE_SELECT
    except Exception:
        logger.warning("Uzbekistan calendar reminder could not open Magic Post", exc_info=True)
        await query.edit_message_text(retention_t("calendar_error", lang), reply_markup=None)
        return ConversationHandler.END


__all__ = [
    "MORNING_IDEA_SELECT",
    "build_calendar_reminder_keyboard",
    "build_morning_digest_keyboard",
    "morning_digest_cancel_callback",
    "morning_digest_create_callback",
    "morning_digest_disable_callback",
    "morning_digest_idea_callback",
    "uzbek_calendar_create_callback",
]
