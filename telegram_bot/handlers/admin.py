import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError, RetryAfter, TimedOut, NetworkError, BadRequest
from telegram.ext import ContextTypes, ConversationHandler
from config import ADMIN_ID, ADMIN_IDS_SET
import database as db
from keyboards.default import (
    get_admin_panel_keyboard,
    get_sponsors_keyboard,
    get_cancel_keyboard,
    BTN_MAIN_MENU,
    BTN_AI_SETTINGS, BTN_CACHE_DB,
)
from keyboards.inline import (
    get_sponsors_delete_keyboard, get_cache_actions_keyboard,
    get_admin_dashboard_keyboard, get_admin_back_keyboard,
)
from utils import ai_agent
from utils.helpers import html_escape, format_post_type_label

logger = logging.getLogger(__name__)

BROADCAST_MESSAGE = 801
ADD_SPONSOR_CHANNEL = 802
SET_CHANNEL_AD = 803
SET_BOT_REPLY_AD = 804
AI_SETTINGS = 805
SET_POST_TAG = 806
ADMIN_GRANT_PRO = 807
ADMIN_PROMO_CREATE = 808

# Broadcast har 20 xabardan keyin shuncha kutadi (Telegram ~30 msg/s limiti).
# 20 xabar / 0.7 s ≈ 28 msg/s — limitdan xavfsiz past.
BROADCAST_BATCH_SIZE = 20
BROADCAST_BATCH_DELAY = 0.7

# Bir vaqtda faqat bitta broadcast ishlashi uchun qulf
_broadcast_lock = asyncio.Lock()

# Telegram matnining ruxsat etilgan maksimal hajmi. UTF-16 birliklarini
# sanaymiz va HTML teglarini ham hisobga olamiz — bu API chegarasidan
# ehtiyotkorlik bilan pastda qoladi.
TELEGRAM_TEXT_LIMIT = 4096
ADMIN_CHANNELS_LIMIT = 20


def _short_text(value, max_length: int) -> str:
    """Ro'yxat qatori haddan tashqari uzun bo'lmasligi uchun qisqartiradi."""
    value = str(value or "")
    if len(value) <= max_length:
        return value
    return f"{value[:max_length - 1]}…"


def _telegram_text_length(text: str) -> int:
    """Telegram amalda ishlatadigan UTF-16 belgilar sonini qaytaradi."""
    return len(text.encode("utf-16-le")) // 2


def format_admin_channels_list(channels: list) -> str:
    """Eng so'nggi kanallar uchun HTML-xavfsiz, 4096 dan oshmaydigan matn."""
    header = (
        f"📋 <b>Eng so'nggi {len(channels)} ta ulangan kanal "
        f"(ko'pi bilan {ADMIN_CHANNELS_LIMIT}):</b>\n\n"
    )
    entries = []
    for channel_id, title, user_id, username in channels:
        title = _short_text(title or "Kanal", 160)
        channel_id = _short_text(channel_id, 64)
        owner = f"@{_short_text(username, 64)}" if username else f"ID:{user_id}"
        entries.append(
            f"📢 <b>{html_escape(title)}</b> (<code>{html_escape(channel_id)}</code>)\n"
            f"   👤 Egasi: {html_escape(owner)}\n\n"
        )

    visible_entries = entries[:]
    while True:
        omitted = len(entries) - len(visible_entries)
        footer = (
            f"… {omitted} ta kanal Telegramning 4096 belgilik limiti sabab ko'rsatilmagan."
            if omitted else ""
        )
        text = header + "".join(visible_entries) + footer
        if _telegram_text_length(text) <= TELEGRAM_TEXT_LIMIT or not visible_entries:
            return text
        # Eng yangi kanallar yuqorida qoladi; faqat sig'magan eski qatorni olamiz.
        visible_entries.pop()


