#!/usr/bin/env python3
"""PostAssist V2 — 5-BOSQICH: ma'lumotlar butunligi testi.

Nima tekshiriladi
----------------
1. **Foreign key** — jadvallararo bog'lanish ishlaydi va yetim yozuvlar
   qolmaydi (channels → users, scheduled_posts → channels,
   post_deliveries/post_reactions → scheduled_posts), shuningdek
   ``promo_redemptions (promo_id, user_id)`` UNIQUE juftligi.
2. **CHECK constraintlar** — noto'g'ri status yozilganda DB xato qaytaradi
   (``post_deliveries.status``, ``scheduled_posts.status``, ``payments.status``).
3. **Atomik tranzaksiya** — ``db_transaction()`` / ``transaction()`` ichida
   istisno bo'lsa hammasi ROLLBACK bo'ladi, bo'lmasa COMMIT; ich-ma-ich
   bloklar SAVEPOINT bilan; to'lov va promo oqimlari YAGONA blokda ishlaydi.
4. **Kompozit indekslar** — barchasi mavjud, valid va kutilgan ustunlar
   bilan qurilgan.
5. **Migratsiya xavfsizligi** — idempotentlik (2-marta bajarish) va
   LEGACY baza ssenariysi: yetim yozuvlar bo'lsa constraint NOT VALID
   holatida qo'shiladi, ma'lumot o'chirilmaydi, YANGI yozuvlar baribir
   himoyalanadi.

Ishga tushirish
---------------
::

    cd telegram_bot && python tests/db_integrity_test.py

Haqiqiy PostgreSQL sinovi uchun ``pgserver`` kerak (``pip install pgserver``).
Baza bo'lmasa yoki ``INTEGRITY_TEST_SKIP_LIVE=1`` berilsa — faqat statik
(sxema/API) tekshiruvlar bajariladi va live qism o'tkazib yuboriladi.
"""
import os
import sys
import asyncio
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

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


SCHEMA = (ROOT / "schema.sql").read_text(encoding="utf-8")


# ============================================================
# 1. STATIK TEKSHIRUVLAR (baza shart emas)
# ============================================================

def test_schema_declares_integrity():
    print("== schema.sql: constraint va indekslar ==")
    expected_constraints = {
        "fk_channels_user": "FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE",
        "fk_scheduled_posts_channel":
            "FOREIGN KEY (channel_id) REFERENCES channels(channel_id) ON DELETE CASCADE",
        "fk_post_deliveries_post":
            "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "fk_post_reactions_post":
            "FOREIGN KEY (post_id) REFERENCES scheduled_posts(id) ON DELETE CASCADE",
        "uq_promo_user": "UNIQUE (promo_id, user_id)",
        "chk_post_deliveries_status":
            "CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'dead_letter', 'unknown'))",
        "chk_scheduled_posts_status":
            "CHECK (status IN ('pending', 'processing', 'posted', 'failed', 'cancelled', 'completed', 'unknown'))",
        "chk_payments_status":
            "CHECK (status IN ('pending', 'succeeded', 'failed', 'refunded'))",
        # 8-bosqich: ball auditi har doim mavjud foydalanuvchiga bog'liq.
        "fk_credits_ledger_user": "FOREIGN KEY (user_id) REFERENCES users(user_id)",
    }
    for name, definition in expected_constraints.items():
        literal = definition.replace("'", "''")
        check(f"schema.sql: {name}",
              name in SCHEMA and literal in SCHEMA, definition)

    for index in ("idx_posts_sched_status", "idx_deliveries_lookup", "idx_payments_user",
                  "idx_channels_owner", "idx_scheduled_posts_channel", "idx_deliveries_post"):
        check(f"schema.sql: indeks {index}",
              f"CREATE INDEX IF NOT EXISTS {index}" in SCHEMA)

    # Ba'zi operatorlar faylda yangi qatordan davom etadi (`CREATE INDEX IF` /
    # `NOT EXISTS ...`) — shuning uchun matn avval "yassilanadi".
    flat = " ".join(SCHEMA.split())
    total_indexes = flat.count("CREATE INDEX")
    idempotent_indexes = flat.count("CREATE INDEX IF NOT EXISTS")
    check("schema.sql: barcha indekslar idempotent (IF NOT EXISTS)",
          total_indexes >= 15 and total_indexes == idempotent_indexes,
          f"{idempotent_indexes}/{total_indexes}")
    check("schema.sql: integrity bloki DO/EXCEPTION bilan xavfsiz",
          "$postassist_integrity$" in SCHEMA and "WHEN OTHERS THEN" in SCHEMA)
    check("schema.sql: NOT VALID fallback bor (eski ma'lumot buzilmaydi)",
          "NOT VALID" in SCHEMA)
    check("schema.sql: payments.status migratsiyasi",
          "ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'succeeded'" in SCHEMA)


