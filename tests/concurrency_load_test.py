#!/usr/bin/env python3
"""PHASE 13 — YUKLAMA VA KONKURENTLIK TESTI (39-band).

Bu suite PostAssist V2 ni **haqiqiy yuk** ostida sinaydi. Maqsad — "bir
foydalanuvchi, bir so'rov" unit-testlaridan farqli o'laroq, **bir vaqtning
o'zida 10 / 25 / 50 ta virtual foydalanuvchi** (va muhit ko'tarsa 100 ta)
oqimini yuritib, quyidagilarni isbotlash:

1. **Parallel virtual foydalanuvchilar oqimi** — har biri to'liq AI oqimini
   bosib o'tadi: ``services.ai_quota.reserve_ai_quota`` (Phase 2 atomik bron)
   → ``AIOrchestrator.orchestrate`` → ``AIConcurrencyManager.run_with_queue``
   (bounded queue + semafor) → provayder → ``utils.telegram_sanitizer``.
   Ya'ni test **haqiqiy kod yo'lini** yuradi, parallel AI quyi tizimini
   o'ylab topmaydi.

2. **Bounded queue to'lganda tizim xavfsizligi** — navbat to'lib ketganda
   so'rov fail-closed rad etiladi (``QUEUE_FULL``), bron qilingan kvota/kredit
   **to'liq qaytariladi** va menejer ichida hech qanday iz (task, slot,
   metadata) qolmaydi.

3. **Resurslar oqib ketmasligi** — asyncio task leak, DB ulanish (pool) leak,
   thread leak va RSS o'sishi har bir ssenariydan keyin o'lchanadi.

4. **DB tranzaksiyalari parallel oqimlarda deadlock bermaydi** — kvota bron
   qilish, Stars to'lovi (idempotency), referral bonusi va promo-kod
   faollashtirish **bitta aralash yuk** ostida (50 thread, DB_POOL_MAX=5)
   yuritiladi: deadlock yo'q, pool starvation yo'q, hisob-kitob aniq.

Muhit cheklovi
--------------
Agar muhit 100 ta virtual foydalanuvchini ko'tara olmasa (CPU / RAM /
PostgreSQL mavjud emas), bu **yashirilmaydi**: tegishli qism aniq
``NOT TESTED — resource limit`` deb qayd etiladi va suite yiqilmaydi
(lekin ``[FAIL]`` ham bosilmaydi — 57-band: soxta PASS taqiqlanadi).

Ishga tushirish::

    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh
    # yoki alohida:
    python tests/concurrency_load_test.py
"""

from __future__ import annotations

import asyncio
import gc
import os
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegram_bot"))
sys.path.insert(0, str(ROOT))

