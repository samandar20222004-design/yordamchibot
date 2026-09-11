#!/usr/bin/env python3
"""PostAssist V2 — 9-BOSQICH: High-Concurrency va Stress testlar.

Nima tekshiriladi
----------------
1. **Static/lojika qismi (baza shart emas, doim ishlaydi)**:
   * ``services/lifecycle_service.py`` — shutdown bayrog'i, in-flight hisob,
     ``wait_for_inflight`` timeout'i (vazifalar bekor QILINMAYDI);
   * ``main.py`` — SIGINT/SIGTERM handlerlari, ``graceful_shutdown`` tartibi
     (updater → scheduler.pause → in-flight kutish → app.stop/shutdown →
     scheduler.shutdown → web → db.close_pool → close_ai_session), exit 0;
   * ``scheduler.py`` — shutdown bayrog'ida yangi post olinmasligi, paket
     o'rtasida yuborilmagan postlar 'pending' ga qaytishi (duplikatsiz);
   * ``services/cleanup_service.py`` — LIMIT 1000 paketlar, alohida
     tranzaksiya, SKIP LOCKED, 30/60 kun chegaralari, cron 03:00 jobi.

2. **Real PostgreSQL qismi** (pgserver yoki STRESS_TEST_DATABASE_URL /
   P0_TEST_DATABASE_URL / INTEGRITY_TEST_DATABASE_URL):
   * 1 daqiqa ichiga rejalashtirilgan **100 ta post**ni **5 ta parallel
     worker** yuboradi — 0 ta duplikat (har post Telegramga aynan 1 marta),
     ``post_deliveries`` da har post uchun aynan 1 ta 'sent';
   * **50 ta parallel Credits + Referral** so'rovi (DB_POOL_MAX=5 bilan) —
     deadlock yo'q, connection starvation yo'q (pool timeout xatosi 0),
     ledger va balans mos;
   * **Graceful shutdown simulyatsiyasi** — yuborish o'rtasida SIGTERM:
     boshlangan postlar tugatiladi (bekor qilinmaydi), yangilari olinmaydi,
     olingan-u yuborilmaganlar 'pending' ga qaytadi, restartdan keyin har
     post baribir aynan 1 marta chiqadi;
   * **Cleanup worker** — faqat 30 kundan eski 'sent' delivery'lar va 60
     kundan eski cancelled/failed qoldiqlar o'chadi; yangi/faol (pending,
     processing, yaqinda sent, failed retry, dead_letter) yozuvlarga
     TEGILMAYDI; paketlar LIMIT bo'yicha bo'linadi; qulflangan qator
     o'tkazib yuboriladi.

Ishga tushirish
---------------
::

    cd telegram_bot && python tests/stress_concurrency_test.py

Real PG bo'lmasa (pgserver yo'q va URL berilmagan) — faqat static qism
bajariladi, live qismi SKIP (repo'dagi P0/integrity testlar kabi).
"""
import asyncio
import inspect
import os
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
# Stress testlar Render Free / Neon pool cheklovini AYNAN taqlid qiladi:
# 5 ta ulanish bilan 50 ta parallel so'rov starvation bermasligi kerak.
os.environ.setdefault("DB_POOL_MIN", "0")
os.environ.setdefault("DB_POOL_MAX", "5")
os.environ.setdefault("POST_BATCH_SIZE", "100")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0
skipped = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


def skip(name, reason=""):
    global skipped
    skipped += 1
    print(f"  [SKIP] {name} {reason}")


MAIN_SRC = (ROOT / "main.py").read_text(encoding="utf-8")
SCH_SRC = (ROOT / "scheduler.py").read_text(encoding="utf-8")
CLEAN_SRC = (ROOT / "services" / "cleanup_service.py").read_text(encoding="utf-8")
LIFE_SRC = (ROOT / "services" / "lifecycle_service.py").read_text(encoding="utf-8")
DB_SRC = (ROOT / "database.py").read_text(encoding="utf-8")


# ============================================================
# 1. STATIC / LOJIKA (baza shart emas)
# ============================================================

def test_static_lifecycle():
    print("== 9-bosqich: lifecycle_service (shutdown bayrog'i, in-flight) ==")
    from services import lifecycle_service as lc

    lc.reset_for_tests()
    check("boshlang'ich: is_shutting_down() == False", lc.is_shutting_down() is False)
    check("boshlang'ich: inflight_count() == 0", lc.inflight_count() == 0)
    check("grace oralig'i 5..10 s",
          lc.SHUTDOWN_GRACE_MIN <= lc.SHUTDOWN_GRACE_SECONDS <= lc.SHUTDOWN_GRACE_MAX,
          str(lc.SHUTDOWN_GRACE_SECONDS))

    with lc.track("post:1") as tok:
        check("track: in-flight 1", lc.inflight_count() == 1)
        check("track: token int", isinstance(tok, int) and tok > 0)
        check("track: label saqlanadi", lc.inflight_labels() == ["post:1"])
    check("track: chiqqach 0", lc.inflight_count() == 0)
    check("completed_count oshdi", lc.completed_count() == 1)

    # Istisno bo'lsa ham ro'yxatdan chiqadi
    try:
        with lc.track("post:2"):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    check("track: istisnoda ham tozalanadi", lc.inflight_count() == 0)

    # end_task idempotent
    t = lc.begin_task("x")
    lc.end_task(t)
    lc.end_task(t)
    check("end_task idempotent", lc.inflight_count() == 0)

    # request_shutdown: birinchi True, keyingilari False
    check("request_shutdown: birinchi True", lc.request_shutdown("SIGTERM") is True)
    check("request_shutdown: takroriy False", lc.request_shutdown("SIGTERM") is False)
    check("is_shutting_down() == True", lc.is_shutting_down() is True)
    check("shutdown_reason saqlanadi", lc.shutdown_reason() == "SIGTERM")
    st = lc.status()
    check("status(): shutting_down/inflight/grace kalitlari",
          st.get("shutting_down") is True and "inflight" in st and "grace_seconds" in st)
    lc.reset_for_tests()
    check("reset_for_tests: bayroq tushdi", lc.is_shutting_down() is False)

    # wait_for_inflight: vazifa tugashini kutadi, BEKOR QILMAYDI
    async def _drain_ok():
        done = {"n": 0}

        async def work():
            with lc.track("post:9"):
                await asyncio.sleep(0.3)
                done["n"] += 1

        task = asyncio.create_task(work())
        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        res = await lc.wait_for_inflight(timeout=5)
        await task
        return res, done["n"], time.monotonic() - t0

    res, n, dt = asyncio.run(_drain_ok())
    check("wait_for_inflight: vazifa tugagach qaytdi (drained)", res["drained"] is True, str(res))
    check("wait_for_inflight: vazifa bekor qilinmadi (natija yozildi)", n == 1)
    check("wait_for_inflight: timeout'gacha kutmadi (<2s)", dt < 2.0, f"{dt:.2f}s")

    # wait_for_inflight: timeout — vazifa baribir bekor qilinmaydi
    async def _drain_timeout():
        state = {"cancelled": False, "finished": False}

        async def slow():
            try:
                with lc.track("post:slow"):
                    await asyncio.sleep(0.6)
                state["finished"] = True
            except asyncio.CancelledError:
                state["cancelled"] = True
                raise

        task = asyncio.create_task(slow())
        await asyncio.sleep(0.05)
        res = await lc.wait_for_inflight(timeout=0.2)
        still_running = not task.done()
        await task
        return res, state, still_running

    res, state, still_running = asyncio.run(_drain_timeout())
    check("timeout: drained=False, remaining=1", res["drained"] is False and res["remaining"] == 1, str(res))
    check("timeout: vazifa hali ishlayotgan edi (bekor qilinmadi)", still_running)
    check("timeout: vazifa oxirigacha tugadi", state["finished"] is True and state["cancelled"] is False)
    check("timeout: labels qaytariladi", res["labels"] == ["post:slow"])

    # Thread-safety: 200 ta thread parallel begin/end — hisob nolga qaytadi
    def _worker(_):
        for _ in range(50):
            with lc.track("t"):
                pass

    with ThreadPoolExecutor(max_workers=16) as ex:
        list(ex.map(_worker, range(200)))
    check("thread-safe: 10 000 track dan keyin in-flight 0", lc.inflight_count() == 0)
    lc.reset_for_tests()

    check("lifecycle: telegram/database import qilmaydi (mustaqil)",
          "import database" not in LIFE_SRC and "import telegram" not in LIFE_SRC)
    check("lifecycle: threading.Lock bilan himoyalangan", "threading.Lock()" in LIFE_SRC)


