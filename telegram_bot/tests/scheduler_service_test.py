#!/usr/bin/env python3
"""SchedulerService testlari — PostAssist V2 (3-bosqich).

Ishga tushirish:
    cd telegram_bot && python tests/scheduler_service_test.py

Mock-testlar DB ulanish talab qilmaydi. Concurrency/backoff oqimlari real
PostgreSQL'da tekshiriladi: P0_TEST_DATABASE_URL berilsa o'sha baza, aks holda
pgserver (o'rnatilgan bo'lsa) orqali lokal baza ishlatiladi. Hech biri bo'lmasa
real-DB testlari o'tkazib yuboriladi (mock + SQL-kafolar testlari baribir ishlaydi).

Talablar (spetsifikatsiya):
  1) 'sent' dan keyin Telegram API qayta chaqirilmaydi (0 duplikat).
  2) Vaqtinchalik xatoda attempt_count oshadi + backoff (30s/2m/5m/15m).
  3) Doimiy xatoda (BotKicked/ChatNotFound/...) → darhol 'dead_letter'.
  4) 2 parallel worker bir xil postni claim qilsa — faqat BIRINCHI yuboradi.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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


# ============================================================
# MOCK DB CURSOR (services_test.py andozasi bilan bir xil)
# ============================================================

class MockCursor:
    """Minimal psycopg2 cursor mock (fetchone/fetchall navbatlari bilan)."""

    def __init__(self):
        self._rows = []
        self._rc = 1
        self._queries = []
        self._params_list = []

    def execute(self, query, params=None):
        self._queries.append(query)
        self._params_list.append(params)

    def fetchone(self):
        if self._rows:
            return self._rows.pop(0)
        return None

    def fetchall(self):
        rows = list(self._rows)
        self._rows.clear()
        return rows

    @property
    def rowcount(self):
        return self._rc

    @rowcount.setter
    def rowcount(self, val):
        self._rc = val

    def close(self):
        pass


def _make_mock_dc(cur):
    @contextmanager
    def _dc(commit=False):
        yield cur
    return _dc


def _fresh_cur(rows=None, rowcount=1):
    cur = MockCursor()
    cur._rows = list(rows) if rows else []
    cur._rc = rowcount
    return cur


def _queries_text(cur):
    return "\n".join(str(q) for q in cur._queries)


NOW = datetime.now(timezone.utc)
FRESH_TS = NOW - timedelta(seconds=30)
STALE_TS = NOW - timedelta(minutes=15)
FUTURE_TS = NOW + timedelta(minutes=5)
PAST_TS = NOW - timedelta(minutes=5)


# ============================================================
# 1. IDEMPOTENCY KALITI — post_id + channel_id + scheduled_time
# ============================================================

def test_idempotency_key_strict():
    print("== Idempotency kaliti (qat'iy uchlik) ==")
    from services.scheduler_service import SchedulerService
    import database as db_mod

    sched = datetime(2026, 9, 10, 14, 30, tzinfo=timezone.utc)
    key = SchedulerService.build_idempotency_key(777, "-100123", sched)
    check("kalit post_id ni o'z ichiga oladi", "777" in key, key)
    check("kalit channel_id ni o'z ichiga oladi", "-100123" in key, key)
    check("kalit scheduled_time ni o'z ichiga oladi", "2026-09-10" in key, key)
    check("kalit db.builder bilan bir xil",
          key == db_mod.build_delivery_idempotency_key(777, "-100123", sched))

    other_time = SchedulerService.build_idempotency_key(
        777, "-100123", sched + timedelta(minutes=1))
    check("boshqa vaqt → boshqa kalit", other_time != key)
    other_channel = SchedulerService.build_idempotency_key(777, "-100999", sched)
    check("boshqa kanal → boshqa kalit", other_channel != key)
    other_post = SchedulerService.build_idempotency_key(778, "-100123", sched)
    check("boshqa post → boshqa kalit", other_post != key)

    # Takroriy build — bir xil kalit (deterministik)
    again = SchedulerService.build_idempotency_key(777, "-100123", sched)
    check("kalit deterministik", again == key)


# ============================================================
# 2. BACKOFF JADVALI
# ============================================================

def test_backoff_mapping():
    print("== Backoff jadvali (30s/2m/5m/15m, 5+ → dead) ==")
    from services.scheduler_service import SchedulerService

    check("1-urinish → 30s", SchedulerService.backoff_for_attempt(1) == 30)
    check("2-urinish → 120s", SchedulerService.backoff_for_attempt(2) == 120)
    check("3-urinish → 300s", SchedulerService.backoff_for_attempt(3) == 300)
    check("4-urinish → 900s", SchedulerService.backoff_for_attempt(4) == 900)
    check("5-urinish → None (dead_letter)",
          SchedulerService.backoff_for_attempt(5) is None)
    check("6-urinish → None", SchedulerService.backoff_for_attempt(6) is None)
    check("0 → None", SchedulerService.backoff_for_attempt(0) is None)
    check("None → None", SchedulerService.backoff_for_attempt(None) is None)
    check("MAX_ATTEMPTS = 5", SchedulerService.MAX_ATTEMPTS == 5)


# ============================================================
# 3. DOIMIY / VAQTINCHALIK XATO TASNIFI
# ============================================================

class BotKicked(Exception):
    """PTB o'ramlari/future versiyalar uchun simulyatsiya."""


