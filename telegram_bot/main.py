import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
import pytz

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)
from database import init_db, get_connection
from scheduler import check_and_send_posts
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 7105264103  # Sizning ID raqamingiz to'g'ridan-to'g'ri biriktirildi

tashkent_tz = pytz.timezone("Asia/Tashkent")

CHOOSE_CHANNEL, CHOOSE_TYPE, GET_CONTENT, GET_TIME = range(4)
ADD_CHANNEL = 10

def get_main_keyboard(is_admin=False):
    keyboard = [
        ["➕ Yangi post rejalashtirish"],
        ["📋 Kutilayotgan postlar", "📢 Kanallar va Guruhlar"]
    ]
    if is_admin:
        keyboard.append(["👑 Admin Panel", "📊 Statistika"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_cancel_keyboard():
    return ReplyKeyboardMarkup([["🔙 Asosiy menyu"]], resize_keyboard=True)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"AssistBot is running 24/7!")

    def log_message(self, format, *args):
        pass

def start_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# Foydalanuvchini bazaga xatosiz yozish
def save_user(user_id, username):
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id, username, created_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO NOTHING
        """, (user_id, username))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"User saqlash xatosi: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.effective_user
    save_user(user.id, user.username or user.first_name)
    
    is_admin = (user.id == ADMIN_ID)
    
    await update.message.reply_text(
        f"Salom, {user.first_name}! 👋\n\n"
        f"🤖 **AssistBot** — Telegram kanallari va guruhlari uchun avtoposting xizmati.\n\n"
        f"Quyidagi menyudan kerakli bo'limni tanlang 👇",
        reply_markup=get_main_keyboard(is_admin),
        parse_mode="Markdown"
    )
    return ConversationHandler.END

# 1. Post rejalashtirish
async def start_new_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    
    channels = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_id, channel_title FROM channels WHERE user_id = %s AND is_active = TRUE", (user_id,))
        channels = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"DB xatosi: {e}")

    if not channels:
        await update.message.reply_text(
            "😔 **Faol kanal yoki guruh topilmadi!**\n\n"
            "Avval '📢 Kanallar va Guruhlar' bo'limidan kanalingizni yoki guruhingizni ulang.",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    keyboard = [[ch[1]] for ch in channels]
    keyboard.append(["🔙 Asosiy menyu"])
    context.user_data["channels_map"] = {ch[1]: ch[0] for ch in channels}

    await update.message.reply_text(
        "📢 **Qaysi kanal yoki guruhga post rejalashtiramiz?**\nRo'yxatdan tanlang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_CHANNEL

async def channel_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    is_admin = (update.effective_user.id == ADMIN_ID)

    if text in ["🔙 Asosiy menyu", "❌ Bekor qilish", "/start"]:
        context.user_data.clear()
        await update.message.reply_text("👌 Jarayon to'xtatildi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    channels_map = context.user_data.get("channels_map", {})
    if text not in channels_map:
        await update.message.reply_text("🤔 Bunday kanal ro'yxatda yo'q. Pastdagi tugmalardan tanlang:")
        return CHOOSE_CHANNEL

    context.user_data["selected_channel_id"] = channels_map[text]
    context.user_data["selected_channel_title"] = text

    keyboard = [
        ["📝 Oddiy matn", "🖼 Rasm + Matn"],
        ["🔙 Asosiy menyu"]
    ]
    await update.message.reply_text(
        f"🎯 Tanlandi: **{text}**\n\nEndi post formatini belgilang 👇",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return CHOOSE_TYPE

async def type_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    is_admin = (update.effective_user.id == ADMIN_ID)

    if text in ["🔙 Asosiy menyu", "❌ Bekor qilish", "/start"]:
        context.user_data.clear()
        await update.message.reply_text("👌 Jarayon to'xtatildi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    if "Oddiy matn" not in text and "Rasm" not in text:
        await update.message.reply_text("⚠️ Iltimos, pastdagi tugmalardan birini bosing.")
        return CHOOSE_TYPE

    context.user_data["post_type"] = "text" if "Oddiy matn" in text else "photo"

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
    is_admin = (update.effective_user.id == ADMIN_ID)

    if update.message.text in ["🔙 Asosiy menyu", "❌ Bekor qilish", "/start"]:
        context.user_data.clear()
        await update.message.reply_text("👌 Jarayon to'xtatildi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

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

    keyboard = [
        ["⏱ +15 daqiqa", "⏳ +1 soat"],
        ["🌅 Ertaga 09:00", "🌇 Ertaga 18:00"],
        ["🔙 Asosiy menyu"]
    ]
    await update.message.reply_text(
        "⏰ **Post qaysi vaqtda chiqarilsin?**\n\n"
        "Tugmalardan tanlang yoki aniq vaqtni yozing:\n"
        "👉 `2026-08-25 15:30`",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
        parse_mode="Markdown"
    )
    return GET_TIME

async def time_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    is_admin = (update.effective_user.id == ADMIN_ID)

    if text in ["🔙 Asosiy menyu", "❌ Bekor qilish", "/start"]:
        context.user_data.clear()
        await update.message.reply_text("👌 Jarayon to'xtatildi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

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
        await update.message.reply_text("❌ Format xato! YYYY-MM-DD HH:MM shaklida yuboring.")
        return GET_TIME

    user_id = update.effective_user.id
    channel_id = context.user_data["selected_channel_id"]
    post_type = context.user_data["post_type"]
    content = context.user_data.get("caption") if post_type == "photo" else context.user_data.get("content_text")
    file_id = context.user_data.get("file_id")

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, file_id, scheduled_time, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'pending')
        """, (user_id, channel_id, post_type, content, file_id, post_time))
        conn.commit()
        cur.close()
        conn.close()

        await update.message.reply_text(
            f"🎉 **Post muvaffaqiyatli rejalashtirildi!**\n\n"
            f"📢 Joylash: **{context.user_data['selected_channel_title']}**\n"
            f"📅 Vaqti: **{post_time.strftime('%Y-%m-%d %H:%M')}**\n\n"
            f"🚀 AssistBot belgilangan vaqtda chop etadi!",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"Post saqlash xatosi: {e}")
        await update.message.reply_text("❌ Xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))

    context.user_data.clear()
    return ConversationHandler.END

# 2. Kanallar va Guruhlar bo'limi
async def channels_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    channels = []
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT channel_title, channel_id FROM channels WHERE user_id = %s", (user_id,))
        channels = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Kanal olish xatosi: {e}")

    text = "📢 **Ulangan kanallar va guruhlar:**\n\n"
    if not channels:
        text += "Hozircha ulangan manbalar yo'q.\n"
    else:
        for idx, ch in enumerate(channels, 1):
            text += f"{idx}. **{ch[0]}** (ID: `{ch[1]}`)\n"

    keyboard = [["➕ Kanal/Guruh qo'shish"], ["🔙 Asosiy menyu"]]
    await update.message.reply_text(text, reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True), parse_mode="Markdown")