def test_static_main_shutdown():
    print("== 9-bosqich: main.py — SIGINT/SIGTERM va graceful_shutdown ==")
    import main as main_mod

    check("main: signal moduli import qilingan", "import signal" in MAIN_SRC)
    check("main: SIGINT va SIGTERM ro'yxatda",
          '"SIGINT"' in MAIN_SRC and '"SIGTERM"' in MAIN_SRC and "SHUTDOWN_SIGNALS" in MAIN_SRC)
    check("main: loop.add_signal_handler ishlatiladi", "loop.add_signal_handler(" in MAIN_SRC)
    check("main: install_signal_handlers mavjud", callable(getattr(main_mod, "install_signal_handlers", None)))
    check("main: graceful_shutdown coroutine",
          inspect.iscoroutinefunction(getattr(main_mod, "graceful_shutdown", None)))
    check("main: run() exit code 0 qaytaradi", "return 0" in inspect.getsource(main_mod.run))
    check("main: sys.exit(run())", "sys.exit(run())" in MAIN_SRC)
    check("main: cleanup_old_records_job cron jobi", "cleanup_old_records_job, 'cron'" in MAIN_SRC)
    check("main: cron soat/daqiqa cleanup_service dan", "hour=CLEANUP_CRON_HOUR" in MAIN_SRC
          and "minute=CLEANUP_CRON_MINUTE" in MAIN_SRC)
    check("main: cleanup job id", "id=CLEANUP_JOB_ID" in MAIN_SRC)
    check("main: eski 6 soatlik tozalash saqlangan (regressiya)", "'cron', hour=\"*/6\"" in MAIN_SRC)
    check("main: stop_event.wait() — signalgacha kutadi", "await stop_event.wait()" in MAIN_SRC)

    # graceful_shutdown tartibi (manba darajasida)
    body = inspect.getsource(main_mod.graceful_shutdown)
    order = ["updater.stop()", "scheduler.pause()", "wait_for_inflight(",
             "application.stop()", "application.shutdown()", "scheduler.shutdown(wait=False)",
             "web_runner.cleanup()", "db.close_pool()", "close_ai_session()"]
    idx = [body.find(s) for s in order]
    check("graceful_shutdown: barcha bosqichlar mavjud", all(i >= 0 for i in idx), str(list(zip(order, idx))))
    check("graceful_shutdown: tartib to'g'ri (updater → pause → drain → app → sched → web → db → ai)",
          idx == sorted(idx), str(idx))
    check("graceful_shutdown: request_shutdown chaqiriladi", "lifecycle.request_shutdown(" in body)
    check("graceful_shutdown: hech qanday task.cancel() yo'q (bekor qilinmaydi)",
          ".cancel()" not in body)

    # Signal handlerlar haqiqatan o'rnatiladi va SIGTERM stop_event'ni yoqadi
    from services import lifecycle_service as lc

    async def _sig():
        import signal as _signal
        lc.reset_for_tests()
        loop = asyncio.get_running_loop()
        ev = asyncio.Event()
        installed = main_mod.install_signal_handlers(loop, ev)
        try:
            names = sorted(getattr(s, "name", str(s)) for s in installed)
            os.kill(os.getpid(), _signal.SIGTERM)
            try:
                await asyncio.wait_for(ev.wait(), timeout=3)
                fired = True
            except asyncio.TimeoutError:
                fired = False
            # takroriy signal — yopilishni qayta boshlamaydi, istisno yo'q
            os.kill(os.getpid(), _signal.SIGINT)
            await asyncio.sleep(0.05)
        finally:
            main_mod.remove_signal_handlers(loop, installed)
        return names, fired, lc.is_shutting_down(), lc.shutdown_reason()

    names, fired, shutting, reason = asyncio.run(_sig())
    check("signal: SIGINT+SIGTERM o'rnatildi", names == ["SIGINT", "SIGTERM"], str(names))
    check("signal: SIGTERM → stop_event yoqildi", fired)
    check("signal: lifecycle bayrog'i ko'tarildi (SIGTERM)", shutting and reason == "SIGTERM", str(reason))
    lc.reset_for_tests()

    # graceful_shutdown fake komponentlar bilan: tartib + xatoga chidamlilik
    events = []

    class _Updater:
        running = True

        async def stop(self):
            self.running = False
            events.append("updater")

    class _App:
        running = True

        def __init__(self):
            self.updater = _Updater()

        async def stop(self):
            self.running = False
            events.append("app_stop")

        async def shutdown(self):
            events.append("app_shutdown")

    class _Sched:
        running = True
        state = 1

        def pause(self):
            events.append("pause")

        def shutdown(self, wait=True):
            events.append(f"sched_shutdown(wait={wait})")

    class _Web:
        async def cleanup(self):
            events.append("web")

    class _BadWeb:
        async def cleanup(self):
            raise RuntimeError("web down")

    import database as db_mod
    orig_close = db_mod.close_pool
    db_mod.close_pool = lambda: events.append("db_pool")
    try:
        rep = asyncio.run(main_mod.graceful_shutdown(_App(), _Sched(), _Web(), grace_seconds=0.2))
    finally:
        db_mod.close_pool = orig_close
    check("graceful_shutdown: fake komponentlar tartibi",
          events == ["updater", "pause", "app_stop", "app_shutdown", "sched_shutdown(wait=False)", "web", "db_pool"],
          str(events))
    check("graceful_shutdown: report clean=True", rep.get("clean") is True, str(rep))
    check("graceful_shutdown: inflight_drained hisoboti bor", "inflight_drained" in rep)

    events.clear()
    db_mod.close_pool = lambda: events.append("db_pool")
    try:
        rep2 = asyncio.run(main_mod.graceful_shutdown(_App(), _Sched(), _BadWeb(), grace_seconds=0.1))
    finally:
        db_mod.close_pool = orig_close
    check("graceful_shutdown: web xatosida ham DB pool yopiladi", "db_pool" in events, str(events))
    check("graceful_shutdown: xato hisobotda", rep2.get("clean") is False and "web_server_closed" in rep2["errors"])
    lc.reset_for_tests()


