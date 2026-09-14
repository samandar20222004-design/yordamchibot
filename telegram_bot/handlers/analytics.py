"""Analytics & Post Performance Dashboard — kanal statistikasi va hisobotlar.

PostAssist V2 (5-mikro qadam): asosiy menyudagi «📊 Statistika» tugmasi
endi IXCHAM umumiy ko'rsatkichlar ekranini ochadi (uzun va noaniq
«Kanallar analytics...» nomi o'rniga aniq «📊 Statistika»):

    📢 Ulangan kanallar soni
    📝 Yaratilgan postlar soni
    📅 Rejalashtirilgan postlar soni
    🤖 AI so'rovlar / Sarflangan kreditlar

Natija ostida amallar: [🔄 Yangilash] [◀️ Orqaga].

Kanal darajasidagi batafsil analitika (eski oqim) ham saqlanadi —
``an_ch:`` / ``an_other`` callback'lari orqaga moslik uchun ishlayveradi.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_IDS_SET
import database as db
from keyboards.default import get_main_keyboard
from keyboards.inline import btn_label, get_user_stats_keyboard
from keyboards.callback_data import cb
from locales.translations import get_lang, get_text, has_key
from translations import settings_stats_t
from utils.helpers import html_escape

logger = logging.getLogger(__name__)

# States
ANALYTICS_CHOOSE = 501
ANALYTICS_VIEW = 502

# PRO tarifga o'tish tugmasi (free foydalanuvchilar analitikani to'liq ko'rmaydi).
# UZ standarti (testlar import qiladi); handler'lar tilga mos variantni ishlatadi.
PRO_UPGRADE_KEYBOARD = InlineKeyboardMarkup([
    [InlineKeyboardButton("⭐️ PRO tarifga o'tish", callback_data="sub_open")],
])

ANALYTICS_FREE_HINT = (
    "📊 <b>Analitika</b>\n\n"
    "📌 Free tarifida oxirgi <b>7 kunlik</b> statistika ko'rsatiladi.\n"
    "⭐️ <b>PRO</b> tarifida to'liq analitika (30 kun, barcha postlar, eng faol soatlar) ochiladi!"
)

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


def build_user_stats_text(stats: dict, lang: str = "uz") -> str:
    """📊 Statistika — ixcham umumiy ko'rsatkichlar ekrani matni (uz/ru/en).

    ``stats`` — ``db.get_user_overview_stats`` natijasi:
    ``{"channels", "created_posts", "scheduled_posts", "ai_requests",
    "credits_spent"}``. Matn SPEKStdagi 4 ta asosiy ko'rsatkichdan tuziladi:

        📢 Ulangan kanallar soni
        📝 Yaratilgan postlar soni
        📅 Rejalashtirilgan postlar soni
        🤖 AI so'rovlar / Sarflangan kreditlar
    """
    stats = stats or {}
    lines = [
        settings_stats_t("ss_stats_title", lang),
        "━━━━━━━━━━━━━━━━━",
        settings_stats_t("ss_stats_channels", lang, n=int(stats.get("channels", 0))),
        settings_stats_t("ss_stats_created", lang, n=int(stats.get("created_posts", 0))),
        settings_stats_t(
            "ss_stats_scheduled", lang, n=int(stats.get("scheduled_posts", 0))
        ),
        settings_stats_t(
            "ss_stats_ai", lang,
            ai=int(stats.get("ai_requests", 0)),
            credits=int(stats.get("credits_spent", 0)),
        ),
        "━━━━━━━━━━━━━━━━━",
        settings_stats_t("ss_stats_footer", lang),
    ]
    return "\n".join(lines)


def _type_label(ptype: str, lang: str = "uz") -> str:
    """Post turi yorlig'i — foydalanuvchi tilida (uz/ru/en)."""
    if lang == "uz":
        return _TYPE_LABEL.get(ptype, ptype)
    key = f"an_type_{ptype}"
    if has_key(key, lang):
        return get_text(key, lang)
    return _TYPE_LABEL.get(ptype, ptype)


