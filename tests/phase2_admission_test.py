#!/usr/bin/env python3
"""Phase 2: real PTB dispatch + pre-lock admission, without Telegram/DB I/O.

Run from repo root: python telegram_bot/tests/phase2_admission_test.py
Optional Lua execution coverage: pip install 'fakeredis[lua]'
"""
import asyncio
import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("BOT_TOKEN", "123456:ADMISSION_TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("ADMIN_ID", "123456789")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "telegram_bot"))

from telegram import CallbackQuery, Chat, Message, PhotoSize, Update, User
from datetime import datetime, timezone
from telegram.ext import ApplicationBuilder, TypeHandler

import main
from services import cache_backend as cb
from cache_backend_test import FakeRedisClient

rl = importlib.import_module("middlewares.rate_limiter")


class AdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sequence = 0
        self.backend = cb.MemoryCacheBackend()
        self.limiter = rl.RateLimiter(self.backend)
        self.limiter.enabled = True
        self.middleware = rl.RateLimitMiddleware(self.limiter)
        self.app = (ApplicationBuilder().token(os.environ["BOT_TOKEN"])
                    .application_class(main.GuardedApplication).build())
        # No network: PTB needs initialization only for bot username/logging.
        self.app.bot._bot_user = User(900, "Test Bot", True, username="test_bot")
        self.app._initialized = True
        self.app.add_handler(self.middleware, group=-1)
        self.processed = []
        self.answer = AsyncMock()
        for target, replacement in (
            ("telegram.CallbackQuery.answer", self.answer),
            ("main.check_global_flood", lambda: False),
            ("main.check_rate_limit", lambda *a, **kw: (False, False)),
            ("main.is_duplicate_message", lambda *a, **kw: False),
        ):
            p = patch(target, replacement)
            p.start()
            self.addCleanup(p.stop)
        self.db_call = patch("main.db.run_db", new_callable=AsyncMock)
        self.db_mock = self.db_call.start()
        self.addCleanup(self.db_call.stop)

    def update(self, uid=42, action="menu:home"):
        self.sequence += 1
        query = CallbackQuery(str(self.sequence), User(uid, "User", False),
                              "chat-instance", data=action)
        query.set_bot(self.app.bot)
        return Update(self.sequence, callback_query=query)

    def handler(self, fn=None):
        async def record(update, context):
            self.processed.append(update.update_id)
        self.app.add_handler(TypeHandler(Update, fn or record))

    def assert_clean(self):
        manager = self.app._lock_manager
        self.assertEqual(manager._pending, 0)
        self.assertEqual(manager._pending_by_key, {})
        self.assertEqual(manager._counts, {})
        self.assertEqual(manager._locks, {})
        self.assertIsNone(self.middleware._admitted_update.get())

    async def test_real_ptb_dispatch_counts_once_and_preserves_other_buttons(self):
        self.handler()
        a, duplicate, other, other_user = (
            self.update(), self.update(), self.update(action="menu:back"),
            self.update(uid=43),
        )
        await self.app.process_update(a)
        key = self.limiter.policy("callback").cache_key("42|menu:home")
        self.assertEqual(await self.backend.get(key), "1")
        await self.app.process_update(duplicate)
        await self.app.process_update(other)
        await self.app.process_update(other_user)
        self.assertEqual(self.processed, [a.update_id, other.update_id, other_user.update_id])
        self.answer.assert_awaited_once()
        self.db_mock.assert_not_awaited()
        self.assert_clean()

    async def test_repeat_rejected_before_user_lock_while_other_user_runs(self):
        started, release = asyncio.Event(), asyncio.Event()
        first = self.update()

        async def slow(update, context):
            self.processed.append(update.update_id)
            if update is first:
                started.set()
                await release.wait()

        self.handler(slow)
        task = asyncio.create_task(self.app.process_update(first))
        try:
            await asyncio.wait_for(started.wait(), 1)
            await asyncio.wait_for(self.app.process_update(self.update()), 0.5)
            self.assertEqual(self.app._lock_manager._counts, {"user:42": 1})
            other = self.update(uid=43)
            await asyncio.wait_for(self.app.process_update(other), 0.5)
            self.assertIn(other.update_id, self.processed)
            self.answer.assert_awaited_once()
        finally:
            release.set()
            await task
        self.assert_clean()

    async def test_cancelled_waiter_releases_admission_and_lock_references(self):
        manager = self.app._lock_manager
        first, second = self.update(), self.update(action="menu:back")
        self.handler()
        async with manager.lock("user:42"):
            waiter = asyncio.create_task(self.app.process_update(first))
            # Yield until it has reached the lock; fail deterministically if not.
            for _ in range(100):
                if manager._counts.get("user:42") == 2:
                    break
                await asyncio.sleep(0)
            self.assertEqual(manager._counts["user:42"], 2)
            waiter.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await waiter
            self.assertEqual(manager._counts, {"user:42": 1})
            self.assertEqual(manager._pending, 0)
        await self.app.process_update(second)
        self.assertEqual(self.processed, [second.update_id])
        self.assert_clean()

    async def test_capacity_rejects_before_cache_db_and_locks_even_when_rate_disabled(self):
        self.app._lock_manager = main.UpdateLockManager(max_pending=2, max_per_user=1)
        manager = self.app._lock_manager
        self.limiter.enabled = False
        self.handler()
        self.app.user_data[42]["lang"] = "en"
        with patch.object(self.backend, "incr", new_callable=AsyncMock) as hit:
            async with manager.admit("user:42"):
                await self.app.process_update(self.update())  # per-user full
                self.assertEqual(manager._locks, {})
                async with manager.admit("user:43"):
                    await self.app.process_update(self.update(uid=44))  # global full
                    self.assertEqual(manager._locks, {})
                    self.assertNotIn(44, self.app.user_data)
                other = self.update(uid=44)
                await self.app.process_update(other)
            hit.assert_not_awaited()
        self.assertEqual(self.processed, [other.update_id])
        self.assertEqual(self.answer.await_count, 2)
        from locales.translations import get_text
        self.assertEqual(self.answer.await_args_list[0].args[0], get_text("sys_wait_short", "en"))
        self.db_mock.assert_not_awaited()
        self.assert_clean()

    async def test_default_capacity_preserves_ten_photo_album_and_user_order(self):
        started, release = asyncio.Event(), asyncio.Event()
        updates = [Update(n, message=Message(
            n, datetime.now(timezone.utc), Chat(42, "private"),
            from_user=User(42, "User", False), media_group_id="album",
            photo=[PhotoSize(f"file-{n}", f"unique-{n}", 100, 100)],
        )) for n in range(1, 11)]

        async def album(update, context):
            self.processed.append(update.update_id)
            if update is updates[0]:
                started.set()
                await release.wait()

        self.handler(album)
        tasks = [asyncio.create_task(self.app.process_update(update)) for update in updates]
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertEqual(self.app._lock_manager._pending, 10)
            self.assertEqual(self.processed, [1])
            self.answer.assert_not_awaited()
        finally:
            release.set()
            await asyncio.gather(*tasks)
        self.assertEqual(self.processed, list(range(1, 11)))
        self.assert_clean()

    async def test_cancellation_during_rate_check_returns_capacity(self):
        entered = asyncio.Event()
        async def hang(*args, **kwargs):
            entered.set()
            await asyncio.Event().wait()
        with patch.object(self.backend, "incr", hang):
            task = asyncio.create_task(self.app.process_update(self.update()))
            await asyncio.wait_for(entered.wait(), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assert_clean()

    async def test_capacity_burst_is_bounded_and_cancelled_tasks_free_slots(self):
        manager = main.UpdateLockManager(max_pending=3, max_per_user=1)
        release = asyncio.Event()
        accepted, rejected = [], []

        async def request(uid):
            try:
                async with manager.admit(f"user:{uid}"):
                    accepted.append(uid)
                    await release.wait()
            except main.UpdateAdmissionError:
                rejected.append(uid)

        tasks = [asyncio.create_task(request(uid)) for uid in range(100)]
        await asyncio.sleep(0)
        self.assertEqual(len(accepted), 3)
        self.assertEqual(len(rejected), 97)
        self.assertEqual(manager._pending, 3)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.assertEqual(manager._pending, 0)
        self.assertEqual(manager._pending_by_key, {})

    async def test_handler_timeout_returns_slot(self):
        async def slow(update, context):
            await asyncio.Event().wait()
        self.handler(slow)
        with patch("main.UPDATE_HANDLER_TIMEOUT_SECONDS", 0.01), \
                patch.object(main.GuardedApplication, "_answer_timeout", new_callable=AsyncMock) as answer:
            await self.app.process_update(self.update())
            answer.assert_awaited_once()
        self.assert_clean()

    async def test_handler_exception_returns_slot(self):
        error = AsyncMock()
        async def broken(update, context):
            raise RuntimeError("test failure")
        self.handler(broken)
        self.app.add_error_handler(error)
        await self.app.process_update(self.update())
        error.assert_awaited_once()
        self.assert_clean()

    async def test_backend_hang_is_bounded_fail_open(self):
        self.handler()
        async def hang(*a, **kw):
            await asyncio.Event().wait()
        original = rl._cfg
        def config(name, default):
            return 0.1 if name == "REDIS_SOCKET_TIMEOUT" else original(name, default)
        with patch.object(self.backend, "incr", hang), patch.object(rl, "_cfg", config):
            update = self.update()
            await asyncio.wait_for(self.app.process_update(update), 0.5)
        self.assertEqual(self.processed, [update.update_id])
        self.assert_clean()

    async def test_marker_does_not_bypass_other_updates_or_survive_in_child(self):
        first, second = self.update(), self.update()
        release = asyncio.Event()
        async def child():
            await release.wait()
            return await self.middleware.process_update(first)
        async with self.middleware.admission(first) as admitted:
            self.assertTrue(admitted)
            self.assertFalse(await self.middleware.process_update(first))
            self.assertTrue(await self.middleware.process_update(second))
            task = asyncio.create_task(child())
        release.set()
        self.assertTrue(await task)  # inherited marker invalidated on scope exit
        self.assertIsNone(self.middleware._admitted_update.get())


class RedisAtomicTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_command_fixed_window_and_orphan_repair(self):
        client = FakeRedisClient()
        backend = cb.RedisCacheBackend(client, key_prefix="test")
        self.assertEqual(await backend.incr("counter", ttl=5), 1)
        self.assertEqual(client.calls, ["eval"])
        self.assertEqual(await backend.incr("counter", ttl=99), 2)
        self.assertEqual(client.ttls["test:counter"], 5)
        # An old deployment can leave INCR without EXPIRE.
        client.values["test:orphan"] = "9"
        self.assertEqual(await backend.incr("orphan", ttl=7), 10)
        self.assertEqual(client.ttls["test:orphan"], 7)
        # Returning to zero must not extend an existing window.
        await backend.incr("counter", ttl=99, amount=-2)
        self.assertEqual(client.ttls["test:counter"], 5)
        await backend.incr("persistent", amount=2)
        self.assertNotIn("test:persistent", client.ttls)

    async def test_eval_failure_uses_existing_resilient_fallback(self):
        client = FakeRedisClient(fail=True)
        resilient = cb.ResilientCacheBackend(cb.RedisCacheBackend(client),
                                             cb.MemoryCacheBackend(), failure_threshold=1)
        self.assertEqual(await resilient.incr("counter", ttl=5), 1)
        self.assertTrue(resilient.circuit_open)
        self.assertEqual(await resilient.incr("counter", ttl=5), 2)

    async def test_lua_execution_two_clients_share_counter(self):
        try:
            from fakeredis.aioredis import FakeRedis
            import fakeredis
            import lupa  # noqa: F401 — required by fakeredis Lua execution
        except ImportError:
            self.skipTest("Optional fakeredis[lua] not installed; command contract still tested")
        server = fakeredis.FakeServer()
        clients = [FakeRedis(server=server), FakeRedis(server=server)]
        backends = [cb.RedisCacheBackend(client, key_prefix="phase2") for client in clients]
        try:
            counts = await asyncio.gather(*[
                backends[n % 2].incr("shared", ttl=60) for n in range(100)
            ])
            self.assertEqual(sorted(counts), list(range(1, 101)))
            ttl = await clients[0].pttl("phase2:shared")
            self.assertGreater(ttl, 0)
            await backends[1].incr("shared", ttl=120)
            self.assertLessEqual(await clients[0].pttl("phase2:shared"), ttl)
            await clients[0].set("phase2:orphan", "12")
            self.assertEqual(await backends[1].incr("orphan", ttl=7), 13)
            self.assertGreater(await clients[0].pttl("phase2:orphan"), 0)
            limiter_a, limiter_b = (rl.RateLimiter(b) for b in backends)
            self.assertTrue(await limiter_a.allow_callback(42, "menu"))
            self.assertFalse(await limiter_b.allow_callback(42, "menu"))
        finally:
            for backend in backends:
                await backend.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
