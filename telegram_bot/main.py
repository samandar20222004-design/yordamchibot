import os
import re
import logging
from datetime import datetime, timedelta

import pytz
from aiohttp import web

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import TelegramError
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, ADMIN_ID
import database as db
from scheduler import check_and_send_posts
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")

# --- Conversation states -----------------------------------------------------
CHOOSE_CHANNEL, CHOOSE_TYPE, GET_CONTENT, GET_TIME = range(4)
ADD_CHANNEL = 10
BROADCAST_MESSAGE = 20

# --- Fixed button labels (kept in one place so text and filters never drift) -
BTN_NEW_POST = "➕ Yangi post rejalashtirish"
BTN_PENDING = "📋 Kutilayotgan postlar"
BTN_CHANNELS = "📢 Kanallar"
BTN_ADMIN_PANEL = "👑 Admin Panel"
BTN_STATS = "📊 Statistika"
BTN_MAIN_MENU = "🔙 Asosiy menyu"
BTN_ADD_CHANNEL = "➕ Kanal qo'shish"
BTN_ALL_CHANNELS_TARGET = "📢 Barcha kanallarga birdaniga"
BTN_TEXT_POST = "📝 Oddiy matn"
BTN_PHOTO_POST = "🖼 Rasm + Matn"
BTN_BROADCAST = "📢 Xabar yuborish"
BTN_ALL_POSTS = "📋 Barcha postlar"
BTN_ALL_CHANNELS = "📢 Barcha kanallar"


def exact(*texts):
    """Tugma matniga aniq (regex maxsus belgilaridan xoli) mos keladigan filtr yaratadi."""
    pattern = "^(" + "|".join(re.escape(t) for t in texts) + ")$"
    return filters.Regex(pattern)


# --- Web server (Render / UptimeRobot uchun) --------------------------------
async def handle_ping(request):
    return web.Response(text="PostAssistrobot OK", status=200)


async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/healthz', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"PostAssistrobot web server 0.0.0.0:{port} portida ishga tushdi.")


# --- Keyboards ----------------------------------------------------------------
def get_main_keyboard(is_admin=False):
    keyboard = [
        [BTN_NEW_POST],
        [BTN_PENDING, BTN_CHANNELS],
    ]
    if is_admin:
        keyboard.append([BTN_ADMIN_PANEL])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[BTN_MAIN_MENU]], resize_keyboard=True)


def get_admin_panel_keyboard():
    return ReplyKeyboardMarkup(
        [
            [BTN_BROADCAST],
            [BTN_ALL_POSTS, BTN_ALL_CHANNELS],
            [BTN_STATS],
            [BTN_MAIN_MENU],
        ],
        resize_keyboard=True,
    )


# --- Shared render helpers -----------------------------------------------------
def render_pending_list(posts, title, show_owner=False):
    if not posts:
        return "📋 Hozircha rejalashtirilgan postlar yo'q.", None

    text = f"{title}\n\n"
    keyboard = []
    scope = "all" if show_owner else "mine"

    for p in posts:
        if show_owner:
            pid, c_title, p_type, s_time, owner_id, owner_username = p
        else:
            pid, c_title, p_type, s_time = p
        ch_title = c_title if c_title else "Kanal"
        line = f"🔹 **#{pid}** | {ch_title}\n⏰ `{s_time.strftime('%Y-%m-%d %H:%M')}` | 📁 {p_type}"
        if show_owner:
            owner_label = f"@{owner_username}" if owner_username else str(owner_id)
            line += f"\n👤 {owner_label}"
        text += line + "\n\n"
        keyboard.append([InlineKeyboardButton(f"❌ #{pid} bekor qilish", callback_data=f"cancel_post:{pid}:{scope}")])

    return text, InlineKeyboardMarkup(keyboard)