def _build_dashboard(stats: dict, channel_title: str = "Barcha kanallar", lang: str = "uz") -> str:
    """Statistika ma'lumotlarini chiroyli matnli dashboard ko'rinishida formatlaydi."""
    sent_7d = stats.get("sent_7d", 0)
    sent_30d = stats.get("sent_30d", 0)
    sent_all = stats.get("sent_all", 0)
    pending = stats.get("pending", 0)
    peak_hours = stats.get("peak_hours", [])
    type_dist = stats.get("type_distribution", {})

    no_data = get_text("an_dash_no_data", lang)

    # Peak hours
    if peak_hours:
        hours_str = ", ".join(_format_hour(h) for h, _ in peak_hours)
    else:
        hours_str = no_data

    # Type distribution
    total_typed = sum(type_dist.values())
    if total_typed > 0:
        parts = []
        for ptype, cnt in type_dist.items():
            emoji = _TYPE_EMOJI.get(ptype, "📎")
            label = _type_label(ptype, lang)
            pct = round(cnt / total_typed * 100)
            parts.append(f"{emoji} {pct}% {label}")
        types_str = " | ".join(parts[:4])  # max 4 ta
    else:
        types_str = no_data

    safe_title = html_escape(channel_title)

    # Empty state
    if sent_all == 0 and pending == 0:
        return get_text("an_dash_empty", lang, channel=safe_title)

    div = get_text("an_dash_div", lang)
    lines = [
        get_text("an_dash_header", lang, channel=safe_title),
        div,
        get_text("an_dash_7d", lang, n=sent_7d),
        get_text("an_dash_30d", lang, n=sent_30d),
        get_text("an_dash_all", lang, n=sent_all),
        get_text("an_dash_pending", lang, n=pending),
        "",
        get_text("an_dash_peak", lang, hours=html_escape(hours_str)),
        get_text("an_dash_types", lang, types=html_escape(types_str)),
        div,
    ]
    return "\n".join(lines)


def _pro_button(lang: str = "uz") -> InlineKeyboardButton:
    """PRO tarifga o'tish tugmasi — foydalanuvchi tilida."""
    return InlineKeyboardButton(get_text("ch_pro_btn", lang), callback_data="sub_open")


def _get_analytics_channel_keyboard(
    channels: list, show_pro: bool = False, lang: str = "uz",
) -> InlineKeyboardMarkup:
    """Analitika uchun kanal tanlash keyboard."""
    keyboard = []
    keyboard.append([
        InlineKeyboardButton(get_text("an_btn_all", lang), callback_data="an_ch:all"),
    ])
    for ch in channels:
        ch_id, ch_title = ch[:2]
        keyboard.append([
            InlineKeyboardButton(
                f"📢 {btn_label(ch_title)}",
                callback_data=cb(f"an_ch:{ch_id}"),
            )
        ])
    if show_pro:
        keyboard.append([_pro_button(lang)])
    keyboard.append([
        InlineKeyboardButton(get_text("pend_close_btn", lang), callback_data="an_close")
    ])
    return InlineKeyboardMarkup(keyboard)


def _get_analytics_view_keyboard(show_pro: bool = False, lang: str = "uz") -> InlineKeyboardMarkup:
    """Statistika ko'rish tugmalari."""
    rows = [
        [
            InlineKeyboardButton(get_text("an_btn_refresh", lang), callback_data="an_refresh"),
            InlineKeyboardButton(get_text("an_btn_other", lang), callback_data="an_other"),
        ],
    ]
    if show_pro:
        rows.append([_pro_button(lang)])
    rows.append([InlineKeyboardButton(get_text("btn_back", lang), callback_data="an_close")])
    return InlineKeyboardMarkup(rows)


