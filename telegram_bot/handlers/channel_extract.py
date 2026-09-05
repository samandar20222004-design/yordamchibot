"""Public Channel Post Extractor — ochiq kanallardan post o'qish va AI re-write."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_button_prompt_keyboard
from keyboards.inline import btn_label
from keyboards.callback_data import cb
from utils.helpers import html_escape, safe_html, get_auto_ad_injection_async, keep_typing
from utils.channel_reader import fetch_latest_channel_posts, format_post_list

logger = logging.getLogger(__name__)

# States
EXTRACT_USERNAME = 701
EXTRACT_CHOOSE_POST = 702


def _get_post_list_keyboard(posts: list[dict], channel: str) -> InlineKeyboardMarkup:
    """Postlar ro'yxati uchun keyboard."""
    keyboard = []
    for i, post in enumerate(posts):
        text = post.get("text", "")
        preview = text[:35] if text else "🖼 Rasm/Video"
        if len(text) > 35:
            preview += "…"
        keyboard.append([
            InlineKeyboardButton(
                f"📄 {i+1}. {preview}",
                callback_data=cb(f"ext_post:{i}"),
            )
        ])
    keyboard.append([InlineKeyboardButton("🔄 Yangilash", callback_data="ext_refresh")])
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="ext_cancel")])
    return InlineKeyboardMarkup(keyboard)