# Admin panelda ko'rsatiladigan AI parametrlari (kalit -> (DB key, UI belgi, tavsif))
AI_SETTINGS_KEYS = {
    "temperature": ("ai_temperature", "🌡 temperature", "0.0–2.0 (0.2 = aniq)"),
    "max_tokens": ("ai_max_tokens", "📄 max_tokens", "128–8192 (1024) yoki off"),
    "top_p": ("ai_top_p", "🎯 top_p", "0.0–1.0 (1.0) yoki off"),
    "max_prompt_chars": ("ai_max_prompt_chars", "🧩 prompt limiti", "500–12000 belgi (3000)"),
    "context_chars": ("ai_context_chars", "💬 kontekst hajmi", "500–20000 belgi (4000)"),
    "context_messages": ("ai_context_messages", "🧠 kontekst xabarlari", "0–20 dona (6)"),
    "extra_context": ("ai_extra_context", "📌 qo'shimcha ko'rsatma", "matn (bo'sh qoldirsangiz o'chadi)"),
}


def _ai_settings_text() -> str:
    params = ai_agent.get_runtime_params()
    lines = []
    for key, (db_key, label, hint) in AI_SETTINGS_KEYS.items():
        value = params.get(key)
        value_text = "-" if value in (None, "") else str(value)
        lines.append(f"   • <b>{label}</b> = <code>{html_escape(value_text)}</code>  <i>({hint})</i>")
    return "\n".join(lines)


def _build_dashboard_text(stats: dict) -> str:
    """Admin dashboard matnini yaratadi."""
    return (
        "👑 <b>Admin Boshqaruv Paneli</b>\n"
        "━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"⭐️ PRO obunachilar: <b>{stats['pro_subscribers']} ta</b>\n"
        f"📢 Ulangan faol kanallar: <b>{stats['channels']} ta</b>\n"
        f"📝 Bugun chiqarilgan postlar: <b>{stats['posts_today']} ta</b>\n"
        f"⏳ Navbatdagi postlar: <b>{stats['pending_posts']} ta</b>\n"
        f"⭐️ Telegram Stars tushumi: <b>{stats['stars_revenue']} XTR</b>\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "Kerakli bo'limni tanlang 👇"
    )


def is_admin(user_id: int) -> bool:
    """Ko'p adminli tekshiruv: ADMIN_ID va ADMIN_IDS ichidan birida bo'lsa admin."""
    return user_id in ADMIN_IDS_SET


# ============================================================
# ADMIN PANEL DASHBOARD
# ============================================================

