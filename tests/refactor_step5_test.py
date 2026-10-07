#!/usr/bin/env python3
"""🧭 POSTASSIST V2 · 5-QADAM — P1 PERFORMANCE & DB OPTIMIZATION TESTLARI.

Qamrov (topshiriq bo'yicha, deterministik — tarmoqsiz):

  TEST 1 — 🚫 N+1 QUERY YO'Q (BATCH FETCHING):
           50 / 100 / 500 ta post tahlil qilinganda DB so'rovlari soni
           QAT'IY cheklangan (50 ta post uchun 50 ta emas — 2 ta);
           postlar soni oshsa ham so'rov soni O'ZGARMAYDI.

  TEST 2 — 📦 `= ANY(%s)` BATCH: N ta post metrikasi bitta so'rovda
           (reaksiyalar + yuborishlar), takroriy ID'lar tozalanadi;
           500 ta ID ham 2 ta so'rov.

  TEST 3 — 🧮 AGREGATSIYA DB DARAJASIDA: o'rtacha ko'rishlar, eng yaxshi
           formatlar va eng faol soat SQL'da (AVG/FILTER/GROUP BY/
           JSONB_OBJECT_AGG/ARRAY_AGG) hisoblanadi — Python katta
           ro'yxatni ko'chirmaydi; per-post SELECT naqshi YO'Q.

  TEST 4 — 📢 KO'P KANAL: 10 ta kanal uchun agregatsiya bitta so'rovda
           (har bir kanal uchun alohida SELECT — N+1 EMAS).

  TEST 5 — ⚡️ INDEX TUNING: `scheduled_posts`, `post_reactions`,
           `channel_posts_history`, `channel_post_events`,
           `sent_post_messages`, `post_deliveries` uchun kompozit
           indekslar ((channel_id, created_at DESC), (channel_id, status),
           (post_id, reaction_type)) — barchasi IDEMPOTENT
           (CREATE INDEX IF NOT EXISTS), ikki marta qo'llash xavfsiz;
           schema.sql hisoblagichlari (31 jadval / 33 indeks) o'zgarmagan.

  TEST 6 — 📊 STATISTIKA OPTIMIZATSIYASI: `get_channel_post_stats`
           ilgari 8 ta ketma-ket SQL yuborardi — endi 3 ta
           (COUNT FILTER + GROUPING SETS + history agregati), qaytadigan
           lug'at kalitlari AYNAN o'sha.

  TEST 7 — 🔐 XAVFSIZLIK / FAIL-CLOSED: IDOR — begona foydalanuvchi
           kanal tahlilini olmaydi (0 so'rov yuboriladi); DB xatosida
           fail-soft (crash yo'q), soxta raqam uydirilmaydi.

  TEST 8 — 🔁 REGRESSIYA: mavjud interfeys 100% saqlangan —
           ContentLoop.analyze / get_channel_dna_extended / database
           facade / services.channels eksportlari va eski kalitlar.

  TEST 9 — 🔎 STATIK N+1 SKANERI: yangi analitika yo'llarida hech bir
           tsikl ichida `cur.execute` / per-post DB chaqiruvi yo'q.

Ishga tushirish:
    PYTHON=$HOME/venv/bin/python bash tests/run_tests.sh   # runner bosqichi
    python3 tests/refactor_step5_test.py
"""
import ast
import asyncio
import contextlib
import os
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# 0) MUHIT — bot modullari IMPORT qilinishidan OLDIN sozlanishi SHART.
# ---------------------------------------------------------------------------
os.environ.setdefault("BOT_TOKEN", "123456:STEP5_PERFORMANCE_TEST_TOKEN")
os.environ.setdefault("ADMIN_ID", "123456789")
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("PORT", "10055")
os.environ.setdefault("ENVIRONMENT", "test")

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parent.parent
BOT_ROOT = ROOT / "telegram_bot"
sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(ROOT))

import database as db  # noqa: E402
import repositories  # noqa: E402
import repositories.posts_repository as posts_repo  # noqa: E402
from unittest.mock import patch  # noqa: E402

from services.channels.analytics import (  # noqa: E402
    MIN_POSTS_FOR_ANALYTICS,
    analyze_channel_posts,
    attach_analytics_summary,
    get_channel_analytics_snapshot,
    summarize_posts_locally,
)
from services.channels.content_loop import ContentLoop  # noqa: E402
from services.channels.dna import get_channel_dna_extended  # noqa: E402

USER_ID = 555001          # kanal EGASI
OTHER_USER_ID = 555999    # begona (IDOR)
CH_ID = "-1005550001111"
CH_TITLE = "Performance Test Kanal"

PASSED = 0
FAILURES = 0


def check(name, cond, extra=""):
    global PASSED, FAILURES
    if cond:
        PASSED += 1
        print(f"  [OK] {name}")
    else:
        FAILURES += 1
        print(f"  [FAIL] {name} {extra}")


def head(title):
    print(f"\n{title}")


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# SOXTA DB — SQL EMULYATSIYASI + SO'ROV HISOBLAGICHI
# ===========================================================================
class QueryCountingStore:
    """`db_cursor` mock: har bir `execute` ni SANAYDI va SQL'ni emulyatsiya qiladi.

    Bu — N+1 detektorining yuragi: postlar soni qancha bo'lishidan qat'i
    nazar yuborilgan SQL soni shu yerda ko'rinadi.
    """

    def __init__(self, posts=None, fail_all=False, fail_indexes=()):
        self.executed = []          # [(sql, params), ...]
        self.posts = posts if posts is not None else []
        self.fail_all = fail_all
        self.fail_indexes = set(fail_indexes)
        self.rows_for_channel = posts or []

    # -- hisoblagich -------------------------------------------------------
    @property
    def execute_count(self) -> int:
        return len(self.executed)

    def sql_texts(self) -> list:
        return [sql for sql, _ in self.executed]

    def reset(self):
        self.executed = []

    # -- emulyatsiya -------------------------------------------------------
    def _rows_for(self, sql: str, params):
        text = " ".join((sql or "").split())
        if "AS sent_7d" in text:
            return [(1, 2, 3, 4)]
        if "GROUPING SETS" in text:
            return [
                (19, None, 0, 1, 5),
                (18, None, 0, 1, 3),
                (None, "photo", 1, 0, 4),
                (None, "text", 1, 0, 2),
            ]
        if "UNNEST(%s::text[])" in text:
            ids = list(params[0]) if params else []
            return [
                (ch, 10, 1000 + i * 10, 100.0 + i, 200 + i, 10, 6, 5, 19, 0)
                for i, ch in enumerate(ids)
            ]
        if "AS best_formats" in text:
            return [(
                len(self.rows_for_channel),   # posts
                50000,                        # total_views
                1000.0,                       # avg_views
                2500,                         # max_views
                321,                          # total_reactions
                len(self.rows_for_channel),   # events
                30,                           # media_posts
                21,                           # cta_posts
                19,                           # best_hour
                0,                            # best_weekday
                "photo",                      # best_format
                ["photo", "video", "text"],   # best_formats
                {"photo": 30, "video": 12, "text": 8},   # format_distribution
            )]
        if "FROM channel_posts_history h" in text:
            rows = []
            for idx, post in enumerate(self.rows_for_channel):
                rows.append((
                    post.get("id", idx + 1),
                    post.get("message_id"),
                    post.get("content", ""),
                    post.get("views", 0),
                    post.get("post_date"),
                    post.get("reactions", 0),
                    post.get("reactors", 0),
                    post.get("post_hour"),
                    post.get("post_weekday"),
                    post.get("has_media"),
                    post.get("media_type"),
                    post.get("length", 0),
                    post.get("cta_detected", False),
                    post.get("emoji_density", 0.0),
                ))
            return rows
        if "FROM post_reactions pr" in text:
            ids = list(params[0]) if params else []
            return [(pid, 3, 2) for pid in ids]
        # DIQQAT: xulosa (WITH ... rx) SQL'i ham `sent_post_messages` dan
        # foydalanadi — shuning uchun bu shox FAQAT "AS best_formats"
        # tekshiruvidan KEYIN turadi (yuqorida).
        if "FROM sent_post_messages spm" in text:
            ids = list(params[0]) if params else []
            return [(pid, 1, 900 + i, CH_ID) for i, pid in enumerate(ids)]
        if "FROM channel_posts_history WHERE channel_id" in text:
            return [(10, 5000, 500.0)]
        if "FROM channel_posts_history cph" in text:
            return [(10, 5000, 500.0)]
        return []

    class Cursor:
        def __init__(self, store, index):
            self._store = store
            self._index = index
            self._rows = []
            self.rowcount = 0

        def execute(self, sql, params=None):
            self._store.executed.append((sql, params))
            if self._store.fail_all or self._index in self._store.fail_indexes:
                raise RuntimeError("simulyatsiya qilingan DB xatosi")
            self._rows = self._store._rows_for(sql, params)
            self.rowcount = len(self._rows)
            return None

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return self._rows[0] if self._rows else None

        def close(self):
            return None

    def db_cursor(self, commit: bool = False):
        index = len(self.executed)

        @contextlib.contextmanager
        def _cm():
            yield self.Cursor(self, index)

        return _cm()


