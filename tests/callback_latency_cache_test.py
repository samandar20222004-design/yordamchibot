#!/usr/bin/env python3
"""⚡ CALLBACK LATENCY + KESHLASH — deterministik testlar (tugmalar tezligi).

Tekshiriladi (vaqtga emas, PARALLELLIK va CHAQIRUVLAR SONIGA tayanadi —
shuning uchun sekin CI'da ham beqaror bo'lmaydi):

  A. Callback «darhol javob» (utils/callback_ack.py):
     * ``CallbackQuery.answer`` idempotent — dublikat javob Telegram'ga bormaydi,
       istisno ko'tarmaydi;
     * sekin handler (javob bermaydi yoki DB'dan keyin javob beradi) — markaziy
       ack muddatida spinner to'xtatiladi (handler tugashini kutmasdan);
     * tez handler'ning toast'i saqlanadi (markaziy ack qo'shilmaydi);
     * handler hech narsa qilmasa va tez tugasa — ortiqcha javob YO'Q;
     * GuardedApplication.process_update orqali haqiqiy dispatch'da ham ishlaydi.

  B. Navigatsiya va obuna (handlers/start.py, handlers/queue.py,
     handlers/statistics.py):
     * homiy kanal a'zoligi (cache miss) Telegram'ga PARALLEL so'raladi;
     * natija tartibi va fail-closed qoidalari saqlanadi; kesh hit = 0 chaqiruv;
     * «📅 Rejalashtirilgan» va «📊 Statistika» mustaqil DB o'qishlarini
       parallel yuboradi;

  C. Keshlash:
     * profil keshi (til, PRO) TTL >= 60 s va issiq profilda 0 DB so'rovi;
     * sodda menyu qarori keshlangach 0 DB so'rovi;
     * I/O thread pool DB havzasi hajmiga moslashtirilgan.

Ishga tushirish (repo ildizidan):
    python tests/callback_latency_cache_test.py
"""

import asyncio
import importlib
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:LATENCY_TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ADMIN_ID", "123456789")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from telegram import CallbackQuery, Update, User  # noqa: E402
from telegram.error import Forbidden, TelegramError  # noqa: E402
from telegram.ext import ApplicationBuilder, TypeHandler  # noqa: E402

import main  # noqa: E402
from utils import callback_ack as ack  # noqa: E402

start_mod = importlib.import_module("handlers.start")
queue_mod = importlib.import_module("handlers.queue")
stats_mod = importlib.import_module("handlers.statistics")
import database as db  # noqa: E402


def _query(qid="1001", uid=42, data="menu:x"):
    """Haqiqiy PTB CallbackQuery + bot (answer_callback_query mock)."""
    bot = MagicMock()
    bot.answer_callback_query = AsyncMock(return_value=True)
    q = CallbackQuery(qid, User(uid, "U", False), "chat-instance", data=data)
    q.set_bot(bot)
    return q, bot.answer_callback_query


async def _wait_until(predicate, timeout=2.0, step=0.005):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        await asyncio.sleep(step)
    return predicate()