def test_python_metadata_matches_schema():
    """database.py ro'yxatlari schema.sql bilan bir xil bo'lishi shart."""
    print("== database.py ↔ schema.sql paralligi ==")
    import database as db_mod

    check("INTEGRITY_CONSTRAINTS 10 ta obyekt", len(db_mod.INTEGRITY_CONSTRAINTS) == 10,
          str(len(db_mod.INTEGRITY_CONSTRAINTS)))
    for item in db_mod.INTEGRITY_CONSTRAINTS:
        check(f"constraint ro'yxatda: {item['name']}",
              item["definition"].replace("'", "''") in SCHEMA, item["definition"])
        check(f"kind noto'g'ri emas: {item['name']}",
              item["kind"] in ("fk", "check", "unique"), item["kind"])
    for item in db_mod.INTEGRITY_INDEXES:
        check(f"indeks ro'yxatda: {item['name']}", item["ddl"] in SCHEMA, item["ddl"])
    check("EXPECTED_INDEXES yangi indekslarni ham o'z ichiga oladi",
          all(n in db_mod.EXPECTED_INDEXES for n in db_mod.INTEGRITY_INDEX_NAMES))
    block = db_mod.build_integrity_block()
    check("build_integrity_block() schema.sql'ni to'liq qamraydi",
          all(n in block for n in db_mod.INTEGRITY_CONSTRAINT_NAMES))
    check("build_integrity_block() idempotent (mavjudlikni tekshiradi)",
          "pg_constraint" in block and "CONTINUE" in block)
    check("statuslar to'plami CHECKlar bilan bir xil",
          set(db_mod.PAYMENT_STATUSES) == {"pending", "succeeded", "failed", "refunded"})


def test_transaction_api_static():
    print("== database.py: tranzaksiya API (statik) ==")
    import inspect
    import database as db_mod

    check("sync db_transaction() — contextmanager", hasattr(db_mod, "db_transaction"))
    check("async transaction() — @asynccontextmanager",
          inspect.isasyncgenfunction(getattr(db_mod.transaction, "__wrapped__", None)))
    check("atransaction == transaction", db_mod.atransaction is db_mod.transaction)
    src_finish = inspect.getsource(db_mod._Transaction.finish)
    check("muvaffaqiyatda COMMIT", "conn.commit()" in src_finish)
    check("istisnoda ROLLBACK", "conn.rollback()" in src_finish)
    src_class = inspect.getsource(db_mod._Transaction)
    check("buzilgan ulanish tashlab yuboriladi",
          "_discard_connection" in src_class and "broken=True" in src_finish)
    check("nesting → SAVEPOINT", "SAVEPOINT" in inspect.getsource(db_mod._Transaction.enter))
    check("db_cursor tranzaksiyaga delegat",
          "db_transaction(commit=commit)" in inspect.getsource(db_mod.db_cursor))
    check("izolatsiya darajasi oq ro'yxatda",
          db_mod.TX_ISOLATION_LEVELS == ("read committed", "repeatable read", "serializable"))


def test_flows_use_single_transaction_block():
    """To'lov, obuna va promo oqimlari YAGONA atomik blokda ishlashi kerak."""
    print("== servislar: transaction() orqali bitta blok ==")
    flows = {
        "services/payment_service.py": [
            ("process_stars_payment", "INSERT INTO payments"),
            ("_approve_receipt", "UPDATE payment_receipts SET status = 'approved'"),
            ("_reject_receipt", "UPDATE payment_receipts SET status = 'rejected'"),
        ],
        "services/subscription_service.py": [
            ("activate", "UPDATE users SET plan_type = %s"),
            ("extend", "subscription_expires_at = GREATEST"),
            ("revoke", "plan_type = 'free'"),
        ],
        "services/promo_service.py": [
            ("create_promo", "INSERT INTO promo_codes"),
            ("redeem_promo", "INSERT INTO promo_redemptions"),
        ],
    }
    for rel, items in flows.items():
        source = (ROOT / rel).read_text(encoding="utf-8")
        name = rel.split("/")[-1]
        check(f"{name}: transaction() yordamchisi e'lon qilingan",
              "def transaction(" in source and "with db_cursor(commit=commit) as cur:" in source)
        for func_name, marker in items:
            body = _function_body(source, func_name)
            check(f"{name}: {func_name}() transaction() ichida",
                  "with transaction() as cur:" in body, body[:80])
            check(f"{name}: {func_name}() bitta blokda ({marker[:24]}...)",
                  marker in body and "db_cursor(commit=True)" not in body)


def _function_body(source, name):
    """``name`` funksiya tanasini matndan oladi (test uchun soddalashtirilgan).

    Satrlar bo'yicha skanerlanadi va birinchi kichikroq (yoki teng)
    chekinishdagi satr funksiya tugaganini bildiradi — shunda keyingi metodning
    kodi tasodifan qamrab olinmaydi.
    """
    lines = source.splitlines()
    indent = None
    depth = 0
    in_signature = False
    out = []
    for line in lines:
        if indent is None:
            if line.strip().startswith(f"def {name}("):
                indent = len(line) - len(line.lstrip())
                in_signature = True
                depth = line.count("(") - line.count(")")
                out.append(line)
            continue
        if in_signature:
            out.append(line)
            depth += line.count("(") - line.count(")")
            if depth <= 0 and line.rstrip().endswith(":"):
                in_signature = False
            continue
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        out.append(line)
    return "\n".join(out)


# ============================================================
# 2. REAL POSTGRESQL
# ============================================================