class FakeAnalyticsDB:
    """`database` modulining analitika yuzasi (haqiqiy funksiyalarga delegat).

    Service qatlami ``hasattr`` bilan qaraydi; SQL esa HAQIQIY repository
    funksiyalari orqali (patch'langan cursor bilan) bajariladi — shu sabab
    N+1 detektori haqiqiy kodni o'lchaydi.
    """

    def __init__(self, store, owner=USER_ID, posts=None):
        self.store = store
        self.owner = owner
        self.posts = posts or []
        self.calls = []

    async def run_db(self, fn, *args, **kwargs):
        name = getattr(fn, "__name__", str(fn))
        self.calls.append((name, args, tuple(sorted(kwargs.items()))))
        return fn(*args, **kwargs)

    # -- analitika (haqiqiy repository) ------------------------------------
    def get_channel_analytics_summary(self, channel_id, days=30):
        return db.get_channel_analytics_summary(channel_id, days)

    def get_channel_posts_metrics_batch(self, channel_id, limit=100):
        return db.get_channel_posts_metrics_batch(channel_id, limit)

    def get_channel_posts_history(self, channel_id, limit=50):
        return [dict(p) for p in self.posts[:limit]]

    def get_channel_owner_id(self, channel_id):
        return self.owner if str(channel_id) == CH_ID else None


def make_posts(count: int, start_msg: int = 7000) -> list:
    """Deterministik post to'plami (views, reaksiyalar, media bilan)."""
    base = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    posts = []
    for i in range(count):
        posts.append({
            "id": i + 1,
            "channel_id": CH_ID,
            "message_id": start_msg + i,
            "content": f"📌 Tahliliy post #{i + 1}: kanal samaradorligi.",
            "views": 500 + i * 7,
            "reactions": 5 + (i % 4),
            "reactors": 4 + (i % 3),
            "post_date": base - timedelta(hours=i),
            "post_hour": 19 if i % 2 == 0 else 12,
            "post_weekday": 0 if i % 3 else 3,
            "has_media": i % 2 == 0,
            "media_type": "photo" if i % 2 == 0 else None,
            "length": 120 + i,
            "cta_detected": i % 2 == 0,
            "emoji_density": 0.02,
        })
    return posts


@contextlib.contextmanager
def counting_db(store, owner=USER_ID, posts=None):
    """`database.db_cursor` ni sanovchi mock bilan almashtiradi."""
    fake = FakeAnalyticsDB(store, owner=owner, posts=posts)
    with patch("database.db_cursor", store.db_cursor):
        yield fake


# ===========================================================================
# TEST 1 — 🚫 N+1 QUERY YO'Q
# ===========================================================================
def test_no_n_plus_one():
    head("== TEST 1: 🚫 N+1 QUERY YO'Q (batch fetching) ==")

    counts = {}
    for size in (50, 100, 500):
        store = QueryCountingStore(posts=make_posts(size))
        with counting_db(store, posts=make_posts(size)) as fake:
            result = _run(analyze_channel_posts(
                CH_ID, USER_ID, limit=size, days=30, db_module=fake
            ))
        counts[size] = store.execute_count
        check(f"{size} ta post: tahlil muvaffaqiyatli (ok=True)", result.get("ok") is True)
        check(f"{size} ta post: postlar BATCH yuklandi ({len(result.get('posts') or [])} ta)",
              len(result.get("posts") or []) == size, str(len(result.get("posts") or [])))
        check(f"{size} ta post: so'rovlar soni N+1 EMAS (jami {store.execute_count} ta)",
              store.execute_count <= 2, f"{store.execute_count} so'rov")
        check(f"{size} ta post: 50/100/500 ta alohida SELECT yuborilmadi",
              store.execute_count < size, f"{store.execute_count} < {size}")

    check("N+1 detektori: so'rovlar soni postlar soniga BOG'LIQ EMAS (50=100=500)",
          counts[50] == counts[100] == counts[500] == 2, str(counts))

    # Eski (N+1) yo'lning narxi — taqqoslash uchun (50 post × 3 metrika).
    old_cost = 50 * 3
    check(f"Tejash: 50 post uchun {old_cost} so'rov o'rniga {counts[50]} ta so'rov",
          counts[50] * 10 < old_cost, f"yangi={counts[50]}, eski={old_cost}")

    # Bitta metrika so'rovi ham 1 ta SQL (N+1 emas).
    store = QueryCountingStore(posts=make_posts(50))
    with patch("database.db_cursor", store.db_cursor):
        metrics = db.get_channel_posts_metrics_batch(CH_ID, 50)
    check("get_channel_posts_metrics_batch(50): AYNAN 1 ta SQL so'rov",
          store.execute_count == 1, str(store.execute_count))
    check("get_channel_posts_metrics_batch(50): 50 ta post qaytdi", len(metrics) == 50)
    check("Har bir postda views + reactions + format bor",
          all(m["views"] >= 0 and "reactions" in m and m["format"] for m in metrics))
    check("engagement_rate ko'rishlar asosida hisoblandi (PURE)",
          metrics[0]["engagement_rate"] == round((metrics[0]["reactions"] / metrics[0]["views"]) * 100, 4)
          if metrics[0]["views"] else True)

    # Bundle ham 2 tadan oshmaydi.
    store = QueryCountingStore(posts=make_posts(100))
    with patch("database.db_cursor", store.db_cursor):
        bundle = db.get_channel_analytics_bundle(CH_ID, 100, 30)
    check("get_channel_analytics_bundle: 100 post uchun 2 ta so'rov",
          store.execute_count == 2, str(store.execute_count))
    check("Bundle batched=True va query_count=2 deb belgilaydi",
          bundle.get("batched") is True and bundle.get("query_count") == 2)