class ChatNotFound(Exception):
    """PTB o'ramlari/future versiyalar uchun simulyatsiya."""


def test_permanent_error_classification():
    print("== Doimiy xato tasnifi ==")
    from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut
    from services.scheduler_service import SchedulerService

    is_perm = SchedulerService.is_permanent_error

    # Klass nomi bo'yicha (spetsifikatsiya: BotKicked / ChatNotFound)
    check("BotKicked → doimiy", is_perm(BotKicked("bot was kicked")) is True)
    check("ChatNotFound → doimiy", is_perm(ChatNotFound("chat not found")) is True)
    # PTB real xatolari — matn naqshlari bo'yicha
    check("Forbidden(bot kicked) → doimiy",
          is_perm(Forbidden("Forbidden: bot was kicked from the group chat")) is True)
    check("BadRequest(chat not found) → doimiy",
          is_perm(BadRequest("Bad Request: chat not found")) is True)
    check("blocked by user → doimiy",
          is_perm(Forbidden("Forbidden: bot was blocked by the user")) is True)
    check("no rights → doimiy",
          is_perm(BadRequest("Bad Request: have no rights to send a message")) is True)
    check("not a member → doimiy",
          is_perm(Forbidden("Forbidden: bot is not a member of the channel")) is True)
    check("string 'chat_not_found' → doimiy", is_perm("chat_not_found") is True)
    check("string 'bot_kicked' → doimiy", is_perm("BOT_KICKED: x") is True)

    # Vaqtinchalik xatolar — doimiy EMAS
    check("RetryAfter → transient", is_perm(RetryAfter(retry_after=5)) is False)
    check("TimedOut → transient", is_perm(TimedOut("timed out")) is False)
    check("NetworkError → transient", is_perm(NetworkError("connection reset")) is False)
    check("oddiy Exception → transient", is_perm(Exception("boom")) is False)
    check("None → transient", is_perm(None) is False)

    # normalize_error_text — 4000 belgi chegarasi, klass nomi bilan
    long_err = "x" * 5000
    norm = SchedulerService.normalize_error_text(ValueError(long_err))
    check("xato matni 4000 belgidan oshmaydi", len(norm) <= 4000, str(len(norm)))
    check("klass nomi matnga qo'shiladi",
          "ValueError" in SchedulerService.normalize_error_text(ValueError("qisqa")))


# ============================================================
# 4. CLAIM — pending → processing (mock)
# ============================================================