def test_static_scheduler_shutdown_guard():
    print("== 9-bosqich: scheduler — shutdown bayrog'ida yangi ish olinmaydi ==")
    import scheduler as sch
    from services import lifecycle_service as lc

    check("scheduler: lifecycle import", "from services import lifecycle_service as lifecycle" in SCH_SRC)
    body = SCH_SRC.split("async def check_and_send_posts", 1)[1].split("\nasync def ", 1)[0]
    check("check_and_send_posts: boshida is_shutting_down tekshiruvi",
          "if lifecycle.is_shutting_down():" in body and body.find("is_shutting_down") < body.find("get_due_posts"))
    check("check_and_send_posts: har post lifecycle.track ichida", "with lifecycle.track(" in body)
    check("check_and_send_posts: paket o'rtasida _requeue_unsent_on_shutdown", "_requeue_unsent_on_shutdown(due_posts[index:])" in body)
    check("scheduler: cleanup_old_records_job mavjud", inspect.iscoroutinefunction(getattr(sch, "cleanup_old_records_job", None)))
    # Regressiya: eski kafolatlar joyida
    check("regressiya: flush_unpersisted_sent_markers saqlangan", "await flush_unpersisted_sent_markers()" in body)
    check("regressiya: mikro-kechikish saqlangan", "await asyncio.sleep(SEND_MICRO_DELAY)" in body)

    # Xatti-harakat: shutdown bayrog'i bilan get_due_posts UMUMAN chaqirilmaydi
    calls = []

    async def _run_db(fn, *a, **k):
        calls.append(getattr(fn, "__name__", str(fn)))
        return []

    orig = sch.db.run_db
    lc.reset_for_tests()
    lc.request_shutdown("test")
    try:
        sch.db.run_db = _run_db
        asyncio.run(sch.check_and_send_posts(object()))
    finally:
        sch.db.run_db = orig
        lc.reset_for_tests()
    check("shutdown paytida get_due_posts chaqirilmadi", "get_due_posts" not in calls, str(calls))

    # Xatti-harakat: paket o'rtasida shutdown → qolganlari retry_post bilan qaytadi
    posts = [(pid, 1, "-100", "text", f"P{pid}", None, None, None, False,
              None, "none", None, None, None, 0, None) for pid in (1, 2, 3, 4)]
    state = {"sent": [], "requeued": []}

    async def _exec(bot, post):
        state["sent"].append(post[0])
        if post[0] == 2:
            lc.request_shutdown("mid-batch")

    async def _run_db2(fn, *a, **k):
        name = getattr(fn, "__name__", "")
        if name == "get_due_posts":
            return posts
        if name == "retry_post":
            state["requeued"].append(a[0])
        return None

    async def _nosleep(_):
        return None

    orig_exec, orig_sleep = sch._execute_send, sch.asyncio.sleep
    lc.reset_for_tests()
    try:
        sch._execute_send = _exec
        sch.db.run_db = _run_db2
        sch.asyncio.sleep = _nosleep
        asyncio.run(sch.check_and_send_posts(object()))
    finally:
        sch._execute_send, sch.asyncio.sleep, sch.db.run_db = orig_exec, orig_sleep, orig
        lc.reset_for_tests()
    check("paket o'rtasida shutdown: boshlanganlar tugadi (1,2), yangilari yuborilmadi",
          state["sent"] == [1, 2], str(state["sent"]))
    check("paket o'rtasida shutdown: yuborilmaganlar (3,4) 'pending' ga qaytdi",
          state["requeued"] == [3, 4], str(state["requeued"]))
    check("in-flight hisob nolga qaytdi", lc.inflight_count() == 0)


def test_static_cleanup_service():
    print("== 9-bosqich: cleanup_service — paketli, tranzaksiyali, xavfsiz ==")
    from services import cleanup_service as cs

    check("cleanup_old_records coroutine", inspect.iscoroutinefunction(cs.cleanup_old_records))
    check("CLEANUP_BATCH_SIZE default 1000", cs.CLEANUP_BATCH_SIZE == 1000, str(cs.CLEANUP_BATCH_SIZE))
    check("30 kun: 'sent' delivery saqlash muddati", cs.DELIVERY_RETENTION_DAYS == 30)
    check("60 kun: vaqtinchalik qoldiqlar saqlash muddati", cs.TEMP_RETENTION_DAYS == 60)
    check("cron: kechasi 03:00", cs.CLEANUP_CRON_HOUR == 3 and cs.CLEANUP_CRON_MINUTE == 0)
    check("job id: cleanup_old_records", cs.CLEANUP_JOB_ID == "cleanup_old_records")
    check("LIMIT paket + FOR UPDATE SKIP LOCKED", "LIMIT %s FOR UPDATE SKIP LOCKED" in CLEAN_SRC)
    check("har paket alohida tranzaksiya (db_transaction)", "with db.db_transaction() as cur:" in CLEAN_SRC)
    check("post_deliveries: faqat status='sent'", "status = 'sent' " in CLEAN_SRC)
    check("scheduled_posts: faqat cancelled/failed", cs.STALE_POST_STATUSES == ("cancelled", "failed"))
    check("pending/processing/posted TEGILMAYDI",
          all(s not in cs.STALE_POST_STATUSES for s in ("pending", "processing", "posted", "completed")))
    check("jadval oq ro'yxati (SQL xavfsizligi)", "post_deliveries" in cs._TABLES_WHITELIST
          and "users" not in cs._TABLES_WHITELIST and "credits_ledger" not in cs._TABLES_WHITELIST)
    check("shutdown paytida yangi paket boshlanmaydi", "lifecycle.is_shutting_down()" in CLEAN_SRC)
    check("CleanupService klassi", cs.CleanupService.BATCH_SIZE == 1000 and cs.CleanupService.JOB_ID == cs.CLEANUP_JOB_ID)
    check("services.__init__ eksporti",
          "CleanupService" in __import__("services").__all__ and "lifecycle_service" in __import__("services").__all__)

    # Xatti-harakat (DB'siz): _delete_batch monkeypatch — paketlar LIMIT bo'yicha bo'linadi
    import database as db_mod
    orig_run_db = db_mod.run_db
    orig_del = cs._delete_batch
    calls = []
    remaining = {"post_deliveries": 2500}

    def _fake_delete(table, where_sql, params, limit, order_by="id"):
        calls.append((table, limit))
        left = remaining.get(table, 0)
        n = min(left, limit)
        remaining[table] = left - n
        return n

    async def _fake_run_db(fn, *a, **k):
        return fn(*a, **k)

    try:
        cs._delete_batch = _fake_delete
        db_mod.run_db = _fake_run_db
        summary = asyncio.run(cs.cleanup_old_records(batch_size=1000))
    finally:
        cs._delete_batch = orig_del
        db_mod.run_db = orig_run_db
    deliv_calls = [c for c in calls if c[0] == "post_deliveries"]
    check("2500 ta 'sent' → 3 paket (1000+1000+500)", len(deliv_calls) == 3, str(deliv_calls))
    check("har paket LIMIT 1000", all(c[1] == 1000 for c in deliv_calls))
    check("summary: post_deliveries_sent=2500", summary["post_deliveries_sent"] == 2500, str(summary))
    check("summary: total/batches/duration_ms", summary["total"] == 2500 and summary["batches"] >= 3 and "duration_ms" in summary)
    check("summary: xatolar yo'q", summary["errors"] == [])

    # Xato bitta amalda — boshqalari davom etadi, istisno ko'tarilmaydi
    def _boom(table, *a, **k):
        if table == "post_deliveries":
            raise RuntimeError("relation locked")
        return 0

    try:
        cs._delete_batch = _boom
        db_mod.run_db = _fake_run_db
        summary2 = asyncio.run(cs.cleanup_old_records())
    finally:
        cs._delete_batch = orig_del
        db_mod.run_db = orig_run_db
    check("bitta jadval xatosi funksiyani yiqitmaydi", summary2["errors"] and "post_deliveries_sent" in summary2["errors"][0])
    check("qolgan amallar bajarildi (kalitlar bor)", "payments_failed" in summary2 and "scheduled_posts_stale" in summary2)

    # Shutdown bayrog'ida tozalash o'tkazib yuboriladi
    from services import lifecycle_service as lc
    lc.reset_for_tests()
    lc.request_shutdown("test")
    try:
        cs._delete_batch = _fake_delete
        db_mod.run_db = _fake_run_db
        summary3 = asyncio.run(cs.cleanup_old_records())
    finally:
        cs._delete_batch = orig_del
        db_mod.run_db = orig_run_db
        lc.reset_for_tests()
    check("shutdown paytida cleanup skip", summary3.get("skipped") == "shutting_down" and summary3["total"] == 0)


