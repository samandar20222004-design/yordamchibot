"""Public Channel Post Extractor — ochiq kanallardan post o'qish va AI re-write."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_button_prompt_keyboard
from keyboards.callback_data import cb
from locales.translations import safe_t, get_lang, is_main_menu_text, localize_service_error
from utils.helpers import html_escape, safe_html, get_auto_ad_injection_async, keep_typing
from utils.channel_reader import (
    format_post_list, read_channel_posts, read_webpage_for_ai,
    extract_channel_username, is_website_link,
)

logger = logging.getLogger(__name__)

# States
EXTRACT_USERNAME = 701
EXTRACT_CHOOSE_POST = 702


def _get_post_list_keyboard(
    posts: list[dict], channel: str, lang: str = "uz",
) -> InlineKeyboardMarkup:
    """Postlar ro'yxati uchun keyboard."""
    keyboard = []
    media_preview = safe_t("ext_media_preview", lang)
    for i, post in enumerate(posts):
        text = post.get("text", "")
        preview = text[:35] if text else media_preview
        if len(text) > 35:
            preview += "…"
        keyboard.append([
            InlineKeyboardButton(
                f"📄 {i+1}. {preview}",
                callback_data=cb(f"ext_post:{i}"),
            )
        ])
    keyboard.append([
        InlineKeyboardButton(safe_t("ext_btn_refresh", lang), callback_data="ext_refresh")
    ])
    keyboard.append([
        InlineKeyboardButton(safe_t("ai_btn_close", lang), callback_data="ext_cancel")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_rewrite_result_keyboard(show_back: bool = True, lang: str = "uz") -> InlineKeyboardMarkup:
    """AI natijasi uchun keyboard (sayt oqimida 'Boshqa post' tugmasi yashirinadi)."""
    rows = [
        [InlineKeyboardButton(safe_t("ai_confirm_schedule", lang), callback_data="ext_schedule")],
        [InlineKeyboardButton(safe_t("ext_btn_rewrite", lang), callback_data="ext_rewrite")],
    ]
    if show_back:
        rows.append([
            InlineKeyboardButton(safe_t("ext_btn_other_post", lang), callback_data="ext_back")
        ])
    rows.append([
        InlineKeyboardButton(safe_t("ai_btn_close", lang), callback_data="ext_cancel")
    ])
    return InlineKeyboardMarkup(rows)


async def start_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ochiq kanaldan post olish oqimini boshlash."""
    lang = get_lang(context)
    await update.message.reply_text(
        safe_t("ext_intro", lang),
        reply_markup=get_cancel_keyboard(lang),
        parse_mode="HTML",
    )
    return EXTRACT_USERNAME


async def _get_user_tone(user_id: int) -> str:
    """Foydalanuvchining birinchi kanali uslubini (tone) qaytaradi."""
    tone = "friendly"
    try:
        channels = await db.run_db(db.get_user_channels, user_id)
        if channels:
            ch_id = channels[0][0]
            tone = await db.run_db(db.get_channel_tone, ch_id)
    except Exception:
        pass
    return tone


async def _handle_website_link(update: Update, context: ContextTypes.DEFAULT_TYPE,
                               url: str, user_id: int):
    """Sayt havolasi (masalan https://kun.uz/) — sahifani o'qib AI'ga tahlilga beradi.

    read_webpage_for_ai() sahifaning <title>, <meta name="description"> va
    asosiy matnini (1000 belgigacha) o'qiydi — natija AI re-write oqimiga
    yetkaziladi.
    """
    lang = get_lang(context)
    await update.message.reply_text(safe_t("ext_reading_site", lang))

    page = await read_webpage_for_ai(url)
    if "error" in page or not (page.get("content") or page.get("title")):
        raw_error = page.get("error") or safe_t("ext_site_read_failed", lang)
        if page.get("error"):
            raw_error = localize_service_error(raw_error, lang)
        await update.message.reply_text(
            raw_error,
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    original_text = page.get("content") or page.get("title") or ""
    source = page.get("title") or page.get("url") or url
    site_url = page.get("url") or url

    context.user_data["extract_channel"] = source
    context.user_data["extract_original"] = original_text
    context.user_data["extract_post_link"] = site_url
    context.user_data["extract_posts"] = []

    await update.message.reply_text(safe_t("ext_ai_analyzing_page", lang))

    from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
    tone = await _get_user_tone(user_id)

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    async with keep_typing(context.bot, chat_id):
        # 🌐 Qayta yozilgan post foydalanuvchi tilida (uz/ru/en).
        result = await rewrite_channel_post(
            original_text, source, site_url, tone,
            **pick_supported_kwargs(rewrite_channel_post, lang=lang),
        )

    if "error" in result:
        await update.message.reply_text(
            localize_service_error(result["error"], lang), parse_mode="HTML"
        )
        return EXTRACT_USERNAME

    rewritten = result.get("post_text", "")
    if not rewritten:
        await update.message.reply_text(safe_t("ext_ai_page_failed", lang))
        return EXTRACT_USERNAME

    context.user_data["extract_rewritten"] = rewritten
    context.user_data["content"] = rewritten
    context.user_data["post_type"] = "text"
    context.user_data["file_id"] = None

    preview = rewritten[:500]
    if len(rewritten) > 500:
        preview += "…"

    ad_line = await get_auto_ad_injection_async(user_id)
    await update.message.reply_text(
        safe_t(
            "ext_ai_proposal_src", lang,
            src=html_escape(source), text=safe_html(preview),
        ) + ad_line,
        reply_markup=_get_rewrite_result_keyboard(show_back=False, lang=lang),
        parse_mode="HTML",
    )
    return EXTRACT_CHOOSE_POST


async def extract_username_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal niki/linki yoki sayt havolasi qabul qilish va postlarni olish."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = get_lang(context)

    if is_main_menu_text(text):
        await update.message.reply_text(
            safe_t("op_cancelled", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    # 1) Sayt havolasi (masalan https://kun.uz/) → sahifani o'qib AI tahliliga beramiz
    if is_website_link(text):
        return await _handle_website_link(update, context, text, user_id)

    # 2) Telegram kanali: @kanal, kanal yoki https://t.me/kanal havolasi
    await update.message.reply_text(safe_t("ext_reading_posts", lang))

    result = await read_channel_posts(text, limit=5)
    status = result.get("status")
    posts = result.get("posts") or []
    username = result.get("channel") or extract_channel_username(text) or text.lstrip("@").strip().rstrip("/")

    if status == "private":
        await update.message.reply_text(
            safe_t("ext_private_channel_full", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if status == "not_found":
        await update.message.reply_text(
            safe_t("ext_not_found", lang, text=html_escape(text)),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if status == "invalid":
        await update.message.reply_text(
            safe_t("ext_invalid_username", lang),
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if not posts:
        if status == "empty":
            await update.message.reply_text(
                safe_t("ext_empty", lang, channel=html_escape(username)),
                reply_markup=get_cancel_keyboard(lang),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                safe_t("ext_read_failed", lang, channel=html_escape(username)),
                reply_markup=get_cancel_keyboard(lang),
                parse_mode="HTML",
            )
        return EXTRACT_USERNAME

    context.user_data["extract_channel"] = username
    context.user_data["extract_posts"] = posts

    list_text = format_post_list(posts, username, lang)
    await update.message.reply_text(
        list_text,
        reply_markup=_get_post_list_keyboard(posts, username, lang),
        parse_mode="HTML",
    )
    return EXTRACT_CHOOSE_POST


async def extract_post_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post tanlash va AI re-write."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    lang = get_lang(context)

    if data == "ext_cancel":
        await query.answer()
        await query.message.reply_text(
            safe_t("op_cancelled", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "ext_back":
        await query.answer()
        username = context.user_data.get("extract_channel", "")
        posts = context.user_data.get("extract_posts", [])
        if posts:
            list_text = format_post_list(posts, username, lang)
            await query.message.reply_text(
                list_text,
                reply_markup=_get_post_list_keyboard(posts, username, lang),
                parse_mode="HTML",
            )
        else:
            await query.message.reply_text(safe_t("ext_no_list", lang))
        return EXTRACT_CHOOSE_POST

    if data == "ext_refresh":
        await query.answer(safe_t("ext_refreshing", lang))
        username = context.user_data.get("extract_channel", "")
        if not username:
            return EXTRACT_CHOOSE_POST

        result = await read_channel_posts(username, limit=5)
        posts = result.get("posts") or []
        if not posts:
            if result.get("status") == "private":
                await query.message.reply_text(safe_t("ext_private_channel", lang))
            else:
                await query.message.reply_text(safe_t("ext_no_posts", lang))
            return EXTRACT_CHOOSE_POST

        context.user_data["extract_posts"] = posts
        list_text = format_post_list(posts, username, lang)
        await query.message.reply_text(
            list_text,
            reply_markup=_get_post_list_keyboard(posts, username, lang),
            parse_mode="HTML",
        )
        return EXTRACT_CHOOSE_POST

    if data.startswith("ext_post:"):
        await query.answer()
        idx_str = data.split(":", 1)[1]
        try:
            idx = int(idx_str)
        except (ValueError, TypeError):
            return EXTRACT_CHOOSE_POST

        posts = context.user_data.get("extract_posts", [])
        if idx < 0 or idx >= len(posts):
            await query.message.reply_text(safe_t("ext_invalid_post", lang))
            return EXTRACT_CHOOSE_POST

        post = posts[idx]
        original_text = post.get("text", "")
        post_link = post.get("post_link", "")
        username = context.user_data.get("extract_channel", "")

        if not original_text:
            await query.message.reply_text(safe_t("ext_post_no_text", lang))
            return EXTRACT_CHOOSE_POST

        # Saqlab qo'yamiz
        context.user_data["extract_original"] = original_text
        context.user_data["extract_post_link"] = post_link

        tone = await _get_user_tone(user_id)

        await query.message.reply_text(safe_t("ext_ai_rewriting", lang))

        from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
            result = await rewrite_channel_post(
                original_text, username, post_link, tone,
                **pick_supported_kwargs(rewrite_channel_post, lang=lang),
            )

        if "error" in result:
            await query.message.reply_text(
                localize_service_error(result["error"], lang), parse_mode="HTML"
            )
            return EXTRACT_CHOOSE_POST

        rewritten = result.get("post_text", "")
        if not rewritten:
            await query.message.reply_text(safe_t("ext_ai_rewrite_failed", lang))
            return EXTRACT_CHOOSE_POST

        context.user_data["extract_rewritten"] = rewritten
        context.user_data["content"] = rewritten
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None

        preview = rewritten[:500]
        if len(rewritten) > 500:
            preview += "…"

        ad_line = await get_auto_ad_injection_async(user_id)
        await query.message.reply_text(
            safe_t("ext_ai_proposal", lang, text=safe_html(preview)) + ad_line,
            reply_markup=_get_rewrite_result_keyboard(lang=lang),
            parse_mode="HTML",
        )
        return EXTRACT_CHOOSE_POST

    if data == "ext_rewrite":
        await query.answer(safe_t("ext_rewriting", lang))
        original_text = context.user_data.get("extract_original", "")
        post_link = context.user_data.get("extract_post_link", "")
        username = context.user_data.get("extract_channel", "")

        tone = await _get_user_tone(user_id)

        from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
            result = await rewrite_channel_post(
                original_text, username, post_link, tone,
                **pick_supported_kwargs(rewrite_channel_post, lang=lang),
            )

        if "error" in result:
            await query.message.reply_text(
                localize_service_error(result["error"], lang), parse_mode="HTML"
            )
            return EXTRACT_CHOOSE_POST

        rewritten = result.get("post_text", "")
        if rewritten:
            context.user_data["extract_rewritten"] = rewritten
            context.user_data["content"] = rewritten
            context.user_data["post_type"] = "text"
            context.user_data["file_id"] = None

            preview = rewritten[:500]
            if len(rewritten) > 500:
                preview += "…"

            await query.message.reply_text(
                safe_t("np_ai_retry_proposal", lang, new=safe_html(preview)),
                reply_markup=_get_rewrite_result_keyboard(lang=lang),
                parse_mode="HTML",
            )
        return EXTRACT_CHOOSE_POST

    if data == "ext_schedule":
        await query.answer()
        rewritten = context.user_data.get("extract_rewritten", "")
        if not rewritten:
            await query.message.reply_text(safe_t("ext_no_post_text", lang))
            return EXTRACT_CHOOSE_POST

        # Post yaratish oqimiga o'tkazish
        context.user_data["content"] = rewritten
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None

        await query.message.reply_text(
            safe_t("ext_post_accepted", lang),
            reply_markup=get_button_prompt_keyboard(lang),
            parse_mode="HTML",
        )
        from handlers.new_post import GET_BTN_TITLE
        return GET_BTN_TITLE

    return EXTRACT_CHOOSE_POST
