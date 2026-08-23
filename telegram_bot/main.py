import os
import asyncio
import logging
from aiohttp import web
from telegram.ext import ApplicationBuilder

from config import BOT_TOKEN
from database import init_db
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# UptimeRobot signallarini qabul qilish uchun veb-server (ping)
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
        logger.error("BOT_TOKEN topilmadi! Render Environment Variables qismini tekshiring.")
        return

    # 1. Ma'lumotlar bazasini ishga tushirish
    init_db()

    # 2. Bot ilovasini qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # 3. Mavjud barcha handlerlarni avtomatik ro'yxatdan o'tkazish
    try:
        import handlers.start as h_start
        if hasattr(h_start, "register_handlers"):
            h_start.register_handlers(application)
    except Exception as e:
        logger.warning(f"Start handler ulanmadi: {e}")

    try:
        import handlers.admin as h_admin
        if hasattr(h_admin, "register_handlers"):
            h_admin.register_handlers(application)
    except Exception as e:
        logger.warning(f"Admin handler ulanmadi: {e}")

    try:
        import handlers.new_post as h_new_post
        if hasattr(h_new_post, "new_post_conv_handler"):
            application.add_handler(h_new_post.new_post_conv_handler)
        elif hasattr(h_new_post, "register_handlers"):
            h_new_post.register_handlers(application)
    except Exception as e:
        logger.warning(f"New post handler ulanmadi: {e}")

    try:
        import handlers.list_posts as h_list
        if hasattr(h_list, "register_handlers"):
            h_list.register_handlers(application)
    except Exception as e:
        logger.warning(f"List posts handler ulanmadi: {e}")

    try:
        import handlers.delete_post as h_del
        if hasattr(h_del, "delete_post_conv_handler"):
            application.add_handler(h_del.delete_post_conv_handler)
        elif hasattr(h_del, "register_handlers"):
            h_del.register_handlers(application)
    except Exception as e:
        logger.warning(f"Delete post handler ulanmadi: {e}")

    # 4. Rejalashtiruvchini (Scheduler) ulash
    start_scheduler(application)

    # 5. Veb-serverni fonda ishga tushirish
    await run_web_server()

    # 6. Botni ishga tushirish
    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    logger.info("Bot Telegram xabarlarini muvaffaqiyatli qabul qilmoqda!")

    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