async def start_analytics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📊 Statistika — IXCHAM umumiy ko'rsatkichlar ekrani (PostAssist V2).

    Oddiy foydalanuvchiga asosiy ko'rsatkichlar bitta ekranda ko'rsatiladi:
    📢 kanallar / 📝 yaratilgan postlar / 📅 rejalashtirilgan / 🤖 AI
    so'rovlar va kreditlar. Natija ostida [🔄 Yangilash] [◀️ Orqaga].

    Kanal yo'q bo'lsa ham ekran ochiladi (nollar bilan) — foydalanuvchi
    hech qachon «bo'sh» qolib ketmaydi. Kanal darajasidagi batafsil
    analitika esa eski ``an_ch:`` / ``an_other`` callback'lari orqali
    (orqaga moslik) mavjudligicha qoladi.
    """
    user_id = update.effective_user.id
    lang = get_lang(context)

    stats = await db.run_db(db.get_user_overview_stats, user_id)
    context.user_data["analytics_overview"] = True
    context.user_data.pop("analytics_channel_id", None)

    await update.message.reply_text(
        build_user_stats_text(stats, lang),
        reply_markup=get_user_stats_keyboard(lang),
        parse_mode="HTML",
    )
    return ANALYTICS_VIEW


async def analytics_channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kanal tanlanganda statistikani ko'rsatadi."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    is_pro = await db.run_db(db.is_premium, user_id)
    show_pro = (not is_admin and not is_pro)
    lang = get_lang(context)

    if data == "an_close":
        await query.message.reply_text(
            get_text("msg_closed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if not data.startswith("an_ch:"):
        return ANALYTICS_CHOOSE

    ch_value = data.split(":", 1)[1]
    channels = context.user_data.get("analytics_channels", [])

    if ch_value == "all":
        channel_id = None
        channel_title = get_text("an_all_channels", lang)
    else:
        channel_id = ch_value
        channel_title = get_text("an_channel_fallback", lang)
        for ch in channels:
            if ch[0] == channel_id:
                channel_title = ch[1]
                break

    context.user_data["analytics_channel_id"] = channel_id
    context.user_data["analytics_channel_title"] = channel_title

    stats = await db.run_db(db.get_channel_post_stats, user_id, channel_id)
    dashboard = _build_dashboard(stats, channel_title, lang)

    await query.message.reply_text(
        dashboard,
        reply_markup=_get_analytics_view_keyboard(show_pro=show_pro, lang=lang),
        parse_mode="HTML",
    )
    return ANALYTICS_VIEW


async def analytics_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangilash yoki boshqa kanal tanlash."""
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS_SET
    is_pro = await db.run_db(db.is_premium, user_id)
    show_pro = (not is_admin and not is_pro)
    lang = get_lang(context)

    if data == "an_close":
        await query.answer()
        await query.message.reply_text(
            get_text("msg_closed", lang),
            reply_markup=get_main_keyboard(is_admin, lang=lang),
        )
        return ConversationHandler.END

    if data == "an_other":
        await query.answer()
        channels = context.user_data.get("analytics_channels", [])
        if not channels:
            channels = await db.run_db(db.get_user_channel_list_for_analytics, user_id)
            context.user_data["analytics_channels"] = channels
        await query.message.reply_text(
            get_text("an_choose_short", lang),
            reply_markup=_get_analytics_channel_keyboard(channels, show_pro=show_pro, lang=lang),
            parse_mode="HTML",
        )
        return ANALYTICS_CHOOSE

    if data == "an_refresh":
        await query.answer(get_text("an_refreshing", lang))

        # 📊 Statistika (PostAssist V2, 5-mikro qadam): umumiy ko'rsatkichlar
        # ekrani yangilanmoqda — kesh tozalanadi va ma'lumotlar qayta o'qiladi.
        if context.user_data.get("analytics_overview"):
            try:
                db.invalidate_user_overview_stats(user_id)
            except Exception:
                pass
            stats = await db.run_db(db.get_user_overview_stats, user_id)
            overview_text = build_user_stats_text(stats, lang)
            overview_kb = get_user_stats_keyboard(lang)
            try:
                await query.edit_message_text(
                    overview_text,
                    reply_markup=overview_kb,
                    parse_mode="HTML",
                )
            except Exception:
                await query.message.reply_text(
                    overview_text,
                    reply_markup=overview_kb,
                    parse_mode="HTML",
                )
            return ANALYTICS_VIEW

        channel_id = context.user_data.get("analytics_channel_id")
        channel_title = context.user_data.get(
            "analytics_channel_title", get_text("an_channel_fallback", lang)
        )

        stats = await db.run_db(db.get_channel_post_stats, user_id, channel_id)
        dashboard = _build_dashboard(stats, channel_title, lang)
        view_kb = _get_analytics_view_keyboard(show_pro=show_pro, lang=lang)

        try:
            await query.edit_message_text(
                dashboard,
                reply_markup=view_kb,
                parse_mode="HTML",
            )
        except Exception:
            await query.message.reply_text(
                dashboard,
                reply_markup=view_kb,
                parse_mode="HTML",
            )
        return ANALYTICS_VIEW

    return ANALYTICS_VIEW
