import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def handle_ping(request):
    return web.Response(text="Bot is running OK", status=200)

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/healthz', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server 0.0.0.0:{port} portida ishlamoqda.")