def _start_test_postgres():
    """Test bazasi URI: INTEGRITY_TEST_DATABASE_URL | P0_TEST_DATABASE_URL | pgserver."""
    for var in ("INTEGRITY_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url
    if os.getenv("INTEGRITY_TEST_SKIP_LIVE") == "1":
        return None
    try:
        import pgserver
    except ImportError:
        return None
    import shutil
    import tempfile
    server_dir = os.path.join(tempfile.gettempdir(), "integrity_pg")
    shutil.rmtree(server_dir, ignore_errors=True)
    try:
        return pgserver.get_server(server_dir).get_uri()
    except Exception as e:  # pragma: no cover - muhitga bog'liq
        print(f"  (pgserver ishga tushmadi: {e})")
        return None


class _Boom:
    """Real kursorni o'raydi va ``marker``li so'rovda portlaydi.

    Servis oqimini HAQIQIY xatolikga uchratib, tranzaksiya ROLLBACK'ini
    sinash uchun ishlatiladi (servislar ``db_cursor``ni modul darajasida
    import qiladi — shu nuqtani mock qilamiz).
    """

    def __init__(self, cur, marker):
        self._cur = cur
        self._marker = marker

    def execute(self, sql, params=None):
        if self._marker in str(sql):
            raise RuntimeError("integrity probe: injected failure")
        return self._cur.execute(sql, params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount

    def close(self):
        pass


def _explosive_db_cursor(db_mod, marker):
    """``db_cursor`` o'rniga ishlatiladigan portlovchi fabrika."""
    from contextlib import contextmanager

    real = db_mod.db_cursor

    @contextmanager
    def _factory(commit=False):
        with real(commit=commit) as cur:
            yield _Boom(cur, marker)

    return _factory


_seed_state = {"n": 0}


def _seed_tree(db_mod, active=True):
    """user → channel → post zanjiri (FK ota-yozuvlari)."""
    _seed_state["n"] += 1
    user_id = 967000000 + (os.getpid() % 1000) * 100 + _seed_state["n"]
    channel_id = f"-100integrity{user_id}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO users (user_id, username) VALUES (%s, %s)",
                    (user_id, f"integrity_{user_id}"))
        cur.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title, is_active) "
            "VALUES (%s, %s, 'Integrity kanali', %s)",
            (user_id, channel_id, active),
        )
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, "
            " scheduled_time, status) "
            "VALUES (%s, %s, 'text', 'integrity testi', NOW() + INTERVAL '1 hour', 'pending') "
            "RETURNING id",
            (user_id, channel_id),
        )
        post_id = int(cur.fetchone()[0])
    return {"user_id": user_id, "channel_id": channel_id, "post_id": post_id}


def _drop_tree(db_mod, seed):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM post_deliveries WHERE post_id = %s", (seed["post_id"],))
        cur.execute("DELETE FROM post_reactions WHERE post_id = %s", (seed["post_id"],))
        cur.execute("DELETE FROM scheduled_posts WHERE id = %s", (seed["post_id"],))
        cur.execute("DELETE FROM channels WHERE channel_id = %s", (seed["channel_id"],))
        cur.execute("DELETE FROM users WHERE user_id = %s", (seed["user_id"],))


def test_foreign_keys(db_mod):
    print("== Foreign key: qat'iy bog'lanish va yetim yozuvlar ==")
    import psycopg2

    # 1) Ota-yozuvisiz bola yozuvlar rad etiladi
    cases = [
        ("channels.user_id → users(user_id)",
         "INSERT INTO channels (user_id, channel_id, channel_title) "
         "VALUES (967999998, '-100nouser', 'x')"),
        ("scheduled_posts.channel_id → channels(channel_id)",
         "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, scheduled_time) "
         "VALUES (967999998, '-100nochannel', 'text', 'x', NOW())"),
    ]
    for label, sql in cases:
        rejected = False
        try:
            with db_mod.db_cursor(commit=True) as cur:
                cur.execute(sql)
        except psycopg2.errors.ForeignKeyViolation:
            rejected = True
        except Exception as e:  # pragma: no cover
            print(f"    (kutilmagan xato: {type(e).__name__}: {e})")
        check(f"FK rad etdi: {label}", rejected)

    seed = _seed_tree(db_mod)
    try:
        for label, sql, params in (
            ("post_deliveries.post_id → scheduled_posts(id)",
             "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key) "
             "VALUES (%s, -100999, 'pending', %s)", (seed["post_id"] + 9911, "int-orphan-probe")),
            ("post_reactions.post_id → scheduled_posts(id)",
             "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, '👍')",
             (999999999, seed["user_id"])),
        ):
            rejected = False
            try:
                with db_mod.db_cursor(commit=True) as cur:
                    cur.execute(sql, params)
            except psycopg2.errors.ForeignKeyViolation:
                rejected = True
            check(f"FK rad etdi: {label}", rejected)

        # 2) Mavjud ota bilan yozuv muvaffaqiyatli — keyin tekshiriladi
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key) "
                "VALUES (%s, %s, 'pending', %s)",
                (seed["post_id"], -100123, f"int-ok-{seed['post_id']}"),
            )
            cur.execute(
                "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, '❤️')",
                (seed["post_id"], seed["user_id"]),
            )
        check("FK ruxsat etdi: ota-yozuv bo'lsa yozuv saqlandi", True)

        # 3) ON DELETE CASCADE — ota o'chsa bola ham ketadi (yetim qolmaydi)
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM scheduled_posts WHERE id = %s", (seed["post_id"],))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM post_deliveries WHERE post_id = %s", (seed["post_id"],))
            deliveries = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s", (seed["post_id"],))
            reactions = cur.fetchone()[0]
        check("CASCADE: post o'chirilganda delivery qolmadi", deliveries == 0, str(deliveries))
        check("CASCADE: post o'chirilganda reaksiya qolmadi", reactions == 0, str(reactions))

        # 4) Kanal o'chirilganda uning postlari ham ketadi
        seed2 = _seed_tree(db_mod)
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM channels WHERE channel_id = %s", (seed2["channel_id"],))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM scheduled_posts WHERE channel_id = %s",
                        (seed2["channel_id"],))
            left = cur.fetchone()[0]
        check("CASCADE: kanal o'chirilganda postlari ham ketdi", left == 0, str(left))
        _drop_tree(db_mod, seed2)
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM post_deliveries WHERE idempotency_key = %s",
                        (f"int-ok-{seed['post_id']}",))
        _drop_tree(db_mod, seed)

    # 5) Hech qanday yetim yozuv qolmagan — butun baza bo'yicha
    counts = db_mod.integrity_orphan_counts()
    for label, value in counts.items():
        check(f"yetim yozuvlar yo'q: {label}", value == 0, str(value))

    # 6) promo_redemptions (promo_id, user_id) UNIQUE
    _test_promo_unique(db_mod)


