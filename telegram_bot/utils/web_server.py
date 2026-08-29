import os
import logging
from aiohttp import web

logger = logging.getLogger(__name__)

async def health_check_handler(request):
    """Отвечает 200 OK на любые запросы от UptimeRobot и Render."""
    return web.Response(text="OK - PostAssist Bot is running!", status=200)

async def start_web_server():
    """Запуск легковесного асинхронного веб-сервера для предотвращения спящего режима."""
    app = web.Application()
    
    # Обрабатываем GET и HEAD запросы для корневого пути и /health
    app.router.add_get("/", health_check_handler)
    app.router.add_head("/", health_check_handler)
    app.router.add_get("/health", health_check_handler)
    app.router.add_head("/health", health_check_handler)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server muvaffaqiyatli ishga tushdi: 0.0.0.0:{port}")
    return runner
