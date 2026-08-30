import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def health_check_handler(request):
    # Render/UptimeRobot uchun yengil, tashqi servisga bog'liq bo'lmagan health-check.
    return web.json_response({"status": "ok", "service": "PostAssist Bot"}, status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server muvaffaqiyatli ishga tushdi: 0.0.0.0:{port}")
    return runner
