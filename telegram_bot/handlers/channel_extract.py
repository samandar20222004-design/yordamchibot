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

from utils.silent_errors import log_silent_failure

logger = logging.getLogger(__name__)

# States
EXTRACT_USERNAME = 701
EXTRACT_CHOOSE_POST = 702
EXTRACT_EDIT = 703  # 2-vazifa: qo'lda tahrirlash holati


async def _edit_wait_message(wait_message, fallback_message, text: str, **kwargs):
    """Edit the wait placeholder, with a reply fallback for minimal adapters."""
    editor = getattr(wait_message, "edit_text", None)
    if callable(editor):
        try:
            return await editor(text, **kwargs)
        except Exception:
            logger.debug("Wait message edit failed; using reply fallback", exc_info=True)
    return await fallback_message.reply_text(text, **kwargs)


import re

# 2-vazifa: begona havolalar, reklamalar, imzolarni tozalash uchun regexlar
_FOREIGN_TME_RE = re.compile(r'(?:https?://)?t\.me/[A-Za-z0-9_]+(?:/[^\s]*)?', re.IGNORECASE)
_MENTION_RE = re.compile(r'@([A-Za-z0-9_]{3,32})')
_URL_RE = re.compile(r'https?://[^\s]+', re.IGNORECASE)
_AD_KEYWORDS = [
    "reklama", "reklamalar", "obuna bo'ling", "kanalga obuna", "a'zo bo'ling",
    "подпишитесь на канал", "реклама", "subscribe", "join channel",
    "manba:", "manba ", "source:", "via @", "via:", "ko'proq", "batafsil",
]
_SIGNATURE_LINES_RE = re.compile(r'(?im)^.*(manba\s*:|source\s*:|via\s*@|@\w+\s*$|t\.me/\w+).*$')


async def _get_user_channels_info(user_id: int):
    """Foydalanuvchi kanallari ro'yxati (id, title) — adapt uchun."""
    try:
        channels = await db.run_db(db.get_user_channels, user_id)
        return channels or []
    except Exception:
        return []


def _clean_foreign_content(text: str, user_channels: list) -> str:
    """Begona havolalar, reklamalar, imzolarni tozalash (regex asosida, fail-safe)."""
    if not text:
        return text
    # Foydalanuvchi kanallarining username'larini ajratib olamiz (agar title @ bo'lsa)
    own_usernames = set()
    for _, title in (user_channels or []):
        if not title:
            continue
        # title dan @username ajratishga harakat
        m = _MENTION_RE.search(title)
        if m:
            own_usernames.add(m.group(1).lower())
        # t.me/username ham
        m2 = _FOREIGN_TME_RE.search(title)
        if m2:
            try:
                uname = m2.group(0).split('/')[-1].split('?')[0].lower()
                own_usernames.add(uname)
            except Exception as _silent_exc:
                log_silent_failure("handlers.channel_extract:_clean_foreign_content", _silent_exc)

    cleaned = text

    # 1) Begona t.me havolalarini olib tashlash (o'z kanalimizdan tashqari)
    def _tme_repl(match):
        url = match.group(0)
        try:
            uname = url.split('/')[-1].split('?')[0].lower().lstrip('@')
            if uname in own_usernames:
                return url  # o'z kanalimiz — saqlaymiz
        except Exception as _silent_exc:
            log_silent_failure("handlers.channel_extract:_clean_foreign_content._tme_repl", _silent_exc)
        return ""  # begona — o'chiramiz

    cleaned = _FOREIGN_TME_RE.sub(_tme_repl, cleaned)

    # 2) @mention'larni tozalash (o'z kanalimizdan tashqari)
    def _mention_repl(match):
        uname = match.group(1).lower()
        if uname in own_usernames:
            return match.group(0)
        return ""

    cleaned = _MENTION_RE.sub(_mention_repl, cleaned)

    # 3) Reklama kalit so'zlari bo'lgan qatorlarni olib tashlash
    lines = cleaned.split('\n')
    filtered_lines = []
    for line in lines:
        low = line.lower()
        is_ad = False
        for kw in _AD_KEYWORDS:
            if kw in low and len(line.strip()) < 120:  # qisqa reklama qatorlari
                # Agar qatorda asosiy kontent ham bo'lsa, saqlaymiz
                if any(x in low for x in ["reklama", "obuna", "manba", "source"]):
                    # Faqat reklama/imzo qatori bo'lsa o'chiramiz
                    if len(line.strip().split()) <= 8:
                        is_ad = True
                        break
        if not is_ad:
            filtered_lines.append(line)
    cleaned = '\n'.join(filtered_lines)

    # 4) Ortig'ini tozalash: ko'p bo'sh qatorlar, ortiqcha bo'shliqlar
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = re.sub(r'[ \t]{2,}', ' ', cleaned)
    return cleaned.strip()