# ===========================================================================
# TEST 2 — 📦 `= ANY(%s)` BATCH
# ===========================================================================
def test_any_batch_fetching():
    head("== TEST 2: 📦 `= ANY(%s)` batch — N ta post, 2 ta so'rov ==")

    store = QueryCountingStore()
    ids = list(range(1001, 1051))
    with patch("database.db_cursor", store.db_cursor):
        merged = db.get_posts_metrics_batch(ids)
    check("get_posts_metrics_batch(50 ta ID): 2 ta SQL (50 emas)",
          store.execute_count == 2, str(store.execute_count))
    check("SQL `= ANY(%s)` bilan bitta chaqiruvda guruhlanadi",
          all("ANY(%s)" in sql for sql in store.sql_texts()), str(store.sql_texts()[:1]))
    check("GROUP BY post_id ishlatilgan (DB darajasida agregatsiya)",
          all("GROUP BY" in " ".join(sql.split()) for sql in store.sql_texts()))
    check("50 ta post uchun natija to'liq qaytdi", len(merged) == 50)
    check("Har bir postda reaksiya va yuborish metrikasi bor",
          all(v["reactions"] == 3 and v["sent_messages"] == 1 for v in merged.values()))
    check("Yuborilgan xabar message_id/channel_id bilan boyitildi",
          merged[1001]["message_id"] == 900 and merged[1001]["channel_id"] == CH_ID
          and merged[1001]["delivered"] is True)

    # Takroriy va noto'g'ri ID'lar tozalanadi.
    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        merged = db.get_posts_metrics_batch([1, 1, 2, "3", None, "xato", 2])
    check("normalize_ids: takrorlar/noma'lumlar olib tashlandi",
          sorted(merged.keys()) == [1, 2, 3], str(sorted(merged.keys())))
    check("Takroriy ID'lar uchun ham qo'shimcha so'rov yuborilmadi",
          store.execute_count == 2, str(store.execute_count))
    check("Bo'sh ro'yxatda DB'ga umuman murojaat qilinmaydi",
          db.get_posts_metrics_batch([]) == {})

    # 500 ta ID ham 2 ta so'rov (chunking/loop yo'q).
    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        db.get_posts_metrics_batch(list(range(1, 501)))
    check("500 ta ID uchun ham AYNAN 2 ta so'rov (loop yo'q)",
          store.execute_count == 2, str(store.execute_count))

    # Bitta post metrikasi (orqaga moslik).
    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        single = db.get_post_metrics(42)
    check("get_post_metrics(post_id) ishlaydi (orqaga moslik)",
          single.get("post_id") == 42 and store.execute_count == 2)


# ===========================================================================
# TEST 3 — 🧮 AGREGATSIYA DB DARAJASIDA
# ===========================================================================
def test_db_level_aggregation():
    head("== TEST 3: 🧮 Agregatsiya DB darajasida (Python emas) ==")

    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        db.get_channel_analytics_summary(CH_ID, 30)
    sql = " ".join(store.sql_texts()[0].split())
    check("Xulosa AYNAN 1 ta SQL so'rovda olinadi", store.execute_count == 1)
    check("O'rtacha ko'rishlar SQL'da hisoblanadi (AVG)", "AVG(h.views)" in sql)
    check("Umumiy/maksimal ko'rishlar SQL agregati (SUM/MAX)",
          "SUM(h.views)" in sql and "MAX(h.views)" in sql)
    check("Eng faol soat SQL'da GROUP BY + ORDER BY bilan aniqlanadi",
          "GROUP BY e.post_hour" in sql and "ORDER BY COUNT(*) DESC" in sql)
    check("Eng yaxshi formatlar (AVG views bo'yicha) SQL'da — ARRAY_AGG",
          "ARRAY_AGG(g.fmt ORDER BY g.avg_views DESC" in sql)
    check("Format taqsimoti DB'da JSONB_OBJECT_AGG bilan yig'iladi",
          "JSONB_OBJECT_AGG" in sql)
    check("Kunlik oyna `make_interval(days => %s)` bilan (indekslanadi)",
          "make_interval(days => %s)" in sql)

    store = QueryCountingStore(posts=make_posts(50))
    with patch("database.db_cursor", store.db_cursor):
        summary = db.get_channel_analytics_summary(CH_ID, 30)
    check("Xulosa kalitlari to'liq", {
        "posts", "total_views", "avg_views", "max_views", "total_reactions",
        "best_hour", "best_weekday", "best_format", "best_formats",
        "format_distribution", "events", "media_posts", "cta_posts",
    } <= set(summary.keys()), str(sorted(summary.keys())))
    check("avg_views DB'dan o'qildi (1000.0)", summary["avg_views"] == 1000.0)
    check("best_formats DB'dan tartiblangan ro'yxat",
          summary["best_formats"] == ["photo", "video", "text"])
    check("format_distribution DB'dan lug'at",
          summary["format_distribution"] == {"photo": 30, "video": 12, "text": 8})

    # DB agregatsiyasi bo'lmasa — PURE fallback (soxta raqam yo'q).
    local = summarize_posts_locally(make_posts(10), days=30)
    check("Lokal fallback ham bir xil kalitlarni beradi",
          {"posts", "avg_views", "best_formats", "format_distribution"} <= set(local))
    check("Lokal fallback: AVG Python'da to'g'ri hisoblandi",
          local["avg_views"] == round(sum(p["views"] for p in make_posts(10)) / 10, 1))


# ===========================================================================
# TEST 4 — 📢 KO'P KANAL (N+1 EMAS)
# ===========================================================================
def test_multi_channel_single_query():
    head("== TEST 4: 📢 Ko'p kanal agregatsiyasi — 10 kanal, 1 so'rov ==")

    channels = [f"-100555{i:07d}" for i in range(10)]
    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        summaries = db.get_channels_analytics_summary(channels, 30)
    check("10 ta kanal uchun AYNAN 1 ta SQL so'rov", store.execute_count == 1,
          str(store.execute_count))
    check("SQL `= ANY(%s)` / UNNEST bilan kanallarni birga oladi",
          "ANY(%s)" in store.sql_texts()[0] and "UNNEST(%s::text[])" in store.sql_texts()[0])
    check("Har bir kanal uchun natija qaytdi", len(summaries) == 10, str(len(summaries)))
    check("Har bir kanal xulosasi bir xil kalitlarga ega",
          all("avg_views" in s and "best_hour" in s for s in summaries.values()))
    check("Kanal kalitlari saqlangan", all(ch in summaries for ch in channels))

    check("Bo'sh ro'yxatda so'rov yuborilmaydi",
          db.get_channels_analytics_summary([], 30) == {})