async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.clear()
    stats = await db.run_db(db.get_admin_dashboard_stats)
    text = _build_dashboard_text(stats)
    await update.message.reply_text(
        text,
        reply_markup=get_admin_dashboard_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def admin_stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """`/admin_stats` — qisqa umumiy statistika."""
    if not is_admin(update.effective_user.id):
        return
    stats = await db.run_db(db.get_system_stats)
    text = (
        "📊 <b>Bot Statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"📢 Ulangan kanallar: <b>{stats['channels']} ta</b>\n"
        f"📢 Homiy kanallar: <b>{stats['sponsors']} ta</b>\n"
        f"⏳ Kutilayotgan postlar: <b>{stats['pending']} ta</b>\n"
        f"✅ Yuborilgan postlar: <b>{stats['sent']} ta</b>\n"
        f"🚫 Bekor qilingan postlar: <b>{stats['cancelled']} ta</b>\n"
        f"⚠️ Xatolik bilan tugagan: <b>{stats['failed']} ta</b>"
    )
    await update.message.reply_text(
        text,
        reply_markup=get_admin_back_keyboard(),
        parse_mode="HTML",
    )


# ============================================================
# ADMIN INLINE CALLBACK HANDLERS
# ============================================================

async def admin_dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin dashboard inline tugmalari."""
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return
    data = query.data

    if data == "adm_stats":
        await query.answer()
        stats = await db.run_db(db.get_system_stats)
        text = (
            "📊 <b>To'liq Statistika:</b>\n\n"
            f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
            f"📢 Ulangan kanallar: <b>{stats['channels']} ta</b>\n"
            f"📢 Homiy kanallar: <b>{stats['sponsors']} ta</b>\n"
            f"⏳ Kutilayotgan postlar: <b>{stats['pending']} ta</b>\n"
            f"✅ Yuborilgan postlar: <b>{stats['sent']} ta</b>\n"
            f"🚫 Bekor qilingan: <b>{stats['cancelled']} ta</b>\n"
            f"⚠️ Xatolik: <b>{stats['failed']} ta</b>"
        )
        try:
            await query.edit_message_text(
                text,
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        except TelegramError:
            await query.message.reply_text(
                text,
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        return

    if data == "adm_promo":
        await query.answer()
        try:
            await query.edit_message_text(
                "🎁 <b>Promo-kod yaratish:</b>\n\n"
                "Format: <code>KOD KUNLAR [MAKS_ISHLATISH]</code>\n\n"
                "Masalan:\n"
                "• <code>MAXSUS30 30 50</code> — 30 kun PRO, 50 marta\n"
                "• <code>YANGI2026 30</code> — 30 kun PRO, cheksiz\n\n"
                "Promo-kodni yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        except TelegramError:
            await query.message.reply_text(
                "🎁 <b>Promo-kod yaratish:</b>\n\n"
                "Format: <code>KOD KUNLAR [MAKS_ISHLATISH]</code>\n\n"
                "Promo-kodni yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data["admin_flow"] = "promo_create"
        return

    if data == "adm_grant_pro":
        await query.answer()
        try:
            await query.edit_message_text(
                "⭐️ <b>Foydalanuvchiga PRO berish:</b>\n\n"
                "Format: <code>USER_ID KUNLAR</code>\n\n"
                "Masalan: <code>123456789 30</code>\n\n"
                "User ID va kunlar sonini yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        except TelegramError:
            await query.message.reply_text(
                "⭐️ <b>Foydalanuvchiga PRO berish:</b>\n\n"
                "Format: <code>USER_ID KUNLAR</code>\n\n"
                "User ID va kunlar sonini yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data["admin_flow"] = "grant_pro"
        return

    if data == "adm_broadcast":
        await query.answer()
        try:
            await query.edit_message_text(
                "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\n"
                "Yuboriladigan xabar matnini yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        except TelegramError:
            await query.message.reply_text(
                "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\n"
                "Yuboriladigan xabar matnini yozing:",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data["admin_flow"] = "broadcast"
        return

    if data == "adm_back":
        await query.answer()
        stats = await db.run_db(db.get_admin_dashboard_stats)
        text = _build_dashboard_text(stats)
        try:
            await query.edit_message_text(
                text,
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        except TelegramError:
            await query.message.reply_text(
                text,
                reply_markup=get_admin_dashboard_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return


async def admin_inline_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin inline flow'dan kelgan matnlarni qayta ishlash."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    flow = context.user_data.get("admin_flow")
    text = update.message.text.strip()

    if flow == "grant_pro":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Noto'g'ri format. <code>USER_ID KUNLAR</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        try:
            target_id = int(parts[0])
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Raqamlar noto'g'ri. <code>USER_ID KUNLAR</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        if days <= 0:
            await update.message.reply_text(
                "❌ Kunlar soni 0 dan katta bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_GRANT_PRO
        success = await db.run_db(db.set_user_plan, target_id, "pro", days)
        if success:
            await update.message.reply_text(
                f"✅ <b>PRO tarif berildi!</b>\n\n"
                f"👤 Foydalanuvchi: <code>{target_id}</code>\n"
                f"📅 Muddat: <b>{days} kun</b>",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            try:
                await context.bot.send_message(
                    chat_id=target_id,
                    text=(
                        f"🎉 <b>Tabriklaymiz!</b>\n\n"
                        f"Sizga <b>{days} kunlik PRO tarif</b> berildi!\n"
                        f"Barcha PRO imkoniyatlardan foydalanishingiz mumkin."
                    ),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await update.message.reply_text(
                "❌ Xatolik yuz berdi. User ID to'g'riligini tekshiring.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_GRANT_PRO

    if flow == "promo_create":
        parts = text.split()
        if len(parts) < 2:
            await update.message.reply_text(
                "❌ Noto'g'ri format. <code>KOD KUNLAR [MAKS]</code> deb yozing.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        code = parts[0].upper()
        try:
            days = int(parts[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Kunlar soni raqam bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        max_uses = None
        if len(parts) >= 3:
            try:
                max_uses = int(parts[2])
            except ValueError:
                await update.message.reply_text(
                    "❌ Maks ishlatish soni raqam bo'lishi kerak.",
                    reply_markup=get_admin_back_keyboard(),
                    parse_mode="HTML",
                )
                return ADMIN_PROMO_CREATE
        if days <= 0:
            await update.message.reply_text(
                "❌ Kunlar soni 0 dan katta bo'lishi kerak.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
            return ADMIN_PROMO_CREATE
        success = await db.run_db(db.create_promo_code, code, "pro", days, max_uses)
        if success:
            max_str = f"{max_uses} marta" if max_uses else "cheksiz"
            await update.message.reply_text(
                f"✅ <b>Promo-kod yaratildi!</b>\n\n"
                f"🏷 Kod: <code>{code}</code>\n"
                f"📅 Muddat: <b>{days} kun</b> PRO\n"
                f"🔢 Maks ishlatish: <b>{max_str}</b>",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                "❌ Promo-kod yaratishda xatolik. Bu kod allaqachon mavjud bo'lishi mumkin.",
                reply_markup=get_admin_back_keyboard(),
                parse_mode="HTML",
            )
        context.user_data.pop("admin_flow", None)
        return ADMIN_PROMO_CREATE

    if flow == "broadcast":
        user_ids = await db.run_db(db.get_all_user_ids)
        await update.message.reply_text(
            f"⏳ Xabar <b>{len(user_ids)} ta</b> foydalanuvchiga yuborilmoqda...\n"
            f"<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>",
            parse_mode="HTML",
        )
        async def _broadcast_task():
            async with _broadcast_lock:
                await _run_broadcast(context.bot, user_ids, text, update.effective_user.id)
        asyncio.create_task(_broadcast_task())
        context.user_data.pop("admin_flow", None)
        return ConversationHandler.END

    return ConversationHandler.END


# ============================================================
# LEGACY ADMIN HANDLERS (ReplyKeyboard bilan ishlaydi)
# ============================================================

async def ai_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "⚙️ <b>AI parametrlarni boshqarish:</b>\n\n"
        f"{_ai_settings_text()}\n\n"
        "O'zgartirish uchun quyidagi formatda satrlarni yuboring:\n"
        "<code>kalit=qiymat</code>\n\n"
        "Masalan:\n"
        "<code>temperature=0.4</code>\n"
        "<code>max_tokens=2048</code>\n"
        "<code>context_messages=8</code>\n"
        "<code>max_tokens=off</code>  <i>(parametr umuman yuborilmaydi)</i>\n\n"
        "👉 Hammasini defaultga qaytarish uchun <code>reset</code> deb yozing.\n"
        "Bekor qilish uchun asosiy menyu tugmasini bosing.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return AI_SETTINGS


async def ai_settings_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text == BTN_MAIN_MENU:
        return ConversationHandler.END

    if text.lower() == "reset":
        for db_key, *_ in AI_SETTINGS_KEYS.values():
            await db.run_db(db.set_setting, db_key, "")
        await ai_agent.reload_runtime_params()
        await update.message.reply_text(
            "✅ <b>Barcha AI parametrlar default holatga qaytarildi.</b>\n\n"
            f"{_ai_settings_text()}",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
        return AI_SETTINGS

    updates = {}
    errors = []
    for line in text.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key not in AI_SETTINGS_KEYS:
            errors.append(f"<code>{html_escape(key)}</code> — noma'lum kalit")
            continue
        import utils.ai_agent as _agent
        valid = _agent._set_runtime_param(key, value)
        if not valid:
            errors.append(f"<code>{html_escape(key)}</code> = <code>{html_escape(value)}</code> — noto'g'ri qiymat")
            continue
        updates[AI_SETTINGS_KEYS[key][0]] = value.strip()
        updates["__ui_key__"] = key

    if errors:
        await update.message.reply_text(
            "⚠️ <b>Quyidagi kalitlarni o'zgartirib bo'lmadi:</b>\n" + "\n".join(errors),
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )

    applied = [(k, v) for k, v in updates.items() if k != "__ui_key__"]
    if applied:
        for db_key, value in applied:
            await db.run_db(db.set_setting, db_key, value)
        # Runtime parametrlarni DB value'lar asosida yangilaymiz.
        await ai_agent.reload_runtime_params()
        await update.message.reply_text(
            "✅ <b>AI parametrlar yangilandi:</b>\n\n"
            f"{_ai_settings_text()}",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
    elif not errors:
        await update.message.reply_text(
            "⚠️ Hech qanday kalit kiritilmadi. <code>kalit=qiymat</code> formatida yuboring.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML",
        )
    return AI_SETTINGS


async def cache_db_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    status = await db.run_db(db.get_db_pool_status)
    collapsed_label = "yo'q" if status.get("collapsed") else "ha"
    cache_label = "yoqilgan" if status.get("cache_enabled") else "o'chirilgan"
    pool_label = "✅ ishlayapti" if status.get("ready") else "⏳ hali ochilmagan"
    text = (
        "🗄️ <b>DB Pool va Kesh holati:</b>\n\n"
        f"   • Pool: <b>{pool_label}</b> ({status.get('message', '')})\n"
        f"   • Min/Maks: <b>{status.get('min')} / {status.get('max')}</b>\n"
        f"   • Band: <b>{status.get('used')}</b> | Bo'sh: <b>{status.get('available')}</b>"
        f" | Yopiq: <b>{collapsed_label}</b>\n"
        f"   • Kesh: <b>{cache_label}</b> — <b>{status.get('cache_entries')} ta</b> yozuv\n\n"
        "Kesh TTL o'zgarishlarsiz avtomatik eskiradi. Tozalash kerak bo'lsa pastdagi tugmani bosing."
    )
    await update.message.reply_text(
        text,
        reply_markup=get_cache_actions_keyboard(),
        parse_mode="HTML",
    )
    return ConversationHandler.END


async def cache_clear_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not is_admin(query.from_user.id):
        await query.answer("Ruxsat yo'q.", show_alert=True)
        return
    await db.run_db(db.cache_clear)
    status = await db.run_db(db.get_db_pool_status)
    await query.answer("✅ Kesh tozalandi.")
    collapsed_label = "yo'q" if status.get("collapsed") else "ha"
    cache_label = "yoqilgan" if status.get("cache_enabled") else "o'chirilgan"
    pool_label = "✅ ishlayapti" if status.get("ready") else "⏳ hali ochilmagan"
    try:
        await query.edit_message_text(
            "🗄️ <b>DB Pool va Kesh holati:</b>\n\n"
            f"   • Pool: <b>{pool_label}</b>\n"
            f"   • Min/Maks: <b>{status.get('min')} / {status.get('max')}</b>\n"
            f"   • Band: <b>{status.get('used')}</b> | Bo'sh: <b>{status.get('available')}</b>"
            f" | Yopiq: <b>{collapsed_label}</b>\n"
            f"   • Kesh: <b>{cache_label}</b> — <b>{status.get('cache_entries')} ta</b> yozuv\n\n"
            "✅ <b>Kesh tozalandi.</b>",
            reply_markup=get_cache_actions_keyboard(),
            parse_mode="HTML",
        )
    except TelegramError:
        pass


async def start_set_post_tag(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    current_tag = await db.run_db(db.get_setting, "post_tag_text", "")
    await update.message.reply_text(
        "🏷 <b>Post nishoni (watermark):</b>\n\n"
        "Hozirgi qiymat: <code>" + html_escape(current_tag or "(bo'sh — nishon yo'q)") + "</code>\n\n"
        "Postlar oxiriga qo'shiladigan matnni yuboring.\n"
        "Masalan: <code>@PostAssistrobot</code>\n"
        "O'chirish uchun <code>clear</code> deb yozing.",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML",
    )
    return SET_POST_TAG


async def post_tag_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() == "clear":
        await db.run_db(db.set_setting, "post_tag_text", "")
        await update.message.reply_text(
            "✅ <b>Post nishoni o'chirildi</b> — postlar toza chiqadi.",
            reply_markup=get_admin_panel_keyboard(),
            parse_mode="HTML",
        )
    else:
        # HTML matn buzilmasligi uchun nishonni xavfsiz saqlaymiz.
        await db.run_db(db.set_setting, "post_tag_text", text)
        await update.message.reply_text(
            f"✅ <b>Post nishoni saqlandi:</b>\n\n<code>{html_escape(text)}</code>",
            reply_markup=get_admin_panel_keyboard(),
            parse_mode="HTML",
        )
    return ConversationHandler.END


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    stats = await db.run_db(db.get_system_stats)
    text = (
        "📊 <b>Bot Statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{stats['users']} ta</b>\n"
        f"📢 Ulangan kanallar: <b>{stats['channels']} ta</b>\n"
        f"📢 Homiy kanallar: <b>{stats['sponsors']} ta</b>\n"
        f"⏳ Kutilayotgan postlar: <b>{stats['pending']} ta</b>\n"
        f"✅ Yuborilgan postlar: <b>{stats['sent']} ta</b>\n"
        f"🚫 Bekor qilingan postlar: <b>{stats['cancelled']} ta</b>\n"
        f"⚠️ Xatolik bilan tugagan: <b>{stats['failed']} ta</b>"
    )
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")


async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    recent_posts = await db.run_db(db.get_recent_posts, 15)

    if not recent_posts:
        await update.message.reply_text("Hozircha hech qanday post mavjud emas.", reply_markup=get_admin_panel_keyboard())
        return

    text = "📋 <b>Oxirgi 15 ta post:</b>\n\n"
    for p in recent_posts:
        pid, uid, title, ptype, stime, status = p
        title_str = title or "Noma'lum kanal"
        status_emoji = "⏳" if status == "pending" else ("✅" if status == "posted" else "🚫")
        text += f"{status_emoji} <b>#{pid}</b> | {html_escape(title_str)} | {format_post_type_label(ptype)} | {status}\n"

    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")


async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    channels = await db.run_db(db.get_all_channels, ADMIN_CHANNELS_LIMIT)
    if not channels:
        await update.message.reply_text("Hozircha ulangan kanallar yo'q.", reply_markup=get_admin_panel_keyboard())
        return

    text = format_admin_channels_list(channels)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")


async def sponsors_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    sponsors = await db.run_db(db.get_active_sponsors)
    if sponsors is None:
        await update.message.reply_text(
            "⚠️ Homiy kanallarni bazadan o'qib bo'lmadi. Keyinroq urinib ko'ring.",
            reply_markup=get_admin_panel_keyboard(),
        )
        return
    text = f"📢 <b>Majburiy a'zolik (Homiy) kanallari ({len(sponsors)} ta):</b>\n\n"
    if sponsors:
        for s in sponsors:
            s_id, ch_id, ch_title, ch_url = s
            text += f"🔹 <b>{html_escape(ch_title)}</b> (<code>{ch_id}</code>)\n   🔗 Havola: {ch_url}\n\n"
    else:
        text += "Hozircha hech qanday homiy kanal qo'shilmagan.\n\n"

    text += "O'chirish uchun pastdagi ro'yxatdan tanlang yoki yangi kanal qo'shing 👇"
    await update.message.reply_text(text, reply_markup=get_sponsors_keyboard(), parse_mode="HTML")
    if sponsors:
        await update.message.reply_text("O'chirish uchun tanlang:", reply_markup=get_sponsors_delete_keyboard(sponsors))


async def start_add_sponsor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "➕ <b>Homiy kanal qo'shish:</b>\n\n"
        "Kanal ma'lumotlarini quyidagi formatda yuboring:\n"
        "<code>KANAL_ID|KANAL_NOMI|HAVOLA</code>\n\n"
        "👉 <i>Masalan: -1001234567890|Mening Kanalim|https://t.me/mening_kanalim</i>",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return ADD_SPONSOR_CHANNEL


async def sponsor_channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    parts = text.split("|")
    if len(parts) != 3:
        await update.message.reply_text("❌ Noto'g'ri format. Qaytadan kiriting (KANAL_ID|KANAL_NOMI|HAVOLA):")
        return ADD_SPONSOR_CHANNEL

    ch_id, title, url = parts[0].strip(), parts[1].strip(), parts[2].strip()
    success = await db.run_db(db.add_sponsor_channel, ch_id, title, url)
    if success:
        await update.message.reply_text(f"✅ Homiy kanal qo'shildi: <b>{html_escape(title)}</b>", reply_markup=get_admin_panel_keyboard(), parse_mode="HTML")
    else:
        await update.message.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END


async def del_sponsor_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Darhol javob — DB so'rovlaridan oldin, tugma muzlab qolmasligi uchun.
    try:
        await query.answer()
    except Exception:
        pass

    if not is_admin(query.from_user.id):
        try:
            await query.message.reply_text("🚫 Ruxsat yo'q.")
        except Exception:
            pass
        return
    s_id = int(query.data.split(":")[1])
    removed = await db.run_db(db.remove_sponsor_channel, s_id)
    if not removed:
        try:
            await query.message.reply_text("⚠️ Homiy kanal o'chirilmadi. Qayta urinib ko'ring.")
        except Exception:
            pass
    # Yangilangan ro'yxatni qayta chizamiz (qolgan homiylar ko'rinib tursin)
    sponsors = await db.run_db(db.get_active_sponsors)
    try:
        if sponsors:
            from keyboards.inline import get_sponsors_delete_keyboard
            await query.edit_message_reply_markup(reply_markup=get_sponsors_delete_keyboard(sponsors))
        else:
            await query.edit_message_text("📭 Barcha homiy kanallar o'chirildi. Yangi qo'shish uchun '➕ Homiy kanal qo'shish' tugmasini bosing.")
    except TelegramError:
        pass


async def start_set_channel_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    current_ad = await db.run_db(db.get_setting, "channel_ad_text", "Mavjud emas")
    await update.message.reply_text(
        f"📢 <b>Kanal postlari ostiga chiquvchi reklama:</b>\n\n"
        f"Hozirgi matn:\n<i>{html_escape(current_ad)}</i>\n\n"
        f"Yangi reklama matnini yuboring (o'chirish uchun <code>clear</code> deb yozing):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return SET_CHANNEL_AD


async def channel_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() == "clear":
        await db.run_db(db.set_setting, "channel_ad_text", "")
        await update.message.reply_text("✅ Kanal postlari reklamasi o'chirildi.", reply_markup=get_admin_panel_keyboard())
    else:
        await db.run_db(db.set_setting, "channel_ad_text", text)
        await update.message.reply_text("✅ Kanal postlari reklamasi muvaffaqiyatli saqlandi!", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END


async def start_set_bot_reply_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    current_ad = await db.run_db(db.get_setting, "bot_reply_ad_text", "Mavjud emas")
    await update.message.reply_text(
        f"🤖 <b>Bot javoblari ostiga chiquvchi reklama:</b>\n\n"
        f"Hozirgi matn:\n<i>{html_escape(current_ad)}</i>\n\n"
        f"Yangi reklama matnini yuboring (o'chirish uchun <code>clear</code> deb yozing):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return SET_BOT_REPLY_AD


async def bot_reply_ad_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() == "clear":
        await db.run_db(db.set_setting, "bot_reply_ad_text", "")
        await update.message.reply_text("✅ Bot javoblari reklamasi o'chirildi.", reply_markup=get_admin_panel_keyboard())
    else:
        await db.run_db(db.set_setting, "bot_reply_ad_text", text)
        await update.message.reply_text("✅ Bot javoblari reklamasi muvaffaqiyatli saqlandi!", reply_markup=get_admin_panel_keyboard())
    return ConversationHandler.END


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "✉️ <b>Barcha foydalanuvchilarga xabar yuborish:</b>\n\nYuboriladigan xabar matnini yozing:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="HTML"
    )
    return BROADCAST_MESSAGE


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    # Avvalgi broadcast hali davom etayotgan bo'lsa — takroriy ishga tushirmaymiz
    if _broadcast_lock.locked():
        await update.message.reply_text(
            "⏳ <b>Avvalgi xabar yuborilishi hali davom etmoqda.</b>\n"
            "Iltimos, yakunlanishini kuting (natija haqida xabar keladi).",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    text = update.message.text
    # DB chaqiruvini event loop'ni bloklamasdan thread'da bajarish
    user_ids = await db.run_db(db.get_all_user_ids)

    await update.message.reply_text(
        f"⏳ Xabar <b>{len(user_ids)} ta</b> foydalanuvchiga yuborilmoqda...\n"
        f"<i>Bu fon rejimida, batch'lar bilan yuboriladi.</i>",
        parse_mode="HTML"
    )

    # Broadcast fon vazifasi sifatida ishlaydi — admin boshqa buyruqlarni
    # bemalol ishlatishi mumkin, Telegram esa rate-limitga tushmaydi.
    async def _broadcast_task():
        async with _broadcast_lock:
            await _run_broadcast(context.bot, user_ids, text, update.effective_user.id)

    asyncio.create_task(_broadcast_task())
    return ConversationHandler.END


async def _run_broadcast(bot, user_ids, text, admin_id):
    """Broadcastni batch'lar bilan, rate-limit va retry bilan yuborish."""
    sent = 0
    failed = 0
    parse_mode = "HTML"

    for i, uid in enumerate(user_ids):
        delivered = False
        for attempt in range(3):
            try:
                await bot.send_message(chat_id=uid, text=text, parse_mode=parse_mode)
                sent += 1
                delivered = True
                break
            except RetryAfter as e:
                # Telegram aytgan vaqtgacha kutamiz va qayta urinamiz
                wait = min(max(int(getattr(e, "retry_after", 2) or 2), 1), 30)
                await asyncio.sleep(wait)
            except BadRequest:
                # HTML xato bo'lsa — oddiy matn sifatida qayta yuboramiz
                try:
                    await bot.send_message(chat_id=uid, text=text)
                    sent += 1
                except TelegramError:
                    failed += 1
                delivered = True
                break
            except (TimedOut, NetworkError):
                if attempt == 2:
                    failed += 1
                    delivered = True  # 3 ta urinish ham tugadi
                else:
                    await asyncio.sleep(1 + attempt)
            except TelegramError:
                # Bot bloklangan / xabar qabul qilinmagan
                failed += 1
                delivered = True
                break
        # Barcha 3 urinish RetryAfter bilan tugasa ham foydalanuvchi
        # "yuborilmagan" hisobiga kiritilishi kerak (jim o'tib ketmasligi uchun).
        if not delivered:
            failed += 1

        # Har batch'da qisqa pauza — Telegram'ning 30 msg/s limitidan oshmaymiz
        if i and i % BROADCAST_BATCH_SIZE == 0:
            await asyncio.sleep(BROADCAST_BATCH_DELAY)

    try:
        await bot.send_message(
            chat_id=admin_id,
            text=(
                f"✅ <b>Xabar tarqatildi!</b>\n\n"
                f"Yetib bordi: <b>{sent} / {len(user_ids)}</b> ta foydalanuvchiga.\n"
                f"❌ Yuborilmagan: <b>{failed} ta</b>."
            ),
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Broadcast yakuni haqida admin xabari yuborilmadi")
    logger.info("Broadcast yakunlandi: sent=%d, failed=%d, total=%d", sent, failed, len(user_ids))