async def _adapt_post_with_ai(original_text: str, user_channels: list, tone: str, lang: str) -> str:
    """AI orqali begona kontentni tozalab, foydalanuvchi kanaliga moslash.

    2-vazifa: "🎯 Kanalimga moslash" — begona havolalar, reklamalar, imzolarni
    tozalab, foydalanuvchi kanali uslubiga moslab qayta yozish.
    """
    # Avval regex bilan tozalash (fail-safe)
    cleaned = _clean_foreign_content(original_text, user_channels)

    # Foydalanuvchi kanali haqida ma'lumot
    channel_info = ""
    if user_channels:
        titles = ", ".join([t for _, t in user_channels[:3] if t])
        channel_info = f"Foydalanuvchi kanallari: {titles}. " if titles else ""

    # AI orqali moslash — agar AI mavjud bo'lsa
    try:
        from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
        prompt_extra = (
            f"{channel_info}Quyidagi postni BEGONA havolalar, reklamalar, imzolar, "
            f"manba ko'rsatkichlari (@username, t.me/...) dan TOZALAB, "
            f"foydalanuvchi kanali uslubiga moslab qayta yoz. "
            f"O'z kanaliga oid bo'lmagan har qanday havola, reklama, imzo olib tashlansin. "
            f"Oxirida foydalanuvchi kanali havolasi yoki nomi tabiiy ravishda qo'shilishi mumkin, "
            f"lekin majburiy emas. Faqat toza, moslashtirilgan post matnini qaytar."
        )
        # rewrite_channel_post mavjud — uni adapt uchun ishlatamiz
        result = await rewrite_channel_post(
            cleaned, "user_channel", "", tone,
            **pick_supported_kwargs(rewrite_channel_post, lang=lang),
        )
        if isinstance(result, dict) and not result.get("error"):
            new_text = str(result.get("post_text") or result.get("text") or "").strip()
            if new_text:
                return new_text
    except Exception as e:
        logger.debug(f"AI adapt xatosi: {e}", exc_info=True)

    # AI ishlamasa — regex tozalangan variantni qaytaramiz
    return cleaned


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
    """AI natijasi uchun keyboard — 2-vazifa: adapt + manual edit tugmalari qo'shildi."""
    # 2-vazifa: yangi tugmalar
    try:
        adapt_text = safe_t("ext_btn_adapt", lang)
    except Exception:
        adapt_text = {"uz": "🎯 Kanalimga moslash", "ru": "🎯 Адаптировать под мой канал", "en": "🎯 Adapt to my channel"}.get(lang, "🎯 Kanalimga moslash")
    try:
        edit_text = safe_t("ext_btn_manual_edit", lang)
    except Exception:
        edit_text = {"uz": "✏️ Qo'lda tahrirlash", "ru": "✏️ Редактировать вручную", "en": "✏️ Edit manually"}.get(lang, "✏️ Qo'lda tahrirlash")

    rows = [
        [InlineKeyboardButton(adapt_text, callback_data="ext_adapt")],
        [InlineKeyboardButton(edit_text, callback_data="ext_edit")],
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
    except Exception as _silent_exc:
        log_silent_failure("handlers.channel_extract:_get_user_tone", _silent_exc, user_id=user_id)
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

    from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
    tone = await _get_user_tone(user_id)

    chat_id = update.effective_chat.id
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception as _silent_exc:
        log_silent_failure("handlers.channel_extract:_handle_website_link", _silent_exc, user_id=user_id, chat_id=chat_id, lang=lang)

    wait_msg = await update.message.reply_text("⏳ Post tayyorlanmoqda, iltimos kuting...")
    async with keep_typing(context.bot, chat_id):
        # 🌐 Qayta yozilgan post foydalanuvchi tilida (uz/ru/en).
        result = await rewrite_channel_post(
            original_text, source, site_url, tone,
            **pick_supported_kwargs(rewrite_channel_post, lang=lang),
        )

    if "error" in result:
        await _edit_wait_message(wait_msg, update.message,
            localize_service_error(result["error"], lang), parse_mode="HTML"
        )
        return EXTRACT_USERNAME

    rewritten = result.get("post_text", "")
    if not rewritten:
        await wait_msg.edit_text(safe_t("ext_ai_page_failed", lang))
        return EXTRACT_USERNAME

    context.user_data["extract_rewritten"] = rewritten
    context.user_data["content"] = rewritten
    context.user_data["post_type"] = "text"
    context.user_data["file_id"] = None

    preview = rewritten[:500]
    if len(rewritten) > 500:
        preview += "…"

    ad_line = await get_auto_ad_injection_async(user_id)
    await wait_msg.edit_text(
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

        from utils.ai_agent import rewrite_channel_post, pick_supported_kwargs
        # Indikator darhol ko'rinsin, keyin uzoq AI so'rovi davomida yangilanib tursin.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as _silent_exc:
            log_silent_failure("handlers.channel_extract:extract_post_chosen:494", _silent_exc, chat_id=chat_id)
        wait_msg = await query.message.reply_text("⏳ Post tayyorlanmoqda, iltimos kuting...")
        async with keep_typing(context.bot, chat_id):
            result = await rewrite_channel_post(
                original_text, username, post_link, tone,
                **pick_supported_kwargs(rewrite_channel_post, lang=lang),
            )

        if "error" in result:
            await _edit_wait_message(wait_msg, query.message,
                localize_service_error(result["error"], lang), parse_mode="HTML"
            )
            return EXTRACT_CHOOSE_POST

        rewritten = result.get("post_text", "")
        if not rewritten:
            await _edit_wait_message(wait_msg, query.message, safe_t("ext_ai_rewrite_failed", lang))
            return EXTRACT_CHOOSE_POST

        context.user_data["extract_rewritten"] = rewritten
        context.user_data["content"] = rewritten
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None

        preview = rewritten[:500]
        if len(rewritten) > 500:
            preview += "…"

        ad_line = await get_auto_ad_injection_async(user_id)
        await _edit_wait_message(wait_msg, query.message,
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
        # Indikator darhol ko'rinsin, natija shu xabarda yangilanadi.
        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as _silent_exc:
            log_silent_failure("handlers.channel_extract:extract_post_chosen:544", _silent_exc, chat_id=chat_id)
        wait_msg = await query.message.reply_text("⏳ Post tayyorlanmoqda, iltimos kuting...")
        async with keep_typing(context.bot, chat_id):
            result = await rewrite_channel_post(
                original_text, username, post_link, tone,
                **pick_supported_kwargs(rewrite_channel_post, lang=lang),
            )

        if "error" in result:
            await _edit_wait_message(wait_msg, query.message,
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

            await _edit_wait_message(wait_msg, query.message,
                safe_t("np_ai_retry_proposal", lang, new=safe_html(preview)),
                reply_markup=_get_rewrite_result_keyboard(lang=lang),
                parse_mode="HTML",
            )
        return EXTRACT_CHOOSE_POST

    # 2-vazifa: 🎯 Kanalimga moslash — begona havolalar/reklamalarni tozalash
    if data == "ext_adapt":
        await query.answer(safe_t("ext_adapting", lang) if "ext_adapting" in safe_t.__code__.co_varnames else "🎯 Moslashtirilmoqda...")
        original = context.user_data.get("extract_original") or context.user_data.get("extract_rewritten") or ""
        if not original:
            await query.message.reply_text(safe_t("ext_no_post_text", lang))
            return EXTRACT_CHOOSE_POST

        tone = await _get_user_tone(user_id)
        user_channels = await _get_user_channels_info(user_id)

        chat_id = query.message.chat_id
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception as _silent_exc:
            log_silent_failure("handlers.channel_extract:extract_post_chosen:591", _silent_exc, chat_id=chat_id)
        wait_msg = await query.message.reply_text("⏳ Kanalga moslashtirilmoqda, iltimos kuting...")

        async with keep_typing(context.bot, chat_id):
            adapted = await _adapt_post_with_ai(original, user_channels, tone, lang)

        if not adapted:
            adapted = _clean_foreign_content(original, user_channels)

        context.user_data["extract_rewritten"] = adapted
        context.user_data["content"] = adapted

        preview = adapted[:500]
        if len(adapted) > 500:
            preview += "…"

        ad_line = await get_auto_ad_injection_async(user_id)
        await _edit_wait_message(wait_msg, query.message,
            safe_t("ext_ai_proposal", lang, text=safe_html(preview)) + ad_line,
            reply_markup=_get_rewrite_result_keyboard(lang=lang),
            parse_mode="HTML",
        )
        return EXTRACT_CHOOSE_POST

    # 2-vazifa: ✏️ Qo'lda tahrirlash — matnni yuborib, qo'lda tahrirlash
    if data == "ext_edit":
        await query.answer()
        current = context.user_data.get("extract_rewritten") or context.user_data.get("extract_original") or ""
        if not current:
            await query.message.reply_text(safe_t("ext_no_post_text", lang))
            return EXTRACT_CHOOSE_POST

        # Hozirgi matnni yuborib, tahrirlashni so'rash
        await query.message.reply_text(
            safe_t("ext_edit_prompt", lang, text=safe_html(current[:3500])),
            parse_mode="HTML",
        )
        return EXTRACT_EDIT

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


async def extract_edit_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """✏️ Qo'lda tahrirlash — foydalanuvchi yangi matn yubordi (2-vazifa)."""
    lang = get_lang(context)
    user_id = update.effective_user.id

    text = (update.message.text or "").strip()
    if not text:
        await update.message.reply_text(safe_t("ext_edit_empty", lang))
        return EXTRACT_EDIT

    # Yangi matnni saqlash
    context.user_data["extract_rewritten"] = text
    context.user_data["content"] = text

    preview = text[:500]
    if len(text) > 500:
        preview += "…"

    ad_line = await get_auto_ad_injection_async(user_id)
    await update.message.reply_text(
        safe_t("ext_ai_proposal", lang, text=safe_html(preview)) + (ad_line or ""),
        reply_markup=_get_rewrite_result_keyboard(lang=lang),
        parse_mode="HTML",
    )
    return EXTRACT_CHOOSE_POST