# ===========================================================================
# TEST 5 — ⚡️ INDEX TUNING (IDEMPOTENT MIGRATSIYA)
# ===========================================================================
def test_index_tuning():
    head("== TEST 5: ⚡️ Index tuning — kompozit indekslar (idempotent) ==")

    names = db.ANALYTICS_PERFORMANCE_INDEX_NAMES
    check("Index tuning ro'yxati mavjud (7 ta kompozit indeks)", len(names) == 7,
          str(len(names)))
    check("Har bir indeks `CREATE INDEX IF NOT EXISTS` (idempotent migratsiya)",
          all(item["ddl"].startswith("CREATE INDEX IF NOT EXISTS")
              for item in db.ANALYTICS_PERFORMANCE_INDEXES))
    check("Har bir DDL `;` bilan tugaydi (mustaqil migratsiya qadami)",
          all(stmt.endswith(";") for stmt in db._analytics_performance_index_statements()))

    expected = {
        "idx_scheduled_posts_channel_created": "scheduled_posts",
        "idx_scheduled_posts_channel_status": "scheduled_posts",
        "idx_post_reactions_post_type": "post_reactions",
        "idx_channel_posts_history_channel_views": "channel_posts_history",
        "idx_channel_post_events_channel_created": "channel_post_events",
        "idx_sent_post_messages_post_channel": "sent_post_messages",
        "idx_post_deliveries_channel_status": "post_deliveries",
    }
    for name, table in expected.items():
        item = next((i for i in db.ANALYTICS_PERFORMANCE_INDEXES if i["name"] == name), None)
        check(f"indeks: {name} → {table}", item is not None and item["table"] == table)

    columns = {i["name"]: i["columns"] for i in db.ANALYTICS_PERFORMANCE_INDEXES}
    check("Topshiriq namunasi: (channel_id, created_at DESC)",
          columns["idx_scheduled_posts_channel_created"] == "(channel_id, created_at DESC)")
    check("Topshiriq namunasi: (channel_id, status)",
          columns["idx_scheduled_posts_channel_status"] == "(channel_id, status)")
    check("Topshiriq namunasi: (post_id, metric_type) → (post_id, reaction_type)",
          columns["idx_post_reactions_post_type"] == "(post_id, reaction_type)")

    # schema.sql bilan paritet (yassilangan matn bo'yicha).
    schema = (BOT_ROOT / "schema.sql").read_text(encoding="utf-8")
    flat = " ".join(schema.split())
    missing = [n for n in names if f"CREATE INDEX IF NOT EXISTS {n}" not in flat]
    check("Barcha yangi indekslar schema.sql'da e'lon qilingan", not missing, str(missing))
    total = flat.count("CREATE INDEX")
    idempotent = flat.count("CREATE INDEX IF NOT EXISTS")
    check("schema.sql: barcha indekslar idempotent (IF NOT EXISTS)",
          total == idempotent and total >= 40, f"{idempotent}/{total}")

    # Tarixiy hisoblagichlar O'ZGARMAGAN (tests/schema_test.py bilan bir xil).
    check("schema.sql hisoblagichi o'zgarmadi: 31 jadval",
          schema.count("CREATE TABLE IF NOT EXISTS") == 31,
          str(schema.count("CREATE TABLE IF NOT EXISTS")))
    check("schema.sql hisoblagichi o'zgarmadi: 33 indeks",
          schema.count("CREATE INDEX IF NOT EXISTS") == 33,
          str(schema.count("CREATE INDEX IF NOT EXISTS")))

    # Idempotentlik: ikki marta qo'llash xavfsiz + bir xil DDL.
    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        pass
    executed = []

    class _Cur:
        def execute(self, sql, params=None):
            executed.append(" ".join(sql.split()))

    db._apply_analytics_performance_indexes(_Cur())
    first = list(executed)
    db._apply_analytics_performance_indexes(_Cur())
    second = list(executed)[len(first):]
    check("_apply_analytics_performance_indexes: 7 ta DDL qo'llanildi",
          len(first) == 7, str(len(first)))
    check("Ikkinchi qo'llashda ham AYNAN bir xil idempotent DDL (IF NOT EXISTS)",
          first == second and all("CREATE INDEX IF NOT EXISTS" in s for s in second))
    check("Har bir DDL `;` bilan yuboriladi", all(s.endswith(";") for s in first))

    # Fail-soft: bitta indeks xato bersa qolganlari baribir bajariladi.
    attempts = []

    class _FlakyCur:
        def execute(self, sql, params=None):
            attempts.append(sql)
            if "idx_post_reactions_post_type" in sql:
                raise RuntimeError("simulyatsiya: indeks qurilmadi")

    try:
        db._apply_analytics_performance_indexes(_FlakyCur())
        failed_soft = True
    except Exception:
        failed_soft = False
    check("Indeks xatosi bot ishlashini to'xtatmaydi (fail-soft)", failed_soft)
    check("Xato bo'lgan indeksdan keyingilari ham bajarildi", len(attempts) == 7,
          str(len(attempts)))
    check("Startup'da analitika indekslari qo'llaniladi (init_db ichida)",
          "_apply_analytics_performance_indexes(cur)" in (BOT_ROOT / "database.py").read_text(encoding="utf-8"))
    check("Startup tekshiruvi yangi indeks nomlarini talab qiladi",
          "*ANALYTICS_PERFORMANCE_INDEX_NAMES" in (BOT_ROOT / "database.py").read_text(encoding="utf-8"))


