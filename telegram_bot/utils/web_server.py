import asyncio
import logging
from datetime import datetime
import pytz
from aiohttp import web
from config import PORT
import database as db

logger = logging.getLogger(__name__)

tashkent_tz = pytz.timezone("Asia/Tashkent")
START_TIME = datetime.now(tashkent_tz)


async def health_live_handler(request):
    """Liveness: bot jarayoni TIRIK ekanini bildiradi — DOIM 200.

    ⚠️ 1-BOSQICH: bu endpoint ``database`` modulini ICHKI OLISH ham qilmaydi
    va baza bilan UMUMAN bog'lanmaydi. Shuning uchun:

      * Render deploy tugagach DARHOL 200 oladi (init_db hali ishlamaydi);
      * Aiven/Render DB uzilsa ham bot «o'lik» deb belgilanmaydi — bu
        ``/health/ready`` ning vazifasi (unika o'lchov: process vs DB).

    Ataylab o'ldirilgan sabablar: aiohttp bilan DB so'rovi qilsak, Aiven
    cold-start yoki idle-timeout holatida ``/health/live`` ham 503 qaytarib
    turardi va Render botni to'g'ri ishlayotgan holda o'ldirardi.
    """
    uptime = (datetime.now(tashkent_tz) - START_TIME).total_seconds()
    return web.json_response(
        {"status": "live", "service": "PostAssist Bot", "uptime_seconds": int(uptime)},
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

    port = PORT
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server muvaffaqiyatli ishga tushdi: 0.0.0.0:{port}")
    return runner
