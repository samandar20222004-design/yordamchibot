import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def health_check_handler(request):
    """UptimeRobot va Render so'rovlariga 200 OK javob qaytaradi."""
    return web.Response(text="OK - PostAssist Bot is running!", status=200)

async def start_web_server():
    """Doimiy ishlashi uchun veb-server (aiohttp)."""
    app = web.Application()
    
    # Faqat add_get yetarli (u GET va HEAD metodlarini avtomatik qo'llab-quvvatlaydi)
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server muvaffaqiyatli ishga tushdi: 0.0.0.0:{port}")
    return runner
