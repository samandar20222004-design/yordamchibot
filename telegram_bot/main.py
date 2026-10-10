import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlsplit
from types import SimpleNamespace
import logging
import signal
import sys
import time
import pytz  # noqa: F401 — vaqt zonasi bilan ishlovchi modullar uchun saqlanadi
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, Application
from telegram import BotCommand, Update
from config import (
    BOT_TOKEN,
    UPDATE_HANDLER_TIMEOUT_SECONDS,
    STALE_UPDATE_SECONDS,
    KEEP_ALIVE_URL,
    KEEP_ALIVE_INTERVAL_SECONDS,
    UPDATE_ADMISSION_MAX_PENDING,
    UPDATE_ADMISSION_MAX_PER_USER,
)
from utils.telegram_delivery import create_safe_bot
from utils.handler_timeout import await_with_timeout
from utils.callback_ack import schedule_early_ack, cancel_early_ack
import database as db
from handlers import register_all_handlers
from scheduler import (
    check_and_send_posts,
    check_and_delete_expired_posts,
    cleanup_old_data_job,
    cleanup_old_records_job,
    poll_content_sources_job,
    weekly_channel_reports_job,
    daily_morning_digest_job,
    uzbekistan_calendar_reminders_job,
    recover_on_startup,
    subscription_sweep_job,
    tashkent_tz,
    TIMEZONE_NAME,
    now_tashkent,
)
from utils.web_server import start_web_server
from utils.ai_agent import close_ai_session, reload_runtime_params
from utils.helpers import (
    check_global_flood, check_rate_limit, is_duplicate_message,
)
from services import cache_backend as cache_backend_svc
from middlewares.rate_limiter import RateLimitMiddleware
from middlewares.rbac import install_resource_middleware
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

from utils.silent_errors import log_silent_failure

# PHASE 10: barcha production stdout loglari JSON Lines formatida. Formatter
# bir xil timestamp/level/event/user/channel/latency/error_code maydonlarini
# chiqaradi va handlerlar secrets scrubber bilan birga o'rnatiladi.
try:
    from utils.sentry_scrubber import (
        configure_structured_logging, install_logging_scrubber,
    )
    install_logging_scrubber()
    configure_structured_logging(level=logging.INFO)
except Exception:  # pragma: no cover - xavfsiz fallback, token scrubber config'da ham bor
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.INFO,
    )
# 1-QISM (LOG XAVFSIZLIGI): httpx/httpcore har bir Telegram API so'rovini
# INFO darajasida log qiladi — so'rov URL'ida BOT TOKENI bor
# (https://api.telegram.org/bot<TOKEN>/...). Darajani WARNING ga tushirish
# va yuqoridagi scrubber-filtr birgalikda token logga tushishini to'sadi.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
# ⏰ Vaqt zonasi YAGONA manbadan (scheduler.tashkent_tz) olinadi — bot,
# APScheduler va DB hisob-kitoblari hech qachon ajralib ketmasligi uchun.


class UpdateAdmissionError(RuntimeError):
    """Local update capacity is full; do not wait for a user lock."""