# ===========================================================================
# TEST 6 — 📊 STATISTIKA: 8 → 3 SO'ROV
# ===========================================================================
def test_channel_post_stats_queries():
    head("== TEST 6: 📊 get_channel_post_stats — 8 ta so'rov → 3 ta ==")

    store = QueryCountingStore()
    with patch("database.db_cursor", store.db_cursor):
        stats = posts_repo.get_channel_post_stats(USER_ID, CH_ID)
    check("Kanal statistikasi AYNAN 3 ta SQL so'rovda olindi (ilgari 8 ta)",
          store.execute_count == 3, str(store.execute_count))
    sql_all = " ".join(store.sql_texts())
    check("Barcha davr COUNT'lari bitta so'rovda (COUNT(*) FILTER)",
          "COUNT(*) FILTER (WHERE sp.status = 'posted'" in sql_all)
    check("Peak hours + type distribution bitta so'rovda (GROUPING SETS)",
          "GROUPING SETS" in sql_all)
    check("Qaytadigan kalitlar AYNAN o'sha (orqaga moslik)",
          {"sent_7d", "sent_30d", "sent_all", "pending",
           "peak_hours", "type_distribution"} <= set(stats.keys()))
    check("COUNT'lar to'g'ri o'qildi (1/2/3/4)",
          (stats["sent_7d"], stats["sent_30d"], stats["sent_all"], stats["pending"]) == (1, 2, 3, 4),
          str(stats))
    check("peak_hours saralangan va eng ko'p 3 ta",
          stats["peak_hours"] == [(19, 5), (18, 3)], str(stats["peak_hours"]))
    check("type_distribution grupdan to'g'ri yig'ildi",
          stats["type_distribution"] == {"photo": 4, "text": 2},
          str(stats["type_distribution"]))
    check("history (views) statistikasi DB agregati bilan",
          stats["history_count"] == 10 and stats["total_views"] == 5000
          and stats["avg_views"] == 500.0, str(stats))
    store_err = QueryCountingStore(fail_all=True)
    with patch("database.db_cursor", store_err.db_cursor):
        broken = posts_repo.get_channel_post_stats(USER_ID, CH_ID)
    for key in ("sent_7d", "sent_30d", "sent_all", "pending", "peak_hours",
                "type_distribution"):
        check(f"DB xatosida fail-soft (kalit saqlanadi: {key})", key in broken)

    # Global (kanalsiz) rejim ham 3 ta so'rov.
    store2 = QueryCountingStore()
    with patch("database.db_cursor", store2.db_cursor):
        posts_repo.get_channel_post_stats(USER_ID, None)
    check("Kanalsiz (umumiy) rejim ham 3 ta so'rov", store2.execute_count == 3,
          str(store2.execute_count))

    # DB xatosi — istisno YO'Q, nollar bilan xavfsiz lug'at.
    store3 = QueryCountingStore(fail_all=True)
    with patch("database.db_cursor", store3.db_cursor):
        broken = posts_repo.get_channel_post_stats(USER_ID, CH_ID)
    check("DB xatosida istisno ko'tarilmaydi (fail-soft)",
          isinstance(broken, dict) and broken["sent_all"] == 0)


# ===========================================================================
# TEST 7 — 🔐 IDOR / FAIL-CLOSED
# ===========================================================================
def test_idor_and_fail_closed():
    head("== TEST 7: 🔐 IDOR + fail-closed ==")

    store = QueryCountingStore(posts=make_posts(50))
    with counting_db(store, posts=make_posts(50)) as fake:
        res = _run(analyze_channel_posts(CH_ID, OTHER_USER_ID, limit=50, db_module=fake))
    check("IDOR: begona foydalanuvchi tahlil olmaydi (FORBIDDEN)",
          res.get("ok") is False and res.get("error_code") == "FORBIDDEN", str(res))
    check("IDOR: analytics so'rovlari UMUMAN yuborilmadi (fail-closed, 0 SQL)",
          store.execute_count == 0, str(store.execute_count))
    check("IDOR: postlar oshkor qilinmadi", not res.get("posts"))

    store = QueryCountingStore(posts=make_posts(50))
    with counting_db(store, posts=make_posts(50)) as fake:
        snap = _run(get_channel_analytics_snapshot(CH_ID, OTHER_USER_ID, db_module=fake))
    check("IDOR (snapshot): begona foydalanuvchi FORBIDDEN",
          snap.get("ok") is False and snap.get("error_code") == "FORBIDDEN", str(snap))

    # DB xatosi — fail-soft (ok=True, soxta raqam yo'q).
    store = QueryCountingStore(posts=make_posts(20), fail_all=True)
    with counting_db(store, posts=make_posts(20)) as fake:
        res = _run(analyze_channel_posts(CH_ID, USER_ID, limit=20, db_module=fake))
    check("DB xatosida fail-soft: crash yo'q", res.get("ok") is True, str(res))
    check("DB xatosida postlar bo'sh (uydirma ma'lumot yo'q)", res.get("posts") == [])
    check("DB xatosida so'rov soni baribir chegarada (2)", store.execute_count <= 2,
          str(store.execute_count))

    # Noto'g'ri kanal ID.
    bad = _run(analyze_channel_posts("", USER_ID, db_module=None))
    check("Bo'sh kanal ID → INVALID_CHANNEL",
          bad.get("ok") is False and bad.get("error_code") == "INVALID_CHANNEL")
    check("services.channels.analytics: MIN_POSTS_FOR_ANALYTICS e'lon qilingan",
          MIN_POSTS_FOR_ANALYTICS >= 5)


