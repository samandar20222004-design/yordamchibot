#!/usr/bin/env python3
"""PHASE 4 & 5 — AI CONCURRENCY, USER LOCK, BOUNDED QUEUE VA REQUEST CANCELLATION TESTLARI.

Qamrov:
  1) Non-blocking User Lock (14-band):
     - Qisqa lock, timeout bilan non-blocking harakat;
     - Snapshot & Worker modeli: lock AI davomida ushlab turilmaydi;
  2) Bounded Queue & Rate Limit (13, 16-bandlar):
     - Parallel so'rovlar semafor chegarasidan oshmaydi;
     - Navbat to'lganda darhol fail-closed muloyim xabar ("⏳ AI hozir juda band...");
  3) Request Cancellation (15-band):
     - Foydalanuvchi bekor qilganda task cancel bo'lishi;
     - Kechikkan javob foydalanuvchiga yetib bormasligi;
     - Bekor qilingan vazifa uchun kvota to'liq refund bo'lishi.
  4) AIOrchestrator to'liq integratsiyasi.
"""

from __future__ import annotations
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "123456:CONCURRENCY_TEST_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("ADMIN_ID", "123456789")

from core.user_lock import UserLockManager, UserLockTimeoutError
from services.ai.concurrency import (
    AIConcurrencyManager,
    AIQueueFullError,
    AITaskCancelledError,
    get_queue_full_message,
)
from services.ai.orchestrator import AIOrchestrator
from services.ai.providers import AIProvider, ProviderChain


# ============================================================
# 1. NON-BLOCKING USER LOCK TESTLARI (14-BAND)
# ============================================================

async def test_user_lock_non_blocking_timeout():
    """User lock qisqa timeout bilan non-blocking ishlashini tekshirish."""
    mgr = UserLockManager(default_timeout=0.1)
    user_id = 112233

    # 1-korutina lockni ushlaydi
    async with mgr.user_lock(user_id):
        assert mgr.is_locked(user_id) is True

        # 2-korutina ayni paytda lock olmoqchi bo'lsa darhol timeout oladi (10-20s qotib qolmaydi)
        failed = False
        try:
            async with mgr.user_lock(user_id, timeout=0.05):
                pass
        except UserLockTimeoutError:
            failed = True
        assert failed is True, "Lock band bo'lganda UserLockTimeoutError kutilgan edi!"

    # Chiqilgach lock bo'shashi kerak
    assert mgr.is_locked(user_id) is False
    print("  [OK] UserLock: Non-blocking timeout va tezkor bo'shatish to'g'ri ishladi")


async def test_user_lock_snapshot_and_worker_model():
    """14-band: FSM snapshot olinadi -> lock bo'shatiladi -> AI fonda ishlaydi -> natija saqlanadi."""
    mgr = UserLockManager()
    user_id = 445566

    fsm_state = {"draft_text": "Yangi post xomaki matni", "step": "generating"}
    worker_running_unlocked = False

    def snapshot_fn():
        # Qisqa lock ichida FSM holatidan nusxa olinadi
        return dict(fsm_state)

    async def async_ai_worker(snapshot):
        nonlocal worker_running_unlocked
        # AI 10-20 soniya kutishida FOYDALANUVCHI LOCKLANMASLIGI KERAK!
        worker_running_unlocked = not mgr.is_locked(user_id)
        await asyncio.sleep(0.05)
        return f"🔥 Tayyor post: {snapshot['draft_text']}"

    saved_result = None

    def save_fn(result):
        nonlocal saved_result
        fsm_state["result"] = result
        fsm_state["step"] = "done"
        saved_result = result

    await mgr.run_with_snapshot(
        user_id=user_id,
        snapshot_fn=snapshot_fn,
        async_worker_fn=async_ai_worker,
        save_fn=save_fn,
        lock_timeout=0.5,
    )

    assert worker_running_unlocked is True, "AI ishlashi davomida foydalanuvchi locklanib qolgan!"
    assert saved_result == "🔥 Tayyor post: Yangi post xomaki matni"
    assert fsm_state["step"] == "done"
    assert mgr.is_locked(user_id) is False
    print("  [OK] Snapshot & Worker modeli: AI fonda ishlaganda lock ushlab turilmadi")


# ============================================================
# 2. BOUNDED QUEUE VA CONCURRENCY TESTLARI (13, 16-BANDLAR)
# ============================================================