class UpdateLockManager:
    """Per-user / per-chat lock menejeri.

    concurrent_updates=True bilan ishlaganda bir xil foydalanuvchi/chatdan
    kelgan update'lar bir vaqtda ConversationHandler va context.user_data'ni
    o'zgartirib race condition keltirib chiqarmasligi uchun navbat bilan (seriyali)
    bajariladi, lekin turli foydalanuvchilar parallel ravishda ishlayveradi.

    Xotira sizib ketmasligi (leak-free) uchun faoliyat tugagach
    foydalanilmagan lock'lar darhol tozalanadi.
    """

    def __init__(self, max_pending=UPDATE_ADMISSION_MAX_PENDING,
                 max_per_user=UPDATE_ADMISSION_MAX_PER_USER):
        self._max_pending = max(1, int(max_pending))
        self._max_per_user = max(1, int(max_per_user))
        self._pending = 0
        self._pending_by_key: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._counts: dict[str, int] = {}
        self._meta_lock = asyncio.Lock()

    @asynccontextmanager
    async def admit(self, key: str | None):
        """Bound active + waiting updates before any I/O (one event loop).

        This is local memory protection, NOT a distributed FSM/user lock.
        Cancellation, rejection and handler errors always return the slot.
        """
        count = self._pending_by_key.get(key, 0) if key else 0
        if self._pending >= self._max_pending or (key and count >= self._max_per_user):
            raise UpdateAdmissionError
        self._pending += 1
        if key:
            self._pending_by_key[key] = count + 1
        try:
            yield
        finally:
            self._pending -= 1
            if key:
                remaining = self._pending_by_key[key] - 1
                if remaining:
                    self._pending_by_key[key] = remaining
                else:
                    self._pending_by_key.pop(key, None)

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

        try:
            async with user_lock:
                yield
        finally:
            # Include cancellation WHILE WAITING, not just inside the lock.
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
    0. Bounded local admission + granular rate limiting BEFORE user locks.
    1. Per-user / per-chat lock: bir foydalanuvchining parallel so'rovlari (double click / race condition)
       seriyalashtiriladi, shunda ConversationHandler va context.user_data kutilmagan bosqichga sakrab ketmaydi.
    2. Global flood bo'lsa — qisqa pauza (backpressure) bilan sekinlashtiramiz.
    3. Bitta foydalanuvchi 2 soniyada 20 tadan ortiq update yuborsa — tashlab yuboramiz.
    4. Bir xil xabarni 1.5 soniya ichida qayta yuborsa — tashlab yuboramiz.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock_manager = UpdateLockManager()

    @staticmethod
    def is_stale_update(update) -> bool:
        """Bu update ESKIMI (Render Free'da bot o'chgan paytda yig'ilgan)?

        Render free-tier instance'i 15 daqiqa faol bo'lmasa O'CHADI va
        keyin xabar kelganda QAYTA OCHILADI (bu "cold start"). O'chgan
        paytda foydalanuvchilar yuborgan xabarlar Telegram serverida
        jamlanadi va qayta ishga tushganda birdan kelib tushadi — ular
        ``/start``, stiker, matn bo'lishi mumkin. Agar hammasi
        bajarilsa, bot bir vaqtda yuzlab xabarni qayta ishlaydi va birinchi
        foydalanuvchining javobi kechikadi.

        ``STALE_UPDATE_SECONDS`` (standart 600s = 10 daqiqa) dan eski
        update'lar INDIRO'LADI: ular hech qachon foydalanuvchiga ko'rinmaydi
        va navbatni to'smaydi. Jonli xabarlar Telegram'da bir necha soniyada
        yuboriladi, shuning uchun chegara haqiqiy xabarni kesib tashlamaydi.
        """
        if STALE_UPDATE_SECONDS <= 0:
            return False
        stamp = getattr(update, "date", None)
        if not isinstance(stamp, datetime):
            return False
        if stamp.tzinfo is None:  # PTB har doim tz-aware UTC beradi
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds()
        return age > STALE_UPDATE_SECONDS

    async def process_update(self, update):
        # 1-BOSQICH: eski update filtri — per-user lockni OLISHDAN OLDIN,
        # shunda o'lik xabarlar navbatni umuman band qilmaydi.
        if self.is_stale_update(update):
            logger.info(
                "Eski update filtrlandi (yosh: %.0fs > STALE_UPDATE_SECONDS=%s, "
                "update_id=%s)", (datetime.now(timezone.utc) - update.date).total_seconds(),
                STALE_UPDATE_SECONDS, getattr(update, "update_id", "?"),
            )
            return None

        # ⚡ DARHOL JAVOB: callback bo'lsa, tugma spinner'i muddatli markaziy
        # ack bilan (utils/callback_ack.py) — per-user lock kutishi, admission
        # va handler (DB/AI) ishi buning ORTIDAN bajariladi. Handler o'zi
        # oldinroq javob bersa, ack vazifasi bekor qilinadi.
        ack_task = schedule_early_ack(getattr(update, "callback_query", None))
        try:
            return await self._process_update_guarded(update)
        finally:
            cancel_early_ack(ack_task)

    async def _process_update_guarded(self, update):
        lock_key = get_update_lock_key(update)
        user_id = getattr(getattr(update, "effective_user", None), "id", None)
        if user_id is not None:
            # Debounced, memory-only mark here; DB writes happen in a periodic
            # worker and never block Telegram update admission.
            health_service.record_user_activity(user_id)
        # Read cached language only: rejecting overload must not query the DB
        # or create new user_data entries for every rejected sender.
        context = SimpleNamespace(user_data=getattr(self, "user_data", {}).get(user_id, {}))
        try:
            async with self._lock_manager.admit(lock_key), AsyncExitStack() as stack:
                # Keep standalone group=-1 middleware registration compatible.
                # Its scoped marker prevents a second hit during PTB dispatch.
                groups = list(getattr(self, "handlers", {}).items())
                for _, handlers in sorted(groups):
                    for handler in list(handlers):
                        if isinstance(handler, RateLimitMiddleware):
                            match = handler.check_update(update)
                            if match is None or match is False:
                                continue
                            admitted = await stack.enter_async_context(
                                handler.admission(update, context)
                            )
                            if not admitted:
                                return None
                return await self._process_admitted_update(update, lock_key)
        except UpdateAdmissionError:
            await RateLimitMiddleware._reject(update, context)
            return None

    async def _process_admitted_update(self, update, lock_key):
        async with self._lock_manager.lock(lock_key):
            try:
                # 1) Global flood — botni to'xtatib qo'ymasdan, yukni sekinlashtiramiz
                if check_global_flood():
                    await asyncio.sleep(0.4)

                # 1b) Callback debounce (tugma spam / double-tap) endi
                # GRANULAR qatlamda: ``RateLimitMiddleware`` uni
                # ``(user_id, callback_action)`` bo'yicha hisoblaydi — ya'ni
                # bir xil tugma ketma-ket bosilganda bloklanadi, boshqa
                # tugma esa bemalol bosiladi (avval barcha tugmalar bir
                # savatda hisoblanardi). Multi-instance holatda hisoblagich
                # Redis'da umumiy saqlanadi (services/cache_backend.py).

                # 2) Foydalanuvchi bo'yicha burst (hujum/flood)
                user = getattr(update, "effective_user", None)
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

            # FAZA 25: QAT'IY asinxron xavfsizlik chegarasi (watchdog).
            # Og'ir AI/tahlil chaqiruvlari ta'sirida handler cheksiz "osilib"
            # qolsa, per-user lock shu foydalanuvchining keyingi update'larini
            # ham, umumiy qabul zanjirini ham zo'riqtirmasligi uchun handler
            # ``UPDATE_HANDLER_TIMEOUT_SECONDS`` ichida tugatilishi SHART.
            # Chegaradan oshsa: vazifa bekor qilinadi, foydalanuvchi
            # xushmuomala javob oladi, batafsil (scrubberdan o'tgan) logga
            # yoziladi — lekin bot qolgan update'larni qabul qilishda
            # davom etadi (fon vazifalari intake'ni to'xtatmaydi).
            try:
                return await await_with_timeout(
                    super().process_update(update),
                    UPDATE_HANDLER_TIMEOUT_SECONDS,
                    label=f"update:{getattr(update, 'update_id', '?')}",
                )
            except asyncio.TimeoutError:
                logger.critical(
                    "FAZA25: update handler timeout (%ss) — update bekor qilindi "
                    "(user_id=%s, update_id=%s)",
                    UPDATE_HANDLER_TIMEOUT_SECONDS,
                    getattr(getattr(update, "effective_user", None), "id", None),
                    getattr(update, "update_id", None))
                await self._answer_timeout(update)
                return None

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
            except Exception as _silent_exc:
                log_silent_failure("main:GuardedApplication._answer_callback_wait", _silent_exc)

    @staticmethod
    async def _resolve_user_language(update) -> str:
        """Update yuborgan foydalanuvchi tilini aniqlaydi (xavfsiz fallback uz)."""
        lang = "uz"
        user = getattr(update, "effective_user", None)
        if user is not None and getattr(user, "id", None):
            try:
                import database as _db
                lang = await _db.run_db(_db.get_user_language, user.id)
            except Exception:
                lang = "uz"
        return lang or "uz"

    @staticmethod
    async def _answer_timeout(update):
        """FAZA 25: handler timeout bo'lganda foydalanuvchiga xushmuomala,
        tilga mos javob — bot boshqa update'larni qabulda davom etadi.

        Ichki xatolik tafsilotlari HECH QACHON ko'rsatilmaydi; faqat
        lug'atdagi qisqa «kutib turing» xabari yuboriladi (callback'lar
        uchun toast, xabarlar uchun reply) — tugma/handler «qotmaydi».
        """
        lang = await GuardedApplication._resolve_user_language(update)
        try:
            from locales.translations import get_text
            text = get_text("sys_wait_short", lang)
        except Exception:
            text = "⏳"
        try:
            query = getattr(update, "callback_query", None)
            if query is not None:
                await query.answer(text, show_alert=False)
                return
            msg = getattr(update, "effective_message", None)
            if msg is not None:
                await msg.reply_text(text)
        except Exception as _silent_exc:
            log_silent_failure("main:GuardedApplication._answer_timeout", _silent_exc, lang=lang)


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