# ---- MUHIM: database/config import qilinishidan OLDIN env sozlash --------
os.environ.setdefault("BOT_TOKEN", "123456:CONCURRENCY_LOAD_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
# Render Free / Neon pool cheklovini AYNAN taqlid qilamiz: 5 ta ulanish bilan
# 50 ta parallel so'rov starvation/deadlock bermasligi kerak.
os.environ.setdefault("DB_POOL_MIN", "0")
os.environ.setdefault("DB_POOL_MAX", "5")

import config  # noqa: E402

PASS = 0
FAIL = 0
NOT_TESTED: list[tuple[str, str]] = []


def check(name: str, cond: bool, extra: str = "") -> bool:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")
    return bool(cond)


def not_tested(name: str, reason: str) -> None:
    NOT_TESTED.append((name, reason))
    print(f"  [NOT TESTED] {name} — {reason}")


def header(title: str) -> None:
    print()
    print("=" * 64)
    print(f" {title}")
    print("=" * 64)


# ============================================================
# 0. MUHIT IMKONIYATLARINI ANIQLASH (39-band: "resource limit" shaffofligi)
# ============================================================

def _cpu_count() -> int:
    try:
        return int(os.cpu_count() or 1)
    except Exception:
        return 1


def _available_memory_mb() -> float:
    """/proc/meminfo dagi MemAvailable (Linux); bo'lmasa -1."""
    try:
        with open("/proc/meminfo", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        return -1.0
    return -1.0


def _rss_mb() -> float:
    """Joriy jarayonning RSS (VmRSS), MB. O'lchanmasa -1."""
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        return -1.0
    return -1.0


ENV: dict = {}


def detect_environment() -> None:
    ENV["cpus"] = _cpu_count()
    ENV["mem_available_mb"] = round(_available_memory_mb(), 1)
    ENV["rss_start_mb"] = round(_rss_mb(), 1)
    ENV["db_pool_max"] = int(getattr(config, "DB_POOL_MAX", 5))
    ENV["full_load_users"] = int(os.getenv("LOAD_TEST_FULL_USERS", "100"))
    # 100 ta virtual foydalanuvchi uchun minimal talab: 2+ yadro va 900+ MB
    # bo'sh xotira. Pastida — "NOT TESTED — resource limit" (yashirilmaydi).
    ENV["can_full_load"] = (
        ENV["cpus"] >= 2
        and (ENV["mem_available_mb"] < 0 or ENV["mem_available_mb"] >= 900.0)
    )


# ============================================================
# REAL POSTGRESQL (pgserver yoki URL) — bo'lmasa DB qismi NOT TESTED
# ============================================================

_local_server: list = []
_db = None  # haqiqiy `database` moduli (live bo'lsa)


def _live_uri() -> str | None:
    for var in ("LOAD_TEST_DATABASE_URL", "STRESS_TEST_DATABASE_URL",
                "P0_TEST_DATABASE_URL", "INTEGRITY_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url
    url = os.getenv("DATABASE_URL")
    if url and "user:pass" not in url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    if _local_server:
        return _local_server[0].get_uri()
    try:
        server = pgserver.get_server(
            os.path.join(tempfile.gettempdir(), "yordamchi_pg_load39"))
    except Exception as exc:  # pragma: no cover - muhitga bog'liq
        print(f"  [WARN] pgserver ishga tushmadi: {type(exc).__name__}: {exc}")
        return None
    _local_server.append(server)
    return server.get_uri()


def bootstrap_db():
    """Haqiqiy PostgreSQL'ga ulanadi; muvaffaqiyatsiz bo'lsa ``None``."""
    global _db
    uri = _live_uri()
    if not uri:
        return None
    import database as db_mod
    db_mod.DATABASE_URL = uri
    os.environ["DATABASE_URL"] = uri
    db_mod._reset_pool()
    try:
        db_mod.init_db()
    except Exception as exc:  # pragma: no cover - muhitga bog'liq
        print(f"  [WARN] PostgreSQL init_db xatosi: {type(exc).__name__}: {exc}")
        return None
    try:
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
    except Exception as exc:
        print(f"  [WARN] PostgreSQL ping xatosi: {type(exc).__name__}: {exc}")
        return None
    _db = db_mod
    return db_mod


# ============================================================
# YORDAMCHILAR
# ============================================================

# Alohida ID diapazoni — boshqa suite'larga tegmaydi.
BASE = 96000000
SCENARIO_OFFSET = 100000


def _exec_sql(sql: str, params=None, commit: bool = False):
    with _db.db_cursor(commit=commit) as cur:
        cur.execute(sql, params or ())
        try:
            return cur.fetchall()
        except Exception:
            return []


def _scalar(sql: str, params=None, default=0):
    rows = _exec_sql(sql, params)
    if not rows:
        return default
    return rows[0][0]


def _insert_returning_id(sql: str, params=None) -> int:
    """``INSERT ... RETURNING id`` — MAJBURIY commit bilan (aks holda
    ``db_cursor(commit=False)`` yozuvni ROLLBACK qilib yuboradi)."""
    with _db.db_cursor(commit=True) as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
    return int(row[0]) if row else 0


def seed_users(user_ids, credits: int = 3, plan: str = "free",
               requests_today: int = 0) -> None:
    """Virtual foydalanuvchilarni bazada yaratadi (idempotent, toza holat)."""
    ids = list(user_ids)
    with _db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM ai_reservations WHERE user_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (ids,))
        for uid in ids:
            cur.execute(
                "INSERT INTO users (user_id, username, plan_type, ai_credits, "
                "ai_requests_today, created_at) "
                "VALUES (%s, %s, %s, %s, %s, NOW()) "
                "ON CONFLICT (user_id) DO UPDATE SET plan_type = EXCLUDED.plan_type, "
                "ai_credits = EXCLUDED.ai_credits, "
                "ai_requests_today = EXCLUDED.ai_requests_today, "
                "subscription_expires_at = NULL, referrer_id = NULL",
                (uid, f"load_{uid}", plan, credits, requests_today),
            )
    for uid in ids:
        _db._invalidate_user(uid)


def cleanup_users(user_ids) -> None:
    ids = list(user_ids)
    if not ids:
        return
    try:
        with _db.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM promo_redemptions WHERE user_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM payments WHERE user_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM payment_receipts WHERE user_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM ai_reservations WHERE user_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (ids,))
    except Exception as exc:  # noqa: BLE001 — tozalash ixtiyoriy
        print(f"  [WARN] tozalash xatosi: {type(exc).__name__}: {exc}")


def _pool_state() -> dict:
    """DB pool holati (ulanishlar qaytganini tekshirish uchun)."""
    try:
        return dict(_db.get_db_pool_status())
    except Exception:
        return {}


def _thread_count() -> int:
    return threading.active_count()


def _task_count() -> int:
    return len([t for t in asyncio.all_tasks() if not t.done()])


# ============================================================
# 1. PARALLEL VIRTUAL FOYDALANUVCHILAR (10 / 25 / 50 / 100)
# ============================================================

class LoadProvider:
    """Deterministik, kechikishli AI provayder (tashqi API'ga chiqmaydi).

    ``AIProvider`` kontraktiga mos: ``generate(prompt, context) -> str`` va
    ``is_available() -> bool``. Parallellikni o'lchash uchun faol chaqiruvlar
    sonini hisoblab boradi.
    """

    name = "LoadMock"

    def __init__(self, latency: float = 0.02):
        self.latency = latency
        self.calls = 0
        self.active = 0
        self.max_active = 0

    def is_available(self) -> bool:
        return True

    async def generate(self, prompt: str, context=None) -> str:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(self.latency)
        finally:
            self.active -= 1
        ctx = context or {}
        return (
            "🔥 <b>Yangi post sarlavhasi</b>\n"
            f"✅ Birinchi qimmatli punkt (intent: {ctx.get('intent', 'n/a')})\n"
            "✅ Ikkinchi amaliy punkt — raqam va fakt bilan\n"
            "✅ Uchinchi punkt — mijoz tajribasidan misol\n\n"
            "👉 Hoziroq sinab ko'ring va natijani izohda yozing!\n\n"
            "#kontent #smm #postassist"
        )


def _user_ids(scenario: str, count: int) -> list[int]:
    base = BASE + abs(hash(scenario)) % SCENARIO_OFFSET
    base = base - (base % 1000)
    return [base + i for i in range(count)]


async def _run_ai_load(n_users: int, *, max_concurrency: int, max_queue: int,
                       queue_timeout: float, latency: float,
                       credits_per_user: int, requests_today: int = 0,
                       arrival_window: float = 0.0, label: str = "ai"):
    """``n_users`` ta virtual foydalanuvchini parallel yuritadi.

    ``arrival_window > 0`` bo'lsa foydalanuvchilar shu vaqt oralig'ida
    **tarkaqab** keladi (real trafik taqlidi); ``0`` bo'lsa hammasi BIR
    LAHZADA tushadi (burst — bounded queue to'ldiriladi).

    Qaytadi: (natijalar, provider, concurrency_manager, ids, o'lchovlar).
    """
    from services.ai.concurrency import AIConcurrencyManager
    from services.ai.orchestrator import AIOrchestrator
    from services.ai.providers import ProviderChain

    ids = _user_ids(f"{label}{n_users}c{max_concurrency}q{max_queue}", n_users)
    seed_users(ids, credits=credits_per_user, requests_today=requests_today)

    provider = LoadProvider(latency=latency)
    cm = AIConcurrencyManager(max_concurrency=max_concurrency,
                              max_queue=max_queue,
                              queue_timeout=queue_timeout)
    orchestrator = AIOrchestrator(provider_chain=ProviderChain([provider]),
                                  concurrency_manager=cm)

    baseline_tasks = _task_count()
    rss_before = _rss_mb()

    async def virtual_user(uid: int, delay: float):
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            return await orchestrator.orchestrate(
                user_id=uid,
                prompt="Menga mahsulotim haqida sotuvchi post yozib ber",
                lang="uz",
                context={},
                db_module=_db,
            )
        except Exception as exc:  # noqa: BLE001 — foydalanuvchi javobsiz qolmasin
            return type("R", (), {"success": False,
                                  "error_code": f"UNCAUGHT:{type(exc).__name__}",
                                  "error": str(exc),
                                  "reservation_id": None})()

    step = arrival_window / n_users if (arrival_window and n_users) else 0.0
    started = time.monotonic()
    results = await asyncio.gather(
        *(virtual_user(uid, step * i) for i, uid in enumerate(ids)))
    elapsed = time.monotonic() - started

    # Event loop'ga tugallanmagan task'larni yig'ish imkonini beramiz.
    await asyncio.sleep(0)
    gc.collect()

    measures = {
        "elapsed": elapsed,
        "leaked_tasks": _task_count() - baseline_tasks,
        "rss_delta_mb": round(_rss_mb() - rss_before, 2) if rss_before >= 0 else None,
        "baseline_tasks": baseline_tasks,
    }
    return results, provider, cm, ids, measures


def run_load(n_users: int, **kw):
    """``_run_ai_load`` ni ``asyncio.run`` orqali yuritadi.

    Thread o'lchovi SHU YERDA (event loop yopilgandan keyin) olinadi — chunki
    ``asyncio.to_thread`` ning default executor threadlari loop yopilguncha
    tirik turadi; loop ichida o'lchash soxta "leak" berardi.
    """
    threads_before = _thread_count()
    out = asyncio.run(_run_ai_load(n_users, **kw))
    results, provider, cm, ids, measures = out
    gc.collect()
    measures["leaked_threads"] = _thread_count() - threads_before
    return results, provider, cm, ids, measures


def _result_summary(results) -> dict:
    out = {"success": 0, "queue_full": 0, "quota": 0, "db_error": 0,
           "cancelled": 0, "other": {}}
    for res in results:
        if getattr(res, "success", False):
            out["success"] += 1
            continue
        code = str(getattr(res, "error_code", "") or "")
        if code == "QUEUE_FULL":
            out["queue_full"] += 1
        elif code in ("QUOTA_EXCEEDED",):
            out["quota"] += 1
        elif code == "DB_ERROR":
            out["db_error"] += 1
        elif code == "CANCELLED":
            out["cancelled"] += 1
        else:
            out["other"][code] = out["other"].get(code, 0) + 1
    return out


def _manager_clean(cm) -> dict:
    return {
        "active_slots": getattr(cm, "_active_slots", None),
        "waiting_count": getattr(cm, "_waiting_count", None),
        "tracked_users": len(getattr(cm, "_user_tasks", {}) or {}),
        "task_metadata": len(getattr(cm, "_task_metadata", {}) or {}),
        "cancelled_generations": len(getattr(cm, "_cancelled_generations", set()) or set()),
    }


def run_ai_load_scenario(n_users: int, *, max_concurrency: int, max_queue: int,
                         queue_timeout: float = 20.0, latency: float = 0.02,
                         credits_per_user: int = 3,
                         arrival_window: float = 0.6,
                         expect_all_served: bool = True,
                         scenario: str = "ai",
                         label: str | None = None) -> None:
    label = label or f"{n_users} ta parallel virtual foydalanuvchi"
    print(f"\n-- {label} "
          f"(MAX_AI_CONCURRENCY={max_concurrency}, MAX_AI_QUEUE={max_queue}, "
          f"kelish oralig'i={arrival_window}s) --")

    ids = _user_ids(f"{scenario}{n_users}c{max_concurrency}q{max_queue}", n_users)
    results, provider, cm, ids, m = run_load(
        n_users, max_concurrency=max_concurrency, max_queue=max_queue,
        queue_timeout=queue_timeout, latency=latency,
        credits_per_user=credits_per_user, arrival_window=arrival_window,
        label=scenario)
    summary = _result_summary(results)

    # 1) Har bir virtual foydalanuvchi JAVOB oldi (crash / javobsiz qolish yo'q)
    check(f"{label}: {n_users} ta natija qaytdi", len(results) == n_users,
          f"{len(results)} != {n_users}")
    check(f"{label}: kutilmagan (UNCAUGHT) xato yo'q", not summary["other"],
          str(summary["other"]))
    check(f"{label}: DB xatosi (DB_ERROR) yo'q", summary["db_error"] == 0,
          f"db_error={summary['db_error']}")

    # 2) Parallellik chegarasi hech qachon buzilmadi
    check(f"{label}: kuzatilgan parallellik {provider.max_active} <= {max_concurrency}",
          provider.max_active <= max_concurrency,
          f"max_active={provider.max_active}")
    check(f"{label}: barcha so'rovlar provaydergacha yetib bordi",
          provider.calls == summary["success"],
          f"calls={provider.calls} success={summary['success']}")

    # 3) Bounded queue: rad etilganlar faqat QUEUE_FULL yoki kvota sababli
    allowed_failures = summary["queue_full"] + summary["quota"]
    check(f"{label}: rad etilganlar faqat QUEUE_FULL/kvota "
          f"(queue_full={summary['queue_full']}, quota={summary['quota']})",
          summary["success"] + allowed_failures == n_users,
          str(summary))
    if expect_all_served:
        check(f"{label}: real trafikda barcha {n_users} foydalanuvchi javob oldi "
              f"(rad etilgan 0)",
              summary["success"] == n_users, str(summary))

    # 4) Menejer ichida hech qanday iz qolmadi (task/slot/metadata leak yo'q)
    state = _manager_clean(cm)
    check(f"{label}: concurrency manager toza (active=0, waiting=0, tracked=0)",
          state["active_slots"] == 0 and state["waiting_count"] == 0
          and state["tracked_users"] == 0 and state["task_metadata"] == 0
          and state["cancelled_generations"] == 0,
          str(state))

    # 5) asyncio task / thread / RSS leak yo'q
    check(f"{label}: asyncio task leak yo'q", m["leaked_tasks"] <= 0,
          f"leaked_tasks={m['leaked_tasks']}")
    check(f"{label}: thread leak yo'q", m["leaked_threads"] <= 0,
          f"leaked_threads={m['leaked_threads']}")

    # 6) DB hisob-kitobi: bron = muvaffaqiyat + qaytarilgan (QUEUE_FULL refund)
    total_rows = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = ANY(%s)", (ids,)))
    refunded = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = ANY(%s) "
        "AND status = 'refunded'", (ids,)))
    active = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = ANY(%s) "
        "AND status = 'active'", (ids,)))
    refund_ledger = int(_scalar(
        "SELECT COUNT(*) FROM credits_ledger WHERE user_id = ANY(%s) "
        "AND operation_type = 'ai_refund'", (ids,)))
    credit_refunded = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations r WHERE r.user_id = ANY(%s) "
        "AND r.status = 'refunded' AND r.source = 'credit'", (ids,)))

    check(f"{label}: bron qatorlari = muvaffaqiyat + rad "
          f"({total_rows} = {summary['success']} + {summary['queue_full']})",
          total_rows == summary["success"] + summary["queue_full"],
          f"rows={total_rows} summary={summary}")
    check(f"{label}: QUEUE_FULL bronlari qaytarildi (refunded={refunded})",
          refunded == summary["queue_full"],
          f"refunded={refunded} queue_full={summary['queue_full']}")
    check(f"{label}: 'active' bronlar = muvaffaqiyatli so'rovlar",
          active == summary["success"], f"active={active}")
    check(f"{label}: kredit refund auditi ledger'da "
          f"(ai_refund={refund_ledger}, credit-source={credit_refunded})",
          refund_ledger == credit_refunded,
          f"ledger={refund_ledger} credit_refunded={credit_refunded}")

    # 7) Balans hech qachon manfiy bo'lmaydi va yechuvlar soni bilan mos
    negative = int(_scalar(
        "SELECT COUNT(*) FROM users WHERE user_id = ANY(%s) AND ai_credits < 0",
        (ids,)))
    check(f"{label}: manfiy kredit balansi yo'q", negative == 0,
          f"negative={negative}")
    total_spent = int(_scalar(
        "SELECT COALESCE(SUM(cost), 0) FROM ai_reservations "
        "WHERE user_id = ANY(%s) AND status = 'active'", (ids,)))
    quota_spent = int(_scalar(
        "SELECT COALESCE(SUM(ai_requests_today), 0) FROM users "
        "WHERE user_id = ANY(%s)", (ids,)))
    credit_spent = int(_scalar(
        "SELECT COALESCE(SUM(cost), 0) FROM ai_reservations "
        "WHERE user_id = ANY(%s) AND status = 'active' AND source = 'credit'",
        (ids,)))
    check(f"{label}: kunlik kvota + kredit yechuvi umumiy bron bilan mos "
          f"({quota_spent} + {credit_spent} = {total_spent})",
          quota_spent + credit_spent == total_spent,
          f"quota={quota_spent} credit={credit_spent} total={total_spent}")

    # 8) DB ulanishlari qaytdi (pool leak yo'q)
    pool = _pool_state()
    check(f"{label}: DB pool'da band ulanish qolmadi",
          int(pool.get("used", 0) or 0) == 0, str(pool))

    print(f"  ↳ {n_users} user / {summary['success']} success / "
          f"{summary['queue_full']} queue_full / {summary['quota']} quota "
          f"— {m['elapsed']:.2f}s, RSS Δ={m['rss_delta_mb']} MB")

    cleanup_users(ids)