def test_static_transfer_lock_order():
    print("== 9-bosqich: transfer_user_credits — deterministik qulf tartibi (deadlock yo'q) ==")
    import database as db_mod
    src = inspect.getsource(db_mod.transfer_user_credits)
    check("ikkala qator bitta so'rovda ORDER BY user_id FOR UPDATE",
          "WHERE user_id IN (%s, %s) ORDER BY user_id FOR UPDATE" in src)
    check("regressiya: CreditsService transfer op_type saqlangan",
          "OP_TRANSFER" in src and src.count("in_tx(") >= 2)
    check("regressiya: 3 kunlik xavfsizlik qoidasi saqlangan", "3 kun" in src)


# ============================================================
# 2. REAL POSTGRESQL (pgserver yoki URL)
# ============================================================

_local_server = []


def _live_uri():
    for var in ("STRESS_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "INTEGRITY_TEST_DATABASE_URL"):
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
        server = pgserver.get_server(os.path.join(tempfile.gettempdir(), "yordamchi_pg_stress"))
    except Exception:  # pragma: no cover - muhitga bog'liq
        return None
    _local_server.append(server)
    return server.get_uri()


# Alohida ID diapazoni — boshqa testlarga tegmaydi.
STRESS_USER = 95000001
STRESS_CHANNEL = f"-100{STRESS_USER}"
CREDIT_USERS = [95100000 + i for i in range(50)]
REFERRER = 95100999
REF_NEW_USERS = [95200000 + i for i in range(50)]
CLEANUP_USER = 95300001
CLEANUP_CHANNEL = f"-100{CLEANUP_USER}"
SHUTDOWN_USER = 95400001
SHUTDOWN_CHANNEL = f"-100{SHUTDOWN_USER}"
ALL_USERS = [STRESS_USER, CLEANUP_USER, SHUTDOWN_USER, REFERRER] + CREDIT_USERS + REF_NEW_USERS


def _cleanup(db_mod):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM credits_ledger WHERE user_id = ANY(%s)", (ALL_USERS,))
        cur.execute("DELETE FROM scheduled_posts WHERE user_id = ANY(%s)", (ALL_USERS,))
        cur.execute("DELETE FROM payment_receipts WHERE user_id = ANY(%s)", (ALL_USERS,))
        cur.execute("DELETE FROM payments WHERE user_id = ANY(%s)", (ALL_USERS,))
        cur.execute("DELETE FROM sent_post_messages WHERE channel_id = ANY(%s)",
                    ([STRESS_CHANNEL, CLEANUP_CHANNEL, SHUTDOWN_CHANNEL],))
        cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (ALL_USERS,))
        cur.execute("UPDATE users SET referrer_id = NULL WHERE referrer_id = ANY(%s)", (ALL_USERS,))
        cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (ALL_USERS,))


def _seed_user_channel(db_mod, user_id, channel_id):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username, full_name, ai_credits, created_at) "
            "VALUES (%s, %s, 'Stress', 5, NOW() - INTERVAL '10 days') "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, f"stress_{user_id}"),
        )
        cur.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title) VALUES (%s, %s, 'Stress kanal') "
            "ON CONFLICT (channel_id) DO UPDATE SET is_active = TRUE",
            (user_id, channel_id),
        )


