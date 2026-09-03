"""Content Plan Generator — AI yordamida haftalik kontent-reja tuzish."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_cancel_keyboard, get_main_keyboard
from keyboards.inline import btn_label
from utils.helpers import html_escape, safe_html, get_auto_ad_injection_async

logger = logging.getLogger(__name__)

# States
# Eslatma: 401-403 AI_ASSISTANT bilan to'qnashgan edi — endi 411-413 unikal.
PLAN_CHOOSE_CHANNEL = 411
PLAN_GET_TOPIC = 412
PLAN_VIEW = 413


def _get_plan_channel_keyboard(channels: list) -> InlineKeyboardMarkup:
    """Kontent-reja uchun kanal tanlash keyboard."""
    keyboard = []
    for ch in channels:
        ch_id, ch_title = ch[:2]
        keyboard.append([
            InlineKeyboardButton(
                f"📢 {btn_label(ch_title)}",
                callback_data=f"plan_ch:{ch_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data="plan_cancel")])
    return InlineKeyboardMarkup(keyboard)


def _get_plan_result_keyboard() -> InlineKeyboardMarkup:
    """Kontent-reja natijasi uchun keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Post yaratish", callback_data="plan_create_post")],
        [InlineKeyboardButton("🔄 Qayta generatsiya", callback_data="plan_regenerate")],
        [InlineKeyboardButton("❌ Yopish", callback_data="plan_cancel")],
    ])


def _get_plan_day_keyboard(plan_items: list) -> InlineKeyboardMarkup:
    """Kun tanlash keyboard (post yaratish uchun)."""
    keyboard = []
    for i, item in enumerate(plan_items):
        day = item.get("day", f"Kun {i+1}")
        title = item.get("title", "")[:30]
        keyboard.append([
            InlineKeyboardButton(
                f"📅 {day}: {title}",
                callback_data=f"plan_day:{i}",
            )
        ])
    keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="plan_back")])
    return InlineKeyboardMarkup(keyboard)