class CallbackAckUnitTests(unittest.IsolatedAsyncioTestCase):
    async def test_answer_is_idempotent_and_never_raises_on_duplicate(self):
        q, api = _query("idem-1")
        await q.answer("birinchi")
        await q.answer()          # dublikat
        await q.answer("uchinchi", show_alert=True)
        self.assertEqual(api.await_count, 1, "Telegram'ga faqat bitta answer borishi kerak")
        self.assertEqual(api.await_args.kwargs.get("text"), "birinchi")

    async def test_slow_handler_is_acked_before_it_finishes(self):
        q, api = _query("slow-1")
        release = asyncio.Event()

        async def slow_handler():
            await release.wait()  # DB/AI ishi tugamaguncha

        task = asyncio.ensure_future(slow_handler())
        ack_task = ack.schedule_early_ack(q, delay=0.02)
        try:
            self.assertTrue(await _wait_until(lambda: api.await_count == 1, timeout=1.0),
                            "markaziy ack handler tugamasdan yuborilishi kerak")
            self.assertFalse(task.done(), "handler hali ishlayotgan bo'lishi kerak")
        finally:
            release.set()
            await task
            ack.cancel_early_ack(ack_task)
        self.assertEqual(api.await_count, 1)

    async def test_fast_handler_keeps_its_toast_and_gets_no_extra_ack(self):
        q, api = _query("fast-toast-1")
        ack_task = ack.schedule_early_ack(q, delay=0.05)
        await q.answer("✅ Saqlandi", show_alert=True)   # handler birinchi qatorda javob beradi
        await asyncio.sleep(0.08)                          # ack muddati o'tsa ham
        ack.cancel_early_ack(ack_task)
        self.assertEqual(api.await_count, 1)
        self.assertEqual(api.await_args.kwargs.get("text"), "✅ Saqlandi")
        self.assertTrue(api.await_args.kwargs.get("show_alert"))

    async def test_fast_handler_without_answer_triggers_no_answer(self):
        q, api = _query("silent-fast-1")
        ack_task = ack.schedule_early_ack(q, delay=0.05)
        await asyncio.sleep(0)            # handler darhol tugadi
        ack.cancel_early_ack(ack_task)
        await asyncio.sleep(0.07)
        self.assertEqual(api.await_count, 0)

    async def test_answer_before_db_work_is_sent_first(self):
        q, api = _query("order-1")
        events = []

        async def handler():
            await q.answer()                       # birinchi qator
            events.append("answered")
            await asyncio.sleep(0.2)               # og'ir DB ishi
            events.append("db-done")

        await handler()
        self.assertEqual(events, ["answered", "db-done"])
        self.assertEqual(api.await_count, 1)

    async def test_early_ack_task_is_none_for_non_callback_and_answered(self):
        self.assertIsNone(ack.schedule_early_ack(None))
        q, _api = _query("done-1")
        await q.answer()
        self.assertIsNone(ack.schedule_early_ack(q))