class StressBot:
    """Telegram botni taqlid qiladi: har yuborishni thread-safe hisoblaydi.

    ``delay`` — Telegram API kechikishi (parallel workerlar bir-biriga
    "yetib olishi" uchun); ``on_send`` — hook (shutdown simulyatsiyasi).
    """

    def __init__(self, delay: float = 0.0, on_send=None):
        self.sent = []          # (chat_id, text)
        self.per_text = {}      # text -> count
        self.lock = threading.Lock()
        self.delay = delay
        self.on_send = on_send
        self._seq = 0

    async def send_message(self, chat_id, text=None, reply_markup=None, parse_mode=None):
        if self.delay:
            await asyncio.sleep(self.delay)
        with self.lock:
            self._seq += 1
            mid = self._seq
            self.sent.append((chat_id, text))
            self.per_text[text] = self.per_text.get(text, 0) + 1
        if self.on_send:
            r = self.on_send(text)
            if asyncio.iscoroutine(r):
                await r
        return SimpleNamespace(message_id=mid)

    async def send_photo(self, chat_id, photo=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_video(self, chat_id, video=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_document(self, chat_id, document=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_animation(self, chat_id, animation=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_audio(self, chat_id, audio=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_voice(self, chat_id, voice=None, caption=None, **kw):
        return await self.send_message(chat_id, text=caption)

    async def send_sticker(self, chat_id, sticker=None, **kw):
        return await self.send_message(chat_id, text="sticker")

    async def send_media_group(self, chat_id, media):
        out = []
        for m in media:
            out.append(await self.send_message(chat_id, text=getattr(m, "caption", None) or "album"))
        return out

    async def delete_message(self, chat_id, message_id):
        return True


def _seed_posts(db_mod, user_id, channel_id, count, prefix, minutes_back=1):
    """``count`` ta postni 1 daqiqa ichiga (o'tmishda) rejalashtiradi."""
    from scheduler import now_tashkent
    base = now_tashkent() - timedelta(minutes=minutes_back)
    step = timedelta(seconds=60.0 / max(1, count))
    ids = []
    with db_mod.db_cursor(commit=True) as cur:
        for i in range(count):
            cur.execute(
                "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status) "
                "VALUES (%s, %s, 'text', %s, %s, 'pending') RETURNING id",
                (user_id, channel_id, f"{prefix} #{i}", base + step * i),
            )
            ids.append(int(cur.fetchone()[0]))
    return ids


def _post_status_counts(db_mod, user_id):
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT status, COUNT(*) FROM scheduled_posts WHERE user_id = %s GROUP BY status", (user_id,))
        return dict(cur.fetchall())


def _delivery_counts(db_mod, user_id):
    with db_mod.db_cursor() as cur:
        cur.execute(
            "SELECT d.status, COUNT(*) FROM post_deliveries d JOIN scheduled_posts p ON p.id = d.post_id "
            "WHERE p.user_id = %s GROUP BY d.status", (user_id,))
        return dict(cur.fetchall())


def _max_sent_per_post(db_mod, user_id):
    with db_mod.db_cursor() as cur:
        cur.execute(
            "SELECT COALESCE(MAX(c), 0) FROM (SELECT COUNT(*) c FROM post_deliveries d "
            "JOIN scheduled_posts p ON p.id = d.post_id WHERE p.user_id = %s AND d.status = 'sent' "
            "GROUP BY d.post_id) s", (user_id,))
        return int(cur.fetchone()[0] or 0)


# ---------------------------------------------------------------- 1
def test_live_100_posts_5_workers(db_mod):
    print("== LIVE: 100 ta post / 5 parallel worker — 0 duplikat ==")
    from scheduler import check_and_send_posts
    from services import lifecycle_service as lc

    lc.reset_for_tests()
    _seed_user_channel(db_mod, STRESS_USER, STRESS_CHANNEL)
    ids = _seed_posts(db_mod, STRESS_USER, STRESS_CHANNEL, 100, "Stress")
    check("100 ta post navbatda (pending)", _post_status_counts(db_mod, STRESS_USER).get("pending") == 100)

    bot = StressBot(delay=0.01)
    # POST_BATCH_SIZE=100 bo'lsa bitta worker hammasini olib qo'yishi mumkin —
    # workerlar bir-biri bilan raqobat qilishi uchun har tick 20 tadan oladi.
    orig_batch = db_mod.POST_BATCH_SIZE
    db_mod.POST_BATCH_SIZE = 20

    async def worker(n):
        # Har worker 1 daqiqa ichida bir necha tick bajaradi (navbat tugaguncha).
        for _ in range(12):
            await check_and_send_posts(bot)
            if not _post_status_counts(db_mod, STRESS_USER).get("pending"):
                break
            await asyncio.sleep(0.005 * n)

    t0 = time.monotonic()
    try:
        async def run_all():
            await asyncio.gather(*(worker(i) for i in range(5)))
        asyncio.run(run_all())
    finally:
        db_mod.POST_BATCH_SIZE = orig_batch
    elapsed = time.monotonic() - t0

    statuses = _post_status_counts(db_mod, STRESS_USER)
    dup = {t: c for t, c in bot.per_text.items() if c > 1}
    check("5 worker: 100 ta post yuborildi", len(bot.sent) == 100, f"sent={len(bot.sent)} statuses={statuses}")
    check("5 worker: 0 ta duplikat (har post 1 marta)", not dup, str(list(dup.items())[:5]))
    check("5 worker: barcha postlar 'posted'", statuses.get("posted") == 100, str(statuses))
    check("5 worker: 'processing'da qolib ketgan post yo'q", not statuses.get("processing"), str(statuses))
    dc = _delivery_counts(db_mod, STRESS_USER)
    check("post_deliveries: 100 ta 'sent', boshqa status yo'q", dc == {"sent": 100}, str(dc))
    check("post_deliveries: har post uchun aynan 1 ta 'sent'", _max_sent_per_post(db_mod, STRESS_USER) == 1)
    check("1 daqiqa ichida tugadi", elapsed < 60, f"{elapsed:.1f}s")
    check("in-flight hisob nolga qaytdi", lc.inflight_count() == 0)

    # Ikkinchi to'lqin (restart taqlidi): hech narsa qayta yuborilmaydi
    asyncio.run(check_and_send_posts(bot))
    check("qayta tick: qo'shimcha yuborish yo'q", len(bot.sent) == 100)
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sent_post_messages WHERE channel_id = %s", (STRESS_CHANNEL,))
        spm = int(cur.fetchone()[0])
    check("sent_post_messages: 100 ta yozuv", spm == 100, str(spm))
    del ids


# ---------------------------------------------------------------- 2
def test_live_50_parallel_credits_referral(db_mod):
    print("== LIVE: 50 parallel Credits + Referral — deadlock/starvation yo'q ==")
    from services.credits_service import CreditsService, InsufficientCreditsError
    from services.referral_service import ReferralService

    with db_mod.db_cursor(commit=True) as cur:
        for uid in CREDIT_USERS + [REFERRER]:
            cur.execute(
                "INSERT INTO users (user_id, username, ai_credits, created_at) "
                "VALUES (%s, %s, 100, NOW() - INTERVAL '10 days') ON CONFLICT (user_id) DO NOTHING",
                (uid, f"cr_{uid}"),
            )
    pool_max = db_mod.DB_POOL_MAX
    check(f"pool cheklovi kichik (DB_POOL_MAX={pool_max} ≤ 5)", pool_max <= 5)

    errors = []
    timings = []

    def credits_job(i):
        uid = CREDIT_USERS[i]
        t0 = time.monotonic()
        try:
            r1 = CreditsService.add_credits(uid, 10, "promo", ref_id=f"stress-{i}")
            r2 = CreditsService.spend_credits(uid, 4, "ai_request", ref_id=f"stress-{i}")
            # Har bir foydalanuvchi 3 ta o'tkazma: A→B (hamma bir xil B) — hot-row
            ok, msg = db_mod.transfer_user_credits(uid, REFERRER, 3)
            if not ok:
                raise RuntimeError(f"transfer: {msg}")
            if not (r1.get("success") and r2.get("success")):
                raise RuntimeError(f"credits: {r1} {r2}")
        except InsufficientCreditsError as e:
            errors.append(f"insufficient {uid}: {e}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}"[:200])
        timings.append(time.monotonic() - t0)

    def referral_job(i):
        new_uid = REF_NEW_USERS[i]
        t0 = time.monotonic()
        try:
            res = ReferralService.register_new_user(new_uid, f"ref_{new_uid}", "Ref", referrer_id=REFERRER)
            if res.get("error"):
                raise RuntimeError(res["error"])
            if not res.get("is_new") or res.get("referrer_id") != REFERRER:
                raise RuntimeError(f"referral natijasi: {res}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{type(e).__name__}: {e}"[:200])
        timings.append(time.monotonic() - t0)

    # 50 ta parallel credits + 50 ta parallel referral = 100 ta bir vaqtda,
    # hammasi REFERRER qatoriga yozadi (hot row) va faqat 5 ta ulanish bor.
    jobs = [("c", i) for i in range(50)] + [("r", i) for i in range(50)]
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=50) as ex:
        list(ex.map(lambda j: credits_job(j[1]) if j[0] == "c" else referral_job(j[1]), jobs))
    elapsed = time.monotonic() - t0

    deadlocks = [e for e in errors if "deadlock" in e.lower()]
    starvation = [e for e in errors if "pool band" in e.lower() or "TimeoutError" in e]
    check("50+50 parallel so'rov: xatolar yo'q", not errors, str(errors[:3]))
    check("deadlock yo'q", not deadlocks, str(deadlocks[:2]))
    check("connection starvation (pool timeout) yo'q", not starvation, str(starvation[:2]))
    check("hammasi 30 s ichida tugadi", elapsed < 30, f"{elapsed:.1f}s")
    check("eng sekin so'rov < 15 s (pool kutish chegarasi)", max(timings) < 15, f"{max(timings):.2f}s")

    # DB pool holati: hamma ulanish qaytarilgan, pool qulab tushmagan
    ps = db_mod.get_db_pool_status()
    check("pool: barcha ulanishlar qaytarildi (used=0)", ps.get("used") == 0, str(ps))
    check("pool: qulab tushmagan", not ps.get("collapsed"), str(ps))

    # Hisob-kitob: har user 100 +10 -4 -3 = 103
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users WHERE user_id = ANY(%s) AND ai_credits = 103", (CREDIT_USERS,))
        ok_users = int(cur.fetchone()[0])
        cur.execute("SELECT ai_credits FROM users WHERE user_id = %s", (REFERRER,))
        ref_credits = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (REFERRER,))
        ref_count = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM credits_ledger WHERE user_id = %s AND operation_type = 'referral'", (REFERRER,))
        ref_ledger = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM credits_ledger WHERE user_id = ANY(%s)", (CREDIT_USERS,))
        cr_ledger = int(cur.fetchone()[0])
    check("credits: 50 ta user balansi to'g'ri (103)", ok_users == 50, str(ok_users))
    check("credits: har user 3 ta ledger yozuvi (promo/ai_request/transfer)", cr_ledger == 150, str(cr_ledger))
    check("referral: 50 ta yangi user referrer'ga biriktirildi", ref_count == 50, str(ref_count))
    check("referral: 50 ta referral ledger yozuvi", ref_ledger == 50, str(ref_ledger))
    # referrer: 100 + 50*3 (transfer) + referral (3+3+3 + 47*1 = 56) = 306
    expected_ref = 100 + 50 * 3 + db_mod.total_referral_reward(50)
    check("referrer balansi = 100 + 150 transfer + referral mukofotlari",
          ref_credits == expected_ref, f"{ref_credits} != {expected_ref}")

    # Ledger zanjiri: referrer uchun balance_after ketma-ketligi mos (audit)
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT amount, balance_after FROM credits_ledger WHERE user_id = %s ORDER BY id", (REFERRER,))
        rows = cur.fetchall()
    running = 100
    chain_ok = True
    for amount, after in rows:
        running += int(amount)
        if int(after) != running:
            chain_ok = False
            break
    check("referrer ledger: balance_after zanjiri uzilmagan (parallel yozuvda ham)", chain_ok and running == ref_credits)


# ---------------------------------------------------------------- 3
def test_live_graceful_shutdown_simulation(db_mod):
    print("== LIVE: graceful shutdown simulyatsiyasi — faol vazifalar bekor qilinmaydi ==")
    import scheduler as sch
    from services import lifecycle_service as lc

    lc.reset_for_tests()
    _seed_user_channel(db_mod, SHUTDOWN_USER, SHUTDOWN_CHANNEL)
    _seed_posts(db_mod, SHUTDOWN_USER, SHUTDOWN_CHANNEL, 40, "Shutdown")

    orig_batch = db_mod.POST_BATCH_SIZE
    db_mod.POST_BATCH_SIZE = 10
    state = {"signal_sent": False, "inflight_at_signal": None}

    async def on_send(text):
        # 7-post yuborilayotgan paytda "SIGTERM" keladi
        if not state["signal_sent"] and len(bot.sent) >= 7:
            state["signal_sent"] = True
            state["inflight_at_signal"] = lc.inflight_count()
            lc.request_shutdown("SIGTERM(sim)")

    bot = StressBot(delay=0.02, on_send=on_send)

    async def run_workers():
        # 3 ta worker parallel, 5 ta tick — shutdown'dan keyin hech biri yangi post olmaydi
        async def w():
            for _ in range(5):
                await sch.check_and_send_posts(bot)
                await asyncio.sleep(0.01)
        await asyncio.gather(w(), w(), w())
        drain = await lc.wait_for_inflight(timeout=5)
        return drain

    try:
        drain = asyncio.run(run_workers())
    finally:
        db_mod.POST_BATCH_SIZE = orig_batch

    statuses = _post_status_counts(db_mod, SHUTDOWN_USER)
    sent_before_restart = len(bot.sent)
    dup = {t: c for t, c in bot.per_text.items() if c > 1}
    check("shutdown: signal yuborildi (7-postdan keyin)", state["signal_sent"])
    check("shutdown: signal paytida faol vazifa bor edi", (state["inflight_at_signal"] or 0) >= 1,
          str(state["inflight_at_signal"]))
    check("shutdown: faol vazifalar tugadi (drained, bekor qilinmadi)", drain["drained"] is True, str(drain))
    check("shutdown: yuborilganlar 40 tadan kam (yangilar olinmadi)", 0 < sent_before_restart < 40,
          f"sent={sent_before_restart}")
    check("shutdown: 'processing'da qolib ketgan post yo'q (yuborilmaganlar pending'ga qaytdi)",
          not statuses.get("processing"), str(statuses))
    check("shutdown: posted + pending = 40", statuses.get("posted", 0) + statuses.get("pending", 0) == 40, str(statuses))
    check("shutdown: yuborilgan soni = 'posted' soni (yarim holat yo'q)",
          statuses.get("posted", 0) == sent_before_restart, f"{statuses} vs {sent_before_restart}")
    check("shutdown: 0 duplikat", not dup, str(dup))
    dc = _delivery_counts(db_mod, SHUTDOWN_USER)
    check("shutdown: post_deliveries 'processing' qolmadi", not dc.get("processing"), str(dc))

    # "Restart": bayroq tushadi, qolganlar yuboriladi — har post baribir 1 marta
    lc.reset_for_tests()
    asyncio.run(sch.check_and_send_posts(bot))
    asyncio.run(sch.check_and_send_posts(bot))
    statuses2 = _post_status_counts(db_mod, SHUTDOWN_USER)
    dup2 = {t: c for t, c in bot.per_text.items() if c > 1}
    check("restart: barcha 40 ta post 'posted'", statuses2.get("posted") == 40, str(statuses2))
    check("restart: jami 40 ta yuborish (0 duplikat)", len(bot.sent) == 40 and not dup2, f"sent={len(bot.sent)} dup={dup2}")
    check("restart: post_deliveries har post uchun 1 ta 'sent'",
          _delivery_counts(db_mod, SHUTDOWN_USER) == {"sent": 40} and _max_sent_per_post(db_mod, SHUTDOWN_USER) == 1)
    check("in-flight nolga qaytdi", lc.inflight_count() == 0)


# ---------------------------------------------------------------- 4
def test_live_cleanup_worker(db_mod):
    print("== LIVE: cleanup worker — faqat eski yozuvlar, faol/yangilarga tegmaydi ==")
    from services import cleanup_service as cs
    from services import lifecycle_service as lc
    import scheduler as sch

    lc.reset_for_tests()
    _seed_user_channel(db_mod, CLEANUP_USER, CLEANUP_CHANNEL)
    ch_num = int(CLEANUP_CHANNEL)
    with db_mod.db_cursor(commit=True) as cur:
        # Asosiy (faol) post — unga delivery'lar bog'lanadi
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status, created_at) "
            "VALUES (%s, %s, 'text', 'anchor', NOW(), 'posted', NOW()) RETURNING id",
            (CLEANUP_USER, CLEANUP_CHANNEL))
        anchor = int(cur.fetchone()[0])
        # 2 300 ta eski 'sent' delivery (45 kun) → o'chishi kerak (3 paket)
        cur.execute(
            "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, created_at, updated_at) "
            "SELECT %s, %s, 'sent', 'cl_old_sent_' || g, NOW() - INTERVAL '45 days', NOW() - INTERVAL '45 days' "
            "FROM generate_series(1, 2300) g", (anchor, ch_num))
        # 7 ta yangi 'sent' (2 kun) → qolishi kerak
        cur.execute(
            "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, created_at, updated_at) "
            "SELECT %s, %s, 'sent', 'cl_fresh_sent_' || g, NOW() - INTERVAL '2 days', NOW() - INTERVAL '2 days' "
            "FROM generate_series(1, 7) g", (anchor, ch_num))
        # Eski, lekin FAOL/audit statuslar → qolishi kerak
        for st in ("pending", "processing", "failed", "dead_letter"):
            cur.execute(
                "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, created_at, updated_at) "
                "VALUES (%s, %s, %s, 'cl_old_' || %s, NOW() - INTERVAL '90 days', NOW() - INTERVAL '90 days')",
                (anchor, ch_num, st, st))
        # 29 kunlik 'sent' — chegaraga yetmagan → qolishi kerak
        cur.execute(
            "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, created_at, updated_at) "
            "VALUES (%s, %s, 'sent', 'cl_29d_sent', NOW() - INTERVAL '29 days', NOW() - INTERVAL '29 days')",
            (anchor, ch_num))
        # scheduled_posts: 1 100 ta eski cancelled (70 kun) → o'chadi; 30 ta eski failed → o'chadi
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status, created_at) "
            "SELECT %s, %s, 'text', 'old cancelled', NOW(), 'cancelled', NOW() - INTERVAL '70 days' FROM generate_series(1, 1100)",
            (CLEANUP_USER, CLEANUP_CHANNEL))
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status, created_at) "
            "SELECT %s, %s, 'text', 'old failed', NOW(), 'failed', NOW() - INTERVAL '61 days' FROM generate_series(1, 30)",
            (CLEANUP_USER, CLEANUP_CHANNEL))
        # Qolishi kerak: yangi cancelled (5 kun), eski pending (kelajak), eski posted, eski processing, 59 kunlik cancelled
        for content, status, age, sched in (
            ("fresh cancelled", "cancelled", "5 days", "NOW()"),
            ("old pending", "pending", "70 days", "NOW() + INTERVAL '1 day'"),
            ("old posted", "posted", "70 days", "NOW()"),
            ("old processing", "processing", "70 days", "NOW()"),
            ("old completed", "completed", "70 days", "NOW()"),
            ("59d cancelled", "cancelled", "59 days", "NOW()"),
        ):
            cur.execute(
                f"INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time, status, created_at) "
                f"VALUES (%s, %s, 'text', %s, {sched}, %s, NOW() - INTERVAL '{age}')",
                (CLEANUP_USER, CLEANUP_CHANNEL, content, status))
        # payment_receipts: eski rejected → o'chadi; yangi rejected, eski approved/pending → qoladi
        for status, age, reviewed in (
            ("rejected", "70 days", "NOW() - INTERVAL '70 days'"),
            ("rejected", "3 days", "NOW() - INTERVAL '3 days'"),
            ("approved", "70 days", "NOW() - INTERVAL '70 days'"),
            ("pending", "70 days", "NULL"),
        ):
            cur.execute(
                f"INSERT INTO payment_receipts (user_id, status, created_at, reviewed_at) "
                f"VALUES (%s, %s, NOW() - INTERVAL '{age}', {reviewed})",
                (CLEANUP_USER, status))
        # payments: eski failed → o'chadi; eski succeeded/refunded, yangi failed → qoladi
        for status, age in (("failed", "70 days"), ("failed", "2 days"), ("succeeded", "70 days"), ("refunded", "70 days")):
            cur.execute(
                f"INSERT INTO payments (user_id, amount, currency, payload, status, created_at) "
                f"VALUES (%s, 10, 'XTR', 'stress', %s, NOW() - INTERVAL '{age}')",
                (CLEANUP_USER, status))
        # sent_post_messages: eski o'chirilgan → o'chadi; faol (deleted_at NULL) va yangi o'chirilgan → qoladi
        cur.execute(
            "INSERT INTO sent_post_messages (post_id, channel_id, message_id, delete_at, deleted_at) VALUES "
            "(%s, %s, 1, NOW() - INTERVAL '70 days', NOW() - INTERVAL '70 days'), "
            "(%s, %s, 2, NOW() + INTERVAL '1 day', NULL), "
            "(%s, %s, 3, NOW() - INTERVAL '3 days', NOW() - INTERVAL '3 days')",
            (anchor, CLEANUP_CHANNEL, anchor, CLEANUP_CHANNEL, anchor, CLEANUP_CHANNEL))

    def deliveries():
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT status, COUNT(*) FROM post_deliveries WHERE post_id = %s GROUP BY status", (anchor,))
            return dict(cur.fetchall())

    def posts():
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT content, COUNT(*) FROM scheduled_posts WHERE user_id = %s GROUP BY content", (CLEANUP_USER,))
            return dict(cur.fetchall())

    def rows(table, extra=""):
        with db_mod.db_cursor() as cur:
            col = "channel_id = %s" if table == "sent_post_messages" else "user_id = %s"
            val = CLEANUP_CHANNEL if table == "sent_post_messages" else CLEANUP_USER
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} {extra}", (val,))
            return int(cur.fetchone()[0])

    before_d, before_p = deliveries(), posts()
    check("seed: 2308 ta 'sent' delivery", before_d.get("sent") == 2308, str(before_d))
    check("seed: 1100 old cancelled + 30 old failed", before_p.get("old cancelled") == 1100 and before_p.get("old failed") == 30)

    # Bir qator BOSHQA tranzaksiya tomonidan qulflangan (worker yuborayotgan
    # kabi) — cleanup uni KUTMASDAN o'tkazib yuborishi kerak (SKIP LOCKED).
    lock_conn = db_mod.psycopg2.connect(db_mod.DATABASE_URL)
    lock_cur = lock_conn.cursor()
    lock_cur.execute("SELECT id FROM post_deliveries WHERE idempotency_key = 'cl_old_sent_1' FOR UPDATE")
    locked_id = lock_cur.fetchone()[0]

    # Job orqali (scheduler.cleanup_old_records_job) — asl integratsiya yo'li
    t0 = time.monotonic()
    summary = asyncio.run(sch.cleanup_old_records_job())
    elapsed = time.monotonic() - t0
    lock_conn.rollback()
    lock_conn.close()

    after_d, after_p = deliveries(), posts()
    check("cleanup: summary qaytdi, xatolar yo'q", isinstance(summary, dict) and summary["errors"] == [], str(summary))
    check("cleanup: eski 'sent' o'chdi (2299 = 2300 - 1 qulflangan)", summary["post_deliveries_sent"] == 2299, str(summary))
    check("cleanup: qulflangan qator KUTILMADI, o'tkazib yuborildi (hali bor)",
          after_d.get("sent", 0) == 1 + 7 + 1, str(after_d))
    check("cleanup: qulf kutilmagani uchun tez tugadi (<5s)", elapsed < 5, f"{elapsed:.2f}s")
    check("cleanup: 7 yangi 'sent' + 29 kunlik 'sent' qoldi", after_d.get("sent", 0) >= 8, str(after_d))
    check("cleanup: pending/processing/failed/dead_letter delivery'lar TEGILMADI",
          all(after_d.get(s) == 1 for s in ("pending", "processing", "failed", "dead_letter")), str(after_d))
    check("cleanup: paketlar LIMIT 1000 bilan bo'lindi (≥3 paket deliveries, ≥2 paket posts)",
          summary["batches"] >= 5, str(summary["batches"]))
    check("cleanup: 1100 old cancelled + 30 old failed o'chdi",
          summary["scheduled_posts_stale"] == 1130 and "old cancelled" not in after_p and "old failed" not in after_p, str(after_p))
    check("cleanup: yangi cancelled (5 kun) qoldi", after_p.get("fresh cancelled") == 1, str(after_p))
    check("cleanup: 59 kunlik cancelled qoldi (chegara 60)", after_p.get("59d cancelled") == 1, str(after_p))
    check("cleanup: eski pending/posted/processing/completed postlar TEGILMADI",
          all(after_p.get(c) == 1 for c in ("old pending", "old posted", "old processing", "old completed", "anchor")), str(after_p))
    check("cleanup: eski rejected chek o'chdi, yangi rejected + approved + pending qoldi",
          summary["payment_receipts_rejected"] == 1 and rows("payment_receipts") == 3)
    check("cleanup: eski failed to'lov o'chdi, succeeded/refunded/yangi failed qoldi",
          summary["payments_failed"] == 1 and rows("payments") == 3)
    check("cleanup: eski o'chirilgan kanal xabari yozuvi o'chdi, faol va yangi qoldi",
          summary["sent_post_messages_deleted"] == 1 and rows("sent_post_messages") == 2)
    check("cleanup: total = yig'indi", summary["total"] == 2299 + 1130 + 1 + 1 + 1, str(summary["total"]))
    # credits_ledger / users / channels — cleanup umuman tegmaydi
    check("cleanup: users/channels o'chmadi", rows("channels") == 1)

    # Ikkinchi ishga tushish (idempotent): endi faqat oldin qulflangan 1 ta qator ketadi
    summary2 = asyncio.run(cs.cleanup_old_records())
    check("cleanup idempotent: takroriy ishga tushirishda faqat qulfdan bo'shagan 1 ta qator",
          summary2["post_deliveries_sent"] == 1 and summary2["scheduled_posts_stale"] == 0, str(summary2))
    summary3 = asyncio.run(cs.cleanup_old_records())
    check("cleanup idempotent: uchinchi ishga tushirishda 0", summary3["total"] == 0, str(summary3))

    # Cleanup va scheduler PARALLEL: tozalash paytida faol postlar yuborilaveradi
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key, created_at, updated_at) "
            "SELECT %s, %s, 'sent', 'cl_par_' || g, NOW() - INTERVAL '40 days', NOW() - INTERVAL '40 days' "
            "FROM generate_series(1, 3000) g", (anchor, ch_num))
    _seed_posts(db_mod, CLEANUP_USER, CLEANUP_CHANNEL, 20, "ParallelClean")
    bot = StressBot(delay=0.005)

    async def both():
        from scheduler import check_and_send_posts
        r = await asyncio.gather(cs.cleanup_old_records(batch_size=500), check_and_send_posts(bot),
                                 check_and_send_posts(bot))
        return r[0]

    sent_before_parallel = _delivery_counts(db_mod, CLEANUP_USER).get("sent", 0)
    par = asyncio.run(both())
    dup = {t: c for t, c in bot.per_text.items() if c > 1}
    check("parallel: cleanup 3000 ta eski 'sent' o'chirdi (6 paket)", par["post_deliveries_sent"] == 3000 and par["batches"] >= 6, str(par))
    check("parallel: 20 ta yangi post yuborildi, 0 duplikat", len(bot.sent) == 20 and not dup, f"sent={len(bot.sent)}")
    posted_after = _post_status_counts(db_mod, CLEANUP_USER).get("posted")
    sent_after = _delivery_counts(db_mod, CLEANUP_USER).get("sent", 0)
    check("parallel: yangi postlar 'posted' (anchor + old posted + 20)", posted_after == 22, str(posted_after))
    check("parallel: yangi 'sent' delivery'lar saqlanib qoldi (eski 3000 tasi ketdi)",
          sent_after == sent_before_parallel - 3000 + 20, f"{sent_after} != {sent_before_parallel} - 3000 + 20")