async def start_add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "➕ **Kanal yoki Guruh ulash tartibi:**\n\n"
        "1. Botni kanalingiz yoki guruhingizga **Admin** qilib tayinlang.\n"
        "2. O'sha kanaldan biron xabarni bu yerga **Forward (Uzatish)** qiling yoki ID raqamini yozing (masalan: `-1001234567890`):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    return ADD_CHANNEL

async def channel_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    msg = update.message

    if msg.text in ["🔙 Asosiy menyu", "❌ Bekor qilish", "/start"]:
        await msg.reply_text("👌 Jarayon to'xtatildi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

    channel_id = None
    channel_title = "Telegram Manba"

    # Yangi PTB v21 forward origin tekshiruvi (Kanal va Guruhlar uchun)
    origin = getattr(msg, 'forward_origin', None)
    if origin:
        chat = getattr(origin, 'chat', None)
        if chat:
            channel_id = chat.id
            channel_title = chat.title or "Telegram Kanal"

    # To'g'ridan-to'g'ri ID yoki @username kiritilgan bo'lsa
    if not channel_id and msg.text:
        t = msg.text.strip()
        if t.startswith("-100") or t.startswith("@"):
            channel_id = t
            channel_title = t

    if not channel_id:
        await msg.reply_text(
            "❌ **Manba aniqlanmadi!**\n\n"
            "Iltimos, kanaldan biror postni to'g'ridan-to'g'ri Forward qiling yoki kanal ID raqamini kiriting:",
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return ADD_CHANNEL

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO channels (user_id, channel_id, channel_title, is_active)
            VALUES (%s, %s, %s, TRUE)
            ON CONFLICT (channel_id) DO UPDATE SET is_active = TRUE, channel_title = EXCLUDED.channel_title
        """, (user_id, channel_id, channel_title))
        conn.commit()
        cur.close()
        conn.close()

        await msg.reply_text(
            f"🎉 **Muvaffaqiyatli ulandi!**\n\n📢 Nomi: **{channel_title}**\n🆔 ID: `{channel_id}`",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except Exception as e:
        logging.error(f"Kanal saqlash xatosi: {e}")
        await msg.reply_text("❌ Saqlashda xatolik yuz berdi.", reply_markup=get_main_keyboard(is_admin))
        return ConversationHandler.END

# 3. Kutilayotgan postlar
async def list_pending_posts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = (user_id == ADMIN_ID)
    posts = []

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT sp.id, c.channel_title, sp.post_type, sp.scheduled_time 
            FROM scheduled_posts sp
            LEFT JOIN channels c ON sp.channel_id = c.channel_id
            WHERE sp.user_id = %s AND sp.status = 'pending'
            ORDER BY sp.scheduled_time ASC
        """, (user_id,))
        posts = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        logging.error(f"Pending posts xatosi: {e}")

    if not posts:
        await update.message.reply_text(
            "📋 **Hozircha rejalashtirilgan postlar yo'q.**",
            reply_markup=get_main_keyboard(is_admin),
            parse_mode="Markdown"
        )
        return

    text = "📋 **Kutilayotgan postlar:**\n\n"
    for p in posts:
        pid, c_title, p_type, s_time = p
        title = c_title if c_title else "Kanal"
        text += f"🔹 **ID: #{pid}** | {title}\n⏰ Vaqti: `{s_time.strftime('%Y-%m-%d %H:%M')}`\n📁 Turi: {p_type}\n\n"

    await update.message.reply_text(text, reply_markup=get_main_keyboard(is_admin), parse_mode="Markdown")

# 4. Admin Panel & Statistika
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔️ Bu bo'lim faqat bot egasi uchun!")
        return

    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM users")
        total_users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM channels WHERE is_active = TRUE")
        total_channels = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'pending'")
        pending_posts = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE status = 'posted'")
        sent_posts = cur.fetchone()[0]
        cur.close()
        conn.close()

        text = (
            f"👑 **ADMIN BOSHQARUV PANELI**\n\n"
            f"👥 Jami foydalanuvchilar: **{total_users} ta**\n"
            f"📢 Ulangan kanallar/guruhlar: **{total_channels} ta**\n"
            f"⏳ Kutilayotgan postlar: **{pending_posts} ta**\n"
            f"✅ Kanalga chiqqan postlar: **{sent_posts} ta**\n"
        )
        await update.message.reply_text(text, reply_markup=get_main_keyboard(True), parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Admin panel xatosi: {e}")
        await update.message.reply_text("❌ Ma'lumotlarni yuklashda xatolik bo'ldi.")

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

def main():
    threading.Thread(target=start_server, daemon=True).start()
    init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    new_post_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("Yangi post"), start_new_post),
            CommandHandler("newpost", start_new_post)
        ],
        states={
            CHOOSE_CHANNEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, channel_chosen)],
            CHOOSE_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, type_chosen)],
            GET_CONTENT: [
                MessageHandler(filters.PHOTO | (filters.TEXT & ~filters.COMMAND), content_received)
            ],
            GET_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, time_received)],
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
            MessageHandler(filters.Regex("(Asosiy|Bekor)"), cancel_handler)
        ],
        allow_reentry=True
    )

    add_channel_conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("Kanal"), start_add_channel)
        ],
        states={
            ADD_CHANNEL: [MessageHandler(filters.ALL & ~filters.COMMAND, channel_received)]
        },
        fallbacks=[
            CommandHandler("start", start),
            CommandHandler("cancel", cancel_handler),
            MessageHandler(filters.Regex("(Asosiy|Bekor)"), cancel_handler)
        ],
        allow_reentry=True
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Regex("Kanallar va Guruhlar"), channels_menu))
    app.add_handler(MessageHandler(filters.Regex("Kutilayotgan postlar"), list_pending_posts))
    app.add_handler(MessageHandler(filters.Regex("Asosiy menyu"), start))
    app.add_handler(MessageHandler(filters.Regex("(Admin Panel|Statistika)"), admin_panel))

    app.add_handler(new_post_conv)
    app.add_handler(add_channel_conv)

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, unknown))

    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_and_send_posts, 'interval', minutes=1, args=[app.bot])
    scheduler.start()

    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
