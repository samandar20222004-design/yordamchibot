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

async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi!")
        return

    # 1. Bazani sozlash
    init_db()

    # 2. Bot ilovasini qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3. Conversation Handlerlarni (Post yaratish va o'chirish jarayonlari) birinchi bo'lib ulash
    try:
        import handlers.new_post as h_new_post
        if hasattr(h_new_post, "new_post_conv_handler"):
            application.add_handler(h_new_post.new_post_conv_handler)
    except Exception as e:
        logger.warning(f"New post handler xatosi: {e}")

    try:
        import handlers.delete_post as h_del
        if hasattr(h_del, "delete_post_conv_handler"):
            application.add_handler(h_del.delete_post_conv_handler)
    except Exception as e:
        logger.warning(f"Delete post handler xatosi: {e}")

    # 4. Handler fayllaridagi register_handlers funksiyalarini ulash
    for module_name in ["handlers.start", "handlers.admin", "handlers.list_posts", "handlers.new_post", "handlers.delete_post"]:
        try:
            mod = __import__(module_name, fromlist=["register_handlers"])
            if hasattr(mod, "register_handlers"):
                mod.register_handlers(application)
        except Exception as e:
            logger.warning(f"{module_name} ro'yxatga olinmadi: {e}")

    # 5. Tugmalar (CallbackQuery) uchun barcha callback funksiyalarni to'liq ulash
    try:
        import handlers.admin as h_admin
        for attr in ["admin_callback", "button_click", "handle_callback", "admin_button_callback"]:
            if hasattr(h_admin, attr):
                application.add_handler(CallbackQueryHandler(getattr(h_admin, attr)))
    except Exception as e:
        logger.warning(f"Admin callback xatosi: {e}")

    try:
        import handlers.start as h_start
        for attr in ["start_callback", "menu_callback", "handle_callback"]:
            if hasattr(h_start, attr):
                application.add_handler(CallbackQueryHandler(getattr(h_start, attr)))
    except Exception as e:
        logger.warning(f"Start callback xatosi: {e}")

    # 6. Buyruqlar uchun zaxira (agar alohida funksiya bo'lsa)
    try:
        import handlers.start as h_start
        if hasattr(h_start, "start"):
            application.add_handler(CommandHandler("start", h_start.start))
        elif hasattr(h_start, "start_handler") and not isinstance(h_start.start_handler, CommandHandler):
            application.add_handler(CommandHandler("start", h_start.start_handler))
    except Exception as e:
        pass

    try:
        import handlers.admin as h_admin
        if hasattr(h_admin, "admin_panel"):
            application.add_handler(CommandHandler("admin", h_admin.admin_panel))
        elif hasattr(h_admin, "admin_panel_handler") and not isinstance(h_admin.admin_panel_handler, CommandHandler):
            application.add_handler(CommandHandler("admin", h_admin.admin_panel_handler))
    except Exception as e:
        pass

    try:
        import handlers.list_posts as h_list
        if hasattr(h_list, "list_posts"):
            application.add_handler(CommandHandler("posts", h_list.list_posts))
        elif hasattr(h_list, "list_posts_handler") and not isinstance(h_list.list_posts_handler, CommandHandler):
            application.add_handler(CommandHandler("posts", h_list.list_posts_handler))
    except Exception as e:
        pass

    # 7. Rejalashtiruvchini (Scheduler) ulash
    start_scheduler(application)

    # 8. UptimeRobot uchun veb-serverni ishga tushirish
    await run_web_server()

    # 9. Botni ishga tushirish
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot tayyor! Barcha tugmalar va buyruqlar ulandi.")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