class CallbackAckDispatchTests(unittest.IsolatedAsyncioTestCase):
    """Haqiqiy GuardedApplication.process_update orqali (admission + lock)."""

    def setUp(self):
        self.app = (ApplicationBuilder().token(os.environ["BOT_TOKEN"])
                    .application_class(main.GuardedApplication).build())
        self.app.bot._bot_user = User(900, "Test Bot", True, username="test_bot")
        self.app._initialized = True
        self.api = AsyncMock(return_value=True)
        self.patches = [
            patch.object(type(self.app.bot), "answer_callback_query", new=self.api),
            patch("main.check_global_flood", lambda: False),
            patch("main.check_rate_limit", lambda *a, **kw: (False, False)),
            patch("main.is_duplicate_message", lambda *a, **kw: False),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        self.seq = 0

    def _update(self, uid=42, data="menu:slow"):
        self.seq += 1
        q = CallbackQuery(str(7000 + self.seq), User(uid, "U", False), "chat", data=data)
        q.set_bot(self.app.bot)
        return Update(7000 + self.seq, callback_query=q)

    async def test_slow_callback_is_acked_while_handler_still_runs(self):
        release = asyncio.Event()

        async def slow(update, context):
            await release.wait()

        self.app.add_handler(TypeHandler(Update, slow))
        upd = self._update()
        task = asyncio.ensure_future(self.app.process_update(upd))
        try:
            self.assertTrue(await _wait_until(lambda: self.api.await_count == 1, timeout=1.5),
                            "sekin callback spinner'i handler tugamasdan to'xtashi kerak")
            self.assertFalse(task.done())
        finally:
            release.set()
            await task
        self.assertEqual(self.api.await_count, 1)

    async def test_fast_callback_dispatch_sends_no_early_ack(self):
        async def fast(update, context):
            return None

        self.app.add_handler(TypeHandler(Update, fast))
        await self.app.process_update(self._update(data="menu:fast"))
        await asyncio.sleep(ack.EARLY_ACK_SECONDS + 0.05)
        self.assertEqual(self.api.await_count, 0)

    async def test_user_lock_wait_does_not_delay_the_ack(self):
        """Bir xil foydalanuvchining oldingi update'i band — ack baribir tez."""
        release = asyncio.Event()

        async def handler(update, context):
            if update.callback_query.data == "menu:first":
                await release.wait()

        self.app.add_handler(TypeHandler(Update, handler))
        first = asyncio.ensure_future(self.app.process_update(self._update(data="menu:first")))
        await asyncio.sleep(0.01)
        second = asyncio.ensure_future(self.app.process_update(self._update(data="menu:second")))
        try:
            self.assertTrue(await _wait_until(lambda: self.api.await_count >= 1, timeout=1.5))
        finally:
            release.set()
            await asyncio.gather(first, second, return_exceptions=True)


class SubscriptionParallelismTests(unittest.IsolatedAsyncioTestCase):
    SPONSORS = [
        (1, -100101, "A", "a", "https://t.me/a"),
        (2, -100102, "B", "b", "https://t.me/b"),
        (3, -100103, "C", "c", "https://t.me/c"),
    ]

    def setUp(self):
        start_mod._membership_cache.clear()
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = []

    def _bot(self, behaviour):
        bot = MagicMock()

        async def get_chat_member(chat_id, user_id):
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            self.calls.append(chat_id)
            try:
                await asyncio.sleep(0.05)
                return behaviour(chat_id)
            finally:
                self.in_flight -= 1

        bot.get_chat_member = get_chat_member
        return bot

    async def _check(self, bot, uid=777):
        with patch.object(start_mod.db, "run_db", new=AsyncMock(return_value=self.SPONSORS)):
            return await start_mod.check_user_subscribed(bot, uid)

    async def test_cache_miss_lookups_run_concurrently(self):
        bot = self._bot(lambda ch: SimpleNamespace(status="member"))
        ok, unsubs = await self._check(bot)
        self.assertTrue(ok)
        self.assertEqual(unsubs, [])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.max_in_flight, 3, "3 ta a'zolik so'rovi bir vaqtda ketishi kerak")

    async def test_result_order_and_fail_closed_rules_are_preserved(self):
        def behaviour(ch):
            if ch == -100101:
                return SimpleNamespace(status="member")
            if ch == -100102:
                return SimpleNamespace(status="left")
            # -100103: vaqtinchalik Telegram xatosi → fail-closed (obuna emas)
            raise TelegramError("network hiccup")

        bot = self._bot(behaviour)
        ok, unsubs = await self._check(bot)
        self.assertFalse(ok)
        self.assertEqual([s[1] for s in unsubs], [-100102, -100103],
                         "a'zo bo'lmagan va tekshirib bo'lmagan (fail-closed) kanallar")

    async def test_forbidden_sponsor_is_skipped_not_blocking(self):
        """Bot kanalga kira olmasa (Forbidden) sponsor o'tkazib yuboriladi —
        butun bot yopilmaydi."""
        bot = self._bot(lambda ch: SimpleNamespace(status="member"))

        async def get_chat_member(chat_id, user_id):
            await asyncio.sleep(0)
            if chat_id == -100101:
                raise Forbidden("bot is not a member")
            return SimpleNamespace(status="left")

        bot.get_chat_member = get_chat_member
        ok, unsubs = await self._check(bot)
        self.assertFalse(ok)
        self.assertEqual([s[1] for s in unsubs], [-100102, -100103])

    async def test_warm_membership_cache_makes_zero_telegram_calls(self):
        bot = self._bot(lambda ch: SimpleNamespace(status="member"))
        await self._check(bot)
        self.calls.clear()
        ok, _ = await self._check(bot)
        self.assertTrue(ok)
        self.assertEqual(self.calls, [], "kesh issiq bo'lsa Telegram'ga so'rov bo'lmasligi kerak")