# ============================================================
# 2. BOUNDED QUEUE TO'LGANDA XAVFSIZLIK (fail-closed + to'liq refund)
# ============================================================

def run_semaphore_saturation_test(n_users: int = 50, max_concurrency: int = 5,
                                  max_queue: int = 60) -> None:
    """Semafor chegarasi **aynan** ushlanishini isbotlaydi.

    Barcha foydalanuvchilar bir lahzada tushadi, lekin navbat sig'imi
    yetarli (``max_queue`` katta) — hech kim rad etilmaydi va shu sababli
    kuzatilgan maksimal parallellik AYNAN ``max_concurrency`` ga teng
    bo'lishi shart (``<=`` emas, ``==``). Bu bounded queue'ning asosiy
    kafolati: ortiqcha parallel AI chaqiruvi provayderga chiqmaydi.
    """
    print(f"\n-- Semafor to'yintirilishi: {n_users} user bir lahzada, "
          f"MAX_AI_CONCURRENCY={max_concurrency}, MAX_AI_QUEUE={max_queue} --")
    results, provider, cm, ids, m = run_load(
        n_users, max_concurrency=max_concurrency, max_queue=max_queue,
        queue_timeout=60.0, latency=0.03, credits_per_user=3,
        arrival_window=0.0, label="sem_sat")
    summary = _result_summary(results)

    check("semafor: hech kim rad etilmadi (navbat sig'imi yetarli)",
          summary["queue_full"] == 0 and summary["quota"] == 0, str(summary))
    check(f"semafor: barcha {n_users} so'rov bajarildi",
          summary["success"] == n_users, str(summary))
    check(f"semafor: kuzatilgan maksimal parallellik AYNAN {max_concurrency} "
          f"(<= emas, ==)", provider.max_active == max_concurrency,
          f"max_active={provider.max_active}")
    check("semafor: menejer toza", _manager_clean(cm)["active_slots"] == 0,
          str(_manager_clean(cm)))
    check("semafor: asyncio task leak yo'q", m["leaked_tasks"] <= 0, str(m))
    print(f"  ↳ {summary['success']}/{n_users} bajarildi, "
          f"peak parallellik={provider.max_active} — {m['elapsed']:.2f}s")
    cleanup_users(ids)


