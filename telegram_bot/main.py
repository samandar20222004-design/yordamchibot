import asyncio
from contextlib import asynccontextmanager
import logging
import signal
import sys
import pytz  # noqa: F401 — vaqt zonasi bilan ishlovchi modullar uchun saqlanadi
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, Application
from telegram import BotCommand
from config import BOT_TOKEN
from utils.telegram_delivery import create_safe_bot
import database as db
from handlers import register_all_handlers
from scheduler import (
    check_and_send_posts,
    check_and_delete_expired_posts,
    cleanup_old_data_job,
    cleanup_old_records_job,
    poll_content_sources_job,
    weekly_channel_reports_job,
    recover_on_startup,
    subscription_sweep_job,
    tashkent_tz,
    TIMEZONE_NAME,
    now_tashkent,
)
from utils.web_server import start_web_server
from utils.ai_agent import close_ai_session, reload_runtime_params
from utils.helpers import (
    check_global_flood, check_rate_limit, is_duplicate_message, is_callback_throttled,
)
from handlers.error_handler import (
    global_error_handler,
    register_error_handlers,
)
from services import health_service
from services import lifecycle_service as lifecycle
from services.cleanup_service import (
    CLEANUP_CRON_HOUR,
    CLEANUP_CRON_MINUTE,
    CLEANUP_JOB_ID,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
# 11-bosqich (P0): basicConfig yaratgan handler'ga ham maxfiylik filtri —
# bot token / DB parol / karta raqami / API kalit loglarga tushmaydi.
try:
    from utils.sentry_scrubber import install_logging_scrubber
    install_logging_scrubber()
except Exception:  # pragma: no cover
    pass
logger = logging.getLogger(__name__)
# ⏰ Vaqt zonasi YAGONA manbadan (scheduler.tashkent_tz) olinadi — bot,
# APScheduler va DB hisob-kitoblari hech qachon ajralib ketmasligi uchun.


class UpdateLockManager:
    """Per-user / per-chat lock menejeri.

    concurrent_updates=True bilan ishlaganda bir xil foydalanuvchi/chatdan
    kelgan update'lar bir vaqtda ConversationHandler va context.user_data'ni
    o'zgartirib race condition keltirib chiqarmasligi uchun navbat bilan (seriyali)
    bajariladi, lekin turli foydalanuvchilar parallel ravishda ishlayveradi.

    Xotira sizib ketmasligi (leak-free) uchun faoliyat tugagach
    foydalanilmagan lock'lar darhol tozalanadi.
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._counts: dict[str, int] = {}
        self._meta_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: str | None):
        if not key:
            yield
            return

        async with self._meta_lock:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
                self._counts[key] = 0
            self._counts[key] += 1
            user_lock = self._locks[key]

        async with user_lock:
            try:
                yield
            finally:
                async with self._meta_lock:
                    self._counts[key] -= 1
                    if self._counts[key] <= 0:
                        self._locks.pop(key, None)
                        self._counts.pop(key, None)


def get_update_lock_key(update) -> str | None:
    """Update uchun yagona lock kaliti (per-user / per-chat)."""
    if update is None:
        return None
    user = getattr(update, "effective_user", None)
    if user is not None and getattr(user, "id", None) is not None:
        return f"user:{user.id}"
    chat = getattr(update, "effective_chat", None)
    if chat is not None and getattr(chat, "id", None) is not None:
        return f"chat:{chat.id}"
    return None


class GuardedApplication(Application):
    """Hujum/ortiqcha yuklama himoyasi va per-user concurrency locking qo'shilgan Application.

    Har bir update process_update() orqali o'tadi:
    1. Per-user / per-chat lock: bir foydalanuvchining parallel so'rovlari (double click / race condition)
       seriyalashtiriladi, shunda ConversationHandler va context.user_data kutilmagan bosqichga sakrab ketmaydi.
    2. Global flood bo'lsa — qisqa pauza (backpressure) bilan sekinlashtiramiz.
    3. Bitta foydalanuvchi 2 soniyada 20 tadan ortiq update yuborsa — tashlab yuboramiz.
    4. Bir xil xabarni 1.5 soniya ichida qayta yuborsa — tashlab yuboramiz.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock_manager = UpdateLockManager()

    async def process_update(self, update):
        lock_key = get_update_lock_key(update)
        async with self._lock_manager.lock(lock_key):
            try:
                # 1) Global flood — botni to'xtatib qo'ymasdan, yukni sekinlashtiramiz
                if check_global_flood():
                    await asyncio.sleep(0.4)

                # 1b) Callback 1.5s debounce — tugma spam / double-tap
                query = getattr(update, "callback_query", None)
                user = getattr(update, "effective_user", None)
                if query is not None and user is not None:
                    if is_callback_throttled(user.id):
                        await self._answer_callback_wait(update)
                        return None

                # 2) Foydalanuvchi bo'yicha burst (hujum/flood)
                if user is not None:
                    blocked, _ = check_rate_limit(user.id, max_requests=20, window_seconds=2.0)
                    if blocked:
                        # Update tashlab yuboriladi, lekin callback bo'lsa tugma
                        # "yuklanmoqda" holatida muzlab qolmasligi uchun darhol
                        # javob beramiz (jim chiqish — tugmalarni qotiradi).
                        await self._answer_rate_limited(update)
                        return None

                    # 3) Dublikat xabar (avtomatik qayta yuborish hujumi)
                    msg = getattr(update, "effective_message", None)
                    text = getattr(msg, "text", None) if msg else None
                    if text and is_duplicate_message(user.id, text):
                        await self._answer_rate_limited(update)
                        return None
            except Exception:
                logger.exception("Guard himoyasida xatolik — update davom ettirilmoqda")

            return await super().process_update(update)

    @staticmethod
    async def _answer_rate_limited(update):
        """Rate-limit/dublikat tufayli tashlab yuborilgan callback'ga darhol
        javob beradi — aks holda Telegram tugmani 'yuklanmoqda' holatida
        qoldiradi (tugma qotib qoladi)."""
        await GuardedApplication._answer_callback_wait(update)

    @staticmethod
    async def _answer_callback_wait(update):
        query = getattr(update, "callback_query", None)
        if query is not None:
            try:
                # 🌐 Throttle toast'i foydalanuvchi tilida (uz/ru/en). Til
                # keshlangan DB o'quvi orqali olinadi (get_user_language —
                # TTL keshli, DB uzilganda 'uz' ga qaytadi).
                lang = "uz"
                user = getattr(update, "effective_user", None)
                if user is not None and getattr(user, "id", None):
                    try:
                        import database as _db
                        lang = await _db.run_db(_db.get_user_language, user.id)
                    except Exception:
                        lang = "uz"
                from locales.translations import get_text
                await query.answer(
                    get_text("sys_wait_short", lang), show_alert=False
                )
            except Exception:
                pass


# Orqaga mos (backward-compatible) nom: asosiy mantiq endi
# ``handlers/error_handler.py`` modulidagi ``global_error_handler`` da.
# Kafolotlar o'zgarmagan:
#   * foydalanuvchiga tilga mos (uz/ru/en) ``sys_unexpected_error``
#     xushmuomala xabari yuboriladi — Python traceback, SQL yoki boshqa
#     ichki xatolik tafsilotlari HECH QACHON ko'rsatilmaydi;
#   * to'liq tafsilot (user_id, handler_name, exception, traceback)
#     strukturalli log formatida qayd etiladi;
#   * kritik xatolar (DB down, fatal) logda [CRITICAL_HEALTH] bilan
#     ajratilib, admin audit jurnaliga best-effort yoziladi.
error_handler = global_error_handler


async def set_bot_commands(application):
    commands = [
        BotCommand("start", "Bosh menyu"),
        BotCommand("newpost", "Yangi post rejalashtirish"),
        BotCommand("imagepost", "Rasm orqali post yaratish"),
        BotCommand("profile", "Kabinet va sozlamalar"),
        BotCommand("help", "Yordam va qo'llanma"),
        BotCommand("channel_advice", "Kanal haftalik hisoboti"),
        BotCommand("cancel", "Amalni bekor qilish"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Telegram Menyu buyruqlari muvaffaqiyatli o'rnatildi.")
    except Exception as e:
        logger.warning(f"Menyu buyruqlarini o'rnatishda xatolik: {e}")


# ============================================================
# 🛑 GRACEFUL SHUTDOWN (PostAssist V2 — 9-bosqich)
# ------------------------------------------------------------
# SIGINT (Ctrl+C) va SIGTERM (Render deploy / systemctl stop / docker stop)
# signallari event loop ichida ushlanadi va yopilish TARTIB BILAN boradi:
#   1) lifecycle.request_shutdown()  — yangi ishlar qabul qilinmaydi
#      (scheduler workerlari navbatdan yangi post olmaydi);
#   2) updater.stop()                — Telegramdan yangi update olish to'xtaydi;
#   3) scheduler.pause()             — navbatdagi joblar ishga tushmaydi,
#      ayni paytda bajarilayotgan yuborishlar davom etadi;
#   4) lifecycle.wait_for_inflight() — faol postlarga tugallanish uchun
#      5–10 soniya (SHUTDOWN_GRACE_SECONDS) beriladi; ular BEKOR QILINMAYDI;
#   5) application.stop()/shutdown() — PTB navbatdagi update'larni tugatadi;
#   6) scheduler.shutdown(wait=False), web server cleanup;
#   7) db.close_pool() + close_ai_session() — Neon pool va aiohttp
#      sessiyalari toza yopiladi;
#   8) jarayon exit code 0 bilan chiqadi.
# Ikkinchi signal (masalan, ikki marta Ctrl+C) yopilishni qayta boshlamaydi.
# ============================================================
SHUTDOWN_SIGNALS = tuple(
    sig for sig in (getattr(signal, "SIGINT", None), getattr(signal, "SIGTERM", None))
    if sig is not None
)


def install_signal_handlers(loop, stop_event: asyncio.Event) -> list:
    """SIGINT/SIGTERM uchun asinxron shutdown handlerlarini o'rnatadi.

    Handler event loop thread'ida ishlaydi (``loop.add_signal_handler``), shu
    sababli ``KeyboardInterrupt`` istisnosi ``await`` o'rtasida "portlab"
    resurslarni yarim yo'lda qoldirmaydi. Windows/cheklangan muhitda
    ``add_signal_handler`` bo'lmasa ``signal.signal`` fallback ishlatiladi.
    Qaytadi: muvaffaqiyatli o'rnatilgan signallar ro'yxati.
    """
    installed = []

    def _on_signal(sig):
        name = getattr(sig, "name", str(sig))
        if lifecycle.request_shutdown(name):
            logger.warning("Signal %s qabul qilindi — graceful shutdown boshlanmoqda.", name)
            loop.call_soon_threadsafe(stop_event.set)
        else:
            logger.warning("Signal %s takror keldi — yopilish allaqachon davom etmoqda.", name)

    for sig in SHUTDOWN_SIGNALS:
        try:
            loop.add_signal_handler(sig, _on_signal, sig)
            installed.append(sig)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                signal.signal(sig, lambda s, f, _sig=sig: _on_signal(_sig))
                installed.append(sig)
            except (ValueError, OSError):
                logger.debug("Signal handler o'rnatilmadi: %s", sig)
    return installed


def remove_signal_handlers(loop, installed) -> None:
    for sig in installed or ():
        try:
            loop.remove_signal_handler(sig)
        except (NotImplementedError, RuntimeError, ValueError):
            pass


async def graceful_shutdown(application=None, scheduler=None, web_runner=None,
                            grace_seconds: float = None) -> dict:
    """Barcha komponentlarni TARTIB bilan, xatolardan himoyalangan holda yopadi.

    Har bir bosqich alohida ``try/except`` da — bittasi xato bersa keyingilari
    baribir bajariladi (DB pool va aiohttp sessiyalari doim yopiladi).
    Qaytadi: bosqichlar hisoboti (testlar/diagnostika uchun).
    """
    report = {"steps": [], "errors": []}

    def _step(name, ok=True, extra=None):
        report["steps"].append(name)
        if not ok:
            report["errors"].append(name)
        if extra is not None:
            report[name] = extra

    lifecycle.request_shutdown("graceful_shutdown")

    # 1) Telegramdan yangi update olishni to'xtatamiz.
    updater = getattr(application, "updater", None) if application is not None else None
    if updater is not None and getattr(updater, "running", False):
        try:
            await updater.stop()
            _step("updater_stopped")
        except Exception:
            logger.exception("Updater'ni to'xtatishda xatolik")
            _step("updater_stopped", ok=False)

    # 2) Scheduler: navbatdagi joblar ishga tushmaydi (pause), faol job
    #    davom etadi. Yopish (shutdown) faol vazifalar tugagach.
    if scheduler is not None:
        try:
            if getattr(scheduler, "running", False):
                scheduler.pause()
            _step("scheduler_paused")
        except Exception:
            logger.exception("Scheduler'ni pauza qilishda xatolik")
            _step("scheduler_paused", ok=False)

    # 3) Faol vazifalarga tugallanish uchun 5–10 soniya (bekor qilinmaydi).
    try:
        drain = await lifecycle.wait_for_inflight(grace_seconds)
        _step("inflight_drained", ok=drain.get("drained", False), extra=drain)
    except Exception:
        logger.exception("Faol vazifalarni kutishda xatolik")
        _step("inflight_drained", ok=False)

    # 4) PTB application: navbatdagi update'lar ishlanadi, so'ng yopiladi.
    if application is not None:
        try:
            if getattr(application, "running", False):
                await application.stop()
            _step("application_stopped")
        except Exception:
            logger.exception("Application.stop() xatolik")
            _step("application_stopped", ok=False)
        try:
            await application.shutdown()
            _step("application_shutdown")
        except Exception:
            logger.exception("Application.shutdown() xatolik")
            _step("application_shutdown", ok=False)

    # 5) Scheduler'ni to'liq yopamiz (kutmasdan — faol vazifalar allaqachon
    #    kutildi; qolganlari DB'da 'processing' bo'lib stale-recovery'ga tushadi).
    if scheduler is not None:
        try:
            if getattr(scheduler, "running", False) or getattr(scheduler, "state", 0):
                scheduler.shutdown(wait=False)
            _step("scheduler_shutdown")
        except Exception:
            logger.exception("Scheduler'ni yopishda xatolik")
            _step("scheduler_shutdown", ok=False)

    # 6) Web server (health endpointlari).
    if web_runner is not None:
        try:
            await web_runner.cleanup()
            _step("web_server_closed")
        except Exception:
            logger.exception("Web serverni yopishda xatolik")
            _step("web_server_closed", ok=False)

    # 7) Neon DB pool va aiohttp ClientSession'lar — HAR DOIM yopiladi.
    try:
        db.close_pool()
        _step("db_pool_closed")
    except Exception:
        logger.exception("DB pool'ni yopishda xatolik")
        _step("db_pool_closed", ok=False)
    try:
        await close_ai_session()
        _step("ai_session_closed")
    except Exception:
        logger.exception("AI (aiohttp) sessiyasini yopishda xatolik")
        _step("ai_session_closed", ok=False)

    report["clean"] = not report["errors"]
    logger.info(
        "Bot to'liq to'xtatildi va barcha resurslar yopildi (bosqichlar: %s%s).",
        ", ".join(report["steps"]),
        f"; xatolar: {report['errors']}" if report["errors"] else "",
    )
    return report


async def main():
    db.init_db()

    # 11-bosqich (P0) restart recovery: avvalgi jarayon 'processing' da
    # qoldirgan postlar — Telegramga chiqqanlari 'posted' (qayta yuborilmaydi),
    # UNKNOWN_DELIVERY bo'lganlari 'unknown', qolganlari 'pending'.
    await recover_on_startup()

    # Admin panelda o'zgartirilgan AI parametrlarini ishga tushirishda yuklaymiz.
    try:
        await reload_runtime_params()
    except Exception:
        logger.exception("AI runtime parametrlarni yuklashda xatolik (defaultlar ishlatiladi)")

    web_runner = None
    scheduler = None
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals = install_signal_handlers(loop, stop_event)
    application = (
        ApplicationBuilder()
        .bot(create_safe_bot(BOT_TOKEN))
        .application_class(GuardedApplication)
        .concurrent_updates(True)
        # SafeHTMLBot applies the SSOT sanitizer to all HTML sends/edits.
        # Network timeout/pool settings are kept in create_safe_bot().
        .build()
    )

    # Kutilmagan xatoliklarni ushlash — universal global error handler
    # (handlers/error_handler.py): strukturalli log + tilga mos xushmuomala
    # foydalanuvchi xabari + kritik xatolarni auditga yozish.
    register_error_handlers(application)

    register_all_handlers(application)
    web_runner = await start_web_server()

    # Scheduler: har bir ish (job) maks. 1 marta parallel ishlaydi (max_instances=1),
    # o'tkazib yuborilgan ishlar birlashtiriladi (coalesce), va bot qayta
    # ishga tushganda kechikkan postlar darhol tekshiriladi (next_run_time).
    # MUHIM: timezone HAR JOYDA aniq ko'rsatiladi — scheduler darajasida ham,
    # har bir trigger darajasida ham. Render/Docker server UTC'da ishlaganda
    # ham cron/interval triggerlari Toshkent vaqti (UTC+5) bo'yicha hisoblanadi.
    scheduler = AsyncIOScheduler(
        timezone=tashkent_tz,
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
    )
    scheduler.add_job(
        check_and_send_posts, 'interval', minutes=1, args=[application.bot],
        id="check_and_send_posts", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=300,
        next_run_time=now_tashkent(),
    )
    scheduler.add_job(
        check_and_delete_expired_posts, 'interval', minutes=1, args=[application.bot],
        id="check_and_delete_expired_posts", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=300,
        next_run_time=now_tashkent(),
    )
    scheduler.add_job(
        cleanup_old_data_job, 'cron', hour="*/6", minute=0,
        id="cleanup_old_data", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    # 3-BOSQICH (P1): muddati o'tgan PRO/enterprise obunalarni avtomatik FREE ga
    # tushirish — har 15 daqiqada bitta yengil UPDATE (index-friendly).
    scheduler.add_job(
        subscription_sweep_job, 'interval', minutes=15,
        id="subscription_sweep", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=300,
    )
    # 📥 PHASE D (2/2): RSS/ATOM manbalarini avtomatik tekshirish — har 15
    # daqiqada vaqti kelgan (``interval_minutes``) manbalar o'qiladi, yangi
    # elementlardan qoralama tayyorlanadi (dublikat QAYTA ishlanmaydi) va
    # autopublish yoqilgan bo'lsa navbatga yoziladi. Job hech qachon istisno
    # tashlamaydi (scheduler barqarorligi).
    scheduler.add_job(
        poll_content_sources_job, 'interval', minutes=15, args=[application.bot],
        id="poll_content_sources", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=300,
    )
    # PHASE E — ixcham haftalik hisobot: har dushanba 09:00 (Toshkent),
    # faqat kanal egasining shaxsiy chatiga yuboriladi.
    scheduler.add_job(
        weekly_channel_reports_job, 'cron', day_of_week='mon', hour=9, minute=0,
        args=[application.bot], id="weekly_channel_reports", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    # 9-bosqich: kunlik paketli tozalash worker'i — har 24 soatda 1 marta,
    # kechasi soat 03:00 (Toshkent). LIMIT 1000 paketlar, har paket alohida
    # tranzaksiya (services/cleanup_service.py). misfire_grace_time=6h —
    # bot 03:00 da o'chiq bo'lsa, ertalab ishga tushganda bir marta bajariladi.
    scheduler.add_job(
        cleanup_old_records_job, 'cron',
        hour=CLEANUP_CRON_HOUR, minute=CLEANUP_CRON_MINUTE,
        id=CLEANUP_JOB_ID, timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )

    try:
        await application.initialize()
        await application.start()
        await set_bot_commands(application)
        await application.updater.start_polling(drop_pending_updates=True)

        # Scheduler'ni app to'liq ishga tushgandan keyin boshlaymiz —
        # shunda birinchi ishlash ham to'liq tayyor muhitda bo'ladi.
        scheduler.start()
        # 🩺 Health service: scheduler/application instansiyalarini ro'yxatga
        # olish + uptime nolini qo'yish — /health buyrug'i shu ma'lumotlarni
        # ko'rsatadi (services/health_service.py).
        health_service.register_application(application)
        health_service.register_scheduler(scheduler)
        health_service.mark_bot_started()
        logger.info(
            "Scheduler started (TZ=%s): postlar har 1 daqiqada, DB tozalash har 6 soatda, "
            "kunlik paketli tozalash %02d:%02d da.",
            TIMEZONE_NAME, CLEANUP_CRON_HOUR, CLEANUP_CRON_MINUTE,
        )
        logger.info("Bot muvaffaqiyatli ishga tushdi.")

        # Signal kelguncha kutamiz (SIGINT/SIGTERM → stop_event).
        await stop_event.wait()
        logger.info("Bot to'xtatilmoqda (%s)...", lifecycle.shutdown_reason() or "signal")
    except (KeyboardInterrupt, SystemExit):
        # Signal handler o'rnatilmagan muhit (masalan, Windows) — eski yo'l.
        lifecycle.request_shutdown("KeyboardInterrupt")
        logger.info("Bot to'xtatilmoqda...")
    finally:
        # Ishga tushirish bosqichida xatolik bo'lgan taqdirda ham
        # ochilgan resurslar yopilishi kerak (shuning uchun None-tekshiruv).
        # graceful_shutdown har bosqichni alohida himoyalaydi — asl xato
        # yashirilmaydi, DB pool va aiohttp sessiyalari DOIM yopiladi.
        remove_signal_handlers(loop, installed_signals)
        await graceful_shutdown(application, scheduler, web_runner)


def run() -> int:
    """Botni ishga tushiradi; toza yopilishda 0 qaytaradi (exit code)."""
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        # Signal handlerlar o'rnatilgan bo'lsa bu yerga kelinmaydi; fallback
        # muhitda ham yopilish main() ning finally blokida tugallangan.
        pass
    return 0


if __name__ == "__main__":
    sys.exit(run())
