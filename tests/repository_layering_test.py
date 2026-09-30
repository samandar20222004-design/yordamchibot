#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=====================================================================
 🗂 PHASE 4 — DATABASE MODULLASHUVI VA REPOSITORY PATTERN
=====================================================================

PR #174 dan keyingi bosqich: ``telegram_bot/database.py`` (8928 qatorli
«God module») yadroga (core runtime) + domain repository'lariga
AJRATILDI. Bu suite shu arxitekturani va uning kafolatlarini tekshiradi.

Tekshiriladigan bandlar
---------------------------------------------------------------
(1) 🧩 FACADE PARITY — ``database.X`` va ``repositories.<mod>.X`` — xuddi
    bir xil obyekt. Mavjud ``import database as db`` / ``from database
    import X`` chaqiruvlari o'zgarishsiz ishlaydi (backward compatibility).
(2) 🚪 API YO'QOTILMADI — kritik funksiyalar va konstantalar facade'da
    mavjud, ``callable``/qiymatli.
(3) 🎯 MOCK NUQTASI SAQLANDI — ``patch("database.db_cursor")`` repository
    ichidagi SQL'ga yetib boradi (avvalgi test kelishuvi).
(4) 🔗 CROSS-REPOSITORY KECH BOG'LANISH — ``patch("database.get_setting")``
    ``posts_repository.get_queue_slots`` ni ham o'zgartiradi.
(5) 🔄 IMPORT TARTIBI ERKIN — ``import repositories.x`` birinchi ham,
    ``import database`` birinchi ham ishlaydi (import sikli yo'q).
(6) 🧱 QATLAM INTIZOMI — core'da domain SQL yo'q, repository'da pool
    mexanikasi yo'q.
(7) 🔒 TRZAKSIYA KAFOLATI — ``db_atomic`` / ``db_transaction`` / async
    ``transaction``: BEGIN/COMMIT/ROLLBACK va SAVEPOINT chegaralari.
(8) 💧 LEAK HIMOYASI — ulanish hisobi har doim 0 ga qaytadi
    (``conn_balance()``), offload hisobi esa nolga tushadi.
(9) 📚 KO'CHIRILGANLIK TO'LIQLIGI — har bir funksiya yagona manzilda
    yashaydi (ikki nusxa yo'q, yo'qotilgan yo'q).
"""
import ast
import inspect
import os
import subprocess
import sys
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOT = os.path.join(ROOT, "telegram_bot")
if BOT not in sys.path:
    sys.path.insert(0, BOT)

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("BOT_TOKEN", "123456:REPOSITORY_LAYERING_TEST")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@127.0.0.1:5432/test")

PASSED = 0
FAILED = 0


def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILED += 1
        print(f"  [FAIL] {name} {detail}")


def head(title):
    print(f"\n== {title} ==")


import database as db  # noqa: E402
import repositories  # noqa: E402
from repositories import (  # noqa: E402
    audit_repository, channels_repository, payments_repository,
    posts_repository, scheduler_repository, settings_repository,
    teams_repository, users_repository,
)

ALL_REPOS = {
    "settings_repository": settings_repository,
    "users_repository": users_repository,
    "channels_repository": channels_repository,
    "posts_repository": posts_repository,
    "scheduler_repository": scheduler_repository,
    "teams_repository": teams_repository,
    "payments_repository": payments_repository,
    "audit_repository": audit_repository,
}


# ======================================================================
# 1) FACADE PARITY
# ======================================================================
def _own_symbols(path):
    """Modulning O'ZIGA tegishli nomlari (import qilinganlar emas)."""
    names = set()
    for node in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    # har bir modul o'z logger'iga ega (qasddan boshqa obyekt)
    names.discard("logger")
    return names


def test_facade_parity():
    head("1) 🧩 Facade parity — database.X === repositories.<mod>.X")
    check("repositories paketi 8 ta modul ro'yxatlaydi",
          len(repositories.REPOSITORIES) == 8, str(repositories.REPOSITORIES))

    shared, mismatched = 0, []
    for name, mod in ALL_REPOS.items():
        for attr in sorted(_own_symbols(mod.__file__)):
            if not hasattr(db, attr):
                mismatched.append(f"{name}.{attr} -> database'da YO'Q")
            elif getattr(db, attr) is not getattr(mod, attr):
                mismatched.append(f"{name}.{attr} -> boshqa obyekt")
            else:
                shared += 1
    check(f"barcha repository eksportlari facade bilan bir xil ({shared} ta)",
          not mismatched, "; ".join(mismatched[:6]))

    # MUHIM: modul ``runtime`` dan olgan proksi nomi bilan o'z ta'rifini
    # birga binda qilmasligi kerak — aks holda proksi o'ziga o'zi murojaat
    # qilib cheksiz rekursiyaga tushadi.
    for name, mod in ALL_REPOS.items():
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        proxied = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom)
                    and node.module == "repositories.runtime"):
                proxied.update(a.asname or a.name for a in node.names)
        clash = proxied & _own_symbols(mod.__file__)
        check(f"{name}: proksi o'z ta'rifi bilan to'qnashmaydi (rekursiya yo'q)",
              not clash, str(sorted(clash)))

    # teskari yo'nalish: har bir repo funksiyasi facade'dan topiladi
    missing = []
    for name, mod in ALL_REPOS.items():
        for attr in _own_symbols(mod.__file__):
            if not hasattr(db, attr):
                missing.append(f"{name}.{attr}")
    check("teskari yo'nalish: facade'da repo eksporti YO'Q emas",
          not missing, str(missing[:6]))


