import os
import asyncio
import logging
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)

from config import BOT_TOKEN
from database import init_db
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# UptimeRobot uchun veb-server
async def handle_ping(request):
    return web.Response(text="Bot 24/7 faol ishlamoqda!")

async def run_web_server():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Veb-server {port}-portda ishga tushdi.")

# Zaxira /start funksiyasi (agar handlers/start.py ulanmasa ham aniq javob beradi)
async def fallback_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name if update.effective_user else "Foydalanuvchi"
    await update.message.reply_text(
        f"Assalomu alaykum, {user_name}!\n\n"
        "🤖 Bot muvaffaqiyatli ishga tushdi va buyruqlarni qabul qilmoqda.\n\n"
        "Mavjud buyruqlar:\n"
        "/start - Botni qayta ishga tushirish\n"
        "/admin - Admin panel\n"
        "/posts - Rejalashtirilgan postlar ro'yxati"
    )

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi!")
        return

    # 1. Bazani sozlash
    init_db()

    # 2. Bot ilovasini qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3. Handlerlarni biriktirish
    attached_start = False
    try:
        import handlers.start as h_start
        for func_name in ["start_handler", "start", "start_command"]:
            if hasattr(h_start, func_name):
                func = getattr(h_start, func_name)
                if isinstance(func, CommandHandler):
                    application.add_handler(func)
                else:
                    application.add_handler(CommandHandler("start", func))
                attached_start = True
                break
        if not attached_start and hasattr(h_start, "register_handlers"):
            h_start.register_handlers(application)
            attached_start = True
    except Exception as e:
        logger.warning(f"Start handler import qilinmadi: {e}")

    # Agar fayldan ulanmasa, kafolatlangan start'ni ulash
    if not attached_start:
        application.add_handler(CommandHandler("start", fallback_start))

    # Boshqa handlerlar
    try:
        import handlers.admin as h_admin
        for func_name in ["admin_panel_handler", "admin_panel", "admin"]:
            if hasattr(h_admin, func_name):
                func = getattr(h_admin, func_name)
                if isinstance(func, CommandHandler):
                    application.add_handler(func)
                else:
                    application.add_handler(CommandHandler("admin", func))
                break
    except Exception as e:
        logger.warning(f"Admin handler: {e}")

    try:
        import handlers.new_post as h_new_post
        if hasattr(h_new_post, "new_post_conv_handler"):
            application.add_handler(h_new_post.new_post_conv_handler)
    except Exception as e:
        logger.warning(f"New post handler: {e}")

    try:
        import handlers.list_posts as h_list
        for func_name in ["list_posts_handler", "list_posts", "posts"]:
            if hasattr(h_list, func_name):
                func = getattr(h_list, func_name)
                if isinstance(func, CommandHandler):
                    application.add_handler(func)
                else:
                    application.add_handler(CommandHandler("posts", func))
                break
    except Exception as e:
        logger.warning(f"List posts handler: {e}")

    # 4. Rejalashtiruvchini ulash
    start_scheduler(application)

    # 5. Veb-serverni ishga tushirish
    await run_web_server()

    # 6. Botni xabarlarni qabul qilish rejimiga o'tkazish
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot tayyor va ishlamoqda!")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