def run_queue_saturation_test(n_users: int = 50) -> None:
    print(f"\n-- Bounded queue to'ldirish: {n_users} user, "
          f"MAX_AI_QUEUE=3, MAX_AI_CONCURRENCY=1 --")
    from services.ai.concurrency import get_queue_full_message

    ids = _user_ids("queue_sat", n_users)
    # Hammasi BIR LAHZADA tushadi (arrival_window=0) va kechikish katta:
    # bounded queue albatta to'ladi va fail-closed rad javobi beriladi.
    results, provider, cm, ids, m = run_load(
        n_users, max_concurrency=1, max_queue=3, queue_timeout=30.0,
        latency=0.03, credits_per_user=3, arrival_window=0.0,
        label="queue_sat")
    summary = _result_summary(results)

    check("queue saturation: kamida bitta QUEUE_FULL rad javobi bo'ldi",
          summary["queue_full"] > 0, str(summary))
    check("queue saturation: hech qanday so'rov javobsiz qolmadi",
          len(results) == n_users)
    check("queue saturation: tizim xatosi (DB_ERROR/UNCAUGHT) yo'q",
          summary["db_error"] == 0 and not summary["other"], str(summary))

    # Rad etilgan foydalanuvchi UCH TILDA ham muloyim xabar oladi
    msgs = {lang: get_queue_full_message(lang) for lang in ("uz", "ru", "en")}
    check("queue saturation: QUEUE_FULL xabari 3 tilda ham mavjud",
          "⏳" in msgs["uz"] and "занят" in msgs["ru"] and "busy" in msgs["en"],
          str(msgs))
    failed = [r for r in results if not getattr(r, "success", False)
              and getattr(r, "error_code", "") == "QUEUE_FULL"]
    check("queue saturation: rad javobida foydalanuvchiga matn bor",
          all("⏳" in str(getattr(r, "error", "")) for r in failed),
          str([getattr(r, "error", "") for r in failed[:2]]))

    refunded = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = ANY(%s) "
        "AND status = 'refunded'", (ids,)))
    active = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = ANY(%s) "
        "AND status = 'active'", (ids,)))
    check("queue saturation: barcha QUEUE_FULL bronlari qaytarildi "
          f"(refunded={refunded} == queue_full={summary['queue_full']})",
          refunded == summary["queue_full"],
          f"refunded={refunded} queue_full={summary['queue_full']}")
    check("queue saturation: 'active' bron = muvaffaqiyatli so'rov "
          f"({active} == {summary['success']})",
          active == summary["success"], f"active={active}")

    # Rad etilgan foydalanuvchining balansi/kvotasi BUTUN qaytdi
    broken = int(_scalar(
        "SELECT COUNT(*) FROM users u WHERE u.user_id = ANY(%s) "
        "AND u.ai_credits < 0", (ids,)))
    check("queue saturation: manfiy balans qolmadi", broken == 0, str(broken))

    state = _manager_clean(cm)
    check("queue saturation: menejer toza (task/slot leak yo'q)",
          state["active_slots"] == 0 and state["waiting_count"] == 0
          and state["tracked_users"] == 0 and state["task_metadata"] == 0,
          str(state))
    check("queue saturation: asyncio task leak yo'q", m["leaked_tasks"] <= 0,
          str(m))
    pool = _pool_state()
    check("queue saturation: DB pool toza",
          int(pool.get("used", 0) or 0) == 0, str(pool))
    print(f"  ↳ {summary['success']} bajarildi, {summary['queue_full']} "
          f"fail-closed rad etildi, {summary['quota']} kvota rad — "
          f"{m['elapsed']:.2f}s")
    cleanup_users(ids)