def render_channels_list(channels, show_owner=False):
    if not channels:
        return "📢 Hozircha ulangan kanallar mavjud emas.", None

    text = "📢 **Ulangan kanallar:**\n\n"
    keyboard = []
    scope = "all" if show_owner else "mine"

    for ch in channels:
        if show_owner:
            channel_id, channel_title, owner_id, owner_username = ch
        else:
            channel_id, channel_title = ch
        line = f"• **{channel_title}** (ID: `{channel_id}`)"
        if show_owner:
            owner_label = f"@{owner_username}" if owner_username else str(owner_id)
            line += f"\n  👤 {owner_label}"
        text += line + "\n"
        keyboard.append([InlineKeyboardButton(f"🗑 {channel_title} o'chirish", callback_data=f"remove_channel:{channel_id}:{scope}")])

    return text, InlineKeyboardMarkup(keyboard)


async def _jump_to(update: Update, context: ContextTypes.DEFAULT_TYPE, fn) -> int:
    """Yordamchi: joriy suhbatni tugatib, oddiy (bosqichsiz) bo'limni ko'rsatadi."""
    context.user_data.clear()
    await fn(update, context)
    return ConversationHandler.END


async def jump_main_menu(update, context):
    return await _jump_to(update, context, start)


async def jump_channels(update, context):
    return await _jump_to(update, context, channels_menu)


async def jump_pending(update, context):
    return await _jump_to(update, context, list_pending_posts)


async def jump_admin_panel(update, context):
    return await _jump_to(update, context, admin_panel_menu)


async def jump_stats(update, context):
    return await _jump_to(update, context, show_statistics)


async def jump_all_posts(update, context):
    return await _jump_to(update, context, admin_all_posts)


async def jump_all_channels(update, context):
    return await _jump_to(update, context, admin_all_channels)


# --- Basic commands -------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    db.save_user(user.id, user.username or user.first_name)
    is_admin = (user.id == ADMIN_ID)

    await update.message.reply_text(
        f"Salom, {user.first_name}! 👋\n\n"
        f"🤖 **PostAssistrobot** — Telegram kanallaringiz uchun aqlli avtoposting yordamchingiz.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    text = (
        "ℹ️ **Buyruqlar ro'yxati:**\n\n"
        "/start — Botni qayta ishga tushirish\n"
        "/newpost — Yangi post rejalashtirish\n"
        "/cancel — Joriy jarayonni bekor qilish\n"
        "/help — Ushbu yordam xabari\n"
    )
    if is_admin:
        text += (
            "\n👑 **Admin buyruqlari:**\n"
            "/admin — Admin panelni ochish\n"
            "/broadcast — Barcha foydalanuvchilarga xabar yuborish\n"
            "/stats — Tezkor statistika\n"
        )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    context.user_data.clear()
    await update.message.reply_text("👌 Jarayon bekor qilindi.", reply_markup=get_main_keyboard(is_admin))
    return ConversationHandler.END


async def unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    is_admin = (update.effective_user.id == ADMIN_ID)
    await update.message.reply_text(
        "🤔 **Buyruq tushunarsiz!**\nPastdagi menyudan foydalaning yoki /start bosing 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
    )