# ============================================================
# 📡 1-BOSQICH: KEEP-ALIVE (Render/Aiven free-tier)
# ------------------------------------------------------------
# Render free-tier'da instance faol bo'lmasa «sleep»ga ketadi. Tashqi
# ping (UptimeRobot / cron-job.org) uni har 10 daqiqada uyg'otib turadi —
# bot bir kun ham o'lib qolmaydi va Telegram'da kechikish bo'lmaydi.
# ============================================================


async def keep_alive_task() -> None:
    """``KEEP_ALIVE_URL`` ga har ``KEEP_ALIVE_INTERVAL_SECONDS`` da GET yuboradi.

    Bo'sh ``KEEP_ALIVE_URL`` da bu vazifa HECH QACHON ishga tushmaydi.
    Xato (tarmoq, 5xx, timeout) botni TO'XTATMAYDI — keyingi sikl
    yana urinadi, faqat logga yoziladi.
    """
    if not KEEP_ALIVE_URL:
        return
    # Maxfiyatlik: URL'ga token qo'yilishi mumkin (Render loglari ochiq) —
    # logga faqat HOST yoziladi, to'liq URL emas.
    try:
        host = urlsplit(KEEP_ALIVE_URL).netloc or "?"
    except Exception:  # pragma: no cover
        host = "?"
    import aiohttp

    while True:
        await asyncio.sleep(KEEP_ALIVE_INTERVAL_SECONDS)
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(KEEP_ALIVE_URL) as response:
                    await response.read()
                    logger.info("Keep-alive %s -> HTTP %s", host, response.status)
        except asyncio.CancelledError:
            logger.info("Keep-alive vazifasi to'xtatildi (%s).", host)
            raise
        except Exception as e:
            # Keep-alive MUHIM EMAS — xato botni halokatga olib kelmasin.
            logger.warning("Keep-alive so'rovi muvaffaqiyatsiz (%s): %s", host, e)


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
#   4) lifecycle.wait_for_inflight() + lifecycle.wait_for_queues() — faol
#      postlar va navbatlar (delivery + scheduler ishlari) uchun jami
#      SHUTDOWN_GRACE_SECONDS byudjeti beriladi (PHASE 12: standart **15
#      soniya**); ular BEKOR QILINMAYDI — timeout tugasa DB'dagi
#      'processing' holati stale-recovery bilan tiklanadi;
#   5) application.stop()/shutdown() — PTB navbatdagi update'larni tugatadi;
#   6) scheduler.shutdown(wait=False), web server cleanup;
#   7) db.close_pool() + close_ai_session() + cache (Redis) backend —
#      DB va Redis connection pool'lari toza yopiladi;
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
        except (NotImplementedError, RuntimeError, ValueError) as _silent_exc:
            log_silent_failure("main:remove_signal_handlers", _silent_exc)