# ============================================================
# 3. DB TRANZAKSIYALARI PARALLEL OQIMLARDA (deadlock yo'q)
# ============================================================

def _run_threads(jobs, workers: int, timeout: float):
    """Thread pool'da parallel ishlatadi; timeout'da (deadlock) xato qaytadi."""
    errors: list[str] = []
    results = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(job) for job in jobs]
        try:
            for fut in futures:
                results.append(fut.result(timeout=timeout))
        except FutureTimeout:
            errors.append(f"TIMEOUT after {timeout}s (deadlock/lock-wait shubhasi)")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    return results, errors, time.monotonic() - started


def test_parallel_quota_reservation() -> None:
    print("\n-- DB: 50 parallel kvota bron (bitta user, kvota=5, kredit=0) --")
    uid = BASE + 910001
    seed_users([uid], credits=0, requests_today=0)
    max_ai = int(config.PLAN_LIMITS["free"]["daily_ai_requests"])

    results, errors, elapsed = _run_threads(
        [lambda: _db.reserve_ai_request(uid, "magic_post", 1) for _ in range(50)],
        workers=50, timeout=90.0)

    allowed = [r for r in results if isinstance(r, dict) and r.get("allowed")]
    denied = [r for r in results if isinstance(r, dict) and not r.get("allowed")]
    check(f"kvota race: deadlock/timeout yo'q ({elapsed:.1f}s)", not errors,
          str(errors[:2]))
    check(f"kvota race: AYNAN {max_ai} ta ruxsat (50 parallel so'rovda)",
          len(allowed) == max_ai, f"allowed={len(allowed)} max_ai={max_ai}")
    check("kvota race: qolganlari rad etildi",
          len(denied) == 50 - max_ai, f"denied={len(denied)}")
    check("kvota race: DB xatosi (db_error) yo'q",
          not [r for r in denied if r.get("reason") == "db_error"],
          str([r.get("reason") for r in denied[:5]]))
    used = int(_scalar("SELECT ai_requests_today FROM users WHERE user_id = %s",
                       (uid,)))
    check(f"kvota race: sanagich limitdan oshmadi (ai_requests_today={used})",
          used == max_ai, f"used={used}")
    rows = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations WHERE user_id = %s", (uid,)))
    check("kvota race: bron qatorlari = ruxsatlar soni", rows == len(allowed),
          f"rows={rows}")

    # Parallel REFUND — idempotent (aynan 1 marta qaytadi)
    res_id = allowed[0]["reservation_id"]
    ref_results, ref_errors, _ = _run_threads(
        [lambda: _db.refund_ai_request(uid, res_id) for _ in range(10)],
        workers=10, timeout=60.0)
    refunded_ok = [r for r in ref_results
                   if isinstance(r, dict) and r.get("success")
                   and r.get("reason") == "refunded"]
    already = [r for r in ref_results
               if isinstance(r, dict) and r.get("reason") == "already_refunded"]
    check("refund race: deadlock yo'q", not ref_errors, str(ref_errors[:2]))
    check("refund race: AYNAN 1 marta qaytarildi", len(refunded_ok) == 1,
          f"refunded={len(refunded_ok)}")
    check("refund race: qolgan 9 tasi 'already_refunded'", len(already) == 9,
          f"already={len(already)}")
    used_after = int(_scalar(
        "SELECT ai_requests_today FROM users WHERE user_id = %s", (uid,)))
    check("refund race: kvota AYNAN 1 ga kamaydi",
          used_after == max_ai - 1, f"used_after={used_after}")
    cleanup_users([uid])