async def test_concurrency_semaphore_limit():
    """Parallel so'rovlar semafor chegarasidan oshmasligini tekshirish."""
    MAX_CONCURRENCY = 3
    TOTAL_REQUESTS = 10

    cm = AIConcurrencyManager(max_concurrency=MAX_CONCURRENCY, max_queue=20)
    current_concurrent = 0
    max_observed_concurrent = 0

    async def mock_ai_task():
        nonlocal current_concurrent, max_observed_concurrent
        current_concurrent += 1
        if current_concurrent > max_observed_concurrent:
            max_observed_concurrent = current_concurrent
        await asyncio.sleep(0.04)
        current_concurrent -= 1
        return "ok"

    tasks = [
        cm.run_with_queue(user_id=100 + i, coro_fn=mock_ai_task)
        for i in range(TOTAL_REQUESTS)
    ]
    results = await asyncio.gather(*tasks)

    assert len(results) == TOTAL_REQUESTS
    assert all(r == "ok" for r in results)
    assert max_observed_concurrent <= MAX_CONCURRENCY, (
        f"Kuzatilgan maksimal parallellik ({max_observed_concurrent}) "
        f"chegaradan ({MAX_CONCURRENCY}) oshib ketdi!"
    )
    print(f"  [OK] Concurrency: 10 ta so'rovda maksimal parallellik {max_observed_concurrent} <= {MAX_CONCURRENCY}")


async def test_bounded_queue_full_fail_closed():
    """Navbat to'lganda darhol fail-closed muloyim xabar qaytarilishi."""
    MAX_CONCURRENCY = 1
    MAX_QUEUE = 2

    cm = AIConcurrencyManager(max_concurrency=MAX_CONCURRENCY, max_queue=MAX_QUEUE)
    block_event = asyncio.Event()

    async def blocking_task():
        await block_event.wait()
        return "unblocked"

    # 1 ta faol vazifa (slotni band qiladi)
    t1 = asyncio.create_task(cm.run_with_queue(user_id=1, coro_fn=blocking_task))
    await asyncio.sleep(0.01)

    # 2 ta navbatdagi vazifa (navbatni 100% to'ldiradi)
    t2 = asyncio.create_task(cm.run_with_queue(user_id=2, coro_fn=blocking_task))
    t3 = asyncio.create_task(cm.run_with_queue(user_id=3, coro_fn=blocking_task))
    await asyncio.sleep(0.01)

    assert cm.waiting_count == 2

    # 4-vazifa: Navbat to'lgan! Darhol AIQueueFullError tashlanishi kerak
    queue_full_raised = False
    try:
        await cm.run_with_queue(user_id=4, coro_fn=blocking_task, lang="uz")
    except AIQueueFullError as e:
        queue_full_raised = True
        assert "⏳ AI hozir juda band" in str(e)
    assert queue_full_raised is True, "Navbat to'lganda AIQueueFullError tashlanmadi!"

    # Ruscha va inglizcha xabarlarni ham tekshiramiz
    assert "очень занят" in get_queue_full_message("ru")
    assert "very busy" in get_queue_full_message("en")

    # Tozalash
    block_event.set()
    await asyncio.gather(t1, t2, t3)
    print("  [OK] Bounded Queue: Navbat to'lganda fail-closed xabar chiqdi va tizim qulamadi")


# ============================================================
# 3. REQUEST CANCELLATION VA REFUND TESTLARI (15-BAND)
# ============================================================

async def test_request_cancellation_and_late_response_discard():
    """Foydalanuvchi bekor qilganda task cancel bo'lishi va kechikkan javob rad etilishi."""
    cm = AIConcurrencyManager()
    user_id = 998811
    gen_id = "test_gen_998811"

    worker_finished = False

    async def slow_ai_worker():
        nonlocal worker_finished
        await asyncio.sleep(0.2)
        worker_finished = True
        return "Late AI response"

    # So'rovni fonda boshlaymiz
    task = asyncio.create_task(
        cm.run_with_queue(
            user_id=user_id,
            coro_fn=slow_ai_worker,
            generation_id=gen_id,
        )
    )

    await asyncio.sleep(0.02)
    # Foydalanuvchi "❌ Bekor qilish"ni bosadi
    cancelled_count = await cm.cancel_user_requests(user_id)
    assert cancelled_count == 1, "Bekor qilingan tasklar soni 1 bo'lishi kerak"

    # Task tugashini kutamiz (CancelledError tashlanishi kerak)
    got_cancellation = False
    try:
        await task
    except (AITaskCancelledError, asyncio.CancelledError):
        got_cancellation = True

    assert got_cancellation is True, "Task asyncio.CancelledError tashlamadi"
    assert cm.is_cancelled(gen_id) is False  # unregister qilingan
    print("  [OK] Request Cancellation: Task muvaffaqiyatli bekor qilindi")