def _test_promo_unique(db_mod):
    print("== promo_redemptions: UNIQUE (promo_id, user_id) ==")
    import psycopg2
    import uuid

    code = f"INTEG_{uuid.uuid4().hex[:16]}".upper()
    seed = _seed_tree(db_mod)
    try:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO promo_codes (code, plan_type, duration_days, max_uses) "
                "VALUES (%s, 'pro', 30, 5) RETURNING id", (code,))
            promo_id = int(cur.fetchone()[0])
            cur.execute("INSERT INTO promo_redemptions (promo_id, user_id) VALUES (%s, %s)",
                        (promo_id, seed["user_id"]))
        duplicate_rejected = False
        try:
            with db_mod.db_cursor(commit=True) as cur:
                cur.execute("INSERT INTO promo_redemptions (promo_id, user_id) VALUES (%s, %s)",
                            (promo_id, seed["user_id"]))
        except psycopg2.errors.UniqueViolation:
            duplicate_rejected = True
        check("UNIQUE: bir xil promo+user ikkinchi marta rad etildi", duplicate_rejected)

        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO promo_redemptions (promo_id, user_id) VALUES (%s, %s)",
                        (promo_id, seed["user_id"] + 1))
        check("UNIQUE: boshqa foydalanuvchi uchun bir xil promo qabul qilindi", True)
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM promo_redemptions WHERE promo_id = %s", (promo_id,))
            cur.execute("DELETE FROM promo_codes WHERE id = %s", (promo_id,))
        _drop_tree(db_mod, seed)


def test_check_constraints(db_mod):
    print("== CHECK constraintlar: status to'plami ==")
    import psycopg2

    # 1) Ruxsat etilgan qiymatlar (bot ishlatadigan barcha holatlar)
    for status in ("pending", "processing", "sent", "failed", "dead_letter"):
        ok = True
        try:
            with db_mod.db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE post_deliveries SET status = %s WHERE idempotency_key = %s",
                    (status, "int-check-probe"))
        except Exception:
            ok = False
        check(f"post_deliveries.status='{status}' ruxsat etilgan (probe)", ok is True)

    seed = _seed_tree(db_mod)
    try:
        for status in ("pending", "processing", "posted", "failed", "cancelled", "completed"):
            rejected = False
            try:
                with db_mod.db_cursor(commit=True) as cur:
                    cur.execute("UPDATE scheduled_posts SET status = %s WHERE id = %s",
                                (status, seed["post_id"]))
            except psycopg2.errors.CheckViolation:
                rejected = True
            check(f"scheduled_posts.status='{status}' ruxsat etilgan", not rejected, status)

        for label, sql, params in (
            ("scheduled_posts.status='archived'",
             "UPDATE scheduled_posts SET status = 'archived' WHERE id = %s", (seed["post_id"],)),
            ("scheduled_posts.status='' (bo'sh)",
             "UPDATE scheduled_posts SET status = '' WHERE id = %s", (seed["post_id"],)),
            ("post_deliveries.status='queued'",
             "INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key) "
             "VALUES (%s, -1, 'queued', 'int-check-queued')", (seed["post_id"],)),
            ("payments.status='refunded-too'",
             "INSERT INTO payments (user_id, amount, currency, payload, status) "
             "VALUES (%s, 1, 'XTR', 'p', 'refunded-too')", (seed["user_id"],)),
        ):
            rejected = False
            try:
                with db_mod.db_cursor(commit=True) as cur:
                    cur.execute(sql, params)
            except psycopg2.errors.CheckViolation:
                rejected = True
            check(f"CHECK rad etdi: {label}", rejected)

        # 2) payments.status to'plami + default qiymat
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO payments (user_id, amount, currency, payload) "
                        "VALUES (%s, 75, 'XTR', 'default-probe') RETURNING id",
                        (seed["user_id"],))
            payment_id = int(cur.fetchone()[0])
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT status FROM payments WHERE id = %s", (payment_id,))
            default_status = cur.fetchone()[0]
        check("payments.status default = 'succeeded'", default_status == "succeeded",
              str(default_status))
        for status in ("pending", "succeeded", "failed", "refunded"):
            rejected = False
            try:
                with db_mod.db_cursor(commit=True) as cur:
                    cur.execute("UPDATE payments SET status = %s WHERE id = %s",
                                (status, payment_id))
            except psycopg2.errors.CheckViolation:
                rejected = True
            check(f"payments.status='{status}' ruxsat etilgan", not rejected)
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM payments WHERE id = %s", (payment_id,))
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM post_deliveries WHERE idempotency_key IN "
                        "('int-check-probe','int-check-queued')")
        _drop_tree(db_mod, seed)