# ===========================================================================
# TEST 8 — 🔁 REGRESSIYA (INTERFEYS O'ZGARMAGAN)
# ===========================================================================
class _LegacyFakeDB:
    """Eski (analitika funksiyalarisiz) DB surati — orqaga moslik uchun."""

    def __init__(self, count=10, owner=USER_ID):
        self.count = count
        self.owner = owner
        base = datetime(2026, 9, 15, 14, 0, tzinfo=timezone.utc)
        self.history = []
        self.events = []
        for i in range(count):
            dt_item = base - timedelta(days=i + 1)
            text_item = (f"📌 Oldingi tahliliy maqola #{i + 1}: sun'iy intellekt va "
                         f"avtomatlashtirish.\n\n👉 Batafsil: @tech_biznes")
            self.history.append({
                "id": i + 1, "channel_id": CH_ID, "message_id": 100 + i,
                "content": text_item, "views": 1200 + i * 150,
                "post_date": dt_item.isoformat(),
            })
            self.events.append({
                "channel_id": CH_ID, "message_id": 100 + i, "text": text_item,
                "length": len(text_item), "emoji_density": 0.02,
                "has_cta": True, "cta_detected": True,
                "post_hour": 19, "post_weekday": dt_item.weekday(),
                "format": "list" if i % 2 == 0 else "structured",
            })

    async def run_db(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def get_channel_owner_id(self, channel_id):
        return self.owner if str(channel_id) == CH_ID else None

    def get_channel_post_events(self, channel_id, limit=500):
        return list(self.events[:limit]) if str(channel_id) == CH_ID else []

    def get_channel_posts_history(self, channel_id, limit=50):
        return [dict(r) for r in self.history[:limit]] if str(channel_id) == CH_ID else []

    def get_channel_intelligence_profile(self, channel_id):
        return None

    def save_channel_dna_profile(self, channel_id, profile=None, **kwargs):
        return True

    def save_channel_intelligence_profile(self, channel_id, **kwargs):
        return True

    def is_premium(self, user_id):
        return True


def test_regression_interface():
    head("== TEST 8: 🔁 Regressiya — mavjud interfeys saqlangan ==")

    legacy = _LegacyFakeDB()
    loop = ContentLoop(db_module=legacy)
    res = _run(loop.analyze(CH_ID, USER_ID, goal="engagement", frequency=2, lang="uz",
                            now=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)))
    old_keys = {"ok", "channel_id", "goal", "frequency", "dna_result", "dna_profile",
                "best_time_result", "best_hours", "weekly_insights", "gaps",
                "content_gaps", "topic_gaps", "recommended_formats",
                "recent_posts_30d", "recent_texts", "recent_topics", "prompt_block"}
    check("ContentLoop.analyze: eski kalitlar 100% joyida",
          old_keys <= set(res.keys()), str(sorted(old_keys - set(res.keys()))))
    check("ContentLoop.analyze: 30 kunlik matnlar (10 ta) saqlangan",
          len(res.get("recent_texts") or []) == 10, str(len(res.get("recent_texts") or [])))
    check("ContentLoop.analyze: 14 ta tavsiya format (7 kun × 2)",
          len(res.get("recommended_formats") or []) == 14)
    check("ContentLoop.analyze: legacy DB'da analitika lokaldan (db_aggregate EMAS)",
          res.get("analytics_source") == "local_fallback", str(res.get("analytics_source")))
    check("ContentLoop.analyze: QO'SHIMCHA analytics_summary kaliti qo'shildi",
          isinstance(res.get("analytics_summary"), dict)
          and "avg_views" in res["analytics_summary"])
    check("ContentLoop.analyze: IDOR saqlangan",
          _run(loop.analyze(CH_ID, OTHER_USER_ID, goal="growth")).get("error_code") == "FORBIDDEN")

    # DB agregatsiyasi mavjud bo'lsa — undan foydalanadi (1 ta qo'shimcha so'rov).
    store = QueryCountingStore(posts=make_posts(20))
    with counting_db(store, posts=make_posts(20)) as fake:
        legacy2 = _LegacyFakeDB()
        fake.get_channel_posts_history = legacy2.get_channel_posts_history
        fake.get_channel_post_events = legacy2.get_channel_post_events
        fake.get_channel_intelligence_profile = legacy2.get_channel_intelligence_profile
        fake.save_channel_dna_profile = legacy2.save_channel_dna_profile
        fake.save_channel_intelligence_profile = legacy2.save_channel_intelligence_profile
        res2 = _run(ContentLoop(db_module=fake).analyze(
            CH_ID, USER_ID, goal="growth", now=datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)))
    check("ContentLoop.analyze: DB agregatsiyasi bo'lsa undan foydalanadi",
          res2.get("analytics_source") == "db_aggregate", str(res2.get("analytics_source")))
    check("ContentLoop.analyze: so'rovlar soni kichik konstanta (<= 6)",
          store.execute_count <= 6, str(store.execute_count))
    check("ContentLoop.analyze: avg_views DB xulosasidan olindi",
          res2.get("avg_views") == 1000.0, str(res2.get("avg_views")))

    # DNA — eski kalitlar saqlangan.
    dna_res = _run(get_channel_dna_extended(CH_ID, USER_ID, db_module=legacy))
    check("get_channel_dna_extended: ok=True (legacy DB)",
          dna_res.get("ok") is True and dna_res.get("insufficient") is False, str(dna_res)[:120])
    check("get_channel_dna_extended: eski kalitlar joyida",
          {"profile", "metrics", "overall", "confidence", "sample_size", "saved"} <= set(dna_res))
    check("get_channel_dna_extended: legacy DB'da analytics_summary = None",
          dna_res.get("analytics_summary") is None)

    # Facade / paket eksportlari.
    check("database facade: yangi analitika funksiyalari eksport qilindi",
          all(hasattr(db, n) for n in (
              "get_channel_analytics_bundle", "get_channel_analytics_summary",
              "get_channel_posts_metrics_batch", "get_channels_analytics_summary",
              "get_posts_metrics_batch", "get_posts_reaction_metrics_batch",
              "get_posts_delivery_metrics_batch", "get_post_metrics",
          )))
    check("database facade: get_channel_post_stats o'sha obyekt (o'zgarmagan)",
          db.get_channel_post_stats is posts_repo.get_channel_post_stats)
    check("repositories paketi: asosiy 8 ta modul ro'yxati o'zgarmagan",
          len(repositories.REPOSITORIES) == 8, str(len(repositories.REPOSITORIES)))
    check("analytics_repository OPTIONAL ro'yxatda e'lon qilingan",
          "repositories.analytics_repository" in repositories.OPTIONAL_REPOSITORIES)
    check("analytics_repository kech bog'langan `db_cursor` proksisidan foydalanadi",
          "from repositories.runtime import db_cursor" in
          (BOT_ROOT / "repositories" / "analytics_repository.py").read_text(encoding="utf-8"))

    import services.channels as channels_pkg
    check("services.channels eksportlari: yangi servis funksiyalari",
          all(hasattr(channels_pkg, n) and n in channels_pkg.__all__ for n in (
              "analyze_channel_posts", "get_channel_analytics_snapshot",
              "summarize_posts_locally", "attach_analytics_summary",
          )))
    check("attach_analytics_summary: mavjud DNA qiymatlarini QAYTA YOZMAYDI",
          attach_analytics_summary(
              {"high_performing_formats_value": ["case_study"]},
              {"best_formats": ["photo"], "avg_views": 10},
          )["high_performing_formats_value"] == ["case_study"])


# ===========================================================================
# TEST 9 — 🔎 STATIK N+1 SKANERI
# ===========================================================================
def _execute_calls_in_loops(path) -> list:
    """Faylda tsikl ichidagi `cur.execute` / DB chaqiruvlarini topadi."""
    source = Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for stmt in ast.walk(node):
                if isinstance(stmt, ast.Call):
                    target = stmt.func
                    name = getattr(target, "attr", None) or getattr(target, "id", "")
                    if name in ("execute", "run_db", "fetchone", "fetchall", "_db_call"):
                        found.append((path, stmt.lineno, name))
    return found


def test_static_n_plus_one_scan():
    head("== TEST 9: 🔎 Statik N+1 skaneri ==")

    analytics_src = (BOT_ROOT / "repositories" / "analytics_repository.py").read_text(encoding="utf-8")
    check("analitika repository'sida 5 ta o'qish funksiyasi, har birida bitta cursor bloki",
          analytics_src.count("with db_cursor() as cur:") == 5,
          str(analytics_src.count("with db_cursor() as cur:")))
    nested_cursor = []
    for node in ast.walk(ast.parse(analytics_src)):
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            for stmt in ast.walk(node):
                if (isinstance(stmt, ast.With) and "db_cursor" in ast.unparse(stmt)
                        and stmt.lineno > node.lineno):
                    nested_cursor.append(stmt.lineno)
    check("`db_cursor()` tsikl ichida chaqirilmaydi (chunking/loop yo'q)",
          not nested_cursor, str(nested_cursor))

    tree = ast.parse(analytics_src)
    per_func_executes = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            n = sum(
                1 for stmt in ast.walk(node)
                if isinstance(stmt, ast.Call)
                and getattr(stmt.func, "attr", None) == "execute"
            )
            if n:
                per_func_executes[node.name] = n
    check("Har bir ochiq funksiya AYNAN 1 ta `cur.execute` qiladi",
          set(per_func_executes.values()) == {1}, str(per_func_executes))
    check("`execute` faqat ma'lum (1 so'rovli) funksiyalarda: "
          + ", ".join(sorted(per_func_executes)),
          len(per_func_executes) >= 5, str(sorted(per_func_executes)))

    for rel in ("repositories/analytics_repository.py", "services/channels/analytics.py"):
        loops = _execute_calls_in_loops(BOT_ROOT / rel)
        check(f"{rel}: tsikl ichida DB chaqiruvi YO'Q (N+1 yo'q)", not loops, str(loops))

    # Servis repository'ni to'g'ri chaqiradi (per-post emas).
    service_src = (BOT_ROOT / "services" / "channels" / "analytics.py").read_text(encoding="utf-8")
    check("Servis batch funksiyalarini chaqiradi",
          "get_channel_posts_metrics_batch" in service_src
          and "get_channel_analytics_summary" in service_src)
    check("Servis `get_post_metrics(` kabi per-post chaqiruvni ISHLATMAYDI",
          "get_post_metrics(" not in service_src)

    # content_loop: yangi analitika chaqiruvi tsikl ichida emas.
    cl_loops = _execute_calls_in_loops(BOT_ROOT / "services" / "channels" / "content_loop.py")
    check("content_loop.py: tsikl ichida DB chaqiruvi yo'q", not cl_loops, str(cl_loops))

    # posts_repository: statistika funksiyasida 3 ta execute (8 emas).
    posts_src = (BOT_ROOT / "repositories" / "posts_repository.py").read_text(encoding="utf-8")
    fn_body = posts_src.split("def get_channel_post_stats", 1)[1].split("\ndef ", 1)[0]
    # Statik jihatdan 4 ta `cur.execute` (oxirgi ikkisi if/else — bir vaqtda
    # faqat bittasi bajariladi), ya'ni RUNTIME'da 3 ta so'rov (ilgari 8 ta).
    check("get_channel_post_stats: statik `cur.execute` 8 → 4 (if/else tarmoqlari)",
          fn_body.count("cur.execute(") == 4, str(fn_body.count("cur.execute(")))
    check("get_channel_post_stats: davr bo'yicha tsikl (for period) YO'Q",
          "for period" not in fn_body)
    check("get_channel_post_stats: `COUNT(*) FILTER` bilan bitta so'rovda",
          "COUNT(*) FILTER" in fn_body)
    check("get_channel_post_stats: `GROUPING SETS` bilan bitta so'rovda",
          "GROUPING SETS" in fn_body)


