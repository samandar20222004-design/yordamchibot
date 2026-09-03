#!/usr/bin/env python3
"""Schema-test: schema.sql, SSL pool va startup schema tekshiruvlari.

Ishga tushirish:
    cd telegram_bot && python tests/schema_test.py

Haqiqiy PostgreSQL sinovi uchun pgserver kerak (pip install pgserver):
    - schema.sql ikki marta qo'llanadi (idempotentlik),
    - startup schema check (jadvallar/indekslar) real bazada tekshiriladi,
    - jadval o'chirilsa o'z-o'zini tiklashi sinovdan o'tkaziladi.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

failures = 0
passed = 0


def check(name, cond, extra=""):
    global failures, passed
    if cond:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failures += 1
        print(f"  [FAIL] {name} {extra}")


SCHEMA = (ROOT / "schema.sql").read_text(encoding="utf-8")
DB_SOURCE = (ROOT / "database.py").read_text(encoding="utf-8")

EXPECTED_TABLES = (
    "users", "channels", "sponsor_channels", "system_settings",
    "bot_settings", "ad_pool", "channel_post_counters", "scheduled_posts",
    "post_reactions", "sent_post_messages", "promo_codes", "payments",
    "channel_posts_history",
)
EXPECTED_INDEXES = (
    "idx_ad_pool_scope",
    "idx_channel_post_counters_updated",
    "idx_payments_user_id",
    "idx_scheduled_posts_status_time",
    "idx_scheduled_posts_user_id",
    "idx_channels_user_id",
    "idx_post_reactions_post_id",
    "idx_channel_posts_history_channel_date",
)


def test_schema_file_tables():
    print("== schema.sql: jadvallar ==")
    for table in EXPECTED_TABLES:
        check(f"jadval: {table}", f"CREATE TABLE IF NOT EXISTS {table} (" in SCHEMA)
    check("jadvallar soni 13",
          SCHEMA.count("CREATE TABLE IF NOT EXISTS") == 13,
          f"topildi: {SCHEMA.count('CREATE TABLE IF NOT EXISTS')}")


def test_schema_file_columns():
    print("== schema.sql: muhim ustunlar/migratsiyalar ==")
    must_have = (
        "tone_of_voice VARCHAR(30) DEFAULT 'friendly'",
        "ADD COLUMN IF NOT EXISTS tone_of_voice",
        "reaction_emojis TEXT",
        "ADD COLUMN IF NOT EXISTS reaction_emojis",
        "user_code VARCHAR(8) UNIQUE",
        "plan_type VARCHAR(20) DEFAULT 'free'",
        "ai_credits INTEGER DEFAULT 5",
        "processing_started_at TIMESTAMP WITH TIME ZONE",
        "recurrence_type VARCHAR(20) DEFAULT 'none'",
        "ALTER TABLE scheduled_posts ALTER COLUMN file_id TYPE TEXT",
        "subscription_expires_at TIMESTAMP WITH TIME ZONE",
    )
    for snippet in must_have:
        check(f"satr: {snippet[:52]}", snippet in SCHEMA)
    check("barcha ALTER idempotent (IF NOT EXISTS)",
          SCHEMA.count("ADD COLUMN IF NOT EXISTS") >= 30,
          f"topildi: {SCHEMA.count('ADD COLUMN IF NOT EXISTS')}")


def test_schema_file_indexes():
    print("== schema.sql: indekslar ==")
    for index in EXPECTED_INDEXES:
        check(f"indeks: {index}", f"CREATE INDEX IF NOT EXISTS {index}" in SCHEMA)
    check("indekslar soni 8",
          SCHEMA.count("CREATE INDEX IF NOT EXISTS") == 8,
          f"topildi: {SCHEMA.count('CREATE INDEX IF NOT EXISTS')}")


def test_database_ssl_pool():
    print("== database.py: SSL pool ==")
    check("sslmode boshqaruvi bor", "sslmode" in DB_SOURCE)
    check("DB_SSLMODE env qo'llab-quvvatlanadi", 'os.getenv("DB_SSLMODE"' in DB_SOURCE)
    check("TCP keepalive'lar yoqilgan", "keepalives" in DB_SOURCE)
    check("pool _connect_kwargs() dan foydalanadi", "**_connect_kwargs()" in DB_SOURCE)
    check("URL'dagi sslmode= ustun bo'ladi", '"sslmode=" in url' in DB_SOURCE)


def test_database_schema_checks():
    print("== database.py: startup schema tekshiruvi ==")
    check("schema.sql fayliga havola bor", '"schema.sql"' in DB_SOURCE)
    check("_apply_schema_file mavjud", "def _apply_schema_file(" in DB_SOURCE)
    check("_verify_schema mavjud", "def _verify_schema(" in DB_SOURCE)
    check("init_db ichida _verify_schema chaqiriladi", "_verify_schema(cur)" in DB_SOURCE)
    check("information_schema orqali jadvallar o'qiladi", "information_schema.tables" in DB_SOURCE)
    check("pg_indexes orqali indekslar o'qiladi", "pg_indexes" in DB_SOURCE)
    check("Neon aniqlanadi (version())", '"Neon" in server' in DB_SOURCE)

    # database.py'dagi EXPECTED_* ro'yxatlari testdagi ro'yxatlar bilan bir xil
    import database as db_mod
    check("EXPECTED_TABLES mos", tuple(db_mod.EXPECTED_TABLES) == EXPECTED_TABLES)
    check("EXPECTED_INDEXES mos", tuple(db_mod.EXPECTED_INDEXES) == EXPECTED_INDEXES)
    check("SCHEMA_FILE mavjud yo'lda", os.path.isfile(db_mod.SCHEMA_FILE))


def test_resolve_sslmode():
    print("== resolve_sslmode() ==")
    import database as db_mod

    old = os.environ.pop("DB_SSLMODE", None)
    try:
        check("URL'da sslmode= → aralashmaslik",
              db_mod.resolve_sslmode("postgresql://u:p@ep-x.neon.tech/db?sslmode=require") == "")
        check("Neon host → require",
              db_mod.resolve_sslmode("postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/db") == "require")
        check("Render host → require",
              db_mod.resolve_sslmode("postgresql://u:p@dpg-xyz-a.frankfurt-postgres.render.com/db") == "require")
        check("localhost → prefer",
              db_mod.resolve_sslmode("postgresql://u:p@localhost:5432/db") == "prefer")
        check("127.0.0.1 → prefer",
              db_mod.resolve_sslmode("postgresql://u:p@127.0.0.1:5432/db") == "prefer")

        os.environ["DB_SSLMODE"] = "disable"
        check("DB_SSLMODE=disable ustun",
              db_mod.resolve_sslmode("postgresql://u:p@ep-x.neon.tech/db") == "disable")
        os.environ["DB_SSLMODE"] = "verify-full"
        check("DB_SSLMODE=verify-full ustun",
              db_mod.resolve_sslmode("postgresql://u:p@localhost/db") == "verify-full")

        os.environ.pop("DB_SSLMODE", None)  # avtomatik rejimga qaytamiz
        check("config DATABASE_URL (localhost) → prefer",
              db_mod.resolve_sslmode() == "prefer")
    finally:
        if old is not None:
            os.environ["DB_SSLMODE"] = old
        else:
            os.environ.pop("DB_SSLMODE", None)


def test_live_postgres():
    """Real PostgreSQL (pgserver): idempotentlik va o'z-o'zini tiklash."""
    try:
        import pgserver
    except ImportError:
        print("== Live PostgreSQL (o'tkazib yuborildi: pgserver yo'q) ==")
        return

    import shutil
    import tempfile
    import database as db_mod

    print("== Live PostgreSQL (pgserver) ==")
    server_dir = os.path.join(tempfile.gettempdir(), "yordamchi_pg_schema")
    shutil.rmtree(server_dir, ignore_errors=True)
    server = pgserver.get_server(server_dir)

    # Modul allaqachon import qilingan (dummy URL bilan) — real URI'ni
    # modulga ham, env'ga ham yozamiz (config faqat import paytida o'qiydi).
    uri = server.get_uri()
    os.environ["DATABASE_URL"] = uri
    db_mod.DATABASE_URL = uri

    # 1) Baza 1-marta ishga tushiriladi
    db_mod._reset_pool()
    db_mod.init_db()
    check("init_db #1 muvaffaqiyatli", True)

    # 2) Idempotentlik: 2-marta ham xatosiz
    try:
        db_mod.init_db()
        check("init_db #2 (idempotent) muvaffaqiyatli", True)
    except Exception as e:
        check("init_db #2 (idempotent) muvaffaqiyatli", False, str(e))

    # 3) Barcha jadvallar/indekslar rostdan ham bor
    with db_mod.db_cursor() as cur:
        cur.execute("SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()")
        tables = {r[0] for r in cur.fetchall()}
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
        indexes = {r[0] for r in cur.fetchall()}
    check("barcha jadvallar real bazada",
          all(t in tables for t in db_mod.EXPECTED_TABLES),
          f"yetishmaydi: {[t for t in db_mod.EXPECTED_TABLES if t not in tables]}")
    check("barcha indekslar real bazada",
          all(i in indexes for i in db_mod.EXPECTED_INDEXES),
          f"yetishmaydi: {[i for i in db_mod.EXPECTED_INDEXES if i not in indexes]}")

    # 4) O'z-o'zini tiklash: jadval o'chirilsa startup check qayta yaratadi
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute("DROP TABLE promo_codes")
    try:
        db_mod.init_db()
        check("o'chirilgan jadval avtomatik tiklandi", True)
    except Exception as e:
        check("o'chirilgan jadval avtomatik tiklandi", False, str(e))

    # 5) SSL bo'lmasa ham lokal ulanish ishlaydi (prefer → fallback)
    check("lokal ulanish (prefer) ishlaydi", db_mod.ping_db() is True)

    db_mod.close_pool()


if __name__ == "__main__":
    test_schema_file_tables()
    test_schema_file_columns()
    test_schema_file_indexes()
    test_database_ssl_pool()
    test_database_schema_checks()
    test_resolve_sslmode()
    test_live_postgres()

    print()
    if failures:
        print(f"O'tdi: {passed}, Xato: {failures}")
        print("Schema-testda xatolar bor ✗")
        sys.exit(1)
    print(f"O'tdi: {passed}, Xato: 0")
    print("Barcha schema-testlar muvaffaqiyatli o'tdi ✔")