# --- New post flow -----------------------------------------------------------
async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)

    channels = db.get_user_channels(user_id)

    if not channels:
        await update.message.reply_text(
            "😔 **Ulangan kanal topilmadi!**\n\n"
            "Avval pastdagi **'📢 Kanallar'** tugmasi orqali kanalingizni ulang.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    keyboard = [[ch[1]] for ch in channels]
    if len(channels) > 1:
        keyboard.append([BTN_ALL_CHANNELS_TARGET])
    keyboard.append([BTN_MAIN_MENU])
    context.user_data["channels_map"] = {ch[1]: ch[0] for ch in channels}

    await update.message.reply_text(
        "📢 **Qaysi kanalga post rejalashtiramiz?**\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_CHANNEL


async def channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text == BTN_ALL_CHANNELS_TARGET:
        context.user_data["selected_channel_id"] = "ALL"
        context.user_data["selected_channel_title"] = "📢 Barcha kanallar"
    else:
        channels_map = context.user_data.get("channels_map", {})
        if text not in channels_map:
            await update.message.reply_text("🤔 Bunday kanal yo'q. Pastdagi tugmalardan tanlang:")
            return CHOOSE_CHANNEL
        context.user_data["selected_channel_id"] = channels_map[text]
        context.user_data["selected_channel_title"] = text

    keyboard = [
        [BTN_TEXT_POST, BTN_PHOTO_POST],
        [BTN_MAIN_MENU]
    ]
    await update.message.reply_text(
        f"🎯 Tanlandi: **{context.user_data['selected_channel_title']}**\n\nEndi post formatini belgilang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_TYPE


async def type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    if text not in (BTN_TEXT_POST, BTN_PHOTO_POST):
        await update.message.reply_text("⚠️ Iltimos, pastdagi tugmalardan birini bosing.")
        return CHOOSE_TYPE

    context.user_data["post_type"] = "text" if text == BTN_TEXT_POST else "photo"

    if context.user_data["post_type"] == "photo":
        await update.message.reply_text(
            "📸 **Rasmni yuboring:**\n(Tagiga post matnini ham yozishingiz mumkin)",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "✍️ **Post matnini yuboring:**",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
    return GET_CONTENT


async def content_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post_type = context.user_data.get("post_type")

    if post_type == "photo":
        if not update.message.photo:
            await update.message.reply_text("❌ Bu rasm emas! Rasm yuboring yoki '🔙 Asosiy menyu'ni bosing.")
            return GET_CONTENT
        context.user_data["file_id"] = update.message.photo[-1].file_id
        context.user_data["caption"] = update.message.caption or ""
    else:
        if not update.message.text:
            await update.message.reply_text("❌ Matn topilmadi! Iltimos, matn yuboring.")
            return GET_CONTENT
        context.user_data["content_text"] = update.message.text

    now = datetime.now(tashkent_tz)
    example = (now + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")

    keyboard = [
        ["⏱ +15 daqiqa", "⏳ +1 soat"],
        ["🌅 Ertaga 09:00", "🌇 Ertaga 18:00"],
        [BTN_MAIN_MENU]
    ]
    await update.message.reply_text(
        "⏰ **Post qaysi vaqtda chiqsin?**\n\n"
        "Tugmalardan tanlang yoki aniq vaqtni yozing:\n"
        f"👉 `{example}`",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return GET_TIME


async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    is_admin = (update.effective_user.id == ADMIN_ID)

    now = datetime.now(tashkent_tz)
    post_time = None

    try:
        if "15 daqiqa" in text:
            post_time = now + timedelta(minutes=15)
        elif "1 soat" in text:
            post_time = now + timedelta(hours=1)
        elif "09:00" in text:
            post_time = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        elif "18:00" in text:
            post_time = (now + timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
        else:
            naive_time = datetime.strptime(text.strip(), "%Y-%m-%d %H:%M")
            post_time = tashkent_tz.localize(naive_time)

        if post_time <= now:
            await update.message.reply_text("⚠️ **Vaqt xato!** Kelajakdagi vaqtni kiriting:")
            return GET_TIME
    except Exception:
        await update.message.reply_text("❌ Format xato! `2026-08-26 18:00` shaklida yuboring.")
        return GET_TIME

    user_id = update.effective_user.id
    selected_channel_id = context.user_data["selected_channel_id"]
    post_type = context.user_data["post_type"]
    content = context.user_data.get("caption") if post_type == "photo" else context.user_data.get("content_text")
    file_id = context.user_data.get("file_id")

    if selected_channel_id == "ALL":
        channels = db.get_user_channels(user_id)
        ok_count = 0
        for ch_id, ch_title in channels:
            if db.add_post(user_id, ch_id, post_type, content, file_id, post_time):
                ok_count += 1
        if ok_count:
            await update.message.reply_text(
                f"🎉 **Post {ok_count} ta kanalga rejalashtirildi!**\n\n"
                f"📅 Vaqti: **{post_time.strftime('%Y-%m-%d %H:%M')}**\n\n"
                f"🚀 PostAssistrobot belgilangan vaqtda barcha kanallarga chiqaradi!",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Bazaga saqlashda xatolik bo'ldi.", reply_markup=get_main_keyboard(is_admin))
    else:
        if db.add_post(user_id, selected_channel_id, post_type, content, file_id, post_time):
            await update.message.reply_text(
                f"🎉 **Post muvaffaqiyatli rejalashtirildi!**\n\n"
                f"📢 Joylash: **{context.user_data['selected_channel_title']}**\n"
                f"📅 Vaqti: **{post_time.strftime('%Y-%m-%d %H:%M')}**\n\n"
                f"🚀 PostAssistrobot belgilangan vaqtda kanalga chiqaradi!",
                reply_markup=get_main_keyboard(is_admin),
                parse_mode="Markdown"
            )
        else:
            await update.message.reply_text("❌ Bazaga saqlashda xatolik bo'ldi.", reply_markup=get_main_keyboard(is_admin))

    context.user_data.clear()
    return ConversationHandler.END


# --- Channels ------------------------------------------------------------------
async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    channels = db.get_user_channels(user_id)

    text, inline_markup = render_channels_list(channels, show_owner=False)

    keyboard = [[BTN_ADD_CHANNEL], [BTN_MAIN_MENU]]
    await update.message.reply_text(
        text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    if inline_markup:
        await update.message.reply_text("O'chirmoqchi bo'lgan kanalni tanlang 👇", reply_markup=inline_markup)
    return ConversationHandler.END


async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "➕ **Kanal yoki guruh ulash:**\n\n"
        "✅ **ENG OSON YO'L:**\n"
        "Botni kanalingizga (admin qilib) yoki guruhingizga (oddiy a'zo sifatida) qo'shing — "
        "bot buni **avtomatik aniqlaydi** va sizga tasdiq xabarini yuboradi. Boshqa hech narsa qilish shart emas!\n\n"
        "📌 **Agar bot allaqachon qo'shilgan bo'lsa:**\n"
        "O'sha kanal/guruhdan biror xabarni shu yerga **Forward (Uzatish)** qiling, "
        "yoki @username'ini yozing 👇",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return ADD_CHANNEL


async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    msg = update.message

    identifier = None

    origin = getattr(msg, 'forward_origin', None)
    if origin:
        chat = getattr(origin, 'chat', None)
        if chat:
            identifier = chat.id

    if identifier is None and msg.text:
        t = msg.text.strip()
        bare = t[1:] if t.startswith('-') else t
        # Guruhlar uchun ID "-100" bilan boshlanmasligi ham mumkin (oddiy guruhlar),
        # shuning uchun har qanday manfiy/musbat butun sonni ham qabul qilamiz.
        if t.startswith("@") or bare.isdigit():
            identifier = t

    if identifier is None:
        await msg.reply_text(
            "❌ **Kanal/guruh aniqlanmadi!**\n\n"
            "Iltimos, o'sha yerdan biror xabarni to'g'ridan-to'g'ri Forward qiling "
            "yoki @username yozing:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return ADD_CHANNEL

    # Kanal/guruh haqiqatan mavjudligini va botning postlash huquqi borligini tekshiramiz.
    # Bu tekshiruv bo'lmasa, keyinchalik post chiqarishga urinilganda botning
    # ruxsati yo'qligi sabab post "jim" yuborilmay qolishi mumkin edi.
    try:
        chat = await context.bot.get_chat(identifier)
        member = await context.bot.get_chat_member(chat.id, context.bot.id)
        status = member.status

        if chat.type == "channel":
            # Kanalda faqat adminlar post joylay oladi (Telegram cheklovi).
            allowed = status in ("administrator", "creator")
        else:
            # Guruh/superguruhda oddiy a'zolik ko'pincha yetarli, lekin
            # "restricted" holatda yozish huquqi alohida tekshiriladi.
            allowed = status in ("administrator", "creator", "member")
            if status == "restricted":
                allowed = getattr(member, "can_send_messages", False)

        if not allowed:
            kind = "kanal" if chat.type == "channel" else "guruh"
            hint = (
                "botni admin qilib tayinlang" if chat.type == "channel"
                else "guruh sozlamalaridan botga yozish ruxsatini bering"
            )
            await msg.reply_text(
                f"⚠️ **Bot bu {kind}da postlash huquqiga ega emas!**\n\n"
                f"Iltimos, {hint} va qaytadan urinib ko'ring.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
            return ADD_CHANNEL

        channel_id = str(chat.id)
        channel_title = chat.title or "Telegram Kanal"
    except TelegramError as e:
        logger.error(f"Kanalni tekshirishda xato: {e}")
        await msg.reply_text(
            "❌ **Ulanib bo'lmadi.**\n\n"
            "Sabablari:\n"
            "• Bot hali kanal/guruhga qo'shilmagan\n"
            "• @username noto'g'ri yozilgan\n\n"
            "Botni kanal/guruhga qo'shib, qaytadan urinib ko'ring.",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return ADD_CHANNEL

    if db.save_channel(user_id, channel_id, channel_title):
        await msg.reply_text(
            f"🎉 **Muvaffaqiyatli ulandi!**\n\n📢 Nomi: **{channel_title}**\n🆔 ID: `{channel_id}`",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
    else:
        await msg.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
    return ConversationHandler.END


# --- Pending posts ---------------------------------------------------------------
async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    posts = db.get_pending_posts(user_id)

    text, inline_markup = render_pending_list(posts, "📋 **Kutilayotgan postlaringiz:**")
    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("Bekor qilish uchun tugmani bosing 👇", reply_markup=inline_markup)


# --- Admin panel -------------------------------------------------------------------
async def admin_panel_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return
    await update.message.reply_text(
        "👑 **Admin boshqaruv paneli**\n\nKerakli bo'limni tanlang 👇",
        reply_markup=get_admin_panel_keyboard(),
        parse_mode="Markdown"
    )


async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return

    stats = db.get_system_stats()
    text = (
        f"📊 **PostAssistrobot statistikasi**\n\n"
        f"👥 Jami foydalanuvchilar: **{stats['users']} ta**\n"
        f"📢 Ulangan kanallar: **{stats['channels']} ta**\n"
        f"⏳ Kutilayotgan postlar: **{stats['pending']} ta**\n"
        f"✅ Chiqqan postlar: **{stats['sent']} ta**\n"
        f"❌ Bekor qilingan postlar: **{stats['cancelled']} ta**\n"
        f"⚠️ Yuborilmagan (xatolik) postlar: **{stats['failed']} ta**\n"
    )
    await update.message.reply_text(text, reply_markup=get_main_keyboard(True), parse_mode="Markdown")


async def admin_all_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return

    posts = db.get_all_pending_posts()
    text, inline_markup = render_pending_list(posts, "📋 **Barcha foydalanuvchilarning kutilayotgan postlari:**", show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("Bekor qilish uchun tugmani bosing 👇", reply_markup=inline_markup)


async def admin_all_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return

    channels = db.get_all_channels()
    text, inline_markup = render_channels_list(channels, show_owner=True)
    await update.message.reply_text(text, reply_markup=get_admin_panel_keyboard(), parse_mode="Markdown")
    if inline_markup:
        await update.message.reply_text("O'chirmoqchi bo'lgan kanalni tanlang 👇", reply_markup=inline_markup)


async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return ConversationHandler.END

    await update.message.reply_text(
        "📢 **Barcha foydalanuvchilarga yuboriladigan xabar matnini yozing:**",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return BROADCAST_MESSAGE


async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return ConversationHandler.END

    text = update.message.text

    user_ids = db.get_all_user_ids()
    sent = 0
    failed = 0
    for uid in user_ids:
        try:
            await context.bot.send_message(chat_id=uid, text=f"🔔 **Tizim xabari:**\n\n{text}", parse_mode="Markdown")
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"✅ Xabar **{sent} ta** foydalanuvchiga yuborildi.\n❌ {failed} ta foydalanuvchiga yetkazilmadi (botni bloklagan bo'lishi mumkin).",
        reply_markup=get_admin_panel_keyboard(),
        parse_mode="Markdown"
    )
    return ConversationHandler.END


# --- Inline callback queries (cancel post / remove channel) --------------------
async def cancel_post_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)

    try:
        _, pid_str, scope = query.data.split(":")
        post_id = int(pid_str)
    except (ValueError, AttributeError):
        await query.answer("❌ Noto'g'ri so'rov.", show_alert=True)
        return

    owner = db.get_post_owner(post_id)
    if not owner:
        await query.answer("❌ Post topilmadi.", show_alert=True)
        return

    owner_id, status = owner
    if not is_admin and owner_id != user_id:
        await query.answer("⛔️ Bu sizning postingiz emas.", show_alert=True)
        return

    if status != "pending":
        await query.answer("ℹ️ Bu post allaqachon chiqqan yoki bekor qilingan.", show_alert=True)
        return

    if db.cancel_post(post_id, user_id, is_admin=is_admin):
        await query.answer("✅ Post bekor qilindi.")
    else:
        await query.answer("❌ Bekor qilib bo'lmadi.", show_alert=True)
        return

    # Ro'yxatni yangilangan holatda qayta chizamiz.
    if scope == "all":
        posts = db.get_all_pending_posts()
        text, markup = render_pending_list(posts, "📋 **Barcha foydalanuvchilarning kutilayotgan postlari:**", show_owner=True)
    else:
        posts = db.get_pending_posts(user_id)
        text, markup = render_pending_list(posts, "📋 **Kutilayotgan postlaringiz:**")

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except TelegramError:
        pass


async def remove_channel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    is_admin = (user_id == ADMIN_ID)

    try:
        _, channel_id, scope = query.data.split(":")
    except (ValueError, AttributeError):
        await query.answer("❌ Noto'g'ri so'rov.", show_alert=True)
        return

    if db.remove_channel(user_id, channel_id, is_admin=is_admin):
        await query.answer("✅ Kanal o'chirildi.")
    else:
        await query.answer("⛔️ Bu kanal sizga tegishli emas yoki allaqachon o'chirilgan.", show_alert=True)
        return

    if scope == "all":
        channels = db.get_all_channels()
        text, markup = render_channels_list(channels, show_owner=True)
    else:
        channels = db.get_user_channels(user_id)
        text, markup = render_channels_list(channels, show_owner=False)

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=markup)
    except TelegramError:
        pass


# --- Error handler ----------------------------------------------------------------
async def on_bot_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Bot biror kanal yoki guruhga qo'shilganda (yoki undan chiqarilganda) avtomatik
    ishlaydi. Foydalanuvchi endi kanal/guruhni qo'lda @username yozib yoki forward
    qilib qo'shishi shart emas — botni o'sha yerga a'zo/admin qilib qo'shishning o'zi
    yetarli, qolganini bot o'zi bajaradi.
    """
    cmu = update.my_chat_member
    if not cmu:
        return

    chat = cmu.chat
    if chat.type not in ("channel", "group", "supergroup"):
        return

    new_status = cmu.new_chat_member.status
    adder = cmu.from_user
    kind = "kanal" if chat.type == "channel" else "guruh"

    if new_status in ("administrator", "creator", "member", "restricted"):
        if chat.type == "channel" and new_status not in ("administrator", "creator"):
            return  # Kanalda faqat admin bo'lsa postlash mumkin
        if new_status == "restricted" and not getattr(cmu.new_chat_member, "can_send_messages", False):
            return

        ok = db.save_channel(adder.id if adder else 0, str(chat.id), chat.title or "Nomsiz")
        if ok and adder:
            try:
                await context.bot.send_message(
                    chat_id=adder.id,
                    text=(
                        f"🎉 **Yangi {kind} avtomatik ulandi!**\n\n"
                        f"📢 Nomi: **{chat.title}**\n"
                        f"🆔 ID: `{chat.id}`\n\n"
                        f"Endi bu yerga post rejalashtira olasiz."
                    ),
                    parse_mode="Markdown"
                )
            except Exception:
                pass  # Foydalanuvchi botni shaxsiyda ishga tushirmagan bo'lishi mumkin

    elif new_status in ("left", "kicked"):
        db.remove_channel(0, str(chat.id), is_admin=True)
        if adder:
            try:
                await context.bot.send_message(
                    chat_id=adder.id,
                    text=f"ℹ️ Bot **{chat.title}** {kind}idan olib tashlandi, u ro'yxatdan chiqarildi.",
                    parse_mode="Markdown"
                )
            except Exception:
                pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Kutilmagan xatolik yuz berdi:", exc_info=context.error)


async def post_init(application):
    await start_web_server()


def main():
    db.init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Bu tugmalar suhbatning QAYSI bosqichida bo'lishidan qat'iy nazar har doim
    # ishlashi kerak (masalan, "Kanal qo'shish" jarayonida turib "Xabar yuborish"
    # tugmasini bossa ham to'g'ri bo'limga o'tishi kerak). Shuning uchun ular HAR
    # bir suhbat bosqichi ro'yxatiga eng birinchi bo'lib qo'shiladi.
    global_jump_handlers = [
        MessageHandler(exact(BTN_MAIN_MENU), jump_main_menu),
        MessageHandler(exact(BTN_NEW_POST), start_new_post),
        MessageHandler(exact(BTN_ADD_CHANNEL), start_add_channel),
        MessageHandler(exact(BTN_CHANNELS), jump_channels),
        MessageHandler(exact(BTN_PENDING), jump_pending),
        MessageHandler(exact(BTN_ADMIN_PANEL), jump_admin_panel),
        MessageHandler(exact(BTN_STATS), jump_stats),
        MessageHandler(exact(BTN_ALL_POSTS), jump_all_posts),
        MessageHandler(exact(BTN_ALL_CHANNELS), jump_all_channels),
        MessageHandler(exact(BTN_BROADCAST), broadcast_start),
    ]

    main_conv = ConversationHandler(
        entry_points=[
            MessageHandler(exact(BTN_NEW_POST), start_new_post),
            MessageHandler(exact(BTN_ADD_CHANNEL), start_add_channel),
            MessageHandler(exact(BTN_BROADCAST), broadcast_start),
            CommandHandler("newpost", start_new_post),
            CommandHandler("broadcast", broadcast_start),
        ],
        states={
            CHOOSE_CHANNEL: global_jump_handlers + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)
            ],
            CHOOSE_TYPE: global_jump_handlers + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, type_chosen)
            ],
            GET_CONTENT: global_jump_handlers + [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), content_received)
            ],
            GET_TIME: global_jump_handlers + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)
            ],
            ADD_CHANNEL: global_jump_handlers + [
                MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)
            ],
            BROADCAST_MESSAGE: global_jump_handlers + [
                MessageHandler(filters.TEXT & ~filters.COMMAND, broadcast_send)
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
        ],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("admin", admin_panel_menu))
    app.add_handler(CommandHandler("stats", show_statistics))

    # MUHIM: main_conv birinchi ro'yxatdan o'tishi SHART. Aks holda, quyidagi
    # "bo'sh holat" tugmalari (masalan, "Kanallar") yoki /start, /cancel kabi
    # buyruqlar suhbat ICHIDA yuborilganda ham to'g'ridan-to'g'ri ushlanib qolib,
    # ConversationHandler o'zining ichki holatini to'g'ri yakunlay olmay,
    # "osilib qolgan" holatga tushib qolar edi.
    app.add_handler(main_conv)

    # Suhbatdan tashqarida (bo'sh holatda) ham shu tugmalar/buyruqlar
    # to'g'ridan-to'g'ri ishlaydi. (main_conv ularni entry_point yoki fallback
    # sifatida tanimasa, bo'sh holatda bu yerga muammosiz "tushib" keladi.)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cancel", cancel_handler))
    app.add_handler(MessageHandler(exact(BTN_CHANNELS), channels_menu))
    app.add_handler(MessageHandler(exact(BTN_PENDING), list_pending_posts))
    app.add_handler(MessageHandler(exact(BTN_MAIN_MENU), start))
    app.add_handler(MessageHandler(exact(BTN_ADMIN_PANEL), admin_panel_menu))
    app.add_handler(MessageHandler(exact(BTN_STATS), show_statistics))
    app.add_handler(MessageHandler(exact(BTN_ALL_POSTS), admin_all_posts))
    app.add_handler(MessageHandler(exact(BTN_ALL_CHANNELS), admin_all_channels))

    app.add_handler(CallbackQueryHandler(cancel_post_callback, pattern=r"^cancel_post:"))
    app.add_handler(CallbackQueryHandler(remove_channel_callback, pattern=r"^remove_channel:"))

    # Bot biror kanal/guruhga qo'shilgan yoki chiqarib yuborilganda avtomatik ishlaydi.
    app.add_handler(ChatMemberHandler(on_bot_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    app.add_error_handler(error_handler)

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_posts, 'interval', minutes=1, args=[app.bot])
    scheduler.start()

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