def test_parallel_payments() -> None:
    print("\n-- DB: 25 parallel Stars to'lov (bitta charge_id) + "
          "25 parallel karta chek tasdiqlash --")
    from services.payment_service import PaymentService

    uid = BASE + 920001
    admin_id = int(os.environ["ADMIN_ID"])
    seed_users([uid], credits=0)
    charge = f"load39-charge-{uuid.uuid4().hex[:12]}"

    results, errors, elapsed = _run_threads(
        [lambda: PaymentService.process_stars_payment(
            uid, charge, 75, f"sub_stars_1m_{uid}", "pro", 30) for _ in range(25)],
        workers=25, timeout=90.0)
    granted = [r for r in results if r.get("ok") and not r.get("duplicate")]
    dup = [r for r in results if r.get("ok") and r.get("duplicate")]
    check(f"to'lov race: deadlock/timeout yo'q ({elapsed:.1f}s)", not errors,
          str(errors[:2]))
    check("to'lov race: 25 parallel urinishda AYNAN 1 marta PRO berildi",
          len(granted) == 1, f"granted={len(granted)}")
    check("to'lov race: qolgan 24 tasi duplicate", len(dup) == 24,
          f"duplicates={len(dup)}")
    payments = int(_scalar(
        "SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id = %s",
        (charge,)))
    check("to'lov race: payments jadvalida 1 ta qator", payments == 1,
          f"payments={payments}")
    days = _scalar(
        "SELECT GREATEST(0, ROUND(EXTRACT(EPOCH FROM "
        "(subscription_expires_at - NOW())) / 86400.0)) FROM users "
        "WHERE user_id = %s", (uid,), 0)
    check("to'lov race: obuna AYNAN 30 kun uzaydi (25× emas)",
          29 <= float(days or 0) <= 31, f"days={days}")

    # --- Karta chek: 10 ta admin bir vaqtda ✅ bosadi -------------------
    uid2 = BASE + 920002
    seed_users([uid2], credits=0)
    receipt_id = _insert_returning_id(
        "INSERT INTO payment_receipts (user_id, username, full_name, media_type, "
        "file_id, caption, status, days_granted, amount_uzs) "
        "VALUES (%s, 'load', 'Load', 'photo', 'AgAD-load', 'chek', 'pending', 30, 90000) "
        "RETURNING id", (uid2,))
    check("chek: pending yozuv yaratildi", receipt_id > 0, str(receipt_id))
    res2, err2, elapsed2 = _run_threads(
        [lambda: PaymentService.process_receipt(receipt_id, admin_id, True)
         for _ in range(10)],
        workers=10, timeout=90.0)
    ok_once = [r for r in res2 if r.get("ok")]
    check(f"chek race: deadlock/timeout yo'q ({elapsed2:.1f}s)", not err2,
          str(err2[:2]))
    check("chek race: 10 parallel tasdiqlashda AYNAN 1 marta PRO",
          len(ok_once) == 1, f"ok={len(ok_once)} res={res2[:3]}")
    ledger = int(_scalar(
        "SELECT COUNT(*) FROM payments WHERE user_id = %s "
        "AND payment_method = 'uzcard_humo'", (uid2,)))
    check("chek race: UZS ledger'da 1 ta qator", ledger == 1, f"ledger={ledger}")
    status = _scalar("SELECT status FROM payment_receipts WHERE id = %s",
                     (receipt_id,), "")
    check("chek race: status 'approved'", status == "approved", str(status))
    cleanup_users([uid, uid2])


def test_parallel_referral() -> None:
    print("\n-- DB: 25 parallel /start ref_<bir xil referrer> (bonus race) --")
    from services.referral_service import ReferralService

    referrer = BASE + 930000
    new_users = [BASE + 930100 + i for i in range(25)]
    with _db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, plan_type, ai_credits, "
            "created_at) VALUES (%s, 'load_referrer', 'free', 0, "
            "NOW() - INTERVAL '20 days') "
            "ON CONFLICT (user_id) DO UPDATE SET ai_credits = 0, "
            "referrer_id = NULL", (referrer,))
    _db._invalidate_user(referrer)
    cleanup_users(new_users)

    results, errors, elapsed = _run_threads(
        [lambda u=u: ReferralService.register_new_user(
            u, f"load_{u}", "Load User", referrer_id=referrer)
         for u in new_users],
        workers=25, timeout=120.0)

    new_ok = [r for r in results if r.get("is_new")]
    check(f"referral race: deadlock/timeout yo'q ({elapsed:.1f}s)", not errors,
          str(errors[:2]))
    check("referral race: 25 ta yangi foydalanuvchi ro'yxatdan o'tdi",
          len(new_ok) == 25, f"is_new={len(new_ok)}")
    check("referral race: barchasiga referrer biriktirildi",
          all(r.get("referrer_id") == referrer for r in new_ok))
    attached = int(_scalar(
        "SELECT COUNT(*) FROM users WHERE referrer_id = %s", (referrer,)))
    check("referral race: bazada 25 ta biriktirilgan do'st", attached == 25,
          f"attached={attached}")

    rewards = [int(r.get("reward") or 0) for r in new_ok]
    expected_total = int(_db.total_referral_reward(25)) if hasattr(
        _db, "total_referral_reward") else sum(
        [3, 3, 3] + [1] * 22)
    balance = int(_scalar("SELECT ai_credits FROM users WHERE user_id = %s",
                          (referrer,)))
    check(f"referral race: mukofotlar yig'indisi tarif jadvaliga mos "
          f"({sum(rewards)} == {expected_total})",
          sum(rewards) == expected_total,
          f"sum={sum(rewards)} expected={expected_total} rewards={sorted(rewards)}")
    check("referral race: referrer balansi = mukofotlar yig'indisi (double-grant yo'q)",
          balance == expected_total, f"balance={balance} expected={expected_total}")
    ledger_rows = int(_scalar(
        "SELECT COUNT(*) FROM credits_ledger WHERE user_id = %s "
        "AND operation_type = 'referral'", (referrer,)))
    check("referral race: ledger'da 25 ta referral auditi", ledger_rows == 25,
          f"ledger={ledger_rows}")
    chain_ok = int(_scalar(
        "SELECT COUNT(*) FROM (SELECT SUM(amount) OVER (ORDER BY id) AS run, "
        "balance_after FROM credits_ledger WHERE user_id = %s) s "
        "WHERE s.run <> s.balance_after", (referrer,)))
    check("referral race: ledger balance_after zanjiri uzilmagan", chain_ok == 0,
          f"broken={chain_ok}")
    cleanup_users(new_users + [referrer])


def test_parallel_promo() -> None:
    print("\n-- DB: 10 parallel promo-kod faollashtirish (max_uses=1) --")
    from services.promo_service import PromoService

    code = f"LOAD39{uuid.uuid4().hex[:6].upper()}"
    users = [BASE + 940000 + i for i in range(10)]
    seed_users(users, credits=0)
    created = PromoService.create_promo(code, duration_days=30, max_uses=1,
                                        plan_type="pro")
    check("promo: kod yaratildi (max_uses=1)", created is True, str(created))

    results, errors, elapsed = _run_threads(
        [lambda u=u: PromoService.redeem_promo(u, code) for u in users],
        workers=10, timeout=90.0)
    ok = [r for r in results if r and r[0]]
    check(f"promo race: deadlock/timeout yo'q ({elapsed:.1f}s)", not errors,
          str(errors[:2]))
    check("promo race: 10 parallel urinishda AYNAN 1 ta faollashdi",
          len(ok) == 1, f"ok={len(ok)} results={results[:3]}")
    redemptions = int(_scalar(
        "SELECT COUNT(*) FROM promo_redemptions WHERE user_id = ANY(%s)",
        (users,)))
    check("promo race: promo_redemptions'da 1 ta qator", redemptions == 1,
          f"redemptions={redemptions}")
    with _db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM promo_redemptions WHERE user_id = ANY(%s)",
                    (users,))
        cur.execute("DELETE FROM promo_codes WHERE code = %s", (code,))
    cleanup_users(users)


