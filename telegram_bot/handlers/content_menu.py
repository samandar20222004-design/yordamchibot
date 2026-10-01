"""🧩 PHASE 9 — `[✍️ Post yaratish]` kontekstual menyusi va dispatcher'i.

`[✍️ Post yaratish]` bosilganda chiqadigan 4x2 kontekstual inline menyu:
  - `[⚡ AI Post]`        | `[📝 Oddiy Post]`
  - `[🖼 Rasmdan Post]`   | `[🎙 Ovozdan Post]`
  - `[🔗 Havoladan Post]` | `[♻️ Qayta ishlash]`
  - `[🤖 AI Yordamchi]`   | `[📊 Post Score]`
"""

from __future__ import annotations

import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import database as db
from handlers.ai_assistant import ai_studio_hub_entry, ai_studio_menu_entry
from handlers.content_creation import content_creation_back
from handlers.image_post import image_post_entry
from handlers.magic_post import magic_post_entry
from handlers.manual_post import manual_post_entry
from handlers.post_score import post_score_entry
from handlers.sources import (
    SRC_URL_INPUT,
    UD_CHANNEL,
    UD_TITLE,
    _render_recycle_list,
    clear_sources_session,
)
from handlers.voice_post import voice_post_entry
from keyboards.callback_data import (
    CB_CTX_AI_ASSISTANT,
    CB_CTX_AI_POST,
    CB_CTX_IMAGE_POST,
    CB_CTX_LINK_POST,
    CB_CTX_MANUAL_POST,
    CB_CTX_POST_SCORE,
    CB_CTX_RECYCLE_POST,
    CB_CTX_VOICE_POST,
)
from keyboards.default import get_cancel_keyboard
from locales.translations import get_lang
from translations import sources_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)


async def _ensure_first_channel(query, context, user_id: int, lang: str):
    """Foydalanuvchining birinchi ulangan kanalini topadi yoki yo'riqnoma beradi."""
    try:
        channels = await db.run_db(db.get_user_channels, user_id)
    except Exception:
        channels = []
    if not channels:
        msg = getattr(query, "message", None)
        if msg is not None:
            try:
                await msg.reply_text(sources_t("src_no_channels", lang), parse_mode="HTML")
            except Exception:
                pass
        return None, None
    ch_id = str(channels[0][0])
    ch_title = str(channels[0][1] or "Kanal") if len(channels[0]) > 1 else "Kanal"
    clear_sources_session(context)
    context.user_data[UD_CHANNEL] = ch_id
    context.user_data[UD_TITLE] = ch_title
    return ch_id, ch_title


async def contextual_post_menu_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    """`[✍️ Post yaratish]` kontekstual menyusidagi 8 ta inline tugma dispatcher'i."""
    query = getattr(update, "callback_query", None)
    if query is None:
        return ConversationHandler.END
    try:
        await query.answer()
    except Exception:
        pass

    data = str(getattr(query, "data", "") or "")
    lang = get_lang(context)
    user = getattr(update, "effective_user", None) or getattr(query, "from_user", None)
    user_id = user.id if user else 0

    if data == CB_CTX_AI_POST:
        return await magic_post_entry(update, context)
    if data == CB_CTX_MANUAL_POST:
        return await manual_post_entry(update, context)
    if data == CB_CTX_IMAGE_POST:
        return await image_post_entry(update, context)
    if data == CB_CTX_VOICE_POST:
        return await voice_post_entry(update, context)
    if data == CB_CTX_AI_ASSISTANT:
        return await ai_studio_hub_entry(update, context)
    if data == CB_CTX_POST_SCORE:
        return await post_score_entry(update, context)

    if data == CB_CTX_LINK_POST:
        ch_id, _ = await _ensure_first_channel(query, context, user_id, lang)
        if not ch_id:
            return ConversationHandler.END
        msg = getattr(query, "message", None)
        if msg is not None:
            try:
                await msg.reply_text(
                    sources_t("src_url_ask", lang),
                    reply_markup=get_cancel_keyboard(lang),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        return SRC_URL_INPUT

    if data == CB_CTX_RECYCLE_POST:
        ch_id, ch_title = await _ensure_first_channel(query, context, user_id, lang)
        if not ch_id:
            return ConversationHandler.END
        return await _render_recycle_list(
            query, context, user_id, ch_id, html_escape(ch_title), lang
        )

    return ConversationHandler.END


__all__ = [
    "ai_studio_menu_entry",
    "content_creation_back",
    "contextual_post_menu_callback",
]