async def start_content_plan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kontent-reja bo'limini boshlash."""
    user_id = update.effective_user.id
    channels = await db.run_db(db.get_user_channels, user_id)

    if not channels:
        await update.message.reply_text(
            "⚠️ <b>Avval kanal ulang.</b>\n\n"
            "Kontent-reja tuzish uchun kamida bitta kanal bo'lishi kerak.\n"
            "📢 Kanallar bo'limidan kanal ulang.",
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    context.user_data["plan_channels"] = channels
    await update.message.reply_text(
        "🧠 <b>Kontent-reja generatori</b>\n\n"
        "Qaysi kanal uchun kontent-reja tuzamiz?",
        reply_markup=_get_plan_channel_keyboard(channels),
        parse_mode="HTML",
    )
    return PLAN_CHOOSE_CHANNEL


async def plan_channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlanganda."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "plan_cancel":
        await query.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=get_main_keyboard(query.from_user.id in ADMIN_IDS_SET),
        )
        return ConversationHandler.END

    if not data.startswith("plan_ch:"):
        return PLAN_CHOOSE_CHANNEL

    channel_id = data.split(":", 1)[1]
    channels = context.user_data.get("plan_channels", [])
    channel_title = "Kanal"
    for ch in channels:
        if ch[0] == channel_id:
            channel_title = ch[1]
            break

    context.user_data["plan_channel_id"] = channel_id
    context.user_data["plan_channel_title"] = channel_title

    await query.message.reply_text(
        f"🧠 <b>Kontent-reja: {html_escape(channel_title)}</b>\n\n"
        f"Kanal mavzusini qisqacha yozing.\n\n"
        f"<i>Masalan:</i>\n"
        f"• Ingliz tili noldan\n"
        f"• Oshxona buyumlari do'koni\n"
        f"• Sog'lom turmush tarzi\n"
        f"• IT yangiliklar",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return PLAN_GET_TOPIC


async def plan_topic_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mavzu qabul qilish va AI dan reja so'rash."""
    text = (update.message.text or "").strip()

    if text in ("🔙 Asosiy menyu", "🔙 Orqaga"):
        await update.message.reply_text(
            "❌ Bekor qilindi.",
            reply_markup=get_main_keyboard(update.effective_user.id in ADMIN_IDS_SET),
        )
        return ConversationHandler.END

    if len(text) < 3:
        await update.message.reply_text(
            "⚠️ Mavzu juda qisqa. Kamida 3 ta belgi yozing.",
            reply_markup=get_cancel_keyboard(),
        )
        return PLAN_GET_TOPIC

    channel_id = context.user_data.get("plan_channel_id", "")
    channel_title = context.user_data.get("plan_channel_title", "Kanal")
    tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"

    # Kanalning real vaqtdagi postlar tarixini olamiz
    recent_posts = []
    if channel_id:
        history = await db.run_db(db.get_channel_posts_history, channel_id, 5)
        recent_posts = [p.get("text") for p in history if p.get("text") and not p.get("text").startswith("[")]

    await update.message.reply_text("⏳ AI kontent-reja tuzmoqda...")

    from utils.ai_agent import generate_content_plan
    result = await generate_content_plan(text, channel_title, tone, recent_posts=recent_posts)

    if "error" in result:
        await update.message.reply_text(
            result["error"],
            reply_markup=get_main_keyboard(update.effective_user.id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    plan_items = result.get("plan", [])
    if not plan_items:
        await update.message.reply_text(
            "⚠️ AI reja tuza olmadi. Qaytadan urinib ko'ring.",
            reply_markup=get_main_keyboard(update.effective_user.id in ADMIN_IDS_SET),
        )
        return ConversationHandler.END

    context.user_data["plan_items"] = plan_items
    context.user_data["plan_topic"] = text

    # Format plan as text
    plan_text = f"🧠 <b>7 kunlik kontent-reja</b>\n"
    plan_text += f"📢 Kanal: <b>{html_escape(channel_title)}</b>\n"
    plan_text += f"📝 Mavzu: <i>{html_escape(text)}</i>\n\n"

    for i, item in enumerate(plan_items):
        day = item.get("day", f"Kun {i+1}")
        fmt = item.get("format", "")
        title = item.get("title", "")
        idea = item.get("idea", "")
        plan_text += f"<b>📅 {day}</b> — {html_escape(fmt)}\n"
        plan_text += f"  📌 <b>{html_escape(title)}</b>\n"
        if idea:
            plan_text += f"  <i>{html_escape(idea[:150])}</i>\n"
        plan_text += "\n"

    ad_line = await get_auto_ad_injection_async(update.effective_user.id)
    plan_text += f"{ad_line}\n\nKunni tanlab, to'g'ridan-to'g'ri post yarating 👇"

    await update.message.reply_text(
        plan_text,
        reply_markup=_get_plan_day_keyboard(plan_items),
        parse_mode="HTML",
    )
    return PLAN_VIEW


async def plan_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kun tanlash yoki qayta generatsiya."""
    query = update.callback_query
    data = query.data
    is_admin = query.from_user.id in ADMIN_IDS_SET

    if data == "plan_cancel":
        await query.answer()
        await query.message.reply_text(
            "❌ Yopildi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "plan_back":
        await query.answer()
        channels = context.user_data.get("plan_channels", [])
        await query.message.reply_text(
            "🧠 <b>Qaysi kanal uchun kontent-reja tuzamiz?</b>",
            reply_markup=_get_plan_channel_keyboard(channels),
            parse_mode="HTML",
        )
        return PLAN_CHOOSE_CHANNEL

    if data == "plan_regenerate":
        await query.answer("🔄 Qayta generatsiya...")
        topic = context.user_data.get("plan_topic", "")
        channel_id = context.user_data.get("plan_channel_id", "")
        channel_title = context.user_data.get("plan_channel_title", "Kanal")
        tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"

        # Kanalning postlar tarixini olamiz
        recent_posts = []
        if channel_id:
            history = await db.run_db(db.get_channel_posts_history, channel_id, 5)
            recent_posts = [p.get("text") for p in history if p.get("text") and not p.get("text").startswith("[")]

        from utils.ai_agent import generate_content_plan
        result = await generate_content_plan(topic, channel_title, tone, recent_posts=recent_posts)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
            return PLAN_VIEW

        plan_items = result.get("plan", [])
        if not plan_items:
            await query.message.reply_text("⚠️ AI reja tuza olmadi.")
            return PLAN_VIEW

        context.user_data["plan_items"] = plan_items

        plan_text = f"🧠 <b>7 kunlik kontent-reja (yangi)</b>\n"
        plan_text += f"📢 Kanal: <b>{html_escape(channel_title)}</b>\n"
        plan_text += f"📝 Mavzu: <i>{html_escape(topic)}</i>\n\n"

        for i, item in enumerate(plan_items):
            day = item.get("day", f"Kun {i+1}")
            fmt = item.get("format", "")
            title = item.get("title", "")
            idea = item.get("idea", "")
            plan_text += f"<b>📅 {day}</b> — {html_escape(fmt)}\n"
            plan_text += f"  📌 <b>{html_escape(title)}</b>\n"
            if idea:
                plan_text += f"  <i>{html_escape(idea[:150])}</i>\n"
            plan_text += "\n"

        await query.message.reply_text(
            plan_text,
            reply_markup=_get_plan_day_keyboard(plan_items),
            parse_mode="HTML",
        )
        return PLAN_VIEW

    if data.startswith("plan_day:"):
        await query.answer()
        idx_str = data.split(":", 1)[1]
        try:
            idx = int(idx_str)
        except (ValueError, TypeError):
            return PLAN_VIEW

        plan_items = context.user_data.get("plan_items", [])
        if idx < 0 or idx >= len(plan_items):
            await query.message.reply_text("❌ Noto'g'ri kun tanlandi.")
            return PLAN_VIEW

        item = plan_items[idx]
        day = item.get("day", f"Kun {idx+1}")
        title = item.get("title", "")
        idea = item.get("idea", "")
        fmt = item.get("format", "")

        # Saqlaymiz — post yaratish oqimiga yo'naltirish uchun
        context.user_data["plan_selected_item"] = item

        detail = (
            f"📅 <b>{html_escape(day)}</b> — {html_escape(fmt)}\n\n"
            f"📌 <b>{html_escape(title)}</b>\n\n"
            f"{html_escape(idea)}\n\n"
            f"Shu mavzuda post yaratishni xohlaysizmi?"
        )

        confirm_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Shu mavzuda post yaratish", callback_data="plan_create_post")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="plan_back_to_list")],
        ])

        await query.message.reply_text(detail, reply_markup=confirm_kb, parse_mode="HTML")
        return PLAN_VIEW

    if data == "plan_create_post":
        await query.answer()
        item = context.user_data.get("plan_selected_item", {})
        if not item:
            # Agar kun tanlanmagan bo'lsa — kunlar ro'yxatini ko'rsatamiz
            plan_items = context.user_data.get("plan_items", [])
            if plan_items:
                await query.message.reply_text(
                    "📅 <b>Qaysi kun uchun post yaratamiz?</b>",
                    reply_markup=_get_plan_day_keyboard(plan_items),
                    parse_mode="HTML",
                )
            return PLAN_VIEW

        # Post yaratish oqimiga yo'naltirish
        topic = context.user_data.get("plan_topic", "")
        title = item.get("title", "")
        idea = item.get("idea", "")
        channel_id = context.user_data.get("plan_channel_id", "")
        channel_title = context.user_data.get("plan_channel_title", "")

        # AI dan to'liq post so'raymiz
        await query.message.reply_text("⏳ AI post matnini tayyorlamoqda...")

        from utils.ai_agent import generate_post_from_plan
        tone = await db.run_db(db.get_channel_tone, channel_id) if channel_id else "friendly"
        result = await generate_post_from_plan(topic, title, idea, tone)

        if "error" in result:
            await query.message.reply_text(result["error"], parse_mode="HTML")
            return PLAN_VIEW

        post_text = result.get("post_text", "")
        if not post_text:
            await query.message.reply_text("⚠️ AI post matni tayyorlay olmadi.")
            return PLAN_VIEW

        # Post matnini user_data ga saqlash va yangi post oqimiga o'tkazish
        context.user_data["content"] = post_text
        context.user_data["post_type"] = "text"
        context.user_data["file_id"] = None
        context.user_data["selected_channel_id"] = channel_id
        context.user_data["selected_channel_title"] = channel_title

        preview = post_text[:500]
        if len(post_text) > 500:
            preview += "…"

        await query.message.reply_text(
            f"✅ <b>Tayyor post:</b>\n\n{safe_html(preview)}\n\n"
            f"📢 Kanal: <b>{html_escape(channel_title)}</b>\n\n"
            f"Endi tugma, vaqt va boshqa sozlamalarni kiriting.",
            parse_mode="HTML",
        )

        # To'g'ridan-to'g'ri GET_BTN_TITLE ga o'tamiz (tugma bosish bosqichi)
        from keyboards.default import get_button_prompt_keyboard
        await query.message.reply_text(
            "🔘 <b>Tugma qo'shasizmi?</b>\n\n"
            "Tugma matni va URL ni yozing:\n"
            "<code>Matn | https://havola.uz</code>\n\n"
            "Yoki tugmasiz davom eting 👇",
            reply_markup=get_button_prompt_keyboard(),
            parse_mode="HTML",
        )
        from handlers.new_post import GET_BTN_TITLE
        return GET_BTN_TITLE

    if data == "plan_back_to_list":
        await query.answer()
        plan_items = context.user_data.get("plan_items", [])
        channel_title = context.user_data.get("plan_channel_title", "Kanal")
        topic = context.user_data.get("plan_topic", "")

        plan_text = f"🧠 <b>7 kunlik kontent-reja</b>\n"
        plan_text += f"📢 Kanal: <b>{html_escape(channel_title)}</b>\n"
        plan_text += f"📝 Mavzu: <i>{html_escape(topic)}</i>\n\n"

        for i, item in enumerate(plan_items):
            day = item.get("day", f"Kun {i+1}")
            fmt = item.get("format", "")
            title = item.get("title", "")
            idea = item.get("idea", "")
            plan_text += f"<b>📅 {day}</b> — {html_escape(fmt)}\n"
            plan_text += f"  📌 <b>{html_escape(title)}</b>\n"
            if idea:
                plan_text += f"  <i>{html_escape(idea[:150])}</i>\n"
            plan_text += "\n"

        await query.message.reply_text(
            plan_text,
            reply_markup=_get_plan_day_keyboard(plan_items),
            parse_mode="HTML",
        )
        return PLAN_VIEW

    return PLAN_VIEW