def test_mixed_workload_no_deadlock() -> None:
    print("\n-- DB: ARALASH YUK — 50 parallel (kvota + to'lov + referral + "
          "promo), DB_POOL_MAX=%s --" % ENV["db_pool_max"])

    quota_users = [BASE + 950000 + i for i in range(15)]
    pay_users = [BASE + 950100 + i for i in range(15)]
    referrer = BASE + 950200
    ref_users = [BASE + 950300 + i for i in range(10)]
    promo_users = [BASE + 950400 + i for i in range(10)]
    code = f"MIX39{uuid.uuid4().hex[:6].upper()}"

    from services.payment_service import PaymentService
    from services.promo_service import PromoService
    from services.referral_service import ReferralService

    seed_users(quota_users, credits=2)
    seed_users(pay_users, credits=0)
    seed_users(promo_users, credits=0)
    with _db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, plan_type, ai_credits, "
            "created_at) VALUES (%s, 'load_mix_ref', 'free', 0, "
            "NOW() - INTERVAL '20 days') ON CONFLICT (user_id) DO UPDATE "
            "SET ai_credits = 0, referrer_id = NULL", (referrer,))
    _db._invalidate_user(referrer)
    cleanup_users(ref_users)
    PromoService.create_promo(code, duration_days=30, max_uses=3, plan_type="pro")

    jobs = []
    for i, uid in enumerate(quota_users):
        jobs.append(lambda u=uid: _db.reserve_ai_request(u, "ai_studio", 1))
    for uid in pay_users:
        jobs.append(lambda u=uid: PaymentService.process_stars_payment(
            u, f"mix39-{u}", 75, f"sub_stars_1m_{u}", "pro", 30))
    for uid in ref_users:
        jobs.append(lambda u=uid: ReferralService.register_new_user(
            u, f"load_{u}", "Load", referrer_id=referrer))
    for uid in promo_users:
        jobs.append(lambda u=uid: PromoService.redeem_promo(u, code))

    threads_before = _thread_count()
    results, errors, elapsed = _run_threads(jobs, workers=50, timeout=180.0)

    check(f"aralash yuk: 50 parallel tranzaksiya deadlock bermadi "
          f"({elapsed:.1f}s, {len(jobs)} job)", not errors, str(errors[:3]))
    check("aralash yuk: barcha job natija qaytardi", len(results) == len(jobs),
          f"{len(results)} != {len(jobs)}")
    db_errors = [r for r in results if isinstance(r, dict)
                 and r.get("reason") in ("db_error", "database_error")]
    check("aralash yuk: DB xatosi (db_error/database_error) yo'q",
          not db_errors, str(db_errors[:3]))
    check("aralash yuk: pool timeout xatosi yo'q",
          not [e for e in errors if "timeout" in str(e).lower()], str(errors[:2]))

    # Hisob-kitob: hech qanday yozuv "yarim" qolmadi
    negative = int(_scalar(
        "SELECT COUNT(*) FROM users WHERE user_id = ANY(%s) AND ai_credits < 0",
        (quota_users + pay_users + promo_users + ref_users + [referrer],)))
    check("aralash yuk: manfiy balans qolmadi", negative == 0, str(negative))
    orphan = int(_scalar(
        "SELECT COUNT(*) FROM ai_reservations r LEFT JOIN users u "
        "ON u.user_id = r.user_id WHERE u.user_id IS NULL"))
    check("aralash yuk: yetim bron qatori yo'q", orphan == 0, str(orphan))
    promo_uses = int(_scalar(
        "SELECT COUNT(*) FROM promo_redemptions WHERE user_id = ANY(%s)",
        (promo_users,)))
    check("aralash yuk: promo max_uses=3 dan oshmadi", promo_uses <= 3,
          f"uses={promo_uses}")
    ref_attached = int(_scalar(
        "SELECT COUNT(*) FROM users WHERE referrer_id = %s", (referrer,)))
    check("aralash yuk: 10 ta referral biriktirildi", ref_attached == 10,
          f"attached={ref_attached}")
    pay_rows = int(_scalar(
        "SELECT COUNT(*) FROM payments WHERE user_id = ANY(%s)", (pay_users,)))
    check("aralash yuk: 15 ta to'lov yozuvi (har biri 1 marta)", pay_rows == 15,
          f"payments={pay_rows}")

    pool = _pool_state()
    check("aralash yuk: DB pool toza (ulanish leak yo'q)",
          int(pool.get("used", 0) or 0) == 0, str(pool))
    check("aralash yuk: thread leak yo'q",
          _thread_count() - threads_before <= 0,
          f"delta={_thread_count() - threads_before}")

    with _db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM promo_redemptions WHERE user_id = ANY(%s)",
                    (promo_users,))
        cur.execute("DELETE FROM promo_codes WHERE code = %s", (code,))
    cleanup_users(quota_users + pay_users + promo_users + ref_users + [referrer])


# ============================================================
# 4. RESURS SOAK — takroriy to'lqinlarda leak bormi?
# ============================================================

