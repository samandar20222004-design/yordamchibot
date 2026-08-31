"""Analytics & Post Performance Dashboard — kanal statistikasi va hisobotlar."""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard
from keyboards.inline import btn_label
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# States
ANALYTICS_CHOOSE = 501
ANALYTICS_VIEW = 502

# Post type emoji mapping
_TYPE_EMOJI = {
    "text": "📝",
    "photo": "🖼",
    "video": "🎥",
    "document": "📄",
    "audio": "🎵",
    "animation": "🎞",
    "album": "📦",
}

_TYPE_LABEL = {
    "text": "Matn",
    "photo": "Rasm",
    "video": "Video",
    "document": "Hujjat",
    "audio": "Audio",
    "animation": "GIF",
    "album": "Albom",
}


def _format_hour(h: int) -> str:
    """Soatni 09:00 formatiga keltiradi."""
    return f"{h:02d}:00"


def _build_dashboard(stats: dict, channel_title: str = "Barcha kanallar") -> str:
    """Statistika ma'lumotlarini chiroyli matnli dashboard ko'rinishida formatlaydi."""
    sent_7d = stats.get("sent_7d", 0)
    sent_30d = stats.get("sent_30d", 0)
    sent_all = stats.get("sent_all", 0)
    pending = stats.get("pending", 0)
    peak_hours = stats.get("peak_hours", [])
    type_dist = stats.get("type_distribution", {})

    # Peak hours
    if peak_hours:
        hours_str = ", ".join(_format_hour(h) for h, _ in peak_hours)
    else:
        hours_str = "Ma'lumot yo'q"

    # Type distribution
    total_typed = sum(type_dist.values())
    if total_typed > 0:
        parts = []
        for ptype, cnt in type_dist.items():
            emoji = _TYPE_EMOJI.get(ptype, "📎")
            label = _TYPE_LABEL.get(ptype, ptype)
            pct = round(cnt / total_typed * 100)
            parts.append(f"{emoji} {pct}% {label}")
        types_str = " | ".join(parts[:4])  # max 4 ta
    else:
        types_str = "Ma'lumot yo'q"

    # Empty state
    if sent_all == 0 and pending == 0:
        return (
            f"📊 <b>{html_escape(channel_title)}</b> — Kanal statistikasi\n"
            f"━━━━━━━━━━━━━━━━━\n\n"
            f"📭 <b>Hali post chiqarilmagan.</b>\n\n"
            f"Birinchi postingizni rejalashtiring va bu yerda statistikani kuzating!\n"
            f"━━━━━━━━━━━━━━━━━"
        )

    lines = [
        f"📊 <b>{html_escape(channel_title)}</b> — Kanal statistikasi",
        f"━━━━━━━━━━━━━━━━━",
        f"📤 Oxirgi 7 kunda: <b>{sent_7d}</b> ta post",
        f"📦 Oxirgi 30 kunda: <b>{sent_30d}</b> ta post",
        f"📋 Jami chiqarilgan: <b>{sent_all}</b> ta post",
        f"⏳ Navbatda kutayotgan: <b>{pending}</b> ta post",
        f"",
        f"🕒 Eng faol vaqtlar: <b>{hours_str}</b>",
        f"📁 Post turlari: {types_str}",
        f"━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def _get_analytics_channel_keyboard(channels: list) -> InlineKeyboardMarkup:
    """Analitika uchun kanal tanlash keyboard."""
    keyboard = []
    keyboard.append([
        InlineKeyboardButton("📊 Barcha kanallar", callback_data="an_ch:all"),
    ])
    for ch in channels:
        ch_id, ch_title = ch[:2]
        keyboard.append([
            InlineKeyboardButton(
                f"📢 {btn_label(ch_title)}",
                callback_data=f"an_ch:{ch_id}",
            )
        ])
    keyboard.append([InlineKeyboardButton("❌ Yopish", callback_data="an_close")])
    return InlineKeyboardMarkup(keyboard)


def _get_analytics_view_keyboard() -> InlineKeyboardMarkup:
    """Statistika ko'rish tugmalari."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Yangilash", callback_data="an_refresh"),
            InlineKeyboardButton("📢 Boshqa kanal", callback_data="an_other"),
        ],
        [InlineKeyboardButton("⬅️ Orqaga", callback_data="an_close")],
    ])


async def start_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analitika bo'limini boshlash."""
    user_id = update.effective_user.id
    channels = await db.run_db(db.get_user_channel_list_for_analytics, user_id)

    if not channels:
        await update.message.reply_text(
            "⚠️ <b>Sizda hali ulangan kanallar mavjud emas.</b>\n\n"
            "Statistika ko'rish uchun avval kanal ulang.",
            reply_markup=get_main_keyboard(user_id in ADMIN_IDS_SET),
            parse_mode="HTML",
        )
        return ConversationHandler.END

    context.user_data["analytics_channels"] = channels
    await update.message.reply_text(
        "📊 <b>Analitika va Statistika</b>\n\n"
        "Qaysi kanal statistikasini ko'rasiz?",
        reply_markup=_get_analytics_channel_keyboard(channels),
        parse_mode="HTML",
    )
    return ANALYTICS_CHOOSE


async def analytics_channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlanganda statistikani ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if data == "an_close":
        await query.message.reply_text(
            "✅ Yopildi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if not data.startswith("an_ch:"):
        return ANALYTICS_CHOOSE

    ch_value = data.split(":", 1)[1]
    channels = context.user_data.get("analytics_channels", [])

    if ch_value == "all":
        channel_id = None
        channel_title = "Barcha kanallar"
    else:
        channel_id = ch_value
        channel_title = "Kanal"
        for ch in channels:
            if ch[0] == channel_id:
                channel_title = ch[1]
                break

    context.user_data["analytics_channel_id"] = channel_id
    context.user_data["analytics_channel_title"] = channel_title

    stats = await db.run_db(db.get_channel_post_stats, user_id, channel_id)
    dashboard = _build_dashboard(stats, channel_title)

    await query.message.reply_text(
        dashboard,
        reply_markup=_get_analytics_view_keyboard(),
        parse_mode="HTML",
    )
    return ANALYTICS_VIEW


async def analytics_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangilash yoki boshqa kanal tanlash."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET

    if data == "an_close":
        await query.answer()
        await query.message.reply_text(
            "✅ Yopildi.",
            reply_markup=get_main_keyboard(is_admin),
        )
        return ConversationHandler.END

    if data == "an_other":
        await query.answer()
        channels = context.user_data.get("analytics_channels", [])
        if not channels:
            channels = await db.run_db(db.get_user_channel_list_for_analytics, user_id)
            context.user_data["analytics_channels"] = channels
        await query.message.reply_text(
            "📊 <b>Qaysi kanal statistikasini ko'rasiz?</b>",
            reply_markup=_get_analytics_channel_keyboard(channels),
            parse_mode="HTML",
        )
        return ANALYTICS_CHOOSE

    if data == "an_refresh":
        await query.answer("🔄 Yangilanmoqda...")
        channel_id = context.user_data.get("analytics_channel_id")
        channel_title = context.user_data.get("analytics_channel_title", "Kanal")

        stats = await db.run_db(db.get_channel_post_stats, user_id, channel_id)
        dashboard = _build_dashboard(stats, channel_title)

        try:
            await query.edit_message_text(
                dashboard,
                reply_markup=_get_analytics_view_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                dashboard,
                reply_markup=_get_analytics_view_keyboard(),
                parse_mode="HTML",
            )
        return ANALYTICS_VIEW

    return ANALYTICS_VIEW