async def graceful_shutdown(application=None, scheduler=None, web_runner=None,
                            grace_seconds: float = None) -> dict:
    """Barcha komponentlarni TARTIB bilan, xatolardan himoyalangan holda yopadi.

    Har bir bosqich alohida ``try/except`` da — bittasi xato bersa keyingilari
    baribir bajariladi (DB pool va aiohttp sessiyalari doim yopiladi).
    Qaytadi: bosqichlar hisoboti (testlar/diagnostika uchun).
    """
    report = {"steps": [], "errors": []}
    shutdown_started = time.monotonic()

    def _step(name, ok=True, extra=None):
        report["steps"].append(name)
        if not ok:
            report["errors"].append(name)
        if extra is not None:
            report[name] = extra

    def _remaining_budget() -> float:
        """Drenaj byudjetining qolgan qismi (soniya).

        ``grace_seconds`` berilmagan bo'lsa PHASE 12 standarti —
        ``lifecycle.SHUTDOWN_GRACE_SECONDS`` (**15 soniya**); env orqali
        sozlanadi va [5, 30] oralig'iga qisiladi.
        """
        total = (lifecycle.SHUTDOWN_GRACE_SECONDS if grace_seconds is None
                 else max(0.0, float(grace_seconds)))
        return max(0.0, total - (time.monotonic() - shutdown_started))

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

    # 3) Faol vazifalarga tugallanish uchun byudjet beriladi (PHASE 12:
    #    standart 15 soniya, `grace_seconds` aniq berilsa o'sha). Vazifalar
    #    BEKOR QILINMAYDI — faqat kutiladi.
    try:
        drain = await lifecycle.wait_for_inflight(grace_seconds)
        _step("inflight_drained", ok=drain.get("drained", False), extra=drain)
    except Exception:
        logger.exception("Faol vazifalarni kutishda xatolik")
        _step("inflight_drained", ok=False)

    # 3b) PHASE 12 · NAVBAT DRENAJI (delivery queue + scheduler ishlari).
    #    In-flight kutish tugagach, navbatlarda qolgan birliklar (masalan,
    #    Telegramga yuborilayotgan xabar yoki RetryAfter kutayotgan delivery)
    #    uchun qolgan byudjet sarflanadi. Navbatdagi ishlar ham BEKOR
    #    QILINMAYDI: timeout tugasa ular DB'da 'processing' bo'lib qoladi va
    #    keyingi ishga tushishda stale-recovery ularni xavfsiz tiklaydi.
    try:
        queues = await lifecycle.wait_for_queues(_remaining_budget())
        _step("queues_drained", ok=queues.get("drained", False), extra=queues)
    except Exception:
        logger.exception("Navbatlar drenajini kutishda xatolik")
        _step("queues_drained", ok=False)

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

    # 5b) PHASE 10: qolgan coalesced faol user ID'larini DB pool yopilishidan
    # oldin bir marta flush qilamiz. Xato shutdown jarayonini to'xtatmaydi.
    try:
        await health_service.flush_user_activity()
        _step("user_activity_flushed")
    except Exception:
        logger.warning("Shutdown vaqtida user activity flush bajarilmadi", extra={
            "event": "shutdown_user_activity_flush_failed",
            "error_code": "USER_ACTIVITY_DB_ERROR",
        })
        _step("user_activity_flushed", ok=False)

    # 6) Web server (health endpointlari).
    if web_runner is not None:
        try:
            await web_runner.cleanup()
            _step("web_server_closed")
        except Exception:
            logger.exception("Web serverni yopishda xatolik")
            _step("web_server_closed", ok=False)

    # 7) DB pool va aiohttp ClientSession'lar — HAR DOIM yopiladi.
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
    # 7b) PHASE 2: cache/Redis ulanishi (ixtiyoriy — yo'q bo'lsa ham
    # xavfsiz, In-Memory backend hech narsa bilan bog'lanmagan).
    try:
        await cache_backend_svc.close_cache_backend()
        _step("cache_closed")
    except Exception:
        logger.exception("Cache backendni yopishda xatolik")
        _step("cache_closed", ok=False)

    report["clean"] = not report["errors"]
    logger.info(
        "Bot to'liq to'xtatildi va barcha resurslar yopildi (bosqichlar: %s%s).",
        ", ".join(report["steps"]),
        f"; xatolar: {report['errors']}" if report["errors"] else "",
    )
    return report