# ======================================================================
# 2) API YO'QOTILMADI
# ======================================================================
CRITICAL_API = {
    "users_repository": [
        "save_user", "get_user_language", "set_user_language",
        "is_premium", "set_user_plan", "reserve_ai_request", "refund_ai_request",
        "check_ai_limit", "check_channel_limit", "check_queue_limit",
        "get_referral_stats", "add_user_credit", "use_user_credit",
        "transfer_user_credits", "create_promo_code", "redeem_promo_code",
    ],
    "channels_repository": [
        "save_channel", "remove_channel", "get_user_channels", "get_channel_tone",
        "set_channel_tone", "insert_channel_post_event", "save_channel_dna_profile",
        "get_channel_dna_profile", "get_channel_intelligence_profile",
        "create_content_source", "get_recycle_candidates",
    ],
    "posts_repository": [
        "add_post", "get_due_posts", "mark_post_processing", "mark_post_as_sent",
        "mark_post_status", "cancel_post", "update_post_content", "get_queue_posts",
        "get_queue_slots", "set_queue_slots", "get_post_templates",
    ],
    "scheduler_repository": [
        "schedule_week_posts", "claim_post_delivery", "mark_post_delivery_sent",
        "recover_stale_processing_posts", "recover_processing_posts_on_startup",
        "cleanup_old_data", "find_next_queue_slot",
    ],
    "teams_repository": [
        "add_channel_member", "set_channel_member_role", "get_channel_member",
        "create_workflow_post", "submit_post_for_approval", "approve_post",
        "reject_post", "schedule_approved_post",
    ],
    "payments_repository": [
        "log_stars_payment", "process_stars_payment", "save_payment_receipt",
        "approve_payment_receipt", "reject_payment_receipt", "create_payment_order",
        "get_user_payment_history",
    ],
    "audit_repository": [
        "log_admin_action", "get_admin_audit_logs", "count_admin_audit_logs",
        "set_admin_role", "delete_admin_role", "create_support_ticket",
        "mark_support_ticket_answered", "get_system_stats",
    ],
    "settings_repository": [
        "get_setting", "set_setting", "get_settings_map", "delete_setting",
    ],
}


