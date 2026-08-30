import os
import asyncio
import logging
from datetime import datetime
import pytz
from aiohttp import web
import database as db

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")
START_TIME = datetime.now(tashkent_tz)


async def health_live_handler(request):
    """Liveness: bot jarayoni ishlayotganini bildiradi (doim 200)."""
    uptime = (datetime.now(tashkent_tz) - START_TIME).total_seconds()
    return web.json_response(
        {"status": "ok", "service": "PostAssist Bot", "uptime_seconds": int(uptime)},
        status=200,
    )


async def health_ready_handler(request):
    """Readiness: bot ishlashga tayyor (baza bilan aloqa mavjud) yoki yo'q (503)."""
    # DB tekshiruvi event loop'ni bloklamasligi uchun thread'da bajariladi
    db_ok = await asyncio.to_thread(db.ping_db)
    if db_ok:
        return web.json_response({"status": "ready", "database": "ok"}, status=200)
    return web.json_response({"status": "not_ready", "database": "error"}, status=503)


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_live_handler)
    app.router.add_get("/health", health_live_handler)
    app.router.add_get("/health/live", health_live_handler)
    app.router.add_get("/health/ready", health_ready_handler)

    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server muvaffaqiyatli ishga tushdi: 0.0.0.0:{port}")
    return runner