class QueueAndStatisticsParallelismTests(unittest.IsolatedAsyncioTestCase):
    async def test_queue_view_reads_are_issued_together(self):
        """count + limit + posts — uchalasi bir vaqtda boshlanadi (barrier)."""
        started = set()
        all_started = asyncio.Event()

        async def fake_run_db(fn, *args, **kwargs):
            started.add(fn.__name__)
            if len(started) == 3:
                all_started.set()
            # Ketma-ket bo'lsa birinchisi shu yerda uzilib tushadi (TimeoutError)
            await asyncio.wait_for(all_started.wait(), timeout=1.0)
            if fn is db.get_queue_post_count:
                return 0
            if fn is db.check_queue_limit:
                return (True, 0, 5)
            return []

        with patch.object(queue_mod.db, "run_db", new=fake_run_db):
            result = await queue_mod._build_queue_view(42, False, "uz")
        self.assertEqual(started, {"get_queue_post_count", "check_queue_limit", "get_queue_posts"})
        self.assertIsInstance(result, tuple)

    async def test_queue_view_total_error_still_propagates(self):
        async def fake_run_db(fn, *args, **kwargs):
            if fn is db.get_queue_post_count:
                raise RuntimeError("db down")
            return None

        with patch.object(queue_mod.db, "run_db", new=fake_run_db):
            with self.assertRaises(RuntimeError):
                await queue_mod._build_queue_view(42, False, "uz")

    async def test_statistics_reads_are_issued_together(self):
        started = set()
        all_started = asyncio.Event()

        async def fake_run_db(fn, *args, **kwargs):
            started.add(fn.__name__)
            if len(started) == 2:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1.0)
            if fn is db.get_user_overview_stats:
                return {"channels": 1, "created_posts": 3, "scheduled_posts": 1,
                        "ai_requests": 0, "credits_spent": 0}
            return 9  # get_user_credits

        async def fake_advice(user_id, channels=None):
            started.add("collect_advice")
            await asyncio.wait_for(all_started.wait(), timeout=1.0)
            return {}

        reply = AsyncMock()
        update = SimpleNamespace(effective_user=SimpleNamespace(id=42),
                                 message=SimpleNamespace(reply_text=reply))
        context = SimpleNamespace(user_data={}, bot=MagicMock())
        with patch.object(stats_mod.db, "run_db", new=fake_run_db), \
                patch.object(stats_mod, "collect_advice", new=fake_advice):
            await stats_mod.show_user_statistics(update, context)
        self.assertEqual(started, {"get_user_overview_stats", "get_user_credits", "collect_advice"})
        reply.assert_awaited_once()


class ProfileCacheTests(unittest.TestCase):
    def test_profile_cache_ttl_is_at_least_60_seconds(self):
        self.assertGreaterEqual(db.DB_PROFILE_CACHE_TTL, 60)

    def test_warm_profile_serves_language_and_pro_without_db(self):
        uid = 987654
        db._profile_clear_all()
        row = ("ru", "CODE1", "name", "Full", 5, 2, "pro", None, 1, 3)

        class _Cur:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def execute(self, *a, **k):
                pass

            def fetchone(self):
                return row

        from contextlib import contextmanager

        @contextmanager
        def fake_cursor(commit=False):
            yield _Cur()

        with patch.object(db, "db_cursor", fake_cursor):
            prof = db.get_user_profile(uid)  # sovuq: bitta so'rov
        self.assertIsNotNone(prof)
        self.assertEqual(prof["lang"], "ru")
        self.assertTrue(prof["is_pro"])

        def boom(*a, **k):
            raise AssertionError("issiq profil DB'ga murojaat qilmasligi kerak")

        with patch.object(db, "db_cursor", boom):
            self.assertEqual(db.get_user_language(uid), "ru")
            self.assertTrue(db.peek_user_profile(uid)["is_pro"])
            again = db.get_user_profile(uid)
        self.assertEqual(again["lang"], "ru")
        db._profile_invalidate(uid)

    def test_simple_menu_decision_is_cached_after_first_lookup(self):
        """Keshlangan «sodda menyu» qarori uchun DB so'rovi bo'lmasligi kerak."""
        import onboarding as ob_service
        handlers_onboarding = importlib.import_module("handlers.onboarding")
        uid = 555001
        ob_service.cache_simple_menu(uid, False)
        calls = []

        async def fake_run_db(fn, *a, **k):
            calls.append(fn)
            return None

        with patch.object(handlers_onboarding.db, "run_db", new=fake_run_db):
            result = asyncio.run(handlers_onboarding.user_wants_simple_menu(uid))
        self.assertFalse(result)
        self.assertEqual(calls, [], "keshlangan qaror uchun DB so'rovi bo'lmasligi kerak")


class IoExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_executor_is_sized_for_db_pool(self):
        main._install_io_executor()
        loop = asyncio.get_running_loop()
        workers = loop._default_executor._max_workers
        self.assertGreaterEqual(workers, 8)
        self.assertGreaterEqual(workers, db.DB_POOL_MAX)


if __name__ == "__main__":
    unittest.main(verbosity=2)