def _install_io_executor() -> None:
    """⚡ ``run_db`` / ``asyncio.to_thread`` uchun thread pool hajmini sozlaydi.

    Standart asyncio executor ``min(32, cpu+4)`` — kichik (1-2 vCPU) instance'da
    atigi ~5-6 ta thread. Bir vaqtda 10 ta foydalanuvchi menyu ochsa, DB
    so'rovlari shu kichik pool'da NAVBATDA kutadi (har biri bir RTT, ustiga
    navbat). Pool hajmi DB ulanish havzasidan (``DB_POOL_MAX``) kelib chiqadi:
    DB o'zi baribir ``DB_POOL_MAX`` ta bilan cheklangan (semafor), shuning
    uchun ortiqcha thread'lar faqat navbatni qisqartiradi. ``BOT_IO_THREADS``
    orqali qo'lda o'zgartirish mumkin.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    try:
        override = int(os.getenv("BOT_IO_THREADS", "0") or 0)
    except ValueError:
        override = 0
    workers = override if override > 0 else max(8, min(32, db.DB_POOL_MAX + 4))
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bot-io")
    )
    logger.info("I/O thread pool: %s thread (DB_POOL_MAX=%s)", workers, db.DB_POOL_MAX)


async def main():
    # ⚡ Thread pool — barcha DB/offload chaqiruvlaridan OLDIN sozlanadi.
    _install_io_executor()

    # ================================================================
    # 1-BOSQICH: PORT AVVAL OCHILADI (0-s readiness)
    # ------------------------------------------------------------
    # Render web service «Deploy successful» deguncha PORT ga ulanishni
    # tekshiradi. ``start_web_server()`` ``db.init_db()`` dan OLDIN
    # ishga tushadi — chunki ``init_db()`` og'ir: TCP + TLS handshake,
    # 3 urinish (3s kutish), ``CREATE TABLE/INDEX IF NOT EXISTS`` va
    # integrity tekshiruvi. Aiven/Render free-tier da bu 5–30 soniya
    # oladi; port shu vaqt YOPIQ bo'lsa, Render deploy'ni muvaffaqiyatsiz
    # deb belgilaydi (health check timeout) yoki bot "sekin start" bo'ladi.
    #
    # ``/health/live`` baza bilan UMUMAN bog'lanmaydi (faqat process
    # tirikligi), shuning uchun bu endpoint DB bo'lmagan holatda ham
    # darhol 200 qaytaradi. DB tekshiruvi faqat ``/health/ready`` da.
    # ================================================================
    web_runner = await start_web_server()

    # Havzani isitish + jadvallarni yaratish. Bu endi KECHIKMAYDI, chunki
    # port allaqachon ochiq — Render darhol 200 oladi va bot init_db
    # tugagach Telegram'ni oladi.
    #
    # ⚠️ MUHIM: ``db.init_db()`` SINXRON (psycopg2) funksiya — uni to'g'ridan
    # chaqirsak, u event loop'ni BUTUNLAY bloklaydi. Socket bound bo'lsa ham,
    # aiohttp server javob BEROLMAYDIGAN edi (loop band) va Render yana
    # health-check timeout olardi. Shuning uchun ``asyncio.to_thread`` —
    # DB ishi worker thread'da, event loop esa shu vaqt /health/live ga
    # javob berishda davom etadi.
    try:
        await asyncio.to_thread(db.init_db)
    except BaseException:
        # DB ko'tarilmadi: ochiq portni YOPAMIZ. Aks holda Render bot
        # o'lganini sezmasdan «healthy» deb qolardi va deploy muvaffaqiyatli
        # ko'rinirdi (lekin Telegram'da javob yo'q bo'lardi).
        logger.critical("DB ishga tushirilmadi — web server yopilmoqda, "
                        "bot to'xtaydi (Render deploy muvaffaqiyatsiz bo'ladi).")
        try:
            await web_runner.cleanup()
        except Exception:
            logger.exception("Web serverni yopishda xatolik")
        raise

    # 11-bosqich (P0) restart recovery: avvalgi jarayon 'processing' da
    # qoldirgan postlar — Telegramga chiqqanlari 'posted' (qayta yuborilmaydi),
    # UNKNOWN_DELIVERY bo'lganlari 'unknown', qolganlari 'pending'.
    await recover_on_startup()

    # PHASE 2 · Distributed state: Redis (ixtiyoriy) / In-Memory backend.
    # `REDIS_URL` + `REDIS_ENABLED` bo'lsa va ulanish muvaffaqiyatli bo'lsa —
    # state (rate limit sanagichlari) BARCHA instance'lar uchun umumiy;
    # aks holda (yoki Redis uzilib qolsa) — In-Memory + circuit breaker.
    # Bu qadam hech qachon botni to'xtatmaydi (muvaffaqiyatsiz bo'lsa
    # jim In-Memory rejimga qaytadi).
    try:
        await cache_backend_svc.init_cache_backend()
    except Exception:
        logger.exception("Cache backend ishga tushirilmadi — In-Memory rejimda davom etamiz")

    # Admin panelda o'zgartirilgan AI parametrlarini ishga tushirishda yuklaymiz.
    try:
        await reload_runtime_params()
    except Exception:
        logger.exception("AI runtime parametrlarni yuklashda xatolik (defaultlar ishlatiladi)")

    # ``web_runner`` yuqorida (init_db'dan oldin) tayinlangan — uni QAYTA
    # null qilmaymiz, aks holda graceful_shutdown uni yopa olmasdi.
    scheduler = None
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed_signals = install_signal_handlers(loop, stop_event)
    # 1-BOSQICH: keep-alive fon vazifasi (KEEP_ALIVE_URL bo'lmasa
    # ishga tushmaydi). Uzoq umrli sikl — ``run_background_task``ning
    # timeout'i uni o'ldirishi mumkin, shuning uchun oddiy
    # ``create_task`` + kuchli havolani saqlash ishlatiladi.
    keep_alive_handle = None
    if KEEP_ALIVE_URL:
        keep_alive_handle = asyncio.create_task(keep_alive_task())
        try:
            keep_alive_handle.set_name("keep-alive")
        except Exception as _silent_exc:  # pragma: no cover — eski Python
            log_silent_failure("main:main:760", _silent_exc)
        logger.info("Keep-alive yoqildi: %s da %ss oralig'ida.",
                    urlsplit(KEEP_ALIVE_URL).netloc or "?",
                    KEEP_ALIVE_INTERVAL_SECONDS)
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

    # 💳 Payme: PerformTransaction muvaffaqiyatli bo'lgach foydalanuvchiga
    # «PRO faollashtirildi» xabari (post-commit, best-effort). Webhook o'zi
    # web serverda allaqachon ochiq — bu faqat bildirishnoma ulanishi.
    try:
        from services.payments.payme_webhook import build_bot_notifier, set_paid_notifier
        set_paid_notifier(build_bot_notifier(application.bot))
    except Exception as _silent_exc:
        log_silent_failure("main:main:payme_notifier", _silent_exc)

    # PHASE 2 · Granular rate limiting — barcha handler'lardan OLDIN
    # GuardedApplication admits BEFORE the user lock; group=-1 dispatch
    # skips only that already-checked update (no double counting).
    # Har bir harakat uchun alohida kalit + TTL:
    # matn xabarlari, (user_id, callback_action) throttling, qimmatli AI
    # amallari va URL/RSS fetch. Sanagichlar Redis'da (ixtiyoriy) —
    # aks holda In-Memory; Redis uzilsa avtomatik fallback (circuit
    # breaker, services/cache_backend.py).
    application.add_handler(RateLimitMiddleware(), group=-1)

    # PHASE 3 · Resurs (kanal/post) darajasidagi RBAC + IDOR qatlami.
    # PTB har bir GURUHDA faqat bitta handler ishlatadi, shu sababli bu
    # middleware ALOHIDA guruhga (-2) qo'yiladi: avval ruxsat, keyin rate
    # limiter (-1), keyin haqiqiy handler'lar (0).  Ruxsat bo'lmasa handler'lar
    # UMUMAN chaqirilmaydi (ApplicationHandlerStop) va foydalanuvchi
    # "Permission Denied" alert oladi; ruxsat bo'lsa — update odatdagi
    # zanjirda davom etadi.  Handler ichidagi tekshiruvlar BARIBIR ishlaydi
    # (chuqur himoya).  Middleware'ni ``RBAC_RESOURCE_MIDDLEWARE=0`` bilan
    # o'chirish mumkin.
    # MUHIM: RateLimitMiddleware ``group=-1`` da qoladi —
    # tests/rate_limiter_redis_test.py shu ro'yxatga olishni qulflaydi.
    install_resource_middleware(application, group=-2)

    register_all_handlers(application)
    # 1-BOSQICH: ``start_web_server()`` endi ``init_db()`` dan OLDIN
    # chaqirilgan (yuqorida) — bu yerda QAYTARIB chaqirilmaydi.

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
    # PHASE 10: update yo'li DB write qilmaydi; aktiv user ID'lari 30s da bir
    # batch bilan flush qilinadi (graceful shutdown'da ham qo'shimcha flush bor).
    scheduler.add_job(
        health_service.flush_user_activity, 'interval', seconds=30,
        id="flush_user_activity", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=60,
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
    # 🌅 Sprint 3 — har kuni Toshkent vaqti bilan 09:00 da faqat
    # 48 soatdan beri post chiqmagan va digestga rozilik bergan egalar uchun.
    scheduler.add_job(
        daily_morning_digest_job, 'cron', hour=9, minute=0,
        args=[application.bot], id="daily_morning_digest", timezone=tashkent_tz,
        max_instances=1, coalesce=True, misfire_grace_time=6 * 3600,
    )
    # 🗓 Uch kun oldingi O'zbekiston bayram/mavsum eslatmalari; digest bilan
    # bir vaqtda ikkita Telegram xabari yubormaslik uchun 09:05 da bajariladi.
    scheduler.add_job(
        uzbekistan_calendar_reminders_job, 'cron', hour=9, minute=5,
        args=[application.bot], id="uzbekistan_calendar_reminders",
        timezone=tashkent_tz, max_instances=1, coalesce=True,
        misfire_grace_time=6 * 3600,
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
        await application.updater.start_polling(
            # 1-BOSQICH: ``False`` — eski xabarlar YO'Q QILINMAYDI.
            # Sabab: Render/Aiven kechikishida foydalanuvchi yuborgan
            # xabar (masalan /start) o'chgan paytda navbatda turadi; agar
            # uni tashlab yuborilsa, foydalanuvchi "javob yo'q" deb qoladi.
            # Eski xabarlar endi ikki bosqichli himoya bilan filtrlanadi:
            #   1) ``GuardedApplication.is_stale_update`` —
            #      STALE_UPDATE_SECONDS (600s) dan eskisi INDIRO'LADI;
            #   2) ``recover_on_startup()`` — 'processing' qolgan postlar
            #      tiklanadi (qayta yuborilmaydi).
            # Bot API 9.2 subscription may not be present in PTB's ALL_TYPES
            # yet; explicitly request it so recurring payment state updates
            # are not silently omitted by long polling.
            allowed_updates=[str(update_type) for update_type in Update.ALL_TYPES]
            + ["subscription"],
            drop_pending_updates=False,
        )

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
        # 1-BOSQICH: keep-alive siklini to'xtatamiz (u ``while True`` —
        # to'xtatilmasa event loop'da osilib qoladi va "Task was destroyed
        # but it is pending" ogohlantirishlari chiqadi).
        if keep_alive_handle is not None and not keep_alive_handle.done():
            keep_alive_handle.cancel()
            try:
                await keep_alive_handle
            except (asyncio.CancelledError, Exception) as _silent_exc:
                log_silent_failure("main:main:928", _silent_exc)
        remove_signal_handlers(loop, installed_signals)
        await graceful_shutdown(application, scheduler, web_runner)


def run() -> int:
    """Botni ishga tushiradi; toza yopilishda 0 qaytaradi (exit code)."""
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as _silent_exc:
        # Signal handlerlar o'rnatilgan bo'lsa bu yerga kelinmaydi; fallback
        # muhitda ham yopilish main() ning finally blokida tugallangan.
        log_silent_failure("main:run", _silent_exc)
    return 0


if __name__ == "__main__":
    sys.exit(run())