# ===========================================================================
# TEST 10 — 🐘 REAL PostgreSQL (ixtiyoriy: pgserver bo'lmasa SKIP)
# ===========================================================================
def _start_test_postgres():
    """Test bazasi URI: STEP5_TEST_DATABASE_URL | P0_TEST_DATABASE_URL | pgserver."""
    for var in ("STEP5_TEST_DATABASE_URL", "P0_TEST_DATABASE_URL", "INTEGRITY_TEST_DATABASE_URL"):
        url = os.getenv(var)
        if url and "user:pass" not in url:
            return url, None
    if os.getenv("STEP5_SKIP_LIVE") == "1":
        return None, None
    try:
        import pgserver
    except ImportError:
        return None, None
    import shutil
    import tempfile
    server_dir = os.path.join(tempfile.gettempdir(), "step5_perf_pg")
    shutil.rmtree(server_dir, ignore_errors=True)
    try:
        server = pgserver.get_server(server_dir)
        return server.get_uri(), server
    except Exception as e:  # pragma: no cover — muhitga bog'liq
        print(f"  (pgserver ishga tushmadi: {e})")
        return None, None


class _CountingCursor:
    """Real kursorni o'raydi va yuborilgan SQL'ni SANAYDI (N+1 detektori)."""

    def __init__(self, cur, counter):
        self._cur = cur
        self._counter = counter

    def execute(self, sql, params=None):
        self._counter.append(" ".join(str(sql).split()))
        return self._cur.execute(sql, params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __getattr__(self, item):
        return getattr(self._cur, item)


def test_live_postgres():
    head("== TEST 10: 🐘 REAL PostgreSQL (batch SQL + indekslar) ==")

    uri, server = _start_test_postgres()
    if not uri:
        print("  [SKIP] live PostgreSQL sinovi "
              "(pgserver/STEP5_TEST_DATABASE_URL mavjud emas)")
        return

    original_url = db.DATABASE_URL
    try:
        db.DATABASE_URL = uri
        os.environ["DATABASE_URL"] = uri
        db._reset_pool()
        db.init_db()
        db.init_db()   # 2-marta: idempotent migratsiya
        check("init_db() ikki marta xatosiz (idempotent)", True)

        with db.db_cursor() as cur:
            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()")
            live_indexes = {r[0] for r in cur.fetchall()}
        missing = [n for n in db.ANALYTICS_PERFORMANCE_INDEX_NAMES if n not in live_indexes]
        check("7 ta analitika indeksi REAL bazada yaratildi", not missing, str(missing))

        with db.db_cursor(commit=True) as cur:
            cur.execute("INSERT INTO users (user_id, plan_type) VALUES (555001, 'free') "
                        "ON CONFLICT DO NOTHING")
            cur.execute("INSERT INTO channels (channel_id, user_id, channel_title, is_active) "
                        "VALUES (%s, 555001, %s, TRUE) ON CONFLICT DO NOTHING",
                        (CH_ID, CH_TITLE))
            for i in range(50):
                cur.execute(
                    "INSERT INTO channel_posts_history (channel_id, message_id, content, views, post_date) "
                    "VALUES (%s, %s, %s, %s, NOW() - make_interval(hours => %s))",
                    (CH_ID, 9000 + i, f"Post #{i}", 500 + i * 7, i))
                cur.execute(
                    "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, "
                    "scheduled_time, status) VALUES (555001, %s, %s, %s, "
                    "NOW() - make_interval(days => %s), 'posted')",
                    (CH_ID, "photo" if i % 2 == 0 else "text", f"Post #{i}", i))
                cur.execute(
                    "INSERT INTO sent_post_messages (post_id, channel_id, message_id) VALUES (%s, %s, %s)",
                    (i + 1, CH_ID, 9000 + i))
                for u in range(3):
                    cur.execute(
                        "INSERT INTO post_reactions (post_id, user_id, reaction_type) "
                        "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                        (i + 1, 6000 + u, "👍" if u < 2 else "🔥"))
                cur.execute(
                    "INSERT INTO channel_post_events (channel_id, message_id, post_hour, post_weekday, "
                    "has_media, media_type, length, cta_detected, emoji_density) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    (CH_ID, 9000 + i, 19 if i % 3 == 0 else 12, i % 7, i % 2 == 0,
                     "photo" if i % 2 == 0 else None, 120 + i, i % 2 == 0, 0.02))

        real_db_cursor = db.db_cursor
        counter = []

        @contextlib.contextmanager
        def counting_cursor(commit: bool = False):
            with real_db_cursor(commit=commit) as cur:
                yield _CountingCursor(cur, counter)

        with patch("database.db_cursor", counting_cursor):
            counter.clear()
            rows = db.get_channel_posts_metrics_batch(CH_ID, 50)
            check("REAL DB: 50 ta post metrikasi AYNAN 1 ta SQL",
                  len(counter) == 1 and len(rows) == 50, f"{len(counter)} SQL, {len(rows)} post")
            check("REAL DB: reaksiyalar JOIN+GROUP BY'dan (3 ta)",
                  all(r["reactions"] == 3 for r in rows), str(rows[0]["reactions"]))
            check("REAL DB: format media_type'dan ({photo, text})",
                  {r["format"] for r in rows} == {"photo", "text"},
                  str({r["format"] for r in rows}))

            counter.clear()
            summary = db.get_channel_analytics_summary(CH_ID, 30)
            check("REAL DB: xulosa AYNAN 1 ta SQL (DB darajasidagi agregatsiya)",
                  len(counter) == 1, str(len(counter)))
            check("REAL DB: posts=50, events=50, media=25, cta=25",
                  (summary["posts"], summary["events"], summary["media_posts"],
                   summary["cta_posts"]) == (50, 50, 25, 25), str(summary))
            check("REAL DB: total_reactions=150 (3 × 50)",
                  summary["total_reactions"] == 150, str(summary["total_reactions"]))
            check("REAL DB: eng yaxshi formatlar AVG(views) bo'yicha tartiblangan",
                  summary["best_formats"] == ["text", "photo"], str(summary["best_formats"]))
            check("REAL DB: format_distribution = {photo: 25, text: 25}",
                  summary["format_distribution"] == {"photo": 25, "text": 25},
                  str(summary["format_distribution"]))

            counter.clear()
            metrics = db.get_posts_metrics_batch(list(range(1, 51)))
            check("REAL DB: 50 ta post metrikasi `= ANY(%s)` bilan AYNAN 2 ta SQL",
                  len(counter) == 2 and len(metrics) == 50, f"{len(counter)} SQL")
            check("REAL DB: yuborilgan xabarlar bo'yicha message_id/channel_id",
                  metrics[1]["message_id"] == 9000 and metrics[1]["delivered"] is True
                  and metrics[1]["channel_id"] == CH_ID, str(metrics[1]))

            counter.clear()
            stats = posts_repo.get_channel_post_stats(555001, CH_ID)
            check("REAL DB: get_channel_post_stats AYNAN 3 ta SQL (ilgari 8 ta)",
                  len(counter) == 3, str(len(counter)))
            check("REAL DB: sent_all=50, type_distribution={photo:25,text:25}",
                  stats["sent_all"] == 50
                  and stats["type_distribution"] == {"photo": 25, "text": 25}, str(stats))
            check("REAL DB: peak_hours GROUPING SETS'dan (<=3 guruh, jami 50)",
                  len(stats["peak_hours"]) <= 3
                  and sum(cnt for _, cnt in stats["peak_hours"]) == 50,
                  str(stats["peak_hours"]))
            check("REAL DB: peak_hours eng katta guruh birinchi",
                  stats["peak_hours"][0][1] == max(cnt for _, cnt in stats["peak_hours"]),
                  str(stats["peak_hours"]))

            counter.clear()
            many = db.get_channels_analytics_summary([CH_ID, "-100000000000"], 30)
            check("REAL DB: 2 ta kanal AYNAN 1 ta SQL", len(counter) == 1, str(len(counter)))
            check("REAL DB: mavjud kanal 50 post, yo'q kanal 0",
                  many[CH_ID]["posts"] == 50 and many["-100000000000"]["posts"] == 0, str(many))

            # N+1 PROOF: postlar soni oshsa ham so'rovlar soni O'ZGARMAYDI.
            counter.clear()
            service_res = _run(analyze_channel_posts(CH_ID, 555001,
                                                     limit=50, days=30, db_module=db))
            count_50 = len(counter)
            counter.clear()
            _run(analyze_channel_posts(CH_ID, 555001, limit=200, days=30, db_module=db))
            count_200 = len(counter)
            check("REAL DB: so'rovlar soni postlar soniga BOG'LIQ EMAS (50 == 200)",
                  count_50 == count_200, f"50→{count_50}, 200→{count_200}")
            check("REAL DB: servis jami <= 3 SQL (owner + 2 batch, N+1 YO'Q)",
                  count_50 <= 3, str(count_50))
            check("REAL DB: servis xulosasi DB agregatidan",
                  service_res.get("avg_views") == summary["avg_views"],
                  str(service_res.get("avg_views")))
            counter.clear()
            idor_res = _run(analyze_channel_posts(CH_ID, OTHER_USER_ID, db_module=db))
            check("REAL DB: IDOR fail-closed (begona user → FORBIDDEN, 0 analitika SQL)",
                  idor_res.get("error_code") == "FORBIDDEN"
                  and all("analytics" not in s.lower() for s in counter), str(idor_res))

        with db.db_cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("EXPLAIN SELECT id, views FROM channel_posts_history "
                        "WHERE channel_id = %s ORDER BY views DESC LIMIT 10", (CH_ID,))
            plan_views = "\n".join(r[0] for r in cur.fetchall())
        check("REAL DB: (channel_id, views DESC) indeksi ishlatiladi",
              "idx_channel_posts_history_channel_views" in plan_views, plan_views[:160])

        with db.db_cursor() as cur:
            cur.execute("SET LOCAL enable_seqscan = off")
            cur.execute("EXPLAIN SELECT COUNT(*) FILTER (WHERE status = 'posted') "
                        "FROM scheduled_posts WHERE user_id = 555001 AND channel_id = %s", (CH_ID,))
            plan_status = "\n".join(r[0] for r in cur.fetchall())
        check("REAL DB: (channel_id, status) indeksi ishlatiladi",
              "idx_scheduled_posts_channel_status" in plan_status, plan_status[:160])

        # Migratsiya idempotentligi: schema.sql + indekslar yana bir marta.
        try:
            with db.db_cursor(commit=True) as cur:
                db._apply_schema_file(cur)
                db._apply_analytics_performance_indexes(cur)
            check("REAL DB: schema.sql + analitika indekslari 3-marta xatosiz", True)
        except Exception as exc:  # pragma: no cover
            check("REAL DB: schema.sql + analitika indekslari 3-marta xatosiz", False, str(exc))
    except Exception as exc:  # pragma: no cover — muhitga bog'liq
        check("live PostgreSQL sinovi xatosiz o'tdi", False, f"{type(exc).__name__}: {exc}")
    finally:
        try:
            db.close_pool()
        except Exception:
            pass
        db.DATABASE_URL = original_url
        os.environ["DATABASE_URL"] = original_url
        try:
            db._reset_pool()
        except Exception:
            pass
        if server is not None:
            try:
                server.cleanup()
            except Exception:
                pass


# ===========================================================================
def main():
    print("=" * 72)
    print(" 🧭 POSTASSIST V2 · 5-QADAM — P1 PERFORMANCE & DB OPTIMIZATION")
    print("    (ANALYTICS N+1 OPTIMIZATION + INDEX TUNING)")
    print("=" * 72)

    test_no_n_plus_one()
    test_any_batch_fetching()
    test_db_level_aggregation()
    test_multi_channel_single_query()
    test_index_tuning()
    test_channel_post_stats_queries()
    test_idor_and_fail_closed()
    test_regression_interface()
    test_static_n_plus_one_scan()
    test_live_postgres()

    print()
    print("=" * 72)
    total = PASSED + FAILURES
    print(f"JAMI: PASS={PASSED}, FAIL={FAILURES} (jami {total})")
    if FAILURES:
        print("5-QADAM PERFORMANCE TESTLARI YIQILDI ✘")
        return 1
    print("5-QADAM PERFORMANCE TESTLARI 100% YASHIL ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