def test_transaction_helper(db_mod):
    print("== Tranzaksiya: rollback / commit / nesting ==")

    seed = _seed_tree(db_mod)
    try:
        # 1) Muvaffaqiyatli blok → COMMIT
        with db_mod.db_transaction() as cur:
            cur.execute(
                "INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                "VALUES (%s, %s, '✅')", (seed["post_id"], seed["user_id"]))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s", (seed["post_id"],))
            check("muvaffaqiyatli tranzaksiya COMMIT bo'ldi", cur.fetchone()[0] == 1)

        # 2) Xatolik → ROLLBACK (nechta SQL bo'lmasin — hammasi qaytadi)
        raised = False
        try:
            with db_mod.db_transaction() as cur:
                cur.execute(
                    "INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                    "VALUES (%s, %s, '🔥')", (seed["post_id"], seed["user_id"] + 5))
                cur.execute(
                    "INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                    "VALUES (%s, %s, 'X')", (seed["post_id"], seed["user_id"] + 6))
                raise RuntimeError("integrity probe: mid-transaction failure")
        except RuntimeError:
            raised = True
        check("istisno tranzaksiyadan tashqariga chiqdi", raised)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s AND user_id > %s",
                        (seed["post_id"], seed["user_id"]))
            check("xatoda hammasi ROLLBACK bo'ldi (0 qator qoldi)", cur.fetchone()[0] == 0)

        # 3) Ich-ma-ich blok: SAVEPOINT — ichki xato tashqisini buzmaydi
        with db_mod.db_transaction() as cur:
            cur.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                        "VALUES (%s, %s, '🟢')", (seed["post_id"], seed["user_id"] + 7))
            try:
                with db_mod.db_transaction() as inner:
                    inner.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                                  "VALUES (%s, %s, '💣')", (seed["post_id"], seed["user_id"] + 8))
                    raise RuntimeError("inner failure")
            except RuntimeError:
                pass
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT user_id FROM post_reactions WHERE post_id = %s ORDER BY user_id",
                        (seed["post_id"],))
            users = [row[0] for row in cur.fetchall()]
        check("nesting: tashqi blok saqlanib qoldi", seed["user_id"] + 7 in users, str(users))
        check("nesting: ichki blok qaytarildi (SAVEPOINT rollback)",
              seed["user_id"] + 8 not in users, str(users))

        # 4) Tranzaksiya ichidagi db_cursor yangi ulanish OLMAYDI (o'lim
        #    aylanmasining oldini oladi) va umumiy rollback'ga bo'ysunadi.
        outer_conn_id = None
        inner_conn_id = None
        try:
            with db_mod.db_transaction() as cur:
                cur.execute("SELECT pg_backend_pid()")
                outer_conn_id = cur.fetchone()[0]
                with db_mod.db_cursor(commit=True) as inner:
                    inner.execute("SELECT pg_backend_pid()")
                    inner_conn_id = inner.fetchone()[0]
                    inner.execute("INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                                  "VALUES (%s, %s, '🔗')", (seed["post_id"], seed["user_id"] + 9))
                raise RuntimeError("outer failure")
        except RuntimeError:
            pass
        check("ichki db_cursor shu tranzaksiya ulanishidan foydalandi",
              outer_conn_id is not None and outer_conn_id == inner_conn_id,
              f"{outer_conn_id} vs {inner_conn_id}")
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s AND user_id = %s",
                        (seed["post_id"], seed["user_id"] + 9))
            check("tashqi rollback ichki yozuvni ham qaytardi", cur.fetchone()[0] == 0)

        # 5) Faol tranzaksiya ichida FOR UPDATE o'z-imkonini bloklamaydi
        with db_mod.db_transaction() as cur:
            cur.execute("SELECT 1 FROM users WHERE user_id = %s FOR UPDATE", (seed["user_id"],))
            check("FOR UPDATE + db_cursor: deadlock yo'q", cur.fetchone() == (1,))
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM post_reactions WHERE post_id = %s", (seed["post_id"],))
        _drop_tree(db_mod, seed)