def test_api_intact():
    head("2) 🚪 Kritik API facade'da mavjud")
    for repo, names in CRITICAL_API.items():
        mod = ALL_REPOS[repo]
        missing = [n for n in names
                   if not callable(getattr(db, n, None))
                   or getattr(db, n) is not getattr(mod, n, None)]
        check(f"{repo}: {len(names)} ta kritik funksiya", not missing, str(missing))

    consts = ["EXPECTED_TABLES", "EXPECTED_INDEXES", "INTEGRITY_CONSTRAINTS",
              "INTEGRITY_INDEXES", "PLAN_LIMITS", "POST_BATCH_SIZE",
              "DB_POOL_MAX", "SCHEMA_FILE", "TX_ISOLATION_LEVELS",
              "PAYMENT_METHODS", "PAYMENT_STATUSES", "TEAM_ROLES",
              "DEFAULT_QUEUE_SLOTS", "VALID_TONES", "DELIVERY_BACKOFF_SECONDS",
              "FREE_QUEUE_MAX_POSTS", "POST_TEMPLATES_LIMIT",
              "CONTENT_SOURCES_LIMIT", "tashkent_tz", "_MISS",
              "save_channel_dna", "get_channel_dna", "create_draft_post",
              "request_post_approval"]
    absent = [c for c in consts if not hasattr(db, c)]
    check(f"{len(consts)} ta konstanta/alias facade'da", not absent, str(absent))

    # profil snapshot keshi onatijcha YADRODA qoladi (users repository emas)
    check("profil snapshot keshi yadroga tegishli",
          db.get_user_profile.__module__ == "database" and
          db.peek_user_profile.__module__ == "database",
          f"{db.get_user_profile.__module__} / {db.peek_user_profile.__module__}")

    core = ["db_cursor", "db_transaction", "transaction", "atransaction",
            "current_transaction", "db_atomic", "run_db", "run_in_thread",
            "init_db", "ping_db", "close_pool", "warm_pool", "cache_clear",
            "integrity_report", "validate_integrity_constraints"]
    absent_core = [c for c in core if not callable(getattr(db, c, None))]
    check(f"{len(core)} ta yadro API joyida", not absent_core, str(absent_core))


# ======================================================================
# 3-4) MOCK NUQTASI VA KECH BOG'LANISH
# ======================================================================
class _RecordingCursor:
    def __init__(self, log):
        self._log = log
        self.rowcount = 1
        self._rows = []

    def execute(self, query, params=None):
        self._log.append((" ".join(str(query).split()), params))
        return self

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def close(self):
        pass


def _patched_db_cursor(log, rows=()):
    """``database.db_cursor`` o'rniga ishlatiladigan soxta kursor."""
    @contextmanager
    def _dc(commit=False):
        cur = _RecordingCursor(log)
        cur._rows = list(rows)
        log.append(("__OPEN__", commit))
        yield cur
    return _dc


def test_mock_seam():
    head("3) 🎯 patch('database.db_cursor') repository'ga yetib boradi")
    from unittest.mock import patch

    log = []
    with patch("database.db_cursor", _patched_db_cursor(log, [("uz",)])):
        lang = db.get_user_language(4242)
    check("users: get_user_language SQL yuborildi",
          any("FROM users" in q for q, _ in log), str(log[:2]))
    check("users: natija to'g'ri qaytirdi", lang == "uz", repr(lang))

    log = []
    with patch("database.db_cursor", _patched_db_cursor(log, [(5,)])):
        n = posts_repository.get_queue_post_count(7)
    check("posts: get_queue_post_count SQL yuborildi",
          any("scheduled_posts" in q for q, _ in log), str(log[:2]))
    check("posts: natija to'g'ri", n == 5, repr(n))

    log = []
    with patch("database.db_cursor", _patched_db_cursor(log, [("ok",)])):
        settings_repository.get_setting("channel_ad_interval")
    check("settings: get_setting SQL yuborildi",
          any("system_settings" in q for q, _ in log), str(log[:2]))

    head("4) 🔗 Cross-repository kech bog'lanish")
    # posts.get_queue_slots -> settings.get_setting (BOSHQA repository):
    # chaqiruv facade orqali kech bog'langan, shuning uchun patch ishlaydi.
    import json
    wanted = ["07:00", "21:30"]
    with patch("database.get_setting", return_value=json.dumps(wanted)):
        slots = posts_repository.get_queue_slots(9)
    check("posts -> settings chaqiruvi facade orqali ishlaydi",
          slots == wanted, repr(slots))

    # channels.remove_channel -> teams._invalidate_rbac_resource_cache
    with patch("database.db_cursor", _patched_db_cursor([], [])):
        with patch("database._invalidate_rbac_resource_cache") as spy:
            channels_repository.remove_channel(1, "-100", is_admin=True)
    check("channels -> teams RBAC invalidate facade orqali chaqirildi", spy.called)