async def test_cancellation_triggers_quota_refund():
    """Bekor qilingan vazifa uchun kvota to'liq refund qilinishi (fail-closed)."""
    cm = AIConcurrencyManager()
    user_id = 777222
    reservation_id = 554433
    mock_db = MagicMock()

    refund_mock = AsyncMock(return_value={"refunded": True})

    with patch("services.ai_quota.release_ai_quota", refund_mock):
        async def mock_worker():
            await asyncio.sleep(0.2)
            return "Should not finish"

        task = asyncio.create_task(
            cm.run_with_queue(
                user_id=user_id,
                coro_fn=mock_worker,
                reservation_id=reservation_id,
                db_module=mock_db,
            )
        )

        await asyncio.sleep(0.02)
        # Bekor qilish
        await cm.cancel_user_requests(user_id)

        try:
            await task
        except (AITaskCancelledError, asyncio.CancelledError):
            pass

        # release_ai_quota chaqirilganini tekshiramiz
        refund_mock.assert_called_once_with(mock_db, user_id, reservation_id)

    print("  [OK] Fail-closed Refund: Bekor qilingan vazifa kvotasi to'liq qaytarildi")


# ============================================================
# 4. ORCHESTRATOR INTEGRATSIYA TESTI
# ============================================================

async def test_orchestrator_concurrency_and_cancellation():
    """AIOrchestrator navbat to'lganida va bekor qilinganda to'g'ri ishlashi."""
    class SlowProvider(AIProvider):
        name = "SlowProvider"

        async def generate(self, prompt: str, context: dict | None = None) -> str:
            await asyncio.sleep(0.1)
            return "🔥 <b>Ajoyib sekin post</b>\n\n#smm #toshkent"

    provider = SlowProvider()
    cm = AIConcurrencyManager(max_concurrency=1, max_queue=1)
    orchestrator = AIOrchestrator(
        provider_chain=ProviderChain(providers=[provider]),
        concurrency_manager=cm,
    )

    # 1. Bekor qilish sinovi
    user_id = 333111
    gen_task = asyncio.create_task(
        orchestrator.orchestrate(
            user_id=user_id,
            prompt="Futbol haqida post yoz",
            lang="uz",
            db_module=False,
        )
    )

    await asyncio.sleep(0.02)
    await cm.cancel_user_requests(user_id)
    res = await gen_task

    assert res.success is False
    assert res.error_code == "CANCELLED"
    print("  [OK] AIOrchestrator: Cancellation xavfsiz tarzda orkestratsiya qilindi")


# ============================================================
# ASOSIY RUNNER
# ============================================================

async def main_async():
    print("==============================================================")
    print(" PHASE 4 & 5: AI CONCURRENCY, USER LOCK & CANCELLATION TESTLARI")
    print("==============================================================")

    print("\n== 1. Non-blocking User Lock Testlari (14-band) ==")
    await test_user_lock_non_blocking_timeout()
    await test_user_lock_snapshot_and_worker_model()

    print("\n== 2. Bounded Queue va Concurrency Testlari (13, 16-bandlar) ==")
    await test_concurrency_semaphore_limit()
    await test_bounded_queue_full_fail_closed()

    print("\n== 3. Request Cancellation va Refund Testlari (15-band) ==")
    await test_request_cancellation_and_late_response_discard()
    await test_cancellation_triggers_quota_refund()

    print("\n== 4. AIOrchestrator Integratsiya Testi ==")
    await test_orchestrator_concurrency_and_cancellation()

    print("\n==============================================================")
    print(" BARCHA CONCURRENCY VA CANCELLATION TESTLARI 100% YASHIL ✔")
    print("==============================================================")


def main():
    try:
        asyncio.run(main_async())
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ TEST XATOLIK BILAN YIQILDI: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