def run_live():
    uri = _live_uri()
    if not uri:
        print("== Real PostgreSQL (o'tkazib yuborildi) ==")
        skip("live 9-bosqich stress testlar", "(pgserver/URL mavjud emas)")
        return
    import database as db_mod
    db_mod.DATABASE_URL = uri
    os.environ["DATABASE_URL"] = uri
    db_mod._reset_pool()
    try:
        db_mod.init_db()
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        skip("live 9-bosqich stress testlar", f"(PostgreSQL mavjud emas: {e})")
        return
    # Scheduler journal holatini izolyatsiya qilamiz
    import scheduler as sch
    sch._UNPERSISTED_SENT.clear()
    sch._journal_loaded = True
    try:
        _cleanup(db_mod)
        test_live_100_posts_5_workers(db_mod)
        test_live_50_parallel_credits_referral(db_mod)
        test_live_graceful_shutdown_simulation(db_mod)
        test_live_cleanup_worker(db_mod)
    except Exception as e:  # pragma: no cover - xavfsizlik
        import traceback
        traceback.print_exc()
        check("live 9-bosqich testlari xatosiz o'tdi", False, f"{type(e).__name__}: {e}")
    finally:
        try:
            _cleanup(db_mod)
        except Exception:  # noqa: BLE001
            pass
        db_mod.close_pool()
        from services import lifecycle_service as lc
        lc.reset_for_tests()


if __name__ == "__main__":
    test_static_lifecycle()
    test_static_main_shutdown()
    test_static_scheduler_shutdown_guard()
    test_static_cleanup_service()
    test_static_transfer_lock_order()
    run_live()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
        print("9-bosqich stress testlarda xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0, O'tkazib yuborildi: {skipped}")
    print("Barcha 9-bosqich stress/concurrency testlari muvaffaqiyatli o'tdi ✔")