# ======================================================================
# 5) IMPORT TARTIBI
# ======================================================================
def test_import_order():
    head("5) 🔄 Import tartibi erkin (import sikli yo'q)")
    for label, code in (
        ("repositories -> database",
         "import repositories.posts_repository as p, database as d;"
         " assert d.get_due_posts is p.get_due_posts"),
        ("database -> repositories",
         "import database as d, repositories.posts_repository as p;"
         " assert d.get_due_posts is p.get_due_posts"),
        ("to'g'ridan-to'g'ri submodule",
         "import repositories.audit_repository as a, database as d;"
         " assert d.log_admin_action is a.log_admin_action"),
        ("runtime ko'prigi",
         "import database as d, repositories.runtime as r;"
         " assert r.db_cursor is not None and len(r.LATE_BOUND) > 0"),
    ):
        proc = subprocess.run(
            [sys.executable, "-c", code], cwd=BOT, capture_output=True, text=True,
            env={**os.environ, "ENVIRONMENT": "test"},
        )
        check(f"{label}", proc.returncode == 0,
              (proc.stderr or "").strip().splitlines()[-1:] and
              (proc.stderr or "").strip().splitlines()[-1] or "")


# ======================================================================
# 6) QATLAM INTIZOMI
# ======================================================================
DOMAIN_SQL = ("INSERT INTO payments", "FROM scheduled_posts sp",
              "FROM admin_audit_logs", "FROM channel_dna_profiles",
              "FROM payment_receipts")
POOL_INTERNALS = ("_get_pool", "ThreadedConnectionPool", "_WarmPool",
                  "_pool_sem", "getconn(")


def _executed_sql(source):
    """Moduldagi barcha ``cur.execute(...)`` SQL matnlarini yig'adi.

    AST bo'yicha ishlaydi — docstring va izohlardagi matnlar hisobga
    olinmaydi (faqat haqiqiy SQL chiquvadi).
    """
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute" and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            out.append(node.args[0].value)
    return "\n".join(out)


