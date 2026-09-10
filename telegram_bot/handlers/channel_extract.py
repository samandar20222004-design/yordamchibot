"""Public Channel Post Extractor — ochiq kanallardan post o'qish va AI re-write."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard, get_button_prompt_keyboard
from keyboards.inline import btn_label
from keyboards.callback_data import cb
from locales.translations import get_text, get_lang
from utils.helpers import html_escape, safe_html, get_auto_ad_injection_async, keep_typing
from utils.channel_reader import (
    format_post_list, read_channel_posts, read_webpage_for_ai,
    extract_channel_username, is_website_link,
)

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


def _get_rewrite_result_keyboard(show_back: bool = True) -> InlineKeyboardMarkup:
    """AI natijasi uchun keyboard (sayt oqimida 'Boshqa post' tugmasi yashirinadi)."""
    rows = [
        [InlineKeyboardButton("✅ Kanalga rejalashtirish", callback_data="ext_schedule")],
        [InlineKeyboardButton("🔄 Qayta yozish", callback_data="ext_rewrite")],
    ]
    if show_back:
        rows.append([InlineKeyboardButton("🔙 Boshqa post tanlash", callback_data="ext_back")])
    rows.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="ext_cancel")])
    return InlineKeyboardMarkup(rows)


async def start_extract(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ochiq kanaldan post olish oqimini boshlash."""
    await update.message.reply_text(
        "📢 <b>Ochiq kanaldan post olish</b>\n\n"
        "Kanal nikini YOKI havolasini yuboring:\n"
        "• <code>@kunuzofficial</code>\n"
        "• <code>https://t.me/kunuzofficial</code>\n\n"
        "Yoki sayt havolasini yuboring (masalan: <code>https://kun.uz/</code>) — "
        "bot sahifani o'qib, AI tahlilini tayyorlaydi.\n\n"
        "<i>Faqat ochiq kanallar uchun ishlaydi.</i>",
        reply_markup=get_cancel_keyboard(),
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
    await update.message.reply_text("⏳ Sayt o'qilmoqda...")

    page = await read_webpage_for_ai(url)
    if "error" in page or not (page.get("content") or page.get("title")):
        error_text = page.get("error") or "⚠️ Saytdan matn o'qib bo'lmadi. Manzilni tekshirib, qayta yuboring."
        await update.message.reply_text(
            error_text,
            reply_markup=get_cancel_keyboard(),
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

    await update.message.reply_text("⏳ AI sahifani tahlil qilmoqda...")

    from utils.ai_agent import rewrite_channel_post
    tone = await _get_user_tone(user_id)

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception:
        pass

    async with keep_typing(context.bot, chat_id):
        result = await rewrite_channel_post(original_text, source, site_url, tone)

    if "error" in result:
        await update.message.reply_text(result["error"], parse_mode="HTML")
        return EXTRACT_USERNAME

    rewritten = result.get("post_text", "")
    if not rewritten:
        await update.message.reply_text("⚠️ AI sahifani qayta ishlolmadi.")
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
        f"✨ <b>AI taklifi ({html_escape(source)}):</b>\n\n{safe_html(preview)}{ad_line}",
        reply_markup=_get_rewrite_result_keyboard(show_back=False),
        parse_mode="HTML",
    )
    return EXTRACT_CHOOSE_POST


async def extract_username_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal niki/linki yoki sayt havolasi qabul qilish va postlarni olish."""
    text = (update.message.text or "").strip()
    user_id = update.effective_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if text in ("🔙 Asosiy menyu", "🔙 Orqaga"):
        await update.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    # 1) Sayt havolasi (masalan https://kun.uz/) → sahifani o'qib AI tahliliga beramiz
    if is_website_link(text):
        return await _handle_website_link(update, context, text, user_id)

    # 2) Telegram kanali: @kanal, kanal yoki https://t.me/kanal havolasi
    await update.message.reply_text("⏳ Kanal postlari o'qilmoqda...")

    result = await read_channel_posts(text, limit=5)
    status = result.get("status")
    posts = result.get("posts") or []
    username = result.get("channel") or extract_channel_username(text) or text.lstrip("@").strip().rstrip("/")

    if status == "private":
        lang = get_lang(context)
        if lang == "ru":
            msg = (
                "🔒 <b>Это закрытый канал.</b>\n\n"
                "Отправьте открытый канал или канал, где вы администратор.\n"
                "Например: <code>@kunuzofficial</code> или "
                "<code>https://t.me/kunuzofficial</code>"
            )
        elif lang == "en":
            msg = (
                "🔒 <b>This is a private channel.</b>\n\n"
                "Send a public channel or one where you are an admin.\n"
                "Example: <code>@kunuzofficial</code> or "
                "<code>https://t.me/kunuzofficial</code>"
            )
        else:
            msg = (
                "🔒 <b>Bu yopiq kanal.</b>\n\n"
                "Ochiq kanallarni yoki o'zingiz admin bo'lgan kanallarni yuboring.\n"
                "Masalan: <code>@kunuzofficial</code> yoki "
                "<code>https://t.me/kunuzofficial</code>"
            )
        await update.message.reply_text(
            msg,
            reply_markup=get_cancel_keyboard(lang),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if status == "not_found":
        await update.message.reply_text(
            f"❌ <b>{html_escape(text)}</b> — bunday kanal topilmadi.\n\n"
            "Manzilni tekshirib, qayta yuboring:\n"
            "<code>@kanal</code> yoki <code>https://t.me/kanal</code>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if status == "invalid":
        await update.message.reply_text(
            "⚠️ Noto'g'ri kanal niki yoki havolasi. Qaytadan kiriting:\n"
            "<code>@kanal</code>, <code>kanal</code> yoki <code>https://t.me/kanal</code>\n\n"
            "Yoki sayt havolasi: <code>https://kun.uz/</code>",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return EXTRACT_USERNAME

    if not posts:
        if status == "empty":
            await update.message.reply_text(
                f"📭 <b>{html_escape(username)}</b> kanalida postlar topilmadi.\n\n"
                "Boshqa kanal yoki sayt havolasini yuboring:",
                reply_markup=get_cancel_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"❌ <b>{html_escape(username)}</b> kanalidan postlar o'qilmadi.\n\n"
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
        else:
            await query.message.reply_text(
                "⚠️ Postlar ro'yxati mavjud emas. Yangi kanal yoki sayt havolasini yuboring:",
            )
        return EXTRACT_CHOOSE_POST

    if data == "ext_refresh":
        await query.answer("🔄 Yangilanmoqda...")
        username = context.user_data.get("extract_channel", "")
        if not username:
            return EXTRACT_CHOOSE_POST

        result = await read_channel_posts(username, limit=5)
        posts = result.get("posts") or []
        if not posts:
            if result.get("status") == "private":
                await query.message.reply_text(
                    "🔒 Bu yopiq kanal. Ochiq kanallarni yoki o'zingiz admin "
                    "bo'lgan kanallarni yuboring.",
                )
            else:
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
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
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
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass
        async with keep_typing(context.bot, chat_id):
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