def _get_rewrite_result_keyboard() -> InlineKeyboardMarkup:
    """AI natijasi uchun keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ext_schedule")],
        [InlineKeyboardButton("🔄 Qayta yozish", callback_data="ext_rewrite")],
        [InlineKeyboardButton("🔙 Boshqa post tanlash", callback_data="ext_back")],
        [InlineKeyboardButton("❌ Bekor qilish", callback_data="ext_cancel")],
    ])


async def start_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ochiq kanaldan post olish oqimini boshlash."""
    await update.message.reply_text(
        "📢 <b>Ochiq kanaldan post olish</b>\n\n"
        "Kanal nikini kiriting (masalan: <code>@kunuzofficial</code> yoki <code>daryo</code>):\n\n"
        "<i>Faqat ochiq kanallar uchun ishlaydi.</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return EXTRACT_USERNAME


async def extract_username_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal niki qabul qilish va postlarni olish."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if text in ("🔙 Asosiy menyu", "🔙 Orqaga"):
        await update.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    # Username tozalash
    username = text.lstrip("@").strip().rstrip("/")
    if not username or len(username) < 3:
        await update.message.reply_text(
            "⚠️ Noto'g'ri kanal niki. Qaytadan kiriting:",
            reply_markup=get_cancel_keyboard(),
        )
        return EXTRACT_USERNAME

    await update.message.reply_text("⏳ Kanal postlari o'qilmoqda...")

    posts = await fetch_latest_channel_posts(username, limit=5)

    if not posts:
        await update.message.reply_text(
            f"❌ <b>@{html_escape(username)}</b> kanalidan postlar o'qilmadi.\n\n"
            "Sabablari:\n"
            "• Kanal yopiq (private)\n"
            "• Kanal niki noto'g'ri\n"
            "• Kanalda postlar yo'q\n\n"
            "Qaytadan urinib ko'ring:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    context.user_data["extract_channel"] = username
    context.user_data["extract_posts"] = posts

    list_text = format_post_list(posts, username)
    await update.message.reply_text(
        list_text,
        reply_markup=_get_post_list_keyboard(posts, username),
        parse_mode="HTML",
    )
    return EXTRACT_CHOOSE_POST


async def extract_post_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Post tanlash va AI re-write."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if data == "ext_cancel":
        await query.answer()
        await query.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "ext_back":
        await query.answer()
        username = context.user_data.get("extract_channel", "")
        posts = context.user_data.get("extract_posts", [])
        if posts:
            list_text = format_post_list(posts, username)
            await query.message.reply_text(
                list_text,
                reply_markup=_get_post_list_keyboard(posts, username),
                parse_mode="HTML",
            )
        return EXTRACT_CHOOSE_POST

    if data == "ext_refresh":
        await query.answer("🔄 Yangilanmoqda...")
        username = context.user_data.get("extract_channel", "")
        if not username:
            return EXTRACT_CHOOSE_POST

        posts = await fetch_latest_channel_posts(username, limit=5)
        if not posts:
            await query.message.reply_text("⚠️ Postlar topilmadi.")
            return EXTRACT_CHOOSE_POST

        context.user_data["extract_posts"] = posts
        list_text = format_post_list(posts, username)
        await query.message.reply_text(
            list_text,
            reply_markup=_get_post_list_keyboard(posts, username),
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
            await query.message.reply_text("❌ Noto'g'ri post tanlandi.")
            return EXTRACT_CHOOSE_POST

        post = posts[idx]
        original_text = post.get("text", "")
        post_link = post.get("post_link", "")
        username = context.user_data.get("extract_channel", "")

        if not original_text:
            await query.message.reply_text(
                "⚠️ Bu postda matn yo'q (faqat rasm/video). Boshqa postni tanlang.",
            )
            return EXTRACT_CHOOSE_POST

        # Saqlab qo'yamiz
        context.user_data["extract_original"] = original_text
        context.user_data["extract_post_link"] = post_link

        # Kanal tone ini olamiz
        tone = "friendly"
        channels = await db.run_db(db.get_user_channels, user_id)
        if channels:
            ch_id = channels[0][0]
            tone = await db.run_db(db.get_channel_tone, ch_id)

        await query.message.reply_text("⏳ AI postni qayta yozmoqda...")

        from utils.ai_agent import rewrite_channel_post
        # AI javob kelgunicha chatda uzluksiz "typing..." ko'rsatamiz
        async with keep_typing(context.bot, query.message.chat_id):
            result = await rewrite_channel_post(original_text, username, post_link, tone)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
            return EXTRACT_CHOOSE_POST

        rewritten = result.get("post_text", "")
        if not rewritten:
            await query.message.reply_text("⚠️ AI postni qayta yozolmadi.")
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
            f"✨ <b>AI taklifi:</b>\n\n{safe_html(preview)}{ad_line}",
            reply_markup=_get_rewrite_result_keyboard(),
            parse_mode="HTML",
        )
        return EXTRACT_CHOOSE_POST

    if data == "ext_rewrite":
        await query.answer("🔄 Qayta yozilmoqda...")
        original_text = context.user_data.get("extract_original", "")
        post_link = context.user_data.get("extract_post_link", "")
        username = context.user_data.get("extract_channel", "")

        tone = "friendly"
        channels = await db.run_db(db.get_user_channels, user_id)
        if channels:
            ch_id = channels[0][0]
            tone = await db.run_db(db.get_channel_tone, ch_id)

        from utils.ai_agent import rewrite_channel_post
        # AI javob kelgunicha chatda uzluksiz "typing..." ko'rsatamiz
        async with keep_typing(context.bot, query.message.chat_id):
            result = await rewrite_channel_post(original_text, username, post_link, tone)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
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
                f"✨ <b>AI taklifi (qayta):</b>\n\n{safe_html(preview)}",
                reply_markup=_get_rewrite_result_keyboard(),
                parse_mode="HTML",
            )
        return EXTRACT_CHOOSE_POST

    if data == "ext_schedule":
        await query.answer()
        rewritten = context.user_data.get("extract_rewritten", "")
        if not rewritten:
            await query.message.reply_text("⚠️ Post matni topilmadi.")
            return EXTRACT_CHOOSE_POST

        # Post yaratish oqimiga o'tkazish
        context.user_data["content"] = rewritten
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None

        from keyboards.default import get_button_prompt_keyboard
        await query.message.reply_text(
            "✅ <b>Post qabul qilindi!</b>\n\n"
            "Endi tugma, vaqt va boshqa sozlamalarni kiriting.",
            reply_markup=get_button_prompt_keyboard(),
            parse_mode="HTML",
        )
        from handlers.new_post import GET_BTN_TITLE
        return GET_BTN_TITLE

    return EXTRACT_CHOOSE_POST
