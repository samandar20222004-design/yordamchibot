import os
import asyncio
import logging
from threading import Thread
from aiohttp import web
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
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

# 1. UptimeRobot uchun veb-serverni alohida oqimda ishga tushirish (xatoliksiz)
async def handle_ping(request):
    return web.Response(text="Bot 24/7 faol ishlamoqda!")

def start_background_web_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    loop.run_until_complete(runner.setup())
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    loop.run_until_complete(site.start())
    logger.info(f"Veb-server {port}-portda ishga tushdi.")
    loop.run_forever()

# Barcha noma'lum tugma bosishlariga javob beruvchi universal funksiya
async def universal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    logger.info(f"Tugma bosildi: {data}")
    # Tugma ma'lumotiga qarab tegishli handlerga yo'naltirish

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN topilmadi!")
        return

    # Bazani ishga tushirish
    init_db()

    # Veb-serverni fonda yoqish
    Thread(target=start_background_web_server, daemon=True).start()

    # Bot ilovasini qurish
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Conversation handlerlarni birinchi bo'lib ulash
    try:
        import handlers.new_post as h_new_post
        if hasattr(h_new_post, "new_post_conv_handler"):
            application.add_handler(h_new_post.new_post_conv_handler)
    except Exception as e:
        logger.warning(f"New post: {e}")

    try:
        import handlers.delete_post as h_del
        if hasattr(h_del, "delete_post_conv_handler"):
            application.add_handler(h_del.delete_post_conv_handler)
    except Exception as e:
        logger.warning(f"Delete post: {e}")

    # Barcha modullardagi register_handlers funksiyalarini ulash
    modules = ["handlers.start", "handlers.admin", "handlers.list_posts", "handlers.new_post", "handlers.delete_post"]
    for mod_name in modules:
        try:
            mod = __import__(mod_name, fromlist=["register_handlers"])
            if hasattr(mod, "register_handlers"):
                mod.register_handlers(application)
        except Exception as e:
            logger.warning(f"{mod_name} yuklanmadi: {e}")

    # Tugmalar uchun universal handler
    application.add_handler(CallbackQueryHandler(universal_callback))

    # Scheduler'ni ulash
    start_scheduler(application)

    # Botni barqaror rejimda doimiy yurgazish
    logger.info("Bot ishga tushdi va to'liq rejimda ishlamoqda...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