def run_soak_test(waves: int = 5, n_users: int = 10) -> None:
    print(f"\n-- Resurs soak: {waves} × {n_users} virtual foydalanuvchi "
          f"(task/thread/RSS monitoringi) --")
    rss_samples: list[float] = []
    task_deltas: list[int] = []
    thread_deltas: list[int] = []
    total_success = 0

    for wave in range(waves):
        results, provider, cm, ids, m = run_load(
            n_users, max_concurrency=5, max_queue=20, queue_timeout=20.0,
            latency=0.01, credits_per_user=3, arrival_window=0.2,
            label=f"soak{wave}")
        summary = _result_summary(results)
        total_success += summary["success"]
        rss_samples.append(round(_rss_mb(), 2))
        task_deltas.append(m["leaked_tasks"])
        thread_deltas.append(m["leaked_threads"])
        cleanup_users(ids)

    check(f"soak: {waves} to'lqinda jami {total_success} ta muvaffaqiyatli javob",
          total_success == waves * n_users, f"success={total_success}")
    check("soak: hech bir to'lqinda asyncio task leak yo'q",
          all(d <= 0 for d in task_deltas), str(task_deltas))
    check("soak: thread soni o'sib bormadi",
          all(d <= 0 for d in thread_deltas), str(thread_deltas))

    valid = [r for r in rss_samples if r >= 0]
    if len(valid) >= 3:
        first_half = sum(valid[:len(valid) // 2]) / max(1, len(valid) // 2)
        second_half = sum(valid[len(valid) // 2:]) / max(
            1, len(valid) - len(valid) // 2)
        growth = second_half - first_half
        check(f"soak: RSS barqaror (o'sish {growth:.1f} MB < 150 MB)",
              growth < 150.0, f"samples={valid} growth={growth:.1f}")
    else:
        not_tested("soak: RSS barqarorligi", "resource limit (/proc/self/status o'qilmadi)")
    print(f"  ↳ RSS namunalari: {valid}")


# ============================================================
# 5. MONITORING SETLARINING O'SISHI (uzoq umrli jarayon xotirasi)
# ============================================================

def run_manager_growth_probe(n: int = 300) -> None:
    print(f"\n-- Concurrency manager ichki to'plamlari o'sishi ({n} bron) --")
    from services.ai.concurrency import AIConcurrencyManager

    cm = AIConcurrencyManager(max_concurrency=5, max_queue=20)
    rss0 = _rss_mb()
    for i in range(n):
        cm._refunded_reservations.add(900000000 + i)
        cm._cancelled_generations.add(f"gen_probe_{i}")
    growth = round(_rss_mb() - rss0, 2) if rss0 >= 0 else None
    print(f"  ↳ {n} ta yozuvdan keyin RSS Δ={growth} MB "
          f"(refunded={len(cm._refunded_reservations)}, "
          f"cancelled={len(cm._cancelled_generations)})")
    if growth is None:
        not_tested("manager ichki to'plamlari o'sishi",
                   "resource limit (/proc/self/status o'qilmadi)")
        return
    check(f"manager growth: {n} yozuv uchun RSS o'sishi oqilona (<20 MB)",
          growth < 20.0, f"growth={growth}")


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    header("PHASE 13 — YUKLAMA VA KONKURENTLIK TESTI (39-band)")
    detect_environment()
    print(f"  CPU: {ENV['cpus']} yadro · MemAvailable: {ENV['mem_available_mb']} MB "
          f"· RSS(start): {ENV['rss_start_mb']} MB · DB_POOL_MAX: {ENV['db_pool_max']}")
    print(f"  Python: {sys.version.split()[0]} · threads(default executor) va "
          f"asyncio event loop orqali parallel oqimlar")

    # --- 0) Real PostgreSQL (barcha DB- bog'liq ssenariylar uchun) -------
    db = bootstrap_db()

    # --- 1) Bounded queue to'lganda xavfsizlik --------------------------
    header("1) BOUNDED QUEUE TO'LGANDA XAVFSIZLIK (fail-closed + refund)")
    if db is None:
        not_tested("Bounded queue to'lganda xavfsizlik (50 user, MAX_AI_QUEUE=3)",
                   "resource limit (PostgreSQL mavjud emas: pgserver yo'q va "
                   "LOAD_TEST_DATABASE_URL berilmagan)")
    else:
        run_queue_saturation_test(50)

    # --- 2) Parallel virtual foydalanuvchilar (haqiqiy DB) --------------
    header("2) PARALLEL VIRTUAL FOYDALANUVCHILAR OQIMI (10 / 25 / 50 / 100)")
    if db is None:
        not_tested("10/25/50/100 parallel virtual foydalanuvchi oqimi",
                   "resource limit (PostgreSQL mavjud emas: pgserver yo'q va "
                   "LOAD_TEST_DATABASE_URL berilmagan)")
        not_tested("DB tranzaksiyalari parallel oqimlarda",
                   "resource limit (PostgreSQL mavjud emas)")
        not_tested("Resurs soak (5×10 to'lqin)",
                   "resource limit (PostgreSQL mavjud emas)")
    else:
        print(f"  [INFO] Live PostgreSQL: {_db.DATABASE_URL}")
        daily = int(config.PLAN_LIMITS["free"]["daily_ai_requests"])
        print(f"  [INFO] FREE kunlik kvota={daily}, virtual user krediti=3 "
              f"→ har user maksimal {daily + 3} ta so'rov")

        for n in (10, 25, 50):
            run_ai_load_scenario(n, max_concurrency=5, max_queue=20,
                                 arrival_window=0.5)

        # SEMAFOR: navbat katta, hech kim rad etilmaydi → peak parallellik
        # AYNAN MAX_AI_CONCURRENCY ga teng bo'lishi shart.
        run_semaphore_saturation_test(50, max_concurrency=5, max_queue=60)

        # BURST: barchasi bir lahzada — bounded queue cheklovi ishlaydimi?
        run_ai_load_scenario(50, max_concurrency=2, max_queue=6, latency=0.03,
                             arrival_window=0.0, expect_all_served=False,
                             scenario="burst",
                             label="BURST: 50 user bir lahzada (queue cheklovi)")

        if ENV["can_full_load"]:
            run_ai_load_scenario(ENV["full_load_users"], max_concurrency=8,
                                 max_queue=30, latency=0.01,
                                 arrival_window=1.0,
                                 label=f"{ENV['full_load_users']} ta parallel "
                                       f"virtual foydalanuvchi (TO'LIQ YUKLAMA)")
        else:
            not_tested(
                f"{ENV['full_load_users']} ta parallel virtual foydalanuvchi "
                f"(to'liq yuklama)",
                f"resource limit (CPU={ENV['cpus']} yadro, "
                f"MemAvailable={ENV['mem_available_mb']} MB — "
                f"kamida 2 yadro va 900 MB kerak)")

        header("3) DB TRANZAKSIYALARI PARALLEL OQIMLARDA (deadlock yo'q)")
        test_parallel_quota_reservation()
        test_parallel_payments()
        test_parallel_referral()
        test_parallel_promo()
        test_mixed_workload_no_deadlock()

        header("4) RESURS SOAK — TAKRORIY TO'LQINLARDA LEAK BORMI?")
        run_soak_test(waves=5, n_users=10)

        try:
            _db.close_pool()
        except Exception:
            pass

    header("5) CONCURRENCY MANAGER ICHKI TO'PLAMLARI (uzoq umrli jarayon)")
    run_manager_growth_probe(300)

    header("PHASE 13 NATIJASI")
    print(f"  JAMI: o'tdi={PASS}, xato={FAIL}, NOT TESTED={len(NOT_TESTED)}")
    for name, reason in NOT_TESTED:
        print(f"  NOT TESTED — {name}: {reason}")
    if FAIL:
        print("YUKLAMA/KONKURENTLIK TESTLARIDA XATOLAR BOR ✗")
        return 1
    print("YUKLAMA VA KONKURENTLIK TESTLARI MUVAFFAQIYATLI O'TDI ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