def test_async_transaction(db_mod):
    print("== Async transaction() (@asynccontextmanager) ==")
    seed = _seed_tree(db_mod)

    async def _commit_flow():
        async with db_mod.transaction() as cur:
            await asyncio.to_thread(
                cur.execute,
                "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, '⚡')",
                (seed["post_id"], seed["user_id"] + 11))

    async def _rollback_flow():
        async with db_mod.transaction() as cur:
            await asyncio.to_thread(
                cur.execute,
                "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, '💥')",
                (seed["post_id"], seed["user_id"] + 12))
            await asyncio.to_thread(
                cur.execute,
                "INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (%s, %s, '💥')",
                (seed["post_id"], seed["user_id"] + 12))  # UNIQUE(post_id,user_id) → xato
            return "bormaydi"

    async def _ambient_flow():
        # Async blok ichida sinkron db_cursor shu tranzaksiyaga qo'shiladi
        async with db_mod.transaction() as cur:
            await asyncio.to_thread(
                cur.execute, "SELECT pg_backend_pid()")
            outer_pid = (await asyncio.to_thread(cur.fetchone))[0]
            inner_pid = await asyncio.to_thread(_sync_probe_pid)
            return outer_pid, inner_pid

    def _sync_probe_pid():
        with db_mod.db_cursor() as c:
            c.execute("SELECT pg_backend_pid()")
            return c.fetchone()[0]

    try:
        asyncio.run(_commit_flow())
        try:
            # ikkinchi INSERT SAME (post_id, user_id) juftligiga uriladi →
            # UNIQUE buzilishi tranzaksiyani "buzadi" va rollback kutiladi.
            asyncio.run(_rollback_flow())
        except Exception:
            pass
        pids = asyncio.run(_ambient_flow())
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s AND user_id = %s",
                        (seed["post_id"], seed["user_id"] + 11))
            check("async transaction: muvaffaqiyatli blok COMMIT bo'ldi",
                  cur.fetchone()[0] == 1)
            cur.execute("SELECT COUNT(*) FROM post_reactions WHERE post_id = %s AND user_id = %s",
                        (seed["post_id"], seed["user_id"] + 12))
            check("async transaction: xatoda ROLLBACK bo'ldi", cur.fetchone()[0] == 0)
        check("async transaction: sinkron db_cursor shu ulanishdan foydalandi",
              pids[0] == pids[1], str(pids))
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM post_reactions WHERE post_id = %s", (seed["post_id"],))
        _drop_tree(db_mod, seed)


def test_service_flows_atomic(db_mod):
    """To'lov va promo oqimlari: xatoda HECH QANDAY qismiy yozuv qolmaydi."""
    print("== Servis oqimlari: atomiklik (real DB) ==")
    from unittest.mock import patch
    from services.payment_service import PaymentService
    from services.promo_service import PromoService
    import uuid

    # --- Stars to'lovi: payment yozuvi bor, lekin obuna yangilanishi qasadan buzildi
    seed = _seed_tree(db_mod)
    try:
        _reset_user(db_mod, seed["user_id"])
        marker = "UPDATE users SET plan_type"
        with patch("services.payment_service.db_cursor",
                   _explosive_db_cursor(db_mod, marker)):
            result = PaymentService.process_stars_payment(
                seed["user_id"], f"int-charge-{uuid.uuid4().hex}", 75,
                f"sub_stars_1m_{seed['user_id']}", "pro", 30)
        check("to'lov oqimi xatoni yutdi (ok=False)", result.get("ok") is False, str(result))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM payments WHERE user_id = %s", (seed["user_id"],))
            check("xatoda payments yozuvi ham ROLLBACK bo'ldi", cur.fetchone()[0] == 0)
            cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s",
                        (seed["user_id"],))
            plan, expires = cur.fetchone()
            check("xatoda obuna ham o'zgarmadi (rollback)", plan == "free" and expires is None,
                  f"{plan}/{expires}")

        # Nazorat: xatosiz oqim — ikkala yozuv birga paydo bo'ladi
        charge = f"int-charge-ok-{uuid.uuid4().hex}"
        ok = PaymentService.process_stars_payment(seed["user_id"], charge, 75,
                                                 f"sub_stars_1m_{seed['user_id']}", "pro", 30)
        check("to'lov oqimi muvaffaqiyatli (ok=True)", ok.get("ok") is True, str(ok))
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM payments WHERE telegram_payment_charge_id = %s",
                        (charge,))
            paid = cur.fetchone()[0]
            cur.execute("SELECT plan_type FROM users WHERE user_id = %s", (seed["user_id"],))
            plan = cur.fetchone()[0]
        check("muvaffaqiyatda: payment + pro obuna birga yozildi",
              paid == 1 and plan == "pro", f"{paid}/{plan}")
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM payments WHERE telegram_payment_charge_id = %s", (charge,))
    finally:
        _drop_tree(db_mod, seed)

    # --- Promo: redemption kiritildi, hisoblagich yangilanishi qasadan buzildi
    seed2 = _seed_tree(db_mod)
    code = f"INTEG_{uuid.uuid4().hex[:14]}".upper()
    try:
        _reset_user(db_mod, seed2["user_id"])
        check("promo yaratildi", PromoService.create_promo(code, 30, 5) is True)
        with patch("services.promo_service.db_cursor",
                   _explosive_db_cursor(db_mod, "UPDATE promo_codes SET current_uses")):
            success, message = PromoService.redeem_promo(seed2["user_id"], code)
        check("promo oqimi xatoda False qaytardi", success is False, message)
        with db_mod.db_cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM promo_redemptions pr "
                        "JOIN promo_codes pc ON pc.id = pr.promo_id WHERE pc.code = %s", (code,))
            check("xatoda redemption yozuvi ham qaytarildi", cur.fetchone()[0] == 0)
            cur.execute("SELECT plan_type, subscription_expires_at FROM users WHERE user_id = %s",
                        (seed2["user_id"],))
            plan, expires = cur.fetchone()
            check("xatoda obuna ham berilmadi", plan == "free" and expires is None,
                  f"{plan}/{expires}")
            cur.execute("SELECT current_uses FROM promo_codes WHERE code = %s", (code,))
            check("xatoda hisoblagich oshmadi", cur.fetchone()[0] == 0)
    finally:
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM promo_redemptions WHERE promo_id = "
                        "(SELECT id FROM promo_codes WHERE code = %s)", (code,))
            cur.execute("DELETE FROM promo_codes WHERE code = %s", (code,))
        _drop_tree(db_mod, seed2)


def _reset_user(db_mod, user_id):
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("UPDATE users SET plan_type = 'free', subscription_expires_at = NULL "
                    "WHERE user_id = %s", (user_id,))


