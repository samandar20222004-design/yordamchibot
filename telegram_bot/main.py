import asyncio
from contextlib import asynccontextmanager
import logging
import pytz  # noqa: F401 — vaqt zonasi bilan ishlovchi modullar uchun saqlanadi
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.ext import ApplicationBuilder, Application
from telegram import BotCommand
from config import BOT_TOKEN
import database as db
from handlers import register_all_handlers
from scheduler import (
    check_and_send_posts,
    check_and_delete_expired_posts,
    cleanup_old_data_job,
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
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
                await query.answer("⏳ Iltimos, kuting...", show_alert=False)
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
        BotCommand("profile", "Kabinet va sozlamalar"),
        BotCommand("help", "Yordam va qo'llanma"),
        BotCommand("cancel", "Amalni bekor qilish"),
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Telegram Menyu buyruqlari muvaffaqiyatli o'rnatildi.")
    except Exception as e:
        logger.warning(f"Menyu buyruqlarini o'rnatishda xatolik: {e}")


async def main():
    db.init_db()

    # Admin panelda o'zgartirilgan AI parametrlarini ishga tushirishda yuklaymiz.
    try:
        await reload_runtime_params()
    except Exception:
        logger.exception("AI runtime parametrlarni yuklashda xatolik (defaultlar ishlatiladi)")

    web_runner = None
    scheduler = None
    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .application_class(GuardedApplication)
        .concurrent_updates(True)
        # Telegram API so'rovlari uchun aniq timeout'lar (Render Free'da
        # tarmoq sekinlashganda bot osilib qolmasligi uchun).
        .connect_timeout(15)
        .read_timeout(15)
        .write_timeout(30)
        .media_write_timeout(60)
        .pool_timeout(5)
        .connection_pool_size(8)
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
        "Scheduler started (TZ=%s): postlar har 1 daqiqada, DB tozalash har 6 soatda.",
        TIMEZONE_NAME,
    )
    logger.info("Bot muvaffaqiyatli ishga tushdi.")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot to'xtatilmoqda...")
    finally:
        # Ishga tushirish bosqichida xatolik bo'lgan taqdirda ham
        # ochilgan resurslar yopilishi kerak (shuning uchun None-tekshiruv).
        # Yopilish xatosi asl xatoni yashirmasligi uchun try/except ichida.
        try:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            updater = getattr(application, "updater", None)
            if updater is not None:
                await updater.stop()
            await application.stop()
            await application.shutdown()
            if web_runner is not None:
                await web_runner.cleanup()
        except Exception:
            logger.exception("Botni to'xtatishda xatolik yuz berdi")
        db.close_pool()
        await close_ai_session()
        logger.info("Bot to'liq to'xtatildi va barcha resurslar yopildi.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
