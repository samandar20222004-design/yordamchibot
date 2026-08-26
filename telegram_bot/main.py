import asyncio
from datetime import datetime
import pytz
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE, PORT
from database import (
    init_db,
    add_user,
    add_channel,
    get_user_channels,
    delete_channel,
    save_scheduled_post,
    get_pending_posts,
    delete_scheduled_post
)
from scheduler import scheduler, schedule_post_job

# Keep-alive Web Server
async def handle_ping(request):
    return web.Response(text="PostAssistrobot faol va ishlamoqda!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    app.router.add_get("/ping", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Keep-alive veb server {PORT}-portda ishga tushdi.")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "", user.full_name or "")
    
    keyboard = [
        [InlineKeyboardButton("📢 Kanallarim", callback_data="my_channels"), InlineKeyboardButton("➕ Kanal ulash", callback_data="add_channel")],
        [InlineKeyboardButton("📋 Rejalashtirilgan postlar", callback_data="list_posts")],
        [InlineKeyboardButton("📝 Tugmali post yaratish", callback_data="create_btn_post")]
    ]
    
    welcome_text = (
        f"Assalomu alaykum, <b>{user.full_name}</b>!\n\n"
        "🤖 <b>PostAssistrobot</b> — kanallarga postlarni rejalashtirish va professional postlar yaratish tizimiga xush kelibsiz.\n\n"
        "Boshqaruv uchun quyidagi tugmalardan foydalaning:"
    )
    await update.message.reply_text(welcome_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def handle_channel_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Kanaldan forward qilingan xabarni tutib kanalni ro'yxatga olish
    if update.message.forward_from_chat and update.message.forward_from_chat.type == "channel":
        chat = update.message.forward_from_chat
        add_channel(chat.id, update.effective_user.id, chat.title, chat.username or "")
        await update.message.reply_text(f"✅ Kanal muvaffaqiyatli ulandi:\n<b>{chat.title}</b> (ID: <code>{chat.id}</code>)", parse_mode="HTML")

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "my_channels":
        channels = get_user_channels(user_id)
        if not channels:
            await query.edit_message_text("Sizda hali ulangan kanallar yo'q.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Kanal ulash", callback_data="add_channel")]]))
            return
        
        msg = "📢 <b>Ulangan kanallaringiz:</b>\n\n"
        keyboard = []
        for ch in channels:
            msg += f"• <b>{ch['title']}</b> (@{ch['username'] if ch['username'] else ch['channel_id']})\n"
            keyboard.append([InlineKeyboardButton(f"❌ O'chirish: {ch['title'][:15]}", callback_data=f"delchan_{ch['channel_id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("delchan_"):
        chan_id = int(data.split("_")[1])
        delete_channel(chan_id, user_id)
        await query.edit_message_text("✅ Kanal muvaffaqiyatli uzildi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Kanallarga qaytish", callback_data="my_channels")]]))

    elif data == "list_posts":
        posts = get_pending_posts(user_id)
        if not posts:
            await query.edit_message_text("Sizda hozircha kutilayotgan postlar yo'q.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")]]))
            return

        msg = "📋 <b>Rejalashtirilgan postlaringiz:</b>\n\n"
        keyboard = []
        for p in posts:
            time_str = p['scheduled_time'].strftime("%Y-%m-%d %H:%M")
            msg += f"🆔 #{p['id']} | Vaqti: <b>{time_str}</b>\n"
            keyboard.append([InlineKeyboardButton(f"❌ Bekor qilish #{p['id']}", callback_data=f"delpost_{p['id']}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Asosiy menyu", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

    elif data.startswith("delpost_"):
        post_id = int(data.split("_")[1])
        delete_scheduled_post(post_id, user_id)
        try:
            scheduler.remove_job(f"post_{post_id}")
        except Exception:
            pass
        await query.edit_message_text(f"✅ #{post_id} raqamli post bekor qilindi.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Postlar ro'yxatiga", callback_data="list_posts")]]))

    elif data == "main_menu":
        keyboard = [
            [InlineKeyboardButton("📢 Kanallarim", callback_data="my_channels"), InlineKeyboardButton("➕ Kanal ulash", callback_data="add_channel")],
            [InlineKeyboardButton("📋 Rejalashtirilgan postlar", callback_data="list_posts")],
            [InlineKeyboardButton("📝 Tugmali post yaratish", callback_data="create_btn_post")]
        ]
        await query.edit_message_text("🤖 <b>Asosiy menyu:</b>", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

def main():
    init_db()
    
    # Scheduler ishga tushirish
    scheduler.start()
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.FORWARDED, handle_channel_forward))
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # Keep-alive serverni fon rejimida yoqish
    loop = asyncio.get_event_loop()
    loop.create_task(start_web_server())
    
    print("PostAssistrobot muvaffaqiyatli ishga tushdi!")
    app.run_polling()

if __name__ == "__main__":
    main()