def test_layering_discipline():
    head("6) 🧱 Qatlam intizomi")
    db_src = open(db.__file__, encoding="utf-8").read()
    core_src = db_src.split("# 🧩 FACADE")[0]
    core_sql = _executed_sql(core_src)
    leaked = [s for s in DOMAIN_SQL if s in core_sql]
    check("core'da domain SQL yo'q (faqat sxema DDL va integritet)", not leaked,
          str(leaked))

    facade_present = "# 🧩 FACADE" in db_src
    check("database.py oxirida FACADE qismi bor", facade_present)

    for name, mod in ALL_REPOS.items():
        src = open(mod.__file__, encoding="utf-8").read()
        pool_hits = [s for s in POOL_INTERNALS if s in src]
        check(f"{name}: pool mexanikasi yo'q", not pool_hits, str(pool_hits))
        tree = ast.parse(src)
        tops = [n.name for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        check(f"{name}: modullar {len(tops)} ta funksiyani o'z ichida saqlaydi",
              len(tops) > 0)

    # runtime ko'prigi faqat kech bog'lanadi
    rt = open(sys.modules["repositories.runtime"].__file__, encoding="utf-8").read()
    check("runtime: modul darajasida `database` importi yo'q",
          "\nimport database" not in rt and "\nfrom database import" not in rt)
    check("runtime: import funksiya ichida (sikli xavfsiz)",
          "        import database" in rt)


# ======================================================================
# 7) TRANZAKSIYA KAFOLATI
# ======================================================================
class _FakeConn:
    """Ulashishni modellashtiruvchi minimal psycopg2 connection."""

    def __init__(self, log, autocommit=False):
        self._log = log
        self.autocommit = autocommit
        self.closed = 0
        self.info = type("I", (), {"transaction_status": 0})()

    def cursor(self):
        return _RecordingCursor(self._log)

    def commit(self):
        self._log.append("COMMIT")

    def rollback(self):
        self._log.append("ROLLBACK")

    def close(self):
        self.closed = 1


@contextmanager
def _fake_transport(log):
    """``_acquire_connection``/``_release_connection`` ni soxta ulashishga almashtiradi."""
    orig_acquire = db._acquire_connection
    orig_release = db._release_connection
    orig_discard = db._discard_connection
    made = []

    def _acquire():
        conn = _FakeConn(log)
        made.append(conn)
        return conn

    def _release(conn):
        log.append("RELEASE")

    def _discard(conn):
        log.append("DISCARD")

    db._acquire_connection = _acquire
    db._release_connection = _release
    db._discard_connection = _discard
    try:
        yield made
    finally:
        db._acquire_connection = orig_acquire
        db._release_connection = orig_release
        db._discard_connection = orig_discard


def test_transaction_guarantees():
    head("7) 🔒 Tranzaksiya chegaralari (BEGIN/COMMIT/ROLLBACK)")

    # --- db_atomic: muvaffaqiyat -> COMMIT
    log = []
    with _fake_transport(log):
        @db.db_atomic
        def ok_flow(a, b=1):
            with db.db_cursor(commit=False) as cur:
                cur.execute("SELECT 1")
            return a + b
        assert ok_flow(1) == 2
    check("db_atomic: muvaffaqiyatda COMMIT", "COMMIT" in log, str(log))
    check("db_atomic: bitta ulanish olindi", log.count("RELEASE") == 1, str(log))
    check("db_atomic: ichki db_cursor qo'shimcha ulanish OLMADI",
          log.count("RELEASE") == 1, str(log))

    # --- db_atomic: xato -> ROLLBACK
    log = []
    with _fake_transport(log):
        @db.db_atomic
        def bad_flow():
            with db.db_cursor() as cur:
                cur.execute("SELECT 1")
            raise ValueError("boom")
        try:
            bad_flow()
        except ValueError:
            pass
    check("db_atomic: xatoda ROLLBACK", "ROLLBACK" in log and "COMMIT" not in log,
          str(log))
    check("db_atomic: xatoda ulanish ham qaytarildi", "RELEASE" in log, str(log))

    # --- nested tranzaksiya -> SAVEPOINT, yangi ulanish yo'q.
    # Ichki blok xatoledi, lekin tashqi tranzaksiya YASHIRILMAYDI —
    # savepoint'ga rollback qilinadi va tashqi blok davom etadi.
    log = []
    with _fake_transport(log):
        with db.db_transaction() as cur:
            cur.execute("SELECT 'outer'")
            try:
                with db.db_transaction() as cur2:
                    cur2.execute("SELECT 'inner'")
                    raise RuntimeError("inner fail")
            except RuntimeError:
                cur.execute("SELECT 'outer continues'")
    check("nested: SAVEPOINT ochildi",
          any("SAVEPOINT" in str(x) for x in log), str(log))
    check("nested: ROLLBACK TO SAVEPOINT bajarildi",
          any("ROLLBACK TO SAVEPOINT" in str(x) for x in log), str(log))
    check("nested: tashqi tranzaksiya COMMIT bilan tugadi", "COMMIT" in log,
          str(log))
    check("nested: BITTA ulanish (2 ta RELEASE emas)", log.count("RELEASE") == 1,
          str(log))
    check("nested: tashqi blok savepoint'dan keyin davom etdi",
          any("outer continues" in str(x) for x in log), str(log))

    # --- ichki xato tashqariga tarqalmasa ham, tashqi catch qilinadi
    log = []
    with _fake_transport(log):
        with db.db_transaction() as cur:
            cur.execute("SELECT 'outer2'")
            try:
                with db.db_transaction() as cur2:
                    raise RuntimeError("inner2")
            except RuntimeError:
                pass
    check("nested: tashqi blok catch qilib, o'z ishini COMMIT qiladi",
          "COMMIT" in log and log.count("RELEASE") == 1, str(log))
    check("nested: SAVEPOINT ochildi",
          any("SAVEPOINT" in str(x) for x in log), str(log))
    check("nested: ROLLBACK TO SAVEPOINT bajarildi",
          any("ROLLBACK TO SAVEPOINT" in str(x) for x in log), str(log))
    check("nested: tashqi COMMIT bajarildi", "COMMIT" in log, str(log))
    check("nested: BITTA ulanish (2 ta RELEASE emas)", log.count("RELEASE") == 1,
          str(log))

    # --- async transaction: BEGIN/COMMIT alohida thread'da
    import asyncio
    log = []
    with _fake_transport(log):
        async def _go():
            async with db.transaction() as cur:
                await asyncio.to_thread(cur.execute, "SELECT 1")
        asyncio.run(_go())
    check("async transaction: COMMIT", "COMMIT" in log, str(log))
    check("async transaction: bitta ulanish", log.count("RELEASE") == 1, str(log))

    log = []
    with _fake_transport(log):
        async def _go_fail():
            async with db.transaction():
                raise RuntimeError("x")
        try:
            asyncio.run(_go_fail())
        except RuntimeError:
            pass
    check("async transaction: xatoda ROLLBACK",
          "ROLLBACK" in log and "COMMIT" not in log, str(log))

    # --- izolatsiya darajasi oq ro'yxati
    try:
        with db.db_transaction(isolation_level="DROP TABLE"):
            pass
        check("noma'lum izolatsiya darajasi rad etiladi", False)
    except ValueError:
        check("noma'lum izolatsiya darajasi rad etiladi", True)
    except Exception as e:
        check("noma'lum izolatsiya darajasi rad etiladi", False, repr(e))

    # --- 3 ta kritik oqim chegarasi HAQIQATDA bitta atomik blok
    head("7b) 🔒 Kritik oqimlar bitta atomik blokda")
    flows = {
        "post rejalashtirish": ("schedule_week_posts",
                                "with db_cursor(commit=True) as cur:"),
        "kvota yechish": ("reserve_ai_request", "with db_transaction("),
    }
    for label, (fn_name, marker) in flows.items():
        src = inspect.getsource(getattr(db, fn_name))
        check(f"{label}: {fn_name} — atomik blok belgisi",
              marker in src, src[:120])

    pay_src = inspect.getsource(payments_repository.log_stars_payment)
    check("to'lov qabul qilish: log_stars_payment — commit chegarasi",
          "with db_cursor(commit=True) as cur:" in pay_src, pay_src[:120])
    plan_src = inspect.getsource(users_repository.set_user_plan)
    check("to'lov qabul qilish: set_user_plan — commit chegarasi",
          "with db_cursor(commit=True) as cur:" in plan_src, plan_src[:120])

    week_src = inspect.getsource(scheduler_repository.schedule_week_posts)
    check("post rejalashtirish: advisory qulf (parallel himoyasi)",
          "pg_advisory_xact_lock" in week_src)
    check("post rejalashtirish: bitta tranzaksiya",
          week_src.count("with db_cursor(commit=True) as cur:") == 1,
          str(week_src.count("with db_cursor(commit=True) as cur:")))


# ======================================================================
# 8) LEAK HIMOYASI
# ======================================================================
def test_leak_guard():
    head("8) 💧 Ulanish leak himoyasi")
    check("conn_balance() boshlang'ich 0", db.conn_balance() == 0,
          str(db.conn_balance()))

    before = db.conn_balance()
    db._conn_acquired()
    db._conn_acquired()
    check("olingan ulanish hisobga olinadi", db.conn_balance() == before + 2,
          str(db.conn_balance()))
    db._conn_released()
    db._conn_released()
    check("qaytarilgan ulanish hisobdan tushadi", db.conn_balance() == before,
          str(db.conn_balance()))

    db._conn_released()   # qo'lda ortiqcha chaqirilsa ham manfiy bo'lmaydi
    check("ortiqcha release manfiy hisobga kirmaydi", db.conn_balance() == 0,
          str(db.conn_balance()))

    st = db.conn_stats()
    check("conn_stats(): inflight/high_water/overflow kalitlari",
          {"conn_inflight", "conn_high_water", "conn_overflow"} <= set(st), str(st))

    os_st = db.offload_stats()
    check("offload_stats(): inflight/peak kalitlari",
          {"offload_inflight", "offload_peak"} <= set(os_st), str(os_st))

    pool_st = db.get_db_pool_status()
    check("get_db_pool_status(): hisob kalitlari chiqadi",
          {"conn_inflight", "conn_high_water", "conn_overflow",
           "offload_inflight", "offload_peak"} <= set(pool_st), str(sorted(pool_st)))
    check("get_db_pool_status(): eski kalitlar saqlanadi",
          {"ready", "max", "used", "available"} <= set(pool_st),
          str(sorted(pool_st)))

    # tranzaksiya tugagach ulanish balansi yana nolga teng
    log = []
    with _fake_transport(log):
        with db.db_transaction() as cur:
            cur.execute("SELECT 1")
    check("tranzaksiya tugagach balans 0", db.conn_balance() == 0,
          str(db.conn_balance()))

    # run_db offload hisobini tozalaydi
    import asyncio
    asyncio.run(db.run_db(lambda: 42))
    check("run_db: offload inflight 0 ga qaytdi",
          db.offload_stats()["offload_inflight"] == 0,
          str(db.offload_stats()))
    check("run_db: peak > 0 (o'lchov ishlayapti)",
          db.offload_stats()["offload_peak"] >= 1, str(db.offload_stats()))


# ======================================================================
# 9) KO'CHIRILGANLIK TO'LIQLIGI
# ======================================================================
def test_no_duplicate_definitions():
    head("9) 📚 Har bir funksiya yagona manzilda")
    db_src = open(db.__file__, encoding="utf-8").read()
    db_names = set()
    for tree in [ast.parse(db_src)]:
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                db_names.add(n.name)

    total, dupes = 0, []
    seen = {}
    for name, mod in ALL_REPOS.items():
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                if n.name in seen or n.name in db_names:
                    dupes.append(f"{n.name} ({seen.get(n.name, 'database')})")
                seen[n.name] = name
    check(f"dublikat funksiya yo'q ({total} ta repository funksiyasi)",
          not dupes, str(dupes[:8]))

    check("repository funksiyalari soni 200+", total >= 200, str(total))

    # har bir modul kamida bitta funksiya beradi
    for name, mod in ALL_REPOS.items():
        n = len([x for x in ast.parse(open(mod.__file__, encoding="utf-8").read()).body
                 if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef))])
        check(f"{name}: funksiyalar mavjud", n > 0, str(n))


def main():
    print("PostAssist V2 — PHASE 4: DATABASE MODULLASHUVI VA REPOSITORY PATTERN")
    test_facade_parity()
    test_api_intact()
    test_mock_seam()
    test_import_order()
    test_layering_discipline()
    test_transaction_guarantees()
    test_leak_guard()
    test_no_duplicate_definitions()

    print()
    print("=" * 64)
    total = PASSED + FAILED
    print(f"repository_layering: o'tdi={PASSED}, xato={FAILED} (jami {total})")
    if FAILED:
        print("FAIL — repository qatlami sinovlari yashil EMAS ✘")
        sys.exit(1)
    print("Barcha repository qatlami sinovlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