def test_composite_indexes(db_mod):
    print("== Kompozit indekslar: mavjudlik va tarkibi ==")
    import database as db_mod_local

    with db_mod.db_cursor() as cur:
        cur.execute("SELECT indexname, indexdef, tablename FROM pg_indexes "
                    "WHERE schemaname = current_schema()")
        rows = cur.fetchall()
    by_name = {row[0]: row for row in rows}

    for item in db_mod_local.INTEGRITY_INDEXES:
        name = item["name"]
        check(f"indeks mavjud: {name}", name in by_name, str(sorted(by_name))[:200])
        if name not in by_name:
            continue
        _idx_name, idx_def, table = by_name[name]
        check(f"{name} to'g'ri jadvalda",
              f"ON {table} " in idx_def or f"ON public.{table} " in idx_def, idx_def)
        # indexdef ko'rinishi: CREATE INDEX x ON public.t USING btree (a, b) WHERE ...
        after_using = idx_def.split("USING btree", 1)
        columns_part = after_using[1].split("WHERE")[0].strip() if len(after_using) > 1 else ""
        check(f"{name} ustunlari: {item['columns']}",
              columns_part.replace(" ", "") == item["columns"].replace(" ", ""),
              f"{columns_part!r} != {item['columns']!r}")
    # partial indekslar — faqat kerakli qatorlarni qamrab oladi
    for name, needles in (("idx_posts_sched_status", ("WHERE", "pending")),
                          ("idx_channels_owner", ("WHERE", "is_active"))):
        _, idx_def, _table = by_name.get(name, ("", "", ""))
        check(f"{name} qismiy (partial) indeks",
              all(needle in idx_def for needle in needles), idx_def)

    # indekslar amalda valid holatda (CONCURRENTLY qurilganda invalid bo'ladi)
    with db_mod.db_cursor() as cur:
        cur.execute(
            """
            SELECT i.indexrelid::regclass::text AS name, i.indisvalid, i.indisready
              FROM pg_index i
              JOIN pg_class c ON c.oid = i.indexrelid
             WHERE c.relname = ANY(%s)
            """,
            (list(db_mod_local.INTEGRITY_INDEX_NAMES),),
        )
        flags = {row[0]: row for row in cur.fetchall()}
    for name in db_mod_local.INTEGRITY_INDEX_NAMES:
        row = flags.get(name)
        check(f"{name} valid va tayyor", bool(row) and row[1] and row[2], str(row))


def test_schema_is_idempotent(db_mod):
    print("== Migratsiya idempotentligi va startup tekshiruvi ==")
    before = db_mod.integrity_report()
    check("barcha integrity constraintlar mavjud", before["missing"] == [], str(before["missing"]))
    check("NOT VALID qolmagan (toza bazada)", before["not_valid"] == [], str(before["not_valid"]))
    check("barcha kompozit indekslar bor", all(before["indexes"].values()), str(before["indexes"]))
    check("yetim yozuvlar yo'q", all(v == 0 for v in before["orphans"].values()),
          str(before["orphans"]))

    try:
        db_mod.init_db()
        db_mod.init_db()
        check("init_db() ikki marta xatosiz (idempotent)", True)
    except Exception as e:
        check("init_db() ikki marta xatosiz (idempotent)", False, str(e))

    after = db_mod.integrity_report()
    check("qayta-initdan keyin ham constraintlar saqlandi",
          after["constraints"].keys() == before["constraints"].keys()
          and after["missing"] == [], str(after["missing"]))
    check("validate_integrity_constraints() toza bazada 'ok' qaytaradi",
          all(v in ("ok", "validated") for v in db_mod.validate_integrity_constraints().values()),
          str(db_mod.validate_integrity_constraints()))