def test_claim_pending_success():
    print("== Claim: pending → processing ==")
    from services.scheduler_service import SchedulerService

    sched = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
    cur = _fresh_cur(rows=[("pending", 0, None, None, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(501, "-100123", sched)
    check("claimed True", res.get("claimed") is True, str(res))
    check("status processing", res.get("status") == "processing")
    check("idempotency_key qaytadi", bool(res.get("idempotency_key")))
    check("kalit qat'iy uchlikdan",
          res.get("idempotency_key") == SchedulerService.build_idempotency_key(501, "-100123", sched))
    q = _queries_text(cur)
    check("INSERT ... ON CONFLICT", "INSERT INTO post_deliveries" in q and "ON CONFLICT DO NOTHING" in q)
    check("SELECT ... FOR UPDATE (atomik)", "FOR UPDATE" in q)
    check("claim urinishni oshirmaydi",
          not any(str(x).strip().upper().startswith("UPDATE") and "attempt_count" in str(x)
                  for x in cur._queries),
          str(cur._queries))
    check("claim'da next_retry_at o'qiladi", "next_retry_at" in q)


def test_claim_sent_skips_duplicate():
    print("== Claim: sent → skip (0 duplikat) ==")
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("sent", 1, 555, None, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(502, "-100123", NOW)
    check("claimed False", res.get("claimed") is False, str(res))
    check("sent True", res.get("sent") is True)
    check("message_id qaytadi", res.get("message_id") == 555)
    check("sent'dan keyin UPDATE yo'q",
          not any(str(x).strip().upper().startswith("UPDATE") for x in cur._queries),
          str(cur._queries))


def test_claim_processing_other_worker():
    print("== Claim: processing (boshqa worker) → kutish ==")
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("processing", 1, None, None, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(503, "-100123", NOW)
    check("claimed False", res.get("claimed") is False, str(res))
    check("status processing", res.get("status") == "processing")
    check("sent False", res.get("sent") is False)


def test_claim_dead_letter_never_retries():
    print("== Claim: dead_letter → hech qachon ==")
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("dead_letter", 5, None, None, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(504, "-100123", NOW)
    check("claimed False", res.get("claimed") is False, str(res))
    check("dead True", res.get("dead") is True)
    check("status dead_letter", res.get("status") == "dead_letter")


def test_claim_retry_pending_and_due():
    print("== Claim: failed + backoff (kutilmoqda / muddati o'tgan) ==")
    from services.scheduler_service import SchedulerService

    # Backoff hali o'tmagan → claim yo'q
    cur = _fresh_cur(rows=[("failed", 2, None, FUTURE_TS, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(505, "-100123", NOW)
    check("backoff o'tmagan → claimed False", res.get("claimed") is False, str(res))
    check("retry_pending True", res.get("retry_pending") is True)
    check("next_retry_at qaytadi", res.get("next_retry_at") == FUTURE_TS)

    # Backoff o'tgan → claim mumkin
    cur2 = _fresh_cur(rows=[("failed", 2, None, PAST_TS, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur2)):
        res2 = SchedulerService.claim_post_for_delivery(505, "-100123", NOW)
    check("backoff o'tgan → claimed True", res2.get("claimed") is True, str(res2))

    # next_retry_at NULL (legacy) → claim mumkin
    cur3 = _fresh_cur(rows=[("failed", 1, None, None, FRESH_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur3)):
        res3 = SchedulerService.claim_post_for_delivery(505, "-100123", NOW)
    check("retry NULL → claimed True", res3.get("claimed") is True, str(res3))


def test_claim_stale_processing_reclaim():
    print("== Claim: stale processing (crash) → qayta olish ==")
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("processing", 1, None, None, STALE_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.claim_post_for_delivery(506, "-100123", NOW)
    check("stale → claimed True", res.get("claimed") is True, str(res))
    check("stale_reclaim belgisi", res.get("stale_reclaim") is True)
    check("crash urinish sifatida sanaladi (1→2)", res.get("attempt_count") == 2)

    # Stale + urinishlar tugagan → dead_letter (cheksiz crash-loop yo'q)
    cur2 = _fresh_cur(rows=[("processing", 4, None, None, STALE_TS)])
    with patch("database.db_cursor", _make_mock_dc(cur2)):
        res2 = SchedulerService.claim_post_for_delivery(506, "-100123", NOW)
    check("stale + 5-urinish → dead", res2.get("dead") is True, str(res2))


def test_claim_resolves_scheduled_time():
    print("== Claim: scheduled_time berilmasa DB'dan o'qiladi ==")
    from services.scheduler_service import SchedulerService

    sched = datetime(2026, 9, 10, 18, 45, tzinfo=timezone.utc)
    resolve_cur = _fresh_cur(rows=[(sched,)])
    claim_cur = _fresh_cur(rows=[("pending", 0, None, None, FRESH_TS)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(resolve_cur)), \
         patch("database.db_cursor", _make_mock_dc(claim_cur)):
        res = SchedulerService.claim_post_for_delivery(507, "-100123", None)
    check("claimed True", res.get("claimed") is True, str(res))
    check("kalit DB'dagi vaqt bilan tuzilgan",
          res.get("idempotency_key") == SchedulerService.build_idempotency_key(507, "-100123", sched),
          str(res.get("idempotency_key")))

    # Noto'g'ri post_id → xavfsiz rad
    res_bad = SchedulerService.claim_post_for_delivery("not-an-int", "-100123", NOW)
    check("yaroqsiz post_id → claimed False", res_bad.get("claimed") is False)


# ============================================================
# 5. MARK AS SENT
# ============================================================

def test_mark_as_sent():
    print("== mark_as_sent (idempotent) ==")
    from services.scheduler_service import SchedulerService

    key = SchedulerService.build_idempotency_key(508, "-100123", NOW)
    cur = _fresh_cur()
    with patch("database.db_cursor", _make_mock_dc(cur)):
        ok = SchedulerService.mark_as_sent(508, "-100123", 4242, NOW)
    check("sent → True", ok is True)
    q = _queries_text(cur)
    check("UPDATE status='sent'", "status = 'sent'" in q, q[:200])
    check("telegram_message_id yoziladi",
          any(p and 4242 in p for p in cur._params_list), str(cur._params_list))
    check("next_retry_at tozalanadi", "next_retry_at = NULL" in q)

    # Kalit bo'yicha variant (scheduler marker oqimi)
    cur2 = _fresh_cur()
    with patch("database.db_cursor", _make_mock_dc(cur2)):
        ok2 = SchedulerService.mark_sent_by_key(key, 4243)
    check("mark_sent_by_key → True", ok2 is True)
    check("bo'sh kalit → False",
          SchedulerService.mark_sent_by_key("", 1) is False)

    # Allaqachon sent (rowcount=0, SELECT topdi) → baribir True
    cur3 = _fresh_cur(rows=[(1,)], rowcount=0)
    with patch("database.db_cursor", _make_mock_dc(cur3)):
        ok3 = SchedulerService.mark_sent_by_key(key, 4244)
    check("qayta sent → idempotent True", ok3 is True)


# ============================================================
# 6. MARK AS FAILED — transient backoff
# ============================================================

def test_mark_failed_transient_backoff():
    print("== mark_as_failed: transient → attempt+backoff ==")
    from telegram.error import NetworkError
    from services.scheduler_service import SchedulerService

    expectations = {0: (1, "30"), 1: (2, "120"), 2: (3, "300"), 3: (4, "900")}
    for current, (new_attempt, backoff) in expectations.items():
        cur = _fresh_cur(rows=[("processing", current)])
        with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
            res = SchedulerService.mark_as_failed(
                509, "-100123", NetworkError("connection reset"),
                is_transient=True, scheduled_time=NOW)
        check(f"attempt {current}→{new_attempt}",
              res.get("status") == "failed" and res.get("attempt_count") == new_attempt,
              str(res))
        check(f"backoff {backoff}s", res.get("backoff_seconds") == int(backoff), str(res))
        q = _queries_text(cur)
        check("next_retry_at o'rnatiladi", "next_retry_at = NOW()" in q, q[:300])
        check("backoff SQL parametri",
              any(p and backoff in p for p in cur._params_list), str(cur._params_list))


def test_mark_failed_exhausted_to_dead_letter():
    print("== mark_as_failed: 5-urinish → dead_letter ==")
    from telegram.error import NetworkError
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("processing", 4)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.mark_as_failed(
            510, "-100123", NetworkError("down"), is_transient=True, scheduled_time=NOW)
    check("status dead_letter", res.get("status") == "dead_letter", str(res))
    check("reason attempts_exhausted", res.get("reason") == "attempts_exhausted")
    check("attempt_count 5", res.get("attempt_count") == 5)
    check("next_retry_at NULL (qayta yo'q)",
          "next_retry_at = NULL" in _queries_text(cur))


def test_mark_failed_permanent_direct_dead_letter():
    print("== mark_as_failed: permanent → darhol dead_letter ==")
    from telegram.error import BadRequest, Forbidden
    from services.scheduler_service import SchedulerService

    cases = [
        ("BotKicked klassi", BotKicked("kicked"), True),
        ("ChatNotFound klassi", ChatNotFound("no chat"), True),
        ("Forbidden matni", Forbidden("Forbidden: bot was kicked from the group chat"), True),
        ("BadRequest matni", BadRequest("Bad Request: chat not found"), True),
        ("is_transient=False", Exception("oddiy xato"), False),
    ]
    for label, err, transient in cases:
        cur = _fresh_cur(rows=[("processing", 0)])
        with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
            res = SchedulerService.mark_as_failed(
                511, "-100123", err, is_transient=transient, scheduled_time=NOW)
        check(f"{label} → dead_letter", res.get("status") == "dead_letter", str(res))
        check(f"{label}: urinish sarflanmaydi",
              res.get("attempt_count") == 0, str(res))


def test_mark_failed_never_overwrites_sent():
    print("== mark_as_failed: sent ustidan yozilmaydi ==")
    from telegram.error import NetworkError
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[("sent", 1)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.mark_as_failed(
            512, "-100123", NetworkError("kechikkan xato"),
            is_transient=True, scheduled_time=NOW)
    check("status sentligicha qoladi", res.get("status") == "sent", str(res))
    check("ok True", res.get("ok") is True)
    q = _queries_text(cur)
    check("failed/dead UPDATE yo'q",
          "SET status = 'failed'" not in q and "SET status = 'dead_letter'" not in q, q[:300])

    # dead_letter ham qayta o'zgarmaydi
    cur2 = _fresh_cur(rows=[("dead_letter", 5)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur2)):
        res2 = SchedulerService.mark_failed_by_key("k", NetworkError("x"))
    check("dead_letter o'zgarmaydi", res2.get("status") == "dead_letter", str(res2))


def test_mark_failed_by_key_missing():
    print("== mark_failed_by_key: yozuv topilmasa ==")
    from services.scheduler_service import SchedulerService

    cur = _fresh_cur(rows=[None])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
        res = SchedulerService.mark_failed_by_key("missing-key", Exception("x"))
    check("ok False", res.get("ok") is False, str(res))
    check("bo'sh kalit → ok False",
          SchedulerService.mark_failed_by_key("", Exception("x")).get("ok") is False)


# ============================================================
# 7. HOLAT SO'ROVLARI
# ============================================================

def test_pending_or_retry_query():
    print("== get_pending_or_retry_posts ==")
    from services.scheduler_service import SchedulerService

    rows = [
        (601, -100123, "post_601_-100123_t", 0, None, None, NOW),
        (602, -100123, "post_602_-100123_t", 2, "timeout", PAST_TS, NOW),
    ]
    cur = _fresh_cur(rows=list(rows))
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
        pending = SchedulerService.get_pending_or_retry_posts(limit=10)
    check("2 ta yozuv", len(pending) == 2, str(pending))
    check("maydonlar to'liq",
          pending and pending[0]["post_id"] == 601
          and pending[1]["attempt_count"] == 2
          and "idempotency_key" in pending[0])
    q = _queries_text(cur)
    check("faqat pending/failed", "IN ('pending', 'failed')" in q, q[:300])
    check("retry filtri (next_retry_at <= NOW())", "next_retry_at <= NOW()" in q)
    check("sent chiqarilmaydi", "'sent'" not in q)
    check("processing chiqarilmaydi", "'processing'" not in q)
    check("dead_letter chiqarilmaydi", "'dead_letter'" not in q)


def test_delivery_status_helpers():
    print("== get_delivery_status / is_already_sent ==")
    from services.scheduler_service import SchedulerService

    key = SchedulerService.build_idempotency_key(603, "-100123", NOW)
    cur = _fresh_cur(rows=[("sent", 1, 777, None, None, NOW)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur)):
        info = SchedulerService.get_delivery_status(603, "-100123", NOW)
    check("status o'qiladi", info and info["status"] == "sent", str(info))
    check("telegram_message_id o'qiladi", info and info["telegram_message_id"] == 777)
    check("kalit qaytadi", info and info["idempotency_key"] == key)

    cur2 = _fresh_cur(rows=[("sent", 1, 777, None, None, NOW)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur2)):
        check("is_already_sent True",
              SchedulerService.is_already_sent(603, "-100123", NOW) is True)

    cur3 = _fresh_cur(rows=[("failed", 2, None, "timeout", FUTURE_TS, NOW)])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur3)):
        check("failed → is_already_sent False",
              SchedulerService.is_already_sent(603, "-100123", NOW) is False)

    cur4 = _fresh_cur(rows=[None])
    with patch("services.scheduler_service.db_cursor", _make_mock_dc(cur4)):
        check("topilmasa → None",
              SchedulerService.get_delivery_status(604, "-100123", NOW) is None)
        check("topilmasa → is_already_sent False",
              SchedulerService.is_already_sent(604, "-100123", NOW) is False)


# ============================================================
# 8. SCHEDULER INTEGRATSIYASI — sent bo'lsa Telegram chaqirilmaydi
# ============================================================

def _make_post(pid=701):
    return (
        pid, 123456789, "-100123", "text", "Salom", None,
        None, None, False, NOW,
        "none", None, None, None,
        0, None,
    )


def test_execute_send_skips_when_sent():
    print("== Scheduler: sent → Telegram API chaqirilmaydi ==")
    import asyncio
    import scheduler as sch_mod

    sch_mod._UNPERSISTED_SENT.clear()
    sch_mod._journal_loaded = True
    orig_path = sch_mod.SENT_JOURNAL_PATH
    sch_mod.SENT_JOURNAL_PATH = ""
    calls = []

    class _CountingBot:
        def __init__(self):
            self.n = 0

        async def send_message(self, chat_id, text, **kw):
            self.n += 1
            return SimpleNamespace(message_id=1000 + self.n)

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": False, "sent": True, "status": "sent",
                    "message_id": 1001, "idempotency_key": "k"}
        if name == "mark_post_status":
            return True
        return None

    bot = _CountingBot()
    orig = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        asyncio.run(sch_mod._execute_send(bot, _make_post(701)))
    finally:
        sch_mod.db.run_db = orig
        sch_mod.SENT_JOURNAL_PATH = orig_path
        sch_mod._UNPERSISTED_SENT.clear()

    check("Telegram API chaqirilmadi (0 duplikat)", bot.n == 0, f"calls={bot.n}")
    names = [c[0] for c in calls]
    check("claim SchedulerService orqali", "claim_post_for_delivery" in names, str(names))
    status_calls = [c for c in calls if c[0] == "mark_post_status"]
    check("post 'posted' deb yakunlandi",
          any(c[1] == (701, "posted") for c in status_calls), str(status_calls))


def test_execute_send_claims_then_sends_once():
    print("== Scheduler: claim → 1 marta yuborish + delivery sent ==")
    import asyncio
    import scheduler as sch_mod

    sch_mod._UNPERSISTED_SENT.clear()
    sch_mod._journal_loaded = True
    orig_path = sch_mod.SENT_JOURNAL_PATH
    sch_mod.SENT_JOURNAL_PATH = ""
    calls = []

    class _CountingBot:
        def __init__(self):
            self.n = 0

        async def send_message(self, chat_id, text, **kw):
            self.n += 1
            return SimpleNamespace(message_id=2000 + self.n)

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": True, "status": "processing", "attempt_count": 0,
                    "idempotency_key": "post_702_-100123_t"}
        if name == "is_premium":
            return True
        if name == "get_setting":
            return ""
        if name == "bump_channel_post_count":
            return 1
        if name in ("mark_post_processing", "mark_post_as_sent", "mark_sent_by_key"):
            return True
        return None

    bot = _CountingBot()
    orig = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        asyncio.run(sch_mod._execute_send(bot, _make_post(702)))
    finally:
        sch_mod.db.run_db = orig
        sch_mod.SENT_JOURNAL_PATH = orig_path
        sch_mod._UNPERSISTED_SENT.clear()

    check("Telegram API aynan 1 marta chaqirildi", bot.n == 1, f"calls={bot.n}")
    names = [c[0] for c in calls]
    check("delivery 'sent' deb belgilandi", "mark_sent_by_key" in names, str(names))
    check("scheduled_posts 'posted' deb belgilandi", "mark_post_as_sent" in names)
    sent_calls = [c for c in calls if c[0] == "mark_sent_by_key"]
    check("telegram_message_id saqlandi",
          sent_calls and sent_calls[0][1][1] == 2001, str(sent_calls))


def test_execute_send_dead_letter_marks_failed():
    print("== Scheduler: dead_letter → 'failed', yuborilmaydi ==")
    import asyncio
    import scheduler as sch_mod

    sch_mod._UNPERSISTED_SENT.clear()
    sch_mod._journal_loaded = True
    orig_path = sch_mod.SENT_JOURNAL_PATH
    sch_mod.SENT_JOURNAL_PATH = ""
    calls = []

    class _CountingBot:
        def __init__(self):
            self.n = 0

        async def send_message(self, chat_id, text, **kw):
            self.n += 1
            return SimpleNamespace(message_id=3000)

    async def fake_run_db(fn, *args, **kwargs):
        name = getattr(fn, "__name__", "")
        calls.append((name, args))
        if name == "claim_post_for_delivery":
            return {"claimed": False, "dead": True, "status": "dead_letter",
                    "idempotency_key": "k"}
        if name == "mark_post_status":
            return True
        return None

    bot = _CountingBot()
    orig = sch_mod.db.run_db
    sch_mod.db.run_db = fake_run_db
    try:
        asyncio.run(sch_mod._execute_send(bot, _make_post(703)))
    finally:
        sch_mod.db.run_db = orig
        sch_mod.SENT_JOURNAL_PATH = orig_path
        sch_mod._UNPERSISTED_SENT.clear()

    check("Telegram API chaqirilmadi", bot.n == 0, f"calls={bot.n}")
    status_calls = [c for c in calls if c[0] == "mark_post_status"]
    check("post 'failed' deb yakunlandi",
          any(c[1] == (703, "failed") for c in status_calls), str(status_calls))


def test_no_journal_in_normal_operation():
    print("== Journal: normal holatda /tmp fayl ishlatilmaydi ==")
    import scheduler as sch_mod

    saved = os.environ.get("SENT_JOURNAL_PATH")
    try:
        os.environ.pop("SENT_JOURNAL_PATH", None)
        check("default bo'sh (opt-in)",
              sch_mod._resolve_sent_journal_path() == "")
        os.environ["SENT_JOURNAL_PATH"] = "off"
        check("'off' → bo'sh", sch_mod._resolve_sent_journal_path() == "")
        os.environ["SENT_JOURNAL_PATH"] = "/tmp/postassist_sent_journal.json"
        check("aniq yo'l → saqlanadi (legacy)",
              sch_mod._resolve_sent_journal_path() == "/tmp/postassist_sent_journal.json")
    finally:
        if saved is None:
            os.environ.pop("SENT_JOURNAL_PATH", None)
        else:
            os.environ["SENT_JOURNAL_PATH"] = saved

    import database as db_mod
    src = Path(db_mod.__file__).read_text(encoding="utf-8")
    check("delivery sxemasi DB'da (post_deliveries)",
          "CREATE TABLE IF NOT EXISTS post_deliveries" in src)
    check("backoff ustuni (next_retry_at)", "next_retry_at" in src)


def test_scheduler_delivery_helpers():
    print("== Scheduler delivery yordamchilari ==")
    import scheduler as sch_mod

    check("dead dict → True",
          sch_mod._delivery_is_dead({"status": "dead_letter"}) is True)
    check("dead bayrog'i → True",
          sch_mod._delivery_is_dead({"dead": True}) is True)
    check("failed → False",
          sch_mod._delivery_is_dead({"status": "failed"}) is False)
    check("None → False", sch_mod._delivery_is_dead(None) is False)
    check("backoff o'qiladi",
          sch_mod._delivery_retry_delay({"backoff_seconds": 120}, 30) == 120.0)
    check("backoff yo'q → fallback",
          sch_mod._delivery_retry_delay({}, 30) == 30.0)
    check("None → fallback", sch_mod._delivery_retry_delay(None, 30) == 30.0)


# ============================================================
# 9. REAL POSTGRESQL — concurrency, backoff, dead_letter
# ============================================================

def _start_test_postgres():
    """Test bazasi URI: P0_TEST_DATABASE_URL yoki pgserver. Topilmasa None."""
    url = os.getenv("P0_TEST_DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    import shutil
    import tempfile
    server_dir = os.path.join(tempfile.gettempdir(), "schedsvc_pg")
    shutil.rmtree(server_dir, ignore_errors=True)
    try:
        server = pgserver.get_server(server_dir)
        return server.get_uri()
    except Exception as e:
        print(f"  (pgserver ishga tushmadi: {e})")
        return None


#: 5-bosqich FK uchun test seed'larining unikal raqam kechiruvi.
_SEED_BASE = 987000000 + (os.getpid() % 500) * 1000
_seed_counter = [0]


def _seed_delivery_post(db_mod):
    """Real (va tozalanadigan) user → channel → post zanjirini yaratadi.

    PostAssist V2 (5-bosqich)dan so'ng ``post_deliveries.post_id`` FK'i
    ``scheduled_posts(id)`` ga bog'langan — ya'ni delivery yozuvi uchun
    ota-qator shart. Testlar shu talabni buzmaydi: avval haqiqiy post
    yaratiladi, keyin shu id bilan delivery claim qilinadi.

    Qaytadi: ``{"post_id": int, "channel_id": str, "user_id": int}``.
    """
    _seed_counter[0] += 1
    user_id = _SEED_BASE + _seed_counter[0]
    channel_id = f"-100{user_id}"
    with db_mod.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO NOTHING",
            (user_id, f"seed_{user_id}"),
        )
        cur.execute(
            "INSERT INTO channels (user_id, channel_id, channel_title) "
            "VALUES (%s, %s, 'Scheduler test kanali') "
            "ON CONFLICT (channel_id) DO UPDATE SET is_active = TRUE",
            (user_id, channel_id),
        )
        cur.execute(
            "INSERT INTO scheduled_posts (user_id, channel_id, post_type, content, "
            " scheduled_time, status) "
            "VALUES (%s, %s, 'text', 'scheduler testi', NOW(), 'pending') "
            "RETURNING id",
            (user_id, channel_id),
        )
        return {"post_id": int(cur.fetchone()[0]), "channel_id": channel_id,
                "user_id": user_id}


def _cleanup_deliveries(db_mod, post_ids, user_ids=()):
    """Test yozuvlarini tozalash.

    5-bosqichdan keyin postni o'chirish delivery'larni ham CASCADE bilan
    olib ketadi — bu funksiya zanjirni (post → kanal → foydalanuvchi)
    izchil tozalaydi.
    """
    with db_mod.db_cursor(commit=True) as cur:
        ids = [int(p) for p in post_ids]
        if ids:
            cur.execute("DELETE FROM post_deliveries WHERE post_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM post_reactions WHERE post_id = ANY(%s)", (ids,))
            cur.execute("DELETE FROM scheduled_posts WHERE id = ANY(%s)", (ids,))
        if user_ids:
            uids = [int(u) for u in user_ids]
            cur.execute("DELETE FROM channels WHERE user_id = ANY(%s)", (uids,))
            cur.execute("DELETE FROM users WHERE user_id = ANY(%s)", (uids,))


def test_real_concurrent_claim_single_winner(db_mod):
    print("== REAL DB: 2 parallel worker → faqat 1 claim ==")
    from services.scheduler_service import SchedulerService

    seed = _seed_delivery_post(db_mod)
    post_id, channel = seed["post_id"], "-1001999000001"
    sched = datetime.now(timezone.utc)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(
                lambda _: SchedulerService.claim_post_for_delivery(post_id, channel, sched),
                range(2)))
        winners = [r for r in results if r.get("claimed") is True]
        check("faqat 1 ta worker claim qildi", len(winners) == 1, str(results))
        check("yutgan status processing",
              winners and winners[0].get("status") == "processing")
        losers = [r for r in results if r.get("claimed") is not True]
        check("yutqazgan 'processing' ni ko'rdi",
              losers and losers[0].get("status") == "processing", str(results))

        # G'olib yuborib bo'lgach — ikkinchi claim 'sent' (skip)
        key = winners[0]["idempotency_key"]
        check("mark_as_sent True",
              SchedulerService.mark_as_sent(post_id, channel, 31337, sched) is True)
        again = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
        check("sent'dan keyin claim → sent", again.get("sent") is True, str(again))
        check("kalit bir xil", again.get("idempotency_key") == key)
        check("is_already_sent True",
              SchedulerService.is_already_sent(post_id, channel, sched) is True)
    finally:
        _cleanup_deliveries(db_mod, [post_id], [seed["user_id"]])


def test_real_transient_backoff_then_dead(db_mod):
    print("== REAL DB: transient backoff (30/120/300/900) → 5-da dead ==")
    from telegram.error import NetworkError
    from services.scheduler_service import SchedulerService

    seed = _seed_delivery_post(db_mod)
    post_id, channel = seed["post_id"], "-1001999000002"
    sched = datetime.now(timezone.utc)
    try:
        first = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
        check("claim True", first.get("claimed") is True, str(first))

        expected = [(1, 30), (2, 120), (3, 300), (4, 900)]
        for attempt, backoff in expected:
            res = SchedulerService.mark_as_failed(
                post_id, channel, NetworkError("timeout"),
                is_transient=True, scheduled_time=sched)
            check(f"attempt {attempt} → failed/backoff {backoff}s",
                  res.get("status") == "failed"
                  and res.get("attempt_count") == attempt
                  and res.get("backoff_seconds") == backoff, str(res))
            # Backoff o'tmasdan claim → retry_pending (Telegram chaqirilmaydi)
            claim = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
            check(f"backoff ichida claim → retry_pending (attempt {attempt})",
                  claim.get("claimed") is False and claim.get("retry_pending") is True,
                  str(claim))
            # Keyingi urinish uchun backoff'ni "o'tkazamiz" (test tezligi uchun)
            with db_mod.db_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE post_deliveries SET next_retry_at = NOW() - INTERVAL '1 second' "
                    "WHERE idempotency_key = %s", (res["idempotency_key"],))
            reclaim = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
            check(f"backoff o'tgach claim True (attempt {attempt})",
                  reclaim.get("claimed") is True, str(reclaim))

        final = SchedulerService.mark_as_failed(
            post_id, channel, NetworkError("timeout"),
            is_transient=True, scheduled_time=sched)
        check("5-urinish → dead_letter",
              final.get("status") == "dead_letter"
              and final.get("reason") == "attempts_exhausted", str(final))
        after = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
        check("dead'dan keyin claim → dead",
              after.get("claimed") is False and after.get("dead") is True, str(after))
    finally:
        _cleanup_deliveries(db_mod, [post_id], [seed["user_id"]])


def test_real_permanent_dead_immediately(db_mod):
    print("== REAL DB: BotKicked/ChatNotFound → darhol dead_letter ==")
    from telegram.error import BadRequest, Forbidden
    from services.scheduler_service import SchedulerService

    seed = _seed_delivery_post(db_mod)
    seed2 = _seed_delivery_post(db_mod)
    post_id, post_id2 = seed["post_id"], seed2["post_id"]
    channel = "-1001999000003"
    sched = datetime.now(timezone.utc)
    try:
        check("claim True",
              SchedulerService.claim_post_for_delivery(post_id, channel, sched).get("claimed") is True)
        res = SchedulerService.mark_as_failed(
            post_id, channel, Forbidden("Forbidden: bot was kicked from the group chat"),
            is_transient=True, scheduled_time=sched)
        check("BotKicked → dead_letter", res.get("status") == "dead_letter", str(res))
        check("urinish sarflanmadi", res.get("attempt_count") == 0, str(res))
        again = SchedulerService.claim_post_for_delivery(post_id, channel, sched)
        check("dead → claim dead", again.get("dead") is True, str(again))

        SchedulerService.claim_post_for_delivery(post_id2, channel, sched)
        res2 = SchedulerService.mark_as_failed(
            post_id2, channel, BadRequest("Bad Request: chat not found"),
            is_transient=True, scheduled_time=sched)
        check("ChatNotFound → dead_letter", res2.get("status") == "dead_letter", str(res2))
    finally:
        _cleanup_deliveries(db_mod, [post_id, post_id2],
                            [seed["user_id"], seed2["user_id"]])


def test_real_pending_retry_filter(db_mod):
    print("== REAL DB: pending/retry filtri (sent/dead yo'q) ==")
    from telegram.error import NetworkError
    from services.scheduler_service import SchedulerService

    seed = _seed_delivery_post(db_mod)
    seed2 = _seed_delivery_post(db_mod)
    base, base2 = seed["post_id"], seed2["post_id"]
    channel = "-1001999000004"
    sched = datetime.now(timezone.utc)
    try:
        # failed + backoff kelajakda → ro'yxatda YO'Q
        SchedulerService.claim_post_for_delivery(base, channel, sched)
        SchedulerService.mark_as_failed(
            base, channel, NetworkError("t"), is_transient=True, scheduled_time=sched)
        keys = {p["idempotency_key"] for p in SchedulerService.get_pending_or_retry_posts(limit=1000)}
        waiting_key = SchedulerService.build_idempotency_key(base, channel, sched)
        check("backoff'dagi failed ro'yxatda yo'q", waiting_key not in keys)

        # backoff o'tgan → ro'yxatda BOR
        with db_mod.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE post_deliveries SET next_retry_at = NOW() - INTERVAL '1 second' "
                "WHERE idempotency_key = %s", (waiting_key,))
        keys2 = {p["idempotency_key"] for p in SchedulerService.get_pending_or_retry_posts(limit=1000)}
        check("backoff o'tgan failed ro'yxatda bor", waiting_key in keys2)

        # sent → ro'yxatda YO'Q
        SchedulerService.claim_post_for_delivery(base2, channel, sched)
        SchedulerService.mark_as_sent(base2, channel, 555, sched)
        keys3 = {p["idempotency_key"] for p in SchedulerService.get_pending_or_retry_posts(limit=1000)}
        sent_key = SchedulerService.build_idempotency_key(base2, channel, sched)
        check("sent ro'yxatda yo'q", sent_key not in keys3)
    finally:
        _cleanup_deliveries(db_mod, [base, base2],
                            [seed["user_id"], seed2["user_id"]])


def test_claim_sql_row_lock_fallback():
    print("== Claim SQL kafolati (FOR UPDATE — parallel serialize) ==")
    import database as db_mod

    src = Path(db_mod.__file__).read_text(encoding="utf-8")
    body = src.split("def claim_post_delivery", 1)[1].split("\ndef ", 1)[0]
    check("claim SELECT ... FOR UPDATE", "FOR UPDATE" in body)
    check("dead_letter himoyasi", "dead_letter" in body)
    check("retry_pending himoyasi", "retry_pending" in body)
    check("stale processing himoyasi", "stale" in body.lower())
    check("sent himoyasi", '"sent"' in body or "'sent'" in body)


def main():
    test_idempotency_key_strict()
    test_backoff_mapping()
    test_permanent_error_classification()
    test_claim_pending_success()
    test_claim_sent_skips_duplicate()
    test_claim_processing_other_worker()
    test_claim_dead_letter_never_retries()
    test_claim_retry_pending_and_due()
    test_claim_stale_processing_reclaim()
    test_claim_resolves_scheduled_time()
    test_mark_as_sent()
    test_mark_failed_transient_backoff()
    test_mark_failed_exhausted_to_dead_letter()
    test_mark_failed_permanent_direct_dead_letter()
    test_mark_failed_never_overwrites_sent()
    test_mark_failed_by_key_missing()
    test_pending_or_retry_query()
    test_delivery_status_helpers()
    test_execute_send_skips_when_sent()
    test_execute_send_claims_then_sends_once()
    test_execute_send_dead_letter_marks_failed()
    test_no_journal_in_normal_operation()
    test_scheduler_delivery_helpers()

    # Real PostgreSQL (concurrency aynan real bazada isbotlanadi)
    uri = _start_test_postgres()
    if not uri:
        skip("real-DB concurrency/backoff/dead",
             "(P0_TEST_DATABASE_URL/pgserver topilmadi)")
        test_claim_sql_row_lock_fallback()
    else:
        import database as db_mod
        db_mod.DATABASE_URL = uri
        db_mod._reset_pool()
        try:
            db_mod.init_db()
        except Exception as e:
            skip("real-DB concurrency/backoff/dead", f"(init_db: {e})")
            test_claim_sql_row_lock_fallback()
            uri = None
        if uri:
            try:
                test_real_concurrent_claim_single_winner(db_mod)
                test_real_transient_backoff_then_dead(db_mod)
                test_real_permanent_dead_immediately(db_mod)
                test_real_pending_retry_filter(db_mod)
            finally:
                db_mod.close_pool()

    print(f"\nO'tdi: {passed}, Xato: {failures}, O'tkazib yuborildi: {skipped}")
    if failures:
        sys.exit(1)
    print("Barcha SchedulerService testlari muvaffaqiyatli o'tdi ✔")


if __name__ == "__main__":
    main()