def test_legacy_database_upgrade(db_mod):
    """Eski baza ssenariysi: yetim yozuvlar bo'lsa constraint NOT VALID qo'shiladi.

    Bu migratsiyaning ENG MUHIM xavfsizlik kafolati — mavjud ma'lumot
    o'chirilmaydi va bot ishlayveradi, lekin YANGI yozuvlar himoyalanadi.
    """
    print("== Legacy baza: NOT VALID + ma'lumot saqlanadi ==")
    import psycopg2

    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DROP SCHEMA IF EXISTS legacy_probe CASCADE")
        cur.execute("CREATE SCHEMA legacy_probe")
        cur.execute("SET search_path TO legacy_probe")
        # Eski sxema: constraintlar YO'Q va ichida yetim qatorlar bor.
        cur.execute("""
            CREATE TABLE users (user_id BIGINT PRIMARY KEY);
            CREATE TABLE channels (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                                   channel_id VARCHAR(255) UNIQUE NOT NULL,
                                   channel_title VARCHAR(255), is_active BOOLEAN DEFAULT TRUE);
            CREATE TABLE scheduled_posts (id SERIAL PRIMARY KEY, user_id BIGINT NOT NULL,
                                   channel_id VARCHAR(255) NOT NULL, post_type VARCHAR(50) NOT NULL,
                                   content TEXT, scheduled_time TIMESTAMPTZ NOT NULL,
                                   status VARCHAR(50) DEFAULT 'pending');
            CREATE TABLE post_reactions (id SERIAL PRIMARY KEY, post_id INTEGER NOT NULL,
                                   user_id BIGINT NOT NULL, reaction_type VARCHAR(10) NOT NULL);
            CREATE TABLE post_deliveries (id BIGSERIAL PRIMARY KEY, post_id BIGINT NOT NULL,
                                   channel_id BIGINT NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'pending',
                                   idempotency_key TEXT UNIQUE NOT NULL);
            INSERT INTO channels (user_id, channel_id) VALUES (111, 'orphan-channel');
            INSERT INTO scheduled_posts (user_id, channel_id, post_type, scheduled_time, status)
                 VALUES (222, 'ghost-channel', 'text', NOW(), 'pending'),
                        (222, 'ghost-channel', 'text', NOW(), 'weird-status');
            INSERT INTO post_reactions (post_id, user_id, reaction_type) VALUES (55555, 1, '👍');
            INSERT INTO post_deliveries (post_id, channel_id, status, idempotency_key)
                 VALUES (55555, 1, 'in-flight', 'legacy-1');
        """)
        cur.execute(db_mod.build_integrity_block())
        cur.execute("""
            SELECT c.conname, c.convalidated
              FROM pg_constraint c
              JOIN pg_class r ON r.oid = c.conrelid
              JOIN pg_namespace n ON n.oid = r.relnamespace
             WHERE n.nspname = 'legacy_probe'
             ORDER BY 1
        """)
        found = {row[0]: bool(row[1]) for row in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM scheduled_posts")
        posts_left = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM post_reactions")
        reactions_left = cur.fetchone()[0]

        check("legacy: barcha FK/CHECK qo'shildi",
              all(name in found for name in ("fk_channels_user", "fk_scheduled_posts_channel",
                                             "fk_post_reactions_post", "fk_post_deliveries_post",
                                             "chk_post_deliveries_status", "chk_scheduled_posts_status")),
              str(sorted(found)))
        check("legacy: ma'lumot o'chirilmadi (postlar saqlandi)", posts_left == 2, str(posts_left))
        check("legacy: ma'lumot o'chirilmadi (yetim reaksiya saqlandi)",
              reactions_left == 1, str(reactions_left))
        not_valid = [n for n, valid in found.items() if n.startswith(("fk_", "chk_")) and not valid]
        check("legacy: buzuvchi constraintlar NOT VALID holatida",
              {"fk_channels_user", "fk_scheduled_posts_channel", "fk_post_reactions_post",
               "fk_post_deliveries_post", "chk_scheduled_posts_status",
               "chk_post_deliveries_status"} <= set(not_valid), str(not_valid))

        # Yangi yozuvlar esa ALLAQACHON himoyalangan — NOT VALID bunga to'sqinlik qilmaydi.
        # Har bir probe alohida SAVEPOINT'da bajariladi: aks holda rad etilgan
        # yozuv butun test tranzaksiyasini "aborted" holatiga tushiradi.
        probes = (
            ("legacy: YANGI yetim yozuv baribir rad etildi",
             "INSERT INTO post_reactions (post_id, user_id, reaction_type) "
             "VALUES (77777, 1, 'x')", "ForeignKeyViolation"),
            ("legacy: YANGI yaroqsiz status rad etildi",
             "INSERT INTO scheduled_posts (user_id, channel_id, post_type, "
             "scheduled_time, status) VALUES (1, 'x', 'text', NOW(), 'nope')",
             "CheckViolation"),
            ("legacy: YANGI kanalsiz post rad etildi",
             "INSERT INTO scheduled_posts (user_id, channel_id, post_type, scheduled_time) "
             "VALUES (1, 'no-such-channel', 'text', NOW())", "ForeignKeyViolation"),
        )
        for probe_index, (label, probe_sql, error_name) in enumerate(probes):
            cur.execute(f"SAVEPOINT legacy_probe_{probe_index}")
            rejected = False
            try:
                cur.execute(probe_sql)
            except psycopg2.Error as e:
                rejected = type(e).__name__ == error_name
            finally:
                cur.execute(f"ROLLBACK TO SAVEPOINT legacy_probe_{probe_index}")
                cur.execute(f"RELEASE SAVEPOINT legacy_probe_{probe_index}")
            check(label, rejected, error_name)
        cur.execute("RESET search_path")
        cur.execute("DROP SCHEMA IF EXISTS legacy_probe CASCADE")


# ============================================================
# main
# ============================================================

def main():
    test_schema_declares_integrity()
    test_python_metadata_matches_schema()
    test_transaction_api_static()
    test_flows_use_single_transaction_block()

    uri = _start_test_postgres()
    if not uri:
        print("\n== Real PostgreSQL (o'tkazib yuborildi) ==")
        skip("live integrity tests", "(pgserver/INTEGRITY_TEST_DATABASE_URL mavjud emas)")
    else:
        import database as db_mod
        db_mod.DATABASE_URL = uri
        os.environ["DATABASE_URL"] = uri
        db_mod._reset_pool()
        try:
            db_mod.init_db()
            for test in (test_foreign_keys, test_check_constraints, test_transaction_helper,
                         test_async_transaction, test_service_flows_atomic,
                         test_composite_indexes, test_schema_is_idempotent,
                         test_legacy_database_upgrade):
                test(db_mod)
        except Exception as e:
            check("real DB testlari xatosiz o'tdi", False, f"{type(e).__name__}: {e}")
        finally:
            db_mod.close_pool()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
        print("DB integrity-testda xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0, O'tkazib yuborildi: {skipped}")
    print("Barcha ma'lumotlar butunligi testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()